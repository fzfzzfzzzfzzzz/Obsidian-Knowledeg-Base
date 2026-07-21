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
VALID_EVENT_STATUS = {
    "active",
    "done",
    "archived",
}
# 事件分类(与日历 category 共享,同步时直接透传)。允许自定义,不强制白名单。
VALID_EVENT_CATEGORIES = {"会议", "财报", "截止日期", "发布", "比赛", "其他"}
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


# —— XSS 消毒(v0.4.6) ——
# summary 正文经 markdown.markdown 渲染后含原始 HTML(用户投稿可能带 <script> 等),
# 必须在 innerHTML 前消毒。用 bleach 而非手写正则(手写不可靠)。

ALLOWED_HTML_TAGS = {
    # 文本结构
    "p", "br", "hr", "span", "div",
    # 标题
    "h1", "h2", "h3", "h4", "h5", "h6",
    # 文字格式
    "strong", "b", "em", "i", "u", "del", "sub", "sup", "mark", "small",
    # 引用
    "blockquote", "q", "cite",
    # 列表
    "ul", "ol", "li", "dl", "dt", "dd",
    # 代码
    "code", "pre", "kbd", "samp",
    # 表格
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    # 链接/图片
    "a", "img",
}

ALLOWED_HTML_ATTRS = {
    "a": ["href", "title", "name"],
    "img": ["src", "alt", "title", "width", "height"],
    # codehilite 加的 class
    "code": ["class"],
    "pre": ["class"],
    "div": ["class"],
    "span": ["class"],
    "th": ["align"],
    "td": ["align"],
}


def sanitize_html(html: str) -> str:
    """用 bleach 消毒 HTML,只保留白名单标签和属性。

    - script / style / iframe 等危险标签被剥离
    - 所有 on* 事件属性(onerror/onclick/...)被剥离
    - javascript: 协议被拒
    bleach 不可用时退化为粗暴 strip(只剩纯文本)。
    """
    try:
        import bleach
        return bleach.clean(
            html,
            tags=ALLOWED_HTML_TAGS,
            attributes=ALLOWED_HTML_ATTRS,
            protocols=["http", "https", "mailto", "ftp"],
            strip=True,
        )
    except ImportError:
        # bleach 缺失时退化为去标签(避免完全无防护)
        import re
        return re.sub(r"<[^>]+>", "", html)