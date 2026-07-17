# v0.4.1 三项增量功能｜Checklist

## 0. 文档范围

本 Checklist 覆盖 v0.4.1 三项功能:批量投稿、Idea/Todo tab 拆分、Todo 日历链接。
对应 PRD:`docs/v0.4.1/v041_features_PRD.md`

---

## P0:批量投稿 — 后端

- [x] `api_ingest` 返回新增 `new_count` / `skipped_count` / `failed_count`
- [x] 从 cmd_ingest 输出 log 正则解析三个计数(不改 cmd_ingest)
- [x] 旧字段(submitted / new_sources / summary_results / log)全部保留
- [x] 空校验 / 失败 500 行为不变

## P0:批量投稿 — 前端

- [x] 新增「📦 批量投稿」panel(拖拽区 + 文件 input + 粘贴 textarea)
- [x] 拖拽区支持 .md / .markdown / .txt(accept 限制 + drop 事件)
- [x] 文件选择 input(multiple)
- [x] 粘贴 textarea(input 事件实时提取)
- [x] URL 提取正则 `https?://[^\s<>"']+` + Set 去重
- [x] 可编辑 URL 列表(勾选 / 单条删除 / 全选 / 全不选 / 清空)
- [x] 提交 POST `/api/ingest` `{items, auto_summary: false}`
- [x] 结果区显示「成功 N / 跳过 M / 失败 K」+ 卡片列表 + 日志
- [x] toast 提示提取结果

## P0:批量投稿 — 样式

- [x] `.batch-drop-zone` 虚线拖拽区 + drag-active 高亮
- [x] `.batch-paste-input` / `.batch-url-list` / `.batch-url-item` 样式

---

## P0:Tab 拆分 — 后端解析器

- [x] `_parse_formal_ideas()`:扫 `03_Ideas/*_ideas.md`,排除 review 队列
- [x] 复用 `kb._split_suggestion_blocks(text, "Idea")` 切块
- [x] area 从文件名推断
- [x] `_parse_formal_todos()`:扫 Weekly / Monthly / someday / completed
- [x] 解析 `- [ ]` / `- [x]` + 缩进子项
- [x] plan / period 从路径文件名推断
- [x] todo 确定性 id(`todo_{sha1(plan|period|title)[:10]}`)
- [x] 文件不存在 / 为空返回 `[]`

## P0:Tab 拆分 — API

- [x] `GET /api/ideas/confirmed`
- [x] `GET /api/todos/confirmed`

## P0:Tab 拆分 — 前端

- [x] ideas.html / todos.html 改 `.tab-bar` + 两个 `.tab-panel`
- [x] 复用 `switchTab`
- [x] 待定面板沿用 `loadSuggestions`(零改动)
- [x] `loadConfirmedIdeas` + `renderFormalIdeaCard`
- [x] `loadConfirmedTodos` + `renderFormalTodoCard`(按 plan 分组)
- [x] tab 懒加载(切到已确定才首次请求)
- [x] 空状态友好提示

---

## P0:Todo 日历链接 — 前端

- [x] `renderFormalTodoCard(item, calItem)` 加日历关联区
- [x] 未加入:显示「📅 放入日历」按钮
- [x] 已加入:显示「已加入·日期」+ 编辑按钮
- [x] `loadConfirmedTodos` 同时拉 `/api/calendar` 建 source_id 映射
- [x] `openTodoCalendar(item, mode)` 复用 `openCalendarEventForm`
- [x] create 模式:source_id = todo.id, defaultTitle = todo 标题, defaultDate = 今天
- [x] edit 模式:查已有事项后打开编辑表单
- [x] 成功 / 删除后 `loadConfirmedTodos()` 刷新

## P0:Todo 日历链接 — 后端

- [x] 复用 `POST /api/calendar`(零改动,已支持 source_id 关联 + 去重)
- [x] 复用 `PATCH /api/calendar/{id}`(编辑模式)

---

## P0:Cache buster

- [x] base.html style.css / app.js 版本号递增

---

## P1:测试

### 批量投稿
- [x] 返回计数字段
- [x] 批量创建多个
- [x] 去重递增 skipped
- [x] auto_summary=false 无 summary
- [x] 新 + 重复混合
- [x] 空 400
- [x] log 正则解析

### Tab 拆分
- [x] idea 解析(基本 / 空目录 / 空文件)
- [x] todo 解析(weekly / someday / 混合 / 空)
- [x] 两个 API 端点
- [x] 空状态

### Todo 日历链接
- [x] 确定性 id
- [x] 重新解析稳定
- [x] 不同 todo 不同 id
- [x] 创建日历事项(source_id 关联)
- [x] source_id 去重
- [x] round-trip

---

## 上线验收

- [x] 批量投稿三入口可用,URL 去重可编辑,无总结卡片入库
- [x] /ideas /todos 各有「待定 / 已确定」tab,懒加载
- [x] 已确定读取正式清单,todo 按 plan 分组
- [x] todo 可放入日历,已加入状态回显,去重生效
- [x] 现有功能(单条投稿 / 图片投稿 / 文章日历 / review 流程)不受影响
- [x] 全量测试零回归

---

## 本增量完成定义

- [x] 三项功能 PRD 验收标准全部满足
- [x] 后端解析器健壮(空 / 缺字段 / 文件不存在不崩)
- [x] 复用现有组件,无重复造轮子
- [x] 全量回归通过
