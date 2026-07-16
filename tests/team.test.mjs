import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

async function loadTeam(fetchImpl = async () => response(200, {})) {
  const source = await readFile(new URL('../team.js', import.meta.url), 'utf8');
  const session = new Map();
  class FormData {}
  const context = {
    console,
    Date,
    Math,
    Map,
    Promise,
    JSON,
    FormData,
    navigator: { onLine: true },
    sessionStorage: {
      getItem: (key) => session.get(key) ?? null,
      setItem: (key, value) => session.set(key, String(value)),
      removeItem: (key) => session.delete(key),
    },
    fetch: fetchImpl,
    crypto: { randomUUID: () => 'fixed-uuid' },
  };
  context.window = context;
  vm.runInNewContext(source, context, { filename: 'team.js' });
  return context.DongboTeam;
}

function response(status, payload, contentType = 'application/json') {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => name.toLowerCase() === 'content-type' ? contentType : null },
    json: async () => payload,
    text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload),
  };
}

test('API pagination keeps authorization and organization scope', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) {
      return response(200, { results: [{ id: 'p1' }], next: 'https://erp.example/api/products/?page=2' });
    }
    return response(200, { results: [{ id: 'p2' }], next: null });
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'access-token';
  gateway.organizationId = 'org-1';

  const items = await gateway.listAll('/products/');

  assert.deepEqual(Array.from(items, (item) => item.id), ['p1', 'p2']);
  assert.equal(calls[0].url, '/api/products/');
  assert.equal(calls[1].url, 'https://erp.example/api/products/?page=2');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer access-token');
  assert.equal(calls[0].options.headers['X-Organization-ID'], 'org-1');
});

test('team adapter exposes every SKU and keeps linked monitoring snapshots on the product', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.warehouseId = 'wh-1';
  gateway.warehouses = [{ id: 'wh-1', code: 'DEFAULT', name: '默认仓', active: true }];
  const raw = {
    suppliers: [{ id: 'sup-1', name: '供应商' }],
    products: [{
      id: 'product-1', name: '多规格商品', seller: 'Dongbo', market: 'MY', sales_currency: 'MYR',
      monitoring_enabled: true, source_url: 'https://example.com/p', purchase_url: '',
      default_supplier: 'sup-1', status: 'active', created_at: '2026-01-01', updated_at: '2026-01-02',
      images: [{ id: 'img-1', url: 'https://example.com/a.jpg' }],
      skus: [
        { id: 'sku-a', code: 'SKU-A', cost: '10', currency: 'MYR', safety_stock: '2', active: true },
        { id: 'sku-b', code: 'SKU-B', cost: '12', currency: 'MYR', safety_stock: '3', active: true },
      ],
    }],
    competitors: [{
      id: 'profile-1', linked_product: 'product-1', name: '自有商品监控', kind: 'direct',
      platform: 'own', market: 'MY', url: 'https://example.com/p', image_url: 'https://example.com/a.jpg',
      seller: 'Dongbo', currency: 'MYR', active: true,
    }],
    snapshots: [{
      id: 'snap-1', product: 'profile-1', captured_at: '2026-01-03T00:00:00Z',
      price: '20', sold_count: 5, rating: '4.8', review_count: 2,
      raw: { low_reviews: 1, shop_rating: 4.9 }, created_at: '2026-01-03T00:00:00Z',
    }],
    purchaseOrders: [],
    balances: [
      { id: 'b1', warehouse: 'wh-1', sku: 'sku-a', on_hand: '4', reserved: '1', in_transit: '2' },
      { id: 'b2', warehouse: 'wh-1', sku: 'sku-b', on_hand: '8', reserved: '0', in_transit: '0' },
    ],
    ledger: [], orders: [], shipments: [], returns: [], transfers: [],
    replenishmentPolicies: [], replenishmentRecommendations: [],
  };

  const state = gateway.adaptState(raw);

  assert.equal(state.products.length, 2);
  assert.deepEqual(Array.from(state.products, (item) => item.sku).sort(), ['SKU-A', 'SKU-B']);
  assert.notEqual(state.products[0].id, state.products[1].id);
  assert.deepEqual(Array.from(state.products, (item) => item.catalogProductId), ['product-1', 'product-1']);
  assert.deepEqual(Array.from(state.products, (item) => item.skuCount), [2, 2]);
  assert.equal(state.snapshots[0].productId, state.products[0].id);
  assert.deepEqual(
    Array.from(state.inventoryBalances, (item) => item.productId).sort(),
    Array.from(state.products, (item) => item.id).sort(),
  );
});

test('saving one product writes every requested SKU and retires removed SKUs safely', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  const calls = [];
  const raw = {
    id: 'product-1', skus: [
      { id: 'sku-old', code: 'OLD', active: true },
      { id: 'sku-keep', code: 'KEEP', active: true },
    ], images: [], status: 'draft',
  };
  gateway.cache = { products: [raw], suppliers: [] };
  gateway.request = async (path, options = {}) => {
    calls.push({ path, options });
    if (path === '/products/product-1/') return raw;
    if (path === '/skus/sku-keep/') return { id: 'sku-keep' };
    if (path === '/skus/') return { id: 'sku-new' };
    return {};
  };
  await gateway.saveProduct({
    kind: 'own', apiProductId: 'product-1', name: '多 SKU 商品', seller: '', market: 'MY',
    salesCurrency: 'MYR', costCurrency: 'MYR', standardCost: 1, safetyStock: 0,
    defaultSupplier: '', productUrl: 'https://example.com/p', purchaseUrl: '', image: '',
    monitoringEnabled: false, status: 'active',
    skus: [
      { id: 'sku-keep', code: 'KEEP', cost: 12, safetyStock: 3, attributes: { color: 'pink' } },
      { code: 'NEW', cost: 15, safetyStock: 4, attributes: { size: 'L' } },
    ],
  });
  assert.deepEqual(calls.map((call) => call.path), [
    '/products/product-1/', '/skus/sku-keep/', '/skus/', '/skus/sku-old/', '/products/product-1/activate/',
  ]);
  assert.equal(calls[1].options.body.code, 'KEEP');
  assert.equal(calls[2].options.body.code, 'NEW');
  assert.equal(calls[3].options.body.active, false);
});

test('unknown network outcome reuses the same inventory idempotency key', async () => {
  const bodies = [];
  let attempt = 0;
  const Team = await loadTeam(async (_url, options) => {
    attempt += 1;
    bodies.push(JSON.parse(options.body));
    if (attempt === 1) throw new Error('connection reset');
    return response(201, { id: 'ledger-1' });
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';
  gateway.warehouseId = 'wh-1';
  const product = { skuId: 'sku-1' };

  await assert.rejects(() => gateway.adjustInventory(product, 'adjust_add', 3, '盘点'));
  await gateway.adjustInventory(product, 'adjust_add', 3, '盘点');

  assert.equal(bodies[0].idempotency_key, bodies[1].idempotency_key);
  assert.equal(bodies[1].delta, 3);
});

test('custom warehouse creation sends operational fields and refreshes the unlimited directory', async () => {
  const calls = [];
  const replies = [
    response(201, { id: 'wh-my', code: 'MY-KL', name: '马来仓', active: true }),
    response(200, [{ id: 'wh-my', code: 'MY-KL', name: '马来仓', warehouse_type: 'overseas', country: 'MY', active: true }]),
  ];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return replies.shift();
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';

  await gateway.createWarehouse({
    code: 'my-kl', name: '马来仓', type: 'overseas', country: 'my', address: 'Kuala Lumpur',
    timezone: 'Asia/Kuala_Lumpur', contact: 'Amy', canReceive: true, canShip: false, active: true,
  });

  assert.equal(calls[0].url, '/api/warehouses/');
  assert.equal(calls[0].options.method, 'POST');
  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.code, 'MY-KL');
  assert.equal(body.name, '马来仓');
  assert.equal(body.warehouse_type, 'overseas');
  assert.equal(body.country, 'MY');
  assert.deepEqual(body.address, { text: 'Kuala Lumpur' });
  assert.deepEqual(body.contact, { text: 'Amy' });
  assert.equal(body.can_receive, true);
  assert.equal(body.can_ship, false);
  assert.equal(calls[1].url, '/api/warehouses/');
  assert.equal(gateway.warehouseId, 'wh-my');
  assert.equal(gateway.warehouses.length, 1);
});

test('editing an inactive warehouse never reactivates it implicitly', async () => {
  const calls = [];
  const replies = [
    response(200, { id: 'wh-old', active: false }),
    response(200, [{ id: 'wh-live', code: 'LIVE', name: '启用仓', active: true }, { id: 'wh-old', code: 'OLD', name: '停用仓', active: false }]),
  ];
  const Team = await loadTeam(async (url, options) => { calls.push({ url, options }); return replies.shift(); });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.organizationId = 'org-1';
  gateway.warehouseId = 'wh-live';
  await gateway.saveWarehouse({ id: 'wh-old', code: 'OLD', name: '停用仓', active: false }, 'wh-old');
  const body = JSON.parse(calls[0].options.body);
  assert.equal(calls[0].options.method, 'PATCH');
  assert.equal(Object.hasOwn(body, 'active'), false);
});

test('team permissions expose the selected granular capabilities', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.user = { is_owner: false };
  gateway.permissions = ['purchase', 'warehouse'];
  assert.equal(gateway.can('purchase'), true);
  assert.equal(gateway.can('receipt'), true);
  assert.equal(gateway.can('order'), false);
  assert.equal(gateway.can('warehouse_admin'), true);
  gateway.permissions = ['order', 'warehouse'];
  assert.equal(gateway.can('order'), true);
  assert.equal(gateway.can('transfer'), true);
  assert.equal(gateway.can('replenishment'), false);
});

test('create-and-ship transfer uses server state transitions and one reusable dispatch key', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) return response(201, { id: 'transfer-1', status: 'draft' });
    return response(200, { id: 'transfer-1', status: 'in_transit' });
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';

  const result = await gateway.createAndShipTransfer({
    number: 'TR-001', sourceWarehouseId: 'wh-forwarder', destinationWarehouseId: 'wh-my', note: '补货',
    lines: [{ skuId: 'sku-1', quantity: 8 }],
  });

  assert.equal(result.status, 'in_transit');
  assert.equal(calls[0].url, '/api/stock-transfers/');
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    number: 'TR-001', source_warehouse: 'wh-forwarder', destination_warehouse: 'wh-my', notes: '补货',
    lines: [{ sku: 'sku-1', quantity: 8 }],
  });
  assert.equal(calls[1].url, '/api/stock-transfers/transfer-1/dispatch/');
  assert.equal(JSON.parse(calls[1].options.body).idempotency_key, 'transfer-dispatch:fixed-uuid');
});

test('one-click shipment and quick sales snapshot call the dedicated atomic endpoints', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return calls.length === 1
      ? response(201, { id: 'shipment-1', status: 'shipped' })
      : response(201, { id: 'snapshot-2', sold_count: 915, price: '18.69' });
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';

  await gateway.confirmAndShipOrder({ id: 'order-1', trackingNumber: 'MY123' });
  await gateway.saveQuickSalesSnapshot(
    { id: 'profile-1', kind: 'direct' },
    { sold: 915, at: '2026-07-15T10:00:00.000Z' },
  );

  assert.equal(calls[0].url, '/api/orders/order-1/confirm-and-ship/');
  const shipmentBody = JSON.parse(calls[0].options.body);
  assert.equal(shipmentBody.idempotency_key, 'confirm-and-ship:fixed-uuid');
  assert.equal(shipmentBody.tracking_number, 'MY123');
  assert.equal(calls[1].url, '/api/competitor-snapshots/quick-sales/');
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    product: 'profile-1', sold_count: 915, captured_at: '2026-07-15T10:00:00.000Z',
  });
});

test('replenishment recommendations are requested for the selected warehouse', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return response(200, [{ sku: 'sku-1', suggested_order_quantity: 24, alert_level: 'red' }]);
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';
  gateway.warehouseId = 'wh-my';

  const recommendations = await gateway.loadReplenishmentRecommendations();

  assert.equal(calls[0].url, '/api/replenishment/recommendations/?warehouse=wh-my');
  assert.equal(recommendations[0].suggested_order_quantity, 24);
});

test('draft transfers and replenishment overrides have explicit recovery endpoints', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => { calls.push({ url, options }); return response(204, null); });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.organizationId = 'org-1';
  gateway.warehouseId = 'wh-my';
  gateway.cache.replenishmentPolicies = [{ id: 'policy-1', warehouse: 'wh-my', sku: 'sku-1' }];
  await gateway.cancelTransfer({ id: 'transfer-1' });
  await gateway.deleteReplenishmentPolicy({ skuId: 'sku-1' });
  assert.equal(calls[0].url, '/api/stock-transfers/transfer-1/cancel/');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[1].url, '/api/replenishment-policies/policy-1/');
  assert.equal(calls[1].options.method, 'DELETE');
});

test('an account outside the internal organization cannot enter onboarding', async () => {
  const replies = [
    response(200, { access: 'a', refresh: 'r' }),
    response(200, { user: { id: 1, username: 'owner' }, memberships: [] }),
  ];
  const Team = await loadTeam(async () => replies.shift());
  const gateway = new Team.TeamGateway({ apiBase: '/api' });

  await assert.rejects(gateway.login('owner', 'secret'), /尚未被主账号启用/);
  assert.equal(gateway.organizationId, '');
  assert.equal(gateway.refreshToken, 'r');
});
