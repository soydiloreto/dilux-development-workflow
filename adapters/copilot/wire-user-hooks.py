#!/usr/bin/env python3
"""DDW — Copilot CLI · write the user-level hooks manifest.

Copilot's gates are wired here and nowhere else, in BOTH install modes, because
of one thing GitHub's hooks reference states only in passing: policy hooks "are
available regardless of folder trust state". The others are not. Repository
hooks — `.github/hooks/*.json` — load only in a folder the user has trusted, and
a folder becomes trusted by answering a dialog that non-interactive mode has no
way to show.

Measured 2026-08-22/23, `copilot -p … --allow-all`, same repo, same prompt, the
ONLY variable changed being `trustedFolders` in ~/.copilot/config.json:

    repo hooks, folder trusted      ->  3 hooks ran, the write was refused
    repo hooks, folder NOT trusted  ->  0 hooks ran, the file was written
    user-level hooks, NOT trusted   ->  hooks ran, the write was refused

So this is not "headless ignores hooks", and it is not about which file the
wiring lives in — both user-level spellings work. It is trust, and the shape of
the trap is that trust is invisible: the repo a developer has been using
interactively for weeks IS trusted, so its gates hold, and the same repo cloned
fresh on CI or driven by a script is not, and enforces nothing while looking
identical. DDW had exactly one wiring, at the level that disappears.

User level survives it, so that is where the gates go — for the drop-in as well
as the plugin. And no repo-level manifest is written at all: where the folder IS
trusted, the reference says every source's hooks are combined and all of them
run, so keeping both levels would judge every write twice.

Adding the repo to `trustedFolders` on the user's behalf was the other way out.
It is not DDW's decision to make — trust is the user's answer about a folder,
and an installer that answers it for them has forged a permission.

This lives in the adapter and not inside install.sh so that it can be RUN — by
the installer, and by the checks, against a sandboxed HOME. A wiring nothing can
execute is a wiring nothing can verify.

    argv[1] (optional)  non-empty  = plugin mode: resolve the installed plugin
                                     root and point the hooks at its scripts.
                        empty/absent = drop-in: point at each repo's own
                                     .github/hooks/ddw/ by RELATIVE path, so one
                                     user-level wiring serves every repo on the
                                     machine and resolves to nothing in a repo
                                     that has no DDW.
"""
import glob, json, os, re, sys
home = os.path.expanduser("~")
arg = sys.argv[1] if len(sys.argv) > 1 else ""
root = None
if arg:
    cfg = os.path.join(home, ".copilot", "config.json")
    try:
        with open(cfg, encoding="utf-8") as fh:
            # JSONC: the file opens with two `//` lines saying it is managed
            # automatically. Parsed as strict JSON it raises, the lookup fell to
            # the "not registered yet" branch, and the install stopped one step
            # short of the gates while reporting the skills as in — the exact
            # half-install that branch exists to warn about.
            raw = re.sub(r"^\s*//.*$", "", fh.read(), flags=re.M)
        for p in (json.loads(raw) or {}).get("installedPlugins") or []:
            if isinstance(p, dict) and str(p.get("name", "")) == "ddw":
                root = p.get("cache_path")
    except (OSError, ValueError, AttributeError):
        pass
    if not root:
        # What is on disk, when the manifest cannot say. The scripts are the
        # thing being pointed at, so their presence is the test.
        for cand in glob.glob(os.path.join(home, ".copilot", "installed-plugins", "*", "*")):
            if os.path.isdir(os.path.join(cand, "adapters", "copilot", "scripts")):
                root = cand
                break
    if not root:
        print("  ⚠ copilot: the plugin's install path is not in ~/.copilot/config.json yet.")
        print("    The skills are in; the GATES are not. Re-run this once the plugin is")
        print("    registered, or the install enforces nothing.")
        sys.exit(0)

def entry(script, timeout):
    if root:
        target = os.path.join(root, "adapters", "copilot", "scripts", script)
        # A user-level hook fires in EVERY repo, so it has to be able to say
        # "not here" — the scripts do, by resolving the method and echoing `{}`
        # when they cannot find one.
        bash = "DDW_PLUGIN_ROOT=%s bash %s" % (root, target)
    else:
        target = ".github/hooks/ddw/" + script
        # `if …; then exec …; fi` and NOT `[ -f x ] && bash x || echo '{}'`. The
        # `&&`/`||` spelling turns a REFUSAL into permission: the gate exits 2,
        # `||` catches it, `echo` exits 0, and Copilot reads 0 as allow. A
        # wrapper that converts every deny into an allow is worse than no
        # wrapper, because the install still reports the gates as wired.
        bash = "if [ -f %s ]; then exec bash %s; fi; echo '{}'" % (target, target)
    return [{"type": "command", "bash": bash, "timeoutSec": timeout}]

path = os.path.join(home, ".copilot", "hooks", "ddw.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"version": 1, "hooks": {
        "sessionStart": entry("session-start.sh", 10),
        "preToolUse": entry("pre-tool-use.sh", 15),
        "postToolUse": entry("post-write.sh", 15),
        "preCompact": entry("pre-compact.sh", 10),
    }}, fh, indent=2)
    fh.write("\n")
print("  ✓ ~/.copilot/hooks/ddw.json  the gates wired at user level%s"
      % ((" → %s" % root) if root else " → each repo's own .github/hooks/ddw/"))

# An earlier DDW wrote its hooks into the `hooks` key of settings.json. Both
# locations load, so leaving that one behind judges every write twice — and
# after an uninstall it points at scripts that are gone, which fails closed and
# denies every tool in every repo. Ours goes; the user's settings stay.
sp = os.path.join(home, ".copilot", "settings.json")
try:
    with open(sp, encoding="utf-8") as fh:
        settings = json.load(fh) or {}
except (OSError, ValueError):
    settings = None
if isinstance(settings, dict) and isinstance(settings.get("hooks"), dict):
    kept = {k: v for k, v in settings["hooks"].items()
            if not (isinstance(v, list) and any("ddw" in json.dumps(e) for e in v))}
    if kept != settings["hooks"]:
        settings["hooks"] = kept
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
            fh.write("\n")
        print("  ✓ ~/.copilot/settings.json  the older DDW hooks removed (they judged every write twice)")
