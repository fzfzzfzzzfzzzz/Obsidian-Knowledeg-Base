# v0.4.3 任务清单

> 日期:2026-07-19
> PRD 见 `v043_refactor_PRD.md`,changelog 见 `changelog.md`

## 0. 文档范围

四个主线:① 文档与死代码清理 ② 核心命令单测 ③ 路径配置派生量化 ④ rebuild-index 命令 ⑤ Web accept 接受即搬运。

## P0(必须)— 全部完成

### 文档与死代码清理
- [x] `kb.py` 顶部 docstring 重写(去「占位」表述)
- [x] `AGENTS.md` phase 状态同步 + 命令登记
- [x] 删除 `kb.py` 内嵌 `AGENTS_MD` 常量(双源真理)
- [x] `cmd_init` 改为只检测 AGENTS.md,不生成副本
- [x] 删除 `cmd_not_implemented` 死代码
- [x] 删除残留空目录(`scripts/04_Plans/`、`scripts/.kb/`)
- [x] `99_System/prompt_library.md` 第 2 节状态同步

### 核心命令单测(test_accept_commands / test_make_prompts / test_format_helpers)
- [x] `test_accept_ideas_moves_accepted_block`
- [x] `test_accept_ideas_skips_non_accepted`
- [x] `test_accept_ideas_no_file_returns_1`
- [x] `test_accept_ideas_productivity_area`
- [x] `test_accept_todos_weekly` / `_monthly` / `_someday`
- [x] `test_accept_todos_marks_original_as_moved`
- [x] `test_accept_todos_no_file_returns_1`
- [x] `test_accept_todos_idempotent_on_second_run`
- [x] `test_make_prompts_reconcile_backfills_summary_path`
- [x] `test_make_prompts_reconcile_skips_already_filled`
- [x] `test_make_prompts_reconcile_sets_action_status`
- [x] `test_make_prompts_reconcile_no_summaries_dir`
- [x] `test_make_prompts_reconcile_ignores_unknown_source_id`
- [x] `test_format_formal_idea_*`(3 个:required_fields / id_format / fallbacks)
- [x] `test_format_weekly_task_*`(2 个:uses_metadata / handles_missing)
- [x] `test_replace_status_in_block_*`(3 个:basic / only_matches_status_line / no_match)
- [x] `test_append_section_*`(2 个:creates_parent / appends_not_overwrites)

### 路径配置派生量化
- [x] `kb.py` 6 个常量全部支持环境变量覆盖
- [x] `conftest.py` `isolate_vault` 同步 patch `kb_web.VAULT_ROOT`
- [x] `.env.example` 补 6 个路径环境变量注释
- [x] `test_paths.py`:defaults / overrides_vault_root / overrides_individual / kb_web_follows_kb

### rebuild-index 命令
- [x] `_parse_frontmatter_tags` helper
- [x] `_scan_summary_frontmatter` 扫盘函数
- [x] `_rebuild_state_index` 核心重建逻辑(纯函数)
- [x] `cmd_rebuild_index` CLI 入口
- [x] `build_parser` 注册 `rebuild-index` 子命令(含 --dry-run / --tags-only / --summary-path-only / -v)
- [x] 写前 `shutil.copy2` 备份
- [x] 孤儿报告(state 里有 summary_path 但文件不存在)
- [x] `test_rebuild_index.py`(13 用例:backfill / correct / sync_tags / override_tags / preserve_user_tags / preserve_reading_state / dry_run / backup / orphan / tags_only / summary_path_only / no_summaries_dir / no_changes)

### Web accept 接受即搬运
- [x] 抽 `_list_accepted_suggestion_ids` / `_rewrite_suggestion_file` helper
- [x] 抽 `move_accepted_idea` / `move_accepted_todo` 纯函数
- [x] `cmd_accept_ideas` / `cmd_accept_todos` 重构为调 move 函数(CLI 行为不变)
- [x] `kb_web._check_suggestion_current_status` 幂等预检
- [x] `api_idea_status` / `api_todo_status` 改为接受即搬运
- [x] 前端 `app.js` `updateStatus` toast 差异化反馈
- [x] `style.css` 补 `.toast--info`
- [x] `base.html` cache buster 递增
- [x] `test_move_functions.py`(11 用例:single_accepted / already_moved / pending / not_found / no_file / productivity / weekly / monthly / someday / double_call)
- [x] `test_web_accept_moves.py`(8 用例:moves_to_research / weekly / monthly / someday / reject_not_move / archived_not_move / pending_not_move / double_accept_noop)
- [x] 适配 `test_reject_delete.py:test_accept_todo_not_deleted`(原断言基于旧搬运行为)

## P1(应该)— 完成

- [x] 真实 vault `rebuild-index --dry-run` 验证(41 summary,0 异常)
- [x] 真实 vault `status` 烟测(输出不变)
- [x] 全量测试 161 passed,零回归

## P2(可选)— 未做

- [ ] TypedDict / dataclass 改造 state schema(改面大,留后续)
- [ ] 静态模板字符串外迁到 `scripts/templates/`(同上)
- [ ] CSS 令牌贯彻(62 种散值)
- [ ] `alert()` 全替换(`calendar.html` / `submit.html` 仍有残留)

## 不在范围(留 v0.4.4)

- `kb_web.py` 2117 行按域拆 8 个 APIRouter
- `kb.py` 抽 `hash_from_source_id` / 合并 filename helpers / inbox 头剥离统一
- 跨模块私有访问封装(`kb.py:1710/1719` 访问 `kb_llm._summary_outline`)
