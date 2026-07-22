#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/services/state_io.py —— 阅读状态 / 标签 / 删除(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException
from web.utils import ENC, backup_file
import kb
from web.services.parsing import _parse_frontmatter


def _ensure_reading_fields(source_record: dict) -> dict:
    """给单条 source 记录补全阅读状态默认值(不修改原 dict)。"""
    r = dict(source_record)
    r.setdefault("read_later", False)
    r.setdefault("is_favorite", False)
    r.setdefault("last_read_at", None)
    r.setdefault("read_count", 0)
    r.setdefault("reading_status", "to_read")
    r.setdefault("tags", [])
    r.setdefault("collection_ids", [])
    return r

def _save_reading_state(source_id: str, **updates) -> dict:
    """更新某 source 的阅读状态字段,写回 state.json。返回更新后的完整记录。

    updates 只允许 READING_FIELDS 中的键。写前备份。
    全程持 state 锁(v0.4.12),防跨进程并发丢更新。
    """
    for k in updates:
        if k not in READING_FIELDS:
            raise HTTPException(400, f"非法字段:{k}")

    try:
        with kb.state_lock():
            state = kb.load_state()
            kb._check_corrupt(state, "state")
            sources = state.get("sources", {})
            if source_id not in sources:
                raise HTTPException(404, f"找不到 source:{source_id}")

            # 备份(命名带时分秒,避免同日多次写覆盖)
            backup_file(kb.STATE_FILE, "state")

            rec = sources[source_id]
            for k, v in updates.items():
                rec[k] = v

            kb.save_state(state)
            return _ensure_reading_fields(rec)
    except kb.CorruptStoreError:
        raise HTTPException(503, "state.json 损坏,请先运行 kb.py rebuild-index")
    except TimeoutError:
        raise HTTPException(503, "操作并发,请稍后重试")

def _mark_read(source_id: str) -> None:
    """标记已读:last_read_at=now, read_count+1, reading_status=read。失败静默。"""
    try:
        with kb.state_lock():
            state = kb.load_state()
            sources = state.get("sources", {})
            if source_id not in sources:
                return
            rec = sources[source_id]
            rec["last_read_at"] = kb.now_ts()
            rec["read_count"] = int(rec.get("read_count", 0) or 0) + 1
            rec["reading_status"] = "read"
            kb.save_state(state)
    except Exception:
        pass

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
    """设置文章 tags,双写 state.json + summary frontmatter。返回最终 tags。

    全程持 state 锁(v0.4.12)。summary frontmatter 写在锁内(虽是另一文件,但与
    state 双写应原子,避免半完成状态)。
    """
    # 去重保序
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tags:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)

    try:
        with kb.state_lock():
            state = kb.load_state()
            kb._check_corrupt(state, "state")
            sources = state.get("sources", {})
            if source_id not in sources:
                raise HTTPException(404, f"找不到 source:{source_id}")

            # 备份(命名带时分秒,避免同日多次写覆盖)
            backup_file(kb.STATE_FILE, "state")

            # 写 state.json
            sources[source_id]["tags"] = deduped
            kb.save_state(state)

            # 写 summary frontmatter(如果有 summary)
            summary_path = sources[source_id].get("summary_path")
            if summary_path:
                _write_summary_frontmatter_tags(kb.VAULT_ROOT / summary_path, deduped)

            return deduped
    except kb.CorruptStoreError:
        raise HTTPException(503, "state.json 损坏,请先运行 kb.py rebuild-index")
    except TimeoutError:
        raise HTTPException(503, "操作并发,请稍后重试")

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
            p = kb.VAULT_ROOT / sp
            if p.exists():
                p.unlink()
                deleted_files.append(sp)
        # 2. 删 summary
        sump = rec.get("summary_path")
        if sump:
            p = kb.VAULT_ROOT / sump
            if p.exists():
                p.unlink()
                deleted_files.append(sump)
        else:
            summaries_dir = kb.VAULT_ROOT / "02_Summaries"
            if summaries_dir.exists():
                for sf in summaries_dir.rglob("*.md"):
                    try:
                        txt = sf.read_text(encoding=ENC)
                        fm, _ = _parse_frontmatter(txt)
                        if fm.get("source_id") == source_id:
                            sf.unlink()
                            deleted_files.append(str(sf.relative_to(kb.VAULT_ROOT).as_posix()))
                            break
                    except Exception:
                        continue
        # 3. 删 raw_text
        rp = kb.VAULT_ROOT / ".kb" / "raw_text" / f"{source_id}.txt"
        if rp.exists():
            rp.unlink()
            deleted_files.append(str(rp.relative_to(kb.VAULT_ROOT).as_posix()))
        # 4. 删 suggestion 候选块
        for sug_path in [kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md",
                         kb.VAULT_ROOT / "04_Plans" / "todo_suggestions.md"]:
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
            with kb.calendar_lock():
                cal = kb.load_calendar()
                cal_changed = False
                for cal_id, cal_item in list(cal.get("items", {}).items()):
                    if cal_item.get("source_id") == source_id:
                        # 移除关联(source_id 清空),事项本身保留
                        cal_item["source_id"] = ""
                        cal_item["source_type"] = ""
                        cal_item["source_title"] = ""
                        cal_item["updated_at"] = kb.now_ts()
                        cal_changed = True
                if cal_changed:
                    kb.save_calendar(cal)
        except Exception:
            pass  # 日历清理失败不阻断删除

        # 6. 清理 task/event 里指向该 source 的 related_source(v0.4.12 M5)
        try:
            kb.cleanup_source_ref(source_id)
        except Exception:
            pass  # 清理失败不阻断删除

        # 7. 从 state 删记录
        del sources[source_id]
        return {"ok": True, "source_id": source_id, "deleted_files": deleted_files}
    except Exception as e:
        return {"ok": False, "source_id": source_id, "error": str(e), "deleted_files": deleted_files}
