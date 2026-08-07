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
