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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ddw_receipt  # noqa: E402 — same directory, resolved above

MINIMUM = 80        # line, branch and function coverage — testing.instructions.md
# `❌` is not a word character, so inside a `\b(...)\b` group it demanded a word
# character on BOTH sides of it — and every shape the verify skill tells the
# model to write (`- AC-01 ❌`, `| AC-01 | ❌ |`) has a space or a pipe there.
# Only `x❌y` ever matched. A report marking every criterion failed read as
# "all N AC carry a passing verdict", F-VER-01 passed, and the receipt was
# written. The mark carries its own boundary; it does not need one imposed.
FAILING = re.compile(r"(?:\b(?:fail|failed|falla|fallo|fallido|error)\b|❌|✗|✘)", re.IGNORECASE)
# `sad-path` as well as `sad path`: the hyphenated adjective is the ordinary
# English spelling in front of a noun ("sad-path tests"), and a rule that reads
# one and not the other refuses the report for a punctuation mark.
SAD_PATH = re.compile(r"\b(sad[ -]path|camino triste|invalid|inv[aá]lid|negative test|"
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
    ap.add_argument("--tier", default="FEATURE", choices=ddw_receipt.TIERS)
    ap.add_argument("--prd", default=None)
    ap.add_argument("--spec", default=None)
    args = ap.parse_args()

    if args.tier == "QUICK-FIX":
        print("validate_verify: tier QUICK-FIX has no VERIFY phase (catalog §Tier Modifier). "
              "Nothing to validate.", file=sys.stderr)
        sys.exit(3)

    try:
        text = open(args.report, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as exc:
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

    # `--prd` and `--spec` are chosen by whoever runs this, and nothing tied
    # them to the ticket the report is about — so the verdict for T-1 could be
    # checked against T-2's documents, or against any file at all. When the
    # report names its ticket, the documents have to name the same one. When it
    # does not (a scratch filename), there is nothing to compare and this says
    # nothing rather than guessing.
    _ticket = re.match(r"verify-(.+)\.md$", os.path.basename(args.report))
    if _ticket:
        want = _ticket.group(1)
        for flag, given in (("--prd", args.prd), ("--spec", args.spec)):
            if not given:
                continue
            stem = os.path.basename(given)
            if not re.search(r"-%s\.md$" % re.escape(want), stem):
                print("validate_verify: %s is %s, which is not a document for ticket %s. The "
                      "verdict for one ticket cannot be checked against another's documents; "
                      "pass this ticket's, or omit the flag and let it be resolved by name."
                      % (flag, stem, want), file=sys.stderr)
                sys.exit(3)

    # F-VER-01: every AC of the PRD accounted for, and none reported failing.
    prd_text = ""
    if prd_path:
        try:
            prd_text = open(prd_path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            prd_text = ""
    acs = _ids(prd_text, "AC") if prd_text else []
    if not prd_text:
        fail("F-VER-01", "the PRD could not be read, so AC coverage was NOT checked. "
                         "Pass --prd <path> and run again")
    elif not acs:
        # Zero criteria is not "every criterion accounted for". `--prd` is chosen
        # by whoever runs this, and pointing it at any file with no AC bullets
        # printed "all 0 AC from the PRD carry a passing verdict" and passed — a
        # green rule whose subject was empty, which is the same nothing-measured
        # this project refuses everywhere else. A PRD with no acceptance criteria
        # is not one this can check: either the wrong file was passed, or the PRD
        # has nothing to verify against yet.
        fail("F-VER-01", "the PRD names no acceptance criteria (%s), so there was nothing to "
                         "check the report against. Point --prd at this ticket's PRD, or write "
                         "the criteria before verifying against them" % _repo_relative(prd_path))
    else:
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
        except (OSError, UnicodeDecodeError):
            spec_text = ""
    if not spec_text:
        fail("F-VER-02/06", "the spec could not be read, so block and test coverage were NOT "
                            "checked. Pass --spec <path> and run again")
    else:
        blocks = re.findall(r"^##\s+Block\s+(\d+)", spec_text, re.MULTILINE)
        missing = [f"Block {b}" for b in blocks
                   if not re.search(r"block\s*%s\b" % b, text, re.IGNORECASE)]
        if not blocks:
            # Same emptiness as F-VER-01, one document over: a spec with no
            # `## Block` heading is not the spec for this ticket, and "all 0
            # spec block(s) are accounted for" said the work was covered.
            fail("F-VER-02", "the spec names no blocks (%s), so there was nothing to check the "
                             "report against. Point --spec at this ticket's spec"
                             % _repo_relative(spec_path))
        elif missing:
            fail("F-VER-02", f"spec block with no verdict in the report: {', '.join(missing)}")
        else:
            ok("F-VER-02", f"all {len(blocks)} spec block(s) are accounted for")

        # The optional backtick is not decoration: the spec skill writes every
        # test name as `` `test_x` ``, and without it this rule read 13 promised
        # tests as zero — and "all 0 test(s) the spec promised are reported"
        # went green on a live run. A rule that measures nothing must not vouch.
        promised = re.findall(r"^[ \t]*[-*]\s+(?:\[[ x]\]\s*)?`?(test[\w./:-]*)", spec_text,
                              re.MULTILINE | re.IGNORECASE)
        if not promised and re.search(r"required tests", spec_text, re.IGNORECASE):
            fail("F-VER-06", "the spec has 'Required tests' sections and not one test name "
                             "could be read from them. Either the spec promises no tests — "
                             "which F-SPEC-06 refuses — or the names are in a format this "
                             "rule cannot parse; both are a NO from a rule that would "
                             "otherwise pass having measured nothing")
        else:
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
        # One writer for all six receipts, so the rule cannot drift six ways —
        # and so that writing one is RECORDED in the journal the gate reads.
        print("Receipt: .ddw-sessions/" + ddw_receipt.write(args.report, "verify", text, args.tier))

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
