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
  const pageErrors = [];
  const consoleErrors = [];
  await page.route('**/api/replenishment-settings/**', route => route.fulfill({ json: { results: [] } }));
  await page.route('**/api/profit-calculator/**', route => {
    const path = new URL(route.request().url()).pathname;
    const fixtures = {
      '/api/profit-calculator/config/': { categories: [], category_tree: [] },
      '/api/profit-calculator/strategies/': [],
      '/api/profit-calculator/working-config/': { revision: 1, config: {}, rate_mode: 'manual', manual_cny_per_myr: '1.68', manual_usd_per_myr: '0.235' },
      '/api/profit-calculator/exchange-rates/': { cny_per_myr: '1.68', usd_per_myr: '0.235', source: 'test' },
    };
    assert.ok(Object.hasOwn(fixtures, path), `unexpected API request ${path}`);
    return route.fulfill({ json: fixtures[path] });
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  const products = Array.from({ length: 28 }, (_, index) => ({
    id: `product-${index}`, kind: 'own', name: `浏览器验收商品 ${index + 1}`,
    sku: `QA-STICKY-${String(index + 1).padStart(3, '0')}`, salesCurrency: 'MYR',
    costCurrency: 'CNY', standardCost: 10 + index, safetyStock: 5, status: 'active',
    image: 'assets/product-placeholder.svg', createdAt: '2026-08-20T00:00:00Z', updatedAt: '2026-08-20T00:00:00Z',
  }));
  const balances = products.map((product) => ({
    warehouseId: 'warehouse-main', productId: product.id, onHand: 20, reserved: 0,
    purchasedPendingShipment: 0, inTransit: 0, inboundTotal: 0,
  }));
  await page.addInitScript(({ products, balances }) => {
    window.DONGBO_CONFIG = { mode: 'team', apiBase: '/api' };
    localStorage.setItem('dongbo-crossborder.v1', JSON.stringify({
      version: 5, revision: 5,
      warehouses: [{ id: 'warehouse-main', code: 'MAIN', name: '验收仓', type: 'overseas', country: 'MY', timezone: 'Asia/Kuala_Lumpur', active: true }],
      products, inventoryBalances: balances,
      ui: { module: 'warehouse', warehouseTab: 'replenishment' },
    }));
  }, { products, balances });
  const response = await page.goto(`http://127.0.0.1:${port}/#warehouse/replenishment`);
  assert.ok(response && response.ok(), `local ERP returned ${response && response.status()}`);
  // V3 removed local replenishment calculation. Supply server-shaped results
  // for this layout test, without introducing a parallel demand algorithm.
  await page.evaluate(({ products, balances }) => {
    closeModal('sessionModal');
    state = normalizeV5({
      warehouses: [{ id: 'warehouse-main', code: 'MAIN', name: '验收仓', active: true }, { id: 'warehouse-other', code: 'OTHER', name: '其他仓', active: true }],
      products, inventoryBalances: balances,
      replenishmentRecommendations: products.map((product, index) => ({
        product_id: product.id, sku: `sku-${index}`, weighted_daily_velocity: '2',
        available: '20', in_transit: '10', inventory_position: '30',
        available_days_of_cover: '10', suggested_order_quantity: '30',
        alert_level: index === 27 ? 'urgent' : 'healthy', lead_days: '15',
        demand: { daily_velocity: '2', breakdown: { '30': { true_outbound: '60' } } },
      })),
      ui: { module: 'warehouse', warehouseTab: 'replenishment' },
    });
    teamGateway.warehouses = state.warehouses;
    teamGateway.warehouseId = 'warehouse-main';
    render();
  }, { products, balances });
  try {
    await page.locator('#replenishmentRows tr').first().waitFor({ state: 'visible', timeout: 10000 });
  } catch (error) {
    throw new Error(`replenishment did not render: ${await page.locator('body').innerText()}`, { cause: error });
  }
  assert.equal(await page.locator('#replenishmentRows tr').count(), 28);
  assert.match(await page.locator('#replenishmentRows tr').first().innerText(), /浏览器验收商品 28/, 'urgent recommendations appear first');
  const source = page.locator('#replenishmentRows tr').first().locator('.replenishment-source');
  assert.equal(await source.locator('strong').innerText(), '60 件', 'use backend true_outbound, not a nonexistent quantity field');
  const quantityBox = await source.locator('strong').boundingBox();
  const detailBox = await source.locator('button').boundingBox();
  assert.ok(detailBox.y >= quantityBox.y + quantityBox.height, 'quantity above detail button');
  await page.locator('#replenishmentRows input[type=checkbox]').first().check();
  await page.getByRole('button', { name: '批量调整参数', exact: true }).click();
  await page.locator('#replenishmentBatchPolicyModal').waitFor({ state: 'visible' });
  assert.deepEqual(await page.locator('#batchPolicyPrimaryWarehouse option').evaluateAll(nodes => nodes.map(n => n.value)), ['warehouse-main']);
  assert.match(await page.locator('#batchPolicyPrimaryWarehouse').innerText(), /当前仓库/);
  await page.locator('#replenishmentBatchPolicyModal').getByRole('button', { name: '取消', exact: true }).click();

  await page.evaluate(() => {
    const table = document.querySelector('#replenishmentTable');
    window.scrollTo(0, table.getBoundingClientRect().top + window.scrollY + 120);
  });
  const sticky = page.locator('.replenishment-sticky-header');
  await sticky.waitFor({ state: 'visible' });
  assert.equal(await sticky.locator('[id]').count(), 0, 'cloned header has no duplicate IDs');
  assert.equal(await sticky.evaluate(node => node.inert), true, 'visual clone is not keyboard interactive');
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.replenishment-sticky-header th:nth-child(2)')).textAlign), 'left');
  assert.equal(await page.locator('#replenishmentTable th').nth(1).evaluate(n => getComputedStyle(n).textAlign), 'left');

  const geometry = async () => page.evaluate(() => {
    const clone = Array.from(document.querySelectorAll('.replenishment-sticky-header th')).map((node) => node.getBoundingClientRect());
    const cells = Array.from(document.querySelectorAll('#replenishmentRows tr:first-child td')).map((node) => node.getBoundingClientRect());
    const product = document.querySelector('#replenishmentRows tr:first-child .product-cell').getBoundingClientRect();
    return {
      clone: clone.map((rect) => ({ left: rect.left, right: rect.right })),
      cells: cells.map((rect) => ({ left: rect.left, right: rect.right })),
      product: { left: product.left, right: product.right },
    };
  });
  const assertAligned = (state) => {
    state.clone.forEach((header, index) => {
      assert.ok(Math.abs(header.left - state.cells[index].left) <= 2, `column ${index} left mismatch`);
      assert.ok(Math.abs(header.right - state.cells[index].right) <= 2, `column ${index} right mismatch`);
    });
    assert.ok(state.product.left >= state.cells[1].left && state.product.right <= state.cells[1].right, 'product media must remain inside 商品 column');
  };
  assertAligned(await geometry());
  mkdirSync(join(root, '.tmp/replenishment-layout'), { recursive: true });
  await page.screenshot({ path: join(root, '.tmp/replenishment-layout/1440.png') });

  await page.locator('#replenishmentTableWrap').evaluate((node) => { node.scrollLeft = 300; node.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(50);
  assertAligned(await geometry());

  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.locator('#replenishmentTableWrap').evaluate((node) => { node.scrollLeft = 0; node.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(50);
  assertAligned(await geometry());
  assert.deepEqual(pageErrors, [], `pageerror: ${pageErrors.join('\n')}`);
  await page.screenshot({ path: join(root, '.tmp/replenishment-layout/1920.png') });
  assert.deepEqual(consoleErrors, [], `console.error: ${consoleErrors.join('\n')}`);

  await page.getByRole('button', { name: /商品中心/ }).click();
  assert.equal(await sticky.isVisible(), false, 'sticky header must hide after switching modules');
  console.log('PASS replenishment sticky header 1440x900 + 1920x1080: vertical stickiness, horizontal sync, <=2px alignment, product containment, zero pageerror and console.error, route hide');
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
