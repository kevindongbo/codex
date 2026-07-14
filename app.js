const STORAGE_KEY = 'dongbo-crossborder.v1';
const LEGACY_STORAGE_KEY = 'pulsetrack.manual.v2';
const STATE_VERSION = 5;
const DEFAULT_WAREHOUSE_ID = 'warehouse-default';
const COLORS = ['#0e8e86', '#e89a42', '#607cce', '#cf655d', '#7a9b55', '#8c6bb1'];
const KIND_LABELS = { own: '本店商品', direct: '直接竞品', indirect: '间接竞品' };
const CURRENCY = { CNY: '¥', MYR: 'RM', USD: '$', GBP: '£', SGD: 'S$', THB: '฿', VND: '₫', PHP: '₱', IDR: 'Rp' };
const PURCHASE_LABELS = { draft: '草稿', ordered: '已下单', transit: '在途', partial: '部分收货', completed: '已完成', cancelled: '已取消' };
const ORDER_LABELS = { shortage: '库存不足', picking: '拣货中', review: '待复核', ready: '待出库', shipped: '已出库', cancelled: '已取消' };
const MOVEMENT_LABELS = {
  opening: '期初库存', receipt: '采购收货', reserve: '订单锁定', release: '释放锁定',
  outbound: '订单出库', return: '退货入库', manual_in: '手动入库', adjust_add: '盘盈', adjust_sub: '盘亏', damage: '报损'
};

function emptyState() {
  return {
    version: STATE_VERSION,
    revision: 1,
    warehouses: [{ id: DEFAULT_WAREHOUSE_ID, name: '默认仓', active: true }],
    products: [],
    snapshots: [],
    purchaseOrders: [],
    receipts: [],
    inventoryBalances: [],
    inventoryMovements: [],
    salesOrders: [],
    reservations: [],
    shipments: [],
    returns: [],
    legacyStockEvents: [],
    migrationIssues: [],
    selectedProductId: '',
    ui: { module: 'products', warehouseTab: 'purchase', competitorTab: 'products' }
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

let state = loadState();
let productFilter = 'all';
let purchaseFilter = 'open';
let orderFilter = 'open';
let inventoryFilter = 'all';
let inventorySection = 'list';
let chartMetric = 'sales';
let searchTerm = '';
let pendingConfirm = null;
let pendingProductImage = '';
let draftPurchaseLines = [];
let draftOrderLines = [];
let toastTimer = null;

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

function normalizeV5(saved) {
  const base = emptyState();
  base.revision = integer(saved.revision) || 1;
  base.warehouses = Array.isArray(saved.warehouses) && saved.warehouses.length ? saved.warehouses : base.warehouses;
  base.products = Array.isArray(saved.products) ? saved.products.map(normalizeProduct) : [];
  base.snapshots = (Array.isArray(saved.snapshots) ? saved.snapshots : []).map(function (item) {
    const product = base.products.find(function (entry) { return entry.id === item.productId; });
    return {
      id: item.id || uid('snap'),
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
      updatedAt: item.updatedAt || ''
    };
  }) : [];
  base.inventoryMovements = Array.isArray(saved.inventoryMovements) ? saved.inventoryMovements : [];
  base.salesOrders = Array.isArray(saved.salesOrders) ? saved.salesOrders : [];
  base.reservations = Array.isArray(saved.reservations) ? saved.reservations : [];
  base.shipments = Array.isArray(saved.shipments) ? saved.shipments : [];
  base.returns = Array.isArray(saved.returns) ? saved.returns : [];
  base.legacyStockEvents = Array.isArray(saved.legacyStockEvents) ? saved.legacyStockEvents : [];
  base.migrationIssues = Array.isArray(saved.migrationIssues) ? saved.migrationIssues : [];
  base.selectedProductId = saved.selectedProductId || '';
  const savedUi = saved.ui && typeof saved.ui === 'object' ? saved.ui : {};
  if (['products', 'warehouse', 'competitors'].includes(savedUi.module)) base.ui.module = savedUi.module;
  if (['purchase', 'inventory', 'orders'].includes(savedUi.warehouseTab)) base.ui.warehouseTab = savedUi.warehouseTab;
  if (['products', 'snapshots', 'trends', 'alerts'].includes(savedUi.competitorTab)) base.ui.competitorTab = savedUi.competitorTab;
  base.version = STATE_VERSION;
  ownProducts(base, true).forEach(function (product) {
    if (!base.inventoryBalances.some(function (item) { return item.productId === product.id; })) {
      base.inventoryBalances.push({ warehouseId: DEFAULT_WAREHOUSE_ID, productId: product.id, onHand: 0, reserved: 0, updatedAt: '' });
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
    const loaded = saved.version === STATE_VERSION ? normalizeV5(saved) : migrateLegacy(saved);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(loaded)); } catch (_) { /* keep usable in memory */ }
    return loaded;
  } catch (_) {
    return seedState();
  }
}

function validateState(next) {
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
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (_) { /* navigation may continue */ }
}

function balanceFor(productId, source) {
  const root = source || state;
  return root.inventoryBalances.find(function (item) {
    return item.productId === productId && item.warehouseId === DEFAULT_WAREHOUSE_ID;
  }) || { warehouseId: DEFAULT_WAREHOUSE_ID, productId: productId, onHand: 0, reserved: 0, updatedAt: '' };
}
function ensureBalance(source, productId) {
  let balance = source.inventoryBalances.find(function (item) {
    return item.productId === productId && item.warehouseId === DEFAULT_WAREHOUSE_ID;
  });
  if (!balance) {
    balance = { warehouseId: DEFAULT_WAREHOUSE_ID, productId: productId, onHand: 0, reserved: 0, updatedAt: '' };
    source.inventoryBalances.push(balance);
  }
  return balance;
}
function availableFor(productId, source) {
  const balance = balanceFor(productId, source);
  return Math.max(0, balance.onHand - balance.reserved);
}
function remainingPurchaseLine(line) {
  return Math.max(0, integer(line.orderedQty) - integer(line.receivedQty) - integer(line.cancelledQty));
}
function isPurchaseOpen(order) {
  return ['ordered', 'transit', 'partial'].includes(order.status) && order.lines.some(function (line) { return remainingPurchaseLine(line) > 0; });
}
function purchaseTransitFor(productId, source) {
  const root = source || state;
  return root.purchaseOrders.reduce(function (sum, order) {
    if (!isPurchaseOpen(order)) return sum;
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
  const balance = ensureBalance(next, details.productId);
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
    id: uid('move'), warehouseId: DEFAULT_WAREHOUSE_ID, productId: details.productId,
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
  const line = order.lines.find(function (item) { return item.id === lineId; });
  const qty = integer(quantity);
  if (!line || qty <= 0) throw new Error('请选择有效的收货商品和数量。');
  if (qty > remainingPurchaseLine(line)) throw new Error('本次收货数量超过未收数量。');
  line.receivedQty += qty;
  const receiptId = uid('receipt');
  next.receipts.push({
    id: receiptId, number: 'GRN-' + Date.now(), purchaseOrderId: order.id,
    warehouseId: DEFAULT_WAREHOUSE_ID, receivedAt: occurredAt, note: note || '',
    lines: [{ id: uid('receipt-line'), purchaseOrderLineId: line.id, productId: line.productId, quantity: qty }],
    createdAt: new Date().toISOString()
  });
  addMovement(next, {
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
  if (!String(note || '').trim()) throw new Error('库存调整必须填写原因。');
  const positive = operation === 'manual_in' || operation === 'adjust_add';
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
  if (order.lines.some(function (line) { return integer(line.reservedQty) > 0; })) throw new Error('该订单已经锁定库存。');
  const demands = mergedOrderDemand(order.lines);
  const shortage = demands.find(function (demand) { return availableFor(demand.productId, next) < demand.quantity; });
  if (shortage) {
    order.status = 'shortage';
    order.updatedAt = new Date().toISOString();
    return false;
  }
  demands.forEach(function (demand) {
    addMovement(next, {
      productId: demand.productId, type: 'reserve', onHandDelta: 0, reservedDelta: demand.quantity,
      sourceType: 'order', sourceId: order.id, sourceLineId: demand.productId,
      sourceNumber: order.number, occurredAt: new Date().toISOString(), note: '订单创建自动锁定'
    });
  });
  order.lines.forEach(function (line) { line.reservedQty = integer(line.quantity); });
  demands.forEach(function (demand) {
    next.reservations.push({
      id: uid('reservation'), orderId: order.id, orderLineId: '',
      warehouseId: DEFAULT_WAREHOUSE_ID, productId: demand.productId,
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
  const active = next.reservations.filter(function (item) { return item.orderId === order.id && item.status === 'active'; });
  const demands = mergedOrderDemand(order.lines);
  if (!active.length || demands.some(function (demand) {
    return active.filter(function (item) { return item.productId === demand.productId; }).reduce(function (sum, item) { return sum + integer(item.quantity); }, 0) < demand.quantity;
  })) throw new Error('订单锁定记录不完整，不能出库。');
  demands.forEach(function (demand) {
    addMovement(next, {
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
    warehouseId: DEFAULT_WAREHOUSE_ID, status: 'shipped',
    trackingNumber: order.trackingNumber || '', shippedAt: new Date().toISOString(),
    note: order.note || '', lines: order.lines.map(function (line) {
      return { id: uid('shipment-line'), orderLineId: line.id, productId: line.productId, quantity: integer(line.quantity) };
    })
  });
  order.status = 'shipped';
  order.shippedAt = new Date().toISOString();
  order.updatedAt = new Date().toISOString();
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

function receiveSalesReturn(next, orderId, orderLineId, quantity, occurredAt, note) {
  const order = next.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || order.status !== 'shipped') throw new Error('只有已出库订单可以办理退货入库。');
  const line = order.lines.find(function (item) { return item.id === orderLineId; });
  const qty = integer(quantity);
  if (!line || qty <= 0) throw new Error('请选择有效的退货商品和数量。');
  if (qty > returnableForLine(line, next)) throw new Error('退货数量不能超过该订单明细的可退数量。');
  if (!String(note || '').trim()) throw new Error('退货入库必须填写原因。');
  const returnId = uid('return');
  const returnNumber = 'RTN-' + Date.now();
  next.returns.push({
    id: returnId, number: returnNumber, orderId: order.id, warehouseId: DEFAULT_WAREHOUSE_ID,
    returnedAt: occurredAt, note: note,
    lines: [{ id: uid('return-line'), orderLineId: line.id, productId: line.productId, quantity: qty }],
    createdAt: new Date().toISOString()
  });
  addMovement(next, {
    productId: line.productId, type: 'return', onHandDelta: qty, reservedDelta: 0,
    sourceType: 'return', sourceId: returnId, sourceLineId: line.id,
    sourceNumber: returnNumber + ' / ' + order.number, occurredAt: occurredAt, note: note
  });
}

function hasBusinessReferences(productId, source) {
  const root = source || state;
  const balance = balanceFor(productId, root);
  return Boolean(
    balance.onHand || balance.reserved || purchaseTransitFor(productId, root) ||
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
function pulseStorage() {
  const chip = $('.storage-state');
  if (!chip) return;
  chip.innerHTML = '<i></i>刚刚已保存';
  setTimeout(function () { chip.innerHTML = '<i></i>已自动保存'; }, 1400);
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
    '</strong><span title="' + escapeHtml(product.productUrl) + '">' + escapeHtml(product.seller || product.market || '—') + '</span></div></div>';
}
function statusPill(label, className) {
  return '<span class="status-pill ' + escapeHtml(className) + '">' + escapeHtml(label) + '</span>';
}
function rowButton(action, id, label, className) {
  return '<button class="row-action ' + (className || '') + '" data-action="' + action + '" data-id="' + escapeHtml(id) + '">' + escapeHtml(label) + '</button>';
}

function setRoute(module, subtab) {
  state.ui.module = module;
  if (module === 'warehouse' && subtab) state.ui.warehouseTab = subtab;
  if (module === 'competitors' && subtab) state.ui.competitorTab = subtab;
  let route = '#' + module;
  if (module === 'products' && productFilter !== 'all') route += '/' + productFilter;
  if (module === 'warehouse') {
    route += '/' + state.ui.warehouseTab;
    if (state.ui.warehouseTab === 'purchase' && purchaseFilter !== 'open') route += '/' + purchaseFilter;
    if (state.ui.warehouseTab === 'orders' && orderFilter !== 'open') route += '/' + orderFilter;
    if (state.ui.warehouseTab === 'inventory') {
      if (inventoryFilter === 'low') route += '/low';
      else if (inventorySection === 'movements') route += '/movements';
    }
  }
  if (module === 'competitors') route += '/' + state.ui.competitorTab;
  history.replaceState(null, '', route);
  saveUiQuietly();
  closeSidebar();
  render();
}
function applyHashRoute() {
  const parts = location.hash.replace(/^#/, '').split('/');
  if (['products', 'warehouse', 'competitors'].includes(parts[0])) state.ui.module = parts[0];
  if (parts[0] === 'products') productFilter = ['own', 'direct', 'indirect', 'inactive'].includes(parts[1]) ? parts[1] : 'all';
  if (parts[0] === 'warehouse' && ['purchase', 'inventory', 'orders'].includes(parts[1])) {
    state.ui.warehouseTab = parts[1];
    if (parts[1] === 'purchase') purchaseFilter = ['overdue', 'all'].includes(parts[2]) ? parts[2] : 'open';
    if (parts[1] === 'orders') orderFilter = ['shortage', 'shipped', 'all'].includes(parts[2]) ? parts[2] : 'open';
    if (parts[1] === 'inventory') {
      inventoryFilter = parts[2] === 'low' ? 'low' : 'all';
      inventorySection = parts[2] === 'movements' ? 'movements' : 'list';
    }
  }
  if (parts[0] === 'competitors' && ['products', 'snapshots', 'trends', 'alerts'].includes(parts[1])) state.ui.competitorTab = parts[1];
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
      }
    }
    if (state.ui.module === 'competitors' && button.dataset.competitorView) {
      active = button.dataset.competitorView === state.ui.competitorTab;
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
  if (button.dataset.competitorView) setRoute('competitors', button.dataset.competitorView);
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
    if (productFilter === 'inactive') return product.status === 'inactive';
    if (product.status === 'inactive') return false;
    return productFilter === 'all' || product.kind === productFilter;
  }).filter(function (product) { return searchMatches(product); });
  products.sort(function (a, b) { return new Date(b.updatedAt) - new Date(a.updatedAt); });
  $('#productRows').innerHTML = products.map(function (product) {
    const balance = balanceFor(product.id);
    const transit = product.kind === 'own' ? purchaseTransitFor(product.id) : 0;
    const available = product.kind === 'own' ? availableFor(product.id) : 0;
    let actions = rowButton('edit-product', product.id, product.status === 'draft' ? '继续完善' : '编辑', 'primary');
    if (product.kind === 'own' && product.status === 'active' && !product.needsReview) actions += rowButton('open-warehouse', product.id, '看库存');
    if (product.status === 'active' && (product.kind !== 'own' || product.monitoringEnabled)) actions += rowButton('add-snapshot', product.id, '录快照');
    if (product.status !== 'draft') actions += rowButton(product.status === 'active' ? 'deactivate-product' : 'activate-product', product.id, product.status === 'active' ? '停用' : '启用');
    actions += rowButton('delete-product', product.id, '删除', 'danger');
    const status = product.status === 'draft'
      ? statusPill(product.needsReview ? '草稿 · 待完善' : '草稿', 'draft')
      : (product.needsReview ? statusPill('待完善', 'shortage') : statusPill(product.status === 'active' ? '启用' : '停用', product.status));
    return '<tr><td>' + productMedia(product) + '</td><td><span class="type-pill ' + product.kind + '">' + KIND_LABELS[product.kind] + '</span></td>' +
      '<td>' + escapeHtml(product.sku || '—') + '</td><td>' + (product.kind === 'own' ? money(product.standardCost, product.costCurrency) : '—') + '</td>' +
      '<td>' + (product.kind === 'own' ? '<span class="stock-number transit">' + transit + '</span>' : '—') + '</td>' +
      '<td>' + (product.kind === 'own' ? '<span class="stock-number instock">' + balance.onHand + '</span>' : '—') + '</td>' +
      '<td>' + (product.kind === 'own' ? '<span class="stock-number ' + (available < product.safetyStock ? 'low' : 'instock') + '">' + available + '</span>' : '—') + '</td>' +
      '<td>' + status + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#productEmpty', products.length === 0);
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
  const owns = ownProducts(state, true);
  const transit = owns.reduce(function (sum, item) { return sum + purchaseTransitFor(item.id); }, 0);
  const onHand = owns.reduce(function (sum, item) { return sum + balanceFor(item.id).onHand; }, 0);
  const reserved = owns.reduce(function (sum, item) { return sum + balanceFor(item.id).reserved; }, 0);
  const openPurchases = state.purchaseOrders.filter(isPurchaseOpen).length;
  const pendingOrders = state.salesOrders.filter(function (item) { return !['shipped', 'cancelled'].includes(item.status); }).length;
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
    const lines = order.lines.slice(0, 2).map(function (line) {
      const product = productById(line.productId);
      return escapeHtml(product ? (product.sku + ' · ' + product.name) : '商品已移除');
    }).join('<br>') + (order.lines.length > 2 ? '<br>等 ' + order.lines.length + ' 项' : '');
    const overdue = purchaseIsOverdue(order);
    let actions = '';
    if (order.status === 'draft') actions += rowButton('submit-purchase', order.id, '确认下单', 'primary');
    if (order.status === 'ordered') actions += rowButton('transit-purchase', order.id, '标记在途', 'primary');
    if (isPurchaseOpen(order)) actions += rowButton('receive-purchase', order.id, '确认收货', 'primary') + rowButton('cancel-purchase', order.id, '取消余量', 'danger');
    const statusClass = overdue ? 'overdue' : order.status;
    const statusLabel = overdue ? '已逾期' : PURCHASE_LABELS[order.status];
    return '<tr><td><strong>' + escapeHtml(order.number) + '</strong><br><small>' + formatDate(order.orderedAt, false) + '</small></td>' +
      '<td>' + escapeHtml(order.supplier) + '</td><td>' + lines + '</td><td>' + ordered + ' / ' + received + '</td>' +
      '<td><span class="stock-number transit">' + (isPurchaseOpen(order) ? transit : 0) + '</span></td>' +
      '<td class="' + (overdue ? 'overdue-copy' : '') + '">' + formatDate(order.expectedAt, false) + '</td><td>' + purchaseAmount(order) + '</td>' +
      '<td>' + statusPill(statusLabel, statusClass) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#purchaseEmpty', orders.length === 0);
}

function renderInventory() {
  let products = ownProducts(state, true).filter(function (product) {
    return (product.status !== 'draft' || hasBusinessReferences(product.id)) && (!product.needsReview || hasBusinessReferences(product.id)) && searchMatches(product);
  });
  if (inventoryFilter === 'low') {
    products = products.filter(function (product) { return product.status === 'active' && availableFor(product.id) < integer(product.safetyStock); });
  }
  $('#warehouseRows').innerHTML = products.map(function (product) {
    const balance = balanceFor(product.id);
    const available = Math.max(0, balance.onHand - balance.reserved);
    const low = available < integer(product.safetyStock);
    return '<tr><td>' + productMedia(product) + '</td><td>' + escapeHtml(product.sku || '待完善') + '</td>' +
      '<td><span class="stock-number instock">' + balance.onHand + '</span></td><td>' + balance.reserved + '</td>' +
      '<td><span class="stock-number ' + (low ? 'low' : 'instock') + '">' + available + '</span></td><td>' + integer(product.safetyStock) + '</td>' +
      '<td>' + money(balance.onHand * nonNegative(product.standardCost), product.costCurrency) + '</td>' +
      '<td>' + (product.status === 'draft' ? statusPill('草稿 · 有库存', 'shortage') : (product.status === 'inactive' ? statusPill('已停用', 'inactive') : (product.needsReview ? statusPill('待完善', 'shortage') : (low ? statusPill('需补货', 'shortage') : statusPill('正常', 'active'))))) + '</td>' +
      '<td><div class="row-actions">' + (product.status === 'active' && !product.needsReview ? rowButton('adjust-stock', product.id, '库存调整', 'primary') : rowButton('edit-product', product.id, '完善商品', 'primary')) + rowButton('view-movements', product.id, '看流水') + '</div></td></tr>';
  }).join('');
  toggleEmpty('#warehouseEmpty', products.length === 0);
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
    return (filter === 'all' || item.productId === filter) && searchMatches(product, item.sourceNumber);
  }).sort(function (a, b) { return new Date(b.occurredAt) - new Date(a.occurredAt); }).slice(0, 40);
  $('#movementRows').innerHTML = movements.map(function (movement) {
    const product = productById(movement.productId);
    const positive = movement.onHandDelta > 0 || movement.reservedDelta > 0;
    const negative = movement.onHandDelta < 0 || movement.reservedDelta < 0;
    return '<tr><td>' + formatDate(movement.occurredAt, true) + '</td><td>' + escapeHtml(product ? product.sku + ' · ' + product.name : '未知商品') + '</td>' +
      '<td>' + escapeHtml(MOVEMENT_LABELS[movement.type] || movement.type) + '</td><td><span class="delta-pill ' + (positive ? 'up' : (negative ? 'down' : 'neutral')) + '">' + movementDeltaText(movement) + '</span></td>' +
      '<td>' + integer(movement.afterOnHand) + '</td><td>' + escapeHtml(movement.sourceNumber || '—') + '</td><td>' + escapeHtml(movement.note || '—') + '</td></tr>';
  }).join('');
  toggleEmpty('#movementEmpty', movements.length === 0);
}

function renderOrders() {
  let orders = state.salesOrders.filter(function (order) {
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
    if (order.status === 'shortage') actions += rowButton('reserve-order', order.id, '重试锁定', 'primary');
    if (order.status === 'picking') actions += rowButton('advance-order', order.id, '完成拣货', 'primary');
    if (order.status === 'review') actions += rowButton('advance-order', order.id, '完成复核', 'primary');
    if (order.status === 'ready') actions += rowButton('ship-order', order.id, '确认出库', 'primary');
    if (order.status === 'shipped' && order.lines.some(function (line) { return returnableForLine(line) > 0; })) actions += rowButton('return-order', order.id, '退货入库', 'primary');
    if (!['shipped', 'cancelled'].includes(order.status)) actions += rowButton('cancel-order', order.id, '取消', 'danger');
    return '<tr><td><strong>' + escapeHtml(order.number) + '</strong></td><td>' + escapeHtml(order.platform) + '<br><small>' + escapeHtml(order.store || '—') + '</small></td>' +
      '<td>' + lineText + '</td><td>' + qty + '</td><td>' + formatDate(order.orderedAt, true) + '</td><td>' + escapeHtml(order.trackingNumber || '—') + '</td>' +
      '<td>' + statusPill(ORDER_LABELS[order.status] || order.status, order.status) + '</td><td><div class="row-actions">' + actions + '</div></td></tr>';
  }).join('');
  toggleEmpty('#orderEmpty', orders.length === 0);
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
function renderCompetitorProducts() {
  const products = monitoredProducts(state).filter(function (product) { return searchMatches(product); });
  $('#competitorRows').innerHTML = products.map(function (product) {
    const change = snapshotChange(product.id);
    const latest = change.pair.latest;
    const salesClass = change.sales == null ? 'neutral' : (change.sales >= 0 ? 'up' : 'down');
    const actions = rowButton('add-snapshot', product.id, '录快照', 'primary') +
      '<a class="row-action" href="' + escapeHtml(product.productUrl) + '" target="_blank" rel="noopener">打开链接</a>' +
      rowButton('edit-product', product.id, '编辑');
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
      '<td>' + (item.rating == null ? '—' : item.rating.toFixed(1)) + '</td><td>' + item.reviews + '</td><td><div class="row-actions">' + rowButton('delete-snapshot', item.id, '删除', 'danger') + '</div></td></tr>';
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
  ['#purchaseLineProduct', '#stockProduct', '#orderLineProduct'].forEach(function (selector) {
    const select = $(selector);
    if (!select) return;
    const previous = select.value;
    select.innerHTML = productOptions || '<option value="">请先完善本店 SKU</option>';
    if (warehouseProducts.some(function (item) { return item.id === previous; })) select.value = previous;
  });
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
  if (!visible || state.ui.module !== 'competitors' || state.ui.competitorTab !== 'trends') return;
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

function render() {
  renderNavigation();
  renderSidebar();
  renderProductSummary();
  renderProducts();
  renderWarehouseSummary();
  renderPurchases();
  renderInventory();
  renderSelects();
  renderMovements();
  renderOrders();
  renderCompetitorProducts();
  renderHistory();
  renderTrendMetrics();
  renderAlerts();
  if (state.ui.module === 'competitors' && state.ui.competitorTab === 'trends') requestAnimationFrame(renderChart);
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
  $('#productSku').value = product ? product.sku : '';
  $('#sellerName').value = product ? product.seller : '';
  $('#productMarket').value = product ? product.market : 'MY';
  $('#productCurrency').value = product ? product.salesCurrency : ($('#productKind').value === 'own' ? 'CNY' : 'MYR');
  $('#productCost').value = product && product.kind === 'own' ? product.standardCost : '';
  $('#productSafetyStock').value = product && product.kind === 'own' ? product.safetyStock : 0;
  $('#productSupplier').value = product ? product.defaultSupplier : '';
  $('#productStatus').value = product ? product.status : 'active';
  $('#productUrl').value = product ? product.productUrl : '';
  $('#productPurchaseUrl').value = product ? product.purchaseUrl : '';
  $('#productCompare').checked = product ? product.monitoringEnabled : false;
  pendingProductImage = product ? product.image : '';
  $('#productImageUrl').value = product ? exportableImageUrl(product.image) : '';
  $('#initialSnapshotFields').hidden = Boolean(product);
  $('#firstSnapshotAt').value = localDateTime(new Date());
  ['#firstPrice', '#firstSold', '#firstRating', '#firstReviews', '#firstLowReviews', '#firstShopRating'].forEach(function (selector) { $(selector).value = ''; });
  toggleProductFields();
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
    if (!product.sku) missing.push('SKU');
    if (rawCost === '' || !Number.isFinite(Number(rawCost)) || Number(rawCost) < 0) missing.push('商品成本');
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
    createdAt: new Date().toISOString()
  };
}

async function compressProductImage(file) {
  if (!file || !/^image\/(jpeg|png|webp)$/i.test(file.type)) throw new Error('请选择 JPG、PNG 或 WebP 图片。');
  if (file.size > 8 * 1024 * 1024) throw new Error('原图不能超过 8MB。');
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
    return '<div class="line-list-item"><strong>' + escapeHtml(product ? product.sku + ' · ' + product.name : '未知商品') + '</strong>' +
      '<span>' + line.quantity + ' 件</span><span>' + money(line.unitCost, product ? product.costCurrency : 'CNY') + ' / 件</span>' +
      '<button class="line-remove" data-remove-purchase-line="' + escapeHtml(line.productId) + '" type="button">移除</button></div>';
  }).join('') : '<div class="last-value">请至少加入一条采购明细。</div>';
}
function openPurchaseEditor() {
  if (!ownProducts(state).filter(function (item) { return !item.needsReview; }).length) {
    showToast('请先在商品中心新增并完善本店 SKU。');
    setRoute('products');
    return;
  }
  $('#purchaseForm').reset();
  draftPurchaseLines = [];
  $('#purchaseNumber').value = 'PO-' + today().replace(/-/g, '') + '-' + String(Date.now()).slice(-4);
  $('#purchaseStatus').value = 'ordered';
  $('#purchaseOrderedAt').value = today();
  const eta = new Date(); eta.setDate(eta.getDate() + 14);
  $('#purchaseEta').value = localDateTime(eta).slice(0, 10);
  $('#purchaseExtraCost').value = 0;
  const first = productById($('#purchaseLineProduct').value);
  $('#purchaseSupplier').value = first ? first.defaultSupplier : '';
  $('#purchaseLineCost').value = first ? first.standardCost : '';
  renderPurchaseDraft();
  openModal('purchaseModal');
}
function renderOrderDraft() {
  $('#orderLineList').innerHTML = draftOrderLines.length ? draftOrderLines.map(function (line) {
    const product = productById(line.productId);
    return '<div class="line-list-item"><strong>' + escapeHtml(product ? product.sku + ' · ' + product.name : '未知商品') + '</strong>' +
      '<span>' + line.quantity + ' 件</span><span>可用 ' + availableFor(line.productId) + '</span>' +
      '<button class="line-remove" data-remove-order-line="' + escapeHtml(line.productId) + '" type="button">移除</button></div>';
  }).join('') : '<div class="last-value">请至少加入一条订单明细。</div>';
}
function openOrderEditor() {
  if (!ownProducts(state).filter(function (item) { return !item.needsReview; }).length) {
    showToast('请先在商品中心新增并完善本店 SKU。');
    setRoute('products');
    return;
  }
  $('#orderForm').reset();
  draftOrderLines = [];
  $('#orderNumber').value = 'SO-' + today().replace(/-/g, '') + '-' + String(Date.now()).slice(-4);
  $('#orderAt').value = localDateTime(new Date());
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
function updateStockHint() {
  const productId = $('#stockProduct').value;
  const balance = balanceFor(productId);
  setText('#stockHint', '当前已在库 ' + balance.onHand + '，锁定 ' + balance.reserved + '，可用 ' + Math.max(0, balance.onHand - balance.reserved) + '。');
}
function openReceiveEditor(purchaseId) {
  const order = state.purchaseOrders.find(function (item) { return item.id === purchaseId; });
  if (!order || !isPurchaseOpen(order)) return showToast('采购单当前不能收货。');
  $('#receiveForm').reset();
  $('#receivePurchaseId').value = order.id;
  $('#receiveIntro').textContent = order.number + ' · ' + order.supplier;
  $('#receiveLine').innerHTML = order.lines.filter(function (line) { return remainingPurchaseLine(line) > 0; }).map(function (line) {
    const product = productById(line.productId);
    return '<option value="' + escapeHtml(line.id) + '">' + escapeHtml((product ? product.sku + ' · ' + product.name : '未知商品') + '（未收 ' + remainingPurchaseLine(line) + '）') + '</option>';
  }).join('');
  $('#receiveAt').value = localDateTime(new Date());
  $('#receiveQty').value = 1;
  updateReceiveHint();
  openModal('receiveModal');
}
function updateReceiveHint() {
  const order = state.purchaseOrders.find(function (item) { return item.id === $('#receivePurchaseId').value; });
  const line = order && order.lines.find(function (item) { return item.id === $('#receiveLine').value; });
  const remaining = line ? remainingPurchaseLine(line) : 0;
  $('#receiveQty').max = remaining;
  setText('#receiveHint', '该明细最多还可收货 ' + remaining + ' 件。确认后会自动减少在途并增加已在库。');
}
function openReturnEditor(orderId) {
  const order = state.salesOrders.find(function (item) { return item.id === orderId; });
  if (!order || order.status !== 'shipped') return showToast('只有已出库订单可以办理退货入库。');
  const availableLines = order.lines.filter(function (line) { return returnableForLine(line) > 0; });
  if (!availableLines.length) return showToast('该订单所有商品都已完成退货，暂无可退数量。');
  $('#returnForm').reset();
  $('#returnOrderId').value = order.id;
  $('#returnIntro').textContent = order.number + ' · 退货会增加已在库，并生成独立库存流水。';
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
  setText('#returnHint', '该订单明细最多还可退货 ' + remaining + ' 件；已登记退货不会重复入库。');
}
function openSnapshotEditor(productId) {
  const monitoring = monitoredProducts(state);
  if (!monitoring.length) return showToast('请先添加竞品或开启本店商品对比。');
  $('#snapshotForm').reset();
  $('#snapshotProduct').value = monitoring.some(function (item) { return item.id === productId; }) ? productId : (state.selectedProductId || monitoring[0].id);
  $('#snapshotAt').value = localDateTime(new Date());
  fillSnapshotHint();
  openModal('snapshotModal');
}
function fillSnapshotHint() {
  const productId = $('#snapshotProduct').value;
  const latest = latestPair(productId).latest;
  if (!latest) {
    setText('#lastValueHint', '尚无历史数据，本次将作为基准快照。');
    return;
  }
  setText('#lastValueHint', '上次：' + formatDate(latest.at, true) + ' · ' + money(latest.price, latest.currency) + ' · 累计销量 ' + latest.sold + ' · 评价 ' + latest.reviews);
  $('#snapshotPrice').value = latest.price;
  $('#snapshotSold').value = latest.sold;
  $('#snapshotRating').value = latest.rating == null ? '' : latest.rating;
  $('#snapshotReviews').value = latest.reviews;
  $('#snapshotLowReviews').value = latest.lowReviews;
  $('#snapshotShopRating').value = latest.shopRating == null ? '' : latest.shopRating;
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
  const blob = new Blob(['\ufeff' + content], { type: type || 'text/csv;charset=utf-8' });
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

function saveProductFromForm(forceDraft) {
  const editId = $('#editProductId').value;
  const current = editId ? productById(editId) : null;
  const kind = $('#productKind').value;
  const requestedStatus = $('#productStatus').value;
  const draft = Boolean(forceDraft || requestedStatus === 'draft');
  const image = safeImageUrl(pendingProductImage || $('#productImageUrl').value);
  const product = normalizeProduct({
    id: editId || uid('product'),
    name: $('#productName').value,
    kind: kind,
    sku: kind === 'own' ? $('#productSku').value : '',
    seller: $('#sellerName').value,
    market: $('#productMarket').value,
    salesCurrency: $('#productCurrency').value,
    costCurrency: $('#productCurrency').value,
    standardCost: kind === 'own' ? $('#productCost').value : 0,
    safetyStock: kind === 'own' ? $('#productSafetyStock').value : 0,
    defaultSupplier: kind === 'own' ? $('#productSupplier').value : '',
    status: draft ? 'draft' : requestedStatus,
    productUrl: $('#productUrl').value,
    purchaseUrl: kind === 'own' ? $('#productPurchaseUrl').value : '',
    image: image,
    monitoringEnabled: kind !== 'own' || $('#productCompare').checked,
    needsReview: false,
    createdAt: current ? current.createdAt : new Date().toISOString(),
    updatedAt: new Date().toISOString()
  });
  const missing = productMissingFields(product, kind === 'own' ? $('#productCost').value : 0);
  product.needsReview = missing.length > 0;
  if (!product.name) return showToast('草稿也需要填写商品名称，便于后续识别。');
  if (!draft && missing.length) return showToast('请先补齐：' + missing.join('、') + '。');
  if (kind === 'own' && product.sku && state.products.some(function (item) { return item.id !== editId && item.kind === 'own' && normalizeSku(item.sku) === normalizeSku(product.sku); })) {
    return showToast('SKU 已存在，请使用唯一的本店 SKU。');
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
  const saved = commit(function (next) {
    const index = next.products.findIndex(function (item) { return item.id === product.id; });
    if (index >= 0) next.products[index] = product; else next.products.push(product);
    if (product.kind === 'own') ensureBalance(next, product.id);
    if (initialSnapshot) next.snapshots.push(initialSnapshot);
    if (!next.selectedProductId && product.status === 'active' && product.monitoringEnabled) next.selectedProductId = product.id;
    if (!product.needsReview) next.migrationIssues = next.migrationIssues.filter(function (issue) { return issue.productId !== product.id; });
  }, draft
    ? (missing.length ? '商品草稿已保存；补齐 ' + missing.join('、') + ' 后即可用于仓库业务。' : '商品草稿已保存。')
    : (current ? '商品已更新。' : '商品已添加。'));
  if (saved) closeModal('productModal');
}
function handleProductSubmit(event) {
  event.preventDefault();
  saveProductFromForm(false);
}

function handlePurchaseSubmit(event) {
  event.preventDefault();
  if (!draftPurchaseLines.length) return showToast('请至少加入一条采购明细。');
  const number = $('#purchaseNumber').value.trim();
  if (state.purchaseOrders.some(function (item) { return item.number.toLowerCase() === number.toLowerCase(); })) return showToast('采购单号不能重复。');
  const status = $('#purchaseStatus').value;
  const order = {
    id: uid('po'), number: number, supplier: $('#purchaseSupplier').value.trim(),
    warehouseId: DEFAULT_WAREHOUSE_ID, status: status,
    orderedAt: $('#purchaseOrderedAt').value, expectedAt: $('#purchaseEta').value,
    extraCost: nonNegative($('#purchaseExtraCost').value), note: $('#purchaseNote').value.trim(),
    lines: draftPurchaseLines.map(function (line) {
      return { id: uid('pol'), productId: line.productId, orderedQty: integer(line.quantity), receivedQty: 0, cancelledQty: 0, unitCost: nonNegative(line.unitCost) };
    }),
    createdAt: new Date().toISOString(), updatedAt: new Date().toISOString()
  };
  const saved = commit(function (next) { next.purchaseOrders.push(order); }, status === 'draft' ? '采购草稿已保存，不计入在途。' : '采购单已创建，已自动计入在途。');
  if (saved) closeModal('purchaseModal');
}
function handleReceiveSubmit(event) {
  event.preventDefault();
  const saved = commit(function (next) {
    receivePurchaseOrder(next, $('#receivePurchaseId').value, $('#receiveLine').value, $('#receiveQty').value, new Date($('#receiveAt').value).toISOString(), $('#receiveNote').value.trim());
  }, '收货完成：在途已减少，库存已增加。');
  if (saved) closeModal('receiveModal');
}
function handleStockSubmit(event) {
  event.preventDefault();
  const saved = commit(function (next) {
    adjustInventory(next, $('#stockProduct').value, $('#stockOperation').value, $('#stockQuantity').value, new Date($('#stockAt').value).toISOString(), $('#stockNote').value.trim());
  }, '库存调整已过账并记录流水。');
  if (saved) closeModal('stockModal');
}
function handleReturnSubmit(event) {
  event.preventDefault();
  const saved = commit(function (next) {
    receiveSalesReturn(next, $('#returnOrderId').value, $('#returnLine').value, $('#returnQty').value, new Date($('#returnAt').value).toISOString(), $('#returnNote').value.trim());
  }, '退货已入库，库存流水已生成。');
  if (saved) closeModal('returnModal');
}
function handleOrderSubmit(event) {
  event.preventDefault();
  if (!draftOrderLines.length) return showToast('请至少加入一条订单明细。');
  const number = $('#orderNumber').value.trim();
  if (state.salesOrders.some(function (item) { return item.number.toLowerCase() === number.toLowerCase(); })) return showToast('订单号不能重复。');
  let reserved = false;
  const saved = commit(function (next) {
    const order = {
      id: uid('order'), number: number, platform: $('#orderPlatform').value,
      store: $('#orderStore').value.trim(), orderedAt: new Date($('#orderAt').value).toISOString(),
      trackingNumber: $('#orderTracking').value.trim(), note: $('#orderNote').value.trim(),
      status: 'shortage', lines: draftOrderLines.map(function (line) {
        return { id: uid('order-line'), productId: line.productId, quantity: integer(line.quantity), reservedQty: 0, shippedQty: 0 };
      }),
      createdAt: new Date().toISOString(), updatedAt: new Date().toISOString()
    };
    next.salesOrders.push(order);
    reserved = reserveOrder(next, order.id);
  }, '');
  if (saved) {
    closeModal('orderModal');
    showToast(reserved ? '订单已创建并整单锁定库存。' : '订单已创建，但库存不足，未产生部分锁定。');
  }
}
function handleSnapshotSubmit(event) {
  event.preventDefault();
  const product = productById($('#snapshotProduct').value);
  if (!product) return showToast('请选择监控商品。');
  let snapshot;
  try { snapshot = snapshotFromForm('#snapshot', product, true); }
  catch (error) { return showToast(error.message); }
  if (state.snapshots.some(function (item) { return item.productId === product.id && new Date(item.at).getTime() === new Date(snapshot.at).getTime(); })) {
    return showToast('同一商品同一时间已经有一条快照。');
  }
  const saved = commit(function (next) {
    next.snapshots.push(snapshot);
    next.selectedProductId = product.id;
  }, snapshotChange(product.id).pair.latest && snapshot.sold < snapshotChange(product.id).pair.latest.sold ? '快照已保存；累计销量回退已标记为异常。' : '公开数据快照已保存。');
  if (saved) closeModal('snapshotModal');
}

function handleAction(action, id) {
  if (action === 'edit-product') return openProductEditor(id);
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
    return commit(function (next) {
      const product = productById(id, next);
      if (product) { product.status = active ? 'active' : 'inactive'; product.needsReview = false; product.updatedAt = new Date().toISOString(); }
    }, active ? '商品已启用。' : '商品已停用，历史单据和库存均已保留。');
  }
  if (action === 'delete-product') {
    const product = productById(id);
    if (!product) return;
    if (hasBusinessReferences(id) || productSnapshots(id).length) {
      if (product.status !== 'inactive') {
        return askConfirm('该商品已有历史记录，不能硬删除。是否改为停用？', function () {
          commit(function (next) { productById(id, next).status = 'inactive'; }, '商品已停用，历史数据已保留。');
        });
      }
      return showToast('该商品已有业务或快照记录，只能停用，不能删除。');
    }
    return askConfirm('确认彻底删除“' + product.name + '”？此操作不可撤销。', function () {
      commit(function (next) {
        next.products = next.products.filter(function (item) { return item.id !== id; });
        next.inventoryBalances = next.inventoryBalances.filter(function (item) { return item.productId !== id; });
      }, '商品已删除。');
    });
  }
  if (action === 'submit-purchase') return commit(function (next) {
    const order = next.purchaseOrders.find(function (item) { return item.id === id; });
    if (!order || order.status !== 'draft') throw new Error('采购单不是草稿状态。');
    order.status = 'ordered'; order.updatedAt = new Date().toISOString();
  }, '采购单已确认，开始计入在途。');
  if (action === 'transit-purchase') return commit(function (next) {
    const order = next.purchaseOrders.find(function (item) { return item.id === id; });
    if (!order || order.status !== 'ordered') throw new Error('采购单当前不能标记在途。');
    order.status = 'transit'; order.updatedAt = new Date().toISOString();
  }, '采购单已标记为在途。');
  if (action === 'receive-purchase') return openReceiveEditor(id);
  if (action === 'cancel-purchase') {
    return askConfirm('确认取消该采购单所有未收数量？已收货库存不会回退。', function () {
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
    let reserved = false;
    const saved = commit(function (next) { reserved = reserveOrder(next, id); }, '');
    if (saved) showToast(reserved ? '库存已整单锁定，订单进入拣货。' : '库存仍不足，未产生任何部分锁定。');
    return;
  }
  if (action === 'advance-order') return commit(function (next) {
    const order = next.salesOrders.find(function (item) { return item.id === id; });
    if (!order) throw new Error('订单不存在。');
    if (order.status === 'picking') order.status = 'review';
    else if (order.status === 'review') order.status = 'ready';
    else throw new Error('订单当前不能推进。');
    order.updatedAt = new Date().toISOString();
  }, '订单状态已更新。');
  if (action === 'ship-order') return askConfirm('确认订单已复核并完成出库？库存和锁定将同时扣减。', function () {
    commit(function (next) { shipOrder(next, id); }, '订单已出库，库存流水已生成。');
  });
  if (action === 'return-order') return openReturnEditor(id);
  if (action === 'cancel-order') return askConfirm('确认取消订单并释放已锁定库存？', function () {
    commit(function (next) { cancelOrder(next, id); }, '订单已取消，锁定库存已释放。');
  });
  if (action === 'delete-snapshot') return askConfirm('确认删除这条快照？趋势会重新计算。', function () {
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
    if (competitorTab) return setRoute('competitors', competitorTab.dataset.competitorTab);
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
    const action = event.target.closest('[data-action]');
    if (action) return handleAction(action.dataset.action, action.dataset.id);
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
  });
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
  $('#globalSearch').addEventListener('input', function (event) {
    searchTerm = event.target.value.trim().toLowerCase();
    renderProducts(); renderPurchases(); renderInventory(); renderMovements(); renderOrders(); renderCompetitorProducts();
  });
  ['#openProductModal', '#tableAddProduct', '#emptyAddProduct'].forEach(function (selector) {
    $(selector).addEventListener('click', function () { openProductEditor('', 'own'); });
  });
  ['#competitorAddProduct', '#competitorTableAdd'].forEach(function (selector) {
    $(selector).addEventListener('click', function () { openProductEditor('', 'direct'); });
  });
  $('#productKind').addEventListener('change', toggleProductFields);
  $('#productImageUrl').addEventListener('input', function () { pendingProductImage = $('#productImageUrl').value; updateProductImagePreview(); });
  $('#chooseProductImage').addEventListener('click', function () { $('#productImageFile').click(); });
  $('#productImageFile').addEventListener('change', async function (event) {
    try {
      pendingProductImage = await compressProductImage(event.target.files[0]);
      $('#productImageUrl').value = '';
      updateProductImagePreview();
      showToast('图片已压缩并保存到本机数据中。');
    } catch (error) {
      showToast(error.message);
    } finally {
      event.target.value = '';
    }
  });
  $('#removeProductImage').addEventListener('click', function () { pendingProductImage = ''; $('#productImageUrl').value = ''; updateProductImagePreview(); });
  $('#productForm').addEventListener('submit', handleProductSubmit);
  if ($('#saveProductDraft')) $('#saveProductDraft').addEventListener('click', function () { saveProductFromForm(true); });
  $('#openPurchaseModal').addEventListener('click', openPurchaseEditor);
  $('#purchaseLineProduct').addEventListener('change', function () {
    const product = productById(this.value);
    if (product) {
      $('#purchaseLineCost').value = product.standardCost;
      if (!$('#purchaseSupplier').value) $('#purchaseSupplier').value = product.defaultSupplier;
    }
  });
  $('#addPurchaseLine').addEventListener('click', function () {
    const productId = $('#purchaseLineProduct').value;
    const product = productById(productId);
    const quantity = integer($('#purchaseLineQty').value);
    const unitCost = nonNegative($('#purchaseLineCost').value);
    if (!product || product.kind !== 'own' || product.needsReview) return showToast('请选择已完善的本店 SKU。');
    if (!quantity) return showToast('采购数量必须大于 0。');
    const existing = draftPurchaseLines.find(function (line) { return line.productId === productId; });
    if (existing) { existing.quantity += quantity; existing.unitCost = unitCost; }
    else draftPurchaseLines.push({ productId: productId, quantity: quantity, unitCost: unitCost });
    $('#purchaseLineQty').value = '';
    renderPurchaseDraft();
  });
  $('#purchaseForm').addEventListener('submit', handlePurchaseSubmit);
  $('#receiveLine').addEventListener('change', updateReceiveHint);
  $('#receiveForm').addEventListener('submit', handleReceiveSubmit);
  $('#returnLine').addEventListener('change', updateReturnHint);
  $('#returnForm').addEventListener('submit', handleReturnSubmit);
  $('#openStockModal').addEventListener('click', function () { openStockEditor(''); });
  $('#stockProduct').addEventListener('change', updateStockHint);
  $('#stockForm').addEventListener('submit', handleStockSubmit);
  $('#openOrderModal').addEventListener('click', openOrderEditor);
  $('#addOrderLine').addEventListener('click', function () {
    const productId = $('#orderLineProduct').value;
    const product = productById(productId);
    const quantity = integer($('#orderLineQty').value);
    if (!product || product.kind !== 'own' || product.needsReview) return showToast('请选择已完善的本店 SKU。');
    if (!quantity) return showToast('订单数量必须大于 0。');
    const existing = draftOrderLines.find(function (line) { return line.productId === productId; });
    if (existing) existing.quantity += quantity;
    else draftOrderLines.push({ productId: productId, quantity: quantity });
    $('#orderLineQty').value = '';
    renderOrderDraft();
  });
  $('#orderForm').addEventListener('submit', handleOrderSubmit);
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
    if (callback) callback();
  });
  $('#clearAllData').addEventListener('click', function () {
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
  $('#importCsv').addEventListener('click', function () { $('#csvFile').click(); });
  $('#csvFile').addEventListener('change', async function (event) {
    const file = event.target.files[0];
    event.target.value = '';
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
    if (state.ui.module === 'competitors' && state.ui.competitorTab === 'trends') renderChart();
  });
  window.addEventListener('hashchange', function () { applyHashRoute(); closeSidebar(); render(); });
}

applyHashRoute();
bindEvents();
render();
