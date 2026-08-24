const STORAGE_KEY = 'dongbo-crossborder.v1';
const LEGACY_STORAGE_KEY = 'pulsetrack.manual.v2';
const UI_STORAGE_KEY = 'dongbo-crossborder.ui.v1';
const STATE_VERSION = 6;
const DEFAULT_WAREHOUSE_ID = 'warehouse-default';
const COLORS = ['#0F8B8D', '#F59E0B', '#3B82F6', '#E05252', '#5A8F62', '#8B6BB5'];
const WAREHOUSE_TYPE_LABELS = { domestic: '国内仓', overseas: '海外仓', forwarder: '货代仓', school: '学校仓', other: '其他' };
const TRANSFER_LABELS = { draft: '草稿', in_transit: '调拨在途', partially_received: '部分收货', received: '已收货', completed_with_exception: '已完成（有异常）', cancelled: '已取消' };
const KIND_LABELS = { own: '本店商品', direct: '直接竞品', indirect: '间接竞品' };
const CURRENCY = { CNY: '¥', MYR: 'RM', USD: '$', GBP: '£', SGD: 'S$', THB: '฿', VND: '₫', PHP: '₱', IDR: 'Rp' };
const PURCHASE_LABELS = { draft: '草稿', ordered: '已下单', transit: '在途', partial: '部分收货', completed: '已完成', cancelled: '已取消' };
const ORDER_LABELS = { shortage: '库存不足', picking: '拣货中', review: '待复核', ready: '待出库', shipped: '已出库', cancelled: '已取消' };
const MOVEMENT_LABELS = {
  opening: '期初库存', receipt: '采购收货', reserve: '订单锁定', release: '释放锁定',
  outbound: '订单出库', return: '退货入库', adjustment: '库存调整', manual_in: '手动入库', manual_inbound: '手动入库', manual_outbound: '手动出库', reversal: '已撤回冲销', adjust_add: '盘盈', adjust_sub: '盘亏', damage: '报损',
  transfer_out: '调拨出库', transfer_in: '调拨入库', transfer_return: '取消调拨退回'
};
const RUNTIME_CONFIG = Object.assign({ mode: 'local', apiBase: '/api', allowLocalFallback: false }, globalThis.DONGBO_CONFIG || {});
const TEAM_MODE = RUNTIME_CONFIG.mode === 'team';
const teamGateway = TEAM_MODE && globalThis.DongboTeam ? new globalThis.DongboTeam.TeamGateway(RUNTIME_CONFIG) : null;

function emptyState() {
  return {
    version: STATE_VERSION,
    revision: 1,
    warehouses: [{
      id: DEFAULT_WAREHOUSE_ID, code: 'MAIN', name: '默认仓', type: 'domestic', country: 'CN',
      address: '', timezone: 'Asia/Shanghai', contact: '', canReceive: true, canShip: true, active: true
    }],
    products: [],
    stores: [],
    storeProducts: [],
    profitCategories: [],
    snapshots: [],
    purchaseOrders: [],
    receipts: [],
    inventoryBalances: [],
    inventoryMovements: [],
    salesOrders: [],
    reservations: [],
    shipments: [],
    returns: [],
    stockTransfers: [],
    replenishmentPolicies: [],
    replenishmentRecommendations: [],
    legacyStockEvents: [],
    migrationIssues: [],
    selectedProductId: '',
    ui: { module: 'products', warehouseTab: 'purchase', competitorTab: 'overview', warehouseId: DEFAULT_WAREHOUSE_ID }
  };
}

function seedState() {
  const base = emptyState();
  const productId = 'tt-my-1734050283349837382';
  base.products.push({
    id: productId,
    name: '蝴蝶图案帆布托特包',
    sku: '',
    seller: 'Tas Inspirasi',
    kind: 'direct',
    market: 'MY',
    salesCurrency: 'MYR',
    costCurrency: 'MYR',
    standardCost: 0,
    safetyStock: 0,
    defaultSupplier: '',
    status: 'active',
    productUrl: 'https://www.tiktok.com/view/product/1734050283349837382',
    purchaseUrl: '',
    image: 'https://images.unsplash.com/photo-1594223274512-ad4803739b7c?auto=format&fit=crop&w=240&q=80',
    monitoringEnabled: true,
    needsReview: false,
    createdAt: '2026-07-14T17:37:26+08:00',
    updatedAt: '2026-07-14T17:37:26+08:00'
  });
  base.snapshots.push({
    id: 'snap-baseline-1734050283349837382',
    productId: productId,
    at: '2026-07-14T17:37:26+08:00',
    currency: 'MYR',
    price: 18.69,
    sold: 901,
    rating: 4.8,
    reviews: 56,
    lowReviews: 1,
    shopRating: null,
    createdAt: '2026-07-14T17:37:26+08:00'
  });
  base.selectedProductId = productId;
  return base;
}

let state = TEAM_MODE ? emptyState() : loadState();
let productFilter = 'all';
let purchaseFilter = 'open';
let transferFilter = 'open';
let orderFilter = 'open';
let inventoryFilter = 'all';
let inventorySection = 'list';
let profitView = 'calculator';
let profitScrollTarget = 'profitInputPanel';
let chartMetric = 'sales';
let searchTerm = '';
let pendingConfirm = null;
let inventoryStickyHeader = null;
let replenishmentStickyHeader = null;
let pendingProductImage = '';
let tiktokConnections = [];
let aiProviderConfigs = [];
let aiInvocationLogs = [];
let aiRecommendations = [];
let alphashopConfig = null;
let draftProductSkus = [];
let draftStoreListings = [];
let draftPurchaseLines = [];
let draftPurchaseShipments = [];
let purchaseEditId = '';
let purchaseMembers = [];
let draftOrderLines = [];
let draftTransferLines = [];
let draftTransferPackages = [];
let activeOrderWarehouseSelection = null;
let activeTransferWorkflow = null;
let activeTransferCompletion = null;
let transferCompletionBusy = false;
let replenishmentSelectedSkuIds = new Set();
let analyticsState = { overview: null, stores: [], skus: [], loading: '', loaded: {}, error: {} };
let creatorState = { rows: [], loading: false, loaded: false, error: '', active: null };
let profitPlanState = { rows: [], loading: false, loaded: false, error: '', active: null, versions: [] };
let expandedProfitSkuIds = new Set();
let monitoringPickerTerm = '';
let monitoringPickerSelected = new Set();
let toastTimer = null;
let teamBusy = false;
let teamLastSyncedAt = '';
let teamRealtimeTimer = null;
let pendingMigrationSource = null;
let pendingMigrationPreview = null;
let ownerLoginChallengeId = '';
let ownerPasswordChallengeId = '';
let ownerPermissionCatalog = {};
let ownerRoleCatalog = {};
let ownerWarehouseCatalog = [];
const INTERNAL_ROLE_CATALOG = {
  admin: '管理员',
  manager: '经理',
  buyer: '采购',
  warehouse: '仓库',
  viewer: '只读',
};
let internalAccounts = [];
let selectionState = {
  statusLoaded: false, configured: false, source: 'none', loadingStatus: false,
  loadingKeywords: false, loadingReport: false, keywords: [], selectedKeyword: '',
  keywordResponseCached: false, report: null, reportCached: false,
  platformRegions: { tiktok: ['MY'], amazon: ['US'] }
};

const $ = function (selector) { return document.querySelector(selector); };
const $$ = function (selector) { return Array.from(document.querySelectorAll(selector)); };
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function uid(prefix) { return prefix + '-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8); }
function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>'"]/g, function (char) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char];
  });
}
function asNumber(value, fallback) {
  const result = Number(value);
  return Number.isFinite(result) ? result : (fallback == null ? 0 : fallback);
}
function nonNegative(value) { return Math.max(0, asNumber(value)); }
function integer(value) { return Math.max(0, Math.floor(asNumber(value))); }
function localDateTime(date) {
  const source = date || new Date();
  const local = new Date(source.getTime() - source.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}
function today() { return localDateTime(new Date()).slice(0, 10); }
function formatDate(value, withTime) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: withTime ? '2-digit' : undefined,
    minute: withTime ? '2-digit' : undefined,
    hour12: false
  }).format(date);
}
function safeImageUrl(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  if (/^data:image\/(?:png|jpe?g|webp);base64,/i.test(text)) return text.length <= 560000 ? text : '';
  if (text.length > 4096) return '';
  try {
    const url = new URL(text);
    return url.protocol === 'http:' || url.protocol === 'https:' ? text : '';
  } catch (_) {
    return '';
  }
}
function exportableImageUrl(value) {
  const image_url = safeImageUrl(value);
  return /^https?:/i.test(image_url) ? image_url : '';
}
function currencySymbol(code) { return CURRENCY[code] || code || ''; }
function money(value, code) {
  return currencySymbol(code) + Number(nonNegative(value)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function productById(productId, source) {
  const root = source || state;
  return root.products.find(function (item) { return item.id === productId; });
}
function ownProducts(source, includeInactive) {
  const root = source || state;
  return root.products.filter(function (item) {
    return item.kind === 'own' && (includeInactive || item.status === 'active');
  });
}
function monitoredProducts(source) {
  const root = source || state;
  return root.products.filter(function (item) {
    return item.status === 'active' && (item.kind !== 'own' || item.monitoringEnabled);
  });
}
function normalizeSku(value) { return String(value || '').trim().toUpperCase(); }

function normalizeProduct(product) {
  const kind = ['own', 'direct', 'indirect'].includes(product.kind) ? product.kind : 'direct';
  const salesCurrency = product.salesCurrency || product.currency || (kind === 'own' ? 'CNY' : 'MYR');
  const image = safeImageUrl(product.image || '');
  const sku = String(product.sku || '').trim();
  const standardCost = nonNegative(product.standardCost == null ? product.cost : product.standardCost);
  return {
    id: product.id || uid('product'),
    apiProductId: product.apiProductId || '',
    apiCompetitorId: product.apiCompetitorId || '',
    skuId: product.skuId || '',
    catalogProductId: product.catalogProductId || product.apiProductId || product.id || '',
    skuActive: product.skuActive !== false,
    imageId: product.imageId || '',
    defaultSupplierId: product.defaultSupplierId || '',
    skuCount: integer(product.skuCount || (product.sku ? 1 : 0)),
    name: String(product.name || '').trim(),
    sku: sku,
    seller: String(product.seller || '').trim(),
    kind: kind,
    market: product.market || 'MY',
    salesCurrency: salesCurrency,
    costCurrency: product.costCurrency || salesCurrency,
    standardCost: standardCost,
    safetyStock: integer(product.safetyStock),
    defaultSupplier: String(product.defaultSupplier || product.supplier || '').trim(),
    status: ['active', 'inactive', 'draft'].includes(product.status) ? product.status : 'active',
    productUrl: String(product.productUrl || product.url || '').trim(),
    purchaseUrl: String(product.purchaseUrl || '').trim(),
    image: image,
    monitoringEnabled: kind !== 'own' ? true : Boolean(product.monitoringEnabled == null ? product.compare : product.monitoringEnabled),
    needsReview: Boolean(product.needsReview),
    createdAt: product.createdAt || new Date().toISOString(),
    updatedAt: product.updatedAt || product.createdAt || new Date().toISOString()
  };
}

function normalizeWarehouse(warehouse, index) {
  const fallbackCode = index === 0 ? 'MAIN' : 'WH-' + String(index + 1).padStart(2, '0');
  const rawType = warehouse.type === 'local' ? 'domestic' : warehouse.type;
  const legacyDefault = !rawType && (String(warehouse.id || '') === DEFAULT_WAREHOUSE_ID || String(warehouse.code || fallbackCode).toUpperCase() === 'MAIN');
  return {
    id: String(warehouse.id || uid('warehouse')),
    apiWarehouseId: warehouse.apiWarehouseId || '',
    code: String(warehouse.code || fallbackCode).trim().toUpperCase(),
    name: String(warehouse.name || '未命名仓库').trim(),
    type: WAREHOUSE_TYPE_LABELS[rawType] ? rawType : (legacyDefault ? 'domestic' : 'other'),
    country: String(warehouse.country || 'CN').trim().toUpperCase(),
    address: String(warehouse.address || '').trim(),
    timezone: String(warehouse.timezone || 'Asia/Shanghai').trim(),
    contact: String(warehouse.contact || '').trim(),
    canReceive: warehouse.canReceive !== false && warehouse.can_receive !== false,
    canShip: warehouse.canShip !== false && warehouse.can_ship !== false,
    active: warehouse.active !== false,
    createdAt: warehouse.createdAt || warehouse.created_at || new Date().toISOString(),
    updatedAt: warehouse.updatedAt || warehouse.updated_at || new Date().toISOString()
  };
}

function normalizeV5(saved) {
  const base = emptyState();
  base.revision = integer(saved.revision) || 1;
  base.warehouses = Array.isArray(saved.warehouses) && saved.warehouses.length
    ? saved.warehouses.map(normalizeWarehouse)
    : base.warehouses;
  base.products = Array.isArray(saved.products) ? saved.products.map(normalizeProduct) : [];
  // TeamGateway already receives these server facts.  Keep them when a fresh
  // normalized state is constructed, otherwise store CRUD appears successful
  // but the next render (and F5) sees an empty collection.
  base.stores = Array.isArray(saved.stores) ? saved.stores : [];
  base.storeProducts = Array.isArray(saved.storeProducts) ? saved.storeProducts : [];
  base.profitCategories = Array.isArray(saved.profitCategories) ? saved.profitCategories : [];
  base.snapshots = (Array.isArray(saved.snapshots) ? saved.snapshots : []).map(function (item) {
    const product = base.products.find(function (entry) { return entry.id === item.productId; });
    return {
      id: item.id || uid('snap'),
      apiSnapshotId: item.apiSnapshotId || '',
      productId: item.productId,
      at: item.at || item.capturedAt || new Date().toISOString(),
      currency: item.currency || (product ? product.salesCurrency : 'CNY'),
      price: nonNegative(item.price),
      sold: integer(item.sold),
      rating: item.rating === '' || item.rating == null ? null : nonNegative(item.rating),
      reviews: integer(item.reviews),
      lowReviews: integer(item.lowReviews),
      shopRating: item.shopRating === '' || item.shopRating == null ? null : nonNegative(item.shopRating),
      createdAt: item.createdAt || item.at || new Date().toISOString()
    };
  }).filter(function (item) { return Boolean(productById(item.productId, base)); });
  base.purchaseOrders = Array.isArray(saved.purchaseOrders) ? saved.purchaseOrders : [];
  base.receipts = Array.isArray(saved.receipts) ? saved.receipts : [];
  base.inventoryBalances = Array.isArray(saved.inventoryBalances) ? saved.inventoryBalances.map(function (item) {
    return {
      warehouseId: item.warehouseId || DEFAULT_WAREHOUSE_ID,
      productId: item.productId,
      onHand: integer(item.onHand),
      reserved: integer(item.reserved),
      purchasedPendingShipment: integer(item.purchasedPendingShipment),
      inTransit: integer(item.inTransit),
      inboundTotal: integer(item.inboundTotal),
      purchasedPendingSources: Array.isArray(item.purchasedPendingSources) ? item.purchasedPendingSources : [],
      inTransitSources: Array.isArray(item.inTransitSources) ? item.inTransitSources : [],
      updatedAt: item.updatedAt || ''
    };
  }) : [];
  base.inventoryMovements = Array.isArray(saved.inventoryMovements) ? saved.inventoryMovements : [];
  base.salesOrders = Array.isArray(saved.salesOrders) ? saved.salesOrders : [];
  base.reservations = Array.isArray(saved.reservations) ? saved.reservations : [];
  base.shipments = Array.isArray(saved.shipments) ? saved.shipments : [];
  base.returns = Array.isArray(saved.returns) ? saved.returns : [];
  base.stockTransfers = Array.isArray(saved.stockTransfers) ? saved.stockTransfers : [];
  base.replenishmentPolicies = Array.isArray(saved.replenishmentPolicies) ? saved.replenishmentPolicies : [];
  base.replenishmentRecommendations = Array.isArray(saved.replenishmentRecommendations) ? saved.replenishmentRecommendations : [];
  base.legacyStockEvents = Array.isArray(saved.legacyStockEvents) ? saved.legacyStockEvents : [];
  base.migrationIssues = Array.isArray(saved.migrationIssues) ? saved.migrationIssues : [];
  base.selectedProductId = saved.selectedProductId || '';
  const savedUi = saved.ui && typeof saved.ui === 'object' ? saved.ui : {};
  if (savedUi.module === 'competitors') base.ui.module = 'analytics';
  else if (['products', 'selection', 'warehouse', 'analytics', 'creators', 'profit'].includes(savedUi.module)) base.ui.module = savedUi.module;
  if (['purchase', 'inventory', 'transfers', 'replenishment', 'orders'].includes(savedUi.warehouseTab)) base.ui.warehouseTab = savedUi.warehouseTab;
  if (['overview', 'stores', 'skus', 'products', 'snapshots', 'trends', 'alerts'].includes(savedUi.competitorTab)) base.ui.competitorTab = savedUi.competitorTab;
  const activeWarehouse = base.warehouses.find(function (item) { return item.active && item.id === savedUi.warehouseId; }) ||
    base.warehouses.find(function (item) { return item.active; }) || base.warehouses[0];
  base.ui.warehouseId = activeWarehouse ? activeWarehouse.id : DEFAULT_WAREHOUSE_ID;
  base.version = STATE_VERSION;
  ownProducts(base, true).forEach(function (product) {
    if (!base.inventoryBalances.some(function (item) { return item.productId === product.id && item.warehouseId === base.ui.warehouseId; })) {
      base.inventoryBalances.push({ warehouseId: base.ui.warehouseId, productId: product.id, onHand: 0, reserved: 0, updatedAt: '' });
    }
  });
  if (!monitoredProducts(base).some(function (item) { return item.id === base.selectedProductId; })) {
    base.selectedProductId = monitoredProducts(base)[0] ? monitoredProducts(base)[0].id : '';
  }
  return base;
}

function migrateLegacy(saved) {
  const next = emptyState();
  const migratedAt = new Date().toISOString();
  next.products = (saved.products || []).map(function (raw) {
    const item = normalizeProduct(raw);
    const issues = [];
    if (!item.name) issues.push('缺少商品名称');
    if (!item.image) issues.push('缺少商品图片');
    if (!item.productUrl) issues.push('缺少商品链接');
    if (item.kind === 'own' && !item.sku) issues.push('缺少 SKU');
    if (item.kind === 'own' && !item.costCurrency) issues.push('缺少成本币种');
    item.needsReview = issues.length > 0;
    issues.forEach(function (reason) {
      next.migrationIssues.push({ id: uid('issue'), productId: item.id, reason: reason, createdAt: migratedAt });
    });
    return item;
  });
  const seenSkus = new Map();
  ownProducts(next, true).forEach(function (product) {
    const sku = normalizeSku(product.sku);
    if (!sku) return;
    if (seenSkus.has(sku)) {
      product.needsReview = true;
      const first = productById(seenSkus.get(sku), next);
      if (first) first.needsReview = true;
      next.migrationIssues.push({ id: uid('issue'), productId: product.id, reason: 'SKU 与其他商品重复', createdAt: migratedAt });
    } else {
      seenSkus.set(sku, product.id);
    }
  });
  next.snapshots = (saved.snapshots || []).map(function (item) {
    const product = productById(item.productId, next);
    return {
      id: item.id || uid('snap'),
      productId: item.productId,
      at: item.at || migratedAt,
      currency: item.currency || (product ? product.salesCurrency : 'CNY'),
      price: nonNegative(item.price),
      sold: integer(item.sold),
      rating: item.rating == null || item.rating === '' ? null : nonNegative(item.rating),
      reviews: integer(item.reviews),
      lowReviews: integer(item.lowReviews),
      shopRating: item.shopRating == null || item.shopRating === '' ? null : nonNegative(item.shopRating),
      createdAt: item.createdAt || item.at || migratedAt
    };
  }).filter(function (item) { return Boolean(productById(item.productId, next)); });
  next.legacyStockEvents = Array.isArray(saved.stockMovements) ? clone(saved.stockMovements) : [];
  (saved.inventory || []).forEach(function (legacy) {
    const product = productById(legacy.productId, next);
    if (!product) return;
    const onHand = integer(legacy.inStock);
    const inTransit = integer(legacy.inTransit);
    next.inventoryBalances.push({
      warehouseId: DEFAULT_WAREHOUSE_ID,
      productId: product.id,
      onHand: onHand,
      reserved: 0,
      updatedAt: legacy.updatedAt || migratedAt
    });
    if (onHand > 0) {
      next.inventoryMovements.push({
        id: uid('move'), warehouseId: DEFAULT_WAREHOUSE_ID, productId: product.id,
        type: 'opening', onHandDelta: onHand, reservedDelta: 0,
        beforeOnHand: 0, beforeReserved: 0, afterOnHand: onHand, afterReserved: 0,
        sourceType: 'migration', sourceId: 'legacy-v4', sourceLineId: product.id,
        occurredAt: migratedAt, postedAt: migratedAt, note: '由旧版已在库余额迁移'
      });
    }
    if (inTransit > 0 && product.kind === 'own') {
      next.purchaseOrders.push({
        id: uid('po'), number: 'MIG-' + (product.sku || product.id.slice(-6)),
        supplier: product.defaultSupplier || '迁移待核对', warehouseId: DEFAULT_WAREHOUSE_ID,
        status: 'transit', orderedAt: migratedAt.slice(0, 10), expectedAt: '',
        extraCost: 0, note: '由旧版在途余额迁移，请人工核对',
        lines: [{ id: uid('pol'), productId: product.id, orderedQty: inTransit, receivedQty: 0, cancelledQty: 0, unitCost: product.standardCost }],
        createdAt: migratedAt, updatedAt: migratedAt, migrated: true
      });
    }
  });
  ownProducts(next, true).forEach(function (product) {
    if (!next.inventoryBalances.some(function (item) { return item.productId === product.id; })) {
      next.inventoryBalances.push({ warehouseId: DEFAULT_WAREHOUSE_ID, productId: product.id, onHand: 0, reserved: 0, updatedAt: '' });
    }
  });
  next.selectedProductId = saved.selectedProductId || (monitoredProducts(next)[0] ? monitoredProducts(next)[0].id : '');
  return normalizeV5(next);
}

function loadState() {
  let raw = null;
  try {
    raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return seedState();
    const saved = JSON.parse(raw);
    if (!saved || !Array.isArray(saved.products)) return seedState();
    const loaded = Number(saved.version) >= 5 ? normalizeV5(saved) : migrateLegacy(saved);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(loaded)); } catch (_) { /* keep usable in memory */ }
    return loaded;
  } catch (_) {
    return seedState();
  }
}

function validateState(next) {
  const warehouseCodes = new Set();
  next.warehouses.forEach(function (warehouse) {
    const code = String(warehouse.code || '').trim().toUpperCase();
    if (!code || !warehouse.name) throw new Error('仓库编码和名称不能为空。');
    if (warehouseCodes.has(code)) throw new Error('仓库编码不能重复：' + code);
    warehouseCodes.add(code);
  });
  const seen = new Set();
  ownProducts(next, true).forEach(function (product) {
    const sku = normalizeSku(product.sku);
    if (!sku) return;
    if (seen.has(sku)) throw new Error('本店 SKU 不能重复：' + product.sku);
    seen.add(sku);
  });
  next.inventoryBalances.forEach(function (balance) {
    if (balance.onHand < 0 || balance.reserved < 0 || balance.reserved > balance.onHand) {
      throw new Error('库存校验失败：锁定库存不能超过已在库。');
    }
    const product = productById(balance.productId, next);
    if (product && product.kind !== 'own' && (balance.onHand || balance.reserved)) {
      throw new Error('竞品不能持有仓库库存。');
    }
  });
  next.purchaseOrders.forEach(function (order) {
    order.lines.forEach(function (line) {
      if (line.receivedQty + line.cancelledQty > line.orderedQty) throw new Error('采购单收货数量超过采购数量。');
      const product = productById(line.productId, next);
      if (!product || product.kind !== 'own') throw new Error('采购单只能选择本店商品。');
    });
  });
  next.salesOrders.forEach(function (order) {
    order.lines.forEach(function (line) {
      if (returnedForLine(line.id, next) > integer(line.shippedQty)) throw new Error('累计退货数量不能超过已出库数量。');
    });
  });
  return true;
}

function commit(mutator, successMessage) {
  if (TEAM_MODE) {
    showToast('团队模式的业务变更必须由服务器确认。');
    return false;
  }
  const next = clone(state);
  try {
    mutator(next);
    next.version = STATE_VERSION;
    next.revision = integer(next.revision) + 1;
    validateState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    state = next;
    render();
    pulseStorage();
    if (successMessage) showToast(successMessage);
    return true;
  } catch (error) {
    showToast(error && error.message ? error.message : '保存失败，请重试。');
    return false;
  }
}

function saveUiQuietly() {
  try {
    if (TEAM_MODE) {
      localStorage.setItem(UI_STORAGE_KEY, JSON.stringify({
        ui: state.ui,
        productFilter: productFilter,
        purchaseFilter: purchaseFilter,
        transferFilter: transferFilter,
        orderFilter: orderFilter,
        inventoryFilter: inventoryFilter,
        inventorySection: inventorySection
      }));
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }
  } catch (_) { /* navigation may continue */ }
}

function restoreUiPreferences() {
  if (!TEAM_MODE) return;
  try {
    const saved = JSON.parse(localStorage.getItem(UI_STORAGE_KEY) || '{}');
    if (saved.ui && saved.ui.module === 'competitors') state.ui.module = 'analytics';
    else if (saved.ui && ['products', 'selection', 'warehouse', 'analytics', 'creators', 'profit'].includes(saved.ui.module)) state.ui.module = saved.ui.module;
    if (saved.ui && ['purchase', 'inventory', 'transfers', 'replenishment', 'orders'].includes(saved.ui.warehouseTab)) state.ui.warehouseTab = saved.ui.warehouseTab;
    if (saved.ui && saved.ui.warehouseId) state.ui.warehouseId = saved.ui.warehouseId;
    if (saved.ui && ['overview', 'stores', 'skus', 'products', 'snapshots', 'trends', 'alerts'].includes(saved.ui.competitorTab)) state.ui.competitorTab = saved.ui.competitorTab;
    if (['all', 'own', 'direct', 'indirect', 'inactive'].includes(saved.productFilter)) productFilter = saved.productFilter;
    if (['open', 'overdue', 'all'].includes(saved.purchaseFilter)) purchaseFilter = saved.purchaseFilter;
    if (['open', 'closed', 'all'].includes(saved.transferFilter)) transferFilter = saved.transferFilter;
    if (['open', 'shortage', 'shipped', 'all'].includes(saved.orderFilter)) orderFilter = saved.orderFilter;
    if (['all', 'low'].includes(saved.inventoryFilter)) inventoryFilter = saved.inventoryFilter;
    if (['list', 'movements'].includes(saved.inventorySection)) inventorySection = saved.inventorySection;
  } catch (_) { /* invalid UI preference is ignored */ }
}

function currentWarehouseId(source) {
  if (TEAM_MODE) return DEFAULT_WAREHOUSE_ID;
  const root = source || state;
  const selected = root.ui && root.ui.warehouseId;
  const warehouse = root.warehouses.find(function (item) { return item.id === selected && item.active; }) ||
    root.warehouses.find(function (item) { return item.active; }) || root.warehouses[0];
  return warehouse ? warehouse.id : DEFAULT_WAREHOUSE_ID;
}
function selectedWarehouse() {
  if (TEAM_MODE && teamGateway) {
    return teamGateway.warehouses.find(function (item) { return String(item.id) === String(teamGateway.warehouseId); }) || null;
  }
  const warehouseId = currentWarehouseId();
  return state.warehouses.find(function (item) { return item.id === warehouseId; }) || null;
}
function warehouseById(warehouseId, source) {
  const root = source || state;
  if (TEAM_MODE && teamGateway) {
    return teamGateway.warehouses.find(function (item) { return String(item.id) === String(warehouseId); }) || null;
  }
  return root.warehouses.find(function (item) { return item.id === warehouseId; }) || null;
}
function isCurrentWarehouseRecord(record) {
  return (record.warehouseId || DEFAULT_WAREHOUSE_ID) === currentWarehouseId();
}
function balanceFor(productId, source, warehouseId) {
  const root = source || state;
  const targetWarehouseId = warehouseId || currentWarehouseId(root);
  return root.inventoryBalances.find(function (item) {
    return item.productId === productId && item.warehouseId === targetWarehouseId;
  }) || { warehouseId: targetWarehouseId, productId: productId, onHand: 0, reserved: 0, purchasedPendingShipment: 0, inTransit: 0, inboundTotal: 0, purchasedPendingSources: [], inTransitSources: [], updatedAt: '' };
}

function inboundFor(productId, source, warehouseId) {
  const balance = balanceFor(productId, source, warehouseId);
  if (TEAM_MODE) return integer(balance.inboundTotal == null
    ? (integer(balance.purchasedPendingShipment) + integer(balance.inTransit))
    : balance.inboundTotal);
  return purchaseTransitFor(productId, source, warehouseId) + (source || state).stockTransfers.reduce(function (sum, transfer) {
    const targetWarehouseId = warehouseId || currentWarehouseId(source || state);
    if (!['in_transit', 'partially_received'].includes(transfer.status) || transfer.destinationWarehouseId !== targetWarehouseId) return sum;
    return sum + transfer.lines.reduce(function (lineSum, line) {
      const remaining = transferLineQuantity(line) - transferReceivedQuantity(line) - integer(line.exceptionClosedQty || line.exception_closed_quantity);
      return line.productId === productId ? lineSum + Math.max(0, remaining) : lineSum;
    }, 0);
  }, 0);
}
function ensureBalance(source, productId, warehouseId) {
  const targetWarehouseId = warehouseId || currentWarehouseId(source);
  let balance = source.inventoryBalances.find(function (item) {
    return item.productId === productId && item.warehouseId === targetWarehouseId;
  });
  if (!balance) {
    balance = { warehouseId: targetWarehouseId, productId: productId, onHand: 0, reserved: 0, updatedAt: '' };
    source.inventoryBalances.push(balance);
  }
  return balance;
}
function availableFor(productId, source, warehouseId) {
  const balance = balanceFor(productId, source, warehouseId);
  return Math.max(0, balance.onHand - balance.reserved);
}
function remainingPurchaseLine(line) {
  return Math.max(0, integer(line.orderedQty) - integer(line.receivedQty) - integer(line.cancelledQty));
}
function isPurchaseOpen(order) {
  return ['ordered', 'transit', 'partial'].includes(order.status) && order.lines.some(function (line) { return remainingPurchaseLine(line) > 0; });
}
function purchaseTransitFor(productId, source, warehouseId) {
  const root = source || state;
  const targetWarehouseId = warehouseId || currentWarehouseId(root);
  return root.purchaseOrders.reduce(function (sum, order) {
    if (!isPurchaseOpen(order) || (order.warehouseId || DEFAULT_WAREHOUSE_ID) !== targetWarehouseId) return sum;
    return sum + order.lines.reduce(function (lineSum, line) {
      return line.productId === productId ? lineSum + remainingPurchaseLine(line) : lineSum;
    }, 0);
  }, 0);
}
function productSnapshots(productId, source) {
  const root = source || state;
  return root.snapshots.filter(function (item) { return item.productId === productId; }).sort(function (a, b) {
    return new Date(a.at) - new Date(b.at);
  });
}
function latestPair(productId) {
  const all = productSnapshots(productId);
  return { all: all, latest: all[all.length - 1], previous: all[all.length - 2] };
}
function ageInDays(value) {
  if (!value) return Infinity;
  return Math.max(0, (Date.now() - new Date(value).getTime()) / 86400000);
}
function searchMatches(product, extra) {
  if (!searchTerm) return true;
  const haystack = [product && product.name, product && product.sku, product && product.seller, product && product.productUrl, extra].join(' ').toLowerCase();
  return haystack.includes(searchTerm);
}
function addMovement(next, details) {
  const warehouseId = details.warehouseId || currentWarehouseId(next);
  const balance = ensureBalance(next, details.productId, warehouseId);
  const beforeOnHand = integer(balance.onHand);
  const beforeReserved = integer(balance.reserved);
  const onHandDelta = asNumber(details.onHandDelta);
  const reservedDelta = asNumber(details.reservedDelta);
  const afterOnHand = beforeOnHand + onHandDelta;
  const afterReserved = beforeReserved + reservedDelta;
  if (afterOnHand < 0 || afterReserved < 0 || afterReserved > afterOnHand) {
    throw new Error('库存不足，无法完成本次操作。');
  }
  balance.onHand = afterOnHand;
  balance.reserved = afterReserved;
  balance.updatedAt = details.occurredAt || new Date().toISOString();
  next.inventoryMovements.push({
    id: uid('move'), warehouseId: warehouseId, productId: details.productId,
    type: details.type, onHandDelta: onHandDelta, reservedDelta: reservedDelta,
    beforeOnHand: beforeOnHand, beforeReserved: beforeReserved,
    afterOnHand: afterOnHand, afterReserved: afterReserved,
    sourceType: details.sourceType || 'adjustment', sourceId: details.sourceId || '',
    sourceLineId: details.sourceLineId || '', sourceNumber: details.sourceNumber || '',
    occurredAt: details.occurredAt || new Date().toISOString(), postedAt: new Date().toISOString(),
    note: details.note || ''
  });
}

function receivePurchaseOrder(next, purchaseId, lineId, quantity, occurredAt, note) {
  const order = next.purchaseOrders.find(function (item) { return item.id === purchaseId; });
  if (!order || !isPurchaseOpen(order)) throw new Error('采购单当前不能收货。');
  const warehouseId = order.warehouseId || currentWarehouseId(next);
  const warehouse = warehouseById(warehouseId, next);
  if (!warehouse || !warehouse.active || warehouse.canReceive === false || warehouse.can_receive === false) throw new Error('当前仓库未开放收货，不能办理采购入库。');
  const line = order.lines.find(function (item) { return item.id === lineId; });
  const qty = integer(quantity);
  if (!line || qty <= 0) throw new Error('请选择有效的收货商品和数量。');
  if (qty > remainingPurchaseLine(line)) throw new Error('本次收货数量超过未收数量。');
  line.receivedQty += qty;
  const receiptId = uid('receipt');
  next.receipts.push({
    id: receiptId, number: 'GRN-' + Date.now(), purchaseOrderId: order.id,
    warehouseId: order.warehouseId || currentWarehouseId(next), receivedAt: occurredAt, note: note || '',
    lines: [{ id: uid('receipt-line'), purchaseOrderLineId: line.id, productId: line.productId, quantity: qty }],
    createdAt: new Date().toISOString()
  });
  addMovement(next, {
    warehouseId: order.warehouseId || currentWarehouseId(next),
    productId: line.productId, type: 'receipt', onHandDelta: qty, reservedDelta: 0,
    sourceType: 'receipt', sourceId: receiptId, sourceLineId: line.id, sourceNumber: order.number,
    occurredAt: occurredAt, note: note || '采购收货'
  });
  const remaining = order.lines.reduce(function (sum, item) { return sum + remainingPurchaseLine(item); }, 0);
  const received = order.lines.reduce(function (sum, item) { return sum + integer(item.receivedQty); }, 0);
  order.status = remaining === 0 ? 'completed' : (received > 0 ? 'partial' : order.status);
  order.updatedAt = new Date().toISOString();
}

function adjustInventory(next, productId, operation, quantity, occurredAt, note) {
  const product = productById(productId, next);
  if (!product || product.kind !== 'own') throw new Error('请选择有效的本店商品。');
  const qty = integer(quantity);
  if (!qty) throw new Error('调整数量必须大于 0。');
  const positive = operation === 'manual_in' || operation === 'manual_inbound' || operation === 'adjust_add';
  if (!positive && qty > availableFor(productId, next)) throw new Error('盘亏或报损不能超过可用库存。');
  addMovement(next, {
    productId: productId, type: operation, onHandDelta: positive ? qty : -qty, reservedDelta: 0,
    sourceType: 'adjustment', sourceId: uid('adjust'), sourceLineId: '',
    sourceNumber: 'ADJ-' + Date.now(), occurredAt: occurredAt, note: note
  });
}

function mergedOrderDemand(lines) {
  const map = new Map();
  lines.forEach(function (line) {
    map.set(line.productId, (map.get(line.productId) || 0) + integer(line.quantity));
  });
  return Array.from(map, function (entry) { return { productId: entry[0], quantity: entry[1] }; });
}

function reserveOrder(next, orderId) {
  const order = next.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || ['shipped', 'cancelled'].includes(order.status)) throw new Error('订单当前不能锁定库存。');
  const warehouse = warehouseById(order.warehouseId || currentWarehouseId(next), next);
  if (!warehouse || !warehouse.active || warehouse.canShip === false || warehouse.can_ship === false) throw new Error('当前仓库未开放出库，不能处理订单。');
  if (order.lines.some(function (line) { return integer(line.reservedQty) > 0; })) throw new Error('该订单已经锁定库存。');
  const demands = mergedOrderDemand(order.lines);
  const warehouseId = order.warehouseId || currentWarehouseId(next);
  const shortage = demands.find(function (demand) { return availableFor(demand.productId, next, warehouseId) < demand.quantity; });
  if (shortage) {
    order.status = 'shortage';
    order.updatedAt = new Date().toISOString();
    return false;
  }
  demands.forEach(function (demand) {
    addMovement(next, {
      warehouseId: warehouseId,
      productId: demand.productId, type: 'reserve', onHandDelta: 0, reservedDelta: demand.quantity,
      sourceType: 'order', sourceId: order.id, sourceLineId: demand.productId,
      sourceNumber: order.number, occurredAt: new Date().toISOString(), note: '订单创建自动锁定'
    });
  });
  order.lines.forEach(function (line) { line.reservedQty = integer(line.quantity); });
  demands.forEach(function (demand) {
    next.reservations.push({
      id: uid('reservation'), orderId: order.id, orderLineId: '',
      warehouseId: warehouseId, productId: demand.productId,
      quantity: demand.quantity, status: 'active', createdAt: new Date().toISOString(), closedAt: ''
    });
  });
  order.status = 'picking';
  order.updatedAt = new Date().toISOString();
  return true;
}

function releaseOrderReservation(next, order, note) {
  const active = next.reservations.filter(function (item) { return item.orderId === order.id && item.status === 'active'; });
  active.forEach(function (reservation) {
    addMovement(next, {
      warehouseId: reservation.warehouseId || order.warehouseId || currentWarehouseId(next),
      productId: reservation.productId, type: 'release', onHandDelta: 0, reservedDelta: -integer(reservation.quantity),
      sourceType: 'order', sourceId: order.id, sourceLineId: reservation.productId,
      sourceNumber: order.number, occurredAt: new Date().toISOString(), note: note || '订单取消释放锁定'
    });
    reservation.status = 'released';
    reservation.closedAt = new Date().toISOString();
  });
  order.lines.forEach(function (line) { line.reservedQty = 0; });
}

function shipOrder(next, orderId) {
  const order = next.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || order.status !== 'ready') throw new Error('订单必须先完成拣货和复核，才能确认出库。');
  const warehouse = warehouseById(order.warehouseId || currentWarehouseId(next), next);
  if (!warehouse || !warehouse.active || warehouse.canShip === false || warehouse.can_ship === false) throw new Error('当前仓库未开放出库，不能确认出库。');
  const active = next.reservations.filter(function (item) { return item.orderId === order.id && item.status === 'active'; });
  const demands = mergedOrderDemand(order.lines);
  if (!active.length || demands.some(function (demand) {
    return active.filter(function (item) { return item.productId === demand.productId; }).reduce(function (sum, item) { return sum + integer(item.quantity); }, 0) < demand.quantity;
  })) throw new Error('订单锁定记录不完整，不能出库。');
  demands.forEach(function (demand) {
    addMovement(next, {
      warehouseId: order.warehouseId || currentWarehouseId(next),
      productId: demand.productId, type: 'outbound', onHandDelta: -demand.quantity, reservedDelta: -demand.quantity,
      sourceType: 'shipment', sourceId: order.id, sourceLineId: demand.productId,
      sourceNumber: order.number, occurredAt: new Date().toISOString(), note: '订单确认出库'
    });
  });
  active.forEach(function (reservation) {
    reservation.status = 'consumed';
    reservation.closedAt = new Date().toISOString();
  });
  order.lines.forEach(function (line) {
    line.shippedQty = integer(line.quantity);
    line.reservedQty = 0;
  });
  next.shipments.push({
    id: uid('shipment'), number: 'OUT-' + Date.now(), orderId: order.id,
    warehouseId: order.warehouseId || currentWarehouseId(next), status: 'shipped',
    trackingNumber: order.trackingNumber || '', shippedAt: new Date().toISOString(),
    note: order.note || '', lines: order.lines.map(function (line) {
      return { id: uid('shipment-line'), orderLineId: line.id, productId: line.productId, quantity: integer(line.quantity) };
    })
  });
  order.status = 'shipped';
  order.shippedAt = new Date().toISOString();
  order.updatedAt = new Date().toISOString();
}

function confirmAndShipOrder(next, orderId) {
  const order = next.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || ['shipped', 'cancelled'].includes(order.status)) throw new Error('订单当前不能出库。');
  const activeReservations = next.reservations.filter(function (item) {
    return item.orderId === order.id && item.status === 'active';
  });
  let reserved = activeReservations.length > 0;
  if (!reserved) reserved = reserveOrder(next, order.id);
  if (!reserved) return false;
  order.status = 'ready';
  shipOrder(next, order.id);
  return true;
}

function cancelOrder(next, orderId) {
  const order = next.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || order.status === 'shipped') throw new Error('已出库订单不能取消，请通过退货流程处理。');
  if (order.status === 'cancelled') throw new Error('订单已经取消。');
  releaseOrderReservation(next, order, '订单取消释放锁定');
  order.status = 'cancelled';
  order.updatedAt = new Date().toISOString();
}

function returnedForLine(orderLineId, source) {
  const root = source || state;
  return root.returns.reduce(function (sum, record) {
    return sum + record.lines.reduce(function (lineSum, line) {
      return line.orderLineId === orderLineId ? lineSum + integer(line.quantity) : lineSum;
    }, 0);
  }, 0);
}

function returnableForLine(line, source) {
  return Math.max(0, integer(line.shippedQty) - returnedForLine(line.id, source));
}

function receiveSalesReturn(next, orderId, orderLineId, quantity, occurredAt, note, condition) {
  const order = next.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || order.status !== 'shipped') throw new Error('只有已出库订单可以办理退货入库。');
  const line = order.lines.find(function (item) { return item.id === orderLineId; });
  const qty = integer(quantity);
  if (!line || qty <= 0) throw new Error('请选择有效的退货商品和数量。');
  if (qty > returnableForLine(line, next)) throw new Error('退货数量不能超过该订单明细的可退数量。');
  if (!String(note || '').trim()) throw new Error('退货入库必须填写原因。');
  const returnId = uid('return');
  const returnNumber = 'RTN-' + Date.now();
  const itemCondition = condition === 'damaged' ? 'damaged' : 'restock';
  next.returns.push({
    id: returnId, number: returnNumber, orderId: order.id, warehouseId: order.warehouseId || currentWarehouseId(next),
    returnedAt: occurredAt, note: note,
    lines: [{ id: uid('return-line'), orderLineId: line.id, productId: line.productId, quantity: qty, condition: itemCondition }],
    createdAt: new Date().toISOString()
  });
  if (itemCondition === 'restock') {
    addMovement(next, {
      warehouseId: order.warehouseId || currentWarehouseId(next),
      productId: line.productId, type: 'return', onHandDelta: qty, reservedDelta: 0,
      sourceType: 'return', sourceId: returnId, sourceLineId: line.id,
      sourceNumber: returnNumber + ' / ' + order.number, occurredAt: occurredAt, note: note
    });
  }
}

function hasBusinessReferences(productId, source) {
  const root = source || state;
  const product = productById(productId, root);
  return Boolean(
    (product && Array.isArray(product.storeProducts) && product.storeProducts.length) ||
    root.inventoryBalances.some(function (balance) { return balance.productId === productId && (balance.onHand || balance.reserved); }) ||
    root.purchaseOrders.some(function (order) { return order.lines.some(function (line) { return line.productId === productId; }); }) ||
    root.salesOrders.some(function (order) { return order.lines.some(function (line) { return line.productId === productId; }); }) ||
    root.returns.some(function (record) { return record.lines.some(function (line) { return line.productId === productId; }); }) ||
    root.inventoryMovements.some(function (movement) { return movement.productId === productId; })
  );
}

function showToast(message) {
  const toast = $('#toast');
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { toast.classList.remove('show'); }, 3200);
}

function teamAuthenticated() {
  return Boolean(TEAM_MODE && teamGateway && teamGateway.user && teamGateway.organizationId);
}

function teamWriteAllowed() {
  return !TEAM_MODE || (teamWriteAuthorized() && !teamBusy);
}

function teamWriteAuthorized() {
  return Boolean(TEAM_MODE && teamAuthenticated() && teamGateway.online !== false && teamGateway.canWrite());
}

function teamCapabilityAllowed(capability) {
  return !TEAM_MODE || Boolean(teamAuthenticated() && teamGateway && teamGateway.can(capability));
}

function teamCapabilityWritable(capability) {
  return !TEAM_MODE || Boolean(teamCapabilityAllowed(capability) && teamGateway.online !== false && !teamBusy);
}

function teamMigrationAllowed() {
  return Boolean(TEAM_MODE && teamCapabilityWritable('migration'));
}

function renderModeControls() {
  const localOnly = ['#importCsv', '#clearAllData', '[data-side-action="import"]'];
  localOnly.forEach(function (selector) {
    $$(selector).forEach(function (node) { node.hidden = TEAM_MODE; });
  });
  const capabilityControls = {
    catalog: ['#openProductModal', '#tableAddProduct', '#emptyAddProduct', '#competitorAddProduct', '#competitorTableAdd', '#competitorAddOwnProduct', '#competitorTableAddOwn', '#confirmAddOwnMonitoring', '#saveProductDraft', '#productForm button[type="submit"]', '#selectionKeywordButton'],
    purchase: ['#openPurchaseModal', '#purchaseForm button[type="submit"]'],
    receipt: ['#receiveForm button[type="submit"]'],
    inventory: ['#openStockModal', '#stockForm button[type="submit"]'],
    order: ['#openOrderModal', '#orderForm button[type="submit"]'],
    return: ['#returnForm button[type="submit"]'],
    competitor: ['#openSnapshotModal', '#snapshotForm button[type="submit"]'],
    warehouse_admin: ['#warehouseForm button[type="submit"]'],
    transfer: ['#openTransferModal', '#transferForm button[type="submit"]'],
    replenishment: ['#replenishmentPolicyForm button[type="submit"]']
  };
  Object.keys(capabilityControls).forEach(function (capability) {
    capabilityControls[capability].forEach(function (selector) {
      $$(selector).forEach(function (node) { node.disabled = TEAM_MODE && !teamCapabilityWritable(capability); });
    });
  });
  if ($('#chooseLocalBackup')) $('#chooseLocalBackup').disabled = TEAM_MODE && !teamMigrationAllowed();
}

function teamRoleLabel(role) {
  return { admin: '管理员', manager: '经理', buyer: '采购', warehouse: '仓库', viewer: '只读成员' }[role] || role || '未知角色';
}

function clearMigrationPreview() {
  pendingMigrationSource = null;
  pendingMigrationPreview = null;
  if ($('#localBackupFile')) $('#localBackupFile').value = '';
  renderMigrationPreview(null);
}

function renderMigrationPreview(preview) {
  const panel = $('#migrationPreview');
  const commitButton = $('#commitLocalMigration');
  if (!panel || !commitButton) return;
  panel.hidden = !preview;
  panel.classList.toggle('invalid', Boolean(preview && !preview.ready));
  if (!preview) {
    setText('#migrationPreviewTitle', '迁移预检');
    setText('#migrationPreviewSummary', '');
    $('#migrationWarnings').innerHTML = '';
    commitButton.disabled = true;
    return;
  }
  const summary = preview.summary || {};
  setText('#migrationPreviewTitle', preview.ready ? '预检通过，可以导入' : '预检未通过');
  setText('#migrationPreviewSummary', [
    '商品 ' + integer(summary.products),
    '本店 SKU ' + integer(summary.own_skus),
    '竞品 ' + integer(summary.competitors),
    '快照 ' + integer(summary.snapshots),
    '期初库存 ' + integer(summary.opening_balance_rows) + ' 行'
  ].join(' · '));
  const messages = []
    .concat((preview.errors || []).map(function (message) { return { kind: 'error', text: message }; }))
    .concat((preview.warnings || []).map(function (message) { return { kind: 'warning', text: message }; }));
  $('#migrationWarnings').innerHTML = messages.length
    ? messages.map(function (item) { return '<li class="' + item.kind + '">' + escapeHtml(item.text) + '</li>'; }).join('')
    : '<li>未发现阻止迁移的问题。</li>';
  commitButton.disabled = !preview.ready || !teamMigrationAllowed();
}

function renderRuntimeState() {
  const button = $('#runtimeStateButton');
  const banner = $('#connectionBanner');
  if (!button || !banner) return;
  renderModeControls();
  button.classList.remove('loading', 'offline');
  banner.classList.remove('danger');
  $('#localSessionPanel').hidden = TEAM_MODE;
  $('#teamLoginForm').hidden = !TEAM_MODE || teamAuthenticated() || Boolean(ownerLoginChallengeId);
  $('#ownerVerificationForm').hidden = !ownerLoginChallengeId || teamAuthenticated();
  $('#teamSessionPanel').hidden = !TEAM_MODE || !teamAuthenticated();
  renderMigrationPreview(pendingMigrationPreview);
  if (!TEAM_MODE) {
    setText('#runtimeStateText', '本机已保存');
    setText('#sidebarRuntimeTitle', '数据保存在本机');
    setText('#sidebarRuntimeDetail', '库存与竞品记录自动保存');
    banner.hidden = true;
    document.body.classList.remove('team-readonly');
    return;
  }
  if (teamBusy) button.classList.add('loading');
  if (!teamAuthenticated()) {
    setText('#runtimeStateText', teamBusy ? '正在连接' : '内部系统 · 待登录');
    setText('#sidebarRuntimeTitle', '内部系统未登录');
    setText('#sidebarRuntimeDetail', '请使用主账号或已启用的子账号登录');
    setText('#connectionBannerTitle', '内部系统尚未登录');
    setText('#connectionBannerDetail', ownerLoginChallengeId ? '请输入发送到主账号邮箱的验证码。' : '子账号由主账号创建后可直接登录，无需创建组织。');
    $('#retryConnection').hidden = true;
    banner.hidden = false;
    document.body.classList.add('team-readonly');
    return;
  }
  const online = teamGateway.online !== false;
  button.classList.toggle('offline', !online);
  const membership = teamGateway.memberships[0] || null;
  const warehouse = teamGateway.warehouses.find(function (item) { return String(item.id) === teamGateway.warehouseId; });
  setText('#runtimeStateText', teamBusy ? '正在同步' : (online ? '团队已同步' : '离线只读'));
  setText('#sidebarRuntimeTitle', membership ? membership.organization.name : '内部系统');
  setText('#sidebarRuntimeDetail', (warehouse ? warehouse.name : '未选仓库') + ' · ' + (teamGateway.user.is_owner ? '主账号' : '内部成员'));
  setText('#teamIdentity', (teamGateway.user.username || teamGateway.user.email || '内部账号'));
  setText('#teamRoleText', (membership ? membership.organization.name : '内部系统') + ' · ' + (teamGateway.user.is_owner ? '主账号（完整权限）' : '内部成员'));
  setText('#teamSyncDetail', teamLastSyncedAt ? '最近同步：' + formatDate(teamLastSyncedAt, true) : '等待首次同步');
  $('#teamWarehouse').innerHTML = teamGateway.warehouses.filter(function (item) { return item.active; }).map(function (item) {
    return '<option value="' + escapeHtml(String(item.id)) + '">' + escapeHtml(item.code + ' · ' + item.name) + '</option>';
  }).join('');
  $('#teamWarehouse').value = teamGateway.warehouseId;
  $('#ownerAccountActions').hidden = !teamGateway.user.is_owner;
  if ($('#openSelectionConfig')) $('#openSelectionConfig').hidden = !teamGateway.user.is_owner;
  if (!online) {
    setText('#connectionBannerTitle', '团队服务器连接中断');
    setText('#connectionBannerDetail', '已保留上次同步的数据用于查看；所有写入已暂停，不会转存到本机。');
    $('#retryConnection').hidden = false;
    banner.classList.add('danger');
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
  document.body.classList.toggle('team-readonly', !online || !teamGateway.canWrite());
  renderModeControls();
  renderMigrationPreview(pendingMigrationPreview);
}

function handleTeamError(error) {
  const message = error && error.message ? error.message : '团队操作失败，请重试。';
  if (error && error.status === 401 && teamGateway) teamGateway.clearSession();
  showToast(message);
  renderRuntimeState();
  return false;
}

function resetInternalAccountForm() {
  $('#internalAccountId').value = '';
  $('#internalAccountUsername').value = '';
  $('#internalAccountDisplayName').value = '';
  $('#internalAccountPassword').value = '';
  $('#internalAccountPassword').required = true;
  $('#internalAccountPasswordRequired').hidden = false;
  $('#saveInternalAccount').textContent = '新增子账号';
  $('#internalAccountRole').value = 'viewer';
  $$('#internalAccountWarehouses input').forEach(function (input) { input.checked = false; });
  applyInternalAccountRoleDefaults();
}

function defaultPermissionsForRole(role) {
  const catalog = {
    admin: Object.keys(ownerPermissionCatalog),
    manager: Object.keys(ownerPermissionCatalog),
    buyer: ['catalog', 'purchase', 'replenishment'],
    warehouse: ['warehouse', 'order'],
    viewer: ['view']
  };
  return catalog[role] || ['view'];
}

function applyInternalAccountRoleDefaults() {
  const selected = new Set(defaultPermissionsForRole($('#internalAccountRole').value));
  $$('#internalAccountPermissions input').forEach(function (input) { input.checked = selected.has(input.value); });
}

function renderInternalAccountManager() {
  const permissions = Object.keys(ownerPermissionCatalog);
  const roleSelect = $('#internalAccountRole');
  const previousRole = roleSelect.value || 'viewer';
  const roleCatalog = Object.keys(ownerRoleCatalog).length ? ownerRoleCatalog : INTERNAL_ROLE_CATALOG;
  roleSelect.innerHTML = Object.keys(roleCatalog).map(function (key) {
    return '<option value="' + escapeHtml(key) + '">' + escapeHtml(roleCatalog[key]) + '</option>';
  }).join('');
  roleSelect.value = roleCatalog[previousRole] ? previousRole : 'viewer';
  $('#internalAccountWarehouses').innerHTML = ownerWarehouseCatalog.length ? ownerWarehouseCatalog.map(function (warehouse) {
    const label = warehouse.name + (warehouse.code ? ' · ' + warehouse.code : '') + (warehouse.active ? '' : '（已停用）');
    return '<label><input type="checkbox" value="' + escapeHtml(warehouse.id) + '"' + (warehouse.active ? '' : ' disabled') + ' />' + escapeHtml(label) + '</label>';
  }).join('') : '<span class="session-help">请先创建仓库，再为成员授权仓库。</span>';
  $('#internalAccountPermissions').innerHTML = permissions.map(function (key) {
    return '<label><input type="checkbox" value="' + escapeHtml(key) + '" />' + escapeHtml(ownerPermissionCatalog[key]) + '</label>';
  }).join('');
  $('#internalAccountRows').innerHTML = internalAccounts.length ? internalAccounts.map(function (account) {
    const status = account.active ? '已启用' : '已停用';
    const access = (account.permissions || []).map(function (key) { return ownerPermissionCatalog[key] || key; }).join('、') || '仅查看';
    const warehouseNames = (account.warehouses || []).map(function (warehouse) { return warehouse.name; }).join('、') || (account.role === 'admin' ? '全部仓库' : '未授权仓库');
    return '<div class="account-row"><div><strong>' + escapeHtml(account.display_name || account.username) + '</strong><small>' + escapeHtml('账号：' + account.username + ' · ' + (roleCatalog[account.role] || account.role) + ' · ' + status + ' · 仓库：' + warehouseNames + ' · ' + access) + '</small></div><div class="inline-actions">' +
      '<button class="button tiny secondary" type="button" data-account-action="edit" data-account-id="' + escapeHtml(account.id) + '">编辑</button>' +
      '<button class="button tiny ' + (account.active ? 'danger-outline' : 'secondary') + '" type="button" data-account-action="toggle" data-account-id="' + escapeHtml(account.id) + '">' + (account.active ? '停用' : '启用') + '</button></div></div>';
  }).join('') : '<p class="session-help">还没有子账号。新增后成员可直接登录，无需创建组织。</p>';
}

async function openInternalAccountManager() {
  if (!teamGateway || !teamGateway.user || !teamGateway.user.is_owner) return;
  const payload = await teamGateway.listInternalAccounts();
  ownerPermissionCatalog = payload.permission_catalog || {};
  ownerRoleCatalog = Object.assign({}, INTERNAL_ROLE_CATALOG, payload.roles || {});
  ownerWarehouseCatalog = payload.warehouses || [];
  internalAccounts = (payload.accounts || []).filter(function (account) { return !account.is_owner; });
  $('#accountManagerPanel').hidden = false;
  $('#ownerPasswordPanel').hidden = true;
  $('#integrationsPanel').hidden = true;
  renderInternalAccountManager();
  resetInternalAccountForm();
}

function renderIntegrationManager() {
  const alpha = alphashopConfig || {};
  const sourceText = alpha.source === 'system' ? '已由系统加密保存（尚未验证连接）' : (alpha.source === 'environment' ? '正在使用旧版服务器配置；保存本表单后会切换为系统配置' : '尚未配置');
  $('#alphashopConfigHint').textContent = sourceText + '。密钥不会回显；如需更新密钥，填写对应字段后保存即可。点击“测试连接”会真实调用一次选品接口，可能消耗接口额度。';
  $('#alphashopApiBaseUrl').value = alpha.api_base_url || 'https://api.alphashop.cn';
  $('#alphashopEnabled').checked = alpha.enabled !== false;
  const selectedAnalysisProvider = alpha.analysis_provider || '';
  const analysisProviders = aiProviderConfigs.filter(function (provider) { return provider.enabled && provider.has_api_key; });
  $('#alphashopAnalysisProvider').innerHTML = '<option value="">不调用大模型，仅展示选品接口数据</option>' + analysisProviders.map(function (provider) {
    return '<option value="' + escapeHtml(provider.id) + '">' + escapeHtml(provider.name + ' · ' + provider.model_name) + '</option>';
  }).join('');
  $('#alphashopAnalysisProvider').value = analysisProviders.some(function (provider) { return String(provider.id) === String(selectedAnalysisProvider); }) ? selectedAnalysisProvider : '';
  $('#alphashopAnalysisEnabled').checked = Boolean(alpha.analysis_enabled && $('#alphashopAnalysisProvider').value);
  $('#alphashopAccessKey').value = '';
  $('#alphashopSecretKey').value = '';
  $('#alphashopAccessKey').required = !alpha.has_access_key;
  $('#alphashopSecretKey').required = !alpha.has_secret_key;
  $('#tiktokConnectionRows').innerHTML = tiktokConnections.length ? tiktokConnections.map(function (connection) {
    const status = connection.status === 'connected' ? '已授权' : (connection.status === 'disconnected' ? '已解绑' : connection.status);
    return '<div class="account-row"><div><strong>' + escapeHtml(connection.shop_name || connection.open_id) + '</strong><small>' + escapeHtml(connection.region + ' · ' + status + ' · 到期 ' + (connection.access_token_expires_at || '未返回')) + '</small></div><div class="inline-actions">' +
      (connection.status === 'connected' ? '<button class="button tiny secondary" type="button" data-tiktok-action="refresh" data-tiktok-id="' + escapeHtml(connection.id) + '">刷新令牌</button><button class="button tiny danger-outline" type="button" data-tiktok-action="disconnect" data-tiktok-id="' + escapeHtml(connection.id) + '">解绑</button>' : '') + '</div></div>';
  }).join('') : '<p class="session-help">尚未授权 TikTok Shop 店铺。</p>';
  $('#aiProviderRows').innerHTML = aiProviderConfigs.length ? aiProviderConfigs.map(function (provider) {
    return '<div class="account-row"><div><strong>' + escapeHtml(provider.name) + '</strong><small>' + escapeHtml(provider.model_name + ' · ' + (provider.enabled ? '已启用' : '已停用') + ' · 密钥' + (provider.has_api_key ? '已加密保存' : '未配置')) + '</small></div><div class="inline-actions"><button class="button tiny secondary" type="button" data-ai-edit-id="' + escapeHtml(provider.id) + '">编辑</button><button class="button tiny secondary" type="button" data-ai-test-id="' + escapeHtml(provider.id) + '">测试连接</button></div></div>';
  }).join('') : '<p class="session-help">尚未配置外部大模型 API。</p>';
  const successful = aiInvocationLogs.filter(function (item) { return item.status === 'success'; });
  const inputTokens = successful.reduce(function (sum, item) { return sum + Number(item.input_tokens || 0); }, 0);
  const outputTokens = successful.reduce(function (sum, item) { return sum + Number(item.output_tokens || 0); }, 0);
  $('#aiUsageSummary').textContent = aiInvocationLogs.length
    ? '调用记录 ' + aiInvocationLogs.length + ' 条，其中成功 ' + successful.length + ' 条；输入 Tokens ' + inputTokens + '，输出 Tokens ' + outputTokens + '。'
    : '尚无大模型调用记录。保存并测试后会在这里汇总用量。';
  const selectedProvider = $('#aiRecommendationProvider').value;
  const enabledProviders = aiProviderConfigs.filter(function (provider) { return provider.enabled && provider.has_api_key; });
  $('#aiRecommendationProvider').innerHTML = enabledProviders.length
    ? enabledProviders.map(function (provider) { return '<option value="' + escapeHtml(provider.id) + '">' + escapeHtml(provider.name + ' · ' + provider.model_name) + '</option>'; }).join('')
    : '<option value="">请先保存并测试一个已启用的大模型</option>';
  if (enabledProviders.some(function (provider) { return String(provider.id) === String(selectedProvider); })) {
    $('#aiRecommendationProvider').value = selectedProvider;
  }
  $('#aiRecommendationRows').innerHTML = aiRecommendations.length ? aiRecommendations.map(function (item) {
    const provider = aiProviderConfigs.find(function (candidate) { return String(candidate.id) === String(item.provider); });
    const labels = { inventory_forecast: '库存预测', replenishment: '补货建议', product_analysis: '商品分析', copywriting: '文案生成' };
    const statuses = { proposed: '待确认', confirmed: '已确认', rejected: '已拒绝' };
    const action = item.status === 'proposed'
      ? '<div class="inline-actions"><button class="button tiny primary" type="button" data-ai-recommendation-action="confirm" data-ai-recommendation-id="' + escapeHtml(item.id) + '">确认方案</button><button class="button tiny danger-outline" type="button" data-ai-recommendation-action="reject" data-ai-recommendation-id="' + escapeHtml(item.id) + '">拒绝</button></div>'
      : '';
    const proposal = escapeHtml(JSON.stringify(item.proposal || {}, null, 2));
    return '<div class="account-row ai-recommendation-row"><div><strong>' + escapeHtml(labels[item.kind] || item.kind) + ' · ' + escapeHtml(statuses[item.status] || item.status) + '</strong><small>' + escapeHtml((provider && provider.name) || '已删除模型') + ' · ' + formatDate(item.created_at, true) + '</small><details><summary>查看建议内容</summary><pre class="ai-proposal">' + proposal + '</pre></details></div>' + action + '</div>';
  }).join('') : '<p class="session-help">尚无 AI 建议。提交输入数据后，系统只会生成待确认方案。</p>';
  $('#aiInvocationRows').innerHTML = aiInvocationLogs.length ? aiInvocationLogs.slice(0, 20).map(function (item) {
    const provider = aiProviderConfigs.find(function (candidate) { return String(candidate.id) === String(item.provider); });
    const tokens = item.status === 'success'
      ? '输入 ' + Number(item.input_tokens || 0) + ' / 输出 ' + Number(item.output_tokens || 0) + ' Tokens'
      : (item.error_code || '调用失败');
    const detail = item.status === 'success' ? tokens : (tokens + (item.error_message ? ' · ' + item.error_message : ''));
    return '<div class="account-row"><div><strong>' + escapeHtml(item.feature || 'AI 调用') + ' · ' + escapeHtml(item.status === 'success' ? '成功' : '失败') + '</strong><small class="ai-log-meta">' + escapeHtml((provider && provider.name) || item.model_name || '已删除模型') + ' · ' + escapeHtml(formatDate(item.created_at, true)) + ' · 尝试 ' + Number(item.attempts || 0) + ' 次 · ' + Number(item.latency_ms || 0) + ' ms · ' + escapeHtml(detail) + '</small></div></div>';
  }).join('') : '<p class="session-help">尚无调用日志。</p>';
}

function resetAIProviderForm() {
  $('#aiProviderForm').reset();
  $('#aiProviderId').value = '';
  $('#aiProviderParameters').value = '{}';
  $('#aiProviderEnabled').checked = true;
  $('#aiProviderKey').required = true;
  $('#aiProviderKeyRequired').hidden = false;
  $('#saveAIProvider').textContent = '加密保存并测试';
}

function editAIProviderConfig(id) {
  const provider = aiProviderConfigs.find(function (item) { return String(item.id) === String(id); });
  if (!provider) return;
  $('#aiProviderId').value = provider.id;
  $('#aiProviderName').value = provider.name || '';
  $('#aiProviderBaseUrl').value = provider.api_base_url || '';
  $('#aiProviderModel').value = provider.model_name || '';
  $('#aiProviderKey').value = '';
  $('#aiProviderKey').required = false;
  $('#aiProviderKeyRequired').hidden = true;
  $('#aiProviderTimeout').value = provider.timeout_seconds || 30;
  $('#aiProviderRetries').value = provider.max_retries == null ? 2 : provider.max_retries;
  $('#aiProviderEnabled').checked = provider.enabled !== false;
  $('#aiProviderParameters').value = JSON.stringify(provider.default_parameters || {}, null, 2);
  $('#saveAIProvider').textContent = '保存修改并测试';
  $('#aiProviderForm').scrollIntoView({ block: 'center', behavior: 'smooth' });
}

async function openIntegrationManager() {
  if (!teamGateway || !teamGateway.user || !teamGateway.user.is_owner) return;
  const results = await Promise.all([teamGateway.listTikTokConnections(), teamGateway.listAIProviders(), teamGateway.getAlphaShopConfig(), teamGateway.listAIInvocations(), teamGateway.listAIRecommendations()]);
  tiktokConnections = results[0] || [];
  aiProviderConfigs = results[1] || [];
  alphashopConfig = results[2] || null;
  aiInvocationLogs = results[3] || [];
  aiRecommendations = results[4] || [];
  $('#accountManagerPanel').hidden = true;
  $('#ownerPasswordPanel').hidden = true;
  $('#integrationsPanel').hidden = false;
  resetAIProviderForm();
  renderIntegrationManager();
}

async function openAlphaShopConfiguration() {
  if (!teamGateway || !teamGateway.user || !teamGateway.user.is_owner) {
    return showToast('只有主账号可以配置选品接口。');
  }
  openModal('sessionModal');
  await openIntegrationManager();
  $('#alphashopConfigForm').scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function editInternalAccount(id) {
  const account = internalAccounts.find(function (item) { return item.id === id; });
  if (!account) return;
  $('#internalAccountId').value = account.id;
  $('#internalAccountUsername').value = account.username;
  $('#internalAccountDisplayName').value = account.display_name || account.username;
  $('#internalAccountPassword').value = '';
  $('#internalAccountPassword').required = false;
  $('#internalAccountPasswordRequired').hidden = true;
  $('#saveInternalAccount').textContent = '保存账号设置';
  $('#internalAccountRole').value = account.role || 'viewer';
  const warehouseIds = new Set(account.warehouse_ids || []);
  $$('#internalAccountWarehouses input').forEach(function (input) { input.checked = warehouseIds.has(input.value); });
  $$('#internalAccountPermissions input').forEach(function (input) { input.checked = (account.permissions || []).includes(input.value); });
}

async function refreshTeamState(successMessage) {
  if (!teamAuthenticated() || teamBusy) return false;
  const currentUi = clone(state.ui);
  teamBusy = true;
  renderRuntimeState();
  try {
    const loaded = await teamGateway.loadState();
    state = normalizeV5(loaded);
    state.ui = currentUi;
    teamLastSyncedAt = new Date().toISOString();
    render();
    renderRuntimeState();
    if (successMessage) showToast(successMessage);
    return true;
  } catch (error) {
    return handleTeamError(error);
  } finally {
    teamBusy = false;
    renderRuntimeState();
  }
}

async function executeTeamCommand(command, successMessage, capability, options) {
  const settings = Object.assign({ applyResult: null, refreshOnError: true }, options || {});
  if (!TEAM_MODE) return false;
  if (!teamAuthenticated()) {
    openModal('sessionModal');
    showToast('请先登录团队账号。');
    return false;
  }
  if (capability && !teamGateway.can(capability)) return showToast('当前角色没有执行该操作的权限。');
  if (!teamGateway.canWrite()) return showToast('当前账号为只读权限，不能执行该操作。');
  if (teamGateway.online === false) return showToast('当前离线只读，恢复连接后再提交。');
  if (teamBusy) return showToast('上一项团队操作仍在处理中。');
  teamBusy = true;
  renderRuntimeState();
  try {
    const result = await command();
    try {
      // Some write endpoints already return the complete updated resource.  In
      // that case consume the response directly instead of synchronously
      // loading every dashboard collection (including competitor monitoring
      // and replenishment).  Those unrelated APIs must never delay or overturn
      // a successful purchase tracking save.
      const loaded = settings.applyResult
        ? settings.applyResult(result)
        : await teamGateway.loadState();
      const currentUi = clone(state.ui);
      state = normalizeV5(loaded);
      state.ui = currentUi;
      teamLastSyncedAt = new Date().toISOString();
      render();
      renderRuntimeState();
      if (successMessage) showToast(successMessage);
    } catch (refreshError) {
      // A completed write must never be presented as a failed save merely
      // because one of the dashboard refresh endpoints is temporarily down.
      // In particular, this used to make a successful purchase edit look like
      // an HTTP 500 and invited the operator to submit it again.
      console.error('Team state refresh failed after a successful command.', refreshError);
      showToast('保存成功，但页面数据刷新失败。请刷新页面后确认最新采购单。');
    }
    return true;
  } catch (error) {
    if (settings.refreshOnError) {
      try {
        const loaded = await teamGateway.loadState();
        const currentUi = clone(state.ui);
        state = normalizeV5(loaded);
        state.ui = currentUi;
        teamLastSyncedAt = new Date().toISOString();
        render();
      } catch (_) { /* keep the last synchronized view when refresh also fails */ }
    }
    return handleTeamError(error);
  } finally {
    teamBusy = false;
    renderRuntimeState();
  }
}

async function initializeTeamMode() {
  restoreUiPreferences();
  renderRuntimeState();
  if (!TEAM_MODE || !teamGateway) return;
  if (!teamGateway.refreshToken) {
    openModal('sessionModal');
    return;
  }
  teamBusy = true;
  renderRuntimeState();
  try {
    const loaded = await teamGateway.restore();
    if (loaded) {
      const currentUi = clone(state.ui);
      state = normalizeV5(loaded);
      state.ui = currentUi;
      teamLastSyncedAt = new Date().toISOString();
      render();
    }
  } catch (error) {
    handleTeamError(error);
    // Do not turn a temporary network/server outage into a logout prompt.
    // The gateway only clears persisted credentials after a confirmed 401.
    if (error && error.status === 401) openModal('sessionModal');
  } finally {
    teamBusy = false;
    renderRuntimeState();
  }
}

async function pollTeamUpdates() {
  if (!TEAM_MODE || !teamGateway || !teamAuthenticated() || teamBusy || document.hidden) return;
  try {
    const loaded = await teamGateway.pollForUpdates();
    if (!loaded) return;
    const currentUi = clone(state.ui);
    state = normalizeV5(loaded);
    state.ui = currentUi;
    teamLastSyncedAt = new Date().toISOString();
    render();
    renderRuntimeState();
    showToast('已同步其他成员的最新修改。');
  } catch (error) {
    if (error && error.status !== 401) return;
    handleTeamError(error);
  }
}

function startRealtimeSync() {
  if (!TEAM_MODE || teamRealtimeTimer) return;
  teamRealtimeTimer = setInterval(pollTeamUpdates, 3000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) pollTeamUpdates();
  });
}

function pulseStorage() {
  if (TEAM_MODE) {
    teamLastSyncedAt = new Date().toISOString();
    renderRuntimeState();
    return;
  }
  setText('#runtimeStateText', '刚刚已保存');
  setTimeout(function () { setText('#runtimeStateText', '已自动保存'); }, 1400);
}
function openModal(id) {
  const modal = $('#' + id);
  if (!modal) return;
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  const focusable = modal.querySelector('input:not([type="hidden"]), select, button');
  if (focusable) setTimeout(function () { focusable.focus(); }, 40);
}
function closeModal(id) {
  const modal = $('#' + id);
  if (!modal) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  if (!$$('.modal-backdrop.open').length) document.body.classList.remove('modal-open');
}
function askConfirm(text, callback) {
  pendingConfirm = callback;
  $('#confirmText').textContent = text;
  $('#confirmBar').classList.add('show');
  $('#confirmBar').setAttribute('aria-hidden', 'false');
}
function closeConfirm() {
  pendingConfirm = null;
  $('#confirmBar').classList.remove('show');
  $('#confirmBar').setAttribute('aria-hidden', 'true');
}
function transitSourceLabel(source) {
  if (source.source_type === 'transfer') return '仓间调拨';
  return source.source_stage === 'pending_shipment' ? '采购在途（待发货）' : '采购在途（已发货）';
}
function openTransitSources(productId) {
  const product = productById(productId);
  const balance = balanceFor(productId);
  const sources = (balance.purchasedPendingSources || []).concat(balance.inTransitSources || []);
  const total = sources.reduce(function (sum, source) { return sum + asNumber(source.remaining_quantity); }, 0);
  setText('#transitSourceModalTitle', (product ? product.sku + ' · ' + product.name : 'SKU') + ' 在途来源');
  setText('#transitSourceIntro', '来源剩余合计 ' + total + ' 件；库存列表显示 ' + inboundFor(productId) + ' 件。');
  $('#transitSourceList').innerHTML = sources.length ? sources.map(function (source) {
    return '<article class="transit-source-card"><header><strong>' + escapeHtml(transitSourceLabel(source) + ' · ' + (source.source_number || '未编号')) + '</strong><span>剩余 ' + asNumber(source.remaining_quantity) + '</span></header><dl>' +
      '<div><dt>物流单号</dt><dd>' + escapeHtml(source.tracking_number || '未填写') + '</dd></div>' +
      '<div><dt>原计划</dt><dd>' + asNumber(source.planned_quantity) + '</dd></div>' +
      '<div><dt>已收</dt><dd>' + asNumber(source.received_quantity) + '</dd></div>' +
      '<div><dt>异常关闭</dt><dd>' + asNumber(source.exception_closed_quantity) + '</dd></div>' +
      '<div><dt>发出/确认时间</dt><dd>' + formatDate(source.started_at, true) + '</dd></div>' +
      '<div><dt>预计到货</dt><dd>' + formatDate(source.expected_at, false) + '</dd></div>' +
      '</dl></article>';
  }).join('') : '<div class="last-value">当前没有可展开的在途来源；如合计不为 0，请使用服务器诊断检查历史阶段余额。</div>';
  openModal('transitSourceModal');
}
function stickyHeaderGeometry(appBottom, sourceRect, tableRect, wrapRect, wrapClientWidth, wrapScrollLeft, tableScrollWidth) {
  const top = Math.max(0, asNumber(appBottom));
  const height = Math.max(0, asNumber(sourceRect && sourceRect.height));
  return {
    visible: Boolean(sourceRect && tableRect && sourceRect.top < top && tableRect.bottom > top + height),
    top: top,
    left: asNumber(wrapRect && wrapRect.left),
    width: Math.max(0, asNumber(wrapClientWidth)),
    height: height,
    tableWidth: Math.max(0, asNumber(tableScrollWidth)),
    translateX: -Math.max(0, asNumber(wrapScrollLeft))
  };
}

function updateClonedStickyHeader(table, wrap, current, className) {
  if (!table || !wrap || !table.tHead || table.closest('[hidden]')) {
    if (current) current.hidden = true;
    return current;
  }
  const appHeader = $('.app-header');
  if (!appHeader) return current;
  const sourceRect = table.tHead.getBoundingClientRect();
  const geometry = stickyHeaderGeometry(appHeader.getBoundingClientRect().bottom, sourceRect, table.getBoundingClientRect(), wrap.getBoundingClientRect(), wrap.clientWidth, wrap.scrollLeft, table.scrollWidth);
  if (!geometry.visible) {
    if (current) current.hidden = true;
    return current;
  }
  if (!current) {
    current = document.createElement('div');
    current.className = className;
    current.setAttribute('aria-hidden', 'true');
    document.body.appendChild(current);
  }
  current.innerHTML = '<table><thead>' + table.tHead.innerHTML + '</thead></table>';
  const cloneTable = current.querySelector('table');
  const cloneHeaders = current.querySelectorAll('th');
  Array.from(table.tHead.querySelectorAll('th')).forEach(function (th, index) {
    if (!cloneHeaders[index]) return;
    const width = th.getBoundingClientRect().width + 'px';
    cloneHeaders[index].style.width = width;
    cloneHeaders[index].style.minWidth = width;
    cloneHeaders[index].style.maxWidth = width;
  });
  current.hidden = false;
  current.style.top = geometry.top + 'px';
  current.style.left = geometry.left + 'px';
  current.style.width = geometry.width + 'px';
  current.style.height = geometry.height + 'px';
  cloneTable.style.width = geometry.tableWidth + 'px';
  cloneTable.style.transform = 'translateX(' + geometry.translateX + 'px)';
  return current;
}

function updateInventoryStickyHeader() {
  inventoryStickyHeader = updateClonedStickyHeader($('#inventoryTable'), $('#inventoryTableWrap'), inventoryStickyHeader, 'inventory-sticky-header');
}

function updateReplenishmentStickyHeader() {
  const active = state.ui.module === 'warehouse' && state.ui.warehouseTab === 'replenishment';
  if (!active) {
    if (replenishmentStickyHeader) replenishmentStickyHeader.hidden = true;
    return;
  }
  replenishmentStickyHeader = updateClonedStickyHeader($('#replenishmentTable'), $('#replenishmentTableWrap'), replenishmentStickyHeader, 'inventory-sticky-header replenishment-sticky-header');
}
function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}
function toggleEmpty(selector, empty) {
  const node = $(selector);
  if (node) node.classList.toggle('show', Boolean(empty));
}
function productMedia(product) {
  const image = safeImageUrl(product.image);
  const initials = (product.name || '商品').slice(0, 2);
  return '<div class="product-cell"><div class="product-media"><span class="product-badge">' + escapeHtml(initials) + '</span>' +
    (image ? '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(product.name) + '" loading="lazy" onerror="this.hidden=true">' : '') +
    '</div><div class="product-copy"><strong title="' + escapeHtml(product.name) + '">' + escapeHtml(product.name || '未命名商品') +
    '</strong><span title="' + escapeHtml(product.productUrl) + '">' + escapeHtml(product.kind === 'own' ? (product.sku || 'SKU 待填写') : (product.seller || product.market || '—')) + '</span></div></div>';
}
function statusPill(label, className) {
  return '<span class="status-pill ' + escapeHtml(className) + '">' + escapeHtml(label) + '</span>';
}
function rowButton(action, id, label, className) {
  const readOnlyActions = ['edit-product', 'open-warehouse', 'view-movements'];
  const writeAction = !readOnlyActions.includes(action);
  const disabled = writeAction && TEAM_MODE && !teamWriteAuthorized();
  return '<button class="row-action ' + (className || '') + '" data-action="' + action + '" data-id="' + escapeHtml(id) + '"' +
    (writeAction ? ' data-team-write' : '') + (disabled ? ' disabled' : '') + '>' + escapeHtml(label) + '</button>';
}

function setRoute(module, subtab) {
  if (module === 'competitors') module = 'analytics';
  state.ui.module = module;
  if (module === 'warehouse' && subtab) state.ui.warehouseTab = subtab;
  if (module === 'analytics' && subtab) state.ui.competitorTab = subtab;
  if (module === 'profit') profitView = ['calculator', 'plans', 'rules'].includes(subtab) ? subtab : 'calculator';
  let route = '#' + module;
  if (module === 'products' && productFilter !== 'all') route += '/' + productFilter;
  if (module === 'warehouse') {
    route += '/' + state.ui.warehouseTab;
    if (state.ui.warehouseTab === 'purchase' && purchaseFilter !== 'open') route += '/' + purchaseFilter;
    if (state.ui.warehouseTab === 'transfers' && transferFilter !== 'open') route += '/' + transferFilter;
    if (state.ui.warehouseTab === 'orders' && orderFilter !== 'open') route += '/' + orderFilter;
    if (state.ui.warehouseTab === 'inventory') {
      if (inventoryFilter === 'low') route += '/low';
      else if (inventorySection === 'movements') route += '/movements';
    }
  }
  if (module === 'analytics') route += '/' + state.ui.competitorTab;
  if (module === 'profit' && profitView !== 'calculator') route += '/' + profitView;
  history.replaceState(null, '', route);
  saveUiQuietly();
  closeSidebar();
  render();
}
function applyHashRoute() {
  const parts = location.hash.replace(/^#/, '').split('/');
  if (parts[0] === 'competitors') {
    state.ui.module = 'analytics';
    if (typeof history !== 'undefined' && history.replaceState) history.replaceState(null, '', '#analytics/' + (parts[1] || 'products'));
  } else if (['products', 'selection', 'warehouse', 'analytics', 'creators', 'profit'].includes(parts[0])) state.ui.module = parts[0];
  if (parts[0] === 'products') productFilter = ['own', 'direct', 'indirect', 'inactive'].includes(parts[1]) ? parts[1] : 'all';
  if (parts[0] === 'warehouse' && ['purchase', 'inventory', 'transfers', 'replenishment', 'orders'].includes(parts[1])) {
    state.ui.warehouseTab = parts[1];
    if (parts[1] === 'purchase') purchaseFilter = ['overdue', 'all'].includes(parts[2]) ? parts[2] : 'open';
    if (parts[1] === 'transfers') transferFilter = ['closed', 'all'].includes(parts[2]) ? parts[2] : 'open';
    if (parts[1] === 'orders') orderFilter = ['shortage', 'shipped', 'all'].includes(parts[2]) ? parts[2] : 'open';
    if (parts[1] === 'inventory') {
      inventoryFilter = parts[2] === 'low' ? 'low' : 'all';
      inventorySection = parts[2] === 'movements' ? 'movements' : 'list';
    }
  }
  if (['competitors', 'analytics'].includes(parts[0]) && ['overview', 'stores', 'skus', 'products', 'snapshots', 'trends', 'alerts'].includes(parts[1])) state.ui.competitorTab = parts[1];
  if (parts[0] === 'profit') profitView = ['plans', 'rules'].includes(parts[1]) ? parts[1] : 'calculator';
}
function renderNavigation() {
  $$('[data-module]').forEach(function (button) {
    const active = button.dataset.module === state.ui.module;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $$('[data-module-page]').forEach(function (page) {
    const active = page.dataset.modulePage === state.ui.module;
    page.hidden = !active;
    page.classList.toggle('active', active);
  });
  $$('[data-warehouse-tab]').forEach(function (button) {
    const active = button.dataset.warehouseTab === state.ui.warehouseTab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $$('[data-warehouse-page]').forEach(function (page) {
    page.hidden = page.dataset.warehousePage !== state.ui.warehouseTab;
  });
  $$('[data-competitor-tab]').forEach(function (button) {
    const active = button.dataset.competitorTab === state.ui.competitorTab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $$('[data-competitor-page]').forEach(function (page) {
    page.hidden = page.dataset.competitorPage !== state.ui.competitorTab;
  });
  $$('[data-profit-view-page]').forEach(function (page) {
    page.hidden = state.ui.module !== 'profit' || page.dataset.profitViewPage !== profitView;
  });
}

function renderSidebar() {
  $$('[data-sidebar-module]').forEach(function (section) {
    const active = section.dataset.sidebarModule === state.ui.module;
    section.hidden = !active;
    section.classList.toggle('active', active);
  });
  $$('[data-side-link]').forEach(function (button) {
    let active = false;
    if (!button.dataset.sideAction && state.ui.module === 'products' && button.dataset.productView) {
      active = button.dataset.productView === productFilter;
    }
    if (state.ui.module === 'warehouse' && button.dataset.warehouseView === state.ui.warehouseTab) {
      if (state.ui.warehouseTab === 'purchase') active = button.dataset.purchaseView === purchaseFilter;
      if (state.ui.warehouseTab === 'orders') active = button.dataset.orderView === orderFilter;
      if (state.ui.warehouseTab === 'inventory') {
        if (button.dataset.productView === 'low-stock') active = inventoryFilter === 'low';
        else if (button.dataset.scrollTarget === 'movementPanel') active = inventoryFilter === 'all' && inventorySection === 'movements';
        else active = inventoryFilter === 'all' && inventorySection === 'list';
      } else if (['transfers', 'replenishment'].includes(state.ui.warehouseTab)) active = true;
    }
    if (state.ui.module === 'analytics' && button.dataset.competitorView) {
      active = button.dataset.competitorView === state.ui.competitorTab;
    }
    if (state.ui.module === 'creators' && button.dataset.creatorView) active = true;
    if (state.ui.module === 'selection' && button.dataset.selectionScroll) {
      active = button.dataset.selectionScroll === 'selectionKeywordPanel';
    }
    if (state.ui.module === 'profit' && button.dataset.profitView) {
      active = button.dataset.profitView === profitView && (profitView === 'rules' || button.dataset.scrollTarget === profitScrollTarget);
    }
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  $$('[data-product-filter]:not([data-side-link])').forEach(function (button) {
    button.classList.toggle('active', button.dataset.productFilter === productFilter);
  });
  $$('[data-purchase-filter]:not([data-side-link])').forEach(function (button) {
    button.classList.toggle('active', button.dataset.purchaseFilter === purchaseFilter);
  });
  $$('[data-transfer-filter]').forEach(function (button) {
    button.classList.toggle('active', button.dataset.transferFilter === transferFilter);
  });
  $$('[data-order-filter]:not([data-side-link])').forEach(function (button) {
    button.classList.toggle('active', button.dataset.orderFilter === orderFilter);
  });
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
  const toggle = $('#sidebarToggle');
  const scrim = $('#sidebarScrim');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
  if (scrim) scrim.setAttribute('aria-hidden', 'true');
}
function toggleSidebar() {
  const opening = !document.body.classList.contains('sidebar-open');
  document.body.classList.toggle('sidebar-open', opening);
  if ($('#sidebarToggle')) $('#sidebarToggle').setAttribute('aria-expanded', String(opening));
  if ($('#sidebarScrim')) $('#sidebarScrim').setAttribute('aria-hidden', String(!opening));
}
function scrollToPanel(id) {
  if (!id) return;
  requestAnimationFrame(function () {
    const target = $('#' + id);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}
function handleSideLink(button) {
  const action = button.dataset.sideAction;
  if (action === 'import' || action === 'export') {
    closeSidebar();
    const target = $('#' + button.dataset.scrollTarget);
    if (target) target.click();
    return;
  }
  if (button.dataset.productView && !button.dataset.warehouseView) {
    productFilter = button.dataset.productView;
    setRoute('products');
    return;
  }
  if (button.dataset.scrollTarget && !button.dataset.warehouseView && !button.dataset.profitView && !button.dataset.selectionScroll) {
    setRoute('products');
    return setTimeout(function () { scrollToPanel(button.dataset.scrollTarget); }, 0);
  }
  if (button.dataset.selectionScroll) {
    setRoute('selection');
    return setTimeout(function () { scrollToPanel(button.dataset.selectionScroll); }, 0);
  }
  if (button.dataset.warehouseView) {
    const view = button.dataset.warehouseView;
    if (view === 'purchase') purchaseFilter = button.dataset.purchaseView || 'open';
    if (view === 'orders') orderFilter = button.dataset.orderView || 'open';
    if (view === 'inventory') {
      inventoryFilter = button.dataset.productView === 'low-stock' ? 'low' : 'all';
      inventorySection = button.dataset.scrollTarget === 'movementPanel' ? 'movements' : 'list';
    }
    const scrollTarget = button.dataset.scrollTarget;
    setRoute('warehouse', view);
    scrollToPanel(scrollTarget);
    return;
  }
  if (button.dataset.competitorView) setRoute('analytics', button.dataset.competitorView);
  if (button.dataset.creatorView || button.dataset.creatorStage) {
    setRoute('creators');
    if (button.dataset.creatorStage && $('#creatorStageFilter')) $('#creatorStageFilter').value = button.dataset.creatorStage === 'sample' ? 'sampling' : 'published';
    loadCreators(true);
  }
  if (button.dataset.profitView) {
    profitScrollTarget = button.dataset.scrollTarget || 'profitInputPanel';
    setRoute('profit', button.dataset.profitView);
    if (button.dataset.scrollTarget) setTimeout(function () { scrollToPanel(button.dataset.scrollTarget); }, 0);
    else window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

function renderProductSummary() {
  const activeProducts = state.products.filter(function (item) { return item.status === 'active'; });
  const owns = ownProducts(state);
  const competitors = activeProducts.filter(function (item) { return item.kind !== 'own'; });
  const replenish = owns.filter(function (product) { return availableFor(product.id) < integer(product.safetyStock); });
  setText('#productTotalMetric', state.products.length);
  setText('#ownProductMetric', owns.length);
  setText('#competitorProductMetric', competitors.length);
  setText('#replenishmentMetric', replenish.length);
  setText('#navProductCount', state.products.length);
}

function renderProducts() {
  let products = state.products.filter(function (product) {
    if (product.kind !== 'own') return false;
    if (productFilter === 'inactive') return product.status === 'inactive';
    if (productFilter === 'own') return true;
    return product.status === 'active';
  }).filter(function (product) { return searchMatches(product); });
  products.sort(function (a, b) { return new Date(b.updatedAt) - new Date(a.updatedAt); });
  $('#productRows').innerHTML = products.map(function (product) {
    const available = availableFor(product.id);
    const summary = product.profitSummary || {};
    const range = function (item, prefix, suffix) {
      if (!item) return '<span class="profit-range">—<small>参数待完善</small></span>';
      const min = Number(item.min); const max = Number(item.max);
      return '<span class="profit-range">' + escapeHtml(prefix + min.toFixed(2) + (min !== max ? '–' + prefix + max.toFixed(2) : '') + suffix) + '</span>';
    };
    const metric = function (item, prefix, suffix) {
      return '<button class="profit-range-button" type="button" data-action="toggle-profit-details" data-id="' + escapeHtml(product.id) + '">' + range(item, prefix, suffix) + '</button>';
    };
    let actions = teamCapabilityAllowed('catalog') ? rowButton('edit-product', product.id, '编辑', 'primary') : '';
    actions += rowButton('toggle-profit-details', product.id, expandedProfitSkuIds.has(product.id) ? '收起' : '测算');
    if (teamCapabilityAllowed('catalog') && product.status === 'inactive') actions += rowButton('activate-product', product.id, '启用');
    else if (teamCapabilityAllowed('catalog')) actions += rowButton('delete-product', product.id, '删除/停用', 'danger');
    const detail = (summary.stores || []).map(function (store) {
      return '<article class="store-profit-card"><strong>' + escapeHtml(store.store_name) + '</strong>' +
        (store.calculable ? '<span>售价 RM' + escapeHtml(store.sale_price) + ' · 毛利 RM' + escapeHtml(store.gross_profit) + '</span><span>毛利率 ' + escapeHtml(store.gross_margin) + '% · ROI ' + escapeHtml(store.break_even_roi == null ? '不可盈利' : store.break_even_roi) + '</span>' : '<span>待完善：' + escapeHtml((store.missing || []).join('、')) + '</span>') + '</article>';
    }).join('') || '<span>尚未配置参与试算的店铺售价。</span>';
    return '<tr><td>' + productMedia(product) + '</td><td>' + metric(summary.sale_price, 'RM', '') + '</td><td>' + metric(summary.gross_profit, 'RM', '') + '</td><td>' + metric(summary.gross_margin, '', '%') + '</td><td>' + metric(summary.break_even_roi, '', '') + '</td>' +
      '<td><span class="stock-number ' + (available < product.safetyStock ? 'low' : 'instock') + '">' + available + '</span></td><td><div class="row-actions">' + actions + '</div></td></tr>' +
      (expandedProfitSkuIds.has(product.id) ? '<tr class="product-profit-detail"><td colspan="7"><div class="store-profit-grid">' + detail + '</div></td></tr>' : '');
  }).join('');
  toggleEmpty('#productEmpty', products.length === 0);
}

function warehouseTypeOf(warehouse) {
  return warehouse ? (warehouse.type || warehouse.warehouse_type || 'other') : 'other';
}
function activeWarehouses() {
  if (TEAM_MODE && teamGateway) return teamGateway.warehouses.filter(function (item) { return item.active !== false; });
  return state.warehouses.filter(function (item) { return item.active; });
}
function renderWarehouseSwitcher() {
  const warehouses = activeWarehouses();
  const selectedId = TEAM_MODE && teamGateway ? String(teamGateway.warehouseId || '') : String(currentWarehouseId());
  const selected = warehouses.find(function (item) { return String(item.id) === selectedId; }) || warehouses[0] || null;
  const switcher = $('#warehouseSwitcher');
  if (switcher) {
    switcher.innerHTML = warehouses.map(function (warehouse) {
      const active = String(warehouse.id) === selectedId;
      return '<button class="warehouse-switch' + (active ? ' active' : '') + '" type="button" data-warehouse-switch="' + escapeHtml(String(warehouse.id)) + '" aria-pressed="' + String(active) + '">' +
        '<strong>' + escapeHtml(warehouse.name) + '</strong><small>' + escapeHtml(warehouse.code || '') + '</small></button>';
    }).join('');
  }
  setText('#currentWarehouseName', selected ? selected.name : '请先创建仓库');
  setText('#currentWarehouseMeta', selected ? (WAREHOUSE_TYPE_LABELS[warehouseTypeOf(selected)] || '其他') + ' · ' + (selected.country || '未设置地区') : '无可用仓库');
}
function renderWarehouseDirectory() {
  const rootWarehouses = TEAM_MODE && teamGateway ? teamGateway.warehouses : state.warehouses;
  const container = $('#warehouseManageRows');
  if (!container) return;
  container.innerHTML = rootWarehouses.map(function (warehouse) {
    const typeLabel = WAREHOUSE_TYPE_LABELS[warehouseTypeOf(warehouse)] || '其他';
    const capabilities = [warehouse.canReceive !== false && warehouse.can_receive !== false ? '可收货' : '', warehouse.canShip !== false && warehouse.can_ship !== false ? '可出库' : ''].filter(Boolean).join(' · ');
    return '<article class="warehouse-directory-item' + (warehouse.active === false ? ' inactive' : '') + '"><div><strong>' + escapeHtml(warehouse.name) + '</strong><span>' + escapeHtml((warehouse.code || '') + ' · ' + typeLabel + ' · ' + (warehouse.country || '未设置地区')) + '</span><small>' + escapeHtml(capabilities || '未开放收发权限') + '</small></div><div class="row-actions">' +
      (teamCapabilityAllowed('warehouse_admin') ? rowButton('edit-warehouse', String(warehouse.id), '编辑', 'primary') + rowButton(warehouse.active === false ? 'activate-warehouse' : 'archive-warehouse', String(warehouse.id), warehouse.active === false ? '启用' : '停用', warehouse.active === false ? '' : 'danger') : '') + '</div></article>';
  }).join('') || '<div class="last-value">还没有仓库。</div>';
}

function warehouseValueText() {
  const groups = new Map();
  ownProducts(state, true).forEach(function (product) {
    const value = balanceFor(product.id).onHand * nonNegative(product.standardCost);
    if (!value) return;
    const code = product.costCurrency || 'CNY';
    groups.set(code, (groups.get(code) || 0) + value);
  });
  if (!groups.size) return '库存金额 ¥0.00';
  return '库存金额 ' + Array.from(groups, function (entry) { return money(entry[1], entry[0]); }).join(' · ');
}
function renderWarehouseSummary() {
  renderWarehouseSwitcher();
  const owns = ownProducts(state, true);
  const transit = owns.reduce(function (sum, item) { return sum + inboundFor(item.id); }, 0);
  const onHand = owns.reduce(function (sum, item) { return sum + balanceFor(item.id).onHand; }, 0);
  const reserved = owns.reduce(function (sum, item) { return sum + balanceFor(item.id).reserved; }, 0);
  const openPurchases = state.purchaseOrders.filter(function (item) { return isCurrentWarehouseRecord(item) && isPurchaseOpen(item); }).length;
  const pendingOrders = state.salesOrders.filter(function (item) { return isCurrentWarehouseRecord(item) && !['shipped', 'cancelled'].includes(item.status); }).length;
  setText('#warehouseTransitTotal', transit);
  setText('#warehouseInStockTotal', onHand);
  setText('#warehouseAvailableTotal', Math.max(0, onHand - reserved));
  setText('#warehousePendingOrderTotal', pendingOrders);
  setText('#warehouseTransitFoot', openPurchases + ' 张未完成采购单');
  setText('#warehouseReservedFoot', '已锁定 ' + reserved + ' 件');
  setText('#warehouseValueFoot', warehouseValueText());
  setText('#purchaseTabCount', openPurchases);
  setText('#inventoryTabCount', owns.filter(function (item) { return balanceFor(item.id).onHand > 0; }).length);
  setText('#orderTabCount', pendingOrders);
  setText('#navWarehouseCount', transit + onHand);
}

function purchaseIsOverdue(order) {
  return isPurchaseOpen(order) && order.expectedAt && order.expectedAt < today();
}
function purchaseAmount(order) {
  const groups = new Map();
  order.lines.forEach(function (line) {
    const product = productById(line.productId);
    const code = product ? product.costCurrency : 'CNY';
    groups.set(code, (groups.get(code) || 0) + integer(line.orderedQty) * nonNegative(line.unitCost));
  });
  if (groups.size === 1) {
    const entry = Array.from(groups)[0];
    return money(entry[1] + nonNegative(order.extraCost), entry[0]);
  }
  return groups.size ? '多币种 ' + groups.size + ' 组' : money(order.extraCost, 'CNY');
}
function renderPurchases() {
  let orders = state.purchaseOrders.filter(function (order) {
    if (!isCurrentWarehouseRecord(order)) return false;
    if (purchaseFilter === 'open') return isPurchaseOpen(order);
    if (purchaseFilter === 'overdue') return purchaseIsOverdue(order);
    return true;
  }).filter(function (order) {
    return !searchTerm || [order.number, order.supplier, order.note].join(' ').toLowerCase().includes(searchTerm) ||
      order.lines.some(function (line) { return searchMatches(productById(line.productId), order.number); });
  }).sort(function (a, b) { return new Date(b.createdAt) - new Date(a.createdAt); });
  $('#purchaseRows').innerHTML = orders.map(function (order) {
    const ordered = order.lines.reduce(function (sum, line) { return sum + integer(line.orderedQty); }, 0);
    const received = order.lines.reduce(function (sum, line) { return sum + integer(line.receivedQty); }, 0);
    const transit = order.lines.reduce(function (sum, line) { return sum + remainingPurchaseLine(line); }, 0);
    const purchaseLineCards = order.lines.map(function (line) {
      const product = productById(line.productId);
      return productQuantityMedia(product || { name: '商品已移除', sku: '' }, line.orderedQty);
    });
    const lines = purchaseLineCards.length > 1
      ? '<details class="purchase-detail-list"><summary>' + purchaseLineCards[0] + '<span>共 ' + purchaseLineCards.length + ' 项</span></summary><div>' + purchaseLineCards.map(function (card) { return '<div class="transfer-product-line">' + card + '</div>'; }).join('') + '</div></details>'
      : (purchaseLineCards[0] ? '<span class="purchase-single-line">' + purchaseLineCards[0] + '</span>' : '<span class="muted">无商品明细</span>');
    const overdue = purchaseIsOverdue(order);
    const shipments = order.shipments || [];
    const tracking = shipments.length ? ('<button class="link-button" data-toggle-purchase-shipments="' + escapeHtml(order.id) + '">' + escapeHtml(shipments[0].trackingNumber) + (shipments.length > 1 ? ' +' + (shipments.length - 1) : '') + '</button>' +
      (order.showShipments ? '<div class="shipment-summary">' + shipments.map(function (shipment) { return '<div><strong>' + escapeHtml(shipment.trackingNumber) + '</strong>：' + shipment.lines.map(function (line) { const product = productById((order.lines.find(function (item) { return item.id === line.purchaseLineId; }) || {}).productId); return escapeHtml((product && product.sku) || 'SKU') + '×' + integer(line.quantity); }).join('，') + '</div>'; }).join('') + '</div>' : '')) : '<span class="muted">未填写</span>';
    let actions = '';
    const canEditPurchase = TEAM_MODE
      ? !['completed', 'cancelled', 'received'].includes(order.status)
      : ['draft', 'ordered', 'transit', 'partial'].includes(order.status);
    if (teamCapabilityAllowed('purchase') && canEditPurchase) actions += rowButton('edit-purchase', order.id, '编辑', 'secondary');
    const warehouse = TEAM_MODE ? selectedWarehouse() : warehouseById(order.warehouseId || currentWarehouseId());
    if (teamCapabilityAllowed('purchase') && order.status === 'draft') actions += rowButton('submit-purchase', order.id, '确认下单', 'primary');
    if (teamCapabilityAllowed('purchase') && order.status === 'draft') actions += rowButton('delete-purchase', order.id, '删除', 'danger');
    if (teamCapabilityAllowed('purchase') && order.status === 'ordered') actions += rowButton('transit-purchase', order.id, '标记在途', 'primary');
    if (isPurchaseOpen(order) && teamCapabilityAllowed('receipt') && warehouse && warehouse.canReceive !== false && warehouse.can_receive !== false) actions += rowButton('receive-purchase', order.id, '确认收货', 'primary');
    if (isPurchaseOpen(order) && teamCapabilityAllowed('purchase')) actions += rowButton('cancel-purchase', order.id, '取消余量', 'danger');
    const statusClass = overdue ? 'overdue' : order.status;
    const statusLabel = overdue ? '已逾期' : PURCHASE_LABELS[order.status];
    return '<tr><td><strong>' + escapeHtml(order.number) + '</strong><br><small>' + formatDate(order.orderedAt, false) + '</small></td>' +
      '<td>' + escapeHtml(order.purchaserName || '操作员') + '</td><td>' + tracking + '</td><td>' + lines + '</td><td>' + ordered + ' / ' + received + '</td>' +
      '<td><span class="stock-number transit">' + (isPurchaseOpen(order) ? transit : 0) + '</span></td>' +
      '<td class="' + (overdue ? 'overdue-copy' : '') + '">' + formatDate(order.expectedAt, false) + '</td><td>' + purchaseAmount(order) + '</td>' +
      '<td>' + statusPill(statusLabel, statusClass) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#purchaseEmpty', orders.length === 0);
}

function renderInventory() {
  let products = ownProducts(state, true).filter(function (product) {
    // A deleted/missing balance is still a valid SKU master.  Keep it visible so
    // the operator can see the SKU and recreate/adjust its stock deliberately.
    // Filtering it here made the whole inventory page look empty after a balance
    // was deleted, even though other inventory data still existed.
    return (product.status !== 'draft' || hasBusinessReferences(product.id)) && (!product.needsReview || hasBusinessReferences(product.id)) && searchMatches(product);
  });
  if (inventoryFilter === 'low') {
    products = products.filter(function (product) { return product.status === 'active' && availableFor(product.id) < integer(product.safetyStock); });
  }
  $('#warehouseRows').innerHTML = products.map(function (product) {
    const balance = balanceFor(product.id);
    const available = Math.max(0, balance.onHand - balance.reserved);
    const low = available < integer(product.safetyStock);
    const canDeleteBalance = TEAM_MODE && teamCapabilityAllowed('inventory') && balance.apiBalanceId;
    const inbound = inboundFor(product.id);
    return '<tr><td>' + productMedia(product) + '</td><td>' + escapeHtml(product.sku || '待完善') + '</td>' +
      '<td><span class="stock-number instock">' + balance.onHand + '</span></td><td>' + balance.reserved + '</td>' +
      '<td><span class="stock-number ' + (low ? 'low' : 'instock') + '">' + available + '</span></td><td><button class="stock-number transit transit-number-button" type="button" data-action="view-transit-sources" data-id="' + escapeHtml(product.id) + '" aria-label="查看在途库存来源">' + inbound + '</button></td><td>' + integer(product.safetyStock) + '</td>' +
      '<td>' + money(balance.onHand * nonNegative(product.standardCost), product.costCurrency) + '</td>' +
      '<td>' + (product.status === 'draft' ? statusPill('草稿 · 有库存', 'shortage') : (product.status === 'inactive' ? statusPill('已停用', 'inactive') : (product.needsReview ? statusPill('待完善', 'shortage') : (low ? statusPill('需补货', 'shortage') : statusPill('正常', 'active'))))) + '</td>' +
      '<td><div class="row-actions">' + (teamCapabilityAllowed('inventory') && product.status === 'active' && !product.needsReview ? rowButton('adjust-stock', product.id, '库存调整', 'primary') : (teamCapabilityAllowed('catalog') && product.needsReview ? rowButton('edit-product', product.id, '完善商品', 'primary') : '')) + rowButton('view-movements', product.id, '看流水') + (canDeleteBalance ? rowButton('delete-stock-balance', product.id, '彻底删除库存', 'danger') : '') + '</div></td></tr>';
  }).join('');
  toggleEmpty('#warehouseEmpty', products.length === 0);
  requestAnimationFrame(updateInventoryStickyHeader);
}
function productQuantityMedia(product, quantity, options) {
  const config = options || {};
  const suffix = config.suffix || '';
  const label = quantity == null || quantity === '' ? '—' : String(quantity);
  return '<div class="product-quantity-cell">' + productMedia(product || {}) + '<span class="product-quantity">× ' + escapeHtml(label + suffix) + '</span></div>';
}
function setControlValue(selector, value) {
  const node = $(selector);
  if (node) node.value = value == null ? '' : value;
  return node;
}
function setControlChecked(selector, checked) {
  const node = $(selector);
  if (node) node.checked = Boolean(checked);
  return node;
}

function movementDeltaText(movement) {
  if (movement.onHandDelta) return (movement.onHandDelta > 0 ? '+' : '') + movement.onHandDelta + ' 在库';
  if (movement.reservedDelta) return (movement.reservedDelta > 0 ? '+' : '') + movement.reservedDelta + ' 锁定';
  return '0';
}
function renderMovements() {
  const filter = $('#movementProduct') ? $('#movementProduct').value : 'all';
  const movements = state.inventoryMovements.filter(function (item) {
    const product = productById(item.productId);
    return isCurrentWarehouseRecord(item) && (filter === 'all' || item.productId === filter) && searchMatches(product, item.sourceNumber);
  }).sort(function (a, b) { return new Date(b.occurredAt) - new Date(a.occurredAt); }).slice(0, 40);
  $('#movementRows').innerHTML = movements.map(function (movement) {
    const product = productById(movement.productId);
    const positive = movement.onHandDelta > 0 || movement.reservedDelta > 0;
    const negative = movement.onHandDelta < 0 || movement.reservedDelta < 0;
    const canRevoke = TEAM_MODE && teamCapabilityAllowed('inventory') && ['adjustment', 'manual_inbound', 'manual_outbound'].includes(movement.type) && !movement.isReversed;
    return '<tr><td>' + formatDate(movement.occurredAt, true) + '</td><td>' + escapeHtml(product ? product.sku + ' · ' + product.name : '未知商品') + '</td>' +
      '<td>' + escapeHtml(MOVEMENT_LABELS[movement.type] || movement.type) + '</td><td><span class="delta-pill ' + (positive ? 'up' : (negative ? 'down' : 'neutral')) + '">' + movementDeltaText(movement) + '</span></td>' +
      '<td>' + integer(movement.afterOnHand) + '</td><td>' + escapeHtml(movement.note || '—') + (movement.isReversed ? '（已撤回）' : '') + '</td>' + (canRevoke ? '<td><div class="row-actions">' + rowButton('revoke-movement', movement.id, '撤回', 'danger') + '</div></td>' : '<td></td>') + '</tr>';
  }).join('');
  toggleEmpty('#movementEmpty', movements.length === 0);
}

function transferWarehouseName(warehouseId) {
  const warehouse = warehouseById(warehouseId);
  return warehouse ? warehouse.name : '未知仓库';
}
function transferLineQuantity(line) { return integer(line.quantity == null ? line.requestedQty : line.quantity); }
function transferReceivedQuantity(line) { return integer(line.receivedQty == null ? line.received_quantity : line.receivedQty); }
function transferTouchesWarehouse(transfer, warehouseId) {
  return String(transfer.sourceWarehouseId || transfer.source_warehouse || '') === String(warehouseId) ||
    String(transfer.destinationWarehouseId || transfer.destination_warehouse || '') === String(warehouseId);
}
function dispatchTransfer(next, transfer) {
  const sourceWarehouseId = transfer.sourceWarehouseId;
  const destinationWarehouseId = transfer.destinationWarehouseId;
  if (!sourceWarehouseId || !destinationWarehouseId || sourceWarehouseId === destinationWarehouseId) throw new Error('调出仓和调入仓必须不同。');
  const sourceWarehouse = warehouseById(sourceWarehouseId, next);
  const destinationWarehouse = warehouseById(destinationWarehouseId, next);
  if (!sourceWarehouse || !sourceWarehouse.active || !destinationWarehouse || !destinationWarehouse.active) throw new Error('调拨仓库不存在或已停用。');
  if (sourceWarehouse.canShip === false || destinationWarehouse.canReceive === false) throw new Error('请检查调出仓的出库权限和调入仓的收货权限。');
  const shortage = transfer.lines.find(function (line) {
    return availableFor(line.productId, next, sourceWarehouseId) < transferLineQuantity(line);
  });
  if (shortage) {
    const product = productById(shortage.productId, next);
    throw new Error((product ? product.name : '商品') + '在调出仓的可用库存不足。');
  }
  const occurredAt = new Date().toISOString();
  transfer.lines.forEach(function (line) {
    addMovement(next, {
      warehouseId: sourceWarehouseId, productId: line.productId, type: 'transfer_out',
      onHandDelta: -transferLineQuantity(line), reservedDelta: 0, sourceType: 'stock_transfer',
      sourceId: transfer.id, sourceLineId: line.id, sourceNumber: transfer.number,
      occurredAt: occurredAt, note: transfer.note || '仓间调拨发出'
    });
  });
  transfer.status = 'in_transit';
  transfer.shippedAt = occurredAt;
  transfer.updatedAt = occurredAt;
}
function receiveTransfer(next, transferId) {
  const transfer = next.stockTransfers.find(function (item) { return item.id === transferId; });
  if (!transfer || transfer.status !== 'in_transit') throw new Error('调拨单当前不能收货。');
  const destinationWarehouse = warehouseById(transfer.destinationWarehouseId, next);
  if (!destinationWarehouse || !destinationWarehouse.active || destinationWarehouse.canReceive === false || destinationWarehouse.can_receive === false) throw new Error('调入仓未开放收货，不能确认调入。');
  const occurredAt = new Date().toISOString();
  transfer.lines.forEach(function (line) {
    const remaining = Math.max(0, transferLineQuantity(line) - transferReceivedQuantity(line));
    if (!remaining) return;
    addMovement(next, {
      warehouseId: transfer.destinationWarehouseId, productId: line.productId, type: 'transfer_in',
      onHandDelta: remaining, reservedDelta: 0, sourceType: 'stock_transfer',
      sourceId: transfer.id, sourceLineId: line.id, sourceNumber: transfer.number,
      occurredAt: occurredAt, note: transfer.note || '仓间调拨收货'
    });
    line.receivedQty = transferLineQuantity(line);
  });
  transfer.status = 'received';
  transfer.receivedAt = occurredAt;
  transfer.updatedAt = occurredAt;
}
function cancelTransfer(next, transferId) {
  const transfer = next.stockTransfers.find(function (item) { return item.id === transferId; });
  if (!transfer || transfer.status !== 'draft') throw new Error('调拨发出后不能取消，请通过异常关闭流程处理。');
  const occurredAt = new Date().toISOString();
  transfer.status = 'cancelled';
  transfer.updatedAt = occurredAt;
}
function transferRemainingQuantity(line) {
  return Math.max(0, transferLineQuantity(line) - transferReceivedQuantity(line) - integer(line.exceptionClosedQty == null ? line.exception_closed_quantity : line.exceptionClosedQty));
}
async function openTransferWorkflow(transfer, mode) {
  if (!transfer || !TEAM_MODE || !teamGateway) return showToast('调拨物流处理仅支持团队在线模式。');
  activeTransferWorkflow = { transfer: transfer, mode: mode, packages: [] };
  const body = $('#transferWorkflowBody');
  const submit = $('#submitTransferWorkflow');
  $('#transferWorkflowModalTitle').textContent = mode === 'packages' ? '维护物流包裹' : (mode === 'exception' ? '关闭运输异常数量' : '部分/全部收货');
  if (mode === 'packages') {
    $('#transferWorkflowModalIntro').textContent = transfer.status === 'draft' ? '发货前可维护多个包裹和各包 SKU 数量；总数必须等于调拨计划。' : '发货后 SKU 数量已锁定，仅可补录物流单号。';
    submit.textContent = '保存物流信息';
    body.innerHTML = '<div class="last-value">正在加载包裹…</div>';
    openModal('transferWorkflowModal');
    try {
      const packages = await teamGateway.listTransferPackages(transfer);
      activeTransferWorkflow.packages = packages;
      renderTransferPackageWorkflow();
    } catch (error) { body.innerHTML = '<div class="last-value">' + escapeHtml(error.message || '加载失败') + '</div>'; }
    return;
  }
  const verb = mode === 'exception' ? '异常关闭' : '本次收货';
  $('#transferWorkflowModalIntro').textContent = '可只处理到货 SKU；remaining = 计划 - 已收货 - 异常关闭。异常关闭不会增加目的仓在库库存。';
  submit.textContent = verb;
  body.innerHTML = '<div class="form-grid two">' + transfer.lines.map(function (line) {
    const product = productById(line.productId);
    const remaining = transferRemainingQuantity(line);
    return '<label>' + productQuantityMedia(product || { name: 'SKU', sku: line.sku || '' }, remaining) + '（剩余 ' + remaining + '）<input type="number" min="0" max="' + remaining + '" value="0" data-transfer-workflow-line="' + escapeHtml(line.id) + '" /></label>';
  }).join('') + '</div>' + (mode === 'exception' ? '<label>异常原因（可选）<input id="transferExceptionReason" maxlength="240" placeholder="可不填写" /></label>' : '');
  openModal('transferWorkflowModal');
}
function renderTransferPackageWorkflow() {
  const workflow = activeTransferWorkflow;
  if (!workflow) return;
  const locked = workflow.transfer.status !== 'draft';
  const packages = workflow.packages || [];
  $('#transferWorkflowBody').innerHTML = packages.map(function (pack, packIndex) {
    const packageLines = (pack.lines || []).map(function (line) {
      const product = productById((state.products || []).find(function (item) { return item.skuId === String(line.sku); })?.id);
      return '<tr><td>' + productQuantityMedia(product || { name: 'SKU', sku: line.sku || '' }, line.quantity) + '</td><td>' + line.quantity + '</td></tr>';
    }).join('');
    return '<article class="line-list-item"><label>物流单号（可留空）<input value="' + escapeHtml(pack.tracking_number || pack.trackingNumber || '') + '" data-workflow-package-tracking="' + packIndex + '" /></label><table><thead><tr><th>SKU</th><th>包内数量</th></tr></thead><tbody>' + packageLines + '</tbody></table>' + (locked ? '<small>已发货：包内 SKU 数量已锁定。</small>' : '') + '</article>';
  }).join('') || '<div class="last-value">当前没有物流包裹；可在新建调拨时添加包裹。</div>';
}
async function submitTransferWorkflow() {
  const workflow = activeTransferWorkflow;
  if (!workflow) return;
  const transfer = workflow.transfer;
  if (workflow.mode === 'packages') {
    $$('#transferWorkflowBody [data-workflow-package-tracking]').forEach(function (input) {
      const pack = workflow.packages[Number(input.dataset.workflowPackageTracking)];
      if (pack) pack.trackingNumber = input.value.trim();
    });
    const saved = await executeTeamCommand(function () { return teamGateway.saveTransferPackages(transfer, workflow.packages); }, '物流包裹信息已保存。', 'transfer');
    if (saved) closeModal('transferWorkflowModal');
    return;
  }
  const quantities = $$('#transferWorkflowBody [data-transfer-workflow-line]').map(function (input) {
    return { transferLineId: input.dataset.transferWorkflowLine, quantity: integer(input.value) };
  }).filter(function (line) { return line.quantity > 0; });
  if (!quantities.length) return showToast('请至少填写一个 SKU 数量。');
  const command = workflow.mode === 'exception'
    ? function () { const reasonInput = $('#transferExceptionReason'); return teamGateway.closeTransferException(transfer, quantities, reasonInput ? reasonInput.value : ''); }
    : function () { return teamGateway.receiveTransfer(transfer, quantities); };
  const saved = await executeTeamCommand(command, workflow.mode === 'exception' ? '异常数量已关闭，不会转入在库。' : '本次收货已入库。', 'transfer');
  if (saved) closeModal('transferWorkflowModal');
}

function openTransferCompletion(transfer) {
  if (!transfer || !TEAM_MODE || !teamGateway) return showToast('结束调拨仅支持团队在线模式。');
  const remainingLines = (transfer.lines || []).map(function (line) {
    return { line: line, remaining: transferRemainingQuantity(line) };
  }).filter(function (item) { return item.remaining > 0; });
  if (!['in_transit', 'partially_received'].includes(transfer.status) || !remainingLines.length) return showToast('这张调拨单没有可结束的在途剩余。');
  activeTransferCompletion = { transfer: transfer, remainingLines: remainingLines };
  transferCompletionBusy = false;
  setControlValue('#transferCompleteReason', '');
  $('#submitTransferComplete').disabled = false;
  $('#submitTransferComplete').textContent = '结束调拨';
  $('#transferCompleteModalTitle').textContent = '结束调拨 · ' + (transfer.number || '未编号');
  $('#transferCompleteIntro').textContent = '以下全部剩余数量将原子记为异常关闭；目的仓不增加在库，来源仓不恢复库存。';
  $('#transferCompleteRows').innerHTML = remainingLines.map(function (item) {
    const line = item.line;
    const product = productById(line.productId || line.product_id);
    const exceptionClosed = integer(line.exceptionClosedQty == null ? line.exception_closed_quantity : line.exceptionClosedQty);
    return '<tr><td>' + escapeHtml(product ? product.sku + ' · ' + product.name : (line.skuId || line.sku || 'SKU')) + '</td><td>' + transferLineQuantity(line) + '</td><td>' + transferReceivedQuantity(line) + '</td><td>' + exceptionClosed + '</td><td><strong>' + item.remaining + '</strong></td></tr>';
  }).join('');
  openModal('transferCompleteModal');
}

async function confirmTransferCompletion() {
  if (!activeTransferCompletion || transferCompletionBusy) return;
  const reasonInput = $('#transferCompleteReason');
  const reason = reasonInput ? reasonInput.value.trim() : '';
  const completion = activeTransferCompletion;
  transferCompletionBusy = true;
  $('#submitTransferComplete').disabled = true;
  $('#submitTransferComplete').textContent = '正在结束…';
  try {
    const saved = await executeTeamCommand(function () {
      return teamGateway.completeTransferWithException(completion.transfer, reason);
    }, '调拨已结束：全部剩余已异常关闭，在途库存已同步减少。', 'transfer', { refreshOnError: false });
    if (saved) {
      closeModal('transferCompleteModal');
      activeTransferCompletion = null;
    }
  } finally {
    transferCompletionBusy = false;
    const button = $('#submitTransferComplete');
    if (button) { button.disabled = false; button.textContent = '结束调拨'; }
  }
}

function handleTransferCompleteSubmit(event) {
  event.preventDefault();
  if (!activeTransferCompletion || transferCompletionBusy) return;
  const reasonInput = $('#transferCompleteReason');
  const reason = reasonInput ? reasonInput.value.trim() : '';
  const total = activeTransferCompletion.remainingLines.reduce(function (sum, item) { return sum + item.remaining; }, 0);
  askConfirm('二次确认：结束调拨并异常关闭全部剩余 ' + total + ' 件？该动作不会恢复来源仓库存。', confirmTransferCompletion);
}

function renderTransfers() {
  const warehouseId = TEAM_MODE ? String(teamGateway && teamGateway.warehouseId || '') : currentWarehouseId();
  const allTransfers = state.stockTransfers.filter(function (transfer) {
    return transferTouchesWarehouse(transfer, warehouseId);
  });
  const transfers = allTransfers.filter(function (transfer) {
    if (transferFilter === 'open') return ['draft', 'in_transit', 'partially_received'].includes(transfer.status);
    if (transferFilter === 'closed') return ['received', 'completed_with_exception', 'cancelled'].includes(transfer.status);
    return true;
  })
    .sort(function (a, b) { return new Date(b.createdAt || b.created_at) - new Date(a.createdAt || a.created_at); });
  const rows = $('#transferRows');
  if (!rows) return;
  rows.innerHTML = transfers.map(function (transfer) {
    const sourceId = transfer.sourceWarehouseId || transfer.source_warehouse;
    const destinationId = transfer.destinationWarehouseId || transfer.destination_warehouse;
    const lines = transfer.lines || [];
    const lineCards = lines.map(function (line) {
      const product = productById(line.productId || line.product_id);
      return '<div class="transfer-product-line">' + productQuantityMedia(product || { name: '未知商品', sku: line.sku || '' }, transferLineQuantity(line)) + '</div>';
    }).join('');
    const lineText = lines.length > 1
      ? '<details class="transfer-detail-list"><summary>' + productQuantityMedia(productById(lines[0].productId || lines[0].product_id) || { name: '未知商品', sku: lines[0].sku || '' }, transferLineQuantity(lines[0])) + '<span>共 ' + lines.length + ' 项</span></summary><div>' + lineCards + '</div></details>'
      : (lineCards || '<span class="muted">无商品明细</span>');
    const total = lines.reduce(function (sum, line) { return sum + transferLineQuantity(line); }, 0);
    let actions = '';
    const sourceWarehouse = warehouseById(sourceId);
    const destinationWarehouse = warehouseById(destinationId);
    const isSource = String(sourceId) === String(warehouseId);
    const isDestination = String(destinationId) === String(warehouseId);
    if (teamCapabilityAllowed('transfer') && transfer.status === 'draft' && isSource) actions += rowButton('manage-transfer-packages', transfer.id, '物流包裹', 'secondary');
    if (teamCapabilityAllowed('transfer') && transfer.status === 'draft' && isSource && sourceWarehouse && sourceWarehouse.canShip !== false && sourceWarehouse.can_ship !== false) actions += rowButton('dispatch-transfer', transfer.id, '发出调拨', 'primary');
    if (teamCapabilityAllowed('transfer') && ['in_transit', 'partially_received'].includes(transfer.status) && isDestination && destinationWarehouse && destinationWarehouse.canReceive !== false && destinationWarehouse.can_receive !== false) {
      actions += rowButton('manage-transfer-packages', transfer.id, '物流单号', 'secondary');
      actions += rowButton('receive-transfer', transfer.id, '办理收货', 'primary');
      actions += rowButton('close-transfer-exception', transfer.id, '异常关闭', 'danger');
      if (lines.some(function (line) { return transferRemainingQuantity(line) > 0; })) actions += rowButton('complete-transfer-with-exception', transfer.id, '结束调拨', 'danger');
    }
    if (teamCapabilityAllowed('transfer') && transfer.status === 'draft' && isSource) actions += rowButton('cancel-transfer', transfer.id, '取消草稿', 'danger');
    if (['in_transit', 'partially_received'].includes(transfer.status) && isSource && !actions) actions += '<span class="row-note">等待目标仓收货或结束调拨</span>';
    return '<tr><td><strong>' + escapeHtml(transfer.number) + '</strong></td><td>' + escapeHtml(transferWarehouseName(sourceId)) + '</td><td>' + escapeHtml(transferWarehouseName(destinationId)) + '</td><td>' + lineText + '</td><td>' + total + '</td><td>' + formatDate(transfer.shippedAt || transfer.shipped_at, true) + '</td><td>' + statusPill(TRANSFER_LABELS[transfer.status] || transfer.status, transfer.status) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#transferEmpty', transfers.length === 0);
  const pending = allTransfers.filter(function (item) { return ['draft', 'in_transit', 'partially_received'].includes(item.status); }).length;
  setText('#transferTabCount', pending);
}

function localPolicyFor(productId, warehouseId) {
  const stored = state.replenishmentPolicies.find(function (item) { return item.productId === productId && item.warehouseId === warehouseId; }) || {};
  return {
    id: stored.id || '', productId: productId, warehouseId: warehouseId,
    leadTimeOverride: stored.leadTimeOverride == null || stored.leadTimeOverride === '' ? null : nonNegative(stored.leadTimeOverride),
    reviewCycleDays: integer(stored.reviewCycleDays || 7) || 7,
    targetDays: integer(stored.targetDays || 30) || 30,
    minOrderQty: integer(stored.minOrderQty || 1) || 1,
    packSize: integer(stored.packSize || 1) || 1,
    safetyStockOverride: stored.safetyStockOverride == null || stored.safetyStockOverride === '' ? null : integer(stored.safetyStockOverride),
    safetyMarginRatio: Math.min(1, Math.max(0, asNumber(stored.safetyMarginRatio, 0.2)))
  };
}
function normalizeTeamRecommendation(item) {
  const lead = item.lead_time || item.leadTime || {};
  const demand = item.demand || {};
  const inventory = item.inventory || {};
  return {
    productId: String(item.product_id || item.productId || item.product || ''),
    skuId: String(item.sku_id || item.skuId || item.sku || ''),
    velocity: asNumber(demand.daily_velocity == null ? item.weighted_daily_velocity : demand.daily_velocity),
    velocity3: asNumber(demand.daily_3), velocity7: asNumber(demand.daily_7), velocity15: asNumber(demand.daily_15), velocity30: asNumber(demand.daily_30),
    leadDays: asNumber(lead.selected_days == null ? item.lead_days : lead.selected_days, 14),
    leadSource: lead.source || item.lead_source || 'fallback', available: integer(inventory.available == null ? item.available : inventory.available),
    inbound: integer(inventory.inbound_total == null ? (inventory.in_transit == null ? item.in_transit : inventory.in_transit) : inventory.inbound_total),
    inventoryPosition: integer(inventory.inventory_position == null ? item.inventory_position : inventory.inventory_position),
    reorderPoint: integer(item.reorder_point), daysCover: item.available_days_of_cover == null ? Infinity : asNumber(item.available_days_of_cover),
    stockoutDate: item.projected_stockout_date || item.available_stockout_date || '', latestOrderDate: item.latest_order_date || '',
    suggestedQty: integer(item.suggested_order_quantity == null ? item.suggested_qty : item.suggested_order_quantity),
    safetyMarginRatio: asNumber(item.safety_margin_ratio, 0), safetyMarginUnits: asNumber(item.safety_margin_units, 0),
    demandBreakdown: demand.breakdown || {}, reasons: Array.isArray(item.reasons) ? item.reasons : [],
    urgency: item.alert_level || item.urgency || 'healthy', confidence: item.confidence || lead.confidence || 'low', policy: item.policy || {}
  };
}
function replenishmentRecommendations() {
  if (TEAM_MODE && Array.isArray(state.replenishmentRecommendations) && state.replenishmentRecommendations.length) {
    return state.replenishmentRecommendations.map(normalizeTeamRecommendation);
  }
  return [];
}
function recommendationProduct(recommendation) {
  return productById(recommendation.productId) || state.products.find(function (item) { return recommendation.skuId && String(item.skuId) === recommendation.skuId; });
}
function renderReplenishment() {
  const recommendations = replenishmentRecommendations().filter(function (item) {
    const product = recommendationProduct(item);
    return Boolean(product) && searchMatches(product, item.skuId || '');
  })
    .sort(function (a, b) { return ({ urgent: 0, red: 0, soon: 1, yellow: 1, healthy: 2, green: 2 }[a.urgency] || 3) - ({ urgent: 0, red: 0, soon: 1, yellow: 1, healthy: 2, green: 2 }[b.urgency] || 3); });
  const rows = $('#replenishmentRows');
  if (!rows) return;
  const visibleSkuIds = recommendations.map(function (item) { return String(item.skuId); });
  const selectAll = $('#replenishmentSelectAll');
  if (selectAll) {
    selectAll.checked = visibleSkuIds.length > 0 && visibleSkuIds.every(function (skuId) { return replenishmentSelectedSkuIds.has(skuId); });
    selectAll.indeterminate = !selectAll.checked && visibleSkuIds.some(function (skuId) { return replenishmentSelectedSkuIds.has(skuId); });
  }
  setText('#replenishmentSelectionCount', replenishmentSelectedSkuIds.size ? ('已选 ' + replenishmentSelectedSkuIds.size + ' 个 SKU') : '未选择 SKU');
  rows.innerHTML = recommendations.map(function (item) {
    const product = recommendationProduct(item);
    const urgency = item.urgency === 'red' ? 'urgent' : (item.urgency === 'yellow' ? 'soon' : (item.urgency === 'green' ? 'healthy' : item.urgency));
    const urgencyLabel = { urgent: '立即补货', soon: '尽快下单', healthy: '库存健康', insufficient: '数据不足' }[urgency] || '待核对';
    const leadLabel = Math.ceil(item.leadDays) + ' 天 · ' + ({ manual: '手工', history_p80: '历史 P80', fallback: '默认' }[item.leadSource] || '历史预测');
    const daysCover = Number.isFinite(item.daysCover) ? item.daysCover.toFixed(1) + ' 天' : '暂无销量';
    const warehouseId = TEAM_MODE && teamGateway ? String(teamGateway.warehouseId) : currentWarehouseId();
    const hasPolicy = state.replenishmentPolicies.some(function (policy) { return policy.productId === product.id && String(policy.warehouseId) === warehouseId; });
    const latestOrder = item.latestOrderDate ? ((item.latestOrderDate < today() ? '已逾期 · ' : '') + formatDate(item.latestOrderDate, false)) : '暂无';
    let actions = '';
    if (teamCapabilityAllowed('purchase') && item.suggestedQty > 0) actions += rowButton('create-purchase-from-replenishment', product.id, '创建采购', 'primary');
    if (teamCapabilityAllowed('replenishment')) actions += rowButton('edit-replenishment', product.id, '调整参数');
    if (teamCapabilityAllowed('replenishment') && hasPolicy) actions += rowButton('reset-replenishment', product.id, '恢复默认', 'danger');
    const selected = replenishmentSelectedSkuIds.has(String(item.skuId));
    const breakdown = item.demandBreakdown || {};
    const thirtyDayQuantity = asNumber((breakdown[30] || breakdown['30'] || {}).quantity);
    const noSalesReason = item.velocity === 0 ? '<small>近30天没有订单正式出库或手动销售出库。</small>' : '';
    return '<tr><td class="replenishment-select-column"><input type="checkbox" data-replenishment-select="' + escapeHtml(item.skuId) + '"' + (selected ? ' checked' : '') + ' aria-label="选择 ' + escapeHtml(product.sku || product.name) + '"></td><td class="replenishment-product-column">' + productMedia(product) + '</td><td><strong>' + item.velocity.toFixed(2) + '</strong>' + noSalesReason + '</td><td><strong>' + thirtyDayQuantity.toFixed(0) + ' 件</strong><button class="replenishment-demand-link" type="button" data-action="view-demand-detail" data-id="' + escapeHtml(product.id) + '">查看周期明细</button></td><td>' + escapeHtml(leadLabel) + '</td><td>' + item.available + ' / ' + item.inbound + '<br><small>库存位 ' + item.inventoryPosition + '</small></td><td>' + daysCover + '<br><small>' + (item.stockoutDate ? '预计缺货 ' + formatDate(item.stockoutDate, false) : '无法预计缺货日') + '</small></td><td>' + latestOrder + '</td><td><strong class="suggested-qty">' + item.suggestedQty + '</strong></td><td>' + statusPill(urgencyLabel, urgency) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#replenishmentEmpty', recommendations.length === 0);
  const needCount = recommendations.filter(function (item) { return ['urgent', 'soon', 'red', 'yellow'].includes(item.urgency); }).length;
  setText('#replenishmentTabCount', needCount);
  setText('#replenishmentMetric', needCount);
}

function demandNumber(row, keys) {
  for (const key of keys) {
    if (row && row[key] != null && Number.isFinite(Number(row[key]))) return Number(row[key]);
  }
  return 0;
}

function normalizeDemandWarehouse(row) {
  const orderOutbound = demandNumber(row, ['order_outbound_quantity', 'order_outbound', 'order_quantity', 'orders']);
  const manualOutbound = demandNumber(row, ['manual_sales_outbound_quantity', 'manual_outbound', 'manual_quantity']);
  const total = row && row.true_outbound != null ? Number(row.true_outbound) : orderOutbound + manualOutbound;
  return {
    name: (row && (row.warehouse_name || row.name)) || '未命名仓库',
    code: (row && (row.warehouse_code || row.code)) || '',
    timezone: (row && row.timezone) || '',
    orderOutbound: orderOutbound,
    manualOutbound: manualOutbound,
    total: total,
    average: row && (row.daily_average != null || row.average_daily_outbound != null)
      ? demandNumber(row, ['daily_average', 'average_daily_outbound']) : 0
  };
}

function renderReplenishmentDemandDetail(product, payload) {
  const rawRows = Array.isArray(payload) ? payload : (payload.warehouses || payload.results || []);
  const warehouses = rawRows.map(normalizeDemandWarehouse);
  setText('#replenishmentDemandTitle', (product.sku || 'SKU') + ' · 各仓库近30天出库来源');
  const rowsNode = $('#replenishmentDemandRows');
  if (!rowsNode) return;
  rowsNode.innerHTML = warehouses.length ? warehouses.map(function (row) {
    return '<tr><td><strong>' + escapeHtml(row.name) + '</strong><small>' + escapeHtml(row.code + (row.timezone ? ' · ' + row.timezone : '')) + '</small></td><td>' + row.orderOutbound + '</td><td>' + row.manualOutbound + '</td><td><strong>' + row.total + '</strong></td><td>' + row.average.toFixed(2) + '</td></tr>';
  }).join('') : '<tr><td colspan="5">所有可访问仓库近30天均无真实销售出库，数量为 0。</td></tr>';
  const total = warehouses.reduce(function (sum, row) {
    sum.orderOutbound += row.orderOutbound; sum.manualOutbound += row.manualOutbound;
    sum.total += row.total; return sum;
  }, { orderOutbound: 0, manualOutbound: 0, total: 0 });
  const days = Number(payload && payload.days) || 30;
  const periods = Array.isArray(payload && payload.periods) ? payload.periods : [];
  const periodText = periods.map(function (period) { return 'Q' + period.days + ' = ' + period.quantity + '，W' + period.days + ' = ' + Number(period.weight).toFixed(2); }).join('；');
  const totalNode = $('#replenishmentDemandTotal');
  if (totalNode) totalNode.innerHTML = '<tr><th>全部可见仓库合计</th><th>' + total.orderOutbound + '</th><th>' + total.manualOutbound + '</th><th>' + total.total + '</th><th>' + (total.total / days).toFixed(2) + '</th></tr>';
  setText('#replenishmentDemandMeta', '近' + days + '天真实出库 = 订单正式出库 + 手动销售出库；权重来源：' + ((payload && payload.weight_source) === 'sku' ? 'SKU 独立' : '全局') + '；' + periodText + '；加权天数分母：' + ((payload && payload.weighted_denominator) || '—') + '；全仓加权日均出库：' + ((payload && payload.weighted_daily_outbound) || '—') + '。退货不冲减需求。');
}

async function openReplenishmentDemandDetail(productId) {
  const product = productById(productId);
  if (!product) return showToast('商品不存在。');
  if (!TEAM_MODE || !teamGateway) return showToast('各仓周期明细仅在团队在线模式下提供。');
  if (!teamCapabilityAllowed('replenishment')) return showToast('当前账号没有查看补货明细的权限。');
  setText('#replenishmentDemandTitle', (product.sku || 'SKU') + ' · 正在读取');
  const rowsNode = $('#replenishmentDemandRows'); if (rowsNode) rowsNode.innerHTML = '<tr><td colspan="5">正在读取各仓库近30天出库来源…</td></tr>';
  const totalNode = $('#replenishmentDemandTotal'); if (totalNode) totalNode.innerHTML = '';
  setText('#replenishmentDemandMeta', '');
  openModal('replenishmentDemandModal');
  try {
    const payload = await teamGateway.getReplenishmentDemandDetail(product, 30);
    renderReplenishmentDemandDetail(product, payload || {});
  } catch (error) {
    if (rowsNode) rowsNode.innerHTML = '<tr><td colspan="5">' + escapeHtml(error && error.message || '读取失败，请重试。') + '</td></tr>';
    handleTeamError(error);
  }
}

const CREATOR_STAGE_LABELS = { pending: '待联系', contacted: '已联系', negotiating: '洽谈中', sampling: '寄样中', publishing: '待发布', published: '已发布', completed: '已完成', paused: '暂停' };

async function loadCreators() {
  if (!TEAM_MODE || !teamGateway || analyticsState.loading === 'creators') return;
  creatorState.loading = true;
  creatorState.error = '';
  try {
    creatorState.rows = await teamGateway.listCreators({
      search: $('#creatorSearch') ? $('#creatorSearch').value.trim() : '',
      stage: $('#creatorStageFilter') ? $('#creatorStageFilter').value : '',
      archived: $('#creatorArchivedFilter') ? $('#creatorArchivedFilter').value : 'false'
    });
    creatorState.loaded = true;
  } catch (error) { creatorState.error = error.message || '读取达人档案失败。'; handleTeamError(error); }
  finally { creatorState.loading = false; renderCreators(); }
}

function renderCreators() {
  const rows = creatorState.rows || [];
  const tbody = $('#creatorRows');
  if (!tbody) return;
  tbody.innerHTML = rows.map(function (item) {
    const contact = item.contact && (item.contact.value || item.contact.phone || item.contact.email || item.contact.wechat) || '—';
    const owner = item.responsible_by_name || item.responsible_by_username || '—';
    const stage = CREATOR_STAGE_LABELS[item.cooperation_status] || item.cooperation_status || '待联系';
    return '<tr><td><strong>' + escapeHtml(item.display_name) + '</strong><br><small>' + escapeHtml(item.account_name || '账号待补充') + '</small></td><td>' + escapeHtml((item.platform || '—') + (item.country ? ' · ' + item.country : '')) + '</td><td>' + escapeHtml(contact) + '</td><td>' + statusPill(stage, item.cooperation_status || 'pending') + '</td><td>' + escapeHtml(owner) + '</td><td>—</td><td>' + (item.incomplete ? '<span class="status-pill soon">待完善</span>' : '<span class="status-pill healthy">完整</span>') + '</td><td><div class="row-actions"><button class="row-action" type="button" data-creator-open="' + escapeHtml(item.id) + '">查看</button><button class="row-action" type="button" data-creator-edit="' + escapeHtml(item.id) + '">编辑</button>' + (item.is_archived ? '<button class="row-action" type="button" data-creator-restore="' + escapeHtml(item.id) + '">恢复</button>' : '<button class="row-action danger" type="button" data-creator-archive="' + escapeHtml(item.id) + '">归档</button>') + '</div></td></tr>';
  }).join('');
  toggleEmpty('#creatorEmpty', !rows.length);
  if (!creatorState.loaded && TEAM_MODE && teamCapabilityAllowed('creator_view')) loadCreators();
}

function openCreatorEditor(id) {
  const item = (creatorState.rows || []).find(function (row) { return String(row.id) === String(id); }) || {};
  $('#creatorId').value = item.id || '';
  $('#creatorName').value = item.display_name || '';
  $('#creatorPlatform').value = item.platform || '';
  $('#creatorHandle').value = item.account_name || '';
  $('#creatorProfileUrl').value = item.profile_url || '';
  $('#creatorMarket').value = item.country || '';
  $('#creatorLanguage').value = item.language || '';
  $('#creatorContact').value = item.contact && (item.contact.value || item.contact.phone || item.contact.email || item.contact.wechat) || '';
  $('#creatorFollowers').value = item.follower_count == null ? '' : item.follower_count;
  $('#creatorTags').value = Array.isArray(item.tags) ? item.tags.join(', ') : '';
  $('#creatorOwner').value = '';
  $('#creatorStage').value = item.cooperation_status || 'pending';
  $('#creatorNotes').value = item.notes || '';
  $('#creatorModalTitle').textContent = item.id ? '编辑达人' : '新建达人';
  openModal('creatorModal');
}

async function saveCreatorFromForm(event) {
  event.preventDefault();
  if (!TEAM_MODE || !teamGateway) return showToast('达人档案仅支持团队在线模式。');
  const id = $('#creatorId').value;
  const contact = $('#creatorContact').value.trim();
  const payload = {
    display_name: $('#creatorName').value.trim(), platform: $('#creatorPlatform').value,
    account_name: $('#creatorHandle').value.trim(), profile_url: $('#creatorProfileUrl').value.trim(),
    country: $('#creatorMarket').value.trim(), language: $('#creatorLanguage').value.trim(),
    contact: contact ? { value: contact } : {},
    follower_count: $('#creatorFollowers').value === '' ? null : Number($('#creatorFollowers').value),
    tags: $('#creatorTags').value.split(',').map(function (value) { return value.trim(); }).filter(Boolean),
    cooperation_status: $('#creatorStage').value, notes: $('#creatorNotes').value.trim()
  };
  if (!payload.display_name) return showToast('达人名称或昵称不能为空。');
  try {
    await teamGateway.saveCreator(payload, id || null);
    closeModal('creatorModal'); await loadCreators(); showToast(id ? '达人档案已更新。' : '达人档案已保存，可后续补充资料。');
  } catch (error) { handleTeamError(error); }
}

function renderProfitPlans() {
  const tbody = $('#profitPlanRows');
  if (!tbody) return;
  const rows = profitPlanState.rows || [];
  tbody.innerHTML = rows.map(function (plan) {
    const version = plan.latest_version || {};
    const item = version.result_snapshot && version.result_snapshot.item || {};
    const value = function (key) { return item[key] == null ? '—' : escapeHtml(String(item[key])); };
    const feeValue = function (key) { return !item.fees || item.fees[key] == null ? '—' : escapeHtml(String(item.fees[key])); };
    const image = plan.image_url_snapshot ? '<img class="thumb" src="' + escapeHtml(plan.image_url_snapshot) + '" alt="" />' : '';
    const store = (state.stores || []).find(function (row) { return String(row.apiStoreId || row.id) === String(plan.store || ''); });
    const rate = version.exchange_rate_snapshot || {};
    const lifecycle = plan.status === 'archived' ? '<button class="row-action" type="button" data-profit-plan-restore="' + escapeHtml(plan.id) + '">恢复</button>' : '<button class="row-action danger" type="button" data-profit-plan-archive="' + escapeHtml(plan.id) + '">归档</button>';
    return '<tr><td><div class="product-cell">' + image + '<div><strong>' + escapeHtml(plan.sku_name_snapshot || '—') + '</strong><br><small>' + escapeHtml(plan.sku_code_snapshot || '—') + '</small></div></div></td><td>' + escapeHtml(store && store.name || '未关联店铺') + '<br><small>' + escapeHtml(plan.name || '默认方案') + '</small></td><td>' + value('revenue') + ' / ' + feeValue('product_cost') + '</td><td>' + value('affiliate_rate') + '% / ' + value('advertising_rebate_percent') + '%</td><td>' + value('gross_profit') + ' / ' + value('gross_margin') + '%</td><td>' + value('advertising_cost') + '</td><td>' + value('net_profit') + ' / ' + value('net_margin') + '%</td><td>' + value('true_roi') + ' / ' + value('true_cpa_usd') + '</td><td>v' + escapeHtml(String(version.version_number || 0)) + ' · ' + escapeHtml(version.rule_version || '—') + '<br><small>' + escapeHtml(rate.effective_date || rate.source || '—') + ' · ' + escapeHtml(version.created_by_name || plan.updated_by_name || '—') + ' · ' + formatDate(version.created_at, true) + '</small></td><td><div class="row-actions"><button class="row-action" type="button" data-profit-plan-history="' + escapeHtml(plan.id) + '">历史</button><button class="row-action" type="button" data-profit-plan-recalculate="' + escapeHtml(plan.id) + '">重新计算</button>' + lifecycle + '</div></td></tr>';
  }).join('');
  toggleEmpty('#profitPlansEmpty', !rows.length);
  if (profitView === 'plans' && !profitPlanState.loaded && TEAM_MODE && teamCapabilityAllowed('profit_record_view')) loadProfitPlans();
}

async function loadProfitPlans() {
  if (!TEAM_MODE || !teamGateway || profitPlanState.loading) return;
  profitPlanState.loading = true;
  try {
    profitPlanState.rows = await teamGateway.listProfitPlans({ search: $('#profitPlanSearch') ? $('#profitPlanSearch').value.trim() : '', store: $('#profitPlanStoreFilter') ? $('#profitPlanStoreFilter').value : '', status: $('#profitPlanStatusFilter') ? $('#profitPlanStatusFilter').value : 'active' });
    profitPlanState.loaded = true;
  } catch (error) { handleTeamError(error); }
  finally { profitPlanState.loading = false; renderProfitPlans(); }
}

async function openCreatorDetail(id) {
  if (!TEAM_MODE || !teamGateway) return;
  try {
    const creator = await teamGateway.getCreator(id);
    creatorState.active = creator;
    $('#creatorDetailTitle').textContent = creator.display_name + ' · 业务记录';
    $('#creatorDetailIntro').textContent = '档案、合作和后续记录均保留在当前组织内；业绩归因不会由销量自动推断。';
    $('#creatorActivityCreatorId').value = creator.id;
    const lists = await Promise.all(['collaborations', 'samples', 'contents', 'followups', 'attributions'].map(function (type) {
      return teamGateway.request('/creators/' + creator.id + '/' + type + '/').catch(function () { return []; });
    }));
    const labels = ['合作', '寄样', '内容', '跟进', '归因'];
    const collaborations = lists[0] || [];
    $('#creatorActivityCollaboration').innerHTML = '<option value="">不关联 / 请先建立合作</option>' + collaborations.map(function (row) {
      const label = CREATOR_STAGE_LABELS[row.stage] || row.stage || '合作';
      return '<option value="' + escapeHtml(row.id) + '">' + escapeHtml(label + (row.notes ? ' · ' + row.notes : '')) + '</option>';
    }).join('');
    $('#creatorActivityStore').innerHTML = '<option value="">不关联店铺</option>' + (state.stores || []).map(function (store) {
      return '<option value="' + escapeHtml(store.apiStoreId || store.id) + '">' + escapeHtml(store.name || store.code || '未命名店铺') + '</option>';
    }).join('');
    $('#creatorActivitySku').innerHTML = '<option value="">不关联商品</option>' + (state.products || []).map(function (product) {
      return '<option value="' + escapeHtml(product.skuId || product.id) + '">' + escapeHtml((product.sku || '—') + ' · ' + (product.name || '未命名商品')) + '</option>';
    }).join('');
    configureCreatorActivityForm();
    $('#creatorActivityRows').innerHTML = lists.flatMap(function (rows, index) {
      return (rows || []).map(function (row) {
        const operator = row.recorded_by_name || row.created_by_name || '';
        const meta = formatDate(row.created_at, true) + (operator ? ' · 操作人：' + operator : '');
        return '<article class="transit-source-card"><strong>' + labels[index] + '</strong><p>' + escapeHtml(row.notes || row.note || row.status || row.stage || row.source || '已记录') + '</p><small>' + escapeHtml(meta) + '</small></article>';
      });
    }).join('') || '<p class="last-value">暂无业务记录，可先新增合作或跟进。</p>';
    openModal('creatorDetailModal');
  } catch (error) { handleTeamError(error); }
}

function configureCreatorActivityForm() {
  const type = $('#creatorActivityType') ? $('#creatorActivityType').value : 'collaboration';
  const options = {
    collaboration: [['pending', '待联系'], ['contacted', '已联系'], ['negotiating', '洽谈中'], ['sampling', '寄样中'], ['publishing', '待发布'], ['published', '已发布'], ['completed', '已完成'], ['paused', '暂停']],
    sample: [['pending', '待发货'], ['shipped', '已发货'], ['received', '已签收'], ['exception', '异常']],
    content: [['video', '视频'], ['live', '直播'], ['post', '图文'], ['other', '其他内容']],
    followup: [['pending', '待跟进']],
    attribution: [['unattributed', '未归因']]
  };
  const status = $('#creatorActivityStatus');
  if (status) status.innerHTML = (options[type] || options.collaboration).map(function (option) {
    return '<option value="' + option[0] + '">' + option[1] + '</option>';
  }).join('');
}

async function openProfitPlanHistory(id) {
  try {
    const plan = await teamGateway.getProfitPlan(id);
    const versions = await teamGateway.listProfitPlanVersions(id);
    profitPlanState.active = plan; profitPlanState.versions = versions;
    $('#profitPlanHistoryTitle').textContent = (plan.sku_code_snapshot || 'SKU') + ' · ' + (plan.name || '利润方案');
    $('#profitPlanHistoryIntro').textContent = '历史版本为不可变快照；重新计算会按当前规则、当前汇率生成新版本。';
    $('#profitPlanVersionRows').innerHTML = versions.map(function (version) {
      const item = version.result_snapshot && version.result_snapshot.item || {};
      return '<tr><td>v' + version.version_number + '</td><td>' + escapeHtml(version.rule_version || '—') + '<br><small>' + escapeHtml((version.exchange_rate_snapshot || {}).source || '—') + '</small></td><td>' + escapeHtml(String(item.advertising_rebate_percent == null ? '—' : item.advertising_rebate_percent)) + '%</td><td>' + escapeHtml(String(item.gross_profit == null ? '—' : item.gross_profit)) + ' / ' + escapeHtml(String(item.net_profit == null ? '—' : item.net_profit)) + '</td><td>' + escapeHtml(version.created_by_name || '—') + '<br><small>' + formatDate(version.created_at, true) + '</small></td><td><div class="row-actions"><button class="row-action" type="button" data-profit-snapshot="' + escapeHtml(version.id) + '">查看原结果</button><button class="row-action" type="button" data-profit-version-recalculate="' + escapeHtml(version.id) + '">按当前规则重算</button></div></td></tr>';
    }).join('');
    openModal('profitPlanHistoryModal');
  } catch (error) { handleTeamError(error); }
}

async function prepareProfitPlanRecalculation(id, versionId) {
  try {
    const payload = await teamGateway.prepareProfitPlanRecalculation(id, versionId);
    if (!payload || !payload.calculation) throw new Error('服务器没有返回可重新计算的原始输入。');
    if (!window.DongboProfitCalculator || typeof window.DongboProfitCalculator.loadCalculation !== 'function') throw new Error('利润试算页面尚未初始化。');
    window.DongboProfitCalculator.loadCalculation(payload.calculation, {
      action: 'new_version', targetPlan: payload.target_plan,
      sourceVersion: payload.source_version, sourceRuleVersion: payload.source_rule_version
    });
    setRoute('profit', 'calculator');
    showToast('已带入历史输入；点击计算并保存会按当前规则和汇率生成新版本。');
  } catch (error) { handleTeamError(error); }
}

async function saveCreatorActivityFromForm(event) {
  event.preventDefault();
  const creatorId = $('#creatorActivityCreatorId').value;
  const type = $('#creatorActivityType').value;
  if (!creatorId) return showToast('请先打开达人详情。');
  const collaboration = $('#creatorActivityCollaboration').value || null;
  const notes = $('#creatorActivityNotes').value.trim();
  const occurredAt = $('#creatorActivityOccurredAt').value ? new Date($('#creatorActivityOccurredAt').value).toISOString() : null;
  const plannedAt = $('#creatorActivityPlannedAt').value ? new Date($('#creatorActivityPlannedAt').value).toISOString() : null;
  const common = {
    stage: $('#creatorActivityStatus').value || 'pending', store: $('#creatorActivityStore').value || null,
    sku: $('#creatorActivitySku').value || null,
    commission_percent: $('#creatorActivityCommission').value === '' ? null : Number($('#creatorActivityCommission').value),
    fixed_fee: $('#creatorActivityFixedFee').value === '' ? null : Number($('#creatorActivityFixedFee').value),
    notes: notes
  };
  let payload;
  if (type === 'collaboration') payload = common;
  if (type === 'sample') {
    if (!collaboration) return showToast('寄样记录必须选择一条合作。');
    const sampleStatus = common.stage || 'pending';
    payload = { collaboration: collaboration, sku: common.sku, quantity: Number($('#creatorActivityQuantity').value || 1), tracking_number: $('#creatorActivityTracking').value.trim(), status: sampleStatus, notes: notes };
    if (occurredAt && sampleStatus === 'shipped') payload.shipped_at = occurredAt;
    if (occurredAt && sampleStatus === 'received') payload.signed_at = occurredAt;
  }
  if (type === 'content') {
    if (!collaboration) return showToast('内容记录必须选择一条合作。');
    payload = { collaboration: collaboration, content_type: common.stage === 'pending' ? '' : common.stage, url: $('#creatorActivityUrl').value.trim(), planned_at: plannedAt, published_at: occurredAt, notes: notes };
  }
  if (type === 'followup') payload = { collaboration: collaboration, note: notes, next_reminder_at: plannedAt };
  if (type === 'attribution') payload = {
    collaboration: collaboration, store: common.store, source: $('#creatorActivitySource').value || 'unattributed',
    order_count: Number($('#creatorActivityOrders').value || 0), units: Number($('#creatorActivityUnits').value || 0),
    gmv: $('#creatorActivityGmv').value === '' ? null : Number($('#creatorActivityGmv').value),
    attributed_on: occurredAt ? occurredAt.slice(0, 10) : null
  };
  try { await teamGateway.createCreatorActivity(creatorId, type, payload); await openCreatorDetail(creatorId); showToast('达人业务记录已保存。'); }
  catch (error) { handleTeamError(error); }
}

function renderOrders() {
  const warehouseId = currentWarehouseId();
  const warehouse = selectedWarehouse();
  const canShip = Boolean(warehouse && warehouse.canShip !== false && warehouse.can_ship !== false);
  let orders = state.salesOrders.filter(function (order) {
    // TeamGateway already scopes loaded orders to the selected real warehouse;
    // its browser state intentionally uses a local display warehouse id.
    if (!TEAM_MODE && order.warehouseId && order.warehouseId !== warehouseId) return false;
    if (orderFilter === 'open') return !['shipped', 'cancelled'].includes(order.status);
    if (orderFilter === 'shortage') return order.status === 'shortage';
    if (orderFilter === 'shipped') return order.status === 'shipped';
    return true;
  }).filter(function (order) {
    return !searchTerm || [order.number, order.platform, order.store, order.trackingNumber].join(' ').toLowerCase().includes(searchTerm) ||
      order.lines.some(function (line) { return searchMatches(productById(line.productId), order.number); });
  }).sort(function (a, b) { return new Date(b.createdAt) - new Date(a.createdAt); });
  $('#orderRows').innerHTML = orders.map(function (order) {
    const qty = order.lines.reduce(function (sum, line) { return sum + integer(line.quantity); }, 0);
    const lineText = order.lines.slice(0, 2).map(function (line) {
      const product = productById(line.productId);
      const returned = returnedForLine(line.id);
      return escapeHtml((product ? product.sku + ' · ' + product.name : '未知商品') + ' × ' + integer(line.quantity) + (returned ? '（已退 ' + returned + '）' : ''));
    }).join('<br>') + (order.lines.length > 2 ? '<br>等 ' + order.lines.length + ' 项' : '');
    let actions = '';
    if (teamCapabilityAllowed('order') && !['shipped', 'cancelled'].includes(order.status) && !order.warehouseId) actions += rowButton('assign-order-warehouse', order.id, '选择仓库', 'primary');
    else if (teamCapabilityAllowed('order') && canShip && !['shipped', 'cancelled'].includes(order.status)) {
      actions += rowButton('confirm-ship-order', order.id, '确认并出库', 'primary');
      if (order.apiStatus === 'allocated') actions += rowButton('change-order-warehouse', order.id, '更换仓库', 'secondary');
    }
    if (teamCapabilityAllowed('return') && order.status === 'shipped' && order.lines.some(function (line) { return returnableForLine(line) > 0; })) actions += rowButton('return-order', order.id, '退货入库', 'primary');
    if (teamCapabilityAllowed('order') && !['shipped', 'cancelled'].includes(order.status)) actions += rowButton('cancel-order', order.id, '取消', 'danger');
    if (teamCapabilityAllowed('order') && order.status === 'cancelled' && order.fulfillmentOverride === 'erp_cancelled') actions += rowButton('restore-order-fulfillment', order.id, '恢复履约', 'secondary');
    return '<tr><td><strong>' + escapeHtml(order.number) + '</strong></td><td>' + escapeHtml(order.platform) + '<br><small>' + escapeHtml(order.store || '—') + '</small></td>' +
      '<td>' + lineText + '</td><td>' + qty + '</td><td>' + formatDate(order.orderedAt, true) + '</td><td>' + escapeHtml(order.trackingNumber || '—') + '</td>' +
      '<td>' + statusPill(ORDER_LABELS[order.status] || order.status, order.status) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#orderEmpty', orders.length === 0);
}

async function openOrderWarehouseSelector(order, change) {
  if (!order || !TEAM_MODE || !teamGateway) return showToast('仓库选择仅支持团队在线模式。');
  const container = $('#orderWarehouseOptions');
  activeOrderWarehouseSelection = { order: order, change: Boolean(change) };
  $('#orderWarehouseModalTitle').textContent = change ? '更换履约仓库' : '选择履约仓库';
  $('#orderWarehouseModalIntro').textContent = '正在校验订单 ' + order.number + ' 的各仓库存…';
  container.innerHTML = '<div class="last-value">正在加载仓库可用量…</div>';
  openModal('orderWarehouseModal');
  try {
    const result = await teamGateway.getOrderWarehouseOptions(order);
    const options = result.options || [];
    $('#orderWarehouseModalIntro').textContent = '每个仓库均按整单 SKU 校验 required / available / shortage；存在缺货或未映射 SKU 时不能选择。';
    container.innerHTML = options.map(function (option) {
      const lines = option.lines || [];
      const warehouse = option.warehouse || option;
      const detail = lines.map(function (line) {
        return '<tr><td>' + escapeHtml(line.sku_code || line.sku || '未映射 SKU') + '</td><td>' + line.required + '</td><td>' + line.available + '</td><td>' + line.shortage + '</td></tr>';
      }).join('');
      const disabled = !option.selectable;
      return '<article class="warehouse-directory-item' + (disabled ? ' disabled' : '') + '"><div><strong>' + escapeHtml(warehouse.code + ' · ' + warehouse.name) + '</strong><small>整单缺货 ' + escapeHtml(option.shortage || '0') + '</small></div>' +
        '<table><thead><tr><th>SKU</th><th>需求</th><th>可用</th><th>缺货</th></tr></thead><tbody>' + detail + '</tbody></table>' +
        '<button class="button ' + (disabled ? 'secondary' : 'primary') + '" type="button" data-choose-order-warehouse="' + escapeHtml(warehouse.id) + '"' + (disabled ? ' disabled' : '') + '>' + (disabled ? '库存不足，不能选择' : '选择并整单锁库') + '</button></article>';
    }).join('') || '<div class="last-value">没有可用于履约的仓库。</div>';
  } catch (error) {
    $('#orderWarehouseModalIntro').textContent = '无法加载仓库库存校验结果。';
    container.innerHTML = '<div class="last-value">' + escapeHtml(error && error.message ? error.message : '加载失败，请重试。') + '</div>';
  }
}

async function chooseOrderWarehouse(warehouseId) {
  const selection = activeOrderWarehouseSelection;
  if (!selection) return;
  const saved = await executeTeamCommand(function () {
    return teamGateway.assignOrderWarehouse(selection.order, warehouseId, selection.change);
  }, selection.change ? '已更换仓库并重新锁库。' : '已选择仓库并完成整单锁库。', 'order');
  if (saved) {
    closeModal('orderWarehouseModal');
    activeOrderWarehouseSelection = null;
  }
}

function snapshotChange(productId) {
  const pair = latestPair(productId);
  return {
    pair: pair,
    sales: pair.latest && pair.previous ? pair.latest.sold - pair.previous.sold : null,
    price: pair.latest && pair.previous ? pair.latest.price - pair.previous.price : null,
    reviews: pair.latest && pair.previous ? pair.latest.reviews - pair.previous.reviews : null
  };
}
function monitoringPickerProducts() {
  const term = monitoringPickerTerm.trim().toLowerCase();
  return ownProducts(state, true).filter(function (product) {
    if (product.status !== 'active' || product.needsReview) return false;
    if (!term) return true;
    return [product.name, product.sku, product.seller, product.market].some(function (value) {
      return String(value || '').toLowerCase().includes(term);
    });
  });
}
function renderMonitoringProductPicker() {
  const container = $('#monitoringProductPicker');
  if (!container) return;
  const products = monitoringPickerProducts();
  const selectable = products.filter(function (product) { return !product.monitoringEnabled; });
  Array.from(monitoringPickerSelected).forEach(function (productId) {
    if (!selectable.some(function (product) { return product.id === productId; })) monitoringPickerSelected.delete(productId);
  });
  const allSelected = selectable.length > 0 && selectable.every(function (product) { return monitoringPickerSelected.has(product.id); });
  const selectAll = $('#monitoringProductSelectAll');
  if (selectAll) {
    selectAll.checked = allSelected;
    selectAll.disabled = selectable.length === 0;
  }
  setText('#monitoringProductPickerHint', products.length
    ? '已选择 ' + monitoringPickerSelected.size + ' 个商品；加入后可在竞品监控里录入快照和销量。'
    : '没有匹配的可用本店商品。');
  const confirm = $('#confirmAddOwnMonitoring');
  if (confirm) confirm.disabled = monitoringPickerSelected.size === 0;
  container.innerHTML = products.map(function (product) {
    const monitored = Boolean(product.monitoringEnabled);
    const checked = monitoringPickerSelected.has(product.id);
    const image = safeImageUrl(product.image);
    return '<label class="monitoring-product-picker-item' + (monitored ? ' monitored' : '') + '">' +
      '<input type="checkbox" data-monitoring-product-id="' + escapeHtml(product.id) + '"' + (checked ? ' checked' : '') + (monitored ? ' disabled' : '') + ' />' +
      '<span class="monitoring-product-picker-image">' + (image ? '<img src="' + escapeHtml(image) + '" alt="" />' : '暂无图') + '</span>' +
      '<span class="monitoring-product-picker-copy"><strong>' + escapeHtml(product.name) + '</strong><small>' + escapeHtml([product.sku, product.seller, product.market].filter(Boolean).join(' · ') || '本店商品') + '</small></span>' +
      '<em>' + (monitored ? '已在监控' : '可加入') + '</em></label>';
  }).join('') || '<div class="monitoring-picker-empty">没有找到可加入监控的本店商品。</div>';
}
function openOwnProductMonitoringPicker() {
  monitoringPickerTerm = '';
  monitoringPickerSelected = new Set();
  const search = $('#monitoringProductSearch');
  if (search) search.value = '';
  renderMonitoringProductPicker();
  openModal('competitorOwnProductModal');
}
async function submitOwnProductsToMonitoring() {
  const selected = Array.from(monitoringPickerSelected);
  if (!selected.length) return showToast('请至少选择一个本店商品。');
  if (TEAM_MODE) {
    const applied = await executeTeamCommand(function () { return teamGateway.addOwnProductsToMonitoring(selected); }, '已将选中的本店商品加入竞品监控。', 'catalog');
    if (applied) closeModal('competitorOwnProductModal');
    return;
  }
  commit(function (next) {
    selected.forEach(function (productId) {
      const product = productById(productId, next);
      if (product && product.kind === 'own') product.monitoringEnabled = true;
    });
  }, '已将选中的本店商品加入竞品监控。');
  closeModal('competitorOwnProductModal');
}
function renderCompetitorProducts() {
  const products = monitoredProducts(state).filter(function (product) { return searchMatches(product); });
  $('#competitorRows').innerHTML = products.map(function (product) {
    const change = snapshotChange(product.id);
    const latest = change.pair.latest;
    const salesClass = change.sales == null ? 'neutral' : (change.sales >= 0 ? 'up' : 'down');
    const isOwnProduct = product.kind === 'own';
    const actions = (teamCapabilityAllowed('competitor') ? rowButton('add-snapshot', product.id, '更新销量', 'primary') : '') +
      (product.productUrl ? '<a class="row-action" href="' + escapeHtml(product.productUrl) + '" target="_blank" rel="noopener">打开链接</a>' : '') +
      (teamCapabilityAllowed('catalog') ? rowButton('edit-product', product.id, '编辑') : '') +
      (teamCapabilityAllowed('catalog') ? rowButton(isOwnProduct ? 'remove-own-monitoring' : 'delete-competitor', product.id, isOwnProduct ? '移出监控' : '删除', 'danger') : '');
    return '<tr><td>' + productMedia(product) + '</td><td><span class="type-pill ' + product.kind + '">' + KIND_LABELS[product.kind] + '</span></td>' +
      '<td>' + (latest ? formatDate(latest.at, true) : '未记录') + '</td><td>' + (latest ? money(latest.price, latest.currency) : '—') + '</td>' +
      '<td>' + (latest ? latest.sold.toLocaleString('zh-CN') : '—') + '</td><td><span class="delta-pill ' + salesClass + '">' + (change.sales == null ? '—' : (change.sales > 0 ? '+' : '') + change.sales) + '</span></td>' +
      '<td>' + (latest ? (latest.rating == null ? '—' : latest.rating.toFixed(1)) + ' / ' + latest.reviews : '—') + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#competitorEmpty', products.length === 0);
}

function renderHistory() {
  const productId = $('#historyProduct') ? $('#historyProduct').value : state.selectedProductId;
  const snapshots = productSnapshots(productId).slice().reverse();
  $('#historyRows').innerHTML = snapshots.map(function (item, index) {
    const older = snapshots[index + 1];
    const sales = older ? item.sold - older.sold : null;
    const product = productById(item.productId);
    return '<tr><td>' + formatDate(item.at, true) + '</td><td>' + escapeHtml(product ? product.name : '未知商品') + '</td><td>' + money(item.price, item.currency) + '</td>' +
      '<td>' + item.sold.toLocaleString('zh-CN') + '</td><td><span class="delta-pill ' + (sales == null ? 'neutral' : (sales >= 0 ? 'up' : 'down')) + '">' + (sales == null ? '基准' : (sales > 0 ? '+' : '') + sales) + '</span></td>' +
      '<td>' + (item.rating == null ? '—' : item.rating.toFixed(1)) + '</td><td>' + item.reviews + '</td><td><div class="row-actions">' + (teamCapabilityAllowed('competitor') ? rowButton('delete-snapshot', item.id, '删除', 'danger') : '') + '</div></td></tr>';
  }).join('');
  toggleEmpty('#historyEmpty', snapshots.length === 0);
}

function buildAlerts() {
  const alerts = [];
  monitoredProducts(state).forEach(function (product) {
    const change = snapshotChange(product.id);
    const latest = change.pair.latest;
    if (!latest) {
      alerts.push({ type: 'info', product: product, title: '尚未建立基准快照', detail: '录入第一条公开数据后开始监控变化。', at: '' });
      return;
    }
    if (ageInDays(latest.at) > 3) alerts.push({ type: 'warning', product: product, title: '超过 3 天未更新', detail: '最近快照：' + formatDate(latest.at, true), at: latest.at });
    if (change.sales != null && change.sales < 0) alerts.push({ type: 'danger', product: product, title: '累计销量出现回退', detail: '较上次减少 ' + Math.abs(change.sales) + '，建议核对口径或商品链接。', at: latest.at });
    if (change.price != null && change.pair.previous && change.pair.previous.price > 0) {
      const rate = change.price / change.pair.previous.price;
      if (Math.abs(rate) >= 0.05) alerts.push({
        type: rate < 0 ? 'danger' : 'info', product: product,
        title: rate < 0 ? '竞品降价提醒' : '价格上涨提醒',
        detail: '价格较上次' + (rate < 0 ? '下降 ' : '上涨 ') + Math.abs(rate * 100).toFixed(1) + '%。', at: latest.at
      });
    }
    if (latest.reviews > 0 && latest.lowReviews / latest.reviews >= 0.1) {
      alerts.push({ type: 'warning', product: product, title: '低星评价占比较高', detail: '1–2 星评价占 ' + (latest.lowReviews / latest.reviews * 100).toFixed(1) + '%。', at: latest.at });
    }
  });
  return alerts;
}
function renderAlerts() {
  const alerts = buildAlerts();
  setText('#navAlertCount', alerts.length);
  setText('#competitorAlertCount', alerts.length);
  setText('#alertMetric', alerts.length);
  setText('#alertMetricFoot', alerts.length ? '查看变化提醒中的异常项' : '暂无异常变化');
  $('#changeList').innerHTML = alerts.length ? alerts.map(function (alert) {
    const icon = alert.type === 'danger' ? '!' : (alert.type === 'info' ? 'i' : '↗');
    return '<article class="alert-card"><div class="alert-icon ' + (alert.type === 'danger' ? 'danger' : (alert.type === 'info' ? 'info' : '')) + '">' + icon + '</div>' +
      '<div class="alert-copy"><strong>' + escapeHtml(alert.title) + '</strong><span>' + escapeHtml(alert.product.name + ' · ' + alert.detail) + '</span><small>' + (alert.at ? formatDate(alert.at, true) : '等待首次录入') + '</small></div></article>';
  }).join('') : '<div class="alert-empty">✓ 当前没有需要处理的变化提醒</div>';
}

function analyticsFilters() {
  const days = $('#analyticsDays') ? $('#analyticsDays').value : '30';
  return {
    days: days === 'custom' ? '' : days,
    date_from: days === 'custom' && $('#analyticsDateFrom') ? $('#analyticsDateFrom').value : '',
    date_to: days === 'custom' && $('#analyticsDateTo') ? $('#analyticsDateTo').value : '',
    store: $('#analyticsStoreFilter') ? $('#analyticsStoreFilter').value : '',
    warehouse: $('#analyticsWarehouseFilter') ? $('#analyticsWarehouseFilter').value : '',
    search: $('#analyticsSkuSearch') ? $('#analyticsSkuSearch').value.trim() : ''
  };
}

function analyticsPayloadRows(payload, keys) {
  if (Array.isArray(payload)) return payload;
  for (const key of keys) if (payload && Array.isArray(payload[key])) return payload[key];
  return payload && Array.isArray(payload.results) ? payload.results : [];
}

function analyticsMetric(payload, keys) {
  const roots = [payload, payload && payload.summary, payload && payload.metrics].filter(Boolean);
  for (const root of roots) for (const key of keys) if (root[key] != null) return root[key];
  return null;
}

function analyticsMeta(payload) {
  if (!payload) return '';
  const period = payload.period || {};
  const interval = [payload.date_from || payload.start_date || period.start, payload.date_to || payload.end_date || period.end].filter(Boolean).join(' 至 ');
  const sources = Array.isArray(payload.data_sources) ? payload.data_sources.join('、') : (Array.isArray(payload.sources) ? payload.sources.join('、') : (payload.data_source || 'ERP 真实数据'));
  return [interval, (payload.timezone || period.timezone) ? '报表时区 ' + (payload.timezone || period.timezone) : '', '来源：' + sources, payload.generated_at ? '生成于 ' + formatDate(payload.generated_at, true) : ''].filter(Boolean).join(' · ');
}

function analyticsMoney(value, currency) {
  return value == null || value === '' ? '暂无数据' : money(value, currency || 'MYR');
}

async function loadAnalyticsTab(tab, force) {
  if (!TEAM_MODE || !teamGateway || !['overview', 'stores', 'skus'].includes(tab)) return;
  if (!teamCapabilityAllowed('analytics')) {
    analyticsState.error[tab] = '当前账号没有数据分析查看权限。';
    analyticsState.loaded[tab] = true;
    return renderAnalytics();
  }
  if (analyticsState.loading || (!force && analyticsState.loaded[tab])) return;
  analyticsState.loading = tab;
  analyticsState.error[tab] = '';
  renderAnalytics();
  try {
    const filters = analyticsFilters();
    const payload = tab === 'overview' ? await teamGateway.getAnalyticsOverview(filters)
      : (tab === 'stores' ? await teamGateway.getAnalyticsStores(filters) : await teamGateway.getAnalyticsSkus(filters));
    analyticsState[tab] = payload;
    analyticsState.loaded[tab] = true;
  } catch (error) {
    analyticsState.error[tab] = error && error.message || '统计读取失败，请重试。';
    handleTeamError(error);
  } finally {
    analyticsState.loading = '';
    renderAnalytics();
  }
}

function renderAnalyticsOverview() {
  const payload = analyticsState.overview;
  const error = analyticsState.error.overview;
  const fields = [
    ['订单数', ['order_count', 'orders']], ['销售件数', ['sales_units', 'units_sold', 'unit_count']],
    ['已出库', ['shipped_units', 'shipped_count']], ['库存不足', ['shortage_order_count', 'shortage_count', 'shortage_orders']],
    ['已取消', ['cancelled_order_count', 'cancelled_count', 'cancelled_orders']], ['期间退货', ['return_units_period_occurrence', 'return_units', 'returns']],
    ['GMV', ['gmv']], ['实际利润', ['profit', 'actual_profit']]
  ];
  $('#analyticsOverviewMetrics').innerHTML = fields.map(function (field, index) {
    const value = analyticsMetric(payload, field[1]);
    const amount = ['GMV', '实际利润'].includes(field[0]);
    return '<article class="metric-card accent-' + ['teal', 'blue', 'amber', 'red'][index % 4] + '"><span>' + field[0] + '</span><strong>' + escapeHtml(amount ? analyticsMoney(value, payload && payload.currency) : (value == null ? '0' : value)) + '</strong><small>' + (amount && value == null ? '没有权威金额来源' : '按当前筛选统计') + '</small></article>';
  }).join('');
  const top = analyticsPayloadRows(payload, ['top_skus', 'top_products']);
  $('#analyticsTopSkus').innerHTML = top.length ? top.map(function (row) {
    return '<article><strong>' + escapeHtml(row.sku_code || row.sku || row.name || 'SKU') + '</strong><span>已出库 ' + nonNegative(row.shipped_units == null ? (row.sales_units == null ? row.units : row.sales_units) : row.shipped_units) + ' 件</span></article>';
  }).join('') : '<p>' + (analyticsState.loading === 'overview' ? '正在读取…' : '暂无热销 SKU。') + '</p>';
  const risks = analyticsPayloadRows(payload, ['inventory_risks', 'risks']).concat(analyticsPayloadRows(payload, ['anomalies', 'recent_anomalies', 'recent_exceptions']));
  if (payload && payload.current_snapshot && Number(payload.current_snapshot.stock_risk_sku_count) > 0) risks.unshift({ title: '库存风险 SKU', detail: payload.current_snapshot.stock_risk_sku_count + ' 个 SKU 当前可用库存不足' });
  $('#analyticsRisks').innerHTML = risks.length ? risks.slice(0, 12).map(function (row) {
    return '<article><strong>' + escapeHtml(row.title || row.sku_code || row.sku || '库存提示') + '</strong><span>' + escapeHtml(row.detail || row.message || row.status || '') + '</span></article>';
  }).join('') : '<p>暂无库存风险或近期异常。</p>';
  $('#analyticsOverviewMeta').textContent = error || analyticsMeta(payload) || (analyticsState.loading === 'overview' ? '正在读取经营统计…' : '尚未读取统计。');
  toggleEmpty('#analyticsOverviewEmpty', Boolean(error));
}

function renderAnalyticsStores() {
  const payload = analyticsState.stores;
  const rows = analyticsPayloadRows(payload, ['stores', 'items']);
  $('#analyticsStoreCards').innerHTML = rows.map(function (row) {
    const storeName = row.store_name || row.name || '未关联店铺';
    const topSkus = Array.isArray(row.top_skus) ? row.top_skus.map(function (sku) { return sku.sku_code || sku.sku || sku.name; }).filter(Boolean).slice(0, 3).join('、') : '暂无';
    return '<article class="analytics-store-card"><header><strong>' + escapeHtml(storeName) + '</strong><span>' + escapeHtml(row.platform || row.platform_code || 'ERP') + '</span></header><dl>' +
      '<div><dt>订单 / 件数</dt><dd>' + nonNegative(row.order_count) + ' / ' + nonNegative(row.sales_units || row.unit_count) + '</dd></div>' +
      '<div><dt>已出库 / 缺货</dt><dd>' + nonNegative(row.shipped_count || row.shipped_units) + ' / ' + nonNegative(row.shortage_order_count || row.shortage_count) + '</dd></div>' +
      '<div><dt>取消 / 退货</dt><dd>' + nonNegative(row.cancelled_order_count || row.cancelled_count) + ' / ' + nonNegative(row.return_units || row.return_count) + '</dd></div>' +
      '<div><dt>GMV / 利润</dt><dd>' + analyticsMoney(row.gmv, row.currency) + ' / ' + analyticsMoney(row.profit || row.actual_profit, row.currency) + '</dd></div>' +
      '</dl><p>热销 SKU：' + escapeHtml(topSkus) + '</p><small>' + escapeHtml(row.data_source || 'ERP 真实数据') + '</small></article>';
  }).join('');
  $('#analyticsStoresMeta').textContent = analyticsState.error.stores || analyticsMeta(payload) || (analyticsState.loading === 'stores' ? '正在读取店铺分析…' : '');
  toggleEmpty('#analyticsStoresEmpty', rows.length === 0 && analyticsState.loading !== 'stores');
}

function renderAnalyticsSkus() {
  const payload = analyticsState.skus;
  const rows = analyticsPayloadRows(payload, ['skus', 'items']);
  $('#analyticsSkuRows').innerHTML = rows.map(function (row) {
    const skuId = String(row.sku_id || row.sku || row.id || '');
    const product = state.products.find(function (item) { return String(item.skuId) === skuId || String(item.sku) === String(row.sku_code || row.sku); });
    const productCell = product ? productMedia(product) : '<div class="product-copy"><strong>' + escapeHtml(row.product_name || row.name || '未命名商品') + '</strong><span>' + escapeHtml(row.sku_code || row.sku || 'SKU') + '</span></div>';
    const salesUnits = row.sales_units == null ? nonNegative(row.net_sales) : nonNegative(row.sales_units);
    return '<tr><td>' + productCell + '</td><td>' + salesUnits + '</td><td>' + nonNegative(row.order_outbound_quantity || row.order_outbound) + ' / ' + nonNegative(row.manual_sales_outbound_quantity || row.manual_outbound) + '</td><td>' + nonNegative(row.return_quantity || row.returns_at_original_sale_date || row.returns) + ' / ' + nonNegative(row.net_sales || row.net_sales_outbound_quantity) + '</td><td>' + nonNegative(row.on_hand) + ' / ' + nonNegative(row.reserved) + ' / ' + nonNegative(row.available) + '</td><td>' + nonNegative(row.in_transit || row.inbound_total) + '</td><td>' + Number(row.daily_average || row.velocity || 0).toFixed(2) + ' / ' + ((row.days_cover == null && row.days_of_cover == null) ? '—' : Number(row.days_cover == null ? row.days_of_cover : row.days_cover).toFixed(1) + ' 天') + '</td><td>' + escapeHtml(row.replenishment_status || row.status || '—') + '</td><td><div class="row-actions"><button class="row-action" data-action="analytics-open-inventory" data-id="' + escapeHtml(skuId) + '">库存</button><button class="row-action" data-action="analytics-open-replenishment" data-id="' + escapeHtml(skuId) + '">补货</button><button class="row-action" data-action="analytics-open-profit-plan" data-id="' + escapeHtml(skuId) + '">利润表</button></div></td></tr>';
  }).join('');
  $('#analyticsSkusMeta').textContent = analyticsState.error.skus || analyticsMeta(payload) || (analyticsState.loading === 'skus' ? '正在读取 SKU 分析…' : '');
  toggleEmpty('#analyticsSkusEmpty', rows.length === 0 && analyticsState.loading !== 'skus');
}

function renderAnalytics() {
  const module = $('#module-analytics');
  if (!module) return;
  const competitorActions = module.querySelector('.page-heading .page-actions');
  if (competitorActions) competitorActions.hidden = !['products', 'snapshots', 'trends', 'alerts'].includes(state.ui.competitorTab);
  renderAnalyticsOverview();
  renderAnalyticsStores();
  renderAnalyticsSkus();
  if (state.ui.module === 'analytics' && ['overview', 'stores', 'skus'].includes(state.ui.competitorTab) && !analyticsState.loaded[state.ui.competitorTab] && !analyticsState.loading) {
    setTimeout(function () { loadAnalyticsTab(state.ui.competitorTab); }, 0);
  }
}

function renderTrendMetrics() {
  const monitored = monitoredProducts(state);
  let product = productById(state.selectedProductId);
  if (!product || !monitored.some(function (item) { return item.id === product.id; })) {
    product = monitored[0];
    state.selectedProductId = product ? product.id : '';
  }
  if (!product) {
    setText('#heroSummary', '添加竞品并录入快照后查看趋势。');
    setText('#salesMetric', '—');
    setText('#salesMetricFoot', '需要至少两次快照');
    setText('#priceMetric', '—');
    setText('#priceMetricFoot', '等待可比较数据');
    setText('#rankMetric', '—');
    setText('#rankMetricFoot', '需要可比较的数据');
    return;
  }
  const change = snapshotChange(product.id);
  const latest = change.pair.latest;
  setText('#heroSummary', product.name + ' · ' + (latest ? '最近更新 ' + formatDate(latest.at, true) : '等待首次快照'));
  setText('#salesMetric', change.sales == null ? '—' : (change.sales > 0 ? '+' : '') + change.sales);
  setText('#salesMetricFoot', change.sales == null ? '需要至少两次快照' : (change.sales < 0 ? '累计值回退，请核对数据' : '相邻两次快照的增量'));
  setText('#priceMetric', latest ? money(latest.price, latest.currency) : '—');
  setText('#priceMetricFoot', change.price == null ? '等待可比较数据' : '较上次 ' + (change.price > 0 ? '+' : '') + money(change.price, latest.currency));
  const comparable = monitored.map(function (item) {
    return { id: item.id, sales: snapshotChange(item.id).sales };
  }).filter(function (item) { return item.sales != null; }).sort(function (a, b) { return b.sales - a.sales; });
  const rank = comparable.findIndex(function (item) { return item.id === product.id; });
  setText('#rankMetric', rank >= 0 ? (rank + 1) + ' / ' + comparable.length : '—');
  setText('#rankMetricFoot', rank >= 0 ? '按相邻快照新增销量排序' : '需要可比较的数据');
}

function renderSelects() {
  const warehouseProducts = ownProducts(state).filter(function (product) { return !product.needsReview; });
  const monitoring = monitoredProducts(state);
  const productOptions = warehouseProducts.map(function (product) {
    return '<option value="' + escapeHtml(product.id) + '">' + escapeHtml((product.sku || '无 SKU') + ' · ' + product.name) + '</option>';
  }).join('');
  ['#stockProduct', '#transferLineProduct'].forEach(function (selector) {
    const select = $(selector);
    if (!select) return;
    const previous = select.value;
    select.innerHTML = productOptions || '<option value="">请先完善本店 SKU</option>';
    if (warehouseProducts.some(function (item) { return item.id === previous; })) select.value = previous;
  });
  const transferDestination = $('#transferDestination');
  if (transferDestination) {
    const sourceId = TEAM_MODE && teamGateway ? String(teamGateway.warehouseId || '') : currentWarehouseId();
    const previous = transferDestination.value;
    const candidates = activeWarehouses().filter(function (warehouse) { return String(warehouse.id) !== String(sourceId) && warehouse.canReceive !== false && warehouse.can_receive !== false; });
    transferDestination.innerHTML = candidates.map(function (warehouse) { return '<option value="' + escapeHtml(String(warehouse.id)) + '">' + escapeHtml((warehouse.code || '') + ' · ' + warehouse.name) + '</option>'; }).join('') || '<option value="">请先创建另一个可收货仓</option>';
    if (candidates.some(function (warehouse) { return String(warehouse.id) === String(previous); })) transferDestination.value = previous;
  }
  const movement = $('#movementProduct');
  if (movement) {
    const previous = movement.value || 'all';
    movement.innerHTML = '<option value="all">全部 SKU</option>' + ownProducts(state, true).map(function (product) {
      return '<option value="' + escapeHtml(product.id) + '">' + escapeHtml((product.sku || '无 SKU') + ' · ' + product.name) + '</option>';
    }).join('');
    movement.value = ownProducts(state, true).some(function (item) { return item.id === previous; }) ? previous : 'all';
  }
  const monitorOptions = monitoring.map(function (product) {
    return '<option value="' + escapeHtml(product.id) + '">' + escapeHtml(product.name) + '</option>';
  }).join('');
  ['#historyProduct', '#activeProduct', '#snapshotProduct'].forEach(function (selector) {
    const select = $(selector);
    if (!select) return;
    const previous = select.value || state.selectedProductId;
    select.innerHTML = monitorOptions || '<option value="">暂无监控商品</option>';
    const chosen = monitoring.some(function (item) { return item.id === previous; }) ? previous : (monitoring[0] ? monitoring[0].id : '');
    select.value = chosen;
  });
}

function renderChart() {
  const canvas = $('#trendChart');
  const empty = $('#chartEmpty');
  const legend = $('#chartLegend');
  if (!canvas || !empty || !legend) return;
  const series = monitoredProducts(state).map(function (product, index) {
    const snapshots = productSnapshots(product.id);
    let points = snapshots.map(function (item, pointIndex) {
      let value = 0;
      if (chartMetric === 'price') value = item.price;
      else if (chartMetric === 'reviews') value = item.reviews;
      else value = pointIndex === 0 ? 0 : Math.max(0, item.sold - snapshots[pointIndex - 1].sold);
      return { value: value, at: item.at };
    });
    return { product: product, points: points, color: COLORS[index % COLORS.length] };
  }).filter(function (entry) { return entry.points.length >= 2; });
  const visible = series.length > 0;
  empty.style.display = visible ? 'none' : 'grid';
  canvas.style.display = visible ? 'block' : 'none';
  legend.innerHTML = series.map(function (entry) {
    return '<span><i style="background:' + entry.color + '"></i>' + escapeHtml(entry.product.name) + '</span>';
  }).join('');
  setText('#chartSubtitle', chartMetric === 'sales' ? '相邻快照的新增销量' : (chartMetric === 'price' ? '公开价格变化' : '评价总数变化'));
  if (!visible || state.ui.module !== 'analytics' || state.ui.competitorTab !== 'trends') return;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(560, rect.width || 900);
  const height = 330;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  const pad = { left: 48, right: 22, top: 22, bottom: 35 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const values = series.flatMap(function (entry) { return entry.points.map(function (point) { return point.value; }); });
  const maxValue = Math.max.apply(null, values.concat([1]));
  ctx.strokeStyle = '#e3ebe9';
  ctx.fillStyle = '#7f8f91';
  ctx.font = '10px system-ui';
  ctx.textAlign = 'right';
  for (let step = 0; step <= 4; step += 1) {
    const y = pad.top + innerH * step / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(Math.round(maxValue * (1 - step / 4)).toLocaleString('zh-CN'), pad.left - 8, y + 3);
  }
  series.forEach(function (entry) {
    ctx.strokeStyle = entry.color;
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    entry.points.forEach(function (point, index) {
      const x = pad.left + innerW * index / Math.max(1, entry.points.length - 1);
      const y = pad.top + innerH * (1 - point.value / maxValue);
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    entry.points.forEach(function (point, index) {
      const x = pad.left + innerW * index / Math.max(1, entry.points.length - 1);
      const y = pad.top + innerH * (1 - point.value / maxValue);
      ctx.fillStyle = '#fff'; ctx.strokeStyle = entry.color; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    });
  });
}

const SELECTION_REGION_LABELS = {
  MY: '马来西亚 MY', ID: '印度尼西亚 ID', VN: '越南 VN', TH: '泰国 TH', PH: '菲律宾 PH',
  SG: '新加坡 SG', US: '美国 US', BR: '巴西 BR', MX: '墨西哥 MX', GB: '英国 GB', ES: '西班牙 ES',
  FR: '法国 FR', DE: '德国 DE', IT: '意大利 IT', JP: '日本 JP', CA: '加拿大 CA'
};

function selectionNumber(value, digits) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return parsed.toLocaleString('zh-CN', { maximumFractionDigits: digits == null ? 0 : digits });
}

function selectionField(source, direct, nested, nestedField) {
  if (source && source[direct] != null) return source[direct];
  if (source && source[nested] && source[nested][nestedField] != null) return source[nested][nestedField];
  return null;
}

function selectionRange(value) {
  if (value == null || value === '') return '—';
  if (Array.isArray(value)) return value.filter(function (item) { return item != null; }).join(' – ') || '—';
  if (typeof value === 'object') {
    const minimum = value.min != null ? value.min : (value.minimum != null ? value.minimum : value.low);
    const maximum = value.max != null ? value.max : (value.maximum != null ? value.maximum : value.high);
    if (minimum != null && maximum != null) return minimum + ' – ' + maximum;
    return Object.values(value).filter(function (item) { return item != null && typeof item !== 'object'; }).join(' – ') || '—';
  }
  return String(value);
}

function renderSelectionRegions() {
  const platform = $('#selectionPlatform').value;
  const regions = selectionState.platformRegions[platform] || [];
  const previous = $('#selectionRegion').value;
  $('#selectionRegion').innerHTML = regions.map(function (region) {
    return '<option value="' + escapeHtml(region) + '">' + escapeHtml(SELECTION_REGION_LABELS[region] || region) + '</option>';
  }).join('');
  $('#selectionRegion').value = regions.includes(previous) ? previous : (regions.includes('MY') ? 'MY' : (regions[0] || ''));
}

function renderSelectionStatus() {
  const node = $('#selectionApiState');
  if (!node) return;
  node.classList.toggle('ready', selectionState.configured);
  node.classList.toggle('error', selectionState.statusLoaded && !selectionState.configured);
  if (!TEAM_MODE) node.innerHTML = '<i></i><div><strong>仅团队服务器可用</strong><span>本机模式不会暴露或保存 API 密钥</span></div>';
  else if (!teamAuthenticated()) node.innerHTML = '<i></i><div><strong>请先登录</strong><span>登录后检查服务器接口配置</span></div>';
  else if (selectionState.loadingStatus) node.innerHTML = '<i></i><div><strong>正在检查接口</strong><span>密钥只保存在服务器</span></div>';
  else if (selectionState.configured) node.innerHTML = '<i></i><div><strong>选品接口已保存</strong><span>' + (selectionState.source === 'system' ? '主账号系统配置 · 密钥已加密保存；请在配置页测试连接' : '服务端鉴权 · 前端不保存密钥') + '</span></div>';
  else node.innerHTML = '<i></i><div><strong>服务器尚未配置密钥</strong><span>主账号可点击“配置选品接口”完成加密保存</span></div>';
}

async function loadProductSelectionStatus() {
  if (!TEAM_MODE || !teamGateway || !teamAuthenticated() || selectionState.loadingStatus || selectionState.statusLoaded) return;
  selectionState.loadingStatus = true;
  renderSelectionStatus();
  try {
    const payload = await teamGateway.productSelectionStatus();
    selectionState.configured = Boolean(payload && payload.configured);
    selectionState.source = (payload && payload.source) || 'none';
    selectionState.platformRegions = payload && payload.platform_regions ? payload.platform_regions : selectionState.platformRegions;
    selectionState.statusLoaded = true;
    renderSelectionRegions();
  } catch (error) {
    selectionState.statusLoaded = true;
    selectionState.configured = false;
    handleTeamError(error);
  } finally {
    selectionState.loadingStatus = false;
    renderSelectionStatus();
  }
}

function renderSelectionKeywords() {
  const results = $('#selectionKeywordResults');
  const empty = $('#selectionKeywordEmpty');
  if (!results || !empty) return;
  results.innerHTML = selectionState.keywords.map(function (item, index) {
    const keyword = String(item.keyword || item.keywordEn || '');
    const keywordCn = String(item.keywordCn || item.keywordCN || '');
    const score = selectionField(item, 'oppScore', 'opportunityInfo', 'score');
    const sold = selectionField(item, 'soldCnt30d', 'salesInfo', 'soldCnt30d');
    const amount = selectionField(item, 'soldAmt30d', 'salesInfo', 'soldAmt30d');
    const rank = selectionField(item, 'searchRank', 'demandInfo', 'searchRank');
    const description = item.oppScoreDesc || item.description || (keywordCn && keywordCn !== keyword ? keywordCn : '候选机会关键词');
    return '<article class="selection-keyword-card ' + (selectionState.selectedKeyword === keyword ? 'selected' : '') + '">' +
      '<div class="selection-keyword-head"><strong title="' + escapeHtml(keyword) + '">' + escapeHtml(keyword || keywordCn || '未命名关键词') + '</strong><span>机会 ' + escapeHtml(selectionNumber(score, 1)) + '</span></div>' +
      '<p>' + escapeHtml(description) + '</p><div class="selection-keyword-metrics">' +
      '<span><b>' + escapeHtml(selectionNumber(rank)) + '</b>搜索排名</span>' +
      '<span><b>' + escapeHtml(selectionNumber(sold)) + '</b>30 天销量</span>' +
      '<span><b>' + escapeHtml(selectionNumber(amount, 2)) + '</b>30 天销售额</span></div>' +
      '<button class="button tiny ' + (selectionState.selectedKeyword === keyword ? 'primary' : 'secondary') + '" type="button" data-selection-keyword-index="' + index + '">' + (selectionState.selectedKeyword === keyword ? '已选择' : '选择这个词') + '</button></article>';
  }).join('');
  empty.classList.toggle('show', !selectionState.loadingKeywords && !selectionState.keywords.length);
  $('#selectionKeywordLoading').hidden = !selectionState.loadingKeywords;
}

function selectionSummaryHtml(summary) {
  if (!summary || !Object.keys(summary).length) return '';
  const info = summary.keywordIndexesInfo || summary.keywordIndexInfo || summary;
  const level = summary.keywordLevelDetail || {};
  const sales = info.salesInfo || {};
  const supply = info.supplyInfo || {};
  const profit = info.profitInfo || {};
  const score = info.oppScore != null ? info.oppScore : summary.oppScore;
  const summaryText = summary.summary || level.text || level.valueLevelDesc || '已生成关键词市场机会分析。';
  return '<section class="selection-market-summary"><div class="selection-summary-head"><div><h3>' +
    escapeHtml(info.keyword || selectionState.selectedKeyword || '关键词机会') + '</h3><p>' + escapeHtml(summaryText) + '</p></div>' +
    '<div class="selection-summary-score"><strong>' + escapeHtml(selectionNumber(score, 1)) + '</strong><span>' + escapeHtml(level.valueLevelDesc || level.valueLevel || '机会评分') + '</span></div></div>' +
    '<div class="selection-summary-metrics">' +
    '<div><span>30 天销量</span><strong>' + escapeHtml(selectionNumber(sales.soldCnt30d || info.soldCnt30d)) + '</strong></div>' +
    '<div><span>30 天销售额</span><strong>' + escapeHtml(selectionNumber(sales.soldAmt30d || info.soldAmt30d, 2)) + '</strong></div>' +
    '<div><span>商品供给数</span><strong>' + escapeHtml(selectionNumber(supply.itemCount || info.itemCount)) + '</strong></div>' +
    '<div><span>平均评分</span><strong>' + escapeHtml(selectionNumber(supply.ratingAvg || info.ratingAvg, 2)) + '</strong></div>' +
    '<div><span>平均价格</span><strong>' + escapeHtml(selectionNumber(profit.priceAvg || info.priceAvg, 2)) + '</strong></div></div></section>';
}

function renderSelectionReport() {
  const report = selectionState.report;
  $('#selectionReportLoading').hidden = !selectionState.loadingReport;
  $('#selectionSummary').innerHTML = report ? selectionSummaryHtml(report.keyword_summary || {}) + selectionAIAnalysisHtml(report.ai_analysis) : '';
  const products = report && Array.isArray(report.products) ? report.products : [];
  $('#selectionProducts').innerHTML = products.map(function (product, index) {
    const image = safeImageUrl(product.mainImgUrl || product.imageUrl || product.image || '');
    const title = product.title || product.productName || '未命名商品';
    const url = validUrl(product.productUrl) ? product.productUrl : '';
    const sold = product.soldCnt30d != null ? product.soldCnt30d : product.salesVolume30d;
    const rating = product.ratingRange != null ? selectionRange(product.ratingRange) : selectionNumber(product.rating, 2);
    const price = selectionRange(product.priceRange != null ? product.priceRange : product.price);
    const days = product.onShelfDays != null ? product.onShelfDays : '—';
    return '<article class="selection-product-card"><div class="selection-product-image">' +
      (image ? '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(title) + '" loading="lazy" onerror="this.hidden=true">' : '') +
      '<span>上架 ' + escapeHtml(String(days)) + ' 天</span></div><div class="selection-product-body"><h3 title="' + escapeHtml(title) + '">' + escapeHtml(title) + '</h3>' +
      '<div class="selection-product-meta"><span><b>' + escapeHtml(price) + '</b>价格</span><span><b>' + escapeHtml(selectionNumber(sold)) + '</b>30 天销量</span><span><b>' + escapeHtml(rating) + '</b>评分 · ' + escapeHtml(selectionNumber(product.reviewCnt)) + ' 评</span></div>' +
      '<div class="selection-product-actions"><button class="button tiny primary" type="button" data-selection-import-index="' + index + '">加入竞品库</button>' +
      (url ? '<a class="button tiny secondary" href="' + escapeHtml(url) + '" target="_blank" rel="noopener">打开商品</a>' : '<button class="button tiny secondary" disabled>无商品链接</button>') + '</div></div></article>';
  }).join('');
  $('#selectionProductEmpty').classList.toggle('show', !selectionState.loadingReport && !products.length);
}

function renderSelection() {
  renderSelectionStatus();
  renderSelectionKeywords();
  renderSelectionReport();
  if (state.ui.module === 'selection') loadProductSelectionStatus();
}

function selectionBasePayload() {
  return {
    platform: $('#selectionPlatform').value,
    region: $('#selectionRegion').value,
    keyword: $('#selectionKeyword').value.trim(),
    listing_time: $('#selectionListingTime').value
  };
}

async function searchSelectionKeywords(event) {
  event.preventDefault();
  if (!TEAM_MODE) return showToast('智能选品只在团队服务器模式中调用，密钥不会保存到浏览器。');
  if (!teamAuthenticated()) return showToast('请先登录团队账号。');
  if (!teamGateway.can('selection')) return showToast('当前账号没有商品与选品权限。');
  if (!selectionState.configured) return showToast('服务器尚未配置选品 API 密钥。');
  const payload = selectionBasePayload();
  if (!payload.keyword) return showToast('请输入产品方向或关键词。');
  selectionState.loadingKeywords = true;
  selectionState.keywords = [];
  selectionState.selectedKeyword = '';
  selectionState.report = null;
  $('#selectionReportButton').disabled = true;
  renderSelectionKeywords();
  renderSelectionReport();
  try {
    const response = await teamGateway.searchProductSelectionKeywords(payload);
    selectionState.keywords = Array.isArray(response.keywords) ? response.keywords : [];
    selectionState.keywordResponseCached = Boolean(response.cached);
    showToast(selectionState.keywords.length ? ('找到 ' + selectionState.keywords.length + ' 个候选词' + (response.cached ? '（已使用缓存）' : '') + '。') : '没有找到候选词，请换一个更具体的产品方向。');
  } catch (error) {
    handleTeamError(error);
  } finally {
    selectionState.loadingKeywords = false;
    renderSelectionKeywords();
  }
}

function chooseSelectionKeyword(index) {
  const item = selectionState.keywords[index];
  if (!item) return;
  const keyword = String(item.keyword || item.keywordEn || '').trim();
  if (!keyword) return showToast('该候选词缺少可提交的英文关键词。');
  selectionState.selectedKeyword = keyword;
  selectionState.report = null;
  $('#selectionChosenKeyword').value = keyword;
  $('#selectionChosenHint').textContent = '已选择：' + keyword + (item.keywordCn ? '（' + item.keywordCn + '）' : '') + '。可继续设置筛选条件。';
  $('#selectionReportButton').disabled = false;
  renderSelectionKeywords();
  renderSelectionReport();
  scrollToPanel('selectionReportPanel');
}

function optionalSelectionValue(selector) {
  const value = $(selector).value;
  return value === '' ? null : Number(value);
}

async function generateSelectionReport() {
  const payload = selectionBasePayload();
  payload.keyword = selectionState.selectedKeyword;
  Object.assign(payload, {
    min_price: optionalSelectionValue('#selectionMinPrice'), max_price: optionalSelectionValue('#selectionMaxPrice'),
    min_volume: optionalSelectionValue('#selectionMinVolume'), max_volume: optionalSelectionValue('#selectionMaxVolume'),
    min_rating: optionalSelectionValue('#selectionMinRating'), max_rating: optionalSelectionValue('#selectionMaxRating')
  });
  selectionState.loadingReport = true;
  selectionState.report = null;
  $('#selectionReportButton').disabled = true;
  renderSelectionReport();
  try {
    const response = await teamGateway.generateProductSelectionReport(payload);
    selectionState.report = response;
    selectionState.reportCached = Boolean(response.cached);
    const count = Array.isArray(response.products) ? response.products.length : 0;
    showToast('报告已生成，共 ' + count + ' 个商品' + (response.cached ? '（已使用缓存）' : '') + '。');
  } catch (error) {
    handleTeamError(error);
  } finally {
    selectionState.loadingReport = false;
    $('#selectionReportButton').disabled = !selectionState.selectedKeyword;
    renderSelectionReport();
  }
}

function submitSelectionReport(event) {
  event.preventDefault();
  if (!TEAM_MODE || !teamAuthenticated()) return showToast('请先登录团队账号。');
  if (!teamGateway.can('selection')) return showToast('当前账号没有商品与选品权限。');
  if (!selectionState.selectedKeyword) return showToast('请先选择候选关键词。');
  askConfirm('确认调用选品报告？该操作可能消耗接口额度，相同条件会优先读取缓存。', generateSelectionReport);
}

function importSelectionProduct(index) {
  const product = selectionState.report && selectionState.report.products && selectionState.report.products[index];
  if (!product) return;
  openProductEditor('', 'direct');
  $('#productName').value = product.title || product.productName || '';
  $('#productMarket').value = $('#selectionRegion').value || 'MY';
  $('#productCurrency').value = $('#selectionRegion').value === 'MY' ? 'MYR' : 'USD';
  $('#productUrl').value = validUrl(product.productUrl) ? product.productUrl : '';
  pendingProductImage = safeImageUrl(product.mainImgUrl || product.imageUrl || product.image || '');
  $('#productImageUrl').value = exportableImageUrl(pendingProductImage);
  $('#firstSold').value = product.soldCnt30d == null ? '' : product.soldCnt30d;
  const rating = Number(product.rating);
  $('#firstRating').value = Number.isFinite(rating) ? rating : '';
  $('#firstReviews').value = product.reviewCnt == null ? '' : product.reviewCnt;
  updateProductImagePreview();
  showToast('已带入竞品资料，请核对后保存。');
}

function render() {
  renderNavigation();
  renderSidebar();
  renderProductSummary();
  renderProducts();
  renderStores();
  renderWarehouseSummary();
  renderWarehouseDirectory();
  renderPurchases();
  renderInventory();
  renderSelects();
  renderMovements();
  renderTransfers();
  renderReplenishment();
  renderOrders();
  renderCompetitorProducts();
  renderHistory();
  renderTrendMetrics();
  renderAlerts();
  renderAnalytics();
  renderCreators();
  renderProfitPlans();
  renderSelection();
  if (state.ui.module === 'analytics' && state.ui.competitorTab === 'trends') requestAnimationFrame(renderChart);
  requestAnimationFrame(updateReplenishmentStickyHeader);
  renderRuntimeState();
}

function updateProductImagePreview() {
  const preview = $('#productImagePreview');
  const empty = $('#productImageEmpty');
  const remove = $('#removeProductImage');
  const image = safeImageUrl(pendingProductImage || $('#productImageUrl').value);
  preview.hidden = !image;
  if (image) preview.src = image;
  empty.hidden = Boolean(image);
  remove.disabled = !image;
}
function toggleProductFields() {
  const own = $('#productKind').value === 'own';
  $$('.own-field').forEach(function (field) { field.hidden = !own; });
  $$('.competitor-field').forEach(function (field) { field.hidden = own; });
}
function skuDraft(item) {
  return {
    id: item && item.id ? String(item.id) : '',
    code: String(item && (item.code || item.sku) || '').trim(),
    cost: item && item.cost != null ? item.cost : (item && item.standardCost != null ? item.standardCost : ''),
    safetyStock: item && item.safety_stock != null ? item.safety_stock : (item && item.safetyStock != null ? item.safetyStock : 0),
    attributes: item && item.attributes ? item.attributes : {},
    categoryCode: item && item.category_code != null ? item.category_code : (item && item.categoryCode || ''),
    packedWeightG: item && item.packed_weight_g != null ? item.packed_weight_g : (item && item.packedWeightG != null ? item.packedWeightG : ''),
    purchaseCostCny: item && item.purchase_cost_cny != null ? item.purchase_cost_cny : (item && item.purchaseCostCny != null ? item.purchaseCostCny : ''),
    creatorCommission: item && item.default_creator_commission_percent != null ? item.default_creator_commission_percent : (item && item.defaultCreatorCommissionPercent != null ? item.defaultCreatorCommissionPercent : ''),
    active: !item || item.active !== false
  };
}
function editableSkuDrafts(product) {
  if (!product || product.kind !== 'own') return [];
  if (TEAM_MODE && teamGateway) {
    const raw = teamGateway.findRawProduct(product);
    if (raw && Array.isArray(raw.skus)) return raw.skus.map(skuDraft);
  }
  const catalogId = product.catalogProductId || product.id;
  const siblings = state.products.filter(function (item) {
    return item.kind === 'own' && (item.catalogProductId || item.id) === catalogId;
  });
  return (siblings.length ? siblings : [product]).map(skuDraft);
}
function renderProductSkuEditor() {
  const list = $('#productSkuList');
  if (!list) return;
  if ($('#productKind').value !== 'own') { list.innerHTML = ''; return; }
  list.innerHTML = draftProductSkus.length ? draftProductSkus.map(function (sku, index) {
    const categoryField = (state.profitCategories || []).length
      ? '<label>利润类目<select data-sku-field="categoryCode"><option value="">待完善</option>' + state.profitCategories.map(function (category) { return '<option value="' + escapeHtml(category.code) + '"' + (category.code === sku.categoryCode ? ' selected' : '') + '>' + escapeHtml((category.path || []).join(' / ')) + '</option>'; }).join('') + '</select></label>'
      : '<label>利润类目编码<input data-sku-field="categoryCode" value="' + escapeHtml(sku.categoryCode || '') + '" /></label>';
    return '<div class="sku-editor-row" data-product-sku-row data-sku-index="' + index + '">' +
      '<label>SKU 编码 <span>*</span><input data-sku-field="code" value="' + escapeHtml(sku.code) + '" placeholder="例如：DB-TOTE-PINK-M" /></label>' +
      '<label>采购成本 <span>*</span><input data-sku-field="cost" type="number" min="0.01" step="0.01" value="' + escapeHtml(sku.cost) + '" /></label>' +
      '<label>安全库存<input data-sku-field="safetyStock" type="number" min="0" step="1" value="' + escapeHtml(sku.safetyStock) + '" /></label>' +
      categoryField +
      '<label>包装后重量（g）<input data-sku-field="packedWeightG" type="number" min="0.01" max="30000" step="0.01" value="' + escapeHtml(sku.packedWeightG || '') + '" /></label>' +
      '<label>采购成本（CNY）<input data-sku-field="purchaseCostCny" type="number" min="0" step="0.01" value="' + escapeHtml(sku.purchaseCostCny || '') + '" /></label>' +
      '<label>默认达人佣金（%）<input data-sku-field="creatorCommission" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(sku.creatorCommission === 0 ? '0' : (sku.creatorCommission || '')) + '" /></label>' +
      '<label>规格（可选）<input data-sku-field="attributes" value="' + escapeHtml(Object.entries(sku.attributes || {}).map(function (entry) { return entry[0] + ':' + entry[1]; }).join('，')) + '" placeholder="颜色:粉色，尺寸:M" /></label>' +
      '<button class="button tiny ghost sku-remove" type="button" data-remove-product-sku="' + index + '"' + (draftProductSkus.length === 1 ? ' disabled' : '') + '>移除</button></div>';
  }).join('') : '<div class="sku-empty">请至少添加一条 SKU 明细。</div>';
  renderProductStoreEditor();
}
function readProductSkuDrafts() {
  return $$('[data-product-sku-row]').map(function (row) {
    const existing = draftProductSkus[Number(row.dataset.skuIndex)] || skuDraft();
    const attributes = {};
    String(row.querySelector('[data-sku-field="attributes"]').value || '').split(/[，,]/).forEach(function (entry) {
      const pair = entry.split(/[:：]/);
      if (pair.length > 1 && pair[0].trim() && pair.slice(1).join(':').trim()) attributes[pair[0].trim()] = pair.slice(1).join(':').trim();
    });
    return Object.assign(existing, {
      code: row.querySelector('[data-sku-field="code"]').value.trim(),
      cost: row.querySelector('[data-sku-field="cost"]').value,
      safetyStock: row.querySelector('[data-sku-field="safetyStock"]').value,
      categoryCode: row.querySelector('[data-sku-field="categoryCode"]').value.trim(),
      packedWeightG: row.querySelector('[data-sku-field="packedWeightG"]').value,
      purchaseCostCny: row.querySelector('[data-sku-field="purchaseCostCny"]').value,
      creatorCommission: row.querySelector('[data-sku-field="creatorCommission"]').value,
      attributes: attributes
    });
  });
}

function renderStores() {
  const rows = $('#storeRows');
  if (!rows) return;
  const stores = state.stores || [];
  rows.innerHTML = stores.map(function (store) {
    let actions = rowButton('edit-store', String(store.id), '编辑', 'primary');
    actions += rowButton('toggle-store', String(store.id), store.is_active === false ? '启用' : '停用');
    actions += rowButton('delete-store', String(store.id), '删除', 'danger');
    return '<tr><td>' + escapeHtml(store.name) + '</td><td>' + escapeHtml(store.platform) + '</td><td>' + escapeHtml(store.market) + '</td><td>' + statusPill(store.is_active === false ? '停用' : '启用', store.is_active === false ? 'inactive' : 'active') + '</td><td>' + formatDate(store.created_at) + '</td><td>' + formatDate(store.updated_at) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('') || '<tr><td colspan="7">尚未创建店铺。</td></tr>';
}

function openStoreEditor(storeId) {
  const store = (state.stores || []).find(function (item) { return String(item.id) === String(storeId); });
  $('#storeForm').reset(); $('#storeEditId').value = store ? String(store.id) : '';
  $('#storeModalTitle').textContent = store ? '编辑店铺' : '新增店铺';
  $('#storeName').value = store ? store.name : ''; $('#storePlatform').value = store ? store.platform : 'TikTok Shop';
  $('#storeMarket').value = store ? store.market : '马来西亚'; $('#storeActive').value = store && store.is_active === false ? 'false' : 'true';
  openModal('storeModal');
}

async function saveStoreFromForm(event) {
  event.preventDefault();
  if (!TEAM_MODE) return showToast('店铺管理仅在团队服务器模式中使用。');
  const id = $('#storeEditId').value;
  const store = { name: $('#storeName').value, platform: $('#storePlatform').value, market: $('#storeMarket').value, is_active: $('#storeActive').value === 'true' };
  const saved = await executeTeamCommand(function () { return teamGateway.saveStore(store, id); }, id ? '店铺已更新。' : '店铺已创建。', 'store');
  if (saved) closeModal('storeModal');
}
function storeListingDraft(raw, sku) {
  return {
    id: raw && raw.id ? String(raw.id) : '', skuId: sku && sku.id ? String(sku.id) : '', skuCode: sku ? sku.code : '',
    store: raw ? String(raw.store) : '', salePrice: raw && raw.sale_price_myr != null ? raw.sale_price_myr : '',
    productUrl: raw && raw.product_url || '', commission: raw && raw.commission_override_percent != null ? raw.commission_override_percent : '',
    include: !raw || raw.include_in_list_calculation !== false
  };
}
function renderProductStoreEditor() {
  const list = $('#productStoreList');
  if (!list) return;
  const stores = (state.stores || []).filter(function (store) { return store.is_active !== false; });
  if (!stores.length) { list.innerHTML = '<div class="sku-empty">请先在商品列表下方新增店铺。</div>'; return; }
  const rows = [];
  draftProductSkus.forEach(function (sku) {
    stores.forEach(function (store) {
      const saved = draftStoreListings.find(function (item) {
        return String(item.store) === String(store.id) && ((sku.id && String(item.skuId) === String(sku.id)) || (!sku.id && item.skuCode === sku.code));
      }) || storeListingDraft(null, sku);
      saved.store = String(store.id); saved.skuCode = sku.code;
      rows.push('<div class="sku-editor-row store-listing-row" data-store-listing data-listing-id="' + escapeHtml(saved.id) + '" data-sku-id="' + escapeHtml(saved.skuId) + '" data-sku-code="' + escapeHtml(sku.code) + '" data-store-id="' + escapeHtml(String(store.id)) + '">' +
        '<label>SKU / 店铺<input value="' + escapeHtml((sku.code || '待填写 SKU') + ' · ' + store.name) + '" disabled /></label>' +
        '<label>售价（RM）<input data-listing-field="price" type="number" min="0" step="0.01" value="' + escapeHtml(saved.salePrice) + '" /></label>' +
        '<label>手工佣金（%）<input data-listing-field="commission" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(saved.commission) + '" placeholder="留空使用默认" /></label>' +
        '<label>商品链接<input data-listing-field="url" type="url" value="' + escapeHtml(saved.productUrl) + '" /></label>' +
        '<label class="checkbox-field"><input data-listing-field="include" type="checkbox"' + (saved.include ? ' checked' : '') + ' /><span><strong>参与列表试算</strong></span></label></div>');
    });
  });
  list.innerHTML = rows.join('') || '<div class="sku-empty">请先填写 SKU。</div>';
}
function readStoreListingDrafts() {
  return $$('[data-store-listing]').map(function (row) {
    return { id: row.dataset.listingId, skuId: row.dataset.skuId, skuCode: row.dataset.skuCode, store: row.dataset.storeId,
      salePrice: row.querySelector('[data-listing-field="price"]').value,
      commission: row.querySelector('[data-listing-field="commission"]').value,
      productUrl: row.querySelector('[data-listing-field="url"]').value.trim(),
      include: row.querySelector('[data-listing-field="include"]').checked };
  });
}
function openProductEditor(productId, presetKind) {
  const product = productId ? productById(productId) : null;
  $('#productForm').reset();
  $('#editProductId').value = product ? product.id : '';
  $('#productModalTitle').textContent = product ? '编辑商品' : '新增商品';
  $('#saveProductButton').textContent = product ? '保存修改' : '保存商品';
  if ($('#saveProductDraft')) $('#saveProductDraft').textContent = product ? '存为草稿' : '保存草稿';
  $('#productName').value = product ? product.name : '';
  $('#productKind').value = product ? product.kind : (presetKind || 'own');
  Array.from($('#productKind').options).forEach(function (option) {
    option.hidden = (product ? product.kind === 'own' : presetKind === 'own') ? option.value !== 'own' : option.value === 'own';
  });
  $('#sellerName').value = product ? product.seller : '';
  $('#sellerRating').value = product && product.sellerRating != null ? product.sellerRating : '';
  $('#sellerIsStar').checked = Boolean(product && product.sellerIsStar);
  $('#sellerType').value = product && product.sellerType || 'normal';
  $('#competitorShippingType').value = product && product.shippingType || '';
  $('#competitorNotes').value = product && product.notes || '';
  $('#productMarket').value = product ? product.market : 'MY';
  $('#productCurrency').value = product ? product.salesCurrency : ($('#productKind').value === 'own' ? 'CNY' : 'MYR');
  draftProductSkus = product && product.kind === 'own' ? editableSkuDrafts(product) : (presetKind === 'own' ? [skuDraft()] : []);
  draftStoreListings = [];
  if (product && product.kind === 'own' && TEAM_MODE && teamGateway) {
    const rawProduct = teamGateway.findRawProduct(product);
    (rawProduct && rawProduct.skus || []).forEach(function (sku) {
      (sku.store_products || []).forEach(function (item) { draftStoreListings.push(storeListingDraft(item, sku)); });
    });
  }
  $('#productSupplier').value = product ? product.defaultSupplier : '';
  $('#productStatus').value = product ? product.status : 'active';
  $('#productUrl').value = product ? product.productUrl : '';
  $('#productPurchaseUrl').value = product ? product.purchaseUrl : '';
  $('#productCompare').checked = product ? product.monitoringEnabled : false;
  pendingProductImage = product ? product.image : '';
  $('#productImageUrl').value = product ? exportableImageUrl(product.image) : '';
  $('#productImageStatus').classList.remove('error');
  $('#productImageStatus').textContent = product && /^data:image\//i.test(product.image || '') ? '当前图片由电脑上传并已同步。' : '';
  $('#initialSnapshotFields').hidden = Boolean(product);
  $('#firstSnapshotAt').value = localDateTime(new Date());
  ['#firstPrice', '#firstSold', '#firstRating', '#firstReviews', '#firstLowReviews', '#firstShopRating'].forEach(function (selector) { $(selector).value = ''; });
  toggleProductFields();
  renderProductSkuEditor();
  updateProductImagePreview();
  openModal('productModal');
}
function validUrl(value) {
  try {
    const url = new URL(String(value || '').trim());
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch (_) {
    return false;
  }
}
function productMissingFields(product, rawCost) {
  const missing = [];
  if (!product.name) missing.push('商品名称');
  if (!validUrl(product.productUrl)) missing.push('商品链接');
  if (!product.image) missing.push('商品图片');
  if (product.kind === 'own') {
    const skus = Array.isArray(product.skus) ? product.skus : [{ code: product.sku, cost: rawCost }];
    if (!skus.length || skus.some(function (sku) { return !String(sku.code || '').trim(); })) missing.push('SKU 编码');
    if (skus.some(function (sku) { return sku.cost === '' || !Number.isFinite(Number(sku.cost)) || Number(sku.cost) <= 0; })) missing.push('大于 0 的 SKU 成本');
    const codes = skus.map(function (sku) { return normalizeSku(sku.code); }).filter(Boolean);
    if (new Set(codes).size !== codes.length) missing.push('不重复的 SKU 编码');
  }
  return missing;
}
function snapshotFromForm(prefix, product, required) {
  const first = prefix === '#firstSnapshot';
  const valuePrefix = first ? '#first' : prefix;
  const at = $(first ? '#firstSnapshotAt' : prefix + 'At').value;
  const priceRaw = $(valuePrefix + 'Price').value;
  const soldRaw = $(valuePrefix + 'Sold').value;
  if (!required && priceRaw === '' && soldRaw === '') return null;
  if (!at || priceRaw === '' || soldRaw === '') throw new Error('快照的时间、价格和累计销量必须完整填写。');
  const rating = $(valuePrefix + 'Rating').value;
  const reviews = integer($(valuePrefix + 'Reviews').value);
  const lowReviews = integer($(valuePrefix + 'LowReviews').value);
  const shopRating = $(valuePrefix + 'ShopRating').value;
  if (lowReviews > reviews) throw new Error('1–2 星评价数不能超过评价总数。');
  if (rating !== '' && (asNumber(rating) < 0 || asNumber(rating) > 5)) throw new Error('商品评分必须在 0–5 之间。');
  if (shopRating !== '' && (asNumber(shopRating) < 0 || asNumber(shopRating) > 5)) throw new Error('店铺评分必须在 0–5 之间。');
  return {
    id: uid('snap'), productId: product.id, at: new Date(at).toISOString(), currency: product.salesCurrency,
    price: nonNegative(priceRaw), sold: integer(soldRaw), rating: rating === '' ? null : asNumber(rating),
    reviews: reviews, lowReviews: lowReviews, shopRating: shopRating === '' ? null : asNumber(shopRating),
    shippingType: first ? (product.shippingType || '') : ($('#snapshotShippingType') ? $('#snapshotShippingType').value : ''),
    createdAt: new Date().toISOString()
  };
}
function snapshotAdvancedChanged(snapshot, latest) {
  if (!latest) return true;
  function optional(value) { return value === '' || value == null ? null : asNumber(value); }
  return asNumber(snapshot.price) !== asNumber(latest.price) ||
    optional(snapshot.rating) !== optional(latest.rating) ||
    integer(snapshot.reviews) !== integer(latest.reviews) ||
    integer(snapshot.lowReviews) !== integer(latest.lowReviews) ||
    optional(snapshot.shopRating) !== optional(latest.shopRating);
}

async function compressProductImage(file) {
  if (!file || !String(file.type || '').toLowerCase().startsWith('image/')) throw new Error('请选择图片文件。');
  if (file.size > 20 * 1024 * 1024) throw new Error('原图不能超过 20MB。');
  const dataUrl = await new Promise(function (resolve, reject) {
    const reader = new FileReader();
    reader.onload = function () { resolve(reader.result); };
    reader.onerror = function () { reject(new Error('图片读取失败。')); };
    reader.readAsDataURL(file);
  });
  const image = await new Promise(function (resolve, reject) {
    const element = new Image();
    element.onload = function () { resolve(element); };
    element.onerror = function () { reject(new Error('图片无法打开。')); };
    element.src = dataUrl;
  });
  const maxSide = 900;
  const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.width * scale));
  canvas.height = Math.max(1, Math.round(image.height * scale));
  canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
  const compressed = canvas.toDataURL('image/webp', 0.82);
  if (compressed.length > 560000) return canvas.toDataURL('image/jpeg', 0.68);
  return compressed;
}

function renderPurchaseDraft() {
  $('#purchaseLineList').innerHTML = draftPurchaseLines.length ? draftPurchaseLines.map(function (line) {
    const product = productById(line.productId);
    return '<div class="line-list-item">' + (product ? productMedia(product) : '<strong>未知商品</strong>') +
      '<label>数量<input data-purchase-line-quantity="' + escapeHtml(line.productId) + '" type="number" min="1" step="1" value="' + integer(line.quantity) + '"></label>' +
      '<label>单价<input data-purchase-line-cost="' + escapeHtml(line.productId) + '" type="number" min="0" step="0.01" value="' + escapeHtml(String(line.unitCost)) + '"></label>' +
      '<button class="line-remove" data-remove-purchase-line="' + escapeHtml(line.productId) + '" type="button">移除</button></div>';
  }).join('') : '<div class="last-value">请至少加入一条采购明细。</div>';
  renderPurchaseSkuPicker();
  renderPurchaseShipments();
}

function selectionAIAnalysisHtml(payload) {
  if (!payload) return '';
  if (payload.status !== 'ready' || !payload.analysis) {
    return '<section class="selection-market-summary"><div class="selection-summary-head"><div><h3>大模型选品分析未完成</h3><p>' + escapeHtml(payload.detail || '原始选品数据仍可正常使用。') + '</p></div></div></section>';
  }
  const analysis = payload.analysis || {};
  const rows = [
    ['机会', analysis.opportunities], ['风险', analysis.risks], ['下一步', analysis.next_actions]
  ].map(function (entry) {
    const value = Array.isArray(entry[1]) ? entry[1].join('；') : entry[1];
    return value ? '<p><b>' + escapeHtml(entry[0]) + '：</b>' + escapeHtml(String(value)) + '</p>' : '';
  }).join('');
  return '<section class="selection-market-summary"><div class="selection-summary-head"><div><h3>大模型选品分析</h3><p>' + escapeHtml(String(analysis.summary || '已基于选品接口原始数据完成分析。')) + '</p>' + rows + '</div><div class="selection-summary-score"><strong>AI</strong><span>' + escapeHtml(payload.provider || '已配置模型') + '</span></div></div></section>';
}

function renderPurchaseShipments() {
  const container = $('#purchaseShipmentList');
  if (!container) return;
  container.innerHTML = draftPurchaseShipments.length ? draftPurchaseShipments.map(function (shipment, shipmentIndex) {
    const allocations = draftPurchaseLines.map(function (line) {
      const product = productById(line.productId);
      const saved = (shipment.lines || []).find(function (item) { return item.productId === line.productId; }) || {};
      return '<label>' + escapeHtml(product ? (product.sku + ' · ' + product.name) : 'SKU') +
        '<input data-shipment-quantity="' + shipmentIndex + ':' + escapeHtml(line.productId) + '" type="number" min="0" step="1" max="' + integer(line.quantity) + '" value="' + (saved.quantity == null ? '' : integer(saved.quantity)) + '" placeholder="本包裹数量"></label>';
    }).join('');
    return '<div class="shipment-editor"><div><strong>物流单号：' + escapeHtml(shipment.trackingNumber) + '</strong><button class="line-remove" data-remove-purchase-shipment="' + shipmentIndex + '" type="button">移除</button></div><div class="shipment-line-grid">' + allocations + '</div></div>';
  }).join('') : '<div class="last-value">尚未填写物流单号。可在创建后继续编辑补充，物流不调用付费接口。</div>';
}
function renderPurchaseSkuPicker() {
  const container = $('#purchaseSkuPicker');
  if (!container) return;
  const term = String($('#purchaseSkuSearch') ? $('#purchaseSkuSearch').value : '').trim().toLowerCase();
  const products = ownProducts(state).filter(function (product) {
    if (product.needsReview || product.status === 'draft' || product.status === 'inactive') return false;
    if (!term) return true;
    return [product.sku, product.name, product.seller, product.defaultSupplier].join(' ').toLowerCase().includes(term);
  });
  setText('#purchaseSkuPickerHint', products.length ? '显示 ' + products.length + ' 个 SKU' : (term ? '未找到匹配 SKU' : '暂无可采购 SKU'));
  container.innerHTML = products.map(function (product) {
    const image = safeImageUrl(product.image);
    const inDraft = draftPurchaseLines.some(function (line) { return line.productId === product.id; });
    const productLink = validUrl(product.productUrl)
      ? '<a href="' + escapeHtml(product.productUrl) + '" target="_blank" rel="noopener noreferrer">商品链接</a>' : '';
    const purchaseLink = validUrl(product.purchaseUrl)
      ? '<a href="' + escapeHtml(product.purchaseUrl) + '" target="_blank" rel="noopener noreferrer">采购链接</a>' : '';
    return '<article class="purchase-sku-card" data-purchase-sku-card="' + escapeHtml(product.id) + '">' +
      '<div class="purchase-sku-image">' + (image ? '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(product.name) + '" loading="lazy" onerror="this.hidden=true">' : '暂无图片') + '</div>' +
      '<div class="purchase-sku-copy"><strong title="' + escapeHtml(product.name) + '">' + escapeHtml(product.name) + '</strong><span class="sku-code">' + escapeHtml(product.sku || '无 SKU') + '</span>' +
      '<div class="purchase-sku-links">' + (productLink || '<span>暂无商品链接</span>') + purchaseLink + '</div></div>' +
      '<div class="purchase-sku-fields"><label>采购数量<input data-purchase-sku-quantity="' + escapeHtml(product.id) + '" type="number" min="1" step="1" value="' + (inDraft ? integer(draftPurchaseLines.find(function (line) { return line.productId === product.id; }).quantity) : '') + '" placeholder="数量"></label>' +
      '<label>实际单价<input data-purchase-sku-cost="' + escapeHtml(product.id) + '" type="number" min="0" step="0.01" value="' + escapeHtml(String(inDraft ? draftPurchaseLines.find(function (line) { return line.productId === product.id; }).unitCost : nonNegative(product.standardCost))) + '"></label>' +
      '<button class="button secondary" data-add-purchase-sku="' + escapeHtml(product.id) + '" type="button">' + (inDraft ? '更新明细' : '加入明细') + '</button></div></article>';
  }).join('') || '<div class="last-value">没有符合条件的 SKU。请调整搜索条件或先完善商品资料。</div>';
}
function renderOrderSkuPicker() {
  const container = $('#orderSkuPicker');
  if (!container) return;
  const term = String($('#orderSkuSearch') ? $('#orderSkuSearch').value : '').trim().toLowerCase();
  const products = ownProducts(state).filter(function (product) {
    if (product.needsReview || product.status === 'draft' || product.status === 'inactive') return false;
    return !term || [product.sku, product.name, product.seller].join(' ').toLowerCase().includes(term);
  });
  setText('#orderSkuPickerHint', products.length ? '显示 ' + products.length + ' 个 SKU' : (term ? '未找到匹配 SKU' : '暂无可销售 SKU'));
  container.innerHTML = products.map(function (product) {
    const image = safeImageUrl(product.image);
    const existing = draftOrderLines.find(function (line) { return line.productId === product.id; });
    const available = availableFor(product.id);
    const quantity = existing ? integer(existing.quantity) : 0;
    const shortage = Math.max(0, quantity - available);
    return '<article class="purchase-sku-card" data-order-sku-card="' + escapeHtml(product.id) + '">' +
      '<div class="purchase-sku-image">' + (image ? '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(product.name) + '" loading="lazy" onerror="this.hidden=true">' : '暂无图片') + '</div>' +
      '<div class="purchase-sku-copy"><strong title="' + escapeHtml(product.name) + '">' + escapeHtml(product.name) + '</strong><span class="sku-code">' + escapeHtml(product.sku || '无 SKU') + '</span>' +
      '<div class="order-stock-copy"><span>当前仓：' + escapeHtml((selectedWarehouse() || {}).name || '未选择') + '</span><span>可用 <b>' + available + '</b></span>' + (shortage ? '<span class="shortage">预计缺口 ' + shortage + '</span>' : '') + '</div></div>' +
      '<div class="purchase-sku-fields"><label>订单数量<input data-order-sku-quantity="' + escapeHtml(product.id) + '" type="number" min="1" step="1" value="' + (quantity || '') + '" placeholder="数量"></label>' +
      '<button class="button secondary" data-add-order-sku="' + escapeHtml(product.id) + '" type="button">' + (existing ? '更新明细' : '加入明细') + '</button></div></article>';
  }).join('') || '<div class="last-value">没有符合条件的 SKU。请调整搜索条件或先完善商品资料。</div>';
}

async function openPurchaseEditor(existingOrder) {
  if (!ownProducts(state).filter(function (item) { return !item.needsReview; }).length) {
    showToast('请先在商品中心新增并完善本店 SKU。');
    setRoute('products');
    return;
  }
  if (TEAM_MODE && !purchaseMembers.length) {
    try {
      purchaseMembers = await teamGateway.listPurchaseMembers();
    } catch (error) {
      // The purchaser list is optional. A temporary member API failure must not
      // prevent a user from opening and creating a purchase order.
      console.warn('Unable to load purchase members; using the operator fallback.', error);
      purchaseMembers = [];
    }
  }
  $('#purchaseForm').reset();
  purchaseEditId = existingOrder ? existingOrder.id : '';
  draftPurchaseLines = existingOrder ? existingOrder.lines.map(function (line) {
    return { productId: line.productId, skuId: line.skuId, purchaseLineId: line.id, quantity: line.orderedQty, unitCost: line.unitCost, receivedQty: line.receivedQty || 0 };
  }) : [];
  draftPurchaseShipments = existingOrder ? (existingOrder.shipments || []).map(function (shipment) {
    return { id: shipment.id, trackingNumber: shipment.trackingNumber, lines: (shipment.lines || []).map(function (line) {
      const linked = existingOrder.lines.find(function (item) { return item.id === line.purchaseLineId; }) || {};
      return { productId: linked.productId, skuId: line.skuId || linked.skuId, purchaseLineId: line.purchaseLineId, quantity: line.quantity };
    }) };
  }) : [];
  $('#purchaseNumber').value = existingOrder ? existingOrder.number : ('PO-' + today().replace(/-/g, '') + '-' + String(Date.now()).slice(-4));
  $('#purchaseSupplier').value = existingOrder ? existingOrder.supplier : '';
  $('#purchaseStatus').value = existingOrder ? (existingOrder.status === 'draft' ? 'draft' : 'ordered') : 'ordered';
  $('#purchaseStatus').disabled = Boolean(existingOrder);
  $('#purchaseOrderedAt').value = existingOrder ? String(existingOrder.orderedAt || '').slice(0, 10) : today();
  const eta = new Date(); eta.setDate(eta.getDate() + 14);
  $('#purchaseEta').value = existingOrder ? String(existingOrder.expectedAt || '').slice(0, 10) : localDateTime(eta).slice(0, 10);
  $('#purchaseExtraCost').value = existingOrder ? nonNegative(existingOrder.extraCost) : 0;
  $('#purchaseNote').value = existingOrder ? (existingOrder.note || '') : '';
  const operator = TEAM_MODE && teamGateway.user ? String(teamGateway.user.id) : '';
  $('#purchasePurchaser').innerHTML = purchaseMembers.map(function (member) {
    return '<option value="' + escapeHtml(String(member.user_id)) + '">' + escapeHtml(member.display_name || member.username) + '</option>';
  }).join('') || '<option value="">当前操作员</option>';
  $('#purchasePurchaser').value = existingOrder ? (existingOrder.purchaserId || operator) : operator;
  $('#purchaseModalTitle').textContent = existingOrder ? '编辑采购单' : '创建采购单';
  $('#purchaseSkuSearch').value = '';
  renderPurchaseDraft();
  openModal('purchaseModal');
}
function renderOrderDraft() {
  $('#orderLineList').innerHTML = draftOrderLines.length ? draftOrderLines.map(function (line) {
    const product = productById(line.productId);
    const available = availableFor(line.productId);
    const shortage = Math.max(0, integer(line.quantity) - available);
    return '<div class="line-list-item">' + productQuantityMedia(product || { name: '未知商品', sku: '' }, line.quantity) +
      '<span>可用 ' + available + (shortage ? ' · 缺口 ' + shortage : '') + '</span>' +
      '<button class="line-remove" data-remove-order-line="' + escapeHtml(line.productId) + '" type="button">移除</button></div>';
  }).join('') : '<div class="last-value">请至少加入一条订单明细。</div>';
  renderOrderSkuPicker();
}
function openOrderEditor() {
  const warehouse = selectedWarehouse();
  if (!warehouse || warehouse.canShip === false || warehouse.can_ship === false) return showToast('当前仓库未开放出库，不能创建出库订单。');
  if (!ownProducts(state).filter(function (item) { return !item.needsReview; }).length) {
    showToast('请先在商品中心新增并完善本店 SKU。');
    setRoute('products');
    return;
  }
  $('#orderForm').reset();
  draftOrderLines = [];
  $('#orderNumber').value = 'SO-' + today().replace(/-/g, '') + '-' + String(Date.now()).slice(-4);
  $('#orderAt').value = localDateTime(new Date());
  $('#orderSkuSearch').value = '';
  renderOrderDraft();
  openModal('orderModal');
}
function openStockEditor(productId) {
  const readyProducts = ownProducts(state).filter(function (item) { return !item.needsReview; });
  if (!readyProducts.length) {
    const incomplete = ownProducts(state, true).find(function (item) { return item.status !== 'inactive'; });
    showToast(incomplete ? '该商品资料尚未完善，请先补齐 SKU、成本、链接和图片。' : '请先新增并完善一个本店 SKU。');
    setRoute('products');
    if (incomplete) openProductEditor(incomplete.id);
    return;
  }
  if (productId && !readyProducts.some(function (item) { return item.id === productId; })) {
    showToast('该商品尚未达到入库条件，请先完善商品资料。');
    setRoute('products');
    openProductEditor(productId);
    return;
  }
  $('#stockForm').reset();
  $('#stockAt').value = localDateTime(new Date());
  if (productId && productById(productId)) $('#stockProduct').value = productId;
  updateStockHint();
  openModal('stockModal');
}
function resetWarehouseEditor() {
  $('#warehouseForm').reset();
  $('#warehouseEditId').value = '';
  $('#warehouseFormTitle').textContent = '新建仓库';
  $('#warehouseType').value = 'overseas';
  $('#warehouseCountry').value = 'MY';
  $('#warehouseTimezone').value = 'Asia/Kuala_Lumpur';
  $('#warehouseCanReceive').checked = true;
  $('#warehouseCanShip').checked = true;
}
function openWarehouseManager() {
  resetWarehouseEditor();
  renderWarehouseDirectory();
  openModal('warehouseModal');
}
function openWarehouseEditor(warehouseId) {
  const warehouse = warehouseById(warehouseId);
  if (!warehouse) return showToast('仓库不存在。');
  $('#warehouseEditId').value = String(warehouse.id);
  $('#warehouseFormTitle').textContent = '编辑仓库';
  $('#warehouseCode').value = warehouse.code || '';
  $('#warehouseName').value = warehouse.name || '';
  $('#warehouseType').value = warehouseTypeOf(warehouse);
  $('#warehouseCountry').value = warehouse.country || '';
  $('#warehouseTimezone').value = warehouse.timezone || 'Asia/Shanghai';
  $('#warehouseContact').value = warehouse.contact || '';
  $('#warehouseAddress').value = warehouse.address || '';
  $('#warehouseCanReceive').checked = warehouse.canReceive !== false && warehouse.can_receive !== false;
  $('#warehouseCanShip').checked = warehouse.canShip !== false && warehouse.can_ship !== false;
  $('#warehouseFormTitle').scrollIntoView({ behavior: 'smooth', block: 'center' });
}
async function switchWarehouse(warehouseId) {
  if (TEAM_MODE) {
    if (!teamAuthenticated() || teamBusy || String(teamGateway.warehouseId) === String(warehouseId)) return;
    const currentUi = clone(state.ui);
    teamBusy = true;
    renderRuntimeState();
    try {
      state = normalizeV5(await teamGateway.selectWarehouse(warehouseId));
      state.ui = currentUi;
      teamLastSyncedAt = new Date().toISOString();
      render();
      showToast('已切换仓库，补货、在途、库存和订单已重新计算。');
    } catch (error) { handleTeamError(error); }
    finally { teamBusy = false; renderRuntimeState(); }
    return;
  }
  const warehouse = state.warehouses.find(function (item) { return item.id === warehouseId && item.active; });
  if (!warehouse) return showToast('仓库不存在或已停用。');
  state.ui.warehouseId = warehouse.id;
  saveUiQuietly();
  render();
  showToast('已切换到“' + warehouse.name + '”。');
}
async function handleWarehouseSubmit(event) {
  event.preventDefault();
  const editId = $('#warehouseEditId').value;
  const warehouseDirectory = TEAM_MODE && teamGateway ? teamGateway.warehouses : state.warehouses;
  const existingWarehouse = warehouseDirectory.find(function (item) { return String(item.id) === String(editId); });
  const warehouse = normalizeWarehouse({
    id: editId || uid('warehouse'), code: $('#warehouseCode').value, name: $('#warehouseName').value,
    type: $('#warehouseType').value, country: $('#warehouseCountry').value, timezone: $('#warehouseTimezone').value,
    contact: $('#warehouseContact').value, address: $('#warehouseAddress').value,
    canReceive: $('#warehouseCanReceive').checked, canShip: $('#warehouseCanShip').checked,
    active: existingWarehouse ? existingWarehouse.active !== false : true
  }, state.warehouses.length);
  const duplicate = warehouseDirectory.find(function (item) {
    return String(item.id) !== String(editId) && String(item.code || '').toUpperCase() === warehouse.code;
  });
  if (duplicate) return showToast('仓库编码已存在，请换一个编码。');
  if (TEAM_MODE) {
    const saved = await executeTeamCommand(function () { return teamGateway.saveWarehouse(warehouse, editId); }, editId ? '仓库资料已更新。' : '新仓库已创建。', 'warehouse_admin');
    if (saved) { resetWarehouseEditor(); renderWarehouseDirectory(); }
    return;
  }
  const saved = commit(function (next) {
    const index = next.warehouses.findIndex(function (item) { return item.id === editId; });
    if (index >= 0) warehouse.active = next.warehouses[index].active;
    if (index >= 0) next.warehouses[index] = warehouse; else next.warehouses.push(warehouse);
    if (!editId) next.ui.warehouseId = warehouse.id;
  }, editId ? '仓库资料已更新。' : '新仓库已创建并切换为当前仓。');
  if (saved) { resetWarehouseEditor(); renderWarehouseDirectory(); }
}
function renderTransferDraft() {
  const container = $('#transferLineList');
  if (!container) return;
  container.innerHTML = draftTransferLines.length ? draftTransferLines.map(function (line) {
    const product = productById(line.productId);
    return '<div class="line-list-item">' + productQuantityMedia(product || { name: '未知商品', sku: '' }, line.quantity) + '<span>当前可用 ' + availableFor(line.productId) + '</span><button class="line-remove" data-remove-transfer-line="' + escapeHtml(line.productId) + '" type="button">移除</button></div>';
  }).join('') : '<div class="last-value">请至少加入一条调拨明细。</div>';
  renderTransferPackageDraft();
}
function ensureDraftTransferPackage() {
  if (!draftTransferPackages.length) draftTransferPackages.push({ id: uid('transfer-package'), trackingNumber: '', quantities: {} });
  return draftTransferPackages[0];
}
function renderTransferPackageDraft() {
  const container = $('#transferPackageList');
  if (!container) return;
  if (draftTransferLines.length) ensureDraftTransferPackage();
  if (!draftTransferLines.length) {
    container.innerHTML = '<div class="last-value">先添加调拨 SKU，才能分配物流包裹数量。</div>';
    return;
  }
  container.innerHTML = draftTransferPackages.map(function (pack, index) {
    const lines = draftTransferLines.map(function (line) {
      const product = productById(line.productId);
      const quantity = pack.quantities[line.productId] == null ? 0 : pack.quantities[line.productId];
      return '<label>' + escapeHtml(product ? product.sku : 'SKU') + '<input type="number" min="0" step="1" value="' + quantity + '" data-transfer-package-qty="' + index + '" data-product-id="' + escapeHtml(line.productId) + '" /></label>';
    }).join('');
    return '<article class="line-list-item"><div><strong>包裹 ' + (index + 1) + '</strong><label>物流单号（可留空）<input value="' + escapeHtml(pack.trackingNumber || '') + '" data-transfer-package-tracking="' + index + '" /></label></div><div class="form-grid three">' + lines + '</div>' +
      '<button class="line-remove" type="button" data-remove-transfer-package="' + index + '"' + (draftTransferPackages.length === 1 ? ' disabled' : '') + '>移除包裹</button></article>';
  }).join('');
}
function collectTransferPackages() {
  $$('#transferPackageList [data-transfer-package-tracking]').forEach(function (input) {
    const pack = draftTransferPackages[Number(input.dataset.transferPackageTracking)];
    if (pack) pack.trackingNumber = input.value.trim();
  });
  $$('#transferPackageList [data-transfer-package-qty]').forEach(function (input) {
    const pack = draftTransferPackages[Number(input.dataset.transferPackageQty)];
    if (pack) pack.quantities[input.dataset.productId] = integer(input.value);
  });
  const packages = draftTransferPackages.map(function (pack) {
    return { id: pack.id, trackingNumber: pack.trackingNumber, lines: draftTransferLines.map(function (line) {
      const product = productById(line.productId);
      return { skuId: product && product.skuId, quantity: integer(pack.quantities[line.productId]) };
    }).filter(function (line) { return line.skuId && line.quantity > 0; }) };
  });
  const invalid = draftTransferLines.some(function (line) {
    const packaged = packages.reduce(function (sum, pack) {
      const packageLine = pack.lines.find(function (item) { return item.skuId === (productById(line.productId) || {}).skuId; });
      return sum + (packageLine ? packageLine.quantity : 0);
    }, 0);
    return packaged !== integer(line.quantity);
  });
  if (invalid) throw new Error('每个 SKU 在所有包裹中的数量总和必须与调拨计划完全一致。');
  return packages;
}
function openTransferEditor() {
  const source = selectedWarehouse();
  const destinations = activeWarehouses().filter(function (item) { return String(item.id) !== String(source && source.id) && item.canReceive !== false && item.can_receive !== false; });
  if (!source) return openWarehouseManager();
  if (source.canShip === false || source.can_ship === false) return showToast('当前仓库未开放出库，不能发起调拨。');
  if (!destinations.length) {
    showToast('请先新建至少一个可收货的目标仓库。');
    return openWarehouseManager();
  }
  if (!ownProducts(state).some(function (item) { return !item.needsReview; })) return showToast('请先建立本店 SKU。');
  $('#transferForm').reset();
  draftTransferLines = [];
  draftTransferPackages = [];
  renderSelects();
  $('#transferNumber').value = 'TR-' + today().replace(/-/g, '') + '-' + String(Date.now()).slice(-4);
  $('#transferSourceName').value = (source.code || '') + ' · ' + source.name;
  renderTransferDraft();
  openModal('transferModal');
}
async function handleTransferSubmit(event) {
  event.preventDefault();
  if (!draftTransferLines.length) return showToast('请至少加入一条调拨明细。');
  const sourceId = TEAM_MODE ? String(teamGateway.warehouseId) : currentWarehouseId();
  let packages;
  try { packages = collectTransferPackages(); } catch (error) { return showToast(error.message); }
  const transfer = {
    id: uid('transfer'), number: $('#transferNumber').value.trim(), sourceWarehouseId: sourceId,
    destinationWarehouseId: $('#transferDestination').value, status: 'draft', note: $('#transferNote').value.trim(),
    lines: draftTransferLines.map(function (line) { const product = productById(line.productId); return { id: uid('transfer-line'), productId: line.productId, skuId: product ? product.skuId : '', quantity: integer(line.quantity), receivedQty: 0 }; }),
    packages: packages, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString()
  };
  if (TEAM_MODE) {
    const saved = await executeTeamCommand(function () { return teamGateway.createAndShipTransfer(transfer); }, '调拨已发出，目标仓确认后转入库存。', 'transfer');
    if (saved) closeModal('transferModal');
    return;
  }
  const saved = commit(function (next) { next.stockTransfers.push(transfer); dispatchTransfer(next, transfer); }, '调拨已发出，目标仓确认后转入库存。');
  if (saved) closeModal('transferModal');
}
function openReplenishmentPolicy(productId) {
  const product = productById(productId);
  if (!product) return;
  const policyWarehouseId = TEAM_MODE && teamGateway ? String(teamGateway.warehouseId) : currentWarehouseId();
  const policy = localPolicyFor(productId, policyWarehouseId);
  const serverRecommendation = (state.replenishmentRecommendations || []).find(function (item) { return String(item.sku || item.sku_id) === String(product.skuId); }) || {};
  const serverWeights = serverRecommendation.weights || {};
  const profileConfig = serverRecommendation.profile_config || {};
  setControlValue('#policyProductId', productId);
  setText('#replenishmentPolicyIntro', (product.sku || '无 SKU') + ' · ' + product.name + '；参数跟随 SKU，未设置主力仓时不会产生正式建议。');
  const primaryWarehouse = $('#policyPrimaryWarehouse');
  if (primaryWarehouse) {
    primaryWarehouse.innerHTML = '<option value="">未设置</option>' + (state.warehouses || []).filter(function (row) { return row.active; }).map(function (row) { return '<option value="' + escapeHtml(row.id) + '">' + escapeHtml(row.name + ' · ' + row.code) + '</option>'; }).join('');
  }
  setControlValue('#policyPrimaryWarehouse', profileConfig.primary_warehouse || serverRecommendation.primary_warehouse || '');
  setControlValue('#policyLeadDays', profileConfig.manual_lead_time_days == null ? (policy.leadTimeOverride == null ? '' : policy.leadTimeOverride) : profileConfig.manual_lead_time_days);
  setControlValue('#policyTargetDays', profileConfig.target_coverage_days == null ? '' : profileConfig.target_coverage_days);
  setControlValue('#policyMoq', profileConfig.min_order_qty == null ? '' : profileConfig.min_order_qty);
  setControlValue('#policyPackSize', profileConfig.pack_size == null ? '' : profileConfig.pack_size);
  setControlValue('#policySafetyStock', profileConfig.safety_stock == null ? (policy.safetyStockOverride == null ? '' : policy.safetyStockOverride) : profileConfig.safety_stock);
  setControlValue('#policyWeight3', serverRecommendation.weight_source === 'sku' ? Math.round(Number(serverWeights.w3) * 100) : '');
  setControlValue('#policyWeight7', serverRecommendation.weight_source === 'sku' ? Math.round(Number(serverWeights.w7) * 100) : '');
  setControlValue('#policyWeight15', serverRecommendation.weight_source === 'sku' ? Math.round(Number(serverWeights.w15) * 100) : '');
  setControlValue('#policyWeight30', serverRecommendation.weight_source === 'sku' ? Math.round(Number(serverWeights.w30) * 100) : '');
  openModal('replenishmentPolicyModal');
}
async function openReplenishmentSettings() {
  if (!TEAM_MODE || !teamGateway) return showToast('全局补货参数仅在团队在线模式下可配置。');
  try {
    const settings = await teamGateway.getReplenishmentSettings() || {
      safety_days: 7, default_lead_time_days: 14, review_cycle_days: 7, target_days: 30,
      service_level_factor: 1.65, safety_margin_ratio: 0.2, initial_reference_shipment_count: 3,
      velocity_weight_3: 0.4, velocity_weight_7: 0.3, velocity_weight_15: 0.2, velocity_weight_30: 0.1,
      ai_provider: null, ai_enabled: false, ai_debounce_minutes: 5
    };
    setControlValue('#settingSafetyDays', settings.safety_days);
    setControlValue('#settingLeadDays', settings.default_lead_time_days);
    setControlValue('#settingReviewDays', settings.review_cycle_days);
    setControlValue('#settingTargetDays', settings.target_days);
    setControlValue('#settingServiceLevel', settings.service_level_factor);
    setControlValue('#settingSafetyMargin', settings.safety_margin_ratio);
    setControlValue('#settingInitialShipments', settings.initial_reference_shipment_count);
    setControlValue('#settingWeight3', settings.velocity_weight_3);
    setControlValue('#settingWeight7', settings.velocity_weight_7);
    setControlValue('#settingWeight15', settings.velocity_weight_15);
    setControlValue('#settingWeight30', settings.velocity_weight_30);
    if (!aiProviderConfigs.length) aiProviderConfigs = await teamGateway.listAIProviders();
    const providerSelect = $('#settingAIProvider');
    if (providerSelect) providerSelect.innerHTML = '<option value="">不调用大模型（仅使用规则）</option>' + aiProviderConfigs
      .filter(function (provider) { return provider.enabled && provider.has_api_key; })
      .map(function (provider) { return '<option value="' + escapeHtml(provider.id) + '">' + escapeHtml(provider.name + ' · ' + provider.model) + '</option>'; }).join('');
    setControlValue('#settingAIProvider', settings.ai_provider || '');
    setControlChecked('#settingAIEnabled', settings.ai_enabled);
    setControlValue('#settingAIDebounce', settings.ai_debounce_minutes || 5);
    openModal('replenishmentSettingsModal');
  } catch (error) { handleTeamError(error); }
}
async function handleReplenishmentSettingsSubmit(event) {
  event.preventDefault();
  if (!TEAM_MODE || !teamGateway) return;
  const payload = {
    safety_days: Number($('#settingSafetyDays').value),
    default_lead_time_days: integer($('#settingLeadDays').value),
    review_cycle_days: integer($('#settingReviewDays').value),
    target_days: integer($('#settingTargetDays').value),
    service_level_factor: Number($('#settingServiceLevel').value),
    safety_margin_ratio: Number($('#settingSafetyMargin').value),
    initial_reference_shipment_count: integer($('#settingInitialShipments').value),
    velocity_weight_3: Number($('#settingWeight3').value),
    velocity_weight_7: Number($('#settingWeight7').value),
    velocity_weight_15: Number($('#settingWeight15').value),
    velocity_weight_30: Number($('#settingWeight30').value),
    ai_provider: $('#settingAIProvider').value || null,
    ai_enabled: $('#settingAIEnabled').checked,
    ai_debounce_minutes: integer($('#settingAIDebounce').value)
  };
  try {
    await executeTeamCommand(function () { return teamGateway.saveReplenishmentSettings(payload); }, '全局补货参数已保存并重新计算。', 'replenishment');
    closeModal('replenishmentSettingsModal');
  } catch (error) { handleTeamError(error); }
}

function selectedReplenishmentItems() {
  return replenishmentRecommendations().filter(function (item) {
    return replenishmentSelectedSkuIds.has(String(item.skuId));
  });
}

function visibleReplenishmentSkuIds() {
  return $$('#replenishmentRows [data-replenishment-select]').map(function (input) {
    return String(input.dataset.replenishmentSelect);
  });
}

async function openBatchReplenishmentPolicy() {
  if (!replenishmentSelectedSkuIds.size) return showToast('请先勾选至少一个 SKU。');
  if (!TEAM_MODE || !teamGateway) return showToast('批量补货参数仅在团队在线模式下可配置。');
  try {
    const settings = await teamGateway.getReplenishmentSettings();
    if (settings) {
      setControlValue('#batchPolicyTargetDays', settings.target_days);
      setControlValue('#batchWeight3', Math.round(Number(settings.velocity_weight_3 == null ? 0.4 : settings.velocity_weight_3) * 100));
      setControlValue('#batchWeight7', Math.round(Number(settings.velocity_weight_7 == null ? 0.3 : settings.velocity_weight_7) * 100));
      setControlValue('#batchWeight15', Math.round(Number(settings.velocity_weight_15 == null ? 0.2 : settings.velocity_weight_15) * 100));
      setControlValue('#batchWeight30', Math.round(Number(settings.velocity_weight_30 == null ? 0.1 : settings.velocity_weight_30) * 100));
    }
    const batchPrimaryWarehouse = $('#batchPolicyPrimaryWarehouse');
    if (batchPrimaryWarehouse) batchPrimaryWarehouse.innerHTML = '<option value="">未设置</option>' + (state.warehouses || []).filter(function (row) { return row.active; }).map(function (row) { return '<option value="' + escapeHtml(row.id) + '">' + escapeHtml(row.name + ' · ' + row.code) + '</option>'; }).join('');
    setText('#replenishmentBatchPolicyTitle', '调整已选 ' + replenishmentSelectedSkuIds.size + ' 个 SKU 参数');
    openModal('replenishmentBatchPolicyModal');
  } catch (error) { handleTeamError(error); }
}

async function handleBatchReplenishmentPolicySubmit(event) {
  event.preventDefault();
  const weights = [$('#batchWeight3'), $('#batchWeight7'), $('#batchWeight15'), $('#batchWeight30')].map(function (input) { return Number(input.value); });
  if ($('#batchPolicyWeightsEnabled').checked && (weights.some(function (value) { return !Number.isFinite(value) || value < 0; }) || Math.abs(weights.reduce(function (sum, value) { return sum + value; }, 0) - 100) > 0.001)) {
    return showToast('近 3/7/15/30 天权重必须为非负数，且合计等于 100%。');
  }
  const fieldInputs = {
    primary_warehouse: '#batchPolicyPrimaryWarehouse',
    manual_lead_time_days: '#batchPolicyLeadDays',
    target_coverage_days: '#batchPolicyTargetDays',
    min_order_qty: '#batchPolicyMoq',
    pack_size: '#batchPolicyPackSize',
    safety_stock: '#batchPolicySafetyStock'
  };
  const fields = {};
  $$('[data-batch-policy-enable]').forEach(function (checkbox) {
    if (!checkbox.checked) return;
    const key = checkbox.dataset.batchPolicyEnable;
    const input = $(fieldInputs[key]);
    fields[key] = input ? input.value : '';
  });
  if ($('#batchPolicyWeightsEnabled').checked) {
    fields.velocity_weight_3 = weights[0] / 100;
    fields.velocity_weight_7 = weights[1] / 100;
    fields.velocity_weight_15 = weights[2] / 100;
    fields.velocity_weight_30 = weights[3] / 100;
  }
  const skuIds = Array.from(replenishmentSelectedSkuIds);
  if (TEAM_MODE) {
    const saved = await executeTeamCommand(function () {
      return Object.keys(fields).length ? teamGateway.batchSaveReplenishmentPolicy(skuIds, fields) : teamGateway.recomputeReplenishment(skuIds);
    }, '所选 SKU 参数已保存，并已重新计算补货建议。', 'replenishment');
    if (saved) closeModal('replenishmentBatchPolicyModal');
    return;
  }
  showToast('本地演示模式不保存批量补货参数。');
}

async function recomputeSelectedReplenishment() {
  const skuIds = Array.from(replenishmentSelectedSkuIds);
  if (!skuIds.length) return showToast('请先勾选需要重新计算的 SKU。');
  if (TEAM_MODE) {
    await executeTeamCommand(function () { return teamGateway.recomputeReplenishment(skuIds); }, '规则已按最新库存流水重新计算；复杂项目会在合并等待后自动请求 AI 分析。', 'replenishment');
    return;
  }
  renderReplenishment();
  showToast('已按当前数据重新计算所选 SKU。');
}

async function openBatchPurchaseDraft() {
  const rows = selectedReplenishmentItems().filter(function (item) { return integer(item.suggestedQty) > 0; });
  if (!rows.length) return showToast('所选 SKU 当前没有需要采购的建议量。');
  await openPurchaseEditor();
  draftPurchaseLines = rows.map(function (item) {
    const product = recommendationProduct(item);
    return { productId: product.id, quantity: integer(item.suggestedQty), unitCost: nonNegative(product.standardCost) };
  });
  setControlValue('#purchaseStatus', 'draft');
  setControlValue('#purchaseSupplier', '');
  renderPurchaseDraft();
  showToast('已生成 ' + rows.length + ' 条采购草稿明细；请核对单价、数量和供应商后再人工确认。');
}
async function handleReplenishmentPolicySubmit(event) {
  event.preventDefault();
  const product = productById($('#policyProductId').value);
  if (!product) return showToast('商品不存在。');
  const weights = [$('#policyWeight3'), $('#policyWeight7'), $('#policyWeight15'), $('#policyWeight30')].map(function (input) { return input.value === '' ? null : Number(input.value); });
  if (weights.some(function (value) { return value === null; }) && !weights.every(function (value) { return value === null; })) return showToast('SKU 独立权重需同时填写 3/7/15/30 天四项，或全部留空。');
  if (weights.every(function (value) { return value !== null; }) && (weights.some(function (value) { return !Number.isFinite(value) || value < 0; }) || Math.abs(weights.reduce(function (sum, value) { return sum + value; }, 0) - 100) > 0.001)) return showToast('SKU 独立权重必须为非负数，且合计等于 100%。');
  const policy = {
    id: '', productId: product.id, skuId: product.skuId || '', warehouseId: TEAM_MODE && teamGateway ? String(teamGateway.warehouseId) : currentWarehouseId(),
    leadTimeOverride: $('#policyLeadDays').value === '' ? null : integer($('#policyLeadDays').value),
    primaryWarehouse: $('#policyPrimaryWarehouse').value || null, targetDays: $('#policyTargetDays').value === '' ? null : integer($('#policyTargetDays').value),
    minOrderQty: $('#policyMoq').value === '' ? null : integer($('#policyMoq').value), packSize: $('#policyPackSize').value === '' ? null : integer($('#policyPackSize').value),
    safetyStockOverride: $('#policySafetyStock').value === '' ? null : integer($('#policySafetyStock').value),
    velocityWeight3: weights[0] == null ? undefined : weights[0] / 100,
    velocityWeight7: weights[1] == null ? undefined : weights[1] / 100,
    velocityWeight15: weights[2] == null ? undefined : weights[2] / 100,
    velocityWeight30: weights[3] == null ? undefined : weights[3] / 100
  };
  if (TEAM_MODE) {
    const saved = await executeTeamCommand(function () { return teamGateway.saveReplenishmentPolicy(product, policy); }, '补货参数已保存并重新计算。', 'replenishment');
    if (saved) closeModal('replenishmentPolicyModal');
    return;
  }
  const saved = commit(function (next) {
    const existing = next.replenishmentPolicies.find(function (item) { return item.productId === policy.productId && item.warehouseId === policy.warehouseId; });
    policy.id = existing ? existing.id : uid('policy');
    if (existing) next.replenishmentPolicies[next.replenishmentPolicies.indexOf(existing)] = policy; else next.replenishmentPolicies.push(policy);
  }, '补货参数已保存并重新计算。');
  if (saved) closeModal('replenishmentPolicyModal');
}
function updateStockHint() {
  const productId = $('#stockProduct').value;
  const balance = balanceFor(productId);
  setText('#stockHint', '当前已在库 ' + balance.onHand + '，锁定 ' + balance.reserved + '，可用 ' + Math.max(0, balance.onHand - balance.reserved) + '。');
}
function openReceiveEditor(purchaseId) {
  const eligibleOrders = state.purchaseOrders.filter(function (item) { return isPurchaseOpen(item) && item.lines.some(function (line) { return remainingPurchaseLine(line) > 0; }); });
  const order = eligibleOrders.find(function (item) { return item.id === purchaseId; }) || eligibleOrders[0];
  if (!order) return showToast('暂无可收货的采购单。');
  const warehouse = TEAM_MODE ? selectedWarehouse() : warehouseById(order.warehouseId || currentWarehouseId());
  if (!warehouse || warehouse.canReceive === false || warehouse.can_receive === false) return showToast('当前仓库未开放收货，不能办理采购入库。');
  $('#receiveForm').reset();
  $('#receivePurchaseId').innerHTML = eligibleOrders.map(function (item) {
    return '<option value="' + escapeHtml(item.id) + '">' + escapeHtml(item.number + ' · ' + item.supplier) + '</option>';
  }).join('');
  $('#receivePurchaseId').value = order.id;
  $('#receiveShipmentId').innerHTML = '<option value="">不指定物流单（按采购单收货）</option>' + (order.shipments || []).map(function (shipment) {
    return '<option value="' + escapeHtml(shipment.id) + '">' + escapeHtml(shipment.trackingNumber) + '</option>';
  }).join('');
  $('#receiveAt').value = localDateTime(new Date());
  renderReceiveLines();
  openModal('receiveModal');
}
function renderReceiveLines() {
  const order = state.purchaseOrders.find(function (item) { return item.id === $('#receivePurchaseId').value; });
  if (!order) {
    $('#receiveLineList').innerHTML = '<div class="last-value">请选择可收货的采购单。</div>';
    return;
  }
  $('#receiveIntro').textContent = order.number + ' · ' + order.supplier + '：可一次性登记该采购单所有商品。';
  const selectedShipmentId = $('#receiveShipmentId').value;
  $('#receiveShipmentId').innerHTML = '<option value="">不指定物流单（按采购单收货）</option>' + (order.shipments || []).map(function (shipment) {
    return '<option value="' + escapeHtml(shipment.id) + '">' + escapeHtml(shipment.trackingNumber) + '</option>';
  }).join('');
  $('#receiveShipmentId').value = selectedShipmentId;
  const lines = order.lines.filter(function (line) { return remainingPurchaseLine(line) > 0; });
  $('#receiveLineList').innerHTML = lines.length ? lines.map(function (line) {
    const product = productById(line.productId);
    const remaining = remainingPurchaseLine(line);
    return '<div class="line-list-item">' + productQuantityMedia(product || { name: '未知商品', sku: '' }, remaining) +
      '<label>本次收货<input data-receive-line-id="' + escapeHtml(line.id) + '" data-receive-remaining="' + remaining + '" type="number" min="0" max="' + remaining + '" step="1" value="0"></label></div>';
  }).join('') : '<div class="last-value">该采购单没有待收货商品。</div>';
  updateReceiveHint();
}
function updateReceiveHint() {
  const inputs = $$('#receiveLineList [data-receive-line-id]');
  const selected = inputs.filter(function (input) { return integer(input.value) > 0; });
  setText('#receiveHint', selected.length ? '已填写 ' + selected.length + ' 个商品的本次收货数量；确认后会自动减少在途并增加已在库。' : '请填写至少一个商品的本次收货数量；留空或填 0 的商品不会入库。');
}
function openReturnEditor(orderId) {
  const order = state.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || order.status !== 'shipped') return showToast('只有已出库订单可以办理退货入库。');
  const availableLines = order.lines.filter(function (line) { return returnableForLine(line) > 0; });
  if (!availableLines.length) return showToast('该订单所有商品都已完成退货，暂无可退数量。');
  $('#returnForm').reset();
  $('#returnOrderId').value = order.id;
  $('#returnIntro').textContent = order.number + ' · 完好商品回到库存；残损商品只登记，不增加可售库存。';
  $('#returnLine').innerHTML = availableLines.map(function (line) {
    const product = productById(line.productId);
    return '<option value="' + escapeHtml(line.id) + '">' + escapeHtml((product ? product.sku + ' · ' + product.name : '未知商品') + '（可退 ' + returnableForLine(line) + '）') + '</option>';
  }).join('');
  $('#returnAt').value = localDateTime(new Date());
  $('#returnQty').value = 1;
  updateReturnHint();
  openModal('returnModal');
}
function updateReturnHint() {
  const order = state.salesOrders.find(function (item) { return item.id === $('#returnOrderId').value; });
  const line = order && order.lines.find(function (item) { return item.id === $('#returnLine').value; });
  const remaining = line ? returnableForLine(line) : 0;
  $('#returnQty').max = remaining;
  const restock = $('#returnCondition').value !== 'damaged';
  setText('#returnHint', '该订单明细最多还可退货 ' + remaining + ' 件；' + (restock ? '确认后增加已在库。' : '残损商品不会增加可售库存。'));
}
function openSnapshotEditor(productId) {
  const monitoring = monitoredProducts(state);
  if (!monitoring.length) return showToast('请先添加竞品或开启本店商品对比。');
  $('#snapshotForm').reset();
  $('#snapshotProduct').value = monitoring.some(function (item) { return item.id === productId; }) ? productId : (state.selectedProductId || monitoring[0].id);
  $('#snapshotAt').value = localDateTime(new Date());
  fillSnapshotHint();
  openModal('snapshotModal');
  setTimeout(function () { if ($('#snapshotSold')) $('#snapshotSold').focus(); }, 0);
}
function fillSnapshotHint() {
  const productId = $('#snapshotProduct').value;
  const latest = latestPair(productId).latest;
  const advanced = $('#snapshotAdvanced');
  if (!latest) {
    if (advanced) advanced.open = true;
    setText('#lastValueHint', '尚无历史数据：首次请完整填写价格和销量，作为后续自动沿用的基准。');
    $('#snapshotPrice').value = '';
    $('#snapshotSold').value = '';
    $('#snapshotRating').value = '';
    $('#snapshotReviews').value = '';
    $('#snapshotLowReviews').value = '';
    $('#snapshotShopRating').value = '';
    return;
  }
  if (advanced) advanced.open = false;
  setText('#lastValueHint', '上次：' + formatDate(latest.at, true) + ' · ' + money(latest.price, latest.currency) + ' · 累计销量 ' + latest.sold + ' · 评价 ' + latest.reviews + '。本次只改销量即可。');
  $('#snapshotPrice').value = latest.price;
  $('#snapshotSold').value = latest.sold;
  $('#snapshotRating').value = latest.rating == null ? '' : latest.rating;
  $('#snapshotReviews').value = latest.reviews;
  $('#snapshotLowReviews').value = latest.lowReviews;
  $('#snapshotShopRating').value = latest.shopRating == null ? '' : latest.shopRating;
  if ($('#snapshotShippingType')) $('#snapshotShippingType').value = latest.shippingType || '';
}

function csvEscape(value) {
  const text = String(value == null ? '' : value);
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}
function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && quoted && next === '"') { cell += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') index += 1;
      row.push(cell); cell = '';
      if (row.some(function (item) { return item !== ''; })) rows.push(row);
      row = [];
    } else cell += char;
  }
  row.push(cell);
  if (row.some(function (item) { return item !== ''; })) rows.push(row);
  return rows;
}
function downloadText(filename, content, type) {
  const mime = type || 'text/csv;charset=utf-8';
  const prefix = mime.includes('json') ? '' : '\ufeff';
  const blob = new Blob([prefix + content], { type: mime });
  const anchor = document.createElement('a');
  anchor.href = URL.createObjectURL(blob);
  anchor.download = filename;
  anchor.click();
  setTimeout(function () { URL.revokeObjectURL(anchor.href); }, 1000);
}
function productCsvRows() {
  const headers = ['name', 'kind', 'sku', 'seller', 'market', 'currency', 'cost', 'safety_stock', 'status', 'url', 'purchase_url', 'image_url', 'monitoring_enabled', 'snapshot_at', 'price', 'sold', 'rating', 'reviews', 'low_reviews', 'shop_rating'];
  const rows = state.products.map(function (product) {
    const latest = latestPair(product.id).latest || {};
    return [
      product.name, product.kind, product.sku, product.seller, product.market, product.salesCurrency,
      product.standardCost, product.safetyStock, product.status, product.productUrl, product.purchaseUrl,
      exportableImageUrl(product.image), product.monitoringEnabled ? 'true' : 'false',
      latest.at || '', latest.price == null ? '' : latest.price, latest.sold == null ? '' : latest.sold,
      latest.rating == null ? '' : latest.rating, latest.reviews == null ? '' : latest.reviews,
      latest.lowReviews == null ? '' : latest.lowReviews, latest.shopRating == null ? '' : latest.shopRating
    ];
  });
  return [headers].concat(rows).map(function (row) { return row.map(csvEscape).join(','); }).join('\n');
}

async function saveProductFromForm(forceDraft) {
  const editId = $('#editProductId').value;
  const current = editId ? productById(editId) : null;
  const kind = $('#productKind').value;
  const requestedStatus = $('#productStatus').value;
  const draft = Boolean(forceDraft || requestedStatus === 'draft');
  const image = safeImageUrl(pendingProductImage || $('#productImageUrl').value);
  const skus = kind === 'own' ? readProductSkuDrafts() : [];
  const storeListings = kind === 'own' ? readStoreListingDrafts() : [];
  const primarySku = skus[0] || skuDraft();
  const product = normalizeProduct({
    id: editId || uid('product'),
    apiProductId: current ? current.apiProductId : '',
    apiCompetitorId: current ? current.apiCompetitorId : '',
    skuId: current ? current.skuId : '',
    imageId: current ? current.imageId : '',
    defaultSupplierId: current ? current.defaultSupplierId : '',
    skuCount: kind === 'own' ? skus.length : 0,
    name: $('#productName').value,
    kind: kind,
    sku: kind === 'own' ? primarySku.code : '',
    seller: $('#sellerName').value,
    sellerRating: kind === 'own' ? null : $('#sellerRating').value,
    sellerIsStar: kind === 'own' ? false : $('#sellerIsStar').checked,
    sellerType: kind === 'own' ? 'normal' : $('#sellerType').value,
    shippingType: kind === 'own' ? '' : $('#competitorShippingType').value,
    notes: kind === 'own' ? '' : $('#competitorNotes').value,
    market: $('#productMarket').value,
    salesCurrency: $('#productCurrency').value,
    costCurrency: $('#productCurrency').value,
    standardCost: kind === 'own' ? primarySku.cost : 0,
    safetyStock: kind === 'own' ? primarySku.safetyStock : 0,
    defaultSupplier: kind === 'own' ? $('#productSupplier').value : '',
    status: draft ? 'draft' : requestedStatus,
    productUrl: $('#productUrl').value,
    purchaseUrl: kind === 'own' ? $('#productPurchaseUrl').value : '',
    image: image,
    skus: skus,
    storeListings: storeListings,
    monitoringEnabled: kind !== 'own' || $('#productCompare').checked,
    needsReview: false,
    createdAt: current ? current.createdAt : new Date().toISOString(),
    updatedAt: new Date().toISOString()
  });
  const missing = productMissingFields(product, kind === 'own' ? primarySku.cost : 0);
  product.needsReview = missing.length > 0;
  if (missing.length) product.status = 'draft';
  if (kind === 'own') {
    const currentCatalogId = current && (current.catalogProductId || current.apiProductId || current.id);
    const existingCodes = state.products.filter(function (item) {
      return item.kind === 'own' && (item.catalogProductId || item.apiProductId || item.id) !== currentCatalogId;
    }).map(function (item) { return normalizeSku(item.sku); });
    if (skus.some(function (sku) { return sku.code && existingCodes.includes(normalizeSku(sku.code)); })) {
      return showToast('SKU 已存在，请使用唯一的本店 SKU 编码。');
    }
  }
  if (current && current.kind === 'own' && kind !== 'own' && hasBusinessReferences(current.id)) {
    return showToast('该商品已有库存或业务单据，只能停用，不能改为竞品。');
  }
  if (draft && current && current.kind === 'own' && hasBusinessReferences(current.id)) {
    return showToast('该商品已有库存或业务单据，不能改为草稿；可继续启用或设为停用。');
  }
  let initialSnapshot = null;
  try { if (!draft && !current && product.monitoringEnabled) initialSnapshot = snapshotFromForm('#firstSnapshot', product, false); }
  catch (error) { return showToast(error.message); }
  const successMessage = draft
    ? (missing.length ? '商品草稿已保存；补齐 ' + missing.join('、') + ' 后即可用于仓库业务。' : '商品草稿已保存。')
    : (missing.length ? '商品信息不完整，已自动保存为草稿。' : (current ? '商品已更新。' : '商品已添加。'));
  if (TEAM_MODE) {
    const savedTeam = await executeTeamCommand(function () {
      return teamGateway.saveProduct(product, initialSnapshot);
    }, successMessage, 'catalog');
    if (savedTeam) closeModal('productModal');
    return;
  }
  const saved = commit(function (next) {
    if (product.kind === 'own') {
      const catalogId = current ? (current.catalogProductId || current.id) : uid('catalog');
      const existing = next.products.filter(function (item) {
        return item.kind === 'own' && (item.catalogProductId || item.id) === catalogId;
      });
      const kept = new Set();
      skus.forEach(function (sku, index) {
        const match = existing.find(function (item) { return sku.id && String(item.id) === String(sku.id); }) || existing.find(function (item) { return normalizeSku(item.sku) === normalizeSku(sku.code); });
        const item = normalizeProduct(Object.assign({}, product, {
          id: match ? match.id : (index === 0 ? product.id : uid('product')), catalogProductId: catalogId, skuId: sku.id || (match ? match.skuId : ''),
          sku: sku.code, standardCost: sku.cost, safetyStock: sku.safetyStock, skuCount: skus.length,
          createdAt: match ? match.createdAt : product.createdAt
        }));
        kept.add(item.id);
        const position = next.products.findIndex(function (entry) { return entry.id === item.id; });
        if (position >= 0) next.products[position] = item; else next.products.push(item);
        ensureBalance(next, item.id);
        if (index === 0) product.id = item.id;
      });
      existing.filter(function (item) { return !kept.has(item.id); }).forEach(function (item) {
        if (hasBusinessReferences(item.id, next)) item.status = 'inactive';
        else next.products = next.products.filter(function (entry) { return entry.id !== item.id; });
      });
    } else {
      const index = next.products.findIndex(function (item) { return item.id === product.id; });
      if (index >= 0) next.products[index] = product; else next.products.push(product);
    }
    if (initialSnapshot) next.snapshots.push(initialSnapshot);
    if (!next.selectedProductId && product.status === 'active' && product.monitoringEnabled) next.selectedProductId = product.id;
    if (!product.needsReview) next.migrationIssues = next.migrationIssues.filter(function (issue) { return issue.productId !== product.id; });
  }, successMessage);
  if (saved) closeModal('productModal');
}
function handleProductSubmit(event) {
  event.preventDefault();
  saveProductFromForm(false);
}

async function handlePurchaseSubmit(event) {
  event.preventDefault();
  // Treat the currently typed tracking number as a pending logistics record.
  // Requiring a separate click on "add logistics" made the save button look
  // broken: the operator could see the number in the field while the payload
  // silently omitted it.  A shipment without per-SKU allocations is valid and
  // can be allocated later before a partial receipt.
  const pendingTrackingNumber = $('#purchaseTrackingNumber').value.trim();
  if (pendingTrackingNumber) {
    const duplicateTracking = draftPurchaseShipments.some(function (item) {
      return String(item.trackingNumber || '').trim().toLowerCase() === pendingTrackingNumber.toLowerCase();
    });
    if (duplicateTracking) return showToast('同一采购单的物流单号不能重复。');
    draftPurchaseShipments.push({ id: '', trackingNumber: pendingTrackingNumber, lines: [] });
    $('#purchaseTrackingNumber').value = '';
  }
  const number = $('#purchaseNumber').value.trim();
  if (number && state.purchaseOrders.some(function (item) { return item.id !== purchaseEditId && item.number.toLowerCase() === number.toLowerCase(); })) return showToast('采购单号不能重复。');
  const status = draftPurchaseLines.length ? $('#purchaseStatus').value : 'draft';
  const order = {
    id: purchaseEditId || uid('po'), number: number, supplier: $('#purchaseSupplier').value.trim(),
    purchaserId: $('#purchasePurchaser').value || '',
    warehouseId: currentWarehouseId(), status: status,
    orderedAt: $('#purchaseOrderedAt').value, expectedAt: $('#purchaseEta').value,
    extraCost: nonNegative($('#purchaseExtraCost').value), note: $('#purchaseNote').value.trim(),
    lines: draftPurchaseLines.map(function (line) {
      const product = productById(line.productId);
      return { id: line.purchaseLineId || uid('pol'), productId: line.productId, skuId: line.skuId || (product ? product.skuId : ''), currency: product ? product.costCurrency : 'CNY', orderedQty: integer(line.quantity), quantity: integer(line.quantity), receivedQty: line.receivedQty || 0, cancelledQty: 0, unitCost: nonNegative(line.unitCost) };
    }),
    shipments: draftPurchaseShipments.map(function (shipment) {
      return { id: shipment.id || '', trackingNumber: shipment.trackingNumber, lines: (shipment.lines || []).map(function (line) {
        const product = productById(line.productId);
        const purchaseLine = draftPurchaseLines.find(function (item) { return item.productId === line.productId; }) || {};
        return { purchaseLineId: line.purchaseLineId || purchaseLine.purchaseLineId || '', skuId: line.skuId || purchaseLine.skuId || (product && product.skuId), quantity: integer(line.quantity) };
      }).filter(function (line) { return line.quantity > 0; }) };
    }),
    createdAt: new Date().toISOString(), updatedAt: new Date().toISOString()
  };
  if (TEAM_MODE) {
    const savedTeam = await executeTeamCommand(
      function () { return purchaseEditId ? teamGateway.editPurchase(order) : teamGateway.createPurchase(order); },
      purchaseEditId ? '采购单已更新；已收货记录和库存流水保持不变。' : (status === 'draft' ? '采购草稿已保存，不计入在途。' : '采购单已创建，已自动计入在途。'),
      'purchase',
      {
        applyResult: function (savedPurchase) { return teamGateway.applyPurchaseOrderResult(savedPurchase); },
        refreshOnError: false
      }
    );
    if (savedTeam) closeModal('purchaseModal');
    return;
  }
  const saved = commit(function (next) { next.purchaseOrders.push(order); }, status === 'draft' ? '采购草稿已保存，不计入在途。' : '采购单已创建，已自动计入在途。');
  if (saved) closeModal('purchaseModal');
}
async function handleReceiveSubmit(event) {
  event.preventDefault();
  const warehouse = selectedWarehouse();
  if (!warehouse || warehouse.canReceive === false || warehouse.can_receive === false) return showToast('当前仓库未开放收货，不能办理采购入库。');
  const order = state.purchaseOrders.find(function (item) { return item.id === $('#receivePurchaseId').value; });
  const lines = $$('#receiveLineList [data-receive-line-id]').map(function (input) {
    const line = order && order.lines.find(function (item) { return item.id === input.dataset.receiveLineId; });
    return { id: input.dataset.receiveLineId, quantity: integer(input.value), unitCost: line ? line.unitCost : 0, remaining: integer(input.dataset.receiveRemaining) };
  }).filter(function (line) { return line.quantity > 0; });
  if (!order || !lines.length) return showToast('请至少填写一个商品的本次收货数量。');
  if (lines.some(function (line) { return line.quantity > line.remaining; })) return showToast('本次收货数量不能超过该商品的未收数量。');
  if (TEAM_MODE) {
    const savedTeam = await executeTeamCommand(function () {
      return teamGateway.receivePurchase(order, lines, $('#receiveShipmentId').value || null);
    }, '收货完成：在途已减少，库存已增加。', 'receipt');
    if (savedTeam) closeModal('receiveModal');
    return;
  }
  const saved = commit(function (next) {
    lines.forEach(function (line) {
      receivePurchaseOrder(next, order.id, line.id, line.quantity, new Date($('#receiveAt').value).toISOString(), $('#receiveNote').value.trim());
    });
  }, '收货完成：在途已减少，库存已增加。');
  if (saved) closeModal('receiveModal');
}
async function handleStockSubmit(event) {
  event.preventDefault();
  if (TEAM_MODE) {
    const product = productById($('#stockProduct').value);
    if (!product || !product.skuId) return showToast('请选择有效 SKU。');
    const savedTeam = await executeTeamCommand(function () {
      return teamGateway.adjustInventory(product, $('#stockOperation').value, $('#stockQuantity').value, $('#stockNote').value.trim());
    }, '库存调整已由服务器过账并记录流水。', 'inventory');
    if (savedTeam) closeModal('stockModal');
    return;
  }
  const saved = commit(function (next) {
    adjustInventory(next, $('#stockProduct').value, $('#stockOperation').value, $('#stockQuantity').value, new Date($('#stockAt').value).toISOString(), $('#stockNote').value.trim());
  }, '库存调整已过账并记录流水。');
  if (saved) closeModal('stockModal');
}
async function handleReturnSubmit(event) {
  event.preventDefault();
  const condition = $('#returnCondition').value;
  if (TEAM_MODE) {
    const order = state.salesOrders.find(function (item) { return item.id === $('#returnOrderId').value; });
    const line = order && order.lines.find(function (item) { return item.id === $('#returnLine').value; });
    if (!order || !line) return showToast('退货订单明细不存在。');
    const savedTeam = await executeTeamCommand(function () {
      return teamGateway.receiveReturn(order, line, $('#returnQty').value, condition, $('#returnNote').value.trim());
    }, condition === 'restock' ? '退货已验收入库，库存流水已生成。' : '残损退货已登记，不增加可售库存。', 'return');
    if (savedTeam) closeModal('returnModal');
    return;
  }
  const saved = commit(function (next) {
    receiveSalesReturn(next, $('#returnOrderId').value, $('#returnLine').value, $('#returnQty').value, new Date($('#returnAt').value).toISOString(), $('#returnNote').value.trim(), condition);
  }, condition === 'restock' ? '退货已入库，库存流水已生成。' : '残损退货已登记，不增加可售库存。');
  if (saved) closeModal('returnModal');
}
async function handleOrderSubmit(event) {
  event.preventDefault();
  const warehouse = selectedWarehouse();
  if (!warehouse || warehouse.canShip === false || warehouse.can_ship === false) return showToast('当前仓库未开放出库，不能创建或处理订单。');
  const number = $('#orderNumber').value.trim();
  const existingOrder = number && state.salesOrders.find(function (item) { return item.number.toLowerCase() === number.toLowerCase(); });
  if (existingOrder) {
    if (TEAM_MODE && !['shipped', 'cancelled'].includes(existingOrder.status)) {
      closeModal('orderModal');
      return showToast('该订单已在服务器保存，请在订单列表点击“确认并出库”继续。');
    }
    return showToast('订单号不能重复。');
  }
  const order = {
    id: uid('order'), number: number, platform: $('#orderPlatform').value,
    warehouseId: currentWarehouseId(),
    store: $('#orderStore').value.trim(), orderedAt: $('#orderAt').value ? new Date($('#orderAt').value).toISOString() : null,
    trackingNumber: $('#orderTracking').value.trim(), note: $('#orderNote').value.trim(),
    status: 'shortage', lines: draftOrderLines.map(function (line) {
      const product = productById(line.productId);
      return { id: uid('order-line'), productId: line.productId, skuId: product ? product.skuId : '', quantity: integer(line.quantity), reservedQty: 0, shippedQty: 0 };
    }),
    createdAt: new Date().toISOString(), updatedAt: new Date().toISOString()
  };
  if (TEAM_MODE) {
    let result = null;
    const savedTeam = await executeTeamCommand(async function () { result = await teamGateway.createOrder(order); return result; }, '', 'order');
    if (savedTeam) {
      closeModal('orderModal');
      showToast(result && result.shipped ? '订单已确认并一次完成出库。' : '订单已保存为库存不足，整单未锁库、未扣库。');
    }
    return;
  }
  let shipped = false;
  const saved = commit(function (next) {
    next.salesOrders.push(order);
    shipped = order.lines.length ? confirmAndShipOrder(next, order.id) : false;
  }, '');
  if (saved) {
    closeModal('orderModal');
    showToast(shipped ? '订单已确认并一次完成出库。' : (order.lines.length ? '订单已保留，但库存不足，未扣减任何库存。' : '订单信息不完整，已保存为草稿。'));
  }
}
async function handleSnapshotSubmit(event) {
  event.preventDefault();
  const product = productById($('#snapshotProduct').value);
  if (!product) return showToast('请选择监控商品。');
  let snapshot;
  try { snapshot = snapshotFromForm('#snapshot', product, true); }
  catch (error) { return showToast(error.message); }
  if (state.snapshots.some(function (item) { return item.productId === product.id && new Date(item.at).getTime() === new Date(snapshot.at).getTime(); })) {
    return showToast('同一商品同一时间已经有一条快照。');
  }
  if (TEAM_MODE) {
    const latest = latestPair(product.id).latest;
    const hasBaseline = Boolean(latest);
    const quickSalesOnly = hasBaseline && !snapshotAdvancedChanged(snapshot, latest);
    const savedTeam = await executeTeamCommand(function () {
      return quickSalesOnly ? teamGateway.saveQuickSalesSnapshot(product, snapshot) : teamGateway.saveSnapshot(product, snapshot);
    }, quickSalesOnly ? '销量已更新，其他字段已自动沿用上次数据。' : (hasBaseline ? '销量和高级字段已完整保存。' : '基准快照已保存。'), 'competitor');
    if (savedTeam) closeModal('snapshotModal');
    return;
  }
  const saved = commit(function (next) {
    next.snapshots.push(snapshot);
    next.selectedProductId = product.id;
  }, snapshotChange(product.id).pair.latest && snapshot.sold < snapshotChange(product.id).pair.latest.sold
    ? '销量已保存；累计值回退已标记为异常。'
    : (snapshotChange(product.id).pair.latest ? '销量已更新，其他公开数据已沿用上次记录。' : '基准快照已保存。'));
  if (saved) closeModal('snapshotModal');
}

async function handleAction(action, id) {
  if (action === 'toggle-profit-details') {
    if (expandedProfitSkuIds.has(id)) expandedProfitSkuIds.delete(id); else expandedProfitSkuIds.add(id);
    return renderProducts();
  }
  if (action === 'edit-store') return openStoreEditor(id);
  if (action === 'toggle-store') {
    const store = (state.stores || []).find(function (item) { return String(item.id) === String(id); });
    if (!store) return;
    return executeTeamCommand(function () { return teamGateway.saveStore(Object.assign({}, store, { is_active: store.is_active === false }), id); }, store.is_active === false ? '店铺已启用。' : '店铺已停用，历史数据已保留。', 'store');
  }
  if (action === 'delete-store') return askConfirm('确认删除这个店铺？已关联 SKU 或审计记录的店铺只能停用。', function () {
    return executeTeamCommand(function () { return teamGateway.deleteStore(id); }, '店铺已删除。', 'store');
  });
  if (action === 'edit-warehouse') return openWarehouseEditor(id);
  if (action === 'archive-warehouse' || action === 'activate-warehouse') {
    const active = action === 'activate-warehouse';
    const warehouse = warehouseById(id);
    if (!warehouse) return showToast('仓库不存在。');
    if (!active && activeWarehouses().length <= 1) return showToast('至少需要保留一个启用中的仓库。');
    return askConfirm((active ? '确认启用“' : '确认停用“') + warehouse.name + '”？历史库存和单据会继续保留。', function () {
      if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.setWarehouseActive(warehouse, active); }, active ? '仓库已启用。' : '仓库已停用。', 'warehouse_admin');
      const saved = commit(function (next) {
        const current = next.warehouses.find(function (item) { return item.id === id; });
        if (!current) throw new Error('仓库不存在。');
        current.active = active;
        current.updatedAt = new Date().toISOString();
        if (!active && next.ui.warehouseId === current.id) next.ui.warehouseId = next.warehouses.find(function (item) { return item.active; }).id;
      }, active ? '仓库已启用。' : '仓库已停用，历史数据已保留。');
      if (saved) renderWarehouseDirectory();
    });
  }
  if (action === 'manage-transfer-packages') return openTransferWorkflow(state.stockTransfers.find(function (item) { return item.id === id; }), 'packages');
  if (action === 'receive-transfer') return openTransferWorkflow(state.stockTransfers.find(function (item) { return item.id === id; }), 'receive');
  if (action === 'close-transfer-exception') return openTransferWorkflow(state.stockTransfers.find(function (item) { return item.id === id; }), 'exception');
  if (action === 'complete-transfer-with-exception') return openTransferCompletion(state.stockTransfers.find(function (item) { return item.id === id; }));
  if (action === 'dispatch-transfer') return askConfirm('确认发出这张调拨单？发出后会立即扣减调出仓库存。', function () {
    const transfer = state.stockTransfers.find(function (item) { return item.id === id; });
    const source = transfer && warehouseById(transfer.sourceWarehouseId || transfer.source_warehouse);
    if (!source || source.canShip === false || source.can_ship === false) return showToast('调出仓未开放出库，不能发出调拨。');
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.dispatchTransfer(transfer); }, '调拨已发出，目标仓确认后转入库存。', 'transfer');
    commit(function (next) {
      const localTransfer = next.stockTransfers.find(function (item) { return item.id === id; });
      dispatchTransfer(next, localTransfer);
    }, '调拨已发出，目标仓确认后转入库存。');
  });
  if (action === 'cancel-transfer') return askConfirm('确认取消这张调拨草稿？', function () {
    const transfer = state.stockTransfers.find(function (item) { return item.id === id; });
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.cancelTransfer(transfer); }, '调拨草稿已取消。', 'transfer');
    commit(function (next) { cancelTransfer(next, id); }, '调拨草稿已取消。');
  });
  if (action === 'edit-replenishment') return openReplenishmentPolicy(id);
  if (action === 'view-demand-detail') return openReplenishmentDemandDetail(id);
  if (action === 'reset-replenishment') return askConfirm('确认删除当前仓的自定义参数并恢复系统默认补货规则？', function () {
    const product = productById(id);
    if (!product) return showToast('商品不存在。');
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.deleteReplenishmentPolicy(product); }, '已恢复系统默认补货参数。', 'replenishment');
    commit(function (next) {
      const warehouseId = currentWarehouseId(next);
      next.replenishmentPolicies = next.replenishmentPolicies.filter(function (policy) { return !(policy.productId === id && policy.warehouseId === warehouseId); });
    }, '已恢复系统默认补货参数。');
  });
  if (action === 'create-purchase-from-replenishment') {
    const product = productById(id);
    const recommendation = replenishmentRecommendations().find(function (item) { return recommendationProduct(item) && recommendationProduct(item).id === id; });
    if (!product || !recommendation || !recommendation.suggestedQty) return showToast('当前没有需要采购的建议量。');
    await openPurchaseEditor();
    draftPurchaseLines = [{ productId: product.id, quantity: recommendation.suggestedQty, unitCost: product.standardCost }];
    const supplier = $('#purchaseSupplier');
    if (supplier) supplier.value = product.defaultSupplier || supplier.value;
    renderPurchaseDraft();
    return;
  }
  if (action === 'edit-product') return openProductEditor(id);
  if (action === 'add-own-monitoring') {
    const product = productById(id);
    if (!product || product.kind !== 'own') return;
    if (product.monitoringEnabled) return showToast('该本店商品已在竞品监控中。');
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.addOwnProductsToMonitoring([product.apiProductId || product.id]); }, '本店商品已加入竞品监控，可直接记录并对比销量。', 'catalog');
    return commit(function (next) { const item = productById(id, next); if (item) item.monitoringEnabled = true; }, '本店商品已加入竞品监控。');
  }
  if (action === 'remove-own-monitoring') {
    const product = productById(id);
    if (!product || product.kind !== 'own') return;
    return askConfirm('二次确认：将“' + product.name + '”移出竞品监控，并删除其监控快照？本店商品、SKU、库存、采购和订单都不会删除。', function () {
      if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.removeMonitoringProfile(product); }, '商品已移出竞品监控；本店商品和库存未受影响。', 'catalog');
      return commit(function (next) {
        const item = productById(id, next);
        if (item) item.monitoringEnabled = false;
        next.snapshots = next.snapshots.filter(function (snapshot) { return snapshot.productId !== id; });
      }, '商品已移出竞品监控。');
    });
  }
  if (action === 'delete-competitor') {
    const product = productById(id);
    if (!product || product.kind === 'own') return;
    return askConfirm('二次确认：彻底删除竞品“' + product.name + '”及其全部监控快照？此操作不可恢复。', function () {
      if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.deleteProduct(product); }, '竞品及其监控快照已彻底删除。', 'catalog');
      return commit(function (next) {
        next.products = next.products.filter(function (item) { return item.id !== id; });
        next.snapshots = next.snapshots.filter(function (snapshot) { return snapshot.productId !== id; });
      }, '竞品及其监控快照已彻底删除。');
    });
  }
  if (action === 'open-warehouse') {
    setRoute('warehouse', 'inventory');
    setTimeout(function () {
      const select = $('#movementProduct');
      if (select) select.value = id;
      renderMovements();
    }, 0);
    return;
  }
  if (action === 'add-snapshot') return openSnapshotEditor(id);
  if (action === 'adjust-stock') return openStockEditor(id);
  if (action === 'view-movements') {
    $('#movementProduct').value = id;
    renderMovements();
    document.querySelector('.movement-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  if (action === 'delete-stock-balance') {
    const product = productById(id);
    const balance = balanceFor(id);
    if (!product || !balance.apiBalanceId) return showToast('库存记录不存在或尚未同步。');
    return askConfirm('二次确认：仅彻底删除“' + product.name + '”在当前仓的这条库存记录及该 SKU 在当前仓的库存流水；不会删除其他商品或其他 SKU。此操作不可恢复。', function () {
      return executeTeamCommand(function () { return teamGateway.deleteStockBalance(balance, true); }, '当前 SKU 在当前仓的库存记录及流水已彻底删除。', 'inventory');
    });
  }
  if (action === 'revoke-movement') {
    const movement = state.inventoryMovements.find(function (item) { return item.id === id; });
    if (!movement || movement.isReversed) return showToast('该流水已撤回或不存在。');
    return askConfirm('确认撤回这笔库存流水？系统会新增一笔反向冲销流水，原流水将永久保留。', function () {
      return executeTeamCommand(function () { return teamGateway.revokeStockLedger(movement, '用户在库存流水中撤回'); }, '库存流水已撤回，系统已生成反向冲销记录。', 'inventory');
    });
  }
  if (action === 'activate-product' || action === 'deactivate-product') {
    const active = action === 'activate-product';
    const current = productById(id);
    if (active && current) {
      const missing = productMissingFields(current, current.standardCost);
      if (current.needsReview || missing.length) {
        showToast('启用前请先完善：' + (missing.length ? missing.join('、') : '商品资料') + '。');
        openProductEditor(id);
        return;
      }
    }
    if (TEAM_MODE && current) {
      return executeTeamCommand(function () { return teamGateway.setProductActive(current, active); }, active ? '商品已启用。' : '商品已停用，历史单据和库存均已保留。', 'catalog');
    }
    return commit(function (next) {
      const product = productById(id, next);
      if (product) { product.status = active ? 'active' : 'inactive'; product.needsReview = false; product.updatedAt = new Date().toISOString(); }
    }, active ? '商品已启用。' : '商品已停用，历史单据和库存均已保留。');
  }
  if (action === 'delete-product') {
    const product = productById(id);
    if (!product) return;
    if (TEAM_MODE && product.kind === 'own') {
      const skuCopy = product.skuCount > 1 ? '及其 ' + product.skuCount + ' 个 SKU' : '及其 SKU';
      if (product.status === 'inactive') {
        return askConfirm('二次确认：彻底删除已停用商品“' + product.name + '”' + skuCopy + '，以及关联库存、流水、采购、订单和快照数据？此操作不可恢复。', function () {
          return executeTeamCommand(function () { return teamGateway.deleteProduct(product, true); }, '已停用商品及关联数据已彻底删除。', 'catalog');
        });
      }
      return askConfirm('确认彻底删除“' + product.name + '”' + skuCopy + '？有业务记录的商品请先停用，再进行二次确认删除。', function () {
        return executeTeamCommand(function () { return teamGateway.deleteProduct(product); }, '商品及其 SKU 已删除。', 'catalog');
      });
    }
    // Competitor snapshots are dependent records and the API deletes them with
    // the selected competitor.  Do not block this operation merely because the
    // competitor already has snapshots; that left the Delete button unusable.
    if (TEAM_MODE && product.kind !== 'own') {
      return askConfirm('二次确认：彻底删除竞品“' + product.name + '”及其全部监控快照？此操作不可恢复。', function () {
        return executeTeamCommand(function () { return teamGateway.deleteProduct(product); }, '竞品及其监控快照已彻底删除。', 'catalog');
      });
    }
    if (hasBusinessReferences(id) || productSnapshots(id).length) {
      if (product.status !== 'inactive') {
        return askConfirm('该商品已有历史记录，不能硬删除。是否改为停用？', function () {
          if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.setProductActive(product, false); }, '商品已停用，历史数据已保留。', 'catalog');
          commit(function (next) { productById(id, next).status = 'inactive'; }, '商品已停用，历史数据已保留。');
        });
      }
      return showToast('该商品已有业务或快照记录，只能停用，不能删除。');
    }
    return askConfirm('确认彻底删除“' + product.name + '”？此操作不可撤销。', function () {
      if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.deleteProduct(product); }, '竞品已删除。', 'catalog');
      commit(function (next) {
        next.products = next.products.filter(function (item) { return item.id !== id; });
        next.inventoryBalances = next.inventoryBalances.filter(function (item) { return item.productId !== id; });
      }, '商品已删除。');
    });
  }
  if (action === 'submit-purchase') {
    const teamOrder = state.purchaseOrders.find(function (item) { return item.id === id; });
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.submitPurchase(teamOrder); }, '采购单已确认，开始计入在途。', 'purchase');
    return commit(function (next) {
    const order = next.purchaseOrders.find(function (item) { return item.id === id; });
    if (!order || order.status !== 'draft') throw new Error('采购单不是草稿状态。');
    order.status = 'ordered'; order.updatedAt = new Date().toISOString();
    }, '采购单已确认，开始计入在途。');
  }
  if (action === 'edit-purchase') {
    const order = state.purchaseOrders.find(function (item) { return item.id === id; });
    if (!order) return;
    return openPurchaseEditor(order).catch(handleTeamError);
  }
  if (action === 'delete-purchase') {
    const teamOrder = state.purchaseOrders.find(function (item) { return item.id === id; });
    if (!teamOrder || teamOrder.status !== 'draft') return showToast('只有草稿采购单可以删除；已下单的采购请使用取消余量。');
    return askConfirm('确认彻底删除采购草稿“' + teamOrder.number + '”？此操作不可撤销。', function () {
      if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.deletePurchase(teamOrder); }, '采购草稿已删除。', 'purchase');
      return commit(function (next) {
        next.purchaseOrders = next.purchaseOrders.filter(function (item) { return item.id !== id; });
      }, '采购草稿已删除。');
    });
  }
  if (action === 'transit-purchase') {
    if (TEAM_MODE) return showToast('团队版采购单确认后已直接计入在途。');
    return commit(function (next) {
    const order = next.purchaseOrders.find(function (item) { return item.id === id; });
    if (!order || order.status !== 'ordered') throw new Error('采购单当前不能标记在途。');
    order.status = 'transit'; order.updatedAt = new Date().toISOString();
    }, '采购单已标记为在途。');
  }
  if (action === 'receive-purchase') return openReceiveEditor(id);
  if (action === 'cancel-purchase') {
    const teamOrder = state.purchaseOrders.find(function (item) { return item.id === id; });
    return askConfirm('确认取消该采购单所有未收数量？已收货库存不会回退。', function () {
      if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.cancelPurchase(teamOrder); }, '采购余量已取消，在途已归零。', 'purchase');
      commit(function (next) {
        const order = next.purchaseOrders.find(function (item) { return item.id === id; });
        if (!order || !isPurchaseOpen(order)) throw new Error('采购单当前不能取消。');
        order.lines.forEach(function (line) { line.cancelledQty += remainingPurchaseLine(line); });
        const received = order.lines.reduce(function (sum, line) { return sum + integer(line.receivedQty); }, 0);
        order.status = received > 0 ? 'completed' : 'cancelled';
        order.updatedAt = new Date().toISOString();
      }, '采购余量已取消，在途已归零。');
    });
  }
  if (action === 'reserve-order') {
    const teamOrder = state.salesOrders.find(function (item) { return item.id === id; });
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.allocateOrder(teamOrder); }, '库存已整单锁定，订单进入拣货。', 'order');
    let reserved = false;
    const saved = commit(function (next) { reserved = reserveOrder(next, id); }, '');
    if (saved) showToast(reserved ? '库存已整单锁定，订单进入拣货。' : '库存仍不足，未产生任何部分锁定。');
    return;
  }
  if (action === 'assign-order-warehouse' || action === 'change-order-warehouse') {
    if (!TEAM_MODE || !teamGateway) return showToast('请在团队数据模式下选择服务器仓库。');
    const order = state.salesOrders.find(function (item) { return item.id === id; });
    return openOrderWarehouseSelector(order, action === 'change-order-warehouse');
  }
  if (action === 'confirm-ship-order') return askConfirm('只需这一次确认：库存足够时，系统将整单校验、扣库并生成出库流水。', function () {
    const warehouse = selectedWarehouse();
    if (!warehouse || warehouse.canShip === false || warehouse.can_ship === false) return showToast('当前仓库未开放出库，不能确认出库。');
    if (TEAM_MODE) {
      const order = state.salesOrders.find(function (item) { return item.id === id; });
      return executeTeamCommand(function () { return teamGateway.confirmAndShipOrder(order); }, '订单已确认并出库。', 'order');
    }
    let shipped = false;
    const saved = commit(function (next) { shipped = confirmAndShipOrder(next, id); }, '');
    if (saved) showToast(shipped ? '订单已确认并出库。' : '库存不足，订单保留在缺货状态，未扣减任何库存。');
  });
  if (action === 'advance-order') {
    const teamOrder = state.salesOrders.find(function (item) { return item.id === id; });
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.advanceOrder(teamOrder); }, teamOrder && teamOrder.apiStatus === 'allocated' ? '拣货已完成，订单进入复核。' : '复核已完成，订单可以出库。', 'order');
    return commit(function (next) {
    const order = next.salesOrders.find(function (item) { return item.id === id; });
    if (!order) throw new Error('订单不存在。');
    if (order.status === 'picking') order.status = 'review';
    else if (order.status === 'review') order.status = 'ready';
    else throw new Error('订单当前不能推进。');
    order.updatedAt = new Date().toISOString();
    }, '订单状态已更新。');
  }
  if (action === 'ship-order') return askConfirm('确认订单已复核并完成出库？库存和锁定将同时扣减。', function () {
    if (TEAM_MODE) {
      const order = state.salesOrders.find(function (item) { return item.id === id; });
      return executeTeamCommand(function () { return teamGateway.shipOrder(order); }, '订单已出库，库存流水已生成。', 'order');
    }
    commit(function (next) { shipOrder(next, id); }, '订单已出库，库存流水已生成。');
  });
  if (action === 'return-order') return openReturnEditor(id);
  if (action === 'cancel-order') return askConfirm('确认取消订单并释放已锁定库存？', function () {
    if (TEAM_MODE) {
      const order = state.salesOrders.find(function (item) { return item.id === id; });
      return executeTeamCommand(function () { return teamGateway.cancelOrder(order); }, '订单已取消，锁定库存已释放。', 'order');
    }
    commit(function (next) { cancelOrder(next, id); }, '订单已取消，锁定库存已释放。');
  });
  if (action === 'restore-order-fulfillment') {
    const order = state.salesOrders.find(function (item) { return item.id === id; });
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.restoreOrderFulfillment(order); }, '已恢复 ERP 履约，请重新选择仓库并锁库。', 'order');
    return showToast('本地演示模式不支持恢复履约。');
  }
  if (action === 'view-transit-sources') return openTransitSources(id);
  if (action === 'delete-snapshot') return askConfirm('确认删除这条快照？趋势会重新计算。', function () {
    if (TEAM_MODE) {
      const snapshot = state.snapshots.find(function (item) { return item.id === id; });
      return executeTeamCommand(function () { return teamGateway.deleteSnapshot(snapshot); }, '快照已删除，趋势已重新计算。', 'competitor');
    }
    commit(function (next) { next.snapshots = next.snapshots.filter(function (item) { return item.id !== id; }); }, '快照已删除。');
  });
}

function bindEvents() {
  document.addEventListener('click', function (event) {
    const sideLink = event.target.closest('[data-side-link]');
    if (sideLink) return handleSideLink(sideLink);
    const moduleButton = event.target.closest('[data-module]');
    if (moduleButton) return setRoute(moduleButton.dataset.module);
    const warehouseTab = event.target.closest('[data-warehouse-tab]');
    if (warehouseTab) return setRoute('warehouse', warehouseTab.dataset.warehouseTab);
    const competitorTab = event.target.closest('[data-competitor-tab]');
    if (competitorTab) return setRoute('analytics', competitorTab.dataset.competitorTab);
    const productChip = event.target.closest('[data-product-filter]');
    if (productChip) {
      productFilter = productChip.dataset.productFilter;
      return setRoute('products');
    }
    const purchaseChip = event.target.closest('[data-purchase-filter]');
    if (purchaseChip) {
      purchaseFilter = purchaseChip.dataset.purchaseFilter;
      return setRoute('warehouse', 'purchase');
    }
    const transferChip = event.target.closest('[data-transfer-filter]');
    if (transferChip) {
      transferFilter = transferChip.dataset.transferFilter;
      return setRoute('warehouse', 'transfers');
    }
    const orderChip = event.target.closest('[data-order-filter]');
    if (orderChip) {
      orderFilter = orderChip.dataset.orderFilter;
      return setRoute('warehouse', 'orders');
    }
    const chartTab = event.target.closest('[data-metric]');
    if (chartTab) {
      chartMetric = chartTab.dataset.metric;
      $$('[data-metric]').forEach(function (node) { node.classList.toggle('active', node === chartTab); });
      return renderChart();
    }
    const warehouseSwitch = event.target.closest('[data-warehouse-switch]');
    if (warehouseSwitch) return switchWarehouse(warehouseSwitch.dataset.warehouseSwitch);
    const selectionKeyword = event.target.closest('[data-selection-keyword-index]');
    if (selectionKeyword) return chooseSelectionKeyword(Number(selectionKeyword.dataset.selectionKeywordIndex));
    const selectionImport = event.target.closest('[data-selection-import-index]');
    if (selectionImport) return importSelectionProduct(Number(selectionImport.dataset.selectionImportIndex));
    const warehouseChoice = event.target.closest('[data-choose-order-warehouse]');
    if (warehouseChoice) return chooseOrderWarehouse(warehouseChoice.dataset.chooseOrderWarehouse);
    const action = event.target.closest('[data-action]');
    if (action) return handleAction(action.dataset.action, action.dataset.id).catch(handleTeamError);
    const creatorOpen = event.target.closest('[data-creator-open]');
    if (creatorOpen) return openCreatorDetail(creatorOpen.dataset.creatorOpen);
    const creatorEdit = event.target.closest('[data-creator-edit]');
    if (creatorEdit) return openCreatorEditor(creatorEdit.dataset.creatorEdit);
    const creatorArchive = event.target.closest('[data-creator-archive]');
    if (creatorArchive) return askConfirm('确认归档该达人档案？历史合作记录会保留。', async function () { await teamGateway.setCreatorArchived(creatorArchive.dataset.creatorArchive, true); await loadCreators(); });
    const creatorRestore = event.target.closest('[data-creator-restore]');
    if (creatorRestore) return teamGateway.setCreatorArchived(creatorRestore.dataset.creatorRestore, false).then(loadCreators).catch(handleTeamError);
    const planHistory = event.target.closest('[data-profit-plan-history]');
    if (planHistory) return openProfitPlanHistory(planHistory.dataset.profitPlanHistory);
    const planRecalculate = event.target.closest('[data-profit-plan-recalculate]');
    if (planRecalculate) return prepareProfitPlanRecalculation(planRecalculate.dataset.profitPlanRecalculate);
    const versionRecalculate = event.target.closest('[data-profit-version-recalculate]');
    if (versionRecalculate && profitPlanState.active) return prepareProfitPlanRecalculation(profitPlanState.active.id, versionRecalculate.dataset.profitVersionRecalculate);
    const snapshotButton = event.target.closest('[data-profit-snapshot]');
    if (snapshotButton) {
      const version = (profitPlanState.versions || []).find(function (row) { return String(row.id) === String(snapshotButton.dataset.profitSnapshot); });
      if (!version) return showToast('历史版本快照不存在。');
      $('#profitPlanSnapshot').hidden = false;
      $('#profitPlanSnapshot').textContent = JSON.stringify({ input: version.input_snapshot, exchange_rate: version.exchange_rate_snapshot, rule_version: version.rule_version, result: version.result_snapshot }, null, 2);
      return;
    }
    const planArchive = event.target.closest('[data-profit-plan-archive]');
    if (planArchive) return askConfirm('确认归档该利润方案？历史版本会保留。', async function () {
      await teamGateway.setProfitPlanArchived(planArchive.dataset.profitPlanArchive, true);
      profitPlanState.loaded = false; await loadProfitPlans();
    });
    const planRestore = event.target.closest('[data-profit-plan-restore]');
    if (planRestore) return teamGateway.setProfitPlanArchived(planRestore.dataset.profitPlanRestore, false).then(function () { profitPlanState.loaded = false; return loadProfitPlans(); }).catch(handleTeamError);
    const close = event.target.closest('[data-close]');
    if (close) return closeModal(close.dataset.close);
    const removePurchase = event.target.closest('[data-remove-purchase-line]');
    if (removePurchase) {
      draftPurchaseLines = draftPurchaseLines.filter(function (line) { return line.productId !== removePurchase.dataset.removePurchaseLine; });
      return renderPurchaseDraft();
    }
    const removeOrder = event.target.closest('[data-remove-order-line]');
    if (removeOrder) {
      draftOrderLines = draftOrderLines.filter(function (line) { return line.productId !== removeOrder.dataset.removeOrderLine; });
      return renderOrderDraft();
    }
    const removeTransfer = event.target.closest('[data-remove-transfer-line]');
    if (removeTransfer) {
      draftTransferLines = draftTransferLines.filter(function (line) { return line.productId !== removeTransfer.dataset.removeTransferLine; });
      draftTransferPackages.forEach(function (pack) { delete pack.quantities[removeTransfer.dataset.removeTransferLine]; });
      return renderTransferDraft();
    }
    const removeTransferPackage = event.target.closest('[data-remove-transfer-package]');
    if (removeTransferPackage) {
      draftTransferPackages.splice(Number(removeTransferPackage.dataset.removeTransferPackage), 1);
      return renderTransferPackageDraft();
    }
    const removeProductSku = event.target.closest('[data-remove-product-sku]');
    if (removeProductSku) {
      draftStoreListings = readStoreListingDrafts();
      draftProductSkus = readProductSkuDrafts();
      draftProductSkus.splice(Number(removeProductSku.dataset.removeProductSku), 1);
      return renderProductSkuEditor();
    }
  });
  if ($('#addStore')) $('#addStore').addEventListener('click', function () { openStoreEditor(''); });
  if ($('#storeForm')) $('#storeForm').addEventListener('submit', saveStoreFromForm);
  if ($('#openCreatorModal')) $('#openCreatorModal').addEventListener('click', function () { openCreatorEditor(''); });
  if ($('#creatorForm')) $('#creatorForm').addEventListener('submit', saveCreatorFromForm);
  if ($('#creatorActivityForm')) $('#creatorActivityForm').addEventListener('submit', saveCreatorActivityFromForm);
  if ($('#creatorActivityType')) $('#creatorActivityType').addEventListener('change', configureCreatorActivityForm);
  if ($('#refreshCreators')) $('#refreshCreators').addEventListener('click', loadCreators);
  if ($('#creatorSearch')) $('#creatorSearch').addEventListener('change', loadCreators);
  if ($('#creatorStageFilter')) $('#creatorStageFilter').addEventListener('change', loadCreators);
  if ($('#creatorArchivedFilter')) $('#creatorArchivedFilter').addEventListener('change', loadCreators);
  if ($('#profitPlanSearch')) $('#profitPlanSearch').addEventListener('change', function () { profitPlanState.loaded = false; loadProfitPlans(); });
  if ($('#profitPlanStoreFilter')) $('#profitPlanStoreFilter').addEventListener('change', function () { profitPlanState.loaded = false; loadProfitPlans(); });
  if ($('#profitPlanStatusFilter')) $('#profitPlanStatusFilter').addEventListener('change', function () { profitPlanState.loaded = false; loadProfitPlans(); });
  window.addEventListener('dongbo-profit-plans-saved', function () { profitPlanState.loaded = false; if (profitView === 'plans') loadProfitPlans(); });
  $$('.modal-backdrop').forEach(function (backdrop) {
    backdrop.addEventListener('mousedown', function (event) { if (event.target === backdrop) closeModal(backdrop.id); });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      const open = $('.modal-backdrop.open');
      if (open) closeModal(open.id);
      else if ($('#confirmBar').classList.contains('show')) closeConfirm();
      else closeSidebar();
    }
  });
  if ($('#sidebarToggle')) $('#sidebarToggle').addEventListener('click', toggleSidebar);
  if ($('#sidebarScrim')) $('#sidebarScrim').addEventListener('click', closeSidebar);
  $('#runtimeStateButton').addEventListener('click', function () { renderRuntimeState(); openModal('sessionModal'); });
  $('#retryConnection').addEventListener('click', function () { refreshTeamState('团队数据已重新连接。'); });
  $('#downloadLocalBackup').addEventListener('click', function () {
    if (TEAM_MODE) return;
    downloadText(
      '东铂跨境-完整备份-' + today() + '.json',
      JSON.stringify(state, null, 2),
      'application/json;charset=utf-8'
    );
    showToast('完整 JSON 备份已下载，请妥善保存。');
  });
  $('#chooseLocalBackup').addEventListener('click', function () {
    if (!TEAM_MODE) return;
    if (!teamAuthenticated()) return showToast('请先登录团队账号。');
    if (!teamMigrationAllowed()) return showToast(teamGateway.online === false ? '当前离线只读，不能迁移。' : '只有管理员或经理可以迁移数据。');
    $('#localBackupFile').click();
  });
  $('#localBackupFile').addEventListener('change', async function (event) {
    const file = event.target.files[0];
    event.target.value = '';
    clearMigrationPreview();
    if (!TEAM_MODE || !file) return;
    if (file.size > 20 * 1024 * 1024) return showToast('备份文件超过 20 MB，请先检查文件是否正确。');
    teamBusy = true;
    renderRuntimeState();
    try {
      const source = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
      pendingMigrationSource = source;
      pendingMigrationPreview = await teamGateway.validateLocalImport(source);
      renderMigrationPreview(pendingMigrationPreview);
      showToast(pendingMigrationPreview.ready ? '预检通过，请核对数量和警告后确认导入。' : '预检未通过，请根据红色提示修正备份或目标组织。');
    } catch (error) {
      pendingMigrationSource = null;
      pendingMigrationPreview = null;
      handleTeamError(error && error.name === 'SyntaxError' ? new Error('无法解析 JSON 备份，请重新导出完整备份。') : error);
    } finally {
      teamBusy = false;
      renderRuntimeState();
    }
  });
  $('#commitLocalMigration').addEventListener('click', async function () {
    if (!pendingMigrationSource || !pendingMigrationPreview || !pendingMigrationPreview.ready) {
      return showToast('请先选择备份并完成预检。');
    }
    const imported = await executeTeamCommand(function () {
      return teamGateway.commitLocalImport(pendingMigrationSource, pendingMigrationPreview.source_hash);
    }, '本机商品、竞品、快照与期初库存已导入团队数据库。', 'migration');
    if (imported) {
      clearMigrationPreview();
      renderRuntimeState();
    }
  });
  $('#teamLoginForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    if (!TEAM_MODE || teamBusy) return;
    teamBusy = true;
    $('#teamLoginButton').disabled = true;
    renderRuntimeState();
    try {
      clearMigrationPreview();
      const currentUi = clone(state.ui);
      const loaded = await teamGateway.login($('#teamUsername').value.trim(), $('#teamPassword').value);
      if (loaded && loaded.email_verification_required) {
        ownerLoginChallengeId = loaded.challenge_id;
        $('#teamPassword').value = '';
        renderRuntimeState();
        showToast('验证码已发送到主账号邮箱。');
        return;
      }
      state = loaded ? normalizeV5(loaded) : emptyState();
      state.ui = currentUi;
      teamLastSyncedAt = loaded ? new Date().toISOString() : '';
      $('#teamPassword').value = '';
      render();
      showToast('登录成功，内部数据已同步。');
    } catch (error) {
      handleTeamError(error);
    } finally {
      teamBusy = false;
      $('#teamLoginButton').disabled = false;
      renderRuntimeState();
    }
  });
  $('#ownerVerificationForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    if (!TEAM_MODE || teamBusy || !ownerLoginChallengeId) return;
    teamBusy = true;
    $('#verifyOwnerLoginButton').disabled = true;
    renderRuntimeState();
    try {
      const currentUi = clone(state.ui);
      const loaded = await teamGateway.verifyOwnerLogin(ownerLoginChallengeId, $('#ownerLoginCode').value.trim());
      ownerLoginChallengeId = '';
      $('#ownerLoginCode').value = '';
      state = normalizeV5(loaded);
      state.ui = currentUi;
      teamLastSyncedAt = new Date().toISOString();
      render();
      showToast('主账号验证成功，数据已同步。');
    } catch (error) { handleTeamError(error); }
    finally { teamBusy = false; $('#verifyOwnerLoginButton').disabled = false; renderRuntimeState(); }
  });
  $('#cancelOwnerVerification').addEventListener('click', function () {
    ownerLoginChallengeId = '';
    $('#ownerLoginCode').value = '';
    renderRuntimeState();
  });
  $('#teamWarehouse').addEventListener('change', async function () {
    if (!TEAM_MODE || teamBusy) return;
    clearMigrationPreview();
    const currentUi = clone(state.ui);
    teamBusy = true;
    renderRuntimeState();
    try {
      state = normalizeV5(await teamGateway.selectWarehouse(this.value));
      state.ui = currentUi;
      teamLastSyncedAt = new Date().toISOString();
      render();
      showToast('已切换仓库并重新计算在途、库存和订单。');
    } catch (error) { handleTeamError(error); }
    finally { teamBusy = false; renderRuntimeState(); }
  });
  $('#refreshTeamData').addEventListener('click', function () { refreshTeamState('团队数据已刷新。'); });
  $('#teamLogout').addEventListener('click', function () {
    if (!TEAM_MODE) return;
    clearMigrationPreview();
    teamGateway.clearSession();
    state = emptyState();
    restoreUiPreferences();
    render();
    renderRuntimeState();
    showToast('已退出团队账号，本页没有切回本机业务数据。');
  });
  $('#openAccountManager').addEventListener('click', function () {
    openInternalAccountManager().catch(handleTeamError);
  });
  $('#openIntegrations').addEventListener('click', function () {
    openIntegrationManager().catch(handleTeamError);
  });
  $('#openSelectionConfig').addEventListener('click', function () {
    openAlphaShopConfiguration().catch(handleTeamError);
  });
  $('#alphashopConfigForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    try {
      const payload = {
        api_base_url: $('#alphashopApiBaseUrl').value.trim(),
        enabled: $('#alphashopEnabled').checked,
        analysis_provider: $('#alphashopAnalysisProvider').value || null,
        analysis_enabled: $('#alphashopAnalysisEnabled').checked && Boolean($('#alphashopAnalysisProvider').value)
      };
      const accessKey = $('#alphashopAccessKey').value;
      const secretKey = $('#alphashopSecretKey').value;
      if (accessKey) payload.access_key = accessKey;
      if (secretKey) payload.secret_key = secretKey;
      alphashopConfig = await teamGateway.saveAlphaShopConfig(payload);
      $('#alphashopAccessKey').value = '';
      $('#alphashopSecretKey').value = '';
      selectionState.statusLoaded = false;
      await loadProductSelectionStatus();
      renderIntegrationManager();
      showToast('AlphaShop 选品配置已加密保存。');
    } catch (error) { handleTeamError(error); }
  });
  $('#testAlphaShopConfig').addEventListener('click', async function () {
    if (!window.confirm('测试会真实调用一次 AlphaShop 选品接口，可能消耗接口额度。是否继续？')) return;
    try {
      const result = await teamGateway.testAlphaShopConfig();
      showToast('选品接口连接成功：已收到 ' + Number(result.keyword_count || 0) + ' 个候选关键词。');
    } catch (error) { handleTeamError(error); }
  });
  $('#startTikTokAuthorization').addEventListener('click', async function () {
    try {
      const result = await teamGateway.startTikTokAuthorization($('#tiktokAuthorizeRegion').value);
      if (!result || !result.authorization_url) throw new Error('授权地址生成失败。');
      window.open(result.authorization_url, '_blank', 'noopener');
      showToast('已打开 TikTok Shop 授权页面；完成授权后返回此处刷新状态。');
    } catch (error) { handleTeamError(error); }
  });
  $('#tiktokConnectionRows').addEventListener('click', async function (event) {
    const button = event.target.closest('[data-tiktok-action]');
    if (!button) return;
    try {
      if (button.dataset.tiktokAction === 'disconnect') await teamGateway.disconnectTikTokConnection(button.dataset.tiktokId);
      else await teamGateway.refreshTikTokConnection(button.dataset.tiktokId);
      await openIntegrationManager();
      showToast(button.dataset.tiktokAction === 'disconnect' ? '店铺已解绑。' : '店铺令牌已刷新。');
    } catch (error) { handleTeamError(error); }
  });
  $('#aiProviderForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    try {
      let defaultParameters = {};
      try {
        defaultParameters = JSON.parse($('#aiProviderParameters').value || '{}');
      } catch (_) { return showToast('请求参数必须是合法的 JSON 对象。'); }
      if (!defaultParameters || Array.isArray(defaultParameters) || typeof defaultParameters !== 'object') {
        return showToast('请求参数必须是 JSON 对象。');
      }
      const id = $('#aiProviderId').value;
      const payload = {
        name: $('#aiProviderName').value.trim(), api_base_url: $('#aiProviderBaseUrl').value.trim(),
        model_name: $('#aiProviderModel').value.trim(), default_parameters: defaultParameters,
        timeout_seconds: integer($('#aiProviderTimeout').value) || 30,
        max_retries: integer($('#aiProviderRetries').value), enabled: $('#aiProviderEnabled').checked
      };
      if ($('#aiProviderKey').value) payload.api_key = $('#aiProviderKey').value;
      if (!id && !payload.api_key) return showToast('首次保存必须填写 API Key。');
      const provider = id ? await teamGateway.updateAIProvider(id, payload) : await teamGateway.saveAIProvider(payload);
      await teamGateway.testAIProvider(provider.id);
      await openIntegrationManager();
      showToast(id ? '大模型配置已保存并通过连接测试。' : '大模型 API 已加密保存并通过连接测试。');
    } catch (error) { handleTeamError(error); }
  });
  $('#resetAIProvider').addEventListener('click', resetAIProviderForm);
  $('#aiProviderRows').addEventListener('click', async function (event) {
    const edit = event.target.closest('[data-ai-edit-id]');
    if (edit) return editAIProviderConfig(edit.dataset.aiEditId);
    const button = event.target.closest('[data-ai-test-id]');
    if (!button) return;
    try {
      await teamGateway.testAIProvider(button.dataset.aiTestId);
      showToast('大模型连接测试成功。');
    } catch (error) { handleTeamError(error); }
  });
  $('#aiRecommendationForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    try {
      const provider = $('#aiRecommendationProvider').value;
      if (!provider) return showToast('请先保存并测试一个已启用的大模型。');
      let inputData = {};
      try { inputData = JSON.parse($('#aiRecommendationInput').value || '{}'); }
      catch (_) { return showToast('AI 建议输入必须是合法的 JSON 对象。'); }
      if (!inputData || Array.isArray(inputData) || typeof inputData !== 'object') {
        return showToast('AI 建议输入必须是 JSON 对象。');
      }
      await teamGateway.createAIRecommendation({
        provider: provider,
        kind: $('#aiRecommendationKind').value,
        input_data: inputData
      });
      await openIntegrationManager();
      showToast('AI 建议已生成，等待你确认；系统没有自动修改库存。');
    } catch (error) { handleTeamError(error); }
  });
  $('#aiRecommendationRows').addEventListener('click', function (event) {
    const button = event.target.closest('[data-ai-recommendation-action]');
    if (!button) return;
    const id = button.dataset.aiRecommendationId;
    const confirm = button.dataset.aiRecommendationAction === 'confirm';
    askConfirm(
      confirm
        ? '确认采纳这条 AI 建议？本操作只记录确认决定，不会自动修改库存。'
        : '确认拒绝这条 AI 建议？原建议和调用记录会保留。',
      async function () {
        if (confirm) await teamGateway.confirmAIRecommendation(id, '用户在 AI 建议工作台确认');
        else await teamGateway.rejectAIRecommendation(id, '用户在 AI 建议工作台拒绝');
        await openIntegrationManager();
        showToast(confirm ? 'AI 建议已确认，库存未被自动修改。' : 'AI 建议已拒绝，原记录已保留。');
      }
    );
  });
  $('#cancelInternalAccount').addEventListener('click', function () {
    resetInternalAccountForm();
  });
  $('#internalAccountForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    if (!teamGateway || !teamGateway.user || !teamGateway.user.is_owner) return;
    const id = $('#internalAccountId').value;
    const permissions = $$('#internalAccountPermissions input:checked').map(function (input) { return input.value; });
    const warehouseIds = $$('#internalAccountWarehouses input:checked').map(function (input) { return input.value; });
    const payload = {
      username: $('#internalAccountUsername').value.trim(),
      display_name: $('#internalAccountDisplayName').value.trim(),
      role: $('#internalAccountRole').value,
      warehouse_ids: warehouseIds,
      permissions: permissions
    };
    const password = $('#internalAccountPassword').value;
    if (password) payload.password = password;
    try {
      if (id) await teamGateway.updateInternalAccount(id, payload); else await teamGateway.createInternalAccount(payload);
      await openInternalAccountManager();
      showToast(id ? '子账号设置已保存。' : '子账号已创建，可以直接登录。');
    } catch (error) { handleTeamError(error); }
  });
  $('#internalAccountRows').addEventListener('click', async function (event) {
    const button = event.target.closest('[data-account-action]');
    if (!button) return;
    const id = button.dataset.accountId;
    if (button.dataset.accountAction === 'edit') return editInternalAccount(id);
    if (button.dataset.accountAction === 'toggle') {
      const account = internalAccounts.find(function (item) { return item.id === id; });
      if (!account) return;
      try {
        await teamGateway.updateInternalAccount(id, { active: !account.active });
        await openInternalAccountManager();
        showToast(account.active ? '子账号已停用。' : '子账号已重新启用。');
      } catch (error) { handleTeamError(error); }
    }
  });
  $('#openOwnerPasswordChange').addEventListener('click', async function () {
    try {
      const challenge = await teamGateway.requestOwnerPasswordChange();
      ownerPasswordChallengeId = challenge.challenge_id;
      $('#accountManagerPanel').hidden = true;
      $('#ownerPasswordPanel').hidden = false;
      showToast('验证码已发送到主账号邮箱。');
    } catch (error) { handleTeamError(error); }
  });
  $('#cancelOwnerPasswordChange').addEventListener('click', function () { ownerPasswordChallengeId = ''; $('#ownerPasswordPanel').hidden = true; });
  $('#ownerPasswordChangeForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    try {
      await teamGateway.confirmOwnerPasswordChange(ownerPasswordChallengeId, $('#ownerPasswordCode').value.trim(), $('#ownerPasswordNew').value);
      ownerPasswordChallengeId = '';
      $('#ownerPasswordPanel').hidden = true;
      $('#ownerPasswordCode').value = '';
      $('#ownerPasswordNew').value = '';
      showToast('主账号密码已修改。');
    } catch (error) { handleTeamError(error); }
  });
  $('#globalSearch').addEventListener('input', function (event) {
    searchTerm = event.target.value.trim().toLowerCase();
    renderProducts(); renderPurchases(); renderInventory(); renderMovements(); renderTransfers(); renderReplenishment(); renderOrders(); renderCompetitorProducts();
  });
  $('#selectionPlatform').addEventListener('change', function () {
    renderSelectionRegions();
    selectionState.keywords = [];
    selectionState.selectedKeyword = '';
    selectionState.report = null;
    $('#selectionReportButton').disabled = true;
    $('#selectionChosenHint').textContent = '请先从上方选择一个候选关键词。';
    renderSelectionKeywords();
    renderSelectionReport();
  });
  ['#selectionRegion', '#selectionListingTime'].forEach(function (selector) {
    $(selector).addEventListener('change', function () {
      selectionState.keywords = [];
      selectionState.selectedKeyword = '';
      selectionState.report = null;
      $('#selectionReportButton').disabled = true;
      $('#selectionChosenHint').textContent = '筛选范围已改变，请重新查询并选择候选关键词。';
      renderSelectionKeywords();
      renderSelectionReport();
    });
  });
  $('#selectionKeywordForm').addEventListener('submit', searchSelectionKeywords);
  $('#selectionReportForm').addEventListener('submit', submitSelectionReport);
  ['#openProductModal', '#tableAddProduct', '#emptyAddProduct'].forEach(function (selector) {
    const button = $(selector);
    if (button) button.addEventListener('click', function () { openProductEditor('', 'own'); });
  });
  ['#competitorAddProduct', '#competitorTableAdd'].forEach(function (selector) {
    $(selector).addEventListener('click', function () { openProductEditor('', 'direct'); });
  });
  ['#competitorAddOwnProduct', '#competitorTableAddOwn'].forEach(function (selector) {
    $(selector).addEventListener('click', openOwnProductMonitoringPicker);
  });
  $('#monitoringProductSearch').addEventListener('input', function (event) {
    monitoringPickerTerm = event.target.value || '';
    renderMonitoringProductPicker();
  });
  $('#monitoringProductSelectAll').addEventListener('change', function (event) {
    monitoringPickerProducts().filter(function (product) { return !product.monitoringEnabled; }).forEach(function (product) {
      if (event.target.checked) monitoringPickerSelected.add(product.id);
      else monitoringPickerSelected.delete(product.id);
    });
    renderMonitoringProductPicker();
  });
  $('#monitoringProductPicker').addEventListener('change', function (event) {
    const checkbox = event.target.closest('[data-monitoring-product-id]');
    if (!checkbox) return;
    if (checkbox.checked) monitoringPickerSelected.add(checkbox.dataset.monitoringProductId);
    else monitoringPickerSelected.delete(checkbox.dataset.monitoringProductId);
    renderMonitoringProductPicker();
  });
  $('#confirmAddOwnMonitoring').addEventListener('click', submitOwnProductsToMonitoring);
  $('#productKind').addEventListener('change', toggleProductFields);
  $('#productKind').addEventListener('change', renderProductSkuEditor);
  $('#addProductSku').addEventListener('click', function () {
    draftStoreListings = readStoreListingDrafts();
    draftProductSkus = readProductSkuDrafts();
    draftProductSkus.push(skuDraft());
    renderProductSkuEditor();
  });
  $('#productImageUrl').addEventListener('input', function () { pendingProductImage = $('#productImageUrl').value; $('#productImageStatus').textContent = ''; updateProductImagePreview(); });
  $('#productImageFile').addEventListener('change', async function (event) {
    const status = $('#productImageStatus');
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    status.classList.remove('error');
    status.textContent = '正在处理：' + file.name;
    try {
      pendingProductImage = await compressProductImage(file);
      $('#productImageUrl').value = '';
      updateProductImagePreview();
      status.textContent = '已选择：' + file.name + '，保存商品后同步到团队。';
      showToast(TEAM_MODE ? '图片已压缩，保存商品时会同步给团队。' : '图片已压缩并保存到本机数据中。');
    } catch (error) {
      status.classList.add('error');
      status.textContent = error.message;
      showToast(error.message);
    } finally {
      event.target.value = '';
    }
  });
  $('#removeProductImage').addEventListener('click', function () { pendingProductImage = ''; $('#productImageUrl').value = ''; $('#productImageStatus').textContent = ''; updateProductImagePreview(); });
  $('#productForm').addEventListener('submit', handleProductSubmit);
  if ($('#saveProductDraft')) $('#saveProductDraft').addEventListener('click', function () { saveProductFromForm(true); });
  $('#openPurchaseModal').addEventListener('click', function () {
    openPurchaseEditor().catch(function (error) {
      console.error('Unable to open the purchase editor.', error);
      showToast('无法打开采购单，请稍后重试。');
    });
  });
  $('#openReceiveModal').addEventListener('click', function () { openReceiveEditor(); });
  $('#purchaseSkuSearch').addEventListener('input', renderPurchaseSkuPicker);
  $('#purchaseSkuPicker').addEventListener('click', function (event) {
    const button = event.target.closest('[data-add-purchase-sku]');
    if (!button) return;
    const productId = button.dataset.addPurchaseSku;
    const product = productById(productId);
    const card = event.target.closest('[data-purchase-sku-card]');
    const quantityInput = card && card.querySelector('[data-purchase-sku-quantity]');
    const costInput = card && card.querySelector('[data-purchase-sku-cost]');
    const quantity = integer(quantityInput && quantityInput.value);
    const unitCost = nonNegative(costInput && costInput.value);
    if (!product || product.kind !== 'own' || product.needsReview) return showToast('请选择已完善的本店 SKU。');
    if (!quantity) return showToast('采购数量必须大于 0。');
    if (unitCost <= 0) return showToast('实际采购单价必须大于 0。');
    const existing = draftPurchaseLines.find(function (line) { return line.productId === productId; });
    if (existing) { existing.quantity = quantity; existing.unitCost = unitCost; }
    else draftPurchaseLines.push({ productId: productId, quantity: quantity, unitCost: unitCost });
    if (!$('#purchaseSupplier').value && product.defaultSupplier) $('#purchaseSupplier').value = product.defaultSupplier;
    renderPurchaseDraft();
  });
  $('#internalAccountRole').addEventListener('change', function () {
    applyInternalAccountRoleDefaults();
  });
  $('#purchaseForm').addEventListener('submit', handlePurchaseSubmit);
  $('#addPurchaseShipment').addEventListener('click', function () {
    const trackingNumber = $('#purchaseTrackingNumber').value.trim();
    if (!trackingNumber) return showToast('请先填写物流单号。');
    if (draftPurchaseShipments.some(function (item) { return item.trackingNumber.toLowerCase() === trackingNumber.toLowerCase(); })) return showToast('同一采购单的物流单号不能重复。');
    draftPurchaseShipments.push({ id: '', trackingNumber: trackingNumber, lines: [] });
    $('#purchaseTrackingNumber').value = '';
    renderPurchaseShipments();
  });
  $('#purchaseShipmentList').addEventListener('click', function (event) {
    const remove = event.target.closest('[data-remove-purchase-shipment]');
    if (!remove) return;
    draftPurchaseShipments.splice(Number(remove.dataset.removePurchaseShipment), 1);
    renderPurchaseShipments();
  });
  $('#purchaseShipmentList').addEventListener('input', function (event) {
    const input = event.target.closest('[data-shipment-quantity]');
    if (!input) return;
    const parts = input.dataset.shipmentQuantity.split(':');
    const shipment = draftPurchaseShipments[Number(parts[0])];
    if (!shipment) return;
    const productId = parts.slice(1).join(':');
    const quantity = Math.max(0, integer(input.value));
    let line = shipment.lines.find(function (item) { return item.productId === productId; });
    if (!line && quantity > 0) { line = { productId: productId, quantity: quantity }; shipment.lines.push(line); }
    if (line) line.quantity = quantity;
  });
  $('#purchaseRows').addEventListener('click', function (event) {
    const toggle = event.target.closest('[data-toggle-purchase-shipments]');
    if (!toggle) return;
    const order = state.purchaseOrders.find(function (item) { return item.id === toggle.dataset.togglePurchaseShipments; });
    if (order) { order.showShipments = !order.showShipments; renderPurchases(); }
  });
  $('#purchaseLineList').addEventListener('input', function (event) {
    const quantityInput = event.target.closest('[data-purchase-line-quantity]');
    const costInput = event.target.closest('[data-purchase-line-cost]');
    const productId = quantityInput ? quantityInput.dataset.purchaseLineQuantity : (costInput ? costInput.dataset.purchaseLineCost : '');
    const line = draftPurchaseLines.find(function (item) { return item.productId === productId; });
    if (!line) return;
    if (quantityInput) line.quantity = Math.max(1, integer(quantityInput.value));
    if (costInput) line.unitCost = nonNegative(costInput.value);
  });
  $('#receivePurchaseId').addEventListener('change', renderReceiveLines);
  $('#receiveShipmentId').addEventListener('change', renderReceiveLines);
  $('#receiveLineList').addEventListener('input', updateReceiveHint);
  $('#receiveForm').addEventListener('submit', handleReceiveSubmit);
  $('#returnLine').addEventListener('change', updateReturnHint);
  $('#returnCondition').addEventListener('change', updateReturnHint);
  $('#returnForm').addEventListener('submit', handleReturnSubmit);
  $('#openStockModal').addEventListener('click', function () { openStockEditor(''); });
  $('#stockProduct').addEventListener('change', updateStockHint);
  $('#stockForm').addEventListener('submit', handleStockSubmit);
  $('#manageWarehouses').addEventListener('click', openWarehouseManager);
  $('#warehouseForm').addEventListener('submit', handleWarehouseSubmit);
  $('#resetWarehouseForm').addEventListener('click', resetWarehouseEditor);
  $('#openTransferModal').addEventListener('click', openTransferEditor);
  $('#addTransferLine').addEventListener('click', function () {
    const productId = $('#transferLineProduct').value;
    const product = productById(productId);
    const quantity = integer($('#transferLineQty').value);
    if (!product || product.kind !== 'own' || product.needsReview) return showToast('请选择已完善的本店 SKU。');
    if (!quantity) return showToast('调拨数量必须大于 0。');
    const existing = draftTransferLines.find(function (line) { return line.productId === productId; });
    if (existing) existing.quantity += quantity; else draftTransferLines.push({ productId: productId, quantity: quantity });
    const defaultPackage = ensureDraftTransferPackage();
    defaultPackage.quantities[productId] = integer(defaultPackage.quantities[productId]) + quantity;
    $('#transferLineQty').value = '';
    renderTransferDraft();
  });
  $('#addTransferPackage').addEventListener('click', function () {
    if (!draftTransferLines.length) return showToast('请先添加调拨 SKU。');
    draftTransferPackages.push({ id: uid('transfer-package'), trackingNumber: '', quantities: {} });
    renderTransferPackageDraft();
  });
  $('#transferForm').addEventListener('submit', handleTransferSubmit);
  $('#submitTransferWorkflow').addEventListener('click', submitTransferWorkflow);
  $('#transferCompleteForm').addEventListener('submit', handleTransferCompleteSubmit);
  $('#replenishmentPolicyForm').addEventListener('submit', handleReplenishmentPolicySubmit);
  $('#replenishmentSettingsForm').addEventListener('submit', handleReplenishmentSettingsSubmit);
  $('#replenishmentBatchPolicyForm').addEventListener('submit', handleBatchReplenishmentPolicySubmit);
  $('#openReplenishmentSettings').addEventListener('click', function () { openReplenishmentSettings().catch(handleTeamError); });
  $('#replenishmentRows').addEventListener('change', function (event) {
    const input = event.target.closest('[data-replenishment-select]');
    if (!input) return;
    const skuId = String(input.dataset.replenishmentSelect);
    if (input.checked) replenishmentSelectedSkuIds.add(skuId); else replenishmentSelectedSkuIds.delete(skuId);
    renderReplenishment();
  });
  $('#replenishmentSelectAll').addEventListener('change', function () {
    const visibleSkuIds = visibleReplenishmentSkuIds();
    visibleSkuIds.forEach((skuId) => { if (this.checked) replenishmentSelectedSkuIds.add(skuId); else replenishmentSelectedSkuIds.delete(skuId); });
    renderReplenishment();
  });
  $('#batchReplenishmentPolicy').addEventListener('click', function () { openBatchReplenishmentPolicy().catch(handleTeamError); });
  $('#batchReplenishmentRecompute').addEventListener('click', function () { recomputeSelectedReplenishment().catch(handleTeamError); });
  $('#batchReplenishmentPurchase').addEventListener('click', function () { openBatchPurchaseDraft().catch(handleTeamError); });
  $('#refreshReplenishment').addEventListener('click', function () {
    if (TEAM_MODE) return executeTeamCommand(function () { return teamGateway.recomputeReplenishment([]); }, '补货建议已按最新库存流水重新计算；复杂项目会自动进入 AI 分析队列。', 'replenishment');
    renderReplenishment();
    showToast('补货建议已重新计算。');
  });
  $('#openOrderModal').addEventListener('click', openOrderEditor);
  $('#orderSkuSearch').addEventListener('input', renderOrderSkuPicker);
  $('#orderSkuPicker').addEventListener('input', function (event) {
    const input = event.target.closest('[data-order-sku-quantity]');
    if (!input) return;
    const card = input.closest('[data-order-sku-card]');
    const available = availableFor(input.dataset.orderSkuQuantity);
    const shortage = Math.max(0, integer(input.value) - available);
    const old = card && card.querySelector('.order-stock-copy .shortage');
    if (old) old.remove();
    if (shortage && card) card.querySelector('.order-stock-copy').insertAdjacentHTML('beforeend', '<span class="shortage">预计缺口 ' + shortage + '</span>');
  });
  $('#orderSkuPicker').addEventListener('click', function (event) {
    const button = event.target.closest('[data-add-order-sku]');
    if (!button) return;
    const productId = button.dataset.addOrderSku;
    const product = productById(productId);
    const input = $('#orderSkuPicker').querySelector('[data-order-sku-quantity="' + CSS.escape(productId) + '"]');
    const quantity = integer(input && input.value);
    if (!product || product.kind !== 'own' || product.needsReview) return showToast('请选择已完善的本店 SKU。');
    if (!quantity) return showToast('订单数量必须大于 0。');
    const existing = draftOrderLines.find(function (line) { return line.productId === productId; });
    if (existing) existing.quantity = quantity;
    else draftOrderLines.push({ productId: productId, quantity: quantity });
    renderOrderDraft();
  });
  $('#orderForm').addEventListener('submit', handleOrderSubmit);
  window.addEventListener('scroll', function () { updateInventoryStickyHeader(); updateReplenishmentStickyHeader(); }, { passive: true });
  window.addEventListener('resize', function () { updateInventoryStickyHeader(); updateReplenishmentStickyHeader(); });
  $('#inventoryTableWrap').addEventListener('scroll', updateInventoryStickyHeader, { passive: true });
  if ($('#replenishmentTableWrap')) $('#replenishmentTableWrap').addEventListener('scroll', updateReplenishmentStickyHeader, { passive: true });
  $('#openSnapshotModal').addEventListener('click', function () { openSnapshotEditor($('#historyProduct').value); });
  $('#snapshotProduct').addEventListener('change', fillSnapshotHint);
  $('#snapshotForm').addEventListener('submit', handleSnapshotSubmit);
  $('#historyProduct').addEventListener('change', function () { state.selectedProductId = this.value; $('#activeProduct').value = this.value; saveUiQuietly(); renderHistory(); renderTrendMetrics(); });
  $('#activeProduct').addEventListener('change', function () { state.selectedProductId = this.value; $('#historyProduct').value = this.value; saveUiQuietly(); renderTrendMetrics(); });
  $('#movementProduct').addEventListener('change', renderMovements);
  $('#cancelConfirm').addEventListener('click', closeConfirm);
  $('#acceptConfirm').addEventListener('click', function () {
    const callback = pendingConfirm;
    closeConfirm();
    if (callback) Promise.resolve(callback()).catch(handleTeamError);
  });
  $('#clearAllData').addEventListener('click', function () {
    if (TEAM_MODE) return showToast('团队模式不提供清空全部业务数据。');
    askConfirm('确认清空本机全部商品、采购、库存、订单和快照数据？', function () {
      const saved = commit(function (next) { Object.assign(next, emptyState()); }, '本机业务数据已清空。');
      if (saved) {
        productFilter = 'all'; purchaseFilter = 'open'; orderFilter = 'open'; inventoryFilter = 'all'; inventorySection = 'list';
        setRoute('products');
      }
    });
  });
  $('#exportCsv').addEventListener('click', function () {
    downloadText('东铂跨境-商品与快照-' + today() + '.csv', productCsvRows());
    showToast('已导出全部商品主档及最新快照。');
  });
  $('#downloadTemplate').addEventListener('click', function () {
    const header = ['name', 'kind', 'sku', 'seller', 'market', 'currency', 'cost', 'safety_stock', 'status', 'url', 'purchase_url', 'image_url', 'monitoring_enabled', 'snapshot_at', 'price', 'sold', 'rating', 'reviews', 'low_reviews', 'shop_rating'];
    const example = ['示例商品', 'own', 'DB-001', 'Dongbo MY', 'MY', 'CNY', '18.5', '20', 'active', 'https://example.com/product', 'https://example.com/purchase', 'https://example.com/image.jpg', 'false', '', '', '', '', '', '', ''];
    downloadText('东铂跨境-商品导入模板.csv', [header, example].map(function (row) { return row.map(csvEscape).join(','); }).join('\n'));
  });
  $('#importCsv').addEventListener('click', function () {
    if (TEAM_MODE) return showToast('团队模式请使用经过校验的迁移流程，不能直接写入浏览器 CSV。');
    $('#csvFile').click();
  });
  $('#csvFile').addEventListener('change', async function (event) {
    const file = event.target.files[0];
    event.target.value = '';
    if (TEAM_MODE) return showToast('团队模式已阻止本机 CSV 写入。');
    if (!file) return;
    try {
      const rows = parseCsv(await file.text());
      if (rows.length < 2) throw new Error('CSV 没有可导入的数据行。');
      const headers = rows[0].map(function (item) { return item.trim(); });
      const objects = rows.slice(1).map(function (row) {
        const result = {};
        headers.forEach(function (header, index) { result[header] = row[index] || ''; });
        return result;
      });
      objects.forEach(function (item, index) {
        if (!item.name || !validUrl(item.url) || !safeImageUrl(item.image_url)) throw new Error('第 ' + (index + 2) + ' 行缺少名称、有效链接或图片网址。');
        if (item.kind === 'own' && !item.sku) throw new Error('第 ' + (index + 2) + ' 行本店商品缺少 SKU。');
      });
      commit(function (next) {
        objects.forEach(function (item) {
          const kind = ['own', 'direct', 'indirect'].includes(item.kind) ? item.kind : 'direct';
          let product = kind === 'own'
            ? next.products.find(function (entry) { return entry.kind === 'own' && normalizeSku(entry.sku) === normalizeSku(item.sku); })
            : next.products.find(function (entry) { return entry.productUrl === item.url; });
          const id = product ? product.id : uid('product');
          const normalized = normalizeProduct({
            id: id, name: item.name, kind: kind, sku: item.sku, seller: item.seller,
            market: item.market || 'MY', salesCurrency: item.currency || (kind === 'own' ? 'CNY' : 'MYR'),
            costCurrency: item.currency || 'CNY', standardCost: item.cost, safetyStock: item.safety_stock,
            status: item.status || 'active', productUrl: item.url, purchaseUrl: item.purchase_url,
            image: item.image_url, monitoringEnabled: kind !== 'own' || item.monitoring_enabled === 'true',
            needsReview: false, createdAt: product ? product.createdAt : new Date().toISOString(), updatedAt: new Date().toISOString()
          });
          if (product) next.products[next.products.indexOf(product)] = normalized; else next.products.push(normalized);
          if (kind === 'own') ensureBalance(next, id);
          if (item.snapshot_at && item.price !== '' && item.sold !== '') {
            const duplicate = next.snapshots.some(function (snapshot) { return snapshot.productId === id && snapshot.at === new Date(item.snapshot_at).toISOString(); });
            if (!duplicate) next.snapshots.push({
              id: uid('snap'), productId: id, at: new Date(item.snapshot_at).toISOString(),
              currency: normalized.salesCurrency, price: nonNegative(item.price), sold: integer(item.sold),
              rating: item.rating === '' ? null : asNumber(item.rating), reviews: integer(item.reviews),
              lowReviews: integer(item.low_reviews), shopRating: item.shop_rating === '' ? null : asNumber(item.shop_rating),
              createdAt: new Date().toISOString()
            });
          }
        });
      }, 'CSV 已整批导入；如有错误将不会保留半成品。');
    } catch (error) {
      showToast(error.message || 'CSV 导入失败。');
    }
  });
  window.addEventListener('resize', function () {
    if (window.innerWidth >= 900) closeSidebar();
    if (state.ui.module === 'analytics' && state.ui.competitorTab === 'trends') renderChart();
  });
  window.addEventListener('hashchange', function () { applyHashRoute(); closeSidebar(); render(); });
  window.addEventListener('offline', function () {
    if (!TEAM_MODE || !teamGateway) return;
    teamGateway.online = false;
    renderRuntimeState();
  });
  window.addEventListener('online', function () {
    if (!TEAM_MODE || !teamGateway) return;
    teamGateway.online = true;
    renderRuntimeState();
    if (teamAuthenticated()) refreshTeamState('网络已恢复，团队数据已重新同步。');
  });
}

applyHashRoute();
bindEvents();
render();
initializeTeamMode();
startRealtimeSync();

