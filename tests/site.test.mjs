import assert from "node:assert/strict";
import test from "node:test";
import worker from "../dist/server/index.js";

const fetchPath = (path, method = "GET") =>
  worker.fetch(new Request(`https://example.test${path}`, { method }));

test("serves the Dongbo cross-border ERP shell", async () => {
  const response = await fetchPath("/");
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /^text\/html/);
  assert.match(html, /东铂跨境/);
  assert.match(html, /商品中心/);
  assert.match(html, /仓配中心/);
  assert.match(html, /竞品监控/);
  assert.doesNotMatch(html, />\s*总览\s*</);
  assert.match(html, /data-module="products"/);
  assert.match(html, /data-module="warehouse"/);
  assert.match(html, /data-module="competitors"/);
  assert.match(html, /data-warehouse-tab="purchase"/);
  assert.match(html, /data-warehouse-tab="inventory"/);
  assert.match(html, /data-warehouse-tab="orders"/);
});

test("contains product, warehouse, order and monitoring workflows", async () => {
  const html = await (await fetchPath("/index.html")).text();
  const requiredIds = [
    "productRows", "productCost", "productImageUrl", "productImageFile",
    "purchaseRows", "purchaseLineList", "receiveForm", "warehouseRows",
    "movementRows", "orderRows", "orderLineList", "returnForm", "competitorRows",
    "historyRows", "trendChart", "changeList", "moduleSidebar", "sidebarToggle",
    "sidebarScrim", "saveProductDraft", "inventoryListPanel", "movementPanel",
  ];

  requiredIds.forEach((id) => assert.match(html, new RegExp(`id="${id}"`)));
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "HTML ids must be unique");
  assert.ok((html.match(/data-side-link/g) || []).length >= 15, "contextual side navigation must expose all ERP workflows");
});

test("serves application assets with the versioned warehouse model", async () => {
  const [script, stylesheet, missing] = await Promise.all([
    fetchPath("/app.js"),
    fetchPath("/styles.css"),
    fetchPath("/missing"),
  ]);

  assert.equal(script.status, 200);
  const scriptText = await script.text();
  assert.match(scriptText, /STATE_VERSION = 5/);
  assert.match(scriptText, /localStorage/);
  assert.match(scriptText, /migrateLegacy/);
  assert.match(scriptText, /compressProductImage/);
  assert.match(scriptText, /purchaseOrders/);
  assert.match(scriptText, /inventoryBalances/);
  assert.match(scriptText, /inventoryMovements/);
  assert.match(scriptText, /reservations/);
  assert.match(scriptText, /receivePurchaseOrder/);
  assert.match(scriptText, /reserveOrder/);
  assert.match(scriptText, /shipOrder/);
  assert.match(scriptText, /receiveSalesReturn/);
  assert.match(scriptText, /reserved > balance\.onHand/);
  assert.match(scriptText, /modal\.classList\.add\('open'\)/);
  assert.match(scriptText, /modal\.classList\.remove\('open'\)/);
  assert.doesNotMatch(scriptText, /modal-backdrop\.show/);
  assert.match(scriptText, /saveProductFromForm/);
  assert.match(scriptText, /draft && current && current\.kind === 'own' && hasBusinessReferences\(current\.id\)/);
  assert.match(scriptText, /handleSideLink/);
  assert.match(scriptText, /route \+= '\/low'/);
  assert.match(scriptText, /inventorySection = parts\[2\] === 'movements'/);
  assert.equal(stylesheet.status, 200);
  assert.match(stylesheet.headers.get("content-type"), /^text\/css/);
  const stylesheetText = await stylesheet.text();
  assert.match(stylesheetText, /\.primary-nav/);
  assert.match(stylesheetText, /\.module-sidebar/);
  assert.match(stylesheetText, /\.modal-backdrop\.open/);
  assert.doesNotMatch(stylesheetText, /\.modal-backdrop\.show/);
  assert.equal(missing.status, 404);
});

test("HEAD requests return headers without a response body", async () => {
  const response = await fetchPath("/", "HEAD");
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
});
