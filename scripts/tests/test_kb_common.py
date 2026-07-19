"""kb.py 公共工具抽取后的行为回归测试(v0.4.4 步骤 4)。

覆盖抽出的公共 helper,确保重构零行为变更:
- hash_from_source_id(替代散落的 replace 魔法链)
- make_note_filename(+ make_source_filename / make_summary_filename 包装等价)
- _strip_inbox_header_lines(+ _strip_inbox_header 委托)
- _count_status_in_file(替代 cmd_status 4 段重复)
- _extract_summary_body(复用 parsefrontmatter)
"""
import kb


def test_hash_from_source_id_strips_prefixes():
    assert kb.hash_from_source_id("source_ff_abc123") == "abc123"
    assert kb.hash_from_source_id("source_abc123") == "abc123"
    assert kb.hash_from_source_id("abc123") == "abc123"  # 无前缀不动


def test_make_note_filename_with_title():
    assert (
        kb.make_note_filename("source", "source_x", "2026-07-19", "My Great Title")
        == "source_20260719_my_great_title.md"
    )
    assert (
        kb.make_note_filename("summary", "source_x", "2026-07-19", "My Great Title")
        == "summary_20260719_my_great_title.md"
    )


def test_make_filename_wrappers_equivalent():
    """公开包装函数与 make_note_filename 完全等价(向后兼容)。"""
    assert kb.make_source_filename("s", "2026-07-19", "T") == kb.make_note_filename(
        "source", "s", "2026-07-19", "T"
    )
    assert kb.make_summary_filename("s", "2026-07-19", "T") == kb.make_note_filename(
        "summary", "s", "2026-07-19", "T"
    )


def test_make_note_filename_fallback_uses_hash():
    """无标题时回退到 source_id 的 hash 段。"""
    fn = kb.make_note_filename("source", "source_ff_abc123", "2026-07-19", "")
    assert fn == "source_20260719_untitled_abc123.md"


def test_strip_inbox_header_lines_removes_header_block():
    text = "# Inbox\n> 说明文字\n\n真正的 item 内容\n---\n第二个 item"
    joined = "\n".join(kb._strip_inbox_header_lines(text.splitlines()))
    assert "# Inbox" not in joined
    assert "> 说明文字" not in joined
    assert "真正的 item 内容" in joined
    assert "第二个 item" in joined


def test_strip_inbox_header_delegates():
    assert kb._strip_inbox_header("# H\n> note\n\nbody line") == "body line"


def test_count_status_in_file(tmp_path):
    p = tmp_path / "sug.md"
    p.write_text(
        "a\nstatus: pending_review\nb\nstatus: accepted_x\nstatus: pending_review\n"
    )
    assert kb._count_status_in_file(p, "pending_review") == 2
    assert kb._count_status_in_file(p, "accepted_") == 1
    # 文件不存在返回 0(不抛)
    assert kb._count_status_in_file(tmp_path / "nope.md", "pending_review") == 0


def test_extract_summary_body_reuses_parsefrontmatter():
    md = "---\nid: summary_x\nsource_id: x\n---\n# 摘要\n正文内容"
    assert kb._extract_summary_body(md) == "# 摘要\n正文内容"
    # 无 frontmatter:原样返回
    assert kb._extract_summary_body("纯文本") == "纯文本"
