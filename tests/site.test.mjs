import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import worker from "../dist/server/index.js";

const fetchPath = (path, method = "GET") =>
  worker.fetch(new Request(`https://example.test${path}`, { method }));

test("serves the Dongbo cross-border Chinese operations shell", async () => {
  const response = await fetchPath("/");
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /^text\/html/);
  assert.match(html, /东铂跨境/);
  assert.match(html, /商品中心/);
  assert.match(html, /仓配中心/);
  assert.match(html, /竞品监控/);
  assert.match(html, /智能选品/);
  assert.doesNotMatch(html, />\s*总览\s*</);
  assert.match(html, /data-module="products"/);
  assert.match(html, /data-module="warehouse"/);
  assert.match(html, /data-module="competitors"/);
  assert.match(html, /data-module="selection"/);
  assert.match(html, /property="og:title" content="东铂跨境 · 跨境电商运营管理系统"/);
  assert.match(html, /账号与权限/);
  assert.match(html, /主账号可统一管理所有内部成员/);
  assert.doesNotMatch(html, /DONGBO COMMERCE|PRODUCT MASTER|FULFILLMENT CENTER|REPLENISHMENT POLICY|DATA & TEAM/);
  assert.match(html, /assets\/dongbo-erp-mark\.png/);
  assert.match(html, /data-warehouse-tab="purchase"/);
  assert.match(html, /data-warehouse-tab="inventory"/);
  assert.match(html, /data-warehouse-tab="transfers"/);
  assert.match(html, /data-warehouse-tab="replenishment"/);
  assert.match(html, /data-warehouse-tab="orders"/);
});

test("versions browser assets so production never mixes new markup with cached scripts", async () => {
  const html = await (await fetchPath("/index.html")).text();
  assert.match(html, /styles\.css\?v=20260723-competitor-monitoring-1/);
  assert.match(html, /team\.js\?v=20260723-purchase-create-1/);
  assert.match(html, /app\.js\?v=20260723-purchase-create-1/);
  assert.match(html, /for="productImageFile">从电脑选择<\/label>/);
  assert.match(html, /id="productImageStatus" aria-live="polite"/);
});

test("contains product, warehouse, order and monitoring workflows", async () => {
  const html = await (await fetchPath("/index.html")).text();
  assert.match(html, /id="purchaseSkuSearch"/);
  assert.match(html, /id="purchaseSkuPicker"/);
  assert.match(html, /id="openReceiveModal"/);
  const requiredIds = [
    "productRows", "productSkuEditor", "productSkuList", "addProductSku", "productImageUrl", "productImageFile",
    "purchaseRows", "purchaseLineList", "openReceiveModal", "receivePurchaseId", "receiveForm", "warehouseRows",
    "movementRows", "orderRows", "orderLineList", "returnForm", "competitorRows",
    "historyRows", "trendChart", "changeList", "moduleSidebar", "sidebarToggle",
    "sidebarScrim", "saveProductDraft", "inventoryListPanel", "movementPanel",
    "runtimeStateButton", "connectionBanner", "sessionModal", "teamLoginForm",
    "ownerVerificationForm", "teamWarehouse", "accountManagerPanel", "internalAccountForm",
    "ownerPasswordChangeForm", "returnCondition",
    "downloadLocalBackup", "localBackupFile", "chooseLocalBackup", "migrationPreview",
    "commitLocalMigration",
    "selectionApiState", "selectionKeywordPanel", "selectionKeywordForm",
    "selectionPlatform", "selectionRegion", "selectionListingTime", "selectionKeyword",
    "selectionKeywordResults", "selectionReportPanel", "selectionReportForm",
    "selectionChosenKeyword", "selectionReportButton", "selectionSummary", "selectionProducts",
    "warehouseSwitcher", "manageWarehouses", "warehouseModal", "warehouseForm",
    "warehouseCode", "warehouseName", "warehouseType", "warehouseCountry",
    "warehouseTimezone", "warehouseContact", "warehouseAddress",
    "warehouseCanReceive", "warehouseCanShip", "warehouseManageRows",
    "transferRows", "transferModal", "transferForm", "transferDestination",
    "transferLineProduct", "transferLineQty", "transferLineList",
    "replenishmentRows", "refreshReplenishment", "openReplenishmentSettings", "replenishmentPolicyModal",
    "replenishmentPolicyForm", "policyLeadDays", "policyReviewDays",
    "policyTargetDays", "policyMoq", "policyPackSize", "policySafetyStock",
    "replenishmentSettingsModal", "replenishmentSettingsForm", "settingSafetyDays", "settingLeadDays",
    "aiProviderId", "aiProviderParameters", "aiProviderEnabled", "resetAIProvider", "aiUsageSummary",
    "aiRecommendationForm", "aiRecommendationProvider", "aiRecommendationKind", "aiRecommendationInput",
    "aiRecommendationRows", "aiInvocationRows",
    "snapshotAdvanced", "competitorAddOwnProduct", "competitorTableAddOwn",
    "competitorOwnProductModal", "monitoringProductSearch", "monitoringProductSelectAll",
    "monitoringProductPicker", "confirmAddOwnMonitoring",
  ];

  requiredIds.forEach((id) => assert.match(html, new RegExp(`id="${id}"`)));
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "HTML ids must be unique");
  assert.ok((html.match(/data-side-link/g) || []).length >= 15, "contextual side navigation must expose all ERP workflows");
  assert.match(html, /仓库数量不受限制/);
  assert.match(html, /一次确认完成整单库存校验、扣库与出库流水/);
  assert.match(html, /已有基准后只需修改累计销量/);
  assert.match(html, /其他公开数据（已自动沿用，有变化时再修改）/);
  assert.match(html, /同一个商品可维护多个颜色、尺寸或套装 SKU/);
  assert.match(html, />确认并出库</);
});

test("keeps multi-line purchase creation and batch receiving usable for long orders", async () => {
  const [html, css] = await Promise.all([
    (await fetchPath("/index.html")).text(),
    (await fetchPath("/styles.css")).text(),
  ]);
  assert.match(html, /id="purchaseLineList"/);
  assert.match(css, /\.purchase-sku-picker \{ max-height: 340px; overflow-y: auto;/);
  assert.match(html, /id="receivePurchaseId"/);
  assert.match(html, /id="receiveLineList"/);
  assert.match(html, /只填写实际到货的数量/);
  assert.match(css, /\.purchase-line-list, \.receive-line-list \{ max-height: 300px; overflow-y: auto;/);
});

test("serves application assets with local and team data modes", async () => {
  const [script, teamScript, runtimeConfig, stylesheet, socialImage, missing] = await Promise.all([
    fetchPath("/app.js"),
    fetchPath("/team.js"),
    fetchPath("/runtime-config.js"),
    fetchPath("/styles.css"),
    fetchPath("/assets/og-dongbo-crossborder.png"),
    fetchPath("/missing"),
  ]);

  assert.equal(script.status, 200);
  const scriptText = await script.text();
  assert.match(scriptText, /STATE_VERSION = 6/);
  assert.match(scriptText, /localStorage/);
  assert.match(scriptText, /migrateLegacy/);
  assert.match(scriptText, /compressProductImage/);
  assert.match(scriptText, /productImageStatus/);
  assert.doesNotMatch(scriptText, /chooseProductImage['"]\)\.disabled\s*=\s*TEAM_MODE/);
  assert.match(scriptText, /purchaseOrders/);
  assert.match(scriptText, /Unable to load purchase members; using the operator fallback\./);
  assert.match(scriptText, /openPurchaseEditor\(\)\.catch/);
  assert.match(scriptText, /delete-purchase/);
  assert.match(scriptText, /teamGateway\.deletePurchase/);
  assert.match(scriptText, /teamGateway\.deleteProduct\(product, true\)/);
  assert.match(scriptText, /addOwnProductsToMonitoring/);
  assert.match(scriptText, /removeMonitoringProfile/);
  assert.match(scriptText, /remove-own-monitoring/);
  assert.match(scriptText, /delete-competitor/);
  assert.match(scriptText, /teamGateway\.deleteStockBalance\(balance, true\)/);
  assert.doesNotMatch(scriptText, /团队版会保留本店 SKU 主档/);
  assert.match(scriptText, /inventoryBalances/);
  assert.match(scriptText, /inventoryMovements/);
  assert.match(scriptText, /reservations/);
  assert.match(scriptText, /receivePurchaseOrder/);
  assert.match(scriptText, /reserveOrder/);
  assert.match(scriptText, /shipOrder/);
  assert.match(scriptText, /confirmAndShipOrder/);
  assert.match(scriptText, /receiveSalesReturn/);
  assert.match(scriptText, /normalizeWarehouse/);
  assert.match(scriptText, /currentWarehouseId/);
  assert.match(scriptText, /stockTransfers/);
  assert.match(scriptText, /dispatchTransfer/);
  assert.match(scriptText, /receiveTransfer/);
  assert.match(scriptText, /replenishmentPolicies/);
  assert.match(scriptText, /localReplenishmentRecommendation/);
  assert.match(scriptText, /velocity7 \* 0\.5 \+ velocity15 \* 0\.3 \+ velocity30 \* 0\.2/);
  assert.match(scriptText, /safetyMarginRatio/);
  assert.match(scriptText, /calculation-basis/);
  assert.match(scriptText, /fillSnapshotHint/);
  assert.match(scriptText, /reserved > balance\.onHand/);
  assert.match(scriptText, /modal\.classList\.add\('open'\)/);
  assert.match(scriptText, /modal\.classList\.remove\('open'\)/);
  assert.doesNotMatch(scriptText, /modal-backdrop\.show/);
  assert.match(scriptText, /saveProductFromForm/);
  assert.match(scriptText, /draft && current && current\.kind === 'own' && hasBusinessReferences\(current\.id\)/);
  assert.match(scriptText, /handleSideLink/);
  assert.match(scriptText, /route \+= '\/low'/);
  assert.match(scriptText, /inventorySection = parts\[2\] === 'movements'/);
  assert.match(scriptText, /executeTeamCommand/);
  assert.match(scriptText, /initializeTeamMode/);
  assert.match(scriptText, /searchSelectionKeywords/);
  assert.match(scriptText, /generateSelectionReport/);
  assert.match(scriptText, /importSelectionProduct/);
  assert.doesNotMatch(scriptText, /ALPHASHOP_(?:ACCESS|SECRET)_KEY/);
  assert.equal(teamScript.status, 200);
  const teamText = await teamScript.text();
  assert.match(teamText, /class TeamGateway/);
  assert.match(teamText, /X-Organization-ID/);
  assert.match(teamText, /idempotencyKey/);
  assert.match(teamText, /receive-from-order/);
  assert.match(teamText, /confirmAndShipOrder/);
  assert.match(teamText, /quick-sales/);
  assert.match(teamText, /competitors\/add-own-products/);
  assert.match(teamText, /stock-transfers/);
  assert.match(teamText, /replenishment/);
  assert.match(teamText, /local-imports\/validate/);
  assert.match(teamText, /local-imports\/commit/);
  assert.match(teamText, /product-selection\/keywords/);
  assert.match(teamText, /product-selection\/report/);
  assert.match(teamText, /force-delete/);
  assert.equal(runtimeConfig.status, 200);
  assert.match(await runtimeConfig.text(), /mode: 'local'/);
  assert.equal(stylesheet.status, 200);
  assert.match(stylesheet.headers.get("content-type"), /^text\/css/);
  const stylesheetText = await stylesheet.text();
  assert.match(stylesheetText, /\.primary-nav/);
  assert.match(stylesheetText, /\.module-sidebar/);
  assert.match(stylesheetText, /\.modal-backdrop\.open/);
  assert.doesNotMatch(stylesheetText, /\.modal-backdrop\.show/);
  assert.match(stylesheetText, /--navy:\s*#16324f/i);
  assert.match(stylesheetText, /--teal:\s*#0f8b8d/i);
  assert.match(stylesheetText, /--blue:\s*#3b82f6/i);
  assert.match(stylesheetText, /--amber:\s*#f59e0b/i);
  assert.match(stylesheetText, /--canvas:\s*#f5f7fa/i);
  assert.match(stylesheetText, /\.warehouse-switcher/);
  assert.match(stylesheetText, /\.warehouse-directory/);
  assert.match(stylesheetText, /\.advanced-fields/);
  assert.match(stylesheetText, /\.replenishment-(?:grid|card)/);
  assert.equal(socialImage.status, 200);
  assert.equal(socialImage.headers.get("content-type"), "image/png");
  const socialImageBytes = new Uint8Array(await socialImage.arrayBuffer());
  assert.deepEqual([...socialImageBytes.slice(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.equal(missing.status, 404);
});

test("HEAD requests return headers without a response body", async () => {
  const response = await fetchPath("/", "HEAD");
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
});

test("Docker team deployment serves the API adapter and runtime mode", async () => {
  const [compose, caddy] = await Promise.all([
    readFile(new URL("../docker-compose.yml", import.meta.url), "utf8"),
    readFile(new URL("../deploy/Caddyfile", import.meta.url), "utf8"),
  ]);
  assert.match(compose, /\.\/team\.js:\/srv\/www\/team\.js:ro/);
  assert.match(compose, /DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE/);
  assert.match(caddy, /mode: "team"/);
  assert.match(caddy, /apiBase: "\/api"/);
  assert.match(caddy, /Cache-Control "no-store"/);
});
