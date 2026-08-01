#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""web/routers/market.py —— 市场(自选股 + 市场聚合视图)路由。

职责:
    页面:GET /market                          「市场」单页(5 板块聚合)
    市场 CRUD:GET/POST /api/market, GET/PATCH/DELETE /api/market/{id}
    复用聚合(只读,无新存储):
        GET /api/market/earnings              财报日历(calendar+events 按 category==财报)
        GET /api/market/materials             收藏资料(「金融」收藏夹内文章)
        GET /api/market/linked-tasks          关联任务(tasks 按 category==金融)

市场条目存 08_Market/market_*.md,仅 watchlist(自选股/赛道)。无外部行情数据源(离线优先)。
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from web.utils import ENC, templates, VALID_EVENT_STATUS
from web.models import (
    MarketCreate, MarketUpdate,
    MarketJudgmentCreate, MarketJudgmentUpdate,
    MarketSimulationCreate, MarketSimulationUpdate,
)
from web.services.cards import _build_collections_list, _build_collection_articles

import kb

# 行情数据接入(可选依赖,akshare 缺失时优雅降级)
try:
    import kb_quote
except Exception:
    kb_quote = None  # type: ignore


# akshare 是同步阻塞库(requests.get 会 hang 在网络层)。在 async def 路由里
# 直接调用会冻结整个事件循环 —— 一旦某个 akshare 请求卡住,服务器所有请求
# (含其他页面/静态文件)全部排队挂起,表现为"网页完全卡死"。
# 解决:把同步阻塞调用丢到线程池(asyncio.to_thread),事件循环保持畅通;
# 即使线程里的请求 hang 住,也只影响那一个请求,不会拖垮全服务器。
async def _run_blocking(fn, *args, **kwargs):
    """在线程池里跑同步阻塞函数,返回结果。akshare 调用必须走这里。"""
    return await asyncio.to_thread(fn, *args, **kwargs)

router = APIRouter()

# 板块4「收藏资料」依赖的收藏夹名(聚合时按名查找,避免硬编码 col_id)
FINANCE_COLLECTION_NAME = "金融"
# 板块2「财报日历」/ 板块5「关联任务」的 category 关键字
EARNINGS_CATEGORY = "财报"
FINANCE_CATEGORY = "金融"
VALID_JUDGMENT_VERDICTS = {"pending", "correct", "wrong", "partial", "archived"}
VALID_SIMULATION_STATUSES = {"active", "closed", "archived"}
MARKET_POSITION_FIELDS = ("cost_price", "shares", "target_price", "stop_price")
STOCK_DETAIL_CACHE_DAYS = 90
STOCK_DETAIL_CACHE_FILE = "stock_details_90d.json"


def _stock_detail_cache_path() -> Path:
    """90 天自选股详情缓存。临时可重建数据,不属于 Markdown 主数据层。"""
    return kb.KB_DIR / "cache" / "market" / STOCK_DETAIL_CACHE_FILE


def _empty_stock_detail_cache() -> dict:
    return {"version": 1, "items": {}}


def _load_stock_detail_cache() -> dict:
    path = _stock_detail_cache_path()
    if not path.exists():
        return _empty_stock_detail_cache()
    try:
        data = json.loads(kb.read_text(path))
    except Exception:
        return _empty_stock_detail_cache()
    if not isinstance(data, dict):
        return _empty_stock_detail_cache()
    items = data.get("items")
    if not isinstance(items, dict):
        data["items"] = {}
    data.setdefault("version", 1)
    return data


def _save_stock_detail_cache(cache: dict) -> None:
    cache["version"] = 1
    cache["updated_at"] = kb.now_ts()
    cache.setdefault("items", {})
    kb.write_text(
        _stock_detail_cache_path(),
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
    )


def _stock_payload_from_market_item(item: dict, market: str, code: str) -> dict:
    return {
        "id": item.get("id", ""),
        "title": item.get("title", ""),
        "market": market,
        "code": code,
        "sector": item.get("sector", ""),
        "note": item.get("note", ""),
        "ticker": item.get("ticker", ""),
    }


def _is_cacheable_stock_detail(detail: dict) -> bool:
    if not isinstance(detail, dict):
        return False
    kline = detail.get("kline")
    return bool(detail.get("ok") is True and isinstance(kline, list) and kline)


def _short_quote_error(msg: str | None = None) -> str:
    raw = str(msg or "")
    if "ProxyError" in raw or "代理" in raw:
        return "行情源连接失败"
    if "Timeout" in raw or "timed out" in raw or "超时" in raw:
        return "行情源超时"
    if "Connection" in raw or "RemoteDisconnected" in raw or "连接" in raw:
        return "行情源连接失败"
    return raw[:24] or "暂无本地行情"


def _display_quote_from_cache_entry(
    market_id: str,
    entry: dict,
    *,
    fallback_stock: dict | None = None,
    stale: bool = False,
) -> dict:
    stock = dict(entry.get("stock") or fallback_stock or {})
    detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
    kline = detail.get("kline") if isinstance(detail.get("kline"), list) else []
    last = kline[-1] if kline and isinstance(kline[-1], dict) else {}
    price = detail.get("price", last.get("close", ""))
    change_pct = detail.get("change_pct", last.get("change_pct", 0))
    return {
        "ok": True,
        "market_id": market_id,
        "title": stock.get("title", ""),
        "market": stock.get("market") or detail.get("market", ""),
        "code": stock.get("code") or detail.get("code", ""),
        "price": price,
        "change_pct": change_pct,
        "date": detail.get("date") or last.get("date", ""),
        "kline_days": len(kline),
        "updated_at": entry.get("updated_at", ""),
        "stale": stale,
    }


def _error_quote_for_market_item(item: dict, market: str, code: str, error: str = "暂无本地行情") -> dict:
    return {
        "ok": False,
        "market_id": item.get("id", ""),
        "title": item.get("title", ""),
        "market": market,
        "code": code,
        "error": _short_quote_error(error),
    }


def _watchlist_quote_targets(market_id: str = "") -> list[tuple[dict, str, str]]:
    if market_id:
        path = kb._find_market_file(market_id)
        if path is None:
            raise HTTPException(404, f"找不到自选股:{market_id}")
        candidates = [kb.load_market_file(path)]
    else:
        candidates = kb.scan_market(kind="watchlist")

    targets: list[tuple[dict, str, str]] = []
    for item in candidates:
        mkt, code = kb.parse_ticker(item.get("ticker", ""))
        if mkt and code:
            targets.append((item, mkt, code))
    return targets


def _cached_watchlist_quote_response(market_id: str = "", *, stale: bool = False) -> dict:
    cache = _load_stock_detail_cache()
    cache_items = cache.get("items", {})
    results = []
    for item, mkt, code in _watchlist_quote_targets(market_id):
        mid = item.get("id", "")
        entry = cache_items.get(mid)
        stock = _stock_payload_from_market_item(item, mkt, code)
        if isinstance(entry, dict) and _is_cacheable_stock_detail(entry.get("detail", {})):
            results.append(_display_quote_from_cache_entry(mid, entry, fallback_stock=stock, stale=stale))
        else:
            results.append(_error_quote_for_market_item(item, mkt, code))
    ok_count = sum(1 for q in results if q.get("ok"))
    stale_count = sum(1 for q in results if q.get("stale"))
    return {
        "items": results,
        "available": kb_quote is not None and kb_quote.is_available(),
        "ok_count": ok_count,
        "stale_count": stale_count,
        "fresh_count": ok_count - stale_count,
        "fail_count": len(results) - ok_count,
    }


@router.get("/market", response_class=HTMLResponse)
async def page_market(request: Request):
    """市场页面:指数/视图/财报/任务/今日阅读/事件聚合(自选股拆到 /market/watchlist)。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "market.html", {"active_nav": "market"}
    )


# 字面路径必须排在 /market/{market_id} 前,否则被 {market_id} 捕获(与 earnings/materials 同理)
@router.get("/market/watchlist", response_class=HTMLResponse)
async def page_watchlist(request: Request):
    """自选股独立子页:卡片网格 + 行情刷新 + CRUD 表单。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "watchlist.html", {"active_nav": "market"}
    )


@router.get("/market/judgments", response_class=HTMLResponse)
async def page_market_judgments(request: Request):
    """个人市场判断子页:记录判断、判断时间和复盘结果。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    return templates.TemplateResponse(
        request, "market_judgments.html", {"active_nav": "market"}
    )


@router.get("/market/{market_id}", response_class=HTMLResponse)
async def page_market_detail(market_id: str, request: Request):
    """自选股详情页:K线图+资金流+财务+盘口(akshare,按市场能力显示)。"""
    if templates is None:
        return HTMLResponse("templates 目录不存在", 500)
    path = kb._find_market_file(market_id)
    if path is None:
        raise HTTPException(404, f"找不到自选股:{market_id}")
    return templates.TemplateResponse(
        request, "stock_detail.html",
        {"active_nav": "market", "market_id": market_id},
    )


# ---------------------------------------------------------------------------
# 市场 CRUD(仅 watchlist)
# ---------------------------------------------------------------------------

@router.get("/api/market")
async def api_market_list(kind: str | None = None):
    """所有市场条目,可选 ?kind=watchlist 过滤。按标题字母序。"""
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


@router.get("/api/market/quote/status")
async def api_market_quote_status():
    """行情功能是否可用(akshare 是否安装)。前端据此决定是否显示「刷新行情」。"""
    available = kb_quote is not None and kb_quote.is_available()
    return JSONResponse({"available": available})


@router.get("/api/market/quote")
async def api_market_quote(market_id: str = "", days: int = 30):
    """拉单只自选股行情(market_id 指定)。手动触发,不自动拉。

    ?market_id=xxx        拉单只(返回该股最新价+涨跌幅+K线)
    ?market_id=           空 = 拉全部 watchlist(逐只拉,较慢)
    days=30               K线天数
    """
    if kb_quote is None:
        raise HTTPException(503, "行情功能不可用:akshare 未安装")

    days = max(7, min(days, 90))  # 限制 7-90 天

    if market_id:
        # 单只
        path = kb._find_market_file(market_id)
        if path is None:
            raise HTTPException(404, f"找不到自选股:{market_id}")
        item = kb.load_market_file(path)
        mkt, code = kb.parse_ticker(item.get("ticker", ""))
        if not mkt or not code:
            raise HTTPException(400, "该自选股没有有效的代码")
        # 走线程池:akshare 同步阻塞,不能直接在事件循环里跑(否则卡死全服务器)
        q = await _run_blocking(kb_quote.get_quote, mkt, code, days)
        q["market_id"] = market_id
        q["title"] = item.get("title", "")
        return JSONResponse(q)
    else:
        # 全部 watchlist:并发拉取。每只仍走线程池隔离 akshare 的同步阻塞,
        # 但不再串行等待所有 eastmoney 分片请求,避免一次刷新拖到几分钟。
        items = kb.scan_market(kind="watchlist")
        tickers = []
        for it in items:
            mkt, code = kb.parse_ticker(it.get("ticker", ""))
            if mkt and code:
                tickers.append((mkt, code, it["id"], it.get("title", "")))

        sem = asyncio.Semaphore(4)

        async def _fetch_one(mkt2: str, code2: str, mid: str, title: str) -> dict:
            async with sem:
                try:
                    q = await _run_blocking(kb_quote.get_quote, mkt2, code2, days)
                except Exception as e:
                    q = {
                        "ok": False, "market": mkt2, "code": code2,
                        "error": f"行情源连接失败,请稍后重试",
                        "error_detail": f"{type(e).__name__}: {str(e)[:180]}",
                    }
                q["market_id"] = mid
                q["title"] = title
                return q

        results = await asyncio.gather(*[
            _fetch_one(mkt2, code2, mid, title)
            for mkt2, code2, mid, title in tickers
        ])
        ok_count = sum(1 for q in results if q.get("ok"))
        fail_count = len(results) - ok_count
        return JSONResponse({
            "items": results,
            "available": kb_quote.is_available(),
            "ok_count": ok_count,
            "fail_count": fail_count,
        })


@router.get("/api/market/quote-cache")
async def api_market_quote_cache(market_id: str = ""):
    """读取服务端 90 天详情缓存,不联网。用于自选股页打开时秒出本地行情。"""
    return JSONResponse(_cached_watchlist_quote_response(market_id))


@router.post("/api/market/quote-cache/refresh")
async def api_market_quote_cache_refresh(market_id: str = ""):
    """刷新自选股 90 天详情缓存。

    缓存按 market_id 独立覆盖:单只成功才更新该股票;失败时保留旧缓存并返回 stale。
    """
    targets = _watchlist_quote_targets(market_id)
    cache = _load_stock_detail_cache()
    cache_items = cache.setdefault("items", {})

    available = kb_quote is not None and kb_quote.is_available()
    if not available:
        data = _cached_watchlist_quote_response(market_id, stale=True)
        data["available"] = False
        return JSONResponse(data)

    sem = asyncio.Semaphore(4)

    async def _refresh_one(item: dict, mkt: str, code: str) -> tuple[str, dict, dict | None]:
        mid = item.get("id", "")
        stock = _stock_payload_from_market_item(item, mkt, code)
        old_entry = cache_items.get(mid)
        async with sem:
            try:
                detail = await _run_blocking(kb_quote.get_stock_detail, mkt, code, STOCK_DETAIL_CACHE_DAYS)
            except Exception as e:
                if isinstance(old_entry, dict) and _is_cacheable_stock_detail(old_entry.get("detail", {})):
                    return mid, _display_quote_from_cache_entry(mid, old_entry, fallback_stock=stock, stale=True), None
                return mid, _error_quote_for_market_item(item, mkt, code, str(e)), None

        if _is_cacheable_stock_detail(detail):
            entry = {"stock": stock, "detail": detail, "updated_at": kb.now_ts()}
            return mid, _display_quote_from_cache_entry(mid, entry, fallback_stock=stock, stale=False), entry

        if isinstance(old_entry, dict) and _is_cacheable_stock_detail(old_entry.get("detail", {})):
            return mid, _display_quote_from_cache_entry(mid, old_entry, fallback_stock=stock, stale=True), None

        error = detail.get("error") if isinstance(detail, dict) else "暂无本地行情"
        return mid, _error_quote_for_market_item(item, mkt, code, error), None

    refreshed = await asyncio.gather(*[_refresh_one(item, mkt, code) for item, mkt, code in targets])
    results = []
    updated_count = 0
    for mid, quote, entry in refreshed:
        results.append(quote)
        if entry is not None:
            cache_items[mid] = entry
            updated_count += 1

    if updated_count:
        _save_stock_detail_cache(cache)

    ok_count = sum(1 for q in results if q.get("ok"))
    stale_count = sum(1 for q in results if q.get("stale"))
    return JSONResponse({
        "items": results,
        "available": available,
        "ok_count": ok_count,
        "fresh_count": updated_count,
        "stale_count": stale_count,
        "fail_count": len(results) - ok_count,
        "updated_count": updated_count,
    })


@router.get("/api/market/detail/{market_id}")
async def api_market_detail(market_id: str, days: int = 90):
    """自选股详情数据(akshare):K线全字段 + 按市场补充资金流/财务/盘口。

    字面路径,必须在 /api/market/{market_id} 之前声明。
    """
    if kb_quote is None:
        raise HTTPException(503, "行情功能不可用:akshare 未安装")
    path = kb._find_market_file(market_id)
    if path is None:
        raise HTTPException(404, f"找不到自选股:{market_id}")
    item = kb.load_market_file(path)
    mkt, code = kb.parse_ticker(item.get("ticker", ""))
    if not mkt or not code:
        raise HTTPException(400, "该自选股没有有效的代码")
    days = max(30, min(days, 365))
    # 走线程池:get_stock_detail 内部多个 akshare 同步调用,不能阻塞事件循环
    detail = await _run_blocking(kb_quote.get_stock_detail, mkt, code, days)
    return JSONResponse({
        "stock": {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "market": mkt, "code": code,
            "sector": item.get("sector", ""),
            "note": item.get("note", ""),
            "ticker": item.get("ticker", ""),
        },
        "detail": detail,
        "available": kb_quote.is_available(),
    })




@router.get("/api/market/fund-flow")
async def api_market_fund_flow(indicator: str = "今日", sector_type: str = "行业资金流", top_n: int = 20):
    """板块资金流排行(akshare):行业/概念/地域 主力净流入,拆 inflow/outflow。

    字面路径,必须在 /api/market/{market_id} 之前声明(否则被 {market_id} 吞)。
    ?indicator=今日|5日|10日  ?sector_type=行业资金流|概念资金流|地域资金流  ?top_n=20
    """
    if kb_quote is None:
        raise HTTPException(503, "行情功能不可用:akshare 未安装")
    top_n = max(5, min(top_n, 50))
    # 走线程池:akshare 同步阻塞,不能直接在事件循环里跑
    result = await _run_blocking(kb_quote.get_sector_fund_flow, indicator, sector_type, top_n)
    return JSONResponse(result)


def _has_position_fields(item: dict) -> bool:
    return any(str(item.get(field, "") or "").strip() for field in MARKET_POSITION_FIELDS)


@router.get("/api/market/personal/holdings")
async def api_market_personal_holdings():
    """Personal current holdings from active watchlist items with position fields."""
    items = [
        it for it in kb.scan_market(kind="watchlist")
        if it.get("status") == "active" and _has_position_fields(it)
    ]
    return JSONResponse({"items": items})


def _validate_iso_date(raw: str, field_name: str) -> str:
    val = (raw or "").strip()
    if not val:
        return ""
    try:
        date.fromisoformat(val)
    except ValueError:
        raise HTTPException(400, f"{field_name}格式错误: {val}")
    return val


def _validate_simulation_status(status: str) -> str:
    val = (status or "active").strip() or "active"
    if val not in VALID_SIMULATION_STATUSES:
        raise HTTPException(400, f"非法模拟盘状态:{val}")
    return val


def _normalize_market_ticker(market: str, ticker: str) -> tuple[str, str]:
    market_code = (market or "").strip().upper()
    raw_ticker = (ticker or "").strip()
    raw_code = raw_ticker.split(":", 1)[-1].strip() if ":" in raw_ticker else raw_ticker
    if market_code and market_code not in kb.MARKET_CODES:
        raise HTTPException(400, f"非法市场:{market_code}(支持 {', '.join(kb.MARKET_CODES)})")
    err = kb.validate_ticker(market_code, raw_code)
    if err:
        raise HTTPException(400, err)
    try:
        return market_code, kb.normalize_ticker(market_code, raw_code)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _simulation_meta_from_payload(simulation_id: str, payload: MarketSimulationCreate) -> dict:
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    market_code, ticker_stored = _normalize_market_ticker(payload.market, payload.ticker)
    return {
        "id": simulation_id,
        "title": title,
        "market": market_code,
        "ticker": ticker_stored,
        "sector": payload.sector.strip(),
        "entry_price": payload.entry_price.strip(),
        "shares": payload.shares.strip(),
        "entry_date": _validate_iso_date(payload.entry_date, "建仓日期"),
        "target_price": payload.target_price.strip(),
        "stop_price": payload.stop_price.strip(),
        "status": _validate_simulation_status(payload.status),
        "exit_price": payload.exit_price.strip(),
        "exit_date": _validate_iso_date(payload.exit_date, "结束日期"),
        "note": payload.note.strip(),
    }


@router.get("/api/market/simulations")
async def api_market_simulations_list(status: str | None = None):
    """List simulated market positions."""
    if status:
        status = _validate_simulation_status(status)
    return JSONResponse({"items": kb.scan_market_simulations(status=status)})


@router.post("/api/market/simulations")
async def api_market_simulations_create(payload: MarketSimulationCreate):
    """Create a simulated market position markdown file."""
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    simulation_id = kb.make_market_simulation_id(title)
    path = kb._market_simulation_file_path(simulation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        simulation_id = kb.make_market_simulation_id(title + str(date.today()))
        path = kb._market_simulation_file_path(simulation_id)
    meta = _simulation_meta_from_payload(simulation_id, payload)
    kb.write_market_simulation_file(path, meta, payload.body.strip(), is_new=True)
    return JSONResponse({"ok": True, "simulation": kb.load_market_simulation_file(path)})


@router.get("/api/market/simulations/{simulation_id}")
async def api_market_simulations_get(simulation_id: str):
    """Get one simulated market position."""
    path = kb._find_market_simulation_file(simulation_id)
    if path is None:
        raise HTTPException(404, f"找不到模拟盘记录:{simulation_id}")
    return JSONResponse(kb.load_market_simulation_file(path))


def _update_simulation_fields(item: dict, payload: MarketSimulationUpdate) -> tuple[dict, str]:
    meta = {k: v for k, v in item.items() if k not in ("body", "path")}
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(400, "标题不能为空")
        meta["title"] = title
    if payload.sector is not None:
        meta["sector"] = payload.sector.strip()
    if payload.entry_price is not None:
        meta["entry_price"] = payload.entry_price.strip()
    if payload.shares is not None:
        meta["shares"] = payload.shares.strip()
    if payload.entry_date is not None:
        meta["entry_date"] = _validate_iso_date(payload.entry_date, "建仓日期")
    if payload.target_price is not None:
        meta["target_price"] = payload.target_price.strip()
    if payload.stop_price is not None:
        meta["stop_price"] = payload.stop_price.strip()
    if payload.status is not None:
        meta["status"] = _validate_simulation_status(payload.status)
    if payload.exit_price is not None:
        meta["exit_price"] = payload.exit_price.strip()
    if payload.exit_date is not None:
        meta["exit_date"] = _validate_iso_date(payload.exit_date, "结束日期")
    if payload.note is not None:
        meta["note"] = payload.note.strip()

    final_market = payload.market if payload.market is not None else meta.get("market", "")
    final_ticker = payload.ticker if payload.ticker is not None else meta.get("ticker", "")
    if payload.market is not None or payload.ticker is not None:
        market_code, ticker_stored = _normalize_market_ticker(final_market, final_ticker)
        meta["market"] = market_code
        meta["ticker"] = ticker_stored

    body = item.get("body", "") if payload.body is None else payload.body.strip()
    return meta, body


@router.patch("/api/market/simulations/{simulation_id}")
async def api_market_simulations_update(simulation_id: str, payload: MarketSimulationUpdate):
    """Update one simulated market position."""
    path = kb._find_market_simulation_file(simulation_id)
    if path is None:
        raise HTTPException(404, f"找不到模拟盘记录:{simulation_id}")
    item = kb.load_market_simulation_file(path)
    meta, body = _update_simulation_fields(item, payload)
    kb.write_market_simulation_file(path, meta, body, is_new=False)
    return JSONResponse({"ok": True, "simulation": kb.load_market_simulation_file(path)})


@router.delete("/api/market/simulations/{simulation_id}")
async def api_market_simulations_delete(simulation_id: str):
    """Delete one simulated market position markdown file."""
    path = kb._find_market_simulation_file(simulation_id)
    if path is None:
        raise HTTPException(404, f"找不到模拟盘记录:{simulation_id}")
    path.unlink()
    return JSONResponse({"ok": True, "deleted": simulation_id})


def _validate_judgment_time(raw: str, field_name: str) -> str:
    """Validate date/datetime strings while preserving the user's exact value."""
    val = (raw or "").strip()
    if not val:
        return ""
    try:
        datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"{field_name}格式错误: {val}")
    return val


def _validate_judgment_verdict(verdict: str) -> str:
    val = (verdict or "pending").strip() or "pending"
    if val not in VALID_JUDGMENT_VERDICTS:
        raise HTTPException(400, f"非法验证状态:{val}")
    return val


def _make_judgment_title(title: str, target: str, judgment: str, judged_at: str) -> str:
    explicit = " ".join((title or "").split())
    if explicit:
        return explicit[:120]
    base = " ".join((target or judgment or "市场判断").split())
    if len(base) > 42:
        base = base[:42] + "..."
    day = judged_at[:10] if judged_at else ""
    return f"{day} {base}".strip()


@router.get("/api/market/judgments")
async def api_market_judgments_list(verdict: str | None = None):
    """List personal market judgments, newest first."""
    items = kb.scan_market_judgments()
    if verdict:
        verdict = _validate_judgment_verdict(verdict)
        items = [it for it in items if it.get("verdict") == verdict]
    return JSONResponse({"items": items})


@router.post("/api/market/judgments")
async def api_market_judgments_create(payload: MarketJudgmentCreate):
    """Create a personal market judgment markdown file."""
    judgment = payload.judgment.strip()
    if not judgment:
        raise HTTPException(400, "判断内容不能为空")
    judged_at = _validate_judgment_time(payload.judged_at.strip() or kb.now_ts(), "判断时间")
    reviewed_at = _validate_judgment_time(payload.reviewed_at.strip(), "复盘时间")
    verdict = _validate_judgment_verdict(payload.verdict)
    if verdict != "pending" and not reviewed_at:
        reviewed_at = kb.now_ts()
    title = _make_judgment_title(payload.title, payload.target, judgment, judged_at)

    judgment_id = kb.make_market_judgment_id(title)
    path = kb._market_judgment_file_path(judgment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": judgment_id,
        "title": title,
        "target": payload.target.strip(),
        "judgment": judgment,
        "judged_at": judged_at,
        "horizon": payload.horizon.strip(),
        "verdict": verdict,
        "actual_result": payload.actual_result.strip(),
        "reviewed_at": reviewed_at,
    }
    kb.write_market_judgment_file(path, meta, payload.body.strip(), is_new=True)
    return JSONResponse({"ok": True, "judgment": kb.load_market_judgment_file(path)})


@router.get("/api/market/judgments/{judgment_id}")
async def api_market_judgments_get(judgment_id: str):
    """Get one personal market judgment."""
    path = kb._find_market_judgment_file(judgment_id)
    if path is None:
        raise HTTPException(404, f"找不到市场判断:{judgment_id}")
    return JSONResponse(kb.load_market_judgment_file(path))


@router.patch("/api/market/judgments/{judgment_id}")
async def api_market_judgments_update(judgment_id: str, payload: MarketJudgmentUpdate):
    """Update one personal market judgment."""
    path = kb._find_market_judgment_file(judgment_id)
    if path is None:
        raise HTTPException(404, f"找不到市场判断:{judgment_id}")
    item = kb.load_market_judgment_file(path)
    meta = {k: v for k, v in item.items() if k not in ("body", "path")}

    if payload.title is not None:
        meta["title"] = payload.title.strip()
    if payload.target is not None:
        meta["target"] = payload.target.strip()
    if payload.judgment is not None:
        judgment = payload.judgment.strip()
        if not judgment:
            raise HTTPException(400, "判断内容不能为空")
        meta["judgment"] = judgment
    if payload.judged_at is not None:
        judged_at = _validate_judgment_time(payload.judged_at.strip(), "判断时间")
        if not judged_at:
            raise HTTPException(400, "判断时间不能为空")
        meta["judged_at"] = judged_at
    if payload.horizon is not None:
        meta["horizon"] = payload.horizon.strip()
    if payload.verdict is not None:
        meta["verdict"] = _validate_judgment_verdict(payload.verdict)
    if payload.actual_result is not None:
        meta["actual_result"] = payload.actual_result.strip()
    if payload.reviewed_at is not None:
        meta["reviewed_at"] = _validate_judgment_time(payload.reviewed_at.strip(), "复盘时间")

    if not meta.get("title"):
        meta["title"] = _make_judgment_title(
            "", meta.get("target", ""), meta.get("judgment", ""), meta.get("judged_at", "")
        )
    if meta.get("verdict") != "pending" and not meta.get("reviewed_at"):
        meta["reviewed_at"] = kb.now_ts()

    body = item.get("body", "") if payload.body is None else payload.body.strip()
    kb.write_market_judgment_file(path, meta, body, is_new=False)
    return JSONResponse({"ok": True, "judgment": kb.load_market_judgment_file(path)})


@router.delete("/api/market/judgments/{judgment_id}")
async def api_market_judgments_delete(judgment_id: str):
    """Delete one personal market judgment markdown file."""
    path = kb._find_market_judgment_file(judgment_id)
    if path is None:
        raise HTTPException(404, f"找不到市场判断:{judgment_id}")
    path.unlink()
    return JSONResponse({"ok": True, "deleted": judgment_id})




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

    # watchlist 校验市场 + ticker(后续要调 API,代码必须规范)
    market_code = ""
    ticker_stored = ""
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
        "cost_price": payload.cost_price.strip(),
        "shares": payload.shares.strip(),
        "target_price": payload.target_price.strip(),
        "stop_price": payload.stop_price.strip(),
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
    if payload.note is not None:
        meta["note"] = payload.note.strip()
    if payload.status is not None:
        if payload.status not in VALID_EVENT_STATUS:
            raise HTTPException(400, f"非法 status 值:{payload.status}")
        meta["status"] = payload.status

    # 持仓位置字段(纯 str 存储,无校验)
    if payload.cost_price is not None:
        meta["cost_price"] = payload.cost_price.strip()
    if payload.shares is not None:
        meta["shares"] = payload.shares.strip()
    if payload.target_price is not None:
        meta["target_price"] = payload.target_price.strip()
    if payload.stop_price is not None:
        meta["stop_price"] = payload.stop_price.strip()

    # market/ticker 联合校验(以更新后最终值为准)
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
