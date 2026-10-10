import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
const script = readFileSync(new URL('../deploy/erp-optimization-20261011-release.sh', import.meta.url), 'utf8');
const bash = process.env.BASH_EXECUTABLE || 'bash';
test('optimization release Bash parses and keeps private/public masks isolated', () => {
  const syntax = spawnSync(bash, ['-n'], {input:script,encoding:'utf8'});
  assert.ifError(syntax.error); assert.equal(syntax.status,0,syntax.stderr);
  const prefix = script.split('[[ "$EUID" == 0 ]]')[0];
  const masks = spawnSync(bash, ['-c', prefix + '\n[[ "$(runtime_command umask)" == 0022 ]]\n[[ "$(umask)" == 0077 ]]'], {encoding:'utf8'});
  assert.ifError(masks.error); assert.equal(masks.status,0,masks.stderr);
});
test('optimization release guards history, schema and narrowly repairs only strategy rights', () => {
  assert.match(script,/git merge-base --is-ancestor/);
  assert.match(script,/backend\/apps\/erp\/migrations backend\/requirements.txt/);
  assert.match(script,/changed=1\nsystemctl stop/);
  assert.ok(script.indexOf('pg_restore --list') < script.indexOf("SELECT format('GRANT"));
  assert.match(script,/ARRAY\['SELECT','INSERT','UPDATE','DELETE'\]/);
  assert.match(script,/WHERE NOT has_table_privilege/);
  assert.doesNotMatch(script,/ALTER.*OWNER|GRANT ALL|--fake|chmod.*-R|manage.py migrate .*--noinput/);
  assert.match(script,/check_erp_optimization_release/);
  assert.match(script,/runtime_command git -C "\$app" switch --detach "\$old"/);
});
test('optimization rollback preserves failure code and does not reverse database', () => {
  const prefix = script.split('[[ "$EUID" == 0 ]]')[0];
  const mock = '\nchanged=1; old=reviewed-old; backup=private-backup\ncd(){ return 0; }; git(){ return 0; }; node(){ return 0; }; systemctl(){ return 0; }; readable(){ return 0; }; health(){ return 0; }; verify_assets(){ return 0; }; runtime_command(){ "$@"; }\nset +e\n(exit 7)\nrollback';
  const result = spawnSync(bash, ['-c', prefix + mock], {encoding:'utf8'});
  assert.ifError(result.error); assert.equal(result.status,7,result.stderr);
  assert.match(result.stdout,/CODE ROLLBACK VERIFIED/);
  assert.match(result.stdout,/no database restore or reverse migration/);
});
