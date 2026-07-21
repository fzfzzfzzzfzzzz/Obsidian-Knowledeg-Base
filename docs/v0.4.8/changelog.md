# Changelog v0.4.8

> 日期:2026-07-22
> 主题:**事件(Events)管理功能 + 日历事件链接**

本版新增「事件」功能:用户主动创建并关注的事项(比赛/会议/财报/截止日期/发布等),
单日期 + Markdown 文件存储(`06_Events/`),支持单向同步到日历。
325 passed(300 → 325,+25)。

---

## 新增

### 1. 事件(Events)管理

**背景**:source → idea/todo 是「从文章里抽取的被动建议」。但用户经常需要主动记录
自己关注的外部事件(某场比赛、某产品发布、某财报日),这些事件不来自某一篇文章,
却需要和文章/日历联动。事件功能填补了这个空缺。

**存储**:
- 新增 `06_Events/` 目录(`cmd_init` 自动创建)
- 每个事件一个 `06_Events/event_<8位hash>.md`,YAML frontmatter + Markdown 正文
- frontmatter 字段:`id` / `title` / `date`(单日期 YYYY-MM-DD)/ `category` /
  `note` / `status`(`active|done|archived`)/ `related_source`(可选关联文章)/
  `synced_calendar_ids`(逗号串,记录已同步到的日历项)

**后端(kb.py)**:
- `make_event_id(title)`:`event_<hash>`,基于标题+时间戳保证新建不冲突
- `_find_event_file(event_id)`:文件名直查(快路径)+ 扫描校验 frontmatter id(兜底)
- `load_event_file(path)`:解析 frontmatter + 正文,`synced_calendar_ids` 解析成 list
- `scan_events()`:扫 `event_*.md`,按日期升序
- `write_event_file(path, meta, body, is_new)`:原子写,新建补 `created_at`,更新刷新 `updated_at`
- `sync_event_to_calendar(event_id)`:单向推送(创建日历项,回指 event_id),幂等

**Web API**(`web/routers/events.py`,7 个端点):
- `GET /events` 页面(事件卡片视图)
- `GET /api/events` 列表(按日期升序,前端按 upcoming/past/all 筛选)
- `POST /api/events` 创建(校验标题非空 + 日期格式 + status 白名单)
- `GET /api/events/{id}` 详情(含正文)
- `PATCH /api/events/{id}` 更新(空串=更新为空,None=不改)
- `DELETE /api/events/{id}` 删除(只删 md 文件,不级联删日历项——单向推送语义)
- `POST /api/events/{id}/sync-calendar` 单向同步(幂等:已有存活日历项不重复创建)

**前端**:
- `templates/events.html` 事件卡片视图(356 行):分类配色、状态徽章、
  即将到来高亮动画(`ev-flash`)、正文预览、同步状态标记
- 导航栏新增「📌 事件」入口(`base.html`)
- `style.css` `.event-card` / `.ev-*` 样式(68 行)

**与日历的联动**:
- 事件同步到日历时,日历项 `source_type="event"`、`event_id` 回指,
  前端可在日历里识别来源是事件而非文章
- category 与日历共享(6 预设:会议/财报/截止日期/发布/比赛/其他)

### 2. 测试
- `test_events.py`(376 行,25 用例):覆盖 CRUD 全链路 + 同步幂等 + 边界
  (空标题/非法日期/非法 status/不存在事件/重复同步/文件名冲突)

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/kb.py` | +195 行:事件管理函数块 + `cmd_init` 加 `06_Events` 目录 + `EVENT_CATEGORIES` |
| `scripts/kb_web.py` | 装配 `events.router` |
| `scripts/web/models.py` | `EventCreate` / `EventUpdate` Pydantic 模型 |
| `scripts/web/routers/events.py` | 新增,162 行,7 端点 |
| `scripts/web/templates/events.html` | 新增,356 行,事件卡片视图 |
| `scripts/web/templates/base.html` | 导航栏加「📌 事件」链接 |
| `scripts/web/static/style.css` | `.event-card` / `.ev-*` 样式 + `--cat-contest` 配色 |
| `scripts/web/static/app.js` | 事件页交互逻辑 |
| `scripts/web/utils.py` | `VALID_EVENT_STATUS` + `VALID_EVENT_CATEGORIES` |
| `scripts/web/routers/calendar.py` | 日历项支持 `source_type=event` |
| `scripts/web/templates/calendar.html` | 日历展示事件来源标记 |
| `scripts/tests/test_events.py` | 新增,376 行,25 用例 |

---

## 不变

- API schema 仅新增(7 个 `/api/events*` 端点),无现有端点改动
- CLI 行为不变(事件纯 Web 管理,无 CLI 命令)
- 文件格式不变(YAML frontmatter + Markdown,与 source/summary 一致风格)
- 默认配置不变

---

## 破坏性变更

**无**。事件是新功能,不影响现有 source/summary/idea/todo/calendar 链路。

---

## 不在本次范围

- 事件的多日期/重复事件(当前仅单日期)
- 事件↔文章的双向关联(当前 `related_source` 单向指向文章,无反向索引)
- 事件删除时级联删日历项(当前是单向推送语义,删事件不动日历)
- CLI 事件管理命令(当前纯 Web)
