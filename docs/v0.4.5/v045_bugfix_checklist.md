# v0.4.5 任务清单

> 日期:2026-07-20
> PRD 见 `v045_bugfix_PRD.md`,changelog 见 `changelog.md`

## P0 真 bug — 全部完成

### kb_date
- [x] `下月底` 正则改 `下(?:月|个月)底`
- [x] `下个月` 正则强制 `个`(不再吞掉 `下月底`)
- [x] `下月` 单用负向前瞻排除 `下月底/下月初/下个月`
- [x] `_resolve_relative` 判断顺序:初/底 先于 月/个月
- [x] `下月底` 算式改"下下月 1 号 - 1 天"
- [x] `本周末` weekday >= 5 返回今天
- [x] test_date.py +12 用例(下月底/本周末/闰年/跨年/大月/回归)

### kb_llm
- [x] `_html_to_text.handle_data` keep/非 keep 暂存分离
- [x] `_extract_json_list` 失败返回 None,类型改 `list | None`
- [x] test_kb_llm_bugs.py 13 用例(HTML 不重复 / JSON 解析各场景)

### ingest-image
- [x] `/api/ingest-image` 改用 `kb.append_to_inbox`
- [x] test_ingest_image.py 2 用例(不覆盖 / 拒非法类型)

## P2 数据一致性 — 全部完成

### 备份命名
- [x] 抽 `web/utils.py:backup_file(stem)` helper
- [x] 替换 6 处旧备份代码(state_io × 2 / articles / ingest / status / kb.py rebuild)
- [x] test_backup_naming.py 4 用例

### 原子写
- [x] `kb.write_text` 用 tempfile + os.fsync + os.replace
- [x] 失败清理临时文件
- [x] test_atomic_and_lock.py 原子写部分 5 用例

### 文件锁
- [x] `kb._file_lock` context manager(Unix fcntl / Windows msvcrt)
- [x] 超时抛 TimeoutError
- [x] test_atomic_and_lock.py 锁部分 4 用例(串行化/超时/异常释放/建目录)

### load_state 损坏检测
- [x] `load_state` 备份损坏文件 + 记 WARNING + 加 `_corrupt` 标记
- [x] `load_calendar` 同款
- [x] `cmd_rebuild_index` 检测 `_corrupt` 返回 2
- [x] test_corrupt_state.py 9 用例

### Web accept 事务化
- [x] `web/services/status.py:accept_and_move()` 高层函数
- [x] 全程持 `_file_lock`
- [x] 搬运失败回滚 status
- [x] 路由 ideas.py / todos.py 改调 `accept_and_move`
- [x] test_accept_transactional.py 3 用例(回滚 / idea 回滚 / 并发不重复)

## P1 安全 — 留 v0.4.6

- [ ] XSS 消毒(后端 + 前端 onclick → data-*)
- [ ] SSRF 过滤
- [ ] serve 0.0.0.0 警告 + 可选 Basic Auth
- [ ] 时区
- [ ] 图片上传前后端一致

## P3 测试网 — 留 v0.4.6

- [ ] kb_llm 核心单测(chat / fetch / parse_env)
- [ ] cmd_status / cmd_clean_x / cmd_extract_suggestions CLI 层测试
- [ ] 端到端链路测试
- [ ] 写端点业务测试

## 验收

- [x] 224 passed(v0.4.4 是 172,+52)
- [x] 真实 vault 烟测(待最终验证)
- [x] 无破坏性变更
