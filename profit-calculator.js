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
  let categoryTree = fallbackTree;
  let categories = [];
  let rowSequence = 0;
  let displayCurrency = 'MYR';
  let openCategoryRow = null;
  let rateMode = 'auto';
  let buyerShippingRegion = 'west_malaysia';
  let loadedStrategies = [];
  let strategyModalMode = 'create';
  let workingConfigSaveTimer = null;
  let workingConfigHydrating = true;
  let workingConfigReady = false;
  let workingConfigRevision = null;
  let workingConfigRetryMode = 'load';
  let workingConfigSaveFailed = false;
  let profitPlanSaveContext = null;
  const manualCommissionByRow = new Map();

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
  function nullablePercent(value) {
    return value == null || String(value).trim() === '' ? null : fixed(value);
  }
  function revisionFrom(payload) {
    if (!payload) return null;
    const value = payload.current_revision == null
      ? (payload.server_revision == null ? payload.revision : payload.server_revision)
      : payload.current_revision;
    return value == null || value === '' ? null : Number(value);
  }
  function buildWorkingConfigPayload(config, selectedRateMode, cnyRate, usdRate, revision) {
    return {
      config: config,
      rate_mode: selectedRateMode,
      manual_cny_per_myr: selectedRateMode === 'manual' ? cnyRate : null,
      manual_usd_per_myr: selectedRateMode === 'manual' ? usdRate : null,
      revision: revision
    };
  }
  function workingConfigFailure(error) {
    const status = Number(error && (error.status || (error.data && error.data.status)));
    return {
      retry_mode: status === 409 ? 'conflict' : 'save',
      current_revision: status === 409 ? revisionFrom(error && error.data) : null
    };
  }
  function strategyActivationPayload(revision) {
    return { working_revision: revision };
  }
  function formatSingleMoney(value, currency) {
    const target = currency || displayCurrency;
    const amount = target === 'CNY' ? number(value) * number(el('profitExchangeRate').value) : number(value);
    const prefix = target === 'CNY' ? '¥ ' : 'RM ';
    return prefix + amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function formatCost(value) { return '− ' + formatSingleMoney(value); }
  function formatDualMoney(value, primaryCurrency) {
    const primary = primaryCurrency || displayCurrency;
    const secondary = primary === 'MYR' ? 'CNY' : 'MYR';
    return formatSingleMoney(value, primary) + ' ／ ' + formatSingleMoney(value, secondary);
  }

  function saveRatePreference(payload) {
    try { localStorage.setItem(RATE_STORAGE_KEY, JSON.stringify(payload)); } catch (_) { /* optional */ }
  }
  function ratePreference() {
    try { return JSON.parse(localStorage.getItem(RATE_STORAGE_KEY) || '{}'); } catch (_) { return {}; }
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
      error.status = response.status;
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

  async function loadExchangeRates(force, preserveMode) {
    const saved = preserveMode ? {} : ratePreference();
    if (!preserveMode) rateMode = saved.mode === 'manual' ? 'manual' : 'auto';
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
    scheduleWorkingConfigSave();
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
      weight_g: '200', product_cost_cny: '18.90', item_price: '79.90', affiliate_rate: '15.00', ad_cost_type: 'none', ad_cost_value: '', advertising_rebate_percent_override: null, buyer_shipping_fee: '0.00'
    }, seed || {});
    manualCommissionByRow.set(rowId, item.manual_commission_rate == null ? '' : fixed(item.manual_commission_rate));
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
      '<td class="profit-ad-cell"><div class="profit-ad-input" style="height:auto;min-height:96px;grid-template-rows:42px 42px;overflow:visible"><select aria-label="实际广告数据类型" data-profit-field="ad_cost_type"><option value="none">不计广告</option><option value="roi">实际 ROI</option><option value="cpa_usd">单件 CPA（USD）</option><option value="ratio">广告费占收入（%）</option></select><input aria-label="实际广告数据" data-profit-field="ad_cost_value" type="number" min="0" step="0.01" value="' + escapeHtml(item.ad_cost_value) + '" placeholder="留空不计入" disabled /><label style="grid-column:1 / -1;display:grid;grid-template-columns:auto minmax(120px,1fr);align-items:center;gap:8px;padding:0 8px;font-size:11px;color:#52677d">返点覆盖（%）<input style="margin:0!important;min-height:36px" aria-label="SKU 广告返点覆盖" data-profit-field="advertising_rebate_percent_override" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(item.advertising_rebate_percent_override == null ? '' : item.advertising_rebate_percent_override) + '" placeholder="留空继承全局" /></label></div></td>' +
      '<td><button class="row-action danger" type="button" data-profit-remove="' + rowId + '" aria-label="删除此 SKU">删除</button></td>';
    el('profitSkuRows').appendChild(tr);
    populateCategoryPicker(tr, item.category_code);
  }
  function collectRow(row) {
    const result = {};
    row.querySelectorAll('[data-profit-field]').forEach(function (field) { result[field.dataset.profitField] = field.value; });
    result.manual_commission_rate = manualCommissionByRow.get(row.dataset.profitRow) || null;
    if (result.ad_cost_type === 'none' || result.ad_cost_value === '') result.ad_cost_value = null;
    result.advertising_rebate_percent_override = nullablePercent(result.advertising_rebate_percent_override);
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
    const detail = row.source_detail ? '<small> · ' + escapeHtml(row.source_detail) + '</small>' : '';
    const date = row.effective_date ? '<small> · ' + escapeHtml(row.effective_date) + '</small>' : '';
    if (source.indexOf('http') !== 0) return '<span>' + escapeHtml(source) + '</span>' + detail + date;
    const label = source.indexOf('mysst.customs.gov.my') >= 0 ? '马来西亚海关官方规则 ↗' : 'TikTok Shop 官方规则 ↗';
    return '<a href="' + escapeHtml(source) + '" target="_blank" rel="noopener">' + label + '</a>' + date;
  }
  function rateShareText(row) {
    const hasRate = row.rate !== null && row.rate !== undefined && row.rate !== '';
    const share = number(row.share);
    if (!hasRate) {
      if (share === 0 && row.key === 'advertising_cost') return '—';
      return (row.kind === 'reference' ? '参考 · ' : '') + '占比 ' + share.toFixed(2) + '%';
    }
    const rate = number(row.rate);
    if (Math.abs(rate - share) < 0.005) return rate.toFixed(2) + '%';
    return '费率 ' + rate.toFixed(2) + '% · 占比 ' + share.toFixed(2) + '%';
  }
  function feeLabel(row) {
    if (row.key !== 'platform_commission') return '<strong>' + escapeHtml(row.label) + '</strong>';
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
      if (group.items.length === 1) {
        const row = group.items[0];
        const label = group.key === '收入' && row.label === '商品售价合计' ? '商品售价' : feeLabel(row);
        const prefix = row.kind === 'income' || row.kind === 'info' || row.kind === 'reference' ? '' : '− ';
        return '<tr class="profit-fee-row profit-single-group" data-profit-group-row="' + escapeHtml(group.key) + '"><td><b>' + escapeHtml(group.label) + '</b></td><td>' + label + '</td>' +
          '<td data-profit-basis-column>' + escapeHtml(row.base || '—') + '</td>' +
          '<td class="profit-rate-share">' + escapeHtml(rateShareText(row)) + '</td>' +
          '<td class="profit-amount ' + escapeHtml(row.kind) + '">' + prefix + formatSingleMoney(row.amount) + '</td>' +
          '<td class="profit-source">' + sourceMarkup(row) + '</td></tr>';
      }
      const groupPrefix = group.kind === 'income' || group.kind === 'info' ? '' : '− ';
      const total = '<tr class="profit-group-total" data-profit-group-total="' + escapeHtml(group.key) + '" data-profit-group-toggle="' + escapeHtml(group.key) + '" tabindex="0" role="button" aria-expanded="false">' +
        '<td><button type="button" class="profit-group-toggle" data-profit-group-toggle="' + escapeHtml(group.key) + '" aria-expanded="false"><span class="profit-group-chevron" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m8 4 8 8-8 8"></path></svg></span><b>' + escapeHtml(group.label) + '</b></button></td>' +
        '<td><strong>' + escapeHtml(group.label) + '合计</strong></td>' +
        '<td data-profit-basis-column>' + (group.key === '物流' ? '买家运费不计入物流合计' : '组内费用汇总') + '</td>' +
        '<td class="profit-rate-share">占比 ' + fixed(group.share) + '%</td>' +
        '<td class="profit-amount ' + escapeHtml(group.kind) + '">' + groupPrefix + formatSingleMoney(group.amount) + '</td><td><span>分组汇总</span></td></tr>';
      const items = group.items.map(function (row) {
        const prefix = row.kind === 'income' || row.kind === 'info' || row.kind === 'reference' ? '' : '− ';
        return '<tr class="profit-fee-row" data-profit-group-row="' + escapeHtml(group.key) + '" hidden><td></td><td>' + feeLabel(row) + '</td>' +
          '<td data-profit-basis-column>' + escapeHtml(row.base || '—') + '</td>' +
          '<td class="profit-rate-share">' + escapeHtml(rateShareText(row)) + '</td>' +
          '<td class="profit-amount ' + escapeHtml(row.kind) + '">' + prefix + formatSingleMoney(row.amount) + '</td>' +
          '<td class="profit-source">' + sourceMarkup(row) + '</td></tr>';
      }).join('');
      return total + items;
    }).join('');
  }
  function setGroupExpanded(group, expanded) {
    const total = document.querySelector('[data-profit-group-total="' + CSS.escape(group) + '"]');
    if (!total) return;
    total.setAttribute('aria-expanded', String(expanded));
    const button = total.querySelector('[data-profit-group-toggle]');
    if (button) button.setAttribute('aria-expanded', String(expanded));
    document.querySelectorAll('[data-profit-group-row="' + CSS.escape(group) + '"]').forEach(function (row) { row.hidden = !expanded; });
  }

  function renderResult(result, shouldScroll) {
    const summary = result.amount_summary || {};
    const primaryProfit = result.has_ad_cost ? result.net_profit : result.gross_profit;
    const primaryMargin = result.has_ad_cost ? result.net_margin : result.gross_margin;
    el('profitPrimaryLabel').textContent = result.has_ad_cost ? '净利润' : '广告前毛利';
    el('profitMarginLabel').textContent = result.has_ad_cost ? '净利率' : '毛利率';
    el('profitMarginHint').textContent = (result.has_ad_cost ? '净利润' : '广告前毛利') + ' ÷ 商品售价';
    el('profitNet').textContent = formatSingleMoney(primaryProfit);
    el('profitNetCny').textContent = displayCurrency === 'MYR' ? '≈ ' + formatSingleMoney(primaryProfit, 'CNY') : '≈ ' + formatSingleMoney(primaryProfit, 'MYR');
    el('profitMargin').textContent = fixed(primaryMargin) + '%';
    el('profitCpa').textContent = '$ ' + number(result.break_even_cpa_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el('profitRoas').textContent = result.break_even_roi == null ? '不可盈利' : fixed(result.break_even_roi);
    el('profitSalesRevenue').textContent = formatSingleMoney(summary.sales_revenue == null ? result.revenue : summary.sales_revenue);
    el('profitBuyerShippingRevenue').textContent = formatSingleMoney(summary.buyer_shipping_revenue || 0);
    el('profitRevenue').textContent = formatSingleMoney(summary.settlement_revenue == null ? result.revenue : summary.settlement_revenue);
    el('profitPlatformFees').textContent = formatCost(summary.platform_fees || 0);
    el('profitAffiliateFees').textContent = formatCost(summary.affiliate_commission || 0);
    el('profitLogisticsCost').textContent = formatCost(summary.logistics_cost || 0);
    el('profitPlatformPayout').textContent = formatSingleMoney(summary.estimated_platform_payout == null ? result.gross_profit : summary.estimated_platform_payout);
    el('profitProductCost').textContent = formatCost(summary.product_cost || 0);
    el('profitCostsBeforeAds').textContent = formatSingleMoney(result.costs_before_ads);
    el('profitGross').textContent = formatSingleMoney(result.gross_profit);
    el('profitAdCost').textContent = result.has_ad_cost
      ? formatSingleMoney(result.advertising_cost) + '（返点前 ' + formatSingleMoney(result.advertising_cost_before_rebate) + '，返点 ' + formatSingleMoney(result.advertising_rebate_amount) + '）'
      : '未填写';
    el('profitFormulaNet').textContent = result.has_ad_cost ? formatSingleMoney(result.net_profit) : '未计算';
    el('profitFormulaNetMargin').textContent = result.has_ad_cost ? fixed(result.net_margin) + '%' : '未计算';
    function settlement(id) {
      return el(id) || document.querySelector('.profit-settlement-summary #' + id);
    }
    settlement('profitTotalRevenue').textContent = formatDualMoney(summary.total_revenue == null ? result.revenue : summary.total_revenue);
    settlement('profitTotalFees').textContent = formatDualMoney(summary.total_fees == null ? result.total_fees : summary.total_fees);
    settlement('profitSettlementAmount').textContent = formatDualMoney(summary.settlement_amount == null ? result.settlement_amount : summary.settlement_amount);
    settlement('profitSettlementCostsBeforeAds').textContent = formatDualMoney(summary.costs_before_ads == null ? result.costs_before_ads : summary.costs_before_ads);
    settlement('profitSettlementGross').textContent = formatDualMoney(summary.gross_profit == null ? result.gross_profit : summary.gross_profit);
    settlement('profitGrossMargin').textContent = fixed(summary.gross_margin == null ? result.gross_margin : summary.gross_margin) + '%';
    const beforeRebate = settlement('profitAdCostBeforeRebate');
    if (beforeRebate) beforeRebate.textContent = result.has_ad_cost ? formatDualMoney(result.advertising_cost_before_rebate) : '未填写广告';
    const rebateAmount = settlement('profitAdRebateAmount');
    if (rebateAmount) rebateAmount.textContent = result.has_ad_cost ? formatDualMoney(result.advertising_rebate_amount) : '未填写广告';
    const actualAdCost = settlement('profitActualAdCost');
    if (actualAdCost) actualAdCost.textContent = result.has_ad_cost ? formatDualMoney(result.advertising_cost) : '未填写广告';
    const trueRoi = settlement('profitTrueRoi');
    if (trueRoi) trueRoi.textContent = !result.has_ad_cost ? '暂无数据' : (result.true_roi_status === 'infinite' ? '∞ / 无需付费' : fixed(result.true_roi));
    const trueCpa = settlement('profitTrueCpa');
    if (trueCpa) trueCpa.textContent = !result.has_ad_cost ? '暂无数据' : (result.true_cpa_usd == null ? '不适用' : '$ ' + fixed(result.true_cpa_usd));
    settlement('profitCostsAfterAds').textContent = result.has_ad_cost ? formatDualMoney(summary.costs_after_ads) : '未填写广告';
    settlement('profitSettlementNet').textContent = result.has_ad_cost ? formatDualMoney(summary.net_profit) : '未填写广告';
    settlement('profitSettlementNetMargin').textContent = result.has_ad_cost ? fixed(summary.net_margin) + '%' : '未填写广告';
    el('profitResultVersion').textContent = '规则版本 ' + result.rule_version + ' · 商家运费 ' + (result.shipping_rate_version || '') + ' · 当前显示 ' + displayCurrency;
    el('profitBreakdownCurrency').textContent = '金额(' + displayCurrency + ')';
    renderBreakdown(result);
    const warnings = el('profitWarnings');
    // Calculation guidance lives on the rules page; the result card must not
    // add a second yellow notice area below the figures.
    warnings.innerHTML = '';
    warnings.hidden = true;
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
    const rows = Array.from(document.querySelectorAll('[data-profit-row]'));
    el('profitFeeModalTitle').textContent = '编辑类目佣金';
    el('profitFeeModalDescription').textContent = '留空时使用“官方类目佣金 + 当前调试百分点”；填写后，仅对应 SKU 使用你输入的最终佣金率。';
    el('profitFeeModalBody').innerHTML = rows.map(function (row) {
      const sku = row.querySelector('[data-profit-field="sku_name"]').value || 'SKU';
      return '<label class="profit-modal-field">' + escapeHtml(sku) + ' · 最终类目佣金率（%）<input data-manual-commission-row="' + escapeHtml(row.dataset.profitRow) + '" type="number" min="0" max="100" step="0.01" placeholder="留空自动恢复默认" value="' + escapeHtml(manualCommissionByRow.get(row.dataset.profitRow) || '') + '" /></label>';
    }).join('');
    const modal = el('profitFeeModal');
    modal.dataset.mode = 'commission';
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    const input = modal.querySelector('input');
    if (input) input.focus();
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
      modal.querySelectorAll('[data-manual-commission-row]').forEach(function (input) {
        manualCommissionByRow.set(input.dataset.manualCommissionRow, input.value.trim() === '' ? '' : fixed(input.value));
      });
    }
    closeFeeModal();
    if (!el('profitResultPanel').hidden) await calculate(false);
  }

  let loadedStrategyId = '';
  function globalRebateValue() {
    const field = el('profitAdvertisingRebatePercent');
    return field && field.value !== '' ? fixed(field.value) : '0.00';
  }
  function strategyConfig() {
    return {
      country: el('profitCountry').value, seller_type: el('profitSellerType').value,
      shop_identity: el('profitShopIdentity').value, bxp: el('profitBxp').checked,
      commission_adjustment: el('profitCommissionAdjustment').value || '0',
      buyer_pays_shipping: el('profitBuyerPaysShipping').checked,
      buyer_shipping_region: el('profitBuyerPaysShipping').checked ? buyerShippingRegion : 'west_malaysia',
      transaction_fee_adjustment: el('profitTransactionFeeAdjustment').value || '0',
      advertising_rebate_percent: globalRebateValue(),
      display_currency: displayCurrency
    };
  }
  function systemStrategyConfig() {
    return {
      country: 'MY', seller_type: 'cross_border', shop_identity: 'marketplace', bxp: false,
      commission_adjustment: '1.00', buyer_pays_shipping: false,
      buyer_shipping_region: 'west_malaysia', transaction_fee_adjustment: '0.00',
      advertising_rebate_percent: '0.00', display_currency: 'MYR'
    };
  }
  function applyStrategyConfig(config) {
    ['country', 'seller_type', 'shop_identity', 'commission_adjustment', 'transaction_fee_adjustment'].forEach(function (key) {
      const field = el('profit' + key.split('_').map(function (part) { return part.charAt(0).toUpperCase() + part.slice(1); }).join(''));
      if (field && config[key] != null) field.value = config[key];
    });
    el('profitBxp').checked = Boolean(config.bxp);
    el('profitBuyerPaysShipping').checked = Boolean(config.buyer_pays_shipping);
    if (el('profitAdvertisingRebatePercent')) {
      el('profitAdvertisingRebatePercent').value = config.advertising_rebate_percent == null ? '0.00' : fixed(config.advertising_rebate_percent);
    }
    buyerShippingRegion = config.buyer_shipping_region || 'west_malaysia';
    displayCurrency = config.display_currency || 'MYR';
    document.querySelectorAll('[data-profit-currency]').forEach(function (button) { button.classList.toggle('active', button.dataset.profitCurrency === displayCurrency); });
    updateBuyerShippingUi();
  }
  function workingConfigPayload() {
    return buildWorkingConfigPayload(
      strategyConfig(), rateMode, el('profitExchangeRate').value,
      el('profitUsdRate').value, workingConfigRevision
    );
  }
  function setWorkingConfigStatus(message, failed, retryMode) {
    const target = el('profitWorkingConfigStatus');
    if (!target) return;
    target.textContent = message;
    target.classList.toggle('error', Boolean(failed));
    target.dataset.retry = failed ? 'true' : 'false';
    workingConfigSaveFailed = Boolean(failed);
    if (retryMode) workingConfigRetryMode = retryMode;
  }
  async function saveWorkingConfig() {
    if (workingConfigHydrating || !workingConfigReady) return;
    setWorkingConfigStatus('当前配置保存中…');
    try {
      const saved = await request('/profit-calculator/working-config/', { method: 'PUT', body: workingConfigPayload() });
      workingConfigRevision = revisionFrom(saved);
      const editor = saved.updated_by_name ? '，由 ' + saved.updated_by_name + ' 更新' : '';
      setWorkingConfigStatus('当前配置已保存' + editor);
    } catch (error) {
      const failure = workingConfigFailure(error);
      if (failure.retry_mode === 'conflict') {
        if (failure.current_revision != null) workingConfigRevision = failure.current_revision;
        setWorkingConfigStatus('配置版本冲突，已保留本页输入；点击重试后以新版本保存', true, 'conflict');
      } else {
        setWorkingConfigStatus('保存失败，已保留本页输入；点击重试', true, 'save');
      }
    }
  }
  function scheduleWorkingConfigSave() {
    if (workingConfigHydrating || !workingConfigReady) return;
    if (workingConfigSaveTimer) root.clearTimeout(workingConfigSaveTimer);
    setWorkingConfigStatus('当前配置待保存…');
    workingConfigSaveTimer = root.setTimeout(function () { saveWorkingConfig(); }, 650);
  }
  async function loadWorkingConfig() {
    workingConfigHydrating = true;
    try {
      const saved = await request('/profit-calculator/working-config/');
      workingConfigRevision = revisionFrom(saved);
      applyStrategyConfig(saved.config || {});
      rateMode = saved.rate_mode === 'manual' ? 'manual' : 'auto';
      if (rateMode === 'manual') {
        el('profitExchangeRate').value = saved.manual_cny_per_myr || '';
        el('profitUsdRate').value = saved.manual_usd_per_myr || '';
        updateRateUi(saved);
      } else {
        await loadExchangeRates(false, true);
      }
      workingConfigReady = true;
      setWorkingConfigStatus('已恢复组织共享的当前配置。');
      return saved;
    } catch (error) {
      workingConfigReady = false;
      setWorkingConfigStatus('当前配置加载失败，点击重试', true, 'load');
      throw error;
    } finally {
      workingConfigHydrating = false;
    }
  }
  async function retryWorkingConfig() {
    if (workingConfigRetryMode === 'load') return loadWorkingConfig();
    if (workingConfigRetryMode === 'conflict' && workingConfigRevision == null) {
      const current = await request('/profit-calculator/working-config/');
      workingConfigRevision = revisionFrom(current);
    }
    return saveWorkingConfig();
  }
  function applyStrategy(strategy) {
    applyStrategyConfig(strategy.config || {});
    loadedStrategyId = strategy.id;
    renderStrategyBar();
  }
  function applySystemStrategy() {
    loadedStrategyId = '';
    applyStrategyConfig(systemStrategyConfig());
    renderStrategyBar();
  }
  function renderStrategyBar() {
    const hasCurrent = Boolean(loadedStrategyId);
    el('profitStrategyList').innerHTML = loadedStrategies.map(function (item) {
      return '<button type="button" class="profit-strategy-chip' + (item.id === loadedStrategyId ? ' active' : '') + '" data-profit-strategy-id="' + escapeHtml(item.id) + '" aria-pressed="' + String(item.id === loadedStrategyId) + '">' + escapeHtml(item.name) + '</button>';
    }).join('');
    el('profitStrategySaveCurrent').disabled = !hasCurrent;
    el('profitStrategyDelete').disabled = !hasCurrent;
  }
  async function loadStrategies() {
    const payload = await request('/profit-calculator/strategies/');
    loadedStrategies = Array.isArray(payload) ? payload : (payload.results || []);
    const initial = loadedStrategies.find(function (item) { return item.is_default; });
    if (initial) applyStrategy(initial); else applySystemStrategy();
  }
  function openStrategyModal(mode) {
    strategyModalMode = mode;
    const overwrite = mode === 'overwrite';
    const current = loadedStrategies.find(function (item) { return item.id === loadedStrategyId; });
    el('profitStrategyModalTitle').textContent = overwrite ? '覆盖当前策略' : (mode === 'save_as' ? '另存为新策略' : '新建计算策略');
    el('profitStrategyModalDescription').textContent = overwrite
      ? '将使用当前页面配置覆盖此策略，并立即设为默认策略。'
      : '其余配置将读取当前页面内容；SKU、广告和本次计算结果不会保存。';
    el('profitStrategyModalName').value = overwrite && current ? current.name : '';
    el('profitStrategyModalName').readOnly = overwrite;
    const inactiveBuyerShipping = !el('profitBuyerPaysShipping').checked;
    const region = inactiveBuyerShipping ? 'west_malaysia' : buyerShippingRegion;
    el('profitStrategyModalRegion').value = region;
    el('profitStrategyModalRegion').disabled = inactiveBuyerShipping;
    el('profitStrategyModalRegionHint').hidden = !inactiveBuyerShipping;
    el('profitStrategyModal').hidden = false;
    el('profitStrategyModal').setAttribute('aria-hidden', 'false');
    el('profitStrategyModalName').focus();
  }
  function closeStrategyModal(id) {
    const modal = el(id);
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }
  function openSaveChoice() {
    el('profitStrategySaveChoiceModal').hidden = false;
    el('profitStrategySaveChoiceModal').setAttribute('aria-hidden', 'false');
  }
  function openDeleteStrategy() {
    const current = loadedStrategies.find(function (item) { return item.id === loadedStrategyId; });
    if (!current) return;
    el('profitStrategyDeleteDescription').textContent = '确定删除策略“' + current.name + '”吗？删除后无法恢复。';
    el('profitStrategyDeleteModal').hidden = false;
    el('profitStrategyDeleteModal').setAttribute('aria-hidden', 'false');
  }
  async function saveStrategyFromModal() {
    const overwrite = strategyModalMode === 'overwrite';
    const name = el('profitStrategyModalName').value.trim();
    if (!name) return setStatus('请填写策略名称。', true);
    buyerShippingRegion = el('profitBuyerPaysShipping').checked ? el('profitStrategyModalRegion').value : 'west_malaysia';
    const path = overwrite ? '/profit-calculator/strategies/' + loadedStrategyId + '/' : '/profit-calculator/strategies/';
    const strategy = await request(path, { method: overwrite ? 'PATCH' : 'POST', body: { name: name, config: strategyConfig() } });
    loadedStrategyId = strategy.id;
    await loadStrategies();
    applyStrategy(strategy);
    scheduleWorkingConfigSave();
    closeStrategyModal('profitStrategyModal');
    setStatus('策略已保存并设为默认策略。');
  }
  async function activateStrategy(id) {
    if (!workingConfigReady || workingConfigRevision == null) {
      throw new Error('组织共享当前配置尚未加载，不能安全激活策略。请先点击当前配置状态重试。');
    }
    let strategy;
    try {
      strategy = await request('/profit-calculator/strategies/' + id + '/activate/', {
        method: 'POST', body: strategyActivationPayload(workingConfigRevision)
      });
    } catch (error) {
      const failure = workingConfigFailure(error);
      if (failure.retry_mode === 'conflict') {
        if (failure.current_revision != null) workingConfigRevision = failure.current_revision;
        setWorkingConfigStatus('策略激活冲突，未覆盖其他成员配置；本页输入已保留', true, 'conflict');
      }
      throw error;
    }
    const activatedRevision = strategy.working_revision == null
      ? revisionFrom(strategy.working_config)
      : Number(strategy.working_revision);
    if (activatedRevision == null) {
      const current = await request('/profit-calculator/working-config/');
      workingConfigRevision = revisionFrom(current);
    } else {
      workingConfigRevision = activatedRevision;
    }
    loadedStrategyId = strategy.id;
    await loadStrategies();
    applyStrategy(strategy);
    setWorkingConfigStatus('策略已激活，并同步为组织共享当前配置。');
    setStatus('已加载并设为默认策略：' + strategy.name + '。');
  }
  async function deleteStrategy() {
    const id = loadedStrategyId;
    if (!id) return;
    await request('/profit-calculator/strategies/' + id + '/', { method: 'DELETE' });
    closeStrategyModal('profitStrategyDeleteModal');
    loadedStrategyId = '';
    await loadStrategies();
    setStatus(loadedStrategyId ? '策略已删除，已加载新的默认策略。' : '策略已删除，当前使用系统默认配置。');
  }
  function updateBuyerShippingUi() {
    if (!el('profitBuyerPaysShipping').checked) buyerShippingRegion = 'west_malaysia';
    const modal = el('profitStrategyModal');
    if (!modal.hidden) {
      const disabled = !el('profitBuyerPaysShipping').checked;
      el('profitStrategyModalRegion').disabled = disabled;
      if (disabled) el('profitStrategyModalRegion').value = 'west_malaysia';
      el('profitStrategyModalRegionHint').hidden = !disabled;
    }
  }

  function ensureAdvertisingRebateUi() {
    if (!el('profitAdvertisingRebatePercent')) {
      const grid = document.querySelector('.profit-config-grid');
      const label = document.createElement('label');
      label.className = 'profit-adjustment-field';
      label.innerHTML = '广告返点（全局默认）<div class="profit-adjustment-input"><input id="profitAdvertisingRebatePercent" type="number" min="0" max="100" step="0.01" value="0.00" inputmode="decimal" /><span>%</span></div>';
      grid.appendChild(label);
    }
    const settlementList = document.querySelector('.profit-settlement-summary dl');
    if (settlementList && !el('profitAdCostBeforeRebate')) {
      const marker = el('profitCostsAfterAds').parentElement;
      [
        ['返点前广告成本', 'profitAdCostBeforeRebate', '未填写广告'],
        ['广告返点金额', 'profitAdRebateAmount', '未填写广告'],
        ['实际广告成本', 'profitActualAdCost', '未填写广告'],
        ['真实 ROI', 'profitTrueRoi', '暂无数据'],
        ['真实 CPA（USD）', 'profitTrueCpa', '不适用']
      ].forEach(function (definition) {
        const row = document.createElement('div');
        row.innerHTML = '<dt>' + definition[0] + '</dt><dd id="' + definition[1] + '">' + definition[2] + '</dd>';
        settlementList.insertBefore(row, marker);
      });
    }
  }

  async function loadStaticConfig() {
    const config = await request('/profit-calculator/config/');
    categories = config.categories || [];
    categoryTree = config.category_tree || fallbackTree;
    const adjustment = config.default_commission_adjustment || '0.00';
    el('profitCommissionAdjustment').value = adjustment;
    document.querySelectorAll('[data-profit-row]').forEach(function (row) {
      populateCategoryPicker(row, row.querySelector('[data-profit-field="category_code"]').value);
    });
    return config;
  }

  async function loadConfig() {
    const failures = [];
    try {
      await loadStaticConfig();
      const groupCount = categoryTree.reduce(function (total, item) { return total + item.children.length; }, 0);
      const leafCount = categoryTree.reduce(function (total, item) { return total + item.children.reduce(function (subtotal, group) { return subtotal + group.children.length; }, 0); }, 0);
      setStatus('已加载箱包、美妆个护完整三级类目（' + groupCount + ' 个二级、' + leafCount + ' 个三级）及马来西亚跨境运费配置。');
    } catch (_) {
      failures.push('基础费率');
    }
    try {
      await loadStrategies();
    } catch (_) {
      failures.push('命名策略');
      el('profitStrategyList').innerHTML = '<span class="session-help error">命名策略加载失败</span>';
    }
    try {
      await loadWorkingConfig();
    } catch (_) {
      failures.push('组织共享当前配置');
      // Rate availability is independent from the working-config endpoint.
      await loadExchangeRates(false);
    }
    if (failures.length) {
      setStatus('以下数据加载失败：' + failures.join('、') + '；其他已成功数据仍可使用。', true);
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
          transaction_fee_adjustment: el('profitTransactionFeeAdjustment').value || '0',
          advertising_rebate_percent: globalRebateValue(),
          buyer_pays_shipping: el('profitBuyerPaysShipping').checked,
          buyer_shipping_region: el('profitBuyerPaysShipping').checked ? buyerShippingRegion : 'west_malaysia',
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

  function loadCalculation(calculation, saveContext) {
    const source = calculation || {};
    const assign = function (id, value) { if (el(id) && value !== undefined && value !== null) el(id).value = value; };
    assign('profitCountry', source.country);
    assign('profitSellerType', source.seller_type);
    assign('profitShopIdentity', source.shop_identity);
    assign('profitCommissionAdjustment', source.commission_adjustment);
    assign('profitTransactionFeeAdjustment', source.transaction_fee_adjustment);
    assign('profitAdvertisingRebatePercent', source.advertising_rebate_percent);
    if (el('profitBxp')) el('profitBxp').checked = Boolean(source.bxp);
    if (el('profitBuyerPaysShipping')) el('profitBuyerPaysShipping').checked = Boolean(source.buyer_pays_shipping);
    buyerShippingRegion = source.buyer_shipping_region || 'west_malaysia';
    el('profitSkuRows').innerHTML = '';
    manualCommissionByRow.clear();
    (source.items || []).forEach(function (item) {
      addRow(item);
      const row = el('profitSkuRows').lastElementChild;
      const type = row.querySelector('[data-profit-field="ad_cost_type"]');
      const value = row.querySelector('[data-profit-field="ad_cost_value"]');
      type.value = item.ad_cost_type || 'none';
      value.disabled = type.value === 'none';
    });
    if (!el('profitSkuRows').children.length) addRow();
    profitPlanSaveContext = saveContext || null;
    el('profitSaveToPlans').textContent = profitPlanSaveContext ? '保存新版本' : '保存到商品利润表';
    el('profitSaveAsPlan').hidden = !profitPlanSaveContext;
    el('profitResultPanel').hidden = true;
    updateBuyerShippingUi();
  }

  async function saveToProfitPlans(forceNewPlan) {
    const panel = el('profitResultPanel');
    if (!panel || panel.hidden || !panel.dataset.lastResult) return setStatus('请先完成利润计算，再保存到商品利润表。', true);
    const rows = Array.from(document.querySelectorAll('[data-profit-row]'));
    const button = el('profitSaveToPlans');
    button.disabled = true;
    try {
      const payload = {
        country: el('profitCountry').value, seller_type: el('profitSellerType').value,
        shop_identity: el('profitShopIdentity').value, bxp: el('profitBxp').checked, delivered: true,
        commission_adjustment: el('profitCommissionAdjustment').value || '0',
        transaction_fee_adjustment: el('profitTransactionFeeAdjustment').value || '0',
        advertising_rebate_percent: globalRebateValue(), buyer_pays_shipping: el('profitBuyerPaysShipping').checked,
        buyer_shipping_region: el('profitBuyerPaysShipping').checked ? buyerShippingRegion : 'west_malaysia',
        cny_per_myr: el('profitExchangeRate').value, usd_per_myr: el('profitUsdRate').value,
        items: rows.map(function (row) {
          const item = collectRow(row);
          item.sku_code = item.sku_name;
          item.plan_name = item.sku_name + ' · 利润方案';
          const updateExisting = !forceNewPlan && profitPlanSaveContext && rows.length === 1;
          item.action = updateExisting ? 'new_version' : 'new_plan';
          if (updateExisting) item.target_plan = profitPlanSaveContext.targetPlan;
          return item;
        }),
        idempotency_key: 'profit-save-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10)
      };
      const result = await request('/profit-calculator/plans/', { method: 'POST', body: payload });
      setStatus('已保存 ' + ((result.plans || []).length || rows.length) + ' 个商品利润方案；以后可在“利润方案”查看并按当前规则重新计算。');
      root.dispatchEvent(new CustomEvent('dongbo-profit-plans-saved'));
      if (!forceNewPlan && profitPlanSaveContext) profitPlanSaveContext = Object.assign({}, profitPlanSaveContext, { sourceVersion: (result.plans && result.plans[0] && result.plans[0].version_id) || profitPlanSaveContext.sourceVersion });
    } catch (error) {
      const detail = error && error.data ? JSON.stringify(error.data) : (error.message || '保存失败');
      setStatus('保存失败：' + detail, true);
    } finally { button.disabled = false; }
  }

  function init() {
    const form = el('profitCalculatorForm');
    if (!form) return;
    ensureAdvertisingRebateUi();
    addRow();
    form.addEventListener('submit', function (event) { event.preventDefault(); calculate(true); });
    el('profitSaveToPlans').addEventListener('click', function () { saveToProfitPlans(false); });
    el('profitSaveAsPlan').addEventListener('click', function () { saveToProfitPlans(true); });
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
    el('profitRateAuto').addEventListener('click', function () { rateMode = 'auto'; saveRatePreference({ mode: 'auto' }); loadExchangeRates(true, true); scheduleWorkingConfigSave(); });
    el('profitRateManual').addEventListener('click', useManualRates);
    el('profitRateRefresh').addEventListener('click', function () { loadExchangeRates(true); });
    el('profitStrategyCreate').addEventListener('click', function () { openStrategyModal('create'); });
    el('profitStrategySaveCurrent').addEventListener('click', openSaveChoice);
    el('profitStrategyDelete').addEventListener('click', openDeleteStrategy);
    el('profitStrategyModalSave').addEventListener('click', function () { saveStrategyFromModal().catch(function (error) { setStatus(error.message || '策略保存失败', true); }); });
    el('profitStrategyOverwrite').addEventListener('click', function () { closeStrategyModal('profitStrategySaveChoiceModal'); openStrategyModal('overwrite'); });
    el('profitStrategySaveAs').addEventListener('click', function () { closeStrategyModal('profitStrategySaveChoiceModal'); openStrategyModal('save_as'); });
    el('profitStrategyDeleteConfirm').addEventListener('click', function () { deleteStrategy().catch(function (error) { setStatus(error.message || '策略删除失败', true); }); });
    ['profitStrategyModalClose', 'profitStrategyModalCancel'].forEach(function (id) { el(id).addEventListener('click', function () { closeStrategyModal('profitStrategyModal'); }); });
    ['profitStrategySaveChoiceClose', 'profitStrategySaveChoiceCancel'].forEach(function (id) { el(id).addEventListener('click', function () { closeStrategyModal('profitStrategySaveChoiceModal'); }); });
    ['profitStrategyDeleteClose', 'profitStrategyDeleteCancel'].forEach(function (id) { el(id).addEventListener('click', function () { closeStrategyModal('profitStrategyDeleteModal'); }); });
    el('profitBuyerPaysShipping').addEventListener('change', function () { updateBuyerShippingUi(); scheduleWorkingConfigSave(); });
    el('profitSellerType').addEventListener('change', function () { updateBuyerShippingUi(); scheduleWorkingConfigSave(); });

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
        if (rateMode === 'manual') scheduleWorkingConfigSave();
        rerenderLastResult();
      }
      if (event.target.matches('#profitCountry, #profitShopIdentity, #profitBxp, #profitCommissionAdjustment, #profitTransactionFeeAdjustment, #profitAdvertisingRebatePercent')) scheduleWorkingConfigSave();
    });
    document.addEventListener('input', function (event) {
      if (event.target.matches('#profitCommissionAdjustment, #profitTransactionFeeAdjustment, #profitAdvertisingRebatePercent, #profitExchangeRate, #profitUsdRate') && (rateMode === 'manual' || !event.target.matches('#profitExchangeRate, #profitUsdRate'))) scheduleWorkingConfigSave();
    });
    document.addEventListener('click', function (event) {
      const currency = event.target.closest('[data-profit-currency]');
      if (currency) {
        displayCurrency = currency.dataset.profitCurrency;
        document.querySelectorAll('[data-profit-currency]').forEach(function (button) { button.classList.toggle('active', button === currency); });
        rerenderLastResult();
        scheduleWorkingConfigSave();
        return;
      }
      const feeEdit = event.target.closest('[data-profit-fee-edit]');
      if (feeEdit) return openCommissionEditor();
      const strategyChip = event.target.closest('[data-profit-strategy-id]');
      if (strategyChip) return activateStrategy(strategyChip.dataset.profitStrategyId).catch(function (error) { setStatus(error.message || '策略切换失败', true); });
      const groupToggle = event.target.closest('[data-profit-group-toggle]');
      if (groupToggle && !event.target.closest('a, [data-profit-fee-edit]')) {
        const group = groupToggle.dataset.profitGroupToggle;
        const total = document.querySelector('[data-profit-group-total="' + CSS.escape(group) + '"]');
        const expanded = total && total.getAttribute('aria-expanded') === 'true';
        setGroupExpanded(group, !expanded);
        return;
      }
      if (event.target.closest('#profitWorkingConfigStatus') && workingConfigSaveFailed) return retryWorkingConfig().catch(function () { /* status already explains the retry */ });
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
        manualCommissionByRow.delete(row.dataset.profitRow);
        row.remove();
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        if (!el('profitFeeModal').hidden) closeFeeModal();
        ['profitStrategyModal', 'profitStrategySaveChoiceModal', 'profitStrategyDeleteModal'].forEach(function (id) { if (!el(id).hidden) closeStrategyModal(id); });
      }
      const total = event.target.closest && event.target.closest('[data-profit-group-total]');
      if (total && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        const group = total.dataset.profitGroupTotal;
        setGroupExpanded(group, total.getAttribute('aria-expanded') !== 'true');
      }
    });
    loadConfig();
    updateBuyerShippingUi();
  }

  root.DongboProfitCalculatorTestHooks = {
    nullablePercent: nullablePercent,
    revisionFrom: revisionFrom,
    buildWorkingConfigPayload: buildWorkingConfigPayload,
    workingConfigFailure: workingConfigFailure,
    strategyActivationPayload: strategyActivationPayload,
    advertisingRebateConfig: function (value) { return { advertising_rebate_percent: value == null || value === '' ? '0.00' : fixed(value) }; }
  };
  root.DongboProfitCalculator = { loadCalculation: loadCalculation };
  if (!root.document) return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(typeof window === 'undefined' ? globalThis : window);
