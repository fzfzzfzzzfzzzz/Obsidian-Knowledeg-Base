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

import kb
from fastapi import FastAPI
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
)

# 直接拷贝 kb.VAULT_ROOT(import-time 副本),供测试 reload / isolate_vault 同步。
VAULT_ROOT = kb.VAULT_ROOT

app = FastAPI(title="Obsidian KB Reader")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# --- 装配各域 router ---
app.include_router(dashboard.router)
app.include_router(articles.router)
app.include_router(ideas.router)
app.include_router(todos.router)
app.include_router(calendar.router)
app.include_router(collections.router)
app.include_router(search.router)
app.include_router(tags.router)
app.include_router(ingest.router)


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
