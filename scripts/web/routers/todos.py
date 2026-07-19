#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/todos.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:Todo suggestion 浏览与状态变更、详情页生成 todo:页面 + /api/todo* /api/todos* /generate-todos
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


def _parse_formal_todos() -> list[dict[str, Any]]:
    """扫描 04_Plans 下的正式 todo 文件,解析 - [ ] / - [x] 任务行及其缩进子项。

    覆盖:Weekly/*.md、Monthly/*.md、someday.md、completed_todos.md。
    每条返回 {title, done, plan, period, source, estimated_time, difficulty, note}。
    plan/period 从路径+文件名推断;文件不存在/为空返回 []。
    """
    plans_dir = kb.VAULT_ROOT / "04_Plans"
    if not plans_dir.exists():
        return []
    results: list[dict[str, Any]] = []

    def _parse_file(path: Path, plan: str, period: str) -> None:
        if not path.exists():
            return
        text = path.read_text(encoding=ENC)
        lines = text.splitlines()
        # 任务行:`- [ ] xxx` 或 `- [x] xxx`(允许 [ ] 内有空格)。子项是紧随其后、
        # 缩进比任务行更深的 `  - ` 行。遇到下一个同级或更浅的非空行就结束归属。
        i = 0
        while i < len(lines):
            line = lines[i]
            mtask = re.match(r"^(\s*)-\s*\[([ xX])\]\s*(.+?)\s*$", line)
            if not mtask:
                i += 1
                continue
            indent = len(mtask.group(1))
            done = mtask.group(2).lower() == "x"
            title = mtask.group(3).strip()
            # 跳过模板里 Review 段的占位任务(如 "Review pending summaries")
            # —— 这些是 weekly 模板预置的,不计为用户 todo?为兼容保留,前端可显示。
            # 确定性 id:基于 plan+period+title,重新解析后不变,供日历关联去重/回显
            _id_raw = f"{plan}|{period}|{title}"
            tid = "todo_" + hashlib.sha1(_id_raw.encode("utf-8")).hexdigest()[:10]
            item: dict[str, Any] = {
                "id": tid,
                "title": title, "done": done, "plan": plan, "period": period,
                "source": "", "estimated_time": "", "difficulty": "", "note": "",
            }
            # 收集缩进子项
            j = i + 1
            while j < len(lines):
                sub = lines[j]
                if sub.strip() == "":
                    j += 1
                    continue
                # 子项:缩进比任务行深
                msub = re.match(r"^(\s+)-\s*(.+?)\s*$", sub)
                if msub and len(msub.group(1)) > indent:
                    kv = msub.group(2).strip()
                    # 解析 `来源:xxx` / `预计时间:xxx` / `难度:xxx` / `难点:xxx`
                    mkv = re.match(r"^(来源|预计时间|难度|难点|备注)[:：]\s*(.*)$", kv)
                    if mkv:
                        key_map = {"来源": "source", "预计时间": "estimated_time",
                                   "难度": "difficulty", "难点": "note", "备注": "note"}
                        item[key_map[mkv.group(1)]] = mkv.group(2).strip()
                    else:
                        # 无标签的子项并入 note
                        item["note"] = (item["note"] + "\n" + kv).strip() if item["note"] else kv
                    j += 1
                else:
                    break
            results.append(item)
            i = j

    # Weekly:文件名形如 2026-W29.md
    weekly_dir = plans_dir / "Weekly"
    if weekly_dir.exists():
        for path in sorted(weekly_dir.glob("*.md")):
            period = path.stem  # 如 2026-W29
            _parse_file(path, "weekly", period)
    # Monthly:文件名形如 2026-07.md
    monthly_dir = plans_dir / "Monthly"
    if monthly_dir.exists():
        for path in sorted(monthly_dir.glob("*.md")):
            period = path.stem  # 如 2026-07
            _parse_file(path, "monthly", period)
    # someday
    _parse_file(plans_dir / "someday.md", "someday", "")
    # completed
    _parse_file(plans_dir / "completed_todos.md", "completed", "")
    return results

@router.get("/todos", response_class=HTMLResponse)
async def page_todos(request: Request):
    """todo list 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "todos.html", {"active_nav": "todos"}
    )

@router.get("/api/todos")
async def api_todos():
    """所有 todo suggestion 块。"""
    path = kb.VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    return JSONResponse({"items": _parse_suggestion_file(path, "Todo Suggestion")})

@router.get("/api/todos/confirmed")
async def api_todos_confirmed():
    """已确定的 todo:扫描 04_Plans/Weekly、Monthly、someday、completed(accept-todos 落盘)。"""
    return JSONResponse({"items": _parse_formal_todos()})

@router.post("/api/todo/{item_id}/status")
async def api_todo_status(item_id: str, payload: StatusUpdate):
    """修改 todo suggestion 的 status。

    若 new_status 以 accepted_ 开头:先把块 status 改成 accepted_*,然后自动搬到
    weekly/monthly/someday(调 kb.move_accepted_todo)。rejected 会直接删块,不搬。

    幂等:若该块已是 moved 状态,不再重复搬运。
    """
    path = kb.VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    pre_check = _check_suggestion_current_status(
        path, "Todo Suggestion", item_id
    )
    if pre_check == "moved" and payload.status.startswith("accepted_"):
        return JSONResponse({
            "ok": True, "id": item_id, "new_status": "moved",
            "deleted": False, "moved": False, "move_reason": "already_moved",
        })

    result = _update_suggestion_status(
        path, "Todo Suggestion", item_id, payload.status, VALID_TODO_STATUS
    )
    if payload.status.startswith("accepted_") and not result.get("deleted"):
        try:
            move_result = kb.move_accepted_todo(item_id)
            result["moved"] = move_result.get("moved", False)
            if move_result.get("moved"):
                result["moved_to"] = move_result.get("target")
                result["plan"] = move_result.get("plan")
            else:
                result["move_reason"] = move_result.get("reason")
        except Exception as e:
            result["moved"] = False
            result["move_error"] = str(e)
    return JSONResponse(result)

@router.post("/api/article/{source_id}/generate-todos")
async def api_generate_todos(source_id: str, payload: GenerateTodosRequest):
    """详情页「生成 Todo 列表」:基于当前 summary + 用户引导,抽取 todo 候选追加进 review 队列。

    生成的候选 status=pending_review,仍需在 /todos 页 accept + 跑 CLI accept-todos 进正式清单。
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
        todos = kb_llm.extract_todos_from_summary(body, hint or None)
    except Exception as e:
        raise HTTPException(500, f"LLM 失败:{e}")

    today = date.today().isoformat()
    for it in todos:
        kb._append_section(
            kb.VAULT_ROOT / "04_Plans" / "todo_suggestions.md",
            kb._format_todo_suggestion(source_id, sources[source_id], it, today),
        )
    return JSONResponse(
        {"ok": True, "source_id": source_id, "kind": "todo", "generated": len(todos)}
    )
