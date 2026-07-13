// Obsidian KB Reader —— 前端交互

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

// ===== 文章卡片 + 稍后读/收藏 toggle =====

// 渲染单张文章卡片(含稍后读/收藏 toggle 按钮)
function renderArticleCard(item) {
  const rl = item.read_later;
  const fav = item.is_favorite;
  const readInfo = item.read_count > 0
    ? `<span class="muted read-info">读过 ${item.read_count} 次${item.last_read_at ? ' · ' + String(item.last_read_at).slice(0,10) : ''}</span>`
    : '';
  const tagsHtml = (item.tags && item.tags.length > 0)
    ? item.tags.map(t => `<span class="tag tag-tag">${escapeHtml(t)}</span>`).join('')
    : '';
  const hasSummaryBadge = item.has_summary === false
    ? '<span class="tag tag-nosummary">无summary</span>'
    : '';
  return `
    <div class="card summary-card article-card" id="article-${escapeHtml(item.source_id)}">
      <a class="card-link" href="/summary/${encodeURIComponent(item.source_id)}">
        <div class="card-header">
          <span class="tag tag-${item.source_type}">${item.source_type}</span>
          ${item.area ? `<span class="tag tag-area">${item.area}</span>` : ''}
          ${hasSummaryBadge}
          ${tagsHtml}
        </div>
        <h3 class="card-title">${escapeHtml(item.title)}</h3>
        <p class="card-excerpt">${item.excerpt ? escapeHtml(item.excerpt) : '<span class="muted">(无摘要)</span>'}</p>
        <div class="card-footer">
          <span class="muted">${item.summarized_at || item.created_at || ''}</span>
          ${readInfo}
        </div>
      </a>
      <div class="card-actions">
        <button class="icon-btn ${rl ? 'active-rl' : ''}" title="稍后阅读"
          onclick="event.preventDefault();event.stopPropagation();toggleReadLater('${escapeHtml(item.source_id)}')">${rl ? '📖✓' : '📖'}</button>
        <button class="icon-btn ${fav ? 'active-fav' : ''}" title="收藏"
          onclick="event.preventDefault();event.stopPropagation();toggleFavorite('${escapeHtml(item.source_id)}')">${fav ? '⭐✓' : '⭐'}</button>
        <button class="icon-btn icon-btn-danger" title="删除"
          onclick="event.preventDefault();event.stopPropagation();deleteArticle('${escapeHtml(item.source_id)}')">🗑</button>
      </div>
    </div>
  `;
}

// 刷新当前页面数据(根据页面调对应函数)
function refreshCurrentPage() {
  if (typeof loadDashboard === 'function') loadDashboard();
  else if (typeof loadRecent === 'function') loadRecent();
  else if (typeof loadFavorites === 'function') loadFavorites();
}

// 彻底删除文章
async function deleteArticle(sourceId) {
  if (!confirm('确认彻底删除?这将删除 source note、summary、raw_text 和相关候选,不可恢复。')) return;
  if (!confirm('再次确认:真的要删除这篇文章吗?此操作不可撤销。')) return;
  try {
    const res = await fetch(`/api/article/${sourceId}`, {method: 'DELETE'});
    const data = await res.json();
    if (!res.ok) { alert('删除失败:' + (data.detail || '')); return; }
    // 如果在详情页,删完回首页;否则刷新当前列表
    if (window.location.pathname.startsWith('/summary/')) {
      window.location.href = '/';
    } else {
      refreshCurrentPage();
    }
  } catch (e) { alert('网络错误:' + e.message); }
}

// 切换稍后阅读
async function toggleReadLater(sourceId) {
  try {
    const res = await fetch(`/api/article/${sourceId}/read-later`, {method: 'POST'});
    const data = await res.json();
    if (!res.ok) { alert('操作失败:' + (data.detail || '')); return; }
    if (typeof loadDashboard === 'undefined') updateDetailButtons('read_later', data.read_later);
    else refreshCurrentPage();
  } catch (e) { alert('网络错误:' + e.message); }
}

// 切换收藏
async function toggleFavorite(sourceId) {
  try {
    const res = await fetch(`/api/article/${sourceId}/favorite`, {method: 'POST'});
    const data = await res.json();
    if (!res.ok) { alert('操作失败:' + (data.detail || '')); return; }
    if (typeof loadDashboard === 'undefined') updateDetailButtons('is_favorite', data.is_favorite);
    else refreshCurrentPage();
  } catch (e) { alert('网络错误:' + e.message); }
}

// 详情页按钮更新(不重载)
function updateDetailButtons(field, value) {
  const btn = document.querySelector(`.detail-action-btn[data-field="${field}"]`);
  if (!btn) return;
  btn.classList.toggle('active-rl', field === 'read_later' && value);
  btn.classList.toggle('active-fav', field === 'is_favorite' && value);
  if (field === 'read_later') btn.textContent = value ? '📖✓ 已加入稍后读' : '📖 稍后阅读';
  if (field === 'is_favorite') btn.textContent = value ? '⭐✓ 已收藏' : '⭐ 收藏';
}

// status 徽章 class 映射
function statusBadgeClass(status) {
  if (!status) return 'status-pending_review';
  return 'status-' + status;
}

// status 中文显示
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

// 加载 idea/todo 候选
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

// 渲染单张 idea/todo 卡片
function renderSuggestionCard(item, type) {
  const f = item.fields || {};
  const status = item.status;
  const isAccepted = status && status.startsWith('accepted_');
  const isMoved = status === 'moved';

  // 操作按钮(只有 pending_review 才能接受)
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

  // 字段表(idea 和 todo 字段不同)
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

// 简单格式化 suggestion body(markdown 子集)
function formatSuggestionBody(body) {
  let html = escapeHtml(body);
  // ### 标题
  html = html.replace(/^###\s+(.+)$/gm, '<h4>$1</h4>');
  // 空行
  html = html.replace(/\n\n+/g, '</p><p>');
  return '<p>' + html + '</p>';
}

// 改 status,调 API
async function updateStatus(type, itemId, newStatus, btn) {
  if (!confirm(`确认将状态改为「${statusLabel(newStatus)}」?`)) return;
  // 禁用当前卡片的按钮
  const card = document.getElementById('card-' + itemId);
  if (card) {
    card.querySelectorAll('button').forEach(b => b.disabled = true);
  }
  try {
    const res = await fetch(`/api/${type}/${itemId}/status`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: newStatus}),
    });
    const data = await res.json();
    if (!res.ok) {
      alert('修改失败:' + (data.detail || '未知错误'));
      if (card) card.querySelectorAll('button').forEach(b => b.disabled = false);
      return;
    }
    // 重新加载整页卡片(简单可靠)
    loadSuggestions(type);
  } catch (e) {
    alert('网络错误:' + e.message);
    if (card) card.querySelectorAll('button').forEach(b => b.disabled = false);
  }
}
