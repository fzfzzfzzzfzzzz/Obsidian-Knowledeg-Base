# v0.4.6 任务清单

> 日期:2026-07-20
> PRD 见 `v046_security_PRD.md`,changelog 见 `changelog.md`

## P1 安全加固 — 全部完成

### XSS 消毒
- [x] `web/utils.py` 新增 `sanitize_html()` + 白名单(bleach 依赖)
- [x] `cards.py` 两处 md.markdown 后调 sanitize_html
- [x] app.js 全局事件委托 setupGlobalDelegation + todoStore
- [x] app.js 文章卡片 4 处 onclick → data-action
- [x] app.js idea/todo 卡片 7 处 onclick → data-action
- [x] app.js openTodoCalendar 改 todoStore(替代 JSON.stringify)
- [x] favorites.html 3 处(select/rename/delete)
- [x] calendar.html 7 处(月/列表/时间轴 + confirmModal)
- [x] submit.html 5 处(消灭 generateAllSummaries 反模式)
- [x] base.html cache buster 递增
- [x] test_summary_sanitize 6 用例

### SSRF 防护
- [x] `_check_url_safe()` helper(ipaddress + socket)
- [x] fetch_url_text 关闭 allow_redirects + 手动 5 跳
- [x] _resolve_tco_and_fetch 同步处理
- [x] test_ssrf 14 用例(loopback/private/云元数据/重定向到内网)

### 图片上传对齐
- [x] `_sniff_image_type()` magic bytes 校验
- [x] 类型/大小对齐前端
- [x] test_ingest_image +3 用例(伪造/超限/WebP)

### serve 警告 + Auth
- [x] cmd_serve host 检测 + KB_SERVE_CONFIRM_EXPOSE 要求
- [x] kb_web._maybe_auth HTTPBasic dependency
- [x] test_serve_auth 6 用例

### 时区
- [x] kb_date._today() helper
- [x] 4 处 date.today() 替换
- [x] calendar.py 2 处 detect_dates 传 reference
- [x] test_timezone 4 用例

## P3 测试网补齐 — 全部完成

- [x] test_kb_llm_bugs 扩展(_extract_json +6 / _parse_env_file +6)
- [x] test_kb_llm_chat 新建(chat 重试 +7)
- [x] test_cmd_clean_x 新建(纯逻辑 +6,顺带修除零 bug)
- [x] test_cmd_status 新建(+4)
- [x] test_e2e_chain 新建(端到端 +2,仓库首个跨命令链路)

## 文档 — 完成

- [x] docs/v0.4.6/(changelog + PRD + checklist)
- [x] docs/ROADMAP.md 更新到 v0.4.6
- [x] .env.example 补 4 个新环境变量

## 验收

- [x] 289 passed(v0.4.5 是 224,+65)
- [x] 真实 vault status 输出不变
- [x] 真实 vault serve 警告正确触发(host=0.0.0.0 被阻)
- [x] 无破坏性变更
