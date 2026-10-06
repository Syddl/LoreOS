// check-licenses: fails when an installed backend package declares a copyleft license
// (backend/check_licenses.py holds the rule and its one exception).
import { spawnSync } from 'node:child_process';

const r = spawnSync('uv', ['--directory', 'backend', 'run', 'python', 'check_licenses.py'], { stdio: 'inherit' });
if (r.error) console.error(`check:licenses: cannot run uv (${r.error.code}); install it from https://docs.astral.sh/uv/`);
process.exit(r.status ?? 1);
