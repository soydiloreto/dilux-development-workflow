---
name: ddw-family-impact
description: >
  The impact analysis a family repo owes before leaving CLASSIFY: gathers the whole family fresh
  (cloning missing members via gh, reading every seam at origin), you write the verdict — every
  member impacted or excluded with a reason — and validation earns the receipt the
  CLASSIFY→DEFINE gate demands. Trigger: /ddw-family-impact, and once per ticket in any repo
  that declares `## Repo family`.
---

# Skill: /ddw-family-impact

## Description

Standing in ANY repo of a family, classification's first duty is the impact question: which
members does this work hit, and which does it provably not. This skill is that step. Its
deterministic half is `family_impact.py`; the judgment half is yours.

A repo with no `## Repo family` section never needs this: single-repo flow, untouched.

## Protocol

1. **Gather the facts** (script, not memory):

   ```bash
   python3 .ddw/scripts/family_impact.py --ticket <TICKET>
   ```

   It resolves the family from this repo's `## Repo family`, finds the workspace and every
   member as sibling clones — **cloning the missing ones via `gh`** — fetches them all, and
   reads the map (`familia.md`) and every member's seams from `origin/<default>`: freshness by
   construction, each repo recorded at the SHA it was read. The facts land in
   `.ddw-work/impact-data-<TICKET>.json`. The standing repo itself is fetched, and
   fast-forwarded only when clean and on the default branch — a diverged tree is reported,
   never merged over.

2. **Write the verdict** to `.ddw-work/impact-<TICKET>.md`. For EVERY member the gather
   printed: impacted (with what part of the work hits it), or `Sin impacto: <reason>` — and the
   reason names the contract that stays intact, not a shrug. Walk `Consumed by` of everything
   the work touches: a consumer of a changing seam that is missing from the impacted list is
   the analysis failing at its one job.

3. **Validate it**:

   ```bash
   python3 .ddw/scripts/family_impact.py --validate .ddw-work/impact-<TICKET>.md
   ```

   Every member accounted for, no invented repos, reasons that exist. On PASS it writes the
   content-hashed receipt (`.ddw-sessions/impact-validated-…`) that the CLASSIFY→DEFINE gate
   demands. Editing the verdict afterwards kills the receipt — revalidate.

4. **Classify with the verdict in hand**: one impacted repo (this one) → an ordinary local
   ticket, normal pipeline. Multiple impacted repos → a multirepo initiative: the index in the
   workspace, per `define.instructions.md` § Multirepo split.

## The honest bargain

The receipt does not prove the judgment is right. It proves the judgment was made over the
WHOLE family, freshly read — and that skipping the step is a deliberate act that leaves no
file where the record demands one.
