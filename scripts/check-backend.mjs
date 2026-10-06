// check-backend: runs the backend tests (backend/tests) against the testdb container.
// Fails with the command to start testdb when it is not running; never skips the database tests.
import { spawnSync } from 'node:child_process';

const r = spawnSync('uv', ['--directory', 'backend', 'run', 'python', '-m', 'pytest'], { stdio: 'inherit' });
if (r.error) console.error(`check:backend: cannot run uv (${r.error.code}); install it from https://docs.astral.sh/uv/`);
process.exit(r.status ?? 1);
