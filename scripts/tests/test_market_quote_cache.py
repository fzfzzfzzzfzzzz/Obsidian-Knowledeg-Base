"""自选股 90 天详情行情缓存。"""
import json

import kb
import kb_web
import web.routers.market as market_router
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


class FakeQuote:
    def __init__(self, detail_fn, available=True):
        self.detail_fn = detail_fn
        self.available = available

    def is_available(self):
        return self.available

    def get_stock_detail(self, market, code, days):
        return self.detail_fn(market, code, days)


def _create_watch(client, title, market, ticker):
    r = client.post("/api/market", json={
        "kind": "watchlist",
        "title": title,
        "market": market,
        "ticker": ticker,
    })
    assert r.status_code == 200
    return r.json()["market"]


def _detail(market, code, price, change_pct, day="2026-08-01"):
    return {
        "ok": True,
        "market": market,
        "code": code,
        "price": price,
        "change_pct": change_pct,
        "date": day,
        "kline": [{"date": day, "close": price, "change_pct": change_pct}],
    }


def _cache_json():
    return json.loads(kb.read_text(market_router._stock_detail_cache_path()))


def test_quote_cache_single_success_overwrites_that_stock(client, isolate_vault, monkeypatch):
    stock = _create_watch(client, "茅台", "SH", "600519")

    monkeypatch.setattr(market_router, "kb_quote", FakeQuote(
        lambda market, code, days: _detail(market, code, 123.4, 1.2)
    ))

    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["updated_count"] == 1
    assert data["items"][0]["ok"] is True
    assert data["items"][0]["price"] == 123.4
    assert data["items"][0]["updated_at"]

    cache = _cache_json()
    entry = cache["items"][stock["id"]]
    assert entry["stock"]["title"] == "茅台"
    assert entry["detail"]["price"] == 123.4
    assert entry["updated_at"]


def test_quote_cache_failure_keeps_existing_stock_cache(client, isolate_vault, monkeypatch):
    stock = _create_watch(client, "茅台", "SH", "600519")
    monkeypatch.setattr(market_router, "kb_quote", FakeQuote(
        lambda market, code, days: _detail(market, code, 123.4, 1.2)
    ))
    assert client.post("/api/market/quote-cache/refresh").status_code == 200

    monkeypatch.setattr(market_router, "kb_quote", FakeQuote(
        lambda market, code, days: {"ok": False, "market": market, "code": code, "error": "ConnectionError: bad"}
    ))
    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["updated_count"] == 0
    assert data["items"][0]["ok"] is True
    assert data["items"][0]["stale"] is True
    assert data["items"][0]["price"] == 123.4
    assert _cache_json()["items"][stock["id"]]["detail"]["price"] == 123.4


def test_quote_cache_partial_success_updates_only_successful_items(client, isolate_vault, monkeypatch):
    mt = _create_watch(client, "茅台", "SH", "600519")
    apple = _create_watch(client, "苹果", "US", "aapl")

    def first_detail(market, code, days):
        return _detail(market, code, 10.0 if code == "600519" else 20.0, 0.5)

    monkeypatch.setattr(market_router, "kb_quote", FakeQuote(first_detail))
    assert client.post("/api/market/quote-cache/refresh").status_code == 200

    def second_detail(market, code, days):
        if code == "600519":
            return _detail(market, code, 30.0, 2.0)
        raise ConnectionError("HTTPSConnectionPool(host='33.push2his.eastmoney.com')")

    monkeypatch.setattr(market_router, "kb_quote", FakeQuote(second_detail))
    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    by_id = {item["market_id"]: item for item in data["items"]}
    assert data["updated_count"] == 1
    assert by_id[mt["id"]]["price"] == 30.0
    assert by_id[mt["id"]].get("stale") is False
    assert by_id[apple["id"]]["price"] == 20.0
    assert by_id[apple["id"]]["stale"] is True

    cache = _cache_json()["items"]
    assert cache[mt["id"]]["detail"]["price"] == 30.0
    assert cache[apple["id"]]["detail"]["price"] == 20.0


def test_quote_cache_all_fail_without_cache_returns_short_errors_and_writes_nothing(client, isolate_vault, monkeypatch):
    _create_watch(client, "茅台", "SH", "600519")
    monkeypatch.setattr(market_router, "kb_quote", FakeQuote(
        lambda market, code, days: (_ for _ in ()).throw(
            ConnectionError("HTTPSConnectionPool(host='33.push2his.eastmoney.com', port=443): Max retries exceeded")
        )
    ))

    r = client.post("/api/market/quote-cache/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["updated_count"] == 0
    assert data["ok_count"] == 0
    assert data["items"][0]["ok"] is False
    assert data["items"][0]["error"] == "行情源连接失败"
    assert "HTTPSConnectionPool" not in data["items"][0]["error"]
    assert not market_router._stock_detail_cache_path().exists()
