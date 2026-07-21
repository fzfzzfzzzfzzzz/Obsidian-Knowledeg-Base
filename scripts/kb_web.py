#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kb_web.py —— 知识库阅读前端(FastAPI)v0.4.4 重构后仅负责装配。

路由按域拆分到 web/routers/*,业务 helper 拆分到 web/services/*,
Pydantic 模型在 web/models.py,共享常量/templates 在 web/utils.py。
本文件只做:app 创建、static 挂载、include_router 装配、向后兼容 re-export。

启动:python scripts/kb.py serve
路由:
    页面: /  /summary/{id}  /ideas  /todos  /recent  /favorites  /articles
          /calendar  /search  /submit
    API:  /api/* (见各 router 文件)
"""

from __future__ import annotations

import os
import secrets

import kb
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from web.utils import TEMPLATES_DIR, STATIC_DIR
from web.routers import (
    dashboard,
    articles,
    ideas,
    todos,
    calendar,
    collections,
    search,
    tags,
    ingest,
    events,
    tasks,
)

# 直接拷贝 kb.VAULT_ROOT(import-time 副本),供测试 reload / isolate_vault 同步。
VAULT_ROOT = kb.VAULT_ROOT

app = FastAPI(title="Obsidian KB Reader")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# 可选 Basic Auth(v0.4.6)
# ---------------------------------------------------------------------------
# 通过环境变量 KB_WEB_USER / KB_WEB_PASSWORD 控制:
# - 都未设置 → 无 auth(pass-through,本地默认)
# - 都设置 → 所有路由强制 Basic Auth
# 用于云端部署 / host=0.0.0.0 场景防止未授权访问。
_security = HTTPBasic(auto_error=False)


async def _maybe_auth(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    """未配置 auth 时直接放行;配置了则校验 Basic Auth。

    每次请求时读环境变量(而非 import-time),便于测试 monkeypatch.setenv 切换。
    """
    user = os.environ.get("KB_WEB_USER")
    password = os.environ.get("KB_WEB_PASSWORD")
    if not (user and password):
        return  # 未配置 auth,放行
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="需要 Basic Auth(在请求头加 Authorization: Basic <base64(user:pass)>)",
            headers={"WWW-Authenticate": "Basic"},
        )
    # secrets.compare_digest 防 timing attack
    user_ok = secrets.compare_digest(credentials.username.encode(), user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Basic"},
        )


# --- 装配各域 router(全部加可选 auth dependency)---
# 始终挂 dependency,内部判断是否真的校验(便于运行时切换)
_auth_deps = [Depends(_maybe_auth)]
app.include_router(dashboard.router, dependencies=_auth_deps)
app.include_router(articles.router, dependencies=_auth_deps)
app.include_router(ideas.router, dependencies=_auth_deps)
app.include_router(todos.router, dependencies=_auth_deps)
app.include_router(calendar.router, dependencies=_auth_deps)
app.include_router(collections.router, dependencies=_auth_deps)
app.include_router(search.router, dependencies=_auth_deps)
app.include_router(tags.router, dependencies=_auth_deps)
app.include_router(ingest.router, dependencies=_auth_deps)
app.include_router(events.router, dependencies=_auth_deps)
app.include_router(tasks.router, dependencies=_auth_deps)


# ---------------------------------------------------------------------------
# 向后兼容 re-export(现有测试通过 kb_web.X 访问以下符号)
# ---------------------------------------------------------------------------
from web.utils import _build_hint  # noqa: E402,F401
from web.models import (  # noqa: E402,F401
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
from web.routers.ideas import _parse_formal_ideas  # noqa: E402,F401
from web.routers.todos import _parse_formal_todos  # noqa: E402,F401
from web.routers.calendar import _resolve_category  # noqa: E402,F401
