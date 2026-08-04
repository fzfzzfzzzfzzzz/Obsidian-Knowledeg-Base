# Changelog v0.4.26

> 日期:2026-08-04
> 主题:**Web 手动新建 Plan**
> 用户可见变化见根 [`../../CHANGELOG.md`](../../CHANGELOG.md#-0426--2026-08-04);本文件记录开发细节。

---

## 新增

### 1. Web 手动新建 Plan

**背景**
Plan 原只能从 summary 由 LLM 抽取,无法用户主动发起;
对「我现在就想要执行某件事,不需要 AI 提炼」的场景不友好。

**实现**
- Plan 页加 `+ 新建 plan` 按钮,点击打开模态框,输入标题后创建。
- 创建后直接追加到 `04_Plans/plan_suggestions.md`,与 AI 抽取的候选共用同一个 review 队列。
- 状态默认 `pending_review`,走与 AI 候选相同的「接受 → 创建独立 plan_*.md」流程。
- id 格式:`plan_suggestion_{YYYYMMDD}_{slug}_{random_hex}`,随机 4 字节后缀防止同名 plan 冲突。

### 2. `POST /api/plans` 端点

**背景**
需要一个 API 让前端触发 plan 创建。

**实现**
- 入参 `PlanCreate { title: str }`,空标题(含纯空白)返回 400。
- 复用 `_append_section` 追加到 `plan_suggestions.md`。
- 与 LLM 抽取的 plan 走同一队列,复用 accept 流程,无新数据源。
- 不依赖 `_format_plan_suggestion`(后者需要 `source_summary` 关联来源文章,手动创建无来源)。

---

## 文件改动

| 类别 | 文件 |
|------|------|
| 路由 | `scripts/web/routers/plans.py`(新增 `POST /api/plans`) |
| 模板 | `scripts/web/templates/plans.html`(新建按钮 + 模态框表单) |
| 测试 | `scripts/tests/test_plans.py`(+3 测试:追加/空标题/id 唯一) |

---

## 不在本次范围

- 新建时不支持填 deadline(留到「接受」弹窗里填,与 AI 候选一致)。
- 新建时不支持关联来源文章(手动发起本身无来源)。
- 批量新建(一次创建多条 plan)未做。

---

## 测试

+3 测试,总计 **460 passed**。

| 测试 | 内容 |
|------|------|
| `test_api_plans_create_appends_to_suggestions` | POST 后文件写入 + GET 能读回 |
| `test_api_plans_create_empty_title_400` | 纯空白标题 → 400 |
| `test_api_plans_create_id_unique` | 连续两条同名 plan 的 id 不同(随机后缀) |
