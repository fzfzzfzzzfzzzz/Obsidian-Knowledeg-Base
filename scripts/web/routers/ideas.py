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
from web.services.status import _check_suggestion_current_status, _update_suggestion_status, accept_and_move
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
    IdeaCreate,
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

@router.post("/api/ideas")
async def api_ideas_create(payload: IdeaCreate):
    """用户手动新建 idea,追加到 idea_suggestions.md 待定队列。

    与 LLM 抽取的 idea 走同一条 review 队列:只含 title + status:pending_review,
    其他字段留空(用户可在接受后于正式清单补充)。复用现有 accept 流程。
    """
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    import secrets
    slug = kb.make_slug(title) or "untitled"
    suffix = secrets.token_hex(4)
    today = kb.today_iso().replace("-", "")
    iid = f"idea_suggestion_{today}_{slug}_{suffix}"
    # 精简块:不依赖 _format_idea_suggestion(那个需要 LLM 完整字段)
    block = (
        f"\n## Idea Suggestion: {title}\n\n"
        f"- id: {iid}\n"
        f"- status: pending_review\n"
        f"- recommended_area: \n"
        f"- source_summary: \n"
        f"- priority: \n"
        f"- feasibility: \n"
        f"- novelty: \n"
        f"- estimated_investment: \n\n"
    )
    sug_path = kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    if not sug_path.exists():
        # 确保队列文件存在
        sug_path.parent.mkdir(parents=True, exist_ok=True)
        sug_path.write_text("# Idea Suggestions\n\n", encoding="utf-8")
    kb._append_section(sug_path, block)
    return JSONResponse({"ok": True, "id": iid, "title": title})

@router.get("/api/ideas/confirmed")
async def api_ideas_confirmed():
    """已确定的 idea:扫描 03_Ideas/*_ideas.md 正式清单(accept-ideas 落盘)。"""
    return JSONResponse({"items": _parse_formal_ideas()})

@router.post("/api/idea/{item_id}/status")
async def api_idea_status(item_id: str, payload: StatusUpdate):
    """修改 idea suggestion 的 status。

    若 new_status 以 accepted_ 开头:事务化地改 status + 搬到正式 idea list。
    v0.4.5: 全程持文件锁(防 TOCTOU 并发重复搬运);搬运失败时回滚 status
    (防卡在 accepted_* 状态)。
    """
    path = kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    result = accept_and_move(
        kind="Idea Suggestion",
        item_id=item_id,
        new_status=payload.status,
        sug_path=path,
        valid_set=VALID_IDEA_STATUS,
        move_func=kb.move_accepted_idea,
    )
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

    today = kb.today_iso()
    for it in ideas:
        kb._append_section(
            kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
            kb._format_idea_suggestion(source_id, sources[source_id], it, today),
        )
    # 不改 action_status,避免影响批量入口的幂等判断
    return JSONResponse(
        {"ok": True, "source_id": source_id, "kind": "idea", "generated": len(ideas)}
    )
