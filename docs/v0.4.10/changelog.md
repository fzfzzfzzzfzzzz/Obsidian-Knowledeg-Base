# Changelog v0.4.10

> 日期:2026-07-23
> 主题:**任务(Tasks)管理系统 —— checklist / 截止日期 / 阻塞 / 项目 / 置顶 / 客户端排序**

本版新增「任务」功能:用户主动创建、长期跟踪的事项,带子任务 checklist、截止日期、
阻塞标记、所属项目。`07_Tasks/task_*.md` 存储,完整 Web CRUD + 单向同步到日历。
346 passed(325 → 346,+21)。

> 覆盖范围说明:本份涵盖 v0.4.10 任务 CRUD 主体,以及后续 v0.4.x 的任务相关增强
> (全页编辑器、置顶、客户端排序、checklist 稳定 id、悬空引用清理)。这些增强
> 主题统一(都是任务系统的演进),合并归档到本份,不再单独建文档。

---

## 新增

### 1. 任务(Task)数据模型

**背景**:source → idea/todo 是「从文章里抽取的被动建议」。但用户经常需要主动创建并长期
跟踪的事项 —— 一个科研课题、一个开发功能、一个待办项目,它们:
- 不来自任何文章(用户主动创建)
- 需要分解成子任务(checklist)跟踪进度
- 有截止日期和阻塞点
- 属于某个项目(如 AAAI-27)

任务系统填补这个空缺。与 todo(`04_Plans/todo_suggestions.md`,文章抽取的待办建议)是**完全不同的两套系统**。

**存储**:`07_Tasks/task_<8位hash>.md`,YAML frontmatter + Markdown 正文。

frontmatter 14 字段(由 `_format_task_file` `kb.py:3091-3116` 固定顺序写出):

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | `task_<8位hash>`,稳定唯一 |
| `title` | str | 标题(必填) |
| `category` | str | 开发/科研/个人/金融/工作/其他,默认"其他" |
| `project` | str | 所属项目(如 "AAAI-27"),区别于标题 |
| `status` | str | active / done / blocked / archived(比事件多 blocked) |
| `deadline` | str | YYYY-MM-DD,可空 |
| `blocker` | str | 当前问题/阻塞 |
| `checklist` | JSON str | 子任务清单,**单行 JSON 字符串**(见下) |
| `related_source` | str | 关联文章 source_id |
| `synced_calendar_ids` | str | 逗号分隔的日历项 id |
| `created_at` | ISO str | 创建时间,新建时补 |
| `updated_at` | ISO str | 每次写盘刷新 |
| `completed_at` | ISO str | 首次 status=done 时写入,重新激活时清空 |
| `pinned` | bool | 置顶,统一输出 `true`/`false` |

**checklist 字段结构**(`kb.py:3135-3141`):
```
[{"id": "cli_xxx", "text": "子任务内容", "done": false}, ...]
```

**设计决策:checklist 为什么存 JSON 单行字符串而非 YAML 列表**
YAML 列表序列化/反序列化在 frontmatter 里容易和正文 / 缩进 / 引号转义打架,
且单项打勾时要精准定位一个 item。存 JSON 单行字符串:`load` 时 `json.loads` 还原成 list,
`write` 时 `json.dumps` 压成一行,前后端都好处理,解析复杂度可控。

### 2. 后端函数(`scripts/kb.py:3057-3258`)

| 函数 | 行号 | 职责 |
|---|---|---|
| `make_task_id(title)` | `3057-3061` | 基于 `title + time.time_ns()` 生成 `task_<8位hash>`,保证新建不冲突 |
| `_task_file_path(task_id)` | `3064-3067` | 由 id 推导 `07_Tasks/task_<hash>.md` 路径 |
| `_find_task_file(task_id)` | `3070-3088` | 先试文件名直查(快路径),再扫 `task_*.md` 校验 frontmatter id(兜底) |
| `_format_task_file(meta, body)` | `3091-3116` | dict → markdown(checklist 存 JSON 串,pinned 统一 true/false) |
| `load_task_file(path)` | `3119-3161` | 读盘 → 完整 dict(checklist 反序列化,兼容旧数据补 id/text/done) |
| `scan_tasks()` | `3164-3180` | 扫全部 `task_*.md`,按 deadline 升序(空 deadline 用 "9999" 哨兵排末尾) |
| `write_task_file(path, meta, body, is_new)` | `3183-3201` | 原子写;补 created_at / 刷 updated_at;维护 completed_at 生命周期 |
| `sync_task_to_calendar(task_id)` | `3204-3258` | 单向推送 deadline 到日历(幂等,无 deadline 返回 reason) |
| `cleanup_calendar_ref(cal_id)` | `3268+` | 删除日历项时清理 task 的 `synced_calendar_ids` 悬空引用 |

**completed_at 生命周期**(`kb.py:3185-3200`):首次 status=done 写入、重复 done 不覆盖、
重新激活清空。这个字段专为工作台「本周完成数」统计服务(见 v0.4.13)。

### 3. Web API(`scripts/web/routers/tasks.py`,271 行,15 个路由)

**页面路由**:
- `GET /tasks` 任务列表页
- `GET /task/{task_id}` 任务详情页(404 if not found)
- `GET /task/{task_id}/edit` 全页编辑器

**API 路由**:
- `GET /api/tasks` 列出所有任务(`scan_tasks` 按 deadline 升序)
- `POST /api/tasks` 创建(校验 title/deadline 格式/status;冲突重试)
- `GET /api/tasks/{task_id}` 单任务详情(含服务端 Markdown 渲染的 `html_body`)
- `PATCH /api/tasks/{task_id}` 整体更新(None=不改,空串=更新为空)
- `PATCH /api/tasks/{task_id}/checklist/{item_id}` **checklist 单项打勾专用端点**(精准改一项,不重写全清单)
- `DELETE /api/tasks/{task_id}` 删除(只删 md,不级联删日历项)
- `POST /api/tasks/{task_id}/sync-calendar` 同步到日历(无 deadline 返回 400,已同步返回 already_synced)
- `POST /api/tasks/{task_id}/pin` **置顶专用端点**(只改 pinned 位,不影响其他字段)

**设计决策:为什么 checklist 单项打勾要专用端点**
如果用整体 PATCH,前端打勾一个 item 要把整个 checklist 数组回传,既浪费带宽,
又容易在并发场景下覆盖其他 item 的状态。专用端点 `PATCH /checklist/{item_id}` 只改一个 item,
精准、幂等、不碰其他项(测试 `test_api_checklist_toggle_single` 验证)。

### 4. 前端三页

| 文件 | 行数 | 职责 |
|---|---|---|
| `templates/tasks.html` | 409 | 任务列表:状态 tab(active/blocked/done/all)、**客户端排序**、卡片网格、新建/编辑模态、checklist 编辑器、事件委托 |
| `templates/task_detail.html` | 197 | 独立详情页:完整元数据、截止徽章(逾期/今天)、checklist 进度条、单项打勾、服务端 html_body、删除确认 |
| `templates/task_edit.html` | 211 | **全页编辑器**:宽敞表单、Ctrl/Cmd+S 快捷保存、checklist 稳定 id 回写 |

**全页编辑器决策**(提交 `48a168f`):任务内容(背景/思路/进展/笔记)往往较长,卡片内的弹窗
编辑器空间局促。改为独立路由 `/task/{id}/edit` 的全页编辑器,适合写详细内容;
新建任务仍用卡片模态(轻量场景)。

### 5. 置顶 + 客户端排序(提交 `e12adcd`)

**置顶语义**:pinned 是排序的「超级键」,永远压过其他排序逻辑(类似微信置顶会话):

```js
// tasks.html:103-105
const ap = a.pinned ? 1 : 0;
const bp = b.pinned ? 1 : 0;
if (ap !== bp) return bp - ap;  // pinned 的排前
```

置顶任务在列表前端永远显示在顶部,不受排序键/方向影响。卡片加 `task-pinned` class + 图钉徽章。

**客户端排序**(`sortTkItems` `tasks.html:99-123`):后端 `scan_tasks` 固定按 deadline 升序,
前端做更灵活的客户端排序,**切换排序键/方向无需重新 fetch**:
- 排序键:`deadline` / `status` / `category` / `created_at`,默认 deadline 升序
- 方向:升降序按钮切换
- 值映射:status/category 用固定语义顺序(非字母序),deadline/created_at 用 ISO 字符串直接比较
- **空值/未知值始终排末尾,不受升降序影响**(`tasks.html:108-113`)—— 避免切降序时空 deadline 涌到最前

### 6. checklist 稳定 id(提交 `e12adcd`)

checklist item 的 id 由前端生成 `cli_<timestamp>_<rand>`,保存后服务端原样返回。
全页编辑器保存后用 `rehydrateFromSaved` 按位置把服务端返回的稳定 id 回写 DOM,
避免反复保存导致 id 漂移使其他页面(工作台首页、详情页)的单项打勾端点 404。

### 7. 任务与日历/工作台的联动

**单向同步 + 悬空清理**:
- 任务 → 日历单向推送(创建日历项,`source_type="task"`、`task_id` 回指),幂等
- 删任务**不级联删**日历项(单向推送语义,与事件一致)
- 删日历项时 `cleanup_calendar_ref`(`kb.py:3268+`)反向清理 task 的 `synced_calendar_ids`(防悬空引用)

**工作台「当前任务」指针**:
- `.kb/workspace_state.json` 存 `current_task_id`(只存指针,不复制任务内容)
- `GET /api/workspace/current_task`(`dashboard.py:166-178`):已指定且文件存在 → 返回该任务;
  否则 `_auto_pick_current_task` 自动挑(优先 active、deadline 最近)
- `PATCH /api/workspace/current_task`:`task_id=""` 表示取消手动指定
- 工作台首页 `loadCurrentTask`(`workspace.html:189-265`)渲染当前任务卡片,
  checklist 只显示前 3 项(防卡片过长),进度条首次渲染从 0 动画增长

### 8. 测试

`scripts/tests/test_tasks.py`(411 行,18 用例),范式照搬 `test_events.py`:
纯函数层(直接调 `kb.*`)+ Web API 层(TestClient),用 `isolate_vault` fixture 隔离。

覆盖:id 生成 / 读写 roundtrip / checklist JSON 序列化与损坏降级 / scan 排序 /
frontmatter 兜底查找 / 同步幂等 / Web CRUD 校验 / **单项打勾只改一项** / 置顶端点往返持久化 /
页面 200 / 404 边界。

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/kb.py` | 任务函数块(`3057-3258`)+ `cleanup_calendar_ref`;`make_task_id` / `load/write_task_file` / `scan_tasks` / `sync_task_to_calendar`;`workspace_state` 读写 |
| `scripts/web/routers/tasks.py` | 新增,271 行,15 路由(3 页面 + 8 API + 4 专用端点) |
| `scripts/web/routers/dashboard.py` | `/api/workspace/current_task` GET/PATCH + 自动挑选逻辑 |
| `scripts/web/models.py` | `TaskCreate` / `TaskUpdate` / `TaskPinRequest` / `ChecklistItemUpdate` Pydantic 模型 |
| `scripts/web/utils.py` | `VALID_TASK_STATUS = {active, done, blocked, archived}` |
| `scripts/web/services/cards.py` | `_build_reminders`(任务截止分桶) |
| `scripts/web/templates/tasks.html` | 新增,任务列表(状态 tab + 客户端排序 + checklist 编辑器) |
| `scripts/web/templates/task_detail.html` | 新增,任务详情页(进度条 + 单项打勾) |
| `scripts/web/templates/task_edit.html` | 新增,全页编辑器(Ctrl+S + 稳定 id 回写) |
| `scripts/web/templates/workspace.html` | 「当前任务」卡片 + 「即将截止」栏 |
| `scripts/web/static/style.css` | `.task-*` / `.cl-*` / `.ws-task-*` 样式 |
| `scripts/tests/test_tasks.py` | 新增,18 用例(+21 测试) |

---

## 不变

- API schema 不向后不兼容(任务端点全新,既有端点不动)
- 既有数据格式不变(任务是新目录 `07_Tasks/`,不碰事件/文章/idea)
- CLI 不变(任务管理完全走 Web,无 CLI 命令)

---

## 破坏性变更

**无**。任务系统是全新模块,既有功能不受影响。

---

## 不在本次范围

- **任务状态元数据统一**:`TK_STATUS_META`(active/done/blocked/archived 的徽章配色)目前在
  `tasks.html` 与 `task_detail.html` 各自定义,与任务**类别**元数据(已统一到 cat-meta.js)是不同维度,
  尚未统一。可记入后续。
- **任务 CLI 命令**:任务管理完全在 Web 端,未提供 CLI(与事件系统一致)。
- **市场页 / 工作台底部四栏的「市场常用」**:占位,真实金融入口在后续版本填。
