#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/ideas.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:Idea suggestion 浏览与状态变更、详情页生成 idea:页面 + /api/idea* /api/ideas* /generate-ideas
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


def _parse_formal_ideas() -> list[dict[str, Any]]:
    """扫描 03_Ideas/*_ideas.md(排除 review 队列和 archived),按 ## Idea: 切块。

    正式 idea 格式(_format_formal_idea 落盘):## Idea: <title> + - key: value + 正文。
    复用 kb._split_suggestion_blocks(text, "Idea")(标题前缀正好是 "Idea")。
    返回 [{id, title, status, area, fields, body}]。文件不存在/为空返回 []。
    """
    ideas_dir = kb.VAULT_ROOT / "03_Ideas"
    if not ideas_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(ideas_dir.glob("*_ideas.md")):
        # 排除 review 队列(idea_suggestions.md 不匹配 *_ideas.md,但保险起见)
        if path.name in ("idea_suggestions.md",):
            continue
        # area 从文件名推断:research_ideas.md → research
        area = path.stem.removesuffix("_ideas") or "other"
        if not path.exists():
            continue
        text = path.read_text(encoding=ENC)
        for raw, meta, body in kb._split_suggestion_blocks(text, "Idea"):
            results.append({
                "id": meta.get("id", ""),
                "title": meta.get("title", ""),
                "status": meta.get("status", "candidate"),
                "area": area,
                "maturity": meta.get("maturity", "spark"),
                "priority": meta.get("priority", "P2"),
                "fields": meta,
                "body": body,
            })
    return results

@router.get("/ideas", response_class=HTMLResponse)
async def page_ideas(request: Request):
    """idea list 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "ideas.html", {"active_nav": "ideas"}
    )

@router.get("/api/ideas")
async def api_ideas():
    """所有 idea suggestion 块。"""
    path = kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    return JSONResponse({"items": _parse_suggestion_file(path, "Idea Suggestion")})

@router.get("/api/ideas/confirmed")
async def api_ideas_confirmed():
    """已确定的 idea:扫描 03_Ideas/*_ideas.md 正式清单(accept-ideas 落盘)。"""
    return JSONResponse({"items": _parse_formal_ideas()})

@router.post("/api/idea/{item_id}/status")
async def api_idea_status(item_id: str, payload: StatusUpdate):
    """修改 idea suggestion 的 status。

    若 new_status 以 accepted_ 开头:先把块 status 改成 accepted_*,然后自动搬到
    正式 idea list(调 kb.move_accepted_idea,搬运时会把原块再标 moved)。
    rejected 会直接删块,不搬。

    幂等:若该块已是 moved 状态(说明之前搬过),不再重复搬运,直接返回。
    """
    path = kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    # 先检查当前状态:已是 moved 的话,接受请求是重复的,no-op
    pre_check = _check_suggestion_current_status(
        path, "Idea Suggestion", item_id
    )
    if pre_check == "moved" and payload.status.startswith("accepted_"):
        return JSONResponse({
            "ok": True, "id": item_id, "new_status": "moved",
            "deleted": False, "moved": False, "move_reason": "already_moved",
        })

    result = _update_suggestion_status(
        path, "Idea Suggestion", item_id, payload.status, VALID_IDEA_STATUS
    )
    # 接受即搬运:accepted_* 触发自动 move
    if payload.status.startswith("accepted_") and not result.get("deleted"):
        try:
            move_result = kb.move_accepted_idea(item_id)
            result["moved"] = move_result.get("moved", False)
            if move_result.get("moved"):
                result["moved_to"] = move_result.get("target")
                result["area"] = move_result.get("area")
            else:
                result["move_reason"] = move_result.get("reason")
        except Exception as e:
            # 搬运失败不阻断 status 更新,但要告知前端
            result["moved"] = False
            result["move_error"] = str(e)
    return JSONResponse(result)

@router.post("/api/article/{source_id}/generate-ideas")
async def api_generate_ideas(source_id: str, payload: GenerateIdeasRequest):
    """详情页「生成 Idea 列表」:基于当前 summary + 用户引导,抽取 idea 候选追加进 review 队列。

    生成的候选 status=pending_review,仍需在 /ideas 页 accept + 跑 CLI accept-ideas 进正式清单。
    允许重抽(不检查 action_status),因为用户带了明确引导意图。
    """
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")

    sp = sources[source_id].get("summary_path")
    if not sp:
        raise HTTPException(400, "该文章没有 summary,无法抽取")
    spath = kb.VAULT_ROOT / sp
    if not spath.exists():
        raise HTTPException(400, "summary 文件不存在,无法抽取")

    _, body = _parse_frontmatter(spath.read_text(encoding=ENC))
    hint = _build_hint(payload)
    try:
        ideas = kb_llm.extract_ideas_from_summary(body, hint or None)
    except Exception as e:
        raise HTTPException(500, f"LLM 失败:{e}")

    today = date.today().isoformat()
    for it in ideas:
        kb._append_section(
            kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
            kb._format_idea_suggestion(source_id, sources[source_id], it, today),
        )
    # 不改 action_status,避免影响批量入口的幂等判断
    return JSONResponse(
        {"ok": True, "source_id": source_id, "kind": "idea", "generated": len(ideas)}
    )
