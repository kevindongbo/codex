(function (root) {
  'use strict';
  const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  const labels = { work: '上班', leave: '请假', out: '外出', rest: '休息', class: '有课', unknown: '待确认' };
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const addDays = (date, n) => new Date(Date.parse(date + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);
  const items = value => Array.isArray(value) ? value : value && value.results || [];
  const blankGrid = () => Array.from({ length: 7 }, () => Array.from({ length: 12 }, () => ({ status: 'unknown', course_name: '' })));
  function normalizeGrid(grid) { return Array.from({ length: 7 }, (_, d) => Array.from({ length: 12 }, (_, p) => Object.assign({ status: 'unknown', course_name: '' }, grid && grid[d] && grid[d][p] || {}))); }
  function knownGrid(grid) { return grid.length === 7 && grid.every(day => day.length === 12 && day.every(c => ['free', 'class'].includes(c.status))); }
  const s = { gateway: null, active: false, page: 'board', context: null, board: null, week: '', followCurrent: true, selectedDay: 0, filter: '', imports: [], evidence: [], draft: null, blob: '', busy: false, error: '', lastSync: '', scope: '', request: 0, dirty: false, keys: new Map() };
  let host;
  const api = (path, options) => { const identity = s.identity; return s.gateway.request('/scheduling/' + path, options).then(result => { if (identity !== s.identity) throw new Error('登录账号已变更，请刷新。'); return result; }); };
  function mutation(path, body, method) {
    const fingerprint = path + JSON.stringify(body);
    if (!s.keys.has(fingerprint)) s.keys.set(fingerprint, 'schedule:' + Array.from(root.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join(''));
    return api(path, { method: method || 'POST', body, headers: { 'Idempotency-Key': s.keys.get(fingerprint) } }).then(result => { s.keys.delete(fingerprint); return result; });
  }
  const admin = () => Boolean(s.context && s.context.user.is_superuser);
  const button = (action, text, extra) => '<button type="button" data-sc="' + action + '" ' + (extra || '') + '>' + text + '</button>';
  const option = (value, text, selected) => '<option value="' + esc(value) + '"' + (selected ? ' selected' : '') + '>' + esc(text) + '</option>';
  function releaseImage() { if (s.blob) URL.revokeObjectURL(s.blob); s.blob = ''; }
  async function run(task) {
    if (s.busy) return;
    if (!navigator.onLine) { s.error = '当前离线，只能查看最后同步的数据。编辑内容仍然保留，请恢复连接后重试。'; render(); return; }
    s.busy = true; s.error = ''; renderStatus();
    try { await task(); } catch (error) { s.error = error.status === 409 ? '版本已更新，未提交本次修改。请先重新读取最新版本再核对；当前编辑仍保留。' : error.message || '请求失败，请重试。'; }
    finally { s.busy = false; render(); }
  }
  async function context() {
    const result = await api('context/');
    s.context = result;
    const nav = document.getElementById('scheduleNav'); if (nav) nav.hidden = !result.enabled;
    if (!s.week || s.followCurrent) s.week = result.week_start;
    return result;
  }
  async function refresh() {
    await context();
    if (!s.context.enabled) return;
    if (s.page === 'board') s.board = await api('board/?week_start=' + encodeURIComponent(s.week));
    else {
      const suffix = '?owner=' + encodeURIComponent(s.scope || s.context.user.id);
      const loadPages = async path => { const rows = []; let page = 1; while (true) { const result = await api(path + '&page=' + page++); rows.push(...items(result)); if (!result.count || rows.length >= result.count || !items(result).length) return rows; } };
      const results = await Promise.all([loadPages('evidence/' + suffix), loadPages('imports/' + suffix)]);
      s.evidence = items(results[0]); s.imports = items(results[1]);
    }
    s.lastSync = new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai' });
  }
  function renderStatus() {
    if (!host) return;
    const el = host.querySelector('[data-sc-status]');
    if (el) el.textContent = s.busy ? '正在处理…' : s.error || (!navigator.onLine ? '离线 · ' : '') + (s.lastSync ? '最后同步 ' + s.lastSync : '');
    host.querySelectorAll('[data-sc-write]').forEach(el => { el.disabled = s.busy || !navigator.onLine; });
  }
  function render() {
    if (!host || !s.active) return;
    if (!s.gateway || !s.gateway.user) { host.innerHTML = '<div class="sc-empty">请先登录团队账号，再查看工作安排。</div>'; return; }
    if (!s.context) { host.innerHTML = '<div class="sc-empty">正在读取排班配置… ' + esc(s.error) + button('refresh', '重试') + '</div>'; return; }
    if (!s.context.enabled) { host.innerHTML = '<div class="sc-empty">团队排班尚未启用，请联系系统管理员。</div>'; return; }
    host.innerHTML = '<div class="sc-heading"><div><small>团队排班</small><h1>' + (s.page === 'board' ? '工作安排' : '原始凭证') + '</h1><p>' + (s.page === 'board' ? '按课程自动安排全部无课成员。请假和外出提交后立即生效。' : '原图永久保留；确认课表后自动生成所选周次的工作安排。') + '</p></div><div class="sc-actions">' + button('refresh', '刷新') + (admin() ? button('settings', '学期与识别设置') + button('participants', '参与人') : '') + '</div></div><p class="sc-status" data-sc-status role="status"></p>' + (s.page === 'board' ? boardHTML() : evidenceHTML());
    document.querySelectorAll('[data-schedule-page]').forEach(el => el.classList.toggle('active', el.dataset.schedulePage === s.page));
    renderStatus();
  }
  function memberHTML(m) { return '<span class="sc-member sc-' + esc(m.status) + '">' + esc(m.name) + (m.annotation ? ' · 人工调整' : '') + '</span>'; }
  function cellHTML(cell) {
    const members = (cell && cell.members || []).filter(m => !s.filter || String(m.user_id) === s.filter);
    const work = members.filter(m => m.status === 'work');
    const absent = members.filter(m => ['leave', 'out'].includes(m.status));
    const others = members.filter(m => ['rest', 'class', 'unknown'].includes(m.status));
    return '<strong>上班 ' + work.length + ' 人</strong><div class="sc-members">' + work.slice(0, 6).map(memberHTML).join('') + '</div>' + (work.length > 6 ? '<details><summary>查看全部 ' + work.length + ' 人</summary>' + work.map(memberHTML).join('') + '</details>' : '') + absent.map(m => '<div class="sc-absence">' + esc(m.name) + ' · ' + labels[m.status] + '</div>').join('') + (others.length ? '<details class="sc-other"><summary>其他 ' + others.length + ' 人</summary>' + others.map(m => '<div>' + esc(m.name) + ' · ' + labels[m.status] + '</div>').join('') + '</details>' : '');
  }
  function boardHTML() {
    const b = s.board; const terms = s.context.terms || [];
    const people = new Map(); if (b) b.cells.forEach(c => c.members.forEach(m => people.set(String(m.user_id), m.name)));
    const term = terms.find(t => s.week >= t.first_monday && s.week < addDays(t.first_monday, t.week_count * 7));
    const weekIndex = term ? Math.floor((Date.parse(s.week) - Date.parse(term.first_monday)) / 604800000) + 1 : 0;
    let html = '<div class="sc-toolbar">' + button('previous', '上一周') + '<strong>' + esc(s.week) + ' — ' + esc(addDays(s.week, 6)) + '</strong>' + button('next', '下一周') + button('today', '回到本周') + '<label>学期<select data-sc-change="term">' + option('', '选择学期', !term) + terms.map(t => option(t.id, t.name, term && term.id === t.id)).join('') + '</select></label>' + (term ? '<label>周次<select data-sc-change="week">' + Array.from({ length: term.week_count }, (_, i) => option(addDays(term.first_monday, i * 7), '第 ' + (i + 1) + ' 周', weekIndex === i + 1)).join('') + '</select></label>' : '') + '<label>成员<select data-sc-change="member">' + option('', '全部成员', !s.filter) + Array.from(people, ([id, name]) => option(id, name, s.filter === id)).join('') + '</select></label>' + button('mine', '仅看本人') + button('adjust', '请假 / 调整', 'data-sc-write') + button('weekend', '周末工作日', 'data-sc-write') + button('history', '我的修改记录') + '</div>';
    if (!term) html += '<p class="sc-notice">当前不在已配置学期，不会自动安排未提交成员。</p>';
    if (!b) return html + '<p>正在加载安排…</p>';
    html += '<p class="sc-legend">上班 · 请假 · 外出 · 休息 · 有课 · 待确认</p><p class="sc-notice">待提交：' + (b.pending.map(m => esc(m.name)).join('、') || '无') + '</p><div class="sc-day-tabs">' + b.days.map((d, i) => button('day', days[i] + '<small>' + d.slice(5) + '</small>', 'data-day="' + i + '" aria-pressed="' + (i === s.selectedDay) + '"')).join('') + '</div><div class="sc-board" role="table" aria-label="本周工作安排"><div class="sc-time sc-colhead" role="columnheader">节次 / 时间</div>' + b.days.map((d, i) => '<div class="sc-colhead sc-day-' + i + (d === s.context.business_date ? ' sc-today' : '') + '" role="columnheader">' + days[i] + '<small>' + d + '</small></div>').join('');
    (b.periods || s.context.periods).forEach(p => {
      html += '<div class="sc-time" role="rowheader"><strong>第 ' + p.number + ' 节</strong><small>' + esc(p.start) + '<br>' + esc(p.end) + '</small></div>';
      b.days.forEach((date, i) => { const cell = b.cells.find(c => c.date === date && c.period === p.number); html += '<div class="sc-cell sc-day-' + i + (i === s.selectedDay ? ' sc-selected-day' : '') + '" role="cell">' + cellHTML(cell) + '</div>'; });
    });
    return html + '</div>';
  }
  function termOptions(selected) { return (s.context.terms || []).map(t => option(t.id, t.name, t.id === selected)).join(''); }
  function weekChoices(term, selected) { return term ? '<div class="sc-weeks">' + Array.from({ length: term.week_count }, (_, i) => '<label><input type="checkbox" name="weeks" value="' + (i + 1) + '"' + (selected.includes(i + 1) ? ' checked' : '') + '>第' + (i + 1) + '周</label>').join('') + '</div>' : '<p>请先创建学期。</p>'; }
  function evidenceHTML() {
    const term = (s.context.terms || [])[0];
    return '<div class="sc-panel"><h2>上传原始课表</h2><form id="sc-upload"><label>原始截图（1—10张，每张≤10MB）<input name="images" type="file" accept="image/jpeg,image/png,image/webp" multiple required></label><label>学期<select name="term_id" data-sc-change="upload-term">' + termOptions(term && term.id) + '</select></label><label>周末工作日<select name="weekend_day"><option value="sat">周六（默认）</option><option value="sun">周日</option></select></label><div id="sc-upload-weeks">' + weekChoices(term, term ? [Math.max(1, Math.min(term.week_count, Math.floor((Date.parse(s.context.week_start) - Date.parse(term.first_monday)) / 604800000) + 1))] : []) + '</div>' + button('all-weeks', '选择全学期') + '<button type="submit" data-sc-write>上传并识别</button><p>每张图片建立独立凭证及草稿，重叠周次必须逐份明确确认替换。没有识别配置也可手工校对。</p></form></div>' + (admin() ? '<label>查看成员（留空为本人）<input data-sc-change="owner" value="' + esc(s.scope) + '" placeholder="成员用户ID"></label>' : '') + '<div class="sc-evidence-list">' + s.evidence.map(e => '<article class="sc-panel"><h3>' + esc(e.original_name) + '</h3><p>上传时间：' + esc(e.created_at) + ' · ' + esc(e.size) + ' 字节</p>' + button('image', '查看原图', 'data-id="' + esc(e.id) + '"') + s.imports.filter(i => i.evidence_id === e.id).map(i => '<div class="sc-import">第 ' + esc(i.selected_weeks.join('、')) + ' 周 · ' + esc(i.state) + ' · 版本 ' + i.revision + button('edit', i.state === 'draft' ? '校对 / 重试识别' : '查看课表', 'data-id="' + esc(i.id) + '"') + (i.state === 'draft' ? button('archive', '归档草稿', 'data-id="' + esc(i.id) + '" data-sc-write') : '') + '</div>').join('') + '</article>').join('') + (!s.evidence.length ? '<p class="sc-empty">暂无原始凭证，请上传你的课表。</p>' : '') + '</div>';
  }
  function dialog(title, content) {
    closeDialog();
    const el = document.createElement('dialog'); el.id = 'sc-dialog'; el.className = 'sc-dialog';
    el.innerHTML = '<div class="sc-dialog-heading"><h2>' + esc(title) + '</h2>' + button('close', '关闭') + '</div><p id="sc-dialog-error" role="alert"></p>' + content;
    document.body.appendChild(el); el.showModal(); el.addEventListener('click', click); el.addEventListener('change', change); el.addEventListener('submit', submit); el.addEventListener('cancel', e => { e.preventDefault(); closeDialog(); });
  }
  function closeDialog() { const el = document.getElementById('sc-dialog'); if (el) { el.close(); el.remove(); } releaseImage(); }
  async function showImage(id) { const identity = s.identity; releaseImage(); const blob = await s.gateway.privateScheduleImage(id); if (identity !== s.identity || !document.querySelector('#sc-image')) return; s.blob = URL.createObjectURL(blob); document.querySelector('#sc-image').src = s.blob; }
  async function editImport(id) {
    s.draft = await api('imports/' + encodeURIComponent(id) + '/'); s.draft.draft_grid = normalizeGrid(s.draft.draft_grid); s.dirty = false;
    editor(); await showImage(s.draft.evidence_id);
    document.querySelectorAll('#sc-editor-form [data-sc=grid]').forEach(el => { const day = Number(el.dataset.day), period = Number(el.dataset.period); el.title = s.draft.draft_grid[day][period].course_name || ''; });
    if (s.draft.job && s.draft.job.warnings) document.getElementById('sc-job-status').textContent = s.draft.job.warnings.join('；');
    if (s.draft.job && ['queued', 'processing'].includes(s.draft.job.status)) {
      watchJob(id, s.draft.job.id).catch(error => { const label = document.getElementById('sc-job-status'); if (label) label.textContent = error.message; });
    }
  }
  function editor() {
    const d = s.draft; const term = s.context.terms.find(t => t.id === d.term_id); const readonly = d.state !== 'draft';
    dialog('校对课表 · 版本 ' + d.revision, '<div class="sc-editor"><div><img id="sc-image" alt="上传的原始课表"><label>原图大小<input type="range" min="100" max="250" value="100" data-sc-change="zoom"></label></div><form id="sc-editor-form"><p>点击格子依次切换：待确认 → 无课 → 有课。必须检查全部七天，包括周末。</p><div class="sc-edit-grid"><span>节次</span>' + days.map(d => '<strong>' + d + '</strong>').join('') + Array.from({ length: 12 }, (_, p) => '<strong>' + (p + 1) + '</strong>' + days.map((_, day) => { const c = d.draft_grid[day][p]; return button('grid', { unknown: '?', free: '无课', class: '有课' }[c.status], 'class="sc-grid-' + c.status + '" data-day="' + day + '" data-period="' + p + '" aria-label="' + days[day] + '第' + (p + 1) + '节 ' + c.status + '"' + (readonly ? ' disabled' : '')); }).join('')).join('') + '</div>' + (!readonly ? button('free', '确认剩余待确认格均无课') + '<label>课程备注（选填，仅本人/管理员可见）<input name="course_note" maxlength="200" placeholder="点选有课格后可逐格标记；识别课程名保留"></label>' : '') + weekChoices(term, d.selected_weeks) + '<label>周末工作日<select name="weekend_day">' + option('sat', '周六', d.weekend_day === 'sat') + option('sun', '周日', d.weekend_day === 'sun') + '</select></label>' + (!readonly ? '<div class="sc-actions">' + button('recognize', '重新识别', 'data-sc-write') + button('save-draft', '保存草稿', 'data-sc-write') + button('publish', '确认并自动排班', 'data-sc-write') + button('reload-draft', '读取最新版本') + '</div>' : '<p>已确认版本只读。请上传新凭证创建新版本。</p>') + '<p id="sc-job-status" role="status"></p></form></div>');
  }
  function captureDraft() { const f = document.getElementById('sc-editor-form'); if (f) { s.draft.selected_weeks = Array.from(f.querySelectorAll('[name=weeks]:checked'), x => Number(x.value)); s.draft.weekend_day = f.elements.weekend_day.value; } }
  async function saveDraft() { captureDraft(); const d = s.draft; s.draft = await mutation('imports/' + d.id + '/', { revision: d.revision, draft_grid: d.draft_grid, selected_weeks: d.selected_weeks, weekend_day: d.weekend_day }, 'PATCH'); s.dirty = false; }
  async function recognize(id) {
    const result = await mutation('imports/' + id + '/recognize/', {});
    const jobId = result.job_id || result.id;
    if (!jobId) throw new Error(result.detail || '自动识别未配置，请手工校对。');
    return watchJob(id, jobId);
  }
  async function watchJob(id, jobId) {
    for (let attempt = 0; attempt < 90; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (!s.active || !document.getElementById('sc-editor-form') || !s.draft || s.draft.id !== id) return;
      const job = await api('jobs/' + jobId + '/');
      const label = document.getElementById('sc-job-status'); if (label) label.textContent = '识别状态：' + job.status;
      if (job.status === 'failed') throw new Error(job.sanitized_error || '识别失败，可重试或手工校对。');
      if (job.status === 'succeeded') { if (!s.dirty) await editImport(id); else if (label) label.textContent = '识别完成。你有未保存编辑，请保存后读取最新版本。'; return; }
    }
    throw new Error('识别仍在后台处理，可以稍后重新打开草稿。');
  }
  async function adjustmentDialog() {
    if (!s.board) return;
    const people = new Map([[String(s.context.user.id), '本人']]); s.board.cells.forEach(c => c.members.forEach(m => people.set(String(m.user_id), m.name)));
    dialog('请假 / 工作调整', '<form id="sc-adjust"><label>成员<select name="target_user">' + Array.from(people).filter(([id]) => admin() || id === String(s.context.user.id)).map(([id, name]) => option(id, name, id === String(s.context.user.id))).join('') + '</select></label><fieldset><legend>日期（可多选）</legend>' + s.board.days.map(d => '<label><input type="checkbox" name="dates" value="' + d + '">' + d + '</label>').join('') + '</fieldset><fieldset><legend>节次（整天则全选；本人仅修改尚未开始的节次）</legend>' + Array.from({ length: 12 }, (_, i) => '<label><input name="periods" type="checkbox" value="' + (i + 1) + '" checked>第' + (i + 1) + '节</label>').join('') + '</fieldset><label>状态<select name="status"><option value="leave">请假</option><option value="out">外出办事</option>' + (admin() ? '<option value="work">上班</option><option value="rest">休息</option>' : '') + '</select></label><label>原因 / 去向<textarea name="reason" maxlength="500"' + (!admin() ? ' required minlength="2"' : '') + '></textarea></label>' + (admin() ? '<label><input name="show_annotation" type="checkbox" checked>显示人工调整标注</label><label><input name="force" type="checkbox">明确允许覆盖有课或未确认课表的冲突</label>' : '') + '<p>原因仅本人及超级管理员可见。提交立即生效。</p><button type="submit" data-sc-write>确认提交</button></form>');
  }
  async function historyDialog() {
    const history = await api('history/'); const records = items(history.adjustments);
    dialog('我的修改记录', records.length ? records.map(r => '<article class="sc-panel"><strong>' + esc(r.date) + ' 第' + esc(r.period) + '节 · ' + esc(labels[r.status] || r.status) + '</strong><p>' + esc(r.reason) + '</p>' + (!r.revoked_at ? button('revoke', '撤销并恢复最新课表安排', 'data-id="' + esc(r.id) + '" data-revision="' + esc(r.revision) + '" data-sc-write') : '<p>已撤销</p>') + '</article>').join('') : '<p>暂无调整记录。</p>');
  }
  async function weekendDialog() {
    const plans = items(await api('plans/')); s.weekendPlans = plans;
    dialog('调整周末工作日', '<form id="sc-weekend"><p>仅重新计算未来时段，保留请假与管理员调整。</p>' + plans.map(p => '<label><input type="checkbox" name="plan" value="' + esc(p.week_start) + '">' + esc(p.week_start) + ' · ' + (p.weekend_day === 'sun' ? '周日' : '周六') + '</label>').join('') + '<label>工作日<select name="weekend_day"><option value="sat">周六</option><option value="sun">周日</option></select></label><button type="submit" data-sc-write>保存所选周</button></form>');
  }
  function settingsDialog() {
    dialog('学期设置', '<p>学期首周必须从周一开始；确认课表后起始日与时间模板锁定。</p>' + s.context.terms.map(t => '<p>' + esc(t.name) + ' · ' + t.first_monday + ' · ' + t.week_count + '周 ' + (t.locked_at ? '已锁定' : '') + '</p>').join('') + '<form id="sc-term"><label>学期名称<input name="name" required maxlength="100"></label><label>第一周周一<input name="first_monday" type="date" required></label><label>周数<input name="week_count" type="number" min="20" max="52" value="20" required></label><button type="submit" data-sc-write>创建学期</button></form><hr><form id="sc-provider"><label>课表视觉识别模型配置ID<input name="provider_id" placeholder="AI模型配置的UUID"></label><p>使用支持图片输入的已配置模型；未配置时允许手动校对。</p><button type="submit" data-sc-write>保存识别配置</button></form>');
  }
  async function dialogRun(task) { const el = document.getElementById('sc-dialog-error'); if (el) el.textContent = ''; try { await task(); } catch (e) { const target = document.getElementById('sc-dialog-error'); if (target) target.textContent = e.message || '操作失败，编辑已保留。'; else throw e; } }
  async function click(event) {
    const el = event.target.closest('[data-sc]'); if (!el) return;
    const action = el.dataset.sc;
    if (action === 'close') { closeDialog(); return; }
    if (action === 'grid') { captureDraft(); const c = s.draft.draft_grid[Number(el.dataset.day)][Number(el.dataset.period)]; c.status = { unknown: 'free', free: 'class', class: 'unknown' }[c.status]; const note = document.querySelector('[name=course_note]'); if (c.status === 'class' && note && note.value) c.course_name = note.value; s.dirty = true; el.textContent = { unknown: '?', free: '无课', class: '有课' }[c.status]; el.className = 'sc-grid-' + c.status; return; }
    if (action === 'free') { const count = s.draft.draft_grid.flat().filter(c => c.status === 'unknown').length; if (!root.confirm('确认剩余 ' + count + ' 个格子（包括周末待确认格）均无课？')) return; captureDraft(); s.draft.draft_grid.flat().forEach(c => { if (c.status === 'unknown') c.status = 'free'; }); s.dirty = true; editor(); await showImage(s.draft.evidence_id); return; }
    if (action === 'all-weeks') { host.querySelectorAll('[name=weeks]').forEach(e => { e.checked = true; }); return; }
    if (action === 'day') { s.selectedDay = Number(el.dataset.day); render(); return; }
    if (action === 'mine') { s.filter = String(s.context.user.id); render(); return; }
    if (action === 'settings') { settingsDialog(); return; }
    if (['save-draft', 'publish', 'recognize', 'reload-draft', 'revoke'].includes(action)) {
      return dialogRun(async () => {
        if (action === 'reload-draft') { if (!s.dirty || root.confirm('放弃未保存编辑并读取最新版本？')) await editImport(s.draft.id); }
        if (action === 'save-draft') { await saveDraft(); document.getElementById('sc-dialog-error').textContent = '草稿已保存。'; }
        if (action === 'publish') { captureDraft(); if (!knownGrid(s.draft.draft_grid)) throw new Error('请先确认全部84格，包括周末。'); await saveDraft(); const revisions = s.draft.expected_week_revisions || {}; const replacing = Object.values(revisions).some(v => v > 0); if (!root.confirm('将发布第 ' + s.draft.selected_weeks.join('、') + ' 周' + (replacing ? '，并替换这些周已有课表' : '') + '，保留请假和人工调整。确认？')) return; await mutation('imports/' + s.draft.id + '/confirm/', { revision: s.draft.revision, expected_week_revisions: revisions, replace_existing: replacing }); closeDialog(); await refresh(); render(); }
        if (action === 'recognize') { await saveDraft(); await recognize(s.draft.id); }
        if (action === 'revoke') { const reason = root.prompt('请填写撤销原因（至少2字）'); if (reason == null) return; await mutation('adjustments/' + el.dataset.id + '/revoke/', { reason, revision: Number(el.dataset.revision) }); await historyDialog(); await refresh(); render(); }
      });
    }
    return run(async () => {
      if (action === 'refresh') await refresh();
      if (['previous', 'next', 'today'].includes(action)) { s.followCurrent = action === 'today'; s.week = action === 'today' ? s.context.week_start : addDays(s.week, action === 'previous' ? -7 : 7); await refresh(); }
      if (action === 'image') { dialog('原始凭证', '<img id="sc-image" alt="上传的原始课表">'); await showImage(el.dataset.id); }
      if (action === 'edit') await editImport(el.dataset.id);
      if (action === 'archive') { if (root.confirm('归档此草稿？原始凭证仍然保留。')) { const current = await api('imports/' + el.dataset.id + '/'); await mutation('imports/' + el.dataset.id + '/archive/', { revision: current.revision }); await refresh(); } }
      if (action === 'adjust') await adjustmentDialog();
      if (action === 'history') await historyDialog();
      if (action === 'weekend') await weekendDialog();
      if (action === 'participants') { const members = items(await api('participants/')); s.participants = members; dialog('参与人管理', members.map(m => '<label><input data-sc-change="participant" data-id="' + esc(m.user_id || m.user) + '" type="checkbox"' + (m.active ? ' checked' : '') + '>' + esc(m.name || m.user_id || m.user) + '</label>').join('') || '<p>成员确认首份课表后自动成为参与人。</p>'); }
    });
  }
  async function change(event) {
    const el = event.target; const action = el.dataset.scChange;
    if (action === 'zoom') { document.getElementById('sc-image').style.width = el.value + '%'; return; }
    if (action === 'upload-term') { const term = s.context.terms.find(t => t.id === el.value); document.getElementById('sc-upload-weeks').innerHTML = weekChoices(term, [1]); return; }
    if (event.target.closest('#sc-editor-form')) s.dirty = true;
    if (action === 'member') { s.filter = el.value; render(); return; }
    if (action === 'participant') return dialogRun(() => mutation('participants/', { target_user: el.dataset.id, active: el.checked }, 'PATCH'));
    if (['term', 'week', 'owner'].includes(action)) return run(async () => { if (action === 'owner') s.scope = el.value.trim(); else { s.followCurrent = false; s.week = action === 'week' ? el.value : (s.context.terms.find(t => t.id === el.value) || {}).first_monday || s.week; } await refresh(); });
  }
  async function submit(event) {
    const f = event.target; if (!f.id.startsWith('sc-')) return; event.preventDefault();
    const submitTask = async () => {
      if (f.id === 'sc-upload') {
        const files = Array.from(f.elements.images.files); const weeks = Array.from(f.querySelectorAll('[name=weeks]:checked'), x => Number(x.value));
        if (!files.length || files.length > 10 || !weeks.length) throw new Error('请选择1—10张图片及至少一个适用周。');
        if (files.some(file => file.size > 10 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) throw new Error('仅支持不超过10MB的JPG、PNG、WebP图片。');
        let last; const warnings = [];
        for (const file of files) {
          const data = new FormData(); data.append('file', file);
          const uploaded = await api('evidence/', { method: 'POST', body: data });
          const evidence = items(uploaded)[0];
          if (!evidence) throw new Error('上传未返回凭证，请刷新后核对。');
          last = await mutation('imports/', { evidence_id: evidence.id, term_id: f.elements.term_id.value, selected_weeks: weeks, weekend_day: f.elements.weekend_day.value });
          try { await mutation('imports/' + last.id + '/recognize/', {}); } catch (e) { warnings.push(e.message); }
        }
        await refresh(); if (last) await editImport(last.id);
        if (warnings.length) document.getElementById('sc-dialog-error').textContent = '原图已保存。' + warnings.join('；') + ' 可直接手工校对。';
      }
      if (f.id === 'sc-term') { await mutation('terms/', { name: f.elements.name.value.trim(), first_monday: f.elements.first_monday.value, week_count: Number(f.elements.week_count.value), periods: s.context.periods }); await refresh(); settingsDialog(); render(); }
      if (f.id === 'sc-provider') { const terms = s.context.terms || []; if (!terms.length) throw new Error('请先创建学期。'); for (const term of terms) await mutation('terms/' + term.id + '/', { recognition_provider_id: f.elements.provider_id.value.trim() || null }, 'PATCH'); await context(); document.getElementById('sc-dialog-error').textContent = '所有学期的识别配置已保存。'; }
      if (f.id === 'sc-weekend') { const selected = Array.from(f.querySelectorAll('[name=plan]:checked'), e => e.value); if (!selected.length) throw new Error('请选择至少一周。'); const revisions = {}; s.weekendPlans.filter(p => selected.includes(p.week_start)).forEach(p => { revisions[p.week_start] = p.revision; }); await mutation('plans/weekend/', { week_starts: selected, weekend_day: f.elements.weekend_day.value, expected_revisions: revisions }); closeDialog(); await refresh(); render(); }
      if (f.id === 'sc-adjust') {
        const dates = Array.from(f.querySelectorAll('[name=dates]:checked'), e => e.value); const periods = Array.from(f.querySelectorAll('[name=periods]:checked'), e => Number(e.value));
        if (!dates.length || !periods.length) throw new Error('请选择日期和节次。');
        const target = f.elements.target_user.value; const revisions = {};
        s.board.cells.filter(c => dates.includes(c.date) && periods.includes(c.period)).forEach(c => { const m = c.members.find(m => String(m.user_id) === target); revisions[c.date + ':' + c.period] = m ? m.revision : 0; });
        await mutation('adjustments/', { target_user: target, dates, periods, status: f.elements.status.value, reason: f.elements.reason.value.trim(), show_annotation: admin() ? f.elements.show_annotation.checked : true, force: admin() && f.elements.force.checked, expected_revisions: revisions }); closeDialog(); await refresh(); render();
      }
    };
    if (f.closest('dialog')) await dialogRun(submitTask); else await run(submitTask);
  }
  async function poll() { if (!s.active || document.hidden || s.busy || !s.context || !navigator.onLine) return; try { const revision = s.context.revision; const week = s.week; await context(); if (revision !== s.context.revision || week !== s.week) { await refresh(); render(); } } catch (_) { /* Last good board remains visible. */ } }
  function mount(gateway, active) {
    host = document.getElementById('schedulingRoot'); if (!host) return;
    s.gateway = gateway; s.active = active;
    const identity = gateway && gateway.user ? gateway.organizationId + ':' + gateway.user.id : '';
    if (s.identity !== identity) { s.identity = identity; s.context = null; s.board = null; s.imports = []; s.evidence = []; s.week = ''; s.filter = ''; s.scope = ''; s.draft = null; s.keys.clear(); const nav = document.getElementById('scheduleNav'); if (nav) nav.hidden = true; closeDialog(); if (identity) run(async () => { await refresh(); }); }
    if (active) render();
  }
  if (typeof document !== 'undefined') {
    document.addEventListener('click', event => {
      const page = event.target.closest('[data-schedule-page]'); if (page) { s.page = page.dataset.schedulePage; run(refresh); return; }
      if (event.target.closest('#schedulingRoot')) click(event);
    });
    document.addEventListener('change', event => { if (event.target.closest('#schedulingRoot')) change(event); });
    document.addEventListener('submit', event => { if (event.target.closest('#schedulingRoot')) submit(event); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    root.addEventListener('online', poll); root.addEventListener('offline', renderStatus); root.setInterval(poll, 30000);
  }
  root.DongboScheduling = { mount, normalizeGrid, knownGrid, blankGrid, addDays, escapeHtml: esc };
})(globalThis);
