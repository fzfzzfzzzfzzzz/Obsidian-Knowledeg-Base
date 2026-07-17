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

import base64
import hashlib
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import kb  # 复用 kb.py 的工具函数
import kb_llm  # 用于生成 summary(generate_summary)
import kb_date  # 日期识别(detect_dates / recommend_date)

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
    """解析 markdown frontmatter(委托给 kb.parsefrontmatter,保证单一真相)。"""
    return kb.parsefrontmatter(text)


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
    r.setdefault("tags", [])
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


# ---------------------------------------------------------------------------
# 标签管理(tags):state.json + summary frontmatter 双写
# ---------------------------------------------------------------------------


def _get_article_tags(source_id: str) -> list[str]:
    """从 state.json 读 tags(兜底 [])。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        return []
    return list(rec.get("tags", []))


def _read_summary_frontmatter_tags(summary_path: Path) -> list[str]:
    """从 summary frontmatter 解析 tags 字段。

    frontmatter 里 tags 写成 `tags: [a, b, c]`(字面串),这里解析为 list。
    旧文件无此字段返回 []。
    """
    if not summary_path.exists():
        return []
    try:
        text = summary_path.read_text(encoding=ENC)
        meta, _ = _parse_frontmatter(text)
        raw = meta.get("tags", "")
        if not raw:
            return []
        # 解析 [a, b, c] 或 a, b, c
        cleaned = raw.strip().strip("[]").strip()
        if not cleaned:
            return []
        return [t.strip().strip('"').strip("'") for t in cleaned.split(",") if t.strip()]
    except Exception:
        return []


def _write_summary_frontmatter_tags(summary_path: Path, tags: list[str]) -> bool:
    """把 tags 写回 summary frontmatter(行级替换)。

    若 frontmatter 无 tags 行则插入一行。返回是否成功。
    """
    if not summary_path.exists():
        return False
    try:
        text = summary_path.read_text(encoding=ENC)
        tags_str = "[" + ", ".join(tags) + "]"
        # 尝试替换已有 tags 行
        new_text, n = re.subn(
            r"^(tags:\s*).*$",
            rf"\g<1>{tags_str}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n == 0:
            # 没有 tags 行,在 frontmatter 末尾(--- 前)插入
            new_text = re.sub(
                r"(\n---\s*\n)",
                f"\ntags: {tags_str}\\1",
                text,
                count=1,
            )
        summary_path.write_text(new_text, encoding=ENC)
        return True
    except Exception:
        return False


def _set_article_tags(source_id: str, tags: list[str]) -> list[str]:
    """设置文章 tags,双写 state.json + summary frontmatter。返回最终 tags。"""
    # 去重保序
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tags:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)

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

    # 写 state.json
    sources[source_id]["tags"] = deduped
    kb.save_state(state)

    # 写 summary frontmatter(如果有 summary)
    summary_path = sources[source_id].get("summary_path")
    if summary_path:
        _write_summary_frontmatter_tags(VAULT_ROOT / summary_path, deduped)

    return deduped


def _add_article_tags(source_id: str, new_tags: list[str]) -> list[str]:
    """追加 tags(不覆盖旧 tags,自动去重)。返回最终 tags。"""
    current = _get_article_tags(source_id)
    return _set_article_tags(source_id, current + new_tags)


def _remove_article_tag(source_id: str, tag: str) -> list[str]:
    """删除单个 tag。返回最终 tags。"""
    current = _get_article_tags(source_id)
    return _set_article_tags(source_id, [t for t in current if t != tag])


def _delete_one(source_id: str, state: dict) -> dict[str, Any]:
    """删除单篇文章的全部文件 + state 记录(不调 save_state,由调用方统一保存)。

    返回 {ok, source_id, deleted_files, error?}。
    单个失败不影响其他文章(批量删除用)。
    """
    sources = state.get("sources", {})
    if source_id not in sources:
        return {"ok": False, "source_id": source_id, "error": "source 不存在", "deleted_files": []}
    rec = sources[source_id]
    deleted_files: list[str] = []
    try:
        # 1. 删 source note
        sp = rec.get("path")
        if sp:
            p = VAULT_ROOT / sp
            if p.exists():
                p.unlink()
                deleted_files.append(sp)
        # 2. 删 summary
        sump = rec.get("summary_path")
        if sump:
            p = VAULT_ROOT / sump
            if p.exists():
                p.unlink()
                deleted_files.append(sump)
        else:
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
        rp = VAULT_ROOT / ".kb" / "raw_text" / f"{source_id}.txt"
        if rp.exists():
            rp.unlink()
            deleted_files.append(str(rp.relative_to(VAULT_ROOT).as_posix()))
        # 4. 删 suggestion 候选块
        for sug_path in [VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
                         VAULT_ROOT / "04_Plans" / "todo_suggestions.md"]:
            if sug_path.exists():
                txt = sug_path.read_text(encoding=ENC)
                pattern = re.compile(
                    rf"\n## (?:Idea|Todo) Suggestion:[^\n]*\n(?:(?!## (?:Idea|Todo) Suggestion:).)*?{re.escape(source_id)}(?:(?!## (?:Idea|Todo) Suggestion:).)*",
                    re.DOTALL,
                )
                new_txt = pattern.sub("", txt)
                if new_txt != txt:
                    sug_path.write_text(new_txt, encoding=ENC)
        # 5. 清理关联的日历事项(PRD 11.6:删除知识时移除日历关联)
        try:
            cal = kb.load_calendar()
            cal_changed = False
            for cal_id, cal_item in list(cal.get("items", {}).items()):
                if cal_item.get("source_id") == source_id:
                    # 移除关联(source_id 清空),事项本身保留
                    cal_item["source_id"] = ""
                    cal_item["source_type"] = ""
                    cal_item["source_title"] = ""
                    cal_item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    cal_changed = True
            if cal_changed:
                kb.save_calendar(cal)
        except Exception:
            pass  # 日历清理失败不阻断删除

        # 6. 从 state 删记录
        del sources[source_id]
        return {"ok": True, "source_id": source_id, "deleted_files": deleted_files}
    except Exception as e:
        return {"ok": False, "source_id": source_id, "error": str(e), "deleted_files": deleted_files}


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
        "tags": rec.get("tags", []),
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


def _build_all_articles() -> list[dict[str, Any]]:
    """所有文章(含无 summary 的),按日期倒序。"""
    cards = _all_cards()
    cards.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return cards


def _build_searchable_articles() -> list[dict[str, Any]]:
    """可搜索的文章:有 summary 的,带 summary 正文用于搜索。"""
    cards = _summary_cards_only()
    # 补充 summary 正文(用于关键词搜索)
    for c in cards:
        c["summary_text"] = ""
        sid = c["source_id"]
        state = kb.load_state()
        rec = state.get("sources", {}).get(sid, {})
        sp = rec.get("summary_path")
        if sp:
            spath = VAULT_ROOT / sp
            if spath.exists():
                try:
                    _, body = _parse_frontmatter(spath.read_text(encoding=ENC))
                    c["summary_text"] = body
                except Exception:
                    pass
    return cards


def _do_search(
    q: str = "",
    reading_status: str = "",
    is_favorite: str = "",
    source_type: str = "",
    tags: str = "",
    has_summary: str = "",
) -> list[dict[str, Any]]:
    """搜索 + 筛选。返回卡片列表(不含 summary_text,避免响应过大)。"""
    articles = _build_searchable_articles()

    # 关键词搜索(title + summary 正文 + tags)
    if q:
        ql = q.lower()
        articles = [
            a for a in articles
            if ql in (a.get("title") or "").lower()
            or ql in (a.get("summary_text") or "").lower()
            or any(ql in (t or "").lower() for t in a.get("tags", []))
        ]

    # 筛选
    if reading_status:
        articles = [a for a in articles if a.get("reading_status") == reading_status]
    if is_favorite == "true":
        articles = [a for a in articles if a.get("is_favorite")]
    if is_favorite == "false":
        articles = [a for a in articles if not a.get("is_favorite")]
    if source_type:
        articles = [a for a in articles if a.get("source_type") == source_type]
    if tags:
        filter_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
        articles = [
            a for a in articles
            if any(ft in [t.lower() for t in a.get("tags", [])] for ft in filter_tags)
        ]
    if has_summary == "true":
        articles = [a for a in articles if a.get("has_summary")]
    if has_summary == "false":
        articles = [a for a in articles if not a.get("has_summary")]

    # 清理 summary_text(不返回给前端)
    for a in articles:
        a.pop("summary_text", None)
    return articles


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

    # 检查 LLM 是否返回了空内容(思考模型可能 token 全用在思考上,没输出)
    if not summary_body or not summary_body.strip():
        return {"ok": False, "source_id": source_id, "error": "LLM 返回空内容(可能是思考模型超时或 token 不足,请重试)"}

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
    返回值含 source_url(从 source note frontmatter 读)。
    """
    import markdown as md

    # 先从 source note 读 source_url(两种路径都需要)
    source_url = ""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id, {})
    sn_path = VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
    if sn_path and sn_path.exists():
        try:
            sn_meta, _ = _parse_frontmatter(sn_path.read_text(encoding=ENC))
            source_url = sn_meta.get("source_url", "").strip()
        except Exception:
            pass

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
                    "source_url": source_url,
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
        "source_url": source_url,
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


def _parse_formal_ideas() -> list[dict[str, Any]]:
    """扫描 03_Ideas/*_ideas.md(排除 review 队列和 archived),按 ## Idea: 切块。

    正式 idea 格式(_format_formal_idea 落盘):## Idea: <title> + - key: value + 正文。
    复用 kb._split_suggestion_blocks(text, "Idea")(标题前缀正好是 "Idea")。
    返回 [{id, title, status, area, fields, body}]。文件不存在/为空返回 []。
    """
    ideas_dir = VAULT_ROOT / "03_Ideas"
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


def _parse_formal_todos() -> list[dict[str, Any]]:
    """扫描 04_Plans 下的正式 todo 文件,解析 - [ ] / - [x] 任务行及其缩进子项。

    覆盖:Weekly/*.md、Monthly/*.md、someday.md、completed_todos.md。
    每条返回 {title, done, plan, period, source, estimated_time, difficulty, note}。
    plan/period 从路径+文件名推断;文件不存在/为空返回 []。
    """
    plans_dir = VAULT_ROOT / "04_Plans"
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


@app.get("/search", response_class=HTMLResponse)
async def page_search(request: Request):
    """搜索页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "search.html", {"active_nav": "search"}
    )


@app.get("/articles", response_class=HTMLResponse)
async def page_articles(request: Request):
    """All Articles 页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "articles.html", {"active_nav": "articles"}
    )


@app.get("/calendar", response_class=HTMLResponse)
async def page_calendar(request: Request):
    """日历页面。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "calendar.html", {"active_nav": "calendar"}
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


@app.get("/api/ideas/confirmed")
async def api_ideas_confirmed():
    """已确定的 idea:扫描 03_Ideas/*_ideas.md 正式清单(accept-ideas 落盘)。"""
    return JSONResponse({"items": _parse_formal_ideas()})


@app.get("/api/todos/confirmed")
async def api_todos_confirmed():
    """已确定的 todo:扫描 04_Plans/Weekly、Monthly、someday、completed(accept-todos 落盘)。"""
    return JSONResponse({"items": _parse_formal_todos()})


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


@app.post("/api/ingest-image")
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
    inbox_path = VAULT_ROOT / "00_Inbox" / "inbox.md"
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


@app.get("/api/pending-summaries")
async def api_pending_summaries():
    """返回还没生成 summary 的 source 列表。"""
    return JSONResponse({"items": _build_pending_summaries()})


@app.post("/api/generate-summary/{source_id}")
async def api_generate_summary(source_id: str):
    """对单个 source 生成 summary。"""
    return JSONResponse(_generate_summary_for_source(source_id))


@app.post("/api/article/{source_id}/regenerate-summary")
async def api_regenerate_summary(source_id: str):
    """重新生成 summary(覆盖已有)。先备份旧 summary 到 .kb/logs/web_backups/。"""
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 备份旧 summary(如果存在)
    old_sp = sources[source_id].get("summary_path")
    if old_sp:
        old_path = VAULT_ROOT / old_sp
        if old_path.exists():
            backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
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


@app.delete("/api/article/{source_id}/summary")
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

    old_path = VAULT_ROOT / old_sp
    # 备份
    if old_path.exists():
        backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
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
    sn_path = VAULT_ROOT / sources[source_id].get("path", "") if sources[source_id].get("path") else None
    if sn_path and sn_path.exists():
        text = sn_path.read_text(encoding=ENC)
        text = re.sub(r"^status:.*", "status: source_created", text, flags=re.MULTILINE)
        text = re.sub(r"summary_location:.*", "summary_location:", text)
        sn_path.write_text(text, encoding=ENC)

    return JSONResponse({"ok": True, "source_id": source_id, "deleted_summary": old_sp})


# ---------------------------------------------------------------------------
# 详情页手动生成 idea/todo(v0.4.0)
# ---------------------------------------------------------------------------


class GenerateIdeasRequest(BaseModel):
    prompt: str = ""
    priority: str = ""  # "" / P0 / P1 / P2 / P3
    area: str = ""  # "" / research / productivity / product / ai_agent / web_design / other


class GenerateTodosRequest(BaseModel):
    prompt: str = ""
    priority: str = ""  # "" / P0 / P1 / P2 / P3
    difficulty: str = ""  # "" / low / medium / high
    estimated_time: str = ""  # "" / 30min / 1h / 2-4h / 半天 / 1-2 天
    plan: str = ""  # "" / weekly / monthly / someday


def _build_hint(payload) -> str:
    """把用户选的非空参数拼成 hint 文本。全空时返回空字符串。"""
    lines = []
    if getattr(payload, "priority", ""):
        lines.append(f"优先级: {payload.priority}")
    for field, label in (
        ("area", "领域"),
        ("difficulty", "难度"),
        ("estimated_time", "预计时间"),
        ("plan", "计划"),
    ):
        val = getattr(payload, field, "")
        if val:
            lines.append(f"{label}: {val}")
    prompt = (getattr(payload, "prompt", "") or "").strip()
    if prompt:
        lines.append(f"引导: {prompt}")
    return "\n".join(lines)


@app.post("/api/article/{source_id}/generate-ideas")
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
    spath = VAULT_ROOT / sp
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
            VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
            kb._format_idea_suggestion(source_id, sources[source_id], it, today),
        )
    # 不改 action_status,避免影响批量入口的幂等判断
    return JSONResponse(
        {"ok": True, "source_id": source_id, "kind": "idea", "generated": len(ideas)}
    )


@app.post("/api/article/{source_id}/generate-todos")
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
    spath = VAULT_ROOT / sp
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
            VAULT_ROOT / "04_Plans" / "todo_suggestions.md",
            kb._format_todo_suggestion(source_id, sources[source_id], it, today),
        )
    return JSONResponse(
        {"ok": True, "source_id": source_id, "kind": "todo", "generated": len(todos)}
    )


# ---------------------------------------------------------------------------
# 日历功能 API(PRD v0.3)
# ---------------------------------------------------------------------------


@app.get("/api/article/{source_id}/detected-dates")
async def api_detected_dates(source_id: str):
    """获取文章的候选日期(识别正文中的日期)。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 优先用缓存的 detected_dates,没有就实时识别
    cached = rec.get("detected_dates")
    if cached:
        ranked = kb_date.rank_dates(cached)
    else:
        # 读正文(source note 或 summary)
        text = ""
        sn_path = VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
        if sn_path and sn_path.exists():
            note = sn_path.read_text(encoding=ENC)
            text = kb._extract_source_body(note)
        if not text.strip() and rec.get("summary_path"):
            sp = VAULT_ROOT / rec["summary_path"]
            if sp.exists():
                _, text = _parse_frontmatter(sp.read_text(encoding=ENC))

        if text.strip():
            detected = kb_date.detect_dates(text)
            ranked = kb_date.rank_dates(detected)
            # 缓存到 state
            rec["detected_dates"] = detected
            kb.save_state(state)
        else:
            ranked = []

    # 推荐日期(第一个未来日期)
    recommended = None
    for d in ranked:
        if d.get("is_future"):
            recommended = d
            break

    return JSONResponse({
        "recommended": recommended,
        "candidates": ranked,
    })


@app.post("/api/article/{source_id}/detect-dates")
async def api_redetect_dates(source_id: str):
    """手动重新识别日期(清除缓存重新扫描)。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        raise HTTPException(404, f"找不到 source:{source_id}")

    # 读正文
    text = ""
    sn_path = VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
    if sn_path and sn_path.exists():
        note = sn_path.read_text(encoding=ENC)
        text = kb._extract_source_body(note)
    if not text.strip() and rec.get("summary_path"):
        sp = VAULT_ROOT / rec["summary_path"]
        if sp.exists():
            _, text = _parse_frontmatter(sp.read_text(encoding=ENC))

    detected = kb_date.detect_dates(text) if text.strip() else []
    rec["detected_dates"] = detected
    kb.save_state(state)

    ranked = kb_date.rank_dates(detected)
    recommended = next((d for d in ranked if d.get("is_future")), None)
    return JSONResponse({"recommended": recommended, "candidates": ranked, "count": len(detected)})


# ---- CalendarItem CRUD ----

class CalendarItemCreate(BaseModel):
    title: str
    date: str  # YYYY-MM-DD
    note: str = ""
    source_id: str = ""
    source_type: str = ""
    source_title: str = ""
    detected_date_id: str = ""
    date_source: str = "manual"  # detected | manual
    date_confidence: str = ""


class CalendarItemUpdate(BaseModel):
    title: str = ""
    date: str = ""
    note: str = ""
    source_id: str | None = None  # None=不改,None 以外的值(含空串)=更新关联


@app.get("/api/calendar")
async def api_calendar_list(start: str = "", end: str = ""):
    """获取日历事项(可按日期范围筛选)。"""
    cal = kb.load_calendar()
    items = list(cal.get("items", {}).values())
    if start:
        items = [i for i in items if i.get("date", "") >= start]
    if end:
        items = [i for i in items if i.get("date", "") <= end]
    items.sort(key=lambda x: x.get("date", ""))
    return JSONResponse({"items": items, "count": len(items)})


@app.get("/api/calendar/{item_id}")
async def api_calendar_get(item_id: str):
    """获取单个日历事项。"""
    cal = kb.load_calendar()
    item = cal.get("items", {}).get(item_id)
    if not item:
        raise HTTPException(404, f"找不到日历事项:{item_id}")
    return JSONResponse(item)


@app.post("/api/calendar")
async def api_calendar_create(payload: CalendarItemCreate):
    """创建日历事项。"""
    if not payload.title.strip():
        raise HTTPException(400, "事项名称不能为空")
    # 校验日期格式
    try:
        date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(400, f"日期格式错误:{payload.date}(需 YYYY-MM-DD)")

    import uuid
    item_id = f"cal_{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat(timespec="seconds")

    # 检查是否已有同 source_id 的事项(防重复,PRD 11.9)
    cal = kb.load_calendar()
    if payload.source_id:
        for existing in cal.get("items", {}).values():
            if existing.get("source_id") == payload.source_id:
                # 返回已有事项(PRD: 不创建重复)
                return JSONResponse({"ok": True, "item": existing, "already_existed": True})

    item = {
        "id": item_id,
        "title": payload.title.strip(),
        "date": payload.date,
        "note": payload.note,
        "source_id": payload.source_id,
        "source_type": payload.source_type,
        "source_title": payload.source_title,
        "detected_date_id": payload.detected_date_id,
        "date_source": payload.date_source,
        "date_confidence": payload.date_confidence,
        "created_at": now,
        "updated_at": now,
    }
    cal["items"][item_id] = item
    kb.save_calendar(cal)
    return JSONResponse({"ok": True, "item": item})


@app.patch("/api/calendar/{item_id}")
async def api_calendar_update(item_id: str, payload: CalendarItemUpdate):
    """更新日历事项。"""
    cal = kb.load_calendar()
    item = cal.get("items", {}).get(item_id)
    if not item:
        raise HTTPException(404, f"找不到日历事项:{item_id}")

    if payload.title:
        item["title"] = payload.title.strip()
    if payload.date:
        try:
            date.fromisoformat(payload.date)
        except ValueError:
            raise HTTPException(400, f"日期格式错误:{payload.date}")
        item["date"] = payload.date
    if payload.note is not None:
        item["note"] = payload.note
    # 移除/更新关联(P1-2 修复:source_id 不为 None 时更新)
    if payload.source_id is not None:
        item["source_id"] = payload.source_id
        if not payload.source_id:
            # 移除关联:同时清空 source_type/source_title
            item["source_type"] = ""
            item["source_title"] = ""
    item["updated_at"] = datetime.now().isoformat(timespec="seconds")

    cal["items"][item_id] = item
    kb.save_calendar(cal)
    return JSONResponse({"ok": True, "item": item})


@app.delete("/api/calendar/{item_id}")
async def api_calendar_delete(item_id: str):
    """删除日历事项。"""
    cal = kb.load_calendar()
    if item_id not in cal.get("items", {}):
        raise HTTPException(404, f"找不到日历事项:{item_id}")
    del cal["items"][item_id]
    kb.save_calendar(cal)
    return JSONResponse({"ok": True, "deleted": item_id})


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
    """彻底删除一篇文章:source note + summary + raw_text + state 记录 + 关联候选。

    删除前备份 state.json。物理文件直接删除(不可恢复)。
    """
    # 备份
    backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"state_{date.today().isoformat()}.json.bak"
    if kb.STATE_FILE.exists():
        shutil.copy2(kb.STATE_FILE, backup)

    state = kb.load_state()
    if source_id not in state.get("sources", {}):
        raise HTTPException(404, f"找不到 source:{source_id}")
    result = _delete_one(source_id, state)
    kb.save_state(state)
    if not result["ok"]:
        raise HTTPException(500, result.get("error", "删除失败"))
    return JSONResponse(result)


class BatchRequest(BaseModel):
    """批量操作请求。"""
    source_ids: list[str]
    action: str  # archive / delete / favorite / unfavorite / add_tags / generate_summary / extract_suggestions
    tags: list[str] = []  # add_tags 时用


VALID_BATCH_ACTIONS = {
    "archive", "delete", "favorite", "unfavorite",
    "add_tags", "generate_summary", "extract_suggestions",
}


@app.post("/api/batch")
async def api_batch(payload: BatchRequest):
    """批量操作。单条失败不影响其他,返回成功/失败/跳过数量 + 失败项。"""
    if not payload.source_ids:
        raise HTTPException(400, "source_ids 不能为空")
    if payload.action not in VALID_BATCH_ACTIONS:
        raise HTTPException(400, f"非法 action:{payload.action}")

    # 删除操作先备份
    if payload.action == "delete":
        backup_dir = VAULT_ROOT / ".kb" / "logs" / "web_backups"
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
                spath = VAULT_ROOT / sp
                if not spath.exists():
                    results["skipped"] += 1
                    continue
                _, body = _parse_frontmatter(spath.read_text(encoding=ENC))
                ideas = kb_llm.extract_ideas_from_summary(body)
                todos = kb_llm.extract_todos_from_summary(body)
                today = date.today().isoformat()
                for it in ideas:
                    kb._append_section(
                        VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
                        kb._format_idea_suggestion(sid, sources[sid], it, today),
                    )
                for it in todos:
                    kb._append_section(
                        VAULT_ROOT / "04_Plans" / "todo_suggestions.md",
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


# ---------------------------------------------------------------------------
# 搜索 / All Articles / tags API
# ---------------------------------------------------------------------------


@app.get("/api/search")
async def api_search(
    q: str = "",
    reading_status: str = "",
    is_favorite: str = "",
    source_type: str = "",
    tags: str = "",
    has_summary: str = "",
):
    """搜索 + 筛选。"""
    results = _do_search(q, reading_status, is_favorite, source_type, tags, has_summary)
    return JSONResponse({"items": results, "count": len(results)})


@app.get("/api/articles")
async def api_articles():
    """所有文章(含无 summary 的)。"""
    return JSONResponse({"items": _build_all_articles()})


@app.get("/api/article/{source_id}/tags")
async def api_get_tags(source_id: str):
    """获取文章 tags。"""
    return JSONResponse({"source_id": source_id, "tags": _get_article_tags(source_id)})


class TagsRequest(BaseModel):
    tags: list[str]


@app.post("/api/article/{source_id}/tags")
async def api_add_tags(source_id: str, payload: TagsRequest):
    """添加 tags(追加,去重)。"""
    final = _add_article_tags(source_id, payload.tags)
    return JSONResponse({"ok": True, "source_id": source_id, "tags": final})


@app.delete("/api/article/{source_id}/tags/{tag}")
async def api_remove_tag(source_id: str, tag: str):
    """删除单个 tag。"""
    final = _remove_article_tag(source_id, tag)
    return JSONResponse({"ok": True, "source_id": source_id, "tags": final})


@app.post("/api/article/{source_id}/ai-tags")
async def api_ai_tags(source_id: str):
    """AI 推荐标签:基于 summary 生成 3-5 个 tags 并写入。"""
    state = kb.load_state()
    rec = state.get("sources", {}).get(source_id)
    if not rec:
        raise HTTPException(404, f"找不到 source:{source_id}")
    sp = rec.get("summary_path")
    if not sp:
        raise HTTPException(400, "该文章没有 summary,无法推荐标签")
    spath = VAULT_ROOT / sp
    if not spath.exists():
        raise HTTPException(404, f"summary 文件不存在:{sp}")
    _, body = _parse_frontmatter(spath.read_text(encoding=ENC))
    try:
        new_tags = kb_llm.recommend_tags_from_summary(body)
    except Exception as e:
        raise HTTPException(500, f"AI 推荐失败:{e}")
    final = _add_article_tags(source_id, new_tags)
    return JSONResponse({"ok": True, "source_id": source_id, "tags": final, "new_tags": new_tags})


@app.get("/api/health")
async def api_health():
    """健康检查。"""
    return {"ok": True, "vault": str(VAULT_ROOT)}
