// DDW — verdict tap for the OpenCode adapter.
//
// Installed by the eval runner only, AROUND the adapter's own plugin. It
// changes no verdict — it records one, in the same
// `.ddw-eval-verdicts.jsonl` the Claude Code tap writes, with the same fields
// (`hook`, `exit`, `tool`, `path`), so `judge_repo_state` does not change.
//
// Why a wrapper and not a shell shim: OpenCode's adapter is a JavaScript
// plugin, not a hook script. Its enforcement boundary is the pair of hooks
// `tool.execute.before` / `tool.execute.after`, and its verdict is not an exit
// code but a THROW: the plugin runs the shared gate with execFileSync and
// re-throws as `DDW blocked the write.` Throwing is what stops the tool call.
// So the tap wraps the returned hook table and reads that boundary directly:
//
//     the real hook returned  -> exit 0   (allowed)
//     the real hook threw     -> exit 2   (blocked; same code Claude's hooks use)
//
// This is the honest reading. It records what the enforcement layer actually
// did to the tool call, not what the model said about it, and it records
// NOTHING when the plugin never loads or never runs — which leaves the
// scenario red, as it must.
import { appendFileSync } from "node:fs"
import { DdwPlugin as RealDdwPlugin } from "__REAL__"

const LOG = "__LOG__"

// The same spellings the shared gate accepts (validate-transition.PATH_KEYS),
// so a path recorded here is the path the gate judged.
const PATH_KEYS = ["file_path", "notebook_path", "path", "filePath", "file", "absolute_path"]

const pickPath = (...bags) => {
  for (const bag of bags) {
    if (!bag || typeof bag !== "object") continue
    for (const k of PATH_KEYS) {
      const v = bag[k]
      if (typeof v === "string" && v) return v
    }
  }
  return null
}

const record = (row) => {
  try {
    appendFileSync(LOG, JSON.stringify(row) + "\n")
  } catch (e) {
    // A tap that cannot write must be loud: a silent tap is the "instrument
    // that reports success for its own failure" this framework exists to stop.
    console.error(`DDW-EVAL-TAP: could not append a verdict to ${LOG}: ${e.message}`)
  }
}

export const DdwPlugin = async (ctx) => {
  const real = await RealDdwPlugin(ctx)
  const wrapped = { ...real }

  for (const name of ["tool.execute.before", "tool.execute.after"]) {
    const fn = real[name]
    if (typeof fn !== "function") continue
    wrapped[name] = async (input, output) => {
      let thrown = null
      try {
        await fn(input, output)
      } catch (e) {
        thrown = e
      }
      record({
        hook: name,
        exit: thrown ? 2 : 0,
        tool: input?.tool ?? null,
        path: pickPath(output?.args, input?.args, output?.metadata),
        reason: thrown ? String(thrown.message ?? thrown).slice(0, 500) : null,
      })
      if (thrown) throw thrown
    }
  }
  return wrapped
}
