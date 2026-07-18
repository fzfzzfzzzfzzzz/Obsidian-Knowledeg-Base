"""v0.4.2: 日历事项 category 字段测试。

聚焦:
- POST 带 category 落库正确,响应回填 category
- POST 不带 category 落库为空串,GET 运行时回填为「其他」
- source_type=todo 且无 category 时回填为「todolist」
- PATCH 更新 category
- 落库 vs 响应区分:磁盘存原值,响应给前端回填值
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "CALENDAR_FILE", kb_dir / "calendar.json")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    return TestClient(kb_web.app), tmp_path


def test_create_with_explicit_category(client):
    """POST 带 category 落库 + 响应回填。"""
    c, _ = client
    r = c.post("/api/calendar", json={
        "title": "WAIC 大会", "date": "2026-07-16", "category": "会议"})
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["category"] == "会议"

    # 落库也是「会议」
    cal = kb.load_calendar()
    stored = list(cal["items"].values())[0]
    assert stored["category"] == "会议"


def test_create_without_category_falls_back_to_other(client):
    """POST 不带 category → 落库空串,GET 回填「其他」。"""
    c, _ = client
    r = c.post("/api/calendar", json={
        "title": "某事项", "date": "2026-07-20", "source_type": ""})
    assert r.status_code == 200
    item_id = r.json()["item"]["id"]

    # 响应回填为「其他」
    assert r.json()["item"]["category"] == "其他"

    # 但磁盘上 category 为空串(未写死)
    cal = kb.load_calendar()
    assert cal["items"][item_id]["category"] == ""

    # GET 也回填「其他」
    got = c.get(f"/api/calendar/{item_id}").json()
    assert got["category"] == "其他"


def test_todo_source_falls_back_to_todolist(client):
    """source_type=todo 且无 category → 回填「todolist」。"""
    c, _ = client
    r = c.post("/api/calendar", json={
        "title": "某 todo", "date": "2026-07-22",
        "source_type": "todo", "source_id": "todo_abc"})
    assert r.status_code == 200
    assert r.json()["item"]["category"] == "todolist"

    # 列表接口也回填
    items = c.get("/api/calendar").json()["items"]
    assert items[0]["category"] == "todolist"


def test_patch_updates_category(client):
    """PATCH 改 category 成功落库。"""
    c, _ = client
    r = c.post("/api/calendar", json={
        "title": "t", "date": "2026-07-20", "category": "会议"})
    item_id = r.json()["item"]["id"]

    r2 = c.patch(f"/api/calendar/{item_id}", json={"category": "截止日期"})
    assert r2.status_code == 200
    assert r2.json()["item"]["category"] == "截止日期"

    # 落库确认
    cal = kb.load_calendar()
    assert cal["items"][item_id]["category"] == "截止日期"


def test_patch_category_none_does_not_change(client):
    """PATCH 不带 category 字段(None) → 不改原 category。"""
    c, _ = client
    r = c.post("/api/calendar", json={
        "title": "t", "date": "2026-07-20", "category": "财报"})
    item_id = r.json()["item"]["id"]

    # 只改 title,不带 category
    r2 = c.patch(f"/api/calendar/{item_id}", json={"title": "改了标题"})
    assert r2.status_code == 200
    assert r2.json()["item"]["category"] == "财报"


def test_custom_category_preserved(client):
    """自定义类别(非预设)原样存储,GET 返回原值。"""
    c, _ = client
    r = c.post("/api/calendar", json={
        "title": "团建", "date": "2026-08-01", "category": "团建活动"})
    assert r.status_code == 200
    item_id = r.json()["item"]["id"]
    assert r.json()["item"]["category"] == "团建活动"

    got = c.get(f"/api/calendar/{item_id}").json()
    assert got["category"] == "团建活动"


def test_resolve_category_helper():
    """单元测试 _resolve_category 逻辑。"""
    assert kb_web._resolve_category({"category": "会议"}) == "会议"
    assert kb_web._resolve_category({"category": "", "source_type": "todo"}) == "todolist"
    assert kb_web._resolve_category({"source_type": "todo"}) == "todolist"
    assert kb_web._resolve_category({"source_type": "github"}) == "其他"
    assert kb_web._resolve_category({}) == "其他"
    assert kb_web._resolve_category({"category": "自定义"}) == "自定义"
