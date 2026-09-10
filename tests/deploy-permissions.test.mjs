import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const script = readFileSync(new URL('../deploy/erp-usability-release.sh', import.meta.url), 'utf8');
test('release and rollback both isolate public code creation from private backup umask', () => {
  assert.match(script, /runtime_command\(\) \{ \(umask 022; "\$@"\); \}/);
  assert.equal((script.match(/runtime_command git .*switch --detach/g) || []).length, 2);
  assert.equal((script.match(/runtime_command node scripts\/build-site\.mjs/g) || []).length, 2);
  assert.match(script, /runtime_command node scripts\/build-site\.mjs\nverify_runtime_readable/);
  assert.match(script, /verify_runtime_readable &&/);
  assert.match(script, /runuser -u "\$service_user" -- test -r/);
  assert.doesNotMatch(script, /chmod.*(?:\.env| -R)/);
});
test('Bash syntax and actual subshell mask isolation', () => {
  const bash = process.env.BASH_EXECUTABLE || 'bash';
  const syntax = spawnSync(bash, ['-n'], { input: script, encoding: 'utf8' });
  assert.ifError(syntax.error);
  assert.equal(syntax.status, 0, syntax.stderr);
  // Only load constants/functions. Never execute production preflight or writes.
  const prefix = script.split('[[ "$EUID" == 0 ]]')[0];
  const result = spawnSync(bash, ['-c', prefix + '\n[[ "$(runtime_command umask)" == 0022 ]]\n[[ "$(umask)" == 0077 ]]\nprintf "mask-isolation-ok\\n"'], { encoding: 'utf8' });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /mask-isolation-ok/);
});
