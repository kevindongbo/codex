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
  const errors = [], consoleErrors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text() + ' ' + m.location().url); });
  page.on('dialog', dialog => dialog.accept());
  await page.addInitScript(({refreshToken,organizationId,warehouseId}) => {
    if (!sessionStorage.getItem('dongbo.team.session.v1')) sessionStorage.setItem('dongbo.team.session.v1', JSON.stringify({refreshToken,organizationId,warehouseId}));
  }, {refreshToken:process.env.MARKET_TEST_REFRESH,organizationId:process.env.MARKET_TEST_ORG,warehouseId:process.env.MARKET_TEST_WH});
  await page.goto(process.env.MARKET_TEST_URL);
  await page.locator('#runtimeStateButton').click();
  await page.locator('#openAccountManager').click();
  await page.locator('[data-account-action="archive"]').click();
  await page.locator('#accountLifecycleDialog').waitFor();
  await page.locator('#cancelAccountLifecycle').click();
  assert.equal(await page.locator('[data-account-action="archive"]').count(),1);
  await page.locator('[data-account-action="archive"]').click();
  await page.locator('#confirmAccountLifecycle').click();
  await page.locator('#accountLifecycleDialog').waitFor({state:'hidden'});
  await page.locator('#internalAccountFilter').selectOption('departed');
  await page.locator('[data-account-action="restore"]').click();
  await page.locator('#confirmAccountLifecycle').click();
  await page.locator('#accountLifecycleDialog').waitFor({state:'hidden'});
  await page.locator('#internalAccountFilter').selectOption('employed');
  await page.waitForFunction(() => document.querySelector('#internalAccountRows').textContent.includes('恢复后待设置新密码'));
  await page.locator('[data-close="sessionModal"]').last().click();
  await page.locator('[data-module="profit"]').click();
  await page.locator('#profitMarketSwitch').selectOption('US');
  await page.locator('#marketForm').waitFor({state:'visible'});
  const set = async (name,value) => page.locator('#marketForm [name="' + name + '"]').fill(value);
  async function fill(c) {
    const values = {seller_program:'local scenario',origin:'local warehouse',destination:c === 'US' ? '90210' : '01000',
      cny_rate:c === 'US' ? '7' : '.35',usd_rate:c === 'US' ? '1' : '.05',rate_source:'测试人工汇率',quote_source:'测试完整仓库报价',
      commission_source:'商家核对类目收费组',other_source:'确认已包含，无其他成本',tax_source:'测试税务口径，不是真实税务资料',
      item0_sku_name:'camera-test',item0_price:c === 'US' ? '100' : '1000',item0_cost:'140',item0_head:'21',
      item0_affiliate:'10',item0_commission:'6',item0_weight:'2',item0_length:'10',item0_width:'8',item0_height:'3',
      item0_shipping:c === 'US' ? '8' : '80',item0_other:'0',item0_tax:'0',item0_withholding:'0'};
    for (const [name,value] of Object.entries(values)) await set(name,value);
    await page.locator('[name="item0_battery"]').selectOption('plug_in_no_battery');
    for (const name of ['eligibility','battery_accepted','surcharges','fees_confirmed',...(c === 'MX' ? ['mx_fee_confirmed'] : [])]) await page.locator('[name="' + name + '"]').check();
  }
  await fill('US');
  await page.locator('#marketSaveWorkspace').click();
  await page.waitForFunction(() => document.querySelector('#marketStatus').textContent.includes('草稿已保存'));
  await page.locator('#marketForm button[type="submit"]').click();
  await page.waitForFunction(() => document.querySelector('#marketResults').textContent.includes('USD 53.00')).catch(async e => { console.log('Market status:',await page.locator('#marketStatus').innerText()); throw e; });
  assert.match(await page.locator('#marketResults').innerText(), /1\.89/);
  await page.locator('#marketPlanName').fill('US real HTTP test');
  await page.locator('#marketSavePlan').click();
  await page.waitForFunction(() => document.querySelector('#marketPlans').textContent.includes('US real HTTP test'));
  for (const width of [1366,1440,1920,390,430]) {
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'market overflow at ' + width);
  }
  const output = process.env.MARKET_TEST_SCREENSHOTS;
  if (output) {mkdirSync(output,{recursive:true}); await page.screenshot({path:join(output,'market-us-mobile.png'),fullPage:true});}
  await page.setViewportSize({width:1440,height:1000});
  await set('item0_price','101');
  await page.locator('#profitMarketSwitch').selectOption('MX');
  await page.locator('#marketSwitchDiscard').click();
  await page.locator('#marketForm [name="item0_price"]').waitFor();
  await page.waitForFunction(() => document.querySelector('#marketForm [name="item0_category"]').value.startsWith('MX:'));
  assert.equal(await page.locator('[name="item0_price"]').inputValue(),'');
  assert.equal(await page.locator('[name="service"] option[value="platform_warehouse"]').evaluate(e => e.disabled),true);
  await fill('MX');
  await page.locator('#marketForm button[type="submit"]').click();
  await page.waitForFunction(() => document.querySelector('#marketResults').textContent.includes('MXN 294.00')).catch(async e => { console.log('Market status:',await page.locator('#marketStatus').innerText()); throw e; });
  await page.locator('#marketPlanName').fill('MX real HTTP test');
  await page.locator('#marketSavePlan').click();
  await page.waitForFunction(() => document.querySelector('#marketPlans').textContent.includes('MX real HTTP test'));
  await page.locator('#profitMarketSwitch').selectOption('US');
  await page.locator('#marketSwitchDiscard').click();
  await page.waitForFunction(() => document.querySelector('#marketForm [name="item0_category"]').value.startsWith('US:'));
  assert.equal(await page.locator('[name="item0_price"]').inputValue(),'100');
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#ownerAccountActions').hidden);
  await page.locator('#profitMarketSwitch').selectOption('US');
  await page.waitForFunction(() => document.querySelector('#marketForm [name="item0_price"]')?.value === '100');
  await page.locator('[data-market-plan]').click();
  await page.waitForFunction(() => document.querySelector('#marketResults').textContent.includes('USD 53.00')).catch(async e => { console.log('Market status:',await page.locator('#marketStatus').innerText()); throw e; });
  assert.equal(await page.locator('#marketSavePlan').evaluate(e => e.disabled),true);
  assert.deepEqual(errors,[]);
  assert.deepEqual(consoleErrors,[]);
  if (output) await page.screenshot({path:join(output,'market-us-desktop.png'),fullPage:true});
  console.log('PASS real PostgreSQL/browser: account archive/cancel/restore, US/MX calculation/save/readback, country isolation, 5 widths, zero browser errors');
} finally { await browser.close(); }
