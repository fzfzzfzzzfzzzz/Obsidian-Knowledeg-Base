# v0.4.13 任务清单(验收记录)

> 日期:2026-07-23
> PRD 见 `v0413_PRD.md`,changelog 见 `changelog.md`
> 涵盖 v0.4.11 + v0.4.13,全部已完成(事后补录)

## 卡片显示简化 — 完成

- [x] idea 卡片简化为单一接受(统一进 general 清单)+ 拒绝(`app.js:493`)
- [x] idea 和 todo 卡片都只留标题,不再显示正文(`app.js:506`)
- [x] 已确定(accepted)idea 卡片也只留标题(`app.js:643`)

## LLM 抽取简化 — 完成

- [x] `extract_ideas_from_summary` 只返回 title(`kb_llm.py:1222`)
- [x] LLM prompt 只要求 title
- [x] 过滤掉没标题的(`kb_llm.py:1248`)
- [x] `extract_todos_from_summary` 只返回 title(`kb_llm.py:1262`)

## 文件格式简化 — 完成

- [x] `_format_idea_suggestion` 只写 title + id + status + source(`kb.py:2452`)
- [x] `_format_todo_suggestion` 只写 title + id + status + source(`kb.py:2473`)
- [x] `_format_formal_idea` 只写 title + id + status + maturity + sources(`kb.py:2494`)
- [x] `_format_weekly_task` 只写 title + 来源 + 截止日期(`kb.py:2518`)
- [x] 删掉 estimated_time / priority / difficulty / recommended_area / feasibility / novelty
- [x] 旧数据带这些字段时精简格式忽略(向后兼容)

## Web 新建 idea — 完成

- [x] `POST /api/ideas` 新建 idea
- [x] `accepted_general` 状态(跳过 review,直接进 general_ideas.md)
- [x] 与抽取链路 pending_review 状态区分

## completed_at 字段 — 完成

- [x] `write_task_file` 维护 completed_at 生命周期(首次 done 写入 / 重复不覆盖 / 重新激活清空)
- [x] 工作台「本周完成数」按 completed_at 统计(`services/cards.py:378`)
- [x] 旧任务无该字段算未完成(向后兼容)

## 验收测试 — 完成

- [x] `test_web_create_idea.py` Web 新建 idea + accepted_general
- [x] `test_format_helpers.py` 精简格式验证(+2 用例)
- [x] `test_suggestions.py` idea suggestion 简化
- [x] `test_kb_llm_bugs.py` extract 只返回 title
- [x] 359 passed(346 → 359,+8)
