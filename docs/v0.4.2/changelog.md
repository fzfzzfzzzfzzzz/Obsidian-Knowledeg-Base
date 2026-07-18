# Changelog v0.4.2

> 日期:2026-07-18

## 新增

### 1. 日历「时间轴」视图(垂直 + 水平)
- **第三个视图**:日历页工具栏在「月视图 / 列表视图」后新增「时间轴」,与现有两个视图并列切换
- **按日期分组**:同一日期的事项聚到同一节点下,日期升序排列;当天节点高亮「今天」标签
- **垂直布局**:左侧竖线 + 圆点节点,事项挂在右侧;默认布局,移动端友好
- **水平布局**:横向滚动,日期作为列标题,事项竖向堆叠;适合看整体时间跨度
- **布局切换持久化**:垂直/水平选择存 `sessionStorage`,刷新页面保留
- **类别着色 + 图标**:每条事项按 category 显示颜色与 emoji(📋/📅/💰/⏰/🚀/📌)

### 2. category 字段 + 标签筛选条(全局)
- **事件类别字段**:`CalendarItem` 新增 `category` 字段,6 个预设类别:
  - 📋 `todolist`(灰) · 📅 `会议`(蓝) · 💰 `财报`(绿) · ⏰ `截止日期`(红) · 🚀 `发布`(紫) · 📌 `其他`(琥珀)
- **自定义类别**:表单支持自由输入,存储原值,前端按字符串 hash 取稳定颜色
- **筛选条**:日历顶部新增「显示类别」chip 行,点击 chip 显示/隐藏该类事项
- **全局生效**:筛选影响 **全部三个视图**(月视图 / 列表视图 / 时间轴),状态存 `sessionStorage`,切换视图时保留
- **一键全选**:筛选条右侧「全选」按钮恢复显示所有类别
- **向后兼容**:旧事项无需迁移,GET 接口运行时按 `source_type` 回填 category(`todo → todolist`,其余 → `其他`),**不写盘**

### 3. 表单类别选择
- **新建/编辑表单加类别选择器**:`openCalendarEventForm` 在「日期」字段后插入 chip 单选组 + 自定义输入框
- **单选互斥**:选预设清空自定义,反之清空预设选中
- **编辑模式预填**:匹配预设则选对应 radio,否则填到自定义输入
- **Todo 默认归类**:从 todo 创建的事项默认 `category = todolist`

## 不变
- review 队列、accept/reject 流程不变
- 正式清单文件格式、todo 确定性 id 算法不改
- 单条/批量/图片投稿流程不受影响
- 月视图/列表视图既有交互(月份切换、列表筛选、删除、编辑弹窗)保持
- 文章详情页日历功能(检测日期路径)不受影响,但新建的事项可带 category

## 文件改动
- `kb_web.py`:`CalendarItemCreate` / `CalendarItemUpdate` 加 `category` 字段;POST 创建落库;PATCH 更新(`None = 不改`);新增 `_resolve_category()`;GET 列表 / GET 单个 / POST 响应 / PATCH 响应运行时回填 category(磁盘留空,仅响应填值)
- `calendar.html`:工具栏加「时间轴」视图按钮 + 容器;顶部加筛选条;JS 加 `CAT_META` / `catColor` / `catIcon` / `resolveCategory` / `collectCategories` / `rebuildFilterBar` / `onFilterChange` / `applyFilter` / `renderTimeline` / `switchTimeline` / `fmtDateLabel` / `fmtWeekday`;月视图 / 列表视图改用 category 着色 + `applyFilter` 过滤;初始化恢复时间轴布局偏好
- `app.js`:`openCalendarEventForm` 加 category 选择器(`CAT_PRESETS` / `catPickerHtml` / `catCustomInput`)+ `readCategory()` 读取逻辑 + radio/自定义互斥交互;POST/PATCH body 加 `category`;todo 来源创建默认 `category = todolist`
- `style.css`:新增 `--cat-*` 令牌(浅色 + 暗色主题各 6 个);新增 `.cal-filter-bar` / `.cal-chip` / `.cal-timeline-view` / `.tl-vertical` / `.tl-node` / `.tl-item` / `.tl-horizontal` / `.cal-cat-picker` / `.cal-cat-opt` 样式
- `base.html`:cache buster 递增(`style.css?v=23`、`app.js?v=24`)
- `tests/`:新增 `test_calendar_category.py`(7 用例)+ 扩展 `test_todo_calendar_link.py`(+1 断言)

## 测试
- 全量 94 个测试通过,零回归(v0.4.1 是 74,本版本 +20)
