#!/usr/bin/env python3
"""Writing a validation receipt, in one place.

Six validators each had their own copy of "hash the text, write
`.ddw-sessions/<prefix>-validated-<digest>`, print the path". Six copies of one
rule is how the rule drifts, and it is the shape this project keeps finding.

What is new here is the second half. The receipt is a file, and a file can be
written by anything that can write files — `printf > .ddw-sessions/prd-validated-
abc123` forges one in a single shell command. The pre-write hook refuses that
path through a tool, but a shell is not a tool call with a path in it
(`docs/RATIONALE.md` decision 11 is honest that the shell is detected rather than
prevented). So the validator that writes a receipt also records THAT IT DID, in
the append-only journal the hook keeps — and the gate then asks for both. A
forged receipt with no journal line is a receipt nobody's validator wrote.

This does not make forgery impossible: both files can be written by the same
shell. It makes it take two coordinated writes instead of one, and it leaves the
second one in a record that survives deleting the state. Stated plainly rather
than implied, because a guarantee whose scope is unstated gets read as total.
"""
import hashlib
import json
import os

JOURNAL = ".ddw-journal.jsonl"
SESSIONS = ".ddw-sessions"


def _tiers():
    """The tiers that exist, read from the graph that defines them.

    Every validator takes `--tier` and none of them constrained it, so any string
    at all was accepted — and since the tier selects which rules run, `--tier
    QUICK-FIX` on a FEATURE's document was a way to be judged by a shorter set of
    rules and get a receipt for it. Constraining the flag is half of closing
    that; the other half is the gate comparing the receipt's tier to the state's.

    Read from the graph rather than typed here, so a tier added there is
    accepted here without anyone remembering to. Falls back to the four that
    exist today if the graph cannot be read: a validator that cannot find the
    graph must still be able to validate a document.
    """
    graph = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         os.pardir, "rules", "transition-graph.json")
    try:
        with open(graph, encoding="utf-8") as fh:
            names = sorted(json.load(fh).get("tiers", {}))
        if names:
            return tuple(names)
    except (OSError, ValueError, AttributeError):
        pass
    return ("DISCOVERY", "FEATURE", "FIX", "QUICK-FIX")


TIERS = _tiers()



FAMILY_MAP_NAMES = ("ddw-family.md", "familia.md")


def find_family_map(start, limit=6):
    """The family map at or above `start`: `ddw-family.md`, or the deprecated
    `familia.md` (still read so existing families keep working; anything that
    CREATES a map writes the new name)."""
    for name in FAMILY_MAP_NAMES:
        p = find_upward(start, name, limit)
        if p:
            return p
    return None


def family_map_in(root):
    """The family map directly inside `root`, preferring the new name."""
    for name in FAMILY_MAP_NAMES:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            return p
    return None


def find_upward(start, name, limit=6):
    """The nearest `name` walking up from `start`'s directory; None past `limit` levels.

    Reports live under docs/ddw/reports/, so the project root is a few levels
    up. Bounded, because an unbounded walk from /tmp finds someone else's file.
    """
    d = os.path.dirname(os.path.abspath(start))
    for _ in range(limit):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def repo_root(artifact_path):
    """The repository the artifact belongs to, from its own path.

    Every phase artifact lives under `docs/ddw/…`, so the segment before `docs/`
    is the root. Falls back to the working directory, which is what the
    validators did individually.
    """
    ab = os.path.abspath(artifact_path)
    idx = ab.rfind(os.sep + "docs" + os.sep)
    return ab[:idx] if idx > 0 else os.getcwd()


def digest_of(text):
    """The receipt's key: the artifact's CURRENT bytes, read as text.

    Text, not bytes, and the gate reads it the same way — the two disagreeing on
    `\\r\\n` alone made a Windows-authored report hash one way for the validator
    and another for the gate, and the refusal said "validate it again", which was
    a loop with no exit.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write(artifact_path, prefix, text, tier=None, asof=None):
    """Write the receipt for `artifact_path` and record having written it.

    Returns the receipt's name, so the caller can print it.

    The receipt records WHICH RULES the document was judged under. Every
    validator takes `--tier`, and the tier decides which rules run: the same
    bytes that FAIL as a FEATURE PASS as a QUICK-FIX. Nothing recorded which one
    had been asked for, and the receipt's name is a digest of the content alone,
    so the two runs produced byte-identical receipts. Anyone could validate a
    FEATURE's PRD under QUICK-FIX rules, and the gate — which knows the state's
    tier perfectly well — had nothing to compare it to.

    A receipt with no tier line is one written before this existed, and it is
    still honoured; the gate only refuses a tier that is present and wrong.

    `asof` is the same argument for a different variable: the CLOCK. SAST
    suppressions expire, `validate_sast.py --today` lets the caller say which
    day to age them against, and nothing recorded the answer — so a report whose
    suppressions lapsed months ago passed under `--today 2025-02-01` and left a
    receipt indistinguishable from one earned this morning. Recorded here, the
    gate can ask; unrecorded, there was nothing to ask.
    """
    root = repo_root(artifact_path)
    name = "%s-validated-%s" % (prefix, digest_of(text))
    sess = os.path.join(root, SESSIONS)
    os.makedirs(sess, exist_ok=True)
    filename = os.path.basename(os.path.abspath(artifact_path))
    with open(os.path.join(sess, name), "w", encoding="utf-8") as fh:
        fh.write(filename + "\n")
        if tier:
            fh.write("tier: %s\n" % tier)
        if asof:
            fh.write("asof: %s\n" % asof)
    # Best effort, like every other write to the journal: a record that cannot be
    # kept must not stop a validation that passed. It costs the extra guarantee,
    # not the run.
    try:
        record = {"record": "receipt", "name": name, "file": filename}
        if tier:
            record["tier"] = tier
        if asof:
            record["asof"] = asof
        line = json.dumps(record, sort_keys=True)
        with open(os.path.join(root, JOURNAL), "a+", encoding="utf-8") as fh:
            # Re-validating unchanged bytes is legitimate and common — the same
            # digest, the same record. Twice in a row is noise the audit then
            # has to explain (measured: lines 48/49 of a live journal, identical
            # and consecutive, one validator run). Skip only the exact repeat of
            # the LAST line: a later re-validation after other records is a real
            # event and stays.
            fh.seek(0)
            tail = ""
            for tail in fh:
                pass
            if tail.strip() != line:
                fh.write(line + "\n")
    except OSError:
        pass
    return name
