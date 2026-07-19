#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/models.py —— Pydantic 请求模型(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

from pydantic import BaseModel


class StatusUpdate(BaseModel):
    status: str

class IngestRequest(BaseModel):
    """投稿请求:多个文本片段(URL 或正文)。"""
    items: list[str]
    auto_summary: bool = True

class GenerateIdeasRequest(BaseModel):
    prompt: str = ""
    priority: str = ""  # "" / P0 / P1 / P2 / P3
    area: str = ""  # "" / research / productivity / product / ai_agent / web_design / other

class GenerateTodosRequest(BaseModel):
    prompt: str = ""
    priority: str = ""  # "" / P0 / P1 / P2 / P3
    difficulty: str = ""  # "" / low / medium / high
    estimated_time: str = ""  # "" / 30min / 1h / 2-4h / 半天 / 1-2 天
    plan: str = ""  # "" / weekly / monthly / someday

class CalendarItemCreate(BaseModel):
    title: str
    date: str  # YYYY-MM-DD
    note: str = ""
    source_id: str = ""
    source_type: str = ""
    source_title: str = ""
    detected_date_id: str = ""
    date_source: str = "manual"  # detected | manual
    date_confidence: str = ""
    category: str = ""  # v0.4.2: 事件类别(todolist/会议/财报/截止日期/发布/其他/自定义)

class CalendarItemUpdate(BaseModel):
    title: str = ""
    date: str = ""
    note: str = ""
    source_id: str | None = None  # None=不改,None 以外的值(含空串)=更新关联
    category: str | None = None  # v0.4.2: None=不改,其余(含空串)=更新类别

class CollectionNameRequest(BaseModel):
    name: str

class ArticleCollectionsRequest(BaseModel):
    collection_ids: list[str]

class BatchRequest(BaseModel):
    """批量操作请求。"""
    source_ids: list[str]
    action: str  # archive / delete / favorite / unfavorite / add_tags / generate_summary / extract_suggestions
    tags: list[str] = []  # add_tags 时用

class TagsRequest(BaseModel):
    tags: list[str]
