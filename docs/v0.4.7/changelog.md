# Changelog v0.4.7

> 日期:2026-07-21
> 主题:**shutdown host 白名单 + extract-suggestions 质量/可观测性修复**

本版收尾 v0.4.6 后工作区遗留的 WIP(网页内关闭服务按钮 + 文章详情 TOC 侧栏),
并修掉 ROADMAP 里两个 extract-suggestions 链路的真 bug。300 passed(289 → 300,+11)。

---

## 新增

### 1. `/api/shutdown` + 网页内关闭按钮
**背景**:本地用户双击 `start_kb.vbs` 起服务后,要关服得找终端窗口按 Ctrl+C,体验差。

**实现**:
- `web/routers/dashboard.py` 新增 `POST /api/shutdown`,延迟 0.5s `os._exit(0)`(让响应先发回客户端)
- `templates/base.html` 导航栏加 ⏻ 按钮,点击 confirm 后 fire-and-forget 调端点,800ms 后把页面替换成「已关闭」提示
- 独立内联 IIFE 脚本,与 `app.js` 业务逻辑解耦

**安全(host 白名单)**:
- docstring 原本声称「仅本地使用」,但代码无校验 —— 配了 Basic Auth 的云端部署也能被任何人远程杀进程
- 新增 `_shutdown_allowed(bind_host, client_host)` 纯函数:**仅当服务绑定到 loopback 且请求来自 loopback 时**才允许
- `cmd_serve` 在 `uvicorn.run()` 前把 `args.host` 存到 `kb_web.app.state.bind_host`,供请求层读取
- 双校验防两类场景:bind 非 loopback(防反向代理/隧道打到 127.0.0.1)、client 非 loopback(防御性)
- 非 loopback 一律 403 `shutdown_not_allowed`,提示用进程管理器关闭

**测试**:`test_web_shutdown.py` 8 用例(注册/调度退出/真 Timer/auth 401/auth 200/纯函数 4 组合/bind 非 loopback 403/默认 loopback 放行)。

### 2. 文章详情 TOC 侧栏(已知限制)
- `templates/summary.html` 新增 `buildToc()`,扫 `.markdown-body` 里的 h2/h3,右侧 aside 渲染可折叠目录
- `static/style.css` 加 `.summary-layout` / `.summary-toc` / `.toc-*` 样式

**已知限制(本轮不修)**:后端 `sanitize_html` 会剥掉所有 heading 的 id 属性(`ALLOWED_HTML_ATTRS` 不含 heading 的 id),
前端只好用 `sec-1/2/3` DOM 索引生成锚点。同一次渲染内锚点一致可用,但跨渲染不稳定。留作下版改进。

### 3. `start_kb.vbs` 桌面启动器
- Windows 双击启动:找注册表 Python → `python scripts\kb.py serve` → 等 `http://127.0.0.1:5173` 就绪 → 默认浏览器打开
- 未跟踪文件,纳入版本管理便于用户重装

---

## 顺手修复的 bug(ROADMAP P1-#6 / #7)

### #6. extract-suggestions 的 `estimated_time` 不再伪造
**问题**:`extract_todos_from_summary` 和 `_format_todo_suggestion` 都有硬兜底,
LLM 没返回 `estimated_time` 时强制填 `"2-4h"`,伪造数据污染 review 队列,用户无法区分「LLM 真估了 2-4h」和「字段缺失被填了默认值」。

**修复**:
- `kb_llm.py:1346` `str(it.get("estimated_time", "")).strip() or "2-4h"` → 去掉 `or "2-4h"`(对照 idea 侧 `estimated_investment` 的正确写法)
- `kb.py:2285` `_format_todo_suggestion` 的 `it.get('estimated_time', '2-4h')` → 默认值改 `''`

**下游已验证安全**:`_format_weekly_task` 用 `meta.get('estimated_time', '')`,空值被容忍;
`test_format_weekly_task_handles_missing_meta` 和 accept 流程的 `_TODO_SOMEDAY`(本就无 estimated_time)证明空值不破解析。
模板文件里的 `2-4h` 是示例值,保持不动。

**测试**:`test_extract_todos_no_estimated_time_stays_empty`(monkeypatch chat)+ `test_format_todo_suggestion_empty_estimated_time` + `test_todo_suggestion_preserves_provided_estimated_time`(对照,确认没误伤合法值)。

### #7. extract-suggestions CLI 失败留痕(最小版)
**问题**:`cmd_extract_suggestions` 的 `except LLMError` 只 `print`,关掉终端就不可见,失败无声丢失。
(`_extract_json_list` 本身在 v0.4.5 已修:正确返回 `None`,调用方 raise `LLMError`。剩余 gap 只是 CLI 的可观测性。)

**修复**:用既有 `append_log` 约定,零新字段:
- except 分支加 `append_log(f"extract-suggestions FAILED source={sid}: {e}")`
- 新增 `failed` 计数器,函数末尾的汇总行加 `failed={failed}`

**不引入 `extract_error` state 字段**(`action_status` 保持 `undecided`,下次自动重试 —— 失败的是单次 LLM 调用,不是该 source 永久不可抽)。
Web 单篇/批量抽取路径的 state 标记留作后续。

**测试**:靠手动跑 + 查 `.kb/logs/kb.log` 验证,行为已由 `test_generate_ideas_llm_failure` 覆盖 LLMError 路径。

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/web/routers/dashboard.py` | `/api/shutdown` + `_schedule_exit` + `_shutdown_allowed` + `_LOOPBACK_HOSTS` |
| `scripts/kb.py` | `cmd_serve` 存 `app.state.bind_host`;`_format_todo_suggestion` 去掉 estimated_time 兜底;`cmd_extract_suggestions` 加 append_log + failed 计数器 |
| `scripts/kb_llm.py` | `extract_todos_from_summary` 去掉 `or "2-4h"` |
| `scripts/web/templates/base.html` | 导航栏 ⏻ 按钮 + 关闭脚本;cache buster v26→v29 |
| `scripts/web/templates/summary.html` | TOC 侧栏 + `buildToc()` |
| `scripts/web/static/style.css` | shutdown 按钮 + TOC + summary layout 样式 |
| `scripts/tests/test_web_shutdown.py` | 新增,8 用例(shutdown 端点 + host 白名单) |
| `scripts/tests/test_web_routers.py` | EXPECTED_PATHS 加 `/api/shutdown` |
| `scripts/tests/test_kb_llm_bugs.py` | +1 用例(estimated_time 留空) |
| `scripts/tests/test_format_helpers.py` | +2 用例(_format_todo_suggestion 空值/合法值) |
| `start_kb.vbs` | 新增,Windows 桌面启动器 |
| `PRODUCT.md` | 版本号 v0.4.1 → v0.4.7(顺带修陈旧值) |
| `docs/ROADMAP.md` | 版本 banner + 列表;P1-#6 标完成、#7 标部分完成 |
| `docs/v0.4.7/changelog.md` | 本文件 |

---

## 不变

- API schema 不变(`/api/shutdown` 是新端点,错误响应加了 `error`/`message` 字段)
- CLI 行为不变(extract-suggestions 失败时 `action_status` 仍保持 `undecided`,只是多了日志)
- 文件格式不变
- 默认配置不变(本地 `kb.py serve` host=127.0.0.1,白名单天然放行)

---

## 破坏性变更

**无**。本地默认部署所有新功能开箱可用;云端/host 非 loopback 部署下 `/api/shutdown` 返回 403(原本是 200,但那个 200 是安全漏洞,403 才是正确行为)。

---

## 不在本次范围

- **TOC 锚点稳定性**:后端 `sanitize_html` 放开 heading 的 id 白名单(要同步改 `test_summary_sanitize.py` 一个断言),留作下版
- **ROADMAP P1-#5**:idea/todo prompt 的量化判定标准(P0/P1/P2/P3/novelty 的门槛定义),单独开版
- **Bug #7 的 `extract_error` state 字段**:在 source state 里标记抽取错误 + 前端显示,留作后续
- **Web 单篇/批量抽取路径的 state 标记**:`web/routers/ingest.py` 批量抽取失败目前只进内存 `failed_items`,不持久化
