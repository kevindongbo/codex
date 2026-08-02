(function (root) {
  'use strict';

  const runtime = Object.assign({ apiBase: '/api' }, root.DONGBO_CONFIG || {});
  const fallbackTree = [
    { label: '箱包', children: [{ label: '女包', children: [
      { code: 'bag-womens-womens-backpacks', label: '女士双肩包' },
      { code: 'bag-womens-womens-handbags', label: '女士手提包' },
      { code: 'bag-womens-womens-tote-bags', label: '女士托特包' }
    ] }] },
    { label: '美妆个护', children: [{ label: '护肤', children: [
      { code: 'beauty-skincare-cleanser', label: '洁面' },
      { code: 'beauty-skincare-serum', label: '面部精华' },
      { code: 'beauty-skincare-sunscreen', label: '防晒' }
    ] }] }
  ];
  const RATE_STORAGE_KEY = 'dongbo-profit-rate-v1';
  const COMMISSION_ADJUSTMENT_KEY = 'dongbo-profit-commission-adjustment-v1';
  let categoryTree = fallbackTree;
  let categories = [];
  let rowSequence = 0;
  let displayCurrency = 'MYR';
  let openCategoryRow = null;
  let rateMode = 'auto';
  let manualCommissionRate = null;
  const buyerShippingByRow = new Map();

  function el(id) { return document.getElementById(id); }
  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, function (char) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char];
    });
  }
  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  function fixed(value) { return number(value).toFixed(2); }
  function formatMoney(value, currency) {
    const target = currency || displayCurrency;
    const amount = target === 'CNY' ? number(value) * number(el('profitExchangeRate').value) : number(value);
    const prefix = target === 'CNY' ? '¥ ' : 'RM ';
    return prefix + amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function formatCost(value) { return '− ' + formatMoney(value); }
  function saveRatePreference(payload) {
    try { localStorage.setItem(RATE_STORAGE_KEY, JSON.stringify(payload)); } catch (_) { /* optional */ }
  }
  function ratePreference() {
    try { return JSON.parse(localStorage.getItem(RATE_STORAGE_KEY) || '{}'); } catch (_) { return {}; }
  }
  function savedCommissionAdjustment(fallback) {
    try {
      const saved = localStorage.getItem(COMMISSION_ADJUSTMENT_KEY);
      return saved == null ? fallback : saved;
    } catch (_) { return fallback; }
  }
  function persistCommissionAdjustment(value) {
    try { localStorage.setItem(COMMISSION_ADJUSTMENT_KEY, value); } catch (_) { /* optional */ }
  }

  async function request(path, options) {
    if (root.DongboTeam) return new root.DongboTeam.TeamGateway(runtime).request(path, options);
    const settings = Object.assign({ headers: { Accept: 'application/json' } }, options || {});
    if (settings.body && typeof settings.body !== 'string') {
      settings.headers['Content-Type'] = 'application/json';
      settings.body = JSON.stringify(settings.body);
    }
    const response = await fetch(runtime.apiBase + path, settings);
    const payload = await response.json();
    if (!response.ok) {
      const error = new Error(payload.detail || '请求失败');
      error.data = payload;
      throw error;
    }
    return payload;
  }

  function updateRateUi(meta) {
    const automatic = rateMode === 'auto';
    el('profitExchangeRate').readOnly = automatic;
    el('profitUsdRate').readOnly = automatic;
    el('profitRateAuto').classList.toggle('active', automatic);
    el('profitRateManual').classList.toggle('active', !automatic);
    el('profitRateMode').textContent = automatic
      ? ('自动更新 · ECB' + (meta && meta.date ? ' · ' + meta.date : ''))
      : '手动汇率';
  }

  async function loadExchangeRates(force) {
    const saved = ratePreference();
    rateMode = saved.mode === 'manual' ? 'manual' : 'auto';
    if (rateMode === 'manual' && !force) {
      if (saved.cny_per_myr) el('profitExchangeRate').value = saved.cny_per_myr;
      if (saved.usd_per_myr) el('profitUsdRate').value = saved.usd_per_myr;
      updateRateUi(saved);
      return;
    }
    rateMode = 'auto';
    updateRateUi(saved);
    try {
      const rates = await request('/profit-calculator/exchange-rates/' + (force ? '?refresh=1' : ''));
      el('profitExchangeRate').value = number(rates.cny_per_myr).toFixed(6);
      el('profitUsdRate').value = number(rates.usd_per_myr).toFixed(6);
      saveRatePreference({ mode: 'auto', date: rates.date, source: rates.source, cny_per_myr: el('profitExchangeRate').value, usd_per_myr: el('profitUsdRate').value });
      updateRateUi(rates);
      rerenderLastResult();
    } catch (_) {
      if (saved.cny_per_myr) el('profitExchangeRate').value = saved.cny_per_myr;
      if (saved.usd_per_myr) el('profitUsdRate').value = saved.usd_per_myr;
      el('profitRateMode').textContent = saved.date ? '最近成功汇率 · ' + saved.date : '自动汇率暂不可用';
    }
  }

  function useManualRates() {
    rateMode = 'manual';
    saveRatePreference({ mode: 'manual', cny_per_myr: el('profitExchangeRate').value, usd_per_myr: el('profitUsdRate').value });
    updateRateUi();
    el('profitExchangeRate').focus();
  }

  function categoryByCode(code) {
    return categories.find(function (item) { return item.code === code; });
  }
  function categoryButtons(items, level, selected) {
    return items.map(function (item) {
      const value = item.code || item.label;
      return '<button type="button" class="' + (value === selected ? 'active' : '') + '" data-category-option="' + level + '" data-category-value="' + escapeHtml(value) + '">' + escapeHtml(item.label) + '<span>›</span></button>';
    }).join('');
  }
  function renderCategoryMenu(row) {
    const industry = categoryTree.find(function (item) { return item.label === row.dataset.categoryIndustry; }) || categoryTree[0];
    const group = industry.children.find(function (item) { return item.label === row.dataset.categoryGroup; }) || industry.children[0];
    row.dataset.categoryIndustry = industry.label;
    row.dataset.categoryGroup = group.label;
    const code = row.querySelector('[data-profit-field="category_code"]').value;
    row.querySelector('[data-category-column="0"]').innerHTML = categoryButtons(categoryTree, 0, industry.label);
    row.querySelector('[data-category-column="1"]').innerHTML = categoryButtons(industry.children, 1, group.label);
    row.querySelector('[data-category-column="2"]').innerHTML = categoryButtons(group.children, 2, code);
  }
  function populateCategoryPicker(row, selectedCode) {
    const hidden = row.querySelector('[data-profit-field="category_code"]');
    const matched = categoryByCode(selectedCode);
    const path = matched && matched.path ? matched.path : [categoryTree[0].label, categoryTree[0].children[0].label, categoryTree[0].children[0].children[0].label];
    const industry = categoryTree.find(function (item) { return item.label === path[0]; }) || categoryTree[0];
    const group = industry.children.find(function (item) { return item.label === path[1]; }) || industry.children[0];
    const leaf = group.children.find(function (item) { return item.code === selectedCode; }) || group.children[0];
    hidden.value = leaf.code;
    row.dataset.categoryIndustry = industry.label;
    row.dataset.categoryGroup = group.label;
    row.querySelector('.profit-category-path').textContent = [industry.label, group.label, leaf.label].join(' / ');
    renderCategoryMenu(row);
  }
  function chooseCategory(row, level, value) {
    if (level === 0) {
      row.dataset.categoryIndustry = value;
      row.dataset.categoryGroup = categoryTree.find(function (item) { return item.label === value; }).children[0].label;
      renderCategoryMenu(row);
      return;
    }
    if (level === 1) {
      row.dataset.categoryGroup = value;
      renderCategoryMenu(row);
      return;
    }
    const category = categoryByCode(value);
    row.querySelector('[data-profit-field="category_code"]').value = value;
    row.querySelector('.profit-category-path').textContent = category && category.path ? category.path.join(' / ') : value;
    row.querySelector('.profit-category-popover').hidden = true;
    openCategoryRow = null;
  }

  function addRow(seed) {
    const rowId = 'profit-row-' + (++rowSequence);
    const item = Object.assign({
      sku_name: 'SKU-' + String(rowSequence).padStart(3, '0'),
      category_code: 'bag-womens-womens-tote-bags',
      weight_g: '200', product_cost_cny: '18.90', item_price: '79.90', affiliate_rate: '15.00', ad_cost_type: 'none', ad_cost_value: '', buyer_shipping_fee: '0.00'
    }, seed || {});
    buyerShippingByRow.set(rowId, fixed(item.buyer_shipping_fee));
    const tr = document.createElement('tr');
    tr.dataset.profitRow = rowId;
    tr.innerHTML =
      '<td><input aria-label="SKU 名称" data-profit-field="sku_name" value="' + escapeHtml(item.sku_name) + '" /></td>' +
      '<td class="profit-category-cell"><input type="hidden" data-profit-field="category_code" />' +
        '<button type="button" class="profit-category-trigger" data-category-open="' + rowId + '"><span class="profit-category-path"></span><b>⌄</b></button>' +
        '<div class="profit-category-popover" hidden><div data-category-column="0"></div><div data-category-column="1"></div><div data-category-column="2"></div></div></td>' +
      '<td><div class="profit-unit-input"><input aria-label="包装后重量" data-profit-field="weight_g" type="number" min="1" max="30000" step="1" value="' + escapeHtml(item.weight_g) + '" required /><span>g</span></div></td>' +
      '<td><input aria-label="商品成本" data-profit-field="product_cost_cny" type="number" min="0" step="0.01" value="' + escapeHtml(item.product_cost_cny) + '" /></td>' +
      '<td><input aria-label="售价" data-profit-field="item_price" type="number" min="0" step="0.01" value="' + escapeHtml(item.item_price) + '" required /></td>' +
      '<td><div class="profit-percent-input"><input aria-label="达人佣金率" data-profit-field="affiliate_rate" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(item.affiliate_rate) + '" /><span>%</span></div></td>' +
      '<td class="profit-ad-cell"><div class="profit-ad-input"><select aria-label="实际广告数据类型" data-profit-field="ad_cost_type"><option value="none">不计广告</option><option value="roi">实际 ROI</option><option value="cpa_usd">单件 CPA（USD）</option><option value="ratio">广告费占收入（%）</option></select><input aria-label="实际广告数据" data-profit-field="ad_cost_value" type="number" min="0" step="0.01" value="' + escapeHtml(item.ad_cost_value) + '" placeholder="留空不计入" disabled /></div></td>' +
      '<td><button class="row-action danger" type="button" data-profit-remove="' + rowId + '" aria-label="删除此 SKU">删除</button></td>';
    el('profitSkuRows').appendChild(tr);
    populateCategoryPicker(tr, item.category_code);
  }
  function collectRow(row) {
    const result = {};
    row.querySelectorAll('[data-profit-field]').forEach(function (field) { result[field.dataset.profitField] = field.value; });
    result.buyer_shipping_fee = buyerShippingByRow.get(row.dataset.profitRow) || '0.00';
    if (result.ad_cost_type === 'none' || result.ad_cost_value === '') result.ad_cost_value = null;
    return result;
  }
  function setStatus(message, isError) {
    const target = el('profitFormStatus');
    target.textContent = message;
    target.classList.toggle('error', Boolean(isError));
  }
  function sourceMarkup(row) {
    if (!row.source) return '<span>自动计算</span>';
    const source = String(row.source);
    const detail = row.source_detail ? '<small>' + escapeHtml(row.source_detail) + '</small>' : '';
    const date = row.effective_date ? '<small>' + escapeHtml(row.effective_date) + '</small>' : '';
    if (source.indexOf('http') !== 0) return '<span>' + escapeHtml(source) + '</span>' + detail + date;
    const label = source.indexOf('mysst.customs.gov.my') >= 0 ? '马来西亚海关官方规则 ↗' : 'TikTok Shop 官方规则 ↗';
    return '<a href="' + escapeHtml(source) + '" target="_blank" rel="noopener">' + label + '</a>' + date;
  }
  function rateShareText(row) {
    const hasRate = row.rate !== null && row.rate !== undefined && row.rate !== '';
    const share = number(row.share);
    if (!hasRate) return share === 0 && row.key === 'advertising_cost' ? '—' : '占比 ' + share.toFixed(2) + '%';
    const rate = number(row.rate);
    if (Math.abs(rate - share) < 0.005) return rate.toFixed(2) + '%';
    return '费率 ' + rate.toFixed(2) + '% · 占比 ' + share.toFixed(2) + '%';
  }
  function feeLabel(row) {
    if (row.key !== 'platform_commission' && row.key !== 'buyer_shipping_fee') return '<strong>' + escapeHtml(row.label) + '</strong>';
    return '<button type="button" class="profit-fee-edit" data-profit-fee-edit="' + escapeHtml(row.key) + '"><strong>' + escapeHtml(row.label) + '</strong><span>编辑</span></button>';
  }
  function normalizedGroups(result) {
    if (result.breakdown_groups) return result.breakdown_groups;
    const groups = [];
    (result.breakdown || []).forEach(function (row) {
      let group = groups.find(function (item) { return item.key === row.group; });
      if (!group) {
        group = { key: row.group, label: row.group, kind: row.kind === 'income' ? 'income' : 'cost', amount: '0', share: '0', items: [] };
        groups.push(group);
      }
      group.items.push(row);
      group.amount = String(number(group.amount) + number(row.amount));
    });
    return groups;
  }
  function renderBreakdown(result) {
    const groups = normalizedGroups(result);
    el('profitBreakdownRows').innerHTML = groups.map(function (group) {
      const groupPrefix = group.kind === 'income' || group.kind === 'info' ? '' : '− ';
      const total = '<tr class="profit-group-total" data-profit-group-total="' + escapeHtml(group.key) + '">' +
        '<td><button type="button" class="profit-group-toggle" data-profit-group-toggle="' + escapeHtml(group.key) + '" aria-expanded="true"><span>⌄</span><b>' + escapeHtml(group.label) + '</b></button></td>' +
        '<td><strong>' + escapeHtml(group.label) + '合计</strong></td>' +
        '<td data-profit-basis-column>' + (group.key === '物流' ? '买家运费不计入物流合计' : '组内费用汇总') + '</td>' +
        '<td class="profit-rate-share">占比 ' + fixed(group.share) + '%</td>' +
        '<td class="profit-amount ' + escapeHtml(group.kind) + '">' + groupPrefix + formatMoney(group.amount) + '</td><td><span>分组汇总</span></td></tr>';
      const items = group.items.map(function (row) {
        const prefix = row.kind === 'income' || row.kind === 'info' || row.kind === 'reference' ? '' : '− ';
        return '<tr class="profit-fee-row" data-profit-group-row="' + escapeHtml(group.key) + '"><td></td><td>' + feeLabel(row) + '</td>' +
          '<td data-profit-basis-column>' + escapeHtml(row.base || '—') + '</td>' +
          '<td class="profit-rate-share">' + escapeHtml(rateShareText(row)) + '</td>' +
          '<td class="profit-amount ' + escapeHtml(row.kind) + '">' + prefix + formatMoney(row.amount) + '</td>' +
          '<td class="profit-source">' + sourceMarkup(row) + '</td></tr>';
      }).join('');
      return total + items;
    }).join('');
  }

  function renderResult(result, shouldScroll) {
    const summary = result.amount_summary || {};
    const primaryProfit = result.has_ad_cost ? result.net_profit : result.gross_profit;
    const primaryMargin = result.has_ad_cost ? result.net_margin : result.gross_margin;
    el('profitPrimaryLabel').textContent = result.has_ad_cost ? '净利润' : '广告前毛利';
    el('profitMarginLabel').textContent = result.has_ad_cost ? '净利率' : '毛利率';
    el('profitMarginHint').textContent = (result.has_ad_cost ? '净利润' : '广告前毛利') + ' ÷ 商品售价';
    el('profitNet').textContent = formatMoney(primaryProfit);
    el('profitNetCny').textContent = displayCurrency === 'MYR' ? '≈ ' + formatMoney(primaryProfit, 'CNY') : '≈ ' + formatMoney(primaryProfit, 'MYR');
    el('profitMargin').textContent = fixed(primaryMargin) + '%';
    el('profitCpa').textContent = '$ ' + number(result.break_even_cpa_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el('profitRoas').textContent = result.break_even_roi == null ? '不可盈利' : fixed(result.break_even_roi);
    el('profitSalesRevenue').textContent = formatMoney(summary.sales_revenue == null ? result.revenue : summary.sales_revenue);
    el('profitBuyerShippingRevenue').textContent = formatMoney(summary.buyer_shipping_revenue || 0);
    el('profitRevenue').textContent = formatMoney(summary.settlement_revenue == null ? result.revenue : summary.settlement_revenue);
    el('profitPlatformFees').textContent = formatCost(summary.platform_fees || 0);
    el('profitAffiliateFees').textContent = formatCost(summary.affiliate_commission || 0);
    el('profitLogisticsCost').textContent = formatCost(summary.logistics_cost || 0);
    el('profitPlatformPayout').textContent = formatMoney(summary.estimated_platform_payout == null ? result.gross_profit : summary.estimated_platform_payout);
    el('profitProductCost').textContent = formatCost(summary.product_cost || 0);
    el('profitCostsBeforeAds').textContent = formatMoney(result.costs_before_ads);
    el('profitGross').textContent = formatMoney(result.gross_profit);
    el('profitAdCost').textContent = result.has_ad_cost ? formatMoney(result.advertising_cost) : '未填写';
    el('profitFormulaNet').textContent = result.has_ad_cost ? formatMoney(result.net_profit) : '未计算';
    el('profitFormulaNetMargin').textContent = result.has_ad_cost ? fixed(result.net_margin) + '%' : '未计算';
    el('profitResultVersion').textContent = '规则版本 ' + result.rule_version + ' · 运费 ' + (result.shipping_rate_version || '') + ' · 当前显示 ' + displayCurrency;
    el('profitBreakdownCurrency').textContent = '金额(' + displayCurrency + ')';
    renderBreakdown(result);
    const warnings = el('profitWarnings');
    warnings.innerHTML = (result.warnings || []).map(function (warning) { return '<p>' + escapeHtml(warning) + '</p>'; }).join('');
    warnings.hidden = !(result.warnings || []).length;
    el('profitResultPanel').hidden = false;
    el('profitResultPanel').dataset.lastResult = JSON.stringify(result);
    if (shouldScroll !== false) el('profitResultPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function rerenderLastResult() {
    const saved = el('profitResultPanel').dataset.lastResult;
    if (saved) renderResult(JSON.parse(saved), false);
  }

  function closeFeeModal() {
    const modal = el('profitFeeModal');
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }
  function openCommissionEditor() {
    el('profitFeeModalTitle').textContent = '编辑类目佣金';
    el('profitFeeModalDescription').textContent = '留空时使用“官方类目佣金 + 当前调试百分点”；填写后，本次试算全部 SKU 优先使用你输入的最终佣金率。';
    el('profitFeeModalBody').innerHTML = '<label class="profit-modal-field">最终类目佣金率（%）<input id="profitManualCommissionInput" type="number" min="0" max="100" step="0.01" placeholder="留空自动恢复默认" value="' + escapeHtml(manualCommissionRate == null ? '' : manualCommissionRate) + '" /></label>';
    const modal = el('profitFeeModal');
    modal.dataset.mode = 'commission';
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    el('profitManualCommissionInput').focus();
  }
  function openBuyerShippingEditor() {
    const rows = Array.from(document.querySelectorAll('[data-profit-row]'));
    el('profitFeeModalTitle').textContent = '编辑买家运费';
    el('profitFeeModalDescription').textContent = '默认 RM0.00。买家运费不增加收入、不抵扣商家运费，仅进入支付交易手续费基数；刷新页面后恢复为 0。';
    el('profitFeeModalBody').innerHTML = rows.map(function (row) {
      const sku = row.querySelector('[data-profit-field="sku_name"]').value || 'SKU';
      return '<label class="profit-modal-field">' + escapeHtml(sku) + '（MYR）<input data-buyer-shipping-row="' + escapeHtml(row.dataset.profitRow) + '" type="number" min="0" step="0.01" value="' + escapeHtml(buyerShippingByRow.get(row.dataset.profitRow) || '0.00') + '" /></label>';
    }).join('');
    const modal = el('profitFeeModal');
    modal.dataset.mode = 'buyer_shipping';
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    const input = modal.querySelector('input');
    if (input) input.focus();
  }
  async function saveFeeModal() {
    const modal = el('profitFeeModal');
    if (modal.dataset.mode === 'commission') {
      const raw = el('profitManualCommissionInput').value.trim();
      manualCommissionRate = raw === '' ? null : fixed(raw);
    } else {
      modal.querySelectorAll('[data-buyer-shipping-row]').forEach(function (input) {
        buyerShippingByRow.set(input.dataset.buyerShippingRow, fixed(Math.max(0, number(input.value))));
      });
    }
    closeFeeModal();
    if (!el('profitResultPanel').hidden) await calculate(false);
  }

  async function loadConfig() {
    try {
      const config = await request('/profit-calculator/config/');
      categories = config.categories || [];
      categoryTree = config.category_tree || fallbackTree;
      const adjustment = savedCommissionAdjustment(config.default_commission_adjustment || '1.00');
      el('profitCommissionAdjustment').value = adjustment;
      document.querySelectorAll('[data-profit-row]').forEach(function (row) {
        populateCategoryPicker(row, row.querySelector('[data-profit-field="category_code"]').value);
      });
      const groupCount = categoryTree.reduce(function (total, item) { return total + item.children.length; }, 0);
      const leafCount = categoryTree.reduce(function (total, item) { return total + item.children.reduce(function (subtotal, group) { return subtotal + group.children.length; }, 0); }, 0);
      setStatus('已加载箱包、美妆个护完整三级类目（' + groupCount + ' 个二级、' + leafCount + ' 个三级）及马来西亚跨境运费配置。');
    } catch (_) {
      setStatus('费率配置暂时无法读取，请确认已登录团队服务器后重试。', true);
    }
  }
  async function calculate(shouldScroll) {
    const rows = Array.from(document.querySelectorAll('[data-profit-row]'));
    if (!rows.length) return setStatus('请至少添加一个 SKU。', true);
    const button = el('profitCalculatorForm').querySelector('[type="submit"]');
    button.disabled = true;
    setStatus('正在按每个 SKU 匹配类目佣金、10g 运费档和税费…');
    try {
      const result = await request('/profit-calculator/calculate/', {
        method: 'POST',
        body: {
          country: el('profitCountry').value,
          seller_type: el('profitSellerType').value,
          shop_identity: el('profitShopIdentity').value,
          bxp: el('profitBxp').checked,
          delivered: true,
          commission_adjustment: el('profitCommissionAdjustment').value || '0',
          manual_commission_rate: manualCommissionRate,
          cny_per_myr: el('profitExchangeRate').value,
          usd_per_myr: el('profitUsdRate').value,
          items: rows.map(collectRow)
        }
      });
      renderResult(result, shouldScroll);
      setStatus('计算完成：跨境商家运费按各 SKU 包装后重量向上取整至 10g；买家运费默认 0。');
    } catch (error) {
      const detail = error && error.data ? JSON.stringify(error.data) : (error.message || '计算失败');
      setStatus('计算失败：' + detail, true);
    } finally {
      button.disabled = false;
    }
  }

  function init() {
    const form = el('profitCalculatorForm');
    if (!form) return;
    addRow();
    form.addEventListener('submit', function (event) { event.preventDefault(); calculate(true); });
    el('profitAddSku').addEventListener('click', function () { addRow({ product_cost_cny: '0.00', item_price: '0.00', affiliate_rate: '0.00' }); });
    el('profitBasisToggle').addEventListener('click', function () {
      const table = el('profitBreakdownTable');
      const expanded = !table.classList.contains('show-basis');
      table.classList.toggle('show-basis', expanded);
      this.setAttribute('aria-expanded', String(expanded));
      this.textContent = expanded ? '收起计费基准' : '展开计费基准';
    });
    el('profitFeeModalSave').addEventListener('click', saveFeeModal);
    el('profitFeeModalCancel').addEventListener('click', closeFeeModal);
    el('profitFeeModalClose').addEventListener('click', closeFeeModal);
    el('profitFeeModal').addEventListener('click', function (event) { if (event.target === this) closeFeeModal(); });
    el('profitRateAuto').addEventListener('click', function () { rateMode = 'auto'; saveRatePreference({ mode: 'auto' }); loadExchangeRates(true); });
    el('profitRateManual').addEventListener('click', useManualRates);
    el('profitRateRefresh').addEventListener('click', function () { loadExchangeRates(true); });

    document.addEventListener('input', function (event) {
      if (event.target.id === 'profitCommissionAdjustment') persistCommissionAdjustment(event.target.value || '0');
    });
    document.addEventListener('change', function (event) {
      if (event.target.matches('[data-profit-field="ad_cost_type"]')) {
        const input = event.target.closest('[data-profit-row]').querySelector('[data-profit-field="ad_cost_value"]');
        const type = event.target.value;
        input.disabled = type === 'none';
        input.placeholder = type === 'roi' ? '例如 4.00' : (type === 'cpa_usd' ? '例如 5.00 USD' : (type === 'ratio' ? '例如 20.00%' : '留空不计入'));
        if (type === 'none') input.value = '';
      }
      if (event.target.matches('#profitExchangeRate, #profitUsdRate')) {
        if (rateMode === 'manual') saveRatePreference({ mode: 'manual', cny_per_myr: el('profitExchangeRate').value, usd_per_myr: el('profitUsdRate').value });
        rerenderLastResult();
      }
    });
    document.addEventListener('click', function (event) {
      const currency = event.target.closest('[data-profit-currency]');
      if (currency) {
        displayCurrency = currency.dataset.profitCurrency;
        document.querySelectorAll('[data-profit-currency]').forEach(function (button) { button.classList.toggle('active', button === currency); });
        rerenderLastResult();
        return;
      }
      const feeEdit = event.target.closest('[data-profit-fee-edit]');
      if (feeEdit) return feeEdit.dataset.profitFeeEdit === 'platform_commission' ? openCommissionEditor() : openBuyerShippingEditor();
      const groupToggle = event.target.closest('[data-profit-group-toggle]');
      if (groupToggle) {
        const group = groupToggle.dataset.profitGroupToggle;
        const expanded = groupToggle.getAttribute('aria-expanded') === 'true';
        groupToggle.setAttribute('aria-expanded', String(!expanded));
        groupToggle.querySelector('span').textContent = expanded ? '›' : '⌄';
        document.querySelectorAll('[data-profit-group-row="' + CSS.escape(group) + '"]').forEach(function (row) { row.hidden = expanded; });
        return;
      }
      const categoryOption = event.target.closest('[data-category-option]');
      if (categoryOption) return chooseCategory(categoryOption.closest('[data-profit-row]'), Number(categoryOption.dataset.categoryOption), categoryOption.dataset.categoryValue);
      const categoryOpen = event.target.closest('[data-category-open]');
      if (categoryOpen) {
        const row = categoryOpen.closest('[data-profit-row]');
        if (openCategoryRow && openCategoryRow !== row) openCategoryRow.querySelector('.profit-category-popover').hidden = true;
        const popover = row.querySelector('.profit-category-popover');
        popover.hidden = !popover.hidden;
        if (!popover.hidden) {
          const rect = categoryOpen.getBoundingClientRect();
          const width = Math.min(680, window.innerWidth - 24);
          const height = Math.min(420, window.innerHeight - 24);
          popover.style.width = width + 'px'; popover.style.height = height + 'px';
          popover.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + 'px';
          popover.style.top = (rect.bottom + 6 + height <= window.innerHeight - 12 ? rect.bottom + 6 : Math.max(12, rect.top - height - 6)) + 'px';
        }
        openCategoryRow = popover.hidden ? null : row;
        return;
      }
      if (openCategoryRow && !event.target.closest('.profit-category-cell')) {
        openCategoryRow.querySelector('.profit-category-popover').hidden = true;
        openCategoryRow = null;
      }
      const remove = event.target.closest('[data-profit-remove]');
      if (remove) {
        const rows = document.querySelectorAll('[data-profit-row]');
        if (rows.length === 1) return setStatus('至少保留一个 SKU。', true);
        const row = remove.closest('[data-profit-row]');
        buyerShippingByRow.delete(row.dataset.profitRow);
        row.remove();
      }
    });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape' && !el('profitFeeModal').hidden) closeFeeModal(); });
    loadConfig();
    loadExchangeRates(false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(window);
