#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/tags.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:文章标签 get/post/delete/ai: /api/article/{id}/tags*
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


@router.get("/api/article/{source_id}/tags")
async def api_get_tags(source_id: str):
    """获取文章 tags。"""
    return JSONResponse({"source_id": source_id, "tags": _get_article_tags(source_id)})

@router.post("/api/article/{source_id}/tags")
async def api_add_tags(source_id: str, payload: TagsRequest):
    """添加 tags(追加,去重)。"""
    final = _add_article_tags(source_id, payload.tags)
    return JSONResponse({"ok": True, "source_id": source_id, "tags": final})

@router.delete("/api/article/{source_id}/tags/{tag}")
async def api_remove_tag(source_id: str, tag: str):
    """删除单个 tag。"""
    final = _remove_article_tag(source_id, tag)
    return JSONResponse({"ok": True, "source_id": source_id, "tags": final})
