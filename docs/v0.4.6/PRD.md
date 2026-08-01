# v0.4.6 PRD:P1 安全加固 + P3 测试网补齐

> 日期:2026-07-20
> 上一版:v0.4.5(见 `docs/v0.4.5/`)
> 性质:安全加固 + 测试覆盖,默认配置完全兼容(所有新功能需显式启用)

## 0. 文档定位

本 PRD 对应 v0.4.6 处理第二轮深度审查的 P1(安全)+ P3(测试)梯队。P0/P2 已在 v0.4.5 完成。所有新功能默认关闭,无 env 配置时行为与 v0.4.5 完全一致。

## 1. P1 安全(5 项)

### 1.1 XSS 消毒
- 后端:`bleach` 消毒 summary HTML(script/onerror/javascript:/iframe 全剥离)
- 前端:30+ 处动态 onclick 拼字符串改 `data-action` + document 事件委托

### 1.2 SSRF 防护
- `_check_url_safe(url)`:标准库 ipaddress + socket,拒绝内网/保留地址
- `fetch_url_text` 关闭自动重定向 + 手动处理 5 跳,每跳重检

### 1.3 图片上传对齐
- 后端对齐前端类型/大小(png/jpeg/webp/gif,10MB)
- magic bytes 校验防 content_type 伪造

### 1.4 serve 警告 + Basic Auth
- host 非 loopback 时要求 KB_SERVE_CONFIRM_EXPOSE=1
- 可选 Basic Auth(KB_WEB_USER / KB_WEB_PASSWORD)

### 1.5 时区
- `_today()` 读 KB_TZ 配置,用 zoneinfo

## 2. P3 测试网(覆盖盲区)

### 2.1 kb_llm 核心
- `_extract_json` / `_parse_env_file` / `chat()` 重试逻辑

### 2.2 cmd_* CLI 层
- `cmd_status` / `cmd_clean_x`(顺带修除零 bug)

### 2.3 端到端链路
- 仓库第一个跨命令链路测试(ingest → reconcile → accept → rebuild)

## 3. 范围外

- rebuild-index 灾难恢复模式(--recover-from-corrupt)
- 9 个 router 重复 import 去重
- tags 解析双份统一
- alert 残留全替换

## 4. 验收标准

- [x] 289 passed(v0.4.5 是 224,+65)
- [x] XSS:script/onerror/javascript:/iframe 在响应中不出现
- [x] SSRF:loopback/private/云元数据/IPv6 全被拒
- [x] Basic Auth:配置后无凭证 401,正确凭证 200
- [x] 时区:KB_TZ=UTC 时 detect_dates 用 UTC 日期
- [x] 真实 vault status 输出与 v0.4.5 一致
- [x] 无破坏性变更(默认配置完全兼容)
