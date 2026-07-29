
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
  assert.match(html, /涓滈搨璺ㄥ/);
  assert.match(html, /鍟嗗搧涓績/);
  assert.match(html, /浠撻厤涓績/);
  assert.match(html, /绔炲搧鐩戞帶/);
  assert.match(html, /鏅鸿兘閫夊搧/);
  assert.doesNotMatch(html, />\s*鎬昏\s*</);
  assert.match(html, /data-module="products"/);
  assert.match(html, /data-module="warehouse"/);
  assert.match(html, /data-module="competitors"/);
  assert.match(html, /data-module="selection"/);
  assert.match(html, /property="og:title" content="涓滈搨璺ㄥ 路 璺ㄥ鐢靛晢杩愯惀绠＄悊绯荤粺"/);
  assert.match(html, /璐﹀彿涓庢潈闄?);
  assert.match(html, /涓昏处鍙峰彲缁熶竴绠＄悊鎵€鏈夊唴閮ㄦ垚鍛?);
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
  assert.match(html, /styles\.css\?v=20260729-profit-input-align-8/);
  assert.match(html, /team\.js\?v=20260728-profit-calculator-server-1/);
  assert.match(html, /profit-calculator\.js\?v=20260729-profit-input-align-8/);
  assert.match(html, /app\.js\?v=20260729-profit-input-align-8/);
  assert.match(html, /for="productImageFile">浠庣數鑴戦€夋嫨<\/label>/);
  assert.match(html, /id="productImageStatus" aria-live="polite"/);
});

test("keeps profit rules on a dedicated route and collapses fee bases by default", async () => {
  const html = await (await fetchPath("/index.html")).text();
  assert.match(html, /data-profit-view="rules"/);
  assert.match(html, /data-profit-view-page="rules"[^>]*hidden/);
  assert.match(html, /id="profitBasisToggle"[^>]*aria-expanded="false"/);
  assert.match(html, /id="profitBreakdownTable"/);
  assert.match(html, /id="profit-rules-flow"/);
  assert.match(html, /id="profit-rules-auto"/);
  assert.match(html, /id="profit-rules-ads"/);
  assert.match(html, /id="profit-rules-boundary"/);
  assert.doesNotMatch(html, /class="profit-formula-notes"/);
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
  assert.match(html, /浠撳簱鏁伴噺涓嶅彈闄愬埗/);
  assert.match(html, /涓€娆＄‘璁ゅ畬鎴愭暣鍗曞簱瀛樻牎楠屻€佹墸搴撲笌鍑哄簱娴佹按/);
  assert.match(html, /宸叉湁鍩哄噯鍚庡彧闇€淇敼绱閿€閲?);
  assert.match(html, /鍏朵粬鍏紑鏁版嵁锛堝凡鑷姩娌跨敤锛屾湁鍙樺寲鏃跺啀淇敼锛?);
  assert.match(html, /鍚屼竴涓晢鍝佸彲缁存姢澶氫釜棰滆壊銆佸昂瀵告垨濂楄 SKU/);
  assert.match(html, />纭骞跺嚭搴?/);
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
  assert.match(html, /鍙～鍐欏疄闄呭埌璐х殑鏁伴噺/);
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
  assert.doesNotMatch(scriptText, /鍥㈤槦鐗堜細淇濈暀鏈簵 SKU 涓绘。/);
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
  assert.match(scriptText, /Treat the currently typed tracking number as a pending logistics record/);
  assert.match(scriptText, /const pendingTrackingNumber = \$\('#purchaseTrackingNumber'\)\.value\.trim\(\)/);
  assert.match(scriptText, /draftPurchaseShipments\.push\(\{ id: '', trackingNumber: pendingTrackingNumber, lines: \[\] \}\)/);
  assert.match(scriptText, /淇濆瓨鎴愬姛锛屼絾椤甸潰鏁版嵁鍒锋柊澶辫触/);
  assert.match(scriptText, /applyResult: function \(savedPurchase\) \{ return teamGateway\.applyPurchaseOrderResult\(savedPurchase\); \}/);
  assert.match(scriptText, /refreshOnError: false/);
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
