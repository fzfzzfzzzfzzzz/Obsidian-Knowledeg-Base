import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


def test_market_simulation_file_roundtrip_and_scan(isolate_vault):
    path = kb._market_simulation_file_path("simulation_roundtrip01")
    meta = {
        "id": "simulation_roundtrip01",
        "title": "芯片ETF 短线模拟",
        "market": "SH",
        "ticker": "SH:588000",
        "sector": "金融",
        "entry_price": "1.23",
        "shares": "1000",
        "entry_date": "2026-08-01",
        "target_price": "1.35",
        "stop_price": "1.18",
        "status": "active",
        "exit_price": "",
        "exit_date": "",
        "note": "验证回调判断",
    }

    kb.write_market_simulation_file(path, meta, "观察三天。", is_new=True)
    rec = kb.load_market_simulation_file(path)

    assert rec["id"] == "simulation_roundtrip01"
    assert rec["title"] == "芯片ETF 短线模拟"
    assert rec["ticker"] == "SH:588000"
    assert rec["entry_date"] == "2026-08-01"
    assert rec["status"] == "active"
    assert "观察三天" in rec["body"]
    assert [it["id"] for it in kb.scan_market_simulations()] == ["simulation_roundtrip01"]
    assert kb.scan_market(kind="watchlist") == []


def test_market_personal_holdings_filters_active_watchlist_with_position(client):
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "有持仓", "market": "SH", "ticker": "600519",
        "cost_price": "1680", "shares": "100",
    })
    assert r.status_code == 200, r.text
    keep_id = r.json()["market"]["id"]

    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "无持仓", "market": "US", "ticker": "aapl",
    })
    assert r.status_code == 200, r.text

    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "已归档持仓", "market": "HK", "ticker": "700",
        "cost_price": "320", "status": "archived",
    })
    assert r.status_code == 200, r.text

    r = client.get("/api/market/personal/holdings")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [it["id"] for it in items] == [keep_id]
    assert items[0]["title"] == "有持仓"


def test_market_simulation_api_crud(client):
    r = client.post("/api/market/simulations", json={
        "title": "苹果模拟",
        "market": "US",
        "ticker": "aapl",
        "sector": "金融",
        "entry_price": "180",
        "shares": "10",
        "entry_date": "2026-08-01",
        "target_price": "195",
        "stop_price": "170",
        "note": "财报前观察",
    })
    assert r.status_code == 200, r.text
    item = r.json()["simulation"]
    assert item["id"].startswith("simulation_")
    assert item["ticker"] == "US:AAPL"
    assert item["status"] == "active"

    r = client.patch("/api/market/simulations/" + item["id"], json={
        "status": "closed",
        "exit_price": "192",
        "exit_date": "2026-08-08",
        "body": "方向基本成立。",
    })
    assert r.status_code == 200, r.text
    updated = r.json()["simulation"]
    assert updated["status"] == "closed"
    assert updated["exit_date"] == "2026-08-08"
    assert "方向基本成立" in updated["body"]

    r = client.get("/api/market/simulations?status=closed")
    assert r.status_code == 200
    assert [it["id"] for it in r.json()["items"]] == [item["id"]]

    r = client.delete("/api/market/simulations/" + item["id"])
    assert r.status_code == 200
    r = client.get("/api/market/simulations/" + item["id"])
    assert r.status_code == 404


def test_market_simulation_api_rejects_invalid_input(client):
    r = client.post("/api/market/simulations", json={"title": ""})
    assert r.status_code == 400

    r = client.post("/api/market/simulations", json={
        "title": "坏代码", "market": "US", "ticker": "1234",
    })
    assert r.status_code == 400

    r = client.post("/api/market/simulations", json={
        "title": "坏日期", "entry_date": "2026-99-99",
    })
    assert r.status_code == 400

    r = client.post("/api/market/simulations", json={
        "title": "坏状态", "status": "pending",
    })
    assert r.status_code == 400


def test_market_page_has_personal_tab_and_no_visible_judgment_entry(client):
    r = client.get("/market")
    assert r.status_code == 200
    html = r.text
    assert 'data-mktab="personal"' in html
    assert "我的当前持仓盘" in html
    assert "我的模拟盘" in html
    assert "个人判断" in html
    assert 'href="/market/judgments"' not in html
    assert "mk-judgments-entry" not in html
