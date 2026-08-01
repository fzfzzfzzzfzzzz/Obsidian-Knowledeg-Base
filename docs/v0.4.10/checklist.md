# v0.4.10 任务清单(验收记录)

> 日期:2026-07-23
> PRD 见 `v0410_PRD.md`,changelog 见 `changelog.md`
> 全部已完成(事后补录,勾选状态反映当前实现)

## 后端 kb.py — 任务函数块 — 完成

- [x] `TASK_DIR_NAME = "07_Tasks"`,`make_task_id(title)` 稳定 hash id
- [x] `_task_file_path(task_id)` / `_find_task_file(task_id)`(文件名直查 + frontmatter 兜底)
- [x] `_format_task_file(meta, body)`(checklist 存 JSON 单行串,pinned 统一 true/false)
- [x] `load_task_file(path)`(checklist 反序列化,兼容旧数据补 id/text/done)
- [x] `scan_tasks()`(按 deadline 升序,空值用 9999 哨兵排末尾,损坏文件备份)
- [x] `write_task_file(path, meta, body, is_new)`(原子写 + created_at/updated_at + completed_at 生命周期)
- [x] `sync_task_to_calendar(task_id)`(单向推送 + 幂等 + task_id 回指)
- [x] `cleanup_calendar_ref(cal_id)`(删日历项时清理 task 悬空引用)
- [x] `load/save_workspace_state`(`.kb/workspace_state.json` 的 current_task_id 指针)

## Web API — tasks router — 完成

- [x] `GET /tasks` / `GET /task/{id}` / `GET /task/{id}/edit` 页面路由
- [x] `GET /api/tasks` 列表(scan_tasks)
- [x] `POST /api/tasks` 创建(校验 title/deadline/status,冲突重试)
- [x] `GET /api/tasks/{id}` 详情(含 html_body 服务端渲染)
- [x] `PATCH /api/tasks/{id}` 整体更新(None=不改,空串=更新为空)
- [x] `PATCH /api/tasks/{id}/checklist/{item_id}` 单项打勾专用端点(精准改一项)
- [x] `DELETE /api/tasks/{id}` 删除(不级联删日历项)
- [x] `POST /api/tasks/{id}/sync-calendar` 同步日历(幂等,无 deadline 返回 400)
- [x] `POST /api/tasks/{id}/pin` 置顶专用端点(只改 pinned 位)

## 前端三页 — 完成

- [x] `templates/tasks.html` 任务列表(状态 tab + 客户端排序 + 卡片网格 + checklist 编辑器)
- [x] `templates/task_detail.html` 任务详情(进度条 + 单项打勾 + 服务端 html_body)
- [x] `templates/task_edit.html` 全页编辑器(Ctrl+S + checklist 稳定 id 回写)

## 排序与置顶 — 完成

- [x] 客户端排序 4 键(deadline/status/category/created_at)+ 升降序,无需 refetch
- [x] pinned 是排序「超级键」,永远压过其他排序逻辑
- [x] 空值/未知值始终排末尾,不受升降序影响
- [x] 置顶卡片视觉标记(task-pinned class + 图钉徽章)

## checklist 稳定 id — 完成

- [x] 前端生成 `cli_<timestamp>_<rand>` id
- [x] 保存后服务端原样返回稳定 id
- [x] 全页编辑器 `rehydrateFromSaved` 按位置回写 DOM,防 id 漂移

## 工作台联动 — 完成

- [x] `.kb/workspace_state.json` current_task_id 指针
- [x] `GET /api/workspace/current_task`(已指定返回该任务,否则自动挑选)
- [x] `PATCH /api/workspace/current_task`(空串取消手动指定)
- [x] 工作台当前任务卡片(checklist 前 3 项 + 进度条动画)
- [x] 「即将截止」栏(任务 deadline 分桶 overdue/due_today/this_week/later)

## Lucide 时序坑修复 — 完成

- [x] 卡片/checklist 删除按钮用 mousedown 事件委托(非 click)
- [x] 注释记录根因(Lucide 在 mousedown→mouseup 间替换 svg)

## 验收测试 — 完成

- [x] `test_tasks.py` 18 用例(纯函数层 + Web API 层)
- [x] 346 passed(325 → 346,+21)
