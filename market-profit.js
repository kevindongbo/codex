(function (root) {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const currencies = { MY: 'MYR', US: 'USD' };
  let gateway, identity = '', current = 'MY', generation = 0, dirty = false, busy = false;
  let result = null, quote = null, rates = null, config = null, workspaceRevision = 0, plan = null, strategies = [];
  const drafts = {};
  let displayCurrency = 'USD', displayedResult = null;
  const itemRows = () => [...$('marketItems').querySelectorAll('tr.market-item')];
  function money(v) { return v == null ? '待完善' : (displayCurrency === 'CNY' ? '¥ ' : '$ ') + (Number(v) * (displayCurrency === 'CNY' ? Number(value('cny_rate')) : 1)).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
  function showView(view) {
    if (current !== 'US') return;
    const target = view === 'plans' ? 'plans' : view === 'rules' ? 'rules' : 'calculator';
    document.querySelectorAll('[data-market-view]').forEach(e => { e.hidden = e.dataset.marketView !== target; });
    const home = target === 'calculator' ? $('usConfigGrid') : document.querySelector('[data-market-view="'+target+'"] .panel-title');
    if(home && $('marketSelector')) home.prepend($('marketSelector'));
  }
  const input = (name, label, options = {}) => '<label>' + label + '<input name="' + name + '" ' +
    (options.text ? 'type="text" maxlength="200"' : 'type="number" min="0" step="0.0001" inputmode="decimal"') +
    ' value="' + escape(options.value == null ? '' : options.value) + '"' + (options.required ? ' required' : '') + ' /></label>';
  const select = (name, label, values) => '<label>' + label + '<select name="' + name + '">' + values.map(v => '<option value="' + escape(v[0]) + '">' + escape(v[1]) + '</option>').join('') + '</select></label>';
  const check = (name, label) => '<label class="market-check"><input type="checkbox" name="' + name + '" />' + label + '</label>';
  const field = name => $('marketForm').elements.namedItem(name);
  const value = name => field(name).value;
  const numberOrNull = name => value(name).trim() === '' ? null : value(name);
  function message(text, error) { $('marketStatus').textContent = text; $('marketStatus').classList.toggle('market-error', Boolean(error)); }
  function invalidate() { result = null; displayedResult = null; $('marketSavePlan').disabled = true; $('marketResults').replaceChildren(); }
  function capture() {
    const values = {};
    for (const e of $('marketForm').elements) if (e.name) values[e.name] = e.type === 'checkbox' ? e.checked : e.value;
    return { country: current, currency: currencies[current], count: itemRows().length, indexes:itemRows().map(r=>Number(r.dataset.index)), values: values };
  }
  function strategyDraft() {
    const draft=capture();
    return {country:draft.country,currency:draft.currency,values:Object.fromEntries(Object.entries(draft.values).filter(([key])=>!key.startsWith('item')))};
  }
  function apply(draft) {
    $('marketItems').replaceChildren();
    const count = draft && draft.count || 1;
    for (const i of draft && draft.indexes || Array.from({length:count},(_,i)=>i)) addItem(i);
    for (const [name, v] of Object.entries(draft && draft.values || {})) {
      const e = field(name); if (e) { if (e.type === 'checkbox') e.checked = v; else e.value = v; }
    }
    itemRows().forEach(row=>{const p='item'+row.dataset.index+'_';field(p+'ad_mode').onchange();});
    updateStoreCapabilities();
    dirty = false; invalidate();
  }
  function addItem(index) {
    const p = 'item' + index + '_';
    const categories = config.categories.map(c => [c.id,c.label.replace('3C／数码 · ','3C / 摄像头 / ')]);
    const row = document.createElement('tr'); row.className = 'market-item'; row.dataset.index = String(index);
    const cell = html => '<td>' + html + '</td>';
    row.innerHTML = cell('<input name="' + p + 'sku_name" aria-label="SKU名称" placeholder="SKU-' + (index+1) + '" />') +
      cell(select(p+'category','',categories)) +
      cell('<div class="us-weight"><input name="'+p+'weight" aria-label="包装重量" type="number" min="0.000001" step="any" />' + select(p+'weight_unit','',[['g','g'],['lb','lb'],['oz','oz'],['kg','kg']]) + '</div>') +
      cell('<input name="'+p+'cost" aria-label="采购成本CNY" type="number" min="0" step="0.01" />') +
      cell('<input name="'+p+'price" aria-label="售价USD" type="number" min="0" step="0.01" />') +
      cell('<div class="profit-percent-input"><input name="'+p+'affiliate" aria-label="达人佣金" type="number" min="0" max="100" step="0.01" /><span>%</span></div>') +
      cell('<div class="us-ad">' + select(p+'ad_mode','',[['none','不计广告'],['roi','实际 ROI'],['cpa_usd','单件 CPA（USD）'],['percent','广告费占比（%）']]) + '<input name="'+p+'ad_value" aria-label="实际广告数据" type="number" min="0" step="0.01" placeholder="选填" disabled /></div>') +
      cell('<button type="button" class="row-action" data-us-details aria-expanded="false">设置</button><button type="button" class="row-action danger" data-us-remove>删除</button>');
    const details = document.createElement('tr'); details.className='us-detail-row'; details.hidden=true; details.dataset.index=String(index);
    details.innerHTML='<td colspan="8"><div class="us-detail-heading"><strong>本行物流、成本与税费</strong><span>同一包裹内数量和尺寸应与实际报价一致</span></div><div class="market-grid">' +
      select(p+'sku_id','关联库存 SKU',[['','临时商品'],...(config.skus||[]).map(x=>[x.id,x.name])]) + input(p+'quantity','包裹内件数',{value:1}) +
      input(p+'head','单件头程成本（CNY）') + input(p+'shipping','本包裹当地运费（USD）') +
      input(p+'length','整包长') + input(p+'width','整包宽') + input(p+'height','整包高') + select(p+'dim_unit','尺寸单位',[['in','英寸 in'],['cm','厘米 cm']]) +
      select(p+'battery','电池属性',[['unknown','请选择'],['plug_in_no_battery','插电，无电池'],['built_in','内置电池'],['removable','可拆／随附电池']]) +
      input(p+'commission','平台佣金覆盖（%，留空继承上方）') + input(p+'seller_discount','单件商家折扣（USD）',{value:0}) + input(p+'platform_discount','单件平台折扣（USD）',{value:0}) +
      input(p+'other','单件其他成本（USD）') + input(p+'tax','单件不可抵扣税费（USD）') + input(p+'withholding','单件税务代扣（USD，仅影响回款）') +
      '</div><button type="button" class="button secondary" data-save-market-profile>保存关联 SKU 包装资料</button></td>';
    $('marketItems').append(row,details);
    row.querySelector('[data-us-details]').onclick=()=>{ details.hidden=!details.hidden; row.querySelector('[data-us-details]').setAttribute('aria-expanded',String(!details.hidden)); };
    row.querySelector('[data-us-remove]').onclick=()=>{ if(itemRows().length===1) return message('至少保留一个 SKU。',true); row.remove();details.remove();dirty=true;quote=null;invalidate(); };
    field(p+'ad_mode').onchange=()=>{ field(p+'ad_value').disabled=value(p+'ad_mode')==='none'; if(field(p+'ad_value').disabled) field(p+'ad_value').value=''; };
    field(p+'sku_id').onchange=()=>{
      const selected=(config.skus||[]).find(x=>x.id===value(p+'sku_id')); if(!selected)return;
      field(p+'sku_name').value=selected.name; field(p+'cost').value=selected.cost_cny||'';
      const profile=selected.profile||{};
      if(profile.category_mapping_id)field(p+'category').value=profile.category_mapping_id;
      if(profile.weight){field(p+'weight').value=profile.weight.value;field(p+'weight_unit').value=profile.weight.unit;}
      if(profile.dimensions){for(const k of ['length','width','height'])field(p+k).value=profile.dimensions[k];field(p+'dim_unit').value=profile.dimensions.unit;}
      if(profile.battery_profile)field(p+'battery').value=profile.battery_profile;
      const listing=(selected.listings||[]).find(l=>l.store===value('store'));
      field(p+'price').value=listing?listing.price:'';field(p+'affiliate').value=listing&&listing.affiliate_rate!=null?listing.affiliate_rate:profile.affiliate_rate??'';
    };
    details.querySelector('[data-save-market-profile]').onclick=()=>act(async()=>{
      const id=value(p+'sku_id');if(!id||value(p+'quantity')!=='1')throw Error('请选择关联 SKU，且包装数量为1。');
      const old=await api('sku-profiles/'+id+'/?country=US');
      const saved=await api('sku-profiles/'+id+'/?country=US',{method:'PUT',body:{revision:old.revision,category_mapping_id:value(p+'category'),weight:{value:value(p+'weight'),unit:value(p+'weight_unit')},dimensions:{length:value(p+'length'),width:value(p+'width'),height:value(p+'height'),unit:value(p+'dim_unit')},battery_profile:value(p+'battery'),affiliate_rate:numberOrNull(p+'affiliate')}});
      config.skus.find(x=>x.id===id).profile=saved.profile;message('美国 SKU 包装资料已保存。');
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
    for (const row of itemRows()) {
      const i = Number(row.dataset.index), p = 'item' + i + '_', id = 'item-' + i, qty = Number(value(p + 'quantity'));
      items.push({ client_item_id:id, sku_id:value(p + 'sku_id') || null, sku_name:value(p + 'sku_name'), category_mapping_id:value(p + 'category'), quantity:qty,
        unit_price:value(p + 'price'), seller_discount:value(p + 'seller_discount') || '0', platform_discount:value(p + 'platform_discount') || '0',
        product_cost_cny:numberOrNull(p + 'cost'), first_leg_cost_cny:numberOrNull(p + 'head'), affiliate_rate:numberOrNull(p + 'affiliate'),
        commission_rate:numberOrNull(p + 'commission') ?? numberOrNull('global_commission'), commission_source:value('commission_source'),
        other_cost:numberOrNull(p + 'other'), other_cost_source:value('other_source'), tax_expense:numberOrNull(p + 'tax'),
        tax_withholding:numberOrNull(p + 'withholding'), tax_source:value('tax_source'), ad_mode:value(p + 'ad_mode'), ad_value:numberOrNull(p + 'ad_value') });
      packages.push({ client_package_id:'parcel-' + i, items:[{client_item_id:id, quantity:qty}],
        weight:{value:value(p + 'weight'), unit:value(p + 'weight_unit')}, dimensions:{length:value(p + 'length'), width:value(p + 'width'), height:value(p + 'height'), unit:value(p + 'dim_unit')}, battery_profile:value(p + 'battery') });
    }
    return {schema_version:2, country:current, currency:currencies[current], store_id:value('store') || null,
      seller_program:value('seller_program'), fulfillment_service:value('service'), items:items, packages:packages,
      buyer_shipping:value('buyer_shipping') || '0', retained_shipping:value('retained_shipping') || '0',
      product_tax_in_price:value('product_tax') || '0', checkout_sales_tax:value('checkout_tax') || '0',
      subsidy:value('subsidy') || '0', subsidy_source:value('subsidy_source'), sfp:false,
      sfp_confirmed:Boolean(field('sfp_confirmed') && field('sfp_confirmed').checked), mx_fee_units_confirmed:Boolean(field('mx_fee_confirmed') && field('mx_fee_confirmed').checked),
      fees_confirmed:field('fees_confirmed').checked, shipping_quote_id:quote && quote.id || null, exchange_rate_set_id:rates && rates.id || null};
  }
  function renderResult(data) {
    displayedResult=data;
    const complete=data.calculation_status==='complete', hasAds=data.net_profit!=null;
    const pct=v=>v==null?'—':Number(v).toFixed(2)+'%';
    const metric=(label,v,hint)=>'<article><div><span>'+label+'</span><strong>'+v+'</strong><small>'+hint+'</small></div></article>';
    const groups=new Map();
    for(const item of data.items){for(const fee of item.fees){
      if(['售出固定费','SFP服务费'].includes(fee.label))continue;
      const group=fee.label==='商品成本'?'商品':fee.label==='头程成本'||fee.label==='当地履约'?'物流':fee.label==='平台佣金'?'平台代扣':fee.label==='达人佣金'?'推广代扣':fee.label==='不可抵扣税费'?'税费':'其他成本';
      if(!groups.has(group))groups.set(group,new Map());const bucket=groups.get(group);const existing=bucket.get(fee.label)||{amount:0,sources:new Set()};existing.amount+=Number(fee.amount);existing.sources.add(fee.source);bucket.set(fee.label,existing);
    }}
    const adTotal=data.items.reduce((total,item)=>total+Number(item.advertising_cost||0),0);
    if(data.items.some(item=>item.advertising_cost!=null))groups.set('广告投放',new Map([['实际广告费用',{amount:adTotal,sources:new Set(['按实际 ROI、CPA 或广告占比计算'])}]]));
    const sales=Number(data.sales||0), share=amount=>sales?(amount/sales*100).toFixed(2)+'%':'—';
    const feeRows=[...groups].map(([name,fees])=>({name,fees,total:[...fees.values()].reduce((a,f)=>a+f.amount,0)})).sort((a,b)=>Math.abs(b.total)-Math.abs(a.total));
    const breakdown=feeRows.map(group=>'<tr class="profit-group-total"><td>'+escape(group.name)+'</td><td><button type="button" class="profit-group-toggle" data-us-group="'+escape(group.name)+'" aria-expanded="false">展开 '+escape(group.name)+'合计</button></td><td>'+share(group.total)+'</td><td>− '+money(group.total)+'</td><td>分组汇总</td></tr>'+[...group.fees].sort((a,b)=>b[1].amount-a[1].amount).map(([label,fee])=>'<tr hidden data-us-fee-group="'+escape(group.name)+'"><td></td><td>'+escape(label)+'</td><td>'+share(fee.amount)+'</td><td>− '+money(fee.amount)+'</td><td>'+[...fee.sources].map(escape).join('；')+'</td></tr>').join('')).join('');
    $('marketResults').innerHTML='<div class="profit-results-toolbar"><span>利润计算结果 · 修改输入后请重新计算</span><button type="button" class="button primary" id="usSaveFromResult" '+(!complete?'disabled':'')+'>保存到商品利润表</button></div>'+
      '<div class="summary-strip profit-summary">'+metric(hasAds?'净利润':'广告前毛利',money(hasAds?data.net_profit:data.gross_profit),'USD / CNY 可切换')+metric(hasAds?'净利率':'毛利率',pct(hasAds?data.net_margin:data.gross_margin),'以商品税外销售收入为基数')+metric('单件保本 CPA（USD）',data.break_even_cpa==null?'—':'$ '+data.break_even_cpa,'单件可承受广告成本')+metric('保本 ROI',escape(data.break_even_roi||'—'),'商品销售收入 ÷ 广告前毛利')+'</div>'+
      (data.missing_inputs.length?'<div class="us-missing" role="alert">请补充：'+data.missing_inputs.map(escape).join('、')+'</div>':'')+
      '<section class="panel profit-breakdown-panel"><div class="panel-title"><div><h2>费用明细</h2><p>美国 · '+escape(data.context.rule_version)+' · 人工费率与报价</p></div></div><div class="table-wrap"><table class="us-breakdown"><thead><tr><th>归类</th><th>费用项</th><th>占比</th><th>金额（'+displayCurrency+'）</th><th>依据</th></tr></thead><tbody><tr><td>收入</td><td>商品销售收入</td><td>100%</td><td>'+money(data.sales)+'</td><td>商品售价减商家折扣，不含结账销售税</td></tr>'+breakdown+'</tbody></table></div></section>'+
      '<section class="panel us-settlement"><div class="panel-title"><h2>结算与利润</h2></div><dl>'+[['预计平台回款',data.platform_payout],['广告前毛利',data.gross_profit],['实际广告费用',hasAds?data.items.reduce((a,i)=>a+Number(i.advertising_cost||0),0):null],['广告后净利润',data.net_profit]].map(([label,v])=>'<div><dt>'+label+'</dt><dd>'+money(v)+'</dd></div>').join('')+'</dl></section>';
    $('usSaveFromResult').onclick=()=>{document.querySelector('[data-side-link][data-profit-view="plans"]').click();$('marketPlanName').focus();message('填写方案名称并保存当前计算结果。');};
    $('marketResults').querySelectorAll('[data-us-group]').forEach(button=>button.onclick=()=>{const expanded=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(expanded));button.textContent=(expanded?'收起 ':'展开 ')+button.dataset.usGroup+'合计';$('marketResults').querySelectorAll('[data-us-fee-group]').forEach(row=>{if(row.dataset.usFeeGroup===button.dataset.usGroup)row.hidden=!expanded;});});
  }
  async function saveWorkspace() {
    const token = generation, c = current, draft = capture();
    const saved = await api('working-config/?country=' + c, {method:'PUT', body:{revision:workspaceRevision, config:draft}});
    if (generation !== token) return;
    workspaceRevision = saved.revision; drafts[c] = draft; dirty = false; message('美国当前配置已保存。');
  }
  async function loadPlans() {
    const token = generation, c = current;
    const plans = await api('plans/?country=' + c);
    if (token !== generation) return;
    $('marketPlans').innerHTML = plans.map(p => '<button type="button" class="button secondary" data-market-plan="' + escape(p.id) + '">' + escape(p.name + ' · v' + p.version + ' · ' + p.currency + ' ' + p.gross_profit) + '</button>').join('') || '<p>此国家尚无已保存方案。</p>';
  }
  function strategyOptions() {
    $('marketStrategy').innerHTML='<option value="">选择美国策略</option>'+strategies.map(x=>'<option value="'+escape(x.id)+'">'+escape(x.name)+'</option>').join('');
    if($('usStrategyChips'))$('usStrategyChips').innerHTML=strategies.map(x=>'<button type="button" class="profit-strategy-chip" data-us-strategy="'+escape(x.id)+'">'+escape(x.name)+'</button>').join('');
    document.querySelectorAll('[data-us-strategy]').forEach(button=>button.onclick=()=>{$('marketStrategy').value=button.dataset.usStrategy;$('marketActivateStrategy').click();});
  }
  async function loadMarket(c) {
    generation += 1; const token = generation;
    if (!['MY','US'].includes(c)) return;
    current = c; dirty = false; result = quote = rates = plan = displayedResult = null;
    $('profitMarketSwitch').value = c;
    $('module-profit').classList.toggle('market-active', c !== 'MY');
    $('marketProfitPanel').hidden = c === 'MY';
    if (c === 'MY') { document.querySelector('.profit-config-grid').prepend($('marketSelector')); return; }
    $('marketProfitPanel').querySelector('.profit-heading-copy').append($('marketSelector'));
    showView('calculator');
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
      message('美国配置已加载，请核对平台佣金与完整运费报价。');
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
    document.querySelector('.profit-config-grid').prepend($('marketSelector'));
    $('marketForm').innerHTML='<section class="panel profit-config-panel"><div class="panel-title profit-config-titlebar"><h2>计算配置</h2><div class="profit-config-actions"><button type="button" class="button secondary" id="usOpenStrategy">＋ 新建计算策略</button><button type="button" class="button secondary" id="usSaveDraft">保存当前配置</button></div></div><div id="usStrategyChips" class="profit-strategy-list"></div><div class="profit-config-grid" id="usConfigGrid">'+
      select('service','发货方式',config.fulfillment_services.filter(x=>x.enabled).map(x=>[x.code,x.label]))+
      select('store','店铺',[['','临时试算'],...config.stores.map(x=>[x.id,x.name])])+
      input('global_commission','平台佣金（手动确认，%）')+
      '<label class="us-settings-link">物流与税费<button type="button" class="button secondary" id="usOpenSettings">配置报价与费用</button></label></div>'+
      '<details class="us-advanced" id="usAdvanced"><summary>物流报价与税费设置</summary><p>保存配置后重复使用。费用必须按实际报价确认；商品包装资料在每行“设置”中填写。</p><div class="market-grid">'+
      input('seller_program','卖家项目／主体',{text:true,required:true})+input('origin','发货区域／邮编',{text:true,required:true})+input('destination','送达区域／邮编',{text:true,required:true})+
      input('quote_source','完整运费报价来源／日期',{text:true,required:true})+input('quote_minutes','报价有效分钟',{value:60,required:true})+select('payment_channel','运费支付方式',[['offline','线下支付'],['platform','平台代扣']])+
      input('commission_source','平台佣金依据',{text:true})+input('other_source','其他成本依据',{text:true})+input('tax_source','税费／代扣依据',{text:true})+
      input('buyer_shipping','买家支付运费（USD）',{value:0})+input('retained_shipping','其中商家保留运费（USD）',{value:0})+input('checkout_tax','平台代收销售税（不计收入）',{value:0})+
      input('subsidy','额外补贴（USD）',{value:0})+input('subsidy_source','补贴依据',{text:true})+
      '</div><input name="usd_rate" type="hidden" value="1"/><input name="product_tax" type="hidden" value="0"/><div class="market-checks">'+
      check('eligibility','服务与店铺资格已确认')+check('battery_accepted','报价支持本包裹电池属性')+check('surcharges','报价含全部附加费')+check('fees_confirmed','已核对费用与税务，填写0代表确认无此费用')+'</div></details></section>'+
      '<section class="panel profit-input-panel"><div class="panel-title"><div><h2>商品信息</h2><p>每行一个 SKU；填写重量、成本、售价与达人佣金，物流和特殊费用在本行设置中维护。</p></div></div><div class="profit-table-wrap"><table class="profit-input-table us-input-table"><thead><tr><th>SKU 名称</th><th>产品类目</th><th>包装重量</th><th>成本（CNY）</th><th>售价（USD）</th><th>达人佣金</th><th>实际广告数据（选填）</th><th>操作</th></tr></thead><tbody id="marketItems"></tbody></table></div><div class="us-input-footer"><button type="button" class="button secondary" id="marketAddItem">＋ 添加 SKU</button><button type="submit" class="button primary">计算利润</button></div></section>';
    // FX controls belong visually in the heading, but remain associated with
    // this form so draft capture and server inputs share the same values.
    $('usRateControls').innerHTML=input('cny_rate','1 USD = CNY',{required:true})+input('rate_source','汇率来源／日期',{text:true,required:true});
    $('usRateControls').querySelectorAll('input').forEach(e=>e.setAttribute('form','marketForm'));
    $('usConfigGrid').prepend($('marketSelector'));
    updateStoreCapabilities();
    $('usOpenSettings').onclick=()=>{$('usAdvanced').open=!$('usAdvanced').open;};
    $('usSaveDraft').onclick=()=>act(saveWorkspace);
    $('usOpenStrategy').onclick=()=>{document.querySelector('[data-side-link][data-profit-view="rules"]').click();$('usStrategySettings').open=true;$('usStrategySettings').scrollIntoView({block:'center'});$('marketStrategyName').focus();};
    field('store').onchange=()=>{const selected=(config.stores||[]).find(x=>x.id===value('store'));if(selected)field('seller_program').value=selected.seller_program||'';updateStoreCapabilities();for(const row of itemRows()){const p='item'+row.dataset.index+'_';if(value(p+'sku_id'))field(p+'sku_id').onchange();}};
    $('marketAddItem').onclick=()=>{const next=Math.max(-1,...itemRows().map(r=>Number(r.dataset.index)))+1;addItem(next);dirty=true;quote=null;invalidate();};
  }
  async function calculateForm(event) {
    event.preventDefault(); if (busy) return;
    const invalid=[...$('marketForm').elements].find(e=>e.willValidate&&!e.checkValidity());
    if(invalid){const row=invalid.closest('.us-detail-row');if(row)row.hidden=false;const details=invalid.closest('details');if(details)details.open=true;invalid.reportValidity();return;}
    busy = true; $('marketForm').inert = true; const token = generation;
    try {
      invalidate();
      const rateInput = {country:current, cny_per_base:value('cny_rate'), usd_per_base:value('usd_rate'), source:value('rate_source')};
      const same = rates && Number(rates.payload.cny_per_base) === Number(rateInput.cny_per_base) && Number(rates.payload.usd_per_base) === Number(rateInput.usd_per_base) && rates.payload.source === rateInput.source && Date.parse(rates.valid_until) > Date.now();
      if (!same) { const next = await api('exchange-rates/', {method:'POST',body:rateInput}); if (token !== generation) return; rates = next; }
      if (token !== generation) return;
      const data = payload();
      const lines = itemRows().map(row => ({package_id:'parcel-' + row.dataset.index, amount:value('item' + row.dataset.index + '_shipping')}));
      const quoteInput = {country:current,currency:currencies[current],store_id:data.store_id,seller_program:data.seller_program,fulfillment_service:data.fulfillment_service,
        packages:data.packages,lines:lines,source:value('quote_source'),origin:value('origin'),destination:value('destination'),
        payment_channel:value('payment_channel'),includes:data.fulfillment_service === 'platform_warehouse' ? ['last_mile','pick_pack','materials','surcharges'] : ['last_mile','surcharges'],
        eligibility_confirmed:field('eligibility').checked,battery_accepted:field('battery_accepted').checked,surcharges_confirmed:field('surcharges').checked,valid_for_minutes:Number(value('quote_minutes'))};
      const nextQuote = await api('shipping-quotes/',{method:'POST',body:quoteInput});
      if (token !== generation) return; quote = nextQuote;
      const calculated = await api('calculate/',{method:'POST',body:payload()});
      if (token !== generation) return;
      result = calculated; renderResult(result); $('marketSavePlan').disabled = result.calculation_status !== 'complete';
      message(result.calculation_status === 'complete' ? '计算完成，可保存到商品利润表。' : '请补齐所列参数后重新计算。');
    } catch (error) { if (token === generation) message(error.message + (error.data ? ' ' + JSON.stringify(error.data) : ''), true); }
    finally { busy = false; $('marketForm').inert = false; }
  }
  function init() {
    const host = document.createElement('div'); host.id='marketSelector'; host.className = 'market-selector';
    host.innerHTML = '<label>销售国家<select id="profitMarketSwitch"><option value="MY">马来西亚 MY</option><option value="US">美国 US</option></select></label>';
    $('profitCountry').closest('label').hidden=true;
    document.querySelector('.profit-config-grid').prepend(host);
    const panel = document.createElement('section'); panel.id = 'marketProfitPanel'; panel.hidden = true;
    panel.innerHTML='<section data-market-view="calculator"><div class="page-heading profit-heading"><div class="profit-heading-copy"><div class="profit-title-row"><h1>利润试算</h1><span class="profit-heading-context">TikTok Shop 美国站 · 3C 摄像头</span></div><p class="profit-heading-description">按商品逐项试算；运费和平台佣金使用已确认的实际配置。</p></div><section class="profit-rate-card us-rate-card"><span class="profit-rate-label">汇率（手动）</span><div id="usRateControls"></div><div class="profit-currency-toggle"><button type="button" class="active" data-us-currency="USD">美元 USD</button><button type="button" data-us-currency="CNY">人民币 CNY</button></div></section></div><p id="marketStatus" role="status"></p><form id="marketForm" hidden novalidate></form><section class="profit-results" id="marketResults" aria-live="polite"></section></section>'+
      '<section class="panel" data-market-view="plans" hidden><div class="panel-title"><h2>商品利润表 · 美国</h2></div><div class="us-plan-controls"><input id="marketPlanName" maxlength="120" placeholder="方案名称" aria-label="方案名称"/><button class="button primary" id="marketSavePlan" disabled>保存计算方案／新版本</button><button class="button secondary" id="marketNewPlan">另存为新方案</button></div><div id="marketPlans"></div></section>'+
      '<section class="panel" data-market-view="rules" hidden><div class="panel-title"><h2>规则与说明 · 美国</h2></div><div class="us-rules"><p>当前为人工费率与物流报价试算。3C 类目包含家用安防摄像头、监控套装和可视门铃；官方末级类目及完整承运商价表待核验。</p><p>采购成本和头程以人民币填写，当地运费与其他费用以美元填写。没有报价时保留空值，不把运费当作0。</p><p>平台销售税不计商品收入；税务代扣只影响回款，不重复扣利润。未填广告数据时只显示广告前毛利。</p><p>保本 ROI = 商品销售收入 ÷ 广告前毛利。切换显示币种只换算展示金额，不修改商品售价。</p><button type="button" class="button secondary" id="marketReload">重新加载配置</button><button type="button" class="button secondary" id="marketSaveWorkspace">保存当前配置</button><details id="usStrategySettings"><summary>维护计算策略</summary><div class="market-actions"><select id="marketStrategy" aria-label="美国策略"></select><input id="marketStrategyName" maxlength="120" placeholder="策略名称" aria-label="策略名称"/><button class="button secondary" id="marketSaveStrategy">另存策略</button><button class="button secondary" id="marketActivateStrategy">加载策略</button><button class="button secondary" id="marketDeleteStrategy">删除策略</button></div></details></div></section>';
    $('module-profit').append(panel);
    const confirm = document.createElement('dialog'); confirm.id = 'marketSwitchDialog'; confirm.className = 'account-lifecycle-dialog';
    confirm.innerHTML = '<h2>当前国家有未保存编辑</h2><p>保存当前配置后切换，或放弃本次编辑。两国金额分别保存。</p><div class="market-actions"><button id="marketSwitchSave" class="button primary">保存后切换</button><button id="marketSwitchDiscard" class="button secondary">放弃后切换</button><button id="marketSwitchCancel" class="button secondary">取消</button></div>'; document.body.append(confirm);
    root.addEventListener('dongbo-profit-view-change',e=>showView(e.detail));
    document.querySelectorAll('[data-us-currency]').forEach(button=>button.onclick=()=>{displayCurrency=button.dataset.usCurrency;document.querySelectorAll('[data-us-currency]').forEach(b=>b.classList.toggle('active',b===button));if(displayedResult)renderResult(displayedResult);});
    let target;
    $('profitMarketSwitch').onchange = function () { target = this.value; this.value = current; if (busy) return message('正在处理请求，请完成后再切换。',true); if (dirty && current !== 'MY') confirm.showModal(); else loadMarket(target); };
    $('marketSwitchSave').onclick = () => act(async () => { await saveWorkspace(); confirm.close(); loadMarket(target); });
    $('marketSwitchDiscard').onclick = () => { delete drafts[current]; confirm.close(); loadMarket(target); };
    $('marketSwitchCancel').onclick = () => confirm.close();
    $('marketForm').addEventListener('input', () => { dirty = true; quote = null; invalidate(); });
    $('marketForm').addEventListener('change', () => { dirty = true; quote = null; invalidate(); });
    $('marketForm').addEventListener('submit', calculateForm);
    $('usRateControls').addEventListener('input',()=>{dirty=true;rates=null;invalidate();});
    $('marketReload').onclick = () => { if (!dirty || root.confirm('重新加载会放弃未保存编辑，继续？')) loadMarket(current); };
    $('marketSaveWorkspace').onclick = () => act(saveWorkspace);
    $('marketSaveStrategy').onclick = () => act(async () => { await api('strategies/?country=' + current,{method:'POST',body:{name:$('marketStrategyName').value,config:strategyDraft()}}); strategies = await api('strategies/?country=' + current); strategyOptions(); message('本国策略已保存。'); });
    $('marketActivateStrategy').onclick = () => act(async () => { const s = strategies.find(s => s.id === $('marketStrategy').value); if (!s) throw new Error('请先选择策略'); if (dirty && !root.confirm('加载策略会替换当前编辑，继续？')) return; const w = await api('strategies/' + s.id + '/activate/?country=' + current,{method:'POST',body:{revision:s.revision,working_revision:workspaceRevision}}); workspaceRevision = w.revision; const merged=capture(); for(const [key,v] of Object.entries(w.config.values||{}))if(!key.startsWith('item'))merged.values[key]=v; apply(merged); await saveWorkspace(); quote = null; message('已加载美国策略，当前 SKU 输入已保留。'); });
    $('marketDeleteStrategy').onclick = () => act(async () => { const s = strategies.find(s => s.id === $('marketStrategy').value); if (!s || !root.confirm('删除策略“' + s.name + '”？已保存的利润版本保留。')) return; await api('strategies/' + s.id + '/?country=' + current,{method:'DELETE',body:{revision:s.revision}}); strategies = await api('strategies/?country=' + current); strategyOptions(); });
    $('marketNewPlan').onclick = () => { plan = null; message('下次保存将创建独立新方案。'); };
    $('marketSavePlan').onclick = () => act(async () => { if (!result) return; const body = {name:$('marketPlanName').value || '摄像头试算',input:payload(),ui_draft:capture(),expected_context_hash:result.context_hash}; if (plan) { body.plan_key = plan.plan_key; body.expected_version = plan.version; } plan = await api('plans/save/',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:body}); message('方案 v' + plan.version + ' 已保存，历史版本保留。'); await loadPlans(); });
    $('marketPlans').onclick = event => { const button = event.target.closest('[data-market-plan]'); if (button) act(async () => { const saved = await api('plans/' + button.dataset.marketPlan + '/?country=' + current); plan = saved; if (saved.payload.ui_draft) apply(saved.payload.ui_draft); $('marketPlanName').value = saved.name; renderResult(saved.payload.result); invalidateSavedResult(); message('已打开历史方案 v' + saved.version + '，修改后重新计算可保存新版本。'); }); };
  }
  function invalidateSavedResult() { result = null; $('marketSavePlan').disabled = true; if($('usSaveFromResult'))$('usSaveFromResult').disabled=true; }
  async function act(fn) { if (busy) return; busy = true; $('marketForm').inert = true; try { await fn(); } catch (error) { message(error.message + (error.data ? ' ' + JSON.stringify(error.data) : ''),true); } finally { busy = false; $('marketForm').inert = false; } }
  root.DongboMarketProfit = { mount(g) {
    gateway = g;
    const next = g && g.user ? String(g.user.id) : '';
    if (identity !== next) { identity = next; generation++; Object.keys(drafts).forEach(k => delete drafts[k]); current = 'MY'; dirty = false; result = quote = rates = plan = config = displayedResult = null; document.querySelector('.profit-config-grid').prepend($('marketSelector')); $('marketForm').replaceChildren(); $('marketResults').replaceChildren(); $('marketPlans').replaceChildren(); $('profitMarketSwitch').value = 'MY'; $('module-profit').classList.remove('market-active'); $('marketProfitPanel').hidden = true; }
  }};
  init();
})(globalThis);
