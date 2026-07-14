const STORAGE_KEY = 'pulsetrack.manual.v2';
const COLORS = ['#0e8e86', '#e89a42', '#607cce', '#cf655d', '#7a9b55', '#8c6bb1'];
const KIND_LABELS = { own: '本店', direct: '直接竞品', indirect: '间接竞品' };
const CURRENCY = { MYR: 'RM', USD: '$', GBP: '£', SGD: 'S$', THB: '฿', VND: '₫', PHP: '₱', IDR: 'Rp' };

const seedState = {
  version: 3,
  products: [{
    id: 'tt-my-1734050283349837382',
    name: '蝴蝶图案帆布托特包',
    seller: 'Tas Inspirasi',
    kind: 'direct',
    market: 'MY',
    currency: 'MYR',
    url: 'https://www.tiktok.com/view/product/1734050283349837382',
    image: '',
    createdAt: '2026-07-14T17:37:26+08:00'
  }],
  snapshots: [{
    id: 'snap-baseline-1734050283349837382',
    productId: 'tt-my-1734050283349837382',
    at: '2026-07-14T17:37:26+08:00',
    price: 18.69,
    sold: 901,
    rating: 4.8,
    reviews: 56,
    lowReviews: 1,
    shopRating: null
  }],
  selectedProductId: 'tt-my-1734050283349837382'
};

let state = loadState();
let chartMetric = 'sales';
let pendingConfirm = null;
let pendingProductImage = '';
let toastTimer;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function uid(prefix) { return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`; }
function escapeHtml(value = '') { return String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char])); }
function localDateTime(date = new Date()) { const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000); return local.toISOString().slice(0, 16); }
function safeImageUrl(value = '') {
  const text = String(value).trim();
  if (!text) return '';
  if (/^data:image\/(?:png|jpe?g|webp);base64,/i.test(text)) return text.length <= 560000 ? text : '';
  if (text.length > 4096) return '';
  try {
    const url = new URL(text);
    return ['http:', 'https:'].includes(url.protocol) ? text : '';
  } catch (_) { return ''; }
}
function exportableImageUrl(value = '') { const image = safeImageUrl(value); return /^https?:/i.test(image) ? image : ''; }

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && Array.isArray(saved.products) && Array.isArray(saved.snapshots)) {
      saved.version = 3;
      saved.products = saved.products.map(product => ({ ...product, image: safeImageUrl(product.image || '') }));
      return saved;
    }
  } catch (_) { /* use seed */ }
  return clone(seedState);
}

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    const chip = $('.storage-state');
    if (chip) { chip.innerHTML = '<i></i>刚刚已保存'; setTimeout(() => { chip.innerHTML = '<i></i>已自动保存'; }, 1400); }
    return true;
  } catch (_) {
    showToast('浏览器存储空间不足，请移除本地图片或改用图片网址。');
    return false;
  }
}

function productSnapshots(productId) {
  return state.snapshots.filter(item => item.productId === productId).sort((a, b) => new Date(a.at) - new Date(b.at));
}

function latestPair(productId) {
  const all = productSnapshots(productId);
  return { all, latest: all.at(-1), previous: all.at(-2) };
}

function changeFor(productId) {
  const { latest, previous } = latestPair(productId);
  if (!latest || !previous) return { baseline: true };
  const hours = (new Date(latest.at) - new Date(previous.at)) / 3600000;
  const soldRaw = Number(latest.sold) - Number(previous.sold);
  return {
    baseline: false,
    hours,
    sold: soldRaw >= 0 ? soldRaw : null,
    soldAnomaly: soldRaw < 0,
    price: Number(latest.price) - Number(previous.price),
    reviews: nullableDelta(latest.reviews, previous.reviews),
    lowReviews: nullableDelta(latest.lowReviews, previous.lowReviews)
  };
}

function nullableDelta(a, b) { return a === '' || a == null || b === '' || b == null ? null : Number(a) - Number(b); }
function fmtNumber(value) { return value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }); }
function fmtMoney(value, currency) { return value == null || value === '' ? '—' : `${CURRENCY[currency] || currency || ''}${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function fmtDate(value, withTime = true) { if (!value) return '—'; const date = new Date(value); return date.toLocaleString('zh-CN', withTime ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' } : { month: '2-digit', day: '2-digit' }); }
function elapsedLabel(hours) { if (!Number.isFinite(hours)) return '期间'; if (hours >= 20 && hours <= 28) return '昨日'; if (hours < 24) return `${Math.max(1, Math.round(hours))}小时`; return `${Math.round(hours / 24)}天`; }

function render() {
  renderSelectors();
  renderMetrics();
  renderProducts();
  renderHistory();
  renderChanges();
  renderChart();
  $('#navProductCount').textContent = state.products.length;
}

function renderSelectors() {
  if (state.selectedProductId && !state.products.some(p => p.id === state.selectedProductId)) state.selectedProductId = state.products[0]?.id || '';
  const options = state.products.map(p => `<option value="${p.id}">${escapeHtml(p.name)} · ${KIND_LABELS[p.kind]}</option>`).join('');
  $('#activeProduct').innerHTML = options || '<option value="">暂无商品</option>';
  $('#activeProduct').value = state.selectedProductId || '';
  $('#snapshotProduct').innerHTML = options;
  $('#historyProduct').innerHTML = `<option value="all">全部商品</option>${options}`;
  $('#openSnapshotModal').disabled = !state.products.length;
}

function renderMetrics() {
  const product = state.products.find(p => p.id === state.selectedProductId);
  if (!product) {
    $('#heroSummary').textContent = '添加商品并录入第一次快照，建立监控基准。';
    ['#salesMetric', '#priceMetric', '#rankMetric'].forEach(id => $(id).textContent = '—');
    $('#alertMetric').innerHTML = '0 <small>项</small>';
    return;
  }
  const { latest } = latestPair(product.id);
  const change = changeFor(product.id);
  $('#heroSummary').textContent = `${KIND_LABELS[product.kind]} · ${product.seller || '未填写店铺'} · ${product.market} · ${productSnapshots(product.id).length} 次快照`;
  $('#salesMetricLabel').textContent = change.baseline ? '期间新增销量' : `${elapsedLabel(change.hours)}新增销量`;
  $('#salesMetric').innerHTML = change.sold == null ? '—' : `${fmtNumber(change.sold)} <small>件</small>`;
  const salesFoot = $('#salesMetricFoot');
  salesFoot.className = `metric-foot ${change.sold > 0 ? 'up' : ''}`;
  salesFoot.textContent = change.soldAnomaly ? '累计销量下降，已标记异常' : change.baseline ? '需要至少两次快照' : `两次记录相隔 ${change.hours.toFixed(1)} 小时`;
  $('#priceMetric').textContent = latest ? fmtMoney(latest.price, product.currency) : '—';
  const priceFoot = $('#priceMetricFoot');
  priceFoot.className = `metric-foot ${change.price < 0 ? 'down' : change.price > 0 ? 'up' : ''}`;
  priceFoot.textContent = change.baseline ? '已建立价格基准' : change.price === 0 ? '价格保持不变' : `${change.price > 0 ? '上涨' : '下降'} ${fmtMoney(Math.abs(change.price), product.currency)}`;

  const ranked = state.products.map(p => ({ p, c: changeFor(p.id) })).filter(x => Number.isFinite(x.c.sold)).sort((a, b) => b.c.sold - a.c.sold);
  const index = ranked.findIndex(x => x.p.id === product.id);
  $('#rankMetric').innerHTML = index < 0 ? '—' : `${index + 1}<small> / ${ranked.length}</small>`;
  $('#rankMetricFoot').textContent = index < 0 ? '需要至少两个可比较快照' : `按各商品最近一个记录周期排名`;

  const alerts = getAlerts();
  $('#alertMetric').innerHTML = `${alerts.length} <small>项</small>`;
  $('#alertMetricFoot').textContent = alerts[0]?.text || '暂无异常变化';
  $('#navAlertCount').textContent = alerts.length;
}

function renderProducts() {
  const rows = state.products.map(product => {
    const { latest } = latestPair(product.id);
    const change = changeFor(product.id);
    const image = safeImageUrl(product.image);
    const media = `${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}" loading="lazy" />` : ''}<span class="product-badge ${product.kind}">${product.kind === 'own' ? 'ME' : product.kind === 'direct' ? 'DC' : 'IC'}</span>`;
    const delta = change.soldAnomaly ? '<span class="delta-pill down">异常</span>' : change.sold == null ? '<span class="delta-pill neutral">待比较</span>' : `<span class="delta-pill ${change.sold > 0 ? 'up' : 'neutral'}">+${fmtNumber(change.sold)}</span>`;
    return `<tr>
      <td><div class="product-cell"><span class="product-media">${media}</span><div class="product-copy"><strong>${escapeHtml(product.name)}</strong><span>${escapeHtml(product.seller || '未填写店铺')} · ${escapeHtml(product.market)}${product.url ? ' · 已保存链接' : ''}</span></div></div></td>
      <td><span class="type-pill ${product.kind}">${KIND_LABELS[product.kind]}</span></td>
      <td>${latest ? fmtDate(latest.at) : '—'}</td><td>${latest ? fmtMoney(latest.price, product.currency) : '—'}</td><td>${latest ? fmtNumber(latest.sold) : '—'}</td><td>${delta}</td>
      <td>${latest?.rating ?? '—'} / ${latest?.reviews ?? '—'}</td>
      <td><div class="row-actions"><button class="row-action primary" data-action="snapshot" data-id="${product.id}">录快照</button><button class="row-action" data-action="edit" data-id="${product.id}">编辑</button><button class="row-action danger" data-action="delete-product" data-id="${product.id}">删除</button></div></td>
    </tr>`;
  }).join('');
  $('#productRows').innerHTML = rows;
  $$('#productRows .product-media img').forEach(image => image.addEventListener('error', () => { image.hidden = true; }));
  $('#productEmpty').classList.toggle('show', !state.products.length);
}

function renderHistory() {
  const filter = $('#historyProduct').value || 'all';
  const productMap = Object.fromEntries(state.products.map(p => [p.id, p]));
  const list = state.snapshots.filter(s => filter === 'all' || s.productId === filter).sort((a, b) => new Date(b.at) - new Date(a.at));
  $('#historyRows').innerHTML = list.map(snapshot => {
    const product = productMap[snapshot.productId];
    if (!product) return '';
    const all = productSnapshots(product.id);
    const position = all.findIndex(item => item.id === snapshot.id);
    const previous = position > 0 ? all[position - 1] : null;
    const raw = previous ? Number(snapshot.sold) - Number(previous.sold) : null;
    const delta = raw == null ? '<span class="delta-pill neutral">基准</span>' : raw < 0 ? '<span class="delta-pill down">异常</span>' : `<span class="delta-pill ${raw ? 'up' : 'neutral'}">+${fmtNumber(raw)}</span>`;
    return `<tr><td>${fmtDate(snapshot.at)}</td><td>${escapeHtml(product.name)}</td><td>${fmtMoney(snapshot.price, product.currency)}</td><td>${fmtNumber(snapshot.sold)}</td><td>${delta}</td><td>${snapshot.rating ?? '—'}</td><td>${snapshot.reviews ?? '—'}</td><td><button class="row-action danger" data-action="delete-snapshot" data-id="${snapshot.id}">删除</button></td></tr>`;
  }).join('');
  $('#historyEmpty').classList.toggle('show', !list.length);
}

function renderChanges() {
  const items = [];
  state.products.forEach(product => {
    const change = changeFor(product.id);
    const { latest } = latestPair(product.id);
    if (!latest) return;
    if (change.baseline) items.push({ icon: '•', kind: 'base', title: product.name, detail: `${fmtDate(latest.at)} 建立首个基准`, value: 'BASE' });
    else {
      if (change.soldAnomaly) items.push({ icon: '!', kind: 'price', title: product.name, detail: '累计销量低于前次记录，请检查录入', value: '异常', down: true });
      else items.push({ icon: '↗', kind: 'sales', title: product.name, detail: `${elapsedLabel(change.hours)}新增销量`, value: `+${fmtNumber(change.sold)}` });
      if (change.price !== 0) items.push({ icon: '¥', kind: 'price', title: product.name, detail: change.price < 0 ? '公开价格下降' : '公开价格上涨', value: `${change.price > 0 ? '+' : '−'}${fmtMoney(Math.abs(change.price), product.currency)}`, down: change.price < 0 });
      if (change.reviews) items.push({ icon: '★', kind: 'review', title: product.name, detail: '评价总数发生变化', value: `${change.reviews > 0 ? '+' : ''}${change.reviews}`, down: change.reviews < 0 });
    }
  });
  $('#changeList').innerHTML = items.slice(0, 7).map(item => `<div class="change-item"><div class="change-icon ${item.kind}">${item.icon}</div><div class="change-copy"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}</span></div><b class="change-value ${item.down ? 'down' : ''}">${item.value}</b></div>`).join('') || '<div class="change-empty">录入快照后，这里会自动生成变化记录。</div>';
}

function getAlerts() {
  const alerts = [];
  state.products.forEach(product => {
    const change = changeFor(product.id);
    if (change.soldAnomaly) alerts.push({ productId: product.id, text: `${product.name} 累计销量下降` });
    if (Number.isFinite(change.price) && change.price < 0) alerts.push({ productId: product.id, text: `${product.name} 降价 ${fmtMoney(Math.abs(change.price), product.currency)}` });
    if (Number.isFinite(change.lowReviews) && change.lowReviews >= 3) alerts.push({ productId: product.id, text: `${product.name} 新增 ${change.lowReviews} 条低星评价` });
  });
  return alerts;
}

function chartSeries(product) {
  const all = productSnapshots(product.id);
  if (chartMetric === 'sales') return all.slice(1).map((item, index) => ({ at: item.at, value: Math.max(0, Number(item.sold) - Number(all[index].sold)) }));
  if (chartMetric === 'price') return all.map(item => ({ at: item.at, value: Number(item.price) }));
  return all.filter(item => item.reviews !== '' && item.reviews != null).map(item => ({ at: item.at, value: Number(item.reviews) }));
}

function renderChart() {
  const canvas = $('#trendChart');
  const series = state.products.map((product, index) => ({ product, color: COLORS[index % COLORS.length], points: chartSeries(product) })).filter(item => item.points.length);
  $('#chartLegend').innerHTML = series.map(item => `<span><i style="background:${item.color}"></i>${escapeHtml(item.product.name)}</span>`).join('');
  $('#chartSubtitle').textContent = chartMetric === 'sales' ? '相邻两次累计销量之差' : chartMetric === 'price' ? '每次快照记录的公开价格' : '每次快照记录的评价总数';
  const empty = !series.length;
  $('#chartEmpty').classList.toggle('show', empty);
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(320, Math.round(rect.width * dpr));
  canvas.height = Math.round(278 * dpr);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const width = canvas.width / dpr, height = canvas.height / dpr;
  ctx.clearRect(0, 0, width, height);
  if (empty) return;
  const pad = { left: 47, right: 20, top: 13, bottom: 31 };
  const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
  const allPoints = series.flatMap(item => item.points);
  const minTime = Math.min(...allPoints.map(p => new Date(p.at).getTime()));
  const maxTime = Math.max(...allPoints.map(p => new Date(p.at).getTime()));
  const values = allPoints.map(p => p.value);
  let minValue = chartMetric === 'price' ? Math.min(...values) : 0;
  let maxValue = Math.max(...values);
  if (maxValue === minValue) { maxValue += maxValue === 0 ? 1 : maxValue * .08; minValue = Math.max(0, minValue - maxValue * .08); }
  const x = time => pad.left + ((new Date(time).getTime() - minTime) / (maxTime - minTime || 1)) * plotW;
  const y = value => pad.top + plotH - ((value - minValue) / (maxValue - minValue || 1)) * plotH;
  ctx.font = '9px system-ui'; ctx.fillStyle = '#8a979a'; ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const py = pad.top + (plotH / 4) * i;
    ctx.strokeStyle = '#e8eceb'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(pad.left, py); ctx.lineTo(width - pad.right, py); ctx.stroke();
    const label = maxValue - ((maxValue - minValue) / 4) * i; ctx.fillText(Number(label.toFixed(1)).toLocaleString(), pad.left - 8, py + 3);
  }
  series.forEach(item => {
    ctx.strokeStyle = item.color; ctx.fillStyle = item.color; ctx.lineWidth = 2.2; ctx.lineJoin = 'round'; ctx.beginPath();
    item.points.forEach((point, index) => { const px = x(point.at), py = y(point.value); index ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.stroke();
    item.points.forEach(point => { ctx.beginPath(); ctx.arc(x(point.at), y(point.value), 3.2, 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.2; ctx.stroke(); });
  });
  ctx.fillStyle = '#8a979a'; ctx.textAlign = 'center';
  const dates = [...new Set(allPoints.map(p => fmtDate(p.at, false)))];
  const tickDates = dates.length <= 6 ? dates : dates.filter((_, i) => i % Math.ceil(dates.length / 6) === 0 || i === dates.length - 1);
  tickDates.forEach(label => { const point = allPoints.find(p => fmtDate(p.at, false) === label); ctx.fillText(label, x(point.at), height - 9); });
}

function openModal(id) { const modal = $(`#${id}`); modal.classList.add('open'); modal.setAttribute('aria-hidden', 'false'); }
function closeModal(id) { const modal = $(`#${id}`); modal.classList.remove('open'); modal.setAttribute('aria-hidden', 'true'); }
function showToast(message) { clearTimeout(toastTimer); const toast = $('#toast'); toast.textContent = message; toast.classList.add('show'); toastTimer = setTimeout(() => toast.classList.remove('show'), 2800); }

function updateProductImagePreview(value = '') {
  pendingProductImage = safeImageUrl(value);
  const preview = $('#productImagePreview');
  const empty = $('#productImageEmpty');
  if (pendingProductImage) {
    preview.src = pendingProductImage;
    preview.hidden = false;
    empty.hidden = true;
    $('#removeProductImage').disabled = false;
  } else {
    preview.removeAttribute('src');
    preview.hidden = true;
    empty.hidden = false;
    empty.textContent = '暂无图片';
    $('#removeProductImage').disabled = true;
  }
}

function loadLocalImage(file) {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => { URL.revokeObjectURL(objectUrl); resolve(image); };
    image.onerror = () => { URL.revokeObjectURL(objectUrl); reject(new Error('无法读取这张图片')); };
    image.src = objectUrl;
  });
}

function renderCompressedImage(image, maxSide, quality) {
  const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL('image/webp', quality);
  if (!/^data:image\/(?:png|jpe?g|webp);base64,/i.test(dataUrl)) throw new Error('浏览器无法压缩这张图片');
  return dataUrl;
}

async function compressProductImage(file) {
  const supported = ['image/jpeg', 'image/png', 'image/webp'];
  if (!supported.includes(file.type)) throw new Error('请选择 JPG、PNG 或 WebP 图片');
  if (file.size > 12 * 1024 * 1024) throw new Error('原图片不能超过 12 MB');
  const image = await loadLocalImage(file);
  let maxSide = 720;
  let quality = .78;
  let result = renderCompressedImage(image, maxSide, quality);
  while (result.length > 360000 && maxSide > 280) {
    maxSide = Math.round(maxSide * .78);
    quality = Math.max(.5, quality - .08);
    result = renderCompressedImage(image, maxSide, quality);
  }
  if (result.length > 560000) throw new Error('压缩后仍然过大，请换一张图片或使用图片网址');
  return result;
}

function openNewProduct() {
  $('#productForm').reset(); $('#editProductId').value = ''; $('#productModalTitle').textContent = '添加监控商品'; $('#saveProductButton').textContent = '保存并建立基准'; $('#initialSnapshotFields').hidden = false;
  updateProductImagePreview(''); $('#firstSnapshotAt').value = localDateTime(); $('#productMarket').value = 'MY'; $('#productCurrency').value = 'MYR'; $('#productKind').value = 'direct'; openModal('productModal'); $('#productName').focus();
}

function openEditProduct(id) {
  const product = state.products.find(p => p.id === id); if (!product) return;
  $('#productForm').reset(); $('#editProductId').value = product.id; $('#productName').value = product.name; $('#sellerName').value = product.seller || ''; $('#productKind').value = product.kind; $('#productMarket').value = product.market; $('#productUrl').value = product.url || ''; $('#productCurrency').value = product.currency; $('#productImageUrl').value = exportableImageUrl(product.image); updateProductImagePreview(product.image);
  $('#productModalTitle').textContent = '编辑商品资料'; $('#saveProductButton').textContent = '保存修改'; $('#initialSnapshotFields').hidden = true; openModal('productModal');
}

function openNewSnapshot(productId = state.selectedProductId) {
  if (!state.products.length) return openNewProduct();
  $('#snapshotForm').reset(); $('#snapshotProduct').value = productId || state.products[0].id; $('#snapshotAt').value = localDateTime(); prefillSnapshot(); openModal('snapshotModal'); $('#snapshotPrice').focus();
}

function prefillSnapshot() {
  const id = $('#snapshotProduct').value; const product = state.products.find(p => p.id === id); const { latest } = latestPair(id);
  if (!product || !latest) { $('#lastValueHint').textContent = '这是该商品的第一条快照。'; return; }
  $('#snapshotPrice').value = latest.price ?? ''; $('#snapshotSold').value = latest.sold ?? ''; $('#snapshotRating').value = latest.rating ?? ''; $('#snapshotReviews').value = latest.reviews ?? ''; $('#snapshotLowReviews').value = latest.lowReviews ?? ''; $('#snapshotShopRating').value = latest.shopRating ?? '';
  $('#lastValueHint').innerHTML = `上次记录：${fmtDate(latest.at)}　价格 <b>${fmtMoney(latest.price, product.currency)}</b>　累计销量 <b>${fmtNumber(latest.sold)}</b>　评价 <b>${latest.reviews ?? '—'}</b>`;
}

$('#productForm').addEventListener('submit', event => {
  event.preventDefault();
  const imageUrlValue = $('#productImageUrl').value.trim();
  const image = imageUrlValue ? safeImageUrl(imageUrlValue) : safeImageUrl(pendingProductImage);
  if (imageUrlValue && !image) { showToast('图片网址无效，请使用 http 或 https 地址。'); return; }
  const editId = $('#editProductId').value;
  if (editId) {
    const product = state.products.find(p => p.id === editId); if (!product) return;
    const before = clone(product);
    Object.assign(product, { name: $('#productName').value.trim(), seller: $('#sellerName').value.trim(), kind: $('#productKind').value, market: $('#productMarket').value, currency: $('#productCurrency').value, url: $('#productUrl').value.trim(), image });
    if (!saveState()) { Object.assign(product, before); return; }
    closeModal('productModal'); render(); showToast('商品资料已更新。'); return;
  }
  const id = uid('product');
  const snapshotId = uid('snapshot');
  const previousSelection = state.selectedProductId;
  state.products.push({ id, name: $('#productName').value.trim(), seller: $('#sellerName').value.trim(), kind: $('#productKind').value, market: $('#productMarket').value, currency: $('#productCurrency').value, url: $('#productUrl').value.trim(), image, createdAt: new Date().toISOString() });
  state.snapshots.push({ id: snapshotId, productId: id, at: new Date($('#firstSnapshotAt').value).toISOString(), price: Number($('#firstPrice').value), sold: Number($('#firstSold').value), rating: valueOrNull('#firstRating'), reviews: valueOrNull('#firstReviews'), lowReviews: valueOrNull('#firstLowReviews'), shopRating: valueOrNull('#firstShopRating') });
  state.selectedProductId = id;
  if (!saveState()) { state.products = state.products.filter(product => product.id !== id); state.snapshots = state.snapshots.filter(snapshot => snapshot.id !== snapshotId); state.selectedProductId = previousSelection; return; }
  closeModal('productModal'); render(); showToast('商品已添加，第一条基准快照已建立。');
});

$('#snapshotForm').addEventListener('submit', event => {
  event.preventDefault(); const productId = $('#snapshotProduct').value;
  const snapshotId = uid('snapshot'); const previousSelection = state.selectedProductId;
  state.snapshots.push({ id: snapshotId, productId, at: new Date($('#snapshotAt').value).toISOString(), price: Number($('#snapshotPrice').value), sold: Number($('#snapshotSold').value), rating: valueOrNull('#snapshotRating'), reviews: valueOrNull('#snapshotReviews'), lowReviews: valueOrNull('#snapshotLowReviews'), shopRating: valueOrNull('#snapshotShopRating') });
  state.selectedProductId = productId;
  if (!saveState()) { state.snapshots = state.snapshots.filter(snapshot => snapshot.id !== snapshotId); state.selectedProductId = previousSelection; return; }
  closeModal('snapshotModal'); render(); const change = changeFor(productId); showToast(change.soldAnomaly ? '快照已保存；累计销量下降，已标记异常。' : `快照已保存，期间新增销量 ${change.sold ?? '待下次计算'} 件。`);
});

function valueOrNull(selector) { const value = $(selector).value; return value === '' ? null : Number(value); }

function askConfirm(text, action) { pendingConfirm = action; $('#confirmText').textContent = text; $('#confirmBar').classList.add('show'); $('#confirmBar').setAttribute('aria-hidden', 'false'); }
function closeConfirm() { pendingConfirm = null; $('#confirmBar').classList.remove('show'); $('#confirmBar').setAttribute('aria-hidden', 'true'); }
$('#acceptConfirm').addEventListener('click', () => { const action = pendingConfirm; closeConfirm(); if (action) action(); });
$('#cancelConfirm').addEventListener('click', closeConfirm);

document.addEventListener('click', event => {
  const close = event.target.closest('[data-close]'); if (close) return closeModal(close.dataset.close);
  const action = event.target.closest('[data-action]'); if (!action) return;
  const { action: type, id } = action.dataset;
  if (type === 'snapshot') openNewSnapshot(id);
  if (type === 'edit') openEditProduct(id);
  if (type === 'delete-product') { const product = state.products.find(p => p.id === id); askConfirm(`删除“${product?.name || '该商品'}”及全部快照？`, () => { state.products = state.products.filter(p => p.id !== id); state.snapshots = state.snapshots.filter(s => s.productId !== id); if (state.selectedProductId === id) state.selectedProductId = state.products[0]?.id || ''; saveState(); render(); showToast('商品及其快照已删除。'); }); }
  if (type === 'delete-snapshot') askConfirm('删除这条快照？删除后相关增量会重新计算。', () => { state.snapshots = state.snapshots.filter(s => s.id !== id); saveState(); render(); showToast('快照已删除，变化数据已重新计算。'); });
});

['openProductModal', 'tableAddProduct', 'emptyAddProduct'].forEach(id => $(`#${id}`).addEventListener('click', openNewProduct));
$('#openSnapshotModal').addEventListener('click', () => openNewSnapshot());
$('#snapshotProduct').addEventListener('change', prefillSnapshot);
$('#activeProduct').addEventListener('change', event => { state.selectedProductId = event.target.value; saveState(); render(); });
$('#historyProduct').addEventListener('change', renderHistory);
$$('.chart-tab').forEach(button => button.addEventListener('click', () => { $$('.chart-tab').forEach(item => item.classList.remove('active')); button.classList.add('active'); chartMetric = button.dataset.metric; renderChart(); }));
$$('.modal-backdrop').forEach(modal => modal.addEventListener('click', event => { if (event.target === modal) closeModal(modal.id); }));
document.addEventListener('keydown', event => { if (event.key === 'Escape') $$('.modal-backdrop.open').forEach(modal => closeModal(modal.id)); });
window.addEventListener('resize', debounce(renderChart, 120));

$('#productImagePreview').addEventListener('load', event => { event.target.hidden = false; $('#productImageEmpty').hidden = true; });
$('#productImagePreview').addEventListener('error', event => { event.target.hidden = true; const empty = $('#productImageEmpty'); empty.hidden = false; empty.textContent = '图片无法显示'; });
$('#chooseProductImage').addEventListener('click', () => $('#productImageFile').click());
$('#removeProductImage').addEventListener('click', () => { $('#productImageUrl').value = ''; $('#productImageFile').value = ''; updateProductImagePreview(''); });
$('#productImageUrl').addEventListener('change', event => {
  const value = event.target.value.trim();
  if (value && !safeImageUrl(value)) { showToast('图片网址无效，请使用 http 或 https 地址。'); return; }
  updateProductImagePreview(value);
});
$('#productImageFile').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  const button = $('#chooseProductImage'); const oldText = button.textContent; button.disabled = true; button.textContent = '正在压缩…';
  try {
    const image = await compressProductImage(file);
    $('#productImageUrl').value = '';
    updateProductImagePreview(image);
    showToast('图片已压缩并加入商品资料。');
  } catch (error) { showToast(error.message); }
  finally { button.disabled = false; button.textContent = oldText; event.target.value = ''; }
});

$('#clearAllData').addEventListener('click', () => askConfirm('清空所有商品和快照？建议先导出数据备份。', () => { state = { version: 3, products: [], snapshots: [], selectedProductId: '' }; saveState(); render(); showToast('全部本机数据已清空。'); }));

function csvEscape(value) { const text = value == null ? '' : String(value); return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text; }
function exportCsv(template = false) {
  const header = ['date','name','seller','type','url','image_url','market','currency','price','cumulative_sales','rating','reviews','low_star_reviews','shop_rating'];
  let rows = [];
  if (template) rows = [[localDateTime().replace('T',' '),'示例商品','示例店铺','direct','https://www.tiktok.com/view/product/...','https://example.com/product.jpg','MY','MYR','18.69','901','4.8','56','1','4.7']];
  else {
    const map = Object.fromEntries(state.products.map(p => [p.id, p]));
    rows = [...state.snapshots].sort((a,b) => new Date(a.at)-new Date(b.at)).map(s => { const p = map[s.productId]; return p ? [s.at,p.name,p.seller,p.kind,p.url,exportableImageUrl(p.image),p.market,p.currency,s.price,s.sold,s.rating,s.reviews,s.lowReviews,s.shopRating] : null; }).filter(Boolean);
  }
  const csv = '\ufeff' + [header, ...rows].map(row => row.map(csvEscape).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = template ? 'pulsetrack-import-template.csv' : `pulsetrack-export-${new Date().toISOString().slice(0,10)}.csv`; link.click(); URL.revokeObjectURL(url);
}

function parseCsv(text) {
  const rows = []; let row = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) { const char = text[i], next = text[i+1]; if (char === '"' && quoted && next === '"') { field += '"'; i++; } else if (char === '"') quoted = !quoted; else if (char === ',' && !quoted) { row.push(field); field = ''; } else if ((char === '\n' || char === '\r') && !quoted) { if (char === '\r' && next === '\n') i++; row.push(field); if (row.some(v => v.trim())) rows.push(row); row = []; field = ''; } else field += char; }
  row.push(field); if (row.some(v => v.trim())) rows.push(row); return rows;
}

$('#csvFile').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    const before = clone(state);
    const rows = parseCsv((await file.text()).replace(/^\ufeff/, '')); const headers = rows.shift().map(h => h.trim()); let addedProducts = 0, addedSnapshots = 0;
    rows.forEach(values => {
      const record = Object.fromEntries(headers.map((h, i) => [h, values[i]?.trim() ?? ''])); if (!record.name || !record.date) return;
      const image = exportableImageUrl(record.image_url || record.image || '');
      let product = state.products.find(p => p.url && record.url && p.url === record.url) || state.products.find(p => p.name === record.name && p.market === (record.market || 'MY'));
      if (!product) { product = { id: uid('product'), name: record.name, seller: record.seller || '', kind: normalizeKind(record.type), market: record.market || 'MY', currency: record.currency || 'MYR', url: record.url || '', image, createdAt: new Date().toISOString() }; state.products.push(product); addedProducts++; }
      else if (image) product.image = image;
      state.snapshots.push({ id: uid('snapshot'), productId: product.id, at: new Date(record.date.replace(' ', 'T')).toISOString(), price: Number(record.price || 0), sold: Number(record.cumulative_sales || 0), rating: record.rating === '' ? null : Number(record.rating), reviews: record.reviews === '' ? null : Number(record.reviews), lowReviews: record.low_star_reviews === '' ? null : Number(record.low_star_reviews), shopRating: record.shop_rating === '' ? null : Number(record.shop_rating) }); addedSnapshots++;
    });
    if (!state.selectedProductId) state.selectedProductId = state.products[0]?.id || '';
    if (!saveState()) { state = before; return; }
    render(); showToast(`导入完成：${addedProducts} 个新商品，${addedSnapshots} 条快照。`);
  } catch (error) { showToast(`导入失败：${error.message}`); }
  event.target.value = '';
});

function normalizeKind(value = '') { const text = value.toLowerCase(); if (text === 'own' || text.includes('本店')) return 'own'; if (text === 'indirect' || text.includes('间接')) return 'indirect'; return 'direct'; }
function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }

$('#importCsv').addEventListener('click', () => $('#csvFile').click());
$('#exportCsv').addEventListener('click', () => exportCsv(false));
$('#downloadTemplate').addEventListener('click', () => exportCsv(true));

render();
