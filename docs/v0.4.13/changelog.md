# Changelog v0.4.13

> 日期:2026-07-23
> 主题:**Idea / Todo 卡片与抽取链路全面简化(只留标题)+ Web 新建 idea**

本版把 idea/todo 的「卡片显示」「LLM 抽取」「文件格式」三处统一简化为只保留标题,
并新增 Web 端直接创建 idea 的能力。359 passed(346 → 359,+8)。

> 覆盖范围说明:本份涵盖 v0.4.11(idea 卡片简化 + 新建 idea + completed_at 字段)
> 与 v0.4.13(todo 卡片简化 + 抽取简化)。两版主题高度统一(都是 idea/todo 的简化与新建),
> 合并归档到本份,文档目录用较晚的 v0.4.13。

---

## 新增

### 1. 卡片显示简化(只留标题)

**背景**:v0.4.10 之前,idea / todo 卡片显示了大量字段 —— 标题、正文、estimated_time、
priority、difficulty、recommended_area、标签等。这些字段:
- LLM 抽取时大多给的是默认/兜底值(见 v0.4.7 已修的 estimated_time 伪造问题),信息量低
- 在卡片里堆叠,视觉密度高,扫读困难
- 真正影响决策的是**标题本身**,其他字段在详情/接受时才需要

**实现**(`scripts/web/static/app.js`):
- `:493` idea 卡片简化为单一接受(统一进 general 清单)+ 拒绝
- `:506` idea 和 todo 卡片都只留标题,不再显示正文
- `:643` 已确定(accepted)idea 卡片也只留标题,去掉所有标签 + 正文

卡片从「字段堆叠」变成「标题 + 操作」,扫读效率大幅提升。

### 2. LLM 抽取简化(只返回 title)

**背景**:与卡片简化配套。既然卡片只显示标题,LLM 抽取时就没必要再生成 estimated_time /
priority / difficulty / recommended_area 等字段 —— 这些字段要么是兜底默认值(信息量低),
要么 LLM 生成质量不稳定(同份 summary 不同时间跑结果不同,见 ROADMAP P1-#5)。

**实现**(`scripts/kb_llm.py`):
- `:1222` `extract_ideas_from_summary` 简化为只返回 title(LLM prompt 也只要求 title)
- `:1248` 只保留 title,过滤掉没标题的
- `:1262` `extract_todos_from_summary` 同样简化为只返回 title

抽取链路从「多字段结构化」收敛为「只问标题」,LLM 调用更稳定、更快、更省 token。

### 3. 文件格式简化

**背景**:卡片和抽取都简化后,文件里继续写 estimated_time / priority / difficulty / recommended_area
就是死字段 —— 没人显示、没人消费,徒增解析复杂度和数据不一致风险。

**实现**(`scripts/kb.py:2452-2529`):
- `_format_idea_suggestion`(`:2452`):只写 `title + id + status + source`,保留 source 追溯来源文章
- `_format_todo_suggestion`(`:2473`):同上
- `_format_formal_idea`(`:2494`):正式 idea 只写 `title + id + status + maturity + sources`
- `_format_weekly_task`(`:2518`):weekly task 只写 `title + 来源 + 截止日期(若有)`

**删掉的字段**:estimated_time / priority / difficulty / recommended_area / feasibility / novelty。
旧数据若带这些字段,精简格式忽略它们(向后兼容,见 `test_format_helpers.py:75`)。

### 4. Web 新建 idea(提交 `d0ad72a`)

**背景**:idea 原本只能从文章 summary 抽取(source → idea 链路)。但用户经常有**凭空的灵感**
(不来自任何文章),需要直接在 Web 端创建。

**实现**:
- `POST /api/ideas` 新建 idea(测试 `test_web_create_idea.py`)
- 新增 `accepted_general` 状态:Web 新建的 idea 直接进正式 `general_ideas.md` 清单,
  不经过 suggestion review 队列
- 与抽取链路的 `pending_review` 状态区分:抽取的需 review,用户主动创建的直接落地

### 5. completed_at 字段(任务,为工作台统计服务)

**背景**:虽是任务字段(`07_Tasks/task_*.md` 的 frontmatter),但它存在的唯一理由是
工作台「本周概览」的「本周完成数」统计 —— 需要按完成时间落在 ISO 周窗口内计数。
与 idea/todo 卡片简化的「工作台数据精简」主题同源,故归到本份。

**实现**(`scripts/kb.py:3186` 注释 + `write_task_file`):
- `write_task_file` 维护 completed_at 生命周期:
  - 首次 status=done → 写入当前时间
  - 重复 status=done → 不覆盖(保留首次完成时间)
  - 重新激活(从 done 改回 active)→ 清空
- 工作台聚合(`services/cards.py:378`)按 `completed_at` 落在当前 ISO 周内计数「本周完成数」
- 旧任务无该字段算未完成(向后兼容)

### 6. 测试

- `test_web_create_idea.py`:Web 新建 idea + `accepted_general` 状态
- `test_format_helpers.py`:精简格式验证(idea/todo suggestion / formal idea / weekly task)
- `test_suggestions.py`:idea suggestion 简化(不再有 recommended_area / priority / feasibility / novelty)
- `test_kb_llm_bugs.py`:extract_todos_from_summary 只返回 title

**359 passed**(346 → 359,+8,主要在 idea 新建与格式简化)。

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/web/static/app.js` | idea/todo 卡片简化为只留标题(`:493, 506, 643`) |
| `scripts/kb_llm.py` | `extract_ideas/todos_from_summary` 只返回 title(`:1222, 1262`),LLM prompt 只要求 title |
| `scripts/kb.py` | `_format_idea_suggestion` / `_format_todo_suggestion` / `_format_formal_idea` / `_format_weekly_task` 精简(删 estimated_time/priority/difficulty 等);`completed_at` 生命周期(`:3186`) |
| `scripts/web/routers/ideas.py` | `POST /api/ideas` 新建 idea + `accepted_general` 状态 |
| `scripts/web/services/cards.py` | 工作台「本周完成数」按 completed_at 统计(`:378`) |
| `scripts/tests/test_web_create_idea.py` | 新增,Web 新建 idea 测试 |
| `scripts/tests/test_format_helpers.py` | 精简格式验证(+2 用例) |
| `scripts/tests/test_suggestions.py` | idea suggestion 简化验证 |
| `scripts/tests/test_kb_llm_bugs.py` | extract 只返回 title 验证 |

---

## 不变

- idea / todo 的**接受流程**不变(accept-ideas / accept-todos 命令、Web accept 端点)
- 既有 idea/todo **数据不迁移**:旧文件里若带 estimated_time 等字段,精简格式读取时忽略,不报错
- 任务系统的其他字段不变(只新增 completed_at,不动 title/checklist/deadline 等)

---

## 破坏性变更

**字段语义收敛(向下游兼容)**:
- idea/todo suggestion 文件不再写 estimated_time / priority / difficulty / recommended_area / feasibility / novelty
- 若有外部脚本依赖这些字段,需适配(本项目的 review/accept 流程已同步简化,不受影响)
- LLM 抽取结果从多字段 dict 变成只含 title 的 dict

这些是**信息收敛**(去掉低价值/不可靠字段),不是数据丢失 —— 真正有价值的标题保留,
来源(source_summary)保留以追溯。属于可见行为变化。

---

## 不在本次范围

- **正式 idea 的 maturity 字段流转**:目前新建 idea 固定 `maturity: spark`, maturity 从 spark →
  exploring → validated 的状态机演进未实现,留作后续
- **抽取链路的 estimated_time 恢复**:ROADMAP P1-#5(idea/todo prompt 量化标准)在本版被「简化掉」
  而非解决,属于主动放弃该方向(认为 LLM 给的字段太不可靠,不如只留标题)
- **todo 的 Web 新建**:本版只做了 idea 的 Web 新建,todo 仍只能从文章抽取
