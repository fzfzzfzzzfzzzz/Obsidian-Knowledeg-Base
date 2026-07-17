"""inbox 解析 / 幂等 / slug / source note 生成 —— 纯函数层。"""
import kb


def test_parse_kb_item_block():
    text = (
        "<!-- KB_ITEM_START -->\n"
        "source_type: github\n"
        "source_title: My Repo\n"
        "area: ai_agent\n\n"
        "这是正文内容。\n"
        "<!-- KB_ITEM_END -->\n"
    )
    items = kb.parse_inbox_items(text)
    assert len(items) == 1
    meta = items[0]["meta"]
    assert meta["source_type"] == "github"
    assert meta["source_title"] == "My Repo"
    assert meta["area"] == "ai_agent"
    assert items[0]["body"] == "这是正文内容。"
    # raw 应保留完整块,便于从 inbox 中移除
    assert "<!-- KB_ITEM_START -->" in items[0]["raw"]
    assert "<!-- KB_ITEM_END -->" in items[0]["raw"]


def test_parse_kb_item_multiple_blocks():
    text = (
        "<!-- KB_ITEM_START -->\nsource_type: web\n\nA\n<!-- KB_ITEM_END -->\n"
        "<!-- KB_ITEM_START -->\nsource_type: manual\n\nB\n<!-- KB_ITEM_END -->\n"
    )
    items = kb.parse_inbox_items(text)
    assert len(items) == 2
    assert items[0]["body"] == "A"
    assert items[1]["body"] == "B"


def test_parse_kb_item_ignores_unknown_meta():
    text = (
        "<!-- KB_ITEM_START -->\n"
        "foo: bar\n"
        "source_type: web\n\n"
        "body\n"
        "<!-- KB_ITEM_END -->\n"
    )
    items = kb.parse_inbox_items(text)
    assert "foo" not in items[0]["meta"]
    assert items[0]["meta"]["source_type"] == "web"


def test_freeform_hr_split():
    text = "> 头部说明\n\n第一条\n\n---\n\n第二条\n"
    items = kb.parse_freeform_items(text)
    assert len(items) == 2
    assert items[0]["body"] == "第一条"
    assert items[1]["body"] == "第二条"


def test_freeform_no_hr_single():
    assert len(kb.parse_freeform_items("只有一段内容")) == 1


def test_freeform_strips_header():
    text = "# Inbox\n> 提示\n\n真正内容\n"
    items = kb.parse_freeform_items(text)
    assert items[0]["body"] == "真正内容"


def test_has_markers_false_for_freeform():
    assert kb.has_kb_item_markers("随便贴点东西\n---\n再贴点") is False


def test_has_markers_true_for_block():
    assert kb.has_kb_item_markers(
        "x\n<!-- KB_ITEM_START -->\ny\n<!-- KB_ITEM_END -->"
    ) is True


def test_source_id_idempotent():
    assert kb.make_source_id("abc") == kb.make_source_id("abc")
    assert kb.make_source_id("abc") != kb.make_source_id("abcd")
    assert kb.make_source_id("abc").startswith("source_ff_")


def test_make_slug_basic():
    assert kb.make_slug("Hello World!") == "hello_world"
    assert kb.make_slug("中文 标题") == "中文_标题"
    assert len(kb.make_slug("x" * 100, 10)) <= 10


def test_build_source_note_frontmatter():
    note = kb.build_source_note(
        "source_ff_12345678",
        {"source_type": "github", "source_title": "T"},
        "body",
    )
    assert "id: source_ff_12345678" in note
    assert "content_hash: 12345678" in note
    assert "kind: source" in note
