# v0.4.2 任务清单

> 日期:2026-07-18
> PRD 见 `v042_features_PRD.md`,changelog 见 `changelog.md`

## 0. 文档范围

三个功能:① category 字段(数据基础)② 标签筛选条(全局)③ 时间轴视图(垂直+水平)。外加表单类别选择 + 文档。

## P0(必须)

### 后端
- [x] `CalendarItemCreate` 加 `category: str = ""`
- [x] `CalendarItemUpdate` 加 `category: str | None = None`
- [x] POST 创建落库 `category`(空串保留)
- [x] PATCH 更新 category(`None = 不改`)
- [x] 新增 `_resolve_category(item)` 辅助函数
- [x] GET `/api/calendar` 运行时回填 category(不写盘)
- [x] GET `/api/calendar/{id}` 运行时回填
- [x] POST 响应回填 category
- [x] PATCH 响应回填 category

### 前端 - calendar.html
- [x] 工具栏加「时间轴」视图按钮 + 容器
- [x] 加筛选条容器 `cal-filter-bar` + `cal-filter-chips`
- [x] JS 加 `CAT_META` / `catColor` / `catIcon` / `resolveCategory`
- [x] JS 加 `collectCategories` / `rebuildFilterBar` / `onFilterChange` / `applyFilter`
- [x] JS 加 `renderTimeline` / `switchTimeline` / `fmtDateLabel` / `fmtWeekday`
- [x] 月视图改用 category 着色 + `applyFilter`
- [x] 列表视图改用 category 着色 + `applyFilter` + category pill
- [x] 初始化恢复时间轴布局偏好(`KBState.get('kb-cal-tl-orient')`)
- [x] 筛选状态持久化(`KBState.set('kb-cal-filters')`)
- [x] 「全选」按钮逻辑

### 前端 - app.js
- [x] `openCalendarEventForm` 读取 `opts.item.category`(编辑)
- [x] Todo 来源创建默认 `category = todolist`
- [x] 加 `CAT_PRESETS` / `catPickerHtml`
- [x] 表单插入类别选择器(6 预设 + 自定义输入)
- [x] radio / 自定义输入互斥交互
- [x] `readCategory()` 读取逻辑
- [x] POST body 加 `category`
- [x] PATCH body 加 `category`

### 样式 - style.css
- [x] 浅色主题加 `--cat-*` 令牌(6 个)
- [x] 暗色主题加 `--cat-*` 覆盖(6 个)
- [x] `.cal-filter-bar` / `.cal-chip` / `.cal-chip-dot` / `.cal-chip-off`
- [x] `.cal-filter-clear`
- [x] `.cal-timeline-view` / `.cal-timeline-subtabs` / `.cal-timeline-scroll`
- [x] `.tl-vertical` + 竖线 `::before` + 节点圆点
- [x] `.tl-node` / `.tl-date` / `.tl-weekday` / `.tl-today-tag`
- [x] `.tl-item` / `.tl-item-icon` / `.tl-item-body` / `.tl-item-title` / `.tl-item-meta` / `.tl-item-cat`
- [x] `.tl-horizontal-scroll` / `.tl-horizontal` + 水平节点样式
- [x] `.cal-cat-picker` / `.cal-cat-opt` / `.cal-cat-custom`

### base.html
- [x] `style.css?v` 递增
- [x] `app.js?v` 递增

## P1(完成 / 验证)

### 测试
- [x] 新建 `test_calendar_category.py`(7 用例)
- [x] 扩展 `test_todo_calendar_link.py`(+1 断言)
- [x] 全量测试通过(94 个,零回归)
- [x] 页面渲染冒烟测试(关键元素都在)

### 文档
- [x] `changelog.md`
- [x] `v042_features_PRD.md`
- [x] `v042_features_checklist.md`(本文件)
- [x] 更新 `docs/ROADMAP.md`(版本号 + 日期)

## 设计决策备忘
- **category 回填不写盘**:保护用户已有数据,旧事项无需迁移。GET 运行时计算,POST/PATCH 响应也回填(前端拿到的总是已 resolve 的值),但磁盘留空。
- **筛选默认全选**:`activeFilters === null` 时初始化为全选;持久化空数组被视为「未初始化」(避免显示空白页)。
- **颜色按 category 而非 source_type**:用户感知的是事件类别,不是来源平台,视觉更直观。source_type 字段保留供去重/关联用。
- **时间轴两种布局**:垂直默认(移动端友好),水平适合看跨度;布局选择持久化但不过度复杂化。
