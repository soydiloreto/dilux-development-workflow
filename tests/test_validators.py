"""The validators and the session boot, asked directly.

Sibling of `test_validate_transition.py` and with the same limited scope: this
does NOT replace `scripts/verify_install.sh`, which installs into a real repo,
sends a real event to a real hook and reads the verdict the tool would read.
What it proves is that the rules say what they mean, which is the half that
costs nothing to ask often.

Everything in this file came out of the same place: running the suite under
`coverage` with `COVERAGE_PROCESS_START` — which also measures subprocesses,
and the validators and the hooks ARE subprocesses — and looking at which lines
never execute once. They are enforcement rules, not error branches: a warning
that the installed enforcement is no longer what was installed, and the expiry
of the security report that opens a gate.
"""
import datetime
import importlib.util
import re
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boot = _load("boot", "ddw/scripts/session-boot.py")


# ── The installed enforcement stopped being what was installed ───────────────

@pytest.fixture()
def installed(tmp_path):
    """A repo with a manifest and with the files the manifest names."""
    repo = tmp_path / "r"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    hook = repo / ".claude" / "hooks" / "enforce.sh"
    hook.write_text("#!/usr/bin/env bash\nexit 0\n")
    digest = subprocess.run(["sha256sum", str(hook)], capture_output=True, text=True
                            ).stdout.split()[0]
    (repo / ".ddw-installed.json").write_text(
        json.dumps({"claude:.claude/hooks/enforce.sh": digest}))
    return repo


def test_a_repo_whose_installed_files_match_says_nothing(installed):
    assert boot.enforcement_drift(str(installed)) == [], \
        "an intact repo warns of a drift it does not have, and a warning that always fires is never read"


def test_a_hook_deleted_from_a_shell_is_reported_as_missing(installed):
    """The hooks refuse to write these files, so a change here came from
    outside the session. It is the only warning there is that the pipeline
    stopped being imposed — without it, the repo looks governed and is not."""
    os.remove(installed / ".claude" / "hooks" / "enforce.sh")
    lines = boot.enforcement_drift(str(installed))
    assert lines, "a hook deleted from the repo produced no warning"
    blob = "\n".join(lines)
    assert "MISSING" in blob and "enforce.sh" in blob, \
        f"the warning does not say what is missing: {blob[:200]}"
    assert "install.sh" in blob, f"the warning does not say how to repair it: {blob[:200]}"


def test_a_hook_edited_from_a_shell_is_reported_as_changed(installed):
    (installed / ".claude" / "hooks" / "enforce.sh").write_text("#!/usr/bin/env bash\nexit 0  # :)\n")
    blob = "\n".join(boot.enforcement_drift(str(installed)))
    assert "CHANGED" in blob and "enforce.sh" in blob, \
        f"a hook rewritten from outside the session went unnoticed: {blob[:200]}"


# ── A stale security report does not open the gate ───────────────────────────

def _template():
    """The report the skill tells the model to write, verbatim.

    Written by hand here, this file would be a second copy of the document's
    shape, and the second copy always falls behind: the defect that has
    bitten this repo the most times is a template and a gate that stopped
    agreeing. It is read from the skill so they cannot.
    """
    skill = open(os.path.join(ROOT, "skills/ddw-security-sast/SKILL.md"),
                 encoding="utf-8").read()
    at = skill.index("### The report, in the shape the validator reads")
    m = re.search(r"```markdown\n(.*?)```", skill[at:], re.S)
    assert m, "the SAST skill no longer carries the example report under that heading"
    return m.group(1).replace("{ticket}", "T-1")


def _with(body, suppression):
    """The report with ONE suppression where the template says `None.`

    Cutting at `## Suppressions` and keeping what is above also takes the
    `Total:` and `Result:` lines that come after, and without them the
    validator refuses NOTHING — so the fresh-suppression test passed without
    there being any suppression to judge. A test that passes for measuring
    nothing is the same family as a check that cannot fail.
    """
    out = body.replace("## Suppressions\nNone.\n", "## Suppressions\n" + suppression, 1)
    assert out != body, "the template no longer says `## Suppressions` followed by `None.`"
    return out


def _suppression(written, review):
    """The suppression block in the shape the rule documents, read from the
    rule — not written here.

    §4.4 of `validation-rules.instructions.md` carries the only worked
    example there is: the SAST skill teaches "the 7-field format" by
    reference and never shows it. Copying the shape by hand into this file
    would be a third version of the same thing, and whichever falls behind
    decides in silence.
    """
    rules = open(os.path.join(ROOT, "ddw/rules/validation-rules.instructions.md"),
                 encoding="utf-8").read()
    at = rules.index("### 4.4 Finding Suppression Protocol")
    m = re.search(r"```markdown\n(.*?)```", rules[at:], re.S)
    assert m, "§4.4 no longer carries the example suppression block"
    block = m.group(1)
    filled = {
        "[finding ID]": "S-01", "[path:line]": "tests/fixtures/key.pem:1",
        "[finding category]": "F-SAST-14",
        "FALSE_POSITIVE / ACCEPTED_RISK": "FALSE_POSITIVE",
        "[name of the user who reviewed it]": "Pablo Di Loreto",
        "[review date]": written,
        "[1\u20133 sentences explaining why it is not exploitable, or why it is accepted]":
            "The fixture holds a key generated for the test suite and used nowhere else.",
        "[ACCEPTED_RISK only: which other control mitigates the risk]": "n/a",
        "[latest date to re-evaluate, at most 6 months out]": review,
    }
    for hole, value in filled.items():
        block = block.replace(hole, value)
    assert "[" not in block.replace("[path:line]", ""), \
        "an unfilled placeholder was left in the block: " + block
    return block


def _sast(tmp_path, body, ticket="T-1", expect_suppression=False):
    path = tmp_path / f"sast-{ticket}.md"
    path.write_text(body, encoding="utf-8")
    r = subprocess.run(["python3", os.path.join(ROOT, "ddw/scripts/validate_sast.py"),
                        str(path), "--tier", "FEATURE"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    # That the block was PARSED, before reading anything about it. The
    # validator has a way of saying "there was no suppression to age", and
    # against that output any assertion about suppressions passes without
    # having judged a single one. It already happened to me with this very
    # file: the block came in with bullets where the rule asks for table
    # rows, the validator saw nothing, and the fresh-suppression test went
    # green.
    if expect_suppression:
        assert "no suppressions to age" not in r.stdout, \
            "the validator saw no suppression, so nothing that follows judged one"
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


def test_a_suppression_written_within_six_months_passes(tmp_path):
    fresh = datetime.date.today() - datetime.timedelta(days=30)
    ahead = datetime.date.today() + datetime.timedelta(days=120)
    _, refused = _sast(tmp_path, _with(_template(), _suppression(fresh.isoformat(), ahead.isoformat())),
                        expect_suppression=True)
    assert not any("F-SAST-19" in ln for ln in refused), \
        "a month-old suppression was refused as stale: " + "\n".join(refused)


def test_a_suppression_older_than_six_months_is_refused_however_its_review_date_reads(tmp_path):
    """The rule is about AGE, and `Date` was read only to see if it was empty.
    A suppression written two years ago with a review date in the future
    passed both rules while being old — and a suppression is exactly the
    place where someone decided a security finding does not matter."""
    old = datetime.date.today() - datetime.timedelta(days=400)
    ahead = datetime.date.today() + datetime.timedelta(days=365)
    _, refused = _sast(tmp_path, _with(_template(), _suppression(old.isoformat(), ahead.isoformat())),
                        expect_suppression=True)
    assert any("F-SAST-19" in ln for ln in refused), \
        ("a suppression over a year old passed because its review date is in the "
         "future: " + ("\n".join(refused) or "no refusals at all"))
    assert any("six months" in ln or "over six" in ln for ln in refused), \
        "the refusal does not say why: " + "\n".join(refused)


def test_the_report_the_skill_teaches_passes_as_written(tmp_path):
    """Without this, everything above measures against a document that was
    already invalid for another reason, and "F-SAST-19 did not fire" would
    mean nothing."""
    r, refused = _sast(tmp_path, _template())
    assert r.returncode == 0 and not refused, \
        "the report ddw-security-sast tells the model to write is refused: " + \
        ("\n".join(refused) or r.stderr[-200:])


# ── The rules that decide whether an empty document earns a gate ─────────────
#
# Eight of these survived the suite's 554 checks. None of the rules they name
# (F-TM-05, F-TM-06, F-TEST-05, F-TEST-06, F-SPEC-10, F-SPEC-11) appeared a
# single time in `verify_install.sh`: they exist in the catalog, they are
# implemented, and nothing proved they could fire.
#
# Every test does the same thing, in this order: checks that the HEALTHY
# document passes, plants ONE violation, and demands the ❌ with its ID. The
# first step is not ceremony — without it, a document already invalid for
# another reason would pass the test without the rule in question having said
# anything.

def _worked(skill, heading, ticket="T-1"):
    text = open(os.path.join(ROOT, "skills", skill, "SKILL.md"), encoding="utf-8").read()
    at = text.index(heading)
    m = re.search(r"```markdown\n(.*?)```", text[at:], re.S)
    assert m, f"{skill} no longer carries a worked document under {heading!r}"
    return m.group(1).replace("{ticket}", ticket)


def _validate(tmp_path, validator, name, body, *extra):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    r = subprocess.run(["python3", os.path.join(ROOT, "ddw/scripts", validator),
                        str(path), "--tier", "FEATURE", *extra],
                       capture_output=True, text=True, cwd=str(tmp_path))
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


def _refuses(refused, rule):
    return any(rule in ln for ln in refused)


# ── The ledger that records why a check cannot fail ──────────────────────────

def test_regenerar_el_ledger_conserva_la_razon_entera(tmp_path):
    """`--write` kept ONE line of each explanation, and the reasons run five
    or six. Regenerating left forty-four excuses cut off mid-sentence, each
    one still excusing its site: green, and without saying why."""
    lkm = _load("lkm", "scripts/lint_kill_map.py")
    ledger = ("# Lint checks that cannot fail\n\n"
              "- [ ] `check_uno[0]`\n"
              "      **Guardia de forma.** Salta cuando el archivo entero\n"
              "      dejó de tener la forma que la tabla promete, que son\n"
              "      todas sus filas a la vez y no una línea.\n"
              "- [ ] `check_dos[1]`\n"
              "      Otra razón, de un solo renglón.\n")
    entera = lkm.existing_reason(ledger, "check_uno[0]")
    assert len(entera.splitlines()) == 3, \
        "the reason would be regenerated truncated: %r" % entera
    assert "todas sus filas" in entera, "the end of the explanation got lost"
    assert "check_dos" not in entera, "the reason swallowed the next item"
    assert lkm.existing_reason(ledger, "check_dos[1]").strip() == "Otra razón, de un solo renglón."
    assert lkm.existing_reason(ledger, "check_tres[0]") == "", \
        "a site with no written reason cannot invent one"


# ── The threat model ─────────────────────────────────────────────────────────

THREAT = "### The threat model, in the shape the validator reads"


def _spec_arg(tmp_path):
    """The threat model is checked AGAINST the real design; without the spec,
    F-TM-06 refuses for not being able to read it and the healthy document
    never passes."""
    path = tmp_path / "spec-T-1.md"
    # The components come out of the worked model itself: a spec written by
    # hand here would name other files, and F-TM-06 — precisely the rule
    # being measured — would refuse the healthy document for not matching it.
    worked = _worked("ddw-threat-modeling", THREAT)
    files = re.findall(r"`([\w./-]+\.\w+)`", worked)
    assert files, "the worked model names no files at all"
    blocks = "".join("## Block %d — %s\n- `%s` — the component\n- POST /api/%d\nCovers FR-0%d.\n\n"
                     % (i, os.path.basename(f), f, i, i)
                     for i, f in enumerate(dict.fromkeys(files), 1))
    path.write_text("# Spec T-1\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n\n" + blocks,
                    encoding="utf-8")
    return "--spec", str(path)


def test_a_threat_model_that_names_nothing_from_its_design_is_refused(tmp_path):
    """F-TM-06. A model that cites not one file, not one endpoint, not one FR
    of its spec is an essay about an imaginary system: it can be impeccable
    and say nothing about this code."""
    base = _worked("ddw-threat-modeling", THREAT)
    r, refused = _validate(tmp_path, "validate_threat.py", "threat-T-1.md", base, *_spec_arg(tmp_path))
    assert r.returncode == 0 and not refused, \
        "the model the skill teaches no longer passes, so the check below measures nothing: " + \
        ("\n".join(refused) or r.stderr[-200:])
    generic = re.sub(r"`[\w./-]+\.(py|ts|js|go|rb)`", "the public API", base)
    assert generic != base, "the probe changed nothing"
    _, refused = _validate(tmp_path, "validate_threat.py", "threat-T-2.md", generic, *_spec_arg(tmp_path))
    assert _refuses(refused, "F-TM-06"), \
        "a model that names nothing from the design earned the gate: " + "\n".join(refused)


def test_a_design_handling_sensitive_data_classifies_it(tmp_path):
    """F-TM-05. Without the table, F-TM-07 says «no PII to encrypt» and the
    document comes out clean: the absence of the classification reads as the
    absence of sensitive data, which is the opposite of what happened."""
    base = _worked("ddw-threat-modeling", THREAT)
    assert "## Data classification" in base, "the worked model no longer carries the table"
    cut = re.split(r"^## Data classification\s*$", base, flags=re.M)[0]
    tail = re.split(r"^## Risks and mitigations\s*$", base, flags=re.M)
    body = cut + "\n## Risks and mitigations\n" + tail[1] if len(tail) > 1 else cut
    assert "email" in body or "password" in body or "token" in body, \
        "without a sensitive word in the rest of the document the rule has nothing to look at"
    _, refused = _validate(tmp_path, "validate_threat.py", "threat-T-3.md", body, *_spec_arg(tmp_path))
    assert _refuses(refused, "F-TM-05"), \
        "a design handling sensitive data passed without classifying any: " + "\n".join(refused)


def test_a_threat_model_written_in_spanish_is_not_told_it_skipped_a_category(tmp_path):
    """The method orders the artifacts written in the user's language, so the
    aliases exist for real documents. Without them, a complete model in
    Spanish is refused over a category it did analyze."""
    base = _worked("ddw-threat-modeling", THREAT)
    es = (base.replace("**Elevation of Privilege:**", "**Elevación de privilegios:**")
              .replace("**Spoofing:**", "**Suplantación:**")
              .replace("**Repudiation:**", "**Repudio:**"))
    assert es != base, "the probe translated no labels"
    r, refused = _validate(tmp_path, "validate_threat.py", "threat-T-4.md", es, *_spec_arg(tmp_path))
    assert not _refuses(refused, "F-TM-01"), \
        "a complete model written in Spanish was reported as incomplete: " + \
        "\n".join(refused)


# ── The test report ──────────────────────────────────────────────────────────

TESTS_DOC = "### The report, in the shape the validator reads"


def test_a_report_cannot_pick_a_floor_it_can_clear(tmp_path):
    """F-TEST-05 + F-TEST-04. The floor is the project's to set; a report that
    cites one lower than the pipeline's minimum and compares itself against
    THAT approves itself. The ⚠️ stays, and a warning stops nothing."""
    base = _worked("ddw-test", TESTS_DOC)
    r, refused = _validate(tmp_path, "validate_tests.py", "tests-T-1.md", base)
    assert r.returncode == 0 and not refused, \
        "the report the skill teaches no longer passes: " + ("\n".join(refused) or r.stderr[-200:])
    low = re.sub(r"^\| Coverage floor \|.*$", "| Coverage floor | 20% (AGENTS.md) |",
                 base, flags=re.M)
    low = re.sub(r"^\| (Line|Branch|Function) coverage \|.*$",
                 lambda m: "| %s coverage | 31%% |" % m.group(1), low, flags=re.M)
    assert low != base, "the probe lowered neither the floor nor the coverage"
    _, refused = _validate(tmp_path, "validate_tests.py", "tests-T-2.md", low)
    assert _refuses(refused, "F-TEST-04"), \
        ("a report with 31% coverage approved itself by choosing a 20% floor: "
         + ("\n".join(refused) or "no refusals at all"))


def test_a_report_that_states_no_floor_is_refused_not_given_one(tmp_path):
    """F-TEST-05. Silently inheriting the flag's default leaves the document
    graded against a number nobody wrote in it."""
    base = _worked("ddw-test", TESTS_DOC)
    nofloor = re.sub(r"^\| Coverage floor \|.*\n", "", base, flags=re.M)
    assert nofloor != base, "the worked report no longer declares a floor"
    _, refused = _validate(tmp_path, "validate_tests.py", "tests-T-3.md", nofloor)
    assert _refuses(refused, "F-TEST-05"), \
        "a report with no floor passed against one DDW invented for it: " + "\n".join(refused)


def test_a_skipped_test_owes_a_reason(tmp_path):
    """F-TEST-06. Skipping is the cheapest way to put a suite in green, and a
    skip without a reason is indistinguishable from one covering a failure."""
    base = _worked("ddw-test", TESTS_DOC)
    # The worked report skips nothing, so the case has to be PLANTED: two
    # tests skipped and not one line saying why.
    mute = re.sub(r"^\| Skipped \|.*$", "| Skipped | 2 |", base, flags=re.M)
    mute = re.sub(r"^\| Passed \| (\d+) \|$",
                  lambda m: "| Passed | %d |" % (int(m.group(1)) - 2), mute, flags=re.M)
    mute = re.sub(r"^## Skips\n\(none\)\s*$",
                  "## Skips\n- `tests/test_auth.py::test_expiry`\n- `tests/test_auth.py::test_refresh`",
                  mute, flags=re.M)
    assert "## Skips\n- " in mute and "| Skipped | 2 |" in mute, \
        "the probe did not plant the two mute skips"
    _, refused = _validate(tmp_path, "validate_tests.py", "tests-T-4.md", mute)
    assert _refuses(refused, "F-TEST-06"), \
        "two skipped tests without one line of reason passed: " + \
        ("\n".join(refused) or "no refusals at all")


def test_a_real_run_of_a_thousand_tests_is_not_refused_for_its_punctuation(tmp_path):
    """The reverse direction, which is the one that costs the most: every
    runner prints the thousands separator, and without stripping it `1,204`
    reads as `1`. The gate refuses the TRUE document, and its author has
    nothing to correct."""
    base = _worked("ddw-test", TESTS_DOC)
    big = base
    for field, value in (("Total", "1,204"), ("Passed", "1,202"),
                         ("Failed", "0"), ("Skipped", "2")):
        big = re.sub(r"^\| %s \|.*$" % field, "| %s | %s |" % (field, value), big, flags=re.M)
    assert big != base, "the probe did not change the counts"
    r, refused = _validate(tmp_path, "validate_tests.py", "tests-T-5.md", big)
    assert not _refuses(refused, "F-TEST-02"), \
        ("a real run of 1,204 tests was refused for its own punctuation: "
         + "\n".join(refused))


# ── The spec ─────────────────────────────────────────────────────────────────

def _fixture(marker, tag):
    """A healthy document from the suite. The spec skill carries a TEMPLATE
    with placeholders, not a worked document, so the only complete example
    there is lives there. Read, not copied: copying it would be a third
    version of the same shape."""
    suite = open(os.path.join(ROOT, "scripts/verify_install.sh"), encoding="utf-8").read()
    at = suite.index(marker)
    end = suite.index("\n" + tag, at)
    return suite[suite.index("\n", at) + 1:end]


def _spec():
    return _fixture('cat > "$VS/spec-FEAT-001.md" <<\'SPECEOF\'', "SPECEOF")


def _prd(tmp_path):
    """The spec is validated AGAINST its PRD; without it the coverage is not
    checked and the healthy document is refused for a reason that is not the
    one being measured."""
    body = _fixture('cat > "$VP/docs/ddw/prd/prd-FEAT-001.md" <<\'PRDEOF\'', "PRDEOF")
    path = tmp_path / "prd-FEAT-001.md"
    path.write_text(body, encoding="utf-8")
    return "--prd", str(path)


def test_a_spec_block_owes_what_can_go_wrong_with_it(tmp_path):
    """F-SPEC-10. With zero documented errors, F-SPEC-16 does not cover the
    hole either: comparing the sad paths against an empty list compares
    nothing."""
    base = _spec()
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md", base, *_prd(tmp_path))
    assert r.returncode == 0 and not refused, \
        "the healthy spec no longer passes: " + ("\n".join(refused) or r.stderr[-200:])
    noerr = re.sub(r"^\*\*Error handling\*\*.*?(?=^\*\*|^## )", "", base, flags=re.M | re.S)
    assert noerr != base, "the healthy spec no longer carries `**Error handling**`"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-002.md", noerr, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-10"), \
        "a block without error handling passed: " + ("\n".join(refused) or "no refusals at all")


# A block that has no errors of its own. Measured in round 6: the truth fit
# nowhere — in prose F-SPEC-10 refuses it, in a bullet F-SPEC-16 charges it a
# test — so a static-render block invented another block's 404, with its test,
# to put the gate in green.

QUIETO = """
## Block 2 — Pagina de ayuda estatica

**Files**
- `app/templates/help.html` (new) — texto de ayuda

**Logic**
Renderiza un texto fijo. No recibe nada del usuario ni toca la base.

**Error handling**
- Sin condiciones de error propias: el render es estatico.

**Required tests**
- [ ] test_ayuda_devuelve_200 — validates AC-01

**Completion criterion**
Pasa test_ayuda_devuelve_200.
"""


def test_un_bloque_sin_errores_propios_puede_decirlo(tmp_path):
    """F-SPEC-10/16. The declaration satisfies the rule and counts as ZERO
    errors: if it counted as one, F-SPEC-16 would ask it for a sad path the
    block does not have, which is the dead end that forced inventing the
    error."""
    base = _spec()
    cuerpo = base.replace("\n## Rollback", QUIETO + "\n## Rollback")
    assert cuerpo != base, "the healthy spec no longer has `## Rollback` to hang the block on"
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-030.md", cuerpo,
                           *_prd(tmp_path))
    assert r.returncode == 0 and not refused, \
        "a block declaring it has no errors was refused: " + (
            "\n".join(refused) or r.stderr[-200:])


def test_la_declaracion_se_refusa_donde_no_puede_ser_cierta(tmp_path):
    """The other half, and the one that keeps it from being a magic word: the
    healthy block receives a form, and what arrives can arrive wrong."""
    base = _spec()
    miente = re.sub(r"^\*\*Error handling\*\*\n(?:- .*\n)+",
                    "**Error handling**\n- Sin condiciones de error propias.\n",
                    base, flags=re.M)
    assert miente != base, "the healthy spec no longer carries `**Error handling**` bullets"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-031.md", miente,
                           *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-10"), \
        "a block with input declared it has no errors and passed: " + (
            "\n".join(refused) or "no refusals at all")


def test_a_spec_owes_the_order_its_blocks_run_in(tmp_path):
    """F-SPEC-11. Once for the whole document, and without it the execution
    order goes undeclared."""
    base = _spec()
    nodeps = re.sub(r"^## Dependencies between blocks.*?(?=^## )", "", base, flags=re.M | re.S)
    assert nodeps != base, "the healthy spec no longer carries the dependencies section"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-003.md", nodeps, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-11"), \
        "a spec with no declared execution order passed: " + "\n".join(refused)


# ── Three spec rules the suite also never executes ───────────────────────────
#
# From the same coverage map: `no_criterion`, `bad_api` and `bad_model` are
# branches the suite never touches once. They are the rules that decide
# whether a block says when it is done, whether an endpoint carries its
# contract and whether a schema declares its constraints — what separates a
# spec from a list of intentions.

def test_a_block_owes_a_verifiable_completion_criterion(tmp_path):
    """F-SPEC-05. Without a criterion, «done» is an opinion, and the phase
    that implements the block has nothing to measure against."""
    base = _spec()
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md", base, *_prd(tmp_path))
    assert r.returncode == 0 and not refused, \
        "the healthy spec no longer passes: " + ("\n".join(refused) or r.stderr[-200:])
    cut = re.sub(r"^\*\*Completion criterion\*\*.*?(?=^\*\*|^## )", "", base, flags=re.M | re.S)
    assert cut != base, "the healthy spec no longer carries `**Completion criterion**`"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-010.md", cut, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-05"), \
        "a block without a completion criterion passed: " + ("\n".join(refused) or "no refusals at all")


def test_an_endpoint_owes_a_complete_contract(tmp_path):
    """F-SPEC-07. A contract missing its error code or its authentication is
    the one that gets discovered in production."""
    base = _spec()
    if "API contract" not in base:
        pytest.skip("the healthy spec declares no API contract to trim")
    # The label sits alone on its line and the content below it, up to the
    # next bold label: replacing only the label's line trims nothing.
    partial = re.sub(r"(?ms)^\*\*API contract\*\*.*?(?=^\*\*|^## )",
                     "**API contract**\n- POST /api/x — request body, response 200\n\n",
                     base, count=1)
    assert partial != base, "the probe did not trim the contract section"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-011.md", partial,
                           *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-07"), \
        ("a contract without error codes or authentication passed: "
         + ("\n".join(refused) or "no refusals at all"))


# ── The ADR ─────────────────────────────────────────────────────────────────
#
# The one artifact that had no check, and therefore the one whose genre
# depended on the model already knowing it. The rule that matters is F-ADR-03:
# an ADR explains a decision already taken and obliges nothing.

ADR_SANO = """# ADR-001: Límite en proceso en lugar de CAPTCHA

| Field | Value |
|-------|-------|
| Date | 2026-08-13 |
| Ticket | T-1 |
| Status | Accepted |

## Context
El formulario es público y anónimo, y cada alta cuesta una llamada al modelo.

## Options considered

### Option 1: CAPTCHA de un tercero
- **Pros:** frena bots conocidos
- **Cons:** suma un tercero a la carga inicial

### Option 2: Límite por IP en proceso
- **Pros:** sin dependencias nuevas
- **Cons:** no distingue IPs compartidas

## Decision
Se eligió el límite en proceso: 5 altas por IP cada 10 minutos.

## Consequences
- Un aula detrás de una sola IP puede toparse con el límite.
- Se revisa cuando entren credenciales a la misma base.
"""


def _adr(tmp_path, body, name="adr-001-limite.md"):
    d = tmp_path / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    r = subprocess.run(["python3", os.path.join(ROOT, "ddw/scripts/validate_adr.py"),
                        str(d / name)], capture_output=True, text=True)
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


def test_un_adr_que_explica_pasa(tmp_path):
    r, refused = _adr(tmp_path, ADR_SANO)
    assert r.returncode == 0, "the healthy ADR was refused: " + "\n".join(refused)


def test_un_adr_que_manda_es_rechazado(tmp_path):
    """F-ADR-03, the rule this validator exists for. An obligation here is a
    requirement no acceptance criterion covers and no gate reads, competing
    with the spec for authority over the code."""
    manda = ADR_SANO.replace("Se eligió el límite en proceso: 5 altas por IP cada 10 minutos.",
                             "El sistema debe limitar a 5 altas por IP cada 10 minutos.")
    _, refused = _adr(tmp_path, manda)
    assert _refuses(refused, "F-ADR-03"), \
        "an ADR that commands passed: " + ("\n".join(refused) or "no refusals at all")


def test_una_obligacion_citada_no_es_del_adr(tmp_path):
    """The same verb, said by another document. Reading a quote as the ADR's
    own voice turned the sharpest rule in the catalog into the noisiest."""
    citando = ADR_SANO.replace("## Consequences",
                               "## Consequences\n\n> El PRD dice: el sistema debe responder en 3 s.\n")
    r, refused = _adr(tmp_path, citando)
    assert not _refuses(refused, "F-ADR-03"), \
        "a quoted obligation was read as the ADR's own: " + "\n".join(refused)
    assert r.returncode == 0


def test_una_sola_opcion_no_es_una_decision(tmp_path):
    """F-ADR-02. One option is a preference; recording it as a decision is
    how a preference acquires the authority of one."""
    sola = re.sub(r"(?s)### Option 2.*?(?=## Decision)", "", ADR_SANO)
    _, refused = _adr(tmp_path, sola)
    assert _refuses(refused, "F-ADR-02"), \
        "an ADR with a single option passed: " + ("\n".join(refused) or "no refusals at all")


def test_dos_decisiones_no_comparten_numero(tmp_path):
    """F-ADR-05. The number is the document's identity: it is how a successor
    names what it replaces."""
    _adr(tmp_path, ADR_SANO, "adr-001-limite.md")
    _, refused = _adr(tmp_path, ADR_SANO, "adr-001-otra.md")
    assert _refuses(refused, "F-ADR-05"), \
        "two ADRs with the same number passed: " + ("\n".join(refused) or "no refusals at all")


# ── The split ───────────────────────────────────────────────────────────────
#
# The protocol REPLACES the parent with an index, so the original's list of
# criteria disappears the moment the split lands. F-PRD-10 is the only place
# where it can be asked whether the parts cover the whole.

INDICE = """# Parent PRD: Triage IA

| Metric | Value |
|--------|-------|
| Ticket | FEAT-001 |
| Status | Split |
| Acceptance criteria to cover | 6 |

## Sub-tickets

| Sub-ticket | Title | PRD | ACs | Dependencies | Status |
|---|---|---|---|---|---|
| FEAT-001a | Ingesta | prd-FEAT-001a.md | AC-01, AC-02, AC-03 | none | active |
| FEAT-001b | IA | prd-FEAT-001b.md | AC-04, AC-05 | depends on a | pending |
| FEAT-001c | Envio | prd-FEAT-001c.md | AC-06 | depends on b | pending |
"""


def _indice(tmp_path, body, name="prd-FEAT-001.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    r = subprocess.run(["python3", os.path.join(ROOT, "ddw/scripts/validate_prd.py"),
                        str(path), "--tier", "FEATURE"], capture_output=True, text=True,
                       cwd=str(tmp_path))
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


def test_un_indice_que_particiona_pasa(tmp_path):
    r, refused = _indice(tmp_path, INDICE)
    assert r.returncode == 0, "the healthy index was refused: " + "\n".join(refused)


def test_un_criterio_que_no_se_lleva_nadie_es_rechazado(tmp_path):
    """F-PRD-10. It is the one loss the split can cause that afterwards
    cannot be detected from anywhere: the original no longer exists."""
    _, refused = _indice(tmp_path, INDICE.replace("| AC-06 | depends on b", "|  | depends on b"))
    assert _refuses(refused, "F-PRD-10"), \
        "a split that left an AC out passed: " + ("\n".join(refused) or "no refusals at all")


def test_un_criterio_en_dos_sub_tickets_es_rechazado(tmp_path):
    """The same AC claimed twice: two tickets believe it is theirs, and in
    VERIFY each one expects the other to cover it."""
    _, refused = _indice(tmp_path, INDICE.replace("AC-04, AC-05", "AC-03, AC-04, AC-05"))
    assert _refuses(refused, "F-PRD-10"), \
        "an AC duplicated across children passed: " + ("\n".join(refused) or "no refusals at all")


def test_un_indice_que_reparte_mas_de_lo_que_declara_es_rechazado(tmp_path):
    """F-PRD-10. The number is written by the model and used to be compared
    against NOTHING, not even the rows below. Measured: an index declared 22
    where the source document had 17 — five decided with the user in DEFINE —
    and the receipt came out certifying «all 22 of the original»."""
    de_mas = INDICE.replace("| AC-06 | depends on b", "| AC-06, AC-07 | depends on b")
    assert de_mas != INDICE, "the healthy index no longer hands out AC-06 in c's row"
    _, refused = _indice(tmp_path, de_mas)
    assert _refuses(refused, "F-PRD-10"), \
        "an index that declares 6 and hands out 7 passed: " + ("\n".join(refused) or "no refusals at all")


def test_el_recibo_del_split_no_habla_del_original(tmp_path):
    """What the rule measures is that the parts divide up what the index puts
    on the table. Saying «of the original» about criteria born in DEFINE is
    certifying something that was not checked."""
    r, _ = _indice(tmp_path, INDICE)
    fila = [ln for ln in r.stdout.splitlines() if "F-PRD-10" in ln]
    assert fila and "of the original" not in fila[0], \
        "the receipt still asserts where the criteria came from: %r" % fila


def test_un_indice_sin_el_total_a_cubrir_es_rechazado(tmp_path):
    """Without that number the question cannot be answered, and the document
    it would be answered against has already been overwritten."""
    sin = "\n".join(l for l in INDICE.splitlines() if "criteria to cover" not in l)
    _, refused = _indice(tmp_path, sin)
    assert _refuses(refused, "F-PRD-10"), \
        "an index without the total passed: " + ("\n".join(refused) or "no refusals at all")


def test_un_indice_que_no_declara_ni_reparte_nada_es_rechazado(tmp_path):
    """The same F-PRD-10 in the one case the rows cannot reach.

    Without the total, the division below is compared against the empty set:
    nothing missing, nothing extra, and a half-written index comes out with a
    green receipt saying its «0 criteria» are each taken by exactly one
    sub-ticket. The index has already replaced the parent, so that green is
    granted over a list of criteria that at that moment exists nowhere.
    """
    vacio = "\n".join(l for l in INDICE.splitlines()
                       if "criteria to cover" not in l and not l.startswith("| FEAT-001"))
    assert "AC-01" not in vacio and "criteria to cover" not in vacio, \
        "the probe index still declares or hands out something, which is the opposite of the case"
    r, refused = _indice(tmp_path, vacio)
    assert _refuses(refused, "F-PRD-10"), \
        ("an index that declares nothing and hands out nothing passed with a green receipt:\n" + r.stdout)


def test_un_sub_prd_que_renumera_sus_criterios_es_rechazado(tmp_path):
    """F-PRD-11. Measured on a live split: the index said «b takes
    AC-09..AC-17» and prd-FEAT-001b.md restarted at AC-01, so every
    cross-reference between the two documents had two possible answers."""
    (tmp_path / "prd-FEAT-001b.md").write_text(
        "# PRD FEAT-001b\n- AC-01: renumbered\n- AC-02: renumbered\n", encoding="utf-8")
    _, refused = _indice(tmp_path, INDICE)
    assert _refuses(refused, "F-PRD-11"), \
        "a sub-PRD that renumbers its assigned ACs passed: " + ("\n".join(refused) or "no refusals")


def test_un_sub_prd_con_los_numeros_del_indice_pasa(tmp_path):
    (tmp_path / "prd-FEAT-001b.md").write_text(
        "# PRD FEAT-001b\n- AC-04: as assigned\n- AC-05: as assigned\n", encoding="utf-8")
    r, refused = _indice(tmp_path, INDICE)
    assert r.returncode == 0, \
        "a sub-PRD carrying exactly its assigned ids was refused: " + "\n".join(refused)


def test_un_indice_sin_partes_en_disco_no_es_juzgado_por_ellas(tmp_path):
    """The index legitimately lands first; F-PRD-11 reads only what exists."""
    r, refused = _indice(tmp_path, INDICE)
    assert r.returncode == 0 and not _refuses(refused, "F-PRD-11"), \
        "an index was refused for parts that do not exist yet: " + "\n".join(refused)


def test_un_sub_prd_mas_grande_que_el_umbral_avisa(tmp_path):
    """W-PRD-06. The split that shrank nothing: a warning, never a block —
    keeping the whole ticket is the user's decision, but the number is not
    theirs to lose."""
    base = _worked("ddw-create-prd", "## PRD Template")
    extra = "\n".join("- AC-%02d (FR-01): WHEN algo pasa, THE sistema SHALL responder." % n
                      for n in range(4, 13))
    grande = base.replace("- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].",
                          "- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].\n" + extra)
    r, _ = _validate(tmp_path, "validate_prd.py", "prd-FEAT-099.md", grande)
    assert "W-PRD-06" in r.stdout, \
        "a 12-AC PRD said nothing about the threshold:\n" + r.stdout[-400:]


# ── The commit gate ─────────────────────────────────────────────────────────
#
# `git commit` was the one act of the pipeline no hook judged: the
# PreToolUse matcher was Edit|Write|NotebookEdit and a commit is a Bash call.
# Measured: five documents committed and the user reading the hash afterwards.

GATE = os.path.join(ROOT, "ddw/scripts/hook-gate.py")
GRAPH_PATH = os.path.join(ROOT, "ddw/rules/transition-graph.json")
PROPOSAL = os.path.join(".ddw-work", "commit-message.txt")
MENSAJE = "\U0001F4DD docs(prd): definir el triage\n\nRefs: F-1\nAI-assisted: yes\n"


def _repo_en_define(tmp_path, autonomy="assisted"):
    state = tmp_path / ".ddw-state.json"
    state.write_text(json.dumps({"phase": "DEFINE", "tier": "FEATURE", "ticket": "F-1",
                                 "autonomy": autonomy, "gates": {},
                                 "history": [{"from": "IDLE", "to": "CLASSIFY", "action": "c",
                                              "tier": "FEATURE", "ticket": "F-1"}]}),
                     encoding="utf-8")
    return state


def _commit(tmp_path, command="git commit -F .ddw-work/commit-message.txt"):
    event = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([sys.executable, GATE, "--mode", "commit",
                           "--state", str(tmp_path / ".ddw-state.json"),
                           "--graph", GRAPH_PATH, "--repo", str(tmp_path)],
                          input=event, capture_output=True, text=True)


def _habla_el_usuario(tmp_path):
    subprocess.run([sys.executable, GATE, "--mode", "turn",
                    "--state", str(tmp_path / ".ddw-state.json"),
                    "--graph", GRAPH_PATH, "--repo", str(tmp_path)],
                   input="{}", capture_output=True, text=True)


def _propone(tmp_path, texto=MENSAJE):
    d = tmp_path / ".ddw-work"
    d.mkdir(exist_ok=True)
    (d / "commit-message.txt").write_text(texto, encoding="utf-8")


def test_un_commit_que_el_usuario_no_vio_es_rechazado(tmp_path):
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    assert _commit(tmp_path).returncode == 2, \
        "showing the message and committing could happen in the same response"


def test_un_commit_visto_y_contestado_pasa_al_primer_intento(tmp_path):
    """The first version refused the FIRST attempt and charged a round trip
    even to the model that had done everything right."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0, "the approved commit was refused anyway"


def test_el_trailer_que_el_metodo_prohibe_no_pasa(tmp_path):
    """`commits.instructions.md` says it in capitals — NEVER `Co-Authored-By`,
    the disclosure is `AI-assisted: yes` — and no gate read the file that
    rule talks about.

    Measured live on Copilot: the model drafted the message, the user
    approved it, and it carried `Co-authored-by: Copilot
    <…@users.noreply.github.com>` — the tool's default doing exactly what the
    rule forbids. Approved and all, that commit attributes an authorship the
    project never agreed to.
    """
    _repo_en_define(tmp_path)
    malo = MENSAJE.rstrip("\n") + "\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>\n"
    _propone(tmp_path, malo)
    _habla_el_usuario(tmp_path)
    r = _commit(tmp_path)
    assert r.returncode == 2, "the commit carried a Co-Authored-By the method forbids"
    assert "AI-assisted" in (r.stdout + r.stderr), \
        "the refusal does not say which trailer DOES go: " + (r.stdout + r.stderr)[-200:]

    # …and the correct message still passes: what gets judged is the trailer,
    # not the body. What the message SAYS belongs to the model and to the
    # user who approves it.
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0, "a legitimate message ended up refused"


def test_mostrar_un_mensaje_y_commitear_otro_es_rechazado(tmp_path):
    """The hole nobody was closing: the bytes get compared."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    _propone(tmp_path, "\U0001F4DD docs: otra cosa completamente distinta\n")
    assert _commit(tmp_path).returncode == 2, "it committed a message the user never saw"


def _post(tmp_path):
    """The PostToolUse that runs after every Bash — consumer of the permission."""
    return subprocess.run([sys.executable, GATE, "--mode", "post",
                           "--state", str(tmp_path / ".ddw-state.json"),
                           "--graph", GRAPH_PATH, "--repo", str(tmp_path)],
                          input="{}", capture_output=True, text=True)


def _git_commitea(tmp_path, mensaje=MENSAJE):
    """A real commit with the approved bytes, as `git commit -F` would leave it."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], env=env, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"],
                   env=env, check=True)
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "doc.md"], env=env, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", mensaje],
                   env=env, check=True)


def test_el_permiso_se_gasta_cuando_el_commit_existe(tmp_path):
    """Spending it on ALLOWING was the defect: the permission is spent by the commit at HEAD."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0
    _git_commitea(tmp_path)          # the approved commit actually landed
    _post(tmp_path)                  # exit code irrelevant: only the consumption matters here
    assert _commit(tmp_path).returncode == 2, "an already-committed message opened the next commit"


def test_un_commit_que_fallo_no_gasta_el_permiso(tmp_path):
    """The gate allowed, git failed (GPG without a TTY, pre-commit, empty
    index): the approval has to stay standing and the retry pass without
    another turn. The first version deleted proposal and stamp on allowing,
    the model found `.ddw-work/` empty, rewrote the same bytes and was
    refused as never-seen. Measured, on the first manual run that got here."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0
    _git_commitea(tmp_path, "otro mensaje: el aprobado nunca llegó a HEAD")
    _post(tmp_path)                  # runs the same after the failed Bash
    assert (tmp_path / PROPOSAL).exists(), "the post consumed a permission no commit spent"
    assert _commit(tmp_path).returncode == 0, \
        "the retry of the approved commit was refused: the gate ate the approval"


def test_un_commit_por_fuera_del_archivo_es_rechazado(tmp_path):
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path, 'git commit -m "otra cosa"').returncode == 2


def test_lo_que_no_es_un_commit_no_le_incumbe(tmp_path):
    _repo_en_define(tmp_path)
    for cmd in ("git status --short", "git log --oneline | grep commit", "git commit --dry-run"):
        assert _commit(tmp_path, cmd).returncode == 0, cmd


def test_minimal_no_espera(tmp_path):
    """Lo que ese modo saca es el preguntar, y un commit es local y reversible."""
    _repo_en_define(tmp_path, autonomy="minimal")
    assert _commit(tmp_path, 'git commit -m "x"').returncode == 0


# ── The rules that passed on emptiness ───────────────────────────────────────
#
# The pattern measured in round 4: a rule whose parser extracts zero elements
# reported "all 0 ... " and went green. A check that measured nothing vouches
# for nothing.

def test_un_prd_cuyos_ids_no_parsean_no_pasa_la_bateria(tmp_path):
    """F-PRD-05: "0 FR, 0 NFR, 0 AC — unique, gapless" was a PASS, and with
    the lists empty F-PRD-01/03/06/09 passed too."""
    body = _fixture('cat > "$VP/docs/ddw/prd/prd-FEAT-001.md" <<\'PRDEOF\'', "PRDEOF")
    sin_ids = body.replace("FR-", "Req ").replace("NFR-", "NReq ").replace("AC-", "Crit ")
    r, refused = _validate(tmp_path, "validate_prd.py", "prd-FEAT-002.md", sin_ids)
    assert _refuses(refused, "F-PRD-05"), \
        "a PRD without a single parseable ID passed the whole battery: " + "\n".join(refused)


def test_una_spec_contra_un_prd_que_parsea_vacio_no_reporta_cobertura(tmp_path):
    """F-SPEC-01/02/03: "all 0 FR are referenced" era cobertura declarada sobre
    nada. Un PRD legible que parsea a cero IDs es el documento equivocado."""
    base = _spec()
    vacio = tmp_path / "prd-vacio.md"
    vacio.write_text("# PRD FEAT-001\n\nRequisitos en prosa, sin IDs con formato.\n",
                     encoding="utf-8")
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-020.md", base,
                           "--prd", str(vacio))
    assert _refuses(refused, "F-SPEC-01/02/03"), \
        "a spec validated coverage against a PRD that parses empty: " + "\n".join(refused)


def _f_ver_06(tmp_path, report, spec):
    rp = tmp_path / "verify.md"
    rp.write_text(report, encoding="utf-8")
    sp = tmp_path / "spec.md"
    sp.write_text(spec, encoding="utf-8")
    r = subprocess.run(["python3", os.path.join(ROOT, "ddw/scripts/validate_verify.py"),
                        str(rp), "--spec", str(sp)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    return [ln for ln in r.stdout.splitlines() if "F-VER-06" in ln]


SPEC_BACKTICKS = ("# Spec\n\n## Block 1 — x\n**Required tests**\n"
                  "- [ ] `test_uno` — valida AC-01\n- [ ] `test_dos` — valida AC-02\n")


def test_los_tests_prometidos_con_backticks_se_leen(tmp_path):
    """F-VER-06: the spec skill emits `test_x` with backticks and the regex
    read zero — "all 0 test(s) the spec promised" went green on a real run
    that had 13 promised and 3 missing from the report."""
    rows = _f_ver_06(tmp_path, "# V\nblock 1: test_uno y test_dos verificados\n",
                     SPEC_BACKTICKS)
    assert rows and "✅" in rows[0] and "2 test(s)" in rows[0], \
        "los nombres con backticks siguen invisibles: %r" % rows


# The fix's two halves cover for each other if measured with the same
# document: scoping to `Required tests` hides that the path leaks in, and
# filtering the path hides the over-reading. One fixture per half, or the
# mutation that re-injects each one survives on the other's defense.

SPEC_RUTA_PROMETIDA = ("# Spec\n\n## Block 1 — x\n"
                       "**Required tests**\n"
                       "- [ ] `test_uno` — valida AC-01\n"
                       "- [ ] `test_dos` — valida AC-02\n"
                       "- [ ] `tests/fakes.py` — el doble del repositorio\n")


def test_una_ruta_de_archivo_no_es_un_test_prometido(tmp_path):
    """F-VER-06. `tests/fakes.py` holds not a single test, and counting it
    inflated the tally: round 6 measured "all 19 test(s) the spec promised"
    over a spec that promised 16. The previous ❌ was closed by adding the
    FILE NAMES to the report — exactly what the rule was misreading. Written
    INSIDE `Required tests` on purpose: narrowing the search is not enough
    for this."""
    rows = _f_ver_06(tmp_path, "# V\nblock 1: test_uno y test_dos verificados\n",
                     SPEC_RUTA_PROMETIDA)
    assert rows and "✅" in rows[0] and "2 test(s)" in rows[0], \
        "a file path still counts as a promised test: %r" % rows


SPEC_NOMBRE_FUERA = ("# Spec\n\n## Block 1 — x\n"
                     "**Required tests**\n- [ ] `test_uno` — valida AC-01\n"
                     "## Rollback\n- `test_smoke_legacy` queda como estaba\n")


def test_un_test_nombrado_fuera_de_required_tests_no_es_una_promesa(tmp_path):
    """The other half: the promise lives in `Required tests` and nowhere
    else. Reading the whole document, a test the spec MENTIONS — the smoke
    test that stays as-is after the rollback — becomes a promise the
    verification report has to name, and VERIFY refuses over something
    nobody promised."""
    rows = _f_ver_06(tmp_path, "# V\nblock 1: test_uno verificado\n", SPEC_NOMBRE_FUERA)
    assert rows and "✅" in rows[0] and "1 test(s)" in rows[0], \
        "a test named outside Required tests was charged as a promise: %r" % rows


def test_un_test_prometido_ausente_del_reporte_refusa(tmp_path):
    rows = _f_ver_06(tmp_path, "# V\nblock 1: solo test_uno\n", SPEC_BACKTICKS)
    assert rows and "❌" in rows[0] and "test_dos" in rows[0], \
        "a promised and absent test passed: %r" % rows


def test_required_tests_ilegibles_no_es_un_pass(tmp_path):
    """The honest half of the fix: if there are Required tests sections and
    the parser extracts zero names, that is a NO — not an "all 0" in green."""
    spec = "# Spec\n**Required tests**\n- [ ] «prueba_uno» — nombre sin formato\n"
    rows = _f_ver_06(tmp_path, "# V\n", spec)
    assert rows and "❌" in rows[0], \
        "a spec with unreadable promises vouched for the report: %r" % rows


# ── El gate del merge ────────────────────────────────────────────────────────
#
# The one act of the pipeline that leaves the repo and that nobody here can
# revert ran with no hook seeing it; the choice arrived via picker, which no
# hook receives. Same design as the commit gate — proposal + stamp — with the
# difference the act demands: it governs in BOTH autonomy modes.

MERGE_PROP = os.path.join(".ddw-work", "merge-proposal.txt")
PROPUESTA_MERGE = "merge PR #7 into main — Recepción de tickets\n"


def _merge(tmp_path, command="gh pr merge 7 --squash", env=None):
    event = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([sys.executable, GATE, "--mode", "commit",
                           "--state", str(tmp_path / ".ddw-state.json"),
                           "--graph", GRAPH_PATH, "--repo", str(tmp_path)],
                          input=event, capture_output=True, text=True, env=env)


def _propone_merge(tmp_path, texto=PROPUESTA_MERGE):
    d = tmp_path / ".ddw-work"
    d.mkdir(exist_ok=True)
    (d / "merge-proposal.txt").write_text(texto, encoding="utf-8")


def _post_hook(tmp_path, env=None):
    return subprocess.run([sys.executable, GATE, "--mode", "post",
                           "--state", str(tmp_path / ".ddw-state.json"),
                           "--graph", GRAPH_PATH, "--repo", str(tmp_path)],
                          input="{}", capture_output=True, text=True, env=env)


def _gh_estado(tmp_path, estado):
    b = tmp_path / "ghbin"
    b.mkdir(exist_ok=True)
    gh = b / "gh"
    gh.write_text('#!/usr/bin/env bash\necho "{\\"state\\":\\"%s\\"}"\n' % estado,
                  encoding="utf-8")
    gh.chmod(0o755)
    return dict(os.environ, PATH=str(b) + os.pathsep + os.environ["PATH"])


def test_un_merge_que_el_usuario_no_vio_es_rechazado(tmp_path):
    _repo_en_define(tmp_path)
    assert _merge(tmp_path).returncode == 2, "a merge ran with nobody having seen it"


def test_un_merge_visto_y_contestado_pasa(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _merge(tmp_path).returncode == 0, "the approved merge was refused anyway"


def test_minimal_no_exime_al_merge(tmp_path):
    """The sentence the prose always said and nothing upheld: the merge keeps
    its confirmation in both modes."""
    _repo_en_define(tmp_path, autonomy="minimal")
    assert _merge(tmp_path).returncode == 2, \
        "minimal exempted the act the prose says is never exempt"


def test_un_merge_propuesto_en_el_mismo_turno_es_rechazado(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    assert _merge(tmp_path).returncode == 2, \
        "showing the proposal and merging could happen in the same response"


def test_un_merge_fallido_no_gasta_la_aprobacion(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _merge(tmp_path).returncode == 0
    _post_hook(tmp_path, env=_gh_estado(tmp_path, "OPEN"))   # the merge did NOT land
    assert (tmp_path / MERGE_PROP).exists(), "the post consumed a merge that does not exist"
    assert _merge(tmp_path).returncode == 0, "the retry of the approved merge was refused"


def test_el_permiso_del_merge_se_gasta_cuando_el_forge_dice_merged(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _merge(tmp_path).returncode == 0
    _post_hook(tmp_path, env=_gh_estado(tmp_path, "MERGED"))
    assert not (tmp_path / MERGE_PROP).exists(), "the post did not consume a landed merge"
    assert _merge(tmp_path).returncode == 2, "a spent approval opened the next merge"


# ── The installer and the uncommitted install ────────────────────────────────

def test_sin_tty_el_instalador_avisa_que_la_instalacion_no_esta_commiteada(tmp_path):
    """Round 4's bomb: an install never committed → the first closeout sweeps
    it into the feature's PR (68 files). Without a terminal it cannot ask,
    but staying silent was the defect."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                    "-m", "base"], check=True)
    r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), str(repo),
                        "--target", "claude", "--mode", "dropin"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]
    assert "not committed" in r.stdout, \
        "the installer left the install uncommitted and said nothing"


def test_instalar_en_un_directorio_sin_git_instala_y_avisa(tmp_path):
    """A regression measured the same day as the installer fix: `set -euo
    pipefail` + an unsaved git capture = the installer died at rc 128 WITHOUT
    PRINTING A LINE about a non-git destination. Installing must work, and
    the notice must exist: the pipeline branches/commits/opens PRs and the
    first ticket dies in CLASSIFY if there is no git."""
    target = tmp_path / "nogit"
    target.mkdir()
    r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), str(target),
                        "--target", "claude", "--mode", "dropin"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert r.returncode == 0, "the installer died on a git-less destination: rc=%s %s" % (
        r.returncode, r.stderr[-200:])
    assert (target / ".ddw" / "orchestrator.md").exists(), "it installed nothing"
    assert "not a git repository" in r.stdout, \
        "it installed in silence where the first ticket will die in CLASSIFY"


# ── The installer's git flow (DDW_GIT_FLOW is the no-terminal spelling) ──────

def _repo_para_instalar(tmp_path, con_commit=True):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "-C", str(r), "init", "-q"], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    if con_commit:
        subprocess.run(["git", "-C", str(r), "commit", "-q", "--allow-empty",
                        "-m", "base"], check=True)
    return r


def _instala(r, flow, push=None):
    env = dict(os.environ, DDW_GIT_FLOW=flow)
    if push is not None:
        env["DDW_GIT_PUSH"] = push
    return subprocess.run(["bash", os.path.join(ROOT, "install.sh"), str(r),
                           "--target", "claude", "--mode", "dropin"],
                          stdin=subprocess.DEVNULL, env=env,
                          capture_output=True, text=True)


def _rama(r):
    return subprocess.run(["git", "-C", str(r), "branch", "--show-current"],
                          capture_output=True, text=True).stdout.strip()


def _sucios(r):
    out = subprocess.run(["git", "-C", str(r), "status", "--short"],
                         capture_output=True, text=True).stdout
    return len([ln for ln in out.splitlines() if ln.strip()])


def test_flow_setup_instala_commitea_en_su_rama_y_deja_limpio(tmp_path):
    r = _repo_para_instalar(tmp_path)
    res = _instala(r, "setup", push="n")
    assert res.returncode == 0, res.stderr[-300:]
    assert _rama(r).startswith("ddw-setup-"), \
        "it chose the setup branch and ended up on %r" % _rama(r)
    assert _sucios(r) == 0, "the install did not end up committed on the setup branch"
    assert "stays local" in res.stdout, "it did not say what happens to the branch without a push"


def test_flow_current_commitea_en_la_rama_actual(tmp_path):
    r = _repo_para_instalar(tmp_path)
    res = _instala(r, "current")
    assert res.returncode == 0, res.stderr[-300:]
    assert _rama(r) in ("main", "master"), "it moved branches with nobody asking"
    assert _sucios(r) == 0, "it chose commit on the current branch and ended up uncommitted"


def test_flow_none_deja_los_archivos_sin_commitear(tmp_path):
    r = _repo_para_instalar(tmp_path)
    res = _instala(r, "none")
    assert res.returncode == 0, res.stderr[-300:]
    assert _sucios(r) > 0, "it chose not to commit and something committed anyway"
    assert "nothing committed" in res.stdout, "it did not say the install was left uncommitted"


def test_un_git_init_sin_commits_ofrece_el_primer_commit(tmp_path):
    r = _repo_para_instalar(tmp_path, con_commit=False)
    res = _instala(r, "setup")   # asks for setup, but with no base no branch is possible
    assert res.returncode == 0, res.stderr[-300:]
    assert "no commits yet" in res.stdout, "it did not explain why there is no branch question"
    assert _sucios(r) == 0, "the repo's first commit was not made"


# ── El vocabulario de caminos tristes lee palabras reales (F-SPEC-16) ────────

_BULLET_VIVO = "- [ ] test_email_invalido_devuelve_422 — email con formato invalido"


def test_un_test_que_dice_rechazado_cuenta_como_camino_triste(tmp_path):
    """A round-5 regression: `rechaz` followed by `\\b` matches no written
    form ("rechazado", "rechaza"), and the real spec ended up changing its
    vocabulary to please the validator. The gate does not legislate words."""
    base = _spec()
    probe = base.replace(
        _BULLET_VIVO,
        "- [ ] test_email_mal_formado_es_devuelto — el email mal formado es rechazado")
    assert probe != base, "the probe did not change the bullet"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md",
                           probe, *_prd(tmp_path))
    assert not _refuses(refused, "F-SPEC-16"), \
        '"rechazado" does not count as a sad path: ' + "\n".join(refused)


def test_la_palabra_triste_en_la_segunda_linea_del_bullet_cuenta(tmp_path):
    """The other half of the same regression: a checkbox wrapped over two
    lines left the keyword out of the count — the item is read whole."""
    base = _spec()
    probe = base.replace(
        _BULLET_VIVO,
        "- [ ] test_email_mal_formado_es_devuelto — el email mal formado\n"
        "      es rechazado con un aviso por campo")
    assert probe != base, "the probe did not change the bullet"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md",
                           probe, *_prd(tmp_path))
    assert not _refuses(refused, "F-SPEC-16"), \
        "the sad word in the bullet's continuation did not count: " + "\n".join(refused)


def test_dos_errores_con_un_solo_test_triste_siguen_refusados(tmp_path):
    """The direction that keeps the matcher from being loosened until it
    matches everything: a happy-path test does not pay a documented error's
    debt."""
    base = _spec()
    probe = base.replace(
        _BULLET_VIVO,
        "- [ ] test_email_guardado — el email se persiste normalizado")
    assert probe != base, "the probe did not change the bullet"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md",
                           probe, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-16"), \
        "two documented errors with a single sad test passed: " + \
        ("\n".join(refused) or "no refusals at all")


# ── The install commit has to reach the remote ───────────────────────────────

def _con_remoto(r, tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(r), "remote", "add", "origin", str(bare)],
                   check=True)
    subprocess.run(["git", "-C", str(r), "push", "-q", "-u", "origin", "HEAD"],
                   check=True)
    return bare


def test_flow_current_con_remoto_avisa_que_el_commit_debe_llegar_al_remoto(tmp_path):
    """Round 5: the install committed on LOCAL main and never pushed ended up
    as 66 framework files in the feature's PR. If the user does not push
    here, the notice has to be impossible to miss."""
    r = _repo_para_instalar(tmp_path)
    _con_remoto(r, tmp_path)
    res = _instala(r, "current", push="n")
    assert res.returncode == 0, res.stderr[-300:]
    assert "YOU MUST GET IT ONTO YOUR DEFAULT" in res.stdout, \
        "the commit stayed local-only and the installer shouted nothing"


def test_flow_current_con_remoto_ofrece_push_y_pushea(tmp_path):
    r = _repo_para_instalar(tmp_path)
    bare = _con_remoto(r, tmp_path)
    res = _instala(r, "current", push="y")
    assert res.returncode == 0, res.stderr[-300:]
    local = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "-C", str(bare), "rev-parse", _rama(r)],
                            capture_output=True, text=True).stdout.strip()
    assert local and local == remote, \
        "it said it was pushing and the remote does not have the install commit"


# ── A shard with no mutations from the diff is an answer, not a failure ──────

def test_un_shard_sin_mutaciones_del_diff_contesta_vacio_y_no_muere(tmp_path):
    """Measured on the dependabot PRs: a diff touching 3 mutations left the
    other 21 shards with an empty selection, and the anti-"I measured
    nothing" guard killed them in red. A shard with no work in a sharded
    --changed run is an ordinary answer — the shards that do have them answer
    the question."""
    spec_ = importlib.util.spec_from_file_location(
        "mut_shard", os.path.join(ROOT, "scripts/mutate.py"))
    mut = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mut)
    objetivo = "ddw/rules/define.instructions.md"
    tocadas = {i for i, (_l, m) in enumerate(mut.MUTATIONS, 1)
               if getattr(m, "probe", None) is None or m.probe[1] == objetivo}
    assert tocadas, "no fault names the scenario's file"
    n = 24
    vacios = [s for s in range(1, n + 1)
              if not tocadas & set(mut.slice_of("%d/%d" % (s, n), len(mut.MUTATIONS)))]
    assert vacios, "el diff del escenario toca mutaciones en los 24 shards; elegir otro archivo"
    # A minimal synthetic repo: the runner only needs to sit in a git whose
    # last commit touches the scenario's file. No cloning ROOT — the mutation
    # suite runs these tests inside a copy WITHOUT .git, and a clone of that
    # copy died at 128 before measuring anything.
    clone = tmp_path / "repo"
    (clone / "scripts").mkdir(parents=True)
    (clone / os.path.dirname(objetivo)).mkdir(parents=True)
    shutil.copy(os.path.join(ROOT, "scripts/mutate.py"),
                str(clone / "scripts" / "mutate.py"))
    subprocess.run(["git", "-C", str(clone), "init", "-q"], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(clone), "config", k, v], check=True)
    (clone / objetivo).write_text("# base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "base"], check=True)
    with open(clone / objetivo, "a", encoding="utf-8") as f:
        f.write("\n<!-- tocado por el escenario del shard vacío -->\n")
    subprocess.run(["git", "-C", str(clone), "add", "--", objetivo], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "toca define"], check=True)
    r = subprocess.run(["python3", "scripts/mutate.py",
                        "--shard", "%d/%d" % (vacios[0], n), "--changed", "HEAD~1"],
                       cwd=str(clone), capture_output=True, text=True)
    assert r.returncode == 0, \
        "the shard with no work died in red again: " + (r.stdout + r.stderr)[-300:]
    assert "holds none of the" in r.stdout, \
        "the empty shard did not say why it injected nothing: " + r.stdout[-300:]
