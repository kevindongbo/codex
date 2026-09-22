import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const require = process.env.CODEX_NODE_MODULES ? createRequire(pathToFileURL(join(process.env.CODEX_NODE_MODULES, 'package.json'))) : createRequire(import.meta.url);
const { chromium } = require('playwright');
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE || (existsSync(edge) ? edge : undefined) });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  await page.goto('about:blank');
  await page.setContent('<button id="scheduleNav" hidden>排班</button><button data-schedule-page="board">工作安排</button><button data-schedule-page="evidence">原始凭证</button><main id="module-scheduling"><div id="schedulingRoot"></div></main>');
  await page.addStyleTag({ content: 'body{margin:16px;font-family:Arial} main{max-width:100%}' + await readFile(new URL('../../scheduling.css', import.meta.url), 'utf8') });
  await page.addScriptTag({ content: await readFile(new URL('../../scheduling.js', import.meta.url), 'utf8') });
  await page.evaluate(() => {
    const dates = ['2035-01-01','2035-01-02','2035-01-03','2035-01-04','2035-01-05','2035-01-06','2035-01-07'];
    const periods = Array.from({length:12}, (_,i) => ({number:i+1,start:'08:20',end:'09:05'}));
    const term = {id:'term',name:'测试学期',first_monday:dates[0],week_count:20};
    let evidence = [], imports = [];
    window.calls = [];
    const gateway = { user:{id:1},organizationId:'org',
      privateScheduleImage:async () => new Blob(['test'],{type:'image/png'}),
      request:async (path,opts={}) => {
        calls.push({path,body:opts.body,method:opts.method});
        if(path === '/scheduling/context/') return {enabled:true,user:{id:1,is_superuser:false},business_date:dates[0],week_start:dates[0],terms:[term],periods,revision:1};
        if(path.startsWith('/scheduling/board/')) return {days:dates,periods,pending:[],cells:dates.flatMap(date => periods.map(p => ({date,period:p.number,members:Array.from({length:100},(_,i)=>({user_id:i+1,name:'成员'+(i+1),status:'work',revision:1}))})))};
        if(path === '/scheduling/evidence/' && opts.method === 'POST') { evidence=[{id:'e',original_name:'课表.png',created_at:'2035-01-01',size:100}]; return {results:evidence}; }
        if(path.startsWith('/scheduling/evidence/?')) return {results:evidence};
        if(path === '/scheduling/imports/' && opts.method === 'POST') { if(opts.body.evidence_id !== 'e') throw new Error('wrong evidence id'); imports=[{id:'i',evidence_id:'e',term_id:'term',state:'draft',selected_weeks:[1],weekend_day:'sat',revision:1,draft_grid:DongboScheduling.blankGrid(),expected_week_revisions:{'2035-01-01':0}}]; return imports[0]; }
        if(path.startsWith('/scheduling/imports/?')) return {results:imports};
        if(path.endsWith('/recognize/')) throw new Error('测试未配置识别');
        if(path === '/scheduling/imports/i/') { if(opts.method==='PATCH') Object.assign(imports[0],opts.body,{revision:imports[0].revision+1}); return structuredClone(imports[0]); }
        if(path.endsWith('/confirm/')) { if(!opts.body.expected_week_revisions) throw new Error('missing revision'); return {}; }
        if(path === '/scheduling/adjustments/') { if(!opts.body.reason) throw new Error('reason required'); return {}; }
        if(path === '/scheduling/history/') return {adjustments:[{id:'a',date:dates[0],period:1,status:'leave',reason:'去办理业务',revision:1}]};
        throw new Error('unexpected API: '+path);
      }};
    DongboScheduling.mount(gateway,true);
  });
  await page.locator('.sc-board').waitFor();
  for(const width of [1366,1440,1920,390,430]) {
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
    const visible = await page.locator('.sc-cell:visible').count();
    assert.equal(visible, width < 700 ? 12 : 84);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-schedule-page=evidence]').click();
  await page.locator('#sc-upload input[type=file]').setInputFiles({name:'test.png',mimeType:'image/png',buffer:Buffer.from('test')});
  await page.locator('#sc-upload button[type=submit]').click();
  await page.locator('#sc-editor-form').waitFor({timeout:5000}).catch(async error => { console.log(await page.locator('body').innerText()); console.log(await page.evaluate(()=>calls)); throw error; });
  await page.locator('[data-sc=free]').click();
  await page.locator('[data-sc=publish]').click();
  await page.waitForFunction(() => calls.some(c=>c.path.endsWith('/confirm/')));
  await page.locator('[data-schedule-page=board]').click();
  await page.locator('[data-sc=adjust]').click();
  await page.locator('[name=dates]').first().check();
  await page.locator('[name=reason]').fill('去办理业务');
  await page.locator('#sc-adjust button[type=submit]').click();
  await page.waitForFunction(() => calls.some(c=>c.path==='/scheduling/adjustments/'));
  await page.locator('[data-sc=history]').click();
  assert.match(await page.locator('#sc-dialog').innerText(), /去办理业务/);
  assert.deepEqual(errors, []);
  await mkdir(new URL('../../.tmp/',import.meta.url),{recursive:true});
  await page.screenshot({path:new URL('../../.tmp/scheduling-browser.png',import.meta.url).pathname.replace(/^\/(.:\/)/,'$1')});
  console.log('Scheduling browser: upload/review/confirm/leave/history + 5 viewports passed (mock transport).');
} finally { await browser.close(); }
