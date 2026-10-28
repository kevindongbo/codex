import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,dirname,delimiter} from 'node:path';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
const source=readFileSync(new URL('../deploy/reconcile-purchase-emergency.sh',import.meta.url),'utf8').replaceAll('\r\n','\n');
const bash=process.env.BASH_EXECUTABLE || 'bash';
const old='0f814ef9962ad328c53e4d14d05a5117ea85e57c';
const target='b'.repeat(40);
const q=x=>`'${x.replaceAll("'", "'\\''")}'`;
for (const scenario of ['clean','known','unknown','fail-old','fail-new']) test('emergency correction reconciliation: '+scenario,()=>{
  const dir=mkdtempSync(join(tmpdir(),'reconcile-')).replaceAll('\\','/');
  try {
    mkdirSync(join(dir,'app/.git'),{recursive:true});
    mkdirSync(join(dir,'app/backend/apps/erp'),{recursive:true});
    mkdirSync(join(dir,'backups'));
    writeFileSync(join(dir,'app/backend/apps/erp/serializers.py'),'known correction');
    writeFileSync(join(dir,'dirty'),scenario==='clean'?'no':'yes');
    writeFileSync(join(dir,'head'),old);
    const release=join(dir,'release.sh');
    writeFileSync(release,`#!/bin/bash\nset -e\n[[ $(cat "$HARNESS_ROOT/dirty") == no ]]\n${scenario==='fail-old'?'exit 55':`printf '%s' ${target} > "$HARNESS_ROOT/head"\n${scenario==='fail-new'?'exit 56':'echo released'}`}\n`);
    const fake=`
git() {
 case "$1" in
 status) [[ $(cat "$HARNESS_ROOT/dirty") == no ]] || echo ' M backend/apps/erp/serializers.py'; return 0 ;;
 rev-parse) if [[ "$2" == HEAD ]]; then cat "$HARNESS_ROOT/head"; else echo expected; fi ;;
 hash-object) [[ "$HARNESS_SCENARIO" != unknown ]] && echo expected || echo unknown ;;
 diff) if [[ "$2" == --name-only ]]; then echo backend/apps/erp/serializers.py; elif [[ "$2" == --binary ]]; then echo 'reviewed patch'; fi ;;
 apply) if [[ "$*" == *--check* ]]; then return 0; elif [[ "$2" == --reverse ]]; then echo no > "$HARNESS_ROOT/dirty"; else echo yes > "$HARNESS_ROOT/dirty"; fi ;;
 *) return 99 ;;
 esac
}
systemctl() { echo "systemctl $*" >> "$HARNESS_ROOT/events"; }
flock() { return 0; }
export -f git systemctl flock
`;
    const isolated=source.replace('app=/opt/dongbo/app',`app=${q(dir+'/app')}`)
      .replace('[[ $EUID == 0 && -d "$app/.git" ]]','[[ -d "$app/.git" ]]')
      .replaceAll('/opt/dongbo/backups',dir+'/backups')
      .replaceAll('/run/lock/dongbo-erp-release.lock',dir+'/release.lock');
    assert.doesNotMatch(isolated,/\/opt\/dongbo|\/run\/lock\/dongbo/);
    const result=spawnSync(bash,['-s','--',target,release],{input:fake+'\n'+isolated,encoding:'utf8',env:{...process.env,HARNESS_ROOT:dir,HARNESS_SCENARIO:scenario,PATH:dirname(bash)+delimiter+process.env.PATH},timeout:15000});
    assert.ifError(result.error);
    assert.equal(result.status,scenario==='unknown'?1:scenario==='fail-old'?55:scenario==='fail-new'?56:0,result.stderr);
    assert.equal(readFileSync(join(dir,'dirty'),'utf8').trim(),['unknown','fail-old'].includes(scenario)?'yes':'no');
  } finally {rmSync(dir,{recursive:true,force:true});}
});
