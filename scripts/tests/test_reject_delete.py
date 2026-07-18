"""拒绝 = 直接删除候选块(而非标成 rejected 保留)。

覆盖 todo + idea 两个端点,验证:
- POST status=rejected → 块从文件物理删除,返回 deleted=True
- 其他 status(accepted_*)仍走原「改 status 行」逻辑,deleted=False
- 删除不影响同文件其他块
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


TODO_FILE_BODY = """# Todo Suggestions (Review Queue)

> 说明

## Todo Suggestion: 任务A

- id: todo_suggestion_20260717_aaa
- status: pending_review
- recommended_plan: weekly

正文A

## Todo Suggestion: 任务B

- id: todo_suggestion_20260717_bbb
- status: pending_review
- recommended_plan: monthly

正文B
"""

IDEA_FILE_BODY = """# Idea Suggestions (Review Queue)

> 说明

## Idea Suggestion: 想法A

- id: idea_suggestion_20260717_aaa
- status: pending_review
- recommended_area: research

正文A
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    plans = tmp_path / "04_Plans"
    plans.mkdir(parents=True)
    (plans / "todo_suggestions.md").write_text(TODO_FILE_BODY, encoding="utf-8")
    ideas = tmp_path / "03_Ideas"
    ideas.mkdir(parents=True)
    (ideas / "idea_suggestions.md").write_text(IDEA_FILE_BODY, encoding="utf-8")
    return TestClient(kb_web.app), tmp_path


def test_reject_todo_deletes_block(client):
    """拒绝 todo = 块从文件删除。"""
    c, tmp = client
    r = c.post("/api/todo/todo_suggestion_20260717_aaa/status", json={"status": "rejected"})
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    # 文件里任务A 没了,任务B 还在
    content = (tmp / "04_Plans" / "todo_suggestions.md").read_text(encoding="utf-8")
    assert "任务A" not in content
    assert "todo_suggestion_20260717_aaa" not in content
    assert "任务B" in content


def test_reject_idea_deletes_block(client):
    """拒绝 idea = 块从文件删除。"""
    c, tmp = client
    r = c.post("/api/idea/idea_suggestion_20260717_aaa/status", json={"status": "rejected"})
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    content = (tmp / "03_Ideas" / "idea_suggestions.md").read_text(encoding="utf-8")
    assert "想法A" not in content
    assert "idea_suggestion_20260717_aaa" not in content


def test_accept_todo_not_deleted(client):
    """接受(非 rejected)仍走原逻辑:改 status 行,块保留,deleted=False。"""
    c, tmp = client
    r = c.post("/api/todo/todo_suggestion_20260717_aaa/status", json={"status": "accepted_weekly"})
    assert r.status_code == 200
    assert r.json()["deleted"] is False
    content = (tmp / "04_Plans" / "todo_suggestions.md").read_text(encoding="utf-8")
    assert "任务A" in content
    assert "accepted_weekly" in content


def test_reject_not_found_404(client):
    c, tmp = client
    r = c.post("/api/todo/todo_suggestion_nope/status", json={"status": "rejected"})
    assert r.status_code == 404


def test_reject_last_block_leaves_header(client):
    """删除最后一个块后,文件只剩 header(不崩,重建成功)。"""
    c, tmp = client
    # 先删 A
    c.post("/api/todo/todo_suggestion_20260717_aaa/status", json={"status": "rejected"})
    # 再删 B
    r = c.post("/api/todo/todo_suggestion_20260717_bbb/status", json={"status": "rejected"})
    assert r.status_code == 200
    content = (tmp / "04_Plans" / "todo_suggestions.md").read_text(encoding="utf-8")
    # 只剩 header,没有任务块
    assert "Todo Suggestions (Review Queue)" in content
    assert "任务A" not in content and "任务B" not in content


def test_get_todos_after_reject(client):
    """拒绝后 GET /api/todos 不再返回被删的候选。"""
    c, tmp = client
    before = c.get("/api/todos").json()["items"]
    assert len(before) == 2
    c.post("/api/todo/todo_suggestion_20260717_aaa/status", json={"status": "rejected"})
    after = c.get("/api/todos").json()["items"]
    assert len(after) == 1
    assert after[0]["id"] == "todo_suggestion_20260717_bbb"
