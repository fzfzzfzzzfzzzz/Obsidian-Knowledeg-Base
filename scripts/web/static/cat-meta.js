/**
 * cat-meta.js —— 全站共享的「类别元数据」单一数据源(Single Source of Truth)。
 *
 * 历史:此映射曾在 calendar.html(CAT_META)、events.html(EV_CAT_META)、
 * workspace.html(CAT_ICON/CAT_COLOR)、app.js(CAT_PRESETS)重复定义 4 份,
 * 导致维护时容易漏改 / 颜色不一致(v0.4.16 曾出现"会议"色值 #3b82f6 vs #2563eb 不一致)。
 * 现统一到这里,所有页面/脚本引用同一份。
 *
 * 设计:
 *   - KB_CATEGORIES:类别 → {icon, color, label} 的有序映射
 *   - KB_CAT_ORDER:类别顺序(用于选择器/筛选条的展示顺序)
 *   - catColor(cat):取类别颜色,未知类别回退"其他"色
 *   - catIcon(cat):返回 <i data-lucide> 标签字符串(杜绝裸拼 iconName 导致图标名以文字显示)
 *   - catLabel(cat):取类别显示名
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

  global.KB_CATEGORIES = KB_CATEGORIES;
  global.KB_CAT_ORDER = KB_CAT_ORDER;
  global.catColor = catColor;
  global.catLabel = catLabel;
  global.catIcon = catIcon;
  global.catPresets = catPresets;
})(window);
