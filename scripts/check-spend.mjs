// check-spend: the live .claude/harness.json spend patterns ask before every command that can bill
// OpenAI (paid:* scripts in any runner, an interpreter touching the paid loreos modules, any HTTP
// client naming the dev API's /api or port 8000) and stay quiet for the checks and the server.
// No form is exempt, --dry-run included. Replays PreToolUse payloads through
// .claude/hooks/guard.mjs as the main session would send them.
//
// Does NOT exercise: the spellings docs/KNOWN-GAPS.md lists (a one-liner posting with its own HTTP
// library, a script file, names held in variables, PowerShell backtick escapes, eval), a subagent
// or background launch (the guard denies those; check:hooks covers it), or that Claude Code
// invokes the hook at all.
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
  // Not anchored at the start, so other package runners, blocks, pipelines and substitutions are seen
  // (the anchored patterns of one commit missed these).
  ['Bash', 'pnpm run paid:smoke', 'ask'],
  ['Bash', 'yarn paid:smoke', 'ask'],
  ['Bash', 'bun run paid:smoke', 'ask'],
  ['Bash', 'node --run paid:smoke', 'ask'],
  ['PowerShell', '1..3 | % { irm -Method Post -Uri http://127.0.0.1:8000/api/ask -Body $b }', 'ask'],
  ['PowerShell', 'try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/ask -Body $b } catch {}', 'ask'],
  ['Bash', 'x=$(curl -F file=@a.md http://127.0.0.1:8000/api/documents)', 'ask'],
  ['Bash', `python -c "from loreos.smoke import cli; cli([])"`, 'ask'],
  ['Bash', `bash -c "curl -F file=@a.md http://127.0.0.1:8000/api/documents"`, 'ask'],
  ['PowerShell', `powershell -Command "irm -Method Post -Uri http://127.0.0.1:8000/api/ask -Body '{}'"`, 'ask'],
  // Third review: npm abbreviations (all run scripts, checked on npm 10.9), npm.ps1, a quoted program
  // path, wrappers and assignments, uv.exe, and URL spellings curl or the server normalise.
  ['Bash', 'npm run-s paid:smoke', 'ask'],
  ['Bash', 'npm runScript paid:smoke', 'ask'],
  ['PowerShell', 'npm.ps1 run paid:smoke', 'ask'],
  ['PowerShell', '& "C:\\Program Files\\nodejs\\npm.cmd" run paid:smoke', 'ask'],
  ['PowerShell', 'cmd /c npm run paid:smoke', 'ask'],
  ['PowerShell', '$out = npm run paid:smoke', 'ask'],
  ['PowerShell', 'Measure-Command { npm run paid:smoke }', 'ask'],
  ['PowerShell', 'pwsh -c "npm run paid:smoke"', 'ask'],
  ['PowerShell', '$o = uv --directory backend run python -m loreos.smoke', 'ask'],
  ['Bash', 'uv.exe run python -m loreos.smoke', 'ask'],
  ['PowerShell', '& "C:\\Program Files\\curl\\curl.exe" -F file=@a.md http://127.0.0.1:8000/api/documents', 'ask'],
  ['Bash', `curl -d '{"question":"x"}' http://127.0.0.1:8000/api/./ask`, 'ask'],
  ['Bash', `curl -d '{"question":"x"}' http://127.0.0.1:8000/api/%61sk`, 'ask'],
  ['Bash', `curl -d '{"question":"x"}' 'http://127.0.0.1:8000/api/[a-a]sk'`, 'ask'],
  ['Bash', `curl -d '{"question":"x"}' http://127.0.0.1:8000/%61pi/ask`, 'ask'],
  ['Bash', 'curl -s http://127.0.0.1:8000/docs', 'ask'],
  // No free form is exempt, --dry-run included: what `npm run paid:smoke -- --dry-run` runs depends on
  // state the text does not show (package.json, .npmrc, an earlier `export npm_config_*=` or
  // PYTHONPATH), so every paid spelling asks and the operator approves the preflight too.
  ['Bash', 'npm run paid:smoke -- --dry-run', 'ask'],
  ['Bash', 'npm run paid:smoke -- --help', 'ask'],
  ['PowerShell', 'npm.cmd run paid:smoke -- --dry-run', 'ask'],
  ['Bash', 'export npm_config_script_shell=evil.sh; npm run paid:smoke -- --dry-run', 'ask'],
  ['Bash', 'npm run paid:eval -- --dry-run', 'ask'],
  ['Bash', 'python -m loreos.evaluation --dry-run', 'ask'],
  ['Bash', 'python -m loreos.demo --help', 'ask'],
  // Fourth review: text around a free form changed what runs (npm flags, other runners, a -c before
  // the module); one-liners importing a paid module; npm through its JS entry; a zero-padded port.
  ['Bash', 'npm --script-shell=evil.cmd run paid:smoke -- --dry-run', 'ask'],
  ['Bash', 'pnpm run paid:smoke -- --dry-run', 'ask'],
  ['Bash', 'node --run paid:smoke -- --dry-run', 'ask'],
  ['Bash', 'uv --directory backend run python -m loreos.smoke --dry-run', 'ask'],
  ['PowerShell', 'py -m loreos.smoke --help', 'ask'],
  ['Bash', `python -c "import os; os.system('x')" -m loreos.smoke --dry-run`, 'ask'],
  ['Bash', `uv --directory backend run python -c "from loreos import smoke; smoke.cli([])"`, 'ask'],
  ['Bash', `uv run python -c "from loreos import answering"`, 'ask'],
  ['PowerShell', 'node "C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js" run paid:smoke', 'ask'],
  ['Bash', 'curl -d x http://127.0.0.1:08000/%61pi/ask', 'ask'],
  // httpie with flags before the URL (narrowing httpie to "URL next" dropped these for one commit).
  ['Bash', 'http -f POST 127.0.0.1:8000/api/documents file@a.md', 'ask'],
  ['Bash', 'http --auth u:p POST localhost/api/ask question=x', 'ask'],
  ['Bash', 'https --verify=no :8000/api/ask question=x', 'ask'],
  // Fails closed: text that names a paid command asks too (the plain `npm run paid:` pattern did the
  // same), and so does a tool run through uv on a paid module's file.
  ['Bash', 'grep -rn "npm run paid:smoke" docs', 'ask'],
  ['Bash', 'grep -rn "python -m loreos.smoke" docs', 'ask'],
  ['Bash', 'uvx ruff check backend/loreos/smoke.py', 'ask'],
  // Free: the checks, the server itself, the exact free forms of paid:smoke, and text that names only
  // a URL, a file or prose.
  ['Bash', 'npm run check:backend', null],
  ['Bash', 'uv --directory backend run python -m pytest', null],
  ['Bash', 'uv --directory backend run python -m pytest tests/test_ingest.py', null],
  ['Bash', 'npm run dev:api', null],
  ['Bash', 'uv --directory backend run python -m uvicorn loreos.main:app --host 127.0.0.1 --port 8000', null],
  ['Bash', 'npm run db:migrate', null],
  ['Bash', 'curl -s https://example.com/health', null],
  ['Bash', 'git commit -m "fix: http 413 for /api/documents"', null],
  ['Bash', 'grep -rn loreos.smoke backend', null],
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
