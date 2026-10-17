import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
const script = readFileSync(new URL('../deploy/recognition-store-profit-release.sh',import.meta.url),'utf8');
const bash = process.env.BASH_EXECUTABLE || 'bash';
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
test('repair release rollback returns original error and verifies both services', () => {
  const mocks = '\nchanged=1; old=previous; backup=private; runtime_command(){ return 0; }; cd(){ return 0; }; readable(){ return 0; }; systemctl(){ return 0; }; health(){ return 0; }; verify_assets(){ return 0; }\nset +e\n(exit 7)\nrollback';
  const result = spawnSync(bash,['-c',prefix+mocks],{encoding:'utf8'});
  assert.ifError(result.error); assert.equal(result.status,7,result.stderr);
  assert.match(result.stdout,/CODE ROLLBACK VERIFIED/);
  assert.match(result.stdout,/no database restore or reverse migration/);
});
