// =====================================================================
// Obsidian KB Reader —— 前端交互 (v10)
// 新增:主题切换 / 汉堡抽屉 / Modal / Toast / 骨架屏 / 仪表盘标签页
// 重构:confirm/alert → Modal/Toast;卡片按钮加 aria-label
// =====================================================================

// HTML 转义,防注入
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// 可选日期字段的渐进增强:
// 原生 <input type="date"> 的占位符(yyyy/mm/dd 等)由浏览器/系统语言决定,代码改不了,
// 而且空值时长得不一致。这里用「text + placeholder ↔ date 控件」切换:
//   - 空值时显示为 text,露出自定义 placeholder(如 2026-08-15,与后端 ISO 格式一致)
//   - 聚焦时切回 date 控件,弹出原生日期选择器(保留便捷选择能力)
//   - 选完/有值后保持 date 控件;清空后失焦切回 text 重新显示 placeholder
// 只用于「可选」日期字段(任务 deadline);必填日期(事件/market)默认有值,无需此处理。
window.KBDate = {
  onFocus: function (el) { if (!el.value) el.type = 'date'; },
  onBlur: function (el) { if (!el.value) el.type = 'text'; },
};

/* ====================== 行情缓存(localStorage) ======================
 * 行情/资金流/详情数据是只读的临时数据,不进 Markdown 数据层(符合 AGENTS.md
 * 的「纯 UI 状态可存 localStorage」)。用途:刷新页面/重开浏览器时先秒显示上次
 * 数据(标注更新时间),再后台拉最新 —— 避免每次刷新空白等几十秒。
 * 失败兜底:拉取失败时若有过期缓存,继续显示缓存 + 提示「网络异常,显示上次数据」。
 * 用 try/catch 包裹(localStorage 可能被隐私模式禁用 / 超额)。
 */
var KB_QUOTE_CACHE = (function(){
  var PREFIX = 'kbqc:';          // 行情缓存键前缀,与 kb-theme 区分
  var MAX_AGE_MS = 1000 * 60 * 60 * 6;  // 6 小时:超过则视为过期(但仍可用于兜底显示)
  function _k(key){ return PREFIX + key; }
  return {
    // 读缓存。返回 {data, age_label, fresh} 或 null(无缓存)。
    // fresh=true 表示在有效期内,可放心显示。
    get: function(key){
      try{
        var raw = localStorage.getItem(_k(key));
        if(!raw) return null;
        var obj = JSON.parse(raw);
        var age = Date.now() - (obj._t || 0);
        return {
          data: obj.data,
          fresh: age < MAX_AGE_MS,
          age_label: _ageLabel(age)
        };
      }catch(e){ return null; }
    },
    // 写缓存。data 是任意可序列化对象。
    set: function(key, data){
      try{
        localStorage.setItem(_k(key), JSON.stringify({data: data, _t: Date.now()}));
      }catch(e){ /* 配额满或被禁用,静默忽略 */ }
    },
    // 清除指定 key
    clear: function(key){
      try{ localStorage.removeItem(_k(key)); }catch(e){}
    }
  };
  function _ageLabel(age){
    var min = Math.floor(age / 60000);
    if(min < 1) return '刚刚';
    if(min < 60) return min + '分钟前';
    var hr = Math.floor(min / 60);
    if(hr < 24) return hr + '小时前';
    return Math.floor(hr / 24) + '天前';
  }
})();


/* ====================== 主题 ====================== */
function applyTheme(theme) {
  if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
  else document.documentElement.removeAttribute('data-theme');
  const btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'dark' ? '#030014' : '#f7f8fa');
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('kb-theme'); } catch (e) {}
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  // 默认采用深色玻璃拟态(匹配 Ardot 工作台设计);已保存的用户选择优先。
  applyTheme(saved || 'dark');
  const btn = document.getElementById('themeToggle');
  if (btn) btn.addEventListener('click', function () {
    const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = cur === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('kb-theme', next); } catch (e) {}
    applyTheme(next);
  });
}

/* ====================== 侧栏收起/展开 ====================== */
// 状态用 html[data-sidebar-collapsed="1"] 标记(base.html 顶部防闪脚本已据此提前应用,
// 避免刷新时侧栏先展开再缩回)。状态持久化到 localStorage('kb-sidebar-collapsed')。
function applySidebarCollapsed(collapsed) {
  if (collapsed) document.documentElement.setAttribute('data-sidebar-collapsed', '1');
  else document.documentElement.removeAttribute('data-sidebar-collapsed');
  // 切换按钮图标:展开态显示 panel-left-close(点击收起);收起态显示 panel-left-open(点击展开)
  const btn = document.getElementById('sidebarCollapse');
  if (btn) {
    const icon = collapsed ? 'panel-left-open' : 'panel-left-close';
    btn.innerHTML = '<i data-lucide="' + icon + '"></i>';
    btn.title = collapsed ? '展开侧栏' : '收起侧栏';
    btn.setAttribute('aria-label', collapsed ? '展开侧栏' : '收起侧栏');
    if (window.refreshIcons) window.refreshIcons();
  }
}

function initSidebarCollapse() {
  // 从 localStorage 恢复(防闪脚本已提前应用属性,这里只同步按钮图标)
  let collapsed = false;
  try { collapsed = localStorage.getItem('kb-sidebar-collapsed') === '1'; } catch (e) {}
  applySidebarCollapsed(collapsed);
  const btn = document.getElementById('sidebarCollapse');
  if (btn) btn.addEventListener('click', function () {
    const next = document.documentElement.getAttribute('data-sidebar-collapsed') === '1' ? false : true;
    try { localStorage.setItem('kb-sidebar-collapsed', next ? '1' : '0'); } catch (e) {}
    applySidebarCollapsed(next);
  });
}

/* ====================== 会话状态持久化(返回时恢复) ====================== */
// 用 sessionStorage:关闭标签页即清空,不污染下次打开,贴合「返回时恢复」的语义。
// 用于:仪表盘标签页 / 搜索筛选 / 收藏夹选中文件夹 / 各列表页滚动位置。
const KBState = {
  get(key, fallback) {
    try {
      const v = sessionStorage.getItem(key);
      return v == null ? fallback : JSON.parse(v);
    } catch (e) { return fallback; }
  },
  set(key, val) {
    try { sessionStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
  },
  del(key) { try { sessionStorage.removeItem(key); } catch (e) {} },
};

// 各列表页 → 滚动位置存储 key
const SCROLL_KEYS = {
  '/': 'kb-scroll-index',
  '/search': 'kb-scroll-search',
  '/articles': 'kb-scroll-articles',
  '/recent': 'kb-scroll-recent',
  '/favorites': 'kb-scroll-favorites',
};

// 记录当前列表页的滚动位置(节流,避免高频写 sessionStorage)
let _scrollSaveTimer = null;
function _onListScroll() {
  const key = SCROLL_KEYS[window.location.pathname];
  if (!key) return;
  if (_scrollSaveTimer) return;
  _scrollSaveTimer = setTimeout(function () {
    _scrollSaveTimer = null;
    KBState.set(key, window.scrollY || 0);
  }, 150);
}
window.addEventListener('scroll', _onListScroll, { passive: true });

// 在列表页数据渲染完成后调用:恢复上次离开时的滚动位置
// rAF 双帧,确保 DOM 已撑开高度再滚,避免 scrollTo 无效。
function restoreScroll() {
  const key = SCROLL_KEYS[window.location.pathname];
  if (!key) return;
  const y = KBState.get(key, 0);
  if (!y) return;
  requestAnimationFrame(function () {
    requestAnimationFrame(function () { window.scrollTo(0, y); });
  });
}

/* ====================== 汉堡抽屉导航 ====================== */
function initNav() {
  const toggle = document.getElementById('navToggle');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('navOverlay');
  const closeBtn = document.getElementById('navClose');
  if (!toggle || !sidebar) return;
  function open() {
    sidebar.classList.add('open');
    overlay.classList.add('open');
    overlay.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  }
  function close() {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
    overlay.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  }
  toggle.addEventListener('click', function () {
    sidebar.classList.contains('open') ? close() : open();
  });
  if (closeBtn) closeBtn.addEventListener('click', close);
  overlay.addEventListener('click', close);
  sidebar.querySelectorAll('a').forEach(a => a.addEventListener('click', close));
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
}

/* ====================== Modal ====================== */
let _modalResolve = null;
function _modalEsc(e) { if (e.key === 'Escape') closeModal(false); }

function openModal(opts) {
  return new Promise(function (resolve) {
    _modalResolve = resolve;
    const overlay = document.getElementById('modalOverlay');
    const box = document.getElementById('modalBox');
    document.getElementById('modalTitle').textContent = opts.title || '请确认';
    document.getElementById('modalBody').textContent = opts.body || '';
    box.classList.toggle('modal--danger', !!opts.danger);
    const actions = document.getElementById('modalActions');
    actions.innerHTML = '';
    if (opts.cancelText) {
      const c = document.createElement('button');
      c.className = 'btn btn-ghost';
      c.textContent = opts.cancelText;
      c.onclick = function () { closeModal(false); };
      actions.appendChild(c);
    }
    const ok = document.createElement('button');
    ok.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
    ok.textContent = opts.confirmText || '确定';
    ok.onclick = function () { closeModal(true); };
    actions.appendChild(ok);
    overlay.hidden = false;
    document.addEventListener('keydown', _modalEsc);
    setTimeout(function () { ok.focus(); }, 30);
  });
}

function closeModal(val) {
  const overlay = document.getElementById('modalOverlay');
  if (overlay) overlay.hidden = true;
  document.removeEventListener('keydown', _modalEsc);
  if (_modalResolve) { _modalResolve(val); _modalResolve = null; }
}

// 返回 Promise<boolean>
function confirmModal(message, opts) {
  opts = opts || {};
  return openModal({
    title: opts.title || '请确认',
    body: message,
    confirmText: opts.confirmText || '确定',
    cancelText: opts.cancelText || '取消',
    danger: !!opts.danger,
  });
}

// 返回 Promise<string|null>:确定返回输入文本,取消/关闭返回 null
function promptModal(title, hint, initialValue) {
  return new Promise(function (resolve) {
    const overlay = document.getElementById('modalOverlay');
    const box = document.getElementById('modalBox');
    if (!overlay || !box) { resolve(null); return; }
    document.getElementById('modalTitle').textContent = title || '请输入';
    box.classList.remove('modal--danger');
    const body = document.getElementById('modalBody');
    const actions = document.getElementById('modalActions');
    body.innerHTML = '';
    actions.innerHTML = '';
    const hintEl = document.createElement('div');
    hintEl.className = 'modal-prompt-hint muted';
    hintEl.textContent = hint || '';
    body.appendChild(hintEl);
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'modal-prompt-input';
    input.value = initialValue || '';
    input.maxLength = 40;
    body.appendChild(input);
    const c = document.createElement('button');
    c.className = 'btn btn-ghost';
    c.textContent = '取消';
    c.onclick = function () { overlay.hidden = true; resolve(null); };
    const ok = document.createElement('button');
    ok.className = 'btn btn-primary';
    ok.textContent = '确定';
    ok.onclick = function () { overlay.hidden = true; resolve(input.value); };
    actions.appendChild(c);
    actions.appendChild(ok);
    overlay.hidden = false;
    setTimeout(function () { input.focus(); input.select(); }, 30);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { overlay.hidden = true; resolve(input.value); }
      if (e.key === 'Escape') { overlay.hidden = true; resolve(null); }
    });
  });
}

// 点击遮罩关闭(视为取消)
function initModalOverlay() {
  const overlay = document.getElementById('modalOverlay');
  if (!overlay) return;
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeModal(false);
  });
}

/* ====================== Toast ====================== */
function toast(message, type, duration) {
  type = type || 'info';
  duration = duration || 3500;
  const wrap = document.getElementById('toastWrap');
  if (!wrap) { console.log('[toast]', message); return; }
  const el = document.createElement('div');
  el.className = 'toast toast--' + type;
  el.textContent = message;
  wrap.appendChild(el);
  setTimeout(function () {
    el.style.transition = 'opacity .3s';
    el.style.opacity = '0';
    setTimeout(function () { el.remove(); }, 320);
  }, duration);
}

/* ====================== 文章卡片 + 稍后读/收藏 ====================== */
// 卡片内只保留「来源 tag」,其余(领域/无summary/关键词 tag)不进入卡片,避免视觉杂乱。
function renderArticleCard(item) {
  const rl = item.read_later;
  const fav = item.is_favorite;
  const readInfo = item.read_count > 0
    ? `<span class="read-info">读过 ${item.read_count} 次${item.last_read_at ? ' · ' + String(item.last_read_at).slice(0, 10) : ''}</span>`
    : '';
  const sid = escapeHtml(item.source_id);
  return `
    <div class="card summary-card article-card" id="article-${sid}">
      <div class="card-top">
        <label class="card-select">
          <input type="checkbox" class="card-checkbox" data-sid="${sid}" aria-label="选择文章"
            data-action="toggle-select"${selectedIds.has(sid) ? ' checked' : ''}>
        </label>
        <span class="tag tag-${item.source_type}">${item.source_type}</span>
      </div>
      <a class="card-link" href="/summary/${encodeURIComponent(item.source_id)}" target="_blank" rel="noopener">
        <h3 class="card-title">${escapeHtml(item.title)}</h3>
        <p class="card-excerpt">${item.excerpt ? escapeHtml(item.excerpt) : '<span class="muted">(无摘要)</span>'}</p>
        <div class="card-footer">
          <span>${item.summarized_at || item.created_at || ''}</span>
          ${readInfo}
        </div>
      </a>
      <div class="card-actions">
        <button class="icon-btn ${rl ? 'active-rl' : ''}" title="稍后阅读" aria-label="稍后阅读"
          data-action="toggle-read-later" data-sid="${sid}"><i data-lucide="bookmark"></i></button>
        <button class="icon-btn ${fav ? 'active-fav' : ''}" title="收藏" aria-label="收藏"
          data-action="toggle-favorite" data-sid="${sid}"><i data-lucide="star"></i></button>
        <button class="icon-btn icon-btn-danger" title="删除" aria-label="删除文章"
          data-action="delete-article" data-sid="${sid}"><i data-lucide="trash-2"></i></button>
      </div>
    </div>
  `;
}

function renderArticleRow(item) {
  const rl = item.read_later;
  const fav = item.is_favorite;
  const sid = escapeHtml(item.source_id);
  const date = item.summarized_at || item.created_at || '';
  const readInfo = item.read_count > 0
    ? (item.last_read_at ? String(item.last_read_at).slice(0, 10) + ' · 读 ' + item.read_count + ' 次' : '读 ' + item.read_count + ' 次')
    : '';
  const excerpt = item.excerpt ? escapeHtml(item.excerpt) : '<span class="muted">(无摘要)</span>';
  return `
    <div class="row-item" id="article-${sid}">
      <label class="row-select">
        <input type="checkbox" class="card-checkbox" data-sid="${sid}" aria-label="选择文章"
          data-action="toggle-select"${selectedIds.has(sid) ? ' checked' : ''}>
      </label>
      <span class="tag tag-${escapeHtml(item.source_type)}">${escapeHtml(item.source_type)}</span>
      <a class="row-main" href="/summary/${encodeURIComponent(item.source_id)}" target="_blank" rel="noopener">
        <span class="row-title">${escapeHtml(item.title)}</span>
        <span class="row-excerpt">${excerpt}</span>
      </a>
      <span class="row-meta">${date}${readInfo ? ' · ' + readInfo : ''}</span>
      <div class="row-actions">
        <button class="icon-btn ${rl ? 'active-rl' : ''}" title="稍后阅读" aria-label="稍后阅读"
          data-action="toggle-read-later" data-sid="${sid}"><i data-lucide="bookmark"></i></button>
        <button class="icon-btn ${fav ? 'active-fav' : ''}" title="收藏" aria-label="收藏"
          data-action="toggle-favorite" data-sid="${sid}"><i data-lucide="star"></i></button>
        <button class="icon-btn icon-btn-danger" title="删除" aria-label="删除文章"
          data-action="delete-article" data-sid="${sid}"><i data-lucide="trash-2"></i></button>
      </div>
    </div>
  `;
}

function refreshCurrentPage() {
  if (typeof initDashboard === 'function' && document.getElementById('stats-overview')) initDashboard();
  else if (typeof loadRecent === 'function') loadRecent();
  else if (typeof loadFavorites === 'function') loadFavorites();
  else if (typeof loadArticles === 'function') loadArticles();
  else if (typeof loadSearch === 'function') loadSearch();
  else if (typeof doSearch === 'function') doSearch();
}

/* ====================== 批量选择 ====================== */
const selectedIds = new Set();
let batchMode = false;  // 是否处于批量选择模式(控制 checkbox 显隐)

function toggleSelect(checkbox, sid) {
  if (checkbox.checked) selectedIds.add(sid);
  else selectedIds.delete(sid);
  updateBatchBar();
}

function updateBatchBar() {
  const bar = document.getElementById('batch-bar');
  if (!bar) return;
  // 仅在批量选择模式下显示操作栏;无选中时隐藏操作栏但仍保持模式
  if (batchMode && selectedIds.size > 0) {
    bar.style.display = 'flex';
    document.getElementById('batch-count').textContent = selectedIds.size;
  } else {
    bar.style.display = 'none';
  }
}

function clearSelection() {
  selectedIds.clear();
  document.querySelectorAll('.card-checkbox').forEach(cb => cb.checked = false);
  updateBatchBar();
}

/* 批量选择模式开关:进入 → 显示 checkbox + 操作栏;退出 → 隐藏并清空 */
function enterBatchMode() {
  batchMode = true;
  document.querySelectorAll('.card-grid').forEach(g => g.classList.add('selectable'));
  updateBatchBtn();
  refreshIcons();
}

function exitBatchMode() {
  batchMode = false;
  document.querySelectorAll('.card-grid').forEach(g => g.classList.remove('selectable'));
  clearSelection();
  const bar = document.getElementById('batch-bar');
  if (bar) bar.style.display = 'none';
  updateBatchBtn();
  refreshIcons();
}

function toggleBatchMode() {
  if (batchMode) exitBatchMode();
  else enterBatchMode();
}

function updateBatchBtn() {
  const btn = document.getElementById('kb-batch-toggle');
  if (!btn) return;
  if (batchMode) {
    btn.innerHTML = '<i data-lucide="x"></i> 退出选择';
    btn.classList.add('btn-primary');
    btn.setAttribute('title', '退出批量选择模式');
  } else {
    btn.innerHTML = '<i data-lucide="check-square"></i> 批量选择';
    btn.classList.remove('btn-primary');
    btn.setAttribute('title', '进入批量选择模式');
  }
}

async function batchAction(action) {
  const ids = Array.from(selectedIds);
  if (ids.length === 0) return;

  if (action === 'delete') {
    if (!await confirmModal(`确认删除 ${ids.length} 篇文章?\n将删除 source note、summary、原文与关联候选,不可恢复。`, { title: '删除文章', danger: true, confirmText: '确认删除' })) return;
    if (!await confirmModal('再次确认:真的要删除吗?此操作不可撤销。', { title: '最后确认', danger: true, confirmText: '仍然删除' })) return;
  } else if (action === 'archive') {
    if (!await confirmModal(`归档 ${ids.length} 篇文章?`)) return;
  } else {
    if (!await confirmModal(`对 ${ids.length} 篇文章执行「${action}」?`)) return;
  }

  let tags = [];
  if (action === 'add_tags') {
    const input = prompt('输入标签(逗号分隔):');
    if (!input) return;
    tags = input.split(',').map(t => t.trim()).filter(t => t);
    if (tags.length === 0) return;
  }

  const bar = document.getElementById('batch-bar');
  if (bar) bar.style.opacity = '0.5';

  try {
    const body = { source_ids: ids, action: action };
    if (tags.length > 0) body.tags = tags;
    const res = await fetch('/api/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      toast('操作失败:' + (data.detail || ''), 'error');
      return;
    }
    let msg = '成功 ' + data.success + ' 篇';
    let type = 'success';
    if (data.skipped > 0) msg += ',跳过 ' + data.skipped + ' 篇';
    if (data.failed > 0) {
      msg += ',失败 ' + data.failed + ' 篇';
      type = 'error';
    }
    toast(msg, type);
    clearSelection();
    refreshCurrentPage();
  } catch (e) {
    toast('网络错误:' + e.message, 'error');
  } finally {
    if (bar) bar.style.opacity = '1';
  }
}

/* ====================== 删除 / 阅读状态 ====================== */
async function deleteArticle(sourceId) {
  if (!await confirmModal('确认彻底删除?\n将删除 source note、summary、raw_text 和相关候选,不可恢复。', { title: '删除文章', danger: true, confirmText: '确认删除' })) return;
  if (!await confirmModal('再次确认:真的要删除这篇文章吗?此操作不可撤销。', { title: '最后确认', danger: true, confirmText: '仍然删除' })) return;
  try {
    const res = await fetch(`/api/article/${sourceId}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) { toast('删除失败:' + (data.detail || ''), 'error'); return; }
    if (window.location.pathname.startsWith('/summary/')) {
      window.location.href = '/';
    } else {
      refreshCurrentPage();
    }
  } catch (e) { toast('网络错误:' + e.message, 'error'); }
}

async function toggleReadLater(sourceId) {
  try {
    const res = await fetch(`/api/article/${sourceId}/read-later`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { toast('操作失败:' + (data.detail || ''), 'error'); return; }
    if (document.querySelector('.detail-action-btn')) updateDetailButtons('read_later', data.read_later);
    else refreshCurrentPage();
  } catch (e) { toast('网络错误:' + e.message, 'error'); }
}

async function toggleFavorite(sourceId) {
  try {
    const res = await fetch(`/api/article/${sourceId}/favorite`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { toast('操作失败:' + (data.detail || ''), 'error'); return; }
    // 详情页(detail-action-btn)就地更新按钮;其余页面(KB/收藏夹/最近阅读等)刷新当前列表,
    // 这样收藏夹页点取消收藏后,文章会从列表移除。
    if (document.querySelector('.detail-action-btn')) updateDetailButtons('is_favorite', data.is_favorite);
    else refreshCurrentPage();
  } catch (e) { toast('网络错误:' + e.message, 'error'); }
}

function updateDetailButtons(field, value) {
  const btn = document.querySelector(`.detail-action-btn[data-field="${field}"]`);
  if (!btn) return;
  btn.classList.toggle('active-rl', field === 'read_later' && value);
  btn.classList.toggle('active-fav', field === 'is_favorite' && value);
  if (field === 'read_later') btn.innerHTML = (value ? '<i data-lucide="bookmark-check"></i> 已加入稍后读' : '<i data-lucide="bookmark"></i> 稍后阅读');
  if (field === 'is_favorite') btn.innerHTML = (value ? '<i data-lucide="star"></i> 已收藏' : '<i data-lucide="star"></i> 收藏');
  if (window.refreshIcons) window.refreshIcons();
}

/* ====================== idea/plan 审阅 ====================== */
function statusBadgeClass(status) {
  if (!status) return 'status-pending_review';
  return 'status-' + status;
}
function statusLabel(status) {
  const map = {
    'pending_review': '待审核',
    'accepted_research': '已接受·科研',
    'accepted_productivity': '已接受·效率',
    'accepted': '已接受',
    'moved': '已移动',
    'rejected': '已拒绝',
    'archived': '已归档',
  };
  return map[status] || status;
}

async function loadSuggestions(type) {
  const gridId = type + '-grid';
  const grid = document.getElementById(gridId);
  if (!grid) return;
  try {
    const res = await fetch(`/api/${type}s`);
    const data = await res.json();
    // 待定列表只显示 pending_review;已接受/已移动/已拒绝的不再留在这里
    const items = (data.items || []).filter(it => it.status === 'pending_review');
    if (items.length === 0) {
      grid.innerHTML = `<div class="empty">还没有 ${type} 候选。运行 <code>python scripts/kb.py extract-suggestions</code> 抽取。</div>`;
      return;
    }
    grid.innerHTML = items.map(item => renderSuggestionCard(item, type)).join('');
  } catch (e) {
    grid.innerHTML = `<div class="error">加载失败:${escapeHtml(e.message)}</div>`;
  }
}

function renderSuggestionCard(item, type) {
  const status = item.status;
  const sid = escapeHtml(item.id);

  // 待定列表只承载 pending_review 卡片,接受/拒绝后即从列表移除(loadSuggestions 已过滤)
  let actions = '';
  if (type === 'idea') {
    // v0.4.11: idea 简化为单一接受(统一进 general 清单)+ 拒绝
    actions = `
      <button class="btn btn-accept" data-action="update-status" data-kind="idea" data-sid="${sid}" data-status="accepted_general">接受</button>
      <button class="btn btn-ghost" data-action="update-status" data-kind="idea" data-sid="${sid}" data-status="rejected">拒绝</button>
    `;
  } else {
    // v0.4.12: plan 简化为接受 / 拒绝;接受弹窗可选填截止日期,按日期自动归类去向
    actions = `
      <button class="btn btn-accept" data-action="accept-plan" data-sid="${sid}">接受</button>
      <button class="btn btn-ghost" data-action="update-status" data-kind="plan" data-sid="${sid}" data-status="rejected">拒绝</button>
    `;
  }

  // v0.4.13: idea 和 plan 卡片都只留标题,不再显示正文
  const bodyHtml = '';

  return `
    <div class="card suggestion-card" id="card-${escapeHtml(item.id)}">
      <div class="card-header">
        <span class="status-badge ${statusBadgeClass(status)}">${statusLabel(status)}</span>
      </div>
      <h3 class="card-title">${escapeHtml(item.title || item.id)}</h3>
      ${bodyHtml}
      <div class="action-row">${actions}</div>
    </div>
  `;
}

function formatSuggestionBody(body, type) {
  let text = body;
  // v0.4.12: plan 过滤掉「主要难点」「验收标准」两节(连同其正文),只保留其它小节
  if (type === 'plan') {
    const DROP = ['主要难点', '验收标准'];
    const parts = text.split(/^###\s+/m);   // [前导文本, "标题\n正文", ...]
    text = parts.map(function (part, idx) {
      if (idx === 0) return part;            // heading 之前的导言,保留
      const nl = part.indexOf('\n');
      const heading = (nl === -1 ? part : part.slice(0, nl)).trim();
      if (DROP.indexOf(heading) !== -1) return '';
      return '### ' + part;
    }).join('').trim();
  }
  let html = escapeHtml(text);
  html = html.replace(/^###\s+(.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/\n\n+/g, '</p><p>');
  return '<p>' + html + '</p>';
}

async function updateStatus(type, itemId, newStatus, btn, deadline) {
  // 拒绝=直接删除,不需二次确认;其他状态变更(接受)仍确认
  if (newStatus !== 'rejected') {
    if (!await confirmModal(`确认将状态改为「${statusLabel(newStatus)}」?`)) return;
  }
  const card = document.getElementById('card-' + itemId);
  if (card) card.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const payload = { status: newStatus };
    if (deadline) payload.deadline = deadline;
    const res = await fetch(`/api/${type}/${itemId}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      toast('修改失败:' + (data.detail || '未知错误'), 'error');
      if (card) card.querySelectorAll('button').forEach(b => b.disabled = false);
      return;
    }
    if (data.deleted) {
      toast('✓ 已删除该候选', 'success');
    } else if (data.moved) {
      // 接受即搬运:给出具体去向
      const where = data.moved_to || '';
      const label = type === 'idea'
        ? `已加入「${data.area || ''}」idea 列表`
        : `已加入计划`;  // v0.4.23: plan 不再分 weekly/monthly/someday
      toast('✓ ' + label + (where ? `(${where})` : ''), 'success');
    } else if (data.move_reason === 'already_moved') {
      toast('该候选已搬运过,无需重复操作', 'info');
    } else if (data.move_error) {
      toast('状态已更新,但搬运失败:' + data.move_error, 'error');
    } else {
      toast('✓ 状态已更新为「' + statusLabel(data.new_status || newStatus) + '」', 'success');
    }
    loadSuggestions(type);
  } catch (e) {
    toast('网络错误:' + e.message, 'error');
    if (card) card.querySelectorAll('button').forEach(b => b.disabled = false);
  }
}

// v0.4.12: plan 接受 —— 弹窗可选填截止日期,确定后调 updateStatus(status=accepted, deadline)
function acceptPlanWithDeadline(itemId, btn) {
  const overlay = document.getElementById('modalOverlay');
  const box = document.getElementById('modalBox');
  if (!overlay || !box) { updateStatus('plan', itemId, 'accepted', btn, ''); return; }
  document.getElementById('modalTitle').textContent = '接受该待办';
  box.classList.remove('modal--danger');
  const body = document.getElementById('modalBody');
  const actions = document.getElementById('modalActions');
  body.innerHTML = '';
  actions.innerHTML = '';
  const hint = document.createElement('div');
  hint.className = 'modal-prompt-hint muted';
  hint.textContent = '可填写截止日期(可不填)。';
  body.appendChild(hint);
  const input = document.createElement('input');
  input.type = 'date';
  input.className = 'modal-prompt-input';
  body.appendChild(input);
  const cancel = document.createElement('button');
  cancel.className = 'btn btn-ghost';
  cancel.textContent = '取消';
  cancel.onclick = function () { overlay.hidden = true; };
  const ok = document.createElement('button');
  ok.className = 'btn btn-primary';
  ok.textContent = '接受';
  ok.onclick = function () {
    const dl = (input.value || '').trim();
    overlay.hidden = true;
    updateStatus('plan', itemId, 'accepted', btn, dl);
  };
  actions.appendChild(cancel);
  actions.appendChild(ok);
  overlay.hidden = false;
  setTimeout(function () { ok.focus(); }, 30);
}

/* ====================== 已确定 idea/plan(正式清单) ====================== */

async function loadConfirmedIdeas() {
  const grid = document.getElementById('idea-confirmed-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const res = await fetch('/api/ideas/confirmed');
    const data = await res.json();
    const items = data.items || [];
    if (items.length === 0) {
      grid.innerHTML = '<div class="empty">还没有正式 idea。先在「待定」确认后运行 <code>python scripts/kb.py accept-ideas</code>。</div>';
      return;
    }
    grid.innerHTML = items.map(renderFormalIdeaCard).join('');
    // v0.4.22: 绑定删除按钮事件委托
    grid.addEventListener('click', function(e) {
      const btn = e.target.closest('[data-action="delete-idea"]');
      if (btn) {
        const id = btn.getAttribute('data-idea-id');
        deleteConfirmedIdea(id);
      }
    });
    // 刷新 Lucide 图标
    if (window.refreshIcons) window.refreshIcons();
  } catch (e) {
    grid.innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }
}

function renderFormalIdeaCard(item) {
  // v0.4.11: 已确定 idea 卡片也只留标题(去掉所有标签 + 正文)
  // v0.4.22: 添加删除按钮(右上角,hover 显示)
  return '<div class="card suggestion-card">' +
    '<button class="icon-btn icon-btn-danger idea-delete-btn" title="删除此 idea" data-action="delete-idea" data-idea-id="' + escapeHtml(item.id) + '">' +
    '<i data-lucide="trash-2"></i></button>' +
    '<h3 class="card-title">' + escapeHtml(item.title || item.id || '(未命名)') + '</h3>' +
    '</div>';
}

async function deleteConfirmedIdea(ideaId) {
  // v0.4.22: 删除已确定的 idea
  if (!await confirmModal('确定删除此 idea？此操作不可撤销。', {
    title: '删除 Idea', danger: true, confirmText: '删除'
  })) return;

  try {
    const res = await fetch('/api/idea/confirmed/' + encodeURIComponent(ideaId), {
      method: 'DELETE'
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail || '删除失败');
    }
    toast('✓ 已删除', 'success');
    await loadConfirmedIdeas(); // 刷新列表
  } catch (e) {
    toast('删除失败:' + e.message, 'error');
  }
}

async function loadConfirmedPlans() {
  const grid = document.getElementById('plan-confirmed-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const res = await fetch('/api/plans/confirmed');
    const data = await res.json();
    const items = data.items || [];
    if (items.length === 0) {
      grid.innerHTML = '<div class="empty">还没有正式 plan。先在「待定」确认后运行 <code>python scripts/kb.py accept-plans</code>。</div>';
      return;
    }
    // 拉日历事项,建 plan_id/source_id → calItem 映射,用于「已加入日历」状态回显
    // v0.4.23:新 plan 日历项用 plan_id 字段(而非 source_id),两端都匹配兼容
    let calMap = {};
    try {
      const calRes = await fetch('/api/calendar');
      const calData = await calRes.json();
      (calData.items || []).forEach(ci => {
        if (ci.source_id) calMap[ci.source_id] = ci;
        if (ci.plan_id) calMap[ci.plan_id] = ci;
      });
    } catch (e) { /* 日历加载失败不阻塞 plan 显示 */ }
    // v0.4.23: 扁平列表(按 status 分两组:待办 / 已完成),不再按 weekly/monthly/someday 分组
    const groups = { active: [], done: [] };
    items.forEach(it => {
      const key = it.status === 'done' ? 'done' : 'active';
      groups[key].push(it);
    });
    const labels = {
      active: '<i data-lucide="circle"></i> 待办',
      done: '<i data-lucide="check"></i> 已完成'
    };
    let html = '';
    for (const key of ['active', 'done']) {
      if (groups[key].length === 0) continue;
      html += '<div class="confirmed-group"><h3 class="confirmed-group-title">' + labels[key] +
              ' <span class="count-badge">' + groups[key].length + '</span></h3>';
      html += '<div class="card-grid">' + groups[key].map(it => renderFormalPlanCard(it, calMap[it.id])).join('') + '</div></div>';
    }
    grid.innerHTML = html || '<div class="empty">暂无</div>';
  } catch (e) {
    grid.innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }
}

function renderFormalPlanCard(item, calItem) {
  // v0.4.6: 存全局 planStore,点击时按 id 取回完整 item(替代 onclick=JSON.stringify 注入)
  if (item.id) window.planStore.set(item.id, item);
  // v0.4.23: 卡片显示 状态 + 标题 + deadline(如有) + 日历关联区
  const isDone = item.status === 'done';
  const doneBadge = isDone ? '<span class="tag" style="background:#dcfce7;color:#166534"><i data-lucide="check"></i> 已完成</span>'
                           : '<span class="tag tag-area"><i data-lucide="circle"></i> 待办</span>';
  const itemId = escapeHtml(item.id || '');
  // deadline 显示(有值才显示,逾期标红)
  const today = new Date().toISOString().slice(0, 10);
  let dlHtml = '';
  if (item.deadline) {
    const overdue = !isDone && item.deadline < today;
    const dlClass = overdue ? 'tk-dl-overdue' : (item.deadline === today ? 'tk-dl-today' : '');
    dlHtml = '<div class="plan-deadline ' + dlClass + '"><i data-lucide="calendar-clock"></i> '
      + (overdue ? '⚠ ' : '') + escapeHtml(item.deadline) + '</div>';
  }
  // 日历关联区:已加入显示日期+编辑,未加入显示「放入日历」按钮
  let calSection;
  if (calItem) {
    calSection = '<div class="plan-cal-link">' +
      '<span class="tag" style="background:#dbeafe;color:#1e40af">📅 已加入日历 · ' + escapeHtml(calItem.date) + '</span>' +
      '<button class="btn btn-sm btn-ghost" data-action="open-plan-calendar" data-plan-id="' + itemId + '" data-mode="edit">编辑</button>' +
      '</div>';
  } else {
    calSection = '<div class="action-row">' +
      '<button class="btn btn-sm btn-primary" data-action="open-plan-calendar" data-plan-id="' + itemId + '" data-mode="create">📅 放入日历</button>' +
      '</div>';
  }
  return '<div class="card suggestion-card' + (isDone ? ' card-done' : '') + '">' +
    '<div class="card-header">' + doneBadge + '</div>' +
    '<h3 class="card-title">' + escapeHtml(item.title) + '</h3>' +
    dlHtml +
    calSection +
    '</div>';
}

// 已确认 plan 放入日历(复用统一日历表单 openCalendarEventForm)
function openPlanCalendar(planItemOrId, mode) {
  // v0.4.6: 兼容两种入参——完整 item 对象(旧调用方)或 id 字符串(事件委托)
  // id 字符串时从全局 planStore 取回完整 item
  let planItem = planItemOrId;
  if (typeof planItemOrId === 'string') {
    planItem = window.planStore ? window.planStore.get(planItemOrId) : null;
    if (!planItem) {
      toast('未找到 plan 数据(可能页面已刷新)', 'warning');
      return;
    }
  }
  if (mode === 'edit') {
    // 编辑模式:先查该 plan 已有的日历事项
    fetch('/api/calendar').then(r => r.json()).then(d => {
      const existing = (d.items || []).find(ci => ci.source_id === planItem.id);
      if (!existing) { toast('未找到关联的日历事项', 'warning'); return; }
      openCalendarEventForm({
        mode: 'edit',
        entry: 'plan-edit',
        item: existing,
        onSaved: function() { loadConfirmedPlans(); },
        onDeleted: function() { loadConfirmedPlans(); },
      });
    }).catch(e => toast('加载日历失败:' + e.message, 'error'));
    return;
  }
  // 创建模式:默认标题=plan 标题,日期=今天,source_id=plan id(用于去重和回显)
  openCalendarEventForm({
    mode: 'create',
    entry: 'plan-create',
    sourceId: planItem.id,
    sourceType: 'plan',
    sourceTitle: planItem.title,
    defaultTitle: planItem.title,
    defaultDate: new Date().toISOString().slice(0, 10),
    onSaved: function() { loadConfirmedPlans(); },
  });
}

/* ====================== 详情页:加入文件夹(收藏夹) ====================== */

// 弹窗:选择文章要加入的文件夹(多选),保存调 POST /api/article/{id}/collections
async function openAddToCollections(sourceId) {
  let collections = [];
  let currentIds = [];
  try {
    const [colRes, artRes] = await Promise.all([
      fetch('/api/collections'), fetch('/api/summary/' + sourceId),
    ]);
    const colData = await colRes.json();
    collections = colData.items || [];
    const artData = await artRes.json();
    currentIds = (artData.collection_ids) || [];
  } catch (e) { toast('加载失败:' + e.message, 'error'); return; }

  if (collections.length === 0) {
    if (!await confirmModal('还没有任何文件夹。先去收藏夹页新建一个文件夹?', {title: '没有文件夹', confirmText: '去收藏夹'})) return;
    window.location.href = '/favorites';
    return;
  }

  // 复用 modal,注入 checkbox 列表
  const overlay = document.getElementById('modalOverlay');
  const box = document.getElementById('modalBox');
  if (!overlay || !box) { toast('弹窗不可用', 'error'); return; }
  document.getElementById('modalTitle').textContent = '加入文件夹';
  box.classList.remove('modal--danger');
  const body = document.getElementById('modalBody');
  const actions = document.getElementById('modalActions');
  const currentSet = new Set(currentIds);
  body.innerHTML = '<div class="modal-prompt-hint muted">勾选要加入的文件夹(可多选),取消勾选则移出。</div>';
  const listEl = document.createElement('div');
  listEl.className = 'modal-check-list';
  collections.forEach(col => {
    const label = document.createElement('label');
    label.className = 'modal-check-item';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = col.id;
    cb.checked = currentSet.has(col.id);
    const span = document.createElement('span');
    span.textContent = '📂 ' + col.name + ' (' + col.count + ')';
    label.appendChild(cb);
    label.appendChild(span);
    listEl.appendChild(label);
  });
  body.appendChild(listEl);
  actions.innerHTML = '';
  const c = document.createElement('button');
  c.className = 'btn btn-ghost';
  c.textContent = '取消';
  c.onclick = function () { overlay.hidden = true; };
  const ok = document.createElement('button');
  ok.className = 'btn btn-primary';
  ok.textContent = '保存';
  ok.onclick = async function () {
    const selected = Array.from(listEl.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
    ok.disabled = true; ok.textContent = '保存中...';
    try {
      const res = await fetch('/api/article/' + sourceId + '/collections', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({collection_ids: selected}),
      });
      const data = await res.json();
      overlay.hidden = true;
      if (!res.ok) { toast('保存失败:' + (data.detail || ''), 'error'); return; }
      toast('✓ 已更新文件夹归属', 'success');
    } catch (e) {
      toast('网络错误:' + e.message, 'error');
      overlay.hidden = true;
    }
  };
  actions.appendChild(c);
  actions.appendChild(ok);
  overlay.hidden = false;
}

/* ====================== 仪表盘(标签页 + 骨架屏) ====================== */
const DASH = { unread: [], read: [], readlater: [], view: KBState.get('kb-art-view', 'card'), visible: { unread: 12, read: 12, readlater: 12 } };

function renderSkeletons(gridId, n) {
  n = n || 6;
  const grid = document.getElementById(gridId);
  if (!grid) return;
  let h = '';
  for (let i = 0; i < n; i++) {
    h += `<div class="card skel-card">
      <div class="skeleton skel-line w-40"></div>
      <div class="skeleton skel-line w-90"></div>
      <div class="skeleton skel-line w-60"></div>
    </div>`;
  }
  grid.innerHTML = h;
}

function renderPanel(tab) {
  const grid = document.getElementById('grid-' + tab);
  const more = document.querySelector('.show-more[data-tab="' + tab + '"]');
  const items = DASH[tab] || [];
  const vis = DASH.visible[tab] || 12;
  const counts = { unread: 'count-unread', read: 'count-read', readlater: 'count-read-later' };
  const countEl = document.getElementById(counts[tab]);
  if (countEl) countEl.textContent = items.length;
  // 视图:卡片 / 列表 —— 切换容器类,列表视图退化为纵向行
  if (grid) grid.classList.toggle('list-view', DASH.view === 'list');
  if (!items.length) {
    const emptyMsg = {
      unread: '没有未读文章,全部已读 🎉',
      read: '还没有最近阅读记录。打开文章详情会自动记录到这里。',
      readlater: '还没有稍后阅读的文章。在文章详情页点 📖 加入。',
    }[tab];
    if (grid) grid.innerHTML = '<div class="empty">' + emptyMsg + '</div>';
    if (more) more.style.display = 'none';
    return;
  }
  const renderer = DASH.view === 'list' ? renderArticleRow : renderArticleCard;
  // 逐张卡片容错:单张渲染失败不能让整个面板空白(防静默白屏)
  const slice = items.slice(0, vis);
  const parts = [];
  for (const item of slice) {
    try { parts.push(renderer(item)); }
    catch (e) {
      console.error('renderPanel(' + tab + ') 卡片渲染失败:', e, item);
      parts.push('<div class="card error">该文章卡片渲染失败:' + escapeHtml(String(e.message || e)) + '</div>');
    }
  }
  if (grid) grid.innerHTML = parts.join('') || '<div class="empty">没有可显示的文章。</div>';
  if (more) more.style.display = vis < items.length ? 'block' : 'none';
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => {
    const on = t.dataset.tab === tab;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tab));
  KBState.set('kb-dash-tab', tab);
}

async function initDashboard() {
  // 标签切换
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));
  // 默认打开未读；如果本次会话里手动切过其它标签，再恢复到上次标签。
  const lastTab = KBState.get('kb-dash-tab', 'unread');
  if (lastTab !== 'unread') switchTab(lastTab);

  // 卡片 / 列表 视图切换(默认轻量卡片,可切列表;选择记忆到会话存储)
  const viewBtns = document.querySelectorAll('.art-view-btn');
  function syncViewBtns() {
    viewBtns.forEach(x => {
      const on = x.dataset.view === DASH.view;
      x.classList.toggle('btn-primary', on);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
  syncViewBtns();
  viewBtns.forEach(b => b.addEventListener('click', () => {
    DASH.view = b.dataset.view;
    KBState.set('kb-art-view', DASH.view);
    syncViewBtns();
    renderPanel('unread'); renderPanel('read'); renderPanel('readlater');
  }));
  // 显示更多
  document.querySelectorAll('.show-more').forEach(b => b.addEventListener('click', () => {
    const tab = b.dataset.tab;
    DASH.visible[tab] = (DASH.visible[tab] || 12) + 12;
    renderPanel(tab);
  }));

  renderSkeletons('grid-unread');
  renderSkeletons('grid-read');
  renderSkeletons('grid-readlater');

  // 统计概览
  const overview = document.getElementById('stats-overview');
  try {
    const res = await fetch('/api/dashboard');
    if (!res.ok) throw new Error('API 返回 ' + res.status);
    const d = await res.json();
    const s = d.stats || {};
    const readLater = (d.read_later || []).length;
    overview.innerHTML = `
      <div class="stat-strip">
        <div class="stat-strip-item stat-unread"><span class="stat-num">${s.unread}</span><span class="stat-label">未读</span></div>
        <div class="stat-strip-sep"></div>
        <div class="stat-strip-item stat-read"><span class="stat-num">${s.read}</span><span class="stat-label">已读</span></div>
        <div class="stat-strip-sep"></div>
        <div class="stat-strip-item stat-total"><span class="stat-num">${s.total}</span><span class="stat-label">总计</span></div>
        <div class="stat-strip-sep"></div>
        <div class="stat-strip-item"><span class="stat-num">${readLater}</span><span class="stat-label">稍后读</span></div>
      </div>
      <div class="kb-progress-row">
        <div class="kb-progress-info"><span class="kb-progress-label">阅读进度</span><span class="kb-progress-pct">${s.progress}%</span></div>
        <div class="progress-bar-wrap kb-progress-wrap"><div class="progress-bar" style="width:${s.progress}%"></div></div>
        <div class="kb-progress-detail muted">${s.read} / ${s.total} 篇已读</div>
      </div>
    `;
    DASH.readlater = d.read_later || [];
  } catch (e) {
    overview.innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }

  // 未读/已读列表
  try {
    const res = await fetch('/api/dashboard_full');
    let data;
    if (res.ok) data = await res.json();
    else { const r2 = await fetch('/api/summaries'); const d2 = await r2.json(); data = { unread: d2.items, read: [] }; }
    DASH.unread = data.unread || [];
    DASH.read = data.read || [];
    // readlater 已在 /api/dashboard 中获取,这里保持不变
    // 每个面板独立渲染 + 容错:单个面板失败不影响其他面板,骨架屏必定被清除(防静默白屏)
    ['unread', 'read', 'readlater'].forEach(t => {
      try { renderPanel(t); }
      catch (e) {
        console.error('renderPanel(' + t + ') 失败:', e);
        const g = document.getElementById('grid-' + t);
        if (g) g.innerHTML = '<div class="error">面板加载失败:' + escapeHtml(String(e.message || e)) + '</div>';
      }
    });
    restoreScroll();
  } catch (e) {
    console.error('initDashboard 加载列表失败:', e);
    const g = document.getElementById('grid-unread');
    if (g) g.innerHTML = '<div class="error">加载失败:' + escapeHtml(String(e.message || e)) + '</div>';
  }
}

/* ====================== 全局初始化 ====================== */
initTheme();
initSidebarCollapse();
initNav();
initModalOverlay();

/* ====================== 统一日历事件表单(v0.3.1) ====================== */

/**
 * 打开统一日历事件表单。
 * opts: { mode, entry, sourceId, sourceType, sourceTitle, item, defaultDate, defaultTitle, recommendedDate, onSaved, onDeleted }
 */
function openCalendarEventForm(opts) {
  opts = opts || {};
  const isEdit = opts.mode === 'edit';
  const today = new Date().toISOString().slice(0, 10);

  // 默认值
  let title = opts.defaultTitle || '';
  let eventDate = opts.defaultDate || today;
  let note = '';
  let sourceId = opts.sourceId || '';
  let sourceType = opts.sourceType || '';
  let sourceTitle = opts.sourceTitle || '';
  let category = '';  // v0.4.2: 事件类别
  let itemId = '';

  if (isEdit && opts.item) {
    title = opts.item.title || '';
    eventDate = opts.item.date || today;
    note = opts.item.note || '';
    sourceId = opts.item.source_id || '';
    sourceType = opts.item.source_type || '';
    sourceTitle = opts.item.source_title || '';
    category = opts.item.category || '';
    itemId = opts.item.id || '';
  } else if (sourceType === 'plan') {
    // v0.4.2: 从 plan 创建的事项默认归类为 todolist
    category = 'todolist';
  }

  // 推荐日期说明(仅 knowledge-detail 入口)
  const rec = opts.recommendedDate;
  let recInfo = '';
  if (opts.entry === 'knowledge-detail') {
    if (rec && rec.normalized_date) {
      const confLabel = rec.confidence === 'high' ? '高可信度' : (rec.confidence === 'medium' ? '可能日期,请确认' : '模糊日期,请确认');
      recInfo = '<div class="cal-form-rec">' +
        '<span>推荐日期:' + escapeHtml(rec.normalized_date) + '</span>' +
        (rec.context ? '<span class="muted">识别依据:"' + escapeHtml(rec.context.slice(0, 60)) + '"</span>' : '') +
        '<span class="' + (rec.confidence === 'high' ? 'conf-high' : (rec.confidence === 'low' ? 'conf-low' : '')) + '">' + confLabel + '</span>' +
        (rec.is_approximate ? '<span class="warn-text">该日期由模糊时间推算,请确认</span>' : '') +
        '</div>';
    } else {
      recInfo = '<div class="cal-form-rec"><span class="muted">未识别到明确日期,已默认选择今天。</span></div>';
    }
  }

  // 关联内容
  let sourceHtml = '';
  if (sourceTitle) {
    sourceHtml = '<div class="cal-form-source">' +
      '<span class="cal-source-label">关联内容:</span>' +
      (sourceId ? '<a href="/summary/' + encodeURIComponent(sourceId) + '" class="cal-source-link" target="_blank">' + escapeHtml(sourceTitle) + '</a>' : '<span>' + escapeHtml(sourceTitle) + '</span>') +
      '<button class="btn btn-sm btn-ghost" id="cal-form-remove-source">移除关联</button>' +
      '</div>';
  }

  // v0.4.17: 类别选择器改用全局共享元数据 cat-meta.js(消除重复定义)
  const CAT_PRESETS = catPresets();
  let selectedCategory = category || '';  // 单一真源,点击直接更新此变量
  const isPreset = CAT_PRESETS.some(p => p.value === selectedCategory);
  const catCustom = isPreset ? '' : selectedCategory;
  const catPickerHtml =
    '<div class="cal-form-field"><label>类别</label>' +
    '<div class="cal-cat-picker" id="cal-cat-picker">' +
    CAT_PRESETS.map(p =>
      '<button type="button" class="cal-cat-opt' + (selectedCategory === p.value ? ' is-selected' : '') + '" ' +
      'data-cat-value="' + p.value + '" style="--ev:' + p.color + '">' +
      '<span><i data-lucide="' + p.icon + '"></i> ' + p.label + '</span></button>'
    ).join('') +
    '<input type="text" id="cal-form-cat-custom" class="cal-cat-custom" value="' + escapeHtml(catCustom) + '" maxlength="20" placeholder="或自定义…">' +
    '</div></div>';

  const formTitle = isEdit ? '编辑事件' : (opts.entry === 'knowledge-detail' ? '添加到日历' : '新建事件');
  const deleteBtn = isEdit ? '<button class="btn btn-danger" id="cal-form-delete">删除事件</button>' : '';
  const saveLabel = isEdit ? '保存' : (opts.entry === 'knowledge-detail' ? '添加' : '保存');

  const formHtml =
    '<div class="cal-form">' +
    '<h3 class="cal-form-title">' + formTitle + '</h3>' +
    recInfo +
    '<div class="cal-form-field"><label>标题 <span class="required">*</span></label>' +
    '<input type="text" id="cal-form-title-input" value="' + escapeHtml(title) + '" maxlength="120" placeholder="请输入标题"></div>' +
    '<div class="cal-form-field"><label>日期 <span class="required">*</span></label>' +
    '<input type="date" id="cal-form-date-input" value="' + eventDate + '"></div>' +
    catPickerHtml +
    sourceHtml +
    '<div class="cal-form-field"><label>备注</label>' +
    '<textarea id="cal-form-note-input" rows="3" maxlength="2000" placeholder="添加备注...">' + escapeHtml(note) + '</textarea></div>' +
    '<div class="cal-form-actions">' + deleteBtn +
    '<button class="btn btn-ghost" id="cal-form-cancel">取消</button>' +
    '<button class="btn btn-primary" id="cal-form-save">' + saveLabel + '</button></div>' +
    '</div>';

  // 渲染到 modal
  const overlay = document.getElementById('modalOverlay');
  const box = document.getElementById('modalBox');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const modalActions = document.getElementById('modalActions');
  if (!overlay || !box) { alert('modal 不可用'); return; }

  modalTitle.textContent = formTitle;
  modalBody.innerHTML = formHtml;
  modalActions.innerHTML = '';  // 隐藏默认按钮(表单自带按钮)
  overlay.hidden = false;

  // 移除关联
  const removeBtn = document.getElementById('cal-form-remove-source');
  if (removeBtn) {
    removeBtn.onclick = function() {
      sourceId = ''; sourceType = ''; sourceTitle = '';
      const srcDiv = document.querySelector('.cal-form-source');
      if (srcDiv) srcDiv.innerHTML = '<span class="muted">关联已移除</span>';
    };
  }

  // v0.4.2: 类别选择交互 —— 按钮直接更新 selectedCategory,与自定义输入互斥
  const catCustomInput = document.getElementById('cal-form-cat-custom');
  const catPicker = document.getElementById('cal-cat-picker');
  const catButtons = catPicker ? catPicker.querySelectorAll('.cal-cat-opt') : [];
  catButtons.forEach(btn => {
    btn.onclick = function() {
      selectedCategory = this.dataset.catValue;
      catCustomInput.value = '';  // 选预设清空自定义
      catButtons.forEach(b => b.classList.toggle('is-selected', b === this));
    };
  });
  if (catCustomInput) {
    catCustomInput.oninput = function() {
      selectedCategory = this.value.trim();
      // 输入自定义时清除预设选中态
      catButtons.forEach(b => b.classList.remove('is-selected'));
    };
  }
  // 读取当前选中的类别(自定义优先,否则 selectedCategory,否则空串)
  function readCategory() {
    if (catCustomInput && catCustomInput.value.trim()) return catCustomInput.value.trim();
    return selectedCategory || '';
  }

  // 取消
  document.getElementById('cal-form-cancel').onclick = function() {
    overlay.hidden = true;
  };

  // 保存
  document.getElementById('cal-form-save').onclick = async function() {
    const btn = this;
    const t = document.getElementById('cal-form-title-input').value.trim();
    const d = document.getElementById('cal-form-date-input').value;
    const n = document.getElementById('cal-form-note-input').value.trim();
    const cat = readCategory();
    if (!t) { alert('标题不能为空'); return; }
    if (!d || !d.match(/^\d{4}-\d{2}-\d{2}$/)) { alert('日期格式错误'); return; }

    btn.disabled = true; btn.textContent = '保存中...';
    try {
      let res;
      if (isEdit) {
        res = await fetch('/api/calendar/' + itemId, {
          method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({title: t, date: d, note: n, category: cat, source_id: sourceId}),
        });
      } else {
        res = await fetch('/api/calendar', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            title: t, date: d, note: n, category: cat,
            source_id: sourceId, source_type: sourceType, source_title: sourceTitle,
            date_source: rec ? 'detected' : 'manual',
            date_confidence: rec ? rec.confidence : '',
          }),
        });
      }
      const data = await res.json();
      if (!res.ok) {
        alert('保存失败:' + (data.detail || ''));
        btn.disabled = false; btn.textContent = saveLabel;
        return;
      }
      overlay.hidden = true;
      if (typeof opts.onSaved === 'function') opts.onSaved(data.item || data, isEdit);
    } catch(e) {
      alert('网络错误:' + e.message);
      btn.disabled = false; btn.textContent = saveLabel;
    }
  };

  // 删除(编辑模式)
  if (isEdit) {
    const delBtn = document.getElementById('cal-form-delete');
    if (delBtn) {
      delBtn.onclick = async function() {
        if (!confirm('确定删除这个事件吗?')) return;
        delBtn.disabled = true;
        try {
          const res = await fetch('/api/calendar/' + itemId, {method: 'DELETE'});
          if (res.ok) {
            overlay.hidden = true;
            if (typeof opts.onDeleted === 'function') opts.onDeleted();
          }
        } catch(e) { alert('删除失败:' + e.message); delBtn.disabled = false; }
      };
    }
  }

  // 聚焦标题
  setTimeout(function() { document.getElementById('cal-form-title-input').focus(); }, 50);
}

// ---------------------------------------------------------------------------
// 详情页手动生成 Idea/Plan(v0.4.0)
// 参考 openCalendarEventForm 的表单弹窗模式:innerHTML 注入 + 自带按钮
// ---------------------------------------------------------------------------

function openGenerateDialog(kind, sourceId) {
  const isIdea = kind === 'idea';
  const title = isIdea ? '生成 Idea 列表' : '生成 Plan 列表';
  const promptPh = isIdea
    ? '例如:重点找可落地的工具型 idea / 关注 Agent 相关方向'
    : '例如:本周能做完的 / 找可立即试用的工具';

  // kind 专属字段
  const ideaFields = isIdea
    ? '<div class="cal-form-field"><label>领域</label>' +
      '<select id="gen-area"><option value="">不限</option>' +
      '<option value="research">research</option>' +
      '<option value="productivity">productivity</option>' +
      '<option value="product">product</option>' +
      '<option value="ai_agent">ai_agent</option>' +
      '<option value="web_design">web_design</option>' +
      '<option value="other">other</option></select></div>'
    : '';
  const planFields = !isIdea
    ? '<div class="cal-form-field"><label>难度</label>' +
      '<select id="gen-difficulty"><option value="">不限</option>' +
      '<option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></div>' +
      '<div class="cal-form-field"><label>预计时间</label>' +
      '<select id="gen-time"><option value="">不限</option>' +
      '<option value="30min">30min</option><option value="1h">1h</option><option value="2-4h">2-4h</option>' +
      '<option value="半天">半天</option><option value="1-2 天">1-2 天</option></select></div>'
    : '';

  const formHtml =
    '<div class="cal-form">' +
    '<div class="cal-form-field"><label>引导提示词(可选)</label>' +
    '<textarea id="gen-prompt" rows="3" maxlength="500" placeholder="' + escapeHtml(promptPh) + '"></textarea></div>' +
    '<div class="cal-form-field"><label>优先级</label>' +
    '<select id="gen-priority"><option value="">不限</option>' +
    '<option value="P0">P0</option><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3</option></select></div>' +
    ideaFields + planFields +
    '<div class="cal-form-actions">' +
    '<button class="btn btn-ghost" id="gen-cancel">取消</button>' +
    '<button class="btn btn-primary" id="gen-submit">生成</button></div>' +
    '</div>';

  // 渲染到 modal
  const overlay = document.getElementById('modalOverlay');
  const box = document.getElementById('modalBox');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const modalActions = document.getElementById('modalActions');
  if (!overlay || !box) { alert('modal 不可用'); return; }

  modalTitle.textContent = title;
  modalBody.innerHTML = formHtml;
  modalActions.innerHTML = '';  // 隐藏默认按钮(表单自带)
  overlay.hidden = false;

  const cancelBtn = document.getElementById('gen-cancel');
  const submitBtn = document.getElementById('gen-submit');
  cancelBtn.onclick = function () { overlay.hidden = true; };

  submitBtn.onclick = async function () {
    const promptVal = (document.getElementById('gen-prompt').value || '').trim();
    const priorityVal = document.getElementById('gen-priority').value;
    const body = { prompt: promptVal.slice(0, 500), priority: priorityVal };
    if (isIdea) {
      body.area = document.getElementById('gen-area').value;
    } else {
      body.difficulty = document.getElementById('gen-difficulty').value;
      body.estimated_time = document.getElementById('gen-time').value;
    }

    const url = '/api/article/' + encodeURIComponent(sourceId) +
                (isIdea ? '/generate-ideas' : '/generate-plans');
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ 生成中...(约 10-30 秒)';
    cancelBtn.disabled = true;
    try {
      const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        toast('生成失败:' + (data.detail || data.error || '未知错误'), 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = '生成';
        cancelBtn.disabled = false;
        return;  // 弹窗保持打开,保留用户输入
      }
      overlay.hidden = true;
      const n = data.generated || 0;
      const listPage = isIdea ? '/ideas' : '/plans';
      if (n > 0) {
        toast('✓ 已生成 ' + n + ' 条候选,前往 ' + listPage + ' 查看', 'success');
      } else {
        toast('未识别到可转化的候选', 'warning');
      }
    } catch (e) {
      toast('网络错误:' + e.message, 'error');
      submitBtn.disabled = false;
      submitBtn.textContent = '生成';
      cancelBtn.disabled = false;
    }
  };

  // 聚焦引导词
  setTimeout(function () { document.getElementById('gen-prompt').focus(); }, 50);
}

/* ====================== 全局事件委托(v0.4.6: 替代 onclick 拼字符串) ======================
 * 所有按钮通过 data-action 标记意图 + data-* 携带参数,document 级委托一次。
 * 避免 onclick='fn("${id}")' 拼字符串的 XSS 风险(id/title 含特殊字符可能突破属性)。
 */
function setupGlobalDelegation() {
  document.addEventListener('click', function (e) {
    // 沿 DOM 树向上找最近的有 data-action 的元素(兼容按钮内嵌图标的情况)
    let target = e.target;
    while (target && target !== document.body) {
      // 遇到链接(a 标签)直接放行默认跳转,不做委托处理
      if (target.tagName === 'A') return;
      if (target.dataset && target.dataset.action) break;
      target = target.parentElement;
    }
    if (!target || !target.dataset || !target.dataset.action) return;

    const action = target.dataset.action;
    const sid = target.dataset.sid;
    e.preventDefault();
    e.stopPropagation();

    switch (action) {
      case 'toggle-read-later':
        if (typeof toggleReadLater === 'function') toggleReadLater(sid);
        break;
      case 'toggle-favorite':
        if (typeof toggleFavorite === 'function') toggleFavorite(sid);
        break;
      case 'delete-article':
        if (typeof deleteArticle === 'function') deleteArticle(sid);
        break;
      case 'update-status':
        if (typeof updateStatus === 'function') {
          updateStatus(target.dataset.kind, sid, target.dataset.status, target);
        }
        break;
      case 'accept-plan':
        if (typeof acceptPlanWithDeadline === 'function') {
          acceptPlanWithDeadline(sid, target);
        }
        break;
      case 'open-plan-calendar':
        if (typeof openPlanCalendar === 'function') {
          openPlanCalendar(target.dataset.planId, target.dataset.mode || 'edit');
        }
        break;
      case 'select-collection':
        if (typeof selectCollection === 'function') selectCollection(target.dataset.colId);
        break;
      case 'rename-collection':
        if (typeof renameCollection === 'function') renameCollection(target.dataset.colId, target.dataset.colName);
        break;
      case 'delete-collection':
        if (typeof deleteCollection === 'function') deleteCollection(target.dataset.colId, target.dataset.colName);
        break;
      case 'edit-calendar-item':
        if (typeof openEditDialog === 'function') openEditDialog(target.dataset.itemId);
        break;
      case 'delete-calendar-item':
        if (typeof deleteCalendarItem === 'function') deleteCalendarItem(target.dataset.itemId);
        break;
      case 'quick-create':
        if (typeof quickCreate === 'function') quickCreate(target.dataset.dateStr);
        break;
      case 'show-day-items':
        if (typeof showDayItems === 'function') showDayItems(target.dataset.dateStr);
        break;
      case 'generate-summary':
        if (typeof generateSummary === 'function') generateSummary(target.dataset.sourceId, target);
        break;
      case 'generate-all-summaries':
        if (typeof generateAllSummaries === 'function') generateAllSummaries();
        break;
      case 'batch-remove':
        if (typeof batchRemove === 'function') batchRemove(parseInt(target.dataset.idx, 10));
        break;
      case 'retry-image':
        if (typeof retryImage === 'function') retryImage(target.dataset.imgId);
        break;
      case 'remove-image':
        if (typeof removeImage === 'function') removeImage(target.dataset.imgId);
        break;
      case 'remove-input':
        if (typeof removeInput === 'function') removeInput(target);
        break;
      case 'edit-event':
        if (typeof editEvent === 'function') editEvent(target.dataset.eventId);
        break;
      case 'sync-event':
        if (typeof syncEventToCalendar === 'function') syncEventToCalendar(target.dataset.eventId);
        break;
      case 'delete-event':
        if (typeof deleteEvent === 'function') deleteEvent(target.dataset.eventId);
        break;
    }
  });

  // change 事件(checkbox 等)单独委托
  document.addEventListener('change', function (e) {
    const el = e.target;
    if (!el.dataset || !el.dataset.action) return;
    if (el.dataset.action === 'toggle-select' && typeof toggleSelect === 'function') {
      toggleSelect(el, el.dataset.sid);
    } else if (el.dataset.action === 'batch-toggle' && typeof batchToggle === 'function') {
      batchToggle(parseInt(el.dataset.idx, 10), el.checked);
    }
  });
}

// 全局 plan 存储(替代 onclick='openPlanCalendar(JSON.stringify(item))')
// 渲染时存,点击时取,避免在 HTML 里序列化整个对象
window.planStore = window.planStore || new Map();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupGlobalDelegation);
} else {
  // DOM 已就绪(脚本在 body 末尾加载时)
  setupGlobalDelegation();
}

/* ====================== 个人工作台:任务详情抽屉 + 切换当前任务 ====================== */
(function(){
  'use strict';

  // v0.4.22: 任务状态配色改读全局 cat-meta.js(taskStatusColor/Label),删本地 TK_STATUS_META。

  let _drawerResolve = null;

  function openDrawer(title, html) {
    const overlay = document.getElementById('drawerOverlay');
    if (!overlay) { console.warn('drawerOverlay 未找到'); return; }
    document.getElementById('drawerTitle').textContent = title || '';
    document.getElementById('drawerBody').innerHTML = html || '';
    overlay.hidden = false;
    // 强制 reflow 后加 open 类触发 transition
    void overlay.offsetWidth;
    overlay.classList.add('open');
    _drawerResolve = function() { closeDrawer(); };
  }

  function closeDrawer() {
    const overlay = document.getElementById('drawerOverlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    setTimeout(function() { overlay.hidden = true; }, 250);
  }

  const drawerCloseBtn = document.getElementById('drawerClose');
  if (drawerCloseBtn) drawerCloseBtn.addEventListener('click', closeDrawer);

  const drawerOverlay = document.getElementById('drawerOverlay');
  if (drawerOverlay) {
    drawerOverlay.addEventListener('click', function(e) {
      if (e.target === drawerOverlay) closeDrawer();
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && drawerOverlay.classList.contains('open')) closeDrawer();
    });
  }

  // 全局暴露:打开任务详情抽屉
  window.openTaskDrawer = async function(taskId) {
    try {
      const r = await fetch('/api/tasks/' + encodeURIComponent(taskId));
      if (!r.ok) throw new Error('加载失败');
      const t = await r.json();
      const sm = { color: taskStatusColor(t.status), label: taskStatusLabel(t.status) };
      const dl = t.deadline;
      const todayStr = new Date().toISOString().slice(0, 10);
      const dlClass = dl && dl < todayStr ? 'overdue' : (dl && dl === todayStr ? 'today' : '');
      const dlText = dl ? (dl < todayStr ? '<i data-lucide="triangle-alert"></i> 已逾期: ' : (dl === todayStr ? '<i data-lucide="alarm-clock"></i> 今天截止: ' : '截止: ')) + dl : '无截止日期';
      const cl = t.checklist || [];
      const clDone = cl.filter(function(x){ return x.done; }).length;
      const clHtml = cl.length
        ? cl.map(function(it) {
            return '<label class="td-cl-item">'
              + '<input type="checkbox" class="cl-toggle" data-item-id="' + escapeHtml(it.id) + '" ' + (it.done ? 'checked' : '') + '>'
              + '<span class="td-cl-text' + (it.done ? ' td-cl-done' : '') + '">' + escapeHtml(it.text) + '</span>'
              + '</label>';
          }).join('')
        : '<div class="muted" style="padding:var(--sp-3)">暂无子任务</div>';
      const blockerHtml = t.blocker
        ? '<div class="td-blocker"><strong><i data-lucide="ban"></i> 当前问题:</strong> ' + escapeHtml(t.blocker) + '</div>' : '';
      const bodyHtml = t.body && t.body.trim() && t.body.trim() !== '（暂无描述）'
        ? '<div class="td-section"><h4 class="td-section-title">描述</h4><div class="td-body">' + escapeHtml(t.body.trim()) + '</div></div>' : '';
      const html =
        '<div class="td-header">'
          + '<span class="tk-status-badge" style="background:' + sm.color + '">' + sm.label + '</span>'
          + '<span class="td-date ' + dlClass + '">' + escapeHtml(dlText) + '</span>'
        + '</div>'
        + '<h1 class="td-title">' + escapeHtml(t.title) + '</h1>'
        + (t.project ? '<p style="color:var(--c-text-muted);margin:0 0 var(--sp-3)">所属项目: ' + escapeHtml(t.project) + '</p>' : '')
        + '<div class="td-actions">'
          + '<a class="btn btn-primary" href="/task/' + encodeURIComponent(t.id) + '">进入任务页面</a>'
          + '<a class="btn btn-sm" href="/task/' + encodeURIComponent(t.id) + '/edit"><i data-lucide="pencil"></i> 编辑</a>'
          + (t.deadline ? '<button class="btn btn-sm" id="drawer-sync"><i data-lucide="calendar"></i> 同步到日历</button>' : '')
        + '</div>'
        + blockerHtml
        + '<section class="td-section">'
          + '<h4 class="td-section-title">Checklist <span class="td-prog-muted">(' + clDone + '/' + cl.length + ')</span></h4>'
          + '<div class="td-checklist" id="drawer-checklist">' + clHtml + '</div>'
        + '</section>'
        + bodyHtml;
      openDrawer('任务详情', html);
      // 绑定 checklist
      document.querySelectorAll('#drawer-checklist .cl-toggle').forEach(function(cb) {
        cb.onchange = async function() {
          const done = cb.checked;
          try {
            const rr = await fetch('/api/tasks/' + encodeURIComponent(t.id) + '/checklist/' + encodeURIComponent(cb.dataset.itemId), {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ done: done })
            });
            if (!rr.ok) throw new Error('更新失败');
            const span = cb.parentElement.querySelector('.td-cl-text');
            if (span) span.classList.toggle('td-cl-done', done);
            // 刷新首页当前任务卡片(如果存在)
            if (typeof window.loadCurrentTask === 'function') window.loadCurrentTask();
          } catch(e) {
            cb.checked = !done;
            toast(e.message, 'error');
          }
        };
      });
      // 同步日历
      const syncBtn = document.getElementById('drawer-sync');
      if (syncBtn) {
        syncBtn.onclick = async function() {
          syncBtn.disabled = true; syncBtn.textContent = '同步中...';
          try {
            const rr = await fetch('/api/tasks/' + encodeURIComponent(t.id) + '/sync-calendar', { method: 'POST' });
            const dd = await rr.json();
            if (!rr.ok) throw new Error(dd.detail || '失败');
            toast(dd.reason === 'already_synced' ? '已同步过' : '已同步到日历', 'success');
            syncBtn.textContent = '📅 已同步';
          } catch(e) { toast(e.message, 'error'); syncBtn.disabled = false; syncBtn.textContent = '📅 同步到日历'; }
        };
      }
    } catch(e) { toast(e.message || '加载失败', 'error'); }
  };

  // 全局暴露:切换当前任务
  window.switchCurrentTaskModal = async function() {
    try {
      const r = await fetch('/api/tasks');
      const d = await r.json();
      let items = (d.items || []).filter(function(x){ return x.status === 'active'; });
      if (!items.length) { toast('没有可切换的进行中任务', 'warning'); return; }
      const stateR = await fetch('/api/workspace/current_task');
      const stateD = await stateR.json();
      const currentId = stateD.task ? stateD.task.id : '';
      const html = '<div class="ws-switch-list">' + items.map(function(t) {
        return '<button class="ws-switch-item' + (t.id === currentId ? ' current' : '') + '" data-task-id="' + escapeHtml(t.id) + '">'
          + '<span class="ws-switch-title">' + escapeHtml(t.title) + '</span>'
          + '<span class="ws-switch-meta">' + (t.deadline ? escapeHtml(t.deadline) : '无截止') + '</span>'
          + '</button>';
      }).join('') + '</div>';
      document.getElementById('modalTitle').textContent = '切换当前任务';
      document.getElementById('modalBody').innerHTML = html;
      document.getElementById('modalActions').innerHTML = '<button class="btn btn-ghost" id="switch-cancel">取消</button>';
      const overlay = document.getElementById('modalOverlay');
      overlay.hidden = false;
      document.getElementById('switch-cancel').onclick = function() { overlay.hidden = true; };
      document.querySelectorAll('.ws-switch-item').forEach(function(btn) {
        btn.onclick = async function() {
          const tid = btn.dataset.taskId;
          try {
            const rr = await fetch('/api/workspace/current_task', {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ task_id: tid })
            });
            if (!rr.ok) throw new Error('切换失败');
            overlay.hidden = true;
            toast('当前任务已切换', 'success');
            if (typeof window.loadCurrentTask === 'function') window.loadCurrentTask();
            else location.reload();
          } catch(e) { toast(e.message, 'error'); }
        };
      });
    } catch(e) { toast(e.message || '加载失败', 'error'); }
  };
})();

