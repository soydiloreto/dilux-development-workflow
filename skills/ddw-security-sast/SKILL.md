---
name: ddw-security-sast
description: >
  Static Application Security Testing (SAST). Scans the code for security vulnerabilities. A
  BLOCKING GATE — you cannot advance to VERIFY with open vulnerabilities.
  Trigger: /ddw-security-sast, during DDW's CODE phase.
---

# Skill: /ddw-security-sast

## Description
Static Application Security Testing (SAST). Scans the code for security vulnerabilities.
**BLOCKING GATE** — you cannot advance to the VERIFY phase with open vulnerabilities.

## Inputs
- The files modified during implementation.
- `.ddw/rules/security.instructions.md` for the practices.
- `.ddw/rules/validation-rules.instructions.md` §4 for the rules (F-SAST-01 to F-SAST-19,
  W-SAST-01) — the single source of truth for severity and disposition.
- The project's stack: the "Stack" section of `AGENTS.md`.

## Execution Protocol

1. **Scan for hardcoded secrets** (F-SAST-01, always Critical):
   - Look for API key, password, token and connection string patterns.
   - Check that `.env` is in `.gitignore`.
   - Look for sensitive files that should not be in the repo.

2. **Scan for injection patterns:**
   - SQL/NoSQL: string concatenation in queries; user objects passed straight into queries
     (F-SAST-02, Critical).
   - Command injection: user input reaching exec/spawn/system (F-SAST-03, Critical).
   - Path traversal: user input in file paths (F-SAST-05, High).

3. **Scan for XSS** (F-SAST-06, High):
   - `innerHTML`, `dangerouslySetInnerHTML` with user input.
   - Missing sanitization on HTML output.

4. **Scan for unsafe functions and broken crypto:**
   - `eval()`, `exec()`, insecure deserialization (F-SAST-04 Critical / F-SAST-17 Medium, depending
     on whether the input is controlled).
   - Weak crypto: MD5/SHA1 for passwords, DES, ECB mode (F-SAST-08, High).

5. **Scan the rest of the mandatory categories:** SSRF (F-SAST-07), debug mode in production
   (F-SAST-09), logging of sensitive data (F-SAST-10), unrestricted upload (F-SAST-11), missing CSRF
   protection (F-SAST-12). Then the two Medium code categories, which the scan protocol used to
   skip past entirely: incomplete input validation (F-SAST-14) and error handling that leaks
   internals (F-SAST-15).

6. **Audit dependencies** (F-SAST-13/16):
   - Run the package manager's audit if available (npm audit, pip audit, cargo audit, etc.).
   - Check for known CVEs.

7. **Classify the findings** and apply the catalog's disposition:
   - 🔴 **Critical** and 🟠 **High** → FAIL, always blocking, **not suppressible**.
   - 🟡 **Medium** → FAIL by default, suppressible only with the full documentation in §4.4.
   - 🟢 **Low / Informational** → WARNING, reported, does not block.

## Suppressions

**Every finding, including false positives, has to be documented** — an undocumented finding is an
unreviewed finding. To suppress a Medium, use the 7-field format in
`.ddw/rules/validation-rules.instructions.md` §4.4 (file, category, disposition, reviewer, date,
justification, compensating control/review-by). Missing any field is a FAIL (F-SAST-18), and a
suppression older than 6 months has to be re-evaluated (F-SAST-19).

Critical and High can never be suppressed. They get fixed.

## Output Format

```
┌─────────────────────────────────────────────────────────────┐
│  /ddw-security-sast — [PASSED | BLOCKED]                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Secrets:                                                    │
│    ✅/❌ [ID]: [what was checked]                            │
│                                                              │
│  Injection:                                                  │
│    ✅/❌ [ID]: [what was checked, with file:line]            │
│                                                              │
│  XSS and unsafe functions:                                   │
│    ✅/❌ [ID]: [what was checked]                            │
│                                                              │
│  Dependencies:                                               │
│    ✅/❌/⚠️ [ID]: [what was checked]                          │
│                                                              │
│  Suppressions: [N]  (each with its 7 fields)                 │
│                                                              │
│  ────────────────────────────────────────────────────────────│
│  Total: X clean, Y vulnerabilities (C critical, H high)       │
│  Report: docs/ddw/security/sast-[ticket].md                  │
│  Next: [recommended action] (attempt N/3)                    │
└─────────────────────────────────────────────────────────────┘
```

**This skill has no script and writes no receipt, on purpose.** Its finding is a model reading code,
and a receipt would dress that up as proof (`docs/RATIONALE.md` decision 16). What it still owes the
user is the same table everything else in the catalog produces: **every rule ID it evaluated, with
its ✅ / ⚠️ / ❌ — never a count with the rows dropped** — written to
`docs/ddw/security/sast-{ticket}.md` and shown in full, with the **Report** row above pointing at it
so the user can read it again without asking. The four steps in the catalog's *How a validation runs*
apply here too: evaluate, fix what is fixable, ask about what needs a decision, then show the whole
table and ask for approval.

## PASS/FAIL criteria
- **PASSED:** 0 Critical or High vulnerabilities, and every Medium either fixed or properly
  suppressed → `gates.sast` = `true`.
- **BLOCKED:** 1+ Critical or High → fix before advancing. Max 3 attempts, then escalate to the
  user.

For triage of whether a finding is a true or false positive, spawn `ddw-sec-auditor` via the Agent
tool.

## Tier modifier: QUICK-FIX
SAST **applies in full**. It is that tier's only security validation and it is not relaxed.

## Updating .ddw-state.json
- `gates.sast` → `true` on PASS. The report is saved to `docs/ddw/security/sast-{ticket}.md` (derived
  from the ticket).

## Language

Write the report in the language the user is working in, citing the rule IDs verbatim.
