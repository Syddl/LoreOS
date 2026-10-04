// Offline contract checks for the installed Codex/Gemini guards. No agent/model invocation.
// This checks fixture policy, not runtime discovery, trust, or OS sandbox enforcement.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'harness-contract-'));
let checks = 0;
try {
  fs.mkdirSync(path.join(fixture, '.harness'));
  fs.writeFileSync(path.join(fixture, '.harness/config.json'), JSON.stringify({
    version: 1, project: { name: 'offline fixture' },
    dangerous: { deny: ['git reset --hard *'] },
    spend: { patterns: ['metered-run'], exempt: ['--dry-run'] },
    protected_paths: { ask: ['.env'], deny: ['secret.json'] },
  }));
  for (const agent of ['codex', 'gemini']) {
    const guard = path.join(project, '.' + agent, 'hooks/guard.mjs');
    if (!fs.existsSync(guard)) {
      const settings = path.join(project, agent === 'codex' ? '.codex/hooks.json' : '.gemini/settings.json');
      const registered = fs.existsSync(settings) && fs.readFileSync(settings, 'utf8').includes('hooks/guard.mjs');
      assert.ok(!registered, agent + ' registered guard is missing: ' + guard);
      continue;
    }
    const event = agent === 'codex' ? 'PreToolUse' : 'BeforeTool';
    const invoke = payload => {
      const result = spawnSync(process.execPath, [guard, event, fixture], {
        cwd: fixture, encoding: 'utf8', windowsHide: true,
        input: typeof payload === 'string' ? payload : JSON.stringify({ cwd: fixture, session_id: 'offline', ...payload }),
      });
      assert.equal(result.status, 0, result.stderr);
      return JSON.parse(result.stdout);
    };
    const decision = output => output.hookSpecificOutput?.permissionDecision || output.decision || 'allow';
    for (const [command, expected] of [['git status','allow'], ['git reset --hard','deny'], ['metered-run','deny'], ['metered-run --dry-run','allow']]) {
      const output = invoke({ tool_name: agent === 'codex' ? 'Bash' : 'run_shell_command', tool_input: { command } });
      assert.equal(decision(output), expected, agent + ': ' + command);
      if (command === 'metered-run') assert.match(output.hookSpecificOutput?.permissionDecisionReason || output.reason, /separate supported approval mechanism/);
      checks++;
    }
    for (const file of ['.env', 'secret.json']) {
      const payload = agent === 'codex'
        ? { tool_name: 'apply_patch', tool_input: { command: '*** Begin Patch\n*** Add File: ' + file + '\n+test\n*** End Patch' } }
        : { tool_name: 'write_file', tool_input: { file_path: file, content: 'test' } };
      assert.equal(decision(invoke(payload)), 'deny', agent + ': ' + file);
      checks++;
    }
    assert.equal(decision(invoke('{bad')), 'deny', agent + ': malformed JSON');
    checks++;
  }
  assert.ok(checks, 'No installed Codex or Gemini guard found');
  console.log(checks + '/' + checks + ' installed adapter checks passed (offline)');
} finally {
  fs.rmSync(fixture, { recursive: true, force: true });
}
