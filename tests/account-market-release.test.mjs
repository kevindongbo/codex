import assert from 'node:assert/strict';
import {chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {delimiter, dirname, join} from 'node:path';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
const script = readFileSync(new URL('../deploy/account-market-release.sh',import.meta.url),'utf8').replaceAll('\r\n','\n');
const bash = process.env.BASH_EXECUTABLE || 'bash';
const env = {...process.env,PATH:dirname(bash)+delimiter+process.env.PATH};
const quote = v => `'${v.replaceAll("'", "'\\''")}'`;
const path = v => v.replaceAll('\\','/');
const oldSha = 'a'.repeat(40), target = 'b'.repeat(40);
const assets = ['index.html','app.js','team.js','styles.css','profit-calculator.js','market-profit.js','scheduling.js','scheduling.css'];
let doubles = readFileSync(new URL('./helpers/repair-release-harness.sh',import.meta.url),'utf8').replaceAll('\r\n','\n')
  .replaceAll('profit-calculator.js scheduling.js','profit-calculator.js market-profit.js scheduling.js')
  .replaceAll('profit-calculator.js|scheduling.js','profit-calculator.js|market-profit.js|scheduling.js')
  .replace('    archive)', "    show) printf '# fixture helper\\n' ;;\n    archive)")
  .replace('    *) return 96 ;;', `    env)
      shift
      while [[ "$1" == *=* ]]; do shift; done
      if "$@"; then return 0; else return $?; fi ;;
    *) return 96 ;;`);

function simulate(scenario) {
  const root = mkdtempSync(join(tmpdir(),'market-release-test-'));
  try {
    for (const dir of ['app/.git','app/backend','app/dist/server','bin','state','backups']) mkdirSync(join(root,dir),{recursive:true});
    for (const asset of assets) writeFileSync(join(root,'app',asset),`fixture release:${oldSha} asset:${asset}\n`);
    for (const unit of ['dongbo-erp.service','dongbo-timetable-worker.service']) writeFileSync(join(root,'state',unit),'active');
    writeFileSync(join(root,'state/sha'),oldSha); writeFileSync(join(root,'state/events'),'');
    writeFileSync(join(root,'app/backend/manage.py'),'fixture'); writeFileSync(join(root,'app/dist/server/index.js'),'fixture');
    writeFileSync(join(root,'app/.env'),'HARNESS_CONFIGURATION_PRESERVED=yes\n');
    writeFileSync(join(root,'scheduling.env'),'SCHEDULING_ENABLED=true\n');
    const python = join(root,'bin/python');
    writeFileSync(python,`#!/usr/bin/env bash
set -eu
printf 'python %s\\n' "$*" >> "$HARNESS_STATE/events"
if [[ "$1" == -c ]]; then
  if [[ "$2" == *current_user* ]]; then printf 'fixture_role\\n'; else read -r payload; [[ "$payload" == '{"status":"ok","database":"ok"}' ]]; fi
elif [[ "\u0024{2:-}" == inventory ]]; then printf '{}' > "$3"
elif [[ "\u0024{2:-}" == compare && "$HARNESS_SCENARIO" == compare ]]; then exit 73
elif [[ "$*" == *'migrate --noinput'* && "$HARNESS_SCENARIO" == migrate ]]; then exit 71
elif [[ "\u0024{2:-}" == grant && "$HARNESS_SCENARIO" == grant ]]; then exit 72
fi
`); chmodSync(python,0o755);
    const configuration = {HARNESS_ISOLATED:'yes',HARNESS_ROOT:path(root),HARNESS_APP:path(join(root,'app')),HARNESS_STATE:path(join(root,'state')),HARNESS_SCENARIO:scenario,HARNESS_OLD:oldSha,HARNESS_TARGET:target,HARNESS_NODE:path(process.execPath)};
    const prefix = Object.entries(configuration).map(([k,v])=>`export ${k}=${quote(v)}`).join('\n');
    const isolated = script.replace('readonly app=/opt/dongbo/app',`readonly app=${quote(configuration.HARNESS_APP)}`)
      .replace('readonly python=/opt/dongbo/venv/bin/python',`readonly python=${quote(path(python))}`)
      .replaceAll('/opt/dongbo/backups',path(join(root,'backups'))).replaceAll('/run/lock/dongbo-erp-release.lock',path(join(root,'release.lock')))
      .replaceAll('/etc/dongbo/scheduling.env',path(join(root,'scheduling.env'))).replace('[[ "$EUID" == 0 ]]','[[ "$HARNESS_ISOLATED" == yes ]]');
    assert.doesNotMatch(isolated,/\/opt\/dongbo|\/etc\/dongbo|\/run\/lock\/dongbo/);
    const r = spawnSync(bash,['-s','--',target],{input:prefix+'\n'+doubles+'\n'+isolated,encoding:'utf8',env,timeout:30000});
    assert.ifError(r.error);
    const events = readFileSync(join(root,'state/events'),'utf8');
    assert.doesNotMatch(events,/reset --hard|pg_restore --dbname|pip install|migrate erp 0038/);
    assert.equal(readFileSync(join(root,'app/.env'),'utf8'),'HARNESS_CONFIGURATION_PRESERVED=yes\n');
    return {...r,events,sha:readFileSync(join(root,'state/sha'),'utf8'),active:readFileSync(join(root,'state/dongbo-erp.service'),'utf8')};
  } finally { rmSync(root,{recursive:true,force:true}); }
}

test('market release and logical rollback parse in Bash',()=>{
  for (const text of [script,readFileSync(new URL('../deploy/disable-market-v2.sh',import.meta.url),'utf8')]) {
    const r=spawnSync(bash,['-n'],{input:text.replaceAll('\r\n','\n'),encoding:'utf8',env}); assert.ifError(r.error); assert.equal(r.status,0,r.stderr);
  }
});
test('complete market release backs up, migrates, reconciles and verifies assets',()=>{
  const r=simulate('success'); assert.equal(r.status,0,r.stderr+'\n'+r.events); assert.equal(r.sha,target); assert.equal(r.active,'active');
  assert.match(r.events,/pg_dump/); assert.match(r.events,/migrate --noinput/); assert.match(r.events,/check_account_market_release/); assert.match(r.events,/release-check.py compare/);
  assert.match(r.stdout,/VERIFIED AT LOCAL NGINX ORIGIN/);
});
for(const [scenario,code] of [['backup',47],['switch',53],['build',61]]) test('pre-migration '+scenario+' failure restores prior services',()=>{
  const r=simulate(scenario); assert.equal(r.status,code,r.stderr+'\n'+r.events); assert.equal(r.sha,oldSha); assert.equal(r.active,'active'); assert.match(r.stdout,/PRE-MIGRATION CODE\/SERVICES RESTORED/);
});
for(const [scenario,code] of [['migrate',71],['grant',72],['compare',73],['restart',57],['health',1],['assets',1]]) test('post-migration '+scenario+' failure preserves new auth and holds maintenance',()=>{
  const r=simulate(scenario); assert.equal(r.status,code,r.stderr+'\n'+r.events); assert.equal(r.sha,target); assert.equal(r.active,'inactive'); assert.match(r.stderr,/MAINTENANCE/); assert.doesNotMatch(r.stdout,/VERIFIED AT LOCAL NGINX ORIGIN/);
});
