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
            onchange="toggleSelect(this, '${sid}')"${selectedIds.has(sid) ? ' checked' : ''}>
        </label>
        <span class="tag tag-${item.source_type}">${item.source_type}</span>
      </div>
      <a class="card-link" href="/summary/${encodeURIComponent(item.source_id)}">
        <h3 class="card-title">${escapeHtml(item.title)}</h3>
        <p class="card-excerpt">${item.excerpt ? escapeHtml(item.excerpt) : '<span class="muted">(无摘要)</span>'}</p>
        <div class="card-footer">
          <span>${item.summarized_at || item.created_at || ''}</span>
          ${readInfo}
        </div>
      </a>
      <div class="card-actions">
        <button class="icon-btn ${rl ? 'active-rl' : ''}" title="稍后阅读" aria-label="稍后阅读"
          onclick="event.preventDefault();event.stopPropagation();toggleReadLater('${sid}')">${rl ? '📖✓' : '📖'}</button>
        <button class="icon-btn ${fav ? 'active-fav' : ''}" title="收藏" aria-label="收藏"
          onclick="event.preventDefault();event.stopPropagation();toggleFavorite('${sid}')">${fav ? '⭐✓' : '⭐'}</button>
        <button class="icon-btn icon-btn-danger" title="删除" aria-label="删除文章"
          onclick="event.preventDefault();event.stopPropagation();deleteArticle('${sid}')">🗑</button>
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
    if (type === 'idea') {
      actions = `
        <button class="btn btn-accept" onclick="updateStatus('idea','${escapeHtml(item.id)}','accepted_research',this)">接受·科研</button>
        <button class="btn btn-accept" onclick="updateStatus('idea','${escapeHtml(item.id)}','accepted_productivity',this)">接受·效率</button>
        <button class="btn btn-ghost" onclick="updateStatus('idea','${escapeHtml(item.id)}','rejected',this)">拒绝</button>
      `;
    } else {
      actions = `
        <button class="btn btn-accept" onclick="updateStatus('todo','${escapeHtml(item.id)}','accepted_weekly',this)">本周</button>
        <button class="btn btn-accept" onclick="updateStatus('todo','${escapeHtml(item.id)}','accepted_monthly',this)">本月</button>
        <button class="btn btn-accept" onclick="updateStatus('todo','${escapeHtml(item.id)}','accepted_someday',this)">someday</button>
        <button class="btn btn-ghost" onclick="updateStatus('todo','${escapeHtml(item.id)}','rejected',this)">拒绝</button>
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
  if (!await confirmModal(`确认将状态改为「${statusLabel(newStatus)}」?`)) return;
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
    loadSuggestions(type);
  } catch (e) {
    toast('网络错误:' + e.message, 'error');
    if (card) card.querySelectorAll('button').forEach(b => b.disabled = false);
  }
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
}

async function initDashboard() {
  // 标签切换
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));
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
  } catch (e) {
    document.getElementById('grid-unread').innerHTML = '<div class="error">加载失败:' + escapeHtml(e.message) + '</div>';
  }
}

/* ====================== 全局初始化 ====================== */
initTheme();
initNav();
initModalOverlay();
