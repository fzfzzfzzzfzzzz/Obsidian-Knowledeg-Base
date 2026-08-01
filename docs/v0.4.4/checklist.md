# v0.4.4 任务清单

> 日期:2026-07-19(规划,待开工)
> PRD 见 `v044_web_refactor_PRD.md`,changelog 待发布时写

## 0. 文档范围

纯结构重构,无新功能。两大块:① `kb_web.py` 按域拆 8 个 APIRouter + services 分层 ② `kb.py` 公共工具抽取。

## P0(必须)

### 步骤 1:目录骨架
- [ ] 建 `scripts/web/__init__.py`
- [ ] 建 `scripts/web/routers/__init__.py`
- [ ] 建 `scripts/web/services/__init__.py`
- [ ] 建 `scripts/web/utils.py`(空)
- [ ] 建 8 个 router 空文件:dashboard / articles / ideas / todos / calendar / collections / search / tags / ingest
- [ ] 建 4 个 service 空文件:parsing / cards / state_io / status
- [ ] 跑测试确认 import 不破(161 passed)

### 步骤 2:抽 services 层
- [ ] `services/parsing.py`:`_parse_frontmatter` / `_parse_suggestion_file` / `_split_suggestion_blocks` 包装(继续委托 kb)
- [ ] `services/utils.py`:`VALID_IDEA_STATUS` / `VALID_TODO_STATUS` / 备份函数 / 路径 helper
- [ ] `services/state_io.py`:`_save_reading_state` / `_set_article_tags` / `_get_article_tags` / `_ensure_reading_fields` / `_read_summary_frontmatter_tags` / `_write_summary_frontmatter_tags`
- [ ] `services/cards.py`:`_build_card` / `_all_cards` / `_build_dashboard` / `_scan_summaries`
- [ ] `services/status.py`:`_update_suggestion_status` / `_check_suggestion_current_status`
- [ ] kb_web.py 保留 re-export(`from .services.* import *`)兼容现有测试
- [ ] 每迁一组跑一次 161 passed

### 步骤 3:拆 routers(逐个迁移,每迁一个跑测试)
- [ ] `routers/search.py`:page_search + /api/search
- [ ] `routers/tags.py`:/api/article/{id}/tags (get/post/delete/ai)
- [ ] `routers/collections.py`:page_favorites + /api/favorites + /api/collections (CRUD)
- [ ] `routers/calendar.py`:page_calendar + /api/calendar (CRUD) + detected-dates
- [ ] `routers/ideas.py`:page_ideas + /api/ideas + /api/ideas/confirmed + /api/idea/{id}/status + generate-ideas
- [ ] `routers/todos.py`:page_todos + /api/todos + /api/todos/confirmed + /api/todo/{id}/status + generate-todos
- [ ] `routers/articles.py`:page_summary/articles/recent + /api/summaries + /api/summary/{id} + /api/articles + /api/article/{id} (delete/read-later/favorite/collections)
- [ ] `routers/dashboard.py`:page_index + /api/dashboard + /api/dashboard_full + /api/recent + /api/health
- [ ] `routers/ingest.py`:page_submit + /api/ingest + /api/ingest-image + /api/batch + /api/pending-summaries + generate/regenerate/delete summary(最后迁,最复杂)
- [ ] kb_web.py 主文件 `app.include_router(<name>.router)` 装配全部 9 个 router
- [ ] kb_web.py 主文件 < 300 行(只剩 app 创建、CORS、middleware、include_router、mount static、templates 挂载)

### 步骤 4:kb.py 公共工具抽取
- [ ] 加 `hash_from_source_id(sid)` 替代 3 处魔法剥离
- [ ] 加 `_make_note_filename(prefix, sid, date_str, title)` 合并 make_source_filename / make_summary_filename
- [ ] 加 `_strip_inbox_header_lines(lines)` 统一 inbox 头剥离(3 处共享)
- [ ] 加 `_count_status_in_file(path, prefix)` 替代 cmd_status 的 4 段重复
- [ ] `_extract_summary_body` 改为复用 `parsefrontmatter(text)[1]`
- [ ] `kb_llm._summary_outline` 改名 `summary_outline`(去下划线),更新 kb.py:1710 调用点
- [ ] 新增 `tests/test_kb_common.py` 覆盖抽出的 helper

### 步骤 5:smoke test + 真实验证
- [ ] 新增 `tests/test_web_routers.py`:9 个 router 各 1 个 smoke test
- [ ] 全套测试 161 + N 全过
- [ ] 真实 vault `kb.py serve` 启动后手动点遍各页面(/、/ideas、/todos、/calendar、/favorites、/search、/submit、/articles、/recent、/summary/<id>)
- [ ] 真实 vault `kb.py status` 输出与 v0.4.3 一致
- [ ] git diff 显示无业务逻辑变更(纯搬迁)

## P1(应该)

- [ ] 每个 router 文件顶部加 docstring 说明该域职责
- [ ] services 层函数加类型提示(趁机补齐 `args: argparse.Namespace` → `-> int` 等)
- [ ] 删 kb.py 内被合并函数的死代码(确认无引用后)

## P2(可选,可不做)

- [ ] Pydantic 模型集中到 `web/models.py`(目前散在各 router)
- [ ] router 用 `APIRouter(prefix="/api/idea", tags=["ideas"])` 简化路径
- [ ] 加 mypy / ruff 检查

## 风险红线

- 任何一个 router 迁移后测试连续红超过 30 分钟 → 立即回退该 router,记入下次会话笔记
- 出现循环 import → services 层不能 import routers;routers 单向依赖 services
- FastAPI 路由顺序异常(`/api/articles` vs `/api/article/{id}` 前缀冲突)→ 显式声明路由顺序,用 `APIRouter(prefix=...)` 隔离

## 不在范围

- TypedDict / dataclass 改造(留 v0.4.5)
- 静态模板外迁(留 v0.4.5)
- 前端 `app.js` 拆分(独立线)
- CSS 令牌贯彻(独立线)
- `alert()` 全替换(独立线)
