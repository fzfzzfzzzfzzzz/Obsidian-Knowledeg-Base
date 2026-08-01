# v0.4.4 PRD:kb_web.py 按域拆分 + kb.py 公共工具抽取

> 日期:2026-07-19(规划)
> 上一版:v0.4.3(见 `docs/v0.4.3/`)
> 性质:纯结构重构,无新功能,无破坏性变更
> 来源:v0.4.3 阶段 5(用户选择延后到专项会话)

## 0. 文档定位

本 PRD 是给**下一次会话**的开工指南。v0.4.3 完成了测试网补齐(161 passed),为本重构铺好保险绳。本版要把 `kb_web.py`(2117 行 / 57 路由)和 `kb.py`(2300+ 行)做结构性拆分,降低后续维护成本。

**核心原则**:零行为变更。所有 API 响应、CLI 输出、文件格式、前端交互必须与 v0.4.3 完全一致。验收标准是 161 个测试全部通过,不增不减(可新增少量 smoke test 验证 router 装配)。

---

## 1. 动机

### 1.1 `kb_web.py` 单文件巨型化

当前 `kb_web.py` 2117 行,在一个文件里承载:
- 12 个页面路由(`page_*`)
- 45 个 API 路由(`api_*`)
- 几十个业务 helper(`_build_card` / `_parse_suggestion_file` / `_scan_summaries` / `_set_article_tags` / `_update_suggestion_status` / ...)

后果:
- 改一个域(如 calendar)要在 2000+ 行里跳来跳去
- 8 个不同业务域混在一起,无 file-level 边界
- 新人定位"收藏夹逻辑在哪"需要全文搜索

### 1.2 `kb.py` 公共工具重复

代码审查发现至少 6 处重复:
- `make_source_filename`(192-204) 与 `make_summary_filename`(207-214) 几乎一致,仅前缀不同
- `source_id.replace("source_ff_", "").replace("source_", "")` 魔法剥离出现在 3 处(202 / 212 / 382)
- inbox 头部剥离逻辑重复 3 处(`parse_freeform_items` / `has_kb_item_markers` / `_strip_inbox_header`)
- `cmd_status` 的 4 段 `read_text().count()` 重复(1259-1278)
- `kb.py:1710/1719` 跨模块访问 `kb_llm._summary_outline`(私有)
- frontmatter 解析(v0.4.3 已部分统一,仍有 `_extract_summary_body` 一处独立实现)

---

## 2. 范围内

### 2.1 `kb_web.py` 按域拆 8 个 APIRouter + services 分层

**目标目录结构**:

```
scripts/
  kb_web.py                  # 主文件:app 创建、CORS、middleware、include_router、模板挂载(约 200 行)
  web/
    __init__.py
    routers/
      __init__.py
      dashboard.py            # GET / + /api/dashboard + /api/dashboard_full + /api/recent + /api/health
      articles.py             # /api/summary* / /api/article/* (read) + page_summary/articles/recent
      ideas.py                # /api/idea* / /api/ideas* + page_ideas
      todos.py                # /api/todo* / /api/todos* + page_todos
      calendar.py             # /api/calendar* + page_calendar
      collections.py          # /api/collections* / /api/favorites + page_favorites
      search.py               # /api/search + page_search
      tags.py                 # /api/article/*/tags*
      ingest.py               # /api/ingest / /api/ingest-image / /api/batch + page_submit
    services/
      __init__.py
      parsing.py              # _parse_frontmatter / _parse_suggestion_file / _split_suggestion_blocks 包装
      cards.py                # _build_card / _all_cards / _build_dashboard / _scan_summaries
      state_io.py             # _save_reading_state / _set_article_tags / _get_article_tags / _ensure_reading_fields
      status.py               # _update_suggestion_status / _check_suggestion_current_status / move_accepted_* 调用层
    utils.py                  # 共享 helper:路径 / 备份 / VALID_*_STATUS 白名单
```

**搬迁原则**:
- `_parse_frontmatter` 已委托 `kb.parsefrontmatter`,services/parsing.py 继续委托,不重新实现
- 每个 router 文件 `from ..services import cards, parsing, state_io`
- `VALID_IDEA_STATUS` / `VALID_TODO_STATUS` 移到 `web/utils.py`
- FastAPI app 在主文件里 `app.include_router(dashboard.router)` 装配,每个 router 用 `APIRouter(prefix=...)` 或显式前缀
- 所有 `_build_*` / `_parse_*` 业务函数移到 services,路由文件只做参数校验 + 调 service + 返回响应
- Pydantic 模型(`StatusUpdate` / `IngestRequest` / `BatchRequest` / `CalendarItem*`)移到 `web/models.py` 或各 router 文件内

**路由归属表**(57 个路由的精确分配):

| Router | 页面路由 | API 路由 |
|---|---|---|
| dashboard | `GET /` | `/api/dashboard` `/api/dashboard_full` `/api/recent` `/api/health` |
| articles | `GET /summary/{id}` `/articles` `/recent` `/favorites`(列表部分) | `/api/summaries` `/api/summary/{id}` `/api/articles` `/api/article/{id}` (delete) `/api/article/{id}/read-later` `/api/article/{id}/favorite` `/api/article/{id}/collections` `/api/article/{id}/summary` (delete) |
| ideas | `GET /ideas` | `/api/ideas` `/api/ideas/confirmed` `/api/idea/{id}/status` `/api/article/{id}/generate-ideas` |
| todos | `GET /todos` | `/api/todos` `/api/todos/confirmed` `/api/todo/{id}/status` `/api/article/{id}/generate-todos` |
| calendar | `GET /calendar` | `/api/calendar` (CRUD + list + single) `/api/article/{id}/detected-dates` `/api/article/{id}/detect-dates` |
| collections | `GET /favorites` | `/api/favorites` `/api/collections` (CRUD) `/api/collections/{id}/articles` |
| search | `GET /search` | `/api/search` |
| tags | (无) | `/api/article/{id}/tags` (get/post/ai) `/api/article/{id}/tags/{tag}` (delete) |
| ingest | `GET /submit` | `/api/ingest` `/api/ingest-image` `/api/batch` `/api/pending-summaries` `/api/generate-summary/{id}` `/api/article/{id}/regenerate-summary` |

**注意**:summary 重生成路由归属 ingest 还是 articles 需要定。建议 generate/regenerate/delete summary 都进 ingest(它们是写操作,触发 LLM),articles 只保留读 + 阅读状态。

### 2.2 `kb.py` 公共工具抽取

**目标**:在 `kb.py` 内部加一个"公共工具"section(不抽独立模块,改动面小),集中以下 helper:

| 新 helper | 替代的重复代码 | 位置 |
|---|---|---|
| `hash_from_source_id(sid)` | `source_id.replace("source_ff_", "").replace("source_", "")` × 3 | kb.py:202/212/382 |
| `_make_note_filename(prefix, sid, date, title)` | `make_source_filename` + `make_summary_filename` 合并 | kb.py:192-214 |
| `_strip_inbox_header_lines(lines)` | `parse_freeform_items` / `has_kb_item_markers` / `_strip_inbox_header` 共享 | kb.py:305-317/348-358/1210-1222 |
| `_count_status_in_file(path, prefix)` | `cmd_status` 的 4 段重复 | kb.py:1259-1278 |
| `_extract_summary_body` 复用 `parsefrontmatter` | 当前独立实现 regex | kb.py:1654-1656 |

**跨模块私有访问**:
- `kb.py:1710` 调 `kb_llm._summary_outline`:在 `kb_llm.py` 把 `_summary_outline` 改名为 `summary_outline`(去下划线),或加公开包装 `build_summary_outline()`。同步更新所有调用点。
- `kb.py:1719` 读 `kb_llm.SUMMARY_SYSTEM_PROMPT`:这个是大写常量,本来就是 public,不用改。

### 2.3 测试

- **现有 161 个测试不动**(它们的 import 路径不变:`import kb` / `import kb_web`)
- 新增 `scripts/tests/test_web_routers.py`:每个 router 至少 1 个 smoke test,确认 `app.include_router` 后端点可访问(如 GET / 返回 200)
- 新增 `scripts/tests/test_kb_common.py`:覆盖抽出的公共 helper(`hash_from_source_id` / `_make_note_filename` / `_strip_inbox_header_lines` / `_count_status_in_file`)

---

## 3. 范围外(整体)

- **不**抽独立 `kb_config.py` 模块(v0.4.3 已做环境变量覆盖,够用)
- **不**改 import-time 冻结的根本机制(只让冻结时读环境变量)
- **不**动 vault 内容文件格式
- **不**改 API 响应 schema
- **不**改 CLI 命令行为
- **不**引入新依赖
- **不**做 TypedDict / dataclass 改造(改面大,留 v0.4.5)
- **不**外迁静态模板字符串到 `scripts/templates/`(同上)
- **不**重构前端(`app.js` 1199 行、`submit.html` 内嵌 545 行 JS)— 前端是另一条线

---

## 4. 实施步骤(建议执行顺序)

### 步骤 1:建目录骨架(15 分钟,风险极低)
- 建 `scripts/web/__init__.py` / `routers/__init__.py` / `services/__init__.py`
- 空 `utils.py` / 各 router 空文件
- 跑测试确认 import 不破

### 步骤 2:抽 services 层(2 小时,中风险)
- 先迁 `services/parsing.py`(最简单,已委托 kb)
- 再迁 `services/utils.py`(VALID_*_STATUS、备份函数、路径 helper)
- 然后 `services/state_io.py`(`_save_reading_state` / `_set_article_tags` / `_get_article_tags` / `_ensure_reading_fields`)
- 然后 `services/cards.py`(`_build_card` / `_all_cards` / `_build_dashboard` / `_scan_summaries`)
- 最后 `services/status.py`(`_update_suggestion_status` / `_check_suggestion_current_status`)
- 每迁一组跑一次测试,确认 kb_web.py 内的引用都改成 `from .services import xxx`
- kb_web.py 保留 re-export(`from .services.state_io import _set_article_tags`)以兼容现有测试的 `kb_web._set_article_tags` 引用

### 步骤 3:拆 routers(3-4 小时,高风险)
- 一次拆一个 router,从最小的开始(search → tags → collections → calendar → ideas → todos → articles → dashboard → ingest)
- 每个 router:
  1. 建 `routers/<name>.py`,`router = APIRouter()`
  2. 把对应路由函数搬过去,`@app.X` 改成 `@router.X`
  3. 在 kb_web.py 主文件 `app.include_router(xxx.router)`
  4. 跑测试
- ingest router 最后拆(最复杂,涉及 LLM + 图片上传 + 批量)

### 步骤 4:kb.py 公共工具抽取(1 小时,低风险)
- 加 `hash_from_source_id` / `_make_note_filename` / `_strip_inbox_header_lines` / `_count_status_in_file`
- 替换所有重复点
- 让 `_extract_summary_body` 复用 `parsefrontmatter`
- `kb_llm._summary_outline` 改名 `summary_outline`,更新调用点
- 新增 `test_kb_common.py`

### 步骤 5:smoke test + 真实验证(30 分钟)
- 新增 `test_web_routers.py` 跑通
- 全套测试 161 → 161+N 全过
- 真实 vault `kb.py serve` 启动后手动点一遍各页面
- 真实 vault `kb.py status` 输出不变

---

## 5. 验收标准

- [ ] 全量测试通过(161 + 新增 smoke/helper test)
- [ ] `kb.py serve` 启动正常,所有页面 200
- [ ] 12 个页面路由 + 45 个 API 路由全部可访问(用 `test_web_routers.py` 覆盖)
- [ ] `kb_web.py` 主文件 < 300 行(只剩 app 装配)
- [ ] `kb.py` 6 处重复代码消除
- [ ] 无循环 import
- [ ] git diff 显示**无任何业务逻辑变更**(纯搬迁)
- [ ] 真实 vault status 输出与 v0.4.3 完全一致

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 循环 import(services ↔ routers) | services 不 import routers;routers 单向依赖 services |
| 测试引用 `kb_web._private_func` 失败 | kb_web.py 保留 re-export(`from .services import *`) |
| FastAPI 路由顺序变化导致匹配异常 | 逐个 router 迁移,每次跑测试;特别注意 `/api/articles` vs `/api/article/{id}` 这种前缀冲突 |
| `app.mount("/static", ...)` 在主文件还是 router | 留主文件(全局资源) |
| 模板 `templates` 对象的共享 | 留主文件,作为 app.state.templates 或 module-level 注入 |

---

## 7. 不做这一版的兜底方案

如果重构过程中发现风险过大(测试大面积红、循环 import 解不开),可以:
- 回退到 v0.4.3 状态(`git checkout`)
- 只保留"kb.py 公共工具抽取"部分(低风险)
- 把 `kb_web.py` 拆分留到 v0.4.5

**判断标准**:如果在步骤 3(拆 routers)中,某个 router 迁移后测试连续红超过 30 分钟无法修复,立即回退该 router,不要硬推。
