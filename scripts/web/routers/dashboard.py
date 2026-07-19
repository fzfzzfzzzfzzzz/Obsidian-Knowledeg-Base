#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/dashboard.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:首页仪表盘:GET / + /api/dashboard* + /api/recent + /api/health
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


@router.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    """首页:summary 卡片仪表盘。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在,请检查安装", 500)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"active_nav": "index"},
    )

@router.get("/api/dashboard")
async def api_dashboard():
    """首页:未读/已读统计 + 稍后读列表。"""
    return JSONResponse(_build_dashboard())

@router.get("/api/dashboard_full")
async def api_dashboard_full():
    """首页:按 reading_status 分组的文章列表(未读/已读,只含有 summary 的)。"""
    cards = _summary_cards_only()
    unread = [c for c in cards if c["reading_status"] in ("to_read", "reading")]
    read = [c for c in cards if c["reading_status"] == "read"]
    unread.sort(key=lambda x: x.get("summarized_at") or "", reverse=True)
    read.sort(key=lambda x: x.get("last_read_at") or "", reverse=True)
    return JSONResponse({"unread": unread, "read": read})

@router.get("/api/recent")
async def api_recent():
    """最近阅读 30 篇(按 last_read_at 倒序)。"""
    return JSONResponse({"items": _build_recent()})

@router.get("/api/health")
async def api_health():
    """健康检查。"""
    return {"ok": True, "vault": str(kb.VAULT_ROOT)}
