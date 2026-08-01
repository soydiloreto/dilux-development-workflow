# DDW for Copilot CLI — installer

> **Agent: you are the installer.** The user asked you to fetch and follow this
> file. Do the steps below exactly, in order, and do nothing else. Show the user
> each edit before you make it.

## Step 1 — marketplace and plugin

Run, in the user's shell:

```bash
copilot plugin marketplace add soydiloreto/dilux-development-workflow
copilot plugin install ddw@dilux
```

Copilot reads the Claude-format manifest and installs the 17 skills. It does
**not** read the hooks manifest — that is step 2, and without it the install
looks alive and enforces nothing.

## Step 2 — user-level hooks (the gates)

Find the plugin's install path in `~/.copilot/config.json` under
`installedPlugins[].cache_path` — call it `ROOT` below. Then **merge** — touch
NOTHING but the `hooks` key — into **`~/.copilot/settings.json`** (NOT
config.json: hooks written there are only migrated to settings.json on a later
start, and every session until then runs with no gates at all — measured live):

```json
{
  "hooks": {
    "sessionStart": [{ "type": "command", "bash": "DDW_PLUGIN_ROOT=ROOT bash ROOT/adapters/copilot/scripts/session-start.sh", "timeoutSec": 10 }],
    "preToolUse":   [{ "type": "command", "bash": "DDW_PLUGIN_ROOT=ROOT bash ROOT/adapters/copilot/scripts/pre-tool-use.sh",  "timeoutSec": 15 }],
    "postToolUse":  [{ "type": "command", "bash": "DDW_PLUGIN_ROOT=ROOT bash ROOT/adapters/copilot/scripts/post-write.sh",    "timeoutSec": 15 }]
  }
}
```

Replace every `ROOT` with the real absolute path. The scripts resolve the
method repo-first: a repo with its own drop-in keeps winning, and the
user-level copy stands down where the repo wires its own hooks.

## Step 3 — hand back to the user

Tell the user: DDW is installed for Copilot. **Close every open `copilot`
session** — hooks are read at startup, so a session opened before this install
runs without gates — then start a fresh one and ask "where is the pipeline?"
to verify. Nothing of DDW lands in any repo until
a ticket starts — then only `.ddw-state.json`, its `.gitignore` entry and the
phase artifacts.

---

# Reference (for humans)

What was driven live on Copilot CLI 1.0.75, and what it means:

- The marketplace/install commands work against this repository directly — no
  separate marketplace repo needed, private works through your GitHub login.
- Plugin skills load (17) and get used; the Claude-format hooks manifest is
  ignored, which is why the gates ride user-level hooks instead.
- With the hooks wired, a forged `.ddw-state.json` was detected live: the model
  invoked `ddw-status`, stopped without writing, and reported — Copilot's post
  hook cannot refuse (GitHub documents that), so this is the model heeding the
  report, which is the strongest thing this tool offers.

The drop-in (`bash install.sh . --target copilot`) remains the everything-in-
the-repo alternative, verified 4/4.

## Uninstall

Both halves, in this order — leaving the hooks behind after removing the plugin
leaves them pointing at scripts that no longer exist, and Copilot fails closed:
**every tool call in every repo gets denied** (measured live).

```bash
copilot plugin uninstall ddw
copilot plugin marketplace remove dilux
```

Then remove the `hooks` key from `~/.copilot/settings.json`.
