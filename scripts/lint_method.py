#!/usr/bin/env python3
"""Check the method's prose against the method's data.

DDW's product is mostly prompts. That makes a whole class of defect invisible to
ordinary testing: a rule cites a validation ID that no longer exists, a phase
promises an artifact nothing writes, a skill names a gate the graph never
carries, two files state different counts of the same thing. Nothing crashes.
The model simply reads the wrong instruction and does the wrong thing, and no
test notices because there is nothing to execute.

So this is the linter for the parts that are text. It compares what the prose
claims against the graph, the rule catalog and the filesystem — the three places
that hold the truth — and fails on any claim it cannot back up.

    python3 scripts/lint_method.py [--repo .]

Exit 0 = every claim checks out. Exit 1 = at least one does not.
"""
import argparse
import glob
import json
import os
import re
import sys

FINDINGS = []


def fail(where, msg):
    FINDINGS.append((where, msg))


def read(path):
    """A method file, as text — or "" with a finding when it is not decodable.

    Every check below reads prose with strict UTF-8, and a single file saved in
    the wrong encoding took the whole linter down with a UnicodeDecodeError and
    exit 1 — the exit code that means "a claim did not check out", from a run
    where no claim was ever read. The linter is allowed to say a file is
    unreadable; it is not allowed to answer with a stack.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        fail(path, "could not be read as UTF-8 (%s), so nothing in it was checked"
                   % exc.__class__.__name__)
        return ""


def rel(root, path):
    return os.path.relpath(path, root)


def load_graph(root):
    with open(os.path.join(root, "ddw/rules/transition-graph.json"), encoding="utf-8") as fh:
        return json.load(fh)


def known_gates(graph):
    """Every gate name any edge in the graph can require."""
    out = set()
    for tier in graph.get("tiers", {}).values():
        for key, cfg in tier.items():
            if key == "extends" or not isinstance(cfg, dict):
                continue
            out.update(cfg.get("gates", []))
    for cfg in graph.get("common", {}).values():
        out.update(cfg.get("gates", []))
    return out


def known_phases(graph):
    out = {"IDLE"}
    for tier in graph.get("tiers", {}).values():
        for key in tier:
            if key == "extends":
                continue
            src, _, dst = key.partition("->")
            out.update({src, dst})
    for key in graph.get("common", {}):
        src, _, dst = key.partition("->")
        out.update({src, dst})
    return out


def check_gate_names(root, graph):
    """`gates.X` in the prose must be a gate the graph actually carries.

    This is how `gates.prd` outlived its rename to `gates.define`, and how
    `gates.dast` survived the control being removed: prose keeps citing a name
    that nothing enforces, and the model dutifully tries to set it.
    """
    gates = known_gates(graph)
    scan = (glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True)
            + glob.glob(os.path.join(root, "adapters/**/*.md"), recursive=True))
    for path in sorted(scan):
        text = read(path)
        for m in re.finditer(r"gates\.([A-Za-z_]+)", text):
            name = m.group(1)
            if name not in gates:
                line = text[:m.start()].count("\n") + 1
                fail(f"{rel(root, path)}:{line}",
                     f"cites `gates.{name}`, which no edge in the graph requires. "
                     f"Known gates: {', '.join(sorted(gates))}")


def check_rule_ids(root):
    """Every F-*/W-* cited in a phase must exist in the catalog, and vice versa.

    A cited rule that does not exist is an instruction the model cannot follow;
    a catalogued rule nobody cites is a rule that never runs.
    """
    catalog_path = os.path.join(root, "ddw/rules/validation-rules.instructions.md")
    catalog_text = read(catalog_path)
    pattern = re.compile(r"\b([FW]-[A-Z]+-[A-Z0-9]{2,})\b")
    defined = set(pattern.findall(catalog_text))
    if not defined:
        fail(rel(root, catalog_path), "no rule IDs found — the catalog looks empty")
        return

    cited = {}
    for path in sorted(glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True)):
        if os.path.samefile(path, catalog_path):
            continue
        text = read(path)
        for m in pattern.finditer(text):
            cited.setdefault(m.group(1), []).append(
                f"{rel(root, path)}:{text[:m.start()].count(chr(10)) + 1}")

    for rid, places in sorted(cited.items()):
        if rid not in defined:
            fail(places[0], f"cites rule {rid}, which is not in the catalog")
    # The other direction, which the docstring promised and nothing did: a rule
    # family the phases never invoke is a set of rules that can never run.
    #
    # At FAMILY granularity on purpose. Phases cite ranges — "every rule in
    # section 5", "F-VER-01 to F-VER-06" — so demanding each ID by name reports
    # a hundred rules as orphaned when they are all reachable. What actually
    # goes wrong is a whole family nobody routes to.
    fam = lambda rid: rid.rsplit("-", 1)[0]
    cited_families = {fam(r) for r in cited}
    for family in sorted({fam(r) for r in defined} - cited_families):
        members = sorted(r for r in defined if fam(r) == family)
        fail(rel(root, catalog_path),
             f"catalogues {len(members)} {family}-* rules ({members[0]}…{members[-1]}) "
             "that no phase cites — nothing routes to them, so they never run")


def method_prose(root):
    """Every file of the method a reader or a model is instructed BY.

    `ddw/**` alone was the scan set, which left out `skills/*/SKILL.md` and
    `agents/*.md` — the two places that name skills and subagents most, and
    therefore the two most able to name one that does not exist. A linter that
    checks the documents least likely to be wrong is a linter with a green light
    and no beam.
    """
    return (sorted(glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True))
            + sorted(glob.glob(os.path.join(root, "skills/*/SKILL.md")))
            + sorted(glob.glob(os.path.join(root, "agents/*.md"))))


def check_paths(root):
    """A `docs/ddw/...` path in one file must match the rest.

    Artifact paths moved once and left citations behind in six places. They are
    derived paths, so nothing breaks loudly — the model just writes the artifact
    where the next phase will not look for it.
    """
    for path in method_prose(root):
        text = read(path)
        for m in re.finditer(r"docs/(?!ddw/|adr/)([a-z]+)/[A-Za-z0-9{}_./-]+\.[a-z]+", text):
            line = text[:m.start()].count("\n") + 1
            fail(f"{rel(root, path)}:{line}",
                 f"writes to `docs/{m.group(1)}/`, outside the `docs/ddw/` namespace. "
                 "Everything the pipeline produces lives under docs/ddw/ (docs/adr/ excepted, "
                 "deliberately).")
    return None


def _is_placeholder(name):
    """Routers show templates: `Skill(skill="a|b|c")`, `subagent_type="<name>"`.
    A placeholder is an example, not a reference that can dangle."""
    return "|" in name or "<" in name or "{" in name


def check_skill_and_agent_refs(root):
    """Every skill and subagent named in the prose must exist on disk."""
    skills = {os.path.basename(d) for d in glob.glob(os.path.join(root, "skills/*"))
              if os.path.isdir(d)}
    agents = {os.path.basename(f)[:-3] for f in glob.glob(os.path.join(root, "agents/*.md"))}

    for path in method_prose(root):
        text = read(path)
        for m in re.finditer(r"""Skill\(skill=["']([^"']+)["']\)""", text):
            if _is_placeholder(m.group(1)):
                continue
            if m.group(1) not in skills:
                line = text[:m.start()].count("\n") + 1
                fail(f"{rel(root, path)}:{line}", f"invokes skill {m.group(1)!r}, which does not exist")
        for m in re.finditer(r'''subagent_type=["']([^"']+)["']''', text):
            if _is_placeholder(m.group(1)):
                continue
            if m.group(1) not in agents:
                line = text[:m.start()].count("\n") + 1
                fail(f"{rel(root, path)}:{line}", f"spawns agent {m.group(1)!r}, which does not exist")
        for m in re.finditer(r"\.ddw/(rules|scripts)/([A-Za-z0-9_-]+(?:\.[a-z]+)+)", text):
            target = os.path.join(root, "ddw", m.group(1), m.group(2))
            if not os.path.exists(target):
                line = text[:m.start()].count("\n") + 1
                fail(f"{rel(root, path)}:{line}",
                     f"points at `.ddw/{m.group(1)}/{m.group(2)}`, which does not exist")


def check_counts(root):
    """Numbers stated in prose must match what is on disk.

    "fifteen skills" and "three auditors" drift the moment one is added, and a
    model that reads a stale count will look for something that is not there.
    """
    n_skills = len([d for d in glob.glob(os.path.join(root, "skills/*")) if os.path.isdir(d)])
    n_agents = len(glob.glob(os.path.join(root, "agents/*.md")))
    n_rules = len(glob.glob(os.path.join(root, "ddw/rules/*.instructions.md")))
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
             8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
             14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
             19: "nineteen", 20: "twenty"}

    # Every markdown that states a total, not just the method's own. Two counts
    # went stale in CHANGELOG.md and adapters/adapter.schema.md while this
    # scanned ddw/ and README.md alone — and a stale count in a file a reader
    # trusts is the same defect wherever it lives.
    scan = (glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True)
            + glob.glob(os.path.join(root, "adapters/**/*.md"), recursive=True)
            + glob.glob(os.path.join(root, "docs/*.md"))
            + [os.path.join(root, f) for f in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md")])
    for path in sorted(scan):
        if not os.path.exists(path):
            continue
        text = read(path)
        for noun, actual in (("skills", n_skills), ("agents", n_agents),
                             ("rule files", n_rules)):
            # Only counts stated as TOTALS. "the three agents that audit" is a
            # subset and saying so is correct; requiring the phrasing of totality
            # keeps this from failing on legitimate prose.
            # A bullet that opens with a count is stating a total — "- Sixteen
            # skills and five subagents". The named prefixes exist to skip
            # subsets ("the three agents that audit"); a list item has no such
            # ambiguity, and two counts went stale in exactly that shape.
            total = r"(?:^[-*]\s+|(?:all|ships|there are|total of|the)\s+)"
            for m in re.finditer(rf"(?:\b|^){total}(\d+|[a-z]+)\s+{noun}\b", text, re.I | re.M):
                tok = m.group(1)
                # .lower(): the match is case-insensitive, so a count opening a
                # sentence arrives as "Fourteen" and never equalled "fourteen".
                # It resolved to None and was skipped — the spelled-out totals,
                # which is most of them in prose, were silently never checked.
                stated = int(tok) if tok.isdigit() else \
                    next((k for k, v in words.items() if v == tok.lower()), None)
                if stated is None or stated == actual:
                    continue
                line = text[:m.start()].count("\n") + 1
                fail(f"{rel(root, path)}:{line}",
                     f"says {tok} {noun}; there are {actual}")


# Phrasings that assert the opposite of "one block = one commit". Each one was
# in the repo at some point, saying so in a file the model reads when it is
# deciding what to do next.
#
# "a single commit at the end" is deliberately NOT here. The rationale in
# commits.instructions.md uses that exact phrase to argue AGAINST it — so the
# pattern fired on prose defending the correct position. A check that fails for
# the wrong reason is worth no more than one that passes for the wrong reason.
_ANTI_PER_BLOCK = (
    r"not one per block",
    r"one commit for the whole implementation",
    r"the orchestrator does,? once",
)


def check_history_stamp(root):
    """A phase that appends to `history` must say what to stamp on the entry.

    The schema promises `ticket` and `tier` on every entry, and only CLOSEOUT
    told the model to put them there — so six phases wrote "add an entry:
    transition X → Y" and got exactly that. A live run came back with `tier`
    stamped (an older convention the model had picked up) and `ticket` on none
    of them.

    Nothing failed: the FSM accepts an entry with no ticket, deliberately, so
    that histories written before the field existed stay valid. What degrades is
    what can be derived from it — an unattributable entry reads as unfinished
    work, so the boot offers sub-tickets that closed weeks ago.

    A schema that promises what no instruction asks for is a schema describing a
    file nobody writes.
    """
    # `ddw/orchestrator.md` también, y no por completitud: es el archivo que el
    # router carga en cada turno, así que una instrucción de historia escrita ahí
    # llega antes que cualquiera de las de fase. El barrido leía sólo
    # `ddw/rules/*.instructions.md`, así que la mitad más leída del método quedaba
    # afuera del check que existe para que las entradas salgan estampadas.
    _corpus = (sorted(glob.glob(os.path.join(root, "ddw/rules/*.instructions.md")))
               + [os.path.join(root, "ddw/orchestrator.md")])
    for path in _corpus:
        if not os.path.exists(path):
            continue
        # state.instructions.md DEFINES the entry; it does not instruct a phase to
        # append one. Reading its schema row as an instruction made the check fire
        # on the very file that documents the answer.
        if os.path.basename(path) == "state.instructions.md":
            continue
        text = read(path)
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            # Matched on the exact phrasing this file happened to use, once —
            # and CLASSIFY says "Append a `history` entry", so it slipped
            # through and shipped entries with no ticket. A check written
            # against your own wording agrees with your own wording.
            if not re.search(r"(add|append)\b[^.]{0,40}`history`|`history`[^.]{0,40}\bentry",
                             line, re.I):
                continue
            # A window, not the line. Prose wraps: CLASSIFY says "Append a
            # `history` entry …, **stamped" and the rest lands on the next line,
            # so a line-by-line check called it unstamped while it was stamped.
            # Whitespace-normalised: the wrap leaves "**stamped" at the end of
            # one line and "     with `ticket`" at the start of the next, so a
            # plain join produces "stamped      with" and the substring missed.
            # La ventana, y también la FORMA declarada. El orquestador no dice
            # «stamped with»: enumera la forma entera —`{timestamp, from, to,
            # action, ticket, tier}`— nueve líneas más abajo, en el mismo
            # párrafo. Un check que sólo acepta una redacción acusa a un archivo
            # que dice lo mismo con otras palabras, y eso empuja a reescribir la
            # prosa para conformar al check en vez de al revés.
            window = re.sub(r"\s+", " ", " ".join(lines[i - 1:i + 10]))
            if "stamped with" in window:
                continue
            # …sin contar los FLAGS. `--ticket <ID>` y `--tier <TIER>` son cómo
            # se invoca el helper, no qué lleva la entrada, y con ellos adentro
            # la ventana se satisfacía sola: borré la forma declarada a propósito
            # y el check siguió verde. Se descuentan antes de preguntar.
            _fields = re.sub(r"--(ticket|tier)\b", "", window)
            if "`ticket`" in _fields and "`tier`" in _fields:
                continue
            fail(f"{rel(root, path)}:{i}",
                 "tells the model to append a history entry without saying to stamp `ticket` and "
                 "`tier` — the schema promises both on every entry, and the model writes what the "
                 "phase asks for")


def check_boot_reads_every_state_field(root):
    """Lo que el boot vuelve a leer del estado tiene que ser todo lo que el
    esquema promete que hay ahí.

    Un turno nuevo, o una compactación, reconstruye la sesión desde
    `.ddw-state.json` — y sólo desde los campos que la Boot Sequence nombra. El
    campo que no se nombra ahí no existe para el turno siguiente: se agregó
    `autonomy` al esquema y quedó fuera de esa lista, así que **toda compactación
    olvidaba el modo** y el pipeline volvía a preguntar por cada arista a alguien
    que había dicho que no le preguntaran. Nada falló; el estado en disco estaba
    perfecto.

    Derivado del esquema, no de una lista escrita acá: una segunda lista es una
    segunda cosa que se queda atrás, que es exactamente el defecto que este
    check existe para atrapar.
    """
    schema = os.path.join(root, "ddw/rules/state.instructions.md")
    orch = os.path.join(root, "ddw/orchestrator.md")
    if not (os.path.exists(schema) and os.path.exists(orch)):
        return
    fields = [m.group(1) for m in re.finditer(r"^\|\s*`(\w+)`\s*\|", read(schema), re.M)]
    if not fields:
        fail("ddw/rules/state.instructions.md",
             "no state field could be read out of the schema table, so the check below "
             "compared the boot against nothing")
        return
    text = read(orch)
    m = re.search(r"^1\. Read `\.ddw-state\.json`.*?(?=^\s*\d+\.\s)", text, re.M | re.S)
    boot = m.group(0) if m else ""
    if not boot:
        fail("ddw/orchestrator.md",
             "the Boot Sequence no longer starts by reading `.ddw-state.json` — nothing says "
             "what a new turn recovers")
        return
    # `gates`, `history` y `discovery` los lee el propio hook y no la prosa del
    # boot: lo que se comprueba acá son los campos de CABECERA, que son los que
    # deciden cómo se comporta el turno.
    header = [f for f in fields if f not in ("gates", "history", "discovery")]
    missing = [f for f in header if "`%s`" % f not in boot]
    if missing:
        fail("ddw/orchestrator.md",
             "the Boot Sequence does not recover %s from the state — a field it does not name "
             "does not survive a compaction, and the run carries on as if it had never been set"
             % ", ".join("`%s`" % f for f in missing))


def check_internal_links(root):
    """A relative link in the docs must point at something that is there.

    The README is where someone decides whether to adopt this, and it sends them
    to five other files. A link that 404s on the first page is not a broken
    link, it is a claim the project cannot back — and renaming or dropping a doc
    leaves no other trace, because nothing executes a README.
    """
    scan = ([os.path.join(root, f) for f in ("README.md", "CHANGELOG.md",
                                             "CONTRIBUTING.md", "SECURITY.md")]
            + sorted(glob.glob(os.path.join(root, "docs/*.md"))))
    for path in scan:
        if not os.path.exists(path):
            continue
        base = os.path.dirname(path)
        text = read(path)
        for m in re.finditer(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)", text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "//")):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, target))):
                fail(f"{rel(root, path)}:{text[:m.start()].count(chr(10)) + 1}",
                     f"links to `{target}`, which does not exist")


def check_context_reaches_agents(root):
    """A tool whose context file is not AGENTS.md must be pointed at AGENTS.md.

    The project's context lives in AGENTS.md for every tool, because that is what
    makes it portable. Four of the six read that file natively, so their block
    sits inside it and there is nothing to bridge. The other two read CLAUDE.md
    and GEMINI.md — and if their snippet never names AGENTS.md, the pipeline runs
    with no idea what the project is built with, while CLASSIFY looks up a
    "Stack" section in a file the tool never opened.

    Gemini shipped exactly that: the shared snippet, whose wording ("the
    project's own context is elsewhere in this file") is true where the block
    lives inside AGENTS.md and false where it does not. Nothing failed. It just
    worked without a stack.
    """
    for recipe_path in sorted(glob.glob(os.path.join(root, "adapters/*/adapter.json"))):
        try:
            with open(recipe_path, encoding="utf-8") as fh:
                recipe = json.load(fh)
        except (OSError, ValueError, RecursionError) as exc:
            fail(rel(root, recipe_path), "is not readable JSON (%s)" % exc.__class__.__name__)
            continue
        ctx = recipe.get("context_file")
        if not ctx or ctx == "AGENTS.md":
            continue                      # the block is inside AGENTS.md already
        adapter_dir = os.path.dirname(recipe_path)
        snippet = (os.path.join(adapter_dir, recipe["snippet"]) if "snippet" in recipe
                   else os.path.join(root, "ddw", "activation.snippet.md"))
        body = read(snippet) if os.path.exists(snippet) else ""
        if "AGENTS.md" not in body:
            fail(rel(root, snippet),
                 f"{recipe.get('id', '?')} reads {ctx}, not AGENTS.md, and its activation block "
                 "never names AGENTS.md — the project's stack, conventions and glossary never "
                 "reach the model")


def check_template_sections_known(root):
    """Every section the context TEMPLATE ships is one `ddw-context-check` looks for.

    `check_context_headings` walks one direction — a heading the method cites has
    to be one the skill knows about. This is the other, and it was open: the
    template shipped `## What this project is` and the skill never named it, so a
    repository missing that section was reported as complete. And the two skills
    that ask for a coverage floor cite `AGENTS.md, "Testing"` in the documents
    they teach, against a template that had no Testing section at all — the
    method telling every project to quote a heading its own installer does not
    create.
    """
    tpl = os.path.join(root, "ddw/AGENTS.template.md")
    skill = os.path.join(root, "skills/ddw-context-check/SKILL.md")
    if not (os.path.exists(tpl) and os.path.exists(skill)):
        return
    known = read(skill)
    for m in re.finditer(r"^##\s+(.+?)\s*$", read(tpl), re.M):
        heading = m.group(1).strip()
        if heading.lower() in ("language",):
            continue                      # the template's own instructions, not a section DDW reads
        if heading not in known:
            fail("ddw/AGENTS.template.md",
                 f"ships a `## {heading}` section that ddw-context-check never looks for — a "
                 "repository missing it is reported as complete")


def check_context_headings(root):
    """A section of AGENTS.md the method reads must be one the skill checks for.

    AGENTS.md is copied from the template once and never managed again, so a
    heading the method looks up by name is only there if it happened to be in
    the template the day that repo was installed. Two ordinary situations leave
    it absent — the repo already had its own AGENTS.md, or a later version of
    DDW started reading a new section — and in both the lookup finds nothing and
    says nothing.

    `ddw-context-check` is what reports them, so this is the link that keeps it
    current: cite a new section in a rule and forget to teach the skill about
    it, and the check that would have caught its absence never learns to look.
    """
    skill = os.path.join(root, "skills/ddw-context-check/SKILL.md")
    if not os.path.exists(skill):
        fail("skills/ddw-context-check/SKILL.md",
             "does not exist, so nothing reports a context file missing what the method reads")
        return
    known = read(skill)

    # Los SKILLS también, no sólo `ddw/**`. Los dos que piden un piso de
    # cobertura citan `AGENTS.md, "Testing"` en el documento que enseñan a
    # escribir, y con el corpus limitado a `ddw/` esa cita no se veía: se podía
    # borrar `## Testing` de la plantilla y el lint quedaba verde. Es
    # exactamente lo que arregló 87ae703, y nada lo sostenía.
    corpus = sorted(glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True)
                    + glob.glob(os.path.join(root, "skills/*/SKILL.md")))
    cited = {}
    for path in corpus:
        if os.path.samefile(path, skill):
            continue
        text = read(path)
        for i, line in enumerate(text.splitlines(), 1):
            if "AGENTS.md" not in line:
                continue
            # Y la forma `AGENTS.md, "Testing"`, que es como la escriben los
            # documentos trabajados. Pidiendo la palabra `section` al lado, la
            # cita que los skills realmente usan no contaba como cita.
            for m in re.finditer(
                    r'"([A-Z][^"]{2,45})"\s+section|section\s+"([A-Z][^"]{2,45})"|'
                    r'AGENTS\.md[,\s]+\u00a7?\s*"?([A-Z][\w ]{2,45}?)"?\s*[)|]|'
                    r'AGENTS\.md\s+\u00a7\s*([A-Z][\w ]{2,45})', line):
                name = next((g for g in m.groups() if g), "").strip()
                if name:
                    cited.setdefault(name, f"{rel(root, path)}:{i}")

    template = os.path.join(root, "ddw/AGENTS.template.md")
    shipped = read(template) if os.path.exists(template) else ""
    for name, where in sorted(cited.items()):
        if f"## {name}" not in known:
            fail(where,
                 f"reads the {name!r} section of AGENTS.md, but ddw-context-check does not list "
                 "it — nothing will notice when a repo's context file has no such heading")
        # …y que la plantilla la TRAIGA. Que el reportero sepa buscarla no la
        # pone en el archivo: sin esto, el método le dice a cada proyecto que
        # cite un encabezado que su propio instalador no escribe.
        if shipped and f"## {name}" not in shipped:
            fail(where,
                 f"reads the {name!r} section of AGENTS.md and ddw/AGENTS.template.md ships no "
                 f"such heading — every repo DDW installs is told to quote a section its own "
                 f"installer never wrote")


def check_rationale(root):
    """Every decision in RATIONALE.md owns up to what it costs.

    The file exists so someone can disagree on the merits before adopting the
    method. An entry with only its upside is advocacy — it reads like reasoning
    and gives the reader nothing to weigh, which is worse than not writing it
    down at all. The file says so itself; this is what makes that a rule rather
    than an aspiration.
    """
    path = os.path.join(root, "docs/RATIONALE.md")
    if not os.path.exists(path):
        fail("docs/RATIONALE.md", "does not exist, and README.md links to it")
        return
    text = read(path)

    entries = re.split(r"^## ", text, flags=re.M)[1:]
    numbered = [e for e in entries if re.match(r"\d+\.", e)]
    if not numbered:
        fail(rel(root, path), "has no numbered decisions — the file looks empty")
        return
    for entry in numbered:
        title = entry.splitlines()[0].strip()
        if "**The cost.**" not in entry:
            fail(rel(root, path),
                 f"decision {title!r} never says what it costs — an entry with only its upside is "
                 "advocacy, not reasoning")


def check_rule_ranges(root):
    """"F-SPEC-01 to F-SPEC-15" has to end at the last rule that exists.

    Half a dozen files tell the validator to apply "every rule from X to Y".
    Add rule 16 and every one of those ranges quietly excludes it: the catalog
    has the rule, the skill that runs the catalog does not know to look for it,
    and nothing fails — the new rule simply never fires. check_rule_ids catches
    an ID that does not exist; this catches the opposite, an ID that exists and
    is not being asked for.
    """
    last = _catalog_last(root)

    # `ddw/**` alone left out the skills, which is where most of these ranges
    # are written — the skill IS the thing that runs the catalog. Same scan set
    # as every other prose check.
    for path in method_prose(root):
        body = read(path)
        # Only ranges that START at 01. Those are the ones claiming "every rule
        # in this section"; a range from 04 to 11 names a group on purpose —
        # per-block completeness, say — and is not asserting it is the whole
        # catalog. Failing on those punishes correct prose.
        #
        # The optional backticks are not cosmetic. Every ID in this repo's prose
        # is written as code, so the range a reader sees is "`F-TEST-01` to
        # `F-TEST-06`" — and demanding whitespace straight after `-01` meant the
        # one shape the method actually uses was the one shape this could not
        # see. It ran for months over ranges that were all correct and was blind
        # to the single stale one.
        for m in re.finditer(r"\b([FW]-[A-Z]+)-0*1`?\s+to\s+`?\1-(\d+)\b", body):
            family, hi = m.group(1), int(m.group(2))
            if family not in last or hi == last[family]:
                continue
            fail(f"{rel(root, path)}:{body[:m.start()].count(chr(10)) + 1}",
                 f"asks for {family}-01 to {family}-{hi:02d}, but the catalog's last "
                 f"{family} rule is {family}-{last[family]:02d} — the ones past {hi} "
                 "are never applied")


# The Quantitative Summary's rows, and the family each one counts. Hard-coded so
# that adding a section to the catalog and forgetting its row is a lint failure
# rather than a row this silently skips.
_SUMMARY_AREAS = {
    "PRD": "PRD",
    "Spec / Fix-Plan": "SPEC",
    "Threat Model": "TM",
    "SAST": "SAST",
    "Test Run Report": "TEST",
    "Module Verify": "VER",
    "ADR": "ADR",
}


def _catalog_last(root):
    """The highest rule number the catalog defines, per family."""
    text = read(os.path.join(root, "ddw/rules/validation-rules.instructions.md"))
    last = {}
    for m in re.finditer(r"^\|\s*([FW]-[A-Z]+)-(\d+)\s*\|", text, re.M):
        family, num = m.group(1), int(m.group(2))
        last[family] = max(last.get(family, 0), num)
    return last


def check_rule_counts(root):
    """The catalog's own summary must count the rules the catalog defines.

    It said 69 FAIL rules and 84 total where the tables define 65 and 80, and
    `ddw/rules/README.md` repeated the 84. Nobody mis-typed a total: rules were
    removed and merged over three rounds and the summary was never recounted,
    which is exactly the drift `check_counts` exists to stop for skills and
    agents — only this table counts the thing the method is FOR, and a reader
    reconciling "21 SAST rules" against nineteen in the tables above it has to
    decide which half of one document to believe.

    Counted from the ID column of the tables, which is the same source
    `check_rule_ids` treats as the definition.
    """
    path = os.path.join(root, "ddw/rules/validation-rules.instructions.md")
    text = read(path)
    actual = {}
    for m in re.finditer(r"^\|\s*([FW])-([A-Z]+)-(\d+)\s*\|", text, re.M):
        actual[(m.group(2), m.group(1))] = actual.get((m.group(2), m.group(1)), 0) + 1

    rows = re.findall(r"^\|\s*(?:\*\*)?([A-Za-z][^|*]*?)(?:\*\*)?\s*\|\s*(?:\*\*)?(\d+)(?:\*\*)?"
                      r"\s*\|\s*(?:\*\*)?(\d+)(?:\*\*)?\s*\|\s*(?:\*\*)?(\d+)(?:\*\*)?\s*\|\s*$",
                      text[text.find("## Quantitative Summary"):], re.M)
    if not rows:
        fail(rel(root, path), "has no Quantitative Summary table to check — either it was "
             "removed or its shape changed, and this check went quiet either way")
        return

    seen, tot_f, tot_w = set(), 0, 0
    for area, f_str, w_str, total_str in rows:
        area, stated = area.strip(), (int(f_str), int(w_str), int(total_str))
        if area.lower() == "total":
            if stated[:2] != (tot_f, tot_w) or stated[2] != tot_f + tot_w:
                fail(rel(root, path), f"totals {stated[0]} FAIL / {stated[1]} WARNING / "
                     f"{stated[2]} rules; its own rows add up to {tot_f} / {tot_w} / "
                     f"{tot_f + tot_w}")
            continue
        if area not in _SUMMARY_AREAS:
            fail(rel(root, path), f"summarises an area named {area!r} that this check does not "
                 "know how to count — map it to a rule family in _SUMMARY_AREAS")
            continue
        family = _SUMMARY_AREAS[area]
        seen.add(area)
        real = (actual.get((family, "F"), 0), actual.get((family, "W"), 0))
        if stated[:2] != real or stated[2] != sum(real):
            fail(rel(root, path), f"says {area} has {stated[0]} FAIL and {stated[1]} WARNING "
                 f"rules ({stated[2]} total); the tables define {real[0]} and {real[1]} "
                 f"({sum(real)})")
        tot_f, tot_w = tot_f + real[0], tot_w + real[1]

    for area in sorted(set(_SUMMARY_AREAS) - seen):
        fail(rel(root, path), f"defines {_SUMMARY_AREAS[area]}-* rules and the Quantitative "
             f"Summary has no {area} row — a section nobody totals is a section nobody recounts")

    # The one number outside the catalog that restates it. It is the line a
    # reader of `ddw/rules/` meets first, and it was wrong for the same reason.
    readme = os.path.join(root, "ddw/rules/README.md")
    body = read(readme)
    for m in re.finditer(r"\bThe (\d+) validation rules\b", body):
        if int(m.group(1)) != tot_f + tot_w:
            fail(f"{rel(root, readme)}:{body[:m.start()].count(chr(10)) + 1}",
                 f"says {m.group(1)} validation rules; the catalog defines {tot_f + tot_w}")


def check_commit_granularity(root):
    """Two files describe when CODE commits, and they once disagreed.

    `commits.instructions.md` said one block = one commit; `code.instructions.md`
    said one commit for the whole implementation, not one per block. Both are
    loaded in CODE, so which one won was a matter of which the model read last —
    and the reader had no way to tell that a rule was being contradicted.

    This is narrow on purpose: it cannot detect contradiction in general, only
    this one, and only in the phrasings that produced it. That is the point —
    a defect that was real once becomes a check that stops it returning, the
    same bargain `scripts/mutate.py` makes.
    """
    code = os.path.join(root, "ddw/rules/code.instructions.md")
    text = read(code)

    # 1. The block loop has to actually commit.
    start = text.find("### Block-by-block implementation")
    end = text.find("### Session Rule", start if start >= 0 else 0)
    if start < 0 or end < 0:
        fail(rel(root, code),
             "the FEATURE block loop is not where this check expects it; the commit-per-block "
             "claim cannot be verified")
    elif "ddw-commit" not in text[start:end]:
        fail(f"{rel(root, code)}:{text[:start].count(chr(10)) + 1}",
             "the block loop never invokes ddw-commit, so blocks are not committed as they close "
             "— but commits.instructions.md states one block = one commit")

    # 2. Nothing anywhere may assert the opposite.
    targets = sorted(glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True))
    for path in targets:
        body = read(path)
        for pat in _ANTI_PER_BLOCK:
            for m in re.finditer(pat, body, re.I):
                fail(f"{rel(root, path)}:{body[:m.start()].count(chr(10)) + 1}",
                     f"says {m.group(0)!r}, contradicting `one block = one commit` in "
                     "ddw/rules/commits.instructions.md")


def check_tiers_documented(root, graph):
    """Every tier the graph defines is explained where a person will look.

    The graph is the authority for which tiers exist, and adding one there is
    one line. What it costs is the part nobody remembers: CLASSIFY has to say
    when to choose it, the state schema has to list it as a legal value, and the
    router has to know what to load when the phase carrying its name comes up.
    `FREE` was added and all three were missed on the first pass — the pipeline
    worked and the method described a product with one fewer tier than it had.

    Checked against the two files a reader and a model actually consult, not
    against every mention: the classification rules, and the schema of the file
    the tier is written into.
    """
    tiers = set(graph.get("tiers", {}))
    if not tiers:
        fail("ddw/rules/transition-graph.json", "defines no tier at all")
        return
    for rel_path in ("ddw/rules/classify.instructions.md", "ddw/rules/state.instructions.md"):
        text = read(os.path.join(root, rel_path))
        missing = sorted(t for t in tiers if t not in text)
        if missing:
            fail(rel_path, "the graph defines %s and this file explains %s — a tier nobody "
                           "documents is one the model cannot choose on purpose"
                 % (", ".join(sorted(tiers)), "none of them" if len(missing) == len(tiers)
                    else "neither " + " nor ".join(missing) if len(missing) > 1
                    else "not " + missing[0]))


def check_blocked_marks_enforcement(root):
    """A router's Blocked line says which half of it a hook actually refuses.

    The lists mixed the two: `source code` (refused by the gate, in the gate's
    own wording) sat beside `modifying the PRD` and `writing outside
    docs/ddw/discovery/` (nobody's hook refuses those — nothing under `docs/` is
    refused in any phase). A reader cannot tell them apart by looking, and this
    whole framework is the argument that the difference matters: "the agent
    politely declines" and "the write is rejected" mean opposite things.

    So every phase whose rules forbid product source marks it, and the legend
    that explains the mark has to be there to be read.
    """
    orch = os.path.join(root, "ddw/orchestrator.md")
    text = read(orch)
    if "🔒" not in text:
        fail("ddw/orchestrator.md",
             "no Blocked line marks what the hook refuses, so every line reads as enforcement")
        return
    if "refused by the hook" not in text:
        fail("ddw/orchestrator.md",
             "the 🔒 mark is used and never explained — a symbol nobody defines is decoration")
    for m in re.finditer(r"^## Router: Phase `([A-Z-]+)`\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        phase, body = m.group(1), m.group(2)
        if phase in ("CODE", "CLOSEOUT", "FREE", "IDLE"):
            continue                      # source is allowed here, or the phase has no gate to state
        blocked = re.search(r"^- \*\*Blocked:\*\*(.*)$", body, re.M)
        if blocked and "source" in blocked.group(1).lower() and "🔒" not in blocked.group(1):
            fail(f"{rel(root, orch)}:{text[:m.start()].count(chr(10)) + 1}",
                 f"{phase} blocks source code and does not mark it as the hook's — it reads like "
                 "the same kind of rule as the ones nothing enforces")


def check_autonomy_prose_matches_the_hook(root):
    """The per-response arrow limit, as the prose states it and as the hook applies it.

    These drifted apart and the prose won, because the prose is what the model
    reads. `second_arrow_in_one_turn` exempts `minimal` by name — the arrows are
    meant to run with nobody between them, which is what that mode is — while
    the orchestrator said the limit held "either way". Measured on a live
    `minimal` run: one arrow, end of turn, a 🙋 banner asking to continue, and a
    person paying an ok for every step the mode was chosen to stop asking about.
    `minimal` was `assisted` with different wording, and nothing was broken —
    the enforcement was right the whole time and unreachable.

    So the claim is checked against the guard itself, driven, not read: a repo
    with a turn already spent, asked once in each mode.
    """
    import importlib.util
    import tempfile

    path = os.path.join(root, "ddw/scripts/validate-transition.py")
    if not os.path.exists(path):
        return                              # check_paths owns a missing file
    spec = importlib.util.spec_from_file_location("_vt_autonomy", path)
    vt = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(vt)
    except Exception as exc:                # noqa: BLE001 — a broken guard is not this check's to name
        fail(rel(root, path), "could not be loaded, so the autonomy claim went unchecked (%s)"
                              % exc.__class__.__name__)
        return

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, ".ddw-sessions"))
        for name in ("turn", "last-arrow"):
            with open(os.path.join(tmp, ".ddw-sessions", name), "w", encoding="utf-8") as fh:
                fh.write("7")               # an arrow already landed in this turn
        nxt = {"phase": "DEFINE", "ticket": "T-1", "tier": "FEATURE", "gates": {}, "history": []}

        def asked(mode):
            old = {"phase": "CLASSIFY", "ticket": "T-1", "tier": "FEATURE",
                   "autonomy": mode, "gates": {}, "history": []}
            return vt.second_arrow_in_one_turn(tmp, old, dict(nxt, autonomy=mode))

        if asked("assisted") is None:
            fail(rel(root, path),
                 "the guard lets a second arrow through under `assisted`, so the limit the method "
                 "states everywhere is not enforced anywhere")
            return
        exempt = asked("minimal") is None

    orch = os.path.join(root, "ddw/orchestrator.md")
    text = read(orch)
    section = text.split("## Autonomy", 1)[-1] if "## Autonomy" in text else ""
    if not section:
        fail(rel(root, orch), "no `## Autonomy` section, so what each mode does is stated nowhere")
        return
    names_guard = "second_arrow_in_one_turn" in section
    if exempt and not names_guard:
        fail(rel(root, orch),
             "the hook exempts `minimal` from the one-arrow-per-turn refusal and the mode's own "
             "section does not say so. A reader who has only the prose stops at every arrow and "
             "pays a turn for each — which is `assisted`, under another name")
    if not exempt and names_guard:
        fail(rel(root, orch),
             "the section says the hook lifts the per-turn limit for `minimal` and the guard "
             "refuses there too, so the mode promises a run nothing will let it take")

    # …and no statement of the limit may read as universal — neither by leaving
    # the mode out nor by spelling out that it holds anyway. Both shapes were on
    # the page at once: one paragraph said the limit applied under `minimal` too
    # ("either way"), the next stated it with no mode at all, and the run obeyed
    # them.
    limit = re.compile(r"transition per response|phase transition in a single response"
                       r"|lands one transition|one arrow per response", re.I)
    universal = re.compile(r"either way|both modes|in both|regardless|whatever the mode"
                           r"|any mode|does not (?:change|apply|go away)", re.I)
    for doc in method_prose(root):
        body = read(doc)
        for para in re.split(r"\n\s*\n", body):
            # Flattened first: the method wraps at a hundred columns, so any
            # phrase of more than one word can straddle a line break — and this
            # one does. Matched against the raw paragraph, the rule read the
            # sentence it exists for as absent and went green over it.
            flat = re.sub(r"\s+", " ", para)
            if not limit.search(flat):
                continue
            where = f"{rel(root, doc)}:{body[:body.index(para)].count(chr(10)) + 1}"
            for sentence in re.split(r"(?<=[.;])\s+", flat):
                if limit.search(sentence) and universal.search(sentence):
                    fail(where,
                         "states the one-arrow-per-response limit as holding in every mode. It is "
                         "`assisted` only — the hook exempts `minimal` — and this is the sentence "
                         "a measured run cited while paying a turn per arrow in a mode chosen to "
                         "stop asking")
                    break
            else:
                if not re.search(r"assisted|minimal", flat, re.I):
                    fail(where,
                         "states the one-arrow-per-response limit without saying which autonomy "
                         "mode it belongs to. It is `assisted` only, and read as universal it "
                         "turns `minimal` into `assisted` with a different banner")


def check_minimal_exemption_reaches_the_phase_rules(root):
    """Every exit the orchestrator exempts from waiting says so where it is read.

    The orchestrator lists them — "user confirms (not under `minimal` — see
    § Autonomy)" — but the phase's own rules file is what the model has open at
    the moment it decides whether to stop, and that file's line is "Wait for the
    user's explicit confirmation." Five of the six carried the exemption as a
    note under exactly that line; CLASSIFY did not, and read on its own it says
    the arrow waits in every mode.
    """
    orch = os.path.join(root, "ddw/orchestrator.md")
    text = read(orch)
    exempt = []
    for m in re.finditer(r"^## Router: Phase `([A-Z-]+)`\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        if "not under `minimal`" in m.group(2):
            exempt.append(m.group(1))
    if not exempt:
        fail(rel(root, orch), "no phase exit says it is exempt from waiting under `minimal`, so "
                              "the mode changes nothing anywhere the phases are described")
        return
    for phase in exempt:
        rules = os.path.join(root, "ddw/rules/%s.instructions.md" % phase.lower())
        if not os.path.exists(rules):
            continue                      # check_paths owns the missing file
        body = read(rules)
        waits = [m for m in re.finditer(r"^Wait for .{0,80}(confirmation|approval)", body, re.M)]
        if not waits:
            continue                      # this phase does not state the wait in its own words
        if not any("minimal" in body[m.end():m.end() + 700] for m in waits):
            fail(f"{rel(root, rules)}:{body[:waits[0].start()].count(chr(10)) + 1}",
                 "tells the reader to wait for a confirmation and never says that `minimal` does "
                 "not — and this file, not the orchestrator, is what is open when the model "
                 "decides whether to stop")


def check_free_tiers_explained_to_people(root, graph):
    """Un tier que no pide NINGUNA compuerta tiene que estar explicado en
    `docs/METHOD.md`.

    No todos: METHOD.md delega en las tablas canónicas a propósito —«every
    phase, every tier, every gate» vive en el catálogo— y exigirle la lista
    entera sería pedirle que duplique lo que este repo evita duplicar. Se probó
    y el lint pidió meter FEATURE, FIX y QUICK-FIX en un documento que decide no
    enumerarlos. Eso no es un hallazgo, es forzar una copia.

    Lo que sí: un tier SIN compuertas es el único del que no se entera nadie por
    el camino. Los demás se anuncian solos — algo se pide, algo se rechaza. En
    ése no se pide nada, y si el documento que le explica el método a una
    persona no lo nombra, el producto tiene un modo sin enforcement del que sólo
    se enteran quienes leen el grafo. Es la mitad de 4c41f3e que ningún check
    sostenía.
    """
    path = os.path.join(root, "docs/METHOD.md")
    if not os.path.exists(path):
        return
    text = read(path)
    for tier in sorted(graph.get("tiers", {})):
        # La cadena `extends`, resuelta acá: un tier que hereda pide lo que
        # pide su padre, y leer sólo sus propias claves diría que no pide nada.
        asks, seen, cur = set(), set(), tier
        while cur and cur not in seen:
            seen.add(cur)
            spec = graph["tiers"].get(cur) or {}
            for key, edge in spec.items():
                if key.startswith("_") or key == "extends" or not isinstance(edge, dict):
                    continue
                asks |= set(edge.get("gates") or [])
            cur = spec.get("extends")
        if not asks and tier not in text:
            fail("docs/METHOD.md",
                 "the graph defines %s, which asks for no gate at all, and this file never names "
                 "it — a mode with no enforcement is the one a reader has to be told about, "
                 "because nothing in the run will tell them" % tier)


def check_phase_names(root, graph):
    """A phase named in a router must be a phase the graph knows."""
    phases = known_phases(graph) | {"DISCOVERY"}
    orch = os.path.join(root, "ddw/orchestrator.md")
    text = read(orch)
    for m in re.finditer(r"^## Router: Phase `([A-Z-]+)`", text, re.M):
        if m.group(1) not in phases:
            line = text[:m.start()].count("\n") + 1
            fail(f"{rel(root, orch)}:{line}",
                 f"routes phase {m.group(1)!r}, which appears in no edge of the graph")


# Retargeting `ticket` on an open run is the one move the validator refuses
# outright: a run belongs to one ticket, its history is stamped with it, and a
# header naming a different one contradicts every entry underneath. The prose
# used to instruct exactly that, and an instruction the gate refuses does not
# stop an agent — it escalates one. That is the road that ended in `rm`.
#
# Warnings have to be able to quote the mistake they warn about, so the rule is
# about where the sentence sits: inside a blockquote it is being reported, at
# the margin it is being ordered.
# Pointing `ticket` at a SUB-ticket is the signature: CLASSIFY assigning a
# ticket for the first time is how every run starts and is legal, so the name
# alone proves nothing. What the validator refuses is the parent's own run being
# renamed into its child.
_SUBTICKET_ASSIGN = re.compile(r"`ticket`\s*(?:->|→|:?=)\s*`?\{TICKET\}[a-z]", re.I)
# Unless the same line opens a NEW run, which is the sanctioned path.
_OPENS_NEW_RUN = re.compile(r"IDLE\s*(?:->|→)\s*CLASSIFY")


def check_compaction_envelopes(root):
    """The compaction table names an envelope per tool; the hook passes a flag.

    Two documents said Codex reads `hookSpecificOutput.additionalContext` while
    its own hook passed `--format text`, and getting this wrong is SILENT: the
    nudge is computed, formatted and dropped, and the pipeline simply never
    starts after a compaction. Nothing could see it because the table is prose,
    the flag is a shell argument, and no check read both.

    The envelope, in the words the table uses, and the flag that produces it:
    """
    ENVELOPE = {
        "hookSpecificOutput.additionalContext": "nested",
        "additional_context": "cursor",
        "additionalContext": "json",
        "stdout": "text",
    }
    doc = os.path.join(root, "docs/DEVELOPMENT.md")
    text = read(doc)
    rows = re.findall(r"^\|\s*([A-Za-z][\w \.]*?)\s*\|\s*`?([\w\.]+)`?\s*\|\s*(.+?)\s*\|\s*$",
                      text, re.MULTILINE)
    table = {}
    for tool, event, channel in rows:
        for phrase, fmt in ENVELOPE.items():          # longest phrase first
            if phrase in channel:
                table[tool.strip().lower()] = (event, fmt)
                break
    if len(table) < 4:
        fail(rel(root, doc), "the compaction table could not be read: the envelopes each tool "
                             "needs are documented nowhere else, and nothing else checks them")
        return
    for hook in sorted(glob.glob(os.path.join(root, "adapters/*/*/pre-compact.sh"))):
        tool_dir = hook.split(os.sep)[-3]
        body = read(hook)
        m_fmt = re.search(r"--format\s+(\w+)", body)
        m_ev = re.search(r"--event\s+(\w+)", body)
        named = [k for k in table if k.startswith(tool_dir)]
        if not named or not m_fmt:
            continue
        want_event, want_fmt = table[named[0]]
        if m_fmt.group(1) != want_fmt:
            fail(rel(root, hook),
                 "passes --format %s while the compaction table says %s reads %s. One of the two "
                 "is wrong and the failure is silent: the nudge is formatted and dropped."
                 % (m_fmt.group(1), named[0], want_fmt))
        if m_ev and m_ev.group(1) != want_event:
            fail(rel(root, hook),
                 "passes --event %s while the table says %s calls it %s"
                 % (m_ev.group(1), named[0], want_event))


def check_ticket_retarget(root):
    """No rule may ORDER what the state machine refuses."""
    for path in sorted(glob.glob(os.path.join(root, "ddw/rules/*.md"))):
        for i, line in enumerate(read(path).splitlines(), 1):
            if line.lstrip().startswith(">"):
                continue                     # quoted: the warning naming the mistake
            if _SUBTICKET_ASSIGN.search(line) and not _OPENS_NEW_RUN.search(line):
                fail(f"{rel(root, path)}:{i}",
                     "instructs retargeting `ticket` at a sub-ticket on an open run, which "
                     "the validator refuses. Close the parent with a `pause:` to IDLE and "
                     "open the sub-ticket as its own run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), ".."))
    args = ap.parse_args()
    root = os.path.abspath(args.repo)

    graph = load_graph(root)
    check_gate_names(root, graph)
    check_rule_ids(root)
    check_paths(root)
    check_skill_and_agent_refs(root)
    check_counts(root)
    check_history_stamp(root)
    check_boot_reads_every_state_field(root)
    check_internal_links(root)
    check_context_reaches_agents(root)
    check_context_headings(root)
    check_template_sections_known(root)
    check_rationale(root)
    check_rule_ranges(root)
    check_rule_counts(root)
    check_commit_granularity(root)
    check_phase_names(root, graph)
    check_blocked_marks_enforcement(root)
    check_tiers_documented(root, graph)
    check_free_tiers_explained_to_people(root, graph)
    check_compaction_envelopes(root)
    check_ticket_retarget(root)
    check_autonomy_prose_matches_the_hook(root)
    check_minimal_exemption_reaches_the_phase_rules(root)

    if not FINDINGS:
        print("lint_method: every claim in the prose checks out against the graph, the catalog "
              "and the filesystem.")
        return 0
    print(f"lint_method: {len(FINDINGS)} claim(s) the prose makes and the repo does not support\n")
    for where, msg in FINDINGS:
        print(f"  {where}\n      {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
