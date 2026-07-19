# Changelog v0.4.3

> 日期:2026-07-19
> 主题:代码健康度提升 + 数据自愈 + Web 体验闭环 + 云端部署就绪

本版没有面向终端用户的大功能,而是一次系统的**结构性维护**:补测试网、加数据自愈命令、打通 Web accept 全流程、为云端部署扫清路径配置障碍。所有改动都有测试兜底(100 → 161 passed)。

---

## 新增

### 1. `rebuild-index` 命令(ROADMAP P1-2 落地)

state.json 与 summary frontmatter 不一致时一键自愈。

- **数据流向**:summary frontmatter → state.json(frontmatter 为权威)
- **同步字段**:`summary_path`(回填 + 修正)、`tags`(补 + 以 frontmatter 为准更新)
- **保护字段**:**不碰** `is_favorite` / `read_count` / `last_read_at` / `collection_ids` / `detected_dates` 等任何用户行为数据
- **保守策略**:frontmatter 无 tags 但 state 有 → **保留**(可能是用户手加),不删
- **安全网**:写前 `shutil.copy2` 备份到 `.kb/logs/web_backups/state_rebuild_YYYYMMDD.json.bak`
- **CLI 参数**:
  - `--dry-run`:只报告差异,不写文件
  - `--tags-only`:只同步 tags
  - `--summary-path-only`:只回填 summary_path
  - `-v / --verbose`:列出每条变更明细
- **孤儿报告**:state 里有 summary_path 但 `02_Summaries/` 找不到对应文件时,在报告中标记为 orphan

**真实 vault 验证**:41 个 summary 跑 `--dry-run`,0 回填 / 0 修正 / 0 更新——说明此前手动维护得很齐,这正是预期表现。

### 2. Web 端「接受即搬运」(ROADMAP P1-15 落地)

消除 Web 改 status + CLI 搬运的流程割裂。

- **触发**:用户在 `/ideas` 或 `/todos` 页点「接受·科研 / 本周 / 本月 / someday」时,后端在改完 status 后**自动调**搬运逻辑
- **搬运目标**:
  - idea:`accepted_research` → `03_Ideas/research_ideas.md`;`accepted_productivity` → `productivity_ideas.md`
  - todo:`accepted_weekly` → `04_Plans/Weekly/<week>.md`(自动 `_ensure_weekly_file`);`accepted_monthly` → `Monthly/<month>.md`;`accepted_someday` → `someday.md`
- **原 suggestion 块**:搬运后 status 改为 `moved`(保留追溯,不删除)
- **前端 toast 升级**:从「已更新状态」变为「✓ 已加入「research」idea 列表(03_Ideas/research_ideas.md)」等具体反馈
- **幂等保护**:已 `moved` 状态的块再次收到 accepted_* 请求时,no-op 返回 `move_reason: already_moved`,不重复搬运
- **rejected 不搬**:rejected 仍走原「直接删块」路径,不触发搬运
- **规则合规**:仍是"只有用户接受的才进正式清单",只是搬运步骤从 CLI 移到 Web,执行时机更早

### 3. 路径配置派生量化(云端部署加固)

`KB_VAULT_ROOT` 环境变量此前只覆盖了 `VAULT_ROOT` 一个常量,其余 5 个派生量仍在 import 时按默认布局算死。本版全部支持环境变量独立覆盖:

| 环境变量 | 默认(未设置时) | 用途 |
|---|---|---|
| `KB_VAULT_ROOT` | `scripts/` 的父目录 | vault 根 |
| `KB_DIR` | `<VAULT_ROOT>/.kb` | 机器运行目录 |
| `KB_STATE_FILE` | `<KB_DIR>/state.json` | state 文件 |
| `KB_CALENDAR_FILE` | `<KB_DIR>/calendar.json` | 日历数据 |
| `KB_RAW_TEXT_DIR` | `<KB_DIR>/raw_text` | 原文快照 |
| `KB_LOGS_DIR` | `<KB_DIR>/logs` | 日志 / 备份 |

云端部署时可把 state / calendar / logs 分卷挂载,或在容器里用只读 vault + 可写 state 卷的布局。

### 4. 测试网补齐(+61 测试)

| 文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `test_accept_commands.py` | 10 | cmd_accept_ideas / cmd_accept_todos 端到端(含 weekly/monthly/someday/幂等/文件缺失) |
| `test_make_prompts.py` | 5 | `make-prompts --reconcile` 回填路径(无 LLM 依赖) |
| `test_format_helpers.py` | 10 | `_format_formal_idea` / `_format_weekly_task` / `_replace_status_in_block` / `_append_section` 纯函数 |
| `test_paths.py` | 4 | 环境变量覆盖 + 默认值向后兼容 |
| `test_rebuild_index.py` | 13 | rebuild-index 全路径(回填/修正/tags 同步/用户数据保护/dry-run/备份/孤儿/过滤参数) |
| `test_move_functions.py` | 11 | `move_accepted_idea` / `move_accepted_todo` 纯函数(幂等/not_found/no_file) |
| `test_web_accept_moves.py` | 8 | Web 端 TestClient 端到端(接受即搬运/reject 不搬/archived 不搬/幂等) |

合计从 100 → **161 passed**。覆盖了所有会改写用户正式清单的高风险操作。

---

## 修复 / 清理

### 文档同步(消除双源真理)

- **`AGENTS.md`**:Phase 2/3/4 从 pending 改为 done(实际早已实现);补登记 `llm-test / extract-suggestions / clean-x / serve` 4 个未登记命令;"MVP Commands" 拆为「无 LLM 也能跑」和「需要 LLM/Web 依赖」两组
- **`kb.py` 顶部 docstring**:从"Phase 0+1 占位"改为完整命令列表,移除「make-prompts / accept-* 未实现」的过时表述
- **`99_System/prompt_library.md`**:第 2 节"Summary 生成(Phase 2,待实现)"改为实际状态(已实现,指向 `kb_llm.SUMMARY_SYSTEM_PROMPT`)
- **删除内嵌 `AGENTS_MD` 常量**(`kb.py:655-697`):与仓库根 `AGENTS.md` 是双源真理,极易漂移。`cmd_init` 改为检测缺失时只提示,不再生成可能不同步的副本

### 死代码 / 残留清理

- 删除 `kb.py` 的 `cmd_not_implemented` 函数(1293-1296 行,无任何调用方)
- 删除残留空目录:`scripts/04_Plans/`、`scripts/.kb/logs/web_backups/`、`scripts/.kb/logs/`、`scripts/.kb/`(均为脚本误创建在 scripts/ 下的运行时残留,正规数据在 vault 根的 `.kb/`)

### Web 前端

- `app.js` 的 `updateStatus` toast 文案根据返回的 `moved / moved_to / area / plan / move_reason / move_error` 给出差异化反馈
- `style.css` 补 `.toast--info` 类(此前只有 success / error / warning,info 用默认样式没颜色)
- `base.html` cache buster 递增:`style.css?v=24→25`、`app.js?v=27→28`

### 测试基础设施

- `conftest.py` 的 `isolate_vault` fixture 扩展:同时 patch `kb_web.VAULT_ROOT`(若 kb_web 已被 import),让 Web 路由测试也能用同一 fixture

---

## 不变

- review 队列文件格式、suggestion 块解析、status 白名单不变
- 正式 idea/todo 清单文件格式不变
- CLI `accept-ideas` / `accept-todos` 行为完全不变(只是内部重构为调 `move_accepted_*` 纯函数)
- `cmd_init` 仍创建同样的目录结构 / 模板 / state.json(只是不再生成 AGENTS.md 副本)
- 投稿、summary 生成、日历、收藏、搜索等流程完全不动
- vault 内容(00_Inbox / 01_Sources / 02_Summaries / 03_Ideas / 04_Plans / state.json / calendar.json)零改动

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/kb.py` | docstring 重写;6 个路径常量环境变量覆盖;删 `AGENTS_MD` 常量 + `cmd_not_implemented`;加 `_parse_frontmatter_tags` / `_scan_summary_frontmatter` / `_rebuild_state_index` / `cmd_rebuild_index`;加 `_list_accepted_suggestion_ids` / `_rewrite_suggestion_file` / `move_accepted_idea` / `move_accepted_todo`;`cmd_accept_ideas` / `cmd_accept_todos` 重构为调 move 函数;`build_parser` 注册 `rebuild-index` 子命令 |
| `scripts/kb_web.py` | `api_idea_status` / `api_todo_status` 改为接受即搬运 + 幂等预检;加 `_check_suggestion_current_status` helper |
| `scripts/conftest.py` | `isolate_vault` fixture 同步 patch `kb_web.VAULT_ROOT` |
| `scripts/web/static/app.js` | `updateStatus` toast 差异化反馈 |
| `scripts/web/static/style.css` | 加 `.toast--info` |
| `scripts/web/templates/base.html` | cache buster 递增 |
| `AGENTS.md` | phase 状态同步 + 命令登记 |
| `.env.example` | 补 6 个路径环境变量注释 |
| `99_System/prompt_library.md` | 第 2 节 Summary 状态同步(vault 内容,不入库) |
| `scripts/tests/` | 新增 7 个测试文件;`test_reject_delete.py` 一处断言适配新搬运行为 |

---

## 测试

- 全量 **161 个测试通过**,零回归
- 真实 vault `kb.py rebuild-index --dry-run`:41 summary,0 异常
- 真实 vault `kb.py status`:输出与重构前一致(41 sources / 41 summaries / 2 idea + 1 todo pending review)

---

## 破坏性变更

**无**。所有命令行为、文件格式、API 响应 schema 都向后兼容。

唯一行为微调:Web 端点 `POST /api/idea|todo/{id}/status` 在 `accepted_*` 状态下,响应 body 多了 `moved / moved_to / area|plan` 字段;原 `ok / id / new_status / deleted` 字段保留不变。前端 `app.js` 已同步适配。

---

## 不在本次范围(留给后续)

- `kb_web.py` 2117 行按域拆 8 个 APIRouter(已写好 PRD,见 `docs/v0.4.4/`)
- `kb.py` 抽公共工具(合并 filename helpers、`hash_from_source_id`、inbox 头剥离统一、跨模块私有访问封装)
- TypedDict / dataclass 改造 state schema
- 静态模板字符串外迁到 `scripts/templates/`
- CSS 令牌贯彻(62 种散值)、`alert()` 全替换
