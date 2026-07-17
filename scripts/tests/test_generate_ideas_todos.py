"""详情页手动生成 idea/todo(v0.4.0)的接口测试。

用 monkeypatch 替换 kb_llm.extract_* 避免真实 LLM 调用,聚焦验证:
- 校验(source 不存在 / 无 summary)
- 成功生成后追加进 review 队列,不覆盖已有内容
- hint 拼装正确
- kb_llm._with_hint 的向后兼容(hint=None 走原路径)
"""
import json

import pytest
from fastapi.testclient import TestClient

import kb
import kb_llm
import kb_web


@pytest.fixture
def client(isolate_vault, monkeypatch):
    """TestClient + 隔离 vault。

    kb_web 在导入时已读取 VAULT_ROOT 模块级常量(指向真实 vault),
    这里 monkeypatch 到隔离路径,并强制让请求处理函数每次重新读取。
    """
    monkeypatch.setattr(kb_web, "VAULT_ROOT", isolate_vault)
    # 建子目录
    (isolate_vault / "03_Ideas").mkdir(parents=True, exist_ok=True)
    (isolate_vault / "04_Plans").mkdir(parents=True, exist_ok=True)
    (isolate_vault / "02_Summaries" / "manual").mkdir(parents=True, exist_ok=True)
    return TestClient(kb_web.app)


def _seed_source_with_summary(vault_root, source_id="source_test1"):
    """在隔离 vault 里造一篇有 summary 的 source。返回 source_id。"""
    state = {"sources": {}}
    summary_path = vault_root / "02_Summaries" / "manual" / f"summary_{source_id}.md"
    summary_path.write_text(
        "---\nid: summary_" + source_id + "\n---\n\n这是测试 summary 正文。\n",
        encoding="utf-8",
    )
    state["sources"][source_id] = {
        "summary_path": str(summary_path.relative_to(vault_root)).replace("\\", "/"),
        "source_type": "manual",
    }
    kb.save_state(state)
    return source_id


# ---------------------------------------------------------------------------
# kb_llm._with_hint 单元
# ---------------------------------------------------------------------------


def test_with_hint_none_returns_truncated():
    assert kb_llm._with_hint("body", None) == "body"
    assert kb_llm._with_hint("body", "   ") == "body"
    assert len(kb_llm._with_hint("x" * 60000, None)) == 50000


def test_with_hint_prepends_pref_block():
    out = kb_llm._with_hint("body", "优先级: P1")
    assert "【用户偏好(参考,不强制)】" in out
    assert "优先级: P1" in out
    assert "--- 以下是文章 summary ---" in out
    assert out.endswith("body")


# ---------------------------------------------------------------------------
# kb_web._build_hint 单元
# ---------------------------------------------------------------------------


def test_build_hint_all_empty():
    assert kb_web._build_hint(kb_web.GenerateIdeasRequest()) == ""


def test_build_hint_idea_fields():
    h = kb_web._build_hint(
        kb_web.GenerateIdeasRequest(prompt="找 agent", priority="P1", area="ai_agent")
    )
    assert "优先级: P1" in h
    assert "领域: ai_agent" in h
    assert "引导: 找 agent" in h


def test_build_hint_todo_partial():
    h = kb_web._build_hint(
        kb_web.GenerateTodosRequest(difficulty="medium", estimated_time="2-4h")
    )
    assert "难度: medium" in h
    assert "预计时间: 2-4h" in h
    assert "优先级" not in h  # 未填的不出现


# ---------------------------------------------------------------------------
# 接口:校验
# ---------------------------------------------------------------------------


def test_generate_ideas_source_not_found(client):
    r = client.post("/api/article/source_none/generate-ideas", json={})
    assert r.status_code == 404


def test_generate_todos_no_summary(client, isolate_vault):
    # source 存在但没 summary
    kb.save_state({"sources": {"source_nosum": {"source_type": "manual"}}})
    r = client.post("/api/article/source_nosum/generate-todos", json={})
    assert r.status_code == 400
    assert "summary" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 接口:成功生成 + 追加不覆盖 + hint 传递
# ---------------------------------------------------------------------------


def test_generate_ideas_success_appends(client, isolate_vault, monkeypatch):
    sid = _seed_source_with_summary(isolate_vault)

    captured = {}

    def fake_extract(summary_text, hint=None):
        captured["summary"] = summary_text
        captured["hint"] = hint
        return [
            {"title": "idea A", "recommended_area": "ai_agent", "priority": "P1",
             "feasibility": "medium", "novelty": "high", "estimated_investment": "2h",
             "reason": "r", "what": "w", "challenges": "c"}
        ]

    monkeypatch.setattr(kb_llm, "extract_ideas_from_summary", fake_extract)

    # 预置一条已有候选,验证追加不覆盖
    idea_file = isolate_vault / "03_Ideas" / "idea_suggestions.md"
    idea_file.write_text("# Idea Suggestions (Review Queue)\n\nOLD CONTENT\n", encoding="utf-8")

    r = client.post(
        f"/api/article/{sid}/generate-ideas",
        json={"prompt": "找 agent", "priority": "P1", "area": "ai_agent"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["kind"] == "idea"
    assert data["generated"] == 1

    # hint 正确拼装并传入(非 None)
    assert captured["hint"] is not None
    assert "优先级: P1" in captured["hint"]
    assert "领域: ai_agent" in captured["hint"]
    assert "引导: 找 agent" in captured["hint"]

    # 老内容保留 + 新候选追加
    content = idea_file.read_text(encoding="utf-8")
    assert "OLD CONTENT" in content
    assert "idea A" in content
    assert "pending_review" in content


def test_generate_todos_success_and_action_status_unchanged(client, isolate_vault, monkeypatch):
    sid = _seed_source_with_summary(isolate_vault)

    monkeypatch.setattr(
        kb_llm, "extract_todos_from_summary",
        lambda text, hint=None: [{"title": "todo A", "recommended_plan": "weekly",
                                  "priority": "P1", "estimated_time": "2-4h",
                                  "difficulty": "medium", "why": "y", "what": "w",
                                  "challenges": "c", "acceptance": "a"}],
    )

    r = client.post(f"/api/article/{sid}/generate-todos", json={"plan": "weekly"})
    assert r.status_code == 200
    assert r.json()["generated"] == 1

    # action_status 不应被设置(允许重抽,不影响批量入口幂等)
    state = kb.load_state()
    assert "action_status" not in state["sources"][sid]

    todo_file = isolate_vault / "04_Plans" / "todo_suggestions.md"
    assert "todo A" in todo_file.read_text(encoding="utf-8")


def test_generate_ideas_zero_candidates(client, isolate_vault, monkeypatch):
    sid = _seed_source_with_summary(isolate_vault)
    monkeypatch.setattr(kb_llm, "extract_ideas_from_summary", lambda *a, **kw: [])
    r = client.post(f"/api/article/{sid}/generate-ideas", json={})
    assert r.status_code == 200
    assert r.json()["generated"] == 0


def test_generate_ideas_llm_failure(client, isolate_vault, monkeypatch):
    sid = _seed_source_with_summary(isolate_vault)

    def boom(*a, **kw):
        raise kb_llm.LLMError("API down")

    monkeypatch.setattr(kb_llm, "extract_ideas_from_summary", boom)
    r = client.post(f"/api/article/{sid}/generate-ideas", json={})
    assert r.status_code == 500
    assert "LLM" in r.json()["detail"]


def test_backward_compat_extract_without_hint(monkeypatch):
    """现有调用方(CLI / 批量动作)不带 hint 调用,行为不变。"""
    # 只验证签名兼容:能以单参数调用(真实 chat 不触发,这里只测签名)
    # extract_ideas_from_summary(summary_text) 必须可调用不报 TypeError
    import inspect
    sig = inspect.signature(kb_llm.extract_ideas_from_summary)
    assert list(sig.parameters) == ["summary_text", "hint"]
    assert sig.parameters["hint"].default is None
    sig2 = inspect.signature(kb_llm.extract_todos_from_summary)
    assert sig2.parameters["hint"].default is None
