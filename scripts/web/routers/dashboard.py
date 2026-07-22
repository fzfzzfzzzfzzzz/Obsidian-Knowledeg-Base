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
    _build_workspace_overview,
    _build_reminders,
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


@router.get("/api/workspace/overview")
async def api_workspace_overview():
    """工作台本周概览:阅读进度 / 任务完成数 / 任务创建数 / 提醒摘要。

    实时聚合,不落盘。本周窗口用 ISO 周(周一~周日),与 kb_date 时区语义一致。
    """
    return JSONResponse(_build_workspace_overview())


@router.get("/api/workspace/reminders")
async def api_workspace_reminders():
    """工作台智能提醒:所有 active 任务中带 deadline 的项,按 urgency 排序。

    urgency: overdue / due_today / due_this_week / later。
    只覆盖任务 deadline;事件/日历请另行请求对应接口。
    """
    return JSONResponse({"items": _build_reminders()})


def _auto_pick_current_task(tasks: list[dict]) -> dict | None:
    """自动挑选当前任务:优先 active 状态且 deadline 最近的任务。"""
    active = [t for t in tasks if t.get("status") == "active"]
    if not active:
        return None
    # 有 deadline 的按 deadline 升序,无 deadline 的排最后
    active.sort(key=lambda t: t.get("deadline") or "9999")
    return active[0]


@router.get("/api/workspace/current_task")
async def api_workspace_current_task():
    """获取当前聚焦任务。未指定时按规则自动挑选;若存储的任务已删除也自动回退。"""
    state = kb.load_workspace_state()
    tasks = kb.scan_tasks()
    current_id = state.get("current_task_id", "")
    if current_id:
        path = kb._find_task_file(current_id)
        if path is not None:
            return JSONResponse({"task": kb.load_task_file(path), "auto": False})
    # 未指定或已删除,自动挑选
    picked = _auto_pick_current_task(tasks)
    return JSONResponse({"task": picked, "auto": True})


@router.patch("/api/workspace/current_task")
async def api_workspace_set_current_task(payload: dict[str, Any]):
    """设置当前聚焦任务。task_id 为空串表示取消手动指定(下次 GET 自动挑选)。"""
    task_id = payload.get("task_id", "")
    if task_id:
        path = kb._find_task_file(task_id)
        if path is None:
            raise HTTPException(404, f"找不到任务:{task_id}")
    state = kb.load_workspace_state()
    state["current_task_id"] = task_id
    kb.save_workspace_state(state)
    return JSONResponse({"ok": True, "current_task_id": task_id})


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
