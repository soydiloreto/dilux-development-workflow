"""Los validadores y el arranque de sesión, preguntados directamente.

Hermano de `test_validate_transition.py` y con el mismo alcance limitado: esto
NO reemplaza a `scripts/verify_install.sh`, que instala en un repo de verdad,
manda un evento de verdad a un hook de verdad y lee el veredicto que leería la
herramienta. Lo que prueba es que las reglas dicen lo que quieren decir, que es
la mitad que no cuesta nada preguntar seguido.

Todo lo de este archivo salió del mismo lugar: correr la suite bajo `coverage`
con `COVERAGE_PROCESS_START` —que mide también los subprocesos, y los
validadores y los hooks SON subprocesos— y mirar qué líneas no se ejecutan ni
una vez. Son reglas de enforcement, no ramas de error: un aviso de que el
enforcement instalado ya no es el que se instaló, y la caducidad del reporte de
seguridad que abre una compuerta.
"""
import datetime
import importlib.util
import re
import json
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boot = _load("boot", "ddw/scripts/session-boot.py")


# ── El enforcement instalado dejó de ser el instalado ────────────────────────

@pytest.fixture()
def installed(tmp_path):
    """Un repo con manifiesto y con los archivos que el manifiesto nombra."""
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
        "un repo intacto avisa de una deriva que no tiene, y un aviso que sale siempre no se lee"


def test_a_hook_deleted_from_a_shell_is_reported_as_missing(installed):
    """Los hooks se niegan a escribir estos archivos, así que un cambio acá vino
    de afuera de la sesión. Es el único aviso que hay de que el pipeline dejó de
    estar impuesto — sin él, el repo parece gobernado y no lo está."""
    os.remove(installed / ".claude" / "hooks" / "enforce.sh")
    lines = boot.enforcement_drift(str(installed))
    assert lines, "un hook borrado del repo no produjo ningún aviso"
    blob = "\n".join(lines)
    assert "MISSING" in blob and "enforce.sh" in blob, \
        f"el aviso no dice qué falta: {blob[:200]}"
    assert "install.sh" in blob, f"el aviso no dice cómo repararlo: {blob[:200]}"


def test_a_hook_edited_from_a_shell_is_reported_as_changed(installed):
    (installed / ".claude" / "hooks" / "enforce.sh").write_text("#!/usr/bin/env bash\nexit 0  # :)\n")
    blob = "\n".join(boot.enforcement_drift(str(installed)))
    assert "CHANGED" in blob and "enforce.sh" in blob, \
        f"un hook reescrito por fuera de la sesión pasó desapercibido: {blob[:200]}"


# ── Un reporte de seguridad caduco no abre la compuerta ──────────────────────

def _template():
    """El reporte que el skill le dice al modelo que escriba, tal cual.

    Escrito a mano acá, este archivo sería una segunda copia de la forma del
    documento, y la segunda copia siempre se queda atrás: el defecto que más
    veces mordió en este repo es una plantilla y una compuerta que dejaron de
    coincidir. Se lee del skill para que no puedan.
    """
    skill = open(os.path.join(ROOT, "skills/ddw-security-sast/SKILL.md"),
                 encoding="utf-8").read()
    at = skill.index("### The report, in the shape the validator reads")
    m = re.search(r"```markdown\n(.*?)```", skill[at:], re.S)
    assert m, "el skill de SAST ya no trae el reporte de ejemplo bajo ese título"
    return m.group(1).replace("{ticket}", "T-1")


def _with(body, suppression):
    """El reporte con UNA supresión donde el template dice `None.`

    Cortar en `## Suppressions` y quedarse con lo de arriba se lleva también las
    líneas `Total:` y `Result:` que van después, y el validador sin ellas no
    rechaza NADA — con lo cual el test de la supresión fresca pasaba sin que
    hubiera ninguna supresión que juzgar. Un test que pasa porque no midió nada
    es la misma familia que un check que no puede fallar.
    """
    out = body.replace("## Suppressions\nNone.\n", "## Suppressions\n" + suppression, 1)
    assert out != body, "el template ya no dice `## Suppressions` seguido de `None.`"
    return out


def _suppression(written, review):
    """El bloque de supresión en la forma que documenta la regla, leída de la
    regla — no escrita acá.

    §4.4 de `validation-rules.instructions.md` trae el único ejemplo trabajado
    que existe: el skill de SAST enseña "el formato de 7 campos" por referencia
    y nunca lo muestra. Copiar la forma a mano en este archivo sería la tercera
    versión de la misma cosa, y la que se quede atrás decide en silencio.
    """
    rules = open(os.path.join(ROOT, "ddw/rules/validation-rules.instructions.md"),
                 encoding="utf-8").read()
    at = rules.index("### 4.4 Finding Suppression Protocol")
    m = re.search(r"```markdown\n(.*?)```", rules[at:], re.S)
    assert m, "§4.4 ya no trae el bloque de supresión de ejemplo"
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
        "quedó un placeholder sin llenar en el bloque: " + block
    return block


def _sast(tmp_path, body, ticket="T-1", expect_suppression=False):
    path = tmp_path / f"sast-{ticket}.md"
    path.write_text(body, encoding="utf-8")
    r = subprocess.run(["python3", os.path.join(ROOT, "ddw/scripts/validate_sast.py"),
                        str(path), "--tier", "FEATURE"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    # Que el bloque haya sido PARSEADO, antes de leer nada sobre él. El
    # validador tiene una forma de decir "no había ninguna supresión que
    # envejecer", y contra esa salida cualquier aserción sobre supresiones pasa
    # sin haber juzgado una sola. Ya me pasó con este mismo archivo: el bloque
    # entraba con viñetas donde la regla pide filas de tabla, el validador no
    # veía nada, y el test de la supresión fresca daba verde.
    if expect_suppression:
        assert "no suppressions to age" not in r.stdout, \
            "el validador no vio ninguna supresión, así que nada de lo que sigue juzgó una"
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


def test_a_suppression_written_within_six_months_passes(tmp_path):
    fresh = datetime.date.today() - datetime.timedelta(days=30)
    ahead = datetime.date.today() + datetime.timedelta(days=120)
    _, refused = _sast(tmp_path, _with(_template(), _suppression(fresh.isoformat(), ahead.isoformat())),
                        expect_suppression=True)
    assert not any("F-SAST-19" in ln for ln in refused), \
        "una supresión de hace un mes fue rechazada por vieja: " + "\n".join(refused)


def test_a_suppression_older_than_six_months_is_refused_however_its_review_date_reads(tmp_path):
    """La regla es sobre la EDAD, y `Date` se leía sólo para ver si estaba vacío.
    Una supresión escrita hace dos años con una fecha de revisión en el futuro
    pasaba las dos reglas siendo vieja — y una supresión es exactamente el lugar
    donde alguien decidió que un hallazgo de seguridad no importa."""
    old = datetime.date.today() - datetime.timedelta(days=400)
    ahead = datetime.date.today() + datetime.timedelta(days=365)
    _, refused = _sast(tmp_path, _with(_template(), _suppression(old.isoformat(), ahead.isoformat())),
                        expect_suppression=True)
    assert any("F-SAST-19" in ln for ln in refused), \
        ("una supresión de hace más de un año pasó porque su fecha de revisión está en el "
         "futuro: " + ("\n".join(refused) or "no refusals at all"))
    assert any("six months" in ln or "over six" in ln for ln in refused), \
        "el rechazo no dice por qué: " + "\n".join(refused)


def test_the_report_the_skill_teaches_passes_as_written(tmp_path):
    """Sin esto, todo lo de arriba mide contra un documento que ya era inválido
    por otra razón, y "no salió F-SAST-19" no querría decir nada."""
    r, refused = _sast(tmp_path, _template())
    assert r.returncode == 0 and not refused, \
        "el reporte que ddw-security-sast le dice al modelo que escriba es rechazado: " + \
        ("\n".join(refused) or r.stderr[-200:])


# ── Las reglas que deciden si un documento vacío gana una compuerta ──────────
#
# Ocho de éstas sobrevivían a las 554 comprobaciones de la suite. Ninguna de las
# reglas que nombran (F-TM-05, F-TM-06, F-TEST-05, F-TEST-06, F-SPEC-10,
# F-SPEC-11) aparecía una sola vez en `verify_install.sh`: existen en el
# catálogo, están implementadas, y nada probaba que se pudieran disparar.
#
# Cada test hace lo mismo, en este orden: comprueba que el documento SANO pasa,
# planta UNA violación, y exige el ❌ con su ID. El primer paso no es ceremonia
# — sin él, un documento que ya era inválido por otra razón haría pasar el test
# sin que la regla en cuestión hubiera opinado nada.

def _worked(skill, heading, ticket="T-1"):
    text = open(os.path.join(ROOT, "skills", skill, "SKILL.md"), encoding="utf-8").read()
    at = text.index(heading)
    m = re.search(r"```markdown\n(.*?)```", text[at:], re.S)
    assert m, f"{skill} ya no trae un documento trabajado bajo {heading!r}"
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


# ── El modelo de amenazas ────────────────────────────────────────────────────

THREAT = "### The threat model, in the shape the validator reads"


def _spec_arg(tmp_path):
    """El modelo de amenazas se comprueba CONTRA el diseño real; sin la spec,
    F-TM-06 refusa por no poder leerla y el documento sano nunca pasa."""
    path = tmp_path / "spec-T-1.md"
    # Los componentes salen del propio modelo trabajado: una spec escrita a mano
    # acá nombraría otros archivos, y F-TM-06 —que es justo la regla que se está
    # midiendo— rechazaría el documento sano por no coincidir con ella.
    worked = _worked("ddw-threat-modeling", THREAT)
    files = re.findall(r"`([\w./-]+\.\w+)`", worked)
    assert files, "el modelo trabajado no nombra ningún archivo"
    blocks = "".join("## Block %d — %s\n- `%s` — the component\n- POST /api/%d\nCovers FR-0%d.\n\n"
                     % (i, os.path.basename(f), f, i, i)
                     for i, f in enumerate(dict.fromkeys(files), 1))
    path.write_text("# Spec T-1\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n\n" + blocks,
                    encoding="utf-8")
    return "--spec", str(path)


def test_a_threat_model_that_names_nothing_from_its_design_is_refused(tmp_path):
    """F-TM-06. Un modelo que no cita ni un archivo, ni un endpoint, ni un FR de
    su spec es una redacción sobre un sistema imaginario: puede ser impecable y
    no decir nada sobre este código."""
    base = _worked("ddw-threat-modeling", THREAT)
    r, refused = _validate(tmp_path, "validate_threat.py", "threat-T-1.md", base, *_spec_arg(tmp_path))
    assert r.returncode == 0 and not refused, \
        "el modelo que el skill enseña ya no pasa, así que lo de abajo no mide nada: " + \
        ("\n".join(refused) or r.stderr[-200:])
    generic = re.sub(r"`[\w./-]+\.(py|ts|js|go|rb)`", "the public API", base)
    assert generic != base, "la sonda no cambió nada"
    _, refused = _validate(tmp_path, "validate_threat.py", "threat-T-2.md", generic, *_spec_arg(tmp_path))
    assert _refuses(refused, "F-TM-06"), \
        "un modelo que no nombra nada del diseño ganó la compuerta: " + "\n".join(refused)


def test_a_design_handling_sensitive_data_classifies_it(tmp_path):
    """F-TM-05. Sin la tabla, F-TM-07 dice «no PII to encrypt» y el documento
    sale limpio: la ausencia de la clasificación se lee como ausencia de datos
    sensibles, que es lo contrario de lo que pasó."""
    base = _worked("ddw-threat-modeling", THREAT)
    assert "## Data classification" in base, "el modelo trabajado ya no trae la tabla"
    cut = re.split(r"^## Data classification\s*$", base, flags=re.M)[0]
    tail = re.split(r"^## Risks and mitigations\s*$", base, flags=re.M)
    body = cut + "\n## Risks and mitigations\n" + tail[1] if len(tail) > 1 else cut
    assert "email" in body or "password" in body or "token" in body, \
        "sin una palabra sensible en el resto del documento la regla no tiene qué mirar"
    _, refused = _validate(tmp_path, "validate_threat.py", "threat-T-3.md", body, *_spec_arg(tmp_path))
    assert _refuses(refused, "F-TM-05"), \
        "un diseño con datos sensibles pasó sin clasificar ninguno: " + "\n".join(refused)


def test_a_threat_model_written_in_spanish_is_not_told_it_skipped_a_category(tmp_path):
    """El método manda escribir los artefactos en el idioma del usuario, así que
    los alias existen para documentos reales. Sin ellos, un modelo completo en
    castellano es rechazado por una categoría que analizó."""
    base = _worked("ddw-threat-modeling", THREAT)
    es = (base.replace("**Elevation of Privilege:**", "**Elevación de privilegios:**")
              .replace("**Spoofing:**", "**Suplantación:**")
              .replace("**Repudiation:**", "**Repudio:**"))
    assert es != base, "la sonda no tradujo ninguna etiqueta"
    r, refused = _validate(tmp_path, "validate_threat.py", "threat-T-4.md", es, *_spec_arg(tmp_path))
    assert not _refuses(refused, "F-TM-01"), \
        "un modelo completo escrito en castellano fue reportado como incompleto: " + \
        "\n".join(refused)


# ── El reporte de tests ──────────────────────────────────────────────────────

TESTS_DOC = "### The report, in the shape the validator reads"


def test_a_report_cannot_pick_a_floor_it_can_clear(tmp_path):
    """F-TEST-05 + F-TEST-04. El piso lo fija el proyecto; un reporte que cita
    uno más bajo que el mínimo del pipeline y se compara contra ÉSE se aprueba
    solo. El ⚠️ queda, y un warning no detiene nada."""
    base = _worked("ddw-test", TESTS_DOC)
    r, refused = _validate(tmp_path, "validate_tests.py", "tests-T-1.md", base)
    assert r.returncode == 0 and not refused, \
        "el reporte que el skill enseña ya no pasa: " + ("\n".join(refused) or r.stderr[-200:])
    low = re.sub(r"^\| Coverage floor \|.*$", "| Coverage floor | 20% (AGENTS.md) |",
                 base, flags=re.M)
    low = re.sub(r"^\| (Line|Branch|Function) coverage \|.*$",
                 lambda m: "| %s coverage | 31%% |" % m.group(1), low, flags=re.M)
    assert low != base, "la sonda no bajó ni el piso ni la cobertura"
    _, refused = _validate(tmp_path, "validate_tests.py", "tests-T-2.md", low)
    assert _refuses(refused, "F-TEST-04"), \
        ("un reporte con 31% de cobertura se aprobó eligiendo un piso de 20%: "
         + ("\n".join(refused) or "no refusals at all"))


def test_a_report_that_states_no_floor_is_refused_not_given_one(tmp_path):
    """F-TEST-05. Heredar el default del flag en silencio hace que el documento
    quede graduado contra un número que nadie escribió en él."""
    base = _worked("ddw-test", TESTS_DOC)
    nofloor = re.sub(r"^\| Coverage floor \|.*\n", "", base, flags=re.M)
    assert nofloor != base, "el reporte trabajado ya no declara un piso"
    _, refused = _validate(tmp_path, "validate_tests.py", "tests-T-3.md", nofloor)
    assert _refuses(refused, "F-TEST-05"), \
        "un reporte sin piso pasó contra uno que DDW le inventó: " + "\n".join(refused)


def test_a_skipped_test_owes_a_reason(tmp_path):
    """F-TEST-06. Saltear es la forma más barata de poner una suite en verde, y
    un skip sin motivo es indistinguible de uno que tapa una falla."""
    base = _worked("ddw-test", TESTS_DOC)
    # El reporte trabajado no saltea nada, así que el caso hay que PLANTARLO:
    # dos tests omitidos y ni una línea que diga por qué.
    mute = re.sub(r"^\| Skipped \|.*$", "| Skipped | 2 |", base, flags=re.M)
    mute = re.sub(r"^\| Passed \| (\d+) \|$",
                  lambda m: "| Passed | %d |" % (int(m.group(1)) - 2), mute, flags=re.M)
    mute = re.sub(r"^## Skips\n\(none\)\s*$",
                  "## Skips\n- `tests/test_auth.py::test_expiry`\n- `tests/test_auth.py::test_refresh`",
                  mute, flags=re.M)
    assert "## Skips\n- " in mute and "| Skipped | 2 |" in mute, \
        "la sonda no plantó los dos skips mudos"
    _, refused = _validate(tmp_path, "validate_tests.py", "tests-T-4.md", mute)
    assert _refuses(refused, "F-TEST-06"), \
        "dos tests omitidos sin una línea de motivo pasaron: " + \
        ("\n".join(refused) or "no refusals at all")


def test_a_real_run_of_a_thousand_tests_is_not_refused_for_its_punctuation(tmp_path):
    """La dirección inversa, que es la que cuesta más caro: todo runner imprime
    el separador de miles, y sin quitarlo `1,204` se lee como `1`. La compuerta
    rechaza el documento VERDADERO, y el autor no tiene nada que corregir."""
    base = _worked("ddw-test", TESTS_DOC)
    big = base
    for field, value in (("Total", "1,204"), ("Passed", "1,202"),
                         ("Failed", "0"), ("Skipped", "2")):
        big = re.sub(r"^\| %s \|.*$" % field, "| %s | %s |" % (field, value), big, flags=re.M)
    assert big != base, "la sonda no cambió los conteos"
    r, refused = _validate(tmp_path, "validate_tests.py", "tests-T-5.md", big)
    assert not _refuses(refused, "F-TEST-02"), \
        ("una corrida real de 1.204 tests fue rechazada por su propia puntuación: "
         + "\n".join(refused))


# ── La spec ──────────────────────────────────────────────────────────────────

def _fixture(marker, tag):
    """Un documento sano de la suite. El skill de spec trae una PLANTILLA con
    placeholders, no un documento trabajado, así que el único ejemplo completo
    que existe está ahí. Leído, no copiado: copiarlo sería una tercera versión
    de la misma forma."""
    suite = open(os.path.join(ROOT, "scripts/verify_install.sh"), encoding="utf-8").read()
    at = suite.index(marker)
    end = suite.index("\n" + tag, at)
    return suite[suite.index("\n", at) + 1:end]


def _spec():
    return _fixture('cat > "$VS/spec-FEAT-001.md" <<\'SPECEOF\'', "SPECEOF")


def _prd(tmp_path):
    """La spec se valida CONTRA su PRD; sin él no se comprueba la cobertura y el
    documento sano es rechazado por una razón que no es la que se está midiendo."""
    body = _fixture('cat > "$VP/docs/ddw/prd/prd-FEAT-001.md" <<\'PRDEOF\'', "PRDEOF")
    path = tmp_path / "prd-FEAT-001.md"
    path.write_text(body, encoding="utf-8")
    return "--prd", str(path)


def test_a_spec_block_owes_what_can_go_wrong_with_it(tmp_path):
    """F-SPEC-10. Con cero errores documentados, F-SPEC-16 tampoco tapa el
    agujero: comparar los caminos tristes contra una lista vacía no compara
    nada."""
    base = _spec()
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md", base, *_prd(tmp_path))
    assert r.returncode == 0 and not refused, \
        "la spec sana ya no pasa: " + ("\n".join(refused) or r.stderr[-200:])
    noerr = re.sub(r"^\*\*Error handling\*\*.*?(?=^\*\*|^## )", "", base, flags=re.M | re.S)
    assert noerr != base, "la spec sana ya no trae `**Error handling**`"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-002.md", noerr, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-10"), \
        "un bloque sin manejo de errores pasó: " + ("\n".join(refused) or "no refusals at all")


def test_a_spec_owes_the_order_its_blocks_run_in(tmp_path):
    """F-SPEC-11. Una sola vez para todo el documento, y sin ella el orden de
    ejecución queda sin declarar."""
    base = _spec()
    nodeps = re.sub(r"^## Dependencies between blocks.*?(?=^## )", "", base, flags=re.M | re.S)
    assert nodeps != base, "la spec sana ya no trae la sección de dependencias"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-003.md", nodeps, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-11"), \
        "una spec sin orden de ejecución declarado pasó: " + "\n".join(refused)
