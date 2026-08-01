#!/usr/bin/env python3
"""ddw-validate-prd, the mechanical half — run by the skill, never re-derived.

Why a script: the skill's box template was already exact, and a live Copilot
run loaded create-prd and validate-prd together as background reading and
"validated" in free prose — theater with a green tint. A report a model renders
is a report a model can skip; a report a script prints is either there or the
command failed. The judgement rules (F-PRD-02 non-binary wording, F-PRD-07
undeclared cross-references, W-PRD-01/03) stay with the model and are printed
as MANUAL lines so their absence is visible instead of silent.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §1 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import hashlib
import os
import re
import sys

# Headers as ddw-create-prd emits them (English headers, prose in any language).
SECTIONS = [
    ("Context and Problem", ("context and problem", "contexto")),
    ("Goals", ("goals", "objetivos")),
    ("Functional Requirements", ("functional requirements", "requerimientos funcionales")),
    ("Non-Functional Requirements", ("non-functional requirements", "requerimientos no funcionales")),
    ("Acceptance Criteria", ("acceptance criteria", "criterios de aceptaci")),
    ("Out of Scope", ("out of scope", "fuera de alcance")),
    ("Dependencies", ("dependencies", "dependencias")),
]
FIX_BRIEF_SECTIONS = ("bug", "change", "regression test", "risk")

AMBIGUOUS = re.compile(
    r"\b(should|could|may|ideally|it is recommended|debería|deberia|podría|podria|"
    r"idealmente|se recomienda)\b", re.IGNORECASE)
# The five EARS patterns, composable; SHALL is the load-bearing word.
EARS = re.compile(
    r"\b(THE\s+.+?\s+SHALL|WHEN\s.+?SHALL|WHILE\s.+?SHALL|WHERE\s.+?SHALL|"
    r"IF\s.+?THEN\s.+?SHALL)\b", re.IGNORECASE | re.DOTALL)
UNWANTED = re.compile(r"\bIF\b.+?\bTHEN\b.+?\bSHALL\b", re.IGNORECASE | re.DOTALL)
REQ_ID = re.compile(r"\b(FR|NFR|AC)-(\d+)\b")


def _items(text, prefix):
    """Bullet items carrying an ID of the given prefix, as (id, full_text)."""
    out = []
    current = None
    for line in text.splitlines():
        # The ID must open the bullet: an AC that CITES "(FR-01)" is not an FR.
        m = re.match(r"\s*[-*]\s+\**(" + prefix + r"-\d+)\**\s*[:.(]", line)
        if m:
            if current:
                out.append(current)
            current = (m.group(1), line)
        elif current and re.match(r"\s{2,}\S", line):
            current = (current[0], current[1] + " " + line.strip())
        else:
            if current:
                out.append(current)
            current = None
    if current:
        out.append(current)
    return out


def _repo_relative(path):
    """The path as the reader will type it: anchored at the repo, not at
    whatever directory the validator happened to be invoked from. A relpath
    against the cwd printed `../../../../tmp/...` — correct, and useless as the
    link the report line exists to be."""
    ab = os.path.abspath(path)
    idx = ab.rfind(os.sep + "docs" + os.sep)
    if idx > 0:
        return ab[idx + 1:]
    try:
        rel = os.path.relpath(ab)
        return rel if not rel.startswith(os.pardir) else ab
    except ValueError:
        return ab


def _section_body(text, names):
    lines = text.splitlines()
    body, inside = [], False
    for ln in lines:
        if re.match(r"\s*#{2,3}\s", ln):
            title = re.sub(r"\s*#{2,3}\s*", "", ln).strip().lower()
            inside = any(title.startswith(n) or n in title for n in names)
            continue
        if inside:
            body.append(ln)
    return "\n".join(body).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prd")
    ap.add_argument("--tier", default="FEATURE")
    args = ap.parse_args()
    try:
        text = open(args.prd, encoding="utf-8").read()
    except OSError as exc:
        print(f"validate_prd: cannot read {args.prd}: {exc}", file=sys.stderr)
        sys.exit(3)

    rows, fails, warns = [], 0, 0

    def fail(rule, msg):
        nonlocal fails
        fails += 1
        rows.append(f"  ❌ {rule}: {msg}")

    def ok(rule, msg):
        rows.append(f"  ✅ {rule}: {msg}")

    def warn(rule, msg):
        nonlocal warns
        warns += 1
        rows.append(f"  ⚠️ {rule}: {msg}")

    if args.tier == "QUICK-FIX":
        low = text.lower()
        missing = [s for s in FIX_BRIEF_SECTIONS if s not in low]
        if missing:
            fail("QUICK-FIX", f"fix-brief incomplete, missing: {', '.join(missing)}")
        else:
            ok("QUICK-FIX", "the four fix-brief sections are present")
    else:
        frs = _items(text, "FR")
        nfrs = _items(text, "NFR")
        acs = _items(text, "AC")

        # F-PRD-08 first: structure gates everything else's meaning.
        missing = [pretty for pretty, names in SECTIONS
                   if not _section_body(text, names)]
        if args.tier != "FEATURE" and "Out of Scope" in missing:
            missing.remove("Out of Scope")
        if missing:
            fail("F-PRD-08", f"missing structural section(s): {', '.join(missing)}")
        else:
            ok("F-PRD-08", "all mandatory sections present")

        # F-PRD-05: unique, gapless IDs.
        dup_msgs = []
        for prefix, items in (("FR", frs), ("NFR", nfrs), ("AC", acs)):
            ids = [i for i, _ in items]
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                dup_msgs.append(f"duplicated {', '.join(dupes)}")
            nums = sorted(int(i.split('-')[1]) for i in set(ids))
            gaps = [f"{prefix}-{n:02d}" for n in range(1, nums[-1] + 1)
                    if nums and n not in nums] if nums else []
            if gaps:
                dup_msgs.append(f"missing {', '.join(gaps)}")
        if dup_msgs:
            fail("F-PRD-05", "; ".join(dup_msgs))
        else:
            ok("F-PRD-05", f"{len(frs)} FR, {len(nfrs)} NFR, {len(acs)} AC — unique, gapless")

        # F-PRD-01: every FR referenced by at least one AC.
        ac_text = " ".join(t for _, t in acs)
        orphans = [i for i, _ in frs if i not in ac_text]
        if orphans:
            fail("F-PRD-01", f"FR with no AC validating it: {', '.join(orphans)}")
        else:
            ok("F-PRD-01", "every FR is validated by at least one AC")

        # F-PRD-03: a number in every NFR.
        unmetered = [i for i, t in nfrs if not re.search(r"\d", t)]
        if unmetered:
            fail("F-PRD-03", f"NFR with no quantitative value: {', '.join(unmetered)}")
        else:
            ok("F-PRD-03", "every NFR carries a quantitative value")

        # F-PRD-04: Out of Scope non-empty (FEATURE).
        if args.tier == "FEATURE":
            oos = _section_body(text, ("out of scope", "fuera de alcance"))
            if re.search(r"^\s*[-*]\s+\S", oos, re.MULTILINE):
                ok("F-PRD-04", "Out of Scope has explicit items")
            else:
                fail("F-PRD-04", "Out of Scope is missing or has no explicit items")

        # F-PRD-06: ambiguous verbs in requirement/criterion lines.
        loose = [i for i, t in frs + nfrs + acs if AMBIGUOUS.search(t)]
        if loose:
            fail("F-PRD-06", f"ambiguous verb (should/could/…): {', '.join(loose)}")
        else:
            ok("F-PRD-06", "no ambiguous verbs in requirements")

        # F-PRD-09: every AC in one of the five EARS shapes.
        non_ears = [i for i, t in acs if not EARS.search(t)]
        if args.tier == "DISCOVERY":
            ok("F-PRD-09", "not applied (DISCOVERY)")
        elif non_ears:
            fail("F-PRD-09", f"AC matching no EARS pattern: {', '.join(non_ears)}")
        else:
            ok("F-PRD-09", "every AC matches an EARS pattern")

        # W-PRD-02: more than 5 ACs on one FR.
        heavy = [i for i, _ in frs if len([1 for _, t in acs if i in t]) > 5]
        if heavy:
            warn("W-PRD-02", f"more than 5 ACs on: {', '.join(heavy)}")

        # W-PRD-04: zero unwanted-behaviour ACs.
        if not any(UNWANTED.search(t) for _, t in acs):
            warn("W-PRD-04", "no IF…THEN…SHALL criterion — nobody wrote the failure modes down")

        # W-PRD-05: risks section empty.
        if not _section_body(text, ("risks", "riesgos")):
            warn("W-PRD-05", "Risks and Mitigations missing or empty")

        rows.append("  👁  F-PRD-02 (binary ACs) and F-PRD-07 (undeclared cross-references) are")
        rows.append("      MANUAL: judge them and say so explicitly in your report.")

    verdict = "PASSED" if fails == 0 else f"FAILED ({fails} FAIL{'S' if fails > 1 else ''})"
    report = [f"/ddw-validate-prd {args.prd} — {verdict}", "─" * 64]
    report += rows
    report.append("─" * 64)
    for line in report:
        print(line)
    passed = sum(1 for r in rows if r.strip().startswith("✅"))
    print(f"Total: {passed} passed, {fails} failed, {warns} warnings")
    print(f"Result: {verdict}")

    # The report is an ARTIFACT, not narration. A live run validated for real,
    # then asked for approval without showing the user a single ✅ — the model
    # summarized the checklist away. Persisted next to the PRD, the result
    # exists whether or not the model deigns to paste it, and the approval can
    # point at a file instead of a claim.
    try:
        report_path = re.sub(r"\.md$", "", os.path.abspath(args.prd)) + ".validation.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(report) + "\n"
                     + f"Total: {passed} passed, {fails} failed, {warns} warnings\n"
                     + f"Result: {verdict}\n```\n")
        print(f"Report: {_repo_relative(report_path)}")
    except OSError:
        pass

    if fails == 0:
        # The receipt is what makes "validated" a fact instead of a claim: it
        # is bound to THIS content, and the define gate demands it. Edit the
        # PRD after validating and the hash no longer matches — validate again.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        prd_abs = os.path.abspath(args.prd)
        idx = prd_abs.rfind(os.sep + "docs" + os.sep)
        root = prd_abs[:idx] if idx > 0 else os.getcwd()
        sess = os.path.join(root, ".ddw-sessions")
        os.makedirs(sess, exist_ok=True)
        with open(os.path.join(sess, f"prd-validated-{digest}"), "w", encoding="utf-8") as fh:
            fh.write(os.path.basename(prd_abs) + "\n")
        print(f"Receipt: .ddw-sessions/prd-validated-{digest}")
    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
