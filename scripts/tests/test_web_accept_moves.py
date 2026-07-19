"""Web 端「接受即搬运」—— POST /api/idea|todo/{id}/status 带 accepted_* 自动搬到正式清单。

回归:覆盖 reject 不搬、accepted 搬运、搬运后原 suggestion 标 moved、
非 accepted 状态(如 archived)不搬。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


TODO_FILE_BODY = """# Todo Suggestions (Review Queue)

> 说明

## Todo Suggestion: 周任务

- id: todo_accept_test_1
- status: pending_review
- recommended_plan: weekly
- estimated_time: 2h
- source_summary: x.md

正文
"""

IDEA_FILE_BODY = """# Idea Suggestions (Review Queue)

> 说明

## Idea Suggestion: 科研想法

- id: idea_accept_test_1
- status: pending_review
- recommended_area: research
- priority: P1
- source_summary: x.md

正文
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """与 test_reject_delete.py 同款 fixture:同时 patch kb 和 kb_web 的 VAULT_ROOT。"""
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


# —— 接受即搬运 ——

def test_accept_idea_moves_to_research_ideas(client):
    """POST idea status=accepted_research → 搬到 research_ideas.md + 原块标 moved。"""
    c, tmp = client
    r = c.post("/api/idea/idea_accept_test_1/status",
               json={"status": "accepted_research"})
    assert r.status_code == 200
    body = r.json()
    assert body["moved"] is True
    assert "research_ideas.md" in body["moved_to"]
    assert body["area"] == "research"

    # 正式文件存在并包含 idea
    research = tmp / "03_Ideas" / "research_ideas.md"
    assert research.exists()
    assert "科研想法" in research.read_text(encoding="utf-8")

    # 原 suggestion 块标 moved(status 行应是 moved,不再是 accepted_research)
    sug = (tmp / "03_Ideas" / "idea_suggestions.md").read_text(encoding="utf-8")
    assert "- status: moved" in sug
    assert "- status: accepted_research" not in sug


def test_accept_todo_moves_to_weekly(client):
    """POST todo status=accepted_weekly → 搬到 04_Plans/Weekly/<tag>.md。"""
    c, tmp = client
    r = c.post("/api/todo/todo_accept_test_1/status",
               json={"status": "accepted_weekly"})
    assert r.status_code == 200
    body = r.json()
    assert body["moved"] is True
    assert body["plan"] == "weekly"
    assert "Weekly" in body["moved_to"]

    weekly_files = list((tmp / "04_Plans" / "Weekly").glob("*.md"))
    assert len(weekly_files) == 1
    assert "周任务" in weekly_files[0].read_text(encoding="utf-8")

    # 原 suggestion 标 moved
    sug = (tmp / "04_Plans" / "todo_suggestions.md").read_text(encoding="utf-8")
    assert "status: moved" in sug


def test_accept_todo_monthly(client):
    c, tmp = client
    r = c.post("/api/todo/todo_accept_test_1/status",
               json={"status": "accepted_monthly"})
    assert r.status_code == 200
    assert r.json()["moved"] is True
    assert r.json()["plan"] == "monthly"
    assert (tmp / "04_Plans" / "Monthly").exists()


def test_accept_todo_someday(client):
    c, tmp = client
    r = c.post("/api/todo/todo_accept_test_1/status",
               json={"status": "accepted_someday"})
    assert r.status_code == 200
    assert r.json()["moved"] is True
    assert r.json()["plan"] == "someday"
    assert (tmp / "04_Plans" / "someday.md").exists()


# —— 非 accepted 状态不搬 ——

def test_reject_does_not_move(client):
    """rejected 触发删块,不应尝试搬运(moved 字段不存在或 False)。"""
    c, tmp = client
    r = c.post("/api/todo/todo_accept_test_1/status",
               json={"status": "rejected"})
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True
    # 不应有 moved_to(rejected 不搬)
    assert "moved_to" not in body
    # 正式清单文件不应被创建
    assert not (tmp / "04_Plans" / "Weekly").exists() or \
           not list((tmp / "04_Plans" / "Weekly").glob("*.md"))


def test_archived_does_not_move(client):
    """archived 不是 accepted_*,不应触发搬运。"""
    c, tmp = client
    r = c.post("/api/idea/idea_accept_test_1/status",
               json={"status": "archived"})
    assert r.status_code == 200
    body = r.json()
    # 不搬
    assert not body.get("moved")
    assert not (tmp / "03_Ideas" / "research_ideas.md").exists()


def test_pending_review_does_not_move(client):
    """pending_review 不应触发搬运。"""
    c, tmp = client
    r = c.post("/api/idea/idea_accept_test_1/status",
               json={"status": "pending_review"})
    assert r.status_code == 200
    assert not r.json().get("moved")
    assert not (tmp / "03_Ideas" / "research_ideas.md").exists()


# —— 幂等 ——

def test_double_accept_second_is_noop(client):
    """第一次 accept 搬运 + 标 moved;第二次再 accept 同一个 id 应 no-op(已 moved)。"""
    c, tmp = client
    # 第一次
    r1 = c.post("/api/idea/idea_accept_test_1/status",
                json={"status": "accepted_research"})
    assert r1.status_code == 200
    assert r1.json()["moved"] is True
    research = tmp / "03_Ideas" / "research_ideas.md"
    content_after_first = research.read_text(encoding="utf-8")
    # 第二次:此时原块已是 moved,但前端可能误发 accepted_research
    # _update_suggestion_status 会找不到 accepted_research 行(已是 moved),
    # 实际上会失败或 no-op。验证不重复追加内容。
    r2 = c.post("/api/idea/idea_accept_test_1/status",
                json={"status": "accepted_research"})
    # 不管 r2 是 200 还是 4xx,research_ideas.md 不应被追加第二次
    if research.exists():
        content_after_second = research.read_text(encoding="utf-8")
        assert content_after_second.count("## Idea: 科研想法") == 1
