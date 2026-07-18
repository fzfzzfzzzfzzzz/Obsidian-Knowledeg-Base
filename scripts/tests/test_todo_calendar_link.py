"""已确认 todo → 日历链接功能测试。

聚焦:
- todo 确定性 id 稳定(重新解析不变)
- POST /api/calendar 用 todo id 作 source_id 创建事项 + 去重
- /api/todos/confirmed 返回的 item 带 id 字段
"""
import hashlib

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


WEEKLY_FILE = """# Weekly Todo: 2026-W29

## 本周重点

- [ ] 测试 todo
  - 来源:[[s]]
  - 预计时间:2-4h
"""


def test_todo_has_deterministic_id(client):
    c, tmp = client
    plans = tmp / "04_Plans"
    (plans / "Weekly").mkdir(parents=True)
    (plans / "Weekly" / "2026-W29.md").write_text(WEEKLY_FILE, encoding="utf-8")

    items = kb_web._parse_formal_todos()
    assert len(items) == 1
    tid = items[0]["id"]
    # 确定性:基于 plan+period+title
    expected_raw = "weekly|2026-W29|测试 todo"
    expected = "todo_" + hashlib.sha1(expected_raw.encode("utf-8")).hexdigest()[:10]
    assert tid == expected


def test_todo_id_stable_across_reparse(client):
    """同一文件解析两次,id 不变(日历关联才不会丢)。"""
    c, tmp = client
    plans = tmp / "04_Plans"
    (plans / "Weekly").mkdir(parents=True)
    (plans / "Weekly" / "2026-W29.md").write_text(WEEKLY_FILE, encoding="utf-8")

    ids1 = [i["id"] for i in kb_web._parse_formal_todos()]
    ids2 = [i["id"] for i in kb_web._parse_formal_todos()]
    assert ids1 == ids2


def test_different_todos_different_ids(client):
    """不同 title 的 todo id 不同。"""
    c, tmp = client
    plans = tmp / "04_Plans"
    (plans / "Weekly").mkdir(parents=True)
    (plans / "Weekly" / "2026-W29.md").write_text(
        "- [ ] 任务甲\n- [ ] 任务乙\n", encoding="utf-8")
    ids = [i["id"] for i in kb_web._parse_formal_todos()]
    assert len(ids) == 2
    assert len(set(ids)) == 2  # 互不相同


def test_api_todos_confirmed_has_id(client):
    c, tmp = client
    plans = tmp / "04_Plans"
    (plans / "Weekly").mkdir(parents=True)
    (plans / "Weekly" / "2026-W29.md").write_text(WEEKLY_FILE, encoding="utf-8")
    items = c.get("/api/todos/confirmed").json()["items"]
    assert len(items) == 1
    assert items[0]["id"].startswith("todo_")


def test_create_calendar_with_todo_source_id(client):
    """用 todo id 作 source_id 创建日历事项。"""
    c, tmp = client
    plans = tmp / "04_Plans"
    (plans / "Weekly").mkdir(parents=True)
    (plans / "Weekly" / "2026-W29.md").write_text(WEEKLY_FILE, encoding="utf-8")
    todo_id = kb_web._parse_formal_todos()[0]["id"]

    r = c.post("/api/calendar", json={
        "title": "测试 todo",
        "date": "2026-07-20",
        "source_id": todo_id,
        "source_type": "todo",
        "source_title": "测试 todo",
    })
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["source_id"] == todo_id
    assert item["source_type"] == "todo"
    assert item["date"] == "2026-07-20"


def test_calendar_dedup_same_todo_source_id(client):
    """同一 todo id 再次创建,返回已有事项(去重),不重复。"""
    c, tmp = client
    todo_id = "todo_abc123"
    r1 = c.post("/api/calendar", json={
        "title": "t", "date": "2026-07-20", "source_id": todo_id, "source_type": "todo"})
    assert r1.status_code == 200
    first_id = r1.json()["item"]["id"]

    r2 = c.post("/api/calendar", json={
        "title": "t", "date": "2026-07-21", "source_id": todo_id, "source_type": "todo"})
    assert r2.status_code == 200
    assert r2.json().get("already_existed") is True
    assert r2.json()["item"]["id"] == first_id  # 同一事项


def test_todo_calendar_linkage_roundtrip(client):
    """端到端:todo → 放日历 → 查 calendar 能按 source_id 找回。"""
    c, tmp = client
    plans = tmp / "04_Plans"
    (plans / "Weekly").mkdir(parents=True)
    (plans / "Weekly" / "2026-W29.md").write_text(WEEKLY_FILE, encoding="utf-8")
    todo_id = kb_web._parse_formal_todos()[0]["id"]

    # 创建日历事项
    c.post("/api/calendar", json={
        "title": "测试 todo", "date": "2026-07-20",
        "source_id": todo_id, "source_type": "todo"})

    # 查日历,能按 source_id 找回这条
    cal_items = c.get("/api/calendar").json()["items"]
    linked = [i for i in cal_items if i["source_id"] == todo_id]
    assert len(linked) == 1
    assert linked[0]["date"] == "2026-07-20"
    assert linked[0]["source_type"] == "todo"
    # v0.4.2: todo 来源事项运行时回填 category=todolist
    assert linked[0]["category"] == "todolist"
