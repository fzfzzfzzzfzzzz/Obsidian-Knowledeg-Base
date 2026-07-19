#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/articles.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:文章详情/列表/阅读状态/收藏夹归属/标签/summary 删除:页面 + /api/summary* /api/article*
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
    backup_file,
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


@router.get("/summary/{source_id}", response_class=HTMLResponse)
async def page_summary(request: Request, source_id: str):
    """单篇 summary 详情页。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request,
        "summary.html",
        {"source_id": source_id, "active_nav": "index"},
    )

@router.get("/recent", response_class=HTMLResponse)
async def page_recent(request: Request):
    """最近阅读页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "recent.html", {"active_nav": "recent"}
    )

@router.get("/articles", response_class=HTMLResponse)
async def page_articles(request: Request):
    """All Articles 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "articles.html", {"active_nav": "articles"}
    )

@router.get("/api/summaries")
async def api_summaries():
    """所有 summary 卡片元数据。"""
    return JSONResponse({"items": _scan_summaries()})

@router.get("/api/summary/{source_id}")
async def api_summary_detail(source_id: str):
    """单篇 summary 详情(含 markdown 转 HTML)。打开即记阅读。"""
    _mark_read(source_id)  # 自动追踪阅读:last_read_at + read_count
    return JSONResponse(_read_summary_detail(source_id))

@router.delete("/api/article/{source_id}/summary")
async def api_delete_summary(source_id: str):
    """删除文章的 summary(不删 source)。备份旧 summary + 清除 state 的 summary_path。

    删除后文章回到"无 summary"状态,可让别的 Agent 重新生成。
    """
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")

    old_sp = sources[source_id].get("summary_path")
    if not old_sp:
        raise HTTPException(400, "该文章没有 summary")

    old_path = kb.VAULT_ROOT / old_sp
    # 备份
    if old_path.exists():
        backup_dir = kb.VAULT_ROOT / ".kb" / "logs" / "web_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        backup_name = f"{old_path.stem}_delsum_{ts}.md"
        shutil.copy2(old_path, backup_dir / backup_name)
        old_path.unlink()

    # 清除 state
    sources[source_id].pop("summary_path", None)
    sources[source_id].pop("action_status", None)
    kb.save_state(state)

    # 回填 source note 的 status(改回 source_created)
    sn_path = kb.VAULT_ROOT / sources[source_id].get("path", "") if sources[source_id].get("path") else None
    if sn_path and sn_path.exists():
        text = sn_path.read_text(encoding=ENC)
        text = re.sub(r"^status:.*", "status: source_created", text, flags=re.MULTILINE)
        text = re.sub(r"summary_location:.*", "summary_location:", text)
        sn_path.write_text(text, encoding=ENC)

    return JSONResponse({"ok": True, "source_id": source_id, "deleted_summary": old_sp})

@router.post("/api/article/{source_id}/collections")
async def api_article_set_collections(source_id: str, payload: ArticleCollectionsRequest):
    """设置某文章的文件夹归属(全量替换 collection_ids)。同步更新各夹的 source_ids。"""
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")
    cols = _get_collections(state)
    new_ids = [c for c in payload.collection_ids if c in cols]
    rec = sources[source_id]
    old_ids = set(rec.get("collection_ids", []))
    new_set = set(new_ids)
    # 加进新夹
    for cid in new_set - old_ids:
        sids = cols[cid].setdefault("source_ids", [])
        if source_id not in sids:
            sids.append(source_id)
    # 从旧夹移除
    for cid in old_ids - new_set:
        if cid in cols:
            cols[cid]["source_ids"] = [
                s for s in cols[cid].get("source_ids", []) if s != source_id
            ]
    rec["collection_ids"] = new_ids
    kb.save_state(state)
    return JSONResponse({"ok": True, "source_id": source_id, "collection_ids": new_ids})

@router.post("/api/article/{source_id}/read-later")
async def api_toggle_read_later(source_id: str):
    """切换稍后阅读标记。"""
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")
    rec = _ensure_reading_fields(sources[source_id])
    new_val = not rec["read_later"]
    updated = _save_reading_state(source_id, read_later=new_val)
    return JSONResponse(
        {"ok": True, "source_id": source_id, "read_later": updated["read_later"]}
    )

@router.post("/api/article/{source_id}/favorite")
async def api_toggle_favorite(source_id: str):
    """切换收藏标记。"""
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")
    rec = _ensure_reading_fields(sources[source_id])
    new_val = not rec["is_favorite"]
    updated = _save_reading_state(source_id, is_favorite=new_val)
    return JSONResponse(
        {"ok": True, "source_id": source_id, "is_favorite": updated["is_favorite"]}
    )

@router.delete("/api/article/{source_id}")
async def api_delete_article(source_id: str):
    """彻底删除一篇文章:source note + summary + raw_text + state 记录 + 关联候选。

    删除前备份 state.json。物理文件直接删除(不可恢复)。
    """
    # 备份(命名带时分秒)
    backup_file(kb.STATE_FILE, "state")

    state = kb.load_state()
    if source_id not in state.get("sources", {}):
        raise HTTPException(404, f"找不到 source:{source_id}")
    result = _delete_one(source_id, state)
    kb.save_state(state)
    if not result["ok"]:
        raise HTTPException(500, result.get("error", "删除失败"))
    return JSONResponse(result)

@router.get("/api/articles")
async def api_articles():
    """所有文章(含无 summary 的)。"""
    return JSONResponse({"items": _build_all_articles()})

@router.post("/api/article/{source_id}/ai-tags")
async def api_ai_tags(source_id: str):
    """AI 推荐标签:基于 summary 生成 3-5 个 tags 并写入。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        raise HTTPException(404, f"找不到 source:{source_id}")
    sp = rec.get("summary_path")
    if not sp:
        raise HTTPException(400, "该文章没有 summary,无法推荐标签")
    spath = kb.VAULT_ROOT / sp
    if not spath.exists():
        raise HTTPException(404, f"summary 文件不存在:{sp}")
    _, body = _parse_frontmatter(spath.read_text(encoding=ENC))
    try:
        new_tags = kb_llm.recommend_tags_from_summary(body)
    except Exception as e:
        raise HTTPException(500, f"AI 推荐失败:{e}")
    final = _add_article_tags(source_id, new_tags)
    return JSONResponse({"ok": True, "source_id": source_id, "tags": final, "new_tags": new_tags})
