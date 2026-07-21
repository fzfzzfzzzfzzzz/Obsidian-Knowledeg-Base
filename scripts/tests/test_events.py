"""事件(Event)功能测试 —— CRUD + 同步到日历 + 幂等 + Web API。

范式参考 test_accept_commands.py(直接调 kb 函数)和 test_accept_transactional.py(TestClient)。
用 isolate_vault fixture 隔离真实 vault。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


# —— 纯函数层:直接调 kb.* ——

def test_make_event_id_stable_prefix(isolate_vault):
    eid = kb.make_event_id("ICML 2026")
    assert eid.startswith("event_")
    assert len(eid) > len("event_")
    # 不同标题生成不同 id
    eid2 = kb.make_event_id("另一个事件")
    assert eid != eid2


def test_write_and_load_event_file_roundtrip(isolate_vault):
    tmp = isolate_vault
    path = tmp / "06_Events" / "event_abc12345.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": "event_abc12345",
        "title": "ICML 2026",
        "date": "2026-07-15",
        "category": "会议",
        "note": "顶会",
        "status": "active",
        "related_source": "",
        "synced_calendar_ids": "cal_x1,cal_x2",
        "created_at": "2026-07-22T10:00:00",
        "updated_at": "2026-07-22T10:00:00",
    }
    kb.write_event_file(path, meta, "会议背景与关注点", is_new=False)
    assert path.exists()

    ev = kb.load_event_file(path)
    assert ev["id"] == "event_abc12345"
    assert ev["title"] == "ICML 2026"
    assert ev["date"] == "2026-07-15"
    assert ev["category"] == "会议"
    assert ev["note"] == "顶会"
    assert ev["status"] == "active"
    # synced_calendar_ids 应解析成 list
    assert ev["synced_calendar_ids"] == ["cal_x1", "cal_x2"]
    assert "会议背景" in ev["body"]
    # path 字段是相对 vault 的 posix 路径
    assert ev["path"] == "06_Events/event_abc12345.md"


def test_load_event_file_empty_synced(isolate_vault):
    """synced_calendar_ids 为空串时解析成空 list(不是 [''])。"""
    tmp = isolate_vault
    path = tmp / "06_Events" / "event_empty.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    kb.write_event_file(path, {
        "id": "event_empty", "title": "T", "date": "2026-01-01",
        "category": "其他", "note": "", "status": "active",
        "synced_calendar_ids": "",
    }, "", is_new=True)
    ev = kb.load_event_file(path)
    assert ev["synced_calendar_ids"] == []


def test_scan_events_sorted_by_date(isolate_vault):
    """scan_events 按日期升序,空 body 走默认占位。"""
    tmp = isolate_vault
    edir = tmp / "06_Events"
    edir.mkdir(parents=True)
    kb.write_event_file(edir / "event_b.md", {
        "id": "event_b", "title": "后来", "date": "2026-12-01",
        "category": "其他", "status": "active", "synced_calendar_ids": "",
    }, "", is_new=True)
    kb.write_event_file(edir / "event_a.md", {
        "id": "event_a", "title": "更早", "date": "2026-01-01",
        "category": "会议", "status": "active", "synced_calendar_ids": "",
    }, "早的事件", is_new=True)

    items = kb.scan_events()
    assert len(items) == 2
    assert items[0]["id"] == "event_a"   # 日期更早的在前
    assert items[1]["id"] == "event_b"


def test_scan_events_empty_when_no_dir(isolate_vault):
    """06_Events 不存在时返回 []。"""
    assert kb.scan_events() == []


def test_find_event_file_by_frontmatter_id(isolate_vault):
    """文件名与 id 不一致时,兜底扫描 frontmatter id 仍能找到。"""
    tmp = isolate_vault
    edir = tmp / "06_Events"
    edir.mkdir(parents=True)
    # 文件名故意不含 id
    path = edir / "event_mismatch.md"
    kb.write_event_file(path, {
        "id": "event_renamed_id", "title": "X", "date": "2026-06-06",
        "category": "其他", "status": "active", "synced_calendar_ids": "",
    }, "", is_new=True)
    found = kb._find_event_file("event_renamed_id")
    assert found is not None
    assert found.name == "event_mismatch.md"


def test_find_event_file_not_found(isolate_vault):
    assert kb._find_event_file("event_nonexistent") is None


# —— 同步到日历 ——

def _create_event(tmp, title="比赛A", date="2026-08-01", category="比赛"):
    """辅助:创建一个事件文件并返回其 id。"""
    edir = tmp / "06_Events"
    edir.mkdir(parents=True, exist_ok=True)
    eid = kb.make_event_id(title)
    path = kb._event_file_path(eid)
    kb.write_event_file(path, {
        "id": eid, "title": title, "date": date,
        "category": category, "note": "备注", "status": "active",
        "synced_calendar_ids": "",
    }, "正文", is_new=True)
    return eid


def test_sync_creates_calendar_item(isolate_vault):
    """首次同步:创建日历项,回指 event_id,source_type=event。"""
    tmp = isolate_vault
    eid = _create_event(tmp)

    result = kb.sync_event_to_calendar(eid)
    assert result["synced"] is True
    assert result["reason"] == "created"
    cal_id = result["calendar_id"]
    assert cal_id.startswith("cal_")

    # 日历里有这条
    cal = kb.load_calendar()
    item = cal["items"][cal_id]
    assert item["title"] == "比赛A"
    assert item["date"] == "2026-08-01"
    assert item["category"] == "比赛"
    assert item["source_type"] == "event"
    assert item["event_id"] == eid

    # 事件的 synced_calendar_ids 已更新
    path = kb._find_event_file(eid)
    ev = kb.load_event_file(path)
    assert cal_id in ev["synced_calendar_ids"]


def test_sync_idempotent_when_already_synced(isolate_vault):
    """已有存活日历项时,再次同步不重复创建。"""
    tmp = isolate_vault
    eid = _create_event(tmp)
    r1 = kb.sync_event_to_calendar(eid)
    assert r1["synced"] is True

    r2 = kb.sync_event_to_calendar(eid)
    assert r2["synced"] is False
    assert r2["reason"] == "already_synced"
    assert r2["calendar_id"] == r1["calendar_id"]

    # 日历里仍只有一条
    cal = kb.load_calendar()
    event_items = [it for it in cal["items"].values() if it.get("event_id") == eid]
    assert len(event_items) == 1


def test_sync_again_after_calendar_deleted(isolate_vault):
    """同步后日历项被删,允许重新推送(单向语义:两边独立)。"""
    tmp = isolate_vault
    eid = _create_event(tmp)
    r1 = kb.sync_event_to_calendar(eid)
    cal_id_1 = r1["calendar_id"]

    # 模拟用户在日历页删了这条
    cal = kb.load_calendar()
    del cal["items"][cal_id_1]
    kb.save_calendar(cal)

    # 再同步:旧 id 已不在日历,应创建新的
    r2 = kb.sync_event_to_calendar(eid)
    assert r2["synced"] is True
    assert r2["reason"] == "created"
    assert r2["calendar_id"] != cal_id_1


def test_sync_event_not_found(isolate_vault):
    result = kb.sync_event_to_calendar("event_ghost")
    assert result["synced"] is False
    assert result["reason"] == "event_not_found"


def test_sync_event_without_date(isolate_vault):
    """事件没有日期时拒绝同步。"""
    tmp = isolate_vault
    edir = tmp / "06_Events"
    edir.mkdir(parents=True)
    eid = "event_nodate"
    kb.write_event_file(edir / f"{eid}.md", {
        "id": eid, "title": "无日期", "date": "",
        "category": "其他", "status": "active", "synced_calendar_ids": "",
    }, "", is_new=True)
    result = kb.sync_event_to_calendar(eid)
    assert result["synced"] is False
    assert result["reason"] == "event_has_no_date"


def test_delete_event_does_not_touch_calendar(isolate_vault):
    """删除事件不级联删日历项(单向推送语义)。"""
    tmp = isolate_vault
    eid = _create_event(tmp)
    r = kb.sync_event_to_calendar(eid)
    cal_id = r["calendar_id"]

    # 删事件
    path = kb._find_event_file(eid)
    path.unlink()
    assert not path.exists()

    # 日历项仍在
    cal = kb.load_calendar()
    assert cal_id in cal["items"]


# —— Web API ——

@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient + 隔离 vault(与 test_accept_transactional 同款)。"""
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb, "CALENDAR_FILE", kb_dir / "calendar.json")
    monkeypatch.setattr(kb, "LOGS_DIR", kb_dir / "logs")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    (tmp_path / "06_Events").mkdir(parents=True)
    (tmp_path / ".kb").mkdir(parents=True)
    return TestClient(kb_web.app), tmp_path


def test_api_create_event(client):
    c, tmp = client
    resp = c.post("/api/events", json={
        "title": "ICML 2026", "date": "2026-07-15",
        "category": "会议", "note": "顶会", "body": "关注 RL 方向",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    ev = data["event"]
    assert ev["title"] == "ICML 2026"
    assert ev["date"] == "2026-07-15"
    assert ev["category"] == "会议"
    assert "关注 RL" in ev["body"]
    assert ev["id"].startswith("event_")
    # 文件确实创建了
    assert (tmp / "06_Events").glob("event_*.md")


def test_api_create_event_rejects_empty_title(client):
    c, _ = client
    resp = c.post("/api/events", json={"title": "", "date": "2026-01-01"})
    assert resp.status_code == 400


def test_api_create_event_rejects_bad_date(client):
    c, _ = client
    resp = c.post("/api/events", json={"title": "X", "date": "not-a-date"})
    assert resp.status_code == 400


def test_api_create_event_rejects_bad_status(client):
    c, _ = client
    resp = c.post("/api/events", json={"title": "X", "date": "2026-01-01", "status": "bogus"})
    assert resp.status_code == 400


def test_api_list_events(client):
    c, _ = client
    c.post("/api/events", json={"title": "事件A", "date": "2026-03-01", "category": "比赛"})
    c.post("/api/events", json={"title": "事件B", "date": "2026-01-01", "category": "会议"})
    resp = c.get("/api/events")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # 按日期升序
    assert items[0]["date"] == "2026-01-01"
    assert items[1]["date"] == "2026-03-01"


def test_api_update_event(client):
    c, _ = client
    create = c.post("/api/events", json={"title": "旧标题", "date": "2026-01-01", "category": "其他"})
    eid = create.json()["event"]["id"]

    resp = c.patch(f"/api/events/{eid}", json={
        "title": "新标题", "date": "2026-09-09", "category": "财报",
        "note": "改了备注", "body": "改了正文", "status": "done",
    })
    assert resp.status_code == 200
    ev = resp.json()["event"]
    assert ev["title"] == "新标题"
    assert ev["date"] == "2026-09-09"
    assert ev["category"] == "财报"
    assert ev["status"] == "done"
    assert "改了正文" in ev["body"]


def test_api_update_event_not_found(client):
    c, _ = client
    resp = c.patch("/api/events/event_ghost", json={"title": "X"})
    assert resp.status_code == 404


def test_api_delete_event(client):
    c, _ = client
    create = c.post("/api/events", json={"title": "待删", "date": "2026-01-01"})
    eid = create.json()["event"]["id"]

    resp = c.delete(f"/api/events/{eid}")
    assert resp.status_code == 200
    # 再 GET 应 404
    assert c.get(f"/api/events/{eid}").status_code == 404


def test_api_get_event(client):
    c, _ = client
    create = c.post("/api/events", json={
        "title": "详情", "date": "2026-05-05", "body": "正文内容",
    })
    eid = create.json()["event"]["id"]
    resp = c.get(f"/api/events/{eid}")
    assert resp.status_code == 200
    ev = resp.json()
    assert ev["id"] == eid
    assert "正文内容" in ev["body"]


def test_api_sync_calendar(client):
    c, _ = client
    create = c.post("/api/events", json={"title": "同步", "date": "2026-08-01", "category": "比赛"})
    eid = create.json()["event"]["id"]

    resp = c.post(f"/api/events/{eid}/sync-calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] is True
    assert data["calendar_id"].startswith("cal_")

    # 再同步:幂等
    resp2 = c.post(f"/api/events/{eid}/sync-calendar")
    assert resp2.status_code == 200
    assert resp2.json()["synced"] is False
    assert resp2.json()["reason"] == "already_synced"


def test_api_sync_calendar_not_found(client):
    c, _ = client
    resp = c.post("/api/events/event_ghost/sync-calendar")
    assert resp.status_code == 404


def test_events_page_renders(client):
    """GET /events 返回 HTML(含导航 active 标记)。"""
    c, _ = client
    resp = c.get("/events")
    assert resp.status_code == 200
    assert "事件" in resp.text
