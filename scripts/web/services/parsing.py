#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/services/parsing.py —— frontmatter / suggestion 文件解析(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

from pathlib import Path

from web.utils import ENC

import kb


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 markdown frontmatter(委托给 kb.parsefrontmatter,保证单一真相)。"""
    return kb.parsefrontmatter(text)

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
