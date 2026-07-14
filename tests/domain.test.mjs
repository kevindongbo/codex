import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function loadDomain() {
  const source = await readFile(new URL("../app.js", import.meta.url), "utf8");
  const boot = "applyHashRoute();\nbindEvents();\nrender();";
  assert.ok(source.includes(boot), "app boot sequence changed unexpectedly");
  const exposed = source.replace(
    boot,
    "globalThis.__domain = { emptyState, normalizeProduct, normalizeV5, migrateLegacy, ownProducts, productMissingFields, ensureBalance, balanceFor, availableFor, purchaseTransitFor, receivePurchaseOrder, reserveOrder, shipOrder, cancelOrder, receiveSalesReturn, returnedForLine, returnableForLine, addMovement };",
  );
  const storage = new Map();
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
  });
  vm.runInContext(exposed, context, { filename: "app.js" });
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
  assert.deepEqual(Array.from(domain.productMissingFields(draft, "")), ["商品链接", "商品图片", "SKU", "商品成本"]);
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
