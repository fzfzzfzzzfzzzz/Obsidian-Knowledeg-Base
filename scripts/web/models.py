#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/models.py —— Pydantic 请求模型(原 kb_web.py 抽取,v0.4.4 纯搬迁)。"""
from __future__ import annotations

from pydantic import BaseModel


class StatusUpdate(BaseModel):
    status: str
    # v0.4.12: todo 接受时可选填截止日期(YYYY-MM-DD,空串=不填)。idea 端点忽略此字段。
    deadline: str = ""

class IdeaCreate(BaseModel):
    """用户手动新建 idea(进待定队列 idea_suggestions.md)。只需标题。"""
    title: str

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
    category: str = ""  # v0.4.2: 事件类别(todolist/会议/财报/截止日期/发布/比赛/其他/自定义)
    event_id: str = ""  # 来源事件回指(从事件同步到日历时填)

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


class EventCreate(BaseModel):
    """创建事件。"""
    title: str
    date: str  # YYYY-MM-DD
    category: str = "其他"  # 会议/财报/截止日期/发布/比赛/其他
    note: str = ""
    body: str = ""  # 正文 Markdown
    related_source: str = ""  # 可选,关联文章 source_id
    status: str = "active"  # active | done | archived


class EventUpdate(BaseModel):
    """更新事件(空串/None 表示不改)。"""
    title: str = ""
    date: str = ""
    category: str = ""
    note: str = ""
    body: str | None = None  # None=不改,其余(含空串)=更新正文
    status: str = ""
    related_source: str | None = None  # None=不改


class ChecklistItem(BaseModel):
    """Checklist 单项。"""
    id: str
    text: str
    done: bool = False


class TaskCreate(BaseModel):
    """创建任务."""
    title: str
    category: str = "其他"  # 开发/调研/写作/阅读/整理/其他
    project: str = ""  # 所属项目(业务上区别于任务标题)
    status: str = "active"  # active | done | blocked | archived
    priority: str = ""  # P0/P1/P2/P3 或 高/中/低
    deadline: str = ""  # YYYY-MM-DD,可空
    blocker: str = ""  # 当前问题/阻塞
    next_action: str = ""  # 下一步行动
    body: str = ""  # 正文 Markdown
    checklist: list[ChecklistItem] = []  # 子任务清单
    related_source: str = ""  # 可选,关联文章 source_id


class TaskUpdate(BaseModel):
    """更新任务(None=不改,提供值含空串=更新为该值)。

    与 EventUpdate 语义不同:这里统一规则更清晰。
    checklist 用 list:None=不改,list(含空 list)=替换整个清单。
    """
    title: str | None = None
    category: str | None = None
    project: str | None = None
    status: str | None = None
    priority: str | None = None
    deadline: str | None = None
    blocker: str | None = None
    next_action: str | None = None
    body: str | None = None
    checklist: list[ChecklistItem] | None = None
    related_source: str | None = None


class ChecklistItemUpdate(BaseModel):
    """单项打勾(只改 done 或 text)。"""
    done: bool | None = None
    text: str | None = None
