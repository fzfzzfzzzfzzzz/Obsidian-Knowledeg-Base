# v0.4.1 三项增量功能｜PRD

## 0. 文档定位

本文档是 v0.4.0 之后的增量 PRD,覆盖三项功能:

1. **投稿页批量投稿**(从 md 文件 / 粘贴文本提取 URL)
2. **Idea / Todo 页拆分「待定 / 已确定」子界面**
3. **已确认 Todo → 日历链接**

除本文明确修改的规则外,v0.1~v0.4.0 的所有功能(采集、总结、review 队列、accept 流程、日历 CRUD、手动生成 idea/todo)保持不变。本文不重复定义上述功能。

对应 changelog 见 `docs/v0.4.1/changelog.md`。

---

## 功能一:投稿页批量投稿

### 1.1 目标

在投稿页(`/submit`)新增「📦 批量投稿」panel,支持三种输入入口,自动提取所有 URL,只入库不生成 summary。

### 1.2 三种输入入口

| 入口 | 说明 |
|---|---|
| 拖拽区 | 拖入 `.md` / `.markdown` / `.txt` 文件(支持多个) |
| 文件选择 | 点击拖拽区或按钮,弹出文件选择(`accept=".md,.markdown,.txt"`,multiple) |
| 粘贴文本 | 一个 textarea,粘贴任意文本(paste / input 事件实时提取 URL) |

### 1.3 URL 提取与编辑

- 正则:`https?://[^\s<>"']+`(与后端 `kb_llm._extract_url` 一致)
- 自动去重:`new Set(...)` 去重
- **可编辑列表**:每个 URL 一行,默认勾选,支持取消勾选 / 单条删除(✕)/ 全选 / 全不选 / 清空
- 提取后 toast 提示「从文件提取 N 个 URL,新增 M 个」

### 1.4 提交

- 复用现有 `POST /api/ingest`,body `{items: [url...], auto_summary: false}`
- `auto_summary` 固定为 false(批量投稿只入库不总结)
- 底层 `cmd_ingest` 逐条处理(去重 SHA1 + 抓取 + LLM 识别 + 建 source note)

### 1.5 后端改动(最小)

`api_ingest` 返回结构新增三个字段(从 cmd_ingest 输出的 log 正则解析,**不改 cmd_ingest**):

```python
"new_count": int,       # [ingest] 新建 source note: N
"skipped_count": int,   # [ingest] 跳过(内容重复): M
"failed_count": int,    # [ingest] 失败(保留在 inbox): K
```

旧字段全部保留,向后兼容。

### 1.6 结果反馈

结果区显示:「✓ 批量投稿完成 / 成功 N 条,跳过 M 条重复,失败 K 条」+ new_sources 卡片列表(每张标「未总结」)+ 可折叠处理日志。

### 1.7 不变

- 单条文字投稿 panel、图片 OCR panel 不受影响
- `/api/ingest` 端点签名不变(只是返回多了字段)
- `cmd_ingest` 逻辑不变

---

## 功能二:Idea / Todo 页拆分「待定 / 已确定」

### 2.1 目标

`/ideas` 和 `/todos` 各自内部拆成两个 tab(同页切换,非两个路由):

- **待定**:现状的 review 队列(来自 `idea_suggestions.md` / `todo_suggestions.md`)
- **已确定**:accept 后进入正式清单的内容

### 2.2 Tab 实现

- 复用首页仪表盘的 `.tab-bar` + `.tab` + `.tab-panel` 样式 + 通用 `switchTab(tab)` 函数
- 导航栏(base.html)不动,「Idea / Todo」仍是两个独立路由
- **懒加载**:切到「已确定」tab 才首次请求,已加载过不重复请求

### 2.3 待定面板

完全沿用现有 `loadSuggestions('idea'/'todo')` + `renderSuggestionCard` + accept/reject 交互,零改动。

### 2.4 已确定面板(新增解析能力)

**当前 Web 完全没读正式清单文件**,必须新增解析器 + API。

#### Idea 已确定

- 数据源:`03_Ideas/*_ideas.md`(排除 `idea_suggestions.md`)
- 解析:按 `## Idea: <title>` 切块(复用 `kb._split_suggestion_blocks(text, "Idea")`)
- 字段:`- id/status/maturity/priority/sources/estimated_investment/main_challenges` + 正文
- area 从文件名推断(`research_ideas.md` → `research`)
- 卡片显示:area / priority / maturity / status / 预估投入 tag + 正文

#### Todo 已确定

- 数据源:`04_Plans/Weekly/*.md`、`Monthly/*.md`、`someday.md`、`completed_todos.md`
- 解析:`- [ ]` / `- [x]` 任务行 + 紧随的缩进子项(来源/预计时间/难度/难点)
- 每条带 `plan`(weekly/monthly/someday/completed,从路径推断)+ `period`(从文件名 `2026-W29`/`2026-07` 推断)
- **确定性 id**:基于 `plan|period|title` 的 sha1 前 10 位(`todo_xxx`),重新解析后不变(供日历关联去重/回显)
- 按 plan 分组渲染(weekly / monthly / someday / 已完成),卡片显示 done 状态 / period / 预计时间 / 难度 / 来源

#### 新增 API

```
GET /api/ideas/confirmed  → {"items": [...]}
GET /api/todos/confirmed  → {"items": [...]}
```

文件不存在 / 为空返回 `[]`(不报错),兼容「还没跑过 accept」。

### 2.5 健壮性

- 解析器对格式宽容:缺字段兜底空串 / 默认值,无法解析的块跳过不崩
- todo 不用日历形式(无具体日期,只有计划桶),用按 plan 分组的卡片列表

### 2.6 不变

- review 队列 accept/reject 流程不变
- `cmd_accept_ideas` / `cmd_accept_todos` / `_format_formal_idea` / `_format_weekly_task` 不改(只读)

---

## 功能三:已确认 Todo → 日历链接

### 3.1 目标

已确定 todo 卡片加「📅 放入日历」按钮,点击后选日期创建日历事项,建立 todo ↔ calendar 的关联。

### 3.2 交互(复用现有日历表单)

- 点击「📅 放入日历」→ 复用统一日历表单 `openCalendarEventForm`
- 默认值:标题 = todo 标题,日期 = 今天,用户可改
- 保存 → `POST /api/calendar` `{title, date, source_id: todo.id, source_type: 'todo'}`
- **去重**:同 source_id 重复放入返回已有事项(不创建重复)
- 成功后 `loadConfirmedTodos()` 刷新,卡片变为「📅 已加入日历 · {date}」+「编辑」按钮

### 3.3 「已加入」状态回显

- `loadConfirmedTodos` 同时拉 `/api/calendar`,建 `source_id → calItem` 映射
- 渲染卡片时查 `calMap[todo.id]`,有则显示已加入状态 + 编辑按钮(编辑模式打开同一表单)
- 依赖 todo 的**确定性 id**(功能二已加),刷新页面后关联不丢

### 3.4 关键设计

- **零新增 API**:`POST /api/calendar` 已支持 source_id 关联 + 同 source_id 去重
- **复用 openCalendarEventForm**:已支持 create 模式(defaultTitle/defaultDate/sourceId/onSaved)
- 日期只存在 calendar.json,**不写回 todo 清单文件**(清单文件保持原样)
- 已完成(completed)分组的 todo 也允许放日历

### 3.5 不变

- 日历 API / CalendarItem 模型不改
- 文章详情页的日历功能(独立路径)不受影响
- todo 清单文件格式不变

---

## 4. 验收标准

### 批量投稿

- [ ] 投稿页有「📦 批量投稿」panel,支持拖入 / 选择 / 粘贴三入口
- [ ] URL 自动去重 + 可编辑(勾选 / 删除)
- [ ] 提交后生成无总结卡片(auto_summary=false),出现在「待生成 summary」板块
- [ ] 结果精确显示「成功 N / 跳过 M / 失败 K」
- [ ] 单条投稿、图片投稿不受影响

### Tab 拆分

- [ ] /ideas、/todos 各有两个 tab「待定 / 已确定」
- [ ] 待定面板行为与现状一致(accept/reject 不受影响)
- [ ] 已确定面板能读取正式清单并渲染卡片
- [ ] todo 按 weekly/monthly/someday/已完成 分组
- [ ] 文件不存在 / 为空时友好空状态,不报错
- [ ] tab 懒加载

### Todo 日历链接

- [ ] 已确定 todo 卡片有「📅 放入日历」按钮
- [ ] 复用现有日历表单,标题默认=todo,日期可选
- [ ] 放入后显示「已加入·日期」+ 编辑按钮
- [ ] 同一 todo 重复放入不创建重复事项
- [ ] 刷新页面后「已加入」状态正确回显
- [ ] 现有日历页、文章详情页日历不受影响

---

## 5. 测试覆盖

- `test_batch_ingest.py`:7 个(计数字段 / 批量创建 / 去重 / auto_summary=false / 混合 / 空 400 / log 解析)
- `test_confirmed_parsers.py`:10 个(idea / todo 解析 + API + 空状态)
- `test_todo_calendar_link.py`:7 个(确定性 id / 稳定 / 去重 / round-trip)

---

## 6. 本次不处理(留 ROADMAP)

- idea/todo 抽取的 prompt 量化打分标准
- todo `estimated_time` 硬兜底 `"2-4h"`
- `_extract_json_list` 解析失败静默
- 自动产出补全模板章节
- Web 端 accept 自动搬运(仍需跑 CLI)
- summary 重生成后允许重抽
