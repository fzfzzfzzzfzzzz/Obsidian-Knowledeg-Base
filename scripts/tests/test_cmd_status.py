"""cmd_status 命令(v0.4.6)—— 输出字段验证。

参考 test_ingest.py 范式:直接调 kb.cmd_status(args),检查返回值。
"""
import argparse
import io
import contextlib

import kb


def test_cmd_status_empty_vault(isolate_vault):
    """空 vault 不崩,返回 0。"""
    tmp_path = isolate_vault
    # 不预置任何文件
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kb.cmd_status(argparse.Namespace(verbose=False))
    assert rc == 0


def test_cmd_status_outputs_expected_fields(isolate_vault):
    """输出含关键统计字段。"""
    tmp_path = isolate_vault
    # 建一个最小 state(1 个 source)
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text(
        '{"version": 1, "sources": {"sid1": {"source_type": "x", "path": "01_Sources/x/sid1.md"}}}',
        encoding="utf-8",
    )
    # 建一个 inbox
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True)
    (inbox / "inbox.md").write_text("# Inbox\n\n> 说明\n\n待处理内容\n", encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kb.cmd_status(argparse.Namespace(verbose=False))
    assert rc == 0
    output = buf.getvalue()
    # 关键字段
    assert "Sources created" in output
    assert "Pending inbox" in output or "inbox items" in output.lower()
    assert "Summaries generated" in output


def test_cmd_status_verbose_mode(isolate_vault):
    """--verbose 不崩(可能输出按 source_type 分组)。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text(
        '{"version": 1, "sources": {"sid1": {"source_type": "x"}}}',
        encoding="utf-8",
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kb.cmd_status(argparse.Namespace(verbose=True))
    assert rc == 0


def test_cmd_status_counts_sources(isolate_vault):
    """source 数量统计正确。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text(
        '{"version": 1, "sources": {"a": {}, "b": {}, "c": {}}}',
        encoding="utf-8",
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        kb.cmd_status(argparse.Namespace(verbose=False))
    output = buf.getvalue()
    assert "3" in output  # 3 个 source
