#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/dashboard.py —— 路由(原 kb_web.py 抽取,v0.4.4 纯搬迁)。

职责:首页仪表盘:GET / + /api/dashboard* + /api/recent + /api/health
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


@router.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    """首页:个人工作台(idea/时间线/活动/推荐文章卡片)。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在,请检查安装", 500)
    return templates.TemplateResponse(
        request,
        "workspace.html",
        {"active_nav": "index"},
    )


@router.get("/kb", response_class=HTMLResponse)
async def page_knowledge_base(request: Request):
    """知识库页:未读/已读/稍后阅读 summary 卡片仪表盘(原首页内容)。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在,请检查安装", 500)
    return templates.TemplateResponse(
        request,
        "knowledge_base.html",
        {"active_nav": "kb"},
    )

@router.get("/api/dashboard")
async def api_dashboard():
    """首页:未读/已读统计 + 稍后读列表。"""
    return JSONResponse(_build_dashboard())

@router.get("/api/dashboard_full")
async def api_dashboard_full():
    """首页:按 reading_status 分组的文章列表(未读/已读,只含有 summary 的)。"""
    cards = _summary_cards_only()
    unread = [c for c in cards if c["reading_status"] in ("to_read", "reading")]
    read = [c for c in cards if c["reading_status"] == "read"]
    unread.sort(key=lambda x: x.get("summarized_at") or "", reverse=True)
    read.sort(key=lambda x: x.get("last_read_at") or "", reverse=True)
    return JSONResponse({"unread": unread, "read": read})

@router.get("/api/recent")
async def api_recent():
    """最近阅读 30 篇(按 last_read_at 倒序)。"""
    return JSONResponse({"items": _build_recent()})

@router.get("/api/health")
async def api_health():
    """健康检查。"""
    return {"ok": True, "vault": str(kb.VAULT_ROOT)}


# /api/shutdown 需要的延迟退出逻辑;独立函数便于测试 monkeypatch
def _schedule_exit(delay: float = 0.5) -> None:
    """delay 秒后 os._exit(0),让当前响应先发回客户端。"""
    import os
    import threading
    threading.Timer(delay, lambda: os._exit(0)).start()


# loopback 白名单(与 kb.cmd_serve 的 safe_hosts 保持同语义)
# /api/shutdown 只允许「服务绑定 loopback 且请求来自 loopback」时调用,
# 双校验防两类场景:
#   - bind 非 loopback:服务暴露到外网,即便请求从 127.0.0.1 进来(反向代理/隧道)也拒绝
#   - client 非 loopback:本地绑定但被外部打到(理论上不会发生,防御性)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", ""}


def _shutdown_allowed(bind_host: str, client_host: str) -> bool:
    """/api/shutdown 是否允许执行。纯函数,便于单测。"""
    return bind_host in _LOOPBACK_HOSTS and client_host in _LOOPBACK_HOSTS


@router.post("/api/shutdown")
async def api_shutdown(request: Request):
    """关闭知识库服务(供网页内"关闭"按钮调用)。

    延迟 0.5s 退出进程,让本响应先发回客户端。
    走 router 级 _maybe_auth,云端 Basic Auth 场景同样受保护。

    host 白名单:**仅当服务绑定到 loopback 且请求来自 loopback 时**才允许关闭。
    服务绑定到 0.0.0.0 / 外网 IP 时一律 403 —— 那种场景应通过进程管理器(systemd/pm2)
    关闭,而不是允许任意能访问页面的人(即便有 Basic Auth)远程杀进程。
    本地默认 `kb.py serve`(host=127.0.0.1)和 start_kb.vbs 都满足白名单。
    """
    bind_host = getattr(request.app.state, "bind_host", "127.0.0.1")
    client_host = request.client.host if request.client else ""
    if not _shutdown_allowed(bind_host, client_host):
        return JSONResponse(
            {
                "ok": False,
                "error": "shutdown_not_allowed",
                "message": (
                    f"远程关闭未启用(bind={bind_host}, client={client_host})。"
                    "服务绑定到非 loopback 地址时请用进程管理器关闭。"
                ),
            },
            status_code=403,
        )
    _schedule_exit(0.5)
    return JSONResponse({"ok": True, "message": "知识库正在关闭..."})
