#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/collections.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:收藏夹文件夹 CRUD + 收藏页:页面 /favorites + /api/favorites /api/collections*
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
    VALID_PLAN_STATUS,
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
    CollectionArticlesRequest,
    BatchRequest,
    GenerateIdeasRequest,
    GeneratePlansRequest,
    TagsRequest,
)

import kb
import kb_llm
import kb_date

router = APIRouter()


@router.get("/favorites", response_class=HTMLResponse)
async def page_favorites(request: Request):
    """收藏夹页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "favorites.html", {"active_nav": "favorites"}
    )

@router.get("/api/favorites")
async def api_favorites():
    """收藏夹列表。"""
    return JSONResponse({"items": _build_favorites()})

@router.get("/api/collections")
async def api_collections_list():
    """所有收藏夹文件夹(+ 每个的文章数)。含一次性默认夹迁移。"""
    return JSONResponse({"items": _build_collections_list()})

@router.post("/api/collections")
async def api_collections_create(payload: CollectionNameRequest):
    """新建收藏夹文件夹。"""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "文件夹名称不能为空")
    if len(name) > 40:
        raise HTTPException(400, "文件夹名称过长(最多 40 字)")
    try:
        with kb.state_lock():
            state = kb.load_state()
            kb._check_corrupt(state, "state")
            _migrate_default_collection(state)
            cols = state.setdefault("collections", {})
            # 同名也允许(用户责任),但 id 唯一
            import uuid
            col_id = "col_" + uuid.uuid4().hex[:10]
            cols[col_id] = {
                "id": col_id,
                "name": name,
                "created_at": kb.today_iso(),
                "source_ids": [],
            }
            kb.save_state(state)
    except kb.CorruptStoreError:
        raise HTTPException(503, "state.json 损坏,请先运行 kb.py rebuild-index")
    except TimeoutError:
        raise HTTPException(503, "操作并发,请稍后重试")
    return JSONResponse({"ok": True, "item": cols[col_id]})

@router.patch("/api/collections/{col_id}")
async def api_collections_rename(col_id: str, payload: CollectionNameRequest):
    """重命名收藏夹文件夹。"""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "文件夹名称不能为空")
    try:
        with kb.state_lock():
            state = kb.load_state()
            kb._check_corrupt(state, "state")
            cols = _get_collections(state)
            if col_id not in cols:
                raise HTTPException(404, f"找不到文件夹:{col_id}")
            cols[col_id]["name"] = name
            kb.save_state(state)
    except kb.CorruptStoreError:
        raise HTTPException(503, "state.json 损坏,请先运行 kb.py rebuild-index")
    except TimeoutError:
        raise HTTPException(503, "操作并发,请稍后重试")
    return JSONResponse({"ok": True, "item": cols[col_id]})

@router.delete("/api/collections/{col_id}")
async def api_collections_delete(col_id: str):
    """删除收藏夹文件夹(文章不删,只解除关联)。"""
    try:
        with kb.state_lock():
            state = kb.load_state()
            kb._check_corrupt(state, "state")
            cols = _get_collections(state)
            if col_id not in cols:
                raise HTTPException(404, f"找不到文件夹:{col_id}")
            # 清理所有 source 的 collection_ids 里对该夹的引用
            for rec in state.get("sources", {}).values():
                cids = rec.get("collection_ids", [])
                if col_id in cids:
                    rec["collection_ids"] = [c for c in cids if c != col_id]
            del cols[col_id]
            kb.save_state(state)
    except kb.CorruptStoreError:
        raise HTTPException(503, "state.json 损坏,请先运行 kb.py rebuild-index")
    except TimeoutError:
        raise HTTPException(503, "操作并发,请稍后重试")
    return JSONResponse({"ok": True, "id": col_id})

@router.get("/api/collections/{col_id}/articles")
async def api_collection_articles(col_id: str):
    """某收藏夹内的文章卡片。"""
    if col_id == "all":
        # 「全部收藏」= 所有 is_favorite=true
        return JSONResponse({"items": _build_favorites()})
    return JSONResponse({"items": _build_collection_articles(col_id)})


@router.post("/api/collections/{col_id}/articles")
async def api_collection_add_articles(col_id: str, payload: CollectionArticlesRequest):
    """把文章批量**追加**到收藏夹(多归属:不移出其他夹,已在的跳过)。

    供收藏夹页的拖拽(单篇)和批量归入(多篇)共用——单篇即 source_ids 长度为 1。
    双向同步 cols[col_id].source_ids 与 sources[sid].collection_ids(见 AGENTS.md 双写约束)。
    """
    if col_id == "all":
        raise HTTPException(400, "「全部收藏」是虚拟视图,不能作为归入目标")
    source_ids = [s for s in (payload.source_ids or []) if s]
    if not source_ids:
        raise HTTPException(400, "source_ids 不能为空")
    try:
        with kb.state_lock():
            state = kb.load_state()
            kb._check_corrupt(state, "state")
            cols = _get_collections(state)
            if col_id not in cols:
                raise HTTPException(404, f"找不到文件夹:{col_id}")
            sources = state.get("sources", {})
            col_sids = cols[col_id].setdefault("source_ids", [])
            added = 0
            for sid in source_ids:
                if sid not in sources:
                    continue  # 不存在的 source 静默跳过(拖拽可能拿到已删文章)
                rec = sources[sid]
                cids = rec.setdefault("collection_ids", [])
                # 正向:加入夹的 source_ids
                if sid not in col_sids:
                    col_sids.append(sid)
                    added += 1
                # 反向:文章的 collection_ids 回指(幂等,不重复)
                if col_id not in cids:
                    cids.append(col_id)
            kb.save_state(state)
    except kb.CorruptStoreError:
        raise HTTPException(503, "state.json 损坏,请先运行 kb.py rebuild-index")
    except TimeoutError:
        raise HTTPException(503, "操作并发,请稍后重试")
    return JSONResponse({"ok": True, "col_id": col_id, "added": added, "count": len(col_sids)})
