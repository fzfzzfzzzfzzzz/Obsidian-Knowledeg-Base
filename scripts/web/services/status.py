#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/services/status.py —— suggestion 状态更新(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException
from web.utils import ENC, backup_file
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

    # 备份(命名带时分秒,避免同日多次改覆盖)
    backup_file(path, path.stem)

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


def accept_and_move(
    kind: str,
    item_id: str,
    new_status: str,
    sug_path,
    valid_set: set,
    move_func,
) -> dict:
    """接受即搬运的事务化封装(v0.4.5)。

    流程(全程持文件锁,避免 TOCTOU):
      1. 检查当前 status:已 moved → no-op(幂等)
      2. 改 status 为 new_status(accepted_*)
      3. 调 move_func(item_id) 搬运
      4. 搬运抛错 → 回滚 status 到原值,返回 move_error(避免卡在 accepted_*)

    参数:
        kind: "Idea Suggestion" / "Todo Suggestion"
        item_id: suggestion 块 id
        new_status: 目标 status(以 accepted_ 开头才触发搬运)
        sug_path: suggestion 文件路径
        valid_set: 合法 status 集合(白名单)
        move_func: kb.move_accepted_idea 或 kb.move_accepted_todo
    """
    # 用 suggestion 文件路径作为锁的基础(同文件互斥)
    lock_path = kb.VAULT_ROOT / ".kb" / "logs" / f"sug_{sug_path.stem}.lock"
    try:
        with kb._file_lock(lock_path, timeout=5.0):
            # 1. 幂等检查
            pre_status = _check_suggestion_current_status(sug_path, kind, item_id)
            if pre_status == "moved" and new_status.startswith("accepted_"):
                return {
                    "ok": True, "id": item_id, "new_status": "moved",
                    "deleted": False, "moved": False, "move_reason": "already_moved",
                }

            # 2. 改 status(若 new_status 不是 accepted_*,直接走原逻辑,不进事务)
            if not new_status.startswith("accepted_"):
                return _update_suggestion_status(
                    sug_path, kind, item_id, new_status, valid_set
                )

            # 3. 改 status + 搬运(事务)
            original_status = pre_status or "pending_review"
            result = _update_suggestion_status(
                sug_path, kind, item_id, new_status, valid_set
            )
            if result.get("deleted"):
                # rejected 走删块,不搬运
                return result

            try:
                move_result = move_func(item_id)
                result["moved"] = move_result.get("moved", False)
                if move_result.get("moved"):
                    result["moved_to"] = move_result.get("target")
                    # idea 用 area,todo 用 plan,都复制到结果
                    if "area" in move_result:
                        result["area"] = move_result["area"]
                    if "plan" in move_result:
                        result["plan"] = move_result["plan"]
                else:
                    result["move_reason"] = move_result.get("reason")
            except Exception as e:
                # 搬运失败:回滚 status 到原值,避免卡死在 accepted_*
                try:
                    kb._rewrite_suggestion_file(
                        kind, {item_id: original_status}
                    )
                except Exception as rollback_err:
                    # 回滚也失败就告知用户
                    result["rollback_error"] = str(rollback_err)
                result["moved"] = False
                result["move_error"] = str(e)
                result["rolled_back_to"] = original_status
            return result
    except TimeoutError as e:
        return {
            "ok": False, "id": item_id, "error": f"操作并发,请重试:{e}",
            "deleted": False, "moved": False,
        }
