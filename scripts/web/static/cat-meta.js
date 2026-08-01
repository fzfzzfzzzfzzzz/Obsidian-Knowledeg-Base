/**
 * cat-meta.js —— 全站共享的「类别元数据」单一数据源(Single Source of Truth)。
 *
 * 历史:此映射曾在 calendar.html(CAT_META)、events.html(EV_CAT_META)、
 * workspace.html(CAT_ICON/CAT_COLOR)、app.js(CAT_PRESETS)重复定义 4 份,
 * 导致维护时容易漏改 / 颜色不一致(v0.4.16 曾出现"会议"色值 #3b82f6 vs #2563eb 不一致)。
 * 现统一到这里,所有页面/脚本引用同一份。
 *
 * 本文件同时管两套类别(详见 AGENTS.md「Shared Category Metadata」):
 *   - 事件 / 日历类别(会议/财报/截止日期/发布/比赛/todolist/其他):
 *       KB_CATEGORIES / KB_CAT_ORDER / catColor / catIcon / catLabel / catPresets
 *   - 任务类别(开发/科研/个人/金融/工作/其他):
 *       KB_TASK_CATEGORIES / KB_TASK_CAT_ORDER / taskCatColor / taskCatIcon / taskCatLabel / taskCatPresets
 *
 * 两套保持独立,因为它们是不同集合,且「其他」配色不同(事件=#d97706,任务=#8b5cf6)。
 *
 * 设计:
 *   - 每个类别含 icon(Lucide 名) / color / label。
 *   - xxxColor(cat):取类别颜色,未知类别回退"其他"色。
 *   - xxxIcon(cat):返回 <i data-lucide> 标签字符串(杜绝裸拼 iconName 导致图标名以文字显示)。
 *   - xxxLabel(cat):取类别显示名。
 */
(function (global) {
  'use strict';

  // 单一数据源:加新类别只改这一处
  var KB_CATEGORIES = {
    'todolist':  { icon: 'list',         color: '#64748b', label: 'todolist' },
    '会议':      { icon: 'users',        color: '#2563eb', label: '会议' },
    '财报':      { icon: 'trending-up',  color: '#16a34a', label: '财报' },
    '截止日期':  { icon: 'alarm-clock',  color: '#dc2626', label: '截止日期' },
    '发布':      { icon: 'rocket',       color: '#8b5cf6', label: '发布' },
    '比赛':      { icon: 'trophy',       color: '#0d9488', label: '比赛' },
    '其他':      { icon: 'pin',          color: '#d97706', label: '其他' }
  };

  var KB_CAT_ORDER = ['todolist', '会议', '财报', '截止日期', '发布', '比赛', '其他'];

  var DEFAULT_CAT = '其他';

  function meta(cat) {
    return KB_CATEGORIES[cat] || KB_CATEGORIES[DEFAULT_CAT];
  }

  /**
   * 取类别颜色。已知类别用预设色;未知/自定义类别基于字符串 hash 取一个稳定颜色
   * (这样用户自定义的类别也有固定配色,不会每次刷新变)。
   */
  function catColor(cat) {
    if (KB_CATEGORIES[cat]) return KB_CATEGORIES[cat].color;
    if (!cat) return KB_CATEGORIES[DEFAULT_CAT].color;
    // 自定义类别:稳定 hash 取色
    var h = 0;
    for (var i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) | 0;
    var palette = ['#0ea5e9', '#9333ea', '#ea580c', '#0d9488', '#be185d', '#4f46e5', '#65a30d'];
    return palette[Math.abs(h) % palette.length];
  }

  function catLabel(cat) {
    return meta(cat).label;
  }

  /**
   * 返回 <i data-lucide="..."> 标签字符串。
   * 这是防裸拼的关键:所有图标渲染必须走这个函数,
   * 保证图标名始终包在 <i data-lucide> 里(lucide.createIcons() / MutationObserver 才能识别)。
   * 绝不要直接拼 '<span>'+iconName+'</span>' —— 那会让图标名以文字显示。
   */
  function catIcon(cat) {
    var name = meta(cat).icon;
    return '<i data-lucide="' + name + '"></i>';
  }

  // 兼容 app.js 的 CAT_PRESETS 格式(数组)
  function catPresets() {
    return KB_CAT_ORDER.map(function (cat) {
      var m = KB_CATEGORIES[cat];
      return { value: cat, icon: m.icon, label: m.label, color: m.color };
    });
  }

  /* ============================================================
   * 任务类别(开发/科研/个人/金融/工作/其他)
   * 与事件类别独立维护(两套不同集合,「其他」配色不同)。
   * 配色沿用 tasks.html 历史值;图标为本次新增分配。
   * 单一数据源:tasks.html / task_detail.html / task_edit.html 都读这里。
   * ============================================================ */
  var KB_TASK_CATEGORIES = {
    '开发': { icon: 'code',           color: '#2563eb', label: '开发' },
    '科研': { icon: 'flask-conical',  color: '#16a34a', label: '科研' },
    '个人': { icon: 'user',           color: '#d97706', label: '个人' },
    '金融': { icon: 'dollar-sign',    color: '#ca8a04', label: '金融' },
    '工作': { icon: 'briefcase',      color: '#0891b2', label: '工作' },
    '其他': { icon: 'circle',         color: '#8b5cf6', label: '其他' }
  };
  var KB_TASK_CAT_ORDER = ['开发', '科研', '个人', '金融', '工作', '其他'];
  var DEFAULT_TASK_CAT = '其他';

  function taskMeta(cat) {
    return KB_TASK_CATEGORIES[cat] || KB_TASK_CATEGORIES[DEFAULT_TASK_CAT];
  }

  // 未知/自定义任务类别:稳定 hash 取色(与事件 catColor 同款算法,独立 palette)
  function taskCatColor(cat) {
    if (KB_TASK_CATEGORIES[cat]) return KB_TASK_CATEGORIES[cat].color;
    if (!cat) return KB_TASK_CATEGORIES[DEFAULT_TASK_CAT].color;
    var h = 0;
    for (var i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) | 0;
    var palette = ['#0ea5e9', '#9333ea', '#ea580c', '#0d9488', '#be185d', '#4f46e5', '#65a30d'];
    return palette[Math.abs(h) % palette.length];
  }

  function taskCatLabel(cat) {
    return taskMeta(cat).label;
  }

  function taskCatIcon(cat) {
    return '<i data-lucide="' + taskMeta(cat).icon + '"></i>';
  }

  function taskCatPresets() {
    return KB_TASK_CAT_ORDER.map(function (cat) {
      var m = KB_TASK_CATEGORIES[cat];
      return { value: cat, icon: m.icon, label: m.label, color: m.color };
    });
  }

  /* ============================================================
   * 任务状态元数据(active / done / blocked / archived)
   *
   * 与上面的「任务类别」是两个不同维度,别混淆:
   *   - 类别 = 开发/科研/个人 等**业务分类**(KB_TASK_CATEGORIES)
   *   - 状态 = active/done/blocked/archived **生命周期阶段**(本表)
   *
   * 历史:状态徽章配色曾在 tasks.html(TK_STATUS_META)、task_detail.html
   * (TK_DETAIL_STATUS)、task_edit.html(TK_STATUS_LABEL)、workspace.html
   * (TK_STATUS_META)、market.html(MK_STATUS_META)、app.js(TK_STATUS_META)
   * 各自重复定义 6 份,色值一致但维护时要 grep 6 个文件。现统一到这里。
   * 单一数据源:所有页面/脚本引用同一份。
   *
   * 设计:与类别元数据同构,每个状态含 icon(Lucide 名)/ color / label。
   * ============================================================ */
  var KB_TASK_STATUS = {
    'active':   { icon: 'loader',  color: '#2563eb', label: '进行中' },
    'done':     { icon: 'check',   color: '#15803d', label: '已完成' },
    'blocked':  { icon: 'ban',     color: '#b91c1c', label: '阻塞' },
    'archived': { icon: 'archive', color: '#64748b', label: '已归档' }
  };
  var KB_TASK_STATUS_ORDER = ['active', 'done', 'blocked', 'archived'];
  var DEFAULT_TASK_STATUS = 'active';

  function taskStatusMeta(status) {
    return KB_TASK_STATUS[status] || KB_TASK_STATUS[DEFAULT_TASK_STATUS];
  }

  function taskStatusColor(status) {
    return taskStatusMeta(status).color;
  }

  function taskStatusLabel(status) {
    return taskStatusMeta(status).label;
  }

  function taskStatusIcon(status) {
    return '<i data-lucide="' + taskStatusMeta(status).icon + '"></i>';
  }

  // 状态选择器选项(供 task 表单的 <select> 用),按固定语义顺序
  function taskStatusOptions(selected) {
    return KB_TASK_STATUS_ORDER.map(function (s) {
      return '<option value="' + s + '"' + (s === selected ? ' selected' : '') + '>'
        + KB_TASK_STATUS[s].label + '</option>';
    }).join('');
  }

  global.KB_CATEGORIES = KB_CATEGORIES;
  global.KB_CAT_ORDER = KB_CAT_ORDER;
  global.catColor = catColor;
  global.catLabel = catLabel;
  global.catIcon = catIcon;
  global.catPresets = catPresets;
  global.KB_TASK_CATEGORIES = KB_TASK_CATEGORIES;
  global.KB_TASK_CAT_ORDER = KB_TASK_CAT_ORDER;
  global.taskCatColor = taskCatColor;
  global.taskCatLabel = taskCatLabel;
  global.taskCatIcon = taskCatIcon;
  global.taskCatPresets = taskCatPresets;
  global.KB_TASK_STATUS = KB_TASK_STATUS;
  global.KB_TASK_STATUS_ORDER = KB_TASK_STATUS_ORDER;
  global.taskStatusColor = taskStatusColor;
  global.taskStatusLabel = taskStatusLabel;
  global.taskStatusIcon = taskStatusIcon;
  global.taskStatusOptions = taskStatusOptions;
})(window);
