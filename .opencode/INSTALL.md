# DDW for OpenCode — installer

> **Agent: you are the installer.** The user asked you to fetch and follow this
> file. Do the steps below exactly, in order, and do nothing else. Show the user
> each edit before you make it.

## Step 1 — register the plugin

Open the user's `opencode.json`. Prefer the global one
(`~/.config/opencode/opencode.json` or `.jsonc`); if the user says this install
is for one project only, use the project's `opencode.json`. Create the file with
`{}` if it does not exist.

**Merge** — never overwrite other keys — this entry into the `plugin` array:

```json
{
  "plugin": ["ddw@git+https://github.com/soydiloreto/dilux-development-workflow.git"]
}
```

There is no step for making the model aware of DDW: the plugin does that
itself. On load it registers the packaged skills with OpenCode's discovery and
prefixes a bootstrap — method path, current phase, classify-first — to the
session's first user message.

## Step 2 — hand back to the user

Tell the user, in these words or your language's equivalent:

> DDW is registered. Restart OpenCode — the plugin installs itself on the next
> start (the first launch takes longer: it is cloning the repo). Then ask me
> "where is the pipeline?" to verify.

Do not restart anything yourself, and do not try to verify before the restart:
the plugin is not loaded in the session that installed it.

---

# Reference (for humans)

> **Agent, if you are reading this from inside an installed plugin package:**
> this file is not addressed to you. Never run `install.sh` into a user's repo
> on your own — the drop-in below is a choice the USER makes. Under a plugin
> install the method stays with the plugin, and installing it into the repo
> breaks that promise.

The plugin delivers the **gates** (pre-write refusal, forged-state detection —
both driven live on OpenCode 1.18.9), the packaged method, the **skills**
(registered with OpenCode's discovery on load) and a **bootstrap** prefixed to
the first user message so the model knows the method's path and phase before it
acts. The acceptance record is `scripts/acceptance.md`.

## Drop-in (everything in the repo — verified 4/4)

```bash
bash install.sh . --target opencode
```

Method, plugin, 17 skills, 5 agents, 17 commands — all in the repo.

## Manual global install (no package manager)

Facts that cost a night: the plugins dir loads **copies, not symlinks**; the
`plugin` config array takes npm-style packages only (no `file:` paths).

```bash
cp adapters/opencode/plugin/ddw.js ~/.config/opencode/plugins/ddw.js
cp -r ddw ~/.config/opencode/ddw
cp -r skills ~/.config/opencode/skills
```

Add `permission.external_directory` allowing `~/.config/opencode/ddw/*` to the
global config so the model can read the method without a prompt. `ddw.js`
resolves the method repo-first, then next to itself (package or global layout),
and finds the skills beside it. The state file stays in the project either way.
