---
applyTo: '**'
version: 1.1.0
---

# Security Conventions

---

## Principles

- **Never trust user input.** All user input is potentially malicious.
- **Defense in depth.** Multiple layers of protection, not a single barrier.
- **Least privilege.** Every component gets only the permissions it needs.
- **Fail securely.** On error, deny by default — never allow.
- **Secure by default.** The default configuration is the safest one.

## Input Validation

- ALL user input must be validated and sanitized.
- Use allowlists (what is permitted) over denylists (what is forbidden).
- Validate type, length, range and format.
- Validate on both client and server (server-side validation is mandatory).

## Authentication and Authorization

- Tokens in headers (Authorization), never in URLs or query params.
- Sessions with a configured expiry.
- RBAC or ABAC, depending on the project.
- Check permissions on EVERY endpoint/operation, not only in the auth middleware.

## Secrets Management

- **NEVER** hardcode secrets, tokens, passwords or API keys in code.
- Use environment variables or secret managers.
- `.env` files NEVER in git (must be in `.gitignore`).
- Document secret rotation where applicable.

## SQL / NoSQL Injection

- **ALWAYS** use parameterized queries / prepared statements.
- **NEVER** concatenate user input into queries.
- Use the ORM's query builder for dynamic queries.
- If raw SQL is needed, document why the ORM is not enough.

## XSS Prevention

- Escape output in HTML.
- Content Security Policy (CSP) headers.
- HttpOnly and Secure flags on cookies.
- Do not use `innerHTML`, `dangerouslySetInnerHTML` or equivalents with user input.

## Dependency Security

- Check for known vulnerabilities before adding new dependencies.
- Prefer actively maintained dependencies with a good security track record.
- Lockfile always committed (package-lock.json, yarn.lock, Cargo.lock, etc.).
- Audit dependencies regularly.

## SAST Gate (CODE phase)

The `ddw-security-sast` skill is a **BLOCKING GATE** in the code phase.

**Validation rules, severity classification and the suppression protocol are defined in section 4 of
`.ddw/rules/validation-rules.instructions.md`** (F-SAST-01 to F-SAST-19, W-SAST-01).

What it scans (mandatory categories — OWASP Top 10, CWE Top 25):
- Hardcoded secrets in code and configuration (F-SAST-01 — always Critical).
- SQL/NoSQL injection patterns (F-SAST-02 — always Critical).
- OS command injection (F-SAST-03 — always Critical).
- Insecure deserialization (F-SAST-04 — always Critical).
- Path traversal (F-SAST-05 — always High).
- XSS vectors (F-SAST-06 — always High).
- SSRF (F-SAST-07 — always High).
- Broken cryptography (F-SAST-08 — always High).
- Debug mode in production (F-SAST-09 — always High).
- Logging of sensitive data (F-SAST-10 — always High).
- Unrestricted upload (F-SAST-11 — always High).
- Missing CSRF protection (F-SAST-12 — always High).
- CVEs in dependencies (F-SAST-13 — Critical/High depending on the CVE).
- Use of unsafe functions (F-SAST-17 — Medium, suppressible with documentation).

**Disposition by severity:**
- Critical/High → **FAIL, always blocks, not suppressible.**
- Medium → **FAIL by default, suppressible with formal documentation** (see the suppression protocol
  in `.ddw/rules/validation-rules.instructions.md` §4.4).
- Low/Informational → **WARNING, reported, does not block.**

If it finds Critical/High vulnerabilities → **BLOCKED**. You cannot advance to the VERIFY phase.

False positives and suppressions must be documented using the format in section 4.4 of
`.ddw/rules/validation-rules.instructions.md` (7 mandatory fields: file, category, disposition,
reviewer, date, justification, compensating control/review).

## Notes for the Agent

- Apply these practices automatically while writing code. Do not wait for the scan.
- If you spot an unsafe pattern in existing code, report it as part of `ddw-validate-arch`.
- Security reports are stored in `docs/ddw/security/` as evidence (threat models, SAST).
- Never disable security checks without the user's explicit approval.
