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

The plugin you just installed ships the script that does this. Find its install
path in `~/.copilot/config.json` under `installedPlugins[].cache_path` — call it
`ROOT` — and run:

```bash
python3 ROOT/adapters/copilot/wire-user-hooks.py ROOT
```

It writes `~/.copilot/hooks/ddw.json` and prints what it wired. Show the user
the file afterwards.

Do not hand-write that JSON instead. The script exists because the wiring has
two ways to look right and be wrong: the wrong LEVEL, and the wrong wrapper.

**Level, and the reason it is not obvious.** Copilot reads hooks from a repo's
`.github/hooks/`, from the user's own `~/.copilot/hooks/`, and from a few other
places; the reference says every source is combined and all of them run. What it
says only in passing is that policy hooks are available *"regardless of folder
trust state"* — the others are not. **Repository hooks load only in a folder the
user has trusted**, and a folder becomes trusted by answering a dialog that
`copilot -p` has no way to show.

Measured 2026-08-22/23, same repo, same prompt, the only variable changed being
`trustedFolders`:

| repo hooks, folder | hooks ran | wrote the file? |
|---|---|---|
| trusted | 3 | no, refused |
| not trusted | **0** | **yes** |

User-level hooks refuse it either way. The trap is that trust is invisible: the
repo a developer has been opening interactively for weeks IS trusted, so its
gates hold — and the same repo cloned fresh on CI, or driven by a script, is not,
and enforces nothing while looking identical. So DDW wires the gates at user
level for the drop-in as well as the plugin, and writes no repo-level manifest at
all: where the folder is trusted, keeping both would run both and judge every
write twice.

Do not "fix" this by adding the repo to `trustedFolders` for the user. Trust is
their answer about a folder; an installer that answers it for them has forged a
permission.

**Wrapper.** `[ -f hook ] && bash hook || echo '{}'` turns every refusal into
permission: the gate exits 2, `||` catches it, `echo` exits 0, and Copilot reads
0 as allow. It must be `if [ -f hook ]; then exec bash hook; fi; echo '{}'`.

The scripts resolve the method repo-first, plugin-root second: a repo with its
own drop-in is judged by its own `.ddw/`, and a repo with no DDW at all is
answered with `{}` and left alone.

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
the-repo alternative, driven live for three of the ritual's checks, with the fourth detected and not prevented — Copilot's post hook cannot refuse. `scripts/acceptance.md` holds the row.

## Uninstall

Both halves, in this order — leaving the hooks behind after removing the plugin
leaves them pointing at scripts that no longer exist, and Copilot fails closed:
**every tool call in every repo gets denied** (measured live).

```bash
copilot plugin uninstall ddw
copilot plugin marketplace remove dilux
```

Then delete `~/.copilot/hooks/ddw.json` — but only if no repo on this machine
still has DDW installed for Copilot. That one file is what gates all of them.
