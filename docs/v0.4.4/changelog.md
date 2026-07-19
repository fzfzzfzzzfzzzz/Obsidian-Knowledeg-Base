# Changelog v0.4.4

> 日期:2026-07-19
> 主题:`kb_web.py` 按域拆分 + `kb.py` 公共工具抽取(纯结构重构,零行为变更)

按 `docs/v0.4.4/v044_web_refactor_PRD.md` 完成纯结构重构,验收标准全部达成。

---

## 一、`kb_web.py` 按域拆分

`scripts/kb_web.py`:**2117 行 → 74 行** 装配文件,只负责 app 创建、static 挂载、include_router、向后兼容 re-export。

拆出的 `scripts/web/` 包(2819 行,均为纯搬迁):

```
scripts/web/
  __init__.py
  models.py               10 个 Pydantic 模型(StatusUpdate / IngestRequest / BatchRequest / CalendarItem* 等)
  utils.py                共享常量(VALID_IDEA_STATUS / VALID_TODO_STATUS)+ 模板挂载
  routers/
    __init__.py
    dashboard.py          # /  /api/dashboard  /api/dashboard_full  /api/recent  /api/health
    articles.py           # /summary/{id} /articles /recent /favorites  +  /api/summary* /api/article/* (read/delete/state)
    ideas.py              # /ideas  +  /api/idea* /api/ideas* /api/article/{id}/generate-ideas
    todos.py              # /todos  +  /api/todo* /api/todos* /api/article/{id}/generate-todos
    calendar.py           # /calendar  +  /api/calendar (CRUD) /api/article/{id}/detect*-dates
    collections.py        # /favorites  +  /api/favorites /api/collections (CRUD)
    search.py             # /search  +  /api/search
    tags.py               # /api/article/{id}/tags (get/post/delete/ai)
    ingest.py             # /submit  +  /api/ingest /api/ingest-image /api/batch /api/pending-summaries /api/generate-summary* /api/article/{id}/regenerate-summary
  services/
    __init__.py
    parsing.py            # _parse_frontmatter / _parse_suggestion_file(继续委托 kb)
    cards.py              # _build_card / _all_cards / _build_dashboard / _scan_summaries
    state_io.py           # _save_reading_state / _set_article_tags / _get_article_tags / _ensure_reading_fields / _read/_write_summary_frontmatter_tags
    status.py             # _update_suggestion_status / _check_suggestion_current_status
```

**实际注册路由 48 个**(12 页面 + 36 API;PRD 估算 57 偏多,差额是部分路径合并到了同一 router 的多 method)。

**向后兼容**:kb_web.py 保留 `from .web.services.* import *` re-export,现有测试(`test_reject_delete.py` / `test_web_accept_moves.py` 等)的 `kb_web._xxx` 引用全部不破。

---

## 二、`kb.py` 公共工具抽取

| 新增 helper | 替代的重复 |
|---|---|
| `hash_from_source_id(sid)` | 2 处 `source_id.replace("source_ff_","").replace("source_","")` 魔法链 |
| `make_note_filename(prefix,sid,date,title)` | 合并 `make_source_filename` / `make_summary_filename`(保留薄包装函数兼容现有调用) |
| `_strip_inbox_header_lines(lines)` | 3 处 inbox 头剥离逻辑统一(parse_freeform_items / has_kb_item_markers / _strip_inbox_header) |
| `_count_status_in_file(path,prefix)` | `cmd_status` 的 4 段重复 `.count()` |
| `_extract_summary_body` 复用 `parsefrontmatter` | 独立的 regex 实现 |
| `kb_llm.summary_outline`(去下划线公开) | `kb.py:1767` 原跨模块访问私有 `_summary_outline`,现走公开接口 |

---

## 三、验证结果

- **全量测试 172 passed**(v0.4.3 是 161,+11:`test_web_routers.py` ×3 + `test_kb_common.py` ×8)
- 真实 vault `kb.py status` 输出与 v0.4.3 **逐字节一致**
- 真实 vault 全部 10 个页面路由 GET → 200,无循环 import
- `kb_web.py` 主文件 < 300 行 ✅(实际 74 行)
- git diff 显示**无业务逻辑变更**(纯搬迁 + helper 抽取)

---

## 四、踩坑记录(已解决)

1. `app.routes` 中 router 路由 `path=None` 是 **inspect 假象**;OpenAPI schema 才是路由注册权威来源,不要被误导改路由声明。
2. 测试 fixture(`isolate_vault`)只 patch 模块级变量,故 router body 内 `VAULT_ROOT` 全局替换为 `kb.VAULT_ROOT`(运行时跟随 kb.VAULT_ROOT);主文件保留 `VAULT_ROOT = kb.VAULT_ROOT` import-time 拷贝用于启动期。
3. pytest 跑在 system Python(`D:/Python/python.exe`)而非 managed venv,导入路径靠 `conftest.py` 的 `sys.path.insert`。

---

## 五、清理

- 删除一次性 AST 抽取脚本 `_gen_refactor.py`(避免误跑覆盖 hand-tuned 的 `web/`)
- 沉淀可复用 skill:`fastapi-monolith-split`(用户级,后续类似重构可调用)

---

## 不变

- API 响应 schema、CLI 命令行为、文件格式、前端交互**全部不变**
- 161 个旧测试零修改通过(仅 re-export 保证引用兼容)
- vault 内容零改动

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/kb_web.py` | 2117 → 74 行(纯装配 + re-export) |
| `scripts/kb.py` | +公共工具 section(hash_from_source_id / make_note_filename / _strip_inbox_header_lines / _count_status_in_file / _extract_summary_body 复用) |
| `scripts/kb_llm.py` | `_summary_outline` → `summary_outline`(公开化) |
| `scripts/web/**`(新) | routers/ ×9 + services/ ×4 + models.py + utils.py + __init__.py |
| `scripts/tests/test_web_routers.py`(新) | 3 个 smoke test 验证 router 装配 |
| `scripts/tests/test_kb_common.py`(新) | 8 个 helper 单测 |

---

## 破坏性变更

**无**。纯结构重构,所有外部行为保持不变。
