# v0.4.5 PRD:P0 真 bug + P2 数据一致性

> 日期:2026-07-20
> 上一版:v0.4.4(见 `docs/v0.4.4/`)
> 性质:bug 修复 + 数据安全加固,无新功能

## 0. 文档定位

本 PRD 对应 v0.4.5 的两批修复:**P0 真 bug**(第二轮深度审查实际运行复核确认的 6 个 bug)+ **P2 数据一致性**(并发/原子性/损坏检测 4 项)。这些是审查报告里影响数据安全和正确性的最高优先级问题。

P1 安全加固和 P3 测试网补齐留到 v0.4.6。

## 1. P0 真 bug(6 个,全部经实跑复核)

### 1.1 kb_date `下月底` 日期识别错
- 影响:截止日差 27 天,日历功能核心路径
- 根因:正则遮蔽 + 算式错(详见 changelog)
- 修复:正则改 `下(?:月|个月)底`;算式用"下下月 1 号 - 1 天"

### 1.2 kb_date `本周末` 周末推到下周
- 影响:周末 deadline 偏一周
- 修复:weekday >= 5(周六/周日)返回今天

### 1.3 kb_llm `_html_to_text` 重复输出
- 影响:div 包裹正文喂给 LLM 两遍,污染 summary 质量、翻倍 token
- 修复:keep/非 keep 标签的暂存逻辑分离

### 1.4 kb_llm `_extract_json_list` 死代码
- 影响:LLM 返回垃圾时静默返回空,漏抽率被低估
- 修复:失败返回 None,调用方 `if items is None` 走通

### 1.5 ingest-image 覆盖 inbox
- 影响:违反 AGENTS.md Hard Rule,丢失用户投稿
- 修复:改用 `kb.append_to_inbox`

### 1.6 备份命名同日覆盖
- 影响:误删后无法恢复到当天早些时候
- 修复:抽 `backup_file` helper,带时分秒

## 2. P2 数据一致性(4 项)

### 2.1 原子写
- 动机:state/calendar/suggestion 文件并发读写时可能读到截断内容
- 方案:`write_text` 用 tempfile + os.replace
- 不引入新依赖

### 2.2 跨平台文件锁
- 动机:Web 端与 CLI 并发操作 state/calendar 时后写覆盖先写
- 方案:`_file_lock` context manager,Unix 用 fcntl,Windows 用 msvcrt
- 零外部依赖(标准库)

### 2.3 load_state 损坏检测
- 动机:state.json 损坏时静默返回空骨架,rebuild-index 误报"已是最新"
- 方案:备份损坏文件 + 记 WARNING 日志 + 返回 `_corrupt: True` 标记
- rebuild-index 检测到 `_corrupt` 时返回 2,要求人工确认

### 2.4 Web accept 事务化
- 动机:TOCTOU 竞态导致重复搬运;搬运失败状态卡死
- 方案:`accept_and_move` 高层函数用锁包住 check+update+move,失败时回滚 status

## 3. 范围外(整体)

- P1 安全(XSS/SSRF/Auth/时区)— v0.4.6
- P3 测试网补齐 — v0.4.6
- rebuild-index 的 `--recover-from-corrupt` 完整灾难恢复 — v0.4.7+
- 9 个 router 重复 import 去重 — 代码异味,留后续
- tags 解析双份统一 — 同上

## 4. 验收标准

- [x] 6 个真 bug 全部实跑验证修复(见 changelog 表格)
- [x] 全量 224 passed,零回归
- [x] 原子写失败时原文件不被污染(test_atomic_write_failure_no_corrupt)
- [x] 并发 accept 只搬一次(test_concurrent_accept_no_duplicate)
- [x] 损坏 state 不被静默吞错(test_load_state_corrupt_*)
- [x] 无破坏性变更
