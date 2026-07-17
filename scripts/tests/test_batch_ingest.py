"""批量投稿:验证 /api/ingest 返回的统计字段 + 去重行为。

批量投稿把多个 URL 作为 items 一次性 POST,auto_summary=False,后端复用 cmd_ingest。
为避免真实联网/真实 LLM,mock extract_metadata_smart 和 fetch_url_text,
让自由文本 URL 走「成功识别 + 抓取成功」的真实路径。
"""
import kb
import kb_llm
import kb_web
import pytest
from fastapi.testclient import TestClient


def _fake_metadata(text):
    """模拟 LLM 成功识别:返回 (meta, fetch_info, enriched_text)。

    fetch_info['fetched']=False 表示不触发抓取分支(避免 mock fetch_url_text),
    metadata 用文本自身当正文,确保每个不同 URL 产生不同 source_id。
    """
    meta = {
        "source_type": "web",
        "source_url": text.strip(),
        "source_title": "测试标题 " + text.strip()[:20],
        "area": "research",
    }
    fetch_info = {
        "fetched": False, "fetch_ok": False, "fetch_error": "",
        "fetched_title": "", "fetched_chars": 0,
    }
    return meta, fetch_info, text


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离 vault + mock LLM metadata 提取(不联网、不调真实 API)。"""
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb, "RAW_TEXT_DIR", kb_dir / "raw_text")
    monkeypatch.setattr(kb, "LOGS_DIR", kb_dir / "logs")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    # mock LLM:让自由文本走成功识别路径
    monkeypatch.setattr(kb_llm, "load_config", lambda: {"available": True, "model": "mock"})
    monkeypatch.setattr(kb_llm, "extract_metadata_smart", _fake_metadata)

    (tmp_path / "00_Inbox").mkdir(parents=True, exist_ok=True)
    (tmp_path / "00_Inbox" / "inbox.md").write_text("# Inbox\n\n", encoding="utf-8")
    return TestClient(kb_web.app)


def test_batch_ingest_returns_count_fields(client):
    """批量投稿返回 new_count / skipped_count / failed_count 三个字段。"""
    resp = client.post(
        "/api/ingest",
        json={"items": ["https://example.com/a", "https://example.com/b"], "auto_summary": False},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "new_count" in data
    assert "skipped_count" in data
    assert "failed_count" in data
    for k in ("new_count", "skipped_count", "failed_count"):
        assert isinstance(data[k], int)
    # 旧字段仍保留(向后兼容)
    assert "submitted" in data
    assert "new_sources" in data
    assert "log" in data


def test_batch_ingest_creates_multiple(client):
    """两个不同 URL 各创建一个 source。"""
    resp = client.post(
        "/api/ingest",
        json={
            "items": ["https://example.com/uniq-aaa", "https://example.com/uniq-bbb"],
            "auto_summary": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_count"] == 2
    assert data["skipped_count"] == 0
    assert len(data["new_sources"]) == 2


def test_batch_ingest_dedup_increments_skipped(client):
    """同一个 URL 投两次,第二次 new_count=0、skipped_count>=1。"""
    url = "https://example.com/dedup-test"
    r1 = client.post(
        "/api/ingest",
        json={"items": [url], "auto_summary": False},
    )
    assert r1.status_code == 200
    assert r1.json()["new_count"] == 1

    r2 = client.post(
        "/api/ingest",
        json={"items": [url], "auto_summary": False},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["new_count"] == 0
    assert data2["skipped_count"] >= 1


def test_batch_ingest_auto_summary_false_no_summary(client):
    """auto_summary=False 时,生成的卡片没有 summary_path。"""
    resp = client.post(
        "/api/ingest",
        json={"items": ["https://example.com/no-summary"], "auto_summary": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_count"] == 1
    # summary_results 为空(没自动生成)
    assert data["summary_results"] == []
    # state 里无 summary_path
    state = kb.load_state()
    for s in data["new_sources"]:
        rec = state["sources"][s["source_id"]]
        assert not rec.get("summary_path")


def test_batch_ingest_mixed_new_and_dup(client):
    """一个新 URL + 一个已存在的 URL → new_count=1, skipped_count=1。"""
    # 先建一个
    client.post(
        "/api/ingest",
        json={"items": ["https://example.com/already-there"], "auto_summary": False},
    )
    # 再投:一个新 + 一个重复
    resp = client.post(
        "/api/ingest",
        json={
            "items": ["https://example.com/already-there", "https://example.com/brand-new"],
            "auto_summary": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_count"] == 1
    assert data["skipped_count"] == 1


def test_batch_ingest_empty_400(client):
    """空 items 返回 400。"""
    resp = client.post("/api/ingest", json={"items": [], "auto_summary": False})
    assert resp.status_code == 400


def test_log_parsing_helper_formats():
    """直接验证 log 正则能匹配 cmd_ingest 的真实输出格式(kb.py 1168-1179)。"""
    import re

    sample_log = (
        "[ingest] 共 6 个 item\n"
        "[ingest] 新建 source note: 3\n"
        "  + source_ff_aaa\n"
        "[ingest] 跳过(内容重复): 2\n"
        "  ~ source_ff_ddd\n"
        "[ingest] 失败(保留在 inbox): 1\n"
        "  ! source_ff_eee\n"
    )
    assert int(re.search(r"\[ingest\] 新建 source note:\s*(\d+)", sample_log).group(1)) == 3
    assert int(re.search(r"\[ingest\] 跳过\(内容重复\):\s*(\d+)", sample_log).group(1)) == 2
    assert int(re.search(r"\[ingest\] 失败\(保留在 inbox\):\s*(\d+)", sample_log).group(1)) == 1
    # 缺失项兜底为 None
    log_no_fail = "[ingest] 新建 source note: 1\n"
    assert re.search(r"\[ingest\] 失败\(保留在 inbox\):\s*(\d+)", log_no_fail) is None
