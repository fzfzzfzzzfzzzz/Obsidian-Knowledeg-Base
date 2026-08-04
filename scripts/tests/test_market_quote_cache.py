"""自选股 90 天详情行情 SQLite 缓存。"""
import kb_web
import kb_quote
import kb_market_cache
import web.routers.market as market_router
from fastapi.testclient import TestClient
import pandas as pd
import pytest


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


def _create_watch(client, title, market, ticker):
    r = client.post("/api/market", json={
        "kind": "watchlist",
        "title": title,
        "market": market,
        "ticker": ticker,
    })
    assert r.status_code == 200
    return r.json()["market"]


def _row(market, code, price, change_pct, day="2026-08-01"):
    return {
        "market": market,
        "code": code,
        "trade_date": day,
        "date": day,
        "adjust": "qfq",
        "currency": kb_quote._currency_for_market(market),
        "open": price - 1,
        "high": price + 2,
        "low": price - 2,
        "close": price,
        "preclose": price - 1,
        "price": price,
        "change_amt": 1.0,
        "change_pct": change_pct,
        "volume_shares": 1000,
        "volume": 1000,
        "amount": 10000,
        "amplitude": 1.5,
        "turnover": 0.8,
        "trade_status": "1",
        "is_st": "0",
    }


def _patch_sources(monkeypatch, baostock_fn=None, akshare_fn=None):
    monkeypatch.setattr(kb_quote, "_BAOSTOCK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", False)
    monkeypatch.setattr(kb_quote, "_fetch_baostock_kline", baostock_fn or (
        lambda market, code, days, adjust="qfq": (_ for _ in ()).throw(ConnectionError("BaoStock down"))
    ))
    monkeypatch.setattr(kb_quote, "_fetch_akshare_kline", akshare_fn or (
        lambda market, code, days, adjust="qfq": (_ for _ in ()).throw(ConnectionError("AKShare down"))
    ))


def test_quote_cache_single_success_overwrites_that_stock(client, isolate_vault, monkeypatch):
    stock = _create_watch(client, "茅台", "SH", "600519")
    _patch_sources(monkeypatch, baostock_fn=lambda market, code, days, adjust="qfq": [
        _row(market, code, 123.4, 1.2)
    ])

    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["updated_count"] == 1
    assert data["items"][0]["ok"] is True
    assert data["items"][0]["price"] == 123.4
    assert data["items"][0]["updated_at"]

    cached = kb_market_cache.load_daily_kline("SH", "600519", limit=1)
    assert cached[0]["close"] == 123.4
    assert cached[0]["volume_shares"] == 1000
    assert market_router._stock_detail_cache_path().exists()
    assert stock["ticker"] == "SH:600519"


def test_quote_cache_open_reads_sqlite_without_refresh(client, isolate_vault, monkeypatch):
    _create_watch(client, "茅台", "SH", "600519")
    _patch_sources(monkeypatch, baostock_fn=lambda market, code, days, adjust="qfq": [
        _row(market, code, 123.4, 1.2)
    ])
    assert client.post("/api/market/quote-cache/refresh").status_code == 200

    r = client.get("/api/market/quote-cache")
    assert r.status_code == 200
    data = r.json()
    assert data["ok_count"] == 1
    assert data["items"][0]["ok"] is True
    assert data["items"][0]["price"] == 123.4
    assert data["items"][0]["kline"][0]["close"] == 123.4
    assert data["items"][0]["stale"] is True


def test_quote_cache_failure_keeps_existing_stock_cache(client, isolate_vault, monkeypatch):
    _create_watch(client, "茅台", "SH", "600519")
    _patch_sources(monkeypatch, baostock_fn=lambda market, code, days, adjust="qfq": [
        _row(market, code, 123.4, 1.2)
    ])
    assert client.post("/api/market/quote-cache/refresh").status_code == 200

    _patch_sources(monkeypatch)
    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["updated_count"] == 0
    assert data["items"][0]["ok"] is True
    assert data["items"][0]["stale"] is True
    assert data["items"][0]["price"] == 123.4
    assert kb_market_cache.load_daily_kline("SH", "600519", limit=1)[0]["close"] == 123.4


def test_quote_cache_partial_success_updates_only_successful_items(client, isolate_vault, monkeypatch):
    mt = _create_watch(client, "茅台", "SH", "600519")
    apple = _create_watch(client, "苹果", "US", "aapl")

    def first_baostock(market, code, days, adjust="qfq"):
        return [_row(market, code, 10.0, 0.5)]

    def first_akshare(market, code, days, adjust="qfq"):
        return [_row(market, code, 20.0, 0.5)]

    _patch_sources(monkeypatch, baostock_fn=first_baostock, akshare_fn=first_akshare)
    assert client.post("/api/market/quote-cache/refresh").status_code == 200

    def second_baostock(market, code, days, adjust="qfq"):
        return [_row(market, code, 30.0, 2.0)]

    def second_akshare(market, code, days, adjust="qfq"):
        raise ConnectionError("HTTPSConnectionPool(host='33.push2his.eastmoney.com')")

    _patch_sources(monkeypatch, baostock_fn=second_baostock, akshare_fn=second_akshare)
    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    by_id = {item["market_id"]: item for item in data["items"]}
    assert data["updated_count"] == 1
    assert by_id[mt["id"]]["price"] == 30.0
    assert by_id[mt["id"]].get("stale") is False
    assert by_id[apple["id"]]["price"] == 20.0
    assert by_id[apple["id"]]["stale"] is True

    assert kb_market_cache.load_daily_kline("SH", "600519", limit=1)[0]["close"] == 30.0
    assert kb_market_cache.load_daily_kline("US", "AAPL", limit=1)[0]["close"] == 20.0


def test_quote_cache_all_fail_without_cache_returns_short_errors_and_writes_nothing(client, isolate_vault, monkeypatch):
    _create_watch(client, "茅台", "SH", "600519")
    _patch_sources(monkeypatch)

    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["updated_count"] == 0
    assert data["ok_count"] == 0
    assert data["items"][0]["ok"] is False
    assert data["items"][0]["error"] == "行情源连接失败"
    assert "HTTPSConnectionPool" not in data["items"][0]["error"]
    assert not market_router._stock_detail_cache_path().exists()


def test_get_quote_overlays_akshare_snapshot_without_replacing_kline(isolate_vault, monkeypatch):
    monkeypatch.setattr(kb_quote, "_BAOSTOCK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "_fetch_baostock_kline", lambda market, code, days, adjust="qfq": [
        _row(market, code, 100.0, 1.0)
    ])
    monkeypatch.setattr(kb_quote, "_fetch_akshare_kline", lambda market, code, days, adjust="qfq": [])
    monkeypatch.setattr(kb_quote, "_fetch_a_quote", lambda code: {
        "\u6700\u65b0": "105",
        "\u6da8\u5e45": "2.5%",
        "\u6da8\u8dcc": "2.5",
        "\u603b\u624b": "10",
        "\u91d1\u989d": "10,000",
    })

    q = kb_quote.get_quote("SH", "600519", days=30)

    assert q["ok"] is True
    assert q["price"] == 105.0
    assert q["change_pct"] == 2.5
    assert q["volume_shares"] == 1000
    assert q["amount"] == 10000.0
    assert q["kline"][-1]["close"] == 100.0
    assert q["quote_source"] == "akshare"
    assert kb_market_cache.load_quote_snapshot("SH", "600519")["price"] == 105.0


def test_hk_history_falls_back_to_sina_when_eastmoney_fails(isolate_vault, monkeypatch):
    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "_fetch_kline_df", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("push2his down")))
    monkeypatch.setattr(kb_quote, "_fetch_sina_daily_df", lambda market, code, adjust="qfq": pd.DataFrame([
        {"date": "2026-07-30", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 1000},
        {"date": "2026-07-31", "open": 102, "high": 106, "low": 101, "close": 105, "volume": 1200},
    ]))

    q = kb_quote.get_quote("HK", "00700", days=30)

    assert q["ok"] is True
    assert q["source"] == "akshare"
    assert q["price"] == 105
    assert q["kline"][-1]["volume_shares"] == 1200
    assert kb_market_cache.load_daily_kline("HK", "00700", limit=2)[-1]["close"] == 105


def test_stock_detail_uses_cached_block_when_akshare_block_fails(isolate_vault, monkeypatch):
    kb_market_cache.upsert_daily_kline([_row("SH", "600519", 100.0, 1.0)], source="baostock")
    cached_info = {"industry": "liquor", "listed_at": "2001-08-27"}
    kb_market_cache.upsert_detail_block("SH", "600519", "info", cached_info, source="akshare")
    monkeypatch.setattr(kb_quote, "_BAOSTOCK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "_fetch_baostock_kline", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("down")))
    monkeypatch.setattr(kb_quote, "_fetch_akshare_kline", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("down")))
    monkeypatch.setattr(kb_quote, "_fetch_a_info", lambda code: (_ for _ in ()).throw(ConnectionError("info down")))
    monkeypatch.setattr(kb_quote, "_fetch_a_quote", lambda code: (_ for _ in ()).throw(ConnectionError("quote down")))
    monkeypatch.setattr(kb_quote, "_fetch_a_fund_flow", lambda code, market: [])
    monkeypatch.setattr(kb_quote, "_fetch_financials", lambda market, code: [])

    detail = kb_quote.get_stock_detail("SH", "600519", days=90)

    assert detail["ok"] is True
    assert detail["source"] == "sqlite"
    assert detail["info"] == cached_info
    assert "info" in detail["sections"]
    assert "info" in detail["stale_blocks"]
    assert "info" not in detail["errors"]


def test_sector_fund_flow_empty_result_uses_sqlite_cache(isolate_vault, monkeypatch):
    indicator = "\u4eca\u65e5"
    sector_type = "\u884c\u4e1a\u8d44\u91d1\u6d41"
    cached = {
        "ok": True,
        "indicator": indicator,
        "sector_type": sector_type,
        "updated_at": "2026-08-01 15:00",
        "inflow": [{"name": "AI", "amount": 1.2}],
        "outflow": [],
        "count": 1,
    }
    kb_market_cache.upsert_detail_block("_MARKET", "fund_flow", f"{sector_type}:{indicator}", cached, source="akshare")

    class FakeAk:
        def stock_sector_fund_flow_rank(self, indicator, sector_type):
            return []

    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "ak", FakeAk())

    result = kb_quote.get_sector_fund_flow(indicator, sector_type, top_n=20)

    assert result["ok"] is True
    assert result["stale"] is True
    assert result["inflow"][0]["name"] == "AI"


def test_industry_trends_from_akshare_writes_sqlite_cache(isolate_vault, monkeypatch):
    class FakeAk:
        def stock_board_industry_name_em(self):
            return pd.DataFrame([
                {"板块名称": "半导体", "板块代码": "BK1001", "涨跌幅": 3.2, "换手率": 2.1, "领涨股票": "样本A", "领涨股票-涨跌幅": 8.1},
                {"板块名称": "银行", "板块代码": "BK1002", "涨跌幅": -0.8, "换手率": 0.7, "领涨股票": "样本B", "领涨股票-涨跌幅": 1.2},
                {"板块名称": "新能源", "板块代码": "BK1003", "涨跌幅": 1.4, "换手率": 1.9, "领涨股票": "样本C", "领涨股票-涨跌幅": 4.5},
            ])

        def stock_board_industry_hist_em(self, symbol, start_date, end_date, period, adjust):
            base = {"BK1001": 100, "BK1002": 200, "BK1003": 80}[symbol]
            return pd.DataFrame([
                {"日期": "2026-07-27", "开盘": base - 1, "收盘": base, "最高": base + 1, "最低": base - 2, "涨跌幅": 0.0, "涨跌额": 0.0, "成交量": 1000, "成交额": 100000000, "振幅": 1.0, "换手率": 1.1},
                {"日期": "2026-07-28", "开盘": base, "收盘": base + 2, "最高": base + 3, "最低": base - 1, "涨跌幅": 2.0, "涨跌额": 2.0, "成交量": 1100, "成交额": 110000000, "振幅": 1.2, "换手率": 1.2},
                {"日期": "2026-07-29", "开盘": base + 2, "收盘": base + 4, "最高": base + 5, "最低": base + 1, "涨跌幅": 1.9, "涨跌额": 2.0, "成交量": 1200, "成交额": 120000000, "振幅": 1.3, "换手率": 1.3},
            ])

    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "ak", FakeAk())
    monkeypatch.setattr(kb_quote, "_fetch_industry_candidates", lambda top_n: [
        {"id": "BK1001", "label": "半导体", "change_pct": 3.2, "turnover": 2.1, "lead_stock": "样本A", "lead_stock_change_pct": 8.1},
        {"id": "BK1002", "label": "银行", "change_pct": -0.8, "turnover": 0.7, "lead_stock": "样本B", "lead_stock_change_pct": 1.2},
        {"id": "BK1003", "label": "新能源", "change_pct": 1.4, "turnover": 1.9, "lead_stock": "样本C", "lead_stock_change_pct": 4.5},
    ][:top_n])

    result = kb_quote.get_industry_trends(days=30, top_n=5)

    assert result["ok"] is True
    assert result["view"] == "industry"
    assert result["series"]
    assert result["heatmap"]
    assert result["series"][0]["summary"]["d20"] > 0
    cached = kb_market_cache.load_daily_kline("IND", "BK1001", adjust="none", limit=10)
    assert len(cached) == 3
    assert cached[0]["close"] == 100


def test_industry_trends_uses_sqlite_cache_when_hist_fails(isolate_vault, monkeypatch):
    class FakeAk:
        def stock_board_industry_name_em(self):
            return pd.DataFrame([
                {"板块名称": "半导体", "板块代码": "BK1001", "涨跌幅": 3.2, "换手率": 2.1, "领涨股票": "样本A", "领涨股票-涨跌幅": 8.1},
            ])

        def stock_board_industry_hist_em(self, symbol, start_date, end_date, period, adjust):
            return pd.DataFrame([
                {"日期": "2026-07-27", "开盘": 99, "收盘": 100, "最高": 101, "最低": 98, "涨跌幅": 0.0, "涨跌额": 0.0, "成交量": 1000, "成交额": 100000000, "振幅": 1.0, "换手率": 1.1},
                {"日期": "2026-07-28", "开盘": 100, "收盘": 103, "最高": 104, "最低": 99, "涨跌幅": 3.0, "涨跌额": 3.0, "成交量": 1100, "成交额": 110000000, "振幅": 1.2, "换手率": 1.2},
            ])

    class DownAk(FakeAk):
        def stock_board_industry_hist_em(self, symbol, start_date, end_date, period, adjust):
            raise ConnectionError("industry hist down")

    monkeypatch.setattr(kb_quote, "_AK_AVAILABLE", True)
    monkeypatch.setattr(kb_quote, "ak", FakeAk())
    monkeypatch.setattr(kb_quote, "_fetch_industry_candidates", lambda top_n: [
        {"id": "BK1001", "label": "半导体", "change_pct": 3.2, "turnover": 2.1, "lead_stock": "样本A", "lead_stock_change_pct": 8.1},
    ][:top_n])
    assert kb_quote.get_industry_trends(days=30, top_n=5)["ok"] is True

    monkeypatch.setattr(kb_quote, "ak", DownAk())
    result = kb_quote.get_industry_trends(days=30, top_n=5)

    assert result["ok"] is True
    assert result["stale"] is True
    assert result["series"][0]["id"] == "BK1001"


def test_market_trends_returns_configured_indexes_and_watchlist_equal_weight(client, isolate_vault, monkeypatch):
    _create_watch(client, "茅台", "SH", "600519")
    kb_market_cache.upsert_daily_kline([
        _row("SH", "600519", 100.0, 0.0, day="2026-07-30"),
        _row("SH", "600519", 105.0, 5.0, day="2026-07-31"),
    ], source="test")

    def fake_index(index, days):
        code = kb_quote._index_cache_code(index)
        return [
            {**_row("IDX", code, 100.0, 0.0, day="2026-07-30"), "adjust": "none", "currency": index.get("currency", "")},
            {**_row("IDX", code, 102.0, 2.0, day="2026-07-31"), "adjust": "none", "currency": index.get("currency", "")},
        ], "fake_index"

    monkeypatch.setattr(kb_quote, "_fetch_market_index_kline", fake_index)
    monkeypatch.setattr(kb_quote, "_fetch_market_breadth", lambda: {
        "ok": True,
        "updated_at": "2026-07-31T15:05:00",
        "up_count": 2100,
        "down_count": 2800,
        "median_change_pct": -0.32,
        "high20_count": 88,
        "low20_count": 41,
        "limit_up_count": 67,
        "limit_down_count": 12,
    })

    result = kb_quote.get_market_trends(days=30)

    assert result["ok"] is True
    assert [card["id"] for card in result["cards"]] == ["csi300", "sp500", "hstech", "watch_equal"]
    assert [series["id"] for series in result["series"]] == ["csi300", "sp500", "hstech", "watch_equal"]

    by_card = {card["id"]: card for card in result["cards"]}
    assert by_card["csi300"]["market"] == "A股"
    assert by_card["sp500"]["label"] == "标普500"
    assert by_card["hstech"]["label"] == "恒生科技指数"
    assert by_card["watch_equal"]["label"] == "自选股等权指数"
    assert by_card["watch_equal"]["value"] == 105.0
    assert by_card["watch_equal"]["return_pct"] == 5.0
    assert [item["label"] for item in result["summary"]] == [
        "上涨/下跌家数",
        "全市场收益中位数",
        "创20日新高/新低",
        "涨停/跌停数量",
    ]
    assert result["summary"][0]["value"] == "2100 / 2800"
    assert result["summary"][1]["value"] == "-0.32%"
    assert result["summary"][2]["value"] == "88 / 41"
    assert result["summary"][3]["value"] == "67 / 12"


def test_cached_market_trends_uses_cached_breadth_summary(isolate_vault):
    kb_market_cache.upsert_daily_kline([
        {**_row("IDX", "sh000300", 100.0, 0.0, day="2026-07-30"), "adjust": "none"},
        {**_row("IDX", "sh000300", 103.0, 3.0, day="2026-07-31"), "adjust": "none"},
    ], source="test")
    kb_market_cache.upsert_detail_block("_MARKET", "market_breadth", "latest", {
        "ok": True,
        "updated_at": "2026-07-31T15:05:00",
        "up_count": 3000,
        "down_count": 1800,
        "median_change_pct": 0.26,
        "high20_count": 120,
        "low20_count": 19,
        "limit_up_count": 81,
        "limit_down_count": 5,
    }, source="akshare")

    result = kb_quote.get_cached_market_trends(days=30)

    assert result["ok"] is True
    assert result["stale"] is True
    assert result["breadth"]["stale"] is True
    assert result["summary"][0]["value"] == "3000 / 1800"
    assert result["summary"][1]["value"] == "+0.26%"
    assert result["summary"][2]["value"] == "120 / 19"
    assert result["summary"][3]["value"] == "81 / 5"
