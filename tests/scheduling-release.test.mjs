import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const script = readFileSync(new URL('../deploy/course-scheduling-release.sh', import.meta.url), 'utf8');
const bash = process.env.BASH_EXECUTABLE || 'bash';
const prefix = script.split('[[ "$EUID" == 0 ]]')[0];
function execute(input) {
  const result = spawnSync(bash, ['-c', input], {encoding:'utf8'});
  assert.ifError(result.error);
  return result;
}
test('scheduling release parses in Bash and uses isolated public runtime masks', () => {
  const parsed = spawnSync(bash, ['-n'], {input:script,encoding:'utf8'});
  assert.ifError(parsed.error); assert.equal(parsed.status, 0, parsed.stderr);
  const result = execute(prefix + '\n[[ "$(runtime_command umask)" == 0022 ]]\n[[ "$(umask)" == 0077 ]]');
  assert.equal(result.status, 0, result.stderr);
});
test('release guards exact repository, ancestor, migration and private storage before migration', () => {
  assert.match(script, /git merge-base --is-ancestor/);
  assert.match(script, /Remote SHA changed/);
  assert.match(script, /Unexpected migration change/);
  assert.match(script, /Existing private storage uses another path/);
  assert.match(script, /readonly private_root=\/var\/lib\/dongbo-timetables/);
  assert.match(script, /EnvironmentFile=\$app\/\.env\nEnvironmentFile=\$env_file/);
  assert.match(script, /check_scheduling_release --expect-migrated/);
  assert.ok(script.indexOf('pg_restore --list') < script.indexOf('migrate erp 0038'));
  assert.doesNotMatch(script, /reset --hard|--fake|migrate erp 0037|pg_restore --dbname|chmod -R/);
  assert.doesNotMatch(script, />\s*"\$app\/\.env"/);
});
test('rollback retains original failure and checks service/assets without reversing data', () => {
  const result = execute(prefix + `
changed=1; config_changed=1; old=previous; backup=test-backup
restore_config() { printf 'restore-config\\n'; }
systemctl() { printf 'service-action:%s\\n' "$1"; }
runtime_command() { return 0; }
health() { return 0; }
verify_assets() { return 0; }
# Substitute only the rollback subshell cwd; never access a production path.
${script.slice(script.indexOf('rollback() {'),script.indexOf('\n[[ "$EUID" == 0 ]]')).replace('(cd "$app" && runtime_command node scripts/build-site.mjs)', '(runtime_command node scripts/build-site.mjs)')}
set +e
(exit 7)
rollback
`);
  assert.equal(result.status, 7, result.stderr);
  assert.match(result.stdout, /CODE ROLLBACK VERIFIED: previous/);
  assert.match(result.stdout, /no reverse migration or database restore/);
});
