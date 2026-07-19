#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/utils.py —— 共享配置与 helper(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

集中:Vault 路径相关常量、Jinja2 templates、status 白名单、批量 action 白名单,
以及纯函数 _build_hint。路由/服务模块从此处导入共享符号。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from fastapi.templating import Jinja2Templates

import kb

BASE_DIR = Path(__file__).resolve().parent.parent  # scripts/web/utils.py -> scripts/
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"
ENC = "utf-8"

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
READING_FIELDS = ("read_later", "is_favorite", "last_read_at", "read_count", "reading_status", "collection_ids")
VALID_READING_STATUS = ("to_read", "reading", "read")
VALID_BATCH_ACTIONS = {
    "archive", "delete", "favorite", "unfavorite",
    "add_tags", "generate_summary", "extract_suggestions",
}

if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.autoescape = False
else:
    templates = None


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


def backup_file(src: Path, stem: str) -> Path | None:
    """把 src 文件备份到 .kb/logs/web_backups/<stem>_<YYYYMMDD_HHMMSS>.bak。

    命名带时分秒(v0.4.5 修复),同一天多次备份不会互相覆盖。
    返回备份文件路径;src 不存在则返回 None。
    """
    if not src.exists():
        return None
    backup_dir = kb.VAULT_ROOT / ".kb" / "logs" / "web_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{stem}_{ts}.bak"
    shutil.copy2(src, backup)
    return backup