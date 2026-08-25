---
applyTo: '**'
version: 2.5.0
---

# State — Schema and Management of `.ddw-state.json`

> **This file is loaded ALWAYS, regardless of the phase.**

---

## `.ddw-state.json` Schema

```json
{
  "tier": "string | null",
  "phase": "string",
  "ticket": "string | null",
  "title": "string | null",
  "tracker": "string | null",
  "autonomy": "string | null",
  "gates": {},
  "block": "string | null",
  "discovery": "object | null",
  "history": []
}
```

### Fields

| Field | Type | Valid values | Description |
|-------|------|--------------|-------------|
| `tier` | `string \| null` | `"QUICK-FIX"`, `"FIX"`, `"FEATURE"`, `"DISCOVERY"`, `"FREE"`, `null` | Tier of the current work. `null` in IDLE. |
| `phase` | `string` | `"IDLE"`, `"CLASSIFY"`, `"DEFINE"`, `"PLAN"`, `"CODE"`, `"VERIFY"`, `"CLOSEOUT"`, `"DISCOVERY"`, `"FREE"` | Current phase of the state machine. |
| `ticket` | `string \| null` | Tracker ID (e.g. `"PROJ-123"`) or internal (e.g. `"FIX-001"`, `"FEAT-001"`, `"DISC-001"`) | The ticket identifier. `null` in IDLE. |
| `title` | `string \| null` | Free text | Descriptive title of the ticket. `null` in IDLE. |
| `tracker` | `string \| null` | The tracker's ID | Set when the ticket comes from a tracker. `null` when the ID is internal. |
| `autonomy` | `string \| null` | `"assisted"`, `"minimal"`, `null` | How much of the pipeline runs without being asked. Set in CLASSIFY, alongside the tier. **Absent or `null` means `assisted`** — a state written before this field existed is not a state that opted into anything. |
| `gates` | `object` | `{"spec": true, …}` | The gates earned in the current phase. A transition reads them; it never trusts a promise. |
| `block` | `string \| null` | Free text | Which block of the spec is being implemented (CODE phase). |
| `discovery` | `object \| null` | Free object | DISCOVERY's working notes. |
| `history` | `array` | Append-only | One entry per transition: `{timestamp, from, to, action, ticket, tier}`. Entries are **only ever appended at the end** — editing or reordering one invalidates the whole chain. |

### The history entry

```json
{ "timestamp": "2026-07-28T14:02:11Z", "from": "CODE", "to": "VERIFY",
  "action": "implementation complete", "ticket": "FEAT-001a", "tier": "FEATURE" }
```

`ticket` and `tier` are stamped on **every** entry. Without them the history says a transition
happened but not what it happened *to*, and a log of anonymous moves cannot answer the one question
worth asking six months later: what became of this piece of work.

They also carry weight now. A closeout resets `ticket` to `null`, so **the entry is the only place
the finished ticket's name survives** — which is what lets the session boot work out that a split
PRD has sub-tickets nobody has run yet, without inventing a second place to store it.

**A stamped `ticket` must be the ticket in hand** — the state's value before the write, or after it.
The FSM refuses anything else: an entry free to name any ticket could credit a closeout to work that
never happened. Entries with no `ticket` remain legal so histories written before this stay valid;
what cannot be attributed is treated as unfinished.

---

## Three ways a ticket reaches IDLE

They look identical in the `phase` field and owe completely different things:

| | What it means | Gates owed | Declared as |
|---|---|---|---|
| **Closeout** | The work is finished and handed over | The edge's gates — no `commit` and `pr`, no close | any `action` |
| **Abandon** | The work will never ship | none | `action: "abandon: <reason>"` |
| **Pause** | Set aside, to be resumed | none | `action: "pause: <reason>"` |

Walking away — abandon or pause — is allowed from any phase **except the ones listed in the graph's
`no_walkaway`**, which today means CLOSEOUT. At CLOSEOUT nothing is left to decide, only steps to
finish, so an exit there is a closeout and owes its gates. Without that rule the word `"abandon"`
would be a skeleton key: relabel the exit and ship without a commit or a PR.

**One exception, and it is narrow.** A **pause** at CLOSEOUT is allowed once `commit` and `pr` are
both true. The work is committed, the pull request is open, and what you are waiting for is another
person — refusing there protects nothing and leaves the ticket sitting in CLOSEOUT for two days while
you cannot start anything else, because there is one state per directory. An **abandon** at CLOSEOUT
is still refused, which is what the skeleton key was about, and both gates are read from the state
*before* the write, so the same write cannot grant them and spend them.

**Resuming at CLOSEOUT gives `commit` and `pr` back false.** Days passed: the pull request may have
been closed, the branch may have been force-pushed. A gate already true is never re-asked, so
without this the closeout would be satisfied by evidence earned before the wait. Both questions are
instant — one to git, one to the forge.

```json
{ "timestamp": "…", "from": "DISCOVERY", "to": "IDLE",
  "action": "abandon: the idea does not survive its own cost analysis" }
```

The marker is matched **anchored** — the first word, on its own or before a colon. `"abandonware
cleanup"` is a title, not a decision.

An exit to IDLE that declares none of the three, on an edge the graph does not carry, is refused.
Bailing out is always allowed; doing it silently is not — the history is the audit trail of what
happened to each ticket, and "this was dropped, and why" is exactly the kind of thing worth being
able to read six months later.

### Going back

**Where the graph declares a backward edge, taking it gives up what that phase granted** — and the
graph is the authority for both halves. It is not "always": DEFINE has no way back in any tier, and
FREE and DISCOVERY have none either. Under FEATURE: `PLAN→DEFINE` gives up `define`, `CODE→PLAN`
gives up `spec` and `threat`, `VERIFY→CODE` gives up `tests` and `sast`, and `CLOSEOUT→VERIFY` gives
up **`verify`, `commit` and `pr`** — three, because the commit and the pull request describe a world
that moves while you are away. Under QUICK-FIX the two edges are `CODE→DEFINE` (gives up `define`)
and `CLOSEOUT→CODE` (gives up `tests`, `sast`, `commit` and `pr`).

Keeping a gate the edge clears is refused, so a write built from a shorter list than the graph's is
rejected — this paragraph named one gate for `CLOSEOUT→VERIFY` where the graph names three, and the
model that believed it had its write bounced with no idea why. Read `clears` from
`transition-graph.json` rather than from here if the two ever disagree again.

**Under `assisted`, the question comes BEFORE the edge.** A backward edge exists because something
already approved turned out to be wrong — and what there is to ask is never permission to correct
a known defect (that is a rubber stamp; the corrective loop is mandatory everywhere the catalog
describes one, `validation-rules.instructions.md` §2) but the decision that MOTIVATES the
correction: which of two contradicting stacks stands, whether the too-big scope splits, the answer
nobody wrote down. Measured on a live run: the helper took `PLAN→DEFINE` first and asked which
stack should prevail after, so a user answering "neither — drop the ticket" would have answered
into a phase already re-entered and a gate already spent. Where such a decision exists, announce
the reason, put the question to the user, and take the edge WITH their answer in hand. Where
nothing is theirs to decide before the fix — CODE finding a block that names the wrong file has no
question in it, only a correction (`code.instructions.md` § When the spec is the thing that is
wrong) — announce with the flag up and go; inventing a question there is the rubber stamp again.
Under `minimal` the pause goes away like every other arrow's, and the move is announced with its
reason.

**The lane is enforced, not promised — through a file.** Before taking a backward edge under
`assisted`, write its reason to `.ddw-work/goback-proposal.txt`, naming the edge and opening with
the lane: `correction: <the defect a validator or review named>`, or `ask: <the question>`. A
`correction:` announces and goes, with the file as its durable record. An `ask:` is held by the
hook until the sealed copy of that exact question matches — which can only be true if it was on
screen before the user answered — so executing the loop first and asking after now bounces instead
of landing (this paragraph alone did not stop it; the fix that introduced it touched only prose,
and a later run took the edge first anyway). Where no turn hook is wired, the gate stands down and
says so here rather than reading as coverage. In both modes what waits at the far end is unchanged:
the corrected artifact re-earning the gate the edge just cleared, from a banner that says where it
came back from — an approval
that does not know it is a re-approval is the same rubber stamp one document later.

Stepping out of CODE backwards also clears `block` — you are not implementing one any more.

To go from CLOSEOUT back to DEFINE you take four steps, and each one is a history entry saying why.
That is the record of how far back a review sent you.

**The validator refuses a backward write that still holds those gates**, and that is not tidiness.
Clearing them in the helper alone left a hand-written state able to step back, keep the gates,
rewrite the artifact and step forward again — with no receipt asked for, because evidence is owed
only when a gate is claimed for the *first* time. That is a rewritten PRD laundered through the
pipeline's own recovery path, and it was reachable until this rule existed.

Going back is never a shortcut: it is strictly more expensive than going forward, because everything
from there on has to be earned again against the artifacts as they now are.

**Reaching IDLE resets the ticket:** `tier` back to `null`, `gates` back to `{}`. This is enforced,
not merely expected. Leaving them behind let the NEXT ticket inherit gates the previous one paid
for, and walk the whole pipeline having earned none of them. `history` is the exception — it is the
audit trail, and it only ever grows.

### `autonomy`, and what it does not change

`assisted` is the default and is what DDW has always done: every arrow waits for the user.

`minimal` stops asking for the arrows and keeps everything else. It does **not** relax a single
gate: the same eight receipts and answers are required, refused by the same hook, over the same
bytes. What it removes is the confirmation on a transition whose evidence is already on disk —
because asking a person to approve what a receipt already attests is asking them to rubber-stamp,
and a rubber stamp teaches people that approvals mean nothing.

**Three things stop the pipeline in `minimal` anyway, and they are not configurable:**

1. **A decision nobody wrote down.** A ❌ the script names is a defect to fix; a question that comes
   from missing information is not. Inventing a requirement to clear a check is a worse defect than
   the one it silenced, and that rule does not have a mode.
2. **The corrective loop hitting its ceiling.** `PRD loops`, `Spec loops` and the CODE phase's three
   attempts are the counters; reaching one means the automatic path has been tried and did not
   converge, and the run stops with what it tried in the record.
3. **A corrupt state.** Already true in both modes, for the reasons decision 14 gives.

Every transition taken without a human carries `"autonomy": "minimal"` in its history entry. Six
months later the record has to distinguish a run somebody watched from one that went through at
three in the morning, and a `history` that reads identically for both is a record that lies by
omission.
