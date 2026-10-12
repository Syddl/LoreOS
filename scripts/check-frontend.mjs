// check-frontend: the frontend typechecks under strict TypeScript, its vitest suite passes, and the build
// writes frontend/dist/index.html, the page FastAPI serves at /.
//
// Does NOT exercise: visual layout or a real browser (a manual row with a screenshot), or the api behind
// the screens (the screens' tests mock fetch).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');

if (!fs.existsSync(path.join(frontend, 'node_modules'))) {
  console.error('check:frontend: frontend/node_modules is missing; run npm ci --prefix frontend');
  process.exit(1);
}
for (const script of ['typecheck', 'test', 'build']) {
  // npm is npm.cmd on Windows, which spawnSync runs only through a shell.
  const r = spawnSync('npm', ['--prefix', 'frontend', 'run', script], { cwd: root, stdio: 'inherit', shell: process.platform === 'win32' });
  if (r.status !== 0) {
    console.error(`check:frontend: npm run ${script} failed`);
    process.exit(r.status ?? 1);
  }
}
if (!fs.existsSync(path.join(frontend, 'dist', 'index.html'))) {
  console.error('check:frontend: the build wrote no frontend/dist/index.html');
  process.exit(1);
}
console.log('check:frontend: typecheck, tests and build pass');
