#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/calendar.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:日历事项 CRUD + 文章日期检测:页面 + /api/calendar* /detect-dates
"""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

from web.utils import (
    ENC,
    templates,
    TEMPLATES_DIR,
    STATIC_DIR,
    BASE_DIR,
    VALID_IDEA_STATUS,
    VALID_TODO_STATUS,
    READING_FIELDS,
    VALID_READING_STATUS,
    VALID_BATCH_ACTIONS,
    _build_hint,
)
from web.services.parsing import _parse_frontmatter, _parse_suggestion_file
from web.services.cards import (
    _summary_card_from_source,
    _all_cards,
    _summary_cards_only,
    _build_dashboard,
    _build_recent,
    _build_favorites,
    _build_pending_summaries,
    _build_all_articles,
    _build_searchable_articles,
    _do_search,
    _build_collections_list,
    _build_collection_articles,
    _migrate_default_collection,
    _get_collections,
    _scan_summaries,
    _read_summary_detail,
)
from web.services.state_io import (
    _ensure_reading_fields,
    _get_article_tags,
    _set_article_tags,
    _add_article_tags,
    _remove_article_tag,
    _save_reading_state,
    _read_summary_frontmatter_tags,
    _write_summary_frontmatter_tags,
    _mark_read,
    _delete_one,
)
from web.services.status import _check_suggestion_current_status, _update_suggestion_status
from web.models import (
    StatusUpdate,
    IngestRequest,
    CalendarItemCreate,
    CalendarItemUpdate,
    CollectionNameRequest,
    ArticleCollectionsRequest,
    BatchRequest,
    GenerateIdeasRequest,
    GenerateTodosRequest,
    TagsRequest,
)

import kb
import kb_llm
import kb_date

router = APIRouter()


@router.get("/calendar", response_class=HTMLResponse)
async def page_calendar(request: Request):
    """日历页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "calendar.html", {"active_nav": "calendar"}
    )

@router.get("/api/article/{source_id}/detected-dates")
async def api_detected_dates(source_id: str):
    """获取文章的候选日期(识别正文中的日期)。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 优先用缓存的 detected_dates,没有就实时识别
    cached = rec.get("detected_dates")
    if cached:
        ranked = kb_date.rank_dates(cached)
    else:
        # 读正文(source note 或 summary)
        text = ""
        sn_path = kb.VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
        if sn_path and sn_path.exists():
            note = sn_path.read_text(encoding=ENC)
            text = kb._extract_source_body(note)
        if not text.strip() and rec.get("summary_path"):
            sp = kb.VAULT_ROOT / rec["summary_path"]
            if sp.exists():
                _, text = _parse_frontmatter(sp.read_text(encoding=ENC))

        if text.strip():
            detected = kb_date.detect_dates(text)
            ranked = kb_date.rank_dates(detected)
            # 缓存到 state
            rec["detected_dates"] = detected
            kb.save_state(state)
        else:
            ranked = []

    # 推荐日期(第一个未来日期)
    recommended = None
    for d in ranked:
        if d.get("is_future"):
            recommended = d
            break

    return JSONResponse({
        "recommended": recommended,
        "candidates": ranked,
    })

@router.post("/api/article/{source_id}/detect-dates")
async def api_redetect_dates(source_id: str):
    """手动重新识别日期(清除缓存重新扫描)。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 读正文
    text = ""
    sn_path = kb.VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
    if sn_path and sn_path.exists():
        note = sn_path.read_text(encoding=ENC)
        text = kb._extract_source_body(note)
    if not text.strip() and rec.get("summary_path"):
        sp = kb.VAULT_ROOT / rec["summary_path"]
        if sp.exists():
            _, text = _parse_frontmatter(sp.read_text(encoding=ENC))

    detected = kb_date.detect_dates(text) if text.strip() else []
    rec["detected_dates"] = detected
    kb.save_state(state)

    ranked = kb_date.rank_dates(detected)
    recommended = next((d for d in ranked if d.get("is_future")), None)
    return JSONResponse({"recommended": recommended, "candidates": ranked, "count": len(detected)})

def _resolve_category(item: dict) -> str:
    """v0.4.2: 推导事项的 category。
    - 已有非空 category 原样返回
    - 否则按 source_type 回填:todo → todolist,其余 → 其他
    - 仅运行时计算,不写盘(避免改动旧用户数据)。
    """
    if item.get("category"):
        return item["category"]
    return "todolist" if item.get("source_type") == "todo" else "其他"

@router.get("/api/calendar")
async def api_calendar_list(start: str = "", end: str = ""):
    """获取日历事项(可按日期范围筛选)。category 字段运行时回填。"""
    cal = kb.load_calendar()
    items = list(cal.get("items", {}).values())
    # v0.4.2: 运行时回填 category,供前端筛选/着色使用(不写盘)
    for it in items:
        it["category"] = _resolve_category(it)
    if start:
        items = [i for i in items if i.get("date", "") >= start]
    if end:
        items = [i for i in items if i.get("date", "") <= end]
    items.sort(key=lambda x: x.get("date", ""))
    return JSONResponse({"items": items, "count": len(items)})

@router.get("/api/calendar/{item_id}")
async def api_calendar_get(item_id: str):
    """获取单个日历事项。category 字段运行时回填。"""
    cal = kb.load_calendar()
    item = cal.get("items", {}).get(item_id)
    if not item:
        raise HTTPException(404, f"找不到日历事项:{item_id}")
    item = dict(item)
    item["category"] = _resolve_category(item)  # v0.4.2: 运行时回填
    return JSONResponse(item)

@router.post("/api/calendar")
async def api_calendar_create(payload: CalendarItemCreate):
    """创建日历事项。"""
    if not payload.title.strip():
        raise HTTPException(400, "事项名称不能为空")
    # 校验日期格式
    try:
        date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(400, f"日期格式错误:{payload.date}(需 YYYY-MM-DD)")

    import uuid
    item_id = f"cal_{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat(timespec="seconds")

    # 检查是否已有同 source_id 的事项(防重复,PRD 11.9)
    cal = kb.load_calendar()
    if payload.source_id:
        for existing in cal.get("items", {}).values():
            if existing.get("source_id") == payload.source_id:
                # 返回已有事项(PRD: 不创建重复)
                return JSONResponse({"ok": True, "item": existing, "already_existed": True})

    item = {
        "id": item_id,
        "title": payload.title.strip(),
        "date": payload.date,
        "note": payload.note,
        "source_id": payload.source_id,
        "source_type": payload.source_type,
        "source_title": payload.source_title,
        "detected_date_id": payload.detected_date_id,
        "date_source": payload.date_source,
        "date_confidence": payload.date_confidence,
        "category": payload.category,  # v0.4.2: 事件类别(空串=不指定,落库留空)
        "created_at": now,
        "updated_at": now,
    }
    cal["items"][item_id] = item
    kb.save_calendar(cal)
    # 响应里回填 category,供前端直接渲染
    resp_item = dict(item)
    resp_item["category"] = _resolve_category(item)
    return JSONResponse({"ok": True, "item": resp_item})

@router.patch("/api/calendar/{item_id}")
async def api_calendar_update(item_id: str, payload: CalendarItemUpdate):
    """更新日历事项。"""
    cal = kb.load_calendar()
    item = cal.get("items", {}).get(item_id)
    if not item:
        raise HTTPException(404, f"找不到日历事项:{item_id}")

    if payload.title:
        item["title"] = payload.title.strip()
    if payload.date:
        try:
            date.fromisoformat(payload.date)
        except ValueError:
            raise HTTPException(400, f"日期格式错误:{payload.date}")
        item["date"] = payload.date
    if payload.note is not None:
        item["note"] = payload.note
    # 移除/更新关联(P1-2 修复:source_id 不为 None 时更新)
    if payload.source_id is not None:
        item["source_id"] = payload.source_id
        if not payload.source_id:
            # 移除关联:同时清空 source_type/source_title
            item["source_type"] = ""
            item["source_title"] = ""
    # v0.4.2: 更新事件类别(None=不改,其余含空串=更新)
    if payload.category is not None:
        item["category"] = payload.category
    item["updated_at"] = datetime.now().isoformat(timespec="seconds")

    cal["items"][item_id] = item
    kb.save_calendar(cal)
    resp_item = dict(item)
    resp_item["category"] = _resolve_category(item)
    return JSONResponse({"ok": True, "item": resp_item})

@router.delete("/api/calendar/{item_id}")
async def api_calendar_delete(item_id: str):
    """删除日历事项。"""
    cal = kb.load_calendar()
    if item_id not in cal.get("items", {}):
        raise HTTPException(404, f"找不到日历事项:{item_id}")
    del cal["items"][item_id]
    kb.save_calendar(cal)
    return JSONResponse({"ok": True, "deleted": item_id})
