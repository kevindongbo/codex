import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = new URL('../../', import.meta.url).pathname.replace(/^\/(.:\/)/, '$1');
const moduleRoot = process.env.CODEX_NODE_MODULES;
const require = moduleRoot
  ? createRequire(pathToFileURL(join(moduleRoot, 'package.json')))
  : createRequire(import.meta.url);
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

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
const installedEdge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const executablePath = process.env.BROWSER_EXECUTABLE || (existsSync(installedEdge) ? installedEdge : undefined);
const browser = await chromium.launch({ headless: true, executablePath });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const requests = [];
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/replenishment/batch-policy/') {
      requests.push(route.request().postDataJSON());
      return route.fulfill({ json: { updated: 1 } });
    }
    const fixtures = {
      '/api/profit-calculator/config/': { categories: [], category_tree: [] },
      '/api/profit-calculator/strategies/': [],
      '/api/profit-calculator/working-config/': { revision: 1, config: {}, rate_mode: 'manual', manual_cny_per_myr: '1.68', manual_usd_per_myr: '0.235' },
      '/api/profit-calculator/exchange-rates/': { cny_per_myr: '1.68', usd_per_myr: '0.235', source: 'test' },
    };
    if (!Object.hasOwn(fixtures, path) && route.request().method() === 'GET') return route.fulfill({ json: { results: [] } });
    assert.ok(Object.hasOwn(fixtures, path), 'unexpected API ' + path);
    return route.fulfill({ json: fixtures[path] });
  });
  await page.addInitScript(() => { window.DONGBO_CONFIG = { mode: 'team', apiBase: '/api' }; });
  await page.goto('http://127.0.0.1:' + port + '/');
  await page.evaluate(() => {
    closeModal('sessionModal');
    const product = { id: 'p1', skuId: '33333333-3333-4333-8333-333333333333', kind: 'own', name: '主力仓测试', sku: 'QA', status: 'active', salesCurrency: 'MYR', costCurrency: 'CNY', standardCost: 2, image: 'assets/product-placeholder.svg' };
    state = normalizeV5({ products: [product], ui: { module: 'warehouse', warehouseTab: 'replenishment' },
      replenishmentRecommendations: [{ product_id: 'p1', sku: product.skuId, weighted_daily_velocity: '2', suggested_order_quantity: '0', primary_warehouse: '11111111-1111-4111-8111-111111111111', profile_config: {}, demand: { breakdown: { '30': { true_outbound: 60 } } } }] });
    teamGateway.user = { is_owner: true };
    teamGateway.organizationId = 'qa';
    teamGateway.warehouses = [{ id: '11111111-1111-4111-8111-111111111111', code: 'SOURCE', name: '原仓', active: true }, { id: '22222222-2222-4222-8222-222222222222', code: 'TARGET', name: '目标仓', active: true }];
    teamGateway.warehouseId = teamGateway.warehouses[0].id;
    // Refresh fixture only; the actual save uses TeamGateway -> intercepted HTTP.
    teamGateway.loadState = async () => state;
    render();
  });
  await page.locator('[data-action="edit-replenishment"]').first().click();
  await page.locator('#policyPrimaryWarehouse').selectOption('22222222-2222-4222-8222-222222222222');
  await page.locator('#policySafetyStock').fill('');
  await page.getByRole('button', { name: '保存并重新计算', exact: true }).click();
  await page.locator('#replenishmentPolicyModal').waitFor({ state: 'hidden' });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].fields.primary_warehouse, '22222222-2222-4222-8222-222222222222');
  assert.equal(Object.hasOwn(requests[0].fields, 'safety_stock'), false);
  assert.deepEqual(errors, []);

  const local = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  local.on('pageerror', e => errors.push(e.message));
  local.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await local.route('**/api/profit-calculator/**', route => route.fulfill({ json: { categories: [], category_tree: [], config: {}, revision: 1 } }));
  await local.addInitScript(() => { window.DONGBO_CONFIG = { mode: 'local' }; });
  await local.goto('http://127.0.0.1:' + port + '/');
  await local.evaluate(() => {
    closeModal('sessionModal');
    const product = { id: 'p1', kind: 'own', name: '采购测试', sku: 'QA', status: 'active', salesCurrency: 'MYR', costCurrency: 'CNY', standardCost: 2, image: 'assets/product-placeholder.svg' };
    state = normalizeV5({ products: [product], warehouses: [{ id: 'qa', name: 'QA', code: 'QA', active: true }], ui: { module: 'warehouse', warehouseTab: 'purchase', warehouseId: 'qa' },
      purchaseOrders: ['A', 'B', 'C'].map((id, i) => ({ id, number: 'PO-' + id, status: 'draft', warehouseId: 'qa', orderedAt: '2026-09-10', expectedAt: '2026-09-20', createdAt: '2026-09-0' + (9-i), lines: [{ id: 'line-' + id, productId: 'p1', orderedQty: 10, receivedQty: 0, unitCost: 2 }], shipments: i === 1 ? [] : [{ id: 'pack-' + id, trackingNumber: '', internationalTrackingNumber: 'INT-SHARED', lines: [] }] })) });
    render();
  });
  await local.evaluate(() => { purchaseFilter = 'all'; renderPurchases(); });
  assert.deepEqual(await local.locator('#purchaseRows tr td:first-child strong').allTextContents(), ['PO-A', 'PO-C', 'PO-B']);
  const header = await local.locator('#purchaseRows').evaluate(n => n.closest('table').tHead.innerText);
  assert.ok(header.includes('国内物流单号') && header.includes('国际物流单号'));
  assert.ok(header.includes('商品明细') && !header.includes('采购 / 已收'));
  await local.evaluate(() => {
    state.products.push({ ...state.products[0], id: 'p2', name: '第二款商品', sku: 'QA-SECOND' });
    state.purchaseOrders.find(order => order.id === 'A').lines.push({ id: 'line-A2', productId: 'p2', orderedQty: 7, receivedQty: 2, unitCost: 3 });
    renderPurchases();
  });
  const details = local.locator('#purchaseRows .purchase-product-details');
  assert.equal(await details.count(), 1);
  assert.equal(await local.locator('#purchaseRows .product-quantity:visible').count(), 0);
  for (const width of [1440, 1920]) {
    await local.setViewportSize({ width, height: width === 1440 ? 900 : 1080 });
    for (const expanded of [true, false]) {
      await details.locator('summary').click();
      assert.equal(await details.evaluate(n => n.open), expanded);
      assert.equal(await local.locator('#purchaseRows .product-quantity:visible').count(), expanded ? 2 : 0);
      if (expanded) {
        assert.deepEqual(await details.locator('.product-quantity').allTextContents(), ['× 10', '× 7']);
        await local.screenshot({ path: join(root, `.tmp/purchase-details-expanded-${width}.png`) });
      }
      for (const scroll of [0, 10000]) {
        const alignment = await local.locator('.purchase-orders-table').evaluate((table, scroll) => {
          table.parentElement.scrollLeft = scroll;
          const heads = [...table.tHead.rows[0].cells];
          return [...table.tBodies[0].rows].every(row => row.cells.length === heads.length && heads.every((head, i) => {
            const h = head.getBoundingClientRect(), c = row.cells[i].getBoundingClientRect();
            return Math.abs(h.x-c.x) <= 1 && Math.abs(h.width-c.width) <= 1 && getComputedStyle(head).textAlign === getComputedStyle(row.cells[i]).textAlign;
          }));
        }, scroll);
        assert.ok(alignment, `purchase columns aligned at ${width}, expanded=${expanded}, scroll=${scroll}`);
      }
    }
    await local.locator('.purchase-orders-table').evaluate(t => { t.parentElement.scrollLeft = 0; });
    await local.screenshot({ path: join(root, `.tmp/purchase-details-${width}.png`) });
  }
  await local.locator('[data-action="edit-purchase"][data-id="B"]').click();
  await local.locator('#purchaseModal').getByRole('button', { name: /保存/, exact: false }).last().click();
  await local.locator('#purchaseModal').waitFor({ state: 'hidden' });
  await local.locator('[data-action="edit-purchase"][data-id="B"]').click();
  await local.locator('#purchaseTrackingNumber').fill('CN-LATER');
  await local.locator('#purchaseInternationalTrackingNumber').fill('INT-SHARED');
  await local.locator('#purchaseModal').getByRole('button', { name: /保存/, exact: false }).last().click();
  await local.locator('#purchaseModal').waitFor({ state: 'hidden' });
  assert.ok((await local.locator('#purchaseRows').innerText()).includes('CN-LATER'));
  await local.locator('[data-action="edit-purchase"][data-id="B"]').click();
  assert.equal(await local.locator('[data-purchase-tracking-field="domesticTrackingNumber"]').inputValue(), 'CN-LATER');
  assert.equal(await local.locator('[data-purchase-tracking-field="internationalTrackingNumber"]').inputValue(), 'INT-SHARED');
  await local.screenshot({ path: join(root, '.tmp/purchase-tracking-editor.png') });
  assert.deepEqual(errors, []);
  console.log('PASS: cross-warehouse UUID save/blank safety; purchase blank save, two-way tracking, grouping; details expand/collapse, single SKU hides quantity, 10-column alignment/scroll at 1440x900 and 1920x1080; pageerror=0 console.error=0');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
