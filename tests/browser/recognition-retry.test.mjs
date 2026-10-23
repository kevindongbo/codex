import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {existsSync} from 'node:fs';
const require=createRequire(pathToFileURL(join(process.env.CODEX_NODE_MODULES,'package.json')));
const {chromium}=require('playwright');
const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||(existsSync(edge)?edge:undefined)});
try {
  const page=await browser.newPage();
  page.on('dialog',d=>d.accept());
  await page.setContent('<button id="scheduleNav"></button><button data-schedule-page="evidence">凭证</button><main id="schedulingRoot"></main>');
  await page.addScriptTag({content:await readFile(new URL('../../scheduling.js',import.meta.url),'utf8')});
  await page.evaluate(()=>{
    const grid=()=>Array.from({length:7},()=>Array.from({length:12},()=>({status:'unknown',course_name:''})));
    const term={id:'term',name:'测试学期',first_monday:'2035-01-01',week_count:20};
    let job={id:'job-first',status:'queued',attempts:0};
    let draft={id:'draft',term_id:'term',evidence_id:'evidence',state:'draft',revision:1,draft_grid:grid(),selected_weeks:[1],weekend_day:'sat',job};
    window.finishInitial=()=>{job.status='succeeded';draft.revision++;draft.draft_grid[1][2]={status:'class',course_name:'识别课程'};};
    window.nextRecognition='failed'; window.requestCount=0; window.saveCount=0; window.confirmCount=0;
    const nativeTimeout=window.setTimeout.bind(window);
    window.setTimeout=(fn,ms)=>nativeTimeout(fn,ms===2000?50:ms);
    const copy=v=>JSON.parse(JSON.stringify(v));
    const gateway={user:{id:1},organizationId:'org',privateScheduleImage:async()=>new Blob(['x'],{type:'image/png'}),request:async(path,options={})=>{
      if(path==='context/')throw Error('missing scheduling prefix');
      if(path==='/scheduling/context/')return {enabled:true,user:{id:1,is_superuser:false},week_start:'2035-01-01',periods:[],terms:[term],revision:1};
      if(path.includes('/board/'))return {cells:[],days:[],pending:[]};
      if(path.startsWith('/scheduling/evidence/'))return {count:1,results:[{id:'evidence',original_name:'课表.png',owner_id:1}]};
      if(path.startsWith('/scheduling/imports/?'))return {count:1,results:[copy(draft)]};
      if(path.endsWith('/confirm/')){window.confirmCount++;return {};}
      if(path.endsWith('/recognize/')){window.requestCount++;job={id:'job-'+requestCount,status:window.nextRecognition,attempts:1,sanitized_error:'invalid_output'};draft.job=job;if(job.status==='succeeded'){draft.revision++;draft.draft_grid[3][4]={status:'class',course_name:'重试识别课程'};}return copy(job);}
      if(path==='/scheduling/imports/draft/'){
        if(options.method==='PATCH'){
          window.saveCount++;window.lastSave=copy(options.body);
          const saved={...draft,...copy(options.body),revision:draft.revision+1};
          if(window.delayNextSave){window.delayNextSave=false;window.savePending=true;await new Promise(resolve=>{window.releaseSave=resolve;});window.savePending=false;}
          draft=saved;
        }
        return copy(draft);
      }
      if(path.startsWith('/scheduling/jobs/'))return copy(job);
      throw Error(path);
    }};
    DongboScheduling.mount(gateway,true);
  });
  await page.locator('[data-schedule-page=evidence]').click();
  await page.locator('[data-sc=edit]').click();
  await page.locator('[name=course_note]').fill('刚输入但还没有失焦的备注');
  await page.evaluate(()=>finishInitial());
  await page.waitForFunction(()=>document.getElementById('sc-job-status').textContent.includes('未保存编辑'));
  assert.equal(await page.locator('[name=course_note]').inputValue(),'刚输入但还没有失焦的备注');
  assert.equal(await page.locator('.sc-grid-class').count(),0);
  await page.locator('[data-sc=reload-draft]').click();
  await page.locator('.sc-grid-class').first().waitFor();
  await page.locator('[data-sc=recognize]').click();
  await page.waitForFunction(()=>document.getElementById('sc-dialog-error').textContent.includes('模型返回'));
  await page.evaluate(()=>{window.nextRecognition='succeeded';});
  await page.locator('[data-sc=recognize]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.sc-grid-class').length===2);
  assert.equal(await page.evaluate(()=>requestCount),2);
  const saves=await page.evaluate(()=>saveCount);
  await page.evaluate(()=>{window.delayNextSave=true;});
  await page.locator('[data-sc=save-draft]').click();
  await page.waitForFunction(()=>window.savePending);
  await page.locator('[name=course_note]').fill('保存期间的新课程');
  const cell=page.locator('[data-sc=grid][data-day="0"][data-period="0"]');
  await cell.click();await cell.click();
  await page.locator('#sc-editor-form [name=weeks][value="2"]').check();
  await page.locator('#sc-editor-form [name=weekend_day]').selectOption('sun');
  await page.locator('[data-sc=save-draft]').click();
  assert.equal(await page.evaluate(()=>saveCount),saves+1,'duplicate save cannot race');
  await page.evaluate(()=>releaseSave());
  await page.waitForFunction(()=>document.getElementById('sc-dialog-error').textContent.includes('新编辑仍未保存'));
  assert.equal(await cell.textContent(),'有课');
  assert.equal(await page.locator('#sc-editor-form [name=weeks][value="2"]').isChecked(),true);
  assert.equal(await page.locator('#sc-editor-form [name=weekend_day]').inputValue(),'sun');
  await page.locator('[data-sc=save-draft]').click();
  await page.waitForFunction(()=>document.getElementById('sc-dialog-error').textContent==='草稿已保存。');
  const saved=await page.evaluate(()=>lastSave);
  assert.equal(saved.draft_grid[0][0].status,'class');
  assert.equal(saved.draft_grid[0][0].course_name,'保存期间的新课程');
  assert.deepEqual(saved.selected_weeks,[1,2]);assert.equal(saved.weekend_day,'sun');
  // A new edit while publish is saving must not confirm the older snapshot.
  await page.locator('[data-sc=free]').click();
  await page.evaluate(()=>{window.delayNextSave=true;});
  await page.locator('[data-sc=publish]').click();
  await page.waitForFunction(()=>window.savePending);
  await page.locator('#sc-editor-form [name=weeks][value="3"]').check();
  await page.evaluate(()=>releaseSave());
  await page.waitForFunction(()=>document.getElementById('sc-dialog-error').textContent.includes('保存期间有新编辑'));
  assert.equal(await page.evaluate(()=>confirmCount),0);
  console.log('Recognition browser: late OCR and save responses preserve edits; duplicate saves blocked; raced publish blocked; explicit recognition retry succeeds.');
} finally {await browser.close();}
