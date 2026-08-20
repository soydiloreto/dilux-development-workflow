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


# ── El ledger que registra por qué un check no puede fallar ──────────────────

def test_regenerar_el_ledger_conserva_la_razon_entera(tmp_path):
    """`--write` guardaba UNA línea de cada explicación, y las razones son de
    cinco o seis. Regenerar dejaba cuarenta y cuatro excusas cortadas a media
    frase, cada una todavía excusando su sitio: verde, y sin decir por qué."""
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
        "la razón se regeneraría truncada: %r" % entera
    assert "todas sus filas" in entera, "se perdió el final de la explicación"
    assert "check_dos" not in entera, "la razón se comió el ítem siguiente"
    assert lkm.existing_reason(ledger, "check_dos[1]").strip() == "Otra razón, de un solo renglón."
    assert lkm.existing_reason(ledger, "check_tres[0]") == "", \
        "un sitio sin razón escrita no puede inventarse una"


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


# Un bloque que no tiene errores propios. Medido en la ronda 6: la verdad no
# entraba en ningún lado —en prosa la rechaza F-SPEC-10, en bullet la cobra
# F-SPEC-16 pidiéndole un test— así que un bloque de render estático se inventó
# un 404 de otro bloque, con su test, para poner la compuerta en verde.

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
    """F-SPEC-10/16. La declaración satisface la regla y cuenta como CERO
    errores: si contara como uno, F-SPEC-16 le pediría un camino triste que el
    bloque no tiene, que es el callejón que obligó a inventar el error."""
    base = _spec()
    cuerpo = base.replace("\n## Rollback", QUIETO + "\n## Rollback")
    assert cuerpo != base, "la spec sana ya no trae `## Rollback` donde colgar el bloque"
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-030.md", cuerpo,
                           *_prd(tmp_path))
    assert r.returncode == 0 and not refused, \
        "un bloque que declara no tener errores fue rechazado: " + (
            "\n".join(refused) or r.stderr[-200:])


def test_la_declaracion_se_refusa_donde_no_puede_ser_cierta(tmp_path):
    """La otra mitad, y la que impide que sea una palabra mágica: el bloque sano
    recibe un formulario, y lo que llega puede llegar mal."""
    base = _spec()
    miente = re.sub(r"^\*\*Error handling\*\*\n(?:- .*\n)+",
                    "**Error handling**\n- Sin condiciones de error propias.\n",
                    base, flags=re.M)
    assert miente != base, "la spec sana ya no trae bullets de `**Error handling**`"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-031.md", miente,
                           *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-10"), \
        "un bloque con entrada declaró no tener errores y pasó: " + (
            "\n".join(refused) or "sin rechazos")


def test_a_spec_owes_the_order_its_blocks_run_in(tmp_path):
    """F-SPEC-11. Una sola vez para todo el documento, y sin ella el orden de
    ejecución queda sin declarar."""
    base = _spec()
    nodeps = re.sub(r"^## Dependencies between blocks.*?(?=^## )", "", base, flags=re.M | re.S)
    assert nodeps != base, "la spec sana ya no trae la sección de dependencias"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-003.md", nodeps, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-11"), \
        "una spec sin orden de ejecución declarado pasó: " + "\n".join(refused)


# ── Tres reglas de la spec que la suite tampoco ejecuta ──────────────────────
#
# Del mismo mapa de cobertura: `no_criterion`, `bad_api` y `bad_model` son ramas
# que la suite no toca ni una vez. Son las reglas que deciden si un bloque dice
# cuándo está terminado, si un endpoint trae su contrato y si un esquema declara
# sus restricciones — lo que separa una spec de una lista de intenciones.

def test_a_block_owes_a_verifiable_completion_criterion(tmp_path):
    """F-SPEC-05. Sin criterio, «terminado» es una opinión, y la fase que
    implementa el bloque no tiene contra qué medirse."""
    base = _spec()
    r, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md", base, *_prd(tmp_path))
    assert r.returncode == 0 and not refused, \
        "la spec sana ya no pasa: " + ("\n".join(refused) or r.stderr[-200:])
    cut = re.sub(r"^\*\*Completion criterion\*\*.*?(?=^\*\*|^## )", "", base, flags=re.M | re.S)
    assert cut != base, "la spec sana ya no trae `**Completion criterion**`"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-010.md", cut, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-05"), \
        "un bloque sin criterio de finalización pasó: " + ("\n".join(refused) or "sin rechazos")


def test_an_endpoint_owes_a_complete_contract(tmp_path):
    """F-SPEC-07. Un contrato al que le falta el código de error o la
    autenticación es el que se descubre en producción."""
    base = _spec()
    if "API contract" not in base:
        pytest.skip("la spec sana no declara un contrato de API que recortar")
    # La etiqueta va sola en su línea y el contenido debajo, hasta la siguiente
    # etiqueta en negrita: reemplazar sólo la línea del rótulo no recorta nada.
    partial = re.sub(r"(?ms)^\*\*API contract\*\*.*?(?=^\*\*|^## )",
                     "**API contract**\n- POST /api/x — request body, response 200\n\n",
                     base, count=1)
    assert partial != base, "la sonda no recortó la sección de contrato"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-011.md", partial,
                           *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-07"), \
        ("un contrato sin códigos de error ni autenticación pasó: "
         + ("\n".join(refused) or "sin rechazos"))


# ── El ADR ──────────────────────────────────────────────────────────────────
#
# El único artefacto que no tenía comprobación, y por eso el único cuyo género
# dependía de que el modelo ya lo supiera. La regla que importa es F-ADR-03: un
# ADR explica una decisión ya tomada y no obliga a nada.

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
    assert r.returncode == 0, "el ADR sano fue rechazado: " + "\n".join(refused)


def test_un_adr_que_manda_es_rechazado(tmp_path):
    """F-ADR-03, la regla por la que existe este validador. Una obligación acá
    es un requerimiento que ningún criterio de aceptación cubre y ninguna
    compuerta lee, compitiendo con la spec por la autoridad sobre el código."""
    manda = ADR_SANO.replace("Se eligió el límite en proceso: 5 altas por IP cada 10 minutos.",
                             "El sistema debe limitar a 5 altas por IP cada 10 minutos.")
    _, refused = _adr(tmp_path, manda)
    assert _refuses(refused, "F-ADR-03"), \
        "un ADR que impone pasó: " + ("\n".join(refused) or "sin rechazos")


def test_una_obligacion_citada_no_es_del_adr(tmp_path):
    """El mismo verbo, dicho por otro documento. Leer una cita como voz propia
    convertía la regla más filosa del catálogo en la más ruidosa."""
    citando = ADR_SANO.replace("## Consequences",
                               "## Consequences\n\n> El PRD dice: el sistema debe responder en 3 s.\n")
    r, refused = _adr(tmp_path, citando)
    assert not _refuses(refused, "F-ADR-03"), \
        "una obligación citada se leyó como propia: " + "\n".join(refused)
    assert r.returncode == 0


def test_una_sola_opcion_no_es_una_decision(tmp_path):
    """F-ADR-02. Una opción es una preferencia; registrarla como decisión es
    cómo una preferencia adquiere la autoridad de una."""
    sola = re.sub(r"(?s)### Option 2.*?(?=## Decision)", "", ADR_SANO)
    _, refused = _adr(tmp_path, sola)
    assert _refuses(refused, "F-ADR-02"), \
        "un ADR con una sola opción pasó: " + ("\n".join(refused) or "sin rechazos")


def test_dos_decisiones_no_comparten_numero(tmp_path):
    """F-ADR-05. El número es la identidad del documento: es como un sucesor
    nombra lo que reemplaza."""
    _adr(tmp_path, ADR_SANO, "adr-001-limite.md")
    _, refused = _adr(tmp_path, ADR_SANO, "adr-001-otra.md")
    assert _refuses(refused, "F-ADR-05"), \
        "dos ADR con el mismo número pasaron: " + ("\n".join(refused) or "sin rechazos")


# ── El split ────────────────────────────────────────────────────────────────
#
# El protocolo REEMPLAZA al padre por un índice, así que la lista de criterios
# del original desaparece en el momento en que el split aterriza. F-PRD-10 es el
# único lugar donde se puede preguntar si las partes cubren el todo.

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
    assert r.returncode == 0, "el índice sano fue rechazado: " + "\n".join(refused)


def test_un_criterio_que_no_se_lleva_nadie_es_rechazado(tmp_path):
    """F-PRD-10. Es la única pérdida que el split puede causar y que después
    no se puede detectar desde ningún lado: el original ya no existe."""
    _, refused = _indice(tmp_path, INDICE.replace("| AC-06 | depends on b", "|  | depends on b"))
    assert _refuses(refused, "F-PRD-10"), \
        "un split que dejó un AC afuera pasó: " + ("\n".join(refused) or "sin rechazos")


def test_un_criterio_en_dos_sub_tickets_es_rechazado(tmp_path):
    """El mismo AC reclamado dos veces: dos tickets creen que les toca, y en
    VERIFY cada uno espera que lo cubra el otro."""
    _, refused = _indice(tmp_path, INDICE.replace("AC-04, AC-05", "AC-03, AC-04, AC-05"))
    assert _refuses(refused, "F-PRD-10"), \
        "un AC duplicado entre hijos pasó: " + ("\n".join(refused) or "sin rechazos")


def test_un_indice_que_reparte_mas_de_lo_que_declara_es_rechazado(tmp_path):
    """F-PRD-10. El número lo escribe el modelo y no se comparaba con NADA, ni
    con las filas de abajo. Medido: un índice declaró 22 donde el documento de
    origen tenía 17 —cinco decididos con el usuario en DEFINE— y el recibo salió
    certificando «los 22 del original»."""
    de_mas = INDICE.replace("| AC-06 | depends on b", "| AC-06, AC-07 | depends on b")
    assert de_mas != INDICE, "el índice sano ya no reparte AC-06 en la fila de c"
    _, refused = _indice(tmp_path, de_mas)
    assert _refuses(refused, "F-PRD-10"), \
        "un índice que declara 6 y reparte 7 pasó: " + ("\n".join(refused) or "sin rechazos")


def test_el_recibo_del_split_no_habla_del_original(tmp_path):
    """Lo que la regla mide es que las partes se reparten lo que el índice pone
    sobre la mesa. Decir «del original» sobre criterios que nacieron en DEFINE
    es certificar algo que no se comprobó."""
    r, _ = _indice(tmp_path, INDICE)
    fila = [ln for ln in r.stdout.splitlines() if "F-PRD-10" in ln]
    assert fila and "of the original" not in fila[0], \
        "el recibo sigue afirmando el origen de los criterios: %r" % fila


def test_un_indice_sin_el_total_a_cubrir_es_rechazado(tmp_path):
    """Sin ese número la pregunta no se puede contestar, y el documento contra
    el que se contestaría ya fue sobrescrito."""
    sin = "\n".join(l for l in INDICE.splitlines() if "criteria to cover" not in l)
    _, refused = _indice(tmp_path, sin)
    assert _refuses(refused, "F-PRD-10"), \
        "un índice sin el total pasó: " + ("\n".join(refused) or "sin rechazos")


def test_un_indice_que_no_declara_ni_reparte_nada_es_rechazado(tmp_path):
    """El mismo F-PRD-10 en el único caso que las filas no alcanzan a cubrir.

    Sin el total, el reparto de abajo se compara contra el conjunto vacío: nada
    falta, nada sobra, y un índice a medio escribir sale con recibo verde
    diciendo que sus «0 criterios» los toma exactamente un sub-ticket cada uno.
    El índice ya reemplazó al padre, así que ese verde se da sobre una lista de
    criterios que en ese momento no existe en ningún lado.
    """
    vacio = "\n".join(l for l in INDICE.splitlines()
                       if "criteria to cover" not in l and not l.startswith("| FEAT-001"))
    assert "AC-01" not in vacio and "criteria to cover" not in vacio, \
        "el índice de prueba todavía declara o reparte algo, que es lo contrario del caso"
    r, refused = _indice(tmp_path, vacio)
    assert _refuses(refused, "F-PRD-10"), \
        ("un índice que no declara ni reparte nada pasó con recibo verde:\n" + r.stdout)


def test_un_sub_prd_mas_grande_que_el_umbral_avisa(tmp_path):
    """W-PRD-06. El split que no achicó nada: aviso, nunca bloqueo — quedarse
    con el ticket entero es decisión del usuario, pero el número no es suyo
    para perderlo."""
    base = _worked("ddw-create-prd", "## PRD Template")
    extra = "\n".join("- AC-%02d (FR-01): WHEN algo pasa, THE sistema SHALL responder." % n
                      for n in range(4, 13))
    grande = base.replace("- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].",
                          "- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].\n" + extra)
    r, _ = _validate(tmp_path, "validate_prd.py", "prd-FEAT-099.md", grande)
    assert "W-PRD-06" in r.stdout, \
        "un PRD de 12 ACs no dijo nada sobre el umbral:\n" + r.stdout[-400:]


# ── El gate del commit ──────────────────────────────────────────────────────
#
# `git commit` era el único acto del pipeline que ningún hook juzgaba: el
# matcher del PreToolUse era Edit|Write|NotebookEdit y un commit es una llamada
# a Bash. Medido: cinco documentos commiteados y el usuario leyendo el hash
# después.

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
        "mostrar el mensaje y commitear pudieron pasar en la misma respuesta"


def test_un_commit_visto_y_contestado_pasa_al_primer_intento(tmp_path):
    """La primera versión rechazaba el PRIMER intento y cobraba un ida y vuelta
    incluso al modelo que había hecho todo bien."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0, "el commit aprobado fue rechazado igual"


def test_mostrar_un_mensaje_y_commitear_otro_es_rechazado(tmp_path):
    """El agujero que no cerraba nadie: los bytes se comparan."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    _propone(tmp_path, "\U0001F4DD docs: otra cosa completamente distinta\n")
    assert _commit(tmp_path).returncode == 2, "commiteó un mensaje que el usuario nunca vio"


def _post(tmp_path):
    """El PostToolUse que corre después de cada Bash — consumidor del permiso."""
    return subprocess.run([sys.executable, GATE, "--mode", "post",
                           "--state", str(tmp_path / ".ddw-state.json"),
                           "--graph", GRAPH_PATH, "--repo", str(tmp_path)],
                          input="{}", capture_output=True, text=True)


def _git_commitea(tmp_path, mensaje=MENSAJE):
    """Un commit real con los bytes aprobados, como lo dejaría `git commit -F`."""
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
    """Gastarlo al PERMITIR era el defecto: el permiso lo gasta el commit en HEAD."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0
    _git_commitea(tmp_path)          # el commit aprobado landeó de verdad
    _post(tmp_path)                  # exit code ajeno: acá solo importa el consumo
    assert _commit(tmp_path).returncode == 2, "un mensaje ya commiteado abrió el commit siguiente"


def test_un_commit_que_fallo_no_gasta_el_permiso(tmp_path):
    """El gate permitió, git falló (GPG sin TTY, pre-commit, índice vacío): la
    aprobación tiene que seguir en pie y el reintento pasar sin otro turno.
    La primera versión borraba proposal y sello al permitir, el modelo
    encontraba `.ddw-work/` vacío, reescribía los mismos bytes y era rechazado
    como nunca-visto. Medido, en la primera corrida manual que llegó acá."""
    _repo_en_define(tmp_path)
    _propone(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _commit(tmp_path).returncode == 0
    _git_commitea(tmp_path, "otro mensaje: el aprobado nunca llegó a HEAD")
    _post(tmp_path)                  # corre igual tras el Bash fallido
    assert (tmp_path / PROPOSAL).exists(), "el post consumió un permiso que ningún commit gastó"
    assert _commit(tmp_path).returncode == 0, \
        "el reintento del commit aprobado fue rechazado: el gate se comió la aprobación"


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


# ── Las reglas que pasaban en vacío ──────────────────────────────────────────
#
# El patrón medido en la ronda 4: una regla cuyo parser extrae cero elementos
# reportaba "all 0 ... " y daba verde. Un check que midió nada no avala nada.

def test_un_prd_cuyos_ids_no_parsean_no_pasa_la_bateria(tmp_path):
    """F-PRD-05: "0 FR, 0 NFR, 0 AC — unique, gapless" era PASS, y con las
    listas vacías F-PRD-01/03/06/09 pasaban también."""
    body = _fixture('cat > "$VP/docs/ddw/prd/prd-FEAT-001.md" <<\'PRDEOF\'', "PRDEOF")
    sin_ids = body.replace("FR-", "Req ").replace("NFR-", "NReq ").replace("AC-", "Crit ")
    r, refused = _validate(tmp_path, "validate_prd.py", "prd-FEAT-002.md", sin_ids)
    assert _refuses(refused, "F-PRD-05"), \
        "un PRD sin un solo ID parseable pasó la batería entera: " + "\n".join(refused)


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
        "una spec validó cobertura contra un PRD que parsea vacío: " + "\n".join(refused)


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
    """F-VER-06: la skill de spec emite `test_x` con backticks y la regex leía
    cero — "all 0 test(s) the spec promised" fue verde en una corrida real que
    tenía 13 prometidos y 3 ausentes del reporte."""
    rows = _f_ver_06(tmp_path, "# V\nblock 1: test_uno y test_dos verificados\n",
                     SPEC_BACKTICKS)
    assert rows and "✅" in rows[0] and "2 test(s)" in rows[0], \
        "los nombres con backticks siguen invisibles: %r" % rows


# Las dos mitades del fix se tapan entre sí si se las mide con el mismo
# documento: acotar a `Required tests` esconde que la ruta se filtra, y filtrar
# la ruta esconde que se lee de más. Un fixture por mitad, o la mutación que
# reinyecta cada una sobrevive sobre la defensa de la otra.

SPEC_RUTA_PROMETIDA = ("# Spec\n\n## Block 1 — x\n"
                       "**Required tests**\n"
                       "- [ ] `test_uno` — valida AC-01\n"
                       "- [ ] `test_dos` — valida AC-02\n"
                       "- [ ] `tests/fakes.py` — el doble del repositorio\n")


def test_una_ruta_de_archivo_no_es_un_test_prometido(tmp_path):
    """F-VER-06. `tests/fakes.py` no tiene un solo test, y contarlo infló la
    cuenta: la ronda 6 midió "all 19 test(s) the spec promised" sobre una spec
    que prometía 16. El ❌ previo se cerró agregando los NOMBRES DE ARCHIVO al
    reporte — justo lo que la regla malleía. Escrito DENTRO de `Required tests`
    a propósito: acotar la búsqueda no alcanza para esto."""
    rows = _f_ver_06(tmp_path, "# V\nblock 1: test_uno y test_dos verificados\n",
                     SPEC_RUTA_PROMETIDA)
    assert rows and "✅" in rows[0] and "2 test(s)" in rows[0], \
        "una ruta de archivo sigue contando como test prometido: %r" % rows


SPEC_NOMBRE_FUERA = ("# Spec\n\n## Block 1 — x\n"
                     "**Required tests**\n- [ ] `test_uno` — valida AC-01\n"
                     "## Rollback\n- `test_smoke_legacy` queda como estaba\n")


def test_un_test_nombrado_fuera_de_required_tests_no_es_una_promesa(tmp_path):
    """La otra mitad: la promesa vive en `Required tests` y en ningún otro lado.
    Leído el documento entero, un test que la spec MENCIONA —el de humo que
    queda igual tras el rollback— se vuelve una promesa que el reporte de
    verificación tiene que nombrar, y VERIFY refusa por algo que nadie
    prometió."""
    rows = _f_ver_06(tmp_path, "# V\nblock 1: test_uno verificado\n", SPEC_NOMBRE_FUERA)
    assert rows and "✅" in rows[0] and "1 test(s)" in rows[0], \
        "un test nombrado fuera de Required tests se cobró como promesa: %r" % rows


def test_un_test_prometido_ausente_del_reporte_refusa(tmp_path):
    rows = _f_ver_06(tmp_path, "# V\nblock 1: solo test_uno\n", SPEC_BACKTICKS)
    assert rows and "❌" in rows[0] and "test_dos" in rows[0], \
        "un test prometido y ausente pasó: %r" % rows


def test_required_tests_ilegibles_no_es_un_pass(tmp_path):
    """La mitad honesta del fix: si hay secciones Required tests y el parser
    extrae cero nombres, eso es un NO — no un "all 0" en verde."""
    spec = "# Spec\n**Required tests**\n- [ ] «prueba_uno» — nombre sin formato\n"
    rows = _f_ver_06(tmp_path, "# V\n", spec)
    assert rows and "❌" in rows[0], \
        "una spec con promesas ilegibles avaló el reporte: %r" % rows


# ── El gate del merge ────────────────────────────────────────────────────────
#
# El único acto del pipeline que sale del repo y que nadie acá puede revertir
# corría sin que ningún hook lo viera; la elección llegaba por picker, que
# ningún hook recibe. Mismo diseño que el gate del commit — proposal + sello —
# con la diferencia que el acto exige: rige en AMBOS modos de autonomía.

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
    assert _merge(tmp_path).returncode == 2, "un merge corrió sin que nadie lo viera"


def test_un_merge_visto_y_contestado_pasa(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _merge(tmp_path).returncode == 0, "el merge aprobado fue rechazado igual"


def test_minimal_no_exime_al_merge(tmp_path):
    """La frase que la prosa dijo siempre y nada sostenía: el merge conserva su
    confirmación en ambos modos."""
    _repo_en_define(tmp_path, autonomy="minimal")
    assert _merge(tmp_path).returncode == 2, \
        "minimal eximió al acto que la prosa dice que nunca exime"


def test_un_merge_propuesto_en_el_mismo_turno_es_rechazado(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    assert _merge(tmp_path).returncode == 2, \
        "mostrar la propuesta y mergear pudieron pasar en la misma respuesta"


def test_un_merge_fallido_no_gasta_la_aprobacion(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _merge(tmp_path).returncode == 0
    _post_hook(tmp_path, env=_gh_estado(tmp_path, "OPEN"))   # el merge NO landeó
    assert (tmp_path / MERGE_PROP).exists(), "el post consumió un merge que no existe"
    assert _merge(tmp_path).returncode == 0, "el reintento del merge aprobado fue rechazado"


def test_el_permiso_del_merge_se_gasta_cuando_el_forge_dice_merged(tmp_path):
    _repo_en_define(tmp_path)
    _propone_merge(tmp_path)
    _habla_el_usuario(tmp_path)
    assert _merge(tmp_path).returncode == 0
    _post_hook(tmp_path, env=_gh_estado(tmp_path, "MERGED"))
    assert not (tmp_path / MERGE_PROP).exists(), "el post no consumió un merge landeado"
    assert _merge(tmp_path).returncode == 2, "una aprobación gastada abrió el merge siguiente"


# ── El instalador y la instalación sin commitear ─────────────────────────────

def test_sin_tty_el_instalador_avisa_que_la_instalacion_no_esta_commiteada(tmp_path):
    """La bomba de la ronda 4: instalación nunca commiteada → el primer closeout
    la barre adentro del PR de la feature (68 archivos). Sin terminal no puede
    preguntar, pero callarse era el defecto."""
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
        "el instalador dejó la instalación sin commitear y no dijo nada"


def test_instalar_en_un_directorio_sin_git_instala_y_avisa(tmp_path):
    """Regresión medida el mismo día del fix del installer: `set -euo pipefail`
    + una captura de git sin guardar = el instalador moría en rc 128 SIN
    IMPRIMIR UNA LÍNEA sobre un destino no-git. Instalar debe funcionar, y el
    aviso debe existir: el pipeline branchea/commitea/abre PRs y el primer
    ticket muere en CLASSIFY si no hay git."""
    target = tmp_path / "nogit"
    target.mkdir()
    r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), str(target),
                        "--target", "claude", "--mode", "dropin"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert r.returncode == 0, "el instalador murió en un destino sin git: rc=%s %s" % (
        r.returncode, r.stderr[-200:])
    assert (target / ".ddw" / "orchestrator.md").exists(), "no instaló nada"
    assert "not a git repository" in r.stdout, \
        "instaló en silencio donde el primer ticket va a morir en CLASSIFY"


# ── El flujo git del instalador (DDW_GIT_FLOW es la ortografía sin terminal) ─

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
        "eligió rama setup y quedó en %r" % _rama(r)
    assert _sucios(r) == 0, "la instalación no quedó commiteada en la rama setup"
    assert "stays local" in res.stdout, "no dijo qué pasa con la rama sin push"


def test_flow_current_commitea_en_la_rama_actual(tmp_path):
    r = _repo_para_instalar(tmp_path)
    res = _instala(r, "current")
    assert res.returncode == 0, res.stderr[-300:]
    assert _rama(r) in ("main", "master"), "se movió de rama sin que nadie lo pida"
    assert _sucios(r) == 0, "eligió commit en la rama actual y quedó sin commitear"


def test_flow_none_deja_los_archivos_sin_commitear(tmp_path):
    r = _repo_para_instalar(tmp_path)
    res = _instala(r, "none")
    assert res.returncode == 0, res.stderr[-300:]
    assert _sucios(r) > 0, "eligió no commitear y algo commiteó igual"
    assert "nothing committed" in res.stdout, "no dijo que quedó sin commitear"


def test_un_git_init_sin_commits_ofrece_el_primer_commit(tmp_path):
    r = _repo_para_instalar(tmp_path, con_commit=False)
    res = _instala(r, "setup")   # pide setup, pero sin base no hay rama posible
    assert res.returncode == 0, res.stderr[-300:]
    assert "no commits yet" in res.stdout, "no explicó por qué no hay pregunta de rama"
    assert _sucios(r) == 0, "el primer commit del repo no se hizo"


# ── El vocabulario de caminos tristes lee palabras reales (F-SPEC-16) ────────

_BULLET_VIVO = "- [ ] test_email_invalido_devuelve_422 — email con formato invalido"


def test_un_test_que_dice_rechazado_cuenta_como_camino_triste(tmp_path):
    """Regresión de la ronda 5: `rechaz` seguido de `\\b` no matchea ninguna
    forma escrita ("rechazado", "rechaza"), y la spec real terminó cambiando su
    vocabulario para complacer al validador. El gate no legisla palabras."""
    base = _spec()
    probe = base.replace(
        _BULLET_VIVO,
        "- [ ] test_email_mal_formado_es_devuelto — el email mal formado es rechazado")
    assert probe != base, "la sonda no cambió el bullet"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md",
                           probe, *_prd(tmp_path))
    assert not _refuses(refused, "F-SPEC-16"), \
        '"rechazado" no cuenta como camino triste: ' + "\n".join(refused)


def test_la_palabra_triste_en_la_segunda_linea_del_bullet_cuenta(tmp_path):
    """La otra mitad de la misma regresión: un checkbox envuelto a dos líneas
    dejaba la palabra clave fuera del conteo — el ítem se lee entero."""
    base = _spec()
    probe = base.replace(
        _BULLET_VIVO,
        "- [ ] test_email_mal_formado_es_devuelto — el email mal formado\n"
        "      es rechazado con un aviso por campo")
    assert probe != base, "la sonda no cambió el bullet"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md",
                           probe, *_prd(tmp_path))
    assert not _refuses(refused, "F-SPEC-16"), \
        "la palabra triste en la continuación del bullet no contó: " + "\n".join(refused)


def test_dos_errores_con_un_solo_test_triste_siguen_refusados(tmp_path):
    """La dirección que impide aflojar el matcher hasta que matchee todo: un
    test de camino feliz no paga la deuda de un error documentado."""
    base = _spec()
    probe = base.replace(
        _BULLET_VIVO,
        "- [ ] test_email_guardado — el email se persiste normalizado")
    assert probe != base, "la sonda no cambió el bullet"
    _, refused = _validate(tmp_path, "validate_spec.py", "spec-FEAT-001.md",
                           probe, *_prd(tmp_path))
    assert _refuses(refused, "F-SPEC-16"), \
        "dos errores documentados con un solo test triste pasaron: " + \
        ("\n".join(refused) or "sin refusals")


# ── El commit de instalación tiene que llegar al remoto ──────────────────────

def _con_remoto(r, tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(r), "remote", "add", "origin", str(bare)],
                   check=True)
    subprocess.run(["git", "-C", str(r), "push", "-q", "-u", "origin", "HEAD"],
                   check=True)
    return bare


def test_flow_current_con_remoto_avisa_que_el_commit_debe_llegar_al_remoto(tmp_path):
    """Ronda 5: la instalación commiteada en el main LOCAL y nunca pusheada
    terminó como 66 archivos de framework en el PR de la feature. Si el user
    no pushea acá, el aviso tiene que ser imposible de no ver."""
    r = _repo_para_instalar(tmp_path)
    _con_remoto(r, tmp_path)
    res = _instala(r, "current", push="n")
    assert res.returncode == 0, res.stderr[-300:]
    assert "YOU MUST GET IT ONTO YOUR DEFAULT" in res.stdout, \
        "el commit quedó solo local y el instalador no gritó nada"


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
        "dijo que pusheaba y el remoto no tiene el commit de instalación"


# ── Un shard sin mutaciones del diff es una respuesta, no una falla ──────────

def test_un_shard_sin_mutaciones_del_diff_contesta_vacio_y_no_muere(tmp_path):
    """Medido en los PRs de dependabot: un diff que tocaba 3 mutaciones dejó a
    los otros 21 shards con selección vacía, y la guardia anti-"medí nada" los
    mató en rojo. Un shard sin trabajo en un run shardeado con --changed es una
    respuesta ordinaria — los shards que sí las tienen contestan la pregunta."""
    spec_ = importlib.util.spec_from_file_location(
        "mut_shard", os.path.join(ROOT, "scripts/mutate.py"))
    mut = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mut)
    objetivo = "ddw/rules/define.instructions.md"
    tocadas = {i for i, (_l, m) in enumerate(mut.MUTATIONS, 1)
               if getattr(m, "probe", None) is None or m.probe[1] == objetivo}
    assert tocadas, "ningún fault nombra el archivo del escenario"
    n = 24
    vacios = [s for s in range(1, n + 1)
              if not tocadas & set(mut.slice_of("%d/%d" % (s, n), len(mut.MUTATIONS)))]
    assert vacios, "el diff del escenario toca mutaciones en los 24 shards; elegir otro archivo"
    # Un repo sintético mínimo: el runner solo necesita existir en un git cuyo
    # último commit toque el archivo del escenario. Nada de clonar ROOT — la
    # suite de mutaciones corre estos tests dentro de una copia SIN .git, y un
    # clone de esa copia moría en 128 antes de medir nada.
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
        "el shard sin trabajo murió en rojo otra vez: " + (r.stdout + r.stderr)[-300:]
    assert "holds none of the" in r.stdout, \
        "el shard vacío no dijo por qué no inyectó nada: " + r.stdout[-300:]
