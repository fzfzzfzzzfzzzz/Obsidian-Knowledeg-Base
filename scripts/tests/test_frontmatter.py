"""frontmatter 解析回归 —— 验证 body 含 --- 时完整保留(不被截断)。"""
import kb


def test_parse_frontmatter_basic():
    text = "---\nid: x\nsource_type: web\n---\n\n# 结论\n\n正文\n"
    meta, body = kb.parsefrontmatter(text)
    assert meta["id"] == "x"
    assert meta["source_type"] == "web"
    assert "正文" in body


def test_parse_frontmatter_with_hr_in_body():
    # body 内出现水平分隔线 ---,应完整保留两段
    text = "---\nid: x\n---\n\n第一段\n\n---\n\n第二段\n"
    meta, body = kb.parsefrontmatter(text)
    assert meta["id"] == "x"
    assert "第一段" in body
    assert "第二段" in body
    assert "---" in body  # 分隔线未被当成 frontmatter 结束


def test_parse_frontmatter_no_frontmatter():
    text = "# 标题\n\n随便正文\n"
    meta, body = kb.parsefrontmatter(text)
    assert meta == {}
    assert body == text
