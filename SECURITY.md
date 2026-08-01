# Security

## What DDW does to your repository

The installer writes into the repo you point it at: `.ddw/`, the wiring
directory for the tools you pick, a context file, and a `.gitignore` block. It
never writes outside that repo, never touches your machine's global config, and
never sends anything anywhere. There is no telemetry and no network access at
any point, install or run.

DDW then installs hooks that your coding agent executes. That is the point — the
enforcement is code running outside the model — but it means installing DDW means
running its scripts on every write. They are short and readable, and reading them
before you install is a reasonable thing to do.

Codex CLI and Gemini CLI fingerprint the hooks a repository brings and quarantine
them until you approve them with `/hooks`. That is a defence against exactly this
class of risk, and it is worth understanding rather than clicking past.

## What DDW does not protect you from

It is a process guard, not a sandbox. It refuses transitions the graph does not
carry and writes of product source from phases that forbid them. It does not
contain what your agent does inside a phase where writing is allowed, and it
cannot stop a tool DDW does not intercept.

The SAST gate finds known patterns in code. It does not find business-logic flaws
or authorization mistakes, and the repository says so in more detail than most
tools would.

## Reporting a vulnerability

Open a GitHub security advisory on the repository rather than a public issue, and
give it a few days before disclosing.

Findings of the shape *"this guard can be bypassed by X"* are the most valuable
thing you can send. A reproduction — the state, the event, the exit code — is
worth more than a description, because the fix ships with a test built from it.
