#!/usr/bin/env python3
"""ddw-verify-module, the mechanical half — run by the skill, never re-derived.

**Read this before assuming what the receipt means.** DDW does not run your test
suite: it does not know whether this is pytest or jest or a monorepo with five
runners, and a gate that cannot be satisfied honestly gets satisfied dishonestly
(docs/RATIONALE.md decisions 2 and 16). So this script does NOT verify that the
tests pass. It verifies that **the verdict was written and is complete** — that
every AC in the PRD is accounted for, every block of the spec is accounted for,
the three coverage numbers are stated and meet the minimum the rules set, and
lint and the sad paths have an answer instead of a silence.

That is a smaller claim than "verified", and it is the whole claim. The numbers
in the report are still the model's report of what it ran. What changes is that
a VERIFY phase can no longer close with a verdict that never mentions half the
acceptance criteria — which is what the `verify` boolean allowed, and what a
reader six months later would have had no way to notice.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §5 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import hashlib
import os
import re
import sys

MINIMUM = 80        # line, branch and function coverage — testing.instructions.md
FAILING = re.compile(r"\b(fail|failed|falla|fallo|fallido|error|❌)\b", re.IGNORECASE)
SAD_PATH = re.compile(r"\b(sad path|camino triste|invalid|inv[aá]lid|negative test|"
                      r"entrada inv[aá]lida|edge case|caso borde)\b", re.IGNORECASE)


def _repo_relative(path):
    ab = os.path.abspath(path)
    idx = ab.rfind(os.sep + "docs" + os.sep)
    if idx > 0:
        return ab[idx + 1:]
    try:
        rel = os.path.relpath(ab)
        return rel if not rel.startswith(os.pardir) else ab
    except ValueError:
        return ab


def _ids(text, prefix):
    """IDs of the given prefix that OPEN a bullet — the same rule the PRD and
    spec validators use, so all three count the same requirements."""
    out = []
    for ln in text.splitlines():
        m = re.match(r"\s*[-*]\s+\**(" + prefix + r"-\d+)\**\s*[:.(]", ln)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _coverage(text):
    """The three numbers, however the report phrases them."""
    out = {}
    for key, pat in (("line", r"(?:line|l[ií]nea)s?"),
                     ("branch", r"(?:branch|rama)s?"),
                     ("function", r"(?:function|funci[oó]n|funciones)")):
        m = re.search(pat + r"[^\n%]{0,40}?(\d{1,3}(?:[.,]\d+)?)\s*%", text, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%[^\n]{0,20}?" + pat, text, re.IGNORECASE)
        if m:
            out[key] = float(m.group(1).replace(",", "."))
    return out


def _find(path_of_report, name_pattern, subdir, stems):
    m = re.match(name_pattern, os.path.basename(path_of_report))
    if not m:
        return None
    here = os.path.dirname(os.path.abspath(path_of_report))
    for stem in stems:
        p = os.path.normpath(os.path.join(here, "..", subdir, "%s-%s.md" % (stem, m.group(1))))
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--tier", default="FEATURE")
    ap.add_argument("--prd", default=None)
    ap.add_argument("--spec", default=None)
    args = ap.parse_args()

    if args.tier == "QUICK-FIX":
        print("validate_verify: tier QUICK-FIX has no VERIFY phase (catalog §Tier Modifier). "
              "Nothing to validate.", file=sys.stderr)
        sys.exit(3)

    try:
        text = open(args.report, encoding="utf-8").read()
    except OSError as exc:
        print(f"validate_verify: cannot read {args.report}: {exc}", file=sys.stderr)
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

    prd_path = args.prd or _find(args.report, r"verify-(.+)\.md$", "prd", ("prd",))
    spec_path = args.spec or _find(args.report, r"verify-(.+)\.md$", "specs", ("spec", "fix"))

    # F-VER-01: every AC of the PRD accounted for, and none reported failing.
    prd_text = ""
    if prd_path:
        try:
            prd_text = open(prd_path, encoding="utf-8").read()
        except OSError:
            prd_text = ""
    if not prd_text:
        fail("F-VER-01", "the PRD could not be read, so AC coverage was NOT checked. "
                         "Pass --prd <path> and run again")
    else:
        acs = _ids(prd_text, "AC")
        unmentioned = [a for a in acs if not re.search(r"\b%s\b" % a, text)]
        if unmentioned:
            fail("F-VER-01", f"AC with no verdict in the report: {', '.join(unmentioned)}")
        else:
            failing = [a for a in acs
                       for ln in text.splitlines()
                       if re.search(r"\b%s\b" % a, ln) and FAILING.search(ln)]
            if failing:
                fail("F-VER-01", f"AC reported as failing: {', '.join(sorted(set(failing)))}")
            else:
                ok("F-VER-01", f"all {len(acs)} AC from the PRD carry a passing verdict")

    # F-VER-02 / F-VER-06: every block, and every test the spec promised.
    spec_text = ""
    if spec_path:
        try:
            spec_text = open(spec_path, encoding="utf-8").read()
        except OSError:
            spec_text = ""
    if not spec_text:
        fail("F-VER-02/06", "the spec could not be read, so block and test coverage were NOT "
                            "checked. Pass --spec <path> and run again")
    else:
        blocks = re.findall(r"^##\s+Block\s+(\d+)", spec_text, re.MULTILINE)
        missing = [f"Block {b}" for b in blocks
                   if not re.search(r"block\s*%s\b" % b, text, re.IGNORECASE)]
        if missing:
            fail("F-VER-02", f"spec block with no verdict in the report: {', '.join(missing)}")
        else:
            ok("F-VER-02", f"all {len(blocks)} spec block(s) are accounted for")

        promised = re.findall(r"^\s*[-*]\s+(?:\[[ x]\]\s*)?(test[\w./:-]*)", spec_text,
                              re.MULTILINE | re.IGNORECASE)
        absent = [t for t in dict.fromkeys(promised) if t not in text]
        if absent:
            fail("F-VER-06", f"test promised by the spec and absent from the report: "
                             f"{', '.join(absent[:5])}{' (and others)' if len(absent) > 5 else ''}")
        else:
            ok("F-VER-06", f"all {len(set(promised))} test(s) the spec promised are reported")

    # F-VER-03: the three numbers, and the floor they have to clear.
    cov = _coverage(text)
    absent = [k for k in ("line", "branch", "function") if k not in cov]
    if absent:
        fail("F-VER-03", f"coverage not stated for: {', '.join(absent)} "
                         f"(the report has to carry all three)")
    else:
        below = [f"{k} {v:.0f}%" for k, v in cov.items() if v < MINIMUM]
        if below:
            fail("F-VER-03", f"coverage below the {MINIMUM}% minimum: {', '.join(below)}")
        else:
            ok("F-VER-03", "line, branch and function coverage all stated and ≥ %d%%" % MINIMUM)
        business = [f"{k} {v:.0f}%" for k, v in cov.items() if MINIMUM <= v < 90]
        if business:
            warn("W-VER-02", f"between 80% and 90% — business logic should be higher: "
                             f"{', '.join(business)}")

    # F-VER-04 / F-VER-05: an answer, not a silence.
    if SAD_PATH.search(text):
        ok("F-VER-04", "the report names sad-path testing")
    else:
        fail("F-VER-04", "no sad-path test named: only the happy path was verified, or only the "
                         "happy path was reported")

    if re.search(r"\b(lint|ruff|eslint|mypy|tsc|type check|typecheck|pyright)\b", text, re.I):
        line = next((ln for ln in text.splitlines()
                     if re.search(r"\b(lint|ruff|eslint|mypy|tsc|typecheck)\b", ln, re.I)), "")
        if FAILING.search(line):
            fail("F-VER-05", "the report says the linter or type checker fails")
        else:
            ok("F-VER-05", "lint / type check reported and clean")
    else:
        fail("F-VER-05", "no lint or type-check result in the report — if the project has none "
                         "configured, the report has to say so")

    rows.append("  👁  DDW does not run your suite: the numbers above are the report's, not this")
    rows.append("      script's. What is checked is that the verdict is COMPLETE — see the header.")

    result = "PASSED" if fails == 0 else f"FAILED ({fails} FAIL{'S' if fails > 1 else ''})"
    out = [f"/ddw-verify-module {args.report} — {result}", "─" * 64]
    out += rows
    out.append("─" * 64)
    passed = sum(1 for r in rows if r.strip().startswith("✅"))
    tail = [f"Total: {passed} passed, {fails} failed, {warns} warnings", f"Result: {result}"]
    for line in out + tail:
        print(line)

    try:
        report_path = re.sub(r"\.md$", "", os.path.abspath(args.report)) + ".validation.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(out + tail) + "\n```\n")
        print(f"Report: {_repo_relative(report_path)}")
    except OSError:
        pass

    if fails == 0:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        abs_ = os.path.abspath(args.report)
        idx = abs_.rfind(os.sep + "docs" + os.sep)
        root = abs_[:idx] if idx > 0 else os.getcwd()
        sess = os.path.join(root, ".ddw-sessions")
        os.makedirs(sess, exist_ok=True)
        with open(os.path.join(sess, f"verify-validated-{digest}"), "w", encoding="utf-8") as fh:
            fh.write(os.path.basename(abs_) + "\n")
        print(f"Receipt: .ddw-sessions/verify-validated-{digest}")
    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
