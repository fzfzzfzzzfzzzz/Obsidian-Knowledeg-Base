# v0.4.10 PRD:任务(Tasks)管理系统

> 日期:2026-07-23
> 上一版:v0.4.9(见 `docs/v0.4.9/`)
> 性质:新功能(用户主动创建的任务系统,带 checklist/deadline/blocker)

## 0. 文档定位

本 PRD 事后补写,记录任务系统的**设计动机与关键决策**。346 passed(325 → 346,+21)。

## 1. 动机:任务 vs Todo 的边界

知识库在 v0.4.10 之前已有「todo」系统(`04_Plans/todo_suggestions.md`),但它有两个限制:
1. **来源单一**:只能从文章 summary 抽取,不能凭空创建
2. **粒度粗**:只有标题 + 截止日期,没有子任务分解、没有阻塞标记、没有进度跟踪

而用户实际有大量**主动创建、长期跟踪**的事项:
- 一个科研课题(要分解成「读 5 篇综述 / 跑 baseline / 写 method」等子任务)
- 一个开发功能(要分解成「设计 API / 写后端 / 写前端 / 测试」)
- 一个待办项目(有截止日期、有所属项目、可能被某事阻塞)

这些事项不来自任何文章,需要分解子任务、跟踪进度、标记阻塞。任务系统填补这个空缺。

| 维度 | Todo(已有) | Task(本版新增) |
|---|---|---|
| 来源 | 文章 summary 抽取 | 用户主动创建 |
| 存储 | `04_Plans/todo_suggestions.md` | `07_Tasks/task_*.md`(每任务一文件) |
| 粒度 | 标题 + 截止 | checklist 子任务 + 截止 + 阻塞 + 项目 |
| 生命周期 | 接受 → weekly/monthly/someday | 长期跟踪,状态流转 |
| 入口 | Web / CLI accept | Web CRUD |

## 2. 数据模型决策

### 2.1 为什么每任务一个 `.md` 文件

todo 系统是「一个文件装所有待办」(`todo_suggestions.md`),因为待办是平铺的短条目。
任务相反,每个任务有独立的长正文(背景/思路/进展/笔记)+ checklist,内容量足以撑起一个文件。
每任务一文件的好处:原子写、独立 git diff、可关联附件、详情页可直接渲染。

### 2.2 为什么 checklist 存 JSON 单行字符串

YAML 列表在 frontmatter 里容易出问题:
- 缩进 / 引号 / 转义与正文边界容易打架
- 单项打勾时要精准定位一个 item,YAML 列表整体替换会覆盖并发修改

存 JSON 单行字符串:
- `load` 时 `json.loads` 还原成 list
- `write` 时 `json.dumps` 压成一行
- 单项打勾用专用端点 `PATCH /checklist/{item_id}`,只改一个 item,不碰其他项

### 2.3 为什么 status 多一个 blocked

事件 status 是 `active/done/archived`。任务多了 `blocked`(阻塞),因为任务常被外部依赖卡住
(等回复、等数据、等评审),需要显式标记区别于「进行中但没卡」。工作台「即将截止」栏会
突出显示 blocked + overdue 任务。

### 2.4 completed_at 字段的生命周期

`completed_at` 不是 status=done 的简单镜像,而是独立维护:
- 首次 status=done → 写入当前时间
- 重复 status=done → **不覆盖**(保留首次完成时间)
- 重新激活(从 done 改回 active)→ **清空**

这个字段专为工作台「本周完成数」统计服务:按 `completed_at` 落在 ISO 周窗口内计数。
如果用 `updated_at` 代替,任何编辑都会刷新时间,统计失真。

## 3. API 设计决策

### 3.1 为什么 checklist 单项打勾用专用端点

整体 PATCH 打勾的问题:
- 浪费带宽(打勾一个 item 要回传整个 checklist 数组)
- 并发不安全(A 勾第 1 项、B 勾第 2 项,后到的会覆盖先到的)
- 易覆盖(前端缓存若陈旧,会丢其他 item 的最新状态)

专用端点 `PATCH /api/tasks/{id}/checklist/{item_id}` 只改一个 item:
```json
// 请求
{"done": true}
// 服务端只改匹配 item_id 的那一项,其他不动
```
测试 `test_api_checklist_toggle_single` 验证「打勾一项不影响其他项」。

### 3.2 为什么置顶用专用端点

置顶(`pinned`)是高频独立操作(列表里点图钉),如果走整体 PATCH 要回传整个任务。
专用端点 `POST /api/tasks/{id}/pin` 只改 pinned 位,不碰其他字段,
失败也不影响任务内容(测试 `test_api_pin_endpoint` 验证持久化)。

### 3.3 单向同步 + 悬空清理

任务 → 日历单向推送(创建日历项,`task_id` 回指),与事件系统一致:
- 删任务**不级联删**日历项(单向推送语义,日历项可能已独立有用)
- 删日历项时 `cleanup_calendar_ref` 反向清理 task 的 `synced_calendar_ids`(防悬空引用)

## 4. 前端决策

### 4.1 为什么排序在客户端做

后端 `scan_tasks` 固定按 deadline 升序(简单、可缓存)。前端做更灵活的客户端排序:
- 4 个排序键(deadline/status/category/created_at)+ 升降序,切换**无需重新 fetch**
- 空值/未知值始终排末尾,不受升降序影响(避免切降序时空 deadline 涌到最前,体验突兀)

### 4.2 为什么置顶是排序「超级键」

pinned 任务永远在列表最前,不受任何排序键/方向影响(类似微信置顶会话)。
这是用户的强预期:置顶 = 「这个最重要,永远先看到」。实现上是排序函数的第一比较键。

### 4.3 全页编辑器 vs 卡片模态

任务正文往往较长,卡片内的弹窗编辑器空间局促。决策:
- **新建任务**:卡片模态(轻量,快速创建)
- **编辑已有任务**:全页编辑器 `/task/{id}/edit`(宽敞,适合写详细内容)
- 快捷键 Ctrl/Cmd+S 保存

### 4.4 checklist 稳定 id 的必要性

checklist item 的 id 由前端生成。如果每次保存都重新生成,会导致:
- 工作台首页 / 详情页此刻显示的旧 id 勾选项失效(单项打勾端点 404)

解决:保存后用服务端返回的稳定 id 回写 DOM(`rehydrateFromSaved`),保证 id 不漂移。
这在使用全页编辑器「保存后留页继续编辑」的场景下尤其关键。

### 4.5 Lucide 图标时序坑

卡片 / checklist 的删除按钮用 `mousedown` 事件委托而非 `click`。原因:Lucide 图标(svg)
在按钮内,全局 MutationObserver 触发的 `refreshIcons()` 会在 requestAnimationFrame 里
重新替换 svg 元素。若用户按住鼠标时 svg 被替换,mouseup 落在新元素上,浏览器判定
mousedown/mouseup 不同源 → 不触发 click。mousedown 在元素被替换前就触发,避开时序坑。

## 5. 工作台联动

任务系统不是孤岛,与工作台深度联动:
- **当前任务指针**:`.kb/workspace_state.json` 的 `current_task_id`,工作台首页渲染当前任务卡片
- **自动挑选**:未手动指定时,自动挑 active + deadline 最近的任务
- **本周概览**:本周任务创建数 / 完成数(依赖 completed_at)/ active 总数
- **即将截止**:active + 有 deadline 的任务,按 urgency 分桶(overdue/due_today/this_week/later)

## 6. 不在本次范围

- 任务**状态**元数据统一(TK_STATUS_META 仍各自定义,与类别元数据是不同维度)
- 任务 CLI 命令(管理完全在 Web)
- 市场页 / 工作台底部四栏的「市场常用」占位
