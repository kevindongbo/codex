import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {join, extname} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
const require = createRequire(pathToFileURL(join(process.env.CODEX_NODE_MODULES, 'package.json')));
const {chromium} = require('playwright');
const mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png'};
const server = createServer(async (req,res) => {
  try {
    const path = new URL(req.url,'http://localhost').pathname;
    const file = join(root,path === '/' ? 'index.html' : path);
    if (!file.startsWith(root)) throw Error('path');
    res.writeHead(200, {'Content-Type':mime[extname(file)] || 'application/octet-stream'}).end(await readFile(file));
  } catch {res.writeHead(404).end();}
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
let browser;
try {
  browser = await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror',error => errors.push(error.message));
  await page.addInitScript(() => {
    window.DONGBO_CONFIG = {mode:'team',apiBase:'/api',allowLocalFallback:false};
    sessionStorage.setItem('dongbo.team.session.v1',JSON.stringify({refreshToken:'synthetic',organizationId:'org',warehouseId:'wh'}));
  });
  let failure = true;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/purchase-orders/' && failure) return route.fulfill({status:500,json:{detail:'Synthetic list failure'}});
    const values = {
      '/api/auth/token/refresh/':{access:'synthetic'},
      '/api/auth/me/':{user:{id:1,username:'test-owner',is_owner:true},memberships:[{organization:{id:'org',name:'合成测试组织'},role:'admin'}],permissions:['catalog']},
      '/api/warehouses/':[{id:'wh',name:'原仓库',code:'WH',country:'MY',active:true}],
      '/api/products/':[{id:'p',name:'原有摄像头',status:'active',images:[],skus:[{id:'s',code:'CAMERA',cost:'10',currency:'CNY'}]}],
      '/api/stock-balances/':[{id:'b',sku:'s',warehouse:'wh',on_hand:'17',reserved:'0'}],
      '/api/sync/version/':{revision:7},
      '/api/profit-calculator/config/':{categories:[],category_tree:[]},
      '/api/scheduling/context/':{enabled:false},
    };
    return route.fulfill({json:values[path] || []});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/#products`);
  await page.waitForFunction(() => document.querySelector('#runtimeStateText').textContent === '数据未完整加载');
  assert.equal(await page.locator('#connectionBanner').isVisible(),true);
  assert.match(await page.locator('#connectionBanner').innerText(),/purchase-orders.*HTTP 500/);
  assert.match(await page.locator('#module-products').innerText(),/原有摄像头/);
  assert.equal(await page.evaluate(() => teamGateway.canWrite()),false);
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),'banner overflow');
  }
  failure = false;
  await page.locator('#retryConnection').click();
  await page.waitForFunction(() => document.querySelector('#runtimeStateText').textContent === '团队已同步');
  assert.equal(await page.locator('#connectionBanner').isVisible(),false);
  assert.equal(await page.evaluate(() => teamGateway.canWrite()),true);
  failure = true;
  await page.evaluate(() => refreshTeamState());
  assert.equal(await page.locator('#connectionBanner').isVisible(),true);
  assert.match(await page.locator('#module-products').innerText(),/原有摄像头/);
  assert.deepEqual(errors,[]);
  console.log('PASS: first-load outage, preserved catalog, warning/read-only, retry recovery, later outage, desktop/mobile; zero page errors');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
