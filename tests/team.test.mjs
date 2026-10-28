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

function emptyRawState() {
  return {
    products: [], suppliers: [], purchaseOrders: [], balances: [], ledger: [],
    orders: [], shipments: [], returns: [], competitors: [], snapshots: [],
    transfers: [], replenishmentPolicies: [], replenishmentRecommendations: [],
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

test('default buyer loads the complete catalog when only the optional profit rule directory returns 403', async () => {
  const calls = [];
  const product = { id: 'product-1', name: '商品', status: 'active', images: [], skus: [{ id: 'sku-1', code: 'SKU-1', cost: '10', currency: 'CNY', store_products: [{ id: 'listing-1', store: 'store-1', sale_price_myr: '79.90' }] }] };
  const summary = { sku: 'sku-1', sale_price: { min: '79.90', max: '79.90' }, gross_profit: { min: '30', max: '30' } };
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    if (url === '/api/profit-calculator/config/') return response(403, { detail: '没有查看利润规则权限' });
    if (url === '/api/sync/version/') return response(200, { revision: 7 });
    if (url === '/api/products/') return response(200, [product]);
    if (url === '/api/skus/profit-summary/') return response(200, [summary]);
    return response(200, []);
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.user = { is_owner: false };
  gateway.role = 'buyer';
  gateway.permissions = ['catalog', 'product_edit', 'purchase', 'replenishment'];
  gateway.accessToken = 'buyer-access';
  gateway.organizationId = 'org-1';
  gateway.warehouseId = 'warehouse-1';
  gateway.warehouses = [{ id: 'warehouse-1', name: '授权仓', active: true }];
  const state = await gateway.loadState();
  assert.equal(gateway.can('profit_rules'), false);
  assert.equal(calls.length, 18);
  assert.equal(state.products[0].storeProducts[0].sale_price_myr, '79.90');
  assert.equal(state.products[0].profitSummary.gross_profit.min, '30');
  assert.equal(state.profitCategories.length, 0);
  assert.equal(gateway.cache.profitConfig.category_tree.length, 0);
  assert.equal(gateway.syncRevision, 7);
  assert.ok(calls.every(call => call.options.headers.Authorization === 'Bearer buyer-access'));
});

test('profit rule failures remain visible; authentication failure still rejects the load', async () => {
  for (const status of [401, 500, 0]) {
    const Team = await loadTeam(async (url) => {
      if (url === '/api/profit-calculator/config/') {
        if (status === 0) throw new Error('connection lost');
        return response(status, { detail: 'request failed' });
      }
      return response(200, url === '/api/sync/version/' ? { revision: 1 } : []);
    });
    const gateway = new Team.TeamGateway({ apiBase: '/api' });
    if (status === 401) await assert.rejects(gateway.loadState(), error => error.status === status);
    else {
      await gateway.loadState();
      assert.equal(gateway.loadErrors[0].status, status);
      assert.equal(gateway.canWrite(), false);
    }
  }
});

test('403 from a core catalog endpoint is never hidden by optional profit rule fallback', async () => {
  for (const corePath of ['/api/products/', '/api/skus/profit-summary/']) {
    const Team = await loadTeam(async (url) => {
      if (url === corePath || url === '/api/profit-calculator/config/') return response(403, { detail: '禁止访问' });
      return response(200, url === '/api/sync/version/' ? { revision: 1 } : []);
    });
    const gateway = new Team.TeamGateway({ apiBase: '/api' });
    await assert.rejects(gateway.loadState(), error => error.status === 403);
  }
});

test('purchase outage preserves products and cached purchases, blocks writes, and retries without a revision change', async () => {
  let failing = false;
  const product = { id: 'p1', name: 'Existing', status: 'active', images: [], skus: [{id:'s1', code:'CAM', currency:'CNY', cost:'10'}] };
  const Team = await loadTeam(async url => {
    if (url === '/api/purchase-orders/' && failing) return response(500, {detail:'failed'});
    if (url === '/api/products/') return response(200, [product]);
    if (url === '/api/purchase-orders/') return response(200, [{id:'po1',number:'OLD',lines:[]}]);
    if (url === '/api/sync/version/') return response(200, {revision:7});
    return response(200, []);
  });
  const gateway = new Team.TeamGateway({apiBase:'/api'});
  gateway.user = {is_owner:true};
  gateway.accessToken = 'test';
  await gateway.loadState();
  failing = true;
  const partial = await gateway.loadState();
  assert.equal(partial.products[0].name, 'Existing');
  assert.equal(gateway.cache.purchaseOrders[0].id, 'po1');
  assert.equal(gateway.loadErrors[0].path, '/purchase-orders/');
  assert.equal(gateway.canWrite(), false);
  await assert.rejects(gateway.request('/orders/', {method:'POST',body:{}}), error => error.status === 409);
  assert.equal(await gateway.pollForUpdates(), null);
  failing = false;
  gateway.nextLoadRetryAt = 0;
  assert.ok(await gateway.pollForUpdates());
  assert.equal(gateway.loadErrors.length, 0);
  assert.equal(gateway.canWrite(), true);
});

test('first-load purchase failure cannot conceal successful catalog and stock reads', async () => {
  const Team = await loadTeam(async url => {
    if (url === '/api/purchase-orders/') return response(500, {detail:'failed'});
    if (url === '/api/products/') return response(200, [{id:'p',name:'Camera',status:'active',skus:[{id:'s',code:'CAM',cost:'1'}]}]);
    if (url === '/api/stock-balances/') return response(200, [{id:'b',sku:'s',warehouse:'w',on_hand:'17',reserved:'0'}]);
    return response(200, []);
  });
  const gateway = new Team.TeamGateway({apiBase:'/api'});
  const state = await gateway.loadState();
  assert.equal(state.products.length, 1);
  assert.equal(gateway.cache.balances[0].on_hand, '17');
  assert.equal(gateway.loadErrors.length, 1);
  assert.equal(gateway.canWrite(), false);
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
    defaultSupplier: '', productUrl: 'https://example.com/p', purchaseUrl: '',
    image: 'data:image/webp;base64,UklGRiIAAABXRUJQVlA4IBYAAABwAQCdASoBAAEAAUAmJaQAA3AA',
    monitoringEnabled: false, status: 'active',
    skus: [
      { id: 'sku-keep', code: 'KEEP', cost: 12, safetyStock: 3, attributes: { color: 'pink' } },
      { code: 'NEW', cost: 15, safetyStock: 4, attributes: { size: 'L' } },
    ],
  });
  assert.deepEqual(calls.map((call) => call.path), [
    '/products/product-1/', '/skus/sku-keep/', '/skus/', '/skus/sku-old/',
    '/product-images/', '/products/product-1/activate/',
  ]);
  assert.equal(calls[1].options.body.code, 'KEEP');
  assert.equal(calls[2].options.body.code, 'NEW');
  assert.equal(calls[3].options.body.active, false);
  assert.equal(calls.some(call => call.path.includes('/store-products/')), false, 'omitted listing draft must not erase existing store prices');
  assert.match(calls[4].options.body.url, /^data:image\/webp;base64,/);
});

function productDraft(overrides = {}) {
  return {
    kind: 'own', apiProductId: 'product-1', name: '商品', defaultSupplier: '',
    salesCurrency: 'CNY', costCurrency: 'CNY', productUrl: 'https://example.com/p',
    status: 'active', monitoringEnabled: false,
    skus: [{ id: 'sku-1', code: 'SKU-1', cost: '10', safetyStock: 0 }],
    storeListings: [{ skuId: 'sku-1', store: 'store-1', salePrice: '79.90', commission: '0' }],
    ...overrides,
  };
}

test('product editors save store pricing without status permission when product status is unchanged', async () => {
  const Team = await loadTeam();
  for (const status of ['active', 'inactive']) {
    const gateway = new Team.TeamGateway({ apiBase: '/api' });
    const raw = { id: 'product-1', status, skus: [{ id: 'sku-1', code: 'SKU-1', active: true }], images: [] };
    gateway.cache = { products: [raw], suppliers: [] };
    const calls = [];
    gateway.request = async (path, options) => {
      calls.push({ path, options });
      if (/\/(?:activate|deactivate)\/$/.test(path)) throw new Error('403: buyer has product_edit but no product_status');
      if (path === '/products/product-1/') return raw;
      if (path === '/skus/sku-1/') return { id: 'sku-1' };
      return [];
    };
    await gateway.saveProduct(productDraft({ status }));
    const listing = calls.find(call => call.path === '/skus/sku-1/store-products/');
    assert.equal(listing.options.body.items[0].sale_price_myr, '79.90');
    assert.equal(listing.options.body.items[0].commission_override_percent, '0');
    assert.equal(calls.some(call => /\/(?:activate|deactivate)\/$/.test(call.path)), false);
  }
});

test('an explicit product status change still calls the protected status endpoint', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  const raw = { id: 'product-1', status: 'active', skus: [{ id: 'sku-1', code: 'SKU-1' }], images: [] };
  gateway.cache = { products: [raw], suppliers: [] };
  const calls = [];
  gateway.request = async (path) => {
    calls.push(path);
    if (path === '/products/product-1/') return raw;
    if (path === '/skus/sku-1/') return { id: 'sku-1' };
    return {};
  };
  await gateway.saveProduct(productDraft({ status: 'inactive', storeListings: [] }));
  assert.equal(calls.filter(path => path === '/products/product-1/deactivate/').length, 1);
});

test('duplicate and incomplete SKU rows are rejected before supplier or product writes', async () => {
  const Team = await loadTeam();
  const cases = [
    { skus: [{ code: 'SKU-A', cost: 10 }, { code: ' sku-a ', cost: 20 }], expected: /编码不能重复/ },
    { skus: [{ code: '', cost: 10 }], expected: /补齐每条 SKU 编码/ },
    { skus: [{ id: 'sku-1', code: 'SKU-1', cost: '' }], expected: /有效的 SKU 成本/ },
    { skus: [{ id: 'sku-1', code: 'SKU-1', cost: 'abc' }], expected: /有效的 SKU 成本/ },
    { skus: [{ id: 'sku-1', code: 'SKU-1', cost: -1 }], expected: /有效的 SKU 成本/ },
  ];
  for (const { skus, expected } of cases) {
    const gateway = new Team.TeamGateway({ apiBase: '/api' });
    gateway.cache = { products: [], suppliers: [] };
    const calls = [];
    gateway.request = async (path) => { calls.push(path); return {}; };
    await assert.rejects(gateway.saveProduct(productDraft({ skus, defaultSupplier: '尚未创建的供应商', storeListings: [] })), expected);
    assert.deepEqual(calls, []);
  }
});

test('a completely blank new SKU can remain an empty draft without requesting a SKU URL', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  const raw = { id: 'product-1', status: 'draft', skus: [], images: [] };
  gateway.cache = { products: [raw], suppliers: [] };
  const calls = [];
  gateway.request = async (path) => { calls.push(path); return raw; };
  await gateway.saveProduct(productDraft({ status: 'draft', skus: [{ id: '', code: '', cost: '', safetyStock: 0, attributes: {}, packedWeightG: '', purchaseCostCny: '', creatorCommission: '', categoryCode: '' }], storeListings: [] }));
  assert.deepEqual(calls, ['/products/product-1/']);
});

test('an incomplete edit cannot downgrade a live product after saving some of its fields', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.cache = { products: [{ id: 'product-1', status: 'active', skus: [], images: [] }], suppliers: [] };
  const calls = [];
  gateway.request = async (path) => { calls.push(path); return {}; };
  await assert.rejects(gateway.saveProduct(productDraft({ status: 'draft' })), /不能退回草稿/);
  assert.deepEqual(calls, []);
});

test('unknown or skipped SKU listing references are rejected before any write', async () => {
  const Team = await loadTeam();
  for (const listing of [
    { skuId: 'removed-sku', store: 'store-1', salePrice: '10', commission: '' },
    { skuCode: 'REMOVED', store: 'store-1', salePrice: '10', commission: '' },
  ]) {
    const gateway = new Team.TeamGateway({ apiBase: '/api' });
    gateway.cache = { products: [], suppliers: [] };
    const calls = [];
    gateway.request = async (path) => { calls.push(path); return {}; };
    await assert.rejects(gateway.saveProduct(productDraft({ storeListings: [listing] })), /未填写或已移除的 SKU/);
    assert.deepEqual(calls, []);
  }
});

test('invalid listing prices and duplicate id/code aliases are rejected before any write', async () => {
  const Team = await loadTeam();
  const valid = { skuId: 'sku-1', store: 'store-1', salePrice: '10', commission: '' };
  const cases = [
    { rows: [{ ...valid, salePrice: null }], expected: /有效的店铺售价/ },
    { rows: [{ ...valid, salePrice: ' ' }], expected: /有效的店铺售价/ },
    { rows: [valid, { ...valid, skuId: '', skuCode: 'SKU-1' }], expected: /只能配置一次/ },
  ];
  for (const { rows, expected } of cases) {
    const gateway = new Team.TeamGateway({ apiBase: '/api' });
    gateway.cache = { products: [], suppliers: [] };
    const calls = [];
    gateway.request = async (path) => { calls.push(path); return {}; };
    await assert.rejects(gateway.saveProduct(productDraft({ storeListings: rows })), expected);
    assert.deepEqual(calls, []);
  }
});

test('multi SKU drafts route existing and new SKU store prices correctly while skipping blank new rows', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  const raw = { id: 'product-1', status: 'draft', skus: [{ id: 'sku-1', code: 'SKU-1' }], images: [] };
  gateway.cache = { products: [raw], suppliers: [] };
  const calls = [];
  gateway.request = async (path, options) => {
    calls.push({ path, options });
    if (path === '/products/product-1/') return raw;
    if (path === '/skus/sku-1/') return { id: 'sku-1' };
    if (path === '/skus/') return { id: 'sku-new' };
    return [];
  };
  await gateway.saveProduct(productDraft({ status: 'draft',
    skus: [{ id: 'sku-1', code: 'SKU-1', cost: 10 }, { code: ' SKU-NEW ', cost: 0 }, { code: '', cost: '', safetyStock: 0, attributes: {} }],
    storeListings: [
      { skuId: 'sku-1', store: 'store-1', salePrice: '79.90', commission: '0', include: false },
      { skuCode: 'SKU-NEW', store: 'store-2', salePrice: '89.90', commission: '' },
    ],
  }));
  const listingCalls = calls.filter(call => call.path.includes('/store-products/'));
  assert.deepEqual(listingCalls.map(call => call.path), ['/skus/sku-1/store-products/', '/skus/sku-new/store-products/']);
  assert.equal(listingCalls[0].options.body.items[0].store, 'store-1');
  assert.equal(listingCalls[0].options.body.items[0].include_in_list_calculation, false);
  assert.equal(listingCalls[1].options.body.items[0].store, 'store-2');
  assert.equal(listingCalls[1].options.body.items[0].commission_override_percent, null);
  assert.equal(calls.find(call => call.path === '/skus/').options.body.cost, 0);
});

test('team gateway hard-deletes an eligible product and a draft purchase', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  const calls = [];
  gateway.request = async (path, options = {}) => { calls.push({ path, options }); return null; };

  await gateway.deleteProduct({ kind: 'own', apiProductId: 'product-1' });
  await gateway.deletePurchase({ id: 'purchase-1' });

  assert.deepEqual(calls.map((call) => call.path), [
    '/products/product-1/', '/purchase-orders/purchase-1/',
  ]);
  assert.deepEqual(calls.map((call) => call.options.method), ['DELETE', 'DELETE']);
});

test('primary warehouse save keeps server UUID and omits blank safety stock', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  let body;
  gateway.request = async (path, options) => { body = options.body; return {}; };
  await gateway.saveReplenishmentPolicy({ skuId: 'sku-1' }, { primaryWarehouse: '22222222-2222-4222-8222-222222222222', safetyStockOverride: null });
  assert.equal(body.fields.primary_warehouse, '22222222-2222-4222-8222-222222222222');
  assert.equal(Object.hasOwn(body.fields, 'safety_stock'), false);
  await gateway.saveReplenishmentPolicy({ skuId: 'sku-1' }, { primaryWarehouse: null, safetyStockOverride: 0 });
  assert.equal(body.fields.safety_stock, 0);
});

test('purchase edit retains blank packages and separate domestic/international tracking', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  let body;
  gateway.request = async (path, options) => { body = options.body; return {}; };
  await gateway.editPurchase({ id: 'po', supplierId: 'supplier', lines: [], shipments: [
    { id: '11111111-1111-4111-8111-111111111111', trackingNumber: '', domesticTrackingNumber: '', internationalTrackingNumber: '', lines: [] },
    { trackingNumber: 'LEGACY', domesticTrackingNumber: ' CN ', internationalTrackingNumber: ' INT ', lines: [] },
  ] });
  assert.equal(body.shipments.length, 2);
  assert.equal(body.shipments[0].id, '11111111-1111-4111-8111-111111111111');
  assert.equal(body.shipments[1].tracking_number, 'LEGACY');
  assert.equal(body.shipments[1].domestic_tracking_number, 'CN');
  assert.equal(body.shipments[1].international_tracking_number, 'INT');
});

test('second purchase edit normalizes legacy tracking data before it reaches the API', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.warehouseId = 'warehouse-1';
  let requestCall;
  gateway.request = async (path, options = {}) => {
    requestCall = { path, options };
    return { id: 'purchase-1' };
  };

  await gateway.editPurchase({
    id: 'purchase-1', number: 'PO-SECOND-EDIT', supplierId: 'supplier-1', purchaserId: '',
    orderedAt: '2026-07-24', expectedAt: '2026-07-30', note: '', extraCost: 0,
    lines: [{ id: 'line-1', skuId: 'sku-1', orderedQty: 10, unitCost: 9.06, currency: 'CNY' }],
    shipments: [{ id: 'browser-draft-shipment', trackingNumber: ' 2313441232 ', lines: [] }],
  });

  const body = requestCall.options.body;
  assert.equal(requestCall.path, '/purchase-orders/purchase-1/edit/');
  assert.equal(body.shipments[0].tracking_number, '2313441232');
  assert.equal(Object.hasOwn(body.shipments[0], 'id'), false);
  assert.equal(Object.hasOwn(body, 'purchaser'), false);
});

test('purchase save response updates cached purchases without loading monitoring APIs', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.warehouseId = 'warehouse-1';
  gateway.warehouses = [{ id: 'warehouse-1', name: '采购仓' }];
  gateway.cache = emptyRawState();
  gateway.cache.products = [{
    id: 'product-1', name: '商品', kind: 'own', status: 'active', currency: 'CNY',
    images: [], skus: [{ id: 'sku-1', code: 'SKU-1', active: true, cost: '1.00', currency: 'CNY' }]
  }];
  gateway.cache.suppliers = [{ id: 'supplier-1', name: '供应商' }];

  const state = gateway.applyPurchaseOrderResult({
    id: 'purchase-1', number: 'PO-CACHED', status: 'submitted', supplier: 'supplier-1',
    warehouse: 'warehouse-1', purchaser: null, ordered_at: '2026-07-27T00:00:00Z',
    expected_at: null, extra_cost: '0', notes: '', created_at: '2026-07-27T00:00:00Z',
    updated_at: '2026-07-27T00:00:00Z',
    lines: [{ id: 'line-1', sku: 'sku-1', quantity_ordered: '2', quantity_received: '0', unit_cost: '1.00' }],
    shipments: [{ id: 'shipment-1', tracking_number: 'YT-SECOND', lines: [] }]
  });

  assert.equal(state.purchaseOrders.length, 1);
  assert.equal(state.purchaseOrders[0].shipments[0].trackingNumber, 'YT-SECOND');
  assert.equal(gateway.cache.competitors.length, 0);
  assert.equal(gateway.cache.snapshots.length, 0);
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

test('team adapter preserves authoritative inbound total and all source rows', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.warehouseId = 'wh-1';
  gateway.warehouses = [{ id: 'wh-1', code: 'MY', name: '马来仓', active: true }];
  const raw = emptyRawState();
  raw.products = [{
    id: 'product-1', name: '豹纹托特-棕色', status: 'active', images: [],
    skus: [{ id: 'sku-1', code: 'AI-BAG-BROWN-05', active: true }],
  }];
  raw.balances = [{
    id: 'balance-1', warehouse: 'wh-1', sku: 'sku-1', on_hand: '7', reserved: '0',
    purchased_pending_shipment: '150.000', in_transit: '95.000', inbound_total: '245.000',
    purchased_pending_sources: [{ source_number: 'PO-20260805-2715', remaining_quantity: '150.000' }],
    in_transit_sources: [{ source_number: 'TR-20260729-1510', remaining_quantity: '95.000' }],
  }];

  const state = gateway.adaptState(raw);
  const balance = state.inventoryBalances[0];

  assert.equal(balance.purchasedPendingShipment, 150);
  assert.equal(balance.inTransit, 95);
  assert.equal(balance.inboundTotal, 245);
  assert.equal(balance.purchasedPendingSources[0].source_number, 'PO-20260805-2715');
  assert.equal(balance.inTransitSources[0].source_number, 'TR-20260729-1510');
});

test('warehouse modal APIs, cancellation restore, and partial transfer payloads use the ERP endpoints once', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  const calls = [];
  gateway.request = async (path, options = {}) => { calls.push({ path, options }); return { id: 'ok' }; };
  const order = { id: 'order-1' };
  const transfer = { id: 'transfer-1', status: 'in_transit' };

  await gateway.getOrderWarehouseOptions(order);
  await gateway.assignOrderWarehouse(order, 'warehouse-1', false);
  await gateway.cancelOrder(order);
  await gateway.restoreOrderFulfillment(order);
  await gateway.receiveTransfer(transfer, [{ transferLineId: 'line-a', quantity: 2 }]);
  await gateway.closeTransferException(transfer, [{ transferLineId: 'line-b', quantity: 1 }], '');

  assert.equal(calls[0].path, '/orders/order-1/warehouse-options/');
  assert.equal(calls[1].path, '/orders/order-1/assign-warehouse/');
  assert.equal(calls[2].path, '/orders/order-1/cancel/');
  assert.equal(calls[3].path, '/orders/order-1/restore-fulfillment/');
  assert.equal(JSON.stringify(calls[4].options.body.quantities), JSON.stringify({ 'line-a': 2 }));
  assert.equal(JSON.stringify(calls[5].options.body.quantities), JSON.stringify({ 'line-b': 1 }));
  assert.match(calls[5].options.body.idempotency_key, /^transfer-close-transit-exception:/);
  assert.equal(calls[5].options.body.reason, '');
});

test('order creation uses one idempotent create-and-ship request and keeps shortage outcome', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.warehouseId = 'warehouse-1';
  const calls = [];
  gateway.request = async (path, options = {}) => {
    calls.push({ path, options });
    return { outcome: 'shortage', order: { id: 'order-1' }, shortages: [{ sku: 'SKU-A', shortage: '2' }] };
  };
  const result = await gateway.createOrder({
    number: 'SO-ONE', platform: 'TikTok Shop', store: 'MY', orderedAt: '2026-08-13T10:00:00Z',
    trackingNumber: '', note: '', lines: [{ skuId: 'sku-a', quantity: 5 }],
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/orders/create-and-ship/');
  assert.equal(calls[0].options.body.lines[0].quantity, 5);
  assert.ok(calls[0].options.body.idempotency_key);
  assert.equal(result.shortage, true);
  assert.equal(result.shipped, false);
});

test('transfer packages allow blank tracking while preserving exact SKU quantities before dispatch', async () => {
  const Team = await loadTeam();
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  let call;
  gateway.request = async (path, options = {}) => { call = { path, options }; return {}; };
  await gateway.saveTransferPackages({ id: 'transfer-1', status: 'draft' }, [
    { id: 'browser-package', trackingNumber: '', lines: [{ skuId: 'sku-a', quantity: 2 }] },
    { trackingNumber: 'TRACK-2', lines: [{ skuId: 'sku-a', quantity: 3 }] },
  ]);
  assert.equal(call.path, '/stock-transfers/transfer-1/packages/');
  assert.equal(call.options.body.packages[0].tracking_number, '');
  assert.equal(Object.hasOwn(call.options.body.packages[0], 'id'), false);
  assert.equal(JSON.stringify(call.options.body.packages[1].lines), JSON.stringify([{ sku: 'sku-a', quantity: 3 }]));
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

test('team adapter adds existing own products to monitoring and deletes only the profile', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return response(options.method === 'DELETE' ? 204 : 200, {});
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'access-token';
  gateway.organizationId = 'org-1';

  await gateway.addOwnProductsToMonitoring(['product-a', 'product-b']);
  await gateway.removeMonitoringProfile({ apiCompetitorId: 'profile-a' });

  assert.equal(calls[0].url, '/api/competitors/add-own-products/');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), { product_ids: ['product-a', 'product-b'] });
  assert.equal(calls[1].url, '/api/competitors/profile-a/');
  assert.equal(calls[1].options.method, 'DELETE');
});

test('API error shows the safe upstream status and diagnostic reference', async () => {
  const Team = await loadTeam(async () => response(502, {
    detail: '选品服务暂时异常，请稍后重试。',
    upstream_status: 503,
    diagnostic_id: 'a1b2c3d4e5f6',
  }));
  const gateway = new Team.TeamGateway({ apiBase: '/api' });

  await assert.rejects(
    () => gateway.searchProductSelectionKeywords({ platform: 'tiktok', region: 'MY', keyword: 'bag' }),
    /选品服务暂时异常.*上游 HTTP 503.*诊断编号 a1b2c3d4e5f6/,
  );
});

test('organization replenishment settings can be loaded and saved independently of SKU overrides', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return response(200, calls.length === 1 ? [{ id: 'settings-1', safety_days: '7.00' }] : { id: 'settings-1' });
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';
  const settings = await gateway.getReplenishmentSettings();
  await gateway.saveReplenishmentSettings({ safety_days: 9, default_lead_time_days: 18 });
  assert.equal(settings.id, 'settings-1');
  assert.equal(calls[0].url, '/api/replenishment-settings/');
  assert.equal(calls[1].url, '/api/replenishment-settings/');
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(JSON.parse(calls[1].options.body).safety_days, 9);
});

test('AI provider settings support edit, request parameters, and usage log queries', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return response(200, []);
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';
  await gateway.updateAIProvider('provider-1', { default_parameters: { temperature: 0.2 } });
  await gateway.listAIInvocations();
  assert.equal(calls[0].url, '/api/ai-providers/provider-1/');
  assert.equal(calls[0].options.method, 'PATCH');
  assert.deepEqual(JSON.parse(calls[0].options.body), { default_parameters: { temperature: 0.2 } });
  assert.equal(calls[1].url, '/api/ai-invocations/');
});

test('AI workbench creates proposals and records confirm or reject decisions separately', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => {
    calls.push({ url, options });
    return response(200, { id: 'recommendation-1' });
  });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.accessToken = 'token';
  gateway.organizationId = 'org-1';
  await gateway.listAIRecommendations();
  await gateway.createAIRecommendation({ provider: 'provider-1', kind: 'replenishment', input_data: { sku: 'sku-1' } });
  await gateway.confirmAIRecommendation('recommendation-1', 'reviewed');
  await gateway.rejectAIRecommendation('recommendation-2', 'not suitable');
  assert.equal(calls[0].url, '/api/ai-recommendations/');
  assert.equal(calls[1].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    provider: 'provider-1', kind: 'replenishment', input_data: { sku: 'sku-1' }
  });
  assert.equal(calls[2].url, '/api/ai-recommendations/recommendation-1/confirm/');
  assert.equal(calls[3].url, '/api/ai-recommendations/recommendation-2/reject/');
  assert.deepEqual(JSON.parse(calls[2].options.body), { reason: 'reviewed' });
  assert.deepEqual(JSON.parse(calls[3].options.body), { reason: 'not suitable' });
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

test('analytics, creator CRM, profit plans and final transfer exception use audited ERP endpoints', async () => {
  const calls = [];
  const Team = await loadTeam(async (url, options) => { calls.push({ url, options }); return response(200, []); });
  const gateway = new Team.TeamGateway({ apiBase: '/api' });
  gateway.organizationId = 'org-1';
  await gateway.getAnalyticsOverview({ days: 7, store: 'store-1' });
  await gateway.getReplenishmentDemandDetail({ skuId: 'sku-1' }, 30);
  await gateway.listCreators({ stage: 'pending' });
  await gateway.createCreatorActivity('creator-1', 'collaboration', { stage: 'pending' });
  await gateway.listProfitPlans({ status: 'active' });
  await gateway.prepareProfitPlanRecalculation('plan-1', 'version-2');
  await gateway.completeTransferWithException({ id: 'transfer-1' }, '');
  assert.match(calls[0].url, /analytics\/overview\/\?days=7.*store=store-1/);
  assert.equal(calls[1].url, '/api/replenishment/demand-detail/?sku=sku-1&days=30');
  assert.equal(calls[2].url, '/api/creators/?stage=pending');
  assert.equal(calls[3].url, '/api/creators/creator-1/collaborations/');
  assert.equal(calls[4].url, '/api/profit-calculator/plans/');
  assert.equal(calls[5].url, '/api/profit-calculator/plans/plan-1/recalculate/');
  assert.deepEqual(JSON.parse(calls[5].options.body), { version: 'version-2' });
  assert.equal(calls[6].url, '/api/stock-transfers/transfer-1/complete-with-exception/');
  assert.equal(JSON.parse(calls[6].options.body).reason, '');
  assert.match(JSON.parse(calls[6].options.body).idempotency_key, /^transfer-complete-with-exception:/);
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
