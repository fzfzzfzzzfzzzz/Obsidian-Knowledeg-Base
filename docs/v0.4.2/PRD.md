# v0.4.2 功能 PRD:日历时间轴视图 + 标签筛选 + category 字段

> 日期:2026-07-18
> 上一版:v0.4.1(见 `docs/v0.4.1/`)

## 0. 文档定位

本 PRD 描述 v0.4.2 三个相互关联的小功能,共同服务于一个目标:**让日历界面能按时间线纵览所有事项,并按事件类别(todolist / 会议 / 财报发布…)筛选显示**。具体实现细节见 `changelog.md`,任务清单见 `v042_features_checklist.md`。

### 范围内
- 日历页新增「时间轴」视图(垂直 + 水平两种布局)
- `CalendarItem` 新增 `category` 字段 + 表单选择
- 全局标签筛选条(影响月/列表/时间轴三个视图)
- 向后兼容旧事项(运行时回填)

### 范围外
- 不改 review 队列、投稿、正式清单解析逻辑
- 不引入新的外部 LLM 依赖
- 不修改 calendar.json 的磁盘 schema(只在运行时为响应加 category 字段)
- 不实现按 category 自动归类智能推断(类别由用户在表单选)

---

## 1. 功能:category 字段(数据基础)

### 目标
让日历事项能按「事件类别」归类(而非只有「来源平台」`source_type`),为筛选/着色/时间轴分组提供统一维度。

### 预设类别(6 种)

| category | 图标 | 颜色 | 语义 |
|---|---|---|---|
| `todolist` | 📋 | `#64748b` 灰 | 来自 todo 的待办 |
| `会议` | 📅 | `#2563eb` 蓝 | 会议/大会(WAIC、AAAI…) |
| `财报` | 💰 | `#16a34a` 绿 | 财报/季报发布 |
| `截止日期` | ⏰ | `#dc2626` 红 | 投稿/提交 deadline |
| `发布` | 🚀 | `#8b5cf6` 紫 | 产品/版本发布 |
| `其他` | 📌 | `#d97706` 琥珀 | 默认/未分类 |

**自定义**:表单可自由输入非预设值,存储原值,前端按字符串 hash 取稳定颜色。

### 数据模型
- `CalendarItemCreate` 加 `category: str = ""`
- `CalendarItemUpdate` 加 `category: str | None = None`(`None = 不改`)
- POST 创建时落库 `category`(空串 = 不指定)
- PATCH 更新时写库

### 向后兼容(关键设计)
旧事项磁盘上没有 `category` 字段。采用**运行时回填,不写盘**策略:

```python
def _resolve_category(item):
    if item.get("category"):
        return item["category"]
    return "todolist" if item.get("source_type") == "todo" else "其他"
```

- GET 列表 / GET 单个 / POST 响应 / PATCH 响应都调用此函数
- **磁盘存储保持原值**(空串),避免改动用户已有数据
- 这样旧事项无需迁移脚本也能被筛选/着色

### 验收
- POST 带 category 落库正确,响应回填
- POST 不带 category 落库空串,GET 回填「其他」
- source_type=todo 且无 category → 回填「todolist」
- PATCH 改 category 成功
- PATCH 不带 category 字段 → 不改原值

---

## 2. 功能:标签筛选条(全局)

### 目标
用户能选择显示/隐藏某类事项。例如隐藏「财报」后,月视图/列表/时间轴都不显示财报类。

### UI
- 位置:日历页 `page-title` 下方,工具栏上方(独立一行)
- 形式:chip 行,每个 chip = 一个 category,前面一个色点 + 图标 + 文字
- 默认全选(所有 chip 高亮);取消勾选的 chip 灰显 + 删除线
- 右侧「全选」按钮:一键恢复全部显示

### 类别集合
- 预设 6 类始终显示
- 自定义类别:扫描当前事项,实际出现的自定义类也加 chip

### 筛选逻辑
- 全局 `activeFilters: Set<category>`(null = 未初始化)
- `applyFilter(items)`:`items.filter(i => activeFilters.has(resolveCategory(i)))`
- chip change → 更新 `activeFilters` → 重渲染当前视图(月/列表/时间轴)
- 状态存 `sessionStorage`(`kb-cal-filters`),刷新保留

### 影响范围
- **月视图**:`dayItems` 过滤;`+N 更多` 计数基于过滤后
- **列表视图**:upcoming/past/all 三档都先 `applyFilter` 再过滤日期
- **时间轴**:分组前先过滤

### 验收
- 取消某类 chip,三个视图都不显示该类
- 「全选」按钮恢复所有类别
- 刷新页面后筛选状态保留
- 自定义类别也出现在筛选条

---

## 3. 功能:时间轴视图(垂直 + 水平)

### 目标
用时间线/时间轴的表达方式纵览所有事项,适合看时间跨度和事项排序。

### 入口
日历页工具栏第三档「时间轴」,与「月视图 / 列表视图」并列切换。

### 布局一:垂直(默认)
```
7月 2026
│
●── 16日 周四 ────────────────
│      📅 WAIC 大会         [会议]
│      📌 产品评审          [其他]
│
●── 21日 周二 ────────────────  ← 今天(节点填充)
│      ⏰ AAAI 摘要截止     [截止日期]
│
●── 28日 周二 ────────────────
       💰 Q2 财报发布        [财报]
```

- 左侧竖线贯穿,每个日期是一个节点(圆点)
- 当天节点填充高亮 + 日期标题变色 + 「今天」标签
- 节点下挂该日所有事项(按 category 着色 + 图标)
- 事项卡左侧 3px 颜色边 + 右侧 category pill

### 布局二:水平
```
┌────────┬────────┬────────┐
│ 16日   │ 21日   │ 28日   │
│ 周四   │ 周二   │ 周二   │   ← 列头(下边框)
├────────┼────────┼────────┤
│📅 WAIC │⏰ AAAI │💰 Q2   │
│📌 评审 │  摘要  │  财报  │
└────────┴────────┴────────┘
        ← 横向滚动 →
```

- flex 横向排列,每列 `min-width: 200px`
- 日期作为列标题,下方横线分隔
- 列内事项竖向堆叠
- 整体横向可滚

### 布局切换
- 顶部「垂直 / 水平」分段控件
- 默认垂直;选择存 `sessionStorage`(`kb-cal-tl-orient`)
- 切换不重新拉数据,只重渲染

### 数据
- 复用 `applyFilter(allItems)`,与月/列表一致
- 按日期分组(`groups[date] = [items]`),日期升序
- 每个事项可点击编辑(复用 `openEditDialog`)

### 验收
- 时间轴显示所有过滤后事项,按日期升序分组
- 垂直/水平布局切换正确
- 当天节点高亮
- 布局选择刷新后保留
- 事项点击进入编辑
- 无事项时显示空状态

---

## 4. 表单改动:类别选择

### 目标
新建/编辑事项时可选 category。

### UI
`openCalendarEventForm` 在「日期」字段后插入:
- 6 个预设 chip(单选 radio,带图标 + 文字 + 选中态用 `--ev` 边框)
- 一个自定义输入框(选中预设时清空,反之清空预设)

### 交互
- 单选互斥:选预设 → 清空自定义;输入自定义 → 清空预设选中
- 编辑模式:匹配预设则预选对应 radio,否则填到自定义输入
- Todo 来源创建:默认 `category = todolist`(用户可改)

### 保存
- POST/PATCH body 加 `category` 字段
- 读取逻辑:`readCategory()` 优先自定义输入,否则选中的预设,否则空串

### 验收
- 选预设保存后 category 正确
- 输入自定义保存后原值存储
- 编辑现有事项预填正确
- radio 与自定义互斥正常

---

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `scripts/kb_web.py` | `CalendarItemCreate`/`Update` 加 category;POST/PATCH 落库;`_resolve_category`;GET/响应回填 |
| `scripts/web/templates/calendar.html` | 时间轴视图按钮+容器;筛选条;JS 新增 `CAT_META`/`renderTimeline`/`switchTimeline`/`applyFilter` 等 |
| `scripts/web/static/app.js` | `openCalendarEventForm` 加 category 选择器 + 保存逻辑 |
| `scripts/web/static/style.css` | `--cat-*` 令牌;`.cal-filter-bar`/`.cal-chip`/`.tl-*`/`.cal-cat-picker` 样式 |
| `scripts/web/templates/base.html` | cache buster 递增 |
| `scripts/tests/test_calendar_category.py` | 新建,7 用例 |
| `scripts/tests/test_todo_calendar_link.py` | +1 断言(todo 回填 todolist) |

## 整体验收
1. 不覆盖已有用户数据(category 空时回填不写盘)
2. 时间轴垂直/水平可切换,样式正确
3. 筛选条影响月/列表/时间轴三视图,状态持久化
4. 新建/编辑表单可选 category,旧事项自动归类
5. 全量 94 测试通过,零回归
