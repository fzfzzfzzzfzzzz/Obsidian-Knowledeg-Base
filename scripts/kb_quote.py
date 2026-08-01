#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kb_quote.py —— 行情数据接入(akshare 封装,可选依赖)。

设计原则(与项目 kb_llm.py 一致):
  - akshare 是可选依赖,缺失时优雅降级(返回 error 字段,不抛异常)
  - 行情数据只读,不存盘,不污染 Markdown 数据层
  - 单只按需查询,不拉全市场(避免数据量爆炸 + 被限流)

三市场对应函数(已实测):
  A股(SH/SZ/BJ): stock_zh_a_hist  symbol=688825        → 日K线
  港股(HK):       stock_hk_hist    symbol=00700        → 日K线
  美股(US):       stock_us_hist    symbol=105.AAPL     → 日K线(需 105/106 前缀)

美股 105=纳斯达克 106=纽交所。无法从 ticker 自动判断交易所,
用常见映射表 + 默认 105 兜底(BABA 等纽交所需手动映射)。
"""
from __future__ import annotations

from datetime import date, timedelta

# 可选依赖:akshare 缺失时降级
try:
    import akshare as ak
    _AK_AVAILABLE = True
except Exception:
    ak = None  # type: ignore
    _AK_AVAILABLE = False


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
    if not _AK_AVAILABLE:
        return {
            "ok": False, "market": market, "code": code,
            "error": "akshare 未安装,无法获取行情。pip install akshare",
        }

    mkt = market.upper()
    today = date.today()
    start = (today - timedelta(days=days + 15)).strftime("%Y%m%d")  # 多拉几天防节假日
    end = today.strftime("%Y%m%d")

    try:
        df = None
        if mkt in ("SH", "SZ", "BJ"):
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                    start_date=start, end_date=end, adjust="qfq")
        elif mkt == "HK":
            df = ak.stock_hk_hist(symbol=code, period="daily",
                                  start_date=start, end_date=end, adjust="qfq")
        elif mkt == "US":
            df = ak.stock_us_hist(symbol=_us_symbol(code), period="daily",
                                  start_date=start, end_date=end, adjust="qfq")
        else:
            return {"ok": False, "market": market, "code": code,
                    "error": f"不支持的市场:{market}"}

        if df is None or len(df) == 0:
            return {"ok": False, "market": market, "code": code,
                    "error": f"无数据(代码 {code} 可能不存在或已退市)"}

        price, pct = _calc_change_pct(df)
        kline = _extract_kline(df, days)
        return {
            "ok": True, "market": mkt, "code": code,
            "price": price, "change_pct": pct,
            "kline": kline, "kline_days": len(kline),
            "date": kline[-1]["date"] if kline else "",
        }
    except Exception as e:
        msg, detail = _friendly_error(e)
        return {"ok": False, "market": market, "code": code,
                "error": msg, "error_detail": detail}


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
    """akshare 是否可用(供前端判断是否显示行情功能)。"""
    return _AK_AVAILABLE


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


def _fetch_kline_df(market: str, code: str, days: int, period: str = "daily"):
    """拉 K线 DataFrame(三市场,内部用)。返回 df 或 None。"""
    today = date.today()
    start = (today - timedelta(days=days + 30)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    mkt = market.upper()
    if mkt in ("SH", "SZ", "BJ"):
        return ak.stock_zh_a_hist(symbol=code, period=period, start_date=start, end_date=end, adjust="qfq")
    elif mkt == "HK":
        return ak.stock_hk_hist(symbol=code, period=period, start_date=start, end_date=end, adjust="qfq")
    elif mkt == "US":
        return ak.stock_us_hist(symbol=_us_symbol(code), period=period, start_date=start, end_date=end, adjust="qfq")
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
    if not _AK_AVAILABLE:
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
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": f"拉取失败:{type(e).__name__}: {str(e)[:120]}"}
    if df is None or len(df) == 0:
        return {"ok": False, "indicator": indicator, "sector_type": sector_type,
                "error": "无数据(数据源可能限流或不可达)"}

    cols = list(df.columns)
    name_col = _pick_col(cols, "名称", "板块")
    amount_col = _pick_col(cols, "主力净流入-净额", "主力净流入-净金额")
    change_col = _pick_col(cols, "涨跌幅")
    main_pct_col = _pick_col(cols, "主力净流入-净占比", "主力净流入净占比")
    lead_col = _pick_col(cols, "主力净流入最大股", "领涨股")
    if not name_col or not amount_col:
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
    return {
        "ok": True,
        "indicator": indicator,
        "sector_type": sector_type,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "inflow": inflow,
        "outflow": outflow,
        "count": len(inflow) + len(outflow),
    }


def get_stock_detail(market: str, code: str, days: int = 90) -> dict:
    """详情页数据:K线全字段 + 按市场补充资金流/财务/盘口/个股信息。

    各数据块独立 try/except,单块失败在 errors 里记录,不阻断其他块。
    返回:
      {ok, market, code, kline:[...全字段], price, change_pct,
       info:{}, quote:{}, fund_flow:[], financials:[],
       sections:[可显示的区块名], errors:{块名:错误}}
    """
    if not _AK_AVAILABLE:
        return {"ok": False, "market": market, "code": code,
                "error": "akshare 未安装,无法获取详情数据。pip install akshare"}

    result = {"ok": True, "market": market, "code": code,
              "kline": [], "info": {}, "quote": {}, "fund_flow": [], "financials": [],
              "sections": [], "errors": {}}
    mkt = market.upper()
    days = max(30, min(days, 365))

    # 1. K线(三市场都有)—— 核心,失败则整体失败
    try:
        df = _fetch_kline_df(mkt, code, days)
        kline = _kline_full(df, days)
        result["kline"] = kline
        if kline:
            last = kline[-1]
            result["price"] = last.get("close", 0)
            result["change_pct"] = last.get("change_pct", 0)
            result["date"] = last.get("date", "")
        result["sections"].append("kline")
    except Exception as e:
        result["ok"] = False
        result["error"] = f"K线拉取失败:{type(e).__name__}: {str(e)[:100]}"
        return result

    # 2. A股补充:个股信息 / 实时盘口 / 资金流向
    if mkt in ("SH", "SZ", "BJ"):
        try:
            result["info"] = _fetch_a_info(code)
            result["sections"].append("info")
        except Exception as e:
            result["errors"]["info"] = str(e)[:80]
        try:
            result["quote"] = _fetch_a_quote(code)
            result["sections"].append("quote")
        except Exception as e:
            result["errors"]["quote"] = str(e)[:80]
        try:
            result["fund_flow"] = _fetch_a_fund_flow(code, mkt)
            if result["fund_flow"]:
                result["sections"].append("fund_flow")
        except Exception as e:
            result["errors"]["fund_flow"] = str(e)[:80]

    # 3. 财务指标(三市场)
    try:
        fins = _fetch_financials(mkt, code)
        if fins:
            result["financials"] = fins
            result["sections"].append("financials")
    except Exception as e:
        result["errors"]["financials"] = str(e)[:80]

    return result
