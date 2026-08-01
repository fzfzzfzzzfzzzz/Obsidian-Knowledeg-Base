# 详情页手动生成 Idea/Todo｜增量 PRD

## 0. 文档定位

本文档是知识库 v0.1~v0.3.1 已有功能的增量补充,仅描述「文章详情页手动生成 idea/todo」相关的新增与变更。

除本文明确修改的规则外,以下内容保持不变:

- summary 生成流程(采集 → 抓取 → 识别 → 生成 summary)
- idea/todo 候选的 review 队列机制(`03_Ideas/idea_suggestions.md`、`04_Plans/todo_suggestions.md`)
- 候选 → 正式清单的 accept 流程(`accept-ideas` / `accept-todos`)
- 首页批量「💡 抽 idea/todo」按钮与 CLI `extract-suggestions`
- suggestion 块的 markdown 格式与字段定义
- review 页面 `/ideas`、`/todos` 的卡片与接受/拒绝交互

本文档不重复定义上述功能。

---

## 1. 背景与批注

### 1.1 现状澄清(经代码核实)

> **结论:summary 生成阶段不会自动抽取 idea/todo。**

核实了全部 6 条 summary 生成路径,均不调用任何 `extract_*`:

| 路径 | 位置 | 是否抽取 |
|---|---|---|
| `kb_llm.generate_summary` | kb_llm.py:602 | 否 |
| `kb.py cmd_make_prompts --auto` | kb.py:1395-1418 | 否 |
| `kb.py _write_summary` | kb.py:1649-1683 | 否 |
| `kb_web.py _generate_summary_for_source` | kb_web.py:508-553 | 否 |
| ingest 的 `auto_summary` | kb_web.py:980 / 1074 | 否 |
| 批量 `generate_summary` | kb_web.py:1514-1523 | 否 |

idea/todo 的抽取是**独立步骤**,只能通过以下两个入口触发:

- **CLI**:`python scripts/kb.py extract-suggestions`(kb.py:1443-1521)
- **Web 批量动作**:首页「💡 抽 idea/todo」按钮 → `POST /api/batch` 且 `action="extract_suggestions"`(kb_web.py:1524-1552)

两个底层 LLM 函数 `extract_ideas_from_summary`(kb_llm.py:720)和 `extract_todos_from_summary`(kb_llm.py:775)目前**只接收 summary 文本,不接收任何用户引导参数**。

### 1.2 当前 idea/todo 生成的已知问题(批注)

经系统性分析,当前生成规则存在以下问题。本 PRD 只解决其中第 1 条,**其余 4 条记入 `docs/ROADMAP.md` 留作后续**:

| # | 问题 | 本版本是否处理 |
|---|---|---|
| 1 | **抽取无引导、无参数**:用户无法就某篇 summary 给出方向偏好或优先级/难度/时间约束,LLM 凭空判断,结果与用户意图脱节 | ✅ 处理(本 PRD 主题) |
| 2 | prompt 缺少量化打分标准(`priority`/`feasibility`/`novelty`/`difficulty` 只给枚举不给门槛),同一份 summary 不同时间跑结果不稳定 | ❌ 留后续(ROADMAP) |
| 3 | todo 的 `estimated_time` 硬兜底 `"2-4h"`(kb_llm.py:812-813),LLM 没返回就伪造,污染 review 队列 | ❌ 留后续(ROADMAP) |
| 4 | `_extract_json_list` 失败返回 `[]`,调用方 `if items is None` 分支永远走不到,解析失败被静默吞成"0 候选" | ❌ 留后续(ROADMAP) |
| 5 | 自动产出的 suggestion 比模板少一半章节(模板的 MVP/风险/下一步 todo/依赖条件等节在 `_format_*` 里没产出) | ❌ 留后续(ROADMAP) |
| 6 | `99_System/prompt_library.md` 滞后,第 42 行仍写「Summary 生成待实现」,idea/todo prompt 未沉淀 | ❌ 留后续(ROADMAP) |

### 1.3 本版本要解决的问题

> 用户在阅读某篇 summary 后,常常有明确的关注方向(例如"只想要 AI agent 相关""只要本周能做的""重点找可落地的工具型 idea")。当前抽取入口无法承载这种意图,导致 review 队列里充斥与用户当下关注点无关的候选。

本版本通过在**文章详情页**新增手动生成入口,并允许用户输入引导词 + 选择参数来定向抽取,解决这一问题。

---

## 2. 变更目标

在文章详情页(`/summary/{source_id}`)的操作栏新增两个按钮:

1. **💡 生成 Idea 列表**
2. **✅ 生成 Todo 列表**

点击任一按钮后,弹出一个统一表单,允许用户:

- 输入自由引导提示词(可选)
- 手动选择优先级、(idea 的)领域、(todo 的)难度/预计时间/计划

提交后,系统把用户输入作为**引导**传给 LLM,从当前文章的 summary 抽取 1-3 条候选,以 `pending_review` 状态追加进对应的 review 队列文件。

生成结果**不自动进正式清单**,用户仍需在 `/ideas`、`/todos` 页面逐条 accept,再跑 CLI `accept-ideas` / `accept-todos` 进入正式清单(与现状一致)。

---

## 3. 明确不变更

| 项 | 规则 |
|---|---|
| summary 生成 | 不变(本就不自动抽取,见 1.1) |
| 首页批量「💡 抽 idea/todo」按钮 | 保留 |
| CLI `extract-suggestions` | 保留 |
| accept 流程 | 不变(生成后 status=`pending_review`,需手动 accept + 跑 CLI) |
| `idea_suggestions.md` / `todo_suggestions.md` 格式 | 不变(沿用 `_format_idea_suggestion` / `_format_todo_suggestion` 的输出) |
| review 页面交互 | 不变 |
| `action_status` 状态机 | 不变(`undecided` → `todo_suggested`),但本入口**允许重抽**(见 8.4) |

---

## 4. 详情页按钮规则

### 4.1 显示条件

- **仅当该文章已有 summary 时显示**(与「🔄 重新生成」「🗑 删除 summary」同条件,复用 `hasSummary` 变量)
- 无 summary 时不显示(没有 summary 无法抽取)

### 4.2 位置

放在现有 `.detail-action-bar`(summary.html 第 50-60 行),紧邻「重新生成」「删除 summary」按钮之后、「删除文章」按钮之前。

### 4.3 视觉

两个按钮均使用 `.btn-primary` 样式,与「重新生成」(`.btn-warn`)区分,强调其"主动产出"语义。

### 4.4 文案

```text
💡 生成 Idea 列表
✅ 生成 Todo 列表
```

---

## 5. 生成弹窗字段

两个按钮共用一个弹窗组件 `openGenerateDialog(kind)`,其中 `kind ∈ {"idea", "todo"}`。根据 kind 显示不同字段。

### 5.1 共通字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| 引导提示词 | textarea(可选) | 否 | 空 | 自由文本,例如「重点找可落地的工具型 idea」「关注 Agent 相关方向」 |

### 5.2 Idea 弹窗额外字段

| 字段 | 类型 | 必填 | 默认值 | 可选值 |
|---|---|---|---|---|
| 优先级 | select | 否 | 不限 | P0 / P1 / P2 / P3 / 不限 |
| 领域 | select | 否 | 不限 | research / productivity / product / ai_agent / web_design / other / 不限 |

### 5.3 Todo 弹窗额外字段

| 字段 | 类型 | 必填 | 默认值 | 可选值 |
|---|---|---|---|---|
| 优先级 | select | 否 | 不限 | P0 / P1 / P2 / P3 / 不限 |
| 难度 | select | 否 | 不限 | low / medium / high / 不限 |
| 预计时间 | select | 否 | 不限 | 30min / 1h / 2-4h / 半天 / 1-2 天 / 不限 |
| 计划 | select | 否 | 不限 | weekly / monthly / someday / 不限 |

### 5.4 字段语义

- **所有参数默认「不限」**:用户不主动选择时,等同于当前的"无约束抽取"行为,保证向后兼容。
- **参数均为引导而非硬约束**:详见第 6 节。

---

## 6. 参数语义(关键设计决策)

用户选择的参数作为**引导(soft hint)**传给 LLM,**不是硬性约束**。

### 6.1 引导的拼装

提交时,前端把用户所选值拼成一段 hint 文本,追加到 summary 文本之前,一起作为 user message 发给 LLM。形如:

```text
【用户偏好(参考,不强制)】
优先级: P1
领域: ai_agent
引导: 重点找可落地的工具型 idea

--- 以下是文章 summary ---
<summary 正文>
```

### 6.2 LLM 的处理规则

system prompt 末尾追加一句:

> 如果用户给了偏好(优先级/难度/时间/领域),请在候选里**优先体现**,但每条候选仍可根据自身性质独立定级。用户偏好不强制套用到所有候选。

### 6.3 为什么不是硬约束

- 一次抽取产出**多条候选**,不同候选天然有不同优先级/难度。强制套用单一值会让候选失去区分度。
- 用户意图是"倾向",不是"必须"。LLM 参考偏好但保留自主判断,产出更贴近内容真实价值。
- 与现有 review 流程(逐条 accept)契合:用户在 review 队列还能二次筛选。

### 6.4 候选数量

- LLM 根据内容自主决定,通常 **1-3 条**
- 全部进 review 队列,用户逐条 accept/reject
- 与现有批量抽取的产出粒度一致(不强制只出 1 条)

---

## 7. 提交与状态

### 7.1 前置校验(前端)

- 弹窗打开即校验当前文章有 summary(按钮本身只在有 summary 时显示,二次保险)
- 引导提示词超长(>500 字)时截断并提示
- 所有 select 字段无需校验(有默认值"不限")

### 7.2 提交流程

| 阶段 | 行为 |
|---|---|
| 点击「生成」 | 按钮文案改「⏳ 生成中...(约 10-30 秒)」+ disabled |
| 请求中 | 弹窗保持打开,遮罩防止误操作 |
| 成功 | 关闭弹窗,toast「✓ 已生成 N 条候选」+ 提供「前往 /ideas 查看」(或 /todos)跳转链接 |
| 失败 | toast 显示错误(LLM 失败 / 无 summary / 网络错误),**弹窗保持打开,保留用户已填内容** |
| 无论成败 | 解除按钮 disabled,恢复文案 |

### 7.3 按钮文案

```text
[取消]  [生成]
```

主按钮「生成」用 `.btn-primary`。

---

## 8. 后端接口设计

### 8.1 新增端点

```text
POST /api/article/{source_id}/generate-ideas
POST /api/article/{source_id}/generate-todos
```

### 8.2 请求 body

**generate-ideas**:

```json
{
  "prompt": "重点找可落地的工具型 idea",
  "priority": "P1",
  "area": "ai_agent"
}
```

**generate-todos**:

```json
{
  "prompt": "本周能做完的",
  "priority": "P1",
  "difficulty": "medium",
  "estimated_time": "2-4h",
  "plan": "weekly"
}
```

所有字段均可选,缺省视为"不限"。`prompt` 为空字符串等同于"无引导词"。

### 8.3 响应

```json
{
  "ok": true,
  "source_id": "source_xxx",
  "kind": "idea",
  "generated": 2
}
```

失败时返回 400/500 + `{"detail": "..."}`(沿用现有 HTTPException 模式)。

### 8.4 实现要点

复用现有函数,不重复造轮子:

| 复用 | 位置 |
|---|---|
| `kb._append_section` | kb.py:1914(追加块到文件) |
| `kb._format_idea_suggestion` | kb.py:1812(候选 → markdown 块) |
| `kb._format_todo_suggestion` | kb.py:1843 |
| `_parse_frontmatter` | kb_web.py(读 summary 文件,分离 frontmatter 与 body) |
| `kb_llm.extract_ideas_from_summary` | kb_llm.py:720(**需扩 hint 参数**) |
| `kb_llm.extract_todos_from_summary` | kb_llm.py:775(**需扩 hint 参数**) |

**去重策略**:

- 检查该 source 是否有 `summary_path`,无则返回 400
- **允许重抽**:即便 `action_status` 已是 `todo_suggested`,本入口仍可再次生成(因为用户带了新引导词,意图明确想要新候选)
- 每条候选的 id 带时间戳(`idea_suggestion_YYYYMMDD_slug`),天然不与已有候选冲突
- 不修改 `action_status`(避免影响批量入口的幂等判断)

**错误处理**:

| 情况 | 响应 |
|---|---|
| source 不存在 | 404 |
| 无 summary | 400 `该文章没有 summary,无法抽取` |
| LLM 调用失败 | 500 `LLM 失败:{detail}` |
| 成功但 0 候选(LLM 判断无可转化内容) | 200 `generated: 0`,前端 toast「未识别到可转化的候选」 |

---

## 9. kb_llm.py 改动

### 9.1 函数签名扩展

```python
def extract_ideas_from_summary(
    summary_text: str,
    hint: str | None = None,   # 新增
) -> list[dict[str, str]]:

def extract_todos_from_summary(
    summary_text: str,
    hint: str | None = None,   # 新增
) -> list[dict[str, str]]:
```

`hint` 默认 `None`,向后兼容现有调用方(CLI extract-suggestions、批量动作)无需改动。

### 9.2 user message 拼装

当 `hint` 非空时,user message 改为:

```python
user_msg = (
    f"【用户偏好(参考,不强制)】\n{hint}\n\n"
    f"--- 以下是文章 summary ---\n{summary_text[:50000]}"
)
```

`hint` 为空时,维持原行为(`summary_text[:50000]` 直接作为 user message)。

### 9.3 system prompt 补充

`IDEA_EXTRACT_SYSTEM_PROMPT` 和 `TODO_EXTRACT_SYSTEM_PROMPT` 末尾各加一句:

```text
- 如果用户在消息开头提供了【用户偏好】,请优先体现,但每条候选仍可根据自身性质独立定级,不强制套用。
```

### 9.4 不改动的部分

- `_extract_json_list` 容错解析逻辑不变
- 字段 `_clamp_enum` 兜底逻辑不变
- temperature / max_tokens 不变
- 已知的 `if items is None` 死分支不在本版本修(留 ROADMAP)

---

## 10. 前端组件改动

### 10.1 新增 JS 函数 `openGenerateDialog(kind, sourceId)`

放在 `scripts/web/static/app.js`,参考现有 `openCalendarEventForm`(app.js:556-717)的表单弹窗模式:

- **不用** `confirmModal`(它 body 是 `textContent`,只支持纯文本)
- 直接操作 `modalBody.innerHTML` 注入表单,清空 `modalActions`(表单自带按钮)
- 复用 `.cal-form` / `.cal-form-field` / `.cal-form-actions` 样式

### 10.2 表单 HTML 结构

```text
生成 Idea 列表 / 生成 Todo 列表

引导提示词(可选)
[textarea, rows=3, placeholder="例如:重点找可落地的工具型 idea"]

优先级
[select: 不限 / P0 / P1 / P2 / P3]

(仅 idea) 领域
[select: 不限 / research / productivity / product / ai_agent / web_design / other]

(仅 todo) 难度
[select: 不限 / low / medium / high]

(仅 todo) 预计时间
[select: 不限 / 30min / 1h / 2-4h / 半天 / 1-2 天]

(仅 todo) 计划
[select: 不限 / weekly / monthly / someday]

[取消]  [生成]
```

### 10.3 hint 拼装(前端)

提交时,把用户所选值拼成 hint 字符串(仅拼非"不限"的字段):

```text
优先级: P1
领域: ai_agent
引导: 重点找可落地的工具型 idea
```

POST 到对应端点。所有字段缺省(=不限)时 hint 为空,等同于无引导抽取。

### 10.4 样式补充

`scripts/web/static/style.css` 现有 `.cal-form-field input/textarea` 规则(style.css:938 附近)扩展一条 `select`,复用相同 border/padding/focus 样式,约 3 行。无需新增样式类。

### 10.5 cache buster

`scripts/web/templates/base.html` 的 `style.css?v=17` 和 `app.js?v=17` 改为 `?v=18`。

---

## 11. 验收标准

### 详情页按钮

- [ ] 文章有 summary 时,详情页操作栏出现「💡 生成 Idea 列表」「✅ 生成 Todo 列表」两个按钮
- [ ] 文章无 summary 时,两个按钮不显示
- [ ] 按钮位置在「重新生成」「删除 summary」之后、「删除文章」之前
- [ ] 按钮使用 `.btn-primary` 样式

### 生成弹窗

- [ ] 点击「生成 Idea 列表」弹出 idea 弹窗,含引导词 + 优先级 + 领域字段
- [ ] 点击「生成 Todo 列表」弹出 todo 弹窗,含引导词 + 优先级 + 难度 + 预计时间 + 计划字段
- [ ] 所有 select 字段默认值为「不限」
- [ ] 弹窗复用 `.cal-form*` 样式,视觉与日历表单一致
- [ ] 弹窗支持 Esc 关闭、点击取消关闭
- [ ] 弹窗打开后自动聚焦引导词输入框

### 参数语义

- [ ] 用户不选任何参数(全"不限")时,生成结果与现有批量抽取行为一致(无约束)
- [ ] 用户选了优先级 P1 后,生成的候选中至少有一条 priority=P1(允许但非全部)
- [ ] 用户填了引导词后,生成的候选方向与引导词相关
- [ ] 一次生成产出 1-3 条候选(由 LLM 根据内容决定)

### 接口

- [ ] `POST /api/article/{id}/generate-ideas` 接收 prompt/priority/area,返回 `{ok, generated}`
- [ ] `POST /api/article/{id}/generate-todos` 接收 prompt/priority/difficulty/estimated_time/plan,返回 `{ok, generated}`
- [ ] source 不存在返回 404
- [ ] 无 summary 返回 400
- [ ] LLM 失败返回 500
- [ ] 0 候选返回 200 + `generated: 0`

### 数据流

- [ ] 生成的候选追加进 `03_Ideas/idea_suggestions.md` / `04_Plans/todo_suggestions.md`,status=`pending_review`
- [ ] 不覆盖文件已有内容(纯 append)
- [ ] 候选 id 带时间戳,不与已有候选冲突
- [ ] 生成后在 `/ideas`、`/todos` 页面立即可见(刷新即可)
- [ ] 用户仍需在 review 页面 accept + 跑 CLI 才进正式清单(流程未变)

### 不破坏现有

- [ ] 首页「💡 抽 idea/todo」批量按钮仍正常工作
- [ ] CLI `extract-suggestions` 仍正常工作
- [ ] 现有 `_format_idea_suggestion` / `_format_todo_suggestion` 输出格式未变
- [ ] `extract_ideas_from_summary` / `extract_todos_from_summary` 不带 hint 参数调用时行为不变(向后兼容)

---

## 12. 本次不处理

以下问题已识别但明确不在本版本范围,记入 `docs/ROADMAP.md` 留作后续:

| # | 后续项 | 去向 |
|---|---|---|
| A | prompt 缺少量化打分标准(priority/feasibility/novelty/difficulty 的判定门槛) | ROADMAP P1 |
| B | todo `estimated_time` 硬兜底 `"2-4h"` 伪造数据 | ROADMAP P1 |
| C | `_extract_json_list` 失败静默吞成"0 候选"(`if items is None` 死分支) | ROADMAP P1 |
| D | 自动产出比模板少一半章节(MVP/风险/下一步 todo 等节未产出) | ROADMAP P2 |
| E | `99_System/prompt_library.md` 滞后,idea/todo prompt 未沉淀 | ROADMAP P2 |
| F | Web 端 accept 后需手动跑 CLI 进正式清单,流程割裂 | ROADMAP P2 |
| G | summary 重新生成后无法重抽 idea/todo(action_status 锁死) | ROADMAP P2 |

---

## 13. 与现有文档的关系

| 文档 | 关系 |
|---|---|
| `PRODUCT.md` 2.3 Idea/Todo 候选 | 不冲突,本 PRD 是其"手动引导抽取"的补充入口 |
| `PRODUCT.md` 2.4 Review 确认 | 不冲突,accept 流程完全沿用 |
| `docs/v0.1/PRD.md` | 不冲突,本 PRD 不改 v0.1 定义的管道架构 |
| `AGENTS.md` 硬规则 | 遵守:AI 生成的 idea/todo 仍先进 suggestion 文件,用户 accept 后才进正式清单 |
