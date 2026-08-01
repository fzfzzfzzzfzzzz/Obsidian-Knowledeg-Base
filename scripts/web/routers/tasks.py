#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/tasks.py —— 任务(用户主动创建,带 checklist/截止日期/阻塞)路由。

职责:任务 CRUD + checklist 单项打勾 + 同步到日历 + 详情页。
    页面:GET /tasks, GET /task/{task_id}
    API :GET/POST /api/tasks, GET/PATCH/DELETE /api/tasks/{task_id},
         PATCH /api/tasks/{task_id}/checklist/{item_id}(单项打勾),
         POST /api/tasks/{task_id}/sync-calendar

任务数据存 07_Tasks/task_*.md(markdown 文件,YAML frontmatter + 正文),
与 04_Plans/plan_suggestions.md(文章抽取的计划建议)是完全不同的系统。
模式照搬 events.py,新增 checklist 单项打勾端点。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from web.utils import (
    ENC,
    templates,
    sanitize_html,
    VALID_TASK_STATUS,
)
from web.models import TaskCreate, TaskUpdate, TaskPinRequest, ChecklistItemUpdate

import kb


def _render_task_body_html(body: str) -> str:
    """把任务正文 Markdown 渲染成消毒后的 HTML(供详情页清晰阅读)。

    与 summary 详情(cards.py)同款:markdown.markdown + sanitize_html。
    空正文返回空串。
    """
    if not body or not body.strip() or body.strip() == "（暂无描述）":
        return ""
    try:
        import markdown as md
        return sanitize_html(md.markdown(
            body,
            extensions=["extra", "codehilite", "toc"],
            extension_configs={"codehilite": {"guess_lang": False}},
        ))
    except Exception:
        return ""

router = APIRouter()


@router.get("/tasks", response_class=HTMLResponse)
async def page_tasks(request: Request):
    """任务列表页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "tasks.html", {"active_nav": "tasks"}
    )


@router.get("/task/{task_id}", response_class=HTMLResponse)
async def page_task_detail(task_id: str, request: Request):
    """任务独立详情页。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    return templates.TemplateResponse(
        request, "task_detail.html",
        {"active_nav": "tasks", "task_id": task_id},
    )


@router.get("/task/{task_id}/edit", response_class=HTMLResponse)
async def page_task_edit(task_id: str, request: Request):
    """任务全页编辑器(编辑已有任务用,适合写详细内容)。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    return templates.TemplateResponse(
        request, "task_edit.html",
        {"active_nav": "tasks", "task_id": task_id},
    )


@router.get("/api/tasks")
async def api_tasks_list():
    """所有任务(按 deadline 升序)。前端按 status 自行筛选。"""
    return JSONResponse({"items": kb.scan_tasks()})


@router.post("/api/tasks")
async def api_tasks_create(payload: TaskCreate):
    """创建任务,写 markdown 文件到 07_Tasks/。"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    if payload.deadline:
        try:
            date.fromisoformat(payload.deadline)
        except ValueError:
            raise HTTPException(400, f"截止日期格式错误:{payload.deadline}(需 YYYY-MM-DD)")
    if payload.status not in VALID_TASK_STATUS:
        raise HTTPException(400, f"非法 status 值:{payload.status}")

    import datetime as _dt
    task_id = kb.make_task_id(title)
    path = kb._task_file_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():  # 文件名冲突(极小概率)
        task_id = kb.make_task_id(title + str(_dt.datetime.now().timestamp()))
        path = kb._task_file_path(task_id)

    meta = {
        "id": task_id,
        "title": title,
        "category": payload.category.strip() or "其他",
        "project": payload.project.strip(),
        "status": payload.status,
        "deadline": payload.deadline.strip(),
        "blocker": payload.blocker.strip(),
        "next_action": payload.next_action.strip(),
        "checklist": [item.model_dump() for item in payload.checklist],
        "related_source": payload.related_source.strip(),
        "synced_calendar_ids": "",
        "completed_at": "",  # v0.4.11: 完成(status=done)时由 write_task_file 写入
        "pinned": bool(payload.pinned),
    }
    kb.write_task_file(path, meta, payload.body, is_new=True)
    task = kb.load_task_file(path)
    return JSONResponse({"ok": True, "task": task})


@router.get("/api/tasks/{task_id}")
async def api_tasks_get(task_id: str):
    """获取单个任务详情(含正文 + checklist + 渲染后的 html_body)。"""
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    task = kb.load_task_file(path)
    task["html_body"] = _render_task_body_html(task.get("body", ""))
    return JSONResponse(task)


def _update_task_fields(task: dict, payload: TaskUpdate) -> dict:
    """把非 None 更新值合并进 task dict,返回新 meta(供 write_task_file)。

    统一语义:None=不改,提供值(含空串)=更新为该值。
    """
    meta = {k: v for k, v in task.items() if k not in ("body", "path")}
    if payload.title is not None:
        meta["title"] = payload.title.strip()
    if payload.category is not None:
        meta["category"] = payload.category.strip() or "其他"
    if payload.project is not None:
        meta["project"] = payload.project.strip()
    if payload.status is not None:
        if payload.status not in VALID_TASK_STATUS:
            raise HTTPException(400, f"非法 status 值:{payload.status}")
        meta["status"] = payload.status
    if payload.deadline is not None:
        dl = payload.deadline.strip()
        if dl:
            try:
                date.fromisoformat(dl)
            except ValueError:
                raise HTTPException(400, f"截止日期格式错误:{dl}")
        meta["deadline"] = dl
    if payload.blocker is not None:
        meta["blocker"] = payload.blocker.strip()
    if payload.next_action is not None:
        meta["next_action"] = payload.next_action.strip()
    if payload.checklist is not None:
        meta["checklist"] = [item.model_dump() for item in payload.checklist]
    if payload.related_source is not None:
        meta["related_source"] = payload.related_source.strip()
    if payload.pinned is not None:
        new_pinned = bool(payload.pinned)
        # 与 /pin 端点保持一致:新置顶时记时间戳(排序用),取消时清空
        if new_pinned and not task.get("pinned"):
            meta["pinned_at"] = kb.now_ts()
        elif not new_pinned:
            meta["pinned_at"] = ""
        meta["pinned"] = new_pinned
    meta["synced_calendar_ids"] = ",".join(task.get("synced_calendar_ids", []))
    return meta


@router.patch("/api/tasks/{task_id}")
async def api_tasks_update(task_id: str, payload: TaskUpdate):
    """更新任务字段(整体字段更新)。

    None=不改,提供值(含空串)=更新为该值。
    checklist 整体替换(传 list);单项打勾用专用端点。

    若 deadline 被改且任务已同步到日历,自动 reconcile 日历项的日期
    (sync_task_to_calendar 内部按日期差异就地更新,不新建)。
    """
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    task = kb.load_task_file(path)
    had_synced = bool(task.get("synced_calendar_ids"))
    deadline_changed = payload.deadline is not None and payload.deadline.strip() != task.get("deadline", "")
    meta = _update_task_fields(task, payload)
    body = task["body"] if payload.body is None else payload.body
    kb.write_task_file(path, meta, body, is_new=False)

    # 改了 deadline 且之前已同步 → 自动更新日历项,避免旧日期点残留
    if deadline_changed and had_synced:
        kb.sync_task_to_calendar(task_id)

    return JSONResponse({"ok": True, "task": kb.load_task_file(path)})


@router.patch("/api/tasks/{task_id}/checklist/{item_id}")
async def api_tasks_checklist_toggle(task_id: str, item_id: str, payload: ChecklistItemUpdate):
    """单项打勾/更新(只改一个 checklist 项,精准,不重写整个清单)。

    payload.done = True/False 打勾/取消;payload.text 改文本。都 None 则不改。
    """
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    task = kb.load_task_file(path)
    checklist = task.get("checklist", [])
    found = False
    for item in checklist:
        if item.get("id") == item_id:
            if payload.done is not None:
                item["done"] = payload.done
            if payload.text is not None:
                item["text"] = payload.text.strip()
            found = True
            break
    if not found:
        raise HTTPException(404, f"找不到 checklist 项:{item_id}")
    meta = {k: v for k, v in task.items() if k not in ("body", "path")}
    meta["checklist"] = checklist
    meta["synced_calendar_ids"] = ",".join(task.get("synced_calendar_ids", []))
    kb.write_task_file(path, meta, task["body"], is_new=False)
    return JSONResponse({"ok": True, "task": kb.load_task_file(path)})


@router.delete("/api/tasks/{task_id}")
async def api_tasks_delete(task_id: str):
    """删除任务(只删 markdown 文件,不级联删已推送的日历项 —— 单向推送语义)。"""
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    path.unlink()
    return JSONResponse({"ok": True, "deleted": task_id})


@router.post("/api/tasks/{task_id}/sync-calendar")
async def api_tasks_sync_calendar(task_id: str):
    """把任务截止日期单向推送到日历(创建一条 calendar item,回指 task_id)。

    幂等:已有存活日历项时不重复创建。任务无 deadline 返回 400。
    """
    result = kb.sync_task_to_calendar(task_id)
    if result.get("reason") == "task_not_found":
        raise HTTPException(404, f"找不到任务:{task_id}")
    if result.get("reason") == "task_has_no_deadline":
        raise HTTPException(400, "任务没有截止日期,无法同步到日历")
    return JSONResponse(result)


@router.post("/api/tasks/{task_id}/pin")
async def api_tasks_pin(task_id: str, payload: TaskPinRequest):
    """置顶/取消置顶任务(专用端点,只改 pinned 位,不影响其他字段)。

    置顶任务在任务列表前端永远显示在顶部,不受排序键/方向影响。
    """
    path = kb._find_task_file(task_id)
    if path is None:
        raise HTTPException(404, f"找不到任务:{task_id}")
    task = kb.load_task_file(path)
    meta = {k: v for k, v in task.items() if k not in ("body", "path")}
    meta["pinned"] = bool(payload.pinned)
    # 置顶时记时间戳(组内按此倒序:最近置顶的排第一);取消时清空
    meta["pinned_at"] = kb.now_ts() if payload.pinned else ""
    kb.write_task_file(path, meta, task["body"], is_new=False)
    return JSONResponse({"ok": True, "task_id": task_id, "pinned": meta["pinned"]})
