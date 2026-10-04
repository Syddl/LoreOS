---
paths: ["backend/**", "frontend/**", "scripts/**"]
---

# House style

Rules a linter cannot express. They load when a matching file is read.

- Defaults over knobs. A behaviour whose absence would be wrong in production ships unconditionally, and a check pins that no environment read disables it. A kill switch is for a behaviour with rollback-worthy operational risk; environment keys are for ops tuning (URLs, cadence, concurrency, timeouts). Do not add an option nobody asked for.
- Fail before you spend. Validate inputs, credentials and quotas before the first paid call. A failure after spend is a bug, not bad luck. A preflight may let an ambiguous read through, but a definitive rejection, such as an invalid key, blocks before the first paid call in every mode.
- An unread value is null, never 0 or an empty list, and every guard states what an unreadable input does: `Number(null)` and `Number('')` are 0 and pass `Number.isFinite`, a failed lookup returns unverified rather than absent, and `if (x && x !== expected)` passes silently when x could not be read.
- Guards fail closed. An auth or spend check that passes when its key list or verifier is unset opens every route in a deployment that configures a different mechanism. Read configuration where it is used, not in a top-level constant evaluated at import, before the env loader has run.
- One owner per fact. A value is computed or declared in one place; everything else reads it. Never copy a constant into a second file. Before changing a rule, a default or an allowed value, search the whole tree for every copy and every reader of the old one, checks and UI mirrors included; a rule patched in N places has an N+1th, and the fix routes every reader through the one owner.
- A resume key covers every input that shaped the checkpoint, options that default from the environment included, or the checkpoint is re-judged against the current settings before reuse. An env-defaulted option hashes the same across a change, and the resume reuses work built for the other setting.
- Prefer a new small module over editing a dormant one. Do not touch files the live path does not import.
- Errors carry the corrective action. "KEY is not set; add it to .env" beats "config error".
- Log what a person will grep for: the id, the stage, the count. Never log a secret or an env value. Every fallback, re-roll, degrade or skipped step writes its reason to the run's persistent record, and the view that shows the record displays it; a recovery that only logs leaves no evidence it ever fired, and a feature that hides itself without a reason reads as broken.
- Classify a failure before handling it, using the failure classes in `harness:triaging-a-failed-run`. The error code discriminates; the message does not.
- Keep template literals single-level and single-line in files that source-text checks read. Hoist a nested clause into a const.
- Relative paths resolve against something. Say against what, or resolve them at the boundary.
- No em-dashes in user-facing copy. This is an example of a project ruling; the reason, and the kill switch when it has one, live in docs/decisions/.
- A change ends with the deliverable: files touched, old vs new behaviour, how it was tested (the command and its result), limitations.
