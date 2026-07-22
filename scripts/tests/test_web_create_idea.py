"""POST /api/ideas 新建 idea 功能测试(v0.4.11)。

验证:手动新建 idea → 追加到 idea_suggestions.md 待定队列 → 出现在 /api/ideas 列表 →
接受(accepted_general)→ 进入 general_ideas.md → 出现在 /api/ideas/confirmed。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(isolate_vault):
    # 确保队列文件存在(空 header)
    sug = kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    sug.parent.mkdir(parents=True, exist_ok=True)
    if not sug.exists():
        sug.write_text("# Idea Suggestions\n\n", encoding="utf-8")
    return TestClient(kb_web.app)


def test_create_idea_basic(client):
    """新建 idea → 200 + 返回 id/title。"""
    r = client.post("/api/ideas", json={"title": "测试新想法"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["title"] == "测试新想法"
    assert d["id"].startswith("idea_suggestion_")


def test_create_idea_appears_in_list(client):
    """新建后,idea 出现在 /api/ideas 待定列表(status=pending_review)。"""
    client.post("/api/ideas", json={"title": "列表里要有我"})
    r = client.get("/api/ideas")
    assert r.status_code == 200
    items = r.json()["items"]
    titles = [it["title"] for it in items]
    assert "列表里要有我" in titles
    # 确认新 idea 是 pending_review
    new = [it for it in items if it["title"] == "列表里要有我"][0]
    assert new["status"] == "pending_review"


def test_create_idea_empty_title_400(client):
    """空标题 → 400。"""
    r = client.post("/api/ideas", json={"title": "   "})
    assert r.status_code == 400


def test_create_idea_strips_whitespace(client):
    """标题 strip 前后空格。"""
    r = client.post("/api/ideas", json={"title": "  带空格的  "})
    assert r.status_code == 200
    assert r.json()["title"] == "带空格的"


def test_create_then_accept_general(client):
    """新建 → 接受(accepted_general)→ 进 general_ideas.md。"""
    # 新建
    r = client.post("/api/ideas", json={"title": "要接受的idea"})
    iid = r.json()["id"]
    # 接受(accepted_general,v0.4.11 新状态)
    r2 = client.post(f"/api/idea/{iid}/status", json={"status": "accepted_general"})
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2.get("moved") is True
    assert d2.get("area") == "general"
    # 确认进入 general_ideas.md
    general_file = kb.VAULT_ROOT / "03_Ideas" / "general_ideas.md"
    assert general_file.exists()
    content = general_file.read_text(encoding="utf-8")
    assert "要接受的idea" in content
    # 确认出现在 confirmed 列表
    r3 = client.get("/api/ideas/confirmed")
    confirmed_titles = [it["title"] for it in r3.json()["items"]]
    assert "要接受的idea" in confirmed_titles


def test_create_then_reject(client):
    """新建 → 拒绝 → 从待定列表删除。"""
    r = client.post("/api/ideas", json={"title": "要拒绝的"})
    iid = r.json()["id"]
    r2 = client.post(f"/api/idea/{iid}/status", json={"status": "rejected"})
    assert r2.status_code == 200
    assert r2.json().get("deleted") is True
    # 确认不在待定列表
    r3 = client.get("/api/ideas")
    titles = [it["title"] for it in r3.json()["items"]]
    assert "要拒绝的" not in titles


def test_create_idea_id_unique(client):
    """连续创建两个 idea,id 不重复(随机后缀)。"""
    r1 = client.post("/api/ideas", json={"title": "重复标题"})
    r2 = client.post("/api/ideas", json={"title": "重复标题"})
    assert r1.json()["id"] != r2.json()["id"]


def test_create_idea_creates_suggestion_file_if_missing(isolate_vault):
    """队列文件不存在时,自动创建。"""
    sug = kb.VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    if sug.exists():
        sug.unlink()
    c = TestClient(kb_web.app)
    r = c.post("/api/ideas", json={"title": "建文件测试"})
    assert r.status_code == 200
    assert sug.exists()
