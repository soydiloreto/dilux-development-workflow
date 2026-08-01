# DDW — Dilux Development Workflow (plugin install)

DDW is installed globally as an OpenCode plugin, so it governs THIS repo — the
one you are working in — even though no DDW files live here. This repo is a
normal project repo, not DDW's own; the method's files live with the plugin.

Before answering, run the Boot Sequence of the orchestrator, resolved repo-first:

- If this repo has `.ddw/orchestrator.md`, read **that one** — the repo's copy
  always wins over the plugin's.
- Otherwise read `~/.config/opencode/ddw/orchestrator.md`.

It is a strict state machine: it decides what you are allowed to do based on the
phase recorded in `.ddw-state.json` at the repo root. No state file means IDLE —
no pipeline has been started in this repo yet: work that touches the repo starts
by CLASSIFYING it into a ticket, not by writing code.
