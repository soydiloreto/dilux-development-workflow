---
applyTo: '**'
version: 1.7.0
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
| `tier` | `string \| null` | `"QUICK-FIX"`, `"FIX"`, `"FEATURE"`, `"DISCOVERY"`, `null` | Tier of the current work. `null` in IDLE. |
| `phase` | `string` | `"IDLE"`, `"CLASSIFY"`, `"DEFINE"`, `"PLAN"`, `"CODE"`, `"VERIFY"`, `"RELEASE"`, `"DISCOVERY"` | Current phase of the state machine. |
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
| **Closeout** | The work ships | The edge's gates — no `commit` and `pr`, no close | any `action` |
| **Abandon** | The work will never ship | none | `action: "abandon: <reason>"` |
| **Pause** | Set aside, to be resumed | none | `action: "pause: <reason>"` |

Walking away — abandon or pause — is allowed from any phase **except the ones listed in the graph's
`no_walkaway`**, which today means RELEASE. At RELEASE nothing is left to decide, only steps to
finish, so an exit there is a closeout and owes its gates. Without that rule the word `"abandon"`
would be a skeleton key: relabel the exit and ship without a commit or a PR.

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
