import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


def test_market_judgment_file_roundtrip(isolate_vault):
    path = kb._market_judgment_file_path("judgment_roundtrip01")
    meta = {
        "id": "judgment_roundtrip01",
        "title": "芯片股回调判断",
        "target": "芯片股",
        "judgment": "7.30 大涨后只是稍微回调\n不看成趋势结束",
        "judged_at": "2026-07-30T14:30",
        "horizon": "1-3天",
        "verdict": "pending",
        "actual_result": "",
        "reviewed_at": "",
    }

    kb.write_market_judgment_file(path, meta, "观察成交量和北向资金。", is_new=True)
    rec = kb.load_market_judgment_file(path)

    assert rec["id"] == "judgment_roundtrip01"
    assert rec["target"] == "芯片股"
    assert rec["judgment"] == "7.30 大涨后只是稍微回调\n不看成趋势结束"
    assert rec["judged_at"] == "2026-07-30T14:30"
    assert rec["verdict"] == "pending"
    assert "观察成交量" in rec["body"]


def test_market_judgments_scan_newest_first_and_not_watchlist(isolate_vault):
    old_path = kb._market_judgment_file_path("judgment_old")
    new_path = kb._market_judgment_file_path("judgment_new")
    base = {
        "title": "判断",
        "target": "半导体",
        "judgment": "回调不深",
        "horizon": "",
        "verdict": "pending",
        "actual_result": "",
        "reviewed_at": "",
    }
    kb.write_market_judgment_file(old_path, {**base, "id": "judgment_old", "judged_at": "2026-07-30T10:00"}, "", is_new=True)
    kb.write_market_judgment_file(new_path, {**base, "id": "judgment_new", "judged_at": "2026-07-31T10:00"}, "", is_new=True)

    items = kb.scan_market_judgments()
    assert [it["id"] for it in items[:2]] == ["judgment_new", "judgment_old"]
    assert kb.scan_market(kind="watchlist") == []


def test_market_judgment_api_crud(client):
    r = client.get("/market/judgments")
    assert r.status_code == 200

    r = client.post("/api/market/judgments", json={
        "target": "芯片股",
        "judgment": "7.30 大涨后只是稍微回调",
        "judged_at": "2026-07-30T14:30",
        "horizon": "1-3天",
    })
    assert r.status_code == 200, r.text
    item = r.json()["judgment"]
    assert item["id"].startswith("judgment_")
    assert item["target"] == "芯片股"
    assert item["judgment"] == "7.30 大涨后只是稍微回调"

    r = client.patch("/api/market/judgments/" + item["id"], json={
        "verdict": "partial",
        "actual_result": "次日低开后继续冲高，判断方向部分成立。",
    })
    assert r.status_code == 200, r.text
    updated = r.json()["judgment"]
    assert updated["verdict"] == "partial"
    assert updated["reviewed_at"]
    assert "部分成立" in updated["actual_result"]

    r = client.delete("/api/market/judgments/" + item["id"])
    assert r.status_code == 200
    r = client.get("/api/market/judgments/" + item["id"])
    assert r.status_code == 404


def test_market_judgment_api_rejects_invalid_input(client):
    r = client.post("/api/market/judgments", json={
        "target": "芯片股",
        "judgment": "",
        "judged_at": "2026-07-30T14:30",
    })
    assert r.status_code == 400

    r = client.post("/api/market/judgments", json={
        "judgment": "回调",
        "judged_at": "not-a-date",
    })
    assert r.status_code == 400

    r = client.post("/api/market/judgments", json={
        "judgment": "回调",
        "judged_at": "2026-07-30T14:30",
        "verdict": "maybe",
    })
    assert r.status_code == 400
