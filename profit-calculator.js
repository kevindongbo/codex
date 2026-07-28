(function (root) {
  'use strict';

  const runtime = Object.assign({ apiBase: '/api' }, root.DONGBO_CONFIG || {});
  const fallbackCategories = [
    ['womens_bags', '女包 / 箱包'],
    ['fashion_accessories', '时尚配饰'],
    ['peripherals_accessories', '电脑外设与配件'],
    ['home_supplies', '家居日用品'],
    ['beauty_skincare', '美妆与护肤'],
    ['musical_instruments', '乐器与配件'],
    ['essential_food', '基础食品（免佣类目）'],
    ['custom', '其他类目（手动填写费率）']
  ];
  let categories = fallbackCategories.slice();
  let rowSequence = 0;

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
  function money(value) { return 'RM ' + number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  async function request(path, options) {
    // Instantiate at request time so logins completed after page load are
    // picked up from sessionStorage immediately.
    if (root.DongboTeam) return new root.DongboTeam.TeamGateway(runtime).request(path, options);
    const settings = Object.assign({ headers: { Accept: 'application/json' } }, options || {});
    if (settings.body && typeof settings.body !== 'string') {
      settings.headers['Content-Type'] = 'application/json';
      settings.body = JSON.stringify(settings.body);
    }
    const response = await fetch(runtime.apiBase + path, settings);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '请求失败');
    return payload;
  }

  function categoryOptions(selected) {
    return categories.map(function (category) {
      return '<option value="' + escapeHtml(category[0]) + '"' + (category[0] === selected ? ' selected' : '') + '>' + escapeHtml(category[1]) + '</option>';
    }).join('');
  }

  function inputCell(label, field, value, attrs) {
    return '<label><span>' + label + '</span><input data-profit-field="' + field + '" value="' + escapeHtml(value) + '" ' + (attrs || '') + ' /></label>';
  }

  function addRow(seed) {
    const rowId = 'profit-row-' + (++rowSequence);
    const item = Object.assign({
      sku_name: 'SKU-' + String(rowSequence).padStart(3, '0'), quantity: 1,
      category_code: 'womens_bags', product_cost_cny: '18.90', item_price: '79.90',
      seller_discount: '5.00', buyer_shipping_fee: '4.90', seller_shipping_cost: '3.00',
      affiliate_rate: '15.00', platform_discount: '0.00', product_tax: '0.00',
      other_cost: '0.00', ad_spend: '0.00', custom_commission_rate: ''
    }, seed || {});
    const tbody = el('profitSkuRows');
    const tr = document.createElement('tr');
    tr.dataset.profitRow = rowId;
    tr.innerHTML =
      '<td><input aria-label="SKU 名称" data-profit-field="sku_name" value="' + escapeHtml(item.sku_name) + '" /></td>' +
      '<td><input aria-label="数量" data-profit-field="quantity" type="number" min="0.01" step="0.01" value="' + escapeHtml(item.quantity) + '" /></td>' +
      '<td><select aria-label="产品类目" data-profit-field="category_code">' + categoryOptions(item.category_code) + '</select><label class="profit-custom-rate" hidden>佣金率 %<input data-profit-field="custom_commission_rate" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(item.custom_commission_rate) + '" /></label></td>' +
      '<td><input aria-label="商品成本" data-profit-field="product_cost_cny" type="number" min="0" step="0.01" value="' + escapeHtml(item.product_cost_cny) + '" /></td>' +
      '<td><input aria-label="售价" data-profit-field="item_price" type="number" min="0" step="0.01" value="' + escapeHtml(item.item_price) + '" required /></td>' +
      '<td><input aria-label="卖家折扣" data-profit-field="seller_discount" type="number" min="0" step="0.01" value="' + escapeHtml(item.seller_discount) + '" /></td>' +
      '<td><input aria-label="买家支付运费" data-profit-field="buyer_shipping_fee" type="number" min="0" step="0.01" value="' + escapeHtml(item.buyer_shipping_fee) + '" /></td>' +
      '<td><input aria-label="卖家承担运费" data-profit-field="seller_shipping_cost" type="number" min="0" step="0.01" value="' + escapeHtml(item.seller_shipping_cost) + '" /></td>' +
      '<td><div class="profit-percent-input"><input aria-label="达人佣金率" data-profit-field="affiliate_rate" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(item.affiliate_rate) + '" /><span>%</span></div></td>' +
      '<td><button class="row-action danger" type="button" data-profit-remove="' + rowId + '" aria-label="删除此 SKU">删除</button></td>';
    tbody.appendChild(tr);

    const advanced = document.createElement('section');
    advanced.className = 'profit-advanced-row';
    advanced.dataset.profitAdvanced = rowId;
    advanced.innerHTML = '<strong>' + escapeHtml(item.sku_name) + '</strong>' +
      inputCell('平台优惠(MYR)', 'platform_discount', item.platform_discount, 'type="number" min="0" step="0.01"') +
      inputCell('商品税(MYR)', 'product_tax', item.product_tax, 'type="number" min="0" step="0.01"') +
      inputCell('其他成本(MYR)', 'other_cost', item.other_cost, 'type="number" min="0" step="0.01"') +
      inputCell('广告花费(MYR)', 'ad_spend', item.ad_spend, 'type="number" min="0" step="0.01"');
    el('profitAdvancedRows').appendChild(advanced);
    toggleCustomRate(tr);
  }

  function toggleCustomRate(row) {
    const select = row.querySelector('[data-profit-field="category_code"]');
    const custom = row.querySelector('.profit-custom-rate');
    if (custom) custom.hidden = select.value !== 'custom';
  }

  function collectRow(row) {
    const result = {};
    row.querySelectorAll('[data-profit-field]').forEach(function (field) { result[field.dataset.profitField] = field.value; });
    const advanced = document.querySelector('[data-profit-advanced="' + row.dataset.profitRow + '"]');
    advanced.querySelectorAll('[data-profit-field]').forEach(function (field) { result[field.dataset.profitField] = field.value; });
    if (result.category_code !== 'custom' || result.custom_commission_rate === '') {
      delete result.custom_commission_rate;
    }
    return result;
  }

  function setStatus(message, isError) {
    const target = el('profitFormStatus');
    target.textContent = message;
    target.classList.toggle('error', Boolean(isError));
  }

  function renderResult(result) {
    const exchange = number(el('profitExchangeRate').value);
    el('profitNet').textContent = money(result.profit);
    el('profitNetCny').textContent = '≈ CNY ' + (number(result.profit) * exchange).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el('profitMargin').textContent = number(result.profit_rate).toFixed(2) + '%';
    el('profitCpa').textContent = money(result.break_even_cpa);
    el('profitRoas').textContent = result.break_even_roas == null ? '不可盈利' : number(result.break_even_roas).toFixed(2);
    el('profitRevenue').textContent = money(result.revenue);
    el('profitTotalCosts').textContent = money(result.total_costs);
    el('profitFormulaNet').textContent = money(result.profit);
    el('profitResultVersion').textContent = '规则版本 ' + result.rule_version + ' · 金额按 MYR 四舍五入到分';
    el('profitWarnings').innerHTML = result.warnings.map(function (warning) { return '<p>i ' + escapeHtml(warning) + '</p>'; }).join('');
    el('profitBreakdownRows').innerHTML = result.breakdown.map(function (row) {
      let rate = row.rate ? row.rate + '%' : '—';
      if (row.key === 'platform_commission') {
        const rates = result.items.map(function (item) { return item.commission_rate + '%'; });
        rate = Array.from(new Set(rates)).join(' / ');
      }
      const source = row.source ? '<a href="' + escapeHtml(row.source) + '" target="_blank" rel="noopener">TikTok Shop 官方规则 ↗</a><small>' + escapeHtml(row.effective_date || '') + '</small>' : '<span>商家输入</span>';
      const amount = row.kind === 'income' ? money(row.amount) : '− ' + money(row.amount);
      return '<tr><td><strong>' + escapeHtml(row.label) + '</strong></td><td>' + escapeHtml(row.base || '—') + '</td><td>' + escapeHtml(rate) + '</td><td class="profit-amount ' + escapeHtml(row.kind) + '">' + amount + '</td><td class="profit-source">' + source + '</td></tr>';
    }).join('');
    const panel = el('profitResultPanel');
    panel.hidden = false;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadConfig() {
    try {
      const config = await request('/profit-calculator/config/');
      categories = config.categories.map(function (item) { return [item.code, item.label]; });
      categories.push(['custom', '其他类目（手动填写费率）']);
      document.querySelectorAll('[data-profit-field="category_code"]').forEach(function (select) {
        const selected = select.value;
        select.innerHTML = categoryOptions(selected);
      });
      setStatus('已加载马来西亚官方费率规则；最后核验日期 2026-07-28。');
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
    setStatus('正在按官方计费基数计算…');
    try {
      const result = await request('/profit-calculator/calculate/', {
        method: 'POST',
        body: {
          country: el('profitCountry').value,
          shop_identity: el('profitShopIdentity').value,
          bxp: el('profitBxp').checked,
          delivered: true,
          cny_per_myr: el('profitExchangeRate').value,
          items: rows.map(collectRow)
        }
      });
      renderResult(result);
      setStatus('计算完成。请按费用明细逐项核对 Seller Center。');
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
    el('profitAddSku').addEventListener('click', function () { addRow({ product_cost_cny: '0.00', item_price: '0.00', seller_discount: '0.00', buyer_shipping_fee: '0.00', seller_shipping_cost: '0.00', affiliate_rate: '0.00' }); });
    document.addEventListener('change', function (event) {
      if (event.target.matches('[data-profit-field="category_code"]')) toggleCustomRate(event.target.closest('[data-profit-row]'));
      if (event.target.matches('[data-profit-field="sku_name"]')) {
        const row = event.target.closest('[data-profit-row]');
        const label = document.querySelector('[data-profit-advanced="' + row.dataset.profitRow + '"] > strong');
        if (label) label.textContent = event.target.value || 'SKU';
      }
    });
    document.addEventListener('click', function (event) {
      const remove = event.target.closest('[data-profit-remove]');
      if (!remove) return;
      const rows = document.querySelectorAll('[data-profit-row]');
      if (rows.length === 1) return setStatus('至少保留一个 SKU。', true);
      const id = remove.dataset.profitRemove;
      document.querySelector('[data-profit-row="' + id + '"]').remove();
      document.querySelector('[data-profit-advanced="' + id + '"]').remove();
    });
    loadConfig();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(window);
