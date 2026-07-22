#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/events.py —— 事件(用户关注的事项)路由。

职责:事件 CRUD + 同步到日历。
    页面:GET /events
    API :GET/POST /api/events, GET/PATCH/DELETE /api/events/{id},
         POST /api/events/{id}/sync-calendar

事件数据存 06_Events/event_*.md(markdown 文件,YAML frontmatter + 正文),
不走 review 队列(纯手动创建)。同步到日历为单向推送。
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from web.utils import (
    ENC,
    templates,
    VALID_EVENT_STATUS,
)
from web.models import EventCreate, EventUpdate

import kb

router = APIRouter()


@router.get("/events", response_class=HTMLResponse)
async def page_events(request: Request):
    """事件列表页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "events.html", {"active_nav": "events"}
    )


@router.get("/api/events")
async def api_events_list():
    """所有事件(按日期升序)。前端按 upcoming/past/all 自行筛选。"""
    return JSONResponse({"items": kb.scan_events()})


@router.post("/api/events")
async def api_events_create(payload: EventCreate):
    """创建事件,写 markdown 文件到 06_Events/。"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    # 校验日期
    try:
        date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(400, f"日期格式错误:{payload.date}(需 YYYY-MM-DD)")
    if payload.status not in VALID_EVENT_STATUS:
        raise HTTPException(400, f"非法 status 值:{payload.status}")

    event_id = kb.make_event_id(title)
    path = kb._event_file_path(event_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 文件名冲突(极小概率):追加随机段
    if path.exists():
        event_id = kb.make_event_id(title + str(datetime.now().timestamp()))
        path = kb._event_file_path(event_id)

    meta = {
        "id": event_id,
        "title": title,
        "date": payload.date,
        "category": payload.category.strip() or "其他",
        "note": payload.note.strip(),
        "status": payload.status,
        "related_source": payload.related_source.strip(),
        "synced_calendar_ids": "",
        "completed_at": "",  # v0.4.12: 完成(status=done)时由 write_event_file 写入
    }
    kb.write_event_file(path, meta, payload.body, is_new=True)

    event = kb.load_event_file(path)
    return JSONResponse({"ok": True, "event": event})


@router.get("/api/events/{event_id}")
async def api_events_get(event_id: str):
    """获取单个事件详情(含正文)。"""
    path = kb._find_event_file(event_id)
    if path is None:
        raise HTTPException(404, f"找不到事件:{event_id}")
    return JSONResponse(kb.load_event_file(path))


def _update_event_fields(event: dict, payload: EventUpdate) -> dict:
    """把非空更新值合并进 event dict,返回新 meta(供 write_event_file)。"""
    meta = {k: v for k, v in event.items() if k not in ("body", "path")}
    if payload.title.strip():
        meta["title"] = payload.title.strip()
    if payload.date:
        try:
            date.fromisoformat(payload.date)
        except ValueError:
            raise HTTPException(400, f"日期格式错误:{payload.date}")
        meta["date"] = payload.date
    if payload.category.strip() or payload.category == "":
        # 空串也允许(用户清空类别),但落盘时回退到"其他"
        meta["category"] = payload.category.strip() or "其他"
    if payload.note or payload.note == "":
        meta["note"] = payload.note.strip()
    if payload.status:
        if payload.status not in VALID_EVENT_STATUS:
            raise HTTPException(400, f"非法 status 值:{payload.status}")
        meta["status"] = payload.status
    if payload.related_source is not None:
        meta["related_source"] = payload.related_source.strip()
    # synced_calendar_ids 保持原样(用逗号串,不在此更新)
    meta["synced_calendar_ids"] = ",".join(event.get("synced_calendar_ids", []))
    return meta


@router.patch("/api/events/{event_id}")
async def api_events_update(event_id: str, payload: EventUpdate):
    """更新事件字段(原子改 frontmatter + 正文)。

    空串=更新为空(类别/备注/正文除外,见各字段判断);None=不改(仅 body/related_source)。
    """
    path = kb._find_event_file(event_id)
    if path is None:
        raise HTTPException(404, f"找不到事件:{event_id}")

    event = kb.load_event_file(path)
    meta = _update_event_fields(event, payload)
    body = event["body"] if payload.body is None else payload.body
    kb.write_event_file(path, meta, body, is_new=False)

    return JSONResponse({"ok": True, "event": kb.load_event_file(path)})


@router.delete("/api/events/{event_id}")
async def api_events_delete(event_id: str):
    """删除事件(只删 markdown 文件,不级联删已推送的日历项 —— 单向推送语义)。"""
    path = kb._find_event_file(event_id)
    if path is None:
        raise HTTPException(404, f"找不到事件:{event_id}")
    path.unlink()
    return JSONResponse({"ok": True, "deleted": event_id})


@router.post("/api/events/{event_id}/sync-calendar")
async def api_events_sync_calendar(event_id: str):
    """把事件单向推送到日历(创建一条 calendar item,回指 event_id)。

    幂等:已有存活日历项时不重复创建。
    """
    result = kb.sync_event_to_calendar(event_id)
    if result.get("reason") == "event_not_found":
        raise HTTPException(404, f"找不到事件:{event_id}")
    if result.get("reason") == "event_has_no_date":
        raise HTTPException(400, "事件没有日期,无法同步到日历")
    return JSONResponse(result)
