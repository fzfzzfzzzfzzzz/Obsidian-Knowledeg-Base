# v0.4.8 任务清单

> 日期:2026-07-22
> PRD 见 `v048_PRD.md`,changelog 见 `changelog.md`

## 后端 kb.py — 事件管理函数块 — 完成

- [x] `EVENT_DIR_NAME = "06_Events"` + `EVENT_CATEGORIES`(6 预设)
- [x] `cmd_init` 加 `06_Events` 目录创建
- [x] `make_event_id(title)`:基于标题+时间戳的稳定 hash id
- [x] `_event_file_path(event_id)`:id → md 路径
- [x] `_find_event_file(event_id)`:文件名直查 + 扫描校验 frontmatter id(兜底)
- [x] `_format_event_file(meta, body)`:frontmatter 序列化(`synced_calendar_ids` 用逗号串)
- [x] `load_event_file(path)`:反序列化(`synced_calendar_ids` 解析成 list)
- [x] `scan_events()`:扫 `event_*.md`,按日期升序
- [x] `write_event_file(path, meta, body, is_new)`:原子写 + created_at/updated_at 维护
- [x] `sync_event_to_calendar(event_id)`:单向推送 + 幂等(已有存活项不重复)

## Web API — events router — 完成

- [x] `web/routers/events.py` 新增(162 行)
- [x] `GET /events` 页面(HTMLResponse)
- [x] `GET /api/events` 列表(按日期升序)
- [x] `POST /api/events` 创建(校验:标题非空 + 日期格式 + status 白名单)
- [x] `GET /api/events/{id}` 详情(含正文)
- [x] `PATCH /api/events/{id}` 更新(空串=更新为空,None=不改)
- [x] `DELETE /api/events/{id}` 删除(单向推送语义,不级联删日历项)
- [x] `POST /api/events/{id}/sync-calendar` 同步(幂等)
- [x] `kb_web.py` 装配 `events.router`(+`_auth_deps`)
- [x] `models.py` `EventCreate` / `EventUpdate` Pydantic 模型
- [x] `utils.py` `VALID_EVENT_STATUS` + `VALID_EVENT_CATEGORIES`

## 前端 — 完成

- [x] `templates/events.html` 事件卡片视图(356 行)
- [x] 分类配色(浅/暗主题各一套 `--cat-*` 变量,含 `--cat-contest`)
- [x] 状态徽章(active/done/archived)
- [x] 即将到来高亮 `ev-flash` 动画
- [x] 正文预览 + 同步状态标记
- [x] `base.html` 导航栏「📌 事件」入口
- [x] `style.css` `.event-card` / `.ev-*` 样式(68 行)
- [x] `app.js` 事件页交互

## 日历联动 — 完成

- [x] `routers/calendar.py` 日历项支持 `source_type=event`
- [x] `templates/calendar.html` 日历展示事件来源标记
- [x] 事件同步时日历项 `event_id` 回指 + category 透传

## 测试 — 完成

- [x] `test_events.py` 新增(376 行,25 用例)
  - [x] CRUD 全链路(创建/读取/更新/删除)
  - [x] 同步幂等(重复调用不重复创建)
  - [x] 校验边界(空标题 400 / 非法日期 400 / 非法 status 400)
  - [x] 不存在事件 404
  - [x] 文件名冲突处理
  - [x] 日期排序

## 验收

- [x] 325 passed(v0.4.7 是 300,+25)
- [x] `/events` 页面渲染正常(HTTP 200)
- [x] 导航栏有「📌 事件」入口
- [x] 事件 CRUD 全链路可用
- [x] 日历同步幂等
- [x] 无破坏性变更(合并后 source/summary/idea/todo/calendar 链路 + shutdown 功能共存)
