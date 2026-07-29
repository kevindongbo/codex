(function (root) {
  'use strict';

  const runtime = Object.assign({ apiBase: '/api' }, root.DONGBO_CONFIG || {});
  const fallbackTree = [
    { label: '箱包', children: [{ label: '女包', children: [
      { code: 'bag-womens-womens-backpacks', label: '女士双肩包' },
      { code: 'bag-womens-womens-handbags', label: '女士手提包' },
      { code: 'bag-womens-womens-tote-bags', label: '女士托特包' },
      { code: 'bag-womens-womens-clutches-wristlets', label: '女士手拿包与腕包' }
    ] }] },
    { label: '美妆个护', children: [{ label: '护肤', children: [
      { code: 'beauty-skincare-cleanser', label: '洁面' },
      { code: 'beauty-skincare-serum', label: '面部精华' },
      { code: 'beauty-skincare-sunscreen', label: '防晒' }
    ] }] }
  ];
  let categoryTree = fallbackTree;
  let categories = [];
  let rowSequence = 0;
  let displayCurrency = 'MYR';
  let openCategoryRow = null;

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
  function formatMoney(value, currency) {
    const target = currency || displayCurrency;
    const amount = target === 'CNY' ? number(value) * number(el('profitExchangeRate').value) : number(value);
    const prefix = target === 'CNY' ? '¥ ' : 'RM ';
    return prefix + amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatCost(value) {
    return '− ' + formatMoney(value);
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

  function categoryByCode(code) {
    return categories.find(function (item) { return item.code === code; });
  }

  function populateCategoryPicker(row, selectedCode) {
    const hidden = row.querySelector('[data-profit-field="category_code"]');
    const matched = categoryByCode(selectedCode);
    const path = matched && matched.path ? matched.path : [categoryTree[0].label, categoryTree[0].children[0].label, categoryTree[0].children[0].children[0].label];
    const industry = categoryTree.find(function (item) { return path && item.label === path[0]; }) || categoryTree[0];
    const group = industry.children.find(function (item) { return path && item.label === path[1]; }) || industry.children[0];
    const leaf = group.children.find(function (item) { return item.code === selectedCode; }) || group.children[0];
    hidden.value = leaf.code;
    row.dataset.categoryIndustry = industry.label;
    row.dataset.categoryGroup = group.label;
    row.querySelector('.profit-category-path').textContent = [industry.label, group.label, leaf.label].join(' / ');
    renderCategoryMenu(row);
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

  function chooseCategory(row, level, value) {
    if (level === 0) {
      row.dataset.categoryIndustry = value;
      const industry = categoryTree.find(function (item) { return item.label === value; });
      row.dataset.categoryGroup = industry.children[0].label;
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
      weight_g: '200', product_cost_cny: '18.90', item_price: '79.90', affiliate_rate: '15.00', ad_cost_type: 'none', ad_cost_value: ''
    }, seed || {});
    const tr = document.createElement('tr');
    tr.dataset.profitRow = rowId;
    tr.innerHTML =
      '<td><input aria-label="SKU 名称" data-profit-field="sku_name" value="' + escapeHtml(item.sku_name) + '" /></td>' +
      '<td class="profit-category-cell"><input type="hidden" data-profit-field="category_code" />' +
        '<button type="button" class="profit-category-trigger" data-category-open="' + rowId + '"><span class="profit-category-path"></span><b>⌄</b></button>' +
        '<div class="profit-category-popover" hidden><div data-category-column="0"></div><div data-category-column="1"></div><div data-category-column="2"></div></div></td>' +
      '<td><div class="profit-unit-input"><input aria-label="重量" data-profit-field="weight_g" type="number" min="1" max="15000" step="1" value="' + escapeHtml(item.weight_g) + '" required /><span>g</span></div></td>' +
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
    if (result.ad_cost_type === 'none' || result.ad_cost_value === '') result.ad_cost_value = null;
    return result;
  }

  function setStatus(message, isError) {
    const target = el('profitFormStatus');
    target.textContent = message;
    target.classList.toggle('error', Boolean(isError));
  }

  function sourceName(url) {
    return url && url.indexOf('mysst.customs.gov.my') >= 0 ? '马来西亚海关官方规则 ↗' : 'TikTok Shop 官方规则 ↗';
  }

  function renderResult(result) {
    const summary = result.amount_summary || {};
    const primaryProfit = result.has_ad_cost ? result.net_profit : result.gross_profit;
    const primaryMargin = result.has_ad_cost ? result.net_margin : result.gross_margin;
    el('profitPrimaryLabel').textContent = result.has_ad_cost ? '净利润' : '广告前毛利';
    el('profitMarginLabel').textContent = result.has_ad_cost ? '净利率' : '毛利率';
    el('profitMarginHint').textContent = (result.has_ad_cost ? '净利润' : '广告前毛利') + ' ÷ 结算收入';
    el('profitNet').textContent = formatMoney(primaryProfit);
    el('profitNetCny').textContent = displayCurrency === 'MYR' ? '≈ ' + formatMoney(primaryProfit, 'CNY') : '≈ ' + formatMoney(primaryProfit, 'MYR');
    el('profitMargin').textContent = number(primaryMargin).toFixed(2) + '%';
    el('profitCpa').textContent = '$ ' + number(result.break_even_cpa_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el('profitRoas').textContent = result.break_even_roi == null ? '不可盈利' : number(result.break_even_roi).toFixed(2);
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
    el('profitFormulaNetMargin').textContent = result.has_ad_cost ? number(result.net_margin).toFixed(2) + '%' : '未计算';
    el('profitResultVersion').textContent = '规则版本 ' + result.rule_version + ' · 当前显示 ' + displayCurrency;
    el('profitWarnings').innerHTML = result.warnings.map(function (warning) { return '<p>i ' + escapeHtml(warning) + '</p>'; }).join('');
    el('profitBreakdownCurrency').textContent = '金额(' + displayCurrency + ')';
    let previousGroup = '';
    el('profitBreakdownRows').innerHTML = result.breakdown.map(function (row) {
      let rate = row.rate ? row.rate + '%' : '—';
      if (row.key === 'platform_commission') {
        rate = Array.from(new Set(result.items.map(function (item) { return item.commission_rate + '%'; }))).join(' / ');
      }
      const source = row.source ? '<a href="' + escapeHtml(row.source) + '" target="_blank" rel="noopener">' + sourceName(row.source) + '</a><small>' + escapeHtml(row.effective_date || '') + '</small>' : '<span>自动计算</span>';
      const prefix = row.kind === 'income' || row.kind === 'info' ? '' : '− ';
      const amount = prefix + formatMoney(row.amount);
      const group = row.group === previousGroup ? '' : '<span class="profit-group-badge">' + escapeHtml(row.group || '其他') + '</span>';
      previousGroup = row.group;
      return '<tr><td>' + group + '</td><td><strong>' + escapeHtml(row.label) + '</strong></td><td data-profit-basis-column>' + escapeHtml(row.base || '—') + '</td><td>' + escapeHtml(rate) + '</td><td>' + number(row.share).toFixed(2) + '%</td><td class="profit-amount ' + escapeHtml(row.kind) + '">' + amount + '</td><td class="profit-source">' + source + '</td></tr>';
    }).join('');
    el('profitResultPanel').hidden = false;
    el('profitResultPanel').dataset.lastResult = JSON.stringify(result);
    el('profitResultPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function rerenderLastResult() {
    const saved = el('profitResultPanel').dataset.lastResult;
    if (saved) renderResult(JSON.parse(saved));
  }

  async function loadConfig() {
    try {
      const config = await request('/profit-calculator/config/');
      categories = config.categories || [];
      categoryTree = config.category_tree || fallbackTree;
      document.querySelectorAll('[data-profit-row]').forEach(function (row) {
        populateCategoryPicker(row, row.querySelector('[data-profit-field="category_code"]').value);
      });
      const secondLevelCount = categoryTree.reduce(function (total, item) { return total + item.children.length; }, 0);
      const thirdLevelCount = categoryTree.reduce(function (total, item) {
        return total + item.children.reduce(function (subtotal, group) { return subtotal + group.children.length; }, 0);
      }, 0);
      setStatus('已加载箱包、美妆个护 2 个一级类目、' + secondLevelCount + ' 个二级类目和 ' + thirdLevelCount + ' 个三级类目。');
    } catch (error) {
      setStatus('费率配置暂时无法读取，请确认已登录团队服务器后重试。', true);
    }
  }

  async function submit(event) {
    event.preventDefault();
    const rows = Array.from(document.querySelectorAll('[data-profit-row]'));
    if (!rows.length) return setStatus('请至少添加一个 SKU。', true);
    const button = event.currentTarget.querySelector('[type="submit"]');
    button.disabled = true;
    setStatus('正在自动匹配三级类目、运费和税费…');
    try {
      const result = await request('/profit-calculator/calculate/', {
        method: 'POST',
        body: {
          country: el('profitCountry').value,
          seller_type: el('profitSellerType').value,
          shop_identity: el('profitShopIdentity').value,
          bxp: el('profitBxp').checked,
          delivered: true,
          cny_per_myr: el('profitExchangeRate').value,
          usd_per_myr: el('profitUsdRate').value,
          items: rows.map(collectRow)
        }
      });
      renderResult(result);
      setStatus('计算完成：卖家折扣固定为 0，买卖双方运费及 LVG 税额均已自动计算。');
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
    form.addEventListener('submit', submit);
    el('profitAddSku').addEventListener('click', function () {
      addRow({ product_cost_cny: '0.00', item_price: '0.00', affiliate_rate: '0.00' });
    });
    const basisToggle = el('profitBasisToggle');
    if (basisToggle) basisToggle.addEventListener('click', function () {
      const table = el('profitBreakdownTable');
      const expanded = !table.classList.contains('show-basis');
      table.classList.toggle('show-basis', expanded);
      basisToggle.setAttribute('aria-expanded', String(expanded));
      basisToggle.textContent = expanded ? '收起计费基准' : '展开计费基准';
    });
    document.addEventListener('change', function (event) {
      if (event.target.matches('[data-profit-field="ad_cost_type"]')) {
        const row = event.target.closest('[data-profit-row]');
        const input = row.querySelector('[data-profit-field="ad_cost_value"]');
        const type = event.target.value;
        input.disabled = type === 'none';
        input.placeholder = type === 'roi' ? '例如 4.00' : (type === 'cpa_usd' ? '例如 5.00 USD' : (type === 'ratio' ? '例如 20.00%' : '留空不计入'));
        if (type === 'none') input.value = '';
      }
      if (event.target.matches('#profitExchangeRate')) rerenderLastResult();
    });
    document.addEventListener('click', function (event) {
      const currency = event.target.closest('[data-profit-currency]');
      if (currency) {
        displayCurrency = currency.dataset.profitCurrency;
        document.querySelectorAll('[data-profit-currency]').forEach(function (button) { button.classList.toggle('active', button === currency); });
        rerenderLastResult();
        return;
      }
      const categoryOption = event.target.closest('[data-category-option]');
      if (categoryOption) {
        chooseCategory(categoryOption.closest('[data-profit-row]'), Number(categoryOption.dataset.categoryOption), categoryOption.dataset.categoryValue);
        return;
      }
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
          popover.style.width = width + 'px';
          popover.style.height = height + 'px';
          popover.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + 'px';
          popover.style.top = (rect.bottom + 6 + height <= window.innerHeight - 12
            ? rect.bottom + 6
            : Math.max(12, rect.top - height - 6)) + 'px';
        }
        openCategoryRow = popover.hidden ? null : row;
        return;
      }
      if (openCategoryRow && !event.target.closest('.profit-category-cell')) {
        openCategoryRow.querySelector('.profit-category-popover').hidden = true;
        openCategoryRow = null;
      }
      const remove = event.target.closest('[data-profit-remove]');
      if (!remove) return;
      const rows = document.querySelectorAll('[data-profit-row]');
      if (rows.length === 1) return setStatus('至少保留一个 SKU。', true);
      remove.closest('[data-profit-row]').remove();
    });
    loadConfig();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(window);
