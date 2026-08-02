#!/usr/bin/env python3
"""ddw-security-sast, the mechanical half — run by the skill, never re-derived.

**What this attests, and what it cannot.** It does not scan your code and it does
not know whether the findings are right. It reads the report the skill wrote and
answers structural questions: did every category the catalog names get a verdict,
does every finding carry a file and a line, does the stated result follow from the
severities listed, does every suppression carry its fields and a review date that
has not expired. The judgement stays the model's; what stops being optional is the
*shape* of the record it leaves — and a report that cannot be parsed is a report
nobody can check, which is how nineteen rules came to be catalogued and none of
them executed.

That distinction is why this exists at all. `docs/RATIONALE.md` decision 16
refused a receipt for `sast` on the grounds that it would dress "the model
reported it looked" up as proof. It would — of the code. It does not, of the
report: exactly the split `validate_verify.py` already makes for the verification
verdict, where the numbers remain the model's and the completeness does not.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §4 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import datetime
import hashlib
import os
import re
import sys

# The seventeen scan categories, with the severity the catalog fixes for each.
# Fixed on purpose: a model that finds a hardcoded secret and files it as Medium
# has downgraded a Critical, and the severity is what decides whether the phase
# advances. F-SAST-18 and F-SAST-19 are about suppressions, not categories.
CATEGORIES = {
    "F-SAST-01": ("hardcoded secrets", "Critical"),
    "F-SAST-02": ("SQL/NoSQL injection", "Critical"),
    "F-SAST-03": ("OS command injection", "Critical"),
    "F-SAST-04": ("insecure deserialization", "Critical"),
    "F-SAST-05": ("path traversal", "High"),
    "F-SAST-06": ("XSS", "High"),
    "F-SAST-07": ("SSRF", "High"),
    "F-SAST-08": ("broken cryptography", "High"),
    "F-SAST-09": ("debug mode in production", "High"),
    "F-SAST-10": ("logging sensitive data", "High"),
    "F-SAST-11": ("unrestricted upload", "High"),
    "F-SAST-12": ("missing CSRF protection", "High"),
    "F-SAST-13": ("Critical/High CVE in a dependency", "Critical"),
    "F-SAST-14": ("incomplete input validation", "Medium"),
    "F-SAST-15": ("insecure error handling", "Medium"),
    "F-SAST-16": ("Medium CVE in a dependency", "Medium"),
    "F-SAST-17": ("unsafe function", "Medium"),
}

# A verdict marker anywhere on the rule's line. Written this way because the
# report is prose with a table in it, not a form: what matters is that the ID and
# a verdict travel together, not which column they sit in.
CLEAN = ("✅", "[ok]", "[clean]")
FOUND = ("❌", "[fail]", "[found]")
WARN = ("⚠️", "[warn]")

# `path/to/file.py:120`, `app/main.py línea 33`. A finding without a location is
# a sentence, and the fix cannot be reviewed against it.
LOCATION = re.compile(r"[\w./\\-]+\.\w{1,6}\s*[:#]\s*\d+|[\w./\\-]+\.\w{1,6}\s+"
                      r"(?:l[ií]nea|line)\s+\d+", re.IGNORECASE)

SUPPRESSION_FIELDS = ("File", "Category", "Disposition", "Reviewer", "Date",
                      "Justification", "Review by")
ACCEPTED_RISK = re.compile(r"accepted[_ ]risk|riesgo[_ ]aceptado", re.IGNORECASE)
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _repo_relative(path):
    """The path as the user will type it, when it is under a repo we can find."""
    p = os.path.abspath(path)
    idx = p.rfind(os.sep + "docs" + os.sep)
    return p[idx + 1:].replace(os.sep, "/") if idx > 0 else p


def _rule_lines(text):
    """Every line that names a catalogued rule, keyed by rule ID."""
    found = {}
    for line in text.splitlines():
        for rule in CATEGORIES:
            if rule in line:
                found.setdefault(rule, []).append(line)
    return found


def _verdict_of(lines):
    """clean / found / warn / None, from the markers on a rule's line(s)."""
    joined = " ".join(lines)
    if any(m in joined for m in FOUND):
        return "found"
    if any(m in joined for m in WARN):
        return "warn"
    if any(m in joined for m in CLEAN):
        return "clean"
    return None


def _suppressions(text):
    """(title, body) per `### Suppression: …` block, in the documented shape."""
    blocks, current, buf = [], None, []
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s*(?:Suppression|Supresi[oó]n)\s*:?\s*(.*)$", line, re.IGNORECASE)
        if m:
            if current is not None:
                blocks.append((current, "\n".join(buf)))
            current, buf = m.group(1).strip() or "(unnamed)", []
        elif current is not None:
            if re.match(r"^#{1,3}\s", line):        # a new top-level heading ends it
                blocks.append((current, "\n".join(buf)))
                current, buf = None, []
            else:
                buf.append(line)
    if current is not None:
        blocks.append((current, "\n".join(buf)))
    return blocks


def _field(body, name):
    """The value of `| Field | Value |` row `name`, or "" when absent/empty."""
    m = re.search(rf"^\s*\|\s*{re.escape(name)}\s*\|\s*(.*?)\s*\|", body,
                  re.IGNORECASE | re.MULTILINE)
    val = (m.group(1) if m else "").strip()
    return "" if val in ("", "-", "—", "N/A", "TBD", "[", "]") or val.startswith("[") else val


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--tier", default="FEATURE")
    ap.add_argument("--today", default=None,
                    help="ISO date to age suppressions against; today if omitted")
    args = ap.parse_args()

    try:
        text = open(args.report, encoding="utf-8").read()
    except OSError as exc:
        print(f"validate_sast: cannot read {args.report}: {exc}", file=sys.stderr)
        sys.exit(3)

    today = (datetime.date.fromisoformat(args.today) if args.today
             else datetime.date.today())

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

    lines = _rule_lines(text)

    # Every category got a verdict. The catalog lists seventeen and SAST is not
    # relaxed for any tier, QUICK-FIX included — it is that tier's only security
    # validation. A category nobody wrote a verdict for was not evaluated, and
    # "no news" is the shape an unrun check takes.
    missing = [r for r in CATEGORIES if r not in lines]
    unjudged = [r for r in CATEGORIES if r in lines and _verdict_of(lines[r]) is None]
    if missing:
        fail("F-SAST-COVERAGE", f"{len(missing)} categor(y/ies) with no verdict in the report: "
                                + ", ".join(sorted(missing)[:6])
                                + (" …" if len(missing) > 6 else ""))
    elif unjudged:
        fail("F-SAST-COVERAGE", "named but with no ✅ / ❌ / ⚠️ beside them: "
                                + ", ".join(sorted(unjudged)))
    else:
        ok("F-SAST-COVERAGE", f"all {len(CATEGORIES)} catalogued categories carry a verdict")

    # A finding has to say where. Reviewing a fix means going to the line.
    located, unlocated = [], []
    for rule, ls in lines.items():
        if _verdict_of(ls) == "found":
            (located if any(LOCATION.search(l) for l in ls) else unlocated).append(rule)
    if unlocated:
        fail("F-SAST-LOCATION", "finding with no file:line, so the fix cannot be reviewed "
                                "against it: " + ", ".join(sorted(unlocated)))
    elif located:
        ok("F-SAST-LOCATION", f"{len(located)} finding(s), each naming a file and a line")
    else:
        ok("F-SAST-LOCATION", "no findings to locate")

    # The stated result has to follow from the severities. This is the one place
    # a complete report can still contradict itself, and it is the contradiction
    # that matters: a Critical listed above a PASSED verdict advances the phase.
    blocking = sorted(r for r in located if CATEGORIES[r][1] in ("Critical", "High"))
    says_blocked = re.search(r"\bBLOCKED\b|\bBLOQUEAD", text, re.IGNORECASE)
    says_passed = re.search(r"^\s*(?:Result|Resultado)\s*:?\s*PASSED", text,
                            re.IGNORECASE | re.MULTILINE)
    if blocking and not says_blocked:
        fail("F-SAST-VERDICT", f"{len(blocking)} Critical/High finding(s) "
                               f"({', '.join(blocking)}) and the report does not say BLOCKED")
    elif blocking:
        ok("F-SAST-VERDICT", f"{len(blocking)} Critical/High finding(s) and the report says BLOCKED")
    elif says_passed or not blocking:
        ok("F-SAST-VERDICT", "no Critical/High findings; the result is allowed to pass")

    # Every Medium is fixed or formally suppressed — never left as a note.
    sups = _suppressions(text)
    med_found = sorted(r for r in located if CATEGORIES[r][1] == "Medium")
    sup_text = " ".join(t + " " + b for t, b in sups)
    unresolved = [r for r in med_found if r not in sup_text and not re.search(
        rf"{r}[^\n]*\b(fixed|corregid|resuelt|remediat)", text, re.IGNORECASE)]
    if unresolved:
        fail("F-SAST-MEDIUM", "Medium finding neither fixed nor suppressed: "
                              + ", ".join(unresolved))
    else:
        ok("F-SAST-MEDIUM", f"{len(med_found)} Medium finding(s), each fixed or suppressed")

    # F-SAST-18: a suppression carries its fields, or it is a shrug in a table.
    incomplete = []
    for title, body in sups:
        missing_f = [f for f in SUPPRESSION_FIELDS if not _field(body, f)]
        if ACCEPTED_RISK.search(_field(body, "Disposition")) and not _field(body, "Compensating control"):
            missing_f.append("Compensating control")
        if missing_f:
            incomplete.append(f"{title} (missing {', '.join(missing_f)})")
    if not sups:
        ok("F-SAST-18", "no suppressions to check")
    elif incomplete:
        fail("F-SAST-18", "suppression with empty fields: " + "; ".join(incomplete))
    else:
        ok("F-SAST-18", f"{len(sups)} suppression(s), every field filled in")

    # F-SAST-19: six months, and the clock is read from the document.
    expired, undated = [], []
    for title, body in sups:
        review = _field(body, "Review by")
        m = DATE.search(review)
        if not m:
            undated.append(title)
            continue
        due = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if due < today:
            expired.append(f"{title} (due {due.isoformat()})")
        elif (due - today).days > 190:
            expired.append(f"{title} (review date {due.isoformat()} is more than 6 months out)")
    if not sups:
        ok("F-SAST-19", "no suppressions to age")
    elif undated:
        fail("F-SAST-19", "suppression with no readable review date: " + ", ".join(undated))
    elif expired:
        fail("F-SAST-19", "suppression past its review date: " + "; ".join(expired))
    else:
        ok("F-SAST-19", f"{len(sups)} suppression(s) within their review window")

    # W-SAST-01 is a warning by catalog: Low/Informational left undocumented.
    lows = re.findall(r"\b(?:low|informational|informativ\w*)\b", text, re.IGNORECASE)
    if lows and not re.search(r"\b(?:documented|documentad|noted|registrad)\w*", text, re.IGNORECASE):
        warn("W-SAST-01", f"{len(lows)} Low/Informational mention(s) with nothing saying they were "
                          "documented")

    verdict = "PASSED" if fails == 0 else f"FAILED ({fails} FAIL{'S' if fails > 1 else ''})"
    report = [f"/ddw-validate-sast {args.report} — {verdict}", "─" * 64]
    report += rows
    report.append("─" * 64)
    for line in report:
        print(line)
    passed = sum(1 for r in rows if r.strip().startswith("✅"))
    print(f"Total: {passed} passed, {fails} failed, {warns} warnings")
    print(f"Result: {verdict}")
    print("Scope: this checks the REPORT is complete — every catalogued category judged, every "
          "finding located,\n       the verdict consistent with the severities, suppressions "
          "documented and in date. It does NOT\n       scan your code, and it does not know "
          "whether a finding is right. That judgement stays the model's.")

    try:
        report_path = re.sub(r"\.md$", "", os.path.abspath(args.report)) + ".validation.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(report) + "\n"
                     + f"Total: {passed} passed, {fails} failed, {warns} warnings\n"
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
        with open(os.path.join(sess, f"sast-validated-{digest}"), "w", encoding="utf-8") as fh:
            fh.write(os.path.basename(abs_p) + "\n")
        print(f"Receipt: .ddw-sessions/sast-validated-{digest}")

    # The table above is for the USER, and it does not reach them by itself.
    # Same reason as every other validator: the rule lives where the output is.
    print("Show the user this table IN FULL — every rule ID, every ✅ / ⚠️ / ❌ — "
          "and the Report line above it.\n"
          "This applies to a re-validation of something unchanged too: they are "
          "approving what they can see, and\na summary is an approval of the "
          "summary. The receipt says the bytes are the same; it does not say "
          "anyone read this.")
    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
