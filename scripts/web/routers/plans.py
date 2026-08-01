#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/plans.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:Plan suggestion 浏览与状态变更、详情页生成 plan:页面 + /api/plan* /api/plans* /generate-plans
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
    GeneratePlansRequest,
    TagsRequest,
)

import kb
import kb_llm
import kb_date

router = APIRouter()


def _parse_formal_plans() -> list[dict[str, Any]]:
    """已确定的 plan:扫描 04_Plans/plan_*.md 独立文件(v0.4.23 重构)。

    直接返回 kb.scan_plans() 结果(每条含 deadline/status 等 frontmatter 字段),
    按 deadline 升序。废弃了旧的 Weekly/Monthly/someday/completed 四桶解析。
    """
    return kb.scan_plans()

@router.get("/plans", response_class=HTMLResponse)
async def page_plans(request: Request):
    """plan list 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "plans.html", {"active_nav": "plans"}
    )

@router.get("/api/plans")
async def api_plans():
    """所有 plan suggestion 块。"""
    path = kb.VAULT_ROOT / "04_Plans" / "plan_suggestions.md"
    return JSONResponse({"items": _parse_suggestion_file(path, "Plan Suggestion")})

@router.get("/api/plans/confirmed")
async def api_plans_confirmed():
    """已确定的 plan:扫描 04_Plans/plan_*.md 独立文件(accept-plans 落盘)。"""
    return JSONResponse({"items": _parse_formal_plans()})

@router.post("/api/plan/{item_id}/status")
async def api_plan_status(item_id: str, payload: StatusUpdate):
    """修改 plan suggestion 的 status。

    若 new_status 为 accepted:事务化地改 status + 生成独立 plan 文件(含 deadline)。
    v0.4.5: 全程持文件锁(防 TOCTOU);搬运失败回滚 status。
    v0.4.23: 不再分 weekly/monthly/someday;接受时可选填 deadline,写进 plan 文件。
    """
    path = kb.VAULT_ROOT / "04_Plans" / "plan_suggestions.md"
    result = accept_and_move(
        kind="Plan Suggestion",
        item_id=item_id,
        new_status=payload.status,
        sug_path=path,
        valid_set=VALID_PLAN_STATUS,
        move_func=kb.move_accepted_plan,
        deadline=(payload.deadline or "").strip(),
    )
    return JSONResponse(result)

@router.post("/api/article/{source_id}/generate-plans")
async def api_generate_plans(source_id: str, payload: GeneratePlansRequest):
    """详情页「生成 Plan 列表」:基于当前 summary + 用户引导,抽取 plan 候选追加进 review 队列。

    生成的候选 status=pending_review,仍需在 /plans 页 accept + 跑 CLI accept-plans 进正式清单。
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
        plans = kb_llm.extract_plans_from_summary(body, hint or None)
    except Exception as e:
        raise HTTPException(500, f"LLM 失败:{e}")

    today = kb.today_iso()
    for it in plans:
        kb._append_section(
            kb.VAULT_ROOT / "04_Plans" / "plan_suggestions.md",
            kb._format_plan_suggestion(source_id, sources[source_id], it, today),
        )
    return JSONResponse(
        {"ok": True, "source_id": source_id, "kind": "plan", "generated": len(plans)}
    )
