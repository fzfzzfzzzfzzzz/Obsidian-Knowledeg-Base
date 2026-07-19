#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/services/status.py —— suggestion 状态更新(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException
from web.utils import ENC
import kb


def _check_suggestion_current_status(path: Path, kind: str, item_id: str) -> str | None:
    """读取指定 item_id 块的当前 status。块不存在返回 None。"""
    if not path.exists():
        return None
    text = path.read_text(encoding=ENC)
    blocks = kb._split_suggestion_blocks(text, kind)
    for raw, meta, body in blocks:
        if meta.get("id") == item_id or meta.get("id", "").endswith(item_id):
            return meta.get("status", "").strip()
    return None

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
    backup_dir = kb.VAULT_ROOT / ".kb" / "logs" / "web_backups"
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
    deleted = False
    new_blocks: list[str] = []
    for raw, meta, body in raw_blocks:
        if meta.get("id") == item_id or meta.get("id", "").endswith(item_id):
            found = True
            if new_status == "rejected":
                # 拒绝 = 直接删除该块(不 append),而非标成 rejected 保留
                deleted = True
                continue
            # 替换该块的 status 行
            old_status = meta.get("status", "pending_review")
            updated = re.sub(
                r"^(-\s*status:\s*)" + re.escape(old_status) + r"\s*$",
                rf"\g<1>{new_status}",
                raw,
                flags=re.MULTILINE,
            )
            new_blocks.append(updated)
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

    return {"ok": True, "id": item_id, "new_status": new_status, "deleted": deleted}
