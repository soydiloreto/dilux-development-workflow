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


def write(artifact_path, prefix, text):
    """Write the receipt for `artifact_path` and record having written it.

    Returns the receipt's name, so the caller can print it.
    """
    root = repo_root(artifact_path)
    name = "%s-validated-%s" % (prefix, digest_of(text))
    sess = os.path.join(root, SESSIONS)
    os.makedirs(sess, exist_ok=True)
    filename = os.path.basename(os.path.abspath(artifact_path))
    with open(os.path.join(sess, name), "w", encoding="utf-8") as fh:
        fh.write(filename + "\n")
    # Best effort, like every other write to the journal: a record that cannot be
    # kept must not stop a validation that passed. It costs the extra guarantee,
    # not the run.
    try:
        with open(os.path.join(root, JOURNAL), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"record": "receipt", "name": name, "file": filename},
                                sort_keys=True) + "\n")
    except OSError:
        pass
    return name
