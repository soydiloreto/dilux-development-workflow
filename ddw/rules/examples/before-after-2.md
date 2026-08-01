# Example: a FEATURE with scope control

## Scenario
The user asks to "add JWT authentication to the system".

## Without DDW (before)
The agent starts writing JWT code straight away, mixing auth + user management + roles into one
giant PR with no documented requirements.

## With DDW (after)
1. **CLASSIFY**: classifies it as FEATURE, assigns FEAT-005
2. **DEFINE**: writes a PRD with 12 acceptance criteria
   - **Scope check**: detects that 12 ACs across 4 modules is too much
   - Proposes splitting into 3 tickets:
     - FEAT-005a: basic login/logout
     - FEAT-005b: refresh tokens
     - FEAT-005c: RBAC
   - The user accepts, work continues with FEAT-005a (4 ACs)
3. **PLAN**: threat modeling + a spec with 2 blocks
4. **CODE**: block 1 → test → block 2 → test → SAST
5. **VERIFY**: verify-module
6. **RELEASE**: commit, PR, tracker updated

## Rules applied
- `.ddw/rules/define.instructions.md` — the scope control gate
- The project's architecture conventions (`AGENTS.md`) — layer separation
- `.ddw/rules/security.instructions.md` — threat modeling + SAST
- `.ddw/rules/tracker.instructions.md` — the ticket in commits, and the tracker update
