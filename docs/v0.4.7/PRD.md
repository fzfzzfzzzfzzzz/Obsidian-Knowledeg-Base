# v0.4.7 PRD:shutdown host 白名单 + extract-suggestions 质量/可观测性修复

> 日期:2026-07-21
> 上一版:v0.4.6(见 `docs/v0.4.6/`)
> 性质:收尾 v0.4.6 后 WIP(网页内关闭服务)+ 修 ROADMAP 两个 extract-suggestions 真 bug

## 0. 文档定位

本 PRD 对应 v0.4.7 的两类工作:
1. **网页内关闭服务按钮的 host 白名单加固**(v0.4.6 WIP 收尾)
2. **extract-suggestions 链路两个真 bug**(ROADMAP P1-#6 / #7)

另含文章详情 TOC 侧栏(WIP,带已知限制)和 Windows 桌面启动器。300 passed(289 → 300,+11)。

## 1. `/api/shutdown` + host 白名单(安全收尾)

### 1.1 背景
v0.4.6 WIP 加了「网页内关闭服务」按钮,但 docstring 声称「仅本地使用」却**无任何校验** ——
配了 Basic Auth 的云端部署下,任何能登录的人都能远程杀掉服务进程。

### 1.2 实现
- `POST /api/shutdown`:延迟 0.5s `os._exit(0)`(让响应先发回客户端)
- `_shutdown_allowed(bind_host, client_host)` 纯函数:**仅当服务绑定到 loopback 且请求来自 loopback** 才允许
- `cmd_serve` 在 `uvicorn.run()` 前把 `args.host` 存到 `kb_web.app.state.bind_host`,供请求层读取
- 双校验防两类场景:
  - bind 非 loopback(防反向代理/隧道打到 127.0.0.1)
  - client 非 loopback(防御性)
- 非 loopback 一律 403 `shutdown_not_allowed`,提示用进程管理器关闭

### 1.3 前端
- `base.html` 导航栏 ⏻ 按钮,confirm 后 fire-and-forget 调端点
- 800ms 后把页面替换成「🔌 知识库服务已关闭」提示
- 独立内联 IIFE 脚本,与 `app.js` 业务逻辑解耦(不碰 57KB 的 app.js)

## 2. extract-suggestions bug 修复(ROADMAP P1)

### 2.1 #6 `estimated_time` 伪造(已修)
- **问题**:`extract_todos_from_summary` 和 `_format_todo_suggestion` 都有硬兜底,
  LLM 没返回 `estimated_time` 时强制填 `"2-4h"`,伪造数据污染 review 队列,
  用户无法区分「LLM 真估了 2-4h」和「字段缺失被填默认值」。
- **修复**:去掉 `or "2-4h"`(对照 idea 侧 `estimated_investment` 正确写法),默认值改空串。
- **下游已验证安全**:`_format_weekly_task` 容忍空值;accept 流程的 `_TODO_SOMEDAY`(本就无 estimated_time)不破。

### 2.2 #7 CLI 失败留痕(最小版,已修)
- **问题**:`cmd_extract_suggestions` 的 `except LLMError` 只 `print`,关掉终端就不可见,失败无声丢失。
- **修复**:用既有 `append_log` 约定(零新字段):
  - except 分支加 `append_log(f"extract-suggestions FAILED source={sid}: {e}")`
  - 新增 `failed` 计数器,汇总行加 `failed={failed}`
- **不引入 `extract_error` state 字段**:`action_status` 保持 `undecided`,下次自动重试
  (失败的是单次 LLM 调用,不是该 source 永久不可抽)。

## 3. 文章详情 TOC 侧栏(已知限制)

- `summary.html` 新增 `buildToc()`:扫 `.markdown-body` 里的 h2/h3,右侧 aside 渲染可折叠目录
- `style.css` 加 `.summary-layout` / `.summary-toc` / `.toc-*` 样式
- **已知限制**:后端 `sanitize_html` 会剥掉所有 heading 的 id(`ALLOWED_HTML_ATTRS` 不含 heading id),
  前端用 `sec-1/2/3` DOM 索引生成锚点。同次渲染内一致可用,跨渲染不稳定。留作下版。

## 4. `start_kb.vbs` Windows 桌面启动器

- 双击启动:找 Python → `python scripts\kb.py serve`(完全隐藏窗口,无黑窗)→ 等健康检查 → 默认浏览器打开
- 端口探测防重复(已跑就直接开浏览器)
- 项目根 = 脚本所在目录,换机器/移动目录不失效
- 技术要点(实测验证):`cmd /c` 包一层提供有效 stdio 句柄;GBK + CRLF 编码;VBS Err 对象每步 Clear

## 5. 范围外(留作后续)

- TOC 锚点稳定性:后端放开 heading 的 id 白名单(需同步改 `test_summary_sanitize.py`)
- ROADMAP P1-#5:idea/todo prompt 的量化判定标准
- Bug #7 的 `extract_error` state 字段:source state 里标记抽取错误 + 前端显示
- Web 单篇/批量抽取路径的 state 标记

## 6. 验收标准

- [x] 300 passed(v0.4.6 是 289,+11)
- [x] `/api/shutdown` 本地默认放行;host 非 loopback 返回 403
- [x] Basic Auth 场景:无凭证 401、正确凭证 200
- [x] `estimated_time` LLM 不返回时留空,不再伪造 "2-4h"
- [x] extract-suggestions LLM 失败进 `.kb/logs/kb.log`
- [x] 桌面启动器:无黑窗启动 + 防重复 + 浏览器自动打开
- [x] 无破坏性变更(默认配置完全兼容;云端 403 是修正漏洞,不是回归)
