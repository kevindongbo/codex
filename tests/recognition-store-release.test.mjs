import assert from 'node:assert/strict';
import {chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {delimiter, dirname, join} from 'node:path';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
const script = readFileSync(new URL('../deploy/recognition-store-profit-release.sh',import.meta.url),'utf8').replaceAll('\r\n', '\n');
const bash = process.env.BASH_EXECUTABLE || 'bash';
const bashEnvironment = {...process.env, PATH: `${dirname(bash)}${delimiter}${process.env.PATH || ''}`};
const prefix = script.split('[[ "$EUID" == 0 ]]')[0];
test('repair release validates exact history and preserves private data', () => {
  const parsed = spawnSync(bash,['-n'],{input:script,encoding:'utf8'});
  assert.ifError(parsed.error); assert.equal(parsed.status,0,parsed.stderr);
  assert.match(script,/codex\/fix-recognition-store-profit-20261017/);
  assert.match(script,/git merge-base --is-ancestor/);
  assert.match(script,/backend\/apps\/erp\/migrations backend\/requirements.txt/);
  assert.match(script,/pg_restore --list/);
  assert.doesNotMatch(script,/GRANT|ALTER.*OWNER|reset --hard|--fake|pg_restore --dbname/);
  const masks = spawnSync(bash,['-c',prefix+'\n[[ "$(runtime_command umask)" == 0022 ]]\n[[ "$(umask)" == 0077 ]]'],{encoding:'utf8'});
  assert.ifError(masks.error); assert.equal(masks.status,0,masks.stderr);
});
const oldSha = 'a'.repeat(40);
const targetSha = 'b'.repeat(40);
const assets = ['index.html', 'app.js', 'team.js', 'styles.css', 'profit-calculator.js', 'scheduling.js', 'scheduling.css'];
const shellQuote = value => `'${value.replaceAll("'", "'\\''")}'`;
const shellPath = value => value.replaceAll('\\', '/');
const doubles = readFileSync(new URL('./helpers/repair-release-harness.sh', import.meta.url), 'utf8').replaceAll('\r\n', '\n');

// Execute the complete release body against private temporary files. Privileged,
// network and application commands are fail-closed doubles; no real Git, DB,
// systemd, application Python or remote requests can be invoked by these tests.
function simulateRelease(scenario) {
  const root = mkdtempSync(join(tmpdir(), 'recognition-release-test-'));
  try {
    const app = join(root, 'app');
    const bin = join(root, 'bin');
    const state = join(root, 'state');
    const backups = join(root, 'backups');
    for (const directory of [join(app, '.git'), join(app, 'backend'), join(app, 'dist/server'), bin, state, backups, join(root, 'originals')]) mkdirSync(directory, {recursive: true});
    writeFileSync(join(state, 'sha'), oldSha);
    writeFileSync(join(state, 'events'), '');
    for (const service of ['dongbo-erp.service', 'dongbo-timetable-worker.service']) writeFileSync(join(state, service), 'active');
    for (const asset of assets) writeFileSync(join(app, asset), `fixture release:${oldSha} asset:${asset}\n`);
    writeFileSync(join(app, 'backend/manage.py'), '# This fixture must never be executed.\n');
    writeFileSync(join(app, 'dist/server/index.js'), 'initial fixture build\n');
    const protectedFiles = new Map([
      [join(app, '.env'), 'HARNESS_CONFIGURATION_PRESERVED=yes\n'],
      [join(root, 'scheduling.env'), 'SCHEDULING_ENABLED=true\n'],
      [join(root, 'database.fixture'), 'original database rows\n'],
      [join(root, 'originals/timetable.fixture'), 'original image bytes\n'],
    ]);
    for (const [path, contents] of protectedFiles) writeFileSync(path, contents);
    const python = join(bin, 'python');
    writeFileSync(python, '#!/usr/bin/env sh\nset -eu\nprintf \'python %s\\n\' "$*" >> "$HARNESS_STATE/events"\nif [ "${1:-}" = -c ]; then\n  payload=\'\'\n  IFS= read -r payload || true\n  [ "$payload" = \'{"status":"ok","database":"ok"}\' ]\nfi\n');
    chmodSync(python, 0o755);
    let isolated = script
      .replace('readonly app=/opt/dongbo/app', `readonly app=${shellQuote(shellPath(app))}`)
      .replace('readonly python=/opt/dongbo/venv/bin/python', `readonly python=${shellQuote(shellPath(python))}`)
      .replaceAll('/opt/dongbo/backups', shellPath(backups))
      .replaceAll('/run/lock/dongbo-erp-release.lock', `${shellPath(root)}/release.lock`)
      .replaceAll('/etc/dongbo/scheduling.env', `${shellPath(root)}/scheduling.env`)
      .replace('[[ "$EUID" == 0 ]]', '[[ "$HARNESS_ISOLATED" == yes ]]');
    assert.doesNotMatch(isolated, /\/opt\/dongbo|\/etc\/dongbo|\/run\/lock\/dongbo/, 'rewrite every production path before execution');
    const fixtureEnvironment = Object.entries({HARNESS_ISOLATED: 'yes', HARNESS_ROOT: shellPath(root), HARNESS_APP: shellPath(app), HARNESS_STATE: shellPath(state), HARNESS_SCENARIO: scenario, HARNESS_OLD: oldSha, HARNESS_TARGET: targetSha, HARNESS_NODE: shellPath(process.execPath)})
      .map(([key, value]) => `export ${key}=${shellQuote(value)}`).join('\n');
    isolated = `${fixtureEnvironment}\n${doubles}\n${isolated}`;
    const result = spawnSync(bash, ['-s', '--', targetSha], {input: isolated, encoding: 'utf8', timeout: 20000, env: bashEnvironment});
    assert.ifError(result.error);
    assert.equal(result.signal, null, result.stderr);
    const events = readFileSync(join(state, 'events'), 'utf8');
    assert.ok(events, `release fixture never reached command doubles: ${result.stderr}\n${result.stdout}`);
    for (const [path, contents] of protectedFiles) assert.equal(readFileSync(path, 'utf8'), contents, `preserve ${path}`);
    assert.doesNotMatch(events, /pg_restore --dbname|^python backend\/manage\.py migrate(?! --check)|reset --hard|pip install/m, 'never restore/modify database or install dependencies');
    for (const service of ['dongbo-erp.service', 'dongbo-timetable-worker.service']) assert.equal(readFileSync(join(state, service), 'utf8'), 'active', `restore/start ${service}`);
    const directories = readdirSync(backups);
    if (scenario.startsWith('env-')) {
      assert.equal(directories.length, 0, 'environment preflight stops before creating a backup');
      assert.doesNotMatch(events, /systemctl (stop|restart)|git(?: -C [^\n]+)? switch|pg_dump|node scripts\/build-site/, 'preflight must leave code and services untouched');
    } else {
      assert.equal(directories.length, 1, `retain one private backup; status=${result.status}\n${result.stderr}\n${events}`);
      const backup = join(backups, directories[0]);
      assert.equal(readFileSync(join(backup, 'previous-sha.txt'), 'utf8').trim(), oldSha);
      assert.match(readFileSync(join(backup, 'previous-code.tar'), 'utf8'), new RegExp(oldSha));
    }
    return {...result, events, sha: readFileSync(join(state, 'sha'), 'utf8')};
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
}

test('complete repair release builds, checks, restarts and verifies the selected SHA', () => {
  const result = simulateRelease('success');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.sha, targetSha);
  assert.match(result.stdout, /VERIFIED AT LOCAL NGINX ORIGIN/);
  assert.match(result.stdout, /Live vision and signed-in public workflows still require acceptance/);
  assert.match(result.events, /python backend\/manage.py check_recognition_store_release/);
  assert.match(result.events, /pg_restore --list/);
  assert.match(result.events, /systemctl restart dongbo-erp.service dongbo-timetable-worker.service/);
  assert.doesNotMatch(result.stdout, /ROLLBACK/);
});

for (const [scenario, expectedStatus] of [['backup', 47], ['switch', 53], ['build', 61], ['restart', 57], ['health', 1], ['assets', 1]]) {
  test(`complete repair release restores old SHA and both services after ${scenario} failure`, () => {
    const result = simulateRelease(scenario);
    assert.equal(result.status, expectedStatus, result.stderr);
    assert.equal(result.sha, oldSha);
    assert.match(result.stdout, new RegExp(`CODE ROLLBACK VERIFIED: ${oldSha}`));
    assert.match(result.stdout, /no database restore or reverse migration/);
    assert.match(result.events, new RegExp(`git -C .* switch --detach ${oldSha}`));
    assert.match(result.events, /systemctl restart dongbo-erp.service dongbo-timetable-worker.service/);
    assert.doesNotMatch(result.stdout, /VERIFIED AT LOCAL NGINX ORIGIN/);
  });
}

for (const [scenario, message] of [['env-app', /Unexpected worker environment configuration/], ['env-scheduling', /Worker scheduling configuration differs/]]) {
  test(`complete repair release rejects ${scenario} preflight without stopping services`, () => {
    const result = simulateRelease(scenario);
    assert.equal(result.status, 1, result.stderr);
    assert.equal(result.sha, oldSha);
    assert.match(result.stderr, message);
    assert.doesNotMatch(result.stdout, /VERIFIED|ROLLBACK/);
  });
}
