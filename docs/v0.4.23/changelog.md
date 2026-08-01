# Changelog v0.4.23

> 日期:2026-07-28 ~ 2026-08-01
> 主题:**todo→plan 域迁移 + market 重构 + task 增强 + UI 改进 + 版本管理规范化**
> 用户可见变化见根 [`../../CHANGELOG.md`](../../CHANGELOG.md#-0423--2026-08-01);本文件记录开发细节。

---

## 新增

### 1. Plan 域(替代 Todo)

**背景**:原 Todo 按 weekly / monthly / someday 分桶,与 Task 的「独立文件 + deadline」模式割裂,
两套机制并存增加维护成本。

**实现**:
- 新增 `web/routers/plans.py`,删除 `web/routers/todos.py`(Git 识别为 `todos.html→plans.html` 50% rename)。
- `kb.py` / `kb_entities.py`:plan 实体走独立 `plan_*.md` 文件,frontmatter 含可选 `deadline`,
  复用 Task 的存储七件套骨架(make_id / file_path / find / load / scan / write / sync)。
- `GenerateTodosRequest` → `GeneratePlansRequest`,去掉 `plan` 分桶字段(weekly/monthly/someday)。
- 模板:`plan_suggestion_template.md`;移除 `weekly_template` / `monthly_template` / `todo_suggestion_template`。
- 测试:`test_plans.py` / `test_plan_calendar_link.py` / `test_generate_ideas_plans.py` 替代旧 todo 三件套。

### 2. Market 重构

- 拆分 `kb_quote.py`(行情数据)为独立模块,与 `kb_date.py` / `kb_entities.py` 同级。
- `MarketCreate` 去掉 alert 相关字段(`date` / `trigger` / `direction` / `magnitude`),
  `kind` 收敛为仅 `watchlist`;异动需求改由事件系统承载。
- `web/routers/market.py` +847 行:聚合视图、个股详情(`/market/stock/{ticker}`)、
  个人自选、判断(judgments)四个子视图。
- 新增模板:`stock_detail.html` / `watchlist.html` / `market_judgments.html`。
- 新增前端:`market-personal.js` / `market-judgments.js` / vendored `sortable.min.js`(拖拽排序)。

### 3. Task `next_action` 字段

- `TaskCreate` / `TaskUpdate` 新增 `next_action`(下一步行动),CRUD 与 Web API 同步。
- `test_tasks.py` 补 next_action 用例。

### 4. 侧栏折叠

- 左侧导航支持折叠 / 展开,状态存 localStorage(`kb-sidebar-collapsed`)。
- `base.html` 加防闪脚本:CSS 加载前应用折叠状态,避免刷新时先展开再缩回。

---

## 变更

### 1. todo→plan 术语全量同步

`AGENTS.md` / `PRODUCT.md` / `README.md` / `VAULT_STRUCTURE.md` 四个根文档把 todo 术语
统一改为 plan,与代码层对齐。`accept-todos` → `accept-plans`,`extract-suggestions` 抽 idea/plan。

### 2. 版本管理规范化

历史问题:版本号散在 4 处文档且互相打架(README = Phase 0+1,PRODUCT = v0.4.7,
AGENTS 页脚 = v0.4.18+,ROADMAP = v0.4.16+,实际 v0.4.23);版本文件夹内部命名后期漂移
(`v0413_PRD.md` / `v099_PRD.md` 等,其中 v099 是笔误)。

**修复**:
- 引入根 `VERSION` 文件作为版本号单一数据源;README / PRODUCT / AGENTS / ROADMAP 的硬编码
  版本号改为引用 VERSION。
- 新建根 `CHANGELOG.md`(Keep a Changelog 格式,记用户可见变化)。
- `docs/vX.Y.Z/` 内部文件统一为 `PRD.md` / `checklist.md` / `changelog.md`(对齐 `docs/README.md` 规则);
  修正 v0.4.9 的 `v099_` 笔误。
- `overview.md` / `AGENT_SUMMARIZE.md` 从根目录挪进 `docs/`(根目录只留面向用户的入口文档)。
- 给 v0.4.22 打 git tag(此前 0 个 tag,版本只活在 commit message 里)。

---

## 文件改动

| 类别 | 文件 |
|------|------|
| 新增模块 | `scripts/kb_quote.py` |
| 新增 router | `scripts/web/routers/plans.py` |
| 删除 router | `scripts/web/routers/todos.py` |
| 新增模板 | `plans.html` / `stock_detail.html` / `watchlist.html` / `market_judgments.html` |
| 删除模板 | `todos.html` |
| 新增静态 | `market-personal.js` / `market-judgments.js` / `sortable.min.js` |
| 新增测试 | `test_plans` / `test_plan_calendar_link` / `test_generate_ideas_plans` / `test_market_judgments` / `test_market_personal` / `test_market_quote_cache` |
| 删除测试 | `test_generate_ideas_todos` / `test_todo_calendar_link` |
| 版本管理 | `VERSION` / `CHANGELOG.md`(根,新建) |
| 文档归位 | `overview.md` → `docs/overview_dark_contrast.md`;`AGENT_SUMMARIZE.md` → `docs/` |

---

## 不在本次范围

- **kb.py 拆分**:kb.py 现 2641 行,超 AGENTS.md 原红线(~1500 基线 / ~1800 警戒)。
  本版决定**暂不拆**,改为上调红线并注明「CLI + 基础设施流水线允许超出」(见 AGENTS.md 更新)。
  下一次若有业务域再长进来,优先拆出 `kb_ingest.py` / `kb_prompts.py`。
- v0.4.17 ~ v0.4.21 仍无独立版本文件夹(其工作已合并归档在 `docs/v0.4.16/changelog.md`
  与根 CHANGELOG 中)。

---

## 测试

427 passed,1 warning(FastAPI TestClient 的 httpx 弃用提示,非本项目问题)。
