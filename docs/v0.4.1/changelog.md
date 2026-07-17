# Changelog v0.4.1

> 日期:2026-07-17

## 新增

### 1. 投稿页批量投稿
- **「📦 批量投稿」panel**:投稿页新增,支持拖入 / 选择 .md/.txt 文件,或直接粘贴文本
- **URL 自动提取 + 去重**:正则提取所有 `https?://` 链接,Set 去重
- **可编辑 URL 列表**:每个 URL 默认勾选,支持取消勾选 / 单条删除 / 全选 / 清空
- **只入库不总结**:`auto_summary` 固定 false,生成的卡片出现在「待生成 summary」板块
- **精确结果反馈**:`/api/ingest` 返回新增 `new_count` / `skipped_count` / `failed_count`(从 cmd_ingest log 正则解析),前端显示「成功 N / 跳过 M / 失败 K」

### 2. Idea / Todo 页拆分「待定 / 已确定」
- **同页 tab 切换**:/ideas、/todos 各加「待定 / 已确定」两个 tab,复用首页 `.tab-bar` + `switchTab`,懒加载
- **已确定 Idea**:新增 `_parse_formal_ideas` 扫 `03_Ideas/*_ideas.md`,按 `## Idea:` 切块;新 API `GET /api/ideas/confirmed`
- **已确定 Todo**:新增 `_parse_formal_todos` 扫 `04_Plans/Weekly`、`Monthly`、`someday`、`completed`,解析 `- [ ]` 任务 + 缩进子项;按 weekly/monthly/someday/已完成 分组;新 API `GET /api/todos/confirmed`
- **Todo 确定性 id**:基于 `plan|period|title` 的 sha1,重新解析不变(为日历关联服务)
- **todo 不用日历**:无具体日期,用按 plan 分组的卡片列表

### 3. 已确认 Todo → 日历链接
- **「📅 放入日历」按钮**:已确定 todo 卡片新增,复用统一日历表单 `openCalendarEventForm`
- **选日期创建**:标题默认 = todo,日期默认 = 今天(可改),`source_id = todo.id`
- **去重**:同 source_id 重复放入返回已有事项,不创建重复
- **「已加入」状态回显**:`loadConfirmedTodos` 同时拉日历建映射,卡片显示「📅 已加入日历 · {date}」+ 编辑按钮
- **零新增 API**:复用 `POST /api/calendar`(已支持 source_id 关联 + 去重)

## 不变
- 单条文字投稿、图片 OCR 投稿不受影响
- review 队列 accept/reject 流程不变
- `cmd_accept_*` / 正式清单文件格式不改(只读解析)
- 文章详情页日历功能(独立路径)不受影响
- 日历 API / CalendarItem 模型不改

## 文件改动
- `kb_web.py`:`api_ingest` 返回加 3 个计数字段 + 新增 `_parse_formal_ideas` / `_parse_formal_todos` + 2 个 confirmed API + todo 确定性 id(`import hashlib`)
- `submit.html`:新增「📦 批量投稿」panel(拖拽 / 选择 / 粘贴 + URL 提取 + 可编辑列表 + 提交)
- `ideas.html` / `todos.html`:改为 tab 结构(待定 / 已确定)
- `app.js`:`loadConfirmedIdeas` / `loadConfirmedTodos` / `renderFormalIdeaCard` / `renderFormalTodoCard` / `openTodoCalendar` + 批量投稿 JS + tab 懒加载
- `style.css`:`.batch-*` 批量投稿区样式
- `base.html`:cache buster 递增
- `tests/`:新增 `test_batch_ingest.py`(7)、`test_confirmed_parsers.py`(10)、`test_todo_calendar_link.py`(7)

## 测试
- 全量 74 个测试通过,零回归
