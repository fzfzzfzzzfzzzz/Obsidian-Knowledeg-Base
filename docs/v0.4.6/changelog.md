# Changelog v0.4.6

> 日期:2026-07-20
> 主题:**P1 安全加固 + P3 测试网补齐**(第二轮审查剩余 20 个问题的处理)

本版接 v0.4.5 之后处理第二轮审查的 P1(安全)+ P3(测试)梯队。289 passed。

---

## 新增(P1 安全加固)

### 1. XSS 消毒(后端 + 前端)
**风险**:summary 正文经 markdown.markdown 渲染后含原始 HTML,前端 innerHTML 直注;多处 onclick 拼字符串可注入。

**修复**:
- **后端**:引入 `bleach` 依赖,新增 `web/utils.py:sanitize_html(html)` helper,在 `cards.py` 两处 `md.markdown(...)` 后调用。白名单标签(p/strong/a/pre/code/table 等),白名单属性(a 的 href、img 的 src/alt 等),protocols 只允许 http/https/mailto/ftp。
- **前端**:30+ 处动态 onclick 拼字符串全部改 `data-action` + `data-*` 属性 + document 级事件委托(`setupGlobalDelegation()`)。涉及:
  - app.js 文章卡片(读/收藏/删)、idea/todo 卡片(updateStatus)、todo 卡片(openTodoCalendar,改用全局 todoStore Map 替代 `JSON.stringify(item)` 注入)
  - favorites.html 文件夹列表(select/rename/delete,删掉双重 escapeHtml 的 safeName 变量)
  - calendar.html 月/列表/时间轴三视图(openEditDialog/deleteCalendarItem/quickCreate)
  - submit.html(消灭 `generateAllSummaries` 反解析 onclick 的反模式,改用 `dataset.sourceId`)
  - calendar.html 删除确认改用 `confirmModal` 替代原生 `confirm`(顺便消灭 XSS)

**测试**:6 用例(test_summary_sanitize),验证 script/onerror/javascript:/iframe 全被剥离,正常标签保留。

### 2. SSRF 防护(标准库 + 关闭自动重定向)
**风险**:`/api/ingest` 投稿 URL 无过滤,可让服务端访问内网/云元数据。

**修复**:
- 新增 `kb_llm._check_url_safe(url)` helper(标准库 `ipaddress + socket`),拒绝 private/loopback/link-local/reserved/multicast 地址
- `fetch_url_text` 入口校验 + `allow_redirects=False`,手动处理重定向最多 5 跳,每跳重新校验
- `_resolve_tco_and_fetch` 的 requests.get 同步关闭 allow_redirects + 校验
- 协议白名单:http/https(file:///、gopher:// 全拒)

**测试**:14 用例(test_ssrf),覆盖 loopback/private/云元数据/IPv6 loopback/content_type 伪造/重定向到内网。

### 3. 图片上传前后端一致 + magic bytes 校验
**风险**:前端 png/jpeg/webp/gif 10MB,后端仅 jpg/png 5MB;无 MIME 嗅探,content_type 可伪造。

**修复**:
- 后端对齐前端:png/jpeg/webp/gif,10MB 上限
- 新增 `_sniff_image_type(data)`:读 magic bytes 判断真实类型(PNG/JPEG/GIF89a/RIFF+WEBP),覆盖 content_type 伪造场景

**测试**:扩展 test_ingest_image(+3 用例:伪造类型/超限/WebP 通过)。

### 4. serve 安全警告 + 可选 Basic Auth
**风险**:`--host 0.0.0.0` 暴露外网时无任何认证,所有路由裸奔。

**修复**:
- `cmd_serve` 检测 host 非 loopback 时打印醒目警告,要求 `KB_SERVE_CONFIRM_EXPOSE=1` 才启动,并提示设置 `KB_WEB_USER`/`KB_WEB_PASSWORD`
- `kb_web.py` 新增 `_maybe_auth` dependency:env 配置后所有 router 强制 HTTPBasic(secrets.compare_digest 防 timing attack)

**测试**:6 用例(test_serve_auth_tz:阻止/继续/无 auth pass-through/401/正确凭证/错误凭证)。

### 5. 时区支持
**风险**:服务器在 UTC 但用户在东八区时,"今天/明天"日期偏一天。

**修复**:
- `kb_date._today()` helper 读 `KB_TZ` 环境变量(如 "Asia/Shanghai"),用 `zoneinfo.ZoneInfo` 算配置时区的当前日期
- kb_date.py 4 处 `date.today()` 改调 `_today()`
- `web/routers/calendar.py` 2 处 `detect_dates(text)` 传 `reference=kb_date._today()`

**测试**:4 用例(默认 UTC/无效时区 fallback/detect_dates 用配置时区)。

---

## 新增(P3 测试网补齐)

### kb_llm 核心单测
- `_extract_json`(单对象解析):6 用例
- `_parse_env_file`:6 用例(引号/注释/空文件)
- `chat()` HTTP 重试:7 用例(mock requests.post + time.sleep,覆盖重试/不重试/退避间隔/凭证缺失)
- `_html_to_text` / `_extract_json_list` 已在 v0.4.5 测过

### cmd_* CLI 层测试
- `cmd_status`:4 用例(空 vault/字段验证/verbose/source 计数)
- `cmd_clean_x`:6 用例(dry-run/幂等/无原始内容段/保留 frontmatter)。**顺带发现并修复一个除零 bug**(所有文件被跳过时 `total_before == 0`)

### 端到端链路测试
- `test_e2e_chain.py`:2 用例,完整跑 KB_ITEM ingest → 手工 summary → reconcile → accept-ideas → rebuild-index,验证 state/summary/正式清单三者一致。**这是仓库第一个跨命令链路测试**,之前都是单命令隔离测。

### 测试增量统计
v0.4.5 是 224 → v0.4.6 是 **289 passed**(+65)。

---

## 顺手修复的 bug

- `cmd_clean_x` 在所有文件都被跳过(无「原始内容」段)时,`100 * (1 - total_after / total_before)` 除零错误。改用条件表达式 `if total_before > 0`。

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/web/utils.py` | 新增 `sanitize_html()` + `ALLOWED_HTML_TAGS/ATTRS`;已有 `backup_file()` |
| `scripts/web/services/cards.py` | 两处 md.markdown 后调 sanitize_html |
| `scripts/web/static/app.js` | 新增 `setupGlobalDelegation()` + 全局 `todoStore`;改 ~10 处 onclick → data-action |
| `scripts/web/templates/{favorites,calendar,submit}.html` | 共改 ~20 处 onclick → data-action |
| `scripts/web/templates/base.html` | cache buster 递增(style v26、app.js v29) |
| `scripts/kb_llm.py` | 新增 `_check_url_safe()` + ipaddress/socket/urlparse import;fetch_url_text 关闭自动重定向 + 手动处理 |
| `scripts/web/routers/ingest.py` | 图片类型/大小对齐前端 + `_sniff_image_type()` magic bytes |
| `scripts/kb.py` | cmd_serve host 检测 + 警告;cmd_clean_x 除零修复 |
| `scripts/kb_web.py` | `_maybe_auth` Basic Auth dependency |
| `scripts/kb_date.py` | `_today()` 时区 helper |
| `scripts/web/routers/calendar.py` | detect_dates 传 reference |
| `requirements.txt` | +bleach>=6.0 |
| `.env.example` | 补 KB_SERVE_CONFIRM_EXPOSE/KB_WEB_USER/KB_WEB_PASSWORD/KB_TZ |
| `scripts/tests/` | 新增 5 测试文件,扩展 1 个,+65 用例 |

---

## 不变

- API 响应 schema 不变(只在错误响应加新字段)
- CLI 行为不变(serve 加了 host 检查但不影响 loopback 默认)
- 文件格式不变
- 默认配置不变(无 env 时所有新功能都不启用,完全兼容)

---

## 破坏性变更

**无**。所有新功能默认关闭,需要显式配置才启用。

---

## 不在本次范围

- rebuild-index 的 `--recover-from-corrupt` 完整灾难恢复
- 9 个 router 重复 import 去重
- tags 解析双份统一
- alert/prompt/confirm 残留的少量替换(calendar.html 已替换一处,submit.html 还有几处)
- CSS 暗色模式贯彻

第二轮审查发现的 30 个问题中,本版 + v0.4.5 共处理 25 个(P0/P1/P2/P3 主体)。剩余 5 个为代码异味,不影响数据安全和正确性。
