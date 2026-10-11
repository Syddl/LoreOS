// check-compose: the image builds, `docker compose up` migrates and starts the api and the worker, the api
// answers /api/health and serves the UI at / and /login, and no .env reaches the image. It runs under its
// own project (loreos-check) with scripts/compose-check.yml: its own database, a fake OpenAI key and an
// unroutable base URL, asserted from the resolved config before anything starts. In CI and on its own,
// not in check:all: it builds the image every run.
//
// Does NOT exercise: a real OpenAI call, Supabase, a browser, or a document reaching the worker.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const compose = ['compose', '-p', 'loreos-check', '-f', 'docker-compose.yml', '-f', 'scripts/compose-check.yml',
  '--env-file', 'scripts/compose-check.env'];
const API = 'http://127.0.0.1:18000';
const CHECK_ENV = { OPENAI_API_KEY: 'sk-check-not-a-real-key', OPENAI_BASE_URL: 'http://0.0.0.0:9/v1' };

function docker(args, { capture = false } = {}) {
  const r = spawnSync('docker', [...compose, ...args], { cwd: root, encoding: 'utf8', stdio: capture ? 'pipe' : 'inherit' });
  if (r.error) throw new Error(`cannot run docker (${r.error.code}); install Docker and start it`);
  return r;
}

function fail(message) {
  throw new Error(message);
}

async function get(urlPath) {
  const res = await fetch(API + urlPath, { headers: { Host: '127.0.0.1' } });
  return { status: res.status, body: await res.text() };
}

async function main() {
  // 0. The resolved config, before anything starts: no service may see .env's database or key.
  const config = docker(['config', '--format', 'json'], { capture: true });
  if (config.status !== 0) fail(`docker compose config failed:\n${config.stderr}`);
  const services = JSON.parse(config.stdout).services;
  for (const name of ['migrate', 'api', 'worker']) {
    const env = services[name]?.environment ?? {};
    if (!String(env.DATABASE_URL ?? '').includes('@checkdb:')) fail(`${name} would use DATABASE_URL ${env.DATABASE_URL ?? '(unset)'}, not checkdb`);
    for (const [key, want] of Object.entries(CHECK_ENV)) {
      if (env[key] !== want) fail(`${name} would use ${key}=${env[key] ?? '(unset)'}, not the check's own value`);
    }
  }
  console.log('  ok   the resolved config points every service at checkdb, a fake key and an unroutable OpenAI URL');

  // 1. Build, migrate, start; --wait returns once the api is healthy.
  if (docker(['up', '--build', '--wait', '--wait-timeout', '600']).status !== 0) fail('docker compose up --build --wait failed');

  // 2 and 3. Health and the UI.
  const health = await get('/api/health');
  if (health.status !== 200) fail(`/api/health returned ${health.status}: ${health.body}`);
  for (const page of ['/', '/login']) {
    const { status, body } = await get(page);
    if (status !== 200 || !body.includes('<div id="root">')) fail(`${page} returned ${status} without the app's #root`);
  }
  console.log('  ok   /api/health is 200, and / and /login serve the app');

  // 4 and 5. No .env in the build context or the image.
  const ignored = fs.readFileSync(path.join(root, '.dockerignore'), 'utf8').split(/\r?\n/).map((line) => line.trim());
  if (!ignored.includes('.env')) fail('.dockerignore does not list .env');
  const probe = "import pathlib, sys; found = sorted(str(p) for p in pathlib.Path('/app').rglob('.env*')); print(found); sys.exit(1 if found else 0)";
  const inImage = docker(['run', '--rm', '--no-deps', '--entrypoint', 'python', 'api', '-c', probe], { capture: true });
  if (inImage.status !== 0) fail(`the image holds an env file: ${inImage.stdout.trim()} ${inImage.stderr.trim()}`);
  console.log('  ok   no .env in the build context or under /app in the image');

  // 6. The worker is running, not restarting.
  const ps = docker(['ps', '--format', 'json', 'worker'], { capture: true });
  const workers = ps.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  if (workers.length !== 1 || workers[0].State !== 'running') fail(`the worker is not running: ${ps.stdout.trim() || '(no container)'}`);
  console.log('  ok   the worker is running');

  // 7. The image size, for the STATUS record against free disk.
  const size = spawnSync('docker', ['image', 'inspect', 'loreos-check:local', '--format', '{{.Size}}'], { encoding: 'utf8' });
  console.log(`  info image loreos-check:local is ${(Number(size.stdout.trim()) / 1e6).toFixed(0)} MB`);
}

let code = 0;
try {
  await main();
  console.log('\ncheck:compose: the image builds, the stack starts healthy and serves the UI');
} catch (e) {
  console.error(`\ncheck:compose: ${e.message}`);
  docker(['logs', '--tail', '40']);
  code = 1;
} finally {
  // 8. Always stop. No -v: checkdb runs on tmpfs, so nothing persists.
  docker(['down', '--remove-orphans']);
}
process.exit(code);
