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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ddw_receipt  # noqa: E402 — same directory, resolved above

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


def _unfilled(value):
    """Is this still the template's placeholder rather than an answer?

    `[like this]` and `{like this}` both, because this repository ships both:
    the PRD template writes `[Title]` and the fix-brief writes `{one descriptive
    line}`. What is left once the placeholders are removed is what somebody
    actually wrote — `docs/api.md:41 — {describe it}` keeps its path and counts.
    """
    v = (value or "").strip().strip("*_`")
    if not v:
        return True
    return not re.search(r"[0-9A-Za-zÀ-ÿ]", re.sub(r"\[[^\[\]]*\]|\{[^{}]*\}", "", v))


def _after_label(text, label):
    """What the document says after `label:`, or "" if the label is absent.

    Not anchored to the start of a line. A fix-brief is four labelled facts and
    nothing says they must be four bullets — "bug: none. change: everything.
    regression test: none. risk: none." is one line and four answers, and
    demanding a line each refused it for its layout, which is the refusal this
    repository keeps having to take back out.

    The answer ends where the next label begins, so one label's answer is never
    read as the next one's.
    """
    m = re.search(r"\b%s\s*\**\s*:" % re.escape(label), text, re.IGNORECASE)
    if not m:
        return ""
    rest = text[m.end():]
    stops = [rest.find("\n")] + [
        mm.start() for other in FIX_BRIEF_SECTIONS if other != label
        for mm in [re.search(r"\b%s\s*\**\s*:" % re.escape(other), rest, re.IGNORECASE)] if mm]
    stops = [i for i in stops if i >= 0]
    return (rest[:min(stops)] if stops else rest).strip()


def _items(text, prefix):
    """Bullet items carrying an ID of the given prefix, as (id, full_text).

    A bullet whose text after the ID is the template's placeholder is not a
    requirement: `- FR-01: [atomic requirement]` says an FR exists and says
    nothing about what it is. Counting those is how a PRD of placeholders came
    out with three FRs, one NFR and three ACs, all of them traced to each other.
    """
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


def _after_id(item_id, text):
    """The requirement itself, with its identifier removed.

    `_items` keeps the whole bullet so a rule can quote it back to the reader.
    Any rule that then asks a question ABOUT THE CONTENT has to ask it of the
    content — `NFR-01` carries digits, `FR-03` carries digits, and a rule looking
    for a number found the label every time.
    """
    return re.sub(r"^[ \t]*[-*]\s+\**" + re.escape(item_id) + r"\**\s*[:.(]?", "", text, count=1)


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



# ── The corrective loop has a ceiling, and it is a number ─────────────────────
#
# `PRD loops` / `Spec loops` were incremented by the skills and compared to
# nothing. Four documents named them as one of the three things that stop an
# unattended run, so the ceiling was asserted in prose and unreachable in fact:
# a counter with no limit is a tally, not a stop.
#
# The ceiling is not a wall. It fails, which shuts the gate, which is what forces
# the one thing the loop cannot produce for itself — a person deciding. Getting
# past it means editing the artifact with them, which is the point: three rounds
# of the model correcting its own document without converging is the signal that
# what is missing is a decision, not another pass.
LOOP_CEILING = 3


def _loop_count(text, label):
    m = re.search(rf"^[ \t]*\|\s*{label}\s*\|\s*(\d+)", text, re.IGNORECASE | re.MULTILINE)
    return int(m.group(1)) if m else 0


def _loops_since_human(text):
    """Rounds since a person last decided something, which is what the ceiling
    is about. Absent, it falls back to the running total — an older document has
    no second number, and reading its total is the safe direction to be wrong
    in: it stops sooner, never later."""
    m = re.search(r"^[ \t]*\|\s*Loops since (?:the )?last human decision\s*\|\s*(\d+)",
                  text, re.IGNORECASE | re.MULTILINE)
    return int(m.group(1)) if m else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prd")
    ap.add_argument("--tier", default="FEATURE", choices=ddw_receipt.TIERS)
    args = ap.parse_args()
    try:
        text = open(args.prd, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as exc:
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

    # A split index is not a PRD and must not be judged as one: the protocol
    # REPLACES the parent with an index, and the AC list it used to hold is gone
    # the moment the split lands. So the one thing nobody could check afterwards
    # is whether the parts actually cover the whole — and nothing did. The index
    # now carries the mapping, and this is where it is counted.
    if re.search(r"^\|\s*Status\s*\|\s*Split\s*\|", text, re.MULTILINE | re.IGNORECASE):
        # The header is a table here, like every other field of the index, so it
        # is read as one — `_after_label` reads `label:` prose and found nothing.
        m = re.search(r"^\|\s*Original acceptance criteria\s*\|\s*(\d+)",
                      text, re.MULTILINE | re.IGNORECASE)
        total = int(m.group(1)) if m else 0
        taken, dupes = {}, []
        for row in re.findall(r"^\|.*$", text, re.MULTILINE):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            sub = cells[0] if cells else ""
            if not re.match(r"^[A-Z]+-\d+[a-z]$", sub):
                continue
            for ac in re.findall(r"AC-\d+", " ".join(cells)):
                if ac in taken:
                    dupes.append(f"{ac} is in {taken[ac]} and {sub}")
                taken[ac] = sub
        if not total:
            fail("F-PRD-10", "the index does not say how many acceptance criteria the original PRD "
                             "had (`| Original acceptance criteria | N |`), so whether the parts "
                             "cover the whole cannot be answered — and the original is gone")
        else:
            want = {f"AC-{n:02d}" for n in range(1, total + 1)}
            lost = sorted(want - set(taken))
            problems = []
            if lost:
                problems.append("no sub-ticket takes " + ", ".join(lost))
            if dupes:
                problems.append("; ".join(dupes))
            if problems:
                fail("F-PRD-10", "the split does not partition the original: " + " · ".join(problems))
            else:
                ok("F-PRD-10", f"the {len(taken)} acceptance criteria of the original are taken by "
                               f"exactly one sub-ticket each ({len(set(taken.values()))} sub-tickets)")
        print(f"\n/ddw-validate-prd {args.prd} — {'FAILED' if fails else 'PASSED'} (split index)")
        print("─" * 64)
        for row in rows:
            print(row)
        print("─" * 64)
        print(f"Result: {'FAILED' if fails else 'PASSED'}")
        sys.exit(2 if fails else 0)

    if args.tier == "QUICK-FIX":
        low = text.lower()
        missing = [s for s in FIX_BRIEF_SECTIONS if s not in low]
        # …and each of them has to SAY something. The four labels were the whole
        # test, so the fix-brief exactly as `ddw-create-prd` ships it — `**Bug**:
        # {one descriptive line}`, `**Change**: {file}:{line}` — passed and wrote
        # the receipt. Copy the template, run the validator, and the one gate
        # QUICK-FIX has before CODE was paid for a document that describes no
        # bug, names no file and promises no test. Measured, receipt and all.
        unwritten = [s for s in FIX_BRIEF_SECTIONS
                     if s not in missing and _unfilled(_after_label(text, s))]
        if missing:
            fail("QUICK-FIX", f"fix-brief incomplete, missing: {', '.join(missing)}")
        elif unwritten:
            fail("QUICK-FIX", "fix-brief still carrying the template's placeholder in: "
                              + ", ".join(unwritten))
        else:
            ok("QUICK-FIX", "the four fix-brief sections are present and filled in")
    else:
        frs = _items(text, "FR")
        nfrs = _items(text, "NFR")
        acs = _items(text, "AC")

        # F-PRD-08 first: structure gates everything else's meaning — and a
        # section is not present because its heading is.
        #
        # `_unfilled` was written for the QUICK-FIX brief and called from there
        # alone, so the big PRD — the document the `define` gate is FOR — passed
        # with every field still bracketed. Measured: the shipped template with
        # ONE line filled in (the NFR, which needs a number) came out
        # `PASSED — 8 passed, 0 failed` and wrote its receipt. Placeholders for
        # the problem, the goals, every FR, every AC, the scope, the
        # dependencies. The comment inside this file already described the bug
        # for the four-line brief; the twenty-line document had the same one and
        # nobody carried the fix across.
        missing = [pretty for pretty, names in SECTIONS
                   if not _section_body(text, names)]
        unwritten = [pretty for pretty, names in SECTIONS
                     if pretty not in missing and _unfilled(_section_body(text, names))]
        if args.tier != "FEATURE" and "Out of Scope" in missing:
            missing.remove("Out of Scope")
        if missing:
            fail("F-PRD-08", f"missing structural section(s): {', '.join(missing)}")
        elif unwritten:
            fail("F-PRD-08", "section(s) still carrying the template's placeholder and nothing "
                             "else: " + ", ".join(unwritten))
        else:
            ok("F-PRD-08", "all mandatory sections present and written in")

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

        # F-PRD-03: a number in every NFR — in the REQUIREMENT, not in its label.
        # `_items` returns the whole bullet, `NFR-01` included, so asking whether
        # the text contains a digit was asking whether the identifier does. It
        # always does. The rule was catalogued, implemented, printed a green row
        # on every run, and could not fail on any document: "the load should be
        # fast" passed as a measured requirement.
        unmetered = [i for i, t in nfrs if not re.search(r"\d", _after_id(i, t))]
        if unmetered:
            fail("F-PRD-03", f"NFR with no quantitative value: {', '.join(unmetered)}")
        else:
            ok("F-PRD-03", "every NFR carries a quantitative value")

        # F-PRD-04: Out of Scope non-empty (FEATURE).
        if args.tier == "FEATURE":
            oos = _section_body(text, ("out of scope", "fuera de alcance"))
            if re.search(r"^[ \t]*[-*]\s+\S", oos, re.MULTILINE):
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

        # W-PRD-06: over the ceiling scope control names, on THIS document.
        #
        # The scope check runs once, on the parent, and nothing looked at the
        # parts it produced. Measured across three runs of one source PRD: a
        # split into four left children of 11, 12, 16 and 12 ACs — every one
        # above the threshold that caused the split — and the box reported "4
        # sub-tickets" without saying so. The user approved a cut that had not
        # solved the problem, because the number that would have said it was on
        # nobody's screen.
        #
        # A warning, not a failure: deciding to keep a ticket whole is the
        # user's to make, and `define.instructions.md` says so. What is not
        # theirs to lose is the number.
        if args.tier == "FEATURE" and len(acs) > 7:
            warn("W-PRD-06", f"{len(acs)} acceptance criteria, over the 5–7 that Scope Control "
                             "names as the point to reassess. Legitimate if it was decided; a "
                             "sub-ticket of a split arriving here means the split did not make "
                             "the parts smaller than the whole")

        # W-PRD-05: risks section empty.
        if not _section_body(text, ("risks", "riesgos")):
            warn("W-PRD-05", "Risks and Mitigations missing or empty")

        rows.append("  👁  F-PRD-02 (binary ACs), F-PRD-07 (undeclared cross-references),")
        rows.append("      W-PRD-01 (FR with no rationale) and W-PRD-03 (passive voice) are")
        rows.append("      MANUAL: judge them and say so explicitly in your report.")
        rows.append("      A rule the script names and never prints is one nobody judges.")

    total_loops = _loop_count(text, "PRD loops")
    since = _loops_since_human(text)
    loops = total_loops if since is None else since
    if since is not None and since > total_loops:
        # The running total counts every round; the second number counts a subset
        # of them. A "since" above the total means one of the two was not being
        # kept — and the one the ceiling reads is the one that would then let the
        # document loop forever, which is the failure this ceiling exists to stop.
        fail("F-PRD-LOOP", f"the header says {since} loop(s) since the last human decision but only "
             f"{total_loops} in total. The total counts every round and is never reset, so it "
             "cannot be the smaller of the two: one of the counters was not incremented.")
    if loops >= LOOP_CEILING:
        fail("F-PRD-LOOP", f"this artifact has been through {loops} corrective loops "
                       f"(the ceiling is {LOOP_CEILING}). Three rounds of correcting a document "
                       "without converging is the signal that what is missing is a decision, not "
                       "another pass. Stop and put the open question to the user; getting past this "
                       "means editing it with them and resetting the counter with their answer "
                       "recorded. Under `autonomy: minimal` this is one of the three stops that do "
                       "not have a mode.")
    else:
        ok("F-PRD-LOOP", f"{loops} loop(s) since a human decided, under the ceiling of "
                     f"{LOOP_CEILING}; {total_loops} in total for this document")

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
        # One writer for all six receipts, so the rule cannot drift six ways —
        # and so that writing one is RECORDED in the journal the gate reads.
        print("Receipt: .ddw-sessions/" + ddw_receipt.write(args.prd, "prd", text, args.tier))

    # The table above is for the USER, and it does not reach them by itself.
    #
    # Twice now, live, a model ran this script and showed the person a summary:
    # "PASSED (7 checks)". Both times the instruction not to existed — in the
    # skill and in the catalog — and both times the model had not loaded either,
    # because it ran the script directly. A rule in a file nobody opened is a
    # rule that is not in the room. This line is: it arrives attached to the very
    # output it governs, in the same context window, every single run.
    print("Show the user this table IN FULL — every rule ID, every ✅ / ⚠️ / ❌ — "
          "and the Report line above it.\n"
          "This applies to a re-validation of something unchanged too: they are "
          "approving what they can see, and\na summary is an approval of the "
          "summary. The receipt says the bytes are the same; it does not say "
          "anyone read this.")

    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
