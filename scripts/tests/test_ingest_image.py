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


def test_ingest_image_rejects_forged_content_type(client):
    """content_type 伪造(magic bytes 不匹配)应被拒。

    防御:攻击者把 .exe 改名 + content_type=image/png 上传。
    """
    c, tmp = client
    # 声称是 png,但内容是纯文本
    r = c.post(
        "/api/ingest-image",
        files={"file": ("fake.png", b"not really an image", "image/png")},
    )
    assert r.status_code == 400


def test_ingest_image_rejects_oversized(client):
    """超过 10MB 的图片应被拒(对齐前端)。"""
    c, tmp = client
    # 构造 > 10MB 的"图片"(用 PNG 头 + 大量填充)
    big_png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * (11 * 1024 * 1024)
    r = c.post(
        "/api/ingest-image",
        files={"file": ("big.png", big_png, "image/png")},
    )
    assert r.status_code == 400
    assert "10MB" in r.json().get("detail", "") or "超过" in r.json().get("detail", "")


def test_ingest_image_accepts_webp_magic(client):
    """WebP 通过 magic bytes 校验(对齐前端 ACCEPTED_TYPES)。"""
    c, tmp = client
    # 真正的 WebP magic(OCR 仍会失败,但类型校验应通过)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20
    r = c.post(
        "/api/ingest-image",
        files={"file": ("test.webp", webp, "image/webp")},
    )
    # OCR 会失败(因为不是真图片),但不应是 400 类型错误
    # 应该是 500(OCR 失败)或 200(OCR 返回空)
    assert r.status_code != 400 or "magic" not in r.json().get("detail", "")
