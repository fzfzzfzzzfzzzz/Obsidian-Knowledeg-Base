"""web /api/ingest 回归 —— 投稿不得覆盖/丢失 inbox 中已有的未处理内容。"""
import kb
import kb_llm
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 隔离 kb 的全部 vault 路径
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb, "RAW_TEXT_DIR", kb_dir / "raw_text")
    monkeypatch.setattr(kb, "LOGS_DIR", kb_dir / "logs")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    # 避免真实联网:让 LLM 配置报告不可用,使自由文本 item 走「失败保留」分支(返回 0,内容留 inbox)
    monkeypatch.setattr(kb_llm, "load_config", lambda: {"available": False})

    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    # 预置用户已在 inbox 中、尚未处理的笔记
    (inbox / "inbox.md").write_text(
        "# Inbox\n\n> 说明\n\n用户已有的重要笔记\n", encoding="utf-8"
    )
    return TestClient(kb_web.app)


def test_api_ingest_preserves_existing(client):
    resp = client.post(
        "/api/ingest",
        json={"items": ["新的投稿内容"], "auto_summary": False},
    )
    assert resp.status_code == 200
    inbox_text = (kb.VAULT_ROOT / "00_Inbox" / "inbox.md").read_text(encoding="utf-8")
    # 原有内容未被覆盖
    assert "用户已有的重要笔记" in inbox_text
    # 新投稿内容已追加
    assert "新的投稿内容" in inbox_text


def test_api_ingest_empty_400(client):
    resp = client.post("/api/ingest", json={"items": ["", "   "]})
    assert resp.status_code == 400
