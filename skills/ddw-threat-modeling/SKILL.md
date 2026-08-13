---
name: ddw-threat-modeling
description: >
  Threat analysis of the proposed design. Identifies new attack surfaces and security risks before
  any code is written. The findings become mitigations folded into the spec.
  Trigger: /ddw-threat-modeling, during DDW's PLAN phase.
---

# Skill: /ddw-threat-modeling

## Description
Threat analysis of the proposed design. Identifies new attack surfaces and security risks before any
code is written. The findings become mitigations folded into the spec.

### What a threat model is, and what it is not

**A threat model asks what an attacker can do to THIS design, and what is done about each answer.**
It names the real components, the real data, the real boundaries the design crosses, and walks
STRIDE over them. Every threat ends in one of two places: a mitigation that goes into the spec, or a
risk formally accepted with who accepted it, why, and when it gets revisited.

It is not a security checklist. A document that says "validate all input, use HTTPS, hash passwords"
without naming a component of this system protects nothing and is why F-TM-06 compares it against
the spec: a model that would read the same for any project has not looked at this one.

It is written before the spec is finished on purpose — it is the last step that can still add files
to the plan, and it regularly does. It is validated after the spec exists, against it.

## Inputs
- The proposed design (the plan in progress, before it is written to disk).
- The PRD at `docs/ddw/prd/prd-{ticket}.md` (if `gates.define` is true and the tier is FEATURE).
- `.ddw/rules/security.instructions.md` for the principles.
- `.ddw/rules/validation-rules.instructions.md` §3 for the rules (F-TM-01 to F-TM-07, W-TM-01 to
  W-TM-02) — the single source of truth for what makes a threat model acceptable.
- The project's architecture conventions (`AGENTS.md`) for architectural context.
- The project's stack: the "Stack" section of `AGENTS.md`.

## Execution Protocol

### 1. Identify attack surfaces

For each new or modified component in the design:
- Does it accept user input? → an injection surface.
- Does it expose sensitive data? → a data leakage surface.
- Does it introduce new authentication/authorization? → a bypass surface.
- Does it integrate with an external service? → a supply chain surface.
- Does it change an existing data flow? → a security regression risk.

Declare the **trust boundaries** between components with different trust levels (F-TM-02): a missing
boundary is a FAIL, because vulnerabilities happen precisely at those crossings.

### 2. Evaluate by STRIDE category

Every component gets all six (F-TM-01):

| Category | Question |
|----------|----------|
| **Spoofing** | Can an actor's identity be impersonated? |
| **Tampering** | Can data be modified in transit or at rest? |
| **Repudiation** | Can an action be denied afterwards? Is there logging? |
| **Information Disclosure** | Is sensitive information exposed? |
| **Denial of Service** | Can the service be degraded or taken down? |
| **Elevation of Privilege** | Can privileges be escalated? |

### 3. Classify the risks

For each identified risk:

| Field | Value |
|-------|-------|
| Risk | [description] |
| STRIDE category | [S/T/R/I/D/E] |
| Likelihood | [High/Medium/Low] |
| Impact | [Critical/High/Medium/Low] |
| Proposed mitigation | [description] |

Classify any sensitive data the design handles (F-TM-05: PII, credentials, financial, public), and
specify encryption at rest and in transit for PII and credentials (F-TM-07).

### 4. Propose mitigations

For every CRITICAL or HIGH risk:
- Propose a concrete mitigation, which gets folded into the spec.
- If the mitigation changes the architecture → tell the user.
- If there is no viable mitigation → document it as an accepted risk. That requires the user's
  approval plus all three fields (F-TM-04): **who accepted it**, **the justification**, and **the
  conditions under which it will be reviewed**. Missing any of the three is a FAIL.

### 5. Stay specific

The threat model must reference the spec's real architecture — its components, endpoints and data
flows (F-TM-06). A generic template with no connection to the concrete design is a FAIL: it is
security theater and protects nothing.

### 6. Write it down, then validate it mechanically

Write the model to `docs/ddw/security/threat-{ticket}.md` using the template below — the headings
are what the validator parses, so a model written in free prose cannot be checked and cannot earn
its receipt. Then run:

`python3 .ddw/scripts/validate_threat.py docs/ddw/security/threat-{ticket}.md --tier <tier>`

(under a plugin install, resolve `.ddw/scripts/` at the plugin's method path). **Paste its output
VERBATIM** — every row, every rule ID, on **every** run, including a re-validation of a model that
has not changed. A PASSED run writes the content-hashed receipt the `threat` gate demands; without it
the PLAN→CODE transition refuses.

**Every ❌ is a mandatory loop:** fix the model, run it again, until zero FAILs. Fix only what the
rule names — a threat invented to fill a STRIDE row is security theater, which is the exact thing
F-TM-06 exists to catch. What survives because it needs a human decision (accepting a risk, above
all) becomes a question with options, asked after the loop, never instead of it.

What the script answers is structural: six categories per component, boundaries declared, every
threat treated, every acceptance approved, data classified, encryption specified, and the model
citing the real design. **Whether each entry is correct, and whether a mitigation actually
mitigates, stays with you** — say so explicitly under the pasted output.

### Threat model template — canonical

```markdown
# Threat model {ticket}: [Title]

| Field | Value |
|-------|-------|
| Ticket | [ticket] |
| Spec | docs/ddw/specs/spec-{ticket}.md |
| Tier | [tier] |
| Date | [timestamp] |

## Components
| Component | Source in the spec |
|---|---|
| `path/to/file.py` | Block 1 |

## Trust boundaries
- [zone A] → [zone B]: [what crosses it]

## STRIDE analysis
### `path/to/file.py`
- **Spoofing:** [analysis]
- **Tampering:** [analysis]
- **Repudiation:** [analysis]
- **Information Disclosure:** [analysis]
- **Denial of Service:** [analysis]
- **Elevation of Privilege:** [analysis]

## Data classification
| Data | Class | At rest | In transit |
|---|---|---|---|
| [field] | [PII / credentials / financial / public] | [control] | [control] |

## Risks and mitigations
| ID | Risk | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| R-01 | [risk] | [S/T/R/I/D/E] | [H/M/L] | [C/H/M/L] | [mitigation] |

## Accepted risks          (only if there are any)
### R-0x
- **Accepted by:** [who]
- **Justification:** [why]
- **Review conditions:** [when this gets revisited]

## Supply chain
[Third-party dependencies and their risk, or why there are none.]

## Availability
[DoS vectors, or why they are out of scope here.]
```

### The threat model, in the shape the validator reads

The template above is a skeleton, and a skeleton **fails**: every bracketed field is a placeholder,
and `validate_threat.py` refuses a document that still carries them. That refusal is the point — a
copied template with the component name changed used to pass all seven rules and write the receipt
that opens PLAN→CODE, which made the `threat` gate decorative for anyone who did what this skill
says. This is the same document with the analysis actually in it, and it is what the suite runs
through the validator.

```markdown
# Threat model {ticket}: Password login

| Field | Value |
|-------|-------|
| Ticket | {ticket} |
| Spec | docs/ddw/specs/spec-{ticket}.md |
| Tier | FEATURE |
| Date | 2026-08-05 |

## Components
| Component | Source in the spec |
|---|---|
| `src/auth/login.ts` | Block 1 |

## Trust boundaries
- Browser → API: `POST /api/login` carries the password over the public internet.
- API → database: the credential lookup crosses into the private subnet.

## STRIDE analysis
### `src/auth/login.ts`
- **Spoofing:** credential stuffing against a public endpoint; mitigated by per-IP and per-account
  rate limits (R-01).
- **Tampering:** the session token is signed; an altered token fails verification and is rejected.
- **Repudiation:** every login attempt is logged with its outcome, source IP and timestamp.
- **Information Disclosure:** the failure message is identical for unknown user and wrong password,
  so the endpoint does not confirm which accounts exist.
- **Denial of Service:** bcrypt is deliberately slow, so unbounded attempts are a CPU exhaustion
  vector; the same rate limit caps it (R-02).
- **Elevation of Privilege:** the token carries no role claim, so a stolen session cannot be
  upgraded by editing it.

## Data classification
| Data | Class | At rest | In transit |
|---|---|---|---|
| password | credentials | bcrypt, cost 12; the plaintext is never stored | TLS 1.3 |
| session token | credentials | hashed in the sessions table | TLS 1.3, cookie flagged Secure |
| email | PII | AES-256 at the column level | TLS 1.3 |

## Risks and mitigations
| ID | Risk | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| R-01 | credential stuffing | S | H | H | 5 attempts per account per minute, then a lockout |
| R-02 | CPU exhaustion via bcrypt | D | M | M | the same limiter, applied before the hash runs |
| R-03 | session token stolen from a shared machine | I | L | H | accepted, see below |

## Accepted risks
### R-03
- **Accepted by:** Pablo Di Loreto, product owner
- **Justification:** a shared-machine session is out of the threat model for the beta, which is
  invite-only and internal.
- **Review conditions:** revisited before the public launch, or immediately if the beta opens to
  external users.

## Supply chain
`bcrypt` and `jsonwebtoken` are the only new dependencies; both are pinned by digest and scanned by
the SAST step.

## Availability
The rate limiter above is the DoS control. The service is behind the platform's edge limits as well,
so a volumetric attack does not reach this code.
```

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-threat-modeling — [PASSED | MITIGATION REQUIRED]   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Attack surfaces identified: [N]                         │
│  Trust boundaries declared: [N]                          │
│                                                          │
│  Risks:                                                  │
│    🔴 CRITICAL: [description] — Mitigation: [action]     │
│    🟠 HIGH: [description] — Mitigation: [action]         │
│    🟡 MEDIUM: [description] — Mitigation: [action]       │
│    🟢 LOW: [description]                                 │
│                                                          │
│  Mitigations to fold into the spec:                      │
│    1. [mitigation 1]                                     │
│    2. [mitigation 2]                                     │
│                                                          │
│  ─────────────────────────────────────────────────────   │
│  Risks: C:[N] H:[N] M:[N] L:[N]                          │
│  Report: docs/ddw/security/threat-[ticket].md            │
│  Full checklist: threat-[ticket].validation.md           │
└─────────────────────────────────────────────────────────┘
```

Both rows are mandatory: the first is the model itself, the second is the validator's checklist —
the path the script printed, so the user can read every rule instead of asking for it again. The
box is a summary **of** the pasted checklist, never a replacement for it.

## PASS/FAIL criteria
- **PASSED:** every CRITICAL/HIGH risk has a mitigation folded into the spec, and rules F-TM-01 to
  F-TM-07 are satisfied.
- **MITIGATION REQUIRED:** there are CRITICAL/HIGH risks with no mitigation → fold them in before
  writing the spec to disk.

## Tier modifier: QUICK-FIX
Does not apply: that tier has no PLAN phase, so threat modeling never runs for it. SAST in CODE is
its only security validation, and the shared gate's scope guard keeps the diff away from
sensitive paths in the first place.

## Updating .ddw-state.json
- `gates.threat` → `true` when PASSED. The report is saved to `docs/ddw/security/threat-{ticket}.md`
  (derived from the ticket).

## Notes
- This skill does NOT block the phase permanently — the risks get mitigated by changing the design
  before the spec is written.
- It is MANDATORY for FEATURE and FIX. Every code change deserves a threat analysis, even
  a brief one.
- The report is stored alongside the spec for traceability.

## Language

Write the report in the language the user is working in.
