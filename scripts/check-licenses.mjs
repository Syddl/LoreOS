// check-licenses: fails when an installed backend package, or a package in the frontend's production tree,
// declares a copyleft license other than MPL-2.0, or none (backend/check_licenses.py holds the rule; decision 0007).
//
// Does NOT exercise: frontend devDependencies (build-time only, so lightningcss is not listed here), or whether
// an MPL-2.0 dependency is in fact unmodified.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

// backend/ and frontend/ resolve against the repository root, whatever directory this runs from.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = ['--directory', 'backend', 'run', 'python', 'check_licenses.py'];

const backend = spawnSync('uv', python, { cwd: root, stdio: 'inherit' });
if (backend.error) console.error(`check:licenses: cannot run uv (${backend.error.code}); install it from https://docs.astral.sh/uv/`);

// npm is npm.cmd on Windows, which spawnSync runs only through a shell.
const npmLs = ['ls', '--omit=dev', '--all', '--json', '--long', '--prefix', 'frontend'];
const ls = spawnSync('npm', npmLs, {
  cwd: root,
  stdio: ['ignore', 'pipe', 'inherit'],
  shell: process.platform === 'win32',
  maxBuffer: 256 * 1024 * 1024,
});
let frontend = 1;
if (ls.status !== 0) {
  console.error('check:licenses: npm ls failed on the frontend tree; run npm ci --prefix frontend');
} else {
  // The tree goes in as bytes; check_licenses.py reads stdin as bytes too.
  const r = spawnSync('uv', [...python, '--npm-tree', '-'], { cwd: root, input: ls.stdout, stdio: ['pipe', 'inherit', 'inherit'] });
  frontend = r.status ?? 1;
}
process.exit(backend.status === 0 && frontend === 0 ? 0 : 1);
