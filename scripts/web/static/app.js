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

/* ====================== 主题 ====================== */
function applyTheme(theme) {
  if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
  else document.documentElement.removeAttribute('data-theme');
  const btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'dark' ? '#0f172a' : '#f7f8fa');
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('kb-theme'); } catch (e) {}
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved || (prefersDark ? 'dark' : 'light'));
  const btn = document.getElementById('themeToggle');
  if (btn) btn.addEventListener('click', function () {
    const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = cur === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('kb-theme', next); } catch (e) {}
    applyTheme(next);
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
  const links = document.getElementById('navLinks');
  const overlay = document.getElementById('navOverlay');
  if (!toggle || !links) return;
  function open() {
    links.classList.add('open');
    overlay.classList.add('open');
    overlay.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  }
  function close() {
    links.classList.remove('open');
    overlay.classList.remove('open');
    overlay.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  }
  toggle.addEventListener('click', function () {
    links.classList.contains('open') ? close() : open();
  });
  overlay.addEventListener('click', close);
  links.querySelectorAll('a').forEach(a => a.addEventListener('click', close));
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
          data-action="toggle-read-later" data-sid="${sid}">${rl ? '📖✓' : '📖'}</button>
        <button class="icon-btn ${fav ? 'active-fav' : ''}" title="收藏" aria-label="收藏"
          data-action="toggle-favorite" data-sid="${sid}">${fav ? '⭐✓' : '⭐'}</button>
        <button class="icon-btn icon-btn-danger" title="删除" aria-label="删除文章"
          data-action="delete-article" data-sid="${sid}">🗑</button>
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

function toggleSelect(checkbox, sid) {
  if (checkbox.checked) selectedIds.add(sid);
  else selectedIds.delete(sid);
  updateBatchBar();
}

function updateBatchBar() {
  const bar = document.getElementById('batch-bar');
  if (!bar) return;
  const count = selectedIds.size;
  if (count > 0) {
    bar.style.display = 'flex';
    document.getElementById('batch-count').textContent = count;
  } else {
    bar.style.display = 'none';
  }
}

function clearSelection() {
  selectedIds.clear();
  document.querySelectorAll('.card-checkbox').forEach(cb => cb.checked = false);
  updateBatchBar();
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
    if (document.getElementById('stats-overview')) refreshCurrentPage();
    else updateDetailButtons('read_later', data.read_later);
  } catch (e) { toast('网络错误:' + e.message, 'error'); }
}

async function toggleFavorite(sourceId) {
  try {
    const res = await fetch(`/api/article/${sourceId}/favorite`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { toast('操作失败:' + (data.detail || ''), 'error'); return; }
    if (document.getElementById('stats-overview')) refreshCurrentPage();
    else updateDetailButtons('is_favorite', data.is_favorite);
  } catch (e) { toast('网络错误:' + e.message, 'error'); }
}

function updateDetailButtons(field, value) {
  const btn = document.querySelector(`.detail-action-btn[data-field="${field}"]`);
  if (!btn) return;
  btn.classList.toggle('active-rl', field === 'read_later' && value);
  btn.classList.toggle('active-fav', field === 'is_favorite' && value);
  if (field === 'read_later') btn.textContent = value ? '📖✓ 已加入稍后读' : '📖 稍后阅读';
  if (field === 'is_favorite') btn.textContent = value ? '⭐✓ 已收藏' : '⭐ 收藏';
}

/* ====================== idea/todo 审阅 ====================== */
function statusBadgeClass(status) {
  if (!status) return 'status-pending_review';
  return 'status-' + status;
}
function statusLabel(status) {
  const map = {
    'pending_review': '待审核',
    'accepted_research': '已接受·科研',
    'accepted_productivity': '已接受·效率',
    'accepted_weekly': '已接受·本周',
    'accepted_monthly': '已接受·本月',
    'accepted_someday': '已接受·someday',
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
    if (!data.items || data.items.length === 0) {
      grid.innerHTML = `<div class="empty">还没有 ${type} 候选。运行 <code>python scripts/kb.py extract-suggestions</code> 抽取。</div>`;
      return;
    }
    grid.innerHTML = data.items.map(item => renderSuggestionCard(item, type)).join('');
  } catch (e) {
    grid.innerHTML = `<div class="error">加载失败:${escapeHtml(e.message)}</div>`;
  }
}

function renderSuggestionCard(item, type) {
  const f = item.fields || {};
  const status = item.status;
  const isAccepted = status && status.startsWith('accepted_');
  const isMoved = status === 'moved';

  let actions = '';
  if (status === 'pending_review') {
    const sid = escapeHtml(item.id);
    if (type === 'idea') {
      actions = `
        <button class="btn btn-accept" data-action="update-status" data-kind="idea" data-sid="${sid}" data-status="accepted_research">接受·科研</button>
        <button class="btn btn-accept" data-action="update-status" data-kind="idea" data-sid="${sid}" data-status="accepted_productivity">接受·效率</button>
        <button class="btn btn-ghost" data-action="update-status" data-kind="idea" data-sid="${sid}" data-status="rejected">拒绝</button>
      `;
    } else {
      actions = `
        <button class="btn btn-accept" data-action="update-status" data-kind="todo" data-sid="${sid}" data-status="accepted_weekly">本周</button>
        <button class="btn btn-accept" data-action="update-status" data-kind="todo" data-sid="${sid}" data-status="accepted_monthly">本月</button>
        <button class="btn btn-accept" data-action="update-status" data-kind="todo" data-sid="${sid}" data-status="accepted_someday">someday</button>
        <button class="btn btn-ghost" data-action="update-status" data-kind="todo" data-sid="${sid}" data-status="rejected">拒绝</button>
      `;
    }
  } else if (isAccepted) {
    actions = `<span class="muted" style="font-size:13px;">已确认 · 运行 <code>accept-${type}s</code> 后进入正式清单</span>`;
  } else if (isMoved) {
    actions = `<span class="muted" style="font-size:13px;">已进入正式清单</span>`;
  }

  let fieldsHtml = '';
  if (type === 'idea') {
    fieldsHtml = `
      <span class="label">领域</span><span>${escapeHtml(f.recommended_area || '-')}</span>
      <span class="label">优先级</span><span>${escapeHtml(f.priority || '-')}</span>
      <span class="label">可行性</span><span>${escapeHtml(f.feasibility || '-')}</span>
      <span class="label">新颖度</span><span>${escapeHtml(f.novelty || '-')}</span>
      <span class="label">预估投入</span><span>${escapeHtml(f.estimated_investment || '-')}</span>
    `;
  } else {
    fieldsHtml = `
      <span class="label">建议计划</span><span>${escapeHtml(f.recommended_plan || '-')}</span>
      <span class="label">优先级</span><span>${escapeHtml(f.priority || '-')}</span>
      <span class="label">预估时间</span><span>${escapeHtml(f.estimated_time || '-')}</span>
      <span class="label">难度</span><span>${escapeHtml(f.difficulty || '-')}</span>
    `;
  }

  return `
    <div class="card suggestion-card" id="card-${escapeHtml(item.id)}">
      <div class="card-header">
        <span class="status-badge ${statusBadgeClass(status)}">${statusLabel(status)}</span>
      </div>
      <h3 class="card-title">${escapeHtml(item.title || item.id)}</h3>
      <div class="suggestion-fields">${fieldsHtml}</div>
      ${item.body ? `<div class="suggestion-body">${formatSuggestionBody(item.body)}</div>` : ''}
      <div class="action-row">${actions}</div>
    </div>
  `;
}

function formatSuggestionBody(body) {
  let html = escapeHtml(body);
  html = html.replace(/^###\s+(.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/\n\n+/g, '</p><p>');
  return '<p>' + html + '</p>';
}

async function updateStatus(type, itemId, newStatus, btn) {
  // 拒绝=直接删除,不需二次确认;其他状态变更(接受/本周/本月...)仍确认
  if (newStatus !== 'rejected') {
    if (!await confirmModal(`确认将状态改为「${statusLabel(newStatus)}」?`)) return;
  }
  const card = document.getElementById('card-' + itemId);
  if (card) card.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const res = await fetch(`/api/${type}/${itemId}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
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
        : `已加入${data.plan === 'weekly' ? '本周' : data.plan === 'monthly' ? '本月' : 'someday'}计划`;
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

/* ====================== 已确定 idea/todo(正式清单) ====================== */

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
  } catch (e) {
    grid.innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }
}

function renderFormalIdeaCard(item) {
  const areaTag = item.area ? '<span class="tag tag-area">' + escapeHtml(item.area) + '</span>' : '';
  const priorityTag = item.priority ? '<span class="tag">' + escapeHtml(item.priority) + '</span>' : '';
  const maturity = item.maturity ? '<span class="tag">' + escapeHtml(item.maturity) + '</span>' : '';
  const statusTag = item.status ? '<span class="tag">' + escapeHtml(item.status) + '</span>' : '';
  const inv = item.fields && item.fields.estimated_investment
    ? '<span class="tag">⏱ ' + escapeHtml(item.fields.estimated_investment) + '</span>' : '';
  const bodyHtml = item.body ? '<div class="suggestion-body">' + formatSuggestionBody(item.body) + '</div>' : '';
  return '<div class="card suggestion-card">' +
    '<div class="card-header">' + areaTag + priorityTag + maturity + statusTag + inv + '</div>' +
    '<h3 class="card-title">' + escapeHtml(item.title || item.id || '(未命名)') + '</h3>' +
    bodyHtml +
    '</div>';
}

async function loadConfirmedTodos() {
  const grid = document.getElementById('todo-confirmed-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const res = await fetch('/api/todos/confirmed');
    const data = await res.json();
    const items = data.items || [];
    if (items.length === 0) {
      grid.innerHTML = '<div class="empty">还没有正式 todo。先在「待定」确认后运行 <code>python scripts/kb.py accept-todos</code>。</div>';
      return;
    }
    // 拉日历事项,建 source_id → calItem 映射,用于「已加入日历」状态回显
    let calMap = {};
    try {
      const calRes = await fetch('/api/calendar');
      const calData = await calRes.json();
      (calData.items || []).forEach(ci => {
        if (ci.source_id) calMap[ci.source_id] = ci;
      });
    } catch (e) { /* 日历加载失败不阻塞 todo 显示 */ }
    // 按 plan 分组:weekly / monthly / someday / completed
    const groups = { weekly: [], monthly: [], someday: [], completed: [] };
    items.forEach(it => {
      const key = groups[it.plan] ? it.plan : 'someday';
      groups[key].push(it);
    });
    const labels = { weekly: '📅 Weekly(按周)', monthly: '📆 Monthly(按月)', someday: '🗓 Someday', completed: '✅ 已完成' };
    let html = '';
    for (const key of ['weekly', 'monthly', 'someday', 'completed']) {
      if (groups[key].length === 0) continue;
      html += '<div class="confirmed-group"><h3 class="confirmed-group-title">' + labels[key] +
              ' <span class="count-badge">' + groups[key].length + '</span></h3>';
      html += '<div class="card-grid">' + groups[key].map(it => renderFormalTodoCard(it, calMap[it.id])).join('') + '</div></div>';
    }
    grid.innerHTML = html || '<div class="empty">暂无</div>';
  } catch (e) {
    grid.innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }
}

function renderFormalTodoCard(item, calItem) {
  // v0.4.6: 存全局 todoStore,点击时按 id 取回完整 item(替代 onclick=JSON.stringify 注入)
  if (item.id) window.todoStore.set(item.id, item);
  const doneBadge = item.done ? '<span class="tag" style="background:#dcfce7;color:#166534">✓ 已完成</span>'
                              : '<span class="tag tag-area">☐ 待办</span>';
  const period = item.period ? '<span class="tag">' + escapeHtml(item.period) + '</span>' : '';
  const time = item.estimated_time ? '<span class="tag">⏱ ' + escapeHtml(item.estimated_time) + '</span>' : '';
  const diff = item.difficulty ? '<span class="tag">' + escapeHtml(item.difficulty) + '</span>' : '';
  const source = item.source ? '<div class="muted">来源:' + escapeHtml(item.source) + '</div>' : '';
  const note = item.note ? '<div class="suggestion-body"><p>' + escapeHtml(item.note) + '</p></div>' : '';
  const itemId = escapeHtml(item.id || '');
  // 日历关联区:已加入显示日期+编辑,未加入显示「放入日历」按钮
  let calSection;
  if (calItem) {
    calSection = '<div class="todo-cal-link">' +
      '<span class="tag" style="background:#dbeafe;color:#1e40af">📅 已加入日历 · ' + escapeHtml(calItem.date) + '</span>' +
      '<button class="btn btn-sm btn-ghost" data-action="open-todo-calendar" data-todo-id="' + itemId + '" data-mode="edit">编辑</button>' +
      '</div>';
  } else {
    calSection = '<div class="action-row">' +
      '<button class="btn btn-sm btn-primary" data-action="open-todo-calendar" data-todo-id="' + itemId + '" data-mode="create">📅 放入日历</button>' +
      '</div>';
  }
  return '<div class="card suggestion-card' + (item.done ? ' card-done' : '') + '">' +
    '<div class="card-header">' + doneBadge + period + time + diff + '</div>' +
    '<h3 class="card-title">' + escapeHtml(item.title) + '</h3>' +
    source + note +
    calSection +
    '</div>';
}

// 已确认 todo 放入日历(复用统一日历表单 openCalendarEventForm)
function openTodoCalendar(todoItemOrId, mode) {
  // v0.4.6: 兼容两种入参——完整 item 对象(旧调用方)或 id 字符串(事件委托)
  // id 字符串时从全局 todoStore 取回完整 item
  let todoItem = todoItemOrId;
  if (typeof todoItemOrId === 'string') {
    todoItem = window.todoStore ? window.todoStore.get(todoItemOrId) : null;
    if (!todoItem) {
      toast('未找到 todo 数据(可能页面已刷新)', 'warning');
      return;
    }
  }
  if (mode === 'edit') {
    // 编辑模式:先查该 todo 已有的日历事项
    fetch('/api/calendar').then(r => r.json()).then(d => {
      const existing = (d.items || []).find(ci => ci.source_id === todoItem.id);
      if (!existing) { toast('未找到关联的日历事项', 'warning'); return; }
      openCalendarEventForm({
        mode: 'edit',
        entry: 'todo-edit',
        item: existing,
        onSaved: function() { loadConfirmedTodos(); },
        onDeleted: function() { loadConfirmedTodos(); },
      });
    }).catch(e => toast('加载日历失败:' + e.message, 'error'));
    return;
  }
  // 创建模式:默认标题=todo 标题,日期=今天,source_id=todo id(用于去重和回显)
  openCalendarEventForm({
    mode: 'create',
    entry: 'todo-create',
    sourceId: todoItem.id,
    sourceType: 'todo',
    sourceTitle: todoItem.title,
    defaultTitle: todoItem.title,
    defaultDate: new Date().toISOString().slice(0, 10),
    onSaved: function() { loadConfirmedTodos(); },
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
const DASH = { unread: [], read: [], readlater: [], visible: { unread: 12, read: 12, readlater: 12 } };

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
  if (!items.length) {
    const emptyMsg = {
      unread: '没有未读文章,全部已读 🎉',
      read: '还没有已读文章。打开文章详情会自动标记为已读。',
      readlater: '还没有稍后阅读的文章。在文章详情页点 📖 加入。',
    }[tab];
    grid.innerHTML = '<div class="empty">' + emptyMsg + '</div>';
    if (more) more.style.display = 'none';
    return;
  }
  grid.innerHTML = items.slice(0, vis).map(renderArticleCard).join('');
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
  // 恢复上次查看的标签(HTML 默认 unread,有会话记录则覆盖)
  const lastTab = KBState.get('kb-dash-tab', 'unread');
  if (lastTab !== 'unread') switchTab(lastTab);
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
    overview.innerHTML = `
      <div class="stat-cards">
        <div class="stat-card stat-unread"><div class="stat-num">${s.unread}</div><div class="stat-label">未读</div></div>
        <div class="stat-card stat-read"><div class="stat-num">${s.read}</div><div class="stat-label">已读</div></div>
        <div class="stat-card stat-total"><div class="stat-num">${s.total}</div><div class="stat-label">总计</div></div>
        <div class="stat-card stat-progress"><div class="stat-num">${s.progress}%</div><div class="stat-label">进度</div></div>
      </div>
      <div class="progress-bar-wrap"><div class="progress-bar" style="width:${s.progress}%"></div></div>
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
    renderPanel('unread');
    renderPanel('read');
    renderPanel('readlater');
    restoreScroll();
  } catch (e) {
    document.getElementById('grid-unread').innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }
}

/* ====================== 全局初始化 ====================== */
initTheme();
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
  } else if (sourceType === 'todo') {
    // v0.4.2: 从 todo 创建的事项默认归类为 todolist
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

  // v0.4.2: 类别选择器(预设 6 类 + 自定义)
  const CAT_PRESETS = [
    { value: 'todolist', icon: '📋', label: 'todolist', color: '#64748b' },
    { value: '会议', icon: '📅', label: '会议', color: '#2563eb' },
    { value: '财报', icon: '💰', label: '财报', color: '#16a34a' },
    { value: '截止日期', icon: '⏰', label: '截止日期', color: '#dc2626' },
    { value: '发布', icon: '🚀', label: '发布', color: '#8b5cf6' },
    { value: '其他', icon: '📌', label: '其他', color: '#d97706' },
  ];
  let selectedCategory = category || '';  // 单一真源,点击直接更新此变量
  const isPreset = CAT_PRESETS.some(p => p.value === selectedCategory);
  const catCustom = isPreset ? '' : selectedCategory;
  const catPickerHtml =
    '<div class="cal-form-field"><label>类别</label>' +
    '<div class="cal-cat-picker" id="cal-cat-picker">' +
    CAT_PRESETS.map(p =>
      '<button type="button" class="cal-cat-opt' + (selectedCategory === p.value ? ' is-selected' : '') + '" ' +
      'data-cat-value="' + p.value + '" style="--ev:' + p.color + '">' +
      '<span>' + p.icon + ' ' + p.label + '</span></button>'
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
// 详情页手动生成 Idea/Todo(v0.4.0)
// 参考 openCalendarEventForm 的表单弹窗模式:innerHTML 注入 + 自带按钮
// ---------------------------------------------------------------------------

function openGenerateDialog(kind, sourceId) {
  const isIdea = kind === 'idea';
  const title = isIdea ? '生成 Idea 列表' : '生成 Todo 列表';
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
  const todoFields = !isIdea
    ? '<div class="cal-form-field"><label>难度</label>' +
      '<select id="gen-difficulty"><option value="">不限</option>' +
      '<option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></div>' +
      '<div class="cal-form-field"><label>预计时间</label>' +
      '<select id="gen-time"><option value="">不限</option>' +
      '<option value="30min">30min</option><option value="1h">1h</option><option value="2-4h">2-4h</option>' +
      '<option value="半天">半天</option><option value="1-2 天">1-2 天</option></select></div>' +
      '<div class="cal-form-field"><label>计划</label>' +
      '<select id="gen-plan"><option value="">不限</option>' +
      '<option value="weekly">weekly</option><option value="monthly">monthly</option><option value="someday">someday</option></select></div>'
    : '';

  const formHtml =
    '<div class="cal-form">' +
    '<div class="cal-form-field"><label>引导提示词(可选)</label>' +
    '<textarea id="gen-prompt" rows="3" maxlength="500" placeholder="' + escapeHtml(promptPh) + '"></textarea></div>' +
    '<div class="cal-form-field"><label>优先级</label>' +
    '<select id="gen-priority"><option value="">不限</option>' +
    '<option value="P0">P0</option><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3</option></select></div>' +
    ideaFields + todoFields +
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
      body.plan = document.getElementById('gen-plan').value;
    }

    const url = '/api/article/' + encodeURIComponent(sourceId) +
                (isIdea ? '/generate-ideas' : '/generate-todos');
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
      const listPage = isIdea ? '/ideas' : '/todos';
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
      case 'open-todo-calendar':
        if (typeof openTodoCalendar === 'function') {
          openTodoCalendar(target.dataset.todoId, target.dataset.mode || 'edit');
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

// 全局 todo 存储(替代 onclick='openTodoCalendar(JSON.stringify(item))')
// 渲染时存,点击时取,避免在 HTML 里序列化整个对象
window.todoStore = window.todoStore || new Map();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupGlobalDelegation);
} else {
  // DOM 已就绪(脚本在 body 末尾加载时)
  setupGlobalDelegation();
}
