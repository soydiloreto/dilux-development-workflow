"""The walk's conductor: one verdict, decided over the forge's answers.

`decide()` is a pure function and these tests pin its order of questions:
a stale index row (child merged, row not done) outranks everything; a next
is offered only when every dependency is MERGED at the forge — never on
another row's recorded status; blocked rows name their blockers; and only
done/declared rows count as out of play.
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "fnx", os.path.join(ROOT, "ddw/scripts/family_next.py"))
fnx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fnx)

vt_spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(ROOT, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(vt_spec)
vt_spec.loader.exec_module(vt)


def rows(*specs):
    lines = ["| Repo | Ticket | Scope | Depends on | Status |",
             "|---|---|---|---|---|"]
    for repo, deps, status in specs:
        lines.append("| acme/%s | T-1 | la parte %s | %s | %s |"
                     % (repo, repo, deps, status))
    return vt.parse_family_rows("\n".join(lines) + "\n")


def test_el_primer_desbloqueado_gana_y_las_dependencias_las_decide_el_forge():
    rs = rows(("pagos", "none", "active"), ("back", "pagos", "pending"))
    # pagos not merged yet -> pagos is next; back waits even though listed after
    v = fnx.decide(rs, {"pagos": None, "back": None})
    assert v["kind"] == "next" and v["repo"] == "acme/pagos"
    # pagos merged (and its row already done) -> back unblocks BY THE MERGE
    rs2 = rows(("pagos", "none", "done"), ("back", "pagos", "pending"))
    v = fnx.decide(rs2, {"pagos": 7, "back": None})
    assert v["kind"] == "next" and v["repo"] == "acme/back"


def test_una_fila_done_en_el_indice_no_desbloquea_sin_merge_en_el_forge():
    # The index CLAIMS pagos is done, the forge shows no merge: back must NOT
    # start on a recorded status — dependencies are satisfied by merges.
    rs = rows(("pagos", "none", "done"), ("back", "pagos", "pending"))
    v = fnx.decide(rs, {"pagos": None, "back": None})
    assert v["kind"] == "waiting", v
    assert v["waits"][0]["on"] == ["pagos"]


def test_el_indice_detras_del_forge_se_corrige_antes_que_nada():
    # pagos merged but its row still says active -> the update outranks the
    # perfectly walkable next step.
    rs = rows(("pagos", "none", "active"), ("back", "pagos", "pending"))
    v = fnx.decide(rs, {"pagos": 7, "back": None})
    assert v["kind"] == "update" and v["repo"] == "acme/pagos" and v["pr"] == 7


def test_dropped_esta_fuera_de_juego_y_todo_cerrado_es_all_done():
    rs = rows(("pagos", "none", "done"),
              ("extra", "none", "dropped: se descartó el alcance"),
              ("back", "pagos", "done"))
    v = fnx.decide(rs, {"pagos": 7, "extra": None, "back": 9})
    assert v["kind"] == "all-done"


def test_el_set_paralelo_es_solo_lo_que_el_forge_desbloqueo():
    # Two independents plus one blocked: the parallel set carries exactly the
    # two whose dependencies are ALL merged — a blocked row never rides along,
    # and a recorded status buys nothing here either.
    rs = rows(("pagos", "none", "active"), ("catalogo", "none", "pending"),
              ("back", "pagos", "pending"))
    listos = fnx.ready(rs, {"pagos": None, "catalogo": None, "back": None})
    assert [r["repo"] for r in listos] == ["acme/pagos", "acme/catalogo"], listos
    # pagos merges (row now stale): it leaves the set — the stale row is
    # decide()'s business — and its merge is what lets back enter.
    listos = fnx.ready(rs, {"pagos": 3, "catalogo": None, "back": None})
    assert [r["repo"] for r in listos] == ["acme/catalogo", "acme/back"], listos


def test_esperando_nombra_a_cada_bloqueador():
    rs = rows(("pagos", "none", "done"), ("back", "pagos", "pending"),
              ("bff", "back", "pending"))
    # pagos merged+done; back not merged -> back is next... unless back also
    # waits: here back IS unblocked, so first-next wins.
    v = fnx.decide(rs, {"pagos": 4, "back": None, "bff": None})
    assert v["kind"] == "next" and v["repo"] == "acme/back"
    # back also blocked (a second dep never merged) -> waiting names both.
    rs2 = rows(("pagos", "none", "done"), ("back", "pagos, extra", "pending"))
    v = fnx.decide(rs2, {"pagos": 4, "back": None})
    assert v["kind"] == "waiting" and v["waits"][0]["on"] == ["extra"]


def test_dos_filas_con_el_mismo_nombre_corto_se_rechazan():
    rs = rows(("pagos", "none", "active"), ("pagos", "none", "pending"))
    assert fnx._dup_shorts(rs) == ["pagos"]
    assert fnx._dup_shorts(rows(("pagos", "none", "active"),
                                ("back", "pagos", "pending"))) == []
