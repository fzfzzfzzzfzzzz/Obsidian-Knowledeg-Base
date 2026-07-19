"""Web accept 事务化(v0.4.5)—— 搬运失败回滚 + 文件锁串行化。

覆盖:
- 搬运失败时 status 回滚到原值(不卡在 accepted_*)
- 并发请求串行化(文件锁)
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


@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    plans = tmp_path / "04_Plans"
    plans.mkdir(parents=True)
    (plans / "todo_suggestions.md").write_text(TODO_FILE_BODY, encoding="utf-8")
    return TestClient(kb_web.app), tmp_path


def test_accept_rollback_on_move_failure(client, monkeypatch):
    """搬运函数抛错时,status 应回滚到原值 pending_review(不卡在 accepted_*)。"""
    c, tmp = client
    # 让 move_accepted_todo 抛错
    def boom(item_id):
        raise RuntimeError("simulated move failure")
    monkeypatch.setattr(kb, "move_accepted_todo", boom)

    r = c.post("/api/todo/todo_accept_test_1/status",
               json={"status": "accepted_weekly"})
    assert r.status_code == 200
    body = r.json()
    assert body["moved"] is False
    assert "move_error" in body
    assert body.get("rolled_back_to") == "pending_review"

    # 验证 suggestion 文件里 status 已回滚
    sug = (tmp / "04_Plans" / "todo_suggestions.md").read_text(encoding="utf-8")
    assert "- status: pending_review" in sug
    assert "- status: accepted_weekly" not in sug
    # weekly 文件不应被创建
    weekly_dir = tmp / "04_Plans" / "Weekly"
    if weekly_dir.exists():
        assert list(weekly_dir.glob("*.md")) == []


def test_accept_rollback_on_idea_move_failure(tmp_path, monkeypatch):
    """idea 端同样验证:move 失败回滚。"""
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    import kb_web
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)

    ideas = tmp_path / "03_Ideas"
    ideas.mkdir(parents=True)
    (ideas / "idea_suggestions.md").write_text(
        "# Idea Suggestions (Review Queue)\n\n> 说明\n\n"
        "## Idea Suggestion: 想法X\n\n"
        "- id: idea_rb1\n- status: pending_review\n- source_summary: x.md\n\n正文\n",
        encoding="utf-8",
    )

    def boom(item_id):
        raise RuntimeError("disk full")
    monkeypatch.setattr(kb, "move_accepted_idea", boom)

    c = TestClient(kb_web.app)
    r = c.post("/api/idea/idea_rb1/status", json={"status": "accepted_research"})
    assert r.status_code == 200
    body = r.json()
    assert body["moved"] is False
    assert body.get("rolled_back_to") == "pending_review"
    # research_ideas.md 不应被创建
    assert not (ideas / "research_ideas.md").exists()


def test_concurrent_accept_no_duplicate(tmp_path, monkeypatch):
    """两个并发 accept 请求:文件锁应串行化,不会重复搬运。"""
    import threading
    import time

    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    import kb_web
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)

    ideas = tmp_path / "03_Ideas"
    ideas.mkdir(parents=True)
    (ideas / "idea_suggestions.md").write_text(
        "# Idea Suggestions (Review Queue)\n\n> 说明\n\n"
        "## Idea Suggestion: 并发想法\n\n"
        "- id: idea_cc1\n- status: pending_review\n- source_summary: x.md\n\n正文\n",
        encoding="utf-8",
    )

    c = TestClient(kb_web.app)
    results = []

    def do_accept():
        try:
            r = c.post("/api/idea/idea_cc1/status",
                       json={"status": "accepted_research"})
            results.append(r.json())
        except Exception as e:
            results.append({"error": str(e)})

    # 两个线程同时发请求
    t1 = threading.Thread(target=do_accept)
    t2 = threading.Thread(target=do_accept)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # 至少一个 moved=True,另一个应该是 already_moved 或 moved=False
    moved_count = sum(1 for r in results if r.get("moved"))
    assert moved_count == 1, f"应该只搬一次,实际搬了 {moved_count} 次: {results}"

    # research_ideas.md 里 "## Idea: 并发想法" 应只出现一次
    research = ideas / "research_ideas.md"
    assert research.exists()
    content = research.read_text(encoding="utf-8")
    assert content.count("## Idea: 并发想法") == 1, \
        f"正式清单出现重复条目!\n{content}"
