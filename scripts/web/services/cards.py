#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/services/cards.py —— 卡片 / dashboard / 收藏夹 / 搜索构建(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException
from web.utils import ENC
import kb
import kb_llm
from web.services.parsing import _parse_frontmatter
from web.services.state_io import _ensure_reading_fields, _get_article_tags


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
        "collection_ids": rec.get("collection_ids", []),
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

def _get_collections(state: dict) -> dict[str, dict]:
    """从 state 取 collections 字典,不存在则返回空 dict(不修改 state)。"""
    cols = state.get("collections")
    if not isinstance(cols, dict):
        return {}
    return cols

def _migrate_default_collection(state: dict) -> bool:
    """一次性迁移:若 state 无 collections,且存在 is_favorite=true 的文章,
    自动建一个「默认收藏夹」把它们放进去。返回是否有改动。
    """
    if state.get("collections") is not None:
        return False  # 已初始化过(哪怕为空)
    fav_ids = [
        sid for sid, rec in state.get("sources", {}).items()
        if rec.get("is_favorite")
    ]
    state["collections"] = {}
    if fav_ids:
        import uuid
        col_id = "col_" + uuid.uuid4().hex[:10]
        state["collections"][col_id] = {
            "id": col_id,
            "name": "默认收藏夹",
            "created_at": date.today().isoformat(),
            "source_ids": fav_ids,
        }
        # 反向写回 source.collection_ids
        for sid in fav_ids:
            state["sources"][sid].setdefault("collection_ids", [])
            if col_id not in state["sources"][sid]["collection_ids"]:
                state["sources"][sid]["collection_ids"].append(col_id)
    return True

def _build_collections_list() -> list[dict[str, Any]]:
    """所有收藏夹文件夹 + 每个的文章数。含一次性迁移。"""
    state = kb.load_state()
    if _migrate_default_collection(state):
        kb.save_state(state)
    cols = _get_collections(state)
    items = []
    for cid, col in cols.items():
        # source_ids 里过滤掉已不存在的 source(防孤儿)
        valid = [s for s in col.get("source_ids", []) if s in state.get("sources", {})]
        items.append({
            "id": cid,
            "name": col.get("name", "(未命名)"),
            "created_at": col.get("created_at", ""),
            "count": len(valid),
            "source_ids": valid,
        })
    items.sort(key=lambda x: x.get("created_at", ""))
    return items

def _build_collection_articles(col_id: str) -> list[dict[str, Any]]:
    """某个收藏夹内的文章卡片(含无 summary 的,因为收藏夹要能看到全部)。"""
    state = kb.load_state()
    cols = _get_collections(state)
    col = cols.get(col_id)
    if not col:
        return []
    sources = state.get("sources", {})
    cards = []
    for sid in col.get("source_ids", []):
        rec = sources.get(sid)
        if rec:
            cards.append(_summary_card_from_source(sid, rec))
    return cards

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
            spath = kb.VAULT_ROOT / sp
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

def _scan_summaries() -> list[dict[str, Any]]:
    """扫描 02_Summaries/ 下所有 summary,返回卡片元数据列表(按日期降序)。"""
    summaries_dir = kb.VAULT_ROOT / "02_Summaries"
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
                "path": str(sf.relative_to(kb.VAULT_ROOT).as_posix()),
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
    sn_path = kb.VAULT_ROOT / rec.get("path", "") if rec.get("path") else None
    if sn_path and sn_path.exists():
        try:
            sn_meta, _ = _parse_frontmatter(sn_path.read_text(encoding=ENC))
            source_url = sn_meta.get("source_url", "").strip()
        except Exception:
            pass

    summaries_dir = kb.VAULT_ROOT / "02_Summaries"
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
                    "path": str(sf.relative_to(kb.VAULT_ROOT).as_posix()),
                    "has_summary": True,
                    "source_url": source_url,
                }

    # 2. 回退:读 source note 原文
    state = kb.load_state()
    sources = state.get("sources", {})
    if source_id not in sources:
        raise HTTPException(404, f"找不到 source_id={source_id}")
    rec = sources[source_id]
    source_path = kb.VAULT_ROOT / rec.get("path", "")
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
        "path": str(source_path.relative_to(kb.VAULT_ROOT).as_posix()),
        "has_summary": False,
        "source_url": source_url,
    }
