# v0.4.8 PRD:事件(Events)管理功能

> 日期:2026-07-22
> 上一版:v0.4.7(见 `docs/v0.4.7/`)
> 性质:新功能(用户主动管理的外部事件 + 日历联动)

## 0. 文档定位

本 PRD 对应 v0.4.8 的「事件」功能。区别于已有的 source/idea/todo 链路(从文章抽取的被动建议),
事件是用户**主动创建**并关注的外部事项(比赛/会议/财报/截止日期/发布等),需要独立存储 +
与日历联动。325 passed(300 → 325,+25)。

## 1. 动机

知识库已有两条数据流:
- **source → summary → idea/todo**:从文章里抽取的被动建议,走 review 队列

但用户经常需要记录**不来自任何文章**的外部事件:
- 某场比赛的日期
- 某产品发布会
- 某公司财报发布日
- 某截止日期

这些事件的特点:
- 单一日期(不需要复杂调度)
- 用户主动创建(不来自文章抽取)
- 需要和日历联动(在日历上看到)
- 可选关联某篇文章(`related_source`)

事件功能填补这个空缺,且与现有日历打通。

## 2. 数据模型

### 2.1 存储
- 目录:`06_Events/`(`cmd_init` 自动创建)
- 文件:`06_Events/event_<8位hash>.md`(每事件一文件)
- 格式:YAML frontmatter + Markdown 正文(与 source/summary 风格一致)

### 2.2 frontmatter 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | `event_<8位hash>`,基于标题+时间戳,保证新建不冲突 |
| `title` | str | 事件标题(必填) |
| `date` | str | 单日期 `YYYY-MM-DD`(必填) |
| `category` | str | 6 预设之一(会议/财报/截止日期/发布/比赛/其他),允许自定义 |
| `note` | str | 简短备注 |
| `status` | str | `active` / `done` / `archived` |
| `related_source` | str | 可选,关联文章 source_id(单向) |
| `synced_calendar_ids` | str | 逗号串,记录已同步到的日历项 id(幂等用) |
| `created_at` / `updated_at` | str | ISO 时间戳 |

### 2.3 正文
Markdown 自由正文(`body`),无强制结构。

## 3. 后端实现(kb.py)

### 3.1 核心函数

- `make_event_id(title)`:`event_<hash(title|time_ns)>`,保证新建不冲突
- `_event_file_path(event_id)`:`06_Events/event_<hash>.md`
- `_find_event_file(event_id)`:文件名直查(快路径)+ 扫描校验 frontmatter id(兜底,防文件名被改)
- `_format_event_file(meta, body)`:frontmatter + 正文序列化(`synced_calendar_ids` 用逗号串避免 YAML 列表复杂度)
- `load_event_file(path)`:反序列化,`synced_calendar_ids` 解析成 `list[str]`
- `scan_events()`:扫 `event_*.md`,按日期升序(无日期排末尾 `9999`)
- `write_event_file(path, meta, body, is_new)`:原子写(`write_text`),新建补 `created_at`,更新刷新 `updated_at`

### 3.2 日历同步

`sync_event_to_calendar(event_id)`:
- **单向推送**:在日历里创建一条 item,不建立双向绑定
- **幂等**:若该事件已有存活日历项(`synced_calendar_ids` 里仍有在日历中的),不重复创建;
  日历项被删后允许重新推送
- 创建的日历项 `source_type="event"`、`event_id` 回指事件(供前端识别来源)
- 推送成功后把新 item_id 追加进事件的 `synced_calendar_ids` 写回 frontmatter

## 4. Web API(`web/routers/events.py`)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/events` | 事件列表页面(HTML) |
| GET | `/api/events` | 所有事件(按日期升序),前端按 upcoming/past/all 筛选 |
| POST | `/api/events` | 创建(校验标题非空 + 日期格式 + status 白名单) |
| GET | `/api/events/{id}` | 单事件详情(含正文) |
| PATCH | `/api/events/{id}` | 更新(空串=更新为空,`None`=不改) |
| DELETE | `/api/events/{id}` | 删除(只删 md,**不级联删日历项**——单向推送语义) |
| POST | `/api/events/{id}/sync-calendar` | 单向同步到日历(幂等) |

所有端点继承 router 级 `_maybe_auth`(云端 Basic Auth 场景同样受保护)。

### 4.1 校验规则
- 标题:strip 后非空,否则 400
- 日期:`date.fromisoformat` 校验,否则 400
- status:必须在 `VALID_EVENT_STATUS`(`active|done|archived`),否则 400
- category:允许自定义,不强制白名单(落盘时空值回退"其他")

## 5. 前端(`templates/events.html`)

- 事件卡片视图:每事件一张卡,左侧分类色条(`.event-card` border-left)
- 分类配色:6 预设各有颜色(浅/暗主题各一套 CSS 变量)
- 状态徽章:`active` / `done` / `archived`
- 即将到来高亮:`.ev-highlight` 触发 `ev-flash` 1.8s 动画
- 正文预览、同步状态标记(`.ev-synced-tag`)
- 导航栏「📌 事件」入口(`base.html`)

## 6. 与日历的联动

- 事件同步到日历后,日历项带 `source_type="event"` + `event_id`
- 日历前端可识别该 item 来源是事件(而非文章),展示对应标记
- category 与日历共享 6 预设(同步时直接透传)

## 7. 范围外(留作后续)

- 多日期 / 重复事件(当前仅单日期)
- 事件↔文章双向关联(当前 `related_source` 单向,无反向索引)
- 事件删除时级联删日历项(当前单向推送语义)
- CLI 事件管理命令(当前纯 Web)

## 8. 验收标准

- [x] 325 passed(v0.4.7 是 300,+25)
- [x] 事件 CRUD 全链路可用(创建/读取/更新/删除)
- [x] 日历同步幂等(重复调用不重复创建)
- [x] 校验生效(空标题/非法日期/非法 status 返回 400)
- [x] 事件页 `/events` 渲染正常,导航栏有入口
- [x] 日历能展示事件来源标记
- [x] 无破坏性变更(现有 source/summary/idea/todo/calendar 链路不受影响)
