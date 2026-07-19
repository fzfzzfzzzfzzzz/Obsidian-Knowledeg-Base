# Changelog v0.4.5

> 日期:2026-07-20
> 主题:**P0 真 bug 修复 + P2 数据一致性**(第二轮代码审查发现的 10 个高危问题)
> 本版基于第二轮深度审查(覆盖 kb_llm / kb_date / 前端 / 安全),修复其中最严重的 10 个

第二轮审查(2026-07-19)发现的 30 个问题中,本版处理 P0(真 bug)+ P2(数据一致性)共 10 个。所有修复均经实际运行复核。

---

## 新增(P0 真 bug 修复)

### 1. kb_date `下月底` / `下个月底` 日期识别错(差 27 天)
**根因(双重)**:
- 正则遮蔽:`RE_RELATIVE["下个月"]` 的 `下个?月` 让 `个` 可选,导致 `下月底` 被它抢先匹配到前两字 `下月`,真正的 `下月底` 规则被位置去重丢弃
- 算式错:`_resolve_relative("下月底", ...)` 的 `+ timedelta(days=32) - timedelta(days=1)` 在大月和 2 月全错

**修复**:
- 正则改 `下(?:月|个月)底`,同时识别 `下月底` 和 `下个月底`
- `_resolve_relative` 判断顺序调整:`下月初/下月底` 先于 `下月/下个月`
- 算式改成 `下下月 1 号 - 1 天`(与 `本月底` 同款),正确处理闰年、跨年、大月
- 实跑验证:7 月说"下月底" → 2026-08-31(此前 2026-08-01);2 月说"下月底" → 2026-02-28/29

### 2. kb_date `本周末` 周六/周日推到下周
**根因**:`days_ahead = 5 - weekday()`,周六得 0,`if days_ahead <= 0` 触发 `+= 7`。
**修复**:周六/周日(weekday >= 5)返回今天,工作日推到本周六。语义:周末说"本周末" = 今天。

### 3. kb_llm `_html_to_text` 重复输出正文
**根因**:非 keep 标签(div/span)的文本被同时写进 `_buf` 和直接 `parts.append`,收尾时 `_buf` 残留又 append 第二次。
**修复**:`_in_keep > 0` 时只写 `_buf`(等 endtag flush);`_in_keep == 0` 时只写 `parts`,不暂存 `_buf`。
**影响**:此前所有 div 包裹的正文在 summary 里重复一遍,污染质量、翻倍 token 消耗。**这很可能就是 commit 4057b89 "summary 质量优化"反复折腾抓取层的根因**。

### 4. kb_llm `_extract_json_list` 死代码(失败静默吞错)
**根因**:类型注解 `-> list[dict]`,失败时 `return []`;调用方写 `if items is None: raise LLMError(...)` 永远走不到。
**修复**:失败改 `return None`,类型改 `list | None`。调用方 `if items is None:` 现在能走通。合法空数组 `[]`(LLM 真没抽到)仍正常处理,不抛错。
**影响**:此前 LLM 返回垃圾时静默返回空列表,用户看到"未发现候选"但实际是抽取崩溃。

### 5. `/api/ingest-image` 覆盖 inbox.md(违反 Hard Rule)
**根因**:`inbox_path.write_text(header + ocr_text)` 是覆盖写,而同文件文本投稿路径明确用 `append_to_inbox`。
**修复**:改用 `kb.append_to_inbox([ocr_text])`,与文本投稿路径一致。
**影响**:此前用户先投稿未处理,下一次图片投稿会清空 inbox 全部内容。直接违反 AGENTS.md "Do not silently overwrite user-authored notes"。

---

## 新增(P2 数据一致性)

### 6. 备份命名带时分秒
**根因**:`state_{date.today().isoformat()}.json.bak` 只到日,同日多次写覆盖。
**修复**:抽 `web/utils.py:backup_file(stem)` helper,命名 `state_YYYYMMDD_HHMMSS.bak`。替换 6 处旧备份代码(state_io × 2 / articles / ingest / status / kb.py rebuild)。

### 7. `write_text` 原子化
**根因**:`path.write_text` 非原子,并发读可能读到截断内容(尤其 Windows)。
**修复**:写临时文件 `tmp_<pid>_<tid>` + `os.fsync` + `os.replace`(Windows/Unix 都原子)。失败时清理临时文件,不污染原文件。
**测试**:`test_atomic_write_failure_no_corrupt` 验证 `os.replace` 抛错时原文件保持不变。

### 8. 跨平台文件锁(零外部依赖)
**新增** `kb._file_lock(lock_path, timeout)` context manager:
- Unix:`fcntl.flock` (LOCK_EX | LOCK_NB)
- Windows:`msvcrt.locking` (LK_NBLCK)
- 超时抛 `TimeoutError`,不无限等待
- 同目录临时文件保证原子性

用于阶段 6 的事务化。

### 9. `load_state` / `load_calendar` 损坏检测
**根因**:此前 `JSONDecodeError` 被静默吞,返回空骨架。`rebuild-index` 跑下来输出"无需更新,state 已是最新"——极具误导性。
**修复**:
- 备份损坏文件到 `.kb/logs/corrupt_state_<ts>.json`
- 记 `WARNING` 到 `kb.log`
- 返回骨架加 `_corrupt: True` 标记
- `cmd_rebuild_index` 检测 `_corrupt` 后明确报告并返回 2(需人工确认),不静默继续

### 10. Web accept 事务化(文件锁 + 失败回滚)
**根因(双重)**:
- TOCTOU 竞态:`_check_suggestion_current_status` 检查与 `move_accepted_idea` 之间无锁,并发请求可能都通过检查然后都搬运
- 失败不回滚:`_update_suggestion_status` 先改 status,move 抛错后状态卡在 `accepted_*` 但正式清单没条目

**修复**:抽 `web/services/status.py:accept_and_move()` 高层函数:
- 全程持 `_file_lock`(锁路径基于 suggestion 文件名)
- 搬运失败时调 `_rewrite_suggestion_file` 回滚 status 到原值
- 返回 `rolled_back_to: <原 status>` 告知前端

**测试**:`test_concurrent_accept_no_duplicate` 用 threading 实测,两个并发 accept 只搬一次,正式清单无重复条目。

---

## 测试

- 全量 **224 passed**(v0.4.4 是 172,+52)
- 新增 6 个测试文件:test_date 扩展、test_kb_llm_bugs、test_ingest_image、test_backup_naming、test_atomic_and_lock、test_corrupt_state、test_accept_transactional
- 零回归

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/kb_date.py` | `下月底`/`下个月底` 正则+算式修复;`本周末` 周末返回今天 |
| `scripts/kb_llm.py` | `_html_to_text` 去重;`_extract_json_list` 失败返回 None;`_summary_outline` 改名 `summary_outline`(v0.4.4) |
| `scripts/kb.py` | `write_text` 原子化;`_file_lock` 跨平台锁;`load_state`/`load_calendar` 损坏检测;rebuild-index 损坏报告 |
| `scripts/web/routers/ingest.py` | ingest-image 改用 `append_to_inbox`;备份 helper 替换 |
| `scripts/web/routers/{articles,ideas,todos}.py` | 备份 helper 替换;accept 路由改调 `accept_and_move` |
| `scripts/web/services/status.py` | 新增 `accept_and_move` 事务化封装 |
| `scripts/web/services/state_io.py` | 备份 helper 替换 |
| `scripts/web/utils.py` | 新增 `backup_file()` helper |
| `scripts/tests/` | +6 测试文件,+52 用例 |

---

## 不变

- API 响应 schema 不变(只在搬运失败响应加 `move_error`/`rolled_back_to` 等新字段,旧字段保留)
- CLI 命令行为不变
- 文件格式不变
- 前端 UI 不变

---

## 破坏性变更

**无**(对外行为完全兼容)。

---

## 不在本次范围(留 v0.4.6)

第二轮审查发现的剩余问题,P1 安全 + P3 测试网:
- XSS 消毒(summary HTML / todo onclick / favorites onclick)
- SSRF 过滤(投稿 URL 内网地址)
- serve 0.0.0.0 警告 + 可选 Basic Auth
- 时区(date.today 改为可配置)
- 图片上传前后端校验一致
- kb_llm 核心单测、cmd_* 补测、端到端链路测试
- 代码异味(9 个 router 重复 import、tags 解析双份等)
