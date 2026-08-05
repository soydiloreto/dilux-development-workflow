---
name: ddw-security-sast
description: >
  Static Application Security Testing (SAST). Scans the code for security vulnerabilities. A
  BLOCKING GATE — the `sast` receipt is what lets a ticket leave CODE, in every tier.
  Trigger: /ddw-security-sast, during DDW's CODE phase.
---

# Skill: /ddw-security-sast

## Description
Static Application Security Testing (SAST). Scans the code for security vulnerabilities.
**BLOCKING GATE** — the `sast` receipt is what lets a ticket leave CODE: to VERIFY in
FEATURE and FIX, straight to CLOSEOUT in QUICK-FIX. No tier leaves it with open
vulnerabilities.

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

**Write the report to `docs/ddw/security/sast-{ticket}.md`, then validate it:**

`python3 .ddw/scripts/validate_sast.py docs/ddw/security/sast-{ticket}.md --tier <tier>`

(under a plugin install, resolve `.ddw/scripts/` at the plugin's method path). **Paste its output
VERBATIM** — every row, every rule ID, on **every** run, including a re-validation of a report that
has not changed. A PASSED run writes the content-hashed receipt the `sast` gate demands; without it
the transition out of CODE refuses — CODE→VERIFY, or CODE→CLOSEOUT in QUICK-FIX.

**What that receipt does and does not say.** DDW does not scan your code — the scan above is a model
reading it, and no file can make that a proof. What the validator answers is whether the **report**
is complete: every catalogued category carrying a verdict, every finding naming a file and a line,
the stated result consistent with the severities listed, every Medium fixed or suppressed, every
suppression carrying its fields and still inside its review window. The judgement stays yours to
read; what stops being optional is the shape of the record. The script says exactly this on every
run, because a receipt whose scope is unstated gets read as covering everything.

The four steps in the catalog's *How a validation runs* apply here: run the script, loop on every ❌
(fixing only what the rule names), ask about what genuinely needs a human decision, then show the
whole table plus the link to the report on disk and ask for approval.

**The report has to be parseable, which means the rule IDs travel with their verdicts.** One line per
catalogued category, its ID and its ✅ / ⚠️ / ❌ on that same line, and a `file:line` on anything
found. A prose paragraph that says the same thing is a report nothing can check — which is how
nineteen catalogued rules went years without one of them being executed.

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
