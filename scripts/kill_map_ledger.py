#!/usr/bin/env python3
"""The ledger of the checks no fault ever provokes.

`scripts/mutate.py --kill-map` records, for every fault, WHICH suite check
caught it. Crossed against every `bad` that `scripts/verify_install.sh` knows
how to say, what remains are the checks no fault provokes. Of those, nobody
knows whether they CAN fail — and a check that cannot fail reports green
because it has nothing else to say, not because it looked at anything. Five
shipped in this repository: they were finding themselves, and they surfaced by
accident while running mutations.

This file is NOT a report. A generated report that gets committed and never
regenerated is lying within two weeks, and an unbacked claim is exactly what
the rest of this repository hunts down. It is an EXPECTATION: the list somebody
already looked at, with the reason beside each line, and CI compares it against
reality.

  · One appears that is not on the list  → red. Write down why, or write it
    a fault.
  · One on the list disappears           → red. It can be measured now; out.

It is the language of SAST suppressions, for the same reason: it forbids
nothing, it forces it to be said out loud.

    python3 scripts/kill_map_ledger.py --parts <dir> --ledger docs/CHECKS-THAT-CANNOT-FAIL.md
    python3 scripts/kill_map_ledger.py --parts <dir> --ledger <f> --write   # regenerate
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITE = os.path.join(ROOT, "scripts", "verify_install.sh")
HEAD = """# Checks that cannot fail

Generated against the suite by `scripts/kill_map_ledger.py`, and **compared** by
CI rather than trusted: this file is what somebody has already looked at, not a
report nobody regenerates.

Every line is a `bad "…"` of `scripts/verify_install.sh` that **no fault in
`scripts/mutate.py` provokes**. That does not prove it cannot fail — it proves
nothing measures whether it can. Either write a fault that makes it fire, or say
here why there is not one.

A check that cannot fail reports green because it has no other thing to say.

"""


def declared_bads(text):
    """Every `bad "…"` the suite knows how to say."""
    return {m.group(1).strip() for m in re.finditer(r'\bbad\s+"((?:[^"\\]|\\.)*)"', text)}


def fired_from(parts_dir):
    """The checks that caught something, merging every shard's partials."""
    fired, seen_faults = set(), 0
    files = sorted(f for f in os.listdir(parts_dir) if f.endswith(".json"))
    if not files:
        raise SystemExit("kill_map_ledger: no partials in %s — a run that examined "
                         "nothing is not a pass" % parts_dir)
    for name in files:
        with open(os.path.join(parts_dir, name), encoding="utf-8") as fh:
            part = json.load(fh)
        for killers in (part.get("kills") or {}).values():
            seen_faults += 1
            fired |= set(killers if isinstance(killers, list) else [killers])
    if seen_faults == 0:
        raise SystemExit("kill_map_ledger: the partials record not a single fault")
    return fired, seen_faults, len(files)


def _longest_literal(msg):
    """The longest literal stretch of a declared message.

    Comparing the WHOLE message does not work, and not because of the
    variables: the shell eats pieces. `bad "inventing a 'pause:' entry…"`
    prints as "inventing a  entry…", without the quoted part. Demanding the
    full text counted that check as never fired while fault 454 fires it —
    the third time in one session that a number sounded like a finding and
    was measuring the formatting.

    The longest stretch is distinctive without being fragile: it survives the
    shell eating a piece for either of its two causes, and it is not so short
    that it matches anything at all.
    """
    # `$(...)` too, not only `$VAR`. Without it, "expected $EXPECT_SKILLS
    # skills, found $(n "$SELF/skills/*/SKILL.md")" left the glob's path as the
    # longest stretch — which never appears in the output — and the four pinned
    # counts read as never fired RIGHT after the fault that fires them was
    # written. The fourth version of the same class of error.
    # …and the UNCLOSED `$(`. `declared_bads` extracts the message with an
    # expression that ends at the first double quote, so "found $(n "$SELF/…")"
    # is cut at `found $(n `. That remainder glued to the literal made the
    # longest stretch something that never appears — and the four pinned counts
    # read as never fired with the kill recorded two lines below in the same
    # file.
    # …and the stretches between BACKTICKS. An unescaped `bad "… \`mkdir
    # .ddw\` …"` is command substitution to bash: the message prints WITHOUT
    # that part, so the declared literal cannot match the output. Three entries
    # sat here because of that and not because of a hole — the very ✗ that
    # fires them was on the map, with the gap in the middle.
    parts = re.split(
        r"\$\([^)]*\)|\$\(|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\d+|'[^']*'|`[^`]*`|\\?\"",
        msg)
    best = max((p.strip() for p in parts), key=len, default="")
    return best if len(best) >= 12 else ""


def _as_pattern(msg):
    """The declared message as an expression: each `$VAR` is whatever it interpolates.

    Comparing by the prefix up to the first `$` sounds reasonable and is not:
    a message that STARTS with a variable — "$label blocks…", and there are
    many — has an empty prefix, and every empty-prefix message counted as
    never fired. The first real run said 92 and part of it was this: another
    number that sounds like a finding and measures the formatting. The
    variable is a wildcard now, and what gets compared is the whole shape.
    """
    parts = re.split(r"\$\([^)]*\)|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\d+", msg)
    rx = ".*".join(re.escape(p) for p in parts if p != "")
    return re.compile(rx if rx else r"(?!x)x")   # no literals, matches nothing


def never_fired(declared, fired):
    """The `bad`s that no observed ✗ line satisfies."""
    out = []
    for msg in sorted(declared):
        pat = _as_pattern(msg)
        if any(pat.search(f) for f in fired):
            continue
        lit = _longest_literal(msg)
        if lit and any(lit in f for f in fired):
            continue
        out.append(msg)
    return out


def _key(msg):
    """The shape an entry is compared by.

    The file is markdown and entries sit between backticks, so a message that
    CARRIES backticks cannot be written verbatim — they become single quotes.
    Read back, it no longer matches the declared one, and seven entries showed
    up at once as "new" and as "already measurable": the ledger contradicted
    itself. Both sides compare through this key.
    """
    return msg.replace("`", "'").replace("\\", "").strip()


def read_ledger(path):
    if not os.path.exists(path):
        return None
    entries = set()
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^- \[( |x)\] `(.+?)`\s*$", line.rstrip())
        if m:
            entries.add(_key(m.group(2)))
    return entries


def render(entries, previous_reasons, faults, shards):
    lines = [HEAD, "<!-- %d fault(s) across %d shard(s) -->\n" % (faults, shards)]
    for msg in sorted(entries):
        lines.append("- [ ] `%s`\n" % _key(msg))
        reason = previous_reasons.get(_key(msg))
        lines.append("      %s\n" % (reason or "**Unjustified.** Write it a fault in "
                                               "`scripts/mutate.py`, or say here why it has "
                                               "none."))
    return "".join(lines)


def reasons_from(path):
    out, current = {}, None
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^- \[( |x)\] `(.+?)`\s*$", line.rstrip())
        if m:
            current = m.group(2)
        elif current and line.startswith("      "):
            out[_key(current)] = line.strip()
            current = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True, help="directory holding the kill-map-*.json")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--write", action="store_true", help="regenerate instead of comparing")
    args = ap.parse_args()

    suite = open(SUITE, encoding="utf-8").read()
    declared = declared_bads(suite)
    fired, faults, shards = fired_from(args.parts)
    dead = set(never_fired(declared, fired))

    with open("kill-map-merged.json", "w", encoding="utf-8") as fh:
        json.dump({"declared": len(declared), "fired": sorted(fired),
                   "never_fired": sorted(dead), "faults": faults, "shards": shards},
                  fh, indent=2)

    print("%d of %d `bad`s fired under some fault; %d did not."
          % (len(declared) - len(dead), len(declared), len(dead)))

    if args.write:
        os.makedirs(os.path.dirname(args.ledger) or ".", exist_ok=True)
        with open(args.ledger, "w", encoding="utf-8") as fh:
            fh.write(render(dead, reasons_from(args.ledger), faults, shards))
        print("wrote %s with %d entry(ies)" % (args.ledger, len(dead)))
        return 0

    known = read_ledger(args.ledger)
    if known is None:
        print("\n%s does not exist. Generate it with --write and justify every line." % args.ledger,
              file=sys.stderr)
        return 1

    keyed = {_key(m): m for m in dead}
    new = sorted(keyed[k] for k in set(keyed) - known)
    gone = sorted(known - set(keyed))
    if not new and not gone:
        print("the ledger describes the suite: %d entry(ies)." % len(known))
        return 0
    if new:
        print("\n%d check(s) no fault provokes and the ledger does not carry. Write them "
              "a fault, or the reason:" % len(new), file=sys.stderr)
        for m in new:
            print("  + %s" % m[:110], file=sys.stderr)
    if gone:
        print("\n%d ledger entry(ies) that CAN be measured now. Take them out:" % len(gone),
              file=sys.stderr)
        for m in gone:
            print("  - %s" % m[:110], file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
