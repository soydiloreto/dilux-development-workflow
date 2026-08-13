#!/usr/bin/env python3
"""ddw-create-adr's mechanical half — the only artifact that had no checker.

Every other document in DDW has a validator pinning what it is: a PRD that is
not a PRD fails eight checks before anyone reads it. The ADR had none, so the
one thing that makes it an ADR — that it EXPLAINS a decision already taken and
binds nobody — rested entirely on the model having the genre right. A different
model, or the same one in a hurry, writes "the system must rate-limit to 5 per
IP" and now a document no gate reads and no script judges is issuing
requirements, competing with the spec for authority over the implementation.

That is the rule this exists for (F-ADR-03), and it is checkable: normative verbs
in the Decision and Consequences sections. The other four are shape.

**No gate reads this.** An ADR is written only when a decision warrants one, so a
gate would demand one per ticket and fill `docs/adr/` with filler, which is worse
than the gap it closes. This is run by the skill that writes the ADR, and its
verdict is for the person reading it.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §7 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ddw_receipt  # noqa: E402 — same directory, resolved above

SECTIONS = ("Context", "Options considered", "Decision", "Consequences")

# Spanish and English, because the skill writes the ADR in the user's language
# and keeps only the section names fixed. A rule that only catches "must" passes
# every Spanish ADR ever written, which is most of them here.
NORMATIVE = (
    r"\bmust\b", r"\bshall\b", r"\bshould\b", r"\bhas to\b", r"\bhave to\b",
    r"\bis required to\b", r"\bare required to\b",
    r"\bdebe\b", r"\bdeben\b", r"\bdeberá\b", r"\bdeberán\b", r"\bdebería\b",
    r"\btiene que\b", r"\btienen que\b", r"\bhay que\b",
)
_NORMATIVE = re.compile("|".join(NORMATIVE), re.IGNORECASE)


def _strip_uncheckable(text):
    """Blank out fenced code and blockquotes, keeping line numbers intact.

    A quoted requirement — `> the PRD requires that…` — is the ADR reporting
    what something else demands, which is exactly what an ADR is for. Reading it
    as the ADR's own voice turned the sharpest rule here into the noisiest.
    """
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        if fenced or line.lstrip().startswith(">"):
            out.append("")
            continue
        out.append(line)
    return out


def _section_bounds(lines):
    """{name: (start, end)} for the `## ` headings this document carries."""
    heads = [(i, ln.strip()[3:].strip()) for i, ln in enumerate(lines)
             if ln.strip().startswith("## ")]
    bounds = {}
    for idx, (i, name) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        bounds[name.lower()] = (i + 1, end)
    return bounds


def _body(lines, bounds, name):
    span = bounds.get(name.lower())
    if not span:
        return []
    return lines[span[0]:span[1]]


def _written_in(chunk):
    """Written in, as opposed to present and empty or still a placeholder."""
    text = "\n".join(chunk).strip()
    if not text:
        return False
    stripped = re.sub(r"\[[^\]]*\]", "", text).strip()   # `[the problem]`
    return len(stripped) >= 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("adr")
    # Every validator in this family takes it, and the family is driven
    # uniformly — by the suite, and by anything else that walks
    # `validate_*.py`. Constrained to the tiers the graph defines, like the
    # others: a flag that accepts any string at all is how a tier came to be
    # decoration. No F-ADR rule varies by tier — an ADR is an ADR in a
    # QUICK-FIX — and the report says so rather than swallowing the flag,
    # because a flag accepted and silently dropped is its own defect.
    ap.add_argument("--tier", default="FEATURE", choices=ddw_receipt.TIERS)
    args = ap.parse_args()

    try:
        with open(args.adr, encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"validate_adr: cannot read {args.adr}: {exc}", file=sys.stderr)
        sys.exit(3)

    lines = _strip_uncheckable(raw)
    bounds = _section_bounds(lines)
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

    # F-ADR-01 — the four sections, present and written in.
    missing = [s for s in SECTIONS if s.lower() not in bounds]
    empty = [s for s in SECTIONS
             if s.lower() in bounds and not _written_in(_body(lines, bounds, s))]
    if missing or empty:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if empty:
            parts.append("present but empty or still a placeholder: " + ", ".join(empty))
        fail("F-ADR-01", "; ".join(parts))
    else:
        ok("F-ADR-01", "Context, Options considered, Decision and Consequences are all written in")

    # F-ADR-02 — at least two options. One option is a preference; recording it
    # as a decision is how a preference acquires the authority of one.
    opts = _body(lines, bounds, "Options considered")
    names = [ln.strip()[4:].strip() for ln in opts if ln.strip().startswith("### ")]
    if len(names) >= 2:
        ok("F-ADR-02", f"{len(names)} options weighed: " + ", ".join(n[:24] for n in names[:4]))
    else:
        fail("F-ADR-02", f"{len(names)} option(s) under 'Options considered' — an ADR records a "
                         "choice, and a choice needs something it was chosen over. One option is a "
                         "preference. Use `### ` for each one")

    # F-ADR-03 — the one that makes it an ADR. Decision and Consequences only:
    # 'Options considered' argues about what a thing would do, and hedged
    # language there is analysis, not instruction.
    offenders = []
    for name in ("Decision", "Consequences"):
        span = bounds.get(name.lower())
        if not span:
            continue
        for i in range(*span):
            m = _NORMATIVE.search(lines[i])
            if m:
                offenders.append((i + 1, m.group(0), lines[i].strip()[:70]))
    if offenders:
        detail = "; ".join(f"line {n}: “{w}” — {t}" for n, w, t in offenders[:3])
        fail("F-ADR-03", f"{len(offenders)} normative sentence(s) in Decision/Consequences. An ADR "
                         f"explains a decision already taken; it does not impose one. {detail}. "
                         "Move the obligation to the spec, and here describe what was decided and "
                         "what it cost")
    else:
        ok("F-ADR-03", "Decision and Consequences describe rather than prescribe")

    # F-ADR-04 — Status. `Accepted`, or superseded by a specific ADR: "obsolete"
    # with no successor is a decision that was undone by nobody, and the reader
    # six months out has no thread to pull.
    m = re.search(r"^\|\s*Status\s*\|\s*([^|]+?)\s*\|", raw, re.MULTILINE | re.IGNORECASE)
    status = (m.group(1).strip() if m else "")
    if re.fullmatch(r"Accepted", status, re.IGNORECASE):
        ok("F-ADR-04", "Status: Accepted")
    elif re.fullmatch(r"Superseded by ADR-\d+", status, re.IGNORECASE):
        ok("F-ADR-04", f"Status: {status}")
    else:
        fail("F-ADR-04", f"Status is {status!r}; it must be `Accepted` or `Superseded by ADR-NNN`. "
                         "A decision is live or it was replaced by a named one — there is no third "
                         "state a reader can act on")

    # F-ADR-05 — the number is this document's identity: the successor names it.
    base = os.path.basename(args.adr)
    m = re.match(r"adr-(\d+)-", base)
    if not m:
        fail("F-ADR-05", f"`{base}` is not named `adr-NNN-title.md`, so no other ADR can supersede "
                         "it by name")
    else:
        mine = m.group(1)
        clash = []
        for other in sorted(os.listdir(os.path.dirname(os.path.abspath(args.adr)) or ".")):
            if other == base:
                continue
            om = re.match(r"adr-(\d+)-", other)
            if om and om.group(1) == mine:
                clash.append(other)
        if clash:
            fail("F-ADR-05", f"number {mine} is already taken by {', '.join(clash)} — two decisions "
                             "answering to one number make every reference to it ambiguous")
        else:
            ok("F-ADR-05", f"ADR-{mine}, and the number is unused elsewhere in docs/adr/")

    # W-ADR-01 — the skill's own ceiling. Long ADRs stop being read, and an ADR
    # nobody reads is a decision nobody can find.
    useful = [ln for ln in lines if ln.strip() and not ln.strip().startswith("|")]
    if len(useful) > 45:
        warn("W-ADR-01", f"{len(useful)} lines of prose; the skill's limit is about 30. What "
                         "belongs to the design belongs in the spec")

    # W-ADR-02 — what it hangs off. Optional: some decisions predate any ticket.
    if not re.search(r"^\|\s*Ticket\s*\|\s*(?!\s*(N/A|-|—)\s*\|)[^|]+\|", raw,
                     re.MULTILINE | re.IGNORECASE):
        warn("W-ADR-02", "no ticket in the header, so nothing connects this decision to the work "
                         "that caused it")

    print(f"\n/ddw-validate-adr {args.adr} — {'FAILED' if fails else 'PASSED'}")
    print("─" * 64)
    for row in rows:
        print(row)
    print("  👁  Whether the reasons are GOOD, and whether the options were the real")
    print("      alternatives, are MANUAL")
    print(f"  ℹ  tier {args.tier}: every F-ADR rule applies in full — none of them vary by tier")
    print("─" * 64)
    print(f"Total: {len(rows) - fails - warns} passed, {fails} failed, {warns} warnings")
    print(f"Result: {'FAILED' if fails else 'PASSED'}")
    sys.exit(2 if fails else 0)


if __name__ == "__main__":
    main()
