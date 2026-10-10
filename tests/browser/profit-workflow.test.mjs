import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = new URL('../../', import.meta.url).pathname.replace(/^\/(.:\/)/, '$1');
const moduleRoot = process.env.CODEX_NODE_MODULES;
const require = moduleRoot ? createRequire(pathToFileURL(join(moduleRoot, 'package.json'))) : createRequire(import.meta.url);
const { chromium } = require('playwright');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml' };
const server = createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname);
  const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const file = normalize(join(root, relative));
  if (!file.startsWith(normalize(root)) || !existsSync(file)) { response.writeHead(404).end(); return; }
  response.writeHead(200, { 'content-type': mime[extname(file)] || 'application/octet-stream' });
  createReadStream(file).pipe(response);
});

const result = {
  rule_version: '2026.08.21', shipping_rate_version: 'test', has_ad_cost: true,
  revenue: '79.90', total_fees: '15.00', settlement_amount: '64.90', costs_before_ads: '30.00',
  gross_profit: '34.90', gross_margin: '43.68', advertising_cost_before_rebate: '19.98',
  advertising_rebate_percent: '12.50', advertising_rebate_amount: '2.50', advertising_cost: '17.48',
  net_profit: '17.42', net_margin: '21.80', true_roi: '4.57', true_roi_status: 'available',
  true_cpa_usd: null, break_even_cpa_usd: '8.20', break_even_roi: '2.29', fees_breakdown: [],
  amount_summary: {
    sales_revenue: '79.90', buyer_shipping_revenue: '0', settlement_revenue: '79.90',
    total_revenue: '79.90', platform_fees: '10.00', affiliate_commission: '5.00', logistics_cost: '0',
    estimated_platform_payout: '64.90', product_cost: '30.00', total_fees: '15.00', settlement_amount: '64.90',
    costs_before_ads: '30.00', gross_profit: '34.90', gross_margin: '43.68', costs_after_ads: '47.48',
    net_profit: '17.42', net_margin: '21.80'
  }
};
const categoryTree = [{ label: '箱包', children: [{ label: '女包', children: [{ code: 'bag-womens-womens-tote-bags', label: '女士托特包' }] }] }];
const historicalInput = {
  country: 'MY', seller_type: 'cross_border', shop_identity: 'marketplace', bxp: false,
  commission_adjustment: '1.00', transaction_fee_adjustment: '0.00', advertising_rebate_percent: '12.50',
  buyer_pays_shipping: false, buyer_shipping_region: 'west_malaysia', cny_per_myr: '1.680000', usd_per_myr: '0.235000',
  items: [{ sku_name: 'AI-BAG-BROWN-05', category_code: 'bag-womens-womens-tote-bags', weight_g: '200', product_cost_cny: '18.90', item_price: '79.90', affiliate_rate: '15.00', ad_cost_type: 'roi', ad_cost_value: '4.00', advertising_rebate_percent_override: null }]
};

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const installedEdge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const executablePath = process.env.BROWSER_EXECUTABLE || (existsSync(installedEdge) ? installedEdge : undefined);
const browser = await chromium.launch({ headless: true, executablePath });
const working = {
  revision: 1, config: { country: 'MY', seller_type: 'cross_border', shop_identity: 'marketplace', advertising_rebate_percent: '3.00', display_currency: 'MYR' },
  rate_mode: 'manual', manual_cny_per_myr: '1.680000', manual_usd_per_myr: '0.235000', updated_by_name: '验收用户'
};
const savedPayloads = [];
let strategiesUnavailable = true;
let strategyErrorStatus = 500;
let delayedCalculation = null;
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.route('**/api/profit-calculator/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (payload, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });
    if (path.endsWith('/config/')) return json({ categories: [{ code: 'bag-womens-womens-tote-bags', label: '女士托特包', path: ['箱包', '女包', '女士托特包'] }], category_tree: categoryTree, default_commission_adjustment: '1.00' });
    if (path.endsWith('/strategies/')) {
      if (strategiesUnavailable) return json({detail:'temporary outage'}, strategyErrorStatus);
      return json({count:2,next:url.searchParams.get('page') ? null : '/api/profit-calculator/strategies/?page=2',results:[{id:url.searchParams.get('page') ? 'strategy-2' : 'strategy-1',name:'测试策略',is_default:true,config:{seller_type:'local',advertising_rebate_percent:'99'}}]});
    }
    if (path.endsWith('/exchange-rates/')) return json({ cny_per_myr: '1.680000', usd_per_myr: '0.235000', date: '2026-08-21', source: 'test' });
    if (path.endsWith('/working-config/') && request.method() === 'GET') return json(working);
    if (path.endsWith('/working-config/') && request.method() === 'PUT') {
      const body = request.postDataJSON();
      assert.equal(body.revision, working.revision);
      working.revision += 1;
      working.config = body.config;
      working.rate_mode = body.rate_mode;
      working.manual_cny_per_myr = body.manual_cny_per_myr;
      working.manual_usd_per_myr = body.manual_usd_per_myr;
      return json(working);
    }
    if (path.endsWith('/calculate/')) {
      if (delayedCalculation) await delayedCalculation;
      return json(result);
    }
    if (path.endsWith('/plans/') && request.method() === 'POST') {
      savedPayloads.push(request.postDataJSON());
      const version = savedPayloads.length;
      return json({ plans: [{ plan_id: version === 3 ? 'plan-copy' : 'plan-1', version_id: `version-${version}`, version_number: version === 3 ? 1 : version }] }, 201);
    }
    return json({ detail: `unhandled ${request.method()} ${path}` }, 404);
  });

  await page.goto(`http://127.0.0.1:${server.address().port}/#profit/calculator`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelector('#profitWorkingConfigStatus')?.textContent.includes('已恢复'));
  assert.equal(await page.locator('#profitAdvertisingRebatePercent').inputValue(), '3.00');
  assert.match(await page.locator('#profitStrategyList').innerText(), /服务暂时不可用/);
  strategyErrorStatus = 403;
  await page.locator('[data-profit-strategy-retry]').click();
  await page.waitForFunction(() => document.querySelector('#profitStrategyList').textContent.includes('没有利润策略权限'));
  strategiesUnavailable = false;
  await page.locator('[data-profit-strategy-retry]').click();
  await page.waitForFunction(() => document.querySelectorAll('[data-profit-strategy-id]').length === 2);
  assert.equal(await page.locator('#profitAdvertisingRebatePercent').inputValue(), '3.00', 'retry must not overwrite working input');
  await page.locator('[data-profit-field="sku_name"]').fill('仅本页临时 SKU');
  await page.locator('#profitAdvertisingRebatePercent').fill('12.50');
  await page.waitForFunction(() => document.querySelector('#profitWorkingConfigStatus')?.textContent.includes('已保存'));
  assert.equal(working.config.advertising_rebate_percent, '12.50');

  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelector('#profitWorkingConfigStatus')?.textContent.includes('已恢复'));
  assert.equal(await page.locator('#profitAdvertisingRebatePercent').inputValue(), '12.50');
  assert.notEqual(await page.locator('[data-profit-field="sku_name"]').inputValue(), '仅本页临时 SKU');

  await page.evaluate((input) => window.DongboProfitCalculator.loadCalculation(input, null), historicalInput);
  await page.locator('#profitCalculatorForm button[type="submit"]').click();
  await page.locator('#profitResultPanel:not([hidden])').waitFor();
  for (const width of [1366, 1920, 390]) {
    await page.setViewportSize({width,height:900});
    for (const card of await page.locator('.profit-summary article').all()) {
      assert.ok(await card.evaluate(el => el.scrollWidth <= el.clientWidth + 1), `metric overflow at ${width}`);
    }
  }
  await page.setViewportSize({width:1440,height:900});
  mkdirSync(join(root, '.tmp'), {recursive:true});
  await page.locator('#profitResultPanel').screenshot({path:join(root,'.tmp','profit-results-20261011.png')});
  await page.locator('#profitSaveToPlans').click();
  await page.waitForFunction(() => document.querySelector('#profitFormStatus')?.textContent.includes('已保存'));
  assert.equal(savedPayloads[0].items[0].action, 'new_plan');

  await page.evaluate((input) => window.DongboProfitCalculator.loadCalculation(input, { action: 'new_version', targetPlan: 'plan-1', sourceVersion: 'version-1' }), historicalInput);
  assert.equal(await page.locator('#profitSaveToPlans').textContent(), '保存新版本');
  await page.locator('[data-profit-field="item_price"]').fill('89.90');
  await page.locator('#profitCalculatorForm button[type="submit"]').click();
  await page.locator('#profitSaveToPlans').click();
  await page.waitForFunction(() => document.querySelector('#profitFormStatus')?.textContent.includes('已保存 1 个'));
  assert.equal(savedPayloads[1].items[0].action, 'new_version');
  assert.equal(savedPayloads[1].items[0].target_plan, 'plan-1');
  assert.equal(savedPayloads[1].items[0].item_price, '89.90');

  await page.evaluate((input) => window.DongboProfitCalculator.loadCalculation(input, { action: 'new_version', targetPlan: 'plan-1' }), historicalInput);
  await page.locator('#profitCalculatorForm button[type="submit"]').click();
  await page.locator('#profitSaveAsPlan').click();
  await page.waitForFunction(() => document.querySelector('#profitFormStatus')?.textContent.includes('已保存 1 个'));
  assert.equal(savedPayloads[2].items[0].action, 'new_plan');
  assert.equal(savedPayloads[2].items[0].target_plan, undefined);
  await page.locator('[data-profit-field="item_price"]').fill('99.90');
  assert.equal(await page.locator('#profitResultPanel').isVisible(), false, 'changed inputs invalidate old results');
  let releaseCalculation;
  delayedCalculation = new Promise(resolve => { releaseCalculation = resolve; });
  const sent = page.waitForRequest('**/api/profit-calculator/calculate/');
  await page.locator('#profitCalculatorForm button[type="submit"]').click();
  await sent;
  await page.locator('[data-profit-field="item_price"]').fill('109.90');
  releaseCalculation();
  await page.waitForFunction(() => document.querySelector('#profitFormStatus').textContent.includes('计算期间输入已修改'));
  assert.equal(await page.locator('#profitResultPanel').isVisible(), false, 'late response must not revive outdated results');
  console.log('PASS profit browser workflow: working-config debounce/F5, temporary SKU isolation, save, reopen, recalculate/new version, save-as');
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
