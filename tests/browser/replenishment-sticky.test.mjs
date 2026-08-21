import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync } from 'node:fs';
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
    localStorage.setItem('dongbo-crossborder.v1', JSON.stringify({
      version: 5, revision: 5,
      warehouses: [{ id: 'warehouse-main', code: 'MAIN', name: '验收仓', type: 'overseas', country: 'MY', timezone: 'Asia/Kuala_Lumpur', active: true }],
      products, inventoryBalances: balances,
      ui: { module: 'warehouse', warehouseTab: 'replenishment' },
    }));
  }, { products, balances });
  const response = await page.goto(`http://127.0.0.1:${port}/#warehouse/replenishment`);
  assert.ok(response && response.ok(), `local ERP returned ${response && response.status()}`);
  try {
    await page.locator('#replenishmentRows tr').first().waitFor({ state: 'visible', timeout: 10000 });
  } catch (error) {
    throw new Error(`replenishment did not render: ${await page.locator('body').innerText()}`, { cause: error });
  }
  assert.equal(await page.locator('#replenishmentRows tr').count(), 28);

  await page.evaluate(() => {
    const table = document.querySelector('#replenishmentTable');
    window.scrollTo(0, table.getBoundingClientRect().top + window.scrollY + 120);
  });
  const sticky = page.locator('.replenishment-sticky-header');
  await sticky.waitFor({ state: 'visible' });

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

  await page.locator('#replenishmentTableWrap').evaluate((node) => { node.scrollLeft = 300; node.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(50);
  assertAligned(await geometry());

  await page.getByRole('button', { name: /商品中心/ }).click();
  assert.equal(await sticky.isVisible(), false, 'sticky header must hide after switching modules');
  console.log('PASS replenishment sticky header 1440x900: vertical stickiness, horizontal sync, <=2px alignment, product containment, route hide');
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
