# Changelog v0.4.0

> 日期:2026-07-17

## 新增
- **详情页手动生成 Idea/Todo**:文章详情页操作栏新增「💡 生成 Idea 列表」「✅ 生成 Todo 列表」两个按钮(仅有 summary 时显示)
- **引导弹窗**:点击后弹窗,可输入引导提示词(可选)+ 手动选优先级 / 领域(idea)/ 难度 · 预计时间 · 计划(todo),所有参数默认「不限」
- **参数语义=引导(非硬约束)**:用户所选拼成 hint 传给 LLM,system prompt 明确「优先体现但不强制套用到所有候选」;一次产出多条候选(1-3 条)
- **新接口**:`POST /api/article/{id}/generate-ideas`、`POST /api/article/{id}/generate-todos`
- **kb_llm 改造**:`extract_ideas_from_summary` / `extract_todos_from_summary` 新增 `hint` 可选参数 + `_with_hint()` 辅助函数,向后兼容(不带 hint 时行为不变)

## 不变
- summary 生成流程不自动抽取 idea/todo(本就不抽)
- 首页批量「💡 抽 idea/todo」按钮 + CLI `extract-suggestions` 保留不变
- 生成的候选仍 `status=pending_review`,需在 /ideas /todos 页 accept + 跑 CLI 进正式清单

## 文件改动
- `kb_llm.py`:两个 extract 函数加 `hint` 参数 + `_with_hint` + system prompt 补引导说明
- `kb_web.py`:新增 `GenerateIdeasRequest` / `GenerateTodosRequest` + `_build_hint` + 2 个 POST 端点
- `summary.html`:详情页操作栏加 2 个按钮
- `app.js`:新增 `openGenerateDialog(kind, sourceId)` 表单弹窗
- `style.css`:`.cal-form-field select` 样式
- `base.html`:cache buster +1
- `tests/test_generate_ideas_todos.py`:12 个测试
