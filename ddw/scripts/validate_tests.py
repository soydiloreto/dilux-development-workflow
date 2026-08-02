#!/usr/bin/env python3
"""ddw-test, the mechanical half — run by the skill, never re-derived.

**What this attests, and what it cannot.** DDW does not run your suite. It does
not know whether this is pytest or jest or a monorepo with five runners, in what
directory, with which environment — and being wrong about that in somebody else's
repository is the failure `docs/RATIONALE.md` decision 2 refuses. The numbers in
the report are the model's account of a run it did.

What stops being optional is the account itself: which runner, the exact command,
how many tests ran and how many passed, every failure named, coverage stated as
three numbers against a floor that is quoted rather than invented, and every skip
carrying a reason. A run reported as "tests pass" is not a report — it is the
sentence a gate used to turn true on, and this is the artifact that replaces it.

The distinction matters more here than anywhere else in the catalog, so the
script prints it on every run: a complete report can be a complete fiction. What
it cannot be any more is absent, vague, or arithmetically impossible.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §6 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import hashlib
import os
import re
import sys

# `| Runner | pytest |`, `Runner: pytest`, `**Runner:** pytest` — the shape the
# model reaches for varies and the field is what matters.
def _field(text, *names):
    for name in names:
        m = re.search(rf"^\s*\|?\s*\*{{0,2}}{name}\*{{0,2}}\s*[:|]\s*(.+?)\s*\|?\s*$",
                      text, re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip().strip("`*|").strip()
            if val and not val.startswith("[") and val not in ("-", "—", "N/A", "TBD"):
                return val
    return ""


def _number(text, *names):
    """A field's leading number, or None. `12 (3 skipped)` is 12."""
    raw = _field(text, *names)
    m = re.match(r"(\d+(?:\.\d+)?)", raw.replace(",", "."))
    return float(m.group(1)) if m else None


def _repo_relative(path):
    p = os.path.abspath(path)
    idx = p.rfind(os.sep + "docs" + os.sep)
    return p[idx + 1:].replace(os.sep, "/") if idx > 0 else p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--tier", default="FEATURE")
    ap.add_argument("--floor", type=float, default=80.0,
                    help="coverage floor when the report does not quote its own")
    args = ap.parse_args()

    try:
        text = open(args.report, encoding="utf-8").read()
    except OSError as exc:
        print(f"validate_tests: cannot read {args.report}: {exc}", file=sys.stderr)
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

    # F-TEST-01: which runner, and the exact command. A report nobody can re-run
    # is an anecdote — and this is the field that makes the rest checkable by a
    # human in ten seconds, which is the only verification DDW can offer here.
    runner = _field(text, "Runner", "Corredor")
    command = _field(text, "Command", "Comando")
    if runner and command:
        ok("F-TEST-01", f"runner and command named: {runner} — `{command[:48]}`")
    else:
        missing = ", ".join(n for n, v in (("Runner", runner), ("Command", command)) if not v)
        fail("F-TEST-01", f"the report does not say how the run was produced (missing: {missing}). "
                          "Nobody can reproduce it, which is the only check available here")

    # F-TEST-02: the counts exist and add up. Arithmetic is the one thing a
    # report cannot lie about without saying so.
    total = _number(text, "Total", "Tests", "Total tests")
    passed = _number(text, "Passed", "Pasaron", "Passing")
    failed = _number(text, "Failed", "Fallaron", "Failing")
    skipped = _number(text, "Skipped", "Omitidos", "Saltados") or 0
    if total is None or passed is None or failed is None:
        missing = ", ".join(n for n, v in (("Total", total), ("Passed", passed),
                                           ("Failed", failed)) if v is None)
        fail("F-TEST-02", f"missing count(s): {missing}. 'the tests pass' is the claim this "
                          "artifact exists to replace")
    elif abs((passed + failed + skipped) - total) > 0.5:
        fail("F-TEST-02", f"the counts do not add up: {passed:.0f} passed + {failed:.0f} failed "
                          f"+ {skipped:.0f} skipped ≠ {total:.0f} total")
    else:
        ok("F-TEST-02", f"{total:.0f} test(s): {passed:.0f} passed, {failed:.0f} failed, "
                        f"{skipped:.0f} skipped — and they add up")

    # F-TEST-03: a failure is named or it is not reported. A count with no names
    # is a number nobody can act on, and the loop has nothing to work from.
    named = re.findall(r"^\s*[-*|]\s*(?:❌\s*)?`?([\w./:\[\]-]+::[\w.\[\]-]+|[\w./-]+\.\w+::?[\w.\[\]-]*)",
                       text, re.MULTILINE)
    if failed is None:
        pass                                          # already reported by F-TEST-02
    elif failed == 0:
        ok("F-TEST-03", "no failures to name")
    elif len(named) >= failed:
        ok("F-TEST-03", f"{failed:.0f} failure(s), each named")
    else:
        fail("F-TEST-03", f"{failed:.0f} failure(s) reported and {len(named)} named. A count "
                          "with no test IDs is a number the fix loop cannot work from")

    # F-TEST-04 / F-TEST-05: three coverage numbers, against a floor the report
    # quotes rather than invents. The floor belongs to the project — AGENTS.md or
    # the spec — and a report that picks its own passes itself.
    line = _number(text, "Line coverage", "Cobertura de l[ií]neas", "Lines")
    branch = _number(text, "Branch coverage", "Cobertura de ramas", "Branches")
    func = _number(text, "Function coverage", "Cobertura de funciones", "Functions")
    have = [(n, v) for n, v in (("line", line), ("branch", branch), ("function", func))]
    absent = [n for n, v in have if v is None]
    if absent:
        fail("F-TEST-04", "coverage missing for: " + ", ".join(absent)
                          + ". Three numbers, because one of them hides the other two")
    else:
        ok("F-TEST-04", f"coverage stated: line {line:.0f}%, branch {branch:.0f}%, "
                        f"function {func:.0f}%")

    floor_raw = _field(text, "Coverage floor", "Piso de cobertura", "Floor")
    floor_m = re.search(r"(\d+(?:\.\d+)?)", floor_raw)
    floor = float(floor_m.group(1)) if floor_m else None
    source = re.search(r"AGENTS\.md|spec-|fix-|docs/ddw", floor_raw)
    if floor is None:
        fail("F-TEST-05", "the report states no coverage floor, so nothing decides whether these "
                          "numbers are good enough. Quote the project's, from AGENTS.md or the spec")
    elif not source:
        warn("F-TEST-05", f"the floor ({floor:.0f}%) is stated but not sourced — say where it comes "
                          "from, or it is a number this report chose for itself")
    else:
        ok("F-TEST-05", f"floor {floor:.0f}%, quoted from {source.group(0)}")

    if floor is not None and not absent:
        under = [f"{n} {v:.0f}%" for n, v in have if v < floor]
        if under:
            fail("F-TEST-04", f"coverage under the floor of {floor:.0f}%: " + ", ".join(under))

    # F-TEST-06: a skip nobody explained is a test that does not exist, and it
    # is the cheapest way to make a suite green.
    if skipped and not re.search(r"skip\w*\s*[:(-]|omitid\w*\s*[:(-]|reason|motivo", text,
                                 re.IGNORECASE):
        fail("F-TEST-06", f"{skipped:.0f} skipped test(s) with no reason given. A silent skip is "
                          "the cheapest way to make a suite green")
    elif skipped:
        ok("F-TEST-06", f"{skipped:.0f} skipped test(s), with reasons")
    else:
        ok("F-TEST-06", "nothing skipped")

    lint = _field(text, "Lint", "Linter", "Type check", "Typecheck")
    if not lint:
        warn("W-TEST-01", "no lint or type-check result reported; VERIFY will ask for it (F-VER-05)")

    verdict = "PASSED" if fails == 0 else f"FAILED ({fails} FAIL{'S' if fails > 1 else ''})"
    report = [f"/ddw-validate-tests {args.report} — {verdict}", "─" * 64]
    report += rows
    report.append("─" * 64)
    for line_out in report:
        print(line_out)
    passed_rows = sum(1 for r in rows if r.strip().startswith("✅"))
    print(f"Total: {passed_rows} passed, {fails} failed, {warns} warnings")
    print(f"Result: {verdict}")
    print("Scope: DDW does NOT run your suite. This checks the REPORT of the run you did — the "
          "runner and command\n       named, the counts adding up, failures identified, three "
          "coverage numbers against a quoted floor,\n       skips explained. The numbers remain "
          "your model's account. A complete report can still be a false one.")

    try:
        report_path = re.sub(r"\.md$", "", os.path.abspath(args.report)) + ".validation.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(report) + "\n"
                     + f"Total: {passed_rows} passed, {fails} failed, {warns} warnings\n"
                     + f"Result: {verdict}\n```\n")
        print(f"Report: {_repo_relative(report_path)}")
    except OSError:
        pass

    if fails == 0:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        abs_p = os.path.abspath(args.report)
        idx = abs_p.rfind(os.sep + "docs" + os.sep)
        root = abs_p[:idx] if idx > 0 else os.getcwd()
        sess = os.path.join(root, ".ddw-sessions")
        os.makedirs(sess, exist_ok=True)
        with open(os.path.join(sess, f"tests-validated-{digest}"), "w", encoding="utf-8") as fh:
            fh.write(os.path.basename(abs_p) + "\n")
        print(f"Receipt: .ddw-sessions/tests-validated-{digest}")

    print("Show the user this table IN FULL — every rule ID, every ✅ / ⚠️ / ❌ — "
          "and the Report line above it.\n"
          "This applies to a re-validation of something unchanged too: they are "
          "approving what they can see, and\na summary is an approval of the "
          "summary. The receipt says the bytes are the same; it does not say "
          "anyone read this.")
    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
