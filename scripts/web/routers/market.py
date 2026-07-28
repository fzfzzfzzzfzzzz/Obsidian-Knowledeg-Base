#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/market.py —— 市场(自选股/异动 + 市场聚合视图)路由。

职责:
    页面:GET /market                          「市场」单页(5 板块聚合)
    市场 CRUD:GET/POST /api/market, GET/PATCH/DELETE /api/market/{id}
    复用聚合(只读,无新存储):
        GET /api/market/earnings              财报日历(calendar+events 按 category==财报)
        GET /api/market/materials             收藏资料(「金融」收藏夹内文章)
        GET /api/market/linked-tasks          关联任务(tasks 按 category==金融)

市场条目存 08_Market/market_*.md,kind 字段区分 watchlist(自选股)/ alert(异动)。
异动纯手动录入,无外部行情数据源(离线优先)。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from web.utils import ENC, templates, VALID_EVENT_STATUS
from web.models import MarketCreate, MarketUpdate
from web.services.cards import _build_collections_list, _build_collection_articles

import kb

router = APIRouter()

# 板块4「收藏资料」依赖的收藏夹名(聚合时按名查找,避免硬编码 col_id)
FINANCE_COLLECTION_NAME = "金融"
# 板块2「财报日历」/ 板块5「关联任务」的 category 关键字
EARNINGS_CATEGORY = "财报"
FINANCE_CATEGORY = "金融"


@router.get("/market", response_class=HTMLResponse)
async def page_market(request: Request):
    """市场页面:自选股/异动/财报日历/收藏资料/关联任务 5 板块聚合。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "market.html", {"active_nav": "market"}
    )


# ---------------------------------------------------------------------------
# 市场 CRUD(watchlist / alert 共用)
# ---------------------------------------------------------------------------

@router.get("/api/market")
async def api_market_list(kind: str | None = None):
    """所有市场条目,可选 ?kind=watchlist|alert 过滤。

    排序:alert 按日期倒序在前,watchlist 按标题序在后(scan_market 已处理)。
    """
    if kind and kind not in kb.MARKET_KINDS:
        raise HTTPException(400, f"非法 kind 值:{kind}(需 {kb.MARKET_KINDS})")
    return JSONResponse({"items": kb.scan_market(kind=kind)})


# ---------------------------------------------------------------------------
# 复用聚合接口(只读,过滤现有数据,无新存储)
# 注意:字面子路径(earnings/materials/linked-tasks)必须声明在
#       /api/market/{market_id} 之前,否则会被 {market_id} 捕获。
# ---------------------------------------------------------------------------

@router.get("/api/market/earnings")
async def api_market_earnings():
    """财报日历:calendar items + events 中 category==财报 的项(按日期升序)。

    返回 {calendar:[...], events:[...]}。calendar 项可能由事件同步而来,
    与 events 可能有重叠(前端按 event_id 去重展示)。
    """
    today_str = date.today().isoformat()
    # 日历项
    cal = kb.load_calendar()
    cal_items = [
        {
            "id": it.get("id", ""),
            "title": it.get("title", ""),
            "date": it.get("date", ""),
            "note": it.get("note", ""),
            "source_id": it.get("source_id", ""),
            "event_id": it.get("event_id", ""),
            "where": "calendar",
        }
        for it in cal.get("items", {}).values()
        if it.get("category") == EARNINGS_CATEGORY
    ]
    # 事件
    ev_items = [
        {
            "id": e.get("id", ""),
            "title": e.get("title", ""),
            "date": e.get("date", ""),
            "note": e.get("note", ""),
            "where": "event",
        }
        for e in kb.scan_events()
        if e.get("category") == EARNINGS_CATEGORY and e.get("status") == "active"
    ]
    # 各自按日期升序
    cal_items.sort(key=lambda x: x["date"] or "9999")
    ev_items.sort(key=lambda x: x["date"] or "9999")
    return JSONResponse({"calendar": cal_items, "events": ev_items, "today": today_str})


@router.get("/api/market/materials")
async def api_market_materials():
    """收藏资料:「金融」收藏夹内的文章卡片(含无 summary 的)。

    若无「金融」收藏夹则返回空列表(不报错)。前端可引导用户创建。
    """
    fin_id = ""
    for col in _build_collections_list():
        if col.get("name") == FINANCE_COLLECTION_NAME:
            fin_id = col["id"]
            break
    if not fin_id:
        return JSONResponse({"items": [], "collection_id": ""})
    cards = _build_collection_articles(fin_id)
    return JSONResponse({"items": cards, "collection_id": fin_id})


@router.get("/api/market/linked-tasks")
async def api_market_linked_tasks():
    """关联任务:tasks 中 category==金融 的项(按 deadline 升序)。"""
    items = [t for t in kb.scan_tasks() if t.get("category") == FINANCE_CATEGORY]
    return JSONResponse({"items": items})


# ---------------------------------------------------------------------------
# 市场 CRUD(watchlist / alert 共用)—— 放在聚合字面路径之后,确保
# /api/market/{market_id} 不会吞掉 earnings/materials/linked-tasks。
# ---------------------------------------------------------------------------

@router.post("/api/market")
async def api_market_create(payload: MarketCreate):
    """创建市场条目,写 markdown 到 08_Market/。"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    if payload.kind not in kb.MARKET_KINDS:
        raise HTTPException(400, f"非法 kind 值:{payload.kind}")
    if payload.status not in VALID_EVENT_STATUS:
        raise HTTPException(400, f"非法 status 值:{payload.status}")
    # alert 必须有合法日期;watchlist 的 date 字段忽略
    if payload.kind == "alert":
        if not payload.date:
            raise HTTPException(400, "异动必须填日期")
        try:
            date.fromisoformat(payload.date)
        except ValueError:
            raise HTTPException(400, f"日期格式错误:{payload.date}(需 YYYY-MM-DD)")
        # direction 非空时必须在白名单(up/down/flat)
        direction = payload.direction.strip().lower()
        if direction and direction not in kb.MARKET_DIRECTIONS:
            raise HTTPException(400, f"非法 direction 值:{direction}(需 {', '.join(kb.MARKET_DIRECTIONS)})")

    # watchlist 校验市场 + ticker(后续要调 API,代码必须规范)
    market_code = ""
    ticker_stored = ""
    if payload.kind == "watchlist":
        market_code = payload.market.strip().upper()
        if market_code and market_code not in kb.MARKET_CODES:
            raise HTTPException(400, f"非法市场:{market_code}(支持 {', '.join(kb.MARKET_CODES)})")
        # ticker 非必填,但填了就必须对(配合市场)
        err = kb.validate_ticker(market_code, payload.ticker)
        if err:
            raise HTTPException(400, err)
        try:
            ticker_stored = kb.normalize_ticker(market_code, payload.ticker)
        except ValueError as e:
            raise HTTPException(400, str(e))

    market_id = kb.make_market_id(title, payload.kind)
    path = kb._market_file_path(market_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():  # 极小概率冲突
        market_id = kb.make_market_id(title + str(date.today()), payload.kind)
        path = kb._market_file_path(market_id)

    meta = {
        "id": market_id,
        "kind": payload.kind,
        "title": title,
        "market": market_code,
        "ticker": ticker_stored,
        "sector": payload.sector.strip(),
        "date": payload.date.strip(),
        "trigger": payload.trigger.strip(),
        "direction": direction if payload.kind == "alert" else "",
        "magnitude": payload.magnitude.strip() if payload.kind == "alert" else "",
        "cost_price": payload.cost_price.strip() if payload.kind == "watchlist" else "",
        "shares": payload.shares.strip() if payload.kind == "watchlist" else "",
        "target_price": payload.target_price.strip() if payload.kind == "watchlist" else "",
        "stop_price": payload.stop_price.strip() if payload.kind == "watchlist" else "",
        "note": payload.note.strip(),
        "status": payload.status,
    }
    kb.write_market_file(path, meta, "", is_new=True)
    return JSONResponse({"ok": True, "market": kb.load_market_file(path)})


@router.get("/api/market/{market_id}")
async def api_market_get(market_id: str):
    """获取单个市场条目详情(含正文)。"""
    path = kb._find_market_file(market_id)
    if path is None:
        raise HTTPException(404, f"找不到市场条目:{market_id}")
    return JSONResponse(kb.load_market_file(path))


def _update_market_fields(item: dict, payload: MarketUpdate) -> dict:
    """把非 None 更新值合并进 market dict,返回新 meta(供 write_market_file)。

    watchlist 的 market/ticker 联合校验:用更新后的最终值(本次 payload + 原值兜底)
    一起校验,保证改完后仍是合法组合。
    """
    meta = {k: v for k, v in item.items() if k not in ("body", "path")}
    if payload.title is not None and payload.title.strip():
        meta["title"] = payload.title.strip()
    if payload.sector is not None:
        meta["sector"] = payload.sector.strip()
    if payload.date is not None:
        d = payload.date.strip()
        if d:
            try:
                date.fromisoformat(d)
            except ValueError:
                raise HTTPException(400, f"日期格式错误:{d}")
        meta["date"] = d
    if payload.trigger is not None:
        meta["trigger"] = payload.trigger.strip()
    if payload.note is not None:
        meta["note"] = payload.note.strip()
    if payload.status is not None:
        if payload.status not in VALID_EVENT_STATUS:
            raise HTTPException(400, f"非法 status 值:{payload.status}")
        meta["status"] = payload.status

    # alert 专属:direction / magnitude(direction 非空必须在白名单)
    if meta.get("kind") == "alert":
        if payload.direction is not None:
            d = payload.direction.strip().lower()
            if d and d not in kb.MARKET_DIRECTIONS:
                raise HTTPException(400, f"非法 direction 值:{d}(需 {', '.join(kb.MARKET_DIRECTIONS)})")
            meta["direction"] = d
        if payload.magnitude is not None:
            meta["magnitude"] = payload.magnitude.strip()

    # watchlist 专属:持仓位置字段(纯 str 存储,无校验)
    if meta.get("kind") == "watchlist":
        if payload.cost_price is not None:
            meta["cost_price"] = payload.cost_price.strip()
        if payload.shares is not None:
            meta["shares"] = payload.shares.strip()
        if payload.target_price is not None:
            meta["target_price"] = payload.target_price.strip()
        if payload.stop_price is not None:
            meta["stop_price"] = payload.stop_price.strip()

    # watchlist 的 market/ticker 联合校验(以更新后最终值为准)
    if meta.get("kind") == "watchlist":
        final_market = (payload.market.strip().upper() if payload.market is not None
                        else meta.get("market", ""))
        if payload.market is not None:
            if final_market and final_market not in kb.MARKET_CODES:
                raise HTTPException(400, f"非法市场:{final_market}(支持 {', '.join(kb.MARKET_CODES)})")
            meta["market"] = final_market
        # ticker 改动或 market 改动时,以最终 market 重新校验+规范化
        if payload.ticker is not None or payload.market is not None:
            final_raw = payload.ticker if payload.ticker is not None else meta.get("ticker", "")
            err = kb.validate_ticker(final_market, final_raw)
            if err:
                raise HTTPException(400, err)
            try:
                meta["ticker"] = kb.normalize_ticker(final_market, final_raw)
            except ValueError as e:
                raise HTTPException(400, str(e))
    return meta


@router.patch("/api/market/{market_id}")
async def api_market_update(market_id: str, payload: MarketUpdate):
    """更新市场条目字段(None=不改,空串=清空)。"""
    path = kb._find_market_file(market_id)
    if path is None:
        raise HTTPException(404, f"找不到市场条目:{market_id}")
    item = kb.load_market_file(path)
    meta = _update_market_fields(item, payload)
    body = item.get("body", "")
    kb.write_market_file(path, meta, body, is_new=False)
    return JSONResponse({"ok": True, "market": kb.load_market_file(path)})


@router.delete("/api/market/{market_id}")
async def api_market_delete(market_id: str):
    """删除市场条目(只删 markdown 文件)。"""
    path = kb._find_market_file(market_id)
    if path is None:
        raise HTTPException(404, f"找不到市场条目:{market_id}")
    path.unlink()
    return JSONResponse({"ok": True, "deleted": market_id})
