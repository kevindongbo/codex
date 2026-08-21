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
  assert.match(html, /数据分析/);
  assert.match(html, /竞品分析/);
  assert.match(html, /智能选品/);
  assert.doesNotMatch(html, />\s*总览\s*</);
  assert.match(html, /data-module="products"/);
  assert.match(html, /data-module="warehouse"/);
  assert.match(html, /data-module="analytics"/);
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
  assert.match(html, /styles\.css\?v=20260821-data-profit-creator-workflow-2/);
  assert.match(html, /team\.js\?v=20260821-data-profit-creator-workflow-2/);
  assert.match(html, /profit-calculator\.js\?v=20260821-data-profit-creator-workflow-2/);
  assert.match(html, /app\.js\?v=20260821-data-profit-creator-workflow-2/);
  assert.match(html, /for="productImageFile">从电脑选择<\/label>/);
  assert.match(html, /id="productImageStatus" aria-live="polite"/);
});

test("keeps the profit advertising controls on one visual baseline", async () => {
  const css = await (await fetchPath("/styles.css")).text();
  assert.match(css, /\.profit-ad-input\s*\{[^}]*height:\s*52px;[^}]*display:\s*grid;[^}]*grid-template-rows:\s*42px;[^}]*align-items:\s*center;/s);
  assert.match(css, /\.profit-input-table \.profit-ad-input > select, \.profit-input-table \.profit-ad-input > input\s*\{[^}]*height:\s*42px !important;[^}]*min-height:\s*42px !important;[^}]*max-height:\s*42px !important;[^}]*margin:\s*0 !important;/s);
});

test("keeps profit strategy actions in the compact calculation titlebar", async () => {
  const [html, css] = await Promise.all([
    (await fetchPath("/index.html")).text(),
    (await fetchPath("/styles.css")).text(),
  ]);
  const titlebarStart = html.indexOf('<div class="panel-title profit-config-titlebar"');
  const strategyListStart = html.indexOf('<div class="profit-strategy-list"', titlebarStart);
  assert.ok(titlebarStart >= 0, "calculation configuration titlebar must exist");
  assert.ok(strategyListStart > titlebarStart, "saved strategy labels must follow the titlebar");
  const titlebar = html.slice(titlebarStart, strategyListStart);
  assert.match(titlebar, /<h2>计算配置<\/h2>/);
  ["profitStrategyCreate", "profitStrategySaveCurrent", "profitStrategyDelete"].forEach((id) => {
    assert.match(titlebar, new RegExp(`id="${id}"`));
  });
  assert.doesNotMatch(html, /选择店铺信息后，系统将自动匹配已核验的马来西亚费率规则。/);
  assert.doesNotMatch(html, /class="profit-strategy-bar"/);
  assert.doesNotMatch(html, /class="profit-strategy-bar-actions"/);
  assert.match(css, /\.profit-page \.profit-config-titlebar\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;[^}]*justify-content:\s*space-between;/s);
  assert.match(css, /\.profit-page \.profit-config-actions\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;[^}]*justify-content:\s*flex-end;[^}]*flex-wrap:\s*nowrap;/s);
  assert.match(css, /\.profit-page \.profit-strategy-list:empty\s*\{[^}]*display:\s*none;/s);
  assert.match(css, /@media \(max-width: 620px\)[\s\S]*?\.profit-page \.profit-config-titlebar\s*\{[^}]*flex-wrap:\s*wrap;/s);
  assert.match(css, /@media \(max-width: 620px\)[\s\S]*?\.profit-page \.profit-config-actions\s*\{[^}]*flex-wrap:\s*wrap;/s);
});

test("keeps the ERP polish controls and daily exchange-rate workflow wired", async () => {
  const [html, appScript, profitScript] = await Promise.all([
    (await fetchPath("/index.html")).text(),
    (await fetchPath("/app.js")).text(),
    (await fetchPath("/profit-calculator.js")).text(),
  ]);
  assert.ok(html.indexOf('data-module="selection"') > html.indexOf('data-module="profit"'));
  assert.doesNotMatch(html, /id="openProductModal"/);
  assert.match(html, /data-transfer-filter="open"/);
  assert.match(html, /data-transfer-filter="closed"/);
  assert.match(html, /id="batchWeight3"[^>]*value="40"/);
  assert.match(html, /id="batchWeight7"[^>]*value="30"/);
  assert.match(html, /id="batchWeight15"[^>]*value="20"/);
  assert.match(html, /id="batchWeight30"[^>]*value="10"/);
  assert.match(html, /id="profitRateAuto"/);
  assert.match(html, /id="profitRateManual"/);
  assert.match(appScript, /purchase-detail-list/);
  assert.match(appScript, /velocity3 \* 0\.4 \+ velocity7 \* 0\.3 \+ velocity15 \* 0\.2 \+ velocity30 \* 0\.1/);
  assert.match(profitScript, /profit-calculator\/exchange-rates\//);
});

test("wires shared profit configuration, modal warehouse allocation, and transfer transit workflows", async () => {
  const [html, appScript, teamScript, profitScript] = await Promise.all([
    (await fetchPath("/index.html")).text(), (await fetchPath("/app.js")).text(),
    (await fetchPath("/team.js")).text(), (await fetchPath("/profit-calculator.js")).text(),
  ]);
  assert.match(html, /id="profitWorkingConfigStatus"/);
  assert.match(profitScript, /profit-calculator\/working-config\//);
  assert.match(profitScript, /scheduleWorkingConfigSave/);
  assert.match(html, /id="orderWarehouseModal"/);
  assert.match(appScript, /function openOrderWarehouseSelector/);
  assert.match(appScript, /required.*available.*shortage/s);
  assert.doesNotMatch(appScript, /window\.prompt/);
  assert.match(teamScript, /warehouse-options/);
  assert.match(html, /在途库存/);
  assert.match(html, /id="transferWorkflowModal"/);
  assert.match(appScript, /exception_closed_quantity/);
  assert.match(appScript, /function openTransferWorkflow/);
  assert.match(teamScript, /close-transit-exception/);
});

test("keeps ERP cancellation as one confirmed internal API call and supports restore fulfillment", async () => {
  const [appScript, teamScript] = await Promise.all([
    (await fetchPath("/app.js")).text(), (await fetchPath("/team.js")).text(),
  ]);
  assert.match(appScript, /action === 'cancel-order'[\s\S]*askConfirm[\s\S]*teamGateway\.cancelOrder/);
  assert.match(appScript, /restore-order-fulfillment/);
  assert.match(teamScript, /\/orders\/' \+ order\.id \+ '\/cancel\/'/);
  assert.match(teamScript, /restore-fulfillment/);
  assert.doesNotMatch(teamScript, /tiktok.*cancel|shopee.*cancel|ozon.*cancel/i);
});

test("hides internal ledger references and wires sticky inventory, unified transit and order SKU cards", async () => {
  const [html, appScript, teamScript, css] = await Promise.all([
    (await fetchPath("/index.html")).text(), (await fetchPath("/app.js")).text(),
    (await fetchPath("/team.js")).text(), (await fetchPath("/styles.css")).text(),
  ]);
  const movementHead = html.match(/id="movementPanel"[\s\S]*?<thead>([\s\S]*?)<\/thead>/)?.[1] || "";
  assert.doesNotMatch(movementHead, /关联单据/);
  assert.doesNotMatch(appScript, /afterOnHand\)[\s\S]{0,120}sourceNumber/);
  assert.match(html, /id="inventoryTable"/);
  assert.match(html, /id="inventoryTableWrap"[\s\S]*id="inventoryTable"[\s\S]*在途库存/);
  assert.match(appScript, /function updateInventoryStickyHeader/);
  assert.match(css, /\.inventory-sticky-header/);
  assert.match(appScript, /function inboundFor/);
  assert.match(appScript, /balance\.inboundTotal == null[\s\S]*balance\.inboundTotal/);
  assert.match(teamScript, /purchasedPendingShipment[\s\S]*inTransit[\s\S]*inboundTotal/);
  assert.match(html, /id="transitSourceModal"/);
  assert.match(html, /id="orderSkuSearch"/);
  assert.match(html, /id="orderSkuPicker"/);
  assert.doesNotMatch(html, /id="orderLineProduct"|id="addOrderLine"/);
  assert.match(appScript, /function renderOrderSkuPicker/);
  assert.match(teamScript, /\/orders\/create-and-ship\//);
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

test("keeps per-SKU profit fee editing and the single rate-share column wired", async () => {
  const [html, profitScript] = await Promise.all([
    (await fetchPath("/index.html")).text(),
    (await fetchPath("/profit-calculator.js")).text(),
  ]);
  assert.match(html, /id="profitCommissionAdjustment"[^>]*value="1\.00"/);
  assert.match(html, /<th>费率 \/ 占比<\/th>/);
  assert.doesNotMatch(html, /<th>费率<\/th>\s*<th>占结算收入<\/th>/);
  assert.match(html, /包装后重量分别向上取整至 10g，只计算商家承担的跨境段运费/);
  assert.match(html, /东南亚跨境物流运费价格表20260515\(1\)\.xlsx/);
  assert.match(profitScript, /const manualCommissionByRow = new Map\(\)/);
  assert.match(profitScript, /data-manual-commission-row/);
  assert.match(profitScript, /result\.manual_commission_rate = manualCommissionByRow\.get/);
  assert.match(profitScript, /参考 · /);
});

test("keeps settlement strategies, order-level buyer shipping, and scoped currency presentation wired", async () => {
  const [html, profitScript] = await Promise.all([
    (await fetchPath("/index.html")).text(),
    (await fetchPath("/profit-calculator.js")).text(),
  ]);
  ["profitBuyerPaysShipping", "profitTransactionFeeAdjustment", "profitStrategyBar", "profitStrategyList", "profitStrategyCreate", "profitStrategySaveCurrent", "profitStrategyDelete", "profitStrategyModal", "profitStrategySaveChoiceModal", "profitStrategyDeleteModal", "profitTotalRevenue", "profitTotalFees", "profitSettlementAmount"].forEach((id) => assert.match(html, new RegExp(`id="${id}"`)));
  ["profitBuyerShippingRegion", "profitStrategySelect", "profitStrategyName", "profitStrategySave"].forEach((id) => assert.doesNotMatch(html, new RegExp(`id="${id}"`)));
  assert.doesNotMatch(html, /计算币种/);
  assert.match(html, /data-profit-currency="MYR"/);
  assert.match(html, /profit-config-grid profit-config-grid-switches[\s\S]*profitBxp[\s\S]*profitBuyerPaysShipping/);
  assert.match(html, /id="profitStrategyModalName"[\s\S]*id="profitStrategyModalRegion"/);
  assert.doesNotMatch(html, /profit-settlement-summary[\s\S]*profit-formula-lines/);
  assert.match(profitScript, /function formatSingleMoney/);
  assert.match(profitScript, /function formatDualMoney/);
  assert.match(profitScript, / ／ /);
  assert.match(profitScript, /≈ ' \+ formatSingleMoney/);
  assert.doesNotMatch(profitScript, /function formatMoney\(/);
  assert.match(profitScript, /buyer_pays_shipping/);
  assert.match(profitScript, /transaction_fee_adjustment/);
  assert.match(profitScript, /profit-calculator\/strategies\/.*activate/);
  assert.doesNotMatch(profitScript, /window\.(confirm|prompt)/);
});

test("keeps single fee rows plain and multi-fee groups collapsed with SVG toggles", async () => {
  const profitScript = await (await fetchPath("/profit-calculator.js")).text();
  assert.match(profitScript, /if \(group\.items\.length === 1\)/);
  assert.match(profitScript, /class="profit-group-chevron"[^]*?<svg/);
  assert.match(profitScript, /aria-expanded="false"/);
  assert.match(profitScript, /data-profit-group-row=.*hidden/);
  assert.match(profitScript, /function setGroupExpanded/);
  assert.doesNotMatch(profitScript, /profit-group-toggle[^]*[⌄›]/);
});

test("wires stores, SKU multi-store profit ranges and competitor seller grouping fields", async () => {
  const [html, appScript, teamScript, profitScript, css] = await Promise.all([
    (await fetchPath("/index.html")).text(), (await fetchPath("/app.js")).text(),
    (await fetchPath("/team.js")).text(), (await fetchPath("/profit-calculator.js")).text(),
    (await fetchPath("/styles.css")).text(),
  ]);
  assert.match(html, /id="storeManagementPanel"/);
  assert.match(html, /id="storeModal"/);
  assert.match(html, /id="productStoreList"/);
  assert.match(html, /店铺售价<\/th><th>广告费前毛利<\/th><th>广告费前毛利率<\/th><th>保本 ROI/);
  assert.doesNotMatch(html, /data-product-filter="direct"|data-product-filter="indirect"/);
  assert.doesNotMatch(html, /id="replenishmentMethodNote"/);
  assert.match(html, /id="sellerRating"/);
  assert.match(html, /id="sellerIsStar"/);
  assert.match(html, /id="sellerType"/);
  assert.match(html, /id="snapshotShippingType"/);
  assert.match(appScript, /function renderProductStoreEditor/);
  assert.match(appScript, /toggle-profit-details/);
  assert.match(profitScript, /if \(group\.items\.length === 1\)/);
  assert.match(teamScript, /\/skus\/profit-summary\//);
  assert.match(teamScript, /commission_override_percent: listing\.commission === '' \? null/);
  assert.match(css, /\.product-media img\s*\{[^}]*object-fit:\s*contain/);
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
  assert.match(scriptText, /velocity3 \* 0\.4 \+ velocity7 \* 0\.3 \+ velocity15 \* 0\.2 \+ velocity30 \* 0\.1/);
  assert.match(scriptText, /safetyMarginRatio/);
  assert.match(scriptText, /purchase-detail-list/);
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
  assert.match(scriptText, /保存成功，但页面数据刷新失败/);
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
});
