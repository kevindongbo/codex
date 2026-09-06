import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, extname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const require = process.env.CODEX_NODE_MODULES
  ? createRequire(pathToFileURL(join(process.env.CODEX_NODE_MODULES, 'package.json')))
  : createRequire(import.meta.url);
const { chromium } = require('playwright');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
const server = createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const file = join(root, pathname === '/' ? 'index.html' : pathname);
  try {
    if (!file.startsWith(root)) throw new Error('Invalid path');
    const content = await readFile(file);
    res.writeHead(200, { 'content-type': mime[extname(file)] || 'application/octet-stream' }).end(content);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE || (existsSync(edge) ? edge : undefined) });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('response', response => { if (response.status() >= 400) console.log('HTTP', response.status(), response.url()); });
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  // Presentation fixtures; calculation behavior has its own browser suite.
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
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const module of ['products', 'warehouse', 'analytics', 'creators', 'profit', 'selection']) {
      await page.locator(`.primary-nav-item[data-module="${module}"]`).click();
      await page.evaluate(() => document.getAnimations().forEach(animation => animation.finish()));
      if (viewport.width < 900) await page.locator('#sidebarToggle').click();
      assert.equal(await page.locator(`[data-sidebar-module="${module}"]`).isVisible(), true, `${module} sidebar at ${viewport.width}`);
      assert.equal(await page.locator('.sidebar-module:visible').count(), 1);
      if (module === 'analytics' || module === 'creators') {
        const control = page.locator(module === 'analytics' ? '#analyticsDays' : '#creatorSearch');
        assert.ok((await control.boundingBox()).height >= 40, `${module} filter is usable at ${viewport.width}`);
      }
      if (viewport.width < 900) await page.locator('#sidebarScrim').click({ position: { x: viewport.width - 5, y: 200 } });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${module}: page-wide overflow at ${viewport.width}`);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  const opener = page.locator('#runtimeStateButton');
  await opener.click();
  await page.waitForTimeout(60);
  assert.ok(await page.evaluate(() => document.querySelector('#sessionModal').contains(document.activeElement)));
  const focusables = page.locator('#sessionModal button:visible:not(:disabled), #sessionModal input:visible:not(:disabled), #sessionModal select:visible:not(:disabled), #sessionModal a[href]:visible');
  await focusables.last().focus();
  await page.keyboard.press('Tab');
  assert.ok(await page.evaluate(() => document.querySelector('#sessionModal').contains(document.activeElement)), 'Tab stays inside dialog');
  await page.keyboard.press('Shift+Tab');
  assert.ok(await page.evaluate(() => document.querySelector('#sessionModal').contains(document.activeElement)), 'Shift+Tab stays inside dialog');
  await page.evaluate(() => askConfirm('测试二次确认，不执行业务操作', () => { throw new Error('must not submit'); }));
  await page.keyboard.press('Tab');
  assert.ok(await page.evaluate(() => document.querySelector('#confirmBar').contains(document.activeElement)), 'confirmation is keyboard-accessible above dialog');
  assert.ok(await page.evaluate(() => Number(getComputedStyle(document.querySelector('#confirmBar')).zIndex) > Number(getComputedStyle(document.querySelector('#sessionModal')).zIndex)));
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#sessionModal').isVisible(), true, 'Escape dismisses confirmation before its parent dialog');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#sessionModal').isVisible(), false);
  assert.equal(await opener.evaluate(el => el === document.activeElement), true, 'focus restored to opener');
  await mkdir(join(root, '.tmp', 'erp-usability'), { recursive: true });
  await page.locator('[data-module="analytics"]').click();
  await page.screenshot({ path: join(root, '.tmp', 'erp-usability', 'analytics-desktop.png'), animations: 'disabled' });
  assert.deepEqual(errors, [], 'no browser errors');
  console.log('PASS: 18 module/viewport combinations, no page overflow, dialog focus loop and restoration, zero browser errors');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
