(function (root) {
  'use strict';

  const runtime = Object.assign({ apiBase: '/api' }, root.DONGBO_CONFIG || {});
  const fallbackTree = [{ label: '箱包', children: [{ label: '女包', children: [
    { code: 'bag-womens-womens-tote-bags', label: '女士托特包' },
    { code: 'bag-womens-womens-handbags', label: '女士手拎包' },
    { code: 'bag-womens-womens-clutches-wristlets', label: '女士手拿包&腕包' }
  ] }] }];
  let categoryTree = fallbackTree;
  let categories = [];
  let rowSequence = 0;
  let displayCurrency = 'MYR';

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

  function optionList(items, valueKey, selected) {
    return items.map(function (item) {
      const value = valueKey ? item[valueKey] : item.label;
      return '<option value="' + escapeHtml(value) + '"' + (value === selected ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>';
    }).join('');
  }

  function categoryByCode(code) {
    return categories.find(function (item) { return item.code === code; });
  }

  function populateCategoryPicker(row, selectedCode) {
    const hidden = row.querySelector('[data-profit-field="category_code"]');
    const industrySelect = row.querySelector('[data-category-level="0"]');
    const groupSelect = row.querySelector('[data-category-level="1"]');
    const leafSelect = row.querySelector('[data-category-level="2"]');
    const matched = categoryByCode(selectedCode);
    const path = matched && matched.path ? matched.path : null;
    const industry = categoryTree.find(function (item) { return path && item.label === path[0]; }) || categoryTree[0];
    industrySelect.innerHTML = optionList(categoryTree, null, industry.label);
    const group = industry.children.find(function (item) { return path && item.label === path[1]; }) || industry.children[0];
    groupSelect.innerHTML = optionList(industry.children, null, group.label);
    const leaf = group.children.find(function (item) { return item.code === selectedCode; }) || group.children[0];
    leafSelect.innerHTML = optionList(group.children, 'code', leaf.code);
    hidden.value = leaf.code;
    row.querySelector('.profit-category-path').textContent = [industry.label, group.label, leaf.label].join(' / ');
  }

  function syncCategoryPicker(row, level) {
    const industrySelect = row.querySelector('[data-category-level="0"]');
    const groupSelect = row.querySelector('[data-category-level="1"]');
    const leafSelect = row.querySelector('[data-category-level="2"]');
    const industry = categoryTree.find(function (item) { return item.label === industrySelect.value; }) || categoryTree[0];
    if (level === 0) groupSelect.innerHTML = optionList(industry.children, null, industry.children[0].label);
    const group = industry.children.find(function (item) { return item.label === groupSelect.value; }) || industry.children[0];
    if (level < 2) leafSelect.innerHTML = optionList(group.children, 'code', group.children[0].code);
    const leaf = group.children.find(function (item) { return item.code === leafSelect.value; }) || group.children[0];
    row.querySelector('[data-profit-field="category_code"]').value = leaf.code;
    row.querySelector('.profit-category-path').textContent = [industry.label, group.label, leaf.label].join(' / ');
  }

  function addRow(seed) {
    const rowId = 'profit-row-' + (++rowSequence);
    const item = Object.assign({
      sku_name: 'SKU-' + String(rowSequence).padStart(3, '0'),
      category_code: 'bag-womens-womens-tote-bags',
      weight_g: '200', product_cost_cny: '18.90', item_price: '79.90', affiliate_rate: '15.00'
    }, seed || {});
    const tr = document.createElement('tr');
    tr.dataset.profitRow = rowId;
    tr.innerHTML =
      '<td><input aria-label="SKU 名称" data-profit-field="sku_name" value="' + escapeHtml(item.sku_name) + '" /></td>' +
      '<td class="profit-category-cell"><input type="hidden" data-profit-field="category_code" />' +
        '<div class="profit-category-cascade"><select aria-label="一级类目" data-category-level="0"></select><select aria-label="二级类目" data-category-level="1"></select><select aria-label="三级类目" data-category-level="2"></select></div>' +
        '<small class="profit-category-path"></small></td>' +
      '<td><div class="profit-unit-input"><input aria-label="重量" data-profit-field="weight_g" type="number" min="1" max="15000" step="1" value="' + escapeHtml(item.weight_g) + '" required /><span>g</span></div></td>' +
      '<td><input aria-label="商品成本" data-profit-field="product_cost_cny" type="number" min="0" step="0.01" value="' + escapeHtml(item.product_cost_cny) + '" /></td>' +
      '<td><input aria-label="售价" data-profit-field="item_price" type="number" min="0" step="0.01" value="' + escapeHtml(item.item_price) + '" required /></td>' +
      '<td><div class="profit-percent-input"><input aria-label="达人佣金率" data-profit-field="affiliate_rate" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(item.affiliate_rate) + '" /><span>%</span></div></td>' +
      '<td><button class="row-action danger" type="button" data-profit-remove="' + rowId + '" aria-label="删除此 SKU">删除</button></td>';
    el('profitSkuRows').appendChild(tr);
    populateCategoryPicker(tr, item.category_code);
  }

  function collectRow(row) {
    const result = {};
    row.querySelectorAll('[data-profit-field]').forEach(function (field) { result[field.dataset.profitField] = field.value; });
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
    el('profitNet').textContent = formatMoney(result.profit);
    el('profitNetCny').textContent = displayCurrency === 'MYR' ? '≈ ' + formatMoney(result.profit, 'CNY') : '≈ ' + formatMoney(result.profit, 'MYR');
    el('profitMargin').textContent = number(result.profit_rate).toFixed(2) + '%';
    el('profitCpa').textContent = '$ ' + number(result.break_even_cpa_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el('profitRoas').textContent = result.break_even_roi == null ? '不可盈利' : number(result.break_even_roi).toFixed(2) + 'x';
    el('profitRevenue').textContent = formatMoney(result.revenue);
    el('profitTotalCosts').textContent = formatMoney(result.total_costs);
    el('profitFormulaNet').textContent = formatMoney(result.profit);
    el('profitResultVersion').textContent = '规则版本 ' + result.rule_version + ' · 当前显示 ' + displayCurrency;
    el('profitWarnings').innerHTML = result.warnings.map(function (warning) { return '<p>i ' + escapeHtml(warning) + '</p>'; }).join('');
    el('profitBreakdownCurrency').textContent = '金额(' + displayCurrency + ')';
    el('profitBreakdownRows').innerHTML = result.breakdown.map(function (row) {
      let rate = row.rate ? row.rate + '%' : '—';
      if (row.key === 'platform_commission') {
        rate = Array.from(new Set(result.items.map(function (item) { return item.commission_rate + '%'; }))).join(' / ');
      }
      const source = row.source ? '<a href="' + escapeHtml(row.source) + '" target="_blank" rel="noopener">' + sourceName(row.source) + '</a><small>' + escapeHtml(row.effective_date || '') + '</small>' : '<span>自动计算</span>';
      const prefix = row.kind === 'income' || row.kind === 'info' ? '' : '− ';
      const amount = prefix + formatMoney(row.amount);
      return '<tr><td><strong>' + escapeHtml(row.label) + '</strong></td><td>' + escapeHtml(row.base || '—') + '</td><td>' + escapeHtml(rate) + '</td><td class="profit-amount ' + escapeHtml(row.kind) + '">' + amount + '</td><td class="profit-source">' + source + '</td></tr>';
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
      setStatus('已加载 ' + categories.length + ' 个三级费率类目、马来西亚 LVG 税则和 2026-05-13 官方运费档。');
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
    document.addEventListener('change', function (event) {
      if (event.target.matches('[data-category-level]')) {
        syncCategoryPicker(event.target.closest('[data-profit-row]'), Number(event.target.dataset.categoryLevel));
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
