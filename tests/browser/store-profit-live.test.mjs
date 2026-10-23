import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {existsSync, mkdirSync} from 'node:fs';
const require = createRequire(pathToFileURL(join(process.env.CODEX_NODE_MODULES, 'package.json')));
const {chromium} = require('playwright');
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await chromium.launch({headless:true, executablePath:process.env.BROWSER_EXECUTABLE || (existsSync(edge) ? edge : undefined)});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', dialog => dialog.accept());
  await page.addInitScript(({refreshToken,organizationId,warehouseId}) => {
    sessionStorage.setItem('dongbo.team.session.v1', JSON.stringify({refreshToken,organizationId,warehouseId}));
  }, {refreshToken:process.env.STORE_TEST_TOKEN,organizationId:process.env.STORE_TEST_ORG,warehouseId:process.env.STORE_TEST_WAREHOUSE});
  await page.goto(process.env.STORE_TEST_URL);
  await page.locator('[data-action="edit-product"]').first().click();
  await page.locator('#addProductStoreListing').click();
  const first = page.locator('[data-store-listing]').nth(0);
  await first.locator('[data-listing-field="store"]').selectOption(process.env.STORE_TEST_FIRST);
  await first.locator('[data-listing-field="price"]').fill('79.90');
  await first.locator('[data-listing-field="commission"]').fill('0');
  await page.locator('#addProductStoreListing').click();
  const second = page.locator('[data-store-listing]').nth(1);
  await second.locator('[data-listing-field="store"]').selectOption(process.env.STORE_TEST_SECOND);
  await second.locator('[data-listing-field="price"]').fill('89.90');
  await page.locator('#saveProductButton').click();
  await page.locator('#productModal').waitFor({state:'hidden'});
  await page.reload();
  await page.locator('[data-action="toggle-profit-details"]').first().click();
  const cards = page.locator('.store-profit-card');
  await cards.first().waitFor();
  assert.equal(await cards.count(), 2);
  assert.match(await cards.first().innerText(), /毛利/);
  assert.match(await cards.first().innerText(), /ROI/);
  assert.doesNotMatch(await page.locator('#productRows').innerText(), /尚未配置参与试算/);
  await page.locator('[data-action="edit-product"]').first().click();
  assert.equal(await first.locator('[data-listing-field="price"]').inputValue(), '79.90');
  assert.equal(await first.locator('[data-listing-field="commission"]').inputValue(), '0.00');
  await first.locator('[data-listing-field="price"]').fill('99.90');
  await page.locator('#saveProductButton').click();
  await page.locator('#productModal').waitFor({state:'hidden'});
  await page.reload();
  await page.locator('[data-action="toggle-profit-details"]').first().click();
  await page.locator('.store-profit-card').first().waitFor();
  assert.match(await page.locator('#productRows').innerText(), /99.90/);
  assert.deepEqual(errors, []);
  const output = process.env.STORE_TEST_SCREENSHOTS;
  if (output) {mkdirSync(output,{recursive:true}); await page.screenshot({path:join(output,'store-profit-desktop.png'),fullPage:true});}
  await page.locator('[data-action="edit-product"]').first().click();
  for (const width of [1440, 390]) {
    await page.setViewportSize({width,height:1000});
    await page.locator('[data-store-listing]').first().scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1), `editor overflow at ${width}`);
    assert.equal(await page.locator('[data-listing-field="store"]').first().inputValue(), process.env.STORE_TEST_FIRST);
    assert.match(await first.locator('[data-listing-summary]').innerText(), /马来一店完整名称/);
    if (output) await page.screenshot({path:join(output,`store-editor-${width}.png`),fullPage:true});
  }
  console.log('Real HTTP/PostgreSQL: two stores saved, reloaded, updated; gross profit and ROI visible.');
} finally { await browser.close(); }
