"""/api/ingest-image 回归 —— OCR 投稿不得覆盖 inbox 已有内容(v0.4.5 修复)。

修复前:ingest.py 用 write_text 覆盖整个 inbox.md,违反 Hard Rule。
修复后:改用 kb.append_to_inbox 增量追加。
"""
import kb
import kb_llm
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb, "CALENDAR_FILE", kb_dir / "calendar.json")
    monkeypatch.setattr(kb, "RAW_TEXT_DIR", kb_dir / "raw_text")
    monkeypatch.setattr(kb, "LOGS_DIR", kb_dir / "logs")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)

    # mock OCR:返回固定文字,不真调 LLM
    monkeypatch.setattr(kb_llm, "ocr_image", lambda img_b64, mime: "OCR 提取的投稿内容")
    # mock LLM 配置 + 抓取:让 ingest 自由文本路径走"LLM 不可用"分支
    monkeypatch.setattr(kb_llm, "load_config", lambda: {"available": False})

    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    # 预置用户已在 inbox 中、尚未处理的笔记
    (inbox / "inbox.md").write_text(
        "# Inbox\n\n> 说明\n\n用户已有的重要笔记\n", encoding="utf-8"
    )
    return TestClient(kb_web.app), tmp_path


def _make_png_bytes(size_kb: int = 1) -> bytes:
    """生成最小的合法 PNG(1x1 像素)。"""
    # PNG 文件头 + IHDR + IDAT + IEND(1x1 透明像素)
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000005000100ffffffa5230000000049454e44ae426082"
    )


def test_ingest_image_preserves_existing_inbox(client):
    """图片 OCR 投稿不应覆盖 inbox 已有内容。"""
    c, tmp = client
    r = c.post(
        "/api/ingest-image",
        files={"file": ("test.png", _make_png_bytes(), "image/png")},
    )
    # OCR 后走 ingest,LLM 不可用时 rc=1(自由文本无 LLM 不能 ingest)
    # 但关键是 inbox 文件不应被覆盖
    inbox_text = (tmp / "00_Inbox" / "inbox.md").read_text(encoding="utf-8")
    assert "用户已有的重要笔记" in inbox_text, "原有 inbox 内容被覆盖了!"
    assert "OCR 提取的投稿内容" in inbox_text, "OCR 内容未追加"


def test_ingest_image_rejects_unsupported_type(client):
    """非图片格式应被拒。"""
    c, tmp = client
    r = c.post(
        "/api/ingest-image",
        files={"file": ("test.txt", b"plain text", "text/plain")},
    )
    assert r.status_code in (400, 415)
    # inbox 未被动
    inbox_text = (tmp / "00_Inbox" / "inbox.md").read_text(encoding="utf-8")
    assert "用户已有的重要笔记" in inbox_text
