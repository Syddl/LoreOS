// check-hooks.mjs — fixture tests for the project guard hook (.claude/hooks/guard.mjs).
//
// What this proves: that guard.mjs returns the intended permission decision for recorded
// PreToolUse / PostToolUse payloads (spend per subcommand with comments stripped, dangerous
// commands in token and regex form, restore on a dirty tree, worktree removal over a junction
// up to three levels deep, reviewer read-only shell including redirections and substitutions,
// git global options before the subcommand (-C, -c, --git-dir, --no-pager, quoted paths) for
// the deny list, the dirty-tree check, worktree removal and the reviewer allowlist, reviewer
// refusal of -c/--config-env/--exec-path, plugin-namespaced reviewer agent types, reviewer
// refusal of the write and exec flags of an allowlisted tool (find -delete/-exec/-fprint...,
// rg --pre/--hostname-bin, git diff/log/show --output, node preload, profile, report and
// inspector flags with _ for -, npm --, -C/--prefix, --node-options, --script-shell and the
// config and log paths in nopt's one-dash, abbreviated and bundled spellings), the shared
// normalisation against every rule (a single & and |& split subcommands while a redirection &
// does not, $'...' ANSI-C and $"..." quoting decode, unquoted brace lists expand and a brace
// bomb is refused, a backslash-newline joins, ${IFS}/$IFS is whitespace, leading !/if/then are
// stripped, quotes and bash backslashes leave each word, subshells and groups open), quote-aware
// splitting (a separator inside '...', "...", $'...' or ${...}, or after a backslash, does not
// split, so a quoted separator neither hides a refused flag nor refuses a harmless pattern; a
// newline inside quotes stays in its word while a heredoc body is judged line by line, including
// inside "$(cat <<'EOF' ... )"; a quote inside a comment is not a quote; an unbalanced quote is
// refused for a reviewer; PowerShell quoting, where a backslash is not an escape), the deny-list
// reason naming its entry, leading
// NAME=value assignments and wrapper words (env, command, nohup, nice, timeout, stdbuf, sudo...)
// before spend regexes, the deny list, the dirty check, worktree removal and the reviewer,
// protected paths, deploy flag with old-flag pruning, kill switch, missing config, bad input)
// and the intended advisory systemMessage for Stop payloads (dirty tree with no ledger row for
// HEAD), against a FIXTURE config in a temp directory. The reviewer agent_type values used here
// match a live observation: Claude Code sent agent_type "harness:reviewer" to PreToolUse hooks
// for a dispatched plugin agent, and null for the main session (2026-09-13, Windows).
//
// What this does NOT exercise: that Claude Code actually invokes the hook (that is
// .claude/settings.json plus the phase-0 spike), the agent_type a later Claude Code version
// sends, permission-rule behaviour in settings.json (the belt to this
// hook's suspenders), the PowerShell tool's own command canonicalisation, shell syntax the
// scanner does not model (a case pattern's ) inside $(...), ' inside a double-quoted ${x#...},
// the commands inside a PowerShell @"..."@ here-string), a command run from a
// shell string or a feeder (bash -c "...", env -S, xargs), a command substitution ($(...),
// backticks) judged outside the reviewer, a variable or eval, a path-qualified binary
// (/usr/bin/env, git.exe), a Git Bash /c/... path given to -C on Windows
// (resolved as written against the cwd), that each refused flag really writes or runs on
// every version of its tool (probed once on GNU find 4.10, ripgrep 15.0, git 2.53, node 22.22
// and npm 10.9), the flags of a tool outside the guard's table, V8 pass-through options, the
// positional arguments a script runner hands its script, or the live .claude/harness.json
// patterns beyond "it parses and has the keys the guard reads". Zero credits, no network.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const guard = path.join(repoRoot, '.claude', 'hooks', 'guard.mjs');

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name}${detail ? ' — ' + detail : ''}`); }
}

const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'harness-check-'));
const proj = path.join(tmpRoot, 'proj');
fs.mkdirSync(path.join(proj, '.claude'), { recursive: true });
const fixtureConfig = {
  version: 1,
  project: { name: 'fixture' },
  spend: { patterns: ['node cli.js', 'npm start', 'probe:', 're:-X\\s+POST\\s+\\S*/api/jobs', 're:^npm\\s+run\\s+backfill\\b'], exempt: ['--dry-run'] },
  dangerous: {
    deny: [
      'git add -A *', 'git add . *', 'git add --all *', 'git push --force *', 'git push -f *', 'git reset --hard *', 'git clean *', 'sudo shutdown *', 'rm -rf output/*',
      're:^git\\s+add\\b(?=.*(?:\\s-[A-Za-z]*A[A-Za-z]*\\b|\\s--all\\b|\\s\\.{1,2}/?(?:\\s|$)|\\s:/|\\s\\*(?:\\s|$)|\\s--\\s+\\.{1,2}/?(?:\\s|$)))',
      're:^git\\s+push\\b(?=.*(?:\\s--force\\b|\\s-f\\b|\\s--force-with-lease\\b|\\s\\+\\S))',
      're:^git\\s+reset\\b(?=.*\\s--hard\\b)',
      're:^(?:rm|rmdir|del)\\b(?=.*(?:\\s-[A-Za-z]*[rR]|\\s--recursive\\b))(?=.*["\']?\\b(?:output|data|sessions)[/\\\\])',
      're:^Remove-Item\\b(?=.*-Recurse)(?=.*\\b(?:output|data|sessions)\\b)',
    ],
    ask_when_dirty: ['git checkout -- *', 'git restore *'],
  },
  protected_paths: { ask: ['.env', 'package-lock.json', '.github/workflows/ci.yml'], deny: ['assets/generated/*.json'] },
  deploy: { code_only: 'npm run deploy:code', env_or_deps: 'npm run deploy:full', env_or_deps_triggers: ['.env', '.env.*', 'package.json', 'package-lock.json'] },
  reviewer: { agent_types: ['reviewer'], readonly_allow: ['git log', 'git show', 'git diff', 'git status', 'git ls-tree', 'git cat-file', 'git ls-files', 'git check-ignore', 'ls', 'cat', 'head', 'tail', 'wc', 'grep', 'rg', 'find', 'node --check', 'npm run lint:js', 'npm run check:'] },
};
fs.writeFileSync(path.join(proj, '.claude', 'harness.json'), JSON.stringify(fixtureConfig, null, 2));

function run(event, payload, envExtra = {}, projectDir = proj) {
  const input = typeof payload === 'string' ? payload : JSON.stringify({ session_id: 'sess-default', hook_event_name: event, cwd: projectDir, permission_mode: 'default', ...payload });
  const r = spawnSync(process.execPath, [guard, event], { input, encoding: 'utf8', env: { ...process.env, CLAUDE_PROJECT_DIR: projectDir, HARNESS_HOOKS: '', ...envExtra } });
  let out = {};
  const text = (r.stdout || '').trim();
  if (text) { try { out = JSON.parse(text); } catch { out = { _unparsable: text }; } }
  const spec = out.hookSpecificOutput || {};
  return { status: r.status, stderr: (r.stderr || '').trim(), out, decision: spec.permissionDecision || null, reason: spec.permissionDecisionReason || '' };
}
const bash = (command, extra = {}) => {
  const { tool_input: ti, ...rest } = extra;
  return { tool_name: 'Bash', tool_input: { command, description: 'x', run_in_background: false, ...(ti || {}) }, ...rest };
};
const pwsh = (command, extra = {}) => ({ tool_name: 'PowerShell', tool_input: { command, description: 'x' }, ...extra });
const edit = (file_path, tool = 'Edit') => ({ tool_name: tool, tool_input: tool === 'NotebookEdit' ? { notebook_path: file_path } : { file_path } });
const reviewer = { agent_id: 'a2', agent_type: 'reviewer' };
// A directory junction on Windows, a directory symlink elsewhere. Returns false when it cannot be made.
function makeLink(link, target) {
  fs.mkdirSync(path.dirname(link), { recursive: true });
  if (process.platform === 'win32') return spawnSync('cmd', ['/c', 'mklink', '/J', link, target], { encoding: 'utf8' }).status === 0;
  try { fs.symlinkSync(target, link, 'dir'); return true; } catch { return false; }
}
function gitRepo(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const g = (...args) => spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...args], { cwd: dir, encoding: 'utf8' });
  g('init', '-q', '-b', 'main');
  fs.writeFileSync(path.join(dir, 'a.txt'), 'one\n');
  g('add', 'a.txt'); g('commit', '-q', '-m', 'init');
  return g;
}

console.log('guard.mjs fixture checks');
console.log('-- existence');
check('guard.mjs exists at .claude/hooks/guard.mjs', fs.existsSync(guard), guard);

console.log('-- spend');
let r = run('PreToolUse', bash('node cli.js'));
check('node cli.js in the main session -> ask', r.decision === 'ask', JSON.stringify(r));
check('every decision exits 0', r.status === 0, 'exit ' + r.status);
r = run('PreToolUse', bash('node cli.js --dry-run'));
check('node cli.js --dry-run is exempt -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', pwsh('node .\\cli.js'));
check('PowerShell tool, node .\\cli.js -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('node cli.js', { agent_id: 'a1', agent_type: 'general-purpose' }));
check('node cli.js inside a subagent -> deny', r.decision === 'deny', JSON.stringify(r.out));
check('deny reason starts with HARNESS:', /^HARNESS:/.test(r.reason), r.reason);
r = run('PreToolUse', bash('node cli.js', { tool_input: { run_in_background: true } }));
check('node cli.js with run_in_background -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm start'));
check('npm start -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm run probe:gpu'));
check('npm run probe:gpu (substring pattern) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm run lint:js'));
check('npm run lint:js -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('curl -s -X POST http://localhost:3000/api/jobs -H "content-type: application/json" -d @submit.json'));
check('curl -X POST .../api/jobs (regex pattern) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('grep -rn "/api/jobs" src/server.js'));
check('grep for /api/jobs (read-only mention) -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('echo --dry-run; node cli.js'));
check('exempt token in a different subcommand (echo --dry-run; node cli.js) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('echo --dry-run; node cli.js', { agent_id: 'a1', agent_type: 'general-purpose' }));
check('same command inside a subagent -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('node cli.js # --dry-run'));
check('exempt token inside a trailing comment (node cli.js # --dry-run) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('node cli.js --dry-run && node cli.js'));
check('exempt first subcommand, paid second (--dry-run && node cli.js) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('echo "# not a comment" --dry-run; node cli.js --dry-run'));
check('a # inside quotes is not a comment; both subcommands exempt -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('echo start # a note\nnode cli.js'));
check('a comment on one line does not swallow the next line (echo # note NEWLINE node cli.js) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('nohup node cli.js'));
check('nohup node cli.js in the main session -> ask (as without nohup)', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('nohup node cli.js', { agent_id: 'a1', agent_type: 'general-purpose' }));
check('nohup node cli.js inside a subagent -> deny (as without nohup)', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm run backfill'));
check('npm run backfill (start-anchored regex pattern) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('FOO=1 timeout 600 npm run backfill'));
check('FOO=1 timeout 600 npm run backfill (assignment and wrapper before an anchored regex) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('env npm run backfill', { agent_id: 'a1', agent_type: 'general-purpose' }));
check('env npm run backfill inside a subagent -> deny', r.decision === 'deny', JSON.stringify(r.out));

console.log('-- dangerous');
r = run('PreToolUse', bash('git add -A'));
check('git add -A -> deny', r.decision === 'deny', JSON.stringify(r.out));
check('dangerous deny reason starts with HARNESS:', /^HARNESS:/.test(r.reason), r.reason);
r = run('PreToolUse', bash('git add ./src/x.js .claude/settings.json'));
check('git add ./src/x.js (explicit path) -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('git add .'));
check('git add . -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('git push --force origin x'));
check('git push --force -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('git push -u origin x'));
check('git push -u -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('cd src && git add -A && git commit -m x'));
check('compound command with git add -A -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('rm -rf output/job-123'));
check('rm -rf output/job-123 -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('rm -rf work/tmp'));
check('rm -rf work/tmp -> no decision', r.decision === null, JSON.stringify(r.out));
for (const c of ['git add ./', 'git add -v -A', 'git add -- .', 'git add :/', 'git add *', 'git add -Av', 'git add ..', 'git push origin main --force', 'git push origin +main', 'rm -fr output/x', 'rm -rf "output/x"', 'rm --recursive --force data/x']) {
  r = run('PreToolUse', bash(c));
  check(`${c} (regex deny entry) -> deny`, r.decision === 'deny', JSON.stringify(r.out));
}
r = run('PreToolUse', pwsh('Remove-Item -Recurse -Force output'));
check('PowerShell Remove-Item -Recurse -Force output (regex deny entry) -> deny', r.decision === 'deny', JSON.stringify(r.out));
for (const c of ['git add -p src/x.js', 'git add -f src/Assets.js', 'git push origin feature', 'rm -f output/x/log.txt']) {
  r = run('PreToolUse', bash(c));
  check(`${c} -> no decision`, r.decision === null, JSON.stringify(r.out));
}
r = run('PreToolUse', bash('git add . # comment'));
check('a comment after a denied command still denies', r.decision === 'deny', JSON.stringify(r.out));
for (const c of ['git -C . add -A', 'git -c core.autocrlf=false add .', 'git --no-pager -C sub push --force origin x', 'git -C "C:/some path/repo" reset --hard HEAD', 'git --git-dir .git --work-tree=. add --all', 'git -P --literal-pathspecs --no-optional-locks reset --hard HEAD~1', 'git --config-env=user.name=U --exec-path=/x add .']) {
  r = run('PreToolUse', bash(c));
  check(`${c} (git global options before the subcommand) -> deny`, r.decision === 'deny', JSON.stringify(r.out));
}
r = run('PreToolUse', pwsh('git -C . add -A'));
check('PowerShell tool, git -C . add -A -> deny', r.decision === 'deny', JSON.stringify(r.out));
for (const c of ['git -C sub add src/x.js', 'git -C "a add -A" status']) {
  r = run('PreToolUse', bash(c));
  check(`${c} (explicit path, or a quoted -C value) -> no decision`, r.decision === null, JSON.stringify(r.out));
}
for (const [prefixed, bare] of [
  ['GIT_DIR=x git add -A', 'git add -A'],
  ['env git add -A', 'git add -A'],
  ['env -i git push --force', 'git push --force'],
  ['command git reset --hard HEAD', 'git reset --hard HEAD'],
  ['nohup git clean -fd', 'git clean -fd'],
  ['timeout 30 git add .', 'git add .'],
  ['sudo rm -rf output/x', 'rm -rf output/x'],
  ['env -u HOME FOO="a b" git add -A', 'git add -A'],
  ['nice -n 10 git push -f origin x', 'git push -f origin x'],
  ['timeout -s KILL -k 5 30s git reset --hard HEAD', 'git reset --hard HEAD'],
  ['stdbuf -oL -e 0 git add --all', 'git add --all'],
  ['sudo -u root -E git clean -fdx', 'git clean -fdx'],
  ['exec -a x git add -A', 'git add -A'],
  ['builtin command git add .', 'git add .'],
  ['time -p git add -A', 'git add -A'],
  ['nohup nice timeout 5 env A=1 git -C sub push --force', 'git push --force'],
]) {
  const bareDecision = run('PreToolUse', bash(bare)).decision;
  r = run('PreToolUse', bash(prefixed));
  check(`${prefixed} (assignment or wrapper prefix) -> deny, as ${bare} is (${bareDecision})`, bareDecision === 'deny' && r.decision === 'deny', JSON.stringify(r.out));
}
for (const c of ['GIT_EDITOR=true git commit -m x', 'FOO=1 git add src/x.js', 'echo env git add -A']) {
  r = run('PreToolUse', bash(c));
  check(`${c} (prefix before an allowed command, or a wrapper word that is not leading) -> no decision`, r.decision === null, JSON.stringify(r.out));
}
r = run('PreToolUse', bash('sudo shutdown now'));
check('sudo shutdown now (a deny entry that names the wrapper still sees the raw subcommand) -> deny', r.decision === 'deny', JSON.stringify(r.out));

console.log('-- restore on a dirty tree');
const gitRepoDir = path.join(tmpRoot, 'repo');
gitRepo(gitRepoDir);
r = run('PreToolUse', { ...bash('git checkout -- a.txt'), cwd: gitRepoDir });
check('git checkout -- on a clean tree -> no decision', r.decision === null, JSON.stringify(r.out));
fs.writeFileSync(path.join(gitRepoDir, 'a.txt'), 'two\n');
r = run('PreToolUse', { ...bash('git checkout -- a.txt'), cwd: gitRepoDir });
check('git checkout -- with a modified tracked file -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash('git restore a.txt'), cwd: gitRepoDir });
check('git restore with a modified tracked file -> ask', r.decision === 'ask', JSON.stringify(r.out));
const cleanRepoDir = path.join(tmpRoot, 'clean-repo');
gitRepo(cleanRepoDir);
r = run('PreToolUse', { ...bash(`git -C "${gitRepoDir}" checkout -- a.txt`), cwd: cleanRepoDir });
check('git -C <dirty repo> checkout -- from a clean cwd -> ask (the dirty check reads the -C path)', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash(`git -C "${cleanRepoDir}" restore a.txt`), cwd: gitRepoDir });
check('git -C <clean repo> restore from a dirty cwd -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', { ...bash('git -C proj -C ../repo checkout -- a.txt'), cwd: tmpRoot });
check('repeated relative -C resolve against each other and the cwd -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash(`git --git-dir="${gitRepoDir}/.git" --work-tree="${gitRepoDir}" checkout -- a.txt`), cwd: cleanRepoDir });
check('git --git-dir/--work-tree <dirty repo> checkout -- from a clean cwd -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash(`GIT_DIR="${gitRepoDir}/.git" GIT_WORK_TREE="${gitRepoDir}" git checkout -- a.txt`), cwd: cleanRepoDir });
check('GIT_DIR/GIT_WORK_TREE=<dirty repo> git checkout -- from a clean cwd -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash(`env git -C "${gitRepoDir}" restore a.txt`), cwd: cleanRepoDir });
check('env git -C <dirty repo> restore from a clean cwd -> ask', r.decision === 'ask', JSON.stringify(r.out));

console.log('-- worktree removal over a junction');
const wtBase = path.join(tmpRoot, 'wts');
fs.mkdirSync(path.join(wtBase, 'wt-plain', 'node_modules', 'pkg'), { recursive: true });
fs.mkdirSync(path.join(wtBase, 'wt-plain', '.git'), { recursive: true });
fs.mkdirSync(path.join(wtBase, 'target-nm'), { recursive: true });
const junctionOk = makeLink(path.join(wtBase, 'wt-junction', 'node_modules'), path.join(wtBase, 'target-nm'));
const nestedOk = makeLink(path.join(wtBase, 'wt-nested', 'apps', 'web', 'node_modules'), path.join(wtBase, 'target-nm'));
if (junctionOk && nestedOk) {
  r = run('PreToolUse', { ...bash('git worktree remove --force wt-junction'), cwd: wtBase });
  check('git worktree remove over a node_modules junction -> deny', r.decision === 'deny', JSON.stringify(r.out));
  check('junction deny reason names the junction', /junction|link/i.test(r.reason), r.reason);
  r = run('PreToolUse', { ...bash('git worktree remove --force wt-nested'), cwd: wtBase });
  check('git worktree remove over a nested apps/web/node_modules junction (depth 3) -> deny', r.decision === 'deny', JSON.stringify(r.out));
  check('nested junction deny reason names the nested path', /apps[\\/]web[\\/]node_modules/.test(r.reason), r.reason);
  r = run('PreToolUse', { ...bash('git worktree remove wt-plain'), cwd: wtBase });
  check('git worktree remove without a junction -> no decision', r.decision === null, JSON.stringify(r.out));
  r = run('PreToolUse', { ...bash(`git -C "${wtBase}" worktree remove --force wt-junction`), cwd: proj });
  check('git -C <dir> worktree remove over a junction, from another cwd -> deny (target resolved against -C)', r.decision === 'deny', JSON.stringify(r.out));
  r = run('PreToolUse', { ...bash(`nohup git -C "${wtBase}" worktree remove --force wt-junction`), cwd: proj });
  check('nohup git -C <dir> worktree remove over a junction -> deny', r.decision === 'deny', JSON.stringify(r.out));
} else {
  console.log('  skip junction cases (could not create a junction here)');
}

console.log('-- reviewer read-only shell');
r = run('PreToolUse', bash('git diff --stat', reviewer));
check('reviewer: git diff -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('git log --oneline | head -5', reviewer));
check('reviewer: pipe of allowed commands -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('npm run check:unit', reviewer));
check('reviewer: declared check command -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('npm install left-pad', reviewer));
check('reviewer: npm install -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('git diff && rm -rf src', reviewer));
check('reviewer: allowed && disallowed -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm install left-pad', { agent_id: 'a3', agent_type: 'general-purpose' }));
check('non-reviewer subagent: npm install -> no decision', r.decision === null, JSON.stringify(r.out));
for (const c of ['cat x > y', 'echo hi >> f', 'git diff $(rm -rf x)', 'git log | tee out.txt', 'cat `rm x`', 'cat <(rm x)']) {
  r = run('PreToolUse', bash(c, reviewer));
  check(`reviewer: ${c} (redirection, substitution or tee) -> deny`, r.decision === 'deny', JSON.stringify(r.out));
}
check('reviewer redirection deny reason starts with HARNESS:', /^HARNESS:/.test(r.reason), r.reason);
r = run('PreToolUse', bash('npm run check:foo 2>&1 | tail -20', reviewer));
check('reviewer: 2>&1 into an allowed pipe -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('git status 2>/dev/null', reviewer));
check('reviewer: 2>/dev/null -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash(`git -C "${proj}" status --short`, reviewer));
check('reviewer: git -C <abs> status --short -> no decision', r.decision === null, JSON.stringify(r.out));
for (const c of ['git -c core.fsmonitor="touch pwned" status', 'git --config-env=core.pager=EVIL log', 'git --exec-path=/tmp/x diff']) {
  r = run('PreToolUse', bash(c, reviewer));
  check(`reviewer: ${c} (config or exec-path injection runs commands) -> deny`, r.decision === 'deny', JSON.stringify(r.out));
}
for (const c of ['LANG=C git log', 'nohup git status', 'sudo cat x', 'env git diff']) {
  r = run('PreToolUse', bash(c, reviewer));
  check(`reviewer: ${c} (a prefix before an allowed command) -> deny`, r.decision === 'deny', JSON.stringify(r.out));
  check(`reviewer: ${c} deny reason names the prefix`, /prefix/i.test(r.reason), r.reason);
}
const pluginReviewer = { agent_id: 'a4', agent_type: 'harness:reviewer' };
r = run('PreToolUse', bash('npm install x', pluginReviewer));
check('plugin reviewer (harness:reviewer vs entry reviewer): npm install -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash(`git -C "${proj}" status --short`, pluginReviewer));
check('plugin reviewer: git -C <abs> status --short -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', bash('git -C x commit -m y', pluginReviewer));
check('plugin reviewer: git -C x commit -m y -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm install x', { agent_id: 'a5', agent_type: 'otherplugin:reviewer' }));
check('otherplugin:reviewer vs entry reviewer: npm install -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm install x', { agent_id: 'a6', agent_type: 'otherplugin:implementer' }));
check('otherplugin:implementer: npm install -> no decision', r.decision === null, JSON.stringify(r.out));
const projFull = path.join(tmpRoot, 'proj-full');
fs.mkdirSync(path.join(projFull, '.claude'), { recursive: true });
fs.writeFileSync(path.join(projFull, '.claude', 'harness.json'), JSON.stringify({ ...fixtureConfig, reviewer: { ...fixtureConfig.reviewer, agent_types: ['harness:reviewer'] } }));
r = run('PreToolUse', bash('npm install x', { agent_id: 'a7', agent_type: 'harness:reviewer' }), {}, projFull);
check('entry harness:reviewer, agent_type harness:reviewer: npm install -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm install x', { agent_id: 'a8', agent_type: 'reviewer' }), {}, projFull);
check('entry harness:reviewer, bare agent_type reviewer: npm install -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', bash('npm install x', { agent_id: 'a9', agent_type: 'otherplugin:reviewer' }), {}, projFull);
check('entry harness:reviewer names one plugin; otherplugin:reviewer: npm install -> no decision', r.decision === null, JSON.stringify(r.out));

console.log('-- reviewer: write and exec flags of allowlisted tools');
// [command, the flag the reason must name]. The reason names the flag as the guard's table
// spells it, so an abbreviated or underscored spelling still names the full flag.
for (const [c, flag] of [
  ['find . -delete', '-delete'], ['find . -name x -exec rm {} ;', '-exec'], ['find . -execdir rm {} +', '-execdir'],
  ['find . -ok rm {} ;', '-ok'], ['find . -okdir rm {} ;', '-okdir'],
  ['find . -fprint out.txt', '-fprint'], ['find . -fprint0 out.txt', '-fprint0'], ['find . -fprintf out.txt %p', '-fprintf'], ['find . -fls out.txt', '-fls'],
  ['rg --pre sh foo', '--pre'], ['rg --pre=sh foo', '--pre'], ['rg --hostname-bin sh foo', '--hostname-bin'],
  ['git diff --output=out.patch', '--output'], ['git diff --output out.patch', '--output'], ['git log --output=x', '--output'],
  ['git show --output=x HEAD', '--output'], ['git -C . diff --output=x', '--output'],
  ['git status; find . -delete', '-delete'], ['git status && find . -delete', '-delete'],
  ['node --check -r ./p.cjs x.js', '-r'], ['node --check --require=./p.cjs x.js', '--require'],
  ['node --check --import ./p.mjs x.js', '--import'], ['node --check --import=data:text/javascript,0 x.js', '--import'],
  ['node --check --loader ./l.mjs x.js', '--loader'], ['node --check --experimental-loader=./l.mjs x.js', '--experimental-loader'],
  ['node --check --env-file=evil.env x.js', '--env-file'], ['node --check --env_file=evil.env x.js', '--env-file'],
  ['node --check --env-file-if-exists=evil.env x.js', '--env-file-if-exists'], ['node --check --run test', '--run'],
  ['node --check --experimental-config-file=c.json x.js', '--experimental-config-file'],
  ['node --check --experimental-default-config-file x.js', '--experimental-default-config-file'],
  ['node --check --snapshot-blob=s.blob x.js', '--snapshot-blob'], ['node --check --build-snapshot x.js', '--build-snapshot'],
  ['node --check --experimental-sea-config=sea.json x.js', '--experimental-sea-config'],
  ['node --check --cpu-prof x.js', '--cpu-prof'], ['node --check --cpu_prof x.js', '--cpu-prof'], ['node --check --heap-prof x.js', '--heap-prof'],
  ['node --check --prof x.js', '--prof'], ['node --check --redirect-warnings=w.txt x.js', '--redirect-warnings'],
  ['node --check --trace-event-categories v8 x.js', '--trace-event-categories'],
  ['node --check --report-on-signal x.js', '--report-on-signal'], ['node --check --report-on-fatalerror x.js', '--report-on-fatalerror'],
  ['node --check --report-uncaught-exception x.js', '--report-uncaught-exception'],
  ['node --check --heapsnapshot-signal=SIGUSR2 x.js', '--heapsnapshot-signal'],
  ['node --check --heapsnapshot-near-heap-limit=1 x.js', '--heapsnapshot-near-heap-limit'],
  ['node --check --localstorage-file=ls.db x.js', '--localstorage-file'],
  ['node --check --inspect x.js', '--inspect'], ['node --check --inspect=9229 x.js', '--inspect'],
  ['node --check --inspect-brk x.js', '--inspect-brk'], ['node --check --inspect-wait x.js', '--inspect-wait'],
  ['npm run check:x -- --import=data:text/javascript,0', '--'],
  ['npm run check:x --node-options=--require=./p.cjs', '--node-options'], ['npm run check:x --node-options "--require ./p.cjs"', '--node-options'],
  ['npm run check:x --node-opt=--require=./p.cjs', '--node-options'], ['npm run check:x -node-options=--require=./p.cjs', '--node-options'],
  ['npm run check:x --script-shell=sh', '--script-shell'], ['npm run check:x --scr=git', '--script-shell'],
  ['npm run check:x --prefix=sub', '--prefix'], ['npm run check:x --prefi=sub', '--prefix'],
  ['npm run check:x -C sub', '-C'], ['npm run check:x -gC sub', '-C'],
  ['npm run check:x --userconfig=evil.npmrc', '--userconfig'], ['npm run check:x --globalconfig=evil.npmrc', '--globalconfig'],
  ['npm run check:x --cache=c', '--cache'], ['npm run check:x --logs-dir=l', '--logs-dir'], ['npm run check:x --logs-d=l', '--logs-dir'],
]) {
  r = run('PreToolUse', bash(c, reviewer));
  check(`reviewer: ${c} (writes or runs a command through ${flag}) -> deny naming ${flag}`, r.decision === 'deny' && r.reason.includes(`through ${flag}. `), JSON.stringify(r.out));
}
check('reviewer flag deny reason starts with HARNESS: and names the agent type', /^HARNESS: the reviewer agent has a read-only shell; /.test(r.reason), r.reason);
r = run('PreToolUse', bash('find . -delete', pluginReviewer));
check('plugin reviewer (harness:reviewer): find . -delete -> deny naming -delete', r.decision === 'deny' && r.reason.includes('through -delete. '), JSON.stringify(r.out));
for (const c of [
  'find . -name "*.mjs"', 'find . -type f -newer package.json', 'find ./x-delete-me -name y',
  'rg --files', 'rg -n foo src', 'rg --pre-glob "*.gz" foo',
  'git diff --stat', 'git diff --output-indicator-new=+', 'git log --oneline -5', 'git show HEAD',
  'node --check x.js', 'npm run check:x --silent', 'npm run check:x --if-present', 'npm run check:x --loglevel=warn', 'npm run lint:js --no-update-notifier',
]) {
  r = run('PreToolUse', bash(c, reviewer));
  check(`reviewer: ${c} (no write or exec flag) -> no decision`, r.decision === null, JSON.stringify(r.out));
}
r = run('PreToolUse', bash('find . -delete', { agent_id: 'a3', agent_type: 'general-purpose' }));
check('non-reviewer subagent: find . -delete -> not refused by the read-only rule', !/read-only shell/.test(r.reason), JSON.stringify(r.out));

console.log('-- shell-expansion evasions in the shared normaliser');
// Each evasion is judged by every rule, so assert it twice: as the main session against the
// deny list (the second/only subcommand is a force push or hard reset), and as a reviewer
// against find -delete. denyMain(): the deny list fires. denyRev(): the read-only shell fires.
const denyMain = (c) => { const x = run('PreToolUse', bash(c)); check(`main: ${c} -> deny`, x.decision === 'deny', JSON.stringify(x.out)); };
const denyRev = (c) => { const x = run('PreToolUse', bash(c, reviewer)); check(`reviewer: ${c} -> deny (read-only)`, x.decision === 'deny' && /read-only shell/.test(x.reason), JSON.stringify(x.out)); };
const noneMain = (c) => { const x = run('PreToolUse', bash(c)); check(`main: ${c} -> no decision`, x.decision === null, JSON.stringify(x.out)); };
const noneRev = (c) => { const x = run('PreToolUse', bash(c, reviewer)); check(`reviewer: ${c} -> no decision`, x.decision === null, JSON.stringify(x.out)); };
const NL = String.fromCharCode(10); // a real newline, for a backslash-newline continuation

// 1. a single & and |& separate subcommands; &&, redirections and &> stay as they are.
denyMain('git status & git push --force origin x');
denyMain('git status|& git push -f origin x');
denyMain('ls & git reset --hard HEAD');
denyRev('git status & find . -delete');
denyRev('git log |& find . -delete');
noneMain('git status && git log --oneline -3');                 // && is one separator, both judged
noneMain('echo x &>/dev/null');                                 // &> is a redirection, not a separator
noneMain('echo x &>>log');                                      // &>> too
noneMain('npm run check:all 2>&1');                             // 2>&1 keeps the one subcommand whole
noneRev('git status && git log --oneline -3');
noneRev('npm run check:all 2>&1');

// 2. $'...' is ANSI-C decoded, $"..." is a double-quoted string, before matching.
denyMain("git reset $'--hard' HEAD");
denyMain("git push $'--force' origin x");
denyMain("git reset $'\\x2d\\x2dhard' HEAD");                   // \xHH: 2d 2d -> --
denyMain('git reset $"--hard" HEAD');
denyRev("find . $'-delete'");
denyRev("find . $'\\x2ddelete'");
denyRev('find . $"-delete"');
noneRev("git log --format=$'%h'");                              // decodes to a git log flag, still allowed

// 3. unquoted brace expansion is expanded and every word judged; a quoted brace is not; a bomb is refused.
denyMain('git reset --{hard,quiet} HEAD');
denyMain('git push --{force,quiet} origin x');
denyRev('find . -{delete,print}');
denyRev('find . -name x -{delete,print}');
noneRev('find . -name "*.{js,mjs}"');                           // quoted, not expanded
noneRev("git log --format='%h {x,y}'");                        // quoted, not expanded
noneMain('echo ${HOME}');                                       // ${VAR} is not a brace list
const braceBomb = 'find . ' + '{a,b}'.repeat(7);               // 2^7 = 128 words > cap 64
r = run('PreToolUse', bash(braceBomb, reviewer));
check('reviewer: a brace bomb (>64 words) -> deny naming brace expansion', r.decision === 'deny' && /brace/i.test(r.reason), JSON.stringify(r.out));
r = run('PreToolUse', bash(braceBomb));
check('main: a brace bomb (>64 words) -> deny naming brace expansion', r.decision === 'deny' && /brace/i.test(r.reason), JSON.stringify(r.out));

// 4. a backslash-newline continuation joins its lines (with nothing between) before splitting.
denyMain('git push --for\\' + NL + 'ce origin x');
denyRev('find . -dele\\' + NL + 'te');
noneMain('git status \\' + NL + '&& git log --oneline -3');

// 5. ${IFS} and $IFS are whitespace when matching. A $IFS bareword expands only before a
//    non-identifier character (git reset$IFS--hard is "git reset --hard"), as bash does.
denyMain('git${IFS}reset${IFS}--hard${IFS}HEAD');
denyMain('git reset$IFS--hard HEAD');
denyRev('find${IFS}.${IFS}-delete');
denyRev('find .$IFS-delete');

// 6. a leading ! and the keywords if/then/elif/else/do/while/until are stripped like wrappers.
denyMain('! git push --force origin x');
denyMain('if true; then git reset --hard HEAD; fi');
denyMain('while true; do git push -f origin x; done');
denyRev('! find . -delete');
denyRev('then find . -delete');
noneRev('then git status');                                    // a keyword before an allowed command is fine
r = run('PreToolUse', bash('nohup find . -delete', reviewer));
check('reviewer: a real wrapper prefix (nohup) is still refused as a prefix', r.decision === 'deny' && /prefix/i.test(r.reason), JSON.stringify(r.out));

// 7. a leading ( subshell and a { ...; } group are opened (nested too), so the inner command is
//    judged by every rule; a lone } or ) that closes one is not a command of its own.
denyMain('( git push --force origin main )');
denyMain('( (git reset --hard HEAD) )');
denyMain('(cd sub && git reset --hard HEAD)');
denyMain('if (git reset --hard HEAD); then :; fi');
denyRev('(find . -delete)');
denyRev('{ find . -delete; }');
noneMain('(echo hi)');
noneMain('(cd src && git status)');
noneRev('(git status)');
noneRev('{ git log --oneline -3; }');
noneRev('find . \\( -name a -o -name b \\)');
noneRev("git log --format='%h (%an)'");

// 8. quotes, and in bash an unquoted backslash, are removed from each word before matching (as
//    the shell removes them before the command runs); a quoted word with a space stays one word.
denyMain('git reset "--hard" HEAD');
denyMain("git push '--force' origin main");
denyMain('git add "-A"');
denyMain('git "reset" --hard HEAD');
denyMain('"git" reset --hard HEAD');
denyMain('g""it reset --hard HEAD');
denyMain('git reset --ha""rd HEAD');
denyMain('git reset --ha\\rd HEAD');
denyRev('git diff --{output,stat}=x');
noneMain('git add src/a.js');
noneMain('git commit -F msg.txt');
noneMain('git log --grep="--force"');
noneMain('echo "git push --force"');
noneMain('git commit -m "note: never git reset --hard"');      // a quoted message with a space stays one word
denyRev('"find" . -delete');
denyRev('f""ind . -delete');
denyRev("find . '-de'lete");

// 9. a ) glued to the deciding word and followed only by redirections still closes the subshell
//    ("--hard)" is "--hard"); a write redirection after a subshell is still refused for a reviewer.
denyMain('(git reset --hard) 2>&1');
denyMain('(git reset --hard)>/dev/null');
denyMain('(git push --force)|cat');
denyMain('{ git push --force; } 2>&1');
denyMain('git status;(git reset --hard HEAD)');
denyMain('git status&&(git push --force origin main)');
denyRev('(find . -delete) 2>&1');
denyRev('(find . -delete)>/dev/null');
denyRev('(git log --oneline -3) > out.txt');
noneMain('(npm run check:all) 2>&1');
noneMain('git status 2>&1');
noneRev('(git log --oneline -3) 2>&1');
r = run('PreToolUse', pwsh('Remove-Item -Recurse -Force output\\job'));
check('PowerShell: Remove-Item -Recurse -Force output\\job (a backslash is a path separator, not an escape) -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash('git "checkout" -- a.txt'), cwd: gitRepoDir });
check('main: git "checkout" -- a.txt on a dirty tree (quoted subcommand) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', bash('node "cli.js"'));
check('main: node "cli.js" (a plain spend pattern behind quotes) -> ask', r.decision === 'ask', JSON.stringify(r.out));

console.log('-- the lead re-check evidence, verbatim (main session: deny list; reviewer: find -delete)');
for (const c of [
  'git status & git push --force origin main', 'git status &git reset --hard HEAD', 'git status |& git reset --hard HEAD',
  "git push $'--force' origin main", "git reset $'--hard' HEAD", "git add $'-A'", 'git push $"--force" origin main',
  'git push --{force,verbose} origin main', 'git reset --{hard,quiet} HEAD', 'git add -{A,v}',
  'git push --for\\' + NL + 'ce origin main',
  '! git push --force origin main', 'if true; then git reset --hard HEAD; fi',
  '(git reset --hard HEAD)', '{ git reset --hard HEAD; }',
  'git${IFS}push${IFS}--force${IFS}origin',
]) denyMain(c);
for (const c of [
  'find . -name x -del\\' + NL + 'ete', 'find . $"-delete"',
  '! find . -delete', 'find${IFS}.${IFS}-delete', 'git status |& find . -delete', 'if true; then find . -delete; fi',
]) denyRev(c);

console.log('-- quote-aware splitting: a separator inside quotes does not split');
// Each separator below sits inside quotes, so bash runs ONE command; judging the fragments on
// either side of it would hide the refused flag after the quote (or refuse a harmless pattern).
const denyRevFlag = (c, flag) => { const x = run('PreToolUse', bash(c, reviewer)); check(`reviewer: ${c} -> deny naming ${flag}`, x.decision === 'deny' && x.reason.includes(`through ${flag}. `), JSON.stringify(x.out)); };
denyRevFlag('find . -name "a;ls x" -o -delete', '-delete');
denyRevFlag("find . -name 'a|ls x' -o -delete", '-delete');
denyRevFlag('find . -name "a&ls x" -o -delete', '-delete');
denyRevFlag('find . -name "a\\";ls" -o -delete', '-delete');     // an escaped quote inside the quotes
denyRevFlag("find . -name $'a;ls' -o -delete", '-delete');
denyRevFlag('git diff "a;b" --output=x', '--output');
denyRevFlag('git status; find . -delete', '-delete');           // a real separator still splits
denyMain('git reset "x;ls y" --hard');
denyMain('git push "origin;x" --force');
denyMain('git reset HEAD~1 --hard');                            // the reordered hard reset (regex entry)
noneRev('grep -E "a|b" src');
noneRev("git log --format='%h;%s'");
noneRev('grep -n "foo && bar" src');
noneRev('rg "a;b"');
noneRev('git status && git log');
r = run('PreToolUse', bash('git log "$(rm -rf x)"', reviewer));
check('reviewer: git log "$(rm -rf x)" (a substitution inside double quotes) -> deny naming the substitution', r.decision === 'deny' && /command substitution/.test(r.reason), JSON.stringify(r.out));
// a newline inside quotes is part of the quoted word; a heredoc body is still judged line by line.
denyMain('git reset "x' + NL + '" --hard');
noneMain('git commit -m "first line' + NL + 'git push --force is mentioned here"');
denyMain("git commit -F - <<'EOF'" + NL + 'git push --force origin main' + NL + 'EOF');
denyMain("cat <<'EOF'" + NL + "don't" + NL + 'EOF' + NL + 'git push --force origin main');
denyMain("git commit -m \"$(cat <<'EOF'" + NL + "it's done" + NL + 'EOF' + NL + ')" && git push --force origin main');
noneMain("git commit -m \"$(cat <<'EOF'" + NL + "fix: don't split inside quotes" + NL + NL + 'Co-Authored-By: A <a@b>' + NL + 'EOF' + NL + ')"');
denyMain("git status # don't" + NL + 'git push --force origin main');   // a quote inside a comment is not a quote
denyMain('echo a\\ #; git push --force origin main');           // an escaped space does not start a comment
denyMain('git reset ${x:-a;b} --hard');                         // no split inside ${...}
denyMain('echo \\>& git push --force origin main');             // an escaped > is not a redirection
denyRev('git log "a; find . -delete');                          // an unbalanced quote fails closed
denyRev(`find . -name "a"';'"b" -delete`);                      // adjacent quoted pieces make one word
denyMain('# note \\' + NL + 'git push --force origin main');   // a backslash does not continue a comment
denyMain('echo $((1<<2))' + NL + 'git reset "x' + NL + '" --hard');   // arithmetic << is judged both ways
r = run('PreToolUse', pwsh('git reset ‘x;y’ --hard'));
check('PowerShell: typographic quotes around a separator quote it -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', pwsh('git reset "x;ls y" --hard'));
check('PowerShell: git reset "x;ls y" --hard -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', pwsh('Write-Output "C:\\dir\\"; Remove-Item -Recurse -Force output'));
check('PowerShell: a backslash before a closing quote is not an escape -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', pwsh('grep -E "a|b" src', reviewer));
check('PowerShell reviewer: grep -E "a|b" src -> no decision', r.decision === null, JSON.stringify(r.out));
// the deny reason names the matched entry and the config section, nothing project-specific.
r = run('PreToolUse', bash('git reset --hard HEAD'));
check('deny-list reason names the matched entry and the dangerous section', r.decision === 'deny' && r.reason.includes('git reset --hard *') && r.reason.includes('dangerous') && r.reason.includes('.claude/harness.json'), r.reason);
check('deny-list reason carries no project-specific directory advice', !/output\/|sessions\/|checkpoint/.test(r.reason), r.reason);

console.log('-- reviewer: read-only git commands');
for (const c of ['git ls-files', 'git ls-files --eol', 'git check-ignore -v src/x.js']) noneRev(c);

console.log('-- deploy flag after an env or dependency edit');
const sid = 'sess-' + Date.now();
const flagDir = path.join(os.tmpdir(), 'harness-guard');
fs.mkdirSync(flagDir, { recursive: true });
const oldFlag = path.join(flagDir, `check-hooks-old-${Date.now()}.json`);
const freshFlag = path.join(flagDir, `check-hooks-fresh-${Date.now()}.json`);
fs.writeFileSync(oldFlag, '{}'); fs.writeFileSync(freshFlag, '{}');
const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000);
fs.utimesSync(oldFlag, eightDaysAgo, eightDaysAgo);
r = run('PreToolUse', { ...bash('npm run deploy:code'), session_id: sid });
check('deploy:code with no prior env/deps edit -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PostToolUse', { ...edit(path.join(proj, 'package.json')), session_id: sid, tool_response: {} });
check('PostToolUse Edit package.json exits 0 with no decision', r.status === 0 && r.decision === null, JSON.stringify(r));
check('a flag file older than 7 days is removed when a new flag is written', !fs.existsSync(oldFlag), oldFlag);
check('a fresh flag file survives the pruning', fs.existsSync(freshFlag), freshFlag);
r = run('PreToolUse', { ...bash('npm run deploy:code'), session_id: sid });
check('deploy:code after package.json edit in the same session -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', { ...bash('npm run deploy:code'), session_id: sid + '-other' });
check('deploy:code in a different session -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', { ...bash('npm run deploy:full'), session_id: sid });
check('deploy:full (the right recipe) -> no decision', r.decision === null, JSON.stringify(r.out));

console.log('-- protected paths');
r = run('PreToolUse', edit(path.join(proj, '.env')));
check('Edit .env -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', edit(path.join(proj, 'sub', 'dir', '.env')));
check('Edit sub/dir/.env (bare filename matches at any depth) -> ask', r.decision === 'ask', JSON.stringify(r.out));
r = run('PreToolUse', edit(path.join(proj, 'assets', 'generated', 'sample.json')));
check('Edit assets/generated/sample.json -> deny', r.decision === 'deny', JSON.stringify(r.out));
r = run('PreToolUse', edit(path.join(proj, 'src', 'foo.js'), 'Write'));
check('Write src/foo.js -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', edit(path.join(proj, '.github', 'workflows', 'ci.yml')));
check('Edit .github/workflows/ci.yml -> ask', r.decision === 'ask', JSON.stringify(r.out));

console.log('-- stop: uncommitted tracked changes with no ledger row for HEAD');
const stopRepo = path.join(tmpRoot, 'stop-repo');
const sg = gitRepo(stopRepo);
fs.mkdirSync(path.join(stopRepo, '.claude'), { recursive: true });
const writeStopConfig = (extra = {}) => fs.writeFileSync(path.join(stopRepo, '.claude', 'harness.json'), JSON.stringify({ ...fixtureConfig, ...extra }));
writeStopConfig();
const headSha = sg('rev-parse', '--short=8', 'HEAD').stdout.trim();
const stop = (extra = {}) => run('Stop', { stop_hook_active: false, ...extra }, {}, stopRepo);
const message = (res) => (typeof res.out.systemMessage === 'string' ? res.out.systemMessage : '');
r = stop();
check('Stop on a clean tree -> {}', r.status === 0 && !message(r) && r.decision === null, JSON.stringify(r));
fs.writeFileSync(path.join(stopRepo, 'a.txt'), 'two\n');
r = stop();
check('Stop with a modified tracked file and no ledger -> systemMessage', r.status === 0 && /^HARNESS:/.test(message(r)), JSON.stringify(r));
check('Stop message names the HEAD short sha', message(r).includes(headSha), message(r));
check('Stop message says no quick check is configured', /no quick check configured/.test(message(r)), message(r));
check('Stop never blocks (no decision, no permissionDecision)', r.out.decision === undefined && r.decision === null, JSON.stringify(r.out));
r = stop({ stop_hook_active: true });
check('Stop with stop_hook_active -> {}', r.status === 0 && !message(r), JSON.stringify(r));
writeStopConfig({ checks: { quick: 'node --version' } });
r = stop();
check('Stop with checks.quick configured -> message carries the quick result', /quick check "node --version" exited 0/.test(message(r)), message(r));
check('Stop quick result carries the last output lines', /v\d+\.\d+\.\d+/.test(message(r)), message(r));
writeStopConfig({ checks: { quick: 'node -e "process.exit(3)"' } });
r = stop();
check('Stop with a red quick check -> message says it exited 3', /exited 3/.test(message(r)), message(r));
writeStopConfig();
fs.mkdirSync(path.join(stopRepo, 'docs', 'sdd', 'feat-a'), { recursive: true });
fs.writeFileSync(path.join(stopRepo, 'docs', 'sdd', 'feat-a', 'STATUS.md'), `| change | ${headSha} | npm run check | checks-only | - |\n`);
r = stop();
check('Stop with a STATUS.md row naming HEAD -> {}', r.status === 0 && !message(r), JSON.stringify(r));
fs.rmSync(path.join(stopRepo, 'docs', 'sdd', 'feat-a'), { recursive: true, force: true });
fs.writeFileSync(path.join(stopRepo, 'docs', 'sdd', 'VERIFICATION.md'), `| date | main | ${headSha} | suite | PASS |\n`);
r = stop();
check('Stop with a VERIFICATION.md row naming HEAD -> {}', r.status === 0 && !message(r), JSON.stringify(r));
fs.rmSync(path.join(stopRepo, 'docs'), { recursive: true, force: true });
writeStopConfig({ artifacts: { root: 'ledgers' } });
fs.mkdirSync(path.join(stopRepo, 'ledgers', 'x'), { recursive: true });
fs.writeFileSync(path.join(stopRepo, 'ledgers', 'x', 'STATUS.md'), `| change | ${headSha} | s | checks-only | - |\n`);
r = stop();
check('Stop honours artifacts.root for the ledger search -> {}', r.status === 0 && !message(r), JSON.stringify(r));

console.log('-- robustness');
const empty = path.join(tmpRoot, 'empty'); fs.mkdirSync(empty);
r = run('PreToolUse', bash('node cli.js'), {}, empty);
check('no harness.json -> exit 0 and no decision', r.status === 0 && r.decision === null, JSON.stringify(r));
r = run('PreToolUse', bash('node cli.js'), { HARNESS_HOOKS: 'off' });
check('HARNESS_HOOKS=off -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('PreToolUse', '{not json');
check('unparsable stdin -> exit 0 and no decision', r.status === 0 && r.decision === null, JSON.stringify(r));
r = run('PreToolUse', bash('node cli.js', { tool_name: 'Read', tool_input: { file_path: 'x' } }));
check('unrelated tool -> no decision', r.decision === null, JSON.stringify(r.out));
r = run('Stop', '{not json');
check('Stop with unparsable stdin -> exit 0 and {}', r.status === 0 && !message(r), JSON.stringify(r));
r = run('Stop', { stop_hook_active: false }, {}, empty);
check('Stop with no harness.json -> exit 0 and {}', r.status === 0 && !message(r), JSON.stringify(r));

console.log('-- live config');
const neutralPath = path.join(repoRoot, '.harness', 'config.json');
const livePath = fs.existsSync(neutralPath) ? neutralPath : path.join(repoRoot, '.claude', 'harness.json');
let live = null; try { live = JSON.parse(fs.readFileSync(livePath, 'utf8')); } catch {}
check(path.relative(repoRoot, livePath).split(path.sep).join('/') + ' parses', !!live, livePath);
check('live config has spend.patterns, dangerous.deny, protected_paths, deploy, reviewer', !!(live && live.spend && Array.isArray(live.spend.patterns) && live.dangerous && Array.isArray(live.dangerous.deny) && live.protected_paths && live.deploy && live.reviewer));

try { fs.rmSync(tmpRoot, { recursive: true, force: true }); } catch {}
for (const f of [oldFlag, freshFlag, path.join(flagDir, `${sid}.json`)]) { try { fs.rmSync(f, { force: true }); } catch {} }
console.log(`\n${pass}/${pass + fail} checks passed`);
process.exit(fail ? 1 : 0);
