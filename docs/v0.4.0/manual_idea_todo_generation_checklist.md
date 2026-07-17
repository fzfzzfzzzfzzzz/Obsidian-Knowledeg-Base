# 详情页手动生成 Idea/Todo｜增量 Checklist

## 0. 文档范围

本 Checklist 仅用于实现「文章详情页手动生成 idea/todo」及其引导参数弹窗。

以下内容不在本 Checklist 中重复拆分:

- summary 生成全流程
- 首页批量抽取 idea/todo 入口
- CLI `extract-suggestions` 子命令
- review 队列文件格式与解析
- accept-ideas / accept-todos 流程
- review 页面 `/ideas`、`/todos` 的卡片渲染与接受交互
- 全局 modal / toast / 按钮 基础组件

上述内容继续使用 v0.1~v0.3.1 已有实现,本版本不改动。

对应 PRD:`docs/v0.4.0/manual_idea_todo_generation_PRD.md`

---

## P0:后端 LLM 函数(kb_llm.py)

- [ ] `extract_ideas_from_summary` 增加 `hint: str | None = None` 参数
- [ ] `extract_todos_from_summary` 增加 `hint: str | None = None` 参数
- [ ] `hint` 非空时,user message 头部拼入「【用户偏好(参考,不强制)】」段 + hint + 分隔线 + summary
- [ ] `hint` 为空时维持原行为(直接传 summary_text),向后兼容
- [ ] `IDEA_EXTRACT_SYSTEM_PROMPT` 末尾追加「用户偏好优先体现但不强制套用」一句
- [ ] `TODO_EXTRACT_SYSTEM_PROMPT` 末尾追加同样一句
- [ ] 不改动 `_extract_json_list` 容错解析逻辑
- [ ] 不改动 `_clamp_enum` 字段兜底逻辑
- [ ] 不改动 temperature / max_tokens
- [ ] 不带 hint 调用时,现有调用方(CLI extract-suggestions、批量动作)行为不变

---

## P0:后端 API(kb_web.py)

- [ ] 新增 `POST /api/article/{source_id}/generate-ideas`
- [ ] 新增 `POST /api/article/{source_id}/generate-todos`
- [ ] generate-ideas 接收 body:`{prompt?, priority?, area?}`
- [ ] generate-todos 接收 body:`{prompt?, priority?, difficulty?, estimated_time?, plan?}`
- [ ] 所有字段可选,缺省视为"不限"
- [ ] 前置校验:source 不存在 → 404
- [ ] 前置校验:无 summary_path → 400 `该文章没有 summary,无法抽取`
- [ ] 读取 summary 文件,用 `_parse_frontmatter` 分离 body
- [ ] 把非"不限"的字段拼成 hint 字符串
- [ ] 调 `kb_llm.extract_ideas_from_summary(body, hint)` / `extract_todos_from_summary(body, hint)`
- [ ] 每条候选用 `kb._format_idea_suggestion` / `kb._format_todo_suggestion` 格式化
- [ ] 用 `kb._append_section` 追加进 `03_Ideas/idea_suggestions.md` / `04_Plans/todo_suggestions.md`
- [ ] 不覆盖文件已有内容(纯 append)
- [ ] 不修改 source 的 `action_status`(保留批量入口的幂等判断)
- [ ] LLM 异常捕获 → 500 `LLM 失败:{detail}`
- [ ] 成功返回 `{ok: true, source_id, kind, generated: N}`
- [ ] 0 候选返回 200 + `generated: 0`(不报错)

---

## P0:详情页按钮(summary.html)

- [ ] 在 `.detail-action-bar` 内新增「💡 生成 Idea 列表」按钮
- [ ] 在 `.detail-action-bar` 内新增「✅ 生成 Todo 列表」按钮
- [ ] 两个按钮均在 `${hasSummary ? ...}` 条件块内(无 summary 不显示)
- [ ] 按钮位置在「重新生成」「删除 summary」之后、「删除文章」之前
- [ ] 按钮使用 `.btn-primary` 样式
- [ ] onclick 调用 `openGenerateDialog('idea', '${SOURCE_ID}')` / `openGenerateDialog('todo', '${SOURCE_ID}')`

---

## P0:生成弹窗组件(app.js)

- [ ] 新增 `openGenerateDialog(kind, sourceId)` 函数,放 app.js
- [ ] 复用现有 modal DOM(`modalOverlay` / `modalBox` / `modalTitle` / `modalBody` / `modalActions`)
- [ ] 用 `modalBody.innerHTML` 注入表单(不用 `confirmModal`,它只支持纯文本)
- [ ] 清空 `modalActions`(表单自带按钮)
- [ ] 表单最外层用 `.cal-form` 样式
- [ ] 引导提示词字段:`.cal-form-field` + `<textarea rows="3" maxlength="500">`,可选
- [ ] 优先级字段:`.cal-form-field` + `<select>`,选项 不限/P0/P1/P2/P3,默认"不限"
- [ ] idea 弹窗:领域字段 `<select>`,选项 不限/research/productivity/product/ai_agent/web_design/other,默认"不限"
- [ ] todo 弹窗:难度字段 `<select>`,选项 不限/low/medium/high,默认"不限"
- [ ] todo 弹窗:预计时间字段 `<select>`,选项 不限/30min/1h/2-4h/半天/1-2 天,默认"不限"
- [ ] todo 弹窗:计划字段 `<select>`,选项 不限/weekly/monthly/someday,默认"不限"
- [ ] 根据 kind 渲染对应字段(idea 不显示难度/时间/计划;todo 不显示领域)
- [ ] 弹窗标题:idea →「生成 Idea 列表」,todo →「生成 Todo 列表」
- [ ] 底部按钮区:`.cal-form-actions` + 「取消」(`.btn-ghost`) + 「生成」(`.btn-primary`)

---

## P0:提交逻辑(app.js)

- [ ] 点击「生成」时,读取所有字段值
- [ ] 引导词 strip 后 >500 字截断
- [ ] 把非"不限"的字段拼成 hint 对象 `{prompt, priority, area/difficulty/estimated_time/plan}`
- [ ] POST 到 `/api/article/{sourceId}/generate-ideas` 或 `/generate-todos`
- [ ] 请求前:按钮文案改「⏳ 生成中...(约 10-30 秒)」+ disabled
- [ ] 请求期间弹窗保持打开,防止误关
- [ ] HTTP 非 2xx 或 `ok: false`:toast 显示 `data.detail`,**弹窗保持打开,保留用户已填内容**,按钮恢复
- [ ] 成功:`generated > 0` → toast「✓ 已生成 N 条候选」+ 「前往 /ideas(或 /todos)查看」可点链接;关闭弹窗
- [ ] 成功:`generated === 0` → toast「未识别到可转化的候选」,关闭弹窗
- [ ] 网络异常:toast「网络错误:{e.message}」,按钮恢复
- [ ] finally 块:解除 disabled,恢复「生成」文案

---

## P0:样式(style.css + base.html)

- [ ] `.cal-form-field select` 复用现有 input/textarea 的 border/padding/font 规则(扩展 L938 附近那条规则)
- [ ] `.cal-form-field select:focus` 复用 focus 样式(border-color + box-shadow)
- [ ] select 选项在深色主题下可读(检查 `color` / `background`)
- [ ] `base.html` 的 `style.css?v=17` → `?v=18`
- [ ] `base.html` 的 `app.js?v=17` → `?v=18`

---

## P1:交互与可访问性

- [ ] 弹窗打开后自动聚焦引导词 textarea(setTimeout 50ms)
- [ ] 支持 Esc 关闭弹窗(复用现有 `_modalEsc` 或自加 keydown 监听)
- [ ] 点击「取消」关闭弹窗
- [ ] 点击 overlay 空白区不误关(避免填一半丢失)— 与日历表单行为对齐
- [ ] 生成中按 Esc 不关闭(防请求中断)
- [ ] 所有 select 有 `<label>`
- [ ] 引导词 textarea 有 placeholder 示例
- [ ] 移动端弹窗不溢出(modal 已有 max-width:440px,验证即可)

---

## P1:测试

### 基础流程

- [ ] 选一篇有 summary 的文章,点「生成 Idea 列表」,弹窗出现
- [ ] 选一篇有 summary 的文章,点「生成 Todo 列表」,弹窗出现
- [ ] 弹窗字段与 kind 对应(idea 不显示难度/时间/计划)
- [ ] 默认值全部为"不限"
- [ ] 点取消,弹窗关闭,无副作用

### 无引导抽取(兼容性)

- [ ] 不填引导词、不选任何参数,直接点「生成」
- [ ] 成功生成候选,行为与现有批量抽取一致
- [ ] 候选出现在 `/ideas` 或 `/todos` 页,status=pending_review

### 带引导抽取

- [ ] 填引导词「重点找 AI agent 相关」+ 选优先级 P1 + 领域 ai_agent,生成 idea
- [ ] 生成的候选中至少有一条 priority=P1 或 recommended_area=ai_agent
- [ ] 候选标题/方向与引导词相关
- [ ] 填引导词「本周能做完的」+ 选难度 medium + 时间 2-4h + 计划 weekly,生成 todo
- [ ] 生成的候选中至少有一条 difficulty=medium 或 recommended_plan=weekly

### 数据完整性

- [ ] 生成后 `idea_suggestions.md` / `todo_suggestions.md` 内容追加在末尾,不覆盖
- [ ] 候选 id 带日期,不与已有候选冲突
- [ ] 生成候选的 source_summary 字段指向当前文章
- [ ] 同一篇文章可多次生成(允许重抽),每次都追加新候选

### 错误处理

- [ ] 无 summary 的文章,详情页不显示两个按钮
- [ ] 手动构造请求(绕过前端)对无 summary 文章调 API,返回 400
- [ ] 不存在的 source_id 调 API,返回 404
- [ ] LLM 失败时,toast 显示错误,弹窗保留输入
- [ ] 0 候选时,toast「未识别到可转化的候选」,不报错

### 不破坏现有

- [ ] 首页「💡 抽 idea/todo」批量按钮仍可正常抽取
- [ ] CLI `python scripts/kb.py extract-suggestions` 仍可正常抽取
- [ ] `/ideas`、`/todos` review 页面正常显示新旧候选
- [ ] accept 流程不受影响(生成候选后仍需 accept + 跑 CLI)

---

## 上线验收

- [ ] 详情页有两个「生成」按钮,无 summary 时不显示
- [ ] 弹窗字段完整,默认值全为"不限"
- [ ] 不带任何参数生成,结果与批量抽取一致
- [ ] 带引导词 + 参数生成,结果体现用户偏好
- [ ] 生成的候选进 review 队列,不覆盖已有内容
- [ ] accept 流程未变(仍需 review 页 accept + CLI 进正式清单)
- [ ] 现有批量入口和 CLI 完全不受影响
- [ ] 错误情况(无 summary / LLM 失败)有明确提示
- [ ] 视觉与日历表单一致(复用 `.cal-form*`)

---

## 本增量完成定义

- [ ] 详情页可手动触发生成 idea/todo,带引导词 + 参数
- [ ] 参数作为引导传给 LLM,不强制套用
- [ ] 生成结果进 review 队列,流程与现状一致
- [ ] 现有批量入口和 CLI 不受影响
- [ ] `kb_llm.py` 的 extract 函数向后兼容(无 hint 参数时行为不变)
- [ ] 已知问题中只有"无引导无参数"被解决,其余记入 ROADMAP
