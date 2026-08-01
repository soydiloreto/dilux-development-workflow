#!/usr/bin/env python3
"""ddw-validate-spec, the mechanical half — run by the skill, never re-derived.

Why a script, when the skill already printed a box: because a box a model renders
is a box a model can compress. It happened in a live run — nineteen rules, a
PASSED verdict, and two lines of chat with the rule names squeezed out. Nothing
lied; the reader simply never saw what was checked.

`validate_prd.py` answered that for the PRD and left the spec where it started:
the largest rule family in the catalog (F-SPEC-01…16, W-SPEC-01…03) judged
entirely by the model, with no artifact on disk and nothing binding the verdict
to the bytes that earned it. This file closes that gap the same way, so the two
read alike and the `spec` gate can rest on a receipt instead of a boolean.

What stays with the model is what a parser cannot honestly answer: whether the
design CONTRADICTS the PRD (F-SPEC-12) and whether the terminology DIVERGES from
it (F-SPEC-13). Both are printed as MANUAL lines so their absence is visible
rather than silent — the same contract validate_prd.py uses.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §2 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import hashlib
import os
import re
import sys

# A block opens with `## Block N — name`; a fix-plan's unit is a numbered step
# under `## Solution — steps`. Both are what the create-spec templates emit.
BLOCK_HEAD = re.compile(r"^##\s+Block\s+(\d+)\s*[—\-:]?\s*(.*)$", re.MULTILINE)

# The template labels every part of a block in bold. Parsing on the label rather
# than on position is what lets a spec add prose without the parser losing the
# thread.
LABELS = ("Files", "Logic", "API contract", "Data model", "Input validation",
          "Error handling", "Required tests", "Completion criterion")

# Vocabulary, in both languages the templates are written in. A spec written in
# Spanish is not a spec with no error handling, and a matcher that only knows
# English says it is.
ENDPOINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+/|endpoint|ruta\s+http", re.IGNORECASE)
SCHEMA = re.compile(r"\b(schema|esquema|migration|migraci[oó]n|table|tabla|entity|entidad|"
                    r"model[oa]?s?|column|columna)\b", re.IGNORECASE)
CONSTRAINT = re.compile(r"\b(nullable|unique|[uú]nico|foreign key|fk|primary key|pk|default|"
                        r"index|[ií]ndice|not null|no nulo|check)\b", re.IGNORECASE)
INPUT_SURFACE = re.compile(r"\b(input|entrada|form|formulario|request body|payload|par[aá]metros|"
                           r"params|query string|upload|campo del usuario)\b", re.IGNORECASE)
SAD_PATH = re.compile(r"\b(invalid|inv[aá]lid[oa]|error|fail|falla|fallo|missing|faltante|"
                      r"reject|rechaz|duplicate|duplicad|unauthor|no autorizado|forbidden|"
                      r"prohibido|timeout|conflict|conflicto|sad path|camino triste|"
                      r"400|401|403|404|409|422|429|500)\b", re.IGNORECASE)
REGRESSION = re.compile(r"\bregression|regresi[oó]n\b", re.IGNORECASE)
ROLLBACK = re.compile(r"\brollback|revert|reversa|reverse migration|migraci[oó]n inversa\b",
                      re.IGNORECASE)


def _section_body(text, names):
    """The body under a `##`/`###` heading whose title starts with one of `names`."""
    body, inside = [], False
    for ln in text.splitlines():
        m = re.match(r"\s*(#{2,4})\s+(.*)$", ln)
        if m:
            title = m.group(2).strip().lower()
            inside = any(title.startswith(n) or n in title for n in names)
            continue
        if inside:
            body.append(ln)
    return "\n".join(body).strip()


def _blocks(text):
    """Every `## Block N` with its body, as (label, body)."""
    heads = list(BLOCK_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        name = (m.group(2) or "").strip()
        label = f"Block {m.group(1)}" + (f" ({name})" if name else "")
        out.append((label, text[m.end():end]))
    return out


def _part(block_body, label):
    """A bold-labelled part of a block, up to the next bold label or the end.

    Returns "" when the label is absent, which is what every completeness rule
    below is really asking about.
    """
    m = re.search(r"^\s*\*\*" + re.escape(label) + r"\*\*.*$", block_body,
                  re.MULTILINE | re.IGNORECASE)
    if not m:
        return ""
    rest = block_body[m.end():]
    nxt = re.search(r"^\s*\*\*(?:" + "|".join(re.escape(x) for x in LABELS) + r")\*\*",
                    rest, re.MULTILINE | re.IGNORECASE)
    return (rest[:nxt.start()] if nxt else rest).strip()


def _bullets(body):
    """Bullet items, with the template's placeholder rows dropped.

    A spec that still carries `- [test name] — validates AC-xx` has not been
    written, it has been copied, and counting the placeholder as content is how
    an empty block passes a completeness check.
    """
    out = []
    for ln in body.splitlines():
        m = re.match(r"\s*(?:[-*]|\d+\.)\s+(?:\[[ x]\]\s*)?(.+)$", ln)
        if not m:
            continue
        item = m.group(1).strip()
        if re.fullmatch(r"\[.*\]", item):      # a bare placeholder, nothing else
            continue
        if item:
            out.append(item)
    return out


def _repo_relative(path):
    """The path as the reader will type it: anchored at the repo, not at
    whatever directory the validator happened to be invoked from.

    `os.path.relpath` against the cwd produced `../../../../tmp/...` — a correct
    path nobody can use as a link, which is the whole point of printing it.
    """
    ab = os.path.abspath(path)
    idx = ab.rfind(os.sep + "docs" + os.sep)
    if idx > 0:
        return ab[idx + 1:]
    try:
        rel = os.path.relpath(ab)
        return rel if not rel.startswith(os.pardir) else ab
    except ValueError:
        return ab


def _prd_ids(prd_text, prefix):
    """IDs of the given prefix that OPEN a bullet in the PRD — same rule as
    validate_prd.py, so the two scripts count the same requirements."""
    ids = []
    for ln in prd_text.splitlines():
        m = re.match(r"\s*[-*]\s+\**(" + prefix + r"-\d+)\**\s*[:.(]", ln)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _find_prd(spec_path, spec_text, explicit):
    """The PRD this spec answers to: the flag, else the header table, else the
    conventional path for the ticket named in the filename."""
    if explicit:
        return explicit
    m = re.search(r"^\|\s*PRD\s*\|\s*([^|]+?)\s*\|", spec_text, re.MULTILINE | re.IGNORECASE)
    root = os.path.dirname(os.path.abspath(spec_path))
    if m:
        cand = m.group(1).strip().strip("`")
        for base in (os.getcwd(), os.path.abspath(os.path.join(root, "..", "..", ".."))):
            p = cand if os.path.isabs(cand) else os.path.join(base, cand)
            if os.path.exists(p):
                return p
    m = re.match(r"(?:spec|fix)-(.+)\.md$", os.path.basename(spec_path))
    if m:
        p = os.path.join(root, "..", "prd", "prd-%s.md" % m.group(1))
        if os.path.exists(p):
            return os.path.normpath(p)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--tier", default="FEATURE")
    ap.add_argument("--prd", default=None,
                    help="the PRD to check coverage against; found from the spec if omitted")
    args = ap.parse_args()
    try:
        text = open(args.spec, encoding="utf-8").read()
    except OSError as exc:
        print(f"validate_spec: cannot read {args.spec}: {exc}", file=sys.stderr)
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

    # QUICK-FIX has no PLAN phase, so it has no spec to validate. Saying so and
    # exiting 3 is not the same as passing: a run that produced no verdict must
    # not leave a receipt behind.
    if args.tier == "QUICK-FIX":
        print("validate_spec: tier QUICK-FIX has no PLAN phase and therefore no spec "
              "(catalog §Tier Modifier). Nothing to validate.", file=sys.stderr)
        sys.exit(3)

    is_fix = args.tier == "FIX"
    units = _blocks(text)
    if is_fix and not units:
        # A fix-plan's unit is the whole document: the template gives it one
        # Solution section rather than numbered blocks.
        units = [("Fix-plan", text)]

    # ── PRD → spec coverage (F-SPEC-01/02/03) ────────────────────────────────
    prd_path = _find_prd(args.spec, text, args.prd)
    prd_text = ""
    if prd_path:
        try:
            prd_text = open(prd_path, encoding="utf-8").read()
        except OSError:
            prd_text = ""

    if is_fix:
        # The catalog scopes §2.1 to FEATURE: a fix-plan answers to an RCA, not
        # to a PRD's FR/NFR/AC. Demanding a PRD here failed every fix-plan for
        # the absence of a document its tier does not produce.
        rows.append("  ·  F-SPEC-01/02/03 do not apply to FIX (no PRD; the plan answers to the RCA)")
    elif not prd_text:
        # Reporting the three as unchecked is the honest move. Silently skipping
        # them is how a spec covering nothing passes coverage.
        fail("F-SPEC-01/02/03", "the PRD could not be read, so coverage was NOT checked. "
                                "Pass --prd <path> and run again")
    else:
        frs, nfrs, acs = (_prd_ids(prd_text, p) for p in ("FR", "NFR", "AC"))

        uncovered = [i for i in frs if not re.search(r"\b%s\b" % i, text)]
        if uncovered:
            fail("F-SPEC-01", f"FR from the PRD covered by no block: {', '.join(uncovered)}")
        else:
            ok("F-SPEC-01", f"all {len(frs)} FR from the PRD are referenced by a block")

        tests_text = " ".join(_part(b, "Required tests") for _, b in units) or text
        untested = [i for i in acs if not re.search(r"\b%s\b" % i, tests_text)]
        if untested:
            fail("F-SPEC-02", f"AC from the PRD named by no test: {', '.join(untested)}")
        else:
            ok("F-SPEC-02", f"all {len(acs)} AC from the PRD are named by at least one test")

        # A strategy is prose, not a mention: an NFR listed with nothing beside
        # it is the row that made this rule necessary.
        strategyless = []
        for i in nfrs:
            lines = [ln for ln in text.splitlines() if re.search(r"\b%s\b" % i, ln)]
            if not lines or max(len(re.sub(r"\b%s\b" % i, "", ln).strip(" |-—:")) for ln in lines) < 20:
                strategyless.append(i)
        if strategyless:
            fail("F-SPEC-03", f"NFR with no documented technical strategy: {', '.join(strategyless)}")
        else:
            ok("F-SPEC-03", f"all {len(nfrs)} NFR carry a technical strategy")

    # ── Per-unit completeness (F-SPEC-04/05/06/07/08/09/10/16, W-SPEC-01/02) ──
    if not units:
        fail("F-SPEC-04", "the spec declares no block: nothing here is actionable")
    else:
        # Informational, deliberately not a ✅: STRUCTURE is not a rule in the
        # catalog, and a row that counts toward "passed" while answering to no
        # rule ID is how a checklist starts inflating itself.
        rows.append(f"  ·  {len(units)} {'step group' if is_fix else 'block'}(s) found")

    no_files, no_criterion, no_tests, no_errors = [], [], [], []
    bad_api, bad_model, no_input_rules, untested_errors = [], [], [], []
    no_fr, oversized = [], []

    for label, body in units:
        files = _bullets(_part(body, "Files"))
        if is_fix and not files:
            files = _bullets(_part(body, "Solution")) or _bullets(
                _section_body(body, ("solution", "soluci")))
        tests = _bullets(_part(body, "Required tests"))
        if is_fix and not tests:
            tests = _bullets(_section_body(body, ("tests", "pruebas")))
        errors = _bullets(_part(body, "Error handling")) or _bullets(
            _section_body(body, ("error handling", "manejo de errores")))
        criterion = _part(body, "Completion criterion")

        if not any(("/" in f or "`" in f or re.search(r"\.\w{1,5}\b", f)) for f in files):
            no_files.append(label)
        if not criterion and not is_fix:
            no_criterion.append(label)
        if not tests:
            no_tests.append(label)
        if not errors:
            no_errors.append(label)

        # What this unit BUILDS, which is where an endpoint, a schema or an input
        # surface is actually introduced. Matching the whole body instead read
        # the rollback note "no toca el esquema" as a schema change and failed a
        # fix-plan for having no data model — a false FAIL, which costs more
        # than the rule saves.
        surface = _part(body, "Files") + "\n" + _part(body, "Logic")
        if is_fix and not surface.strip():
            surface = _part(body, "Solution") or _section_body(body, ("solution", "soluci"))

        api = _part(body, "API contract")
        if api:
            missing = [k for k, pat in (
                ("method+path", r"(GET|POST|PUT|PATCH|DELETE)\b|m[eé]todo|method"),
                ("request", r"request|petici[oó]n|body|par[aá]metros"),
                ("response", r"response|respuesta"),
                ("error codes", r"error|c[oó]digo"),
                ("auth", r"auth|autenticaci|autorizaci"),
            ) if not re.search(pat, api, re.IGNORECASE)]
            if missing:
                bad_api.append(f"{label} (missing {', '.join(missing)})")
        elif ENDPOINT.search(surface):
            bad_api.append(f"{label} (an endpoint with no API contract section)")

        model = _part(body, "Data model")
        if model:
            if not CONSTRAINT.search(model):
                bad_model.append(f"{label} (fields with no constraints)")
        elif SCHEMA.search(surface):
            bad_model.append(f"{label} (touches a schema with no Data model section)")

        if INPUT_SURFACE.search(surface) and not _part(body, "Input validation"):
            no_input_rules.append(label)

        # F-SPEC-16: the errors this block wrote down against the tests that
        # name one. Counting is the rule's own wording, and it is the version a
        # parser can defend — which of the two lists a given test belongs to is
        # a judgement, how many there are is not.
        sad = [t for t in tests if SAD_PATH.search(t)]
        if errors and len(sad) < len(errors):
            untested_errors.append(f"{label} ({len(errors)} error(s), {len(sad)} test(s) naming one)")

        # W-SPEC-01 is PRD→spec traceability, and a fix-plan answers to an RCA
        # rather than to FRs. Warning about it there is noise the reader learns
        # to skip, which is how a real warning goes unread.
        if not is_fix and not re.search(r"\bFR-\d+\b", body):
            no_fr.append(label)
        if len(files) > 5 or len(body.split()) > 500:
            oversized.append(f"{label} ({len(files)} files, {len(body.split())} words)")

    def verdict(rule, bad, ok_msg, bad_msg):
        if bad:
            fail(rule, f"{bad_msg}: {', '.join(bad)}")
        else:
            ok(rule, ok_msg)

    verdict("F-SPEC-04", no_files, "every block lists the files it creates or modifies",
            "block with no file list")
    if not is_fix:
        verdict("F-SPEC-05", no_criterion, "every block has a verifiable completion criterion",
                "block with no completion criterion")
    verdict("F-SPEC-06", no_tests, "every block lists at least one required test",
            "block with no tests")
    verdict("F-SPEC-07", bad_api, "every endpoint carries a complete contract",
            "incomplete API contract")
    verdict("F-SPEC-08", bad_model, "every schema declares its constraints",
            "data model with no constraints")
    verdict("F-SPEC-09", no_input_rules, "every block taking input documents its validation",
            "input with no documented validation")
    verdict("F-SPEC-10", no_errors, "every block documents its error handling",
            "block with no error handling")
    verdict("F-SPEC-16", untested_errors, "every documented error is named by a test",
            "documented error that appears in no test")

    # F-SPEC-11: the ordering, once, for the whole document.
    deps = _section_body(text, ("dependencies", "dependencias"))
    if deps:
        ok("F-SPEC-11", "dependencies between blocks are declared")
    else:
        fail("F-SPEC-11", "no dependencies section: the execution order is undeclared")

    if is_fix:
        pool = " ".join(_part(b, "Required tests") + " " + b for _, b in units)
        if REGRESSION.search(pool):
            ok("F-SPEC-14", "the fix-plan declares a regression test")
        else:
            fail("F-SPEC-14", "no regression test: this bug has nothing stopping it from returning")
        rb = _section_body(text, ("rollback", "plan de rollback", "reversa"))
        if rb:
            ok("F-SPEC-15", "the fix-plan has a rollback plan")
        else:
            fail("F-SPEC-15", "no rollback plan (mandatory for FIX, even to say reverting is trivial)")

    if no_fr:
        warn("W-SPEC-01", f"block referencing no FR — enabler or gold-plating?: {', '.join(no_fr)}")
    if oversized:
        warn("W-SPEC-02", f"large block, consider splitting: {', '.join(oversized)}")
    if not is_fix and SCHEMA.search(text) and not ROLLBACK.search(text):
        warn("W-SPEC-03", "schema changes with no rollback or reverse-migration consideration")

    rows.append("  👁  F-SPEC-12 (contradicts the PRD) and F-SPEC-13 (terminology diverging from")
    rows.append("      the PRD) are MANUAL: judge them and say so explicitly in your report.")

    result = "PASSED" if fails == 0 else f"FAILED ({fails} FAIL{'S' if fails > 1 else ''})"
    report = [f"/ddw-validate-spec {args.spec} — {result}", "─" * 64]
    report += rows
    report.append("─" * 64)
    passed = sum(1 for r in rows if r.strip().startswith("✅"))
    tail = [f"Total: {passed} passed, {fails} failed, {warns} warnings",
            f"Result: {result}"]
    for line in report + tail:
        print(line)

    # The report is an ARTIFACT, not narration — same reasoning as the PRD's.
    # Persisted, the checklist exists whether or not the model pastes it, and
    # the approval the user gives can point at a file instead of a claim.
    report_path = None
    try:
        report_path = re.sub(r"\.md$", "", os.path.abspath(args.spec)) + ".validation.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(report + tail) + "\n```\n")
        print(f"Report: {_repo_relative(report_path)}")
    except OSError:
        report_path = None

    if fails == 0:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        spec_abs = os.path.abspath(args.spec)
        idx = spec_abs.rfind(os.sep + "docs" + os.sep)
        root = spec_abs[:idx] if idx > 0 else os.getcwd()
        sess = os.path.join(root, ".ddw-sessions")
        os.makedirs(sess, exist_ok=True)
        with open(os.path.join(sess, f"spec-validated-{digest}"), "w", encoding="utf-8") as fh:
            fh.write(os.path.basename(spec_abs) + "\n")
        print(f"Receipt: .ddw-sessions/spec-validated-{digest}")
    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
