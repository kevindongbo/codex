(function (root) {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const currencies = { MY: 'MYR', US: 'USD', MX: 'MXN' };
  let gateway, identity = '', current = 'MY', generation = 0, dirty = false, busy = false;
  let result = null, quote = null, rates = null, config = null, workspaceRevision = 0, plan = null, strategies = [];
  const drafts = {};
  const input = (name, label, options = {}) => '<label>' + label + '<input name="' + name + '" ' +
    (options.text ? 'type="text" maxlength="200"' : 'type="number" min="0" step="0.0001" inputmode="decimal"') +
    ' value="' + escape(options.value == null ? '' : options.value) + '"' + (options.required ? ' required' : '') + ' /></label>';
  const select = (name, label, values) => '<label>' + label + '<select name="' + name + '">' + values.map(v => '<option value="' + escape(v[0]) + '">' + escape(v[1]) + '</option>').join('') + '</select></label>';
  const check = (name, label) => '<label class="market-check"><input type="checkbox" name="' + name + '" />' + label + '</label>';
  const field = name => $('marketForm').elements.namedItem(name);
  const value = name => field(name).value;
  const numberOrNull = name => value(name).trim() === '' ? null : value(name);
  function message(text, error) { $('marketStatus').textContent = text; $('marketStatus').classList.toggle('market-error', Boolean(error)); }
  function invalidate() { result = null; $('marketSavePlan').disabled = true; $('marketResults').replaceChildren(); }
  function capture() {
    const values = {};
    for (const e of $('marketForm').elements) if (e.name) values[e.name] = e.type === 'checkbox' ? e.checked : e.value;
    return { country: current, currency: currencies[current], count: $('marketItems').children.length, values: values };
  }
  function apply(draft) {
    $('marketItems').replaceChildren();
    const count = draft && draft.count || 1;
    for (let i = 0; i < count; i++) addItem(i);
    for (const [name, v] of Object.entries(draft && draft.values || {})) {
      const e = field(name); if (e) { if (e.type === 'checkbox') e.checked = v; else e.value = v; }
    }
    updateStoreCapabilities();
    dirty = false; invalidate();
  }
  function addItem(index) {
    const p = 'item' + index + '_';
    const categories = config.categories.map(c => [c.id, c.label + '（官方映射待核验）']);
    const row = document.createElement('section'); row.className = 'market-item'; row.dataset.index = String(index);
    row.innerHTML = '<h3>商品 ' + (index + 1) + ' · 整包重量／尺寸须包含本行全部数量</h3><div class="market-grid">' +
      select(p + 'sku_id', '关联库存SKU（可选）', [['','临时商品，不写入主档'], ...(config.skus || []).map(s => [s.id,s.name])]) +
      input(p + 'sku_name', 'SKU／商品名称', { text:true, required:true }) + select(p + 'category', '摄像头类目', categories) +
      input(p + 'quantity', '同一包裹内件数', { value:1, required:true }) + input(p + 'price', '单件售价（' + currencies[current] + '）', { required:true }) +
      input(p + 'cost', '单件采购成本（CNY）') + input(p + 'head', '单件头程（CNY，已包含请填0）') +
      input(p + 'affiliate', '达人佣金（%，允许0）') + input(p + 'commission', '平台佣金（%，参考6；请核实）') +
      input(p + 'weight', '整包实重') + select(p + 'weight_unit', '重量单位', current === 'US' ? [['lb','磅 lb'],['oz','盎司 oz'],['g','克 g'],['kg','千克 kg']] : [['kg','千克 kg'],['g','克 g'],['lb','磅 lb']]) +
      input(p + 'length', '整包长度') + input(p + 'width', '整包宽度') + input(p + 'height', '整包高度') +
      select(p + 'dim_unit', '尺寸单位', current === 'US' ? [['in','英寸 in'],['cm','厘米 cm']] : [['cm','厘米 cm'],['in','英寸 in']]) +
      select(p + 'battery', '电池属性', [['unknown','待确认'],['plug_in_no_battery','插电且不含电池'],['built_in','内置电池'],['removable','可拆电池／随附电池']]) +
      input(p + 'shipping', '本包裹完整当地履约报价（' + currencies[current] + '）') + '</div>' +
      '<details open><summary>折扣、税费与广告（金额为' + currencies[current] + '，每件）</summary><div class="market-grid">' +
      input(p + 'seller_discount', '商家折扣', {value:0}) + input(p + 'platform_discount', '平台折扣', {value:0}) +
      input(p + 'other', '其他落地／仓储／耗材／退货成本') + input(p + 'tax', '不可抵扣税费支出') + input(p + 'withholding', '平台税务代扣（仅扣回款）') +
      select(p + 'ad_mode', '实际广告数据', [['none','未填写，只计算毛利'],['cpa_usd','单件CPA（USD）'],['roi','实际ROI（商品税外收入／广告费）'],['percent','广告费占商品税外收入%']]) +
      input(p + 'ad_value', '实际广告数值（选填）') + '</div></details><button type="button" class="button secondary" data-save-market-profile>保存关联SKU的单件包装／市场类目</button>';
    $('marketItems').append(row);
    row.querySelector('[name="' + p + 'sku_id"]').onchange = () => {
      const selected = (config.skus || []).find(s => s.id === value(p + 'sku_id'));
      if (!selected) return;
      field(p + 'sku_name').value = selected.name;
      field(p + 'cost').value = selected.cost_cny || '';
      const profile = selected.profile || {};
      if (profile.category_mapping_id) field(p + 'category').value = profile.category_mapping_id;
      if (profile.weight) { field(p + 'weight').value = profile.weight.value; field(p + 'weight_unit').value = profile.weight.unit; }
      if (profile.dimensions) { for (const k of ['length','width','height']) field(p + k).value = profile.dimensions[k]; field(p + 'dim_unit').value = profile.dimensions.unit; }
      if (profile.battery_profile) field(p + 'battery').value = profile.battery_profile;
      const listing = (selected.listings || []).find(l => l.store === value('store'));
      field(p + 'price').value = listing ? listing.price : '';
      field(p + 'affiliate').value = listing && listing.affiliate_rate != null ? listing.affiliate_rate : (selected.profile && selected.profile.affiliate_rate != null ? selected.profile.affiliate_rate : '');
      message('已读取当前市场SKU资料，请核对包装数量及各项费用。');
    };
    row.querySelector('[data-save-market-profile]').onclick = () => act(async () => {
      const id = value(p + 'sku_id');
      if (!id || value(p + 'quantity') !== '1') throw new Error('关联库存SKU且包裹为单件时，才可保存单件包装资料。');
      const existing = await api('sku-profiles/' + id + '/?country=' + current);
      const saved = await api('sku-profiles/' + id + '/?country=' + current,{method:'PUT',body:{revision:existing.revision,
        category_mapping_id:value(p + 'category'),weight:{value:value(p + 'weight'),unit:value(p + 'weight_unit')},
        dimensions:{length:value(p + 'length'),width:value(p + 'width'),height:value(p + 'height'),unit:value(p + 'dim_unit')},battery_profile:value(p + 'battery'),affiliate_rate:numberOrNull(p + 'affiliate')}});
      (config.skus || []).find(s => s.id === id).profile = saved.profile;
      message('当前国家的SKU包装／类目已保存；官方末级映射仍待核验。');
    });
  }
  async function api(path, options) {
    if (!gateway || !gateway.accessToken) throw new Error('请先登录团队账号，再使用或保存试算。');
    const token = generation;
    const response = await gateway.request('/profit-calculator/v2/' + path, options);
    if (token !== generation) throw new Error('页面上下文已切换，请重新操作。');
    return response;
  }
  function payload() {
    const items = [], packages = [];
    for (const row of $('marketItems').children) {
      const i = Number(row.dataset.index), p = 'item' + i + '_', id = 'item-' + i, qty = Number(value(p + 'quantity'));
      items.push({ client_item_id:id, sku_id:value(p + 'sku_id') || null, sku_name:value(p + 'sku_name'), category_mapping_id:value(p + 'category'), quantity:qty,
        unit_price:value(p + 'price'), seller_discount:value(p + 'seller_discount') || '0', platform_discount:value(p + 'platform_discount') || '0',
        product_cost_cny:numberOrNull(p + 'cost'), first_leg_cost_cny:numberOrNull(p + 'head'), affiliate_rate:numberOrNull(p + 'affiliate'),
        commission_rate:numberOrNull(p + 'commission'), commission_source:value('commission_source'),
        other_cost:numberOrNull(p + 'other'), other_cost_source:value('other_source'), tax_expense:numberOrNull(p + 'tax'),
        tax_withholding:numberOrNull(p + 'withholding'), tax_source:value('tax_source'), ad_mode:value(p + 'ad_mode'), ad_value:numberOrNull(p + 'ad_value') });
      packages.push({ client_package_id:'parcel-' + i, items:[{client_item_id:id, quantity:qty}],
        weight:{value:value(p + 'weight'), unit:value(p + 'weight_unit')}, dimensions:{length:value(p + 'length'), width:value(p + 'width'), height:value(p + 'height'), unit:value(p + 'dim_unit')}, battery_profile:value(p + 'battery') });
    }
    return {schema_version:2, country:current, currency:currencies[current], store_id:value('store') || null,
      seller_program:value('seller_program'), fulfillment_service:value('service'), items:items, packages:packages,
      buyer_shipping:value('buyer_shipping') || '0', retained_shipping:value('retained_shipping') || '0',
      product_tax_in_price:value('product_tax') || '0', checkout_sales_tax:value('checkout_tax') || '0',
      subsidy:value('subsidy') || '0', subsidy_source:value('subsidy_source'), sfp:current === 'MX' && field('sfp').checked,
      sfp_confirmed:Boolean(field('sfp_confirmed') && field('sfp_confirmed').checked), mx_fee_units_confirmed:Boolean(field('mx_fee_confirmed') && field('mx_fee_confirmed').checked),
      fees_confirmed:field('fees_confirmed').checked, shipping_quote_id:quote && quote.id || null, exchange_rate_set_id:rates && rates.id || null};
  }
  function renderResult(data) {
    const money = v => v == null ? '待完善' : escape(data.currency + ' ' + v);
    $('marketResults').innerHTML = '<h2>' + (data.calculation_status === 'complete' ? '商家确认情景测算' : '缺少参数，未生成完整利润') + '</h2>' +
      '<div class="market-metrics">' + [['广告前毛利',money(data.gross_profit)],['毛利率',data.gross_margin == null ? '—' : escape(data.gross_margin) + '%'],
      ['保本ROI',escape(data.break_even_roi || '—')],['单件保本CPA',money(data.break_even_cpa)],['广告后净利润',money(data.net_profit)],['预计平台回款',money(data.platform_payout)]].map(x => '<div><small>' + x[0] + '</small><strong>' + x[1] + '</strong></div>').join('') + '</div>' +
      (data.missing_inputs.length ? '<ul>' + data.missing_inputs.map(x => '<li>' + escape(x) + '</li>').join('') + '</ul>' : '') +
      data.items.map(item => '<details open><summary>' + escape(item.sku_name) + ' · 毛利 ' + money(item.gross_profit) + '</summary><table><thead><tr><th>费用</th><th>金额</th><th>依据</th></tr></thead><tbody>' +
        item.fees.map(f => '<tr><td>' + escape(f.label) + '</td><td>' + money(f.amount) + '</td><td>' + escape(f.source) + '</td></tr>').join('') + '</tbody></table></details>').join('') +
      '<p>' + data.warnings.map(escape).join('<br>') + '</p><small>规则版本 ' + escape(data.context.rule_version) + ' · 上下文 ' + escape(data.context_hash.slice(0,12)) + '</small>';
  }
  async function saveWorkspace() {
    const token = generation, c = current, draft = capture();
    const saved = await api('working-config/?country=' + c, {method:'PUT', body:{revision:workspaceRevision, config:draft}});
    if (generation !== token) return;
    workspaceRevision = saved.revision; drafts[c] = draft; dirty = false; message('当前国家草稿已保存，版本 ' + saved.revision);
  }
  async function loadPlans() {
    const token = generation, c = current;
    const plans = await api('plans/?country=' + c);
    if (token !== generation) return;
    $('marketPlans').innerHTML = plans.map(p => '<button type="button" class="button secondary" data-market-plan="' + escape(p.id) + '">' + escape(p.name + ' · v' + p.version + ' · ' + p.currency + ' ' + p.gross_profit) + '</button>').join('') || '<p>此国家尚无已保存方案。</p>';
  }
  function strategyOptions() {
    $('marketStrategy').innerHTML = '<option value="">选择本国策略</option>' + strategies.map(s => '<option value="' + escape(s.id) + '">' + escape(s.name + (s.is_default ? '（默认）' : '')) + '</option>').join('');
  }
  async function loadMarket(c) {
    generation += 1; const token = generation;
    current = c; dirty = false; result = quote = rates = plan = null;
    $('profitMarketSwitch').value = c;
    $('module-profit').classList.toggle('market-active', c !== 'MY');
    $('marketProfitPanel').hidden = c === 'MY';
    if (c === 'MY') return;
    $('marketForm').hidden = true; $('marketResults').replaceChildren(); $('marketPlans').replaceChildren();
    message('正在读取' + c + '配置…');
    try {
      const values = await Promise.all([api('config/?country=' + c), api('working-config/?country=' + c), api('exchange-rates/?country=' + c), api('strategies/?country=' + c)]);
      if (token !== generation) return;
      config = values[0]; workspaceRevision = values[1].revision; rates = values[2].id ? values[2] : null; strategies = values[3];
      buildForm();
      apply(drafts[c] || values[1].config);
      if (rates) { field('cny_rate').value = rates.payload.cny_per_base; field('usd_rate').value = rates.payload.usd_per_base; field('rate_source').value = rates.payload.source; }
      $('marketForm').hidden = false; strategyOptions();
      message(c + ' / ' + currencies[c] + ' · 商家确认情景。官方末级类目、税务与完整物流价表待核验。');
      await loadPlans();
    } catch (error) { if (token === generation) message('加载失败：' + error.message + '；登录后点击“重新加载”。', true); }
  }
  function updateStoreCapabilities() {
    const selected = (config.stores || []).find(s => s.id === value('store'));
    const service = field('service');
    for (const option of service.options) {
      const definition = config.fulfillment_services.find(s => s.code === option.value);
      option.disabled = !definition.enabled || Boolean(selected && !(selected.capabilities || []).includes(option.value));
    }
    if (service.selectedOptions[0] && service.selectedOptions[0].disabled) service.value = '';
    service.required = true;
  }
  function buildForm() {
    $('marketForm').innerHTML = '<div class="market-grid">' +
      select('store','店铺（未关联为情景）',[['','未关联店铺'], ...config.stores.map(s => [s.id,s.name])]) +
      input('seller_program','卖家项目／主体假设（如当地注册或跨境主体）',{text:true,required:true}) +
      select('service','当地仓履约',config.fulfillment_services.map(s => [s.code,s.label + (s.enabled ? ' · 人工确认报价' : ' · 待核验不可用')])) +
      input('origin','当地发货区域／邮编',{text:true,required:true}) + input('destination','目的地区域／邮编',{text:true,required:true}) +
      input('cny_rate','1 ' + currencies[current] + ' = CNY',{required:true}) +
      input('usd_rate','1 ' + currencies[current] + ' = USD',{value:current === 'US' ? 1 : '',required:true}) + input('rate_source','汇率来源／日期',{text:true,required:true}) +
      input('quote_source','履约报价来源／日期（含旺季、区域、带电等附加费）',{text:true,required:true}) + input('quote_minutes','本次报价有效分钟（1～1440）',{value:60,required:true}) +
      select('payment_channel','履约费用支付方式',[['offline','线下支付，只扣利润'],['platform','平台代扣，同时扣回款']]) +
      input('commission_source','佣金确认依据（类目／订单样例）',{text:true}) + input('other_source','其他成本依据（含零／已包含说明）',{text:true}) +
      input('tax_source','税务口径依据（含主体、价内税／代扣／抵扣性）',{text:true}) +
      input('buyer_shipping','买家支付运费',{value:0}) + input('retained_shipping','其中商家实际保留运费',{value:0}) +
      input('product_tax','整单商品价内税（US须为0；MX按依据填写）',{value:0}) + input('checkout_tax','结账销售税（US平台过手项，不计收入）',{value:0}) +
      input('subsidy','额外补贴（不含已计入的平台商品折扣）',{value:0}) + input('subsidy_source','补贴来源（无补贴可留空）',{text:true}) + '</div>' +
      '<div class="market-checks">' + check('eligibility','已确认服务／店铺资格及本次包裹可承运') + check('battery_accepted','承运报价已确认电池属性') +
      check('surcharges','报价包含本次全部附加费') + check('fees_confirmed','已确认各项费用及税务口径；填0表示确认无此项或已包含') +
      (current === 'MX' ? check('mx_fee_confirmed','已核验本单MXN6按件费用适用') + check('sfp','本单参加SFP（8%，上限40 MXN／件）') + check('sfp_confirmed','已确认SFP资格与收费基数；未预设运费补贴') : '') + '</div>' +
      '<p>每行按一个整包报价，可装多件本SKU。不同SKU合包可通过v2接口提交。平台仓报价须含拣包、耗材、尾程，其他成本不要重复填写。</p>' +
      '<div id="marketItems"></div><div class="market-actions"><button type="button" class="button secondary" id="marketAddItem">添加商品／包裹</button><button type="button" class="button secondary" id="marketRemoveItem">移除最后一行</button><button type="submit" class="button primary">确认报价、汇率并计算</button></div>';
    updateStoreCapabilities();
    field('store').onchange = () => {
      const selected = (config.stores || []).find(s => s.id === value('store'));
      if (selected) field('seller_program').value = selected.seller_program || '';
      updateStoreCapabilities();
      for (const row of $('marketItems').children) {
        const p = 'item' + row.dataset.index + '_';
        const sku = (config.skus || []).find(s => s.id === value(p + 'sku_id'));
        if (sku) {
          const listing = (sku.listings || []).find(l => l.store === value('store'));
          field(p + 'price').value = listing ? listing.price : '';
          field(p + 'affiliate').value = listing && listing.affiliate_rate != null ? listing.affiliate_rate : (sku.profile && sku.profile.affiliate_rate != null ? sku.profile.affiliate_rate : '');
        }
      }
    };
    $('marketAddItem').onclick = () => { addItem($('marketItems').children.length); dirty = true; quote = null; invalidate(); };
    $('marketRemoveItem').onclick = () => { if ($('marketItems').children.length > 1) { $('marketItems').lastElementChild.remove(); dirty = true; quote = null; invalidate(); } };
  }
  async function calculateForm(event) {
    event.preventDefault(); if (busy) return;
    busy = true; $('marketForm').inert = true; const token = generation;
    try {
      invalidate();
      const rateInput = {country:current, cny_per_base:value('cny_rate'), usd_per_base:value('usd_rate'), source:value('rate_source')};
      const same = rates && Number(rates.payload.cny_per_base) === Number(rateInput.cny_per_base) && Number(rates.payload.usd_per_base) === Number(rateInput.usd_per_base) && rates.payload.source === rateInput.source && Date.parse(rates.valid_until) > Date.now();
      if (!same) { const next = await api('exchange-rates/', {method:'POST',body:rateInput}); if (token !== generation) return; rates = next; }
      if (token !== generation) return;
      const data = payload();
      const lines = [...$('marketItems').children].map(row => ({package_id:'parcel-' + row.dataset.index, amount:value('item' + row.dataset.index + '_shipping')}));
      const quoteInput = {country:current,currency:currencies[current],store_id:data.store_id,seller_program:data.seller_program,fulfillment_service:data.fulfillment_service,
        packages:data.packages,lines:lines,source:value('quote_source'),origin:value('origin'),destination:value('destination'),
        payment_channel:value('payment_channel'),includes:data.fulfillment_service === 'platform_warehouse' ? ['last_mile','pick_pack','materials','surcharges'] : ['last_mile','surcharges'],
        eligibility_confirmed:field('eligibility').checked,battery_accepted:field('battery_accepted').checked,surcharges_confirmed:field('surcharges').checked,valid_for_minutes:Number(value('quote_minutes'))};
      const nextQuote = await api('shipping-quotes/',{method:'POST',body:quoteInput});
      if (token !== generation) return; quote = nextQuote;
      const calculated = await api('calculate/',{method:'POST',body:payload()});
      if (token !== generation) return;
      result = calculated; renderResult(result); $('marketSavePlan').disabled = result.calculation_status !== 'complete';
      message(result.calculation_status === 'complete' ? '计算完成。方案保存时会由服务器重新计算并核对上下文。' : '参数不全，毛利、净利及ROI保持空值。');
    } catch (error) { if (token === generation) message(error.message + (error.data ? ' ' + JSON.stringify(error.data) : ''), true); }
    finally { busy = false; $('marketForm').inert = false; }
  }
  function init() {
    const host = document.createElement('section'); host.className = 'panel market-selector';
    host.innerHTML = '<label>销售市场<select id="profitMarketSwitch"><option value="MY">马来西亚 MY · MYR</option><option value="US">美国 US · USD</option><option value="MX">墨西哥 MX · MXN</option></select></label><span>市场分别保存；US/MX采用当地仓履约</span>';
    $('module-profit').prepend(host);
    const panel = document.createElement('section'); panel.id = 'marketProfitPanel'; panel.className = 'panel market-profit-panel'; panel.hidden = true;
    panel.innerHTML = '<h1>摄像头利润试算</h1><p>官方规则与商家报价分开标识。未核验的官方类目和服务不自动套用费用。</p><p id="marketStatus" role="status"></p>' +
      '<div class="market-actions"><button type="button" class="button secondary" id="marketReload">重新加载</button><button type="button" class="button secondary" id="marketSaveWorkspace">保存本国草稿</button><select id="marketStrategy" aria-label="本国策略"></select><input id="marketStrategyName" maxlength="120" placeholder="策略名称" aria-label="策略名称" /><button class="button secondary" id="marketSaveStrategy">另存策略</button><button class="button secondary" id="marketActivateStrategy">加载策略</button><button class="button secondary" id="marketDeleteStrategy">删除策略</button></div>' +
      '<form id="marketForm" hidden></form><section id="marketResults" aria-live="polite"></section>' +
      '<div class="market-actions"><input id="marketPlanName" maxlength="120" placeholder="方案名称" aria-label="方案名称" /><button class="button primary" id="marketSavePlan" disabled>保存计算方案／新版本</button><button class="button secondary" id="marketNewPlan">另存为新方案</button></div><h2>本市场历史方案（含版本）</h2><div id="marketPlans" class="market-actions"></div>';
    $('module-profit').append(panel);
    const confirm = document.createElement('dialog'); confirm.id = 'marketSwitchDialog'; confirm.className = 'account-lifecycle-dialog';
    confirm.innerHTML = '<h2>当前国家有未保存编辑</h2><p>保存本国草稿后切换，或放弃本次编辑。金额不会直接换币种。</p><div class="market-actions"><button id="marketSwitchSave" class="button primary">保存后切换</button><button id="marketSwitchDiscard" class="button secondary">放弃后切换</button><button id="marketSwitchCancel" class="button secondary">取消</button></div>'; document.body.append(confirm);
    let target;
    $('profitMarketSwitch').onchange = function () { target = this.value; this.value = current; if (busy) return message('正在处理请求，请完成后再切换。',true); if (dirty && current !== 'MY') confirm.showModal(); else loadMarket(target); };
    $('marketSwitchSave').onclick = () => act(async () => { await saveWorkspace(); confirm.close(); loadMarket(target); });
    $('marketSwitchDiscard').onclick = () => { delete drafts[current]; confirm.close(); loadMarket(target); };
    $('marketSwitchCancel').onclick = () => confirm.close();
    $('marketForm').addEventListener('input', () => { dirty = true; quote = null; invalidate(); });
    $('marketForm').addEventListener('change', () => { dirty = true; quote = null; invalidate(); });
    $('marketForm').addEventListener('submit', calculateForm);
    $('marketReload').onclick = () => { if (!dirty || root.confirm('重新加载会放弃未保存编辑，继续？')) loadMarket(current); };
    $('marketSaveWorkspace').onclick = () => act(saveWorkspace);
    $('marketSaveStrategy').onclick = () => act(async () => { await api('strategies/?country=' + current,{method:'POST',body:{name:$('marketStrategyName').value,config:capture()}}); strategies = await api('strategies/?country=' + current); strategyOptions(); message('本国策略已保存。'); });
    $('marketActivateStrategy').onclick = () => act(async () => { const s = strategies.find(s => s.id === $('marketStrategy').value); if (!s) throw new Error('请先选择策略'); if (dirty && !root.confirm('加载策略会替换当前编辑，继续？')) return; const w = await api('strategies/' + s.id + '/activate/?country=' + current,{method:'POST',body:{revision:s.revision,working_revision:workspaceRevision}}); workspaceRevision = w.revision; apply(w.config); quote = null; message('已加载本国策略。'); });
    $('marketDeleteStrategy').onclick = () => act(async () => { const s = strategies.find(s => s.id === $('marketStrategy').value); if (!s || !root.confirm('删除策略“' + s.name + '”？已保存的利润版本保留。')) return; await api('strategies/' + s.id + '/?country=' + current,{method:'DELETE',body:{revision:s.revision}}); strategies = await api('strategies/?country=' + current); strategyOptions(); });
    $('marketNewPlan').onclick = () => { plan = null; message('下次保存将创建独立新方案。'); };
    $('marketSavePlan').onclick = () => act(async () => { if (!result) return; const body = {name:$('marketPlanName').value || '摄像头试算',input:payload(),ui_draft:capture(),expected_context_hash:result.context_hash}; if (plan) { body.plan_key = plan.plan_key; body.expected_version = plan.version; } plan = await api('plans/save/',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:body}); message('方案v' + plan.version + '已保存，原版本不可变。'); await loadPlans(); });
    $('marketPlans').onclick = event => { const button = event.target.closest('[data-market-plan]'); if (button) act(async () => { const saved = await api('plans/' + button.dataset.marketPlan + '/?country=' + current); plan = saved; if (saved.payload.ui_draft) apply(saved.payload.ui_draft); $('marketPlanName').value = saved.name; renderResult(saved.payload.result); invalidateSavedResult(); message('只读历史快照v' + saved.version + '。编辑当前输入并重新计算后可追加新版本。'); }); };
  }
  function invalidateSavedResult() { result = null; $('marketSavePlan').disabled = true; }
  async function act(fn) { if (busy) return; busy = true; $('marketForm').inert = true; try { await fn(); } catch (error) { message(error.message + (error.data ? ' ' + JSON.stringify(error.data) : ''),true); } finally { busy = false; $('marketForm').inert = false; } }
  root.DongboMarketProfit = { mount(g) {
    gateway = g;
    const next = g && g.user ? String(g.user.id) : '';
    if (identity !== next) { identity = next; generation++; Object.keys(drafts).forEach(k => delete drafts[k]); current = 'MY'; dirty = false; result = quote = rates = plan = config = null; $('marketForm').replaceChildren(); $('marketResults').replaceChildren(); $('marketPlans').replaceChildren(); $('profitMarketSwitch').value = 'MY'; $('module-profit').classList.remove('market-active'); $('marketProfitPanel').hidden = true; }
  }};
  init();
})(globalThis);
