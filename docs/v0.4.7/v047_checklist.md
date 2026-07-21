# v0.4.7 任务清单

> 日期:2026-07-21
> PRD 见 `v047_PRD.md`,changelog 见 `changelog.md`

## /api/shutdown + host 白名单 — 全部完成

### 后端端点
- [x] `web/routers/dashboard.py` 新增 `_schedule_exit()`(延迟 0.5s `os._exit(0)`,独立函数便于测试 monkeypatch)
- [x] `POST /api/shutdown` 端点
- [x] `_shutdown_allowed(bind_host, client_host)` 纯函数 + `_LOOPBACK_HOSTS` 常量
- [x] `kb.py cmd_serve` 存 `kb_web.app.state.bind_host = args.host`
- [x] 非 loopback 一律 403 `shutdown_not_allowed`,带 `error`/`message` 字段

### 前端
- [x] `base.html` 导航栏 ⏻ 按钮(`nav-shutdown` / `kbShutdownBtn`)
- [x] 独立内联 IIFE 脚本(confirm → fire-and-forget fetch → 800ms 后替换页面)
- [x] `style.css` `.nav-shutdown` 样式(hover 变红)
- [x] cache buster 递增(style.css v26→v29)

### 测试
- [x] `test_web_shutdown.py` 8 用例(注册/调度退出/真 Timer/auth 401/auth 200/纯函数 4 组合/bind 非 loopback 403/默认 loopback 放行)
- [x] `test_web_routers.py` EXPECTED_PATHS 加 `/api/shutdown`(回归护栏)

## extract-suggestions bug 修复 — 全部完成

### #6 estimated_time 不再伪造
- [x] `kb_llm.py:1346` 去掉 `or "2-4h"`
- [x] `kb.py:2285` `_format_todo_suggestion` 默认值 `''`
- [x] `test_kb_llm_bugs.py` +1 用例(extract_todos_no_estimated_time_stays_empty)
- [x] `test_format_helpers.py` +2 用例(空值/合法值对照)

### #7 CLI 失败留痕
- [x] `kb.py cmd_extract_suggestions` except 分支加 `append_log`
- [x] 新增 `failed` 计数器,汇总行加 `failed={failed}`

## 文章详情 TOC 侧栏 — 完成(带已知限制)

- [x] `summary.html` `buildToc()`(扫 h2/h3 渲染右侧目录)
- [x] `style.css` `.summary-layout` / `.summary-toc` / `.toc-*` 样式
- [~] 锚点稳定性:用 DOM 索引 `sec-N`(后端 sanitize_html 剥 id,已知限制,留作下版)

## start_kb.vbs 桌面启动器 — 完成

- [x] VBS 脚本:推导项目根 + python 路径 + 端口探测防重复
- [x] `cmd /c` 隐藏窗口启动(SW_HIDE)
- [x] 健康检查轮询(最多 30s)
- [x] `IsServerUp()` 用 GET(非 HEAD,避免 405)+ 每步 `Err.Clear`
- [x] GBK + CRLF 编码(VBS 中文 Windows 兼容)
- [x] 桌面快捷方式(知识库.lnk → start_kb.vbs)

## 文档 — 完成

- [x] docs/v0.4.7/changelog.md
- [x] docs/ROADMAP.md 更新到 v0.4.7
- [x] PRODUCT.md 版本号 v0.4.1 → v0.4.7

## 验收

- [x] 300 passed(v0.4.6 是 289,+11)
- [x] 本地默认配置 `/api/shutdown` 放行;host 非 loopback 返回 403
- [x] 桌面启动器:无黑窗启动 + 防重复 + 浏览器自动打开(实测 2s 就绪)
- [x] 无破坏性变更
