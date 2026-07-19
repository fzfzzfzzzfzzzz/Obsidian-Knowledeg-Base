#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/ingest.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:投稿 / 图片投稿 / 批量 / 待生成 summary / 生成与重生成 summary:页面 /submit + /api/ingest* /api/batch*
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


def _generate_summary_for_source(source_id: str) -> dict[str, Any]:
    """对单个 source 生成 summary。复用 kb.py 的核心逻辑。

    返回 {ok, source_id, summary_path?, error?}
    """
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")
    rec = sources[source_id]
    source_note_path = kb.VAULT_ROOT / rec.get("path", "")
    if not source_note_path.exists():
        raise HTTPException(404, f"source note 不存在:{source_note_path}")

    # 读正文
    note_text = source_note_path.read_text(encoding=ENC)
    source_body = kb._extract_source_body(note_text)
    if not source_body.strip():
        return {"ok": False, "source_id": source_id, "error": "source 正文为空"}
    if "content_status: url_only" in source_body:
        return {"ok": False, "source_id": source_id, "error": "仅 URL 无正文(抓取失败)"}

    # 调 LLM 生成 summary
    try:
        summary_body = kb_llm.generate_summary(source_body, rec.get("source_type", "manual"))
    except Exception as e:
        return {"ok": False, "source_id": source_id, "error": f"LLM 失败:{e}"}

    # 检查 LLM 是否返回了空内容(思考模型可能 token 全用在思考上,没输出)
    if not summary_body or not summary_body.strip():
        return {"ok": False, "source_id": source_id, "error": "LLM 返回空内容(可能是思考模型超时或 token 不足,请重试)"}

    # 写 summary 文件(复用 kb.py 的 _write_summary)
    summary_path = kb._write_summary(source_id, rec, summary_body)
    # 回填 source note
    kb._backfill_source_note(source_note_path, source_id, summary_path, "summarized")
    # 更新 state
    rec["summary_path"] = summary_path.relative_to(kb.VAULT_ROOT).as_posix()
    rec.setdefault("action_status", "undecided")
    kb.save_state(state)

    return {
        "ok": True,
        "source_id": source_id,
        "summary_path": summary_path.relative_to(kb.VAULT_ROOT).as_posix(),
    }

@router.get("/submit", response_class=HTMLResponse)
async def page_submit(request: Request):
    """投稿页面:粘贴 URL 或文本,提交后自动 ingest。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "submit.html", {"active_nav": "submit"}
    )

@router.post("/api/ingest")
async def api_ingest(payload: IngestRequest):
    """投稿:把前端传来的多个文本片段写进 inbox,然后跑 ingest。

    auto_summary=True 时,ingest 后自动对新增 source 生成 summary。
    """
    texts = [t.strip() for t in payload.items if t and t.strip()]
    if not texts:
        raise HTTPException(400, "没有有效内容")

    # 增量追加到 inbox.md,绝不覆盖用户已在 inbox 中、尚未处理的内容
    # (对应 Hard Rule:Do not silently overwrite user-authored notes)
    kb.append_to_inbox(texts)

    import io
    import contextlib

    buf = io.StringIO()
    import argparse as _ap
    args = _ap.Namespace(no_llm=False)
    rc = 0
    with contextlib.redirect_stdout(buf):
        rc = kb.cmd_ingest(args)
    log = buf.getvalue()
    if rc != 0:
        raise HTTPException(500, f"ingest 失败:\n{log}")

    # 找本次新增的 source
    state = kb.load_state()
    today_str = date.today().isoformat()
    new_source_ids = [
        sid for sid, rec in state.get("sources", {}).items()
        if rec.get("ingested_at") == today_str and not rec.get("summary_path")
    ]
    new_sources = [
        {"source_id": sid, "title": state["sources"][sid].get("source_title", sid),
         "source_type": state["sources"][sid].get("source_type", "?")}
        for sid in new_source_ids
    ]

    # 可选:自动生成 summary
    summary_results = []
    if payload.auto_summary and new_source_ids:
        for sid in new_source_ids:
            r = _generate_summary_for_source(sid)
            summary_results.append(r)

    # 从 cmd_ingest 的输出里解析统计(供批量投稿前端显示「成功 N / 跳过 M」)
    # 输出格式见 kb.py 末尾:[ingest] 新建 source note: N / 跳过(内容重复): M / 失败(保留在 inbox): K
    def _parse_ingest_count(pattern: str, default: int = 0) -> int:
        m = re.search(pattern, log)
        return int(m.group(1)) if m else default

    new_count = _parse_ingest_count(r"\[ingest\] 新建 source note:\s*(\d+)")
    skipped_count = _parse_ingest_count(r"\[ingest\] 跳过\(内容重复\):\s*(\d+)")
    failed_count = _parse_ingest_count(r"\[ingest\] 失败\(保留在 inbox\):\s*(\d+)")

    return JSONResponse(
        {
            "ok": True,
            "submitted": len(texts),
            "log": log,
            "new_sources": new_sources,
            "summary_results": summary_results,
            "new_count": new_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        }
    )

@router.post("/api/ingest-image")
async def api_ingest_image(
    file: UploadFile = File(...),
    auto_summary: bool = Form(True),
):
    """上传图片 → OCR 提取文字 → 走 ingest 流程。

    图片存到 .kb/raw_text/,调 GLM-4V-Flash OCR,然后文字走现有 ingest。
    """
    # 校验文件类型
    allowed_types = {"image/jpeg", "image/png", "image/jpg"}
    content_type = file.content_type or ""
    if content_type not in allowed_types:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            raise HTTPException(400, f"不支持的文件类型:{content_type}。只支持 jpg/png。")
        content_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

    # 读图片
    image_bytes = await file.read()
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(400, "图片不能超过 5MB")
    if not image_bytes:
        raise HTTPException(400, "图片为空")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_mime = content_type
    ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"

    # OCR 提取文字
    try:
        ocr_text = kb_llm.ocr_image(image_b64, image_mime)
    except Exception as e:
        raise HTTPException(500, f"OCR 失败:{e}")

    if not ocr_text.strip() or "未检测到文字" in ocr_text:
        raise HTTPException(400, "图片中未检测到文字内容")

    # 用 OCR 文字走 ingest(写入 inbox → cmd_ingest)
    inbox_path = kb.VAULT_ROOT / "00_Inbox" / "inbox.md"
    header = "# Inbox\n\n> web image submit\n\n"
    inbox_path.write_text(header + ocr_text + "\n", encoding=ENC)

    import io
    import contextlib
    import argparse as _ap

    buf = io.StringIO()
    args = _ap.Namespace(no_llm=False)
    with contextlib.redirect_stdout(buf):
        rc = kb.cmd_ingest(args)
    log = buf.getvalue()
    if rc != 0:
        raise HTTPException(500, f"ingest 失败:\n{log}")

    # 找新增的 source
    state = kb.load_state()
    today_str = date.today().isoformat()
    new_source_ids = [
        sid for sid, rec in state.get("sources", {}).items()
        if rec.get("ingested_at") == today_str and not rec.get("summary_path")
    ]
    new_sources = [
        {"source_id": sid, "title": state["sources"][sid].get("source_title", sid),
         "source_type": state["sources"][sid].get("source_type", "?")}
        for sid in new_source_ids
    ]

    # 把图片保存到 raw_text(覆盖 ingest 生成的 txt)
    for sid in new_source_ids:
        img_path = kb.RAW_TEXT_DIR / f"{sid}{ext}"
        img_path.write_bytes(image_bytes)
        # 更新 state 记录标记来源为 ocr
        state["sources"][sid]["metadata_source"] = "ocr"
    kb.save_state(state)

    # 可选:自动生成 summary
    summary_results = []
    if auto_summary and new_source_ids:
        for sid in new_source_ids:
            r = _generate_summary_for_source(sid)
            summary_results.append(r)

    return JSONResponse({
        "ok": True,
        "ocr_text": ocr_text[:500],
        "log": log,
        "new_sources": new_sources,
        "summary_results": summary_results,
    })

@router.get("/api/pending-summaries")
async def api_pending_summaries():
    """返回还没生成 summary 的 source 列表。"""
    return JSONResponse({"items": _build_pending_summaries()})

@router.post("/api/generate-summary/{source_id}")
async def api_generate_summary(source_id: str):
    """对单个 source 生成 summary。"""
    return JSONResponse(_generate_summary_for_source(source_id))

@router.post("/api/article/{source_id}/regenerate-summary")
async def api_regenerate_summary(source_id: str):
    """重新生成 summary(覆盖已有)。先备份旧 summary 到 .kb/logs/web_backups/。"""
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 备份旧 summary(如果存在)
    old_sp = sources[source_id].get("summary_path")
    if old_sp:
        old_path = kb.VAULT_ROOT / old_sp
        if old_path.exists():
            backup_dir = kb.VAULT_ROOT / ".kb" / "logs" / "web_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%H%M%S")
            backup_name = f"{old_path.stem}_regen_{ts}.md"
            shutil.copy2(old_path, backup_dir / backup_name)
            # 删除旧 summary,清除 summary_path,让 _generate_summary_for_source 重新生成
            old_path.unlink()
            sources[source_id].pop("summary_path", None)
            sources[source_id].pop("action_status", None)
            kb.save_state(state)

    return JSONResponse(_generate_summary_for_source(source_id))

@router.post("/api/batch")
async def api_batch(payload: BatchRequest):
    """批量操作。单条失败不影响其他,返回成功/失败/跳过数量 + 失败项。"""
    if not payload.source_ids:
        raise HTTPException(400, "source_ids 不能为空")
    if payload.action not in VALID_BATCH_ACTIONS:
        raise HTTPException(400, f"非法 action:{payload.action}")

    # 删除操作先备份
    if payload.action == "delete":
        backup_dir = kb.VAULT_ROOT / ".kb" / "logs" / "web_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"state_{date.today().isoformat()}.json.bak"
        if kb.STATE_FILE.exists():
            shutil.copy2(kb.STATE_FILE, backup)

    state = kb.load_state()
    sources = state.get("sources", {})
    results = {"success": 0, "failed": 0, "skipped": 0, "failed_items": []}

    for sid in payload.source_ids:
        if sid not in sources:
            results["failed"] += 1
            results["failed_items"].append({"source_id": sid, "error": "source 不存在"})
            continue

        try:
            if payload.action == "archive":
                sources[sid]["reading_status"] = "archived"
                results["success"] += 1
            elif payload.action == "delete":
                r = _delete_one(sid, state)
                if r["ok"]:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["failed_items"].append({"source_id": sid, "error": r.get("error", "")})
            elif payload.action == "favorite":
                sources[sid]["is_favorite"] = True
                results["success"] += 1
            elif payload.action == "unfavorite":
                sources[sid]["is_favorite"] = False
                results["success"] += 1
            elif payload.action == "add_tags":
                if not sources[sid].get("summary_path"):
                    results["skipped"] += 1
                    continue
                _add_article_tags(sid, payload.tags)
                results["success"] += 1
            elif payload.action == "generate_summary":
                if sources[sid].get("summary_path"):
                    results["skipped"] += 1
                    continue
                r = _generate_summary_for_source(sid)
                if r.get("ok"):
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["failed_items"].append({"source_id": sid, "error": r.get("error", "")})
            elif payload.action == "extract_suggestions":
                if not sources[sid].get("summary_path"):
                    results["skipped"] += 1
                    continue
                if sources[sid].get("action_status") == "todo_suggested":
                    results["skipped"] += 1
                    continue
                # 调抽取逻辑
                sp = sources[sid]["summary_path"]
                spath = kb.VAULT_ROOT / sp
                if not spath.exists():
                    results["skipped"] += 1
                    continue
                _, body = _parse_frontmatter(spath.read_text(encoding=ENC))
                ideas = kb_llm.extract_ideas_from_summary(body)
                todos = kb_llm.extract_todos_from_summary(body)
                today = date.today().isoformat()
                for it in ideas:
                    kb._append_section(
                        kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
                        kb._format_idea_suggestion(sid, sources[sid], it, today),
                    )
                for it in todos:
                    kb._append_section(
                        kb.VAULT_ROOT / "04_Plans" / "todo_suggestions.md",
                        kb._format_todo_suggestion(sid, sources[sid], it, today),
                    )
                sources[sid]["action_status"] = "todo_suggested"
                results["success"] += 1
        except Exception as e:
            results["failed"] += 1
            results["failed_items"].append({"source_id": sid, "error": str(e)})

    # 统一保存(add_tags/generate_summary/extract_suggestions 内部可能已 save,再 save 一次保证一致)
    kb.save_state(state)
    return JSONResponse(results)
