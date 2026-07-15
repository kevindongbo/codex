import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function loadDomain() {
  const source = (await readFile(new URL("../app.js", import.meta.url), "utf8")).replace(/\r\n/g, "\n");
  const boot = "applyHashRoute();\nbindEvents();\nrender();\ninitializeTeamMode();\nstartRealtimeSync();";
  assert.ok(source.includes(boot), "app boot sequence changed unexpectedly");
  const exposed = source.replace(
    boot,
    "globalThis.__domain = { emptyState, normalizeProduct, normalizeWarehouse, normalizeV5, migrateLegacy, ownProducts, productMissingFields, currentWarehouseId, ensureBalance, balanceFor, availableFor, purchaseTransitFor, receivePurchaseOrder, reserveOrder, shipOrder, confirmAndShipOrder, cancelOrder, receiveSalesReturn, returnedForLine, returnableForLine, addMovement, dispatchTransfer, receiveTransfer, cancelTransfer, localReplenishmentRecommendation, normalizeTeamRecommendation, snapshotFromForm, snapshotAdvancedChanged, fillSnapshotHint, getState: () => state, setState: (value) => { state = value; } };",
  );
  const storage = new Map();
  const domNodes = new Map();
  const context = vm.createContext({
    console,
    URL,
    Date,
    Math,
    Intl,
    setTimeout,
    clearTimeout,
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
    },
    document: {
      querySelector: (selector) => domNodes.get(selector) ?? null,
      querySelectorAll: () => [],
    },
  });
  vm.runInContext(exposed, context, { filename: "app.js" });
  context.__domain.__nodes = domNodes;
  return context.__domain;
}

function ownProduct(domain, overrides = {}) {
  return domain.normalizeProduct({
    id: "p-1",
    name: "测试商品",
    kind: "own",
    sku: "DB-001",
    salesCurrency: "CNY",
    costCurrency: "CNY",
    standardCost: 10,
    safetyStock: 2,
    status: "active",
    productUrl: "https://example.com/product",
    image: "https://example.com/image.jpg",
    ...overrides,
  });
}

test("draft products remain drafts and cannot enter warehouse selectors", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  const draft = domain.normalizeProduct({
    id: "draft-1",
    name: "待完善商品",
    kind: "own",
    status: "draft",
  });
  state.products.push(draft);

  assert.equal(draft.status, "draft");
  assert.deepEqual(Array.from(domain.productMissingFields(draft, "")), ["商品链接", "商品图片", "SKU", "大于 0 的商品成本"]);
  assert.equal(domain.ownProducts(state).length, 0);
  assert.equal(domain.ownProducts(state, true).length, 1);
});

test("invalid persisted navigation falls back to safe ERP routes", async () => {
  const domain = await loadDomain();
  const saved = domain.emptyState();
  saved.ui = { module: "unknown", warehouseTab: "missing", competitorTab: "broken" };
  const normalized = domain.normalizeV5(saved);
  assert.equal(normalized.ui.module, "products");
  assert.equal(normalized.ui.warehouseTab, "purchase");
  assert.equal(normalized.ui.competitorTab, "products");

  saved.ui = { module: "warehouse", warehouseTab: "replenishment", competitorTab: "products", warehouseId: "warehouse-default" };
  assert.equal(domain.normalizeV5(saved).ui.warehouseTab, "replenishment");
});

test("custom warehouses keep separate balances, purchase transit and operational fields", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.warehouses = [
    domain.normalizeWarehouse({ id: "wh-my", code: "MY-KL", name: "马来仓", type: "overseas", country: "MY", address: "Kuala Lumpur", timezone: "Asia/Kuala_Lumpur", contact: "Amy", canReceive: true, canShip: true }, 0),
    domain.normalizeWarehouse({ id: "wh-forwarder", code: "CN-FWD", name: "货代仓", type: "forwarder", country: "CN", canReceive: true, canShip: true }, 1),
    domain.normalizeWarehouse({ id: "wh-school", code: "MY-SCHOOL", name: "学校仓", type: "school", country: "MY", canReceive: true, canShip: false }, 2),
  ];
  state.ui.warehouseId = "wh-my";
  state.products.push(ownProduct(domain));

  domain.addMovement(state, { warehouseId: "wh-my", productId: "p-1", type: "opening", onHandDelta: 10, reservedDelta: 0 });
  domain.addMovement(state, { warehouseId: "wh-school", productId: "p-1", type: "opening", onHandDelta: 3, reservedDelta: 0 });
  state.purchaseOrders.push(
    { id: "po-my", warehouseId: "wh-my", status: "transit", lines: [{ productId: "p-1", orderedQty: 4, receivedQty: 0, cancelledQty: 0 }] },
    { id: "po-school", warehouseId: "wh-school", status: "transit", lines: [{ productId: "p-1", orderedQty: 9, receivedQty: 0, cancelledQty: 0 }] },
  );

  assert.equal(state.warehouses.length, 3);
  assert.equal(state.warehouses[0].type, "overseas");
  assert.equal(state.warehouses[0].contact, "Amy");
  assert.equal(state.warehouses[0].address, "Kuala Lumpur");
  assert.equal(state.warehouses[2].canShip, false);
  assert.equal(domain.currentWarehouseId(state), "wh-my");
  assert.equal(domain.balanceFor("p-1", state, "wh-my").onHand, 10);
  assert.equal(domain.balanceFor("p-1", state, "wh-school").onHand, 3);
  assert.equal(domain.purchaseTransitFor("p-1", state, "wh-my"), 4);
  assert.equal(domain.purchaseTransitFor("p-1", state, "wh-school"), 9);
});

test("legacy default warehouse safely migrates to the domestic type", async () => {
  const domain = await loadDomain();
  const warehouse = domain.normalizeWarehouse({ id: "warehouse-default", code: "MAIN", name: "默认仓" }, 0);
  assert.equal(warehouse.type, "domestic");
});

test("warehouse transfer subtracts at dispatch and adds only when the destination receives", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.warehouses = [
    domain.normalizeWarehouse({ id: "wh-source", code: "SOURCE", name: "货代仓", type: "forwarder", canReceive: true, canShip: true }, 0),
    domain.normalizeWarehouse({ id: "wh-destination", code: "DEST", name: "马来仓", type: "overseas", canReceive: true, canShip: true }, 1),
  ];
  state.ui.warehouseId = "wh-source";
  state.products.push(ownProduct(domain));
  domain.addMovement(state, { warehouseId: "wh-source", productId: "p-1", type: "opening", onHandDelta: 8, reservedDelta: 0 });
  const transfer = {
    id: "transfer-1", number: "TR-001", sourceWarehouseId: "wh-source", destinationWarehouseId: "wh-destination",
    status: "draft", note: "补马来仓", lines: [{ id: "transfer-line-1", productId: "p-1", quantity: 5, receivedQty: 0 }],
  };
  state.stockTransfers.push(transfer);

  domain.dispatchTransfer(state, transfer);
  assert.equal(transfer.status, "in_transit");
  assert.equal(domain.balanceFor("p-1", state, "wh-source").onHand, 3);
  assert.equal(domain.balanceFor("p-1", state, "wh-destination").onHand, 0);
  assert.equal(state.inventoryMovements.at(-1).type, "transfer_out");

  domain.receiveTransfer(state, transfer.id);
  assert.equal(transfer.status, "received");
  assert.equal(domain.balanceFor("p-1", state, "wh-destination").onHand, 5);
  assert.equal(state.inventoryMovements.at(-1).type, "transfer_in");
  assert.throws(() => domain.receiveTransfer(state, transfer.id), /不能收货/);
});

test("cancelling an in-transit transfer restores source stock", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.warehouses.push(domain.normalizeWarehouse({ id: "wh-to", code: "TO", name: "目标仓" }, 1));
  state.products.push(ownProduct(domain));
  domain.addMovement(state, { productId: "p-1", type: "opening", onHandDelta: 6, reservedDelta: 0 });
  const transfer = {
    id: "transfer-cancel", number: "TR-CANCEL", sourceWarehouseId: "warehouse-default", destinationWarehouseId: "wh-to",
    status: "draft", lines: [{ id: "line", productId: "p-1", quantity: 4, receivedQty: 0 }],
  };
  state.stockTransfers.push(transfer);
  domain.dispatchTransfer(state, transfer);
  assert.equal(domain.balanceFor("p-1", state).onHand, 2);
  domain.cancelTransfer(state, transfer.id);
  assert.equal(transfer.status, "cancelled");
  assert.equal(domain.balanceFor("p-1", state).onHand, 6);
  assert.equal(state.inventoryMovements.at(-1).type, "transfer_return");
});

test("purchase receipt moves quantity from transit to on-hand", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.products.push(ownProduct(domain));
  domain.ensureBalance(state, "p-1");
  state.purchaseOrders.push({
    id: "po-1",
    number: "PO-001",
    supplier: "供应商 A",
    status: "transit",
    orderedAt: "2026-07-01",
    expectedAt: "2026-07-20",
    lines: [{ id: "pol-1", productId: "p-1", orderedQty: 10, receivedQty: 0, cancelledQty: 0, unitCost: 10 }],
  });

  assert.equal(domain.purchaseTransitFor("p-1", state), 10);
  domain.receivePurchaseOrder(state, "po-1", "pol-1", 3, "2026-07-14T10:00:00.000Z", "首批到货");
  assert.equal(domain.purchaseTransitFor("p-1", state), 7);
  assert.equal(domain.balanceFor("p-1", state).onHand, 3);
  assert.equal(state.purchaseOrders[0].status, "partial");
  assert.equal(state.inventoryMovements.at(-1).type, "receipt");
  assert.throws(() => domain.receivePurchaseOrder(state, "po-1", "pol-1", 8, "2026-07-14T11:00:00.000Z", "超量"), /超过未收数量/);
});

test("warehouse receive and ship capabilities are enforced by local posting functions", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.products.push(ownProduct(domain));
  state.purchaseOrders.push({
    id: "po-blocked", warehouseId: "warehouse-default", status: "transit",
    lines: [{ id: "line", productId: "p-1", orderedQty: 1, receivedQty: 0, cancelledQty: 0 }],
  });
  state.warehouses[0].canReceive = false;
  assert.throws(() => domain.receivePurchaseOrder(state, "po-blocked", "line", 1, new Date().toISOString(), "blocked"), /未开放收货/);
  state.warehouses[0].canReceive = true;
  state.warehouses[0].canShip = false;
  state.salesOrders.push({ id: "so-blocked", number: "SO-BLOCKED", status: "shortage", lines: [{ id: "sol", productId: "p-1", quantity: 1 }] });
  assert.throws(() => domain.confirmAndShipOrder(state, "so-blocked"), /未开放出库/);
});

test("legacy balances migrate once without replaying old stock events", async () => {
  const domain = await loadDomain();
  const legacy = {
    version: 4,
    products: [{
      id: "legacy-own", name: "旧版商品", kind: "own", sku: "OLD-001", currency: "CNY",
      cost: 8, url: "https://example.com/old", image: "https://example.com/old.jpg",
    }],
    snapshots: [],
    inventory: [{ productId: "legacy-own", inStock: 5, inTransit: 2 }],
    stockMovements: [{ id: "old-event", type: "receive", quantity: 5 }],
  };
  const migrated = domain.migrateLegacy(legacy);
  assert.equal(domain.balanceFor("legacy-own", migrated).onHand, 5);
  assert.equal(domain.purchaseTransitFor("legacy-own", migrated), 2);
  assert.equal(migrated.inventoryMovements.length, 1);
  assert.equal(migrated.legacyStockEvents.length, 1);

  const loadedAgain = domain.normalizeV5(migrated);
  assert.equal(domain.balanceFor("legacy-own", loadedAgain).onHand, 5);
  assert.equal(domain.purchaseTransitFor("legacy-own", loadedAgain), 2);
  assert.equal(loadedAgain.inventoryMovements.length, 1);
});

test("order reservation is all-or-nothing and shipment is idempotent", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.products.push(ownProduct(domain));
  domain.ensureBalance(state, "p-1");
  domain.addMovement(state, { productId: "p-1", type: "opening", onHandDelta: 5, reservedDelta: 0 });
  state.salesOrders.push({
    id: "so-short",
    number: "SO-SHORT",
    status: "shortage",
    lines: [
      { id: "sol-a", productId: "p-1", quantity: 4, reservedQty: 0, shippedQty: 0 },
      { id: "sol-b", productId: "p-1", quantity: 2, reservedQty: 0, shippedQty: 0 },
    ],
  });

  assert.equal(domain.reserveOrder(state, "so-short"), false);
  assert.equal(domain.balanceFor("p-1", state).reserved, 0);

  state.salesOrders.push({
    id: "so-ok",
    number: "SO-OK",
    status: "shortage",
    lines: [{ id: "sol-ok", productId: "p-1", quantity: 4, reservedQty: 0, shippedQty: 0 }],
  });
  assert.equal(domain.reserveOrder(state, "so-ok"), true);
  assert.equal(domain.balanceFor("p-1", state).reserved, 4);
  state.salesOrders.find((order) => order.id === "so-ok").status = "ready";
  domain.shipOrder(state, "so-ok");
  assert.deepEqual(
    { onHand: domain.balanceFor("p-1", state).onHand, reserved: domain.balanceFor("p-1", state).reserved },
    { onHand: 1, reserved: 0 },
  );
  assert.throws(() => domain.shipOrder(state, "so-ok"), /必须先完成拣货和复核/);
});

test("one confirmation atomically ships a whole order and leaves shortages untouched", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.products.push(ownProduct(domain));
  domain.addMovement(state, { productId: "p-1", type: "opening", onHandDelta: 5, reservedDelta: 0 });
  state.salesOrders.push({
    id: "so-one-click", number: "SO-ONE-CLICK", warehouseId: "warehouse-default", status: "shortage",
    lines: [{ id: "sol-one-click", productId: "p-1", quantity: 4, reservedQty: 0, shippedQty: 0 }],
  });

  assert.equal(domain.confirmAndShipOrder(state, "so-one-click"), true);
  assert.equal(state.salesOrders[0].status, "shipped");
  assert.equal(state.salesOrders[0].lines[0].shippedQty, 4);
  assert.equal(domain.balanceFor("p-1", state).onHand, 1);
  assert.equal(domain.balanceFor("p-1", state).reserved, 0);
  assert.equal(state.shipments.length, 1);
  assert.equal(state.reservations.filter((item) => item.status === "active").length, 0);

  state.salesOrders.push({
    id: "so-insufficient", number: "SO-INSUFFICIENT", warehouseId: "warehouse-default", status: "shortage",
    lines: [{ id: "sol-insufficient", productId: "p-1", quantity: 2, reservedQty: 0, shippedQty: 0 }],
  });
  const movementsBefore = state.inventoryMovements.length;
  const shipmentsBefore = state.shipments.length;
  assert.equal(domain.confirmAndShipOrder(state, "so-insufficient"), false);
  assert.equal(state.salesOrders[1].status, "shortage");
  assert.equal(domain.balanceFor("p-1", state).onHand, 1);
  assert.equal(domain.balanceFor("p-1", state).reserved, 0);
  assert.equal(state.inventoryMovements.length, movementsBefore);
  assert.equal(state.shipments.length, shipmentsBefore);
});

test("replenishment combines weighted outbound velocity, lead time, inbound stock and pack rounding", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  const product = ownProduct(domain, { safetyStock: 2 });
  state.products.push(product);
  domain.addMovement(state, { productId: product.id, type: "opening", onHandDelta: 10, reservedDelta: 0 });
  state.replenishmentPolicies.push({
    id: "policy-1", productId: product.id, warehouseId: "warehouse-default",
    leadTimeOverride: 10, reviewCycleDays: 7, targetDays: 30, minOrderQty: 12, packSize: 6,
  });
  state.purchaseOrders.push({
    id: "po-inbound", warehouseId: "warehouse-default", status: "transit",
    lines: [{ productId: product.id, orderedQty: 5, receivedQty: 0, cancelledQty: 0 }],
  });
  for (let day = 0; day < 7; day += 1) {
    state.inventoryMovements.push({
      id: `outbound-${day}`, warehouseId: "warehouse-default", productId: product.id,
      type: "outbound", onHandDelta: -2, reservedDelta: -2,
      occurredAt: new Date(Date.now() - day * 86400000).toISOString(),
    });
  }
  domain.setState(state);

  const recommendation = domain.localReplenishmentRecommendation(product);
  assert.ok(Math.abs(recommendation.velocity7 - 2) < 0.001);
  assert.ok(Math.abs(recommendation.velocity14 - 1) < 0.001);
  assert.ok(Math.abs(recommendation.velocity30 - (14 / 30)) < 0.001);
  assert.ok(Math.abs(recommendation.velocity - (2 * 0.5 + 1 * 0.3 + (14 / 30) * 0.2)) < 0.001);
  assert.equal(recommendation.leadDays, 10);
  assert.equal(recommendation.leadSource, "manual");
  assert.equal(recommendation.available, 10);
  assert.equal(recommendation.inbound, 5);
  assert.equal(recommendation.inventoryPosition, 15);
  assert.equal(recommendation.suggestedQty, 30);
  assert.equal(recommendation.urgency, "urgent");
  assert.equal(recommendation.confidence, "medium");
  assert.ok(recommendation.latestOrderDate);
  const localNow = new Date();
  const localToday = [localNow.getFullYear(), String(localNow.getMonth() + 1).padStart(2, "0"), String(localNow.getDate()).padStart(2, "0")].join("-");
  assert.ok(recommendation.latestOrderDate < localToday, "overdue order dates must not be clamped to today");
});

test("zero demand and zero safety stock is data-insufficient instead of an urgent zero-quantity reorder", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  const product = ownProduct(domain, { safetyStock: 0 });
  state.products.push(product);
  domain.setState(state);
  const recommendation = domain.localReplenishmentRecommendation(product);
  assert.equal(recommendation.velocity, 0);
  assert.equal(recommendation.suggestedQty, 0);
  assert.equal(recommendation.urgency, "insufficient");
  assert.equal(recommendation.stockoutDate, "");
});

test("team replenishment response maps the final forecast dataclass fields without losing quantities or dates", async () => {
  const domain = await loadDomain();
  const recommendation = domain.normalizeTeamRecommendation({
    product: "product-1", sku: "sku-1", policy: "policy-1",
    lead_time: { selected_days: 18, source: "historical_full_p80", confidence: "high" },
    demand: { daily_velocity: "2.4000", daily_7: "3.0000", daily_14: "2.0000", daily_30: "1.5000" },
    inventory: { available: "10.000", in_transit: "20.000", inventory_position: "30.000" },
    reorder_point: "41.000", suggested_order_quantity: "24.000", alert_level: "red",
    available_days_of_cover: "4.2", available_stockout_date: "2026-07-20",
    projected_stockout_date: "2026-07-29", latest_order_date: "2026-07-11", confidence: "high",
  });

  assert.equal(recommendation.productId, "product-1");
  assert.equal(recommendation.skuId, "sku-1");
  assert.equal(recommendation.velocity, 2.4);
  assert.equal(recommendation.velocity7, 3);
  assert.equal(recommendation.velocity14, 2);
  assert.equal(recommendation.velocity30, 1.5);
  assert.equal(recommendation.leadDays, 18);
  assert.equal(recommendation.leadSource, "historical_full_p80");
  assert.equal(recommendation.available, 10);
  assert.equal(recommendation.inbound, 20);
  assert.equal(recommendation.inventoryPosition, 30);
  assert.equal(recommendation.reorderPoint, 41);
  assert.equal(recommendation.suggestedQty, 24);
  assert.equal(recommendation.daysCover, 4.2);
  assert.equal(recommendation.stockoutDate, "2026-07-29");
  assert.equal(recommendation.latestOrderDate, "2026-07-11");
  assert.equal(recommendation.urgency, "red");
  assert.equal(recommendation.confidence, "high");
});

test("a repeat competitor snapshot only changes sales while public metrics inherit from the latest snapshot", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  const product = domain.normalizeProduct({
    id: "competitor-1", name: "竞品", kind: "direct", salesCurrency: "MYR",
    productUrl: "https://example.com/competitor", image: "https://example.com/competitor.jpg", status: "active",
  });
  state.products.push(product);
  state.snapshots.push({
    id: "baseline", productId: product.id, at: "2026-07-14T10:00:00.000Z", currency: "MYR",
    price: 18.69, sold: 901, rating: 4.8, reviews: 56, lowReviews: 1, shopRating: 4.9,
  });
  state.selectedProductId = product.id;
  domain.setState(state);

  const fields = {
    "#snapshotProduct": { value: product.id },
    "#snapshotAt": { value: "2026-07-15T10:00" },
    "#snapshotPrice": { value: "" },
    "#snapshotSold": { value: "" },
    "#snapshotRating": { value: "" },
    "#snapshotReviews": { value: "" },
    "#snapshotLowReviews": { value: "" },
    "#snapshotShopRating": { value: "" },
    "#snapshotAdvanced": { open: true },
    "#lastValueHint": { textContent: "" },
  };
  Object.entries(fields).forEach(([selector, node]) => domain.__nodes.set(selector, node));

  domain.fillSnapshotHint();
  assert.equal(Number(fields["#snapshotPrice"].value), 18.69);
  assert.equal(Number(fields["#snapshotSold"].value), 901);
  assert.equal(Number(fields["#snapshotRating"].value), 4.8);
  assert.equal(Number(fields["#snapshotReviews"].value), 56);
  assert.equal(Number(fields["#snapshotLowReviews"].value), 1);
  assert.equal(Number(fields["#snapshotShopRating"].value), 4.9);
  assert.equal(fields["#snapshotAdvanced"].open, false, "repeat updates should keep inherited fields collapsed");

  fields["#snapshotSold"].value = "915";
  const next = domain.snapshotFromForm("#snapshot", product, true);
  assert.equal(next.sold, 915);
  assert.equal(next.price, 18.69);
  assert.equal(next.rating, 4.8);
  assert.equal(next.reviews, 56);
  assert.equal(next.lowReviews, 1);
  assert.equal(next.shopRating, 4.9);
  assert.equal(domain.snapshotAdvancedChanged(next, state.snapshots[0]), false);
  assert.equal(domain.snapshotAdvancedChanged({ ...next, price: 17.5 }, state.snapshots[0]), true);

  state.snapshots = [];
  fields["#snapshotAdvanced"].open = false;
  domain.fillSnapshotHint();
  assert.equal(fields["#snapshotAdvanced"].open, true, "first snapshot must reveal the required baseline fields");
});

test("cancel releases reservations and a sales return cannot exceed shipped quantity", async () => {
  const domain = await loadDomain();
  const state = domain.emptyState();
  state.products.push(ownProduct(domain));
  domain.ensureBalance(state, "p-1");
  domain.addMovement(state, { productId: "p-1", type: "opening", onHandDelta: 8, reservedDelta: 0 });
  state.salesOrders.push({
    id: "so-cancel",
    number: "SO-CANCEL",
    status: "shortage",
    lines: [{ id: "sol-cancel", productId: "p-1", quantity: 3, reservedQty: 0, shippedQty: 0 }],
  });
  domain.reserveOrder(state, "so-cancel");
  domain.cancelOrder(state, "so-cancel");
  assert.equal(domain.balanceFor("p-1", state).reserved, 0);
  assert.equal(state.salesOrders[0].status, "cancelled");

  state.salesOrders.push({
    id: "so-return",
    number: "SO-RETURN",
    status: "shipped",
    lines: [{ id: "sol-return", productId: "p-1", quantity: 2, reservedQty: 0, shippedQty: 2 }],
  });
  domain.receiveSalesReturn(state, "so-return", "sol-return", 1, "2026-07-14T12:00:00.000Z", "商品完好");
  assert.equal(domain.returnedForLine("sol-return", state), 1);
  assert.equal(domain.balanceFor("p-1", state).onHand, 9);
  assert.throws(() => domain.receiveSalesReturn(state, "so-return", "sol-return", 2, "2026-07-14T13:00:00.000Z", "超量"), /不能超过/);
});
