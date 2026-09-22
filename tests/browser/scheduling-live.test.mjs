// Called only by the isolated Django LiveServerTestCase. Never targets production.
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const base = process.env.SCHEDULING_TEST_URL;
assert.match(base || '', /^http:\/\/localhost:\d+$/);
const require = process.env.CODEX_NODE_MODULES ? createRequire(pathToFileURL(join(process.env.CODEX_NODE_MODULES,'package.json'))) : createRequire(import.meta.url);
const { chromium } = require('playwright');
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE || (existsSync(edge) ? edge : undefined)});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[]; page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.goto(base+'/__scheduling_test__/');
  await page.evaluate(async config => {
    const login = await fetch('/api/auth/token/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'schedule-e2e-member',password:config.password})});
    if (!login.ok) throw new Error('Fixture login failed: '+login.status);
    const token = (await login.json()).access;
    window.fixtureHeaders = {Authorization:'Bearer '+token,'X-Organization-ID':config.org};
    const gateway = {user:{id:config.user},organizationId:config.org,
      request:async (path, options={}) => {
        const form = options.body instanceof FormData;
        const response = await fetch('/api'+path,{...options,headers:{...fixtureHeaders,...(!form ? {'Content-Type':'application/json'} : {}),...(options.headers||{})},body:options.body ? (form ? options.body : JSON.stringify(options.body)) : undefined});
        const data=await response.json(); if(!response.ok) throw new Error(JSON.stringify(data)); return data;
      },
      privateScheduleImage:async id => {const r=await fetch('/api/scheduling/evidence/'+id+'/content/',{headers:fixtureHeaders}); if(!r.ok)throw new Error('Private image failed'); return r.blob();}
    };
    window.fixtureWeek = (await gateway.request('/scheduling/context/')).terms[0].first_monday;
    DongboScheduling.mount(gateway,true);
  }, {password:process.env.SCHEDULING_TEST_PASSWORD,org:process.env.SCHEDULING_TEST_ORG,user:Number(process.env.SCHEDULING_TEST_USER)});
  await page.locator('.sc-board').waitFor();
  await page.locator('[data-schedule-page=evidence]').click();
  await page.locator('#sc-upload input[type=file]').setInputFiles({name:'original.png',mimeType:'image/png',buffer:Buffer.from(process.env.SCHEDULING_TEST_IMAGE,'base64')});
  await page.locator('#sc-upload button[type=submit]').click();
  await page.locator('#sc-editor-form .sc-grid-class').first().waitFor({timeout:15000});
  assert.equal(await page.locator('#sc-editor-form .sc-grid-class').count(),2);
  await page.locator('[data-sc=free]').click();
  await page.locator('[data-sc=publish]').click();
  await page.locator('#sc-dialog').waitFor({state:'detached'});
  await page.locator('[data-schedule-page=board]').click();
  await page.locator('[data-sc=next]').click();
  await page.waitForFunction(() => document.querySelector('.sc-toolbar strong')?.textContent.startsWith(window.fixtureWeek));
  await page.locator('[data-sc=adjust]').click();
  await page.locator('[name=dates]').nth(1).check();
  await page.locator('[name=reason]').fill('私密测试请假原因');
  await page.locator('#sc-adjust button[type=submit]').click();
  await page.locator('#sc-dialog').waitFor({state:'detached'});
  assert.match(await page.locator('.sc-board').innerText(), /请假/);
  const privacy = await page.evaluate(async password => {
    const login=await fetch('/api/auth/token/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'schedule-e2e-other',password})});
    const token=(await login.json()).access;
    const evidence=(await (await fetch('/api/scheduling/evidence/',{headers:fixtureHeaders})).json()).results[0];
    const denied=await fetch(evidence.content_url,{headers:{...fixtureHeaders,Authorization:'Bearer '+token}});
    const board=await (await fetch('/api/scheduling/board/',{headers:{...fixtureHeaders,Authorization:'Bearer '+token}})).text();
    return {status:denied.status,board};
  },process.env.SCHEDULING_TEST_PASSWORD);
  assert.ok([403,404].includes(privacy.status));
  assert.doesNotMatch(privacy.board,/私密测试请假原因|Private fixture course|original\.png/);
  assert.deepEqual(errors,[]);
  console.log('Live Django + PostgreSQL + browser + worker passed; vision transport mocked, no paid provider call.');
} finally {await browser.close();}
