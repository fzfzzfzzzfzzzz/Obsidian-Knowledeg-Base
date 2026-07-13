#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kb_web.py —— 知识库阅读前端(FastAPI)

提供卡片仪表盘式 UI,展示 summary / idea / todo,支持在前端直接改 status。

启动:python scripts/kb.py serve
路由:
    页面: /  /summary/{id}  /ideas  /todos
    API:  /api/summaries  /api/summary/{id}  /api/ideas  /api/todos
          /api/idea/{id}/status  /api/todo/{id}/status  (POST)
"""

from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import kb  # 复用 kb.py 的工具函数
import kb_llm  # 用于生成 summary(generate_summary)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

VAULT_ROOT = kb.VAULT_ROOT
ENC = "utf-8"

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

app = FastAPI(title="Obsidian KB Reader")

if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.autoescape = False  # markdown HTML 不转义
else:
    templates = None

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# status 合法值白名单(防注入)
VALID_IDEA_STATUS = {
    "pending_review",
    "accepted_research",
    "accepted_productivity",
    "rejected",
    "archived",
    "moved",
}
VALID_TODO_STATUS = {
    "pending_review",
    "accepted_weekly",
    "accepted_monthly",
    "accepted_someday",
    "rejected",
    "archived",
    "moved",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 markdown frontmatter,返回 (metadata_dict, body)。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([\w_]+)\s*:\s*(.*)$", line.strip())
        if mm:
            meta[mm.group(1)] = mm.group(2).strip()
    return meta, m.group(2).strip()


# ---------------------------------------------------------------------------
# 阅读状态管理(稍后阅读 / 最近阅读 / 收藏)
# ---------------------------------------------------------------------------

READING_FIELDS = ("read_later", "is_favorite", "last_read_at", "read_count", "reading_status")
VALID_READING_STATUS = ("to_read", "reading", "read")


def _ensure_reading_fields(source_record: dict) -> dict:
    """给单条 source 记录补全阅读状态默认值(不修改原 dict)。"""
    r = dict(source_record)
    r.setdefault("read_later", False)
    r.setdefault("is_favorite", False)
    r.setdefault("last_read_at", None)
    r.setdefault("read_count", 0)
    r.setdefault("reading_status", "to_read")
    return r


def _save_reading_state(source_id: str, **updates) -> dict:
    """更新某 source 的阅读状态字段,写回 state.json。返回更新后的完整记录。

    updates 只允许 READING_FIELDS 中的键。写前备份。
    """
    for k in updates:
        if k not in READING_FIELDS:
            raise HTTPException(400, f"非法字段:{k}")

    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 备份
    backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"state_{date.today().isoformat()}.json.bak"
    if kb.STATE_FILE.exists():
        shutil.copy2(kb.STATE_FILE, backup)

    rec = sources[source_id]
    for k, v in updates.items():
        rec[k] = v

    kb.save_state(state)
    return _ensure_reading_fields(rec)


def _mark_read(source_id: str) -> None:
    """标记已读:last_read_at=now, read_count+1, reading_status=read。失败静默。"""
    try:
        state = kb.load_state()
        sources = state.get("sources", {})
        if source_id not in sources:
            return
        rec = sources[source_id]
        rec["last_read_at"] = datetime.now().isoformat(timespec="seconds")
        rec["read_count"] = int(rec.get("read_count", 0) or 0) + 1
        rec["reading_status"] = "read"
        kb.save_state(state)
    except Exception:
        pass


def _summary_card_from_source(source_id: str, rec: dict) -> dict[str, Any]:
    """把 state.json 里的 source 记录转成前端卡片数据(含阅读状态)。"""
    return {
        "source_id": source_id,
        "title": rec.get("source_title", source_id),
        "source_type": rec.get("source_type", "?"),
        "area": rec.get("area", ""),
        "excerpt": "",  # 卡片复用时会从 summary 补 excerpt
        "created_at": rec.get("created_at", ""),
        "summarized_at": rec.get("ingested_at", ""),
        "read_later": rec.get("read_later", False),
        "is_favorite": rec.get("is_favorite", False),
        "last_read_at": rec.get("last_read_at"),
        "read_count": rec.get("read_count", 0),
        "reading_status": rec.get("reading_status", "to_read"),
    }


def _all_cards() -> list[dict[str, Any]]:
    """构建所有文章的卡片列表(合并 state 状态 + summary excerpt)。"""
    state = kb.load_state()
    sources = state.get("sources", {})
    summaries = {s["source_id"]: s for s in _scan_summaries()}

    cards: list[dict[str, Any]] = []
    for sid, rec in sources.items():
        card = _summary_card_from_source(sid, _ensure_reading_fields(rec))
        has_summary = sid in summaries
        card["has_summary"] = has_summary
        if has_summary:
            sm = summaries[sid]
            card["title"] = sm.get("title") or card["title"]
            card["excerpt"] = sm.get("excerpt", "")
            card["summarized_at"] = sm.get("summarized_at", card["summarized_at"])
        cards.append(card)
    return cards


def _summary_cards_only() -> list[dict[str, Any]]:
    """只返回有 summary 的卡片(首页/最近阅读/收藏夹用)。"""
    return [c for c in _all_cards() if c.get("has_summary")]


def _build_dashboard() -> dict[str, Any]:
    """首页 dashboard:只统计有 summary 的文章。"""
    cards = _summary_cards_only()
    unread = [c for c in cards if c["reading_status"] in ("to_read", "reading")]
    read = [c for c in cards if c["reading_status"] == "read"]
    read_later = [c for c in cards if c["read_later"]]

    total = len(cards)
    return {
        "stats": {
            "total": total,
            "unread": len(unread),
            "read": len(read),
            "read_later": len(read_later),
            "progress": round(len(read) / total * 100, 1) if total else 0,
        },
        "read_later": read_later,
    }


def _build_recent() -> list[dict[str, Any]]:
    """最近阅读:有 summary + 有 last_read_at,按时间倒序,最多 30 篇。"""
    cards = _summary_cards_only()
    recent = sorted(
        [c for c in cards if c["last_read_at"]],
        key=lambda x: x["last_read_at"],
        reverse=True,
    )[:30]
    return recent


def _build_favorites() -> list[dict[str, Any]]:
    """收藏夹:有 summary + is_favorite。"""
    cards = _summary_cards_only()
    return [c for c in cards if c["is_favorite"]]


def _build_pending_summaries() -> list[dict[str, Any]]:
    """待生成 summary 的文章(有 source note 但没 summary)。"""
    return [c for c in _all_cards() if not c.get("has_summary")]


def _generate_summary_for_source(source_id: str) -> dict[str, Any]:
    """对单个 source 生成 summary。复用 kb.py 的核心逻辑。

    返回 {ok, source_id, summary_path?, error?}
    """
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")
    rec = sources[source_id]
    source_note_path = VAULT_ROOT / rec.get("path", "")
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

    # 写 summary 文件(复用 kb.py 的 _write_summary)
    summary_path = kb._write_summary(source_id, rec, summary_body)
    # 回填 source note
    kb._backfill_source_note(source_note_path, source_id, summary_path, "summarized")
    # 更新 state
    rec["summary_path"] = summary_path.relative_to(VAULT_ROOT).as_posix()
    rec.setdefault("action_status", "undecided")
    kb.save_state(state)

    return {
        "ok": True,
        "source_id": source_id,
        "summary_path": summary_path.relative_to(VAULT_ROOT).as_posix(),
    }


def _scan_summaries() -> list[dict[str, Any]]:
    """扫描 02_Summaries/ 下所有 summary,返回卡片元数据列表(按日期降序)。"""
    summaries_dir = VAULT_ROOT / "02_Summaries"
    if not summaries_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for sf in summaries_dir.rglob("*.md"):
        try:
            meta, body = _parse_frontmatter(sf.read_text(encoding=ENC))
        except Exception:
            continue
        # 提取一句话结论作为摘要
        concl = ""
        m = re.search(r"#\s*一句话结论\s*\n+(.+?)(?=\n#|\Z)", body, re.DOTALL)
        if m:
            concl = m.group(1).strip().split("\n")[0][:160]
        source_id = meta.get("source_id", sf.stem)
        items.append(
            {
                "source_id": source_id,
                "title": meta.get("source_title", sf.stem)
                or sf.stem,
                "source_type": meta.get("source_type", "?"),
                "area": meta.get("area", ""),
                "summarized_at": meta.get("summarized_at", ""),
                "created_at": meta.get("created_at", ""),
                "excerpt": concl,
                "path": str(sf.relative_to(VAULT_ROOT).as_posix()),
            }
        )
    # 按日期降序(summarized_at 优先,空值排后)
    items.sort(key=lambda x: x.get("summarized_at") or "", reverse=True)
    return items


def _read_summary_detail(source_id: str) -> dict[str, Any]:
    """读单篇 summary,返回 frontmatter + markdown 转 HTML 后的正文。

    若 summary 不存在,回退读 source note 的原始内容(投稿后未生成 summary 的情况)。
    """
    import markdown as md

    summaries_dir = VAULT_ROOT / "02_Summaries"
    # 1. 先找 summary
    if summaries_dir.exists():
        for sf in summaries_dir.rglob("*.md"):
            try:
                text = sf.read_text(encoding=ENC)
                meta, body = _parse_frontmatter(text)
            except Exception:
                continue
            if meta.get("source_id") == source_id or sf.stem == source_id:
                html_body = md.markdown(
                    body,
                    extensions=["extra", "codehilite", "toc"],
                    extension_configs={"codehilite": {"guess_lang": False}},
                )
                return {
                    "source_id": source_id,
                    "title": meta.get("source_title", source_id),
                    "meta": meta,
                    "html_body": html_body,
                    "path": str(sf.relative_to(VAULT_ROOT).as_posix()),
                    "has_summary": True,
                }

    # 2. 回退:读 source note 原文
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source_id={source_id}")
    rec = sources[source_id]
    source_path = VAULT_ROOT / rec.get("path", "")
    if not source_path.exists():
        raise HTTPException(404, f"source 文件不存在:{source_path}")

    text = source_path.read_text(encoding=ENC)
    meta, body = _parse_frontmatter(text)
    # 提取 source note 里的「原始内容」区
    m = re.search(r"##\s*原始内容\s*\n(.*)", body, re.DOTALL)
    raw_body = m.group(1).strip() if m else body
    html_body = md.markdown(
        raw_body,
        extensions=["extra", "codehilite", "toc"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )
    return {
        "source_id": source_id,
        "title": rec.get("source_title", source_id),
        "meta": {
            "source_type": rec.get("source_type", "?"),
            "source_title": rec.get("source_title", ""),
            "area": rec.get("area", ""),
            "created_at": rec.get("created_at", ""),
            "ingested_at": rec.get("ingested_at", ""),
        },
        "html_body": html_body,
        "path": str(source_path.relative_to(VAULT_ROOT).as_posix()),
        "has_summary": False,
    }


def _parse_suggestion_file(path: Path, kind: str) -> list[dict[str, Any]]:
    """解析 idea_suggestions.md / todo_suggestions.md 的候选块。

    kind: "Idea Suggestion" 或 "Todo Suggestion"
    返回 [{id, title, status, fields..., body}],每块含解析出的字段。
    """
    if not path.exists():
        return []
    text = path.read_text(encoding=ENC)
    # 复用 kb.py 的切块逻辑
    raw_blocks = kb._split_suggestion_blocks(text, kind)
    results: list[dict[str, Any]] = []
    for raw, meta, body in raw_blocks:
        item = {
            "id": meta.get("id", ""),
            "title": meta.get("title", ""),
            "status": meta.get("status", "pending_review"),
            "raw": raw,
            "body": body,
        }
        # 把所有解析出的字段都带上(前端按需显示)
        item["fields"] = meta
        results.append(item)
    return results


def _update_suggestion_status(
    path: Path, kind: str, item_id: str, new_status: str, valid_set: set[str]
) -> dict[str, Any]:
    """修改某个 suggestion 块的 status,写回 markdown 文件。

    只改匹配 item_id 的块里的 status 行,其他内容不动。
    """
    if new_status not in valid_set:
        raise HTTPException(400, f"非法 status 值:{new_status}")

    if not path.exists():
        raise HTTPException(404, f"文件不存在:{path}")

    text = path.read_text(encoding=ENC)

    # 备份(防写错)
    backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    backup = backup_dir / f"{path.stem}_{today}.bak"
    shutil.copy2(path, backup)

    # 定位含该 id 的块,替换其 status 行
    # 策略:先按 kind 切块,找到 id 匹配的块,在块内替换 status,再拼回
    raw_blocks = kb._split_suggestion_blocks(text, kind)
    if not raw_blocks:
        raise HTTPException(404, f"文件里没有 {kind} 块")

    found = False
    new_blocks: list[str] = []
    for raw, meta, body in raw_blocks:
        if meta.get("id") == item_id or meta.get("id", "").endswith(item_id):
            # 替换该块的 status 行
            old_status = meta.get("status", "pending_review")
            updated = re.sub(
                r"^(-\s*status:\s*)" + re.escape(old_status) + r"\s*$",
                rf"\g<1>{new_status}",
                raw,
                flags=re.MULTILINE,
            )
            new_blocks.append(updated)
            found = True
        else:
            new_blocks.append(raw)

    if not found:
        raise HTTPException(404, f"找不到 id={item_id} 的块")

    # 重建文件:头部 + 块
    header_kind = "idea" if "Idea" in kind else "todo"
    header = kb._suggestion_header(
        "Idea Suggestions (Review Queue)" if header_kind == "idea" else "Todo Suggestions (Review Queue)",
        header_kind,
    )
    new_content = header + "\n".join(new_blocks) + "\n"
    path.write_text(new_content, encoding=ENC)

    return {"ok": True, "id": item_id, "new_status": new_status}


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    """首页:summary 卡片仪表盘。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在,请检查安装", 500)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"active_nav": "index"},
    )


@app.get("/summary/{source_id}", response_class=HTMLResponse)
async def page_summary(request: Request, source_id: str):
    """单篇 summary 详情页。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request,
        "summary.html",
        {"source_id": source_id, "active_nav": "index"},
    )


@app.get("/ideas", response_class=HTMLResponse)
async def page_ideas(request: Request):
    """idea list 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "ideas.html", {"active_nav": "ideas"}
    )


@app.get("/todos", response_class=HTMLResponse)
async def page_todos(request: Request):
    """todo list 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "todos.html", {"active_nav": "todos"}
    )


@app.get("/recent", response_class=HTMLResponse)
async def page_recent(request: Request):
    """最近阅读页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "recent.html", {"active_nav": "recent"}
    )


@app.get("/favorites", response_class=HTMLResponse)
async def page_favorites(request: Request):
    """收藏夹页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "favorites.html", {"active_nav": "favorites"}
    )


@app.get("/submit", response_class=HTMLResponse)
async def page_submit(request: Request):
    """投稿页面:粘贴 URL 或文本,提交后自动 ingest。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "submit.html", {"active_nav": "submit"}
    )


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------


@app.get("/api/summaries")
async def api_summaries():
    """所有 summary 卡片元数据。"""
    return JSONResponse({"items": _scan_summaries()})


@app.get("/api/summary/{source_id}")
async def api_summary_detail(source_id: str):
    """单篇 summary 详情(含 markdown 转 HTML)。打开即记阅读。"""
    _mark_read(source_id)  # 自动追踪阅读:last_read_at + read_count
    return JSONResponse(_read_summary_detail(source_id))


@app.get("/api/ideas")
async def api_ideas():
    """所有 idea suggestion 块。"""
    path = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    return JSONResponse({"items": _parse_suggestion_file(path, "Idea Suggestion")})


@app.get("/api/todos")
async def api_todos():
    """所有 todo suggestion 块。"""
    path = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    return JSONResponse({"items": _parse_suggestion_file(path, "Todo Suggestion")})


class StatusUpdate(BaseModel):
    status: str


@app.post("/api/idea/{item_id}/status")
async def api_idea_status(item_id: str, payload: StatusUpdate):
    """修改 idea suggestion 的 status。"""
    path = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    return JSONResponse(
        _update_suggestion_status(
            path, "Idea Suggestion", item_id, payload.status, VALID_IDEA_STATUS
        )
    )


@app.post("/api/todo/{item_id}/status")
async def api_todo_status(item_id: str, payload: StatusUpdate):
    """修改 todo suggestion 的 status。"""
    path = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    return JSONResponse(
        _update_suggestion_status(
            path, "Todo Suggestion", item_id, payload.status, VALID_TODO_STATUS
        )
    )


@app.get("/api/dashboard")
async def api_dashboard():
    """首页:未读/已读统计 + 稍后读列表。"""
    return JSONResponse(_build_dashboard())


class IngestRequest(BaseModel):
    """投稿请求:多个文本片段(URL 或正文)。"""
    items: list[str]
    auto_summary: bool = True


@app.post("/api/ingest")
async def api_ingest(payload: IngestRequest):
    """投稿:把前端传来的多个文本片段写进 inbox,然后跑 ingest。

    auto_summary=True 时,ingest 后自动对新增 source 生成 summary。
    """
    texts = [t.strip() for t in payload.items if t and t.strip()]
    if not texts:
        raise HTTPException(400, "没有有效内容")

    inbox_path = VAULT_ROOT / "00_Inbox" / "inbox.md"
    header = "# Inbox\n\n> web submit\n\n"
    body = "\n\n---\n\n".join(texts)
    inbox_path.write_text(header + body + "\n", encoding=ENC)

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

    return JSONResponse(
        {
            "ok": True,
            "submitted": len(texts),
            "log": log,
            "new_sources": new_sources,
            "summary_results": summary_results,
        }
    )


@app.get("/api/pending-summaries")
async def api_pending_summaries():
    """返回还没生成 summary 的 source 列表。"""
    return JSONResponse({"items": _build_pending_summaries()})


@app.post("/api/generate-summary/{source_id}")
async def api_generate_summary(source_id: str):
    """对单个 source 生成 summary。"""
    return JSONResponse(_generate_summary_for_source(source_id))


@app.get("/api/dashboard_full")
async def api_dashboard_full():
    """首页:按 reading_status 分组的文章列表(未读/已读,只含有 summary 的)。"""
    cards = _summary_cards_only()
    unread = [c for c in cards if c["reading_status"] in ("to_read", "reading")]
    read = [c for c in cards if c["reading_status"] == "read"]
    unread.sort(key=lambda x: x.get("summarized_at") or "", reverse=True)
    read.sort(key=lambda x: x.get("last_read_at") or "", reverse=True)
    return JSONResponse({"unread": unread, "read": read})


@app.get("/api/recent")
async def api_recent():
    """最近阅读 30 篇(按 last_read_at 倒序)。"""
    return JSONResponse({"items": _build_recent()})


@app.get("/api/favorites")
async def api_favorites():
    """收藏夹列表。"""
    return JSONResponse({"items": _build_favorites()})


@app.post("/api/article/{source_id}/read-later")
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


@app.post("/api/article/{source_id}/favorite")
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


@app.delete("/api/article/{source_id}")
async def api_delete_article(source_id: str):
    """彻底删除一篇文章:source note + summary + raw_text + state 记录。

    删除前备份 state.json。物理文件直接删除(不可恢复)。
    """
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")
    rec = sources[source_id]
    deleted_files: list[str] = []

    # 备份 state
    backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"state_{date.today().isoformat()}.json.bak"
    shutil.copy2(kb.STATE_FILE, backup)

    # 1. 删 source note
    source_path = VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
    if source_path and source_path.exists():
        source_path.unlink()
        deleted_files.append(str(source_path.relative_to(VAULT_ROOT).as_posix()))

    # 2. 删 summary(如果存在)
    summary_path = rec.get("summary_path")
    if summary_path:
        sp = VAULT_ROOT / summary_path
        if sp.exists():
            sp.unlink()
            deleted_files.append(str(sp.relative_to(VAULT_ROOT).as_posix()))
    else:
        # summary_path 没记录,扫 02_Summaries 找匹配 source_id 的
        summaries_dir = VAULT_ROOT / "02_Summaries"
        if summaries_dir.exists():
            for sf in summaries_dir.rglob("*.md"):
                try:
                    txt = sf.read_text(encoding=ENC)
                    fm, _ = _parse_frontmatter(txt)
                    if fm.get("source_id") == source_id:
                        sf.unlink()
                        deleted_files.append(str(sf.relative_to(VAULT_ROOT).as_posix()))
                        break
                except Exception:
                    continue

    # 3. 删 raw_text
    raw_path = VAULT_ROOT / ".kb" / "raw_text" / f"{source_id}.txt"
    if raw_path.exists():
        raw_path.unlink()
        deleted_files.append(str(raw_path.relative_to(VAULT_ROOT).as_posix()))

    # 4. 删 idea_suggestions / todo_suggestions 里关联的候选(source_id 匹配)
    for sug_path, kind in [
        (VAULT_ROOT / "03_Ideas" / "idea_suggestions.md", "idea"),
        (VAULT_ROOT / "04_Plans" / "todo_suggestions.md", "todo"),
    ]:
        if sug_path.exists():
            txt = sug_path.read_text(encoding=ENC)
            # 删除引用了该 source_id 的候选块
            pattern = re.compile(
                rf"\n## (?:Idea|Todo) Suggestion:[^\n]*\n(?:(?!## (?:Idea|Todo) Suggestion:).)*?{re.escape(source_id)}(?:(?!## (?:Idea|Todo) Suggestion:).)*",
                re.DOTALL,
            )
            new_txt = pattern.sub("", txt)
            if new_txt != txt:
                sug_path.write_text(new_txt, encoding=ENC)

    # 5. 从 state 删除记录
    del sources[source_id]
    kb.save_state(state)

    return JSONResponse(
        {"ok": True, "source_id": source_id, "deleted_files": deleted_files}
    )


@app.get("/api/health")
async def api_health():
    """健康检查。"""
    return {"ok": True, "vault": str(VAULT_ROOT)}
