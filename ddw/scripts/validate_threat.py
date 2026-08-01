#!/usr/bin/env python3
"""ddw-threat-modeling, the mechanical half — run by the skill, never re-derived.

The threat model was the most self-declared artifact in the pipeline: seven FAIL
rules, two warnings, a box the model drew itself, and a `threat` gate that turned
true because the model said the analysis went well. F-TM-06 exists precisely
because a threat model can be a template with nothing of the real system in it —
and nothing was checking F-TM-06 either.

What a parser can answer here is narrower than for the PRD, and the split is the
point rather than an apology: **whether every component got all six STRIDE
categories, whether the boundaries and the classification exist, whether every
risk carries a mitigation, whether an accepted risk carries its three fields, and
whether the document names the real design** are structural questions. Whether
the analysis is *correct* is not, and no receipt will make it so. The report says
which is which, on every run.

Rules mirror `.ddw/rules/validation-rules.instructions.md` §3 — the catalog is
the source of truth; this file implements, it does not redefine.

Exit: 0 = PASSED (warnings allowed) · 2 = FAILED · 3 = cannot read/parse.
"""

import argparse
import hashlib
import os
import re
import sys

STRIDE = ("Spoofing", "Tampering", "Repudiation", "Information Disclosure",
          "Denial of Service", "Elevation of Privilege")
# What each category is allowed to be called, so a model writing in Spanish or
# abbreviating to the STRIDE initial is not reported as having skipped it.
STRIDE_ALIASES = {
    "Spoofing": (r"spoofing|suplantaci[oó]n"),
    "Tampering": (r"tampering|manipulaci[oó]n|alteraci[oó]n"),
    "Repudiation": (r"repudiation|repudio"),
    "Information Disclosure": (r"information disclosure|divulgaci[oó]n|fuga de informaci[oó]n"),
    "Denial of Service": (r"denial of service|dos\b|denegaci[oó]n de servicio"),
    "Elevation of Privilege": (r"elevation of privilege|elevaci[oó]n de privilegios?|escalada"),
}
SENSITIVE = re.compile(r"\b(pii|credential|credencial|password|contrase[ñn]a|token|secret|"
                       r"secreto|financial|financier|tarjeta|card|dni|cuit|email|correo)\b",
                       re.IGNORECASE)
AT_REST = re.compile(r"\b(at rest|en reposo|en disco|encrypt\w*|cifrad\w*|hash\w*|bcrypt|argon)\b",
                     re.IGNORECASE)
IN_TRANSIT = re.compile(r"\b(in transit|en tr[aá]nsito|tls|https|ssl|mtls)\b", re.IGNORECASE)
ACCEPTED = re.compile(r"riesgo aceptado|accepted risk", re.IGNORECASE)


def _sections(text):
    """Every `##` section as {lowercased title: body}."""
    out, title, buf = {}, None, []
    for ln in text.splitlines():
        m = re.match(r"\s*##\s+(?!#)(.*)$", ln)
        if m:
            if title is not None:
                out[title] = "\n".join(buf).strip()
            title, buf = m.group(1).strip().lower(), []
        elif title is not None:
            buf.append(ln)
    if title is not None:
        out[title] = "\n".join(buf).strip()
    return out


def _section(sections, *names):
    for key, body in sections.items():
        if any(key.startswith(n) or n in key for n in names):
            return body
    return ""


def _subsections(body):
    """Every `###` block inside a section, as (title, body)."""
    out, title, buf = [], None, []
    for ln in body.splitlines():
        m = re.match(r"\s*###\s+(.*)$", ln)
        if m:
            if title is not None:
                out.append((title, "\n".join(buf)))
            title, buf = m.group(1).strip(), []
        elif title is not None:
            buf.append(ln)
    if title is not None:
        out.append((title, "\n".join(buf)))
    return out


def _table_rows(body):
    """Data rows of a markdown table, as lists of cells. Header and separator
    dropped: counting the header as a risk is how an empty table passes."""
    rows = []
    for ln in body.splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:] if len(rows) > 1 else []


def _repo_relative(path):
    ab = os.path.abspath(path)
    idx = ab.rfind(os.sep + "docs" + os.sep)
    if idx > 0:
        return ab[idx + 1:]
    try:
        rel = os.path.relpath(ab)
        return rel if not rel.startswith(os.pardir) else ab
    except ValueError:
        return ab


def _find_spec(tm_path, text, explicit):
    if explicit:
        return explicit
    m = re.search(r"^\|\s*Spec\s*\|\s*([^|]+?)\s*\|", text, re.MULTILINE | re.IGNORECASE)
    here = os.path.dirname(os.path.abspath(tm_path))
    if m:
        cand = m.group(1).strip().strip("`")
        for base in (os.getcwd(), os.path.abspath(os.path.join(here, "..", "..", ".."))):
            p = cand if os.path.isabs(cand) else os.path.join(base, cand)
            if os.path.exists(p):
                return p
    m = re.match(r"threat-(.+)\.md$", os.path.basename(tm_path))
    if m:
        for stem in ("spec", "fix"):
            p = os.path.join(here, "..", "specs", "%s-%s.md" % (stem, m.group(1)))
            if os.path.exists(p):
                return os.path.normpath(p)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("threat_model")
    ap.add_argument("--tier", default="FEATURE")
    ap.add_argument("--spec", default=None,
                    help="the spec this model analyses; found from the document if omitted")
    args = ap.parse_args()

    if args.tier == "QUICK-FIX":
        print("validate_threat: tier QUICK-FIX has no PLAN phase and therefore no threat model "
              "(catalog §Tier Modifier). Nothing to validate.", file=sys.stderr)
        sys.exit(3)

    try:
        text = open(args.threat_model, encoding="utf-8").read()
    except OSError as exc:
        print(f"validate_threat: cannot read {args.threat_model}: {exc}", file=sys.stderr)
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

    sections = _sections(text)
    components = _table_rows(_section(sections, "components", "componentes"))
    stride_body = _section(sections, "stride")
    analysed = _subsections(stride_body)

    # F-TM-01: all six categories, for every component.
    if not components:
        fail("F-TM-01", "no components table: nothing declares what is being analysed")
    elif not analysed:
        fail("F-TM-01", "no per-component STRIDE analysis found")
    else:
        named = {t.strip().lower() for t, _ in analysed}
        unanalysed = [c[0] for c in components
                      if not any(c[0].strip().lower() in n or n in c[0].strip().lower()
                                 for n in named)]
        gaps = []
        for title, body in analysed:
            missing = [cat for cat in STRIDE
                       if not re.search(STRIDE_ALIASES[cat], body, re.IGNORECASE)]
            if missing:
                gaps.append(f"{title} (missing {', '.join(missing)})")
        if unanalysed:
            fail("F-TM-01", f"component with no STRIDE analysis: {', '.join(unanalysed)}")
        elif gaps:
            fail("F-TM-01", f"incomplete STRIDE coverage: {'; '.join(gaps)}")
        else:
            ok("F-TM-01", f"all 6 STRIDE categories evaluated for {len(analysed)} component(s)")

    # F-TM-02: the crossings.
    boundaries = _section(sections, "trust boundaries", "fronteras de confianza", "l[ií]mites")
    if re.search(r"^\s*[-*|]\s*\S", boundaries, re.MULTILINE):
        ok("F-TM-02", "trust boundaries are declared")
    else:
        fail("F-TM-02", "no trust boundary declared: the crossings are where the vulnerabilities are")

    # F-TM-03 / F-TM-04: every risk treated, every acceptance approved.
    risk_body = _section(sections, "risks", "riesgos")
    risks = _table_rows(risk_body)
    if not risks:
        fail("F-TM-03", "no risks table: a threat model that identifies nothing treats nothing")
    else:
        untreated = [r[0] for r in risks
                     if len(r) < 2 or not r[-1] or re.fullmatch(r"[-–—.\s]*", r[-1])]
        if untreated:
            fail("F-TM-03", f"threat with neither mitigation nor accepted risk: {', '.join(untreated)}")
        else:
            ok("F-TM-03", f"all {len(risks)} identified threats carry a mitigation or an acceptance")

    accepted_body = _section(sections, "accepted risks", "riesgos aceptados")
    accepted = _subsections(accepted_body)
    if not accepted_body.strip() and not ACCEPTED.search(risk_body):
        ok("F-TM-04", "no accepted risks to approve")
    elif not accepted:
        fail("F-TM-04", "a risk is marked accepted with no approval entry naming who, why "
                        "and when it gets reviewed")
    else:
        incomplete = []
        for title, body in accepted:
            missing = [label for label, pat in (
                ("who accepted it", r"accepted by|aceptad[oa] por|aprobad[oa] por"),
                ("the justification", r"justification|justificaci[oó]n|motivo"),
                ("the review conditions", r"review|revisi[oó]n|condiciones"),
            ) if not re.search(pat, body, re.IGNORECASE)]
            if missing:
                incomplete.append(f"{title} (missing {', '.join(missing)})")
        if incomplete:
            fail("F-TM-04", f"accepted risk with an incomplete approval: {'; '.join(incomplete)}")
        else:
            ok("F-TM-04", f"all {len(accepted)} accepted risk(s) name who, why and when reviewed")

    # F-TM-05 / F-TM-07: classification, then the controls the class demands.
    data_body = _section(sections, "data classification", "clasificaci[oó]n de datos", "datos")
    data_rows = _table_rows(data_body)
    if data_rows:
        unclassified = [r[0] for r in data_rows if len(r) < 2 or not r[1].strip()]
        if unclassified:
            fail("F-TM-05", f"sensitive data with no classification: {', '.join(unclassified)}")
        else:
            ok("F-TM-05", f"all {len(data_rows)} data item(s) are classified")
    elif SENSITIVE.search(text):
        fail("F-TM-05", "the design handles sensitive data and the model classifies none of it")
    else:
        ok("F-TM-05", "no sensitive data to classify")

    sensitive_rows = [r for r in data_rows
                      if len(r) > 1 and re.search(r"pii|credential|credencial|financ", r[1], re.I)]
    if not sensitive_rows:
        ok("F-TM-07", "no PII or credentials to encrypt")
    else:
        scope = data_body + "\n" + risk_body
        missing = [w for w, pat in (("at rest", AT_REST), ("in transit", IN_TRANSIT))
                   if not pat.search(scope)]
        if missing:
            fail("F-TM-07", f"PII/credentials with no encryption {' and no '.join(missing)}")
        else:
            ok("F-TM-07", "PII/credentials specify encryption at rest and in transit")

    # F-TM-06: the model has to be about THIS design.
    spec_path = _find_spec(args.threat_model, text, args.spec)
    spec_text = ""
    if spec_path:
        try:
            spec_text = open(spec_path, encoding="utf-8").read()
        except OSError:
            spec_text = ""
    if not spec_text:
        fail("F-TM-06", "the spec could not be read, so the model was NOT checked against the "
                        "real design. Pass --spec <path> and run again")
    else:
        # Files and endpoints named by the spec, and how many of them this model
        # mentions. A template about "the API" and "the database" cites none.
        anchors = set(re.findall(r"`([\w./-]+\.\w{1,5})`", spec_text))
        anchors |= {m.group(0) for m in re.finditer(
            r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/\S+", spec_text)}
        anchors |= set(re.findall(r"\bFR-\d+\b", spec_text))
        cited = [a for a in anchors if a in text]
        if anchors and not cited:
            fail("F-TM-06", "the model cites nothing from the spec — no file, endpoint or FR. "
                            "A threat model unattached to the design protects nothing")
        else:
            ok("F-TM-06", f"the model cites {len(cited)} concrete element(s) of the spec")

    if not re.search(r"supply chain|cadena de suministro|dependenc", text, re.IGNORECASE):
        warn("W-TM-01", "no supply chain / dependency analysis")
    if not re.search(r"denial of service|dos\b|disponibilidad|availability", text, re.IGNORECASE):
        warn("W-TM-02", "no availability / DoS analysis")

    rows.append("  👁  Whether each STRIDE entry is CORRECT, and whether a mitigation actually")
    rows.append("      mitigates, are MANUAL: judge them and say so explicitly in your report.")

    result = "PASSED" if fails == 0 else f"FAILED ({fails} FAIL{'S' if fails > 1 else ''})"
    report = [f"/ddw-threat-modeling {args.threat_model} — {result}", "─" * 64]
    report += rows
    report.append("─" * 64)
    passed = sum(1 for r in rows if r.strip().startswith("✅"))
    tail = [f"Total: {passed} passed, {fails} failed, {warns} warnings", f"Result: {result}"]
    for line in report + tail:
        print(line)

    try:
        report_path = re.sub(r"\.md$", "", os.path.abspath(args.threat_model)) + ".validation.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(report + tail) + "\n```\n")
        print(f"Report: {_repo_relative(report_path)}")
    except OSError:
        pass

    if fails == 0:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        tm_abs = os.path.abspath(args.threat_model)
        idx = tm_abs.rfind(os.sep + "docs" + os.sep)
        root = tm_abs[:idx] if idx > 0 else os.getcwd()
        sess = os.path.join(root, ".ddw-sessions")
        os.makedirs(sess, exist_ok=True)
        with open(os.path.join(sess, f"threat-validated-{digest}"), "w", encoding="utf-8") as fh:
            fh.write(os.path.basename(tm_abs) + "\n")
        print(f"Receipt: .ddw-sessions/threat-validated-{digest}")
    sys.exit(0 if fails == 0 else 2)


if __name__ == "__main__":
    main()
