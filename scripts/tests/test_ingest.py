"""ingest 集成层 + append_to_inbox 不覆盖 —— 用 isolate_vault 隔离真实 vault。"""
import argparse

import kb


def _setup_inbox(tmp_path, body: str):
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "inbox.md").write_text(
        "# Inbox\n\n> 说明\n\n" + body, encoding="utf-8"
    )


def test_ingest_idempotent(isolate_vault):
    tmp_path = isolate_vault
    block = (
        "<!-- KB_ITEM_START -->\n"
        "source_type: web\n"
        "source_title: T\n\n"
        "body内容\n"
        "<!-- KB_ITEM_END -->\n"
    )
    _setup_inbox(tmp_path, block)
    args = argparse.Namespace(no_llm=True)
    assert kb.cmd_ingest(args) == 0
    assert len(kb.load_state()["sources"]) == 1

    # 用户重新粘贴相同内容再 ingest -> 应跳过,source 数量不变
    _setup_inbox(tmp_path, block)
    assert kb.cmd_ingest(args) == 0
    assert len(kb.load_state()["sources"]) == 1


def test_ingest_moves_to_processed(isolate_vault):
    tmp_path = isolate_vault
    block = (
        "<!-- KB_ITEM_START -->\n"
        "source_type: web\n"
        "source_title: T\n\n"
        "body内容\n"
        "<!-- KB_ITEM_END -->\n"
    )
    _setup_inbox(tmp_path, block)
    assert kb.cmd_ingest(argparse.Namespace(no_llm=True)) == 0

    remaining = (tmp_path / "00_Inbox" / "inbox.md").read_text(encoding="utf-8")
    # 实际正文内容已被移走(标准头部里出现的 KB_ITEM_START 仅是示例,不计)
    assert "body内容" not in remaining

    processed = (tmp_path / "00_Inbox" / "processed.md").read_text(encoding="utf-8")
    assert "body内容" in processed


def test_append_to_inbox_preserves_existing(isolate_vault):
    tmp_path = isolate_vault
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    # 用户已在 inbox 中贴了未处理内容
    (inbox / "inbox.md").write_text(
        "# Inbox\n\n> 说明\n\n用户已有的重要笔记\n", encoding="utf-8"
    )
    kb.append_to_inbox(["新的投稿内容"])
    text = (inbox / "inbox.md").read_text(encoding="utf-8")
    assert "用户已有的重要笔记" in text
    assert "新的投稿内容" in text


def test_append_to_inbox_empty_noop(isolate_vault):
    tmp_path = isolate_vault
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    original = "# Inbox\n\n> 说明\n\n已有内容\n"
    (inbox / "inbox.md").write_text(original, encoding="utf-8")
    kb.append_to_inbox(["", "   "])
    assert (inbox / "inbox.md").read_text(encoding="utf-8") == original
