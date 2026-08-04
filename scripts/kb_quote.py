#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kb_quote.py —— 行情数据接入(BaoStock + AKShare + SQLite 缓存)。

设计原则(与项目 kb_llm.py 一致):
  - BaoStock / AKShare 是可选依赖,缺失时优雅降级(返回 error 字段,不抛异常)
  - 行情缓存只写 .kb/cache/market/market_cache.sqlite,不污染 Markdown 数据层
  - 单只按需查询,不拉全市场(避免数据量爆炸 + 被限流)

历史日线数据源:
  A股(SH/SZ):      BaoStock 优先,AKShare 兜底,SQLite 再兜底
  北交所(BJ):      AKShare 优先,SQLite 兜底
  港股/美股(HK/US):AKShare 优先,SQLite 兜底

美股 105=纳斯达克 106=纽交所。无法从 ticker 自动判断交易所,
用常见映射表 + 默认 105 兜底(BABA 等纽交所需手动映射)。
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any

import kb_market_cache

# 可选依赖:akshare 缺失时降级
try:
    import akshare as ak
    _AK_AVAILABLE = True
except Exception:
    ak = None  # type: ignore
    _AK_AVAILABLE = False

# 可选依赖:BaoStock 缺失时不影响 AKShare/SQLite 缓存兜底
try:
    import baostock as bs
    _BAOSTOCK_AVAILABLE = True
except Exception:
    bs = None  # type: ignore
    _BAOSTOCK_AVAILABLE = False


# ===========================================================================
# 网络层:专用 requests Session(针对 eastmoney 国内数据源)
# 为什么需要:akshare 内部用裸 requests.get(url),会通过 trust_env 自动继承
#   系统代理。但 eastmoney 是国内源,本应直连;走代理时部分子域名(如美股
#   63.push2his)会被代理拒收,导致 ProxyError / ConnectionError 间歇性失败。
# 方案:monkeypatch requests.get,对 eastmoney 域名改用专用 Session
#   (trust_env=False 不读系统代理 + urllib3 自动重试兜住间歇 reset)。
#   非 eastmoney 请求原样放行,不影响其他模块。
# ===========================================================================
import requests as _requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
    _HAS_RETRY = True
except Exception:
    _HAS_RETRY = False


def _make_em_session() -> _requests.Session:
    """eastmoney 专用 Session:禁系统代理 + 自动重试。"""
    s = _requests.Session()
    s.trust_env = False            # 不读系统代理注册表/环境变量(国内源应直连)
    s.proxies = {"http": None, "https": None}  # 显式禁代理
    if _HAS_RETRY:
        # eastmoney 分片域名在部分网络下会直接断开连接。这里少量重试即可,
        # 避免一次刷新被 8 只自选股串行拖到几分钟。
        retry = Retry(total=1, backoff_factor=0.2,
                      status_forcelist=[502, 503, 504],
                      allowed_methods=frozenset(["GET"]))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })
    return s


_EM_SESSION = _make_em_session()
_EM_HOSTS = ("eastmoney.com",)  # 命中这些 host 的请求走专用 Session
_orig_requests_get = _requests.get

# eastmoney 请求的默认超时(秒)。akshare 默认传 timeout=None(无限等),
# 一旦网络 hang 住(实测会发生),请求会永久阻塞。行情是可重试缓存数据,
# 这里宁可快速失败交给前端缓存兜底,也不要长期占住 worker。
_EM_TIMEOUT = (3, 8)  # (连接超时, 读取超时)


def _friendly_error(exc: Exception) -> tuple[str, str]:
    """把 requests/akshare 的长网络异常压成 UI 可读提示,同时保留 detail。"""
    detail = f"{type(exc).__name__}: {str(exc)[:240]}"
    raw = str(exc)
    if "ProxyError" in raw:
        return "行情源代理连接失败,已保留缓存", detail
    if "push2his.eastmoney.com" in raw or "RemoteDisconnected" in raw:
        return "行情源连接失败,请稍后重试", detail
    if "timed out" in raw.lower() or "ReadTimeout" in raw or "ConnectTimeout" in raw:
        return "行情源响应超时,请稍后重试", detail
    if "ConnectionError" in detail:
        return "行情源网络连接失败,请稍后重试", detail
    return detail[:120], detail


def _patched_get(url, params=None, **kwargs):
    """对 eastmoney 域名用专用 Session(禁代理+重试+超时),其余请求原样放行。"""
    if isinstance(url, str) and any(h in url for h in _EM_HOSTS):
        # akshare 调用形如 requests.get(url, params=..., timeout=None);
        # 强制超时:akshare 默认 timeout=None 会无限阻塞,必须兜底。
        if not kwargs.get("timeout"):
            kwargs["timeout"] = _EM_TIMEOUT
        kwargs.pop("cookies", None)  # Session 自管 cookies,避免冲突
        return _EM_SESSION.get(url, params=params, **kwargs)
    return _orig_requests_get(url, params=params, **kwargs)


# 仅当 akshare 可用时才打补丁(避免无谓影响无 akshare 的环境)
if _AK_AVAILABLE:
    _requests.get = _patched_get
    # akshare 内部 `import requests as ...` 后调 requests.get ——
    # 它引用的是同一个 requests 模块对象,patch 模块属性即可全局生效。


# 美股纳斯达克(105)/纽交所(106)映射。未列出的默认 105(纳斯达克居多)。
# 这些是你自选股里实际会用到的;加新的纽交所股票在此补一行。
_US_EXCHANGE_PREFIX: dict[str, str] = {
    "BABA": "106",   # 阿里(纽交所)
    "BIDU": "106",   # 百度
    "JD":   "106",   # 京东
    "PDD":  "106",   # 拼多多
    "NIO":  "106",   # 蔚来
    "PETR": "106",
}
# 默认纳斯达克(MU/SNDK/AAPL/MSFT/GOOG/NVDA/TSLA/AMZN 等都在纳斯达克)
_DEFAULT_US_PREFIX = "105"


def _us_symbol(code: str) -> str:
    """美股代码 → 东财格式(加交易所前缀)。code 是纯代码如 AAPL。"""
    prefix = _US_EXCHANGE_PREFIX.get(code.upper(), _DEFAULT_US_PREFIX)
    return f"{prefix}.{code.upper()}"


_STD_TO_BAOSTOCK_ADJUST = {"hfq": "1", "qfq": "2", "none": "3"}
_BAOSTOCK_TO_STD_ADJUST = {"1": "hfq", "2": "qfq", "3": "none"}
_STD_TO_AK_ADJUST = {"hfq": "hfq", "qfq": "qfq", "none": ""}
_BAOSTOCK_FIELDS = ",".join([
    "date", "code", "open", "high", "low", "close", "preclose",
    "volume", "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST",
])


def _normalize_adjust(adjust: str = "qfq") -> str:
    val = (adjust or "qfq").strip().lower()
    if val in ("hfq", "后复权"):
        return "hfq"
    if val in ("none", "不复权", "bfq", ""):
        return "none"
    return "qfq"


def _currency_for_market(market: str) -> str:
    return {"SH": "CNY", "SZ": "CNY", "BJ": "CNY", "HK": "HKD", "US": "USD"}.get(market.upper(), "")


def _to_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            v = v.strip().replace(",", "")
            if v.endswith("%"):
                v = v[:-1].strip()
            if not v:
                return default
        f = float(v)
        return default if math.isnan(f) else round(f, 4)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int | None = None) -> int | None:
    f = _to_float(v, None)
    if f is None:
        return default
    return int(round(f))


def _field(row: Any, *names: str) -> Any:
    for name in names:
        try:
            val = row[name]
        except Exception:
            continue
        if val is not None:
            return val
    return None


def _baostock_symbol(market: str, code: str) -> str:
    mkt = market.upper()
    if mkt == "SH":
        return f"sh.{code}"
    if mkt == "SZ":
        return f"sz.{code}"
    raise ValueError(f"BaoStock 不支持市场:{market}")


def _normalized_row_base(market: str, code: str, trade_date: str, adjust: str) -> dict[str, Any]:
    return {
        "market": market.upper(),
        "code": code,
        "trade_date": trade_date,
        "adjust": adjust,
        "currency": _currency_for_market(market),
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "preclose": None,
        "price": None,
        "change_amt": None,
        "change_pct": None,
        "volume_shares": None,
        "amount": None,
        "amplitude": None,
        "turnover": None,
        "trade_status": "",
        "is_st": "",
    }


def _normalize_baostock_row(row: dict[str, Any], market: str, code: str) -> dict[str, Any]:
    """BaoStock 日线标准化。

    BaoStock volume 已是股; pctChg/turn 是百分数数值,不转小数。
    adjustflag: 1=后复权,2=前复权,3=不复权。
    """
    adjust = _BAOSTOCK_TO_STD_ADJUST.get(str(row.get("adjustflag") or "3"), "none")
    item = _normalized_row_base(market, code, str(row.get("date") or ""), adjust)
    close = _to_float(row.get("close"), None)
    preclose = _to_float(row.get("preclose"), None)
    item.update({
        "open": _to_float(row.get("open"), None),
        "high": _to_float(row.get("high"), None),
        "low": _to_float(row.get("low"), None),
        "close": close,
        "preclose": preclose,
        "price": close,
        "change_amt": round(close - preclose, 4) if close is not None and preclose not in (None, 0) else None,
        "change_pct": _to_float(row.get("pctChg"), 0.0),
        "volume_shares": _to_int(row.get("volume"), None),
        "amount": _to_float(row.get("amount"), None),
        "turnover": _to_float(row.get("turn"), None),
        "trade_status": str(row.get("tradestatus") or ""),
        "is_st": str(row.get("isST") or ""),
    })
    return item


def _normalize_akshare_row(row: Any, market: str, code: str, adjust: str = "qfq") -> dict[str, Any]:
    """AKShare 日线标准化。

    A 股/BJ 的「成交量」来自东财接口,单位为手,转为股;HK/US 按股保留。
    「涨跌幅」「换手率」保持百分数数值。
    """
    mkt = market.upper()
    item = _normalized_row_base(mkt, code, str(_field(row, "日期", "date") or ""), _normalize_adjust(adjust))
    close = _to_float(_field(row, "收盘", "close"), None)
    raw_volume = _to_float(_field(row, "成交量", "volume"), None)
    volume_shares = None
    if raw_volume is not None:
        volume_shares = int(round(raw_volume * 100)) if mkt in ("SH", "SZ", "BJ") else int(round(raw_volume))
    item.update({
        "open": _to_float(_field(row, "开盘", "open"), None),
        "high": _to_float(_field(row, "最高", "high"), None),
        "low": _to_float(_field(row, "最低", "low"), None),
        "close": close,
        "price": close,
        "change_amt": _to_float(_field(row, "涨跌额", "change_amt"), None),
        "change_pct": _to_float(_field(row, "涨跌幅", "change_pct"), 0.0),
        "volume_shares": volume_shares,
        "amount": _to_float(_field(row, "成交额", "amount"), None),
        "amplitude": _to_float(_field(row, "振幅", "amplitude"), None),
        "turnover": _to_float(_field(row, "换手率", "turnover"), None),
    })
    return item


def _with_legacy_volume_alias(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["date"] = item.get("date") or item.get("trade_date", "")
        item["volume"] = item.get("volume_shares")
        out.append(item)
    return out


def _history_result(
    market: str,
    code: str,
    rows: list[dict[str, Any]],
    *,
    source: str,
    adjust: str,
    stale: bool = False,
) -> dict[str, Any]:
    rows = _with_legacy_volume_alias(rows)
    last = rows[-1] if rows else {}
    return {
        "ok": bool(rows),
        "market": market.upper(),
        "code": code,
        "source": source,
        "currency": _currency_for_market(market),
        "adjust": adjust,
        "price": last.get("close", 0),
        "change_amt": last.get("change_amt"),
        "change_pct": last.get("change_pct", 0),
        "volume_shares": last.get("volume_shares"),
        "amount": last.get("amount"),
        "kline": rows,
        "kline_days": len(rows),
        "date": last.get("date", ""),
        "updated_at": last.get("fetched_at", ""),
        "stale": stale,
    }


def _fetch_baostock_kline(market: str, code: str, days: int, adjust: str = "qfq") -> list[dict[str, Any]]:
    if not _BAOSTOCK_AVAILABLE:
        raise RuntimeError("baostock 未安装")
    mkt = market.upper()
    if mkt not in ("SH", "SZ"):
        raise RuntimeError(f"BaoStock 不支持市场:{market}")
    end = date.today()
    start = end - timedelta(days=days + 45)
    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        raise RuntimeError(f"BaoStock 登录失败:{getattr(lg, 'error_msg', '')}")
    try:
        rs = bs.query_history_k_data_plus(
            _baostock_symbol(mkt, code),
            _BAOSTOCK_FIELDS,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag=_STD_TO_BAOSTOCK_ADJUST[_normalize_adjust(adjust)],
        )
        if getattr(rs, "error_code", "0") != "0":
            raise RuntimeError(f"BaoStock 拉取失败:{getattr(rs, 'error_msg', '')}")
        rows: list[dict[str, Any]] = []
        fields = list(getattr(rs, "fields", []))
        while rs.next():
            raw = dict(zip(fields, rs.get_row_data()))
            item = _normalize_baostock_row(raw, mkt, code)
            if item.get("trade_date") and item.get("close") is not None:
                rows.append(item)
        return rows[-days:]
    finally:
        try:
            bs.logout()
        except Exception:
            pass


def _fetch_akshare_kline(market: str, code: str, days: int, adjust: str = "qfq") -> list[dict[str, Any]]:
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    errors: list[str] = []
    try:
        df = _fetch_kline_df(market, code, days, adjust=adjust)
    except Exception as e:
        df = None
        errors.append(f"eastmoney:{type(e).__name__}: {str(e)[:120]}")
    if (df is None or len(df) == 0) and market.upper() in ("HK", "US"):
        try:
            df = _fetch_sina_daily_df(market, code, adjust=adjust)
        except Exception as e:
            errors.append(f"sina:{type(e).__name__}: {str(e)[:120]}")
    if df is None or len(df) == 0:
        if errors:
            raise RuntimeError("; ".join(errors))
        return []
    rows = []
    for _, row in df.tail(days).iterrows():
        item = _normalize_akshare_row(row, market, code, adjust)
        if item.get("trade_date") and item.get("close") is not None:
            rows.append(item)
    return rows


def get_cached_history_kline(market: str, code: str, days: int = 90, adjust: str = "qfq") -> dict[str, Any]:
    mkt = market.upper()
    adj = _normalize_adjust(adjust)
    cached = kb_market_cache.load_daily_kline(mkt, code, adjust=adj, limit=days)
    if cached:
        return _history_result(mkt, code, cached, source="sqlite", adjust=adj, stale=True)
    return {"ok": False, "market": mkt, "code": code, "error": "暂无本地行情"}


def get_history_kline(market: str, code: str, days: int = 90, adjust: str = "qfq") -> dict[str, Any]:
    """历史日线协调层:BaoStock/AKShare → SQLite → 短错误。"""
    mkt = market.upper()
    days = max(7, min(int(days), 365))
    adj = _normalize_adjust(adjust)
    errors: list[str] = []

    providers: list[tuple[str, Any]] = []
    if mkt in ("SH", "SZ"):
        providers.append(("baostock", _fetch_baostock_kline))
        providers.append(("akshare", _fetch_akshare_kline))
    else:
        providers.append(("akshare", _fetch_akshare_kline))

    for source, fetcher in providers:
        try:
            rows = fetcher(mkt, code, days, adj)
            if not rows:
                raise RuntimeError("无历史行情数据")
            kb_market_cache.upsert_daily_kline(rows, source=source)
            kb_market_cache.record_fetch_status(mkt, code, "daily_kline", source, ok=True)
            return _history_result(mkt, code, rows, source=source, adjust=adj, stale=False)
        except Exception as e:
            errors.append(f"{source}:{type(e).__name__}: {str(e)[:120]}")
            kb_market_cache.record_fetch_status(
                mkt, code, "daily_kline", source, ok=False, error=str(e), create_on_failure=False
            )

    cached = get_cached_history_kline(mkt, code, days, adj)
    if cached.get("ok"):
        cached["error_detail"] = "; ".join(errors)
        return cached

    msg = errors[-1] if errors else "无可用行情源"
    short, detail = _friendly_error(RuntimeError(msg))
    return {"ok": False, "market": mkt, "code": code, "error": short, "error_detail": detail}


_QUOTE_KEY_LATEST = "\u6700\u65b0"
_QUOTE_KEY_CHANGE_PCT = "\u6da8\u5e45"
_QUOTE_KEY_CHANGE_AMT = "\u6da8\u8dcc"
_QUOTE_KEY_TOTAL_HANDS = "\u603b\u624b"
_QUOTE_KEY_AMOUNT = "\u91d1\u989d"

_MARKET_INDEXES: list[dict[str, Any]] = [
    {
        "id": "csi300",
        "market_label": "A股",
        "label": "沪深300",
        "symbol": "sh000300",
        "cache_code": "sh000300",
        "source": "cn_index",
        "currency": "CNY",
        "color": "#dc2626",
        "baostock_market": "SH",
        "baostock_code": "000300",
    },
    {
        "id": "sp500",
        "market_label": "美股",
        "label": "标普500",
        "symbol": ".INX",
        "cache_code": "SPX",
        "source": "us_index",
        "currency": "USD",
        "color": "#2563eb",
        "em_symbol": "标普500",
    },
    {
        "id": "hstech",
        "market_label": "港股",
        "label": "恒生科技指数",
        "symbol": "HSTECH",
        "cache_code": "HSTECH",
        "source": "hk_index",
        "currency": "HKD",
        "color": "#0d9488",
    },
]

_WATCHLIST_EQUAL_WEIGHT_INDEX: dict[str, Any] = {
    "id": "watch_equal",
    "market_label": "自选股",
    "label": "自选股等权指数",
    "symbol": "WATCH_EQUAL",
    "cache_code": "WATCH_EQUAL",
    "source": "watchlist_cache",
    "currency": "",
    "color": "#8b5cf6",
}

_INDUSTRY_COLORS = [
    "#dc2626", "#2563eb", "#f59e0b", "#7c3aed",
    "#0891b2", "#ea580c", "#16a34a", "#be123c",
    "#4f46e5", "#0f766e", "#ca8a04", "#9333ea",
]
_EM_INDUSTRY_FAILURE_TTL_SECONDS = 600
_em_industry_failure_until = 0.0
_MARKET_BREADTH_CODE = "market_breadth"
_MARKET_BREADTH_BLOCK = "latest"


def _has_value(v: Any) -> bool:
    return v is not None and v != ""


def _append_unique(seq: list, item: Any) -> None:
    if item not in seq:
        seq.append(item)


def _apply_realtime_quote_payload(result: dict[str, Any], quote: dict[str, Any], *, source: str) -> bool:
    latest = _to_float(quote.get(_QUOTE_KEY_LATEST), None)
    if latest is None:
        return False
    result["price"] = latest
    result["change_pct"] = _to_float(quote.get(_QUOTE_KEY_CHANGE_PCT), result.get("change_pct", 0.0))
    result["change_amt"] = _to_float(quote.get(_QUOTE_KEY_CHANGE_AMT), result.get("change_amt"))
    total_hands = _to_float(quote.get(_QUOTE_KEY_TOTAL_HANDS), None)
    if total_hands is not None:
        result["volume_shares"] = int(round(total_hands * 100))
    amount = _to_float(quote.get(_QUOTE_KEY_AMOUNT), None)
    if amount is not None:
        result["amount"] = amount
    result["quote_source"] = source
    result["quote_updated_at"] = datetime.now().isoformat(timespec="seconds")
    return True


def _overlay_cached_quote_snapshot(result: dict[str, Any], snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    changed = False
    for key in ("price", "change_amt", "change_pct", "volume_shares", "amount", "currency"):
        val = snapshot.get(key)
        if _has_value(val):
            result[key] = val
            changed = True
    if changed:
        result["quote_source"] = "sqlite"
        result["quote_updated_at"] = snapshot.get("quote_updated_at") or snapshot.get("updated_at") or ""
        _append_unique(result.setdefault("stale_blocks", []), "quote_snapshot")
    return changed


def _apply_akshare_realtime_quote(result: dict[str, Any], market: str, code: str) -> dict[str, Any]:
    mkt = market.upper()
    if not result.get("ok") or mkt not in ("SH", "SZ", "BJ"):
        return result
    out = dict(result)
    if _AK_AVAILABLE:
        try:
            quote = _fetch_a_quote(code)
            if _apply_realtime_quote_payload(out, quote, source="akshare"):
                return out
        except Exception:
            pass
    _overlay_cached_quote_snapshot(out, kb_market_cache.load_quote_snapshot(mkt, code))
    return out


def _index_cache_code(index: dict[str, Any]) -> str:
    return str(index.get("cache_code") or index.get("symbol") or index.get("id") or "")


def _date_key(value: Any) -> str:
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    text = str(value or "").strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    return text[:10]


def _coerce_index_cache_rows(rows: list[dict[str, Any]], index: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    code = _index_cache_code(index)
    for row in rows:
        item = dict(row)
        trade_date = item.get("trade_date") or item.get("date")
        trade_date = _date_key(trade_date)
        if not trade_date:
            continue
        item["market"] = "IDX"
        item["code"] = code
        item["trade_date"] = str(trade_date)
        item["date"] = str(trade_date)
        item["adjust"] = "none"
        item["currency"] = index.get("currency", item.get("currency", ""))
        item["price"] = item.get("price", item.get("close"))
        out.append(item)
    return out


def _normalize_index_rows(
    raw_rows: list[dict[str, Any]],
    symbol: str,
    *,
    source: str,
    currency: str = "CNY",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        trade_date = _field(raw, "date", "日期", "trade_date", "时间")
        trade_date = _date_key(trade_date)
        close = _to_float(_field(raw, "close", "收盘", "最新价", "latest", "收盘价"), None)
        if not trade_date or close is None:
            continue
        item = _normalized_row_base("IDX", symbol, str(trade_date), "none")
        item.update({
            "currency": currency,
            "open": _to_float(_field(raw, "open", "开盘", "今开"), None),
            "high": _to_float(_field(raw, "high", "最高"), None),
            "low": _to_float(_field(raw, "low", "最低"), None),
            "close": close,
            "price": close,
            "volume_shares": _to_int(_field(raw, "volume", "成交量"), None),
            "amount": _to_float(_field(raw, "amount", "成交额"), None),
        })
        rows.append(item)
    rows.sort(key=lambda x: x.get("trade_date", ""))
    prev_close = None
    for row in rows:
        close = row.get("close")
        if close is not None and prev_close not in (None, 0):
            row["preclose"] = prev_close
            row["change_amt"] = round(close - prev_close, 4)
            row["change_pct"] = round((close - prev_close) / prev_close * 100, 4)
        prev_close = close
        row["source"] = source
    return rows


def _fetch_cn_index_kline(index: dict[str, Any], days: int) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    if index.get("baostock_market") and _BAOSTOCK_AVAILABLE:
        try:
            rows = _fetch_baostock_kline(
                str(index["baostock_market"]),
                str(index["baostock_code"]),
                days,
                adjust="none",
            )
            rows = _coerce_index_cache_rows(rows, index)
            if rows:
                return rows, "baostock_index"
            errors.append("baostock_index:empty")
        except Exception as e:
            errors.append(f"baostock_index:{type(e).__name__}: {str(e)[:120]}")

    if not _AK_AVAILABLE:
        raise RuntimeError("; ".join(errors) or "akshare 未安装")
    symbol = str(index["symbol"])
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=days + 45)).strftime("%Y%m%d")
    try:
        df = ak.stock_zh_index_daily_em(symbol=symbol, start_date=start, end_date=end)
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_index_em", currency=str(index.get("currency", "CNY"))
            ), "akshare_index_em"
        errors.append("akshare_index_em:empty")
    except Exception as e:
        errors.append(f"akshare_index_em:{type(e).__name__}: {str(e)[:120]}")
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_index_sina", currency=str(index.get("currency", "CNY"))
            ), "akshare_index_sina"
        errors.append("akshare_index_sina:empty")
    except Exception as e:
        errors.append(f"akshare_index_sina:{type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError("; ".join(errors) or "指数行情源不可用")


def _fetch_us_index_kline(index: dict[str, Any], days: int) -> tuple[list[dict[str, Any]], str]:
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    errors: list[str] = []
    symbol = str(index.get("symbol", ".INX"))
    try:
        df = ak.index_us_stock_sina(symbol=symbol)
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_us_index_sina", currency=str(index.get("currency", "USD"))
            ), "akshare_us_index_sina"
        errors.append("akshare_us_index_sina:empty")
    except Exception as e:
        errors.append(f"akshare_us_index_sina:{type(e).__name__}: {str(e)[:120]}")
    try:
        df = ak.stock_us_daily(symbol=symbol, adjust="")
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_us_daily_sina", currency=str(index.get("currency", "USD"))
            ), "akshare_us_daily_sina"
        errors.append("akshare_us_daily_sina:empty")
    except Exception as e:
        errors.append(f"akshare_us_daily_sina:{type(e).__name__}: {str(e)[:120]}")
    try:
        df = ak.index_global_hist_em(symbol=str(index.get("em_symbol", index.get("label", ""))))
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_global_index_em", currency=str(index.get("currency", "USD"))
            ), "akshare_global_index_em"
        errors.append("akshare_global_index_em:empty")
    except Exception as e:
        errors.append(f"akshare_global_index_em:{type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError("; ".join(errors) or "指数行情源不可用")


def _fetch_hk_index_kline(index: dict[str, Any], days: int) -> tuple[list[dict[str, Any]], str]:
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    errors: list[str] = []
    symbol = str(index.get("symbol", "HSTECH"))
    try:
        df = ak.stock_hk_index_daily_sina(symbol=symbol)
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_hk_index_sina", currency=str(index.get("currency", "HKD"))
            ), "akshare_hk_index_sina"
        errors.append("akshare_hk_index_sina:empty")
    except Exception as e:
        errors.append(f"akshare_hk_index_sina:{type(e).__name__}: {str(e)[:120]}")
    try:
        df = ak.stock_hk_index_daily_em(symbol=symbol)
        if df is not None and len(df) > 0:
            rows = [dict(row) for _, row in df.tail(days).iterrows()]
            return _normalize_index_rows(
                rows, _index_cache_code(index), source="akshare_hk_index_em", currency=str(index.get("currency", "HKD"))
            ), "akshare_hk_index_em"
        errors.append("akshare_hk_index_em:empty")
    except Exception as e:
        errors.append(f"akshare_hk_index_em:{type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError("; ".join(errors) or "指数行情源不可用")


def _fetch_market_index_kline(index: dict[str, Any], days: int) -> tuple[list[dict[str, Any]], str]:
    source = index.get("source")
    if source == "cn_index":
        return _fetch_cn_index_kline(index, days)
    if source == "us_index":
        return _fetch_us_index_kline(index, days)
    if source == "hk_index":
        return _fetch_hk_index_kline(index, days)
    raise RuntimeError(f"未知指数源:{source}")


def _fetch_akshare_index_kline(symbol: str, days: int) -> tuple[list[dict[str, Any]], str]:
    """兼容旧测试/调用方:按 A 股指数符号拉 AKShare 日线。"""
    index = {
        "id": symbol,
        "label": symbol,
        "symbol": symbol,
        "cache_code": symbol,
        "source": "cn_index",
        "currency": "CNY",
        "color": "#dc2626",
    }
    return _fetch_cn_index_kline(index, days)


def _index_series_from_rows(index: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    points = []
    clean = [row for row in rows if row.get("date") or row.get("trade_date")]
    clean.sort(key=lambda row: _date_key(row.get("date") or row.get("trade_date")))
    if len(clean) < 2:
        return None
    base = _to_float(clean[0].get("close"), None)
    if base in (None, 0):
        return None
    for row in clean:
        close = _to_float(row.get("close"), None)
        if close is None:
            continue
        ret = round((close - base) / base * 100, 4)
        points.append({
            "date": _date_key(row.get("date") or row.get("trade_date")),
            "close": ret,
            "index_close": close,
            "change_pct": row.get("change_pct", 0),
            "volume": row.get("volume") or row.get("volume_shares") or 0,
            "amount": row.get("amount") or 0,
        })
    if len(points) < 2:
        return None
    return {
        "id": index["id"],
        "market": index.get("market_label", ""),
        "label": index["label"],
        "color": index["color"],
        "points": points,
    }


def _watchlist_equal_weight_series(days: int) -> dict[str, Any] | None:
    try:
        import kb
    except Exception:
        return None

    stocks: list[dict[str, Any]] = []
    for item in kb.scan_market(kind="watchlist"):
        if item.get("status") and item.get("status") not in ("active", "watching"):
            continue
        market, code = kb.parse_ticker(item.get("ticker", ""))
        if not market or not code:
            continue
        rows = kb_market_cache.load_daily_kline(market, code, adjust="qfq", limit=days)
        points = []
        for row in rows:
            trade_date = _date_key(row.get("date") or row.get("trade_date"))
            close = _to_float(row.get("close") or row.get("price"), None)
            if not trade_date or close is None:
                continue
            points.append({
                "date": str(trade_date),
                "close": close,
                "volume": row.get("volume") or row.get("volume_shares") or 0,
                "amount": row.get("amount") or 0,
            })
        if len(points) >= 2:
            stocks.append({"id": item.get("id", ""), "points": points[-days:]})

    by_date: dict[str, dict[str, Any]] = {}
    for stock in stocks:
        points = stock["points"]
        base = _to_float(points[0].get("close"), None)
        if base in (None, 0):
            continue
        for point in points:
            trade_date = point["date"]
            bucket = by_date.setdefault(trade_date, {"date": trade_date, "ret": 0.0, "count": 0, "volume": 0, "amount": 0})
            bucket["ret"] += ((_to_float(point.get("close"), 0) or 0) - base) / base * 100
            bucket["count"] += 1
            bucket["volume"] += point.get("volume") or 0
            bucket["amount"] += point.get("amount") or 0

    prev_ret: float | None = None
    points = []
    for trade_date in sorted(by_date):
        bucket = by_date[trade_date]
        if not bucket["count"]:
            continue
        ret = round(bucket["ret"] / bucket["count"], 4)
        points.append({
            "date": trade_date,
            "close": ret,
            "index_close": round(100 + ret, 4),
            "change_pct": 0.0 if prev_ret is None else round(ret - prev_ret, 4),
            "volume": bucket["volume"],
            "amount": bucket["amount"],
        })
        prev_ret = ret

    if len(points) < 2:
        return None
    return {
        "id": _WATCHLIST_EQUAL_WEIGHT_INDEX["id"],
        "market": _WATCHLIST_EQUAL_WEIGHT_INDEX["market_label"],
        "label": _WATCHLIST_EQUAL_WEIGHT_INDEX["label"],
        "color": _WATCHLIST_EQUAL_WEIGHT_INDEX["color"],
        "points": points[-days:],
    }


def _index_card_from_series(index: dict[str, Any], series: dict[str, Any]) -> dict[str, Any] | None:
    points = series.get("points") or []
    if not points:
        return None
    last = points[-1]
    value = _to_float(last.get("index_close"), None)
    if value is None:
        close_ret = _to_float(last.get("close"), 0.0) or 0.0
        value = 100 + close_ret
    change_pct = _to_float(last.get("change_pct"), None)
    if change_pct is None and len(points) >= 2:
        change_pct = (_to_float(last.get("close"), 0.0) or 0.0) - (_to_float(points[-2].get("close"), 0.0) or 0.0)
    return {
        "id": index["id"],
        "market": index.get("market_label", ""),
        "label": index["label"],
        "value": round(value, 2),
        "change_pct": round(change_pct or 0.0, 2),
        "return_pct": round(_to_float(last.get("close"), 0.0) or 0.0, 2),
        "updated_at": last.get("date", ""),
        "currency": index.get("currency", ""),
    }


def _market_breadth_cache() -> dict[str, Any] | None:
    cached = kb_market_cache.load_detail_block("_MARKET", _MARKET_BREADTH_CODE, _MARKET_BREADTH_BLOCK)
    if isinstance(cached, dict) and cached:
        cached = dict(cached)
        cached["stale"] = True
        return cached
    return None


def _format_summary_pct(value: Any) -> str:
    n = _to_float(value, None)
    return "—" if n is None else f"{n:+.2f}%"


def _format_summary_pair(left: Any, right: Any) -> str:
    l = _to_int(left, None)
    r = _to_int(right, None)
    return f"{l if l is not None else '—'} / {r if r is not None else '—'}"


def _summary_trend(left: Any, right: Any) -> float:
    l = _to_float(left, None)
    r = _to_float(right, None)
    if l is None or r is None:
        return 0.0
    return l - r


def _market_breadth_summary(breadth: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = breadth or {}
    return [
        {
            "label": "上涨/下跌家数",
            "value": _format_summary_pair(data.get("up_count"), data.get("down_count")),
            "trend": _summary_trend(data.get("up_count"), data.get("down_count")),
        },
        {
            "label": "全市场收益中位数",
            "value": _format_summary_pct(data.get("median_change_pct")),
            "trend": _to_float(data.get("median_change_pct"), 0.0) or 0.0,
        },
        {
            "label": "创20日新高/新低",
            "value": _format_summary_pair(data.get("high20_count"), data.get("low20_count")),
            "trend": _summary_trend(data.get("high20_count"), data.get("low20_count")),
        },
        {
            "label": "涨停/跌停数量",
            "value": _format_summary_pair(data.get("limit_up_count"), data.get("limit_down_count")),
            "trend": _summary_trend(data.get("limit_up_count"), data.get("limit_down_count")),
        },
    ]


def get_cached_market_breadth() -> dict[str, Any] | None:
    """只读 SQLite 中的市场宽度摘要,不访问外部源。"""
    return _market_breadth_cache()


def _median(values: list[float]) -> float | None:
    clean = sorted(v for v in values if v is not None and math.isfinite(v))
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 4)
    return round((clean[mid - 1] + clean[mid]) / 2, 4)


def _latest_cn_trade_date() -> str:
    rows = kb_market_cache.load_daily_kline("IDX", "sh000300", adjust="none", limit=1)
    if rows:
        trade_date = _date_key(rows[-1].get("date") or rows[-1].get("trade_date"))
        if trade_date:
            return trade_date.replace("-", "")
    dt = date.today()
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")


def _count_rows(df: Any) -> int | None:
    if df is None:
        return None
    try:
        return int(len(df))
    except Exception:
        return None


def _fetch_market_high_low_20() -> dict[str, Any]:
    df = ak.stock_a_high_low_statistics(symbol="all")
    if df is None or len(df) == 0:
        raise RuntimeError("high_low_empty")
    row = dict(df.tail(1).iloc[0])
    return {
        "high20_count": _to_int(row.get("high20"), None),
        "low20_count": _to_int(row.get("low20"), None),
        "high_low_date": _date_key(row.get("date")),
    }


def _fetch_a_spot_rows_direct() -> list[dict[str, Any]]:
    params = {
        "pn": "1",
        "pz": "6000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f12,f14",
    }
    errors: list[str] = []
    for host in ("push2.eastmoney.com", "82.push2.eastmoney.com", "79.push2.eastmoney.com"):
        url = f"https://{host}/api/qt/clist/get"
        try:
            resp = _EM_SESSION.get(url, params=params, timeout=_EM_TIMEOUT)
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
            rows = data.get("diff") or []
            if rows:
                return rows
            errors.append(f"{host}:empty")
        except Exception as e:
            errors.append(f"{host}:{type(e).__name__}: {str(e)[:100]}")
    raise RuntimeError("; ".join(errors))


def _spot_df_changes(df: Any) -> list[float]:
    changes = []
    if df is None or len(df) == 0:
        return changes
    for _, row in df.iterrows():
        change = _to_float(_field(row, "涨跌幅"), None)
        price = _to_float(_field(row, "最新价"), None)
        if change is None or price is None or price <= 0:
            continue
        changes.append(change)
    return changes


def _fetch_a_spot_changes() -> list[float]:
    errors: list[str] = []
    for name, fn in (
        ("eastmoney_ak", lambda: _spot_df_changes(ak.stock_zh_a_spot_em())),
        ("sina_ak", lambda: _spot_df_changes(ak.stock_zh_a_spot())),
    ):
        try:
            changes = fn()
            if changes:
                return changes
            errors.append(f"{name}:empty")
        except Exception as e:
            errors.append(f"{name}:{type(e).__name__}: {str(e)[:120]}")

    try:
        for row in _fetch_a_spot_rows_direct():
            change = _to_float(_field(row, "f3", "涨跌幅"), None)
            price = _to_float(_field(row, "f2", "最新价"), None)
            if change is None or price is None or price <= 0:
                continue
            changes.append(change)
        if changes:
            return changes
        errors.append("eastmoney_direct:empty")
    except Exception as e:
        errors.append(f"eastmoney_direct:{type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError("; ".join(errors))


def _fetch_limit_pool_count(fn: Any, trade_date: str) -> tuple[int | None, str]:
    start = datetime.strptime(trade_date, "%Y%m%d").date()
    errors: list[str] = []
    for offset in range(0, 8):
        day = (start - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            count = _count_rows(fn(date=day))
            if count is not None:
                return count, day
        except Exception as e:
            errors.append(f"{day}:{type(e).__name__}: {str(e)[:80]}")
    raise RuntimeError("; ".join(errors) or "limit_pool_unavailable")


def _fetch_market_breadth() -> dict[str, Any]:
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    errors: dict[str, str] = {}
    payload: dict[str, Any] = {
        "ok": True,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare",
    }

    try:
        changes = _fetch_a_spot_changes()
        payload.update({
            "total_count": len(changes),
            "up_count": sum(1 for v in changes if v > 0),
            "down_count": sum(1 for v in changes if v < 0),
            "flat_count": sum(1 for v in changes if abs(v) < 0.0001),
            "median_change_pct": _median(changes),
        })
    except Exception as e:
        errors["spot"] = f"{type(e).__name__}: {str(e)[:160]}"

    try:
        payload.update(_fetch_market_high_low_20())
    except Exception as e:
        errors["high_low_20"] = f"{type(e).__name__}: {str(e)[:160]}"

    limit_date = str(payload.get("high_low_date") or _latest_cn_trade_date()).replace("-", "")
    if len(limit_date) != 8:
        limit_date = _latest_cn_trade_date()
    try:
        limit_up, used_date = _fetch_limit_pool_count(ak.stock_zt_pool_em, limit_date)
        payload["limit_up_count"] = limit_up
        payload["limit_date"] = used_date
    except Exception as e:
        errors["limit_up"] = f"{type(e).__name__}: {str(e)[:160]}"
    try:
        limit_down, used_date = _fetch_limit_pool_count(ak.stock_zt_pool_dtgc_em, limit_date)
        payload["limit_down_count"] = limit_down
        payload["limit_date"] = payload.get("limit_date") or used_date
    except Exception as e:
        errors["limit_down"] = f"{type(e).__name__}: {str(e)[:160]}"

    payload["errors"] = errors
    if not any(
        payload.get(key) is not None
        for key in ("up_count", "down_count", "median_change_pct", "high20_count", "low20_count", "limit_up_count", "limit_down_count")
    ):
        raise RuntimeError("; ".join(f"{k}:{v}" for k, v in errors.items()) or "market_breadth_empty")
    kb_market_cache.upsert_detail_block("_MARKET", _MARKET_BREADTH_CODE, _MARKET_BREADTH_BLOCK, payload, source="akshare")
    return payload


def _market_trends_payload(
    series: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    *,
    updated_at: str = "",
    stale: bool = False,
    errors: dict[str, str] | None = None,
    breadth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not series:
        return {
            "ok": False,
            "view": "market",
            "title": "市场趋势",
            "series": [],
            "cards": [],
            "summary": [],
            "updated_at": "",
            "stale": stale,
            "error": "暂无市场趋势数据",
            "error_detail": "; ".join(f"{k}:{v}" for k, v in (errors or {}).items()),
        }

    summary = _market_breadth_summary(breadth)

    return {
        "ok": True,
        "view": "market",
        "title": "市场趋势",
        "series": series,
        "cards": cards,
        "summary": summary,
        "breadth": breadth or {},
        "updated_at": updated_at,
        "stale": stale,
        "errors": errors or {},
    }


def get_cached_market_trends(days: int = 90) -> dict[str, Any]:
    """只读 SQLite 缓存构建市场趋势,不访问外部行情源。"""
    days = max(30, min(int(days), 365))
    series = []
    cards = []
    updated_at = ""
    for index in _MARKET_INDEXES:
        code = _index_cache_code(index)
        rows = kb_market_cache.load_daily_kline("IDX", code, adjust="none", limit=days)
        s = _index_series_from_rows(index, _with_legacy_volume_alias(rows))
        if s is None:
            continue
        series.append(s)
        card = _index_card_from_series(index, s)
        if card is not None:
            cards.append(card)
        if rows:
            updated_at = max(updated_at, str(
                rows[-1].get("fetched_at") or rows[-1].get("date") or rows[-1].get("trade_date") or ""
            ))

    watch_series = _watchlist_equal_weight_series(days)
    if watch_series is not None:
        series.append(watch_series)
        card = _index_card_from_series(_WATCHLIST_EQUAL_WEIGHT_INDEX, watch_series)
        if card is not None:
            cards.append(card)
            updated_at = max(updated_at, str(card.get("updated_at", "")))

    breadth = get_cached_market_breadth()
    if breadth and breadth.get("updated_at"):
        updated_at = max(updated_at, str(breadth.get("updated_at", "")))
    return _market_trends_payload(series, cards, updated_at=updated_at, stale=True, breadth=breadth)


def get_market_trends(days: int = 90) -> dict[str, Any]:
    """市场指数趋势。外部源成功写 SQLite,失败优先读旧缓存。"""
    days = max(30, min(int(days), 365))
    series = []
    cards = []
    errors: dict[str, str] = {}
    stale = False
    updated_at = ""

    for index in _MARKET_INDEXES:
        code = _index_cache_code(index)
        rows: list[dict[str, Any]] = []
        source = ""
        try:
            rows, source = _fetch_market_index_kline(index, days)
            if rows:
                kb_market_cache.upsert_daily_kline(rows, source=source)
                kb_market_cache.record_fetch_status("IDX", code, "daily_kline", source, ok=True)
        except Exception as e:
            errors[code] = str(e)[:180]
            cached = kb_market_cache.load_daily_kline("IDX", code, adjust="none", limit=days)
            if cached:
                rows = cached
                source = "sqlite"
                stale = True
        s = _index_series_from_rows(index, _with_legacy_volume_alias(rows))
        if s is not None:
            series.append(s)
            card = _index_card_from_series(index, s)
            if card is not None:
                cards.append(card)
            if rows:
                updated_at = max(updated_at, str(
                    rows[-1].get("fetched_at") or rows[-1].get("date") or rows[-1].get("trade_date") or ""
                ))

    watch_series = _watchlist_equal_weight_series(days)
    if watch_series is not None:
        series.append(watch_series)
        card = _index_card_from_series(_WATCHLIST_EQUAL_WEIGHT_INDEX, watch_series)
        if card is not None:
            cards.append(card)
            updated_at = max(updated_at, str(card.get("updated_at", "")))

    breadth = None
    try:
        breadth = _fetch_market_breadth()
        if breadth.get("updated_at"):
            updated_at = max(updated_at, str(breadth.get("updated_at", "")))
    except Exception as e:
        errors["market_breadth"] = str(e)[:180]
        breadth = get_cached_market_breadth()
        if breadth is not None:
            stale = True
            if breadth.get("updated_at"):
                updated_at = max(updated_at, str(breadth.get("updated_at", "")))

    return _market_trends_payload(series, cards, updated_at=updated_at, stale=stale, errors=errors, breadth=breadth)


def _industry_color(idx: int) -> str:
    return _INDUSTRY_COLORS[idx % len(_INDUSTRY_COLORS)]


def _cached_industry_trends(cache_key: str) -> dict[str, Any] | None:
    cached = kb_market_cache.load_detail_block("_MARKET", "industry_trends", cache_key)
    if isinstance(cached, dict) and cached.get("series"):
        cached = dict(cached)
        cached["stale"] = True
        return cached
    return None


def get_cached_industry_trends(days: int = 90, top_n: int = 8) -> dict[str, Any]:
    """只读 SQLite 派生缓存中的行业趋势聚合结果,不访问外部行情源。"""
    days = max(30, min(int(days), 365))
    top_n = max(5, min(int(top_n), 16))
    cached = _cached_industry_trends(f"{days}:{top_n}")
    if cached is not None:
        return cached
    return {
        "ok": False,
        "view": "industry",
        "title": "行业趋势",
        "series": [],
        "heatmap": [],
        "summary": [],
        "updated_at": "",
        "stale": True,
        "error": "暂无行业趋势缓存",
    }


def _fetch_em_industry_candidates(top_n: int) -> list[dict[str, Any]]:
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90 t:2 f:!50",
        "fields": "f3,f8,f12,f14,f128,f136",
    }
    r = _EM_SESSION.get(url, params=params, timeout=_EM_TIMEOUT)
    r.raise_for_status()
    data = r.json().get("data") or {}
    diff = data.get("diff") or []
    if not diff:
        return []

    rows: list[dict[str, Any]] = []
    for row in diff:
        label = str(row.get("f14") or "").strip()
        code = str(row.get("f12") or label).strip()
        if not label or not code:
            continue
        rows.append({
            "id": code,
            "label": label,
            "change_pct": _to_float(row.get("f3"), 0.0) or 0.0,
            "turnover": _to_float(row.get("f8"), None),
            "lead_stock": str(row.get("f128") or ""),
            "lead_stock_change_pct": _to_float(row.get("f136"), None),
        })
    if not rows:
        return []

    ranked = sorted(rows, key=lambda x: x.get("change_pct", 0.0), reverse=True)
    strong_count = max(1, int(math.ceil(top_n * 0.7)))
    weak_count = max(0, top_n - strong_count)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ranked[:strong_count] + list(reversed(ranked[-weak_count:] if weak_count else [])):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        picked.append(item)
        if len(picked) >= top_n:
            break
    return picked


def _fetch_ths_industry_candidates(top_n: int) -> list[dict[str, Any]]:
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    df = ak.stock_board_industry_name_ths()
    if df is None or len(df) == 0:
        return []

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        label = str(_field(row, "name", "板块名称") or "").strip()
        code = str(_field(row, "code", "板块代码") or label).strip()
        if not label or not code:
            continue
        rows.append({
            "id": f"THS{code}",
            "label": label,
            "source": "ths",
            "change_pct": 0.0,
            "turnover": None,
            "lead_stock": "",
            "lead_stock_change_pct": None,
        })
    return rows[:top_n]


def _fetch_industry_candidates(top_n: int) -> list[dict[str, Any]]:
    global _em_industry_failure_until
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    if time.monotonic() >= _em_industry_failure_until:
        try:
            rows = _fetch_em_industry_candidates(top_n)
            if rows:
                _em_industry_failure_until = 0.0
                for row in rows:
                    row["source"] = "em"
                return rows
        except Exception:
            _em_industry_failure_until = time.monotonic() + _EM_INDUSTRY_FAILURE_TTL_SECONDS
    return _fetch_ths_industry_candidates(top_n)


def _normalize_industry_rows(raw_rows: list[dict[str, Any]], board: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    code = str(board.get("id") or board.get("label") or "")
    for raw in raw_rows:
        trade_date = _field(raw, "日期", "date", "trade_date")
        if hasattr(trade_date, "isoformat"):
            trade_date = trade_date.isoformat()
        close = _to_float(_field(raw, "收盘", "收盘价", "close"), None)
        if not trade_date or close is None:
            continue
        item = _normalized_row_base("IND", code, str(trade_date), "none")
        item.update({
            "currency": "CNY",
            "open": _to_float(_field(raw, "开盘", "开盘价", "open"), None),
            "high": _to_float(_field(raw, "最高", "最高价", "high"), None),
            "low": _to_float(_field(raw, "最低", "最低价", "low"), None),
            "close": close,
            "price": close,
            "change_amt": _to_float(_field(raw, "涨跌额", "change_amt"), None),
            "change_pct": _to_float(_field(raw, "涨跌幅", "change_pct"), None),
            "volume_shares": _to_int(_field(raw, "成交量", "volume"), None),
            "amount": _to_float(_field(raw, "成交额", "amount"), None),
            "amplitude": _to_float(_field(raw, "振幅", "amplitude"), None),
            "turnover": _to_float(_field(raw, "换手率", "turnover"), None),
            "source": source,
        })
        rows.append(item)

    rows.sort(key=lambda x: x.get("trade_date", ""))
    prev_close = None
    for row in rows:
        close = row.get("close")
        if close is not None and prev_close not in (None, 0) and row.get("change_pct") is None:
            row["preclose"] = prev_close
            row["change_amt"] = round(close - prev_close, 4)
            row["change_pct"] = round((close - prev_close) / prev_close * 100, 4)
        if row.get("change_pct") is None:
            row["change_pct"] = 0.0
        prev_close = close
    return rows


def _fetch_akshare_industry_kline(board: dict[str, Any], days: int) -> tuple[list[dict[str, Any]], str]:
    if not _AK_AVAILABLE:
        raise RuntimeError("akshare 未安装")
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=days + 45)).strftime("%Y%m%d")
    if board.get("source") == "ths":
        df = ak.stock_board_industry_index_ths(
            symbol=str(board.get("label") or ""),
            start_date=start,
            end_date=end,
        )
        if df is None or len(df) == 0:
            return [], "akshare_industry_ths"
        rows = [dict(row) for _, row in df.tail(days).iterrows()]
        return _normalize_industry_rows(rows, board, source="akshare_industry_ths"), "akshare_industry_ths"

    symbol = str(board.get("id") or board.get("label") or "")
    df = ak.stock_board_industry_hist_em(
        symbol=symbol,
        start_date=start,
        end_date=end,
        period="日k",
        adjust="",
    )
    if df is None or len(df) == 0:
        return [], "akshare_industry_em"
    rows = [dict(row) for _, row in df.tail(days).iterrows()]
    return _normalize_industry_rows(rows, board, source="akshare_industry_em"), "akshare_industry_em"


def _series_delta(points: list[dict[str, Any]], n: int) -> float:
    if len(points) < 2:
        return 0.0
    idx = max(0, len(points) - 1 - n)
    last = _to_float(points[-1].get("close"), 0.0) or 0.0
    prev = _to_float(points[idx].get("close"), 0.0) or 0.0
    return round(last - prev, 4)


def _points_volatility(points: list[dict[str, Any]]) -> float:
    vals = [_to_float(p.get("change_pct"), None) for p in points]
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return 0.0
    avg = sum(vals) / len(vals)
    variance = sum((v - avg) ** 2 for v in vals) / len(vals)
    return round(math.sqrt(variance), 4)


def _industry_series_from_rows(board: dict[str, Any], rows: list[dict[str, Any]], idx: int) -> dict[str, Any] | None:
    clean = [row for row in rows if row.get("date") or row.get("trade_date")]
    clean.sort(key=lambda row: str(row.get("date") or row.get("trade_date") or ""))
    if len(clean) < 2:
        return None
    base = _to_float(clean[0].get("close"), None)
    if base in (None, 0):
        return None

    points = []
    for row in clean:
        close = _to_float(row.get("close"), None)
        if close is None:
            continue
        ret = round((close - base) / base * 100, 4)
        points.append({
            "date": row.get("date") or row.get("trade_date"),
            "close": ret,
            "board_close": close,
            "change_pct": _to_float(row.get("change_pct"), 0.0) or 0.0,
            "volume": row.get("volume") or row.get("volume_shares") or 0,
            "amount": row.get("amount") or 0,
            "turnover": row.get("turnover"),
        })
    if len(points) < 2:
        return None

    d5 = _series_delta(points, 5)
    d20 = _series_delta(points, 20)
    strength = "偏强" if d20 > 3 else ("偏弱" if d20 < -3 else "震荡")
    return {
        "id": str(board.get("id") or board.get("label")),
        "label": str(board.get("label") or board.get("id")),
        "color": _industry_color(idx),
        "points": points,
        "sort_value": d20,
        "summary": {
            "d5": d5,
            "d20": d20,
            "volatility": _points_volatility(points),
            "strength": strength,
            "turnover": board.get("turnover"),
            "lead_stock": board.get("lead_stock", ""),
            "lead_stock_change_pct": board.get("lead_stock_change_pct"),
        },
    }


def _industry_heatmap(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells = []
    for s in series:
        for p in s.get("points", []):
            cells.append({
                "industry_id": s.get("id", ""),
                "industry": s.get("label", ""),
                "date": p.get("date", ""),
                "value": p.get("close", 0),
                "change_pct": p.get("change_pct", 0),
                "amount": p.get("amount", 0),
                "volume": p.get("volume", 0),
            })
    return cells


def get_industry_trends(days: int = 90, top_n: int = 8, max_workers: int = 4) -> dict[str, Any]:
    """行业板块轮动趋势。主数据源为 AKShare 东方财富行业板块日 K。"""
    days = max(30, min(int(days), 365))
    top_n = max(5, min(int(top_n), 16))
    max_workers = max(1, min(int(max_workers), 4, top_n))
    cache_key = f"{days}:{top_n}"
    cached = _cached_industry_trends(cache_key)
    if not _AK_AVAILABLE:
        if cached is not None:
            return cached
        return {
            "ok": False,
            "view": "industry",
            "title": "行业趋势",
            "series": [],
            "heatmap": [],
            "summary": [],
            "updated_at": "",
            "stale": False,
            "error": "akshare 未安装",
        }

    errors: dict[str, str] = {}
    stale = False
    updated_at = ""
    try:
        candidates = _fetch_industry_candidates(top_n)
    except Exception as e:
        if cached is not None:
            return cached
        return {
            "ok": False,
            "view": "industry",
            "title": "行业趋势",
            "series": [],
            "heatmap": [],
            "summary": [],
            "updated_at": "",
            "stale": False,
            "error": "行业列表拉取失败",
            "error_detail": f"{type(e).__name__}: {str(e)[:180]}",
        }

    def _fetch_one(args: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any], list[dict[str, Any]], str]:
        idx, board = args
        code = str(board.get("id") or board.get("label") or "")
        rows: list[dict[str, Any]] = []
        try:
            rows, source = _fetch_akshare_industry_kline(board, days)
            if rows:
                kb_market_cache.upsert_daily_kline(rows, source=source)
                kb_market_cache.record_fetch_status("IND", code, "daily_kline", source, ok=True)
            return idx, board, rows, ""
        except Exception as e:
            cached_rows = kb_market_cache.load_daily_kline("IND", code, adjust="none", limit=days)
            if cached_rows:
                return idx, board, cached_rows, f"{type(e).__name__}: {str(e)[:160]}"
            return idx, board, [], f"{type(e).__name__}: {str(e)[:160]}"

    series: list[dict[str, Any]] = []
    fetch_args = list(enumerate(candidates))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fetched = list(pool.map(_fetch_one, fetch_args))

    for idx, board, rows, error in fetched:
        code = str(board.get("id") or board.get("label") or "")
        if error:
            errors[code] = error
            if rows:
                stale = True
        s = _industry_series_from_rows(board, _with_legacy_volume_alias(rows), idx)
        if s is not None:
            series.append(s)
            if rows:
                updated_at = max(updated_at, str(
                    rows[-1].get("fetched_at") or rows[-1].get("date") or rows[-1].get("trade_date") or ""
                ))

    if not series:
        if cached is not None:
            return cached
        return {
            "ok": False,
            "view": "industry",
            "title": "行业趋势",
            "series": [],
            "heatmap": [],
            "summary": [],
            "updated_at": "",
            "stale": stale,
            "error": "暂无行业趋势数据",
            "error_detail": "; ".join(f"{k}:{v}" for k, v in errors.items()),
        }

    series.sort(key=lambda x: x.get("sort_value", 0), reverse=True)
    for idx, s in enumerate(series):
        s["color"] = _industry_color(idx)

    best = series[0]
    weakest = series[-1]
    summary = [
        {"label": "最强行业", "value": f"{best['label']} {best['sort_value']:+.2f}%", "trend": best.get("sort_value", 0)},
        {"label": "最弱行业", "value": f"{weakest['label']} {weakest['sort_value']:+.2f}%", "trend": weakest.get("sort_value", 0)},
        {"label": "样本行业", "value": f"{len(series)} 个", "trend": 0},
        {"label": "当前周期", "value": f"{days} 日", "trend": 0},
    ]
    result = {
        "ok": True,
        "view": "industry",
        "title": "行业趋势",
        "series": series,
        "heatmap": _industry_heatmap(series),
        "summary": summary,
        "updated_at": updated_at,
        "stale": stale,
        "errors": errors,
    }
    kb_market_cache.upsert_detail_block("_MARKET", "industry_trends", cache_key, result, source="akshare")
    return result


def _calc_change_pct(df) -> tuple[float, float]:
    """从日K线 DataFrame 算最新涨跌幅(%)。返回 (收盘价, 涨跌幅%)。"""
    if df is None or len(df) == 0:
        return (0.0, 0.0)
    close_col = "收盘" if "收盘" in df.columns else df.columns[-1]
    latest = float(df.iloc[-1][close_col])
    if len(df) >= 2:
        prev = float(df.iloc[-2][close_col])
        pct = round((latest - prev) / prev * 100, 2) if prev else 0.0
    else:
        pct = 0.0
    return (latest, pct)


def _extract_kline(df, n: int = 30) -> list[dict]:
    """从日K线 DataFrame 取最近 n 天的 {date, close}。"""
    if df is None or len(df) == 0:
        return []
    close_col = "收盘" if "收盘" in df.columns else df.columns[-1]
    date_col = "日期" if "日期" in df.columns else df.columns[0]
    tail = df.tail(n)
    return [
        {"date": str(row[date_col]), "close": round(float(row[close_col]), 3)}
        for _, row in tail.iterrows()
    ]


def get_quote(market: str, code: str, days: int = 30) -> dict:
    """拉单只股票行情。

    Args:
        market: SH/SZ/BJ/HK/US
        code: 纯代码(不含市场前缀),如 600519 / 00700 / AAPL
        days: K线天数(默认30)

    Returns:
        {ok, market, code, name?, price, change_pct, kline, error?}
        ok=False 时带 error 字段(akshare 缺失 / 拉取失败 / 不支持的市场)
    """
    mkt = market.upper()
    if mkt not in ("SH", "SZ", "BJ", "HK", "US"):
        return {"ok": False, "market": market, "code": code, "error": f"不支持的市场:{market}"}
    result = get_history_kline(mkt, code, days, adjust="qfq")
    result = _apply_akshare_realtime_quote(result, mkt, code)
    snapshot_source = str(result.get("quote_source") or result.get("source") or "history")
    if result.get("ok") and snapshot_source != "sqlite":
        kb_market_cache.upsert_quote_snapshot(result, source=snapshot_source)
    return result


def get_quote_batch(tickers: list[tuple[str, str]], days: int = 30) -> list[dict]:
    """批量拉行情。tickers = [(market, code), ...]。逐只拉,单只失败不影响其他。

    返回 [{ticker: {market,code}, ...quote}] 列表。
    """
    results = []
    for market, code in tickers:
        q = get_quote(market, code, days)
        q["ticker"] = {"market": market, "code": code}
        results.append(q)
    return results


def is_available() -> bool:
    """任一行情能力是否可用。缓存存在时也允许页面展示旧数据。"""
    return _AK_AVAILABLE or _BAOSTOCK_AVAILABLE or kb_market_cache.has_any_cache()


# ===========================================================================
# 详情页数据(get_stock_detail):K线全字段 + 按市场补充资金流/财务/盘口/个股信息
# 各数据块独立 try/except,单块失败返回 {error} 不阻断其他块。
# ===========================================================================

def _fund_flow_market(market: str) -> str | None:
    """资金流接口的 market 参数:SH→sh, SZ→sz, BJ→bj。非A股返回 None。"""
    return {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market.upper())


def _financial_symbol(market: str, code: str) -> str:
    """财务接口的 symbol 格式(与 K线 不同):
    A股: 688825.SH / 688825.SZ  (加交易所后缀)
    港股: 00700                   (纯代码)
    美股: AAPL                    (纯代码,无 105. 前缀)
    """
    mkt = market.upper()
    if mkt in ("SH", "SZ", "BJ"):
        return f"{code}.{mkt}"
    return code  # HK / US 用纯代码


def _safe_float(v, default=0.0) -> float:
    """安全转 float,pandas/akshare 常返回 NaN/None/str。"""
    try:
        f = float(v)
        import math
        return default if math.isnan(f) else round(f, 4)
    except (TypeError, ValueError):
        return default


def _kline_full(df, n: int = 90) -> list[dict]:
    """K线全字段提取(供前端画蜡烛图+成交量)。列名三市场基本一致。"""
    if df is None or len(df) == 0:
        return []
    colmap = {  # 列名 → 输出键
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "振幅": "amplitude",
        "涨跌幅": "change_pct", "涨跌额": "change_amt", "换手率": "turnover",
    }
    rows = []
    for _, row in df.tail(n).iterrows():
        item = {}
        for cn, key in colmap.items():
            if cn in df.columns:
                item[key] = _safe_float(row[cn]) if key != "date" else str(row[cn])
        if item.get("date"):
            rows.append(item)
    return rows


def _fetch_kline_df(market: str, code: str, days: int, period: str = "daily", adjust: str = "qfq"):
    """拉 K线 DataFrame(三市场,内部用)。返回 df 或 None。"""
    today = date.today()
    start = (today - timedelta(days=days + 30)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    mkt = market.upper()
    ak_adjust = _STD_TO_AK_ADJUST[_normalize_adjust(adjust)]
    if mkt in ("SH", "SZ", "BJ"):
        return ak.stock_zh_a_hist(symbol=code, period=period, start_date=start, end_date=end, adjust=ak_adjust)
    elif mkt == "HK":
        return ak.stock_hk_hist(symbol=code, period=period, start_date=start, end_date=end, adjust=ak_adjust)
    elif mkt == "US":
        return ak.stock_us_hist(symbol=_us_symbol(code), period=period, start_date=start, end_date=end, adjust=ak_adjust)
    return None


def _fetch_sina_daily_df(market: str, code: str, adjust: str = "qfq"):
    """HK/US fallback that avoids EastMoney push2his shards."""
    ak_adjust = _STD_TO_AK_ADJUST[_normalize_adjust(adjust)]
    mkt = market.upper()
    if mkt == "HK":
        return ak.stock_hk_daily(symbol=code, adjust=ak_adjust)
    if mkt == "US":
        return ak.stock_us_daily(symbol=code.upper(), adjust=ak_adjust)
    return None


def _fetch_a_info(code: str) -> dict:
    """A股个股信息(市值/股本/行业/上市日)。返回 dict。"""
    df = ak.stock_individual_info_em(symbol=code)
    info = dict(zip(df["item"].astype(str), df["value"].astype(str)))
    return {
        "总市值": info.get("总市值", ""),
        "流通市值": info.get("流通市值", ""),
        "行业": info.get("行业", ""),
        "总股本": info.get("总股本", ""),
        "流通股": info.get("流通股", ""),
        "上市时间": info.get("上市时间", ""),
    }


def _fetch_a_quote(code: str) -> dict:
    """A股实时盘口(最新价/今开/昨收/量比/换手/5档买卖盘)。返回 dict。"""
    df = ak.stock_bid_ask_em(symbol=code)
    q = dict(zip(df["item"].astype(str), df["value"].astype(str)))
    # 5档买卖盘组织成结构
    bids, asks = [], []
    for i in range(1, 6):
        bids.append({"price": q.get(f"buy_{i}", ""), "vol": q.get(f"buy_{i}_vol", "")})
        asks.append({"price": q.get(f"sell_{i}", ""), "vol": q.get(f"sell_{i}_vol", "")})
    return {
        "最新": q.get("最新", ""), "今开": q.get("今开", ""), "昨收": q.get("昨收", ""),
        "最高": q.get("最高", ""), "最低": q.get("最低", ""),
        "均价": q.get("均价", ""), "涨幅": q.get("涨幅", ""), "涨跌": q.get("涨跌", ""),
        "总手": q.get("总手", ""), "金额": q.get("金额", ""),
        "换手": q.get("换手", ""), "量比": q.get("量比", ""),
        "涨停": q.get("涨停", ""), "跌停": q.get("跌停", ""),
        "外盘": q.get("外盘", ""), "内盘": q.get("内盘", ""),
        "bids": bids, "asks": asks,
    }


def _fetch_a_fund_flow(code: str, market: str) -> list[dict]:
    """A股资金流向(主力/超大/大/中/小单净流入,近10天)。返回 list。"""
    mk = _fund_flow_market(market)
    if not mk:
        return []
    df = ak.stock_individual_fund_flow(stock=code, market=mk)
    # 取最近10天,挑关键列
    cols = {
        "日期": "date", "收盘价": "close", "涨跌幅": "change_pct",
        "主力净流入-净额": "main_net", "主力净流入-净占比": "main_pct",
        "超大单净流入-净额": "xl_net", "大单净流入-净额": "l_net",
        "中单净流入-净额": "m_net", "小单净流入-净额": "s_net",
    }
    rows = []
    for _, row in df.tail(10).iterrows():
        item = {}
        for cn, key in cols.items():
            if cn in df.columns:
                item[key] = _safe_float(row[cn]) if key != "date" else str(row[cn])
        rows.append(item)
    return rows


# 财务指标:三市场列名不同,统一映射成前端用的键
_FIN_KEY_MAP_A = {  # A股(中文键)
    "REPORT_DATE_NAME": "period", "EPSJB": "eps", "BPS": "bps",
    "TOTALOPERATEREVE": "revenue", "PARENTNETPROFIT": "net_profit",
    "XSJLL": "net_margin", "XSMLL": "gross_margin", "ROEJQ": "roe",
    "ZCFZL": "debt_ratio", "LD": "current_ratio",
}
_FIN_KEY_MAP_HK = {  # 港股(英文键)
    "REPORT_DATE": "period", "BASIC_EPS": "eps", "BPS": "bps",
    "OPERATE_INCOME": "revenue", "HOLDER_PROFIT": "net_profit",
    "NET_PROFIT_RATIO": "net_margin", "GROSS_PROFIT_RATIO": "gross_margin",
    "ROE_AVG": "roe", "DEBT_ASSET_RATIO": "debt_ratio", "CURRENT_RATIO": "current_ratio",
}
_FIN_KEY_MAP_US = {  # 美股(英文键)
    "REPORT_DATE": "period", "BASIC_EPS": "eps",
    "OPERATE_INCOME": "revenue", "PARENT_HOLDER_NETPROFIT": "net_profit",
    "NET_PROFIT_RATIO": "net_margin", "GROSS_PROFIT_RATIO": "gross_margin",
    "ROE_AVG": "roe", "DEBT_ASSET_RATIO": "debt_ratio", "CURRENT_RATIO": "current_ratio",
}


def _fetch_financials(market: str, code: str) -> list[dict]:
    """财务指标(最近4期,统一键名)。三市场不同函数+不同symbol格式。"""
    mkt = market.upper()
    if mkt in ("SH", "SZ", "BJ"):
        df = ak.stock_financial_analysis_indicator_em(
            symbol=_financial_symbol(mkt, code), indicator="按报告期")
        keymap = _FIN_KEY_MAP_A
    elif mkt == "HK":
        df = ak.stock_financial_hk_analysis_indicator_em(symbol=code, indicator="报告期")
        keymap = _FIN_KEY_MAP_HK
    elif mkt == "US":
        df = ak.stock_financial_us_analysis_indicator_em(symbol=code, indicator="单季报")
        keymap = _FIN_KEY_MAP_US
    else:
        return []
    if df is None or len(df) == 0:
        return []
    rows = []
    for _, row in df.head(4).iterrows():  # 最近4期
        item = {}
        for src, dst in keymap.items():
            if src in df.columns:
                val = row[src]
                if dst == "period":
                    item[dst] = str(val)
                else:
                    # 大数值(营收/利润)以亿元为单位,方便阅读
                    f = _safe_float(val, None)
                    if f is not None and dst in ("revenue", "net_profit") and abs(f) > 1e8:
                        f = round(f / 1e8, 2)
                        item[dst + "_unit"] = "亿元"
                    item[dst] = f if f is not None else ""
        rows.append(item)
    return rows


# ===========================================================================
# 板块资金流排行(get_sector_fund_flow):行业/概念/地域 主力净流入排行
# 数据源 akshare.stock_sector_fund_flow_rank(indicator, sector_type)。
# indicator 仅 今日/5日/10日(akshare 无分钟级);sector_type 三档。
# 列名前缀随 indicator 变(今日主力净流入-净额 / 5日主力净流入-净额 / 10日...),
# 用「主力净流入-净额」「涨跌幅」等后缀匹配,适配三档。
# ===========================================================================

# indicator / sector_type 白名单(与 akshare 文档一致,非法值直接拒绝,不透传)
_SECTOR_INDICATORS = ("今日", "5日", "10日")
_SECTOR_TYPES = ("行业资金流", "概念资金流", "地域资金流")


def _pick_col(columns, *suffixes):
    """按后缀匹配列名(列名前缀随 indicator 变,后缀稳定)。
    suffixes 按优先级匹配,返回第一个命中的列名;都未命中返回 None。
    """
    for suf in suffixes:
        for c in columns:
            if isinstance(c, str) and c.endswith(suf):
                return c
    return None


def _cached_sector_fund_flow(block_key: str) -> dict[str, Any] | None:
    cached = kb_market_cache.load_detail_block("_MARKET", "fund_flow", block_key)
    if isinstance(cached, dict):
        cached = dict(cached)
        cached["stale"] = True
        return cached
    return None


def get_sector_fund_flow(indicator: str = "今日", sector_type: str = "行业资金流", top_n: int = 20) -> dict:
    """行业/概念/地域板块资金流排行(akshare)。

    Args:
        indicator: 今日 / 5日 / 10日(akshare 仅此三档,无实时/分钟级)
        sector_type: 行业资金流 / 概念资金流 / 地域资金流
        top_n: inflow / outflow 各取前 N 条(限制 5-50)

    Returns:
        {ok, indicator, sector_type, updated_at,
         inflow:[{name, amount, change_pct, main_pct, lead_stock}],
         outflow:[...], error?}
        amount 单位「亿」(主力净流入-净额 原始元 ÷ 1e8,round 2 位)。
        inflow = amount > 0 的项按 amount 降序;outflow = < 0 按 amount 升序(绝对值大在前)。
        ok=False 时带 error(akshare 缺失 / 非法参数 / 拉取失败)。
    """
    block_key = f"{sector_type}:{indicator}"
    if not _AK_AVAILABLE:
        cached = _cached_sector_fund_flow(block_key)
        if cached is not None:
            return cached
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": "akshare 未安装,无法获取资金流。pip install akshare"}
    # 白名单校验(不把任意串透传给 akshare,避免误触发意外请求)
    if indicator not in _SECTOR_INDICATORS:
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": f"非法 indicator:{indicator}(需 {_SECTOR_INDICATORS})"}
    if sector_type not in _SECTOR_TYPES:
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": f"非法 sector_type:{sector_type}(需 {_SECTOR_TYPES})"}
    top_n = max(5, min(int(top_n), 50))

    try:
        df = ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=sector_type)
    except Exception as e:
        cached = _cached_sector_fund_flow(block_key)
        if cached is not None:
            return cached
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": f"拉取失败:{type(e).__name__}: {str(e)[:120]}"}
    if df is None or len(df) == 0:
        cached = _cached_sector_fund_flow(block_key)
        if cached is not None:
            return cached
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": "无数据(数据源可能限流或不可达)"}

    cols = list(df.columns)
    name_col = _pick_col(cols, "名称", "板块")
    amount_col = _pick_col(cols, "主力净流入-净额", "主力净流入-净金额")
    change_col = _pick_col(cols, "涨跌幅")
    main_pct_col = _pick_col(cols, "主力净流入-净占比", "主力净流入净占比")
    lead_col = _pick_col(cols, "主力净流入最大股", "领涨股")
    if not name_col or not amount_col:
        cached = _cached_sector_fund_flow(block_key)
        if cached is not None:
            return cached
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": f"列结构异常,找不到 名称/主力净流入-净额 列:{cols[:8]}"}

    rows = []
    for _, row in df.iterrows():
        amt = _safe_float(row[amount_col], None)
        if amt is None:
            continue
        item = {
            "name": str(row[name_col]),
            "amount": round(amt / 1e8, 2),  # 元 → 亿
            "change_pct": _safe_float(row[change_col], 0.0) if change_col else 0.0,
            "main_pct": _safe_float(row[main_pct_col], 0.0) if main_pct_col else 0.0,
            "lead_stock": str(row[lead_col]) if lead_col else "",
        }
        rows.append(item)

    # —— 行业去重 / 固定行业层级 ——
    # akshare「行业资金流」会混入申万一级/二级/三级(如「银行」+「银行Ⅱ」、「保险Ⅱ」+「保险Ⅲ」),
    # 偶发同名重复行(两个「白酒Ⅱ」)。统一按「去尾随罗马数字后的规范化名」归组,
    # 优先保留无罗马数字后缀的一级行业(如「银行」),否则取 |净额| 最大的一条,
    # 既去重又锁到同一行业层级,避免气泡里出现层级混用 / 重复名。
    import re as _re
    def _norm_sector(name: str) -> str:
        return _re.sub(r"[\u2160-\u217F]+$", "", str(name)).strip()

    _groups, _order = {}, []
    for r in rows:
        key = _norm_sector(r["name"])
        if key not in _groups:
            _groups[key] = []
            _order.append(key)
        _groups[key].append(r)
    _deduped = []
    for key in _order:
        grp = _groups[key]
        if len(grp) == 1:
            _deduped.append(grp[0])
            continue
        l1 = [x for x in grp if x["name"] == key]  # 无罗马数字后缀的一级行业
        if l1:
            _deduped.append(max(l1, key=lambda x: abs(x["amount"])))
        else:
            _deduped.append(max(grp, key=lambda x: abs(x["amount"])))
    rows = _deduped

    inflow = sorted([r for r in rows if r["amount"] > 0], key=lambda x: x["amount"], reverse=True)[:top_n]
    outflow = sorted([r for r in rows if r["amount"] < 0], key=lambda x: x["amount"])[:top_n]

    from datetime import datetime
    result = {
        "ok": True,
        "indicator": indicator,
        "sector_type": sector_type,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "inflow": inflow,
        "outflow": outflow,
        "count": len(inflow) + len(outflow),
    }
    kb_market_cache.upsert_detail_block("_MARKET", "fund_flow", block_key, result, source="akshare")
    return result


def _merge_cached_detail_blocks(result: dict[str, Any], market: str, code: str, *blocks: str) -> bool:
    wanted = blocks or ("info", "quote", "fund_flow", "financials")
    cached = kb_market_cache.load_detail_blocks(market, code)
    merged = False
    for block in wanted:
        payload = cached.get(block)
        if payload in (None, "", [], {}):
            continue
        result[block] = payload
        _append_unique(result.setdefault("sections", []), block)
        _append_unique(result.setdefault("stale_blocks", []), block)
        if isinstance(result.get("errors"), dict):
            result["errors"].pop(block, None)
        merged = True
    return merged


def get_stock_detail(market: str, code: str, days: int = 90) -> dict:
    """详情页数据:K线全字段 + 按市场补充资金流/财务/盘口/个股信息。

    各数据块独立 try/except,单块失败在 errors 里记录,不阻断其他块。
    返回:
      {ok, market, code, kline:[...全字段], price, change_pct,
       info:{}, quote:{}, fund_flow:[], financials:[],
       sections:[可显示的区块名], errors:{块名:错误}}
    """
    result = {"ok": True, "market": market, "code": code,
              "kline": [], "info": {}, "quote": {}, "fund_flow": [], "financials": [],
              "sections": [], "errors": {}}
    mkt = market.upper()
    days = max(30, min(days, 365))

    # 1. K线(核心):SH/SZ 优先 BaoStock,其他市场保持 AKShare;都失败则读 SQLite。
    hist = get_history_kline(mkt, code, days, adjust="qfq")
    if not hist.get("ok"):
        result["ok"] = False
        result["error"] = hist.get("error", "详情数据拉取失败")
        result["error_detail"] = hist.get("error_detail", "")
        return result
    result["kline"] = hist.get("kline", [])
    result["price"] = hist.get("price", 0)
    result["change_amt"] = hist.get("change_amt")
    result["change_pct"] = hist.get("change_pct", 0)
    result["date"] = hist.get("date", "")
    result["source"] = hist.get("source", "")
    result["currency"] = hist.get("currency", "")
    result["updated_at"] = hist.get("updated_at", "")
    result["stale"] = bool(hist.get("stale"))
    result["sections"].append("kline")

    # 后续 AKShare 扩展块不可用时不影响历史 K 线。
    if not _AK_AVAILABLE:
        if mkt in ("SH", "SZ", "BJ"):
            _overlay_cached_quote_snapshot(result, kb_market_cache.load_quote_snapshot(mkt, code))
        _merge_cached_detail_blocks(result, mkt, code)
        return result

    # 2. A股补充:个股信息 / 实时盘口 / 资金流向
    if mkt in ("SH", "SZ", "BJ"):
        try:
            result["info"] = _fetch_a_info(code)
            kb_market_cache.upsert_detail_block(mkt, code, "info", result["info"], source="akshare")
            _append_unique(result["sections"], "info")
        except Exception as e:
            if not _merge_cached_detail_blocks(result, mkt, code, "info"):
                result["errors"]["info"] = str(e)[:80]
        try:
            result["quote"] = _fetch_a_quote(code)
            kb_market_cache.upsert_detail_block(mkt, code, "quote", result["quote"], source="akshare")
            if _apply_realtime_quote_payload(result, result["quote"], source="akshare"):
                kb_market_cache.upsert_quote_snapshot(result, source="akshare")
            _append_unique(result["sections"], "quote")
        except Exception as e:
            _overlay_cached_quote_snapshot(result, kb_market_cache.load_quote_snapshot(mkt, code))
            if not _merge_cached_detail_blocks(result, mkt, code, "quote"):
                result["errors"]["quote"] = str(e)[:80]
        try:
            result["fund_flow"] = _fetch_a_fund_flow(code, mkt)
            if result["fund_flow"]:
                kb_market_cache.upsert_detail_block(mkt, code, "fund_flow", result["fund_flow"], source="akshare")
                _append_unique(result["sections"], "fund_flow")
            else:
                _merge_cached_detail_blocks(result, mkt, code, "fund_flow")
        except Exception as e:
            if not _merge_cached_detail_blocks(result, mkt, code, "fund_flow"):
                result["errors"]["fund_flow"] = str(e)[:80]

    # 3. 财务指标(三市场)
    try:
        fins = _fetch_financials(mkt, code)
        if fins:
            result["financials"] = fins
            kb_market_cache.upsert_detail_block(mkt, code, "financials", fins, source="akshare")
            _append_unique(result["sections"], "financials")
        else:
            _merge_cached_detail_blocks(result, mkt, code, "financials")
    except Exception as e:
        if not _merge_cached_detail_blocks(result, mkt, code, "financials"):
            result["errors"]["financials"] = str(e)[:80]

    return result


def get_cached_stock_detail(market: str, code: str, days: int = 90) -> dict:
    """只读 SQLite 缓存,不触网。用于页面打开时快速展示旧行情。"""
    mkt = market.upper()
    hist = get_cached_history_kline(mkt, code, days, adjust="qfq")
    if not hist.get("ok"):
        return {"ok": False, "market": mkt, "code": code, "error": hist.get("error", "暂无本地行情")}

    detail = {
        "ok": True,
        "market": mkt,
        "code": code,
        "kline": hist.get("kline", []),
        "price": hist.get("price", 0),
        "change_amt": hist.get("change_amt"),
        "change_pct": hist.get("change_pct", 0),
        "date": hist.get("date", ""),
        "source": "sqlite",
        "currency": hist.get("currency", ""),
        "updated_at": hist.get("updated_at", ""),
        "stale": True,
        "stale_blocks": [],
        "sections": ["kline"],
        "errors": {},
        "info": {},
        "quote": {},
        "fund_flow": [],
        "financials": [],
    }
    if mkt in ("SH", "SZ", "BJ"):
        _overlay_cached_quote_snapshot(detail, kb_market_cache.load_quote_snapshot(mkt, code))
    _merge_cached_detail_blocks(detail, mkt, code)
    return detail
