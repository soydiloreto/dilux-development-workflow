---
applyTo: '**'
version: 1.8.0
---

# Validation Rules — Central Catalog

This file defines EVERY validation rule applied by the DDW pipeline's validation skills. Each rule
has a unique ID, a precise description, a severity (FAIL or WARNING) and a basis in industry
standards or best practices.

**The validation skills (`ddw-validate-prd`, `ddw-validate-spec`, `ddw-threat-modeling`,
`ddw-security-sast`, `ddw-test`, `ddw-verify-module`) MUST evaluate these rules
mechanically. There is no room for subjective interpretation.**

> **Requirement identifiers.** Functional requirements are `FR-xx`, non-functional requirements are
> `NFR-xx`, acceptance criteria are `AC-xx`. These prefixes are what the rules match on — keep them
> as written even when the PRD's prose is in another language.

---

## Guiding Principle: FAIL vs WARNING

```
FAIL = The absence of this element affects the artifact's coverage,
       completeness, correctness, traceability or security.
       → Blocks progress. Must be resolved before continuing.

WARNING = The artifact serves its purpose without this element, but
          could be improved in quality, clarity or maintainability.
          → Reported, does not block. Stays as an optional improvement.

When in doubt → FAIL.
A false FAIL costs one conversation.
A false WARNING costs rework, bugs or security incidents.
```

### What can NEVER be a WARNING

- A PRD requirement with no coverage in the spec.
- An acceptance criterion with no test.
- An attack surface with no mitigation.
- A confirmed security vulnerability (any severity ≥ Medium).
- An undocumented security finding (not even false positives).

---

## Tier Modifier: QUICK-FIX

When `tier == "QUICK-FIX"`, the DEFINE artifact is a **4-line fix-brief**, not a PRD. This
catalog's rules apply with the following conditionality:

| Family | Behavior with QUICK-FIX |
|---|---|
| `F-PRD-*` / `W-PRD-*` (PRD validation) | **Do not apply.** `ddw-validate-prd` for QUICK-FIX requires ONLY the fix-brief's 4 sections: **Bug**, **Change**, **Regression test**, **Risk**. If all 4 are present and non-empty → PASS. |
| `F-SPEC-*` / `W-SPEC-*` (spec/fix-plan) | **Do not apply.** QUICK-FIX has no PLAN phase, so it has no spec, no rollback plan and no RCA — it is too small for any of the three to be worth writing. The regression test is declared in the fix-brief (the "Regression test" field). |
| `F-TM-*` / `W-TM-*` (threat model) | **Skipped** if the diff does NOT touch security-sensitive paths (backed by the shared gate's QUICK-FIX scope guard, which is a path/LOC denylist, not a proof that no attack surface exists; SAST runs regardless). They are replaced by the automatic entry: "No new attack surface — diff confined to `{paths}`, ≤ 10 LOC, no auth/API/schema/input-validation". |
| `F-SAST-*` (SAST) | **Apply in full.** SAST is QUICK-FIX's only security validation and it is a blocking gate (the `sast` gate). It is NOT relaxed. |
| `F-VER-*` (verify-module) | **Do not apply.** QUICK-FIX has no VERIFY phase. |

Guiding rule: QUICK-FIX reduces validation noise (it does not demand NFRs, an "Out of Scope"
section, or PRD↔spec traceability for a typo) **without** touching the security floor: a regression
test + a clean SAST remain mandatory.

---

## 1. PRD Validation (`ddw-validate-prd`)

**Applies in:** the DEFINE phase.
**Basis:** IEEE 830 (Software Requirements Specification), INVEST (Independent, Negotiable,
Valuable, Estimable, Small, Testable), EARS (Easy Approach to Requirements Syntax).

### FAIL rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-PRD-01 | FR with no AC | Every functional requirement (FR-xx) must have at least one acceptance criterion (AC-xx) validating it, and the AC must **name** it — the check looks for the FR's own identifier inside the criterion's text, because "validates it" is not something a script can read any other way. Write `- AC-01 (FR-01): …`. If an FR is named by no AC → FAIL. | IEEE 830 §4.3.1: every requirement must be verifiable. INVEST: Testable. If you cannot verify it, you cannot ship it. |
| F-PRD-02 | Non-binary AC | Every acceptance criterion must be evaluable as PASS or FAIL without ambiguity. It must follow the pattern: "Given [context], when [action], then [measurable result]". If an AC says "works correctly", "behaves appropriately" or uses any unmeasurable adjective → FAIL. | BDD: acceptance criteria are verifiable contracts. An ambiguous AC produces divergent implementations. |
| F-PRD-03 | NFR with no metric | Every non-functional requirement (NFR-xx) must include a quantitative value. Valid examples: "< 500ms p95", "99.9% uptime", "≥ 80% coverage". Invalid examples: "fast", "secure", "scalable", "highly available". | IEEE 830 §3.4: NFRs must be measurable. "Fast" is not a requirement, it is a wish. Without a number there is no possible acceptance criterion. |
| F-PRD-04 | Empty "Out of Scope" | For tier FEATURE: the "Out of Scope" section must exist and contain at least one explicit item. If the section is missing or empty → FAIL. | The #1 cause of scope creep is not defining what is NOT included. Whatever is not explicitly excluded is assumed to be included. |
| F-PRD-05 | Non-unique IDs | Every FR, NFR and AC must have a unique identifier (FR-01, NFR-01, AC-01). If there are duplicate or missing IDs → FAIL. | Without unique IDs there is no traceability. You cannot link PRD → spec → test → code. |
| F-PRD-06 | Ambiguous verb | Requirements must use defined imperative verbs: "must", "must not". If a requirement uses "should", "could", "may", "ideally", "it is recommended" → FAIL. | IEEE 830 §3.1: "shall" for mandatory; "should" is forbidden in requirements because it creates contractual ambiguity. A requirement that "should" be met is a requirement that can be ignored. |
| F-PRD-07 | Undeclared dependencies | If an FR references another module, an external service, or an existing feature, that dependency must be listed in the "Dependencies" section. If there are undeclared cross-references → FAIL. | Undeclared dependencies cause implementation blockers and integration errors. |
| F-PRD-08 | Missing structural section | The PRD must contain ALL of these sections: Context and Problem, Goals, Functional Requirements, Non-Functional Requirements, Acceptance Criteria, Out of Scope (FEATURE), Dependencies. If any is missing → FAIL. | A structurally incomplete PRD cannot be validated. Missing sections are requirements nobody thought about. |
| F-PRD-LOOP | Corrective loop at its ceiling | The PRD header's `Loops since last human decision` reached 3 (falling back to `PRD loops` when a document predates the second counter). **Two numbers on purpose:** `PRD loops` is the running total, never reset, so six months on the document can say what it cost; the ceiling measures rounds since a person last decided something, because a round the model drove and a round a reviewer asked for are not the same event — and a review comment is already the decision this ceiling exists to provoke. The loop is mandatory while it converges; three rounds without converging means what is missing is a decision nobody wrote down, not another pass. → FAIL, and the way past it is a human answering, with the counter reset and their answer recorded. | Under `autonomy: minimal` this is one of the three stops that have no mode. A counter incremented and compared to nothing is a tally, not a stop. |
| F-PRD-09 | AC not in EARS form | Every acceptance criterion must match one of the five EARS patterns (see below). An AC that matches none → FAIL, quoting it and naming the pattern it most likely wants. **Does not apply to DISCOVERY**, whose PRDs are exploratory, or to QUICK-FIX, whose artifact is the 4-line fix-brief. | EARS (Easy Approach to Requirements Syntax, Rolls-Royce) turns a criterion into a shape a reader can check rather than a sentence they have to interpret. It is what AWS's Kiro adopted for spec-driven work with agents, for the same reason: a template makes an *absent* case visible, and free prose does not. |

### WARNING rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| W-PRD-01 | FR with no rationale | An FR has no context for why it exists. The requirement is clear, but the motivation is not explained. | IEEE 830 §2.4: rationale makes trade-off decisions easier. Does not block, because the requirement is executable without it. |
| W-PRD-02 | Too many ACs per FR | An FR has more than 5 acceptance criteria. It may indicate the requirement should be split. | INVEST: Small. Does not block, because it can be legitimate (a complex requirement), but it flags a possible granularity problem. |
| W-PRD-03 | Passive voice | A requirement uses the passive voice ("the data is validated" instead of "the system must validate the data"). The passive voice hides the responsible actor. | Clarity. Does not block, because the meaning may be inferable from context. |
| W-PRD-04 | No unwanted-behaviour AC | **No acceptance criterion uses the EARS unwanted-behaviour pattern** (`IF … THEN … SHALL`). Count them: zero → WARNING naming the FRs whose failure modes nobody wrote down. | Completeness, made checkable. Phrased as "an FR does not mention what happens if it fails" this was a judgement the reader had to make and could quietly not make; as a count of a pattern it is either there or it is not. Still does not block at PRD level — a feature can legitimately have no error path, and the rule that *does* block is F-SPEC-16, one phase later, where the answer is actionable. |
| W-PRD-05 | Empty "Risks and Mitigations" | The section exists but has no content, or does not exist. | Planning. Does not block, because technical risks are explored further in the spec and threat model. |

### The five EARS patterns (for F-PRD-09 and W-PRD-04)

| # | Pattern | Template | For |
|---|---|---|---|
| 1 | Ubiquitous | `THE <system> SHALL <response>` | Always true, no trigger |
| 2 | Event-driven | `WHEN <trigger>, THE <system> SHALL <response>` | A response to something happening |
| 3 | State-driven | `WHILE <precondition>, THE <system> SHALL <response>` | True for as long as a state holds |
| 4 | Optional feature | `WHERE <feature is included>, THE <system> SHALL <response>` | Only in variants that have it |
| 5 | **Unwanted behaviour** | `IF <trigger>, THEN THE <system> SHALL <response>` | **Faults, failures, errors, misuse** |

They compose: `WHILE <precondition>, WHEN <trigger>, THE <system> SHALL <response>`.

**Pattern 5 is the one that earns the notation its place here.** The other four describe what the
system does when things go as expected, and those get written without being asked for. The failure
cases are the ones that get left out — and in free prose, leaving them out looks exactly like a
requirement that has none. Given a template, their absence is countable.

```
AC-03  WHEN a ticket is submitted, THE system SHALL classify it and store the draft reply.
AC-04  IF the classifier is unavailable, THEN THE system SHALL queue the ticket and
       notify the operator within 30 seconds.
```

`SHALL` and not "should": F-PRD-06 already forbids the ambiguous verbs, and EARS uses the one it
demands.

---

## 2. Spec and Fix-Plan Validation (`ddw-validate-spec`)

**Applies in:** the PLAN phase.
**Basis:** bidirectional traceability (IEEE 830 §2.6), OWASP ASVS (security in design), the
completeness principle (every design decision must be documented).

### 2.1 PRD → Spec coverage (FAIL = incomplete coverage)

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-SPEC-01 | FR with no coverage | **Every FR in the PRD must map to at least one block of the spec.** If an FR-xx from the PRD is not referenced in any block → FAIL. No exceptions. If the FR was deliberately deferred → it must first be removed from the PRD (with the user's approval), not ignored in the spec. | This is the fundamental rule of the PRD→Spec contract. An approved FR nobody implements is a broken promise. If the scope changed, the PRD must reflect it. |
| F-SPEC-02 | AC with no test | **Every AC in the PRD must map to at least one test described in the spec.** If an AC-xx has no associated test in any block → FAIL. | IEEE 830 verifiability. If no test is planned for an AC, that AC will not be verified. What is not verified, does not work. |
| F-SPEC-03 | NFR with no strategy | **Every NFR in the PRD must have a documented technical strategy in the spec.** If the PRD says "< 500ms p95" and the spec does not explain how that is achieved → FAIL. | NFRs with no strategy are discovered as problems in production. The strategy may be "the framework handles it by default", but it has to be written down. |

### 2.2 Spec → PRD traceability

| ID | Check | Precise description | Basis |
|---|---|---|---|
| W-SPEC-01 | Block with no FR | A block of the spec references no FR from the PRD. It may be gold-plating (unapproved scope) or a legitimate technical enabler. Report it for review. | Bidirectional traceability. A block with no FR may be necessary (infra, setup) but must be justified. WARNING because there are legitimate technical blocks with no direct FR. |

### 2.3 Per-block completeness

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-SPEC-04 | Block with no files | Every block must explicitly list which files are created and/or modified, with relative paths. If a block has no file list → FAIL. | A block with no files is not actionable. The implementer does not know where to work. |
| F-SPEC-05 | Block with no completion criterion | Every block must have a verifiable completion criterion (not "it is done" but "tests X, Y, Z pass and the endpoint returns 200"). If missing → FAIL. | Without a completion criterion, you cannot determine when a block is ready. Causes infinite "is it done yet?" loops. |
| F-SPEC-06 | Block with no tests | Every block must list at least one required test, with a description of what it validates. If a block has no tests → FAIL. | Code with no planned tests = code with no verification. Tests are not optional. |
| F-SPEC-07 | API with no contract | Every block that creates or modifies an endpoint must specify: HTTP method, path, request body/params (with types), response body (with types), error codes, and authentication/authorization requirements. If any is missing → FAIL. | An endpoint without a complete contract produces: trial-and-error integration, runtime type errors, and authentication vulnerabilities. OWASP ASVS V13: API Security. |
| F-SPEC-08 | Data model with no constraints | Every block that creates or modifies a model/schema must specify: entity name, fields with types, constraints (nullable, unique, FK, default), and indexes where applicable. If any is missing → FAIL. | A schema without constraints = data corruption. A field that "should" be unique but has no constraint will end up with duplicates. |
| F-SPEC-09 | Input with no validation | Every block that receives user input must specify validation rules: type, maximum length, format, allowed values. If the block accepts input and does not document validation → FAIL. | OWASP Top 10 A03 (Injection). Input with no documented validation = input with no implemented validation = a vulnerability. |
| F-SPEC-10 | No error handling | Every block must document which errors can occur and how they are handled (error code, message, action). If a block has no error-handling section → FAIL. | Undocumented error handling gets implemented ad hoc: every developer invents their own format, errors get swallowed, and the user sees inconsistent messages or stack traces. |
| F-SPEC-11 | Undocumented dependencies between blocks/steps | The spec (or fix-plan) must have a dependencies section stating which blocks (FEATURE) or steps (FIX) depend on which. If blocks or steps reference other blocks' entities/services with no declared ordering → FAIL. | Without a dependency order, parallel implementation causes merge conflicts and integration errors. |
| F-SPEC-LOOP | Corrective loop at its ceiling | The spec header's `Loops since last human decision` reached 3. Same rule and same reason as `F-PRD-LOOP`. | Same. |
| F-SPEC-16 | Documented error with no test | **Every error a block documents under F-SPEC-10 must appear in that block's test list (F-SPEC-06).** Count them: fewer tests naming an error condition than errors documented → FAIL, naming which ones are unaccounted for. | This is the same standard F-VER-04 already applies — every input path needs a sad-path test — moved to the phase where it can still be met. F-SPEC-10 makes the errors *written down*; without this rule nothing makes them *tested*, so a spec passes PLAN with a full error section and a happy-path-only test list. VERIFY then catches it two phases later, when the code exists and the test can no longer be written first: a test added to cover an error path that already works documents the status quo, which is exactly what Rule #-1 in `testing.instructions.md` says proves nothing. The gap is not in CODE. It is here. |

### 2.4 Spec ↔ PRD consistency

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-SPEC-12 | Contradicts the PRD | The spec must not contradict any requirement in the PRD. If the PRD says "response < 200ms" and the spec designs a synchronous chain of 5 external calls with no cache → FAIL (the design cannot meet the requirement). | The spec is the HOW for the PRD's WHAT. If the HOW cannot satisfy the WHAT, one of the two has to change — you do not ignore the contradiction. |
| F-SPEC-13 | Inconsistent terminology | The spec must use the same terminology as the PRD. If the PRD says "Product" and the spec says "Item" or "Article" for the same entity → FAIL. | Divergent terminology causes divergent implementations. If the name changes, there must be an explicit mapping. |

### 2.5 Fix-Plan (tier FIX)

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-SPEC-14 | Fix with no regression test | Every fix-plan must include at least one test reproducing the original bug. If there is no regression test → FAIL. | A fix with no regression test will break again. The test must fail BEFORE the fix and pass AFTER. Standard practice in every engineering team. |
| F-SPEC-15 | Fix-plan with no rollback plan | For tier FIX: the fix-plan must include rollback steps and the indicators for when to apply them. If reverting really is trivial, the section still has to exist and say so explicitly. Absent → FAIL. | A fix that reaches production with no thought about reverting it can end up worse than the defect. Standard in incident management (ITIL, Google SRE). If a change is too small to deserve a rollback plan, it is a QUICK-FIX, not a FIX. |

### 2.6 Spec warnings

| ID | Check | Precise description | Basis |
|---|---|---|---|
| W-SPEC-02 | Large block | A block modifies more than 5 files or has more than 500 words of description. It may indicate it should be split. | Maintainability. Does not block, because some blocks (refactoring, infra) legitimately touch many files. |
| W-SPEC-03 | No rollback (FEATURE) | For tier FEATURE: the spec includes no rollback or reverse-migration considerations. Does not apply if there are no schema changes or data migrations. | Good practice. Not always necessary for pure features with no migration. |

---

## 3. Threat Model Validation (`ddw-threat-modeling`)

**Applies in:** the PLAN phase.
**Basis:** STRIDE (Microsoft), OWASP Threat Modeling, OWASP ASVS, ISO 27001 (security risk
management).

### FAIL rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-TM-01 | Component with no STRIDE analysis | Every component or service the spec introduces or modifies must be evaluated against the 6 STRIDE categories (Spoofing, Tampering, Repudiation, Information Disclosure, DoS, Elevation of Privilege). If a component has no analysis → FAIL. | STRIDE is the de facto standard for threat modeling. An unanalyzed component is an invisible attack surface. Microsoft SDL requires it for every new feature. |
| F-TM-02 | Unidentified trust boundary | Every interface between components with different trust levels must be identified as a trust boundary (e.g. client→server, server→DB, API→external service). If there are interfaces between trust zones with none declared → FAIL. | Vulnerabilities happen at trust boundary crossings. If you do not identify them, you do not protect them. OWASP Threat Modeling Cheat Sheet. |
| F-TM-03 | Threat with no mitigation | Every identified threat must have a documented mitigation OR an accepted risk with formal approval. If a threat is listed with neither mitigation nor acceptance → FAIL. | An identified but untreated threat is worse than an unidentified one: it proves the risk was known and ignoring it was a choice. ISO 27001 §6.1.2: risk treatment. |
| F-TM-04 | Accepted risk with no approval | If a threat is marked "accepted risk", it must include: (1) who accepted it, (2) the justification, (3) the conditions under which it will be reviewed. If any of the three is missing → FAIL. | ISO 27001 §6.1.3: accepting risk requires approval from the person with authority. A developer cannot self-accept a security risk without the user/owner validating it. |
| F-TM-05 | Sensitive data with no classification | If the spec handles user data, credentials, tokens, or financial information, the threat model must classify it (PII, credentials, financial, public). If there is unclassified sensitive data → FAIL. | You cannot protect what you have not classified. GDPR Art. 32, OWASP ASVS V8: Data Protection. The classification determines the required controls (encryption, access, retention). |
| F-TM-06 | Generic threat model | The threat model must reference the spec's real architecture (components, endpoints, specific data flows). If the threat model is a generic template unrelated to the concrete design → FAIL. | A threat model that does not reflect the real system is security theater. It protects nothing. |
| F-TM-07 | Sensitive data with no encryption | If the threat model identifies data classified as PII or credentials, it must specify encryption at rest and in transit. If it does not → FAIL. | OWASP ASVS V6: Cryptography. GDPR Art. 32: appropriate technical measures. Storing PII unencrypted is a regulatory violation in most jurisdictions. |

### WARNING rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| W-TM-01 | No dependency analysis | The threat model does not analyze supply chain risks (third-party dependencies). | Relevant but not always applicable if no new dependencies are added. OWASP A06: Vulnerable Components. |
| W-TM-02 | No availability analysis | The threat model does not analyze DoS vectors for services that are non-critical or internal-only. | DoS is part of STRIDE, but for low-traffic internal services it may be a minor risk. |

---

## 4. SAST Validation (`ddw-security-sast`)

**Applies in:** the CODE phase (blocking gate).
**Basis:** OWASP Top 10 (2021), CWE Top 25, OWASP ASVS v4, NIST SP 800-53.

### 4.1 Finding Severity Classification

SAST findings are classified by severity. The severity determines the disposition:

| Severity | Disposition | Can be suppressed | Condition for suppression |
|---|---|---|---|
| **Critical** | **FAIL — always blocks** | No | None. It must be fixed. |
| **High** | **FAIL — always blocks** | No | None. It must be fixed. |
| **Medium** | **FAIL — blocks by default** | Yes, with documentation | A false positive documented with justification + reviewer, OR an accepted risk with the user's approval. |
| **Low** | **WARNING** | N/A (does not block) | Reported and documented. Does not block. |
| **Informational** | **WARNING** | N/A (does not block) | Reported. Does not block. |

### 4.2 Categories that are ALWAYS FAIL

Regardless of tool or context, these findings are ALWAYS FAIL (Critical/High):

| ID | Category | CWE | Severity | Basis |
|---|---|---|---|---|
| F-SAST-01 | Hardcoded secrets | CWE-798 | Critical | Credentials in source code persist in git history forever. OWASP A07. |
| F-SAST-02 | SQL injection | CWE-89 | Critical | Direct database compromise. OWASP A03. |
| F-SAST-03 | OS command injection | CWE-78 | Critical | Remote code execution on the server. OWASP A03. |
| F-SAST-04 | Insecure deserialization | CWE-502 | Critical | Remote code execution vector. OWASP A08. |
| F-SAST-05 | Path traversal | CWE-22 | High | Access to system files outside the allowed directory. OWASP A01. |
| F-SAST-06 | XSS (Reflected or Stored) | CWE-79 | High | Code execution in other users' browsers. OWASP A03. |
| F-SAST-07 | SSRF | CWE-918 | High | Access to the internal network and cloud metadata. OWASP A10. |
| F-SAST-08 | Broken cryptography | CWE-327 | High | MD5, SHA1 for passwords, DES, ECB mode. Passwords compromisable in a breach. OWASP A02. |
| F-SAST-09 | Debug mode in production | CWE-489 | High | Exposes stack traces, internal configuration, and possibly code execution. OWASP A05. |
| F-SAST-10 | Logging sensitive data | CWE-532 | High | Passwords, tokens, PII in logs = a data breach via logs. OWASP A09. |
| F-SAST-11 | Unrestricted upload | CWE-434 | High | Uploading executables, webshells. OWASP A04. |
| F-SAST-12 | Missing CSRF protection | CWE-352 | High | State-changing operations without CSRF protection in web apps. OWASP A01. |
| F-SAST-13 | Critical/High CVE in a dependency | — | Critical/High | A public exploit is available. OWASP A06. |

### 4.3 Medium categories (FAIL, suppressible with documentation)

| ID | Category | Example | Basis |
|---|---|---|---|
| F-SAST-14 | Incomplete input validation | Input accepted without validating type/length/format. | CWE-20. Depends on context: internal vs external input. |
| F-SAST-15 | Insecure error handling | A generic catch that exposes internal details. | CWE-209. The impact depends on what information is exposed. |
| F-SAST-16 | Medium CVE in a dependency | Known vulnerability, non-trivial exploit. | OWASP A06. Assess whether the vulnerable function is used. |
| F-SAST-17 | Unsafe function | Use of `eval()`, `exec()`, deserialization functions without context. | CWE-95. Depends on whether the input is controlled. |

### 4.4 Finding Suppression Protocol

**Every finding, including false positives, must be documented.** An undocumented finding is an
unreviewed finding.

To suppress a Medium finding as a false positive or an accepted risk:

```markdown
### Suppression: [finding ID]

| Field | Value |
|---|---|
| File | [path:line] |
| Category | [finding category] |
| Disposition | FALSE_POSITIVE / ACCEPTED_RISK |
| Reviewer | [name of the user who reviewed it] |
| Date | [review date] |
| Justification | [1–3 sentences explaining why it is not exploitable, or why it is accepted] |
| Compensating control | [ACCEPTED_RISK only: which other control mitigates the risk] |
| Review by | [latest date to re-evaluate, at most 6 months out] |
```

**Suppression rules:**

| ID | Check | Severity |
|---|---|---|
| F-SAST-SEVERITY | Severity downgraded by marker | A Critical or High category filed under `⚠️`. The catalog fixes the severity per category; a marker does not change it, and *What can NEVER be a WARNING* names a confirmed vulnerability explicitly. → FAIL, and it still owes a location, a BLOCKED verdict and (never) a suppression. | It was the cheapest bypass in the script: a warning marker exempted a Critical from every other rule at once. |
| F-SAST-SUPPRESS | Critical or High suppressed | §4.1 says Critical and High cannot be suppressed. A suppression block naming one → FAIL. | Nothing enforced it, so the seven fields were being validated for a finding the catalog says has to be fixed. |
| F-SAST-COVERAGE | A catalogued category with no verdict | Every mandatory category above has to carry a ✅ / ⚠️ / ❌ on its own line, with its ID. A category the report never judged is a category nobody scanned, and it used to be indistinguishable from a clean one. → FAIL, naming each missing ID. |
| F-SAST-LOCATION | A finding with no file and line | Any ❌ or ⚠️ has to name `file:line`. A finding nobody can navigate to is a finding nobody will fix, and it is what a report says when it is describing a category rather than reporting a scan. → FAIL. |
| F-SAST-MEDIUM | A Medium neither fixed nor suppressed | §4.1 makes Medium a FAIL by default, suppressible only with the seven fields of §4.4. A Medium listed and then left alone is the disposition the catalog does not have. → FAIL. |
| F-SAST-VERDICT | The stated result contradicts the findings | The report says PASSED (or does not say BLOCKED) while listing a Critical or High. The verdict line is what the state reads; a report whose summary disagrees with its own body is the one shape a receipt must never attest. → FAIL. |
| F-SAST-18 | Every suppression must have all 7 fields filled in. If any is missing → FAIL. | FAIL |
| F-SAST-19 | Suppressions must be reviewed when SAST is re-run. If a suppression is more than 6 months old → FAIL (it must be re-evaluated). | FAIL |
| W-SAST-01 | Low or Informational finding left undocumented. | WARNING |

---

## 5. Module Verification (`ddw-verify-module`)

**Applies in:** the VERIFY phase.
**Basis:** requirements traceability, test coverage, the principle of independent verification.

### FAIL rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-VER-01 | AC with no passing test | **Every AC in the PRD must have at least one test validating it, and that test must be passing.** If an AC has no test, or the test exists but fails → FAIL. | The AC is the contract with the user. Without a test validating it, there is no evidence it works. |
| F-VER-02 | Spec task not implemented | **Every task/block in the spec, or step in the fix-plan, must be implemented.** If a whole block or a fix-plan step has no corresponding code → FAIL. | The spec is the approved plan. Partial implementation = an incomplete feature = a bug. |
| F-VER-03 | Test coverage below the minimum | **Line coverage ≥ 80%, branch coverage ≥ 80%, and function coverage ≥ 80%** over the new/modified code. If any is below → FAIL. | `.ddw/rules/testing.instructions.md` defines these three minimums. Verify they are met, not just that "there are tests". |
| F-VER-04 | No sad-path tests | **Every endpoint or function accepting input must have at least one test with invalid input.** If there are only happy-path tests → FAIL. | The worst bugs live in edge cases and sad paths. Testing only the happy path tests only 20% of the real behavior. |
| F-VER-05 | Lint/type checker fails | If the project has a linter or type checker configured and there are errors → FAIL. | Lint/type errors indicate code that can fail at runtime. You cannot verify code that does not compile or pass lint. |
| F-VER-06 | Spec tests not implemented | **Every test listed in the spec must exist and pass.** If the spec says "test: creating a product with an empty name returns 400" and that test does not exist → FAIL. | The spec's tests are quality commitments the user approved. Not implementing them is breaching the spec. |

### WARNING rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| W-VER-01 | Dead code | Unused imports, unreferenced functions, declared-but-unused variables. | Cleanliness. Does not affect functionality but reduces maintainability. |
| W-VER-02 | Business-logic coverage < 90% | Core business logic (services, domain) has coverage between 80–90%. It does not fail (it is above the minimum) but it should be higher. | `.ddw/rules/testing.instructions.md` recommends 90%+ for business logic. |
| W-VER-03 | Fragile test | A test depending on execution order, global state, or hardcoded values (timestamps, IDs). | Test maintainability. Does not block but causes future flakiness. |

---
## 6. Test Run Report (`ddw-test`)

**Applies in:** the CODE phase, before the `tests` gate is claimed.
**Artifact:** `docs/ddw/reports/tests-{ticket}.md`.

**DDW does not run your suite, and this section does not pretend otherwise.** It does not know
whether this is pytest or jest or a monorepo with five runners, in what directory, with which
environment; being wrong about that in somebody else's repository is what `docs/RATIONALE.md`
decision 2 refuses. The numbers below are the model's account of a run it did.

What stops being optional is the account. `tests: true` used to be a sentence — no runner, no
command, no numbers, no names, nothing anyone could reproduce or act on. These rules make the report
a document; whether it is a true document remains the reader's judgement, and every run says so.

### FAIL rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| F-TEST-01 | Run not reproducible | The report must name the **runner** and the **exact command**. Missing either → FAIL. | A result nobody can re-run is an anecdote. This is also the only verification available to a human in ten seconds, which is the whole point of writing it down. |
| F-TEST-02 | Counts absent or impossible | Total, passed and failed must be present, and `passed + failed + skipped` must equal `total`. Missing or contradictory → FAIL. | Arithmetic is the one thing a report cannot get wrong quietly. A count that does not add up is a report about two different runs. |
| F-TEST-03 | Failure with no name | Every reported failure must be identified by its test ID. A count with no names → FAIL. | The corrective loop needs something to work from. "3 failed" tells nobody which three. |
| F-TEST-04 | Coverage incomplete or under the floor | Line, branch and function coverage must each be stated as a number, and each must be at or above the floor. Missing one, or under → FAIL. | One coverage number hides the other two: a suite can touch every line and no branch. Under the floor is the condition the loop exists for. |
| F-TEST-05 | Floor not stated or not sourced | The report must state the coverage floor and where it comes from (`AGENTS.md`, the spec). Absent → FAIL; stated without a source → WARNING. | A report that chooses its own floor passes itself. The floor belongs to the project. |
| F-TEST-07 | More than one run in one report | A count or coverage field appearing twice (a per-suite breakdown). Every rule reads the first value it finds, so a second suite is not checked at all → FAIL. | A green unit suite above a red integration suite was read as the unit suite alone, with five failures on the page nobody counted. |
| F-TEST-08 | A red run earning the gate | `Failed` greater than zero → FAIL. `ddw-test`'s own criterion is 0 failing tests, and the validator that writes the gate's receipt was not checking it. | A report of a red run does not earn the tests gate, however complete the report is. |
| F-TEST-06 | Silent skip | Every skipped test must carry a reason. Skips with no explanation → FAIL. | A silent skip is the cheapest way to make a suite green, and it looks identical to a test that exists. |

### WARNING rules

| ID | Check | Precise description | Basis |
|---|---|---|---|
| W-TEST-01 | No lint or type-check result | The report does not state the linter or type checker's result. | VERIFY asks for it under F-VER-05, so this is a reminder rather than a block — but a CODE phase that never ran the linter will find out two phases later. |


---


## Quantitative Summary

| Area | FAIL rules | WARNING rules | Total |
|---|---|---|---|
| PRD | 10 | 5 | 15 |
| Spec / Fix-Plan | 17 | 3 | 20 |
| Threat Model | 7 | 2 | 9 |
| SAST | 21 | 1 | 22 |
| Test Run Report | 8 | 1 | 9 |
| Module Verify | 6 | 3 | 9 |
| **Total** | **69** | **15** | **84** |

---

## Operational Skills (no rules in this catalog)

The following skills perform operational checks (direct pass/fail) and have NO rules enumerated in
this catalog. Their behavior is defined in their respective instruction files:

| Skill | Phase | Behavior | Defined in |
|---|---|---|---|
| `ddw-validate-arch` | CODE | Validates the project's architecture conventions. The rules depend on the target project (`AGENTS.md`). If it reports violations → BLOCKED. | `.ddw/rules/code.instructions.md` |
| `ddw-test` | CODE | **Moved to §6.** Its run report has `F-TEST-01`…`08` and `W-TEST-01`, and the `tests` gate refuses without the receipt they write. This row said it was a runner with no rules in this catalog while the catalog carried eight of them. | Runs the test suite. If it fails → BLOCKED. It is a runner, not an artifact validator. | `.ddw/rules/code.instructions.md`, `.ddw/rules/testing.instructions.md` |

These skills are operational gates: they run and report pass/fail. Test quality rules (coverage,
traceability, sad paths) are evaluated in the VERIFY phase by `ddw-verify-module` (section 5 of this
catalog).

---

## How a validation runs — the same four steps every time

This section is the protocol. Every skill in this catalog follows it, and a skill that skips a step
has not validated anything, whatever its box says.

### 1. Run the script. It IS the validation.

| Skill | Script | Receipt it writes on PASSED |
|---|---|---|
| `ddw-validate-prd` | `.ddw/scripts/validate_prd.py <artifact> --tier <tier>` | `.ddw-sessions/prd-validated-<hash>` |
| `ddw-validate-spec` | `.ddw/scripts/validate_spec.py <artifact> --tier <tier>` | `.ddw-sessions/spec-validated-<hash>` |
| `ddw-threat-modeling` | `.ddw/scripts/validate_threat.py <artifact> --tier <tier>` | `.ddw-sessions/threat-validated-<hash>` |
| `ddw-verify-module` | `.ddw/scripts/validate_verify.py <artifact> --tier <tier>` | `.ddw-sessions/verify-validated-<hash>` |
| `ddw-security-sast` | `.ddw/scripts/validate_sast.py <artifact> --tier <tier>` | `.ddw-sessions/sast-validated-<hash>` |
| `ddw-test` | `.ddw/scripts/validate_tests.py <artifact> --tier <tier>` | `.ddw-sessions/tests-validated-<hash>` |

The hash is of the artifact's **current bytes**, and the gate the phase needs asks for exactly that
receipt. So the incentive points the right way: there is no route to the next phase that goes around
the checklist, and editing the artifact afterwards costs another run rather than nothing.

`ddw-security-sast`'s receipt is the newest and the one whose scope is easiest to overread. **It
attests the REPORT, never the code.** DDW does not scan anything: the finding is a model reading
source, and no file will make that a proof. What the validator answers is structural — every
catalogued category carrying a verdict, every finding naming a file and a line, the stated result
consistent with the severities listed, every Medium fixed or suppressed, every suppression carrying
its fields and inside its review window.

That distinction is the whole of it, and it is the same one `validate_verify.py` already makes: the
numbers stay the model's, the completeness stops being optional. What went unguarded while the
distinction was being argued about was the report itself — nineteen rules catalogued here, none of
them ever executed, and a `sast` gate that turned true because the model said the reading went well.

### 2. Fix what the script found — the loop, before anyone is asked anything

- **❌ FAIL — the loop is mandatory.** Correct the artifact and run the script again. Repeat until
  zero FAILs or until a fix would require deciding something nobody has written down. Fix **only
  what the rule names**: a rule about a missing test list is not permission to invent requirements,
  and an invented requirement is a worse defect than the one it silenced.
- **⚠️ WARNING — attempt it.** Same restriction. If clearing it needs a decision, leave it and carry
  it to step 3. Warnings never block.
- **Never edit the rules, the catalog, or the script to make a check pass.** That is the one
  correction that is always wrong.

### 3. Ask, only about what is genuinely undecided

Whatever survives the loop because it needs a human decision becomes a question — asked **after** the
loop, never instead of it. Each question carries: what is missing, **2–4 concrete options** with what
choosing each one means, and the option of the user answering in their own words. Ask in plain
language: the user is deciding about their product, not about this pipeline's vocabulary.

### 4. Show the whole table, then ask for approval

Paste the script's output **verbatim**. Not a summary, not the IDs with the descriptions dropped, not
"7 checks passed" — every row, with its ✅ / ⚠️ / ❌, its rule ID and what was checked. Then the
totals, the verdict, and **always the link to the full report on disk**, which every script writes
next to the artifact as `<artifact>.validation.md`.

A run that shows the user no checklist did not validate anything they can act on. The user is the one
approving; approval on a summary is approval of a summary.

**A re-validation is a validation, and it shows the whole table too.** Running the script again on an
artifact that has not changed — reopening a ticket, resuming after a split, being asked to advance a
second time — ends in the same paste, in full. The temptation to compress it is specific and it is
wrong twice over: *"you already saw this"* is a claim about a previous screen, in a session that may
not be this one, and *"the receipt already matches"* answers a different question — the receipt says
the bytes are unchanged, not that anyone read what was checked. Measured live: the first run of five
PRDs printed five complete tables, and the re-validation of the same artifact minutes later collapsed
to `Validación: ✅ PASSED (7 checks)`. Same script, same output, half of it withheld at exactly the
moment the user was asked to approve.

---

## Validation Report Format

Every validation skill must produce a report in this format:

```
┌─────────────────────────────────────────────────────────────┐
│  /ddw-validate-[type] [artifact] — [PASSED | FAILED]         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Section 1: category name]                                  │
│    ✅ [ID]: [check description] (if it passed)               │
│    ❌ [ID]: [check description] (if it failed)               │
│       → [explanation of what is missing and how to fix it]   │
│    ⚠️  [ID]: [check description] (if warning)                 │
│       → [improvement suggestion]                             │
│                                                              │
│  [Section 2: category name]                                  │
│    ...                                                       │
│                                                              │
│  ────────────────────────────────────────────────────────────│
│  Total: [N] passed, [M] failed, [K] warnings                 │
│  Result: [PASSED if M == 0 | FAILED if M > 0]                │
│  Full report: [path to <artifact>.validation.md]             │
│  Next: [what to do based on the result]                      │
└─────────────────────────────────────────────────────────────┘
```

The **Full report** row is mandatory and never a placeholder: it is the path the script printed, and
it is what lets the user read the whole checklist without asking for it again.

**Result rule:**
- If there is at least 1 FAIL → result = **FAILED**. Gate blocked.
- If there are 0 FAILs → result = **PASSED** (with or without warnings).
- Warnings are reported but never block.
