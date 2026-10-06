// check-spend: the live .claude/harness.json spend patterns ask before every command that bills
// OpenAI (paid:* scripts, the paid entry modules run directly, an HTTP post to /api/ask or
// /api/documents) and stay quiet for the checks and read-only calls. Replays PreToolUse payloads
// through .claude/hooks/guard.mjs as the main session would send them.
//
// Does NOT exercise: spellings no pattern names (httpie, wget, a Python one-liner that posts),
// a subagent or background launch (the guard denies those; check:hooks covers it), or that
// Claude Code invokes the hook at all.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const guard = path.join(root, '.claude', 'hooks', 'guard.mjs');

function decision(tool, command) {
  const input = JSON.stringify({
    session_id: 'check-spend', hook_event_name: 'PreToolUse', cwd: root, permission_mode: 'default',
    tool_name: tool, tool_input: { command, description: 'x' },
  });
  const r = spawnSync(process.execPath, [guard, 'PreToolUse'], { input, encoding: 'utf8', env: { ...process.env, CLAUDE_PROJECT_DIR: root, HARNESS_HOOKS: '' } });
  const text = (r.stdout || '').trim();
  return text ? JSON.parse(text).hookSpecificOutput?.permissionDecision ?? null : null;
}

const cases = [
  ['Bash', 'npm run paid:smoke', 'ask'],
  ['Bash', 'uv --directory backend run python -m loreos.smoke', 'ask'],
  ['PowerShell', 'py -m loreos.evaluation', 'ask'],
  ['Bash', 'cd backend && python -m loreos.demo', 'ask'],
  ['Bash', 'curl -F file=@handbook.md http://127.0.0.1:8000/api/documents', 'ask'],
  ['Bash', `curl -s -X POST http://127.0.0.1:8000/api/ask -H 'content-type: application/json' -d '{"question":"x"}'`, 'ask'],
  ['Bash', `curl --json '{"question":"x"}' localhost:8000/api/ask`, 'ask'],
  ['PowerShell', `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/ask -Body '{"question":"x"}' -ContentType application/json`, 'ask'],
  ['PowerShell', 'irm http://127.0.0.1:8000/api/documents -Method Post -Form $form', 'ask'],
  // Spellings that slipped past the first patterns (whole-branch review): an exempt token as a
  // substring (-h in --header or a filename), bundled flags, --module, assignments, aliases.
  ['Bash', `curl -X POST --header "content-type: application/json" -d '{"question":"x"}' http://127.0.0.1:8000/api/ask`, 'ask'],
  ['Bash', 'curl -F file=@employee-handbook.md http://127.0.0.1:8000/api/documents', 'ask'],
  ['Bash', 'curl -sFfile=@a.md http://127.0.0.1:8000/api/documents', 'ask'],
  ['Bash', 'uv run --module loreos.smoke', 'ask'],
  ['Bash', 'python -mloreos.smoke', 'ask'],
  ['Bash', 'uv run python backend/loreos/smoke.py', 'ask'],
  ['PowerShell', '$r = Invoke-RestMethod -Method:Post -Uri http://127.0.0.1:8000/api/ask -Body $b', 'ask'],
  ['PowerShell', 'curl -Method Post -Uri http://127.0.0.1:8000/api/ask -Body $b', 'ask'],
  ['Bash', 'http POST 127.0.0.1:8000/api/ask question=x', 'ask'],
  ['Bash', 'npm run-script paid:smoke', 'ask'],
  ['PowerShell', 'npm.cmd run paid:smoke', 'ask'],
  // A GET of the document list asks too: the HTTP pattern fails closed on any client naming a paid route.
  ['Bash', 'curl -s http://127.0.0.1:8000/api/documents', 'ask'],
  // From the re-review: a --dry-run or --help anywhere else in the text exempts nothing, npm flags
  // around run, and a client called by its path.
  ['Bash', 'npm run paid:smoke --dry-run', 'ask'],
  ['Bash', 'python -m loreos.smoke --dry-run --now', 'ask'],
  ['Bash', `curl -d '{"question":"what does --dry-run do?"}' http://127.0.0.1:8000/api/ask`, 'ask'],
  ['Bash', 'npm run -s paid:smoke', 'ask'],
  ['Bash', 'npm --silent run paid:smoke', 'ask'],
  ['Bash', '/usr/bin/curl -F file=@a.md http://127.0.0.1:8000/api/documents', 'ask'],
  ['Bash', '/c/Windows/System32/curl.exe -F file=@a.md http://127.0.0.1:8000/api/documents', 'ask'],
  ['PowerShell', 'C:\\Windows\\System32\\curl.exe -F file=@a.md http://127.0.0.1:8000/api/documents', 'ask'],
  // Free: the checks, the server itself, the exact free forms of a paid entry, and text that only
  // names the routes or modules.
  ['Bash', 'npm run check:backend', null],
  ['Bash', 'uv --directory backend run python -m pytest', null],
  ['Bash', 'npm run dev:api', null],
  ['Bash', 'npm run paid:smoke -- --dry-run', null],
  ['Bash', 'npm run paid:smoke -- --help', null],
  ['Bash', 'uv --directory backend run python -m loreos.smoke --dry-run', null],
  ['PowerShell', 'py -m loreos.smoke --help', null],
  ['Bash', 'curl -s http://127.0.0.1:8000/docs', null],
  ['Bash', 'grep -rn loreos.smoke backend', null],
  ['Bash', 'grep -rn "python -m loreos.smoke" docs', null],
  ['Bash', 'grep -rn "npm run paid:smoke" docs', null],
  ['Bash', 'grep -rn "http://127.0.0.1:8000/api/ask" docs', null],
  ['Bash', 'git commit -m "uv: loreos.smoke refuses args"', null],
  ['Bash', 'git add backend/loreos/smoke.py', null],
];

let fail = 0;
for (const [tool, command, want] of cases) {
  const got = decision(tool, command);
  const ok = got === want;
  if (!ok) fail++;
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${tool}: ${command} -> ${got ?? 'no decision'}${ok ? '' : ` (want ${want ?? 'no decision'})`}`);
}
console.log(`\n${cases.length - fail}/${cases.length} spend checks passed`);
process.exit(fail ? 1 : 0);
