"""format helper 纯函数 —— 把 suggestion 块转成正式清单格式。

范式参考 test_suggestions.py:不碰磁盘,字面量输入 + 子串断言。
"""
import kb


# —— _format_formal_idea ——

def test_format_formal_idea_required_fields():
    # v0.4.13: 正式 idea 简化为只写 title + status + maturity + source
    meta = {
        "title": "测试想法",
        "source_summary": "02_Summaries/x/summary_xx.md",
    }
    out = kb._format_formal_idea(meta, "正文内容", "research")
    assert "## Idea: 测试想法" in out
    assert "status: candidate" in out
    assert "maturity: spark" in out
    assert "02_Summaries/x/summary_xx.md" in out
    assert "正文内容" in out


def test_format_formal_idea_id_format():
    """id 应包含日期 + slug。"""
    meta = {"title": "我的想法", "source_summary": "x.md"}
    out = kb._format_formal_idea(meta, "body", "research")
    # 应有 - id: idea_YYYYMMDD_xxx
    import re
    m = re.search(r"- id: (idea_\d{8}_\S+)", out)
    assert m, f"id 格式不对: {out}"


def test_format_formal_idea_fallbacks_when_missing():
    """meta 缺字段时用合理默认值,不应抛错。"""
    out = kb._format_formal_idea({}, "", "research")
    assert "## Idea:" in out  # 标题用默认


# —— _format_weekly_task ——

def test_format_weekly_task_uses_metadata():
    # v0.4.13: weekly task 简化为只写 title + 来源 + 截止日期(若有)
    meta = {
        "title": "周任务",
        "source_summary": "02_Summaries/x/summary_xx.md",
    }
    out = kb._format_weekly_task(meta, "正文")
    assert "- [ ] 周任务" in out
    assert "02_Summaries/x/summary_xx.md" in out


def test_format_weekly_task_handles_missing_meta():
    out = kb._format_weekly_task({}, "")
    assert "- [ ]" in out


# —— _format_todo_suggestion ——

def test_format_todo_suggestion_empty_estimated_time():
    """v0.4.13: todo suggestion 简化为只写 title + id + status + source,
    不再有 estimated_time 字段。验证精简格式 + 无伪造默认值。
    """
    it = {"title": "测试 todo"}
    out = kb._format_todo_suggestion("src_20260101_x", {"source_type": "web"}, it, "2026-07-21")
    assert "## Todo Suggestion: 测试 todo" in out
    assert "status: pending_review" in out
    # v0.4.13: 不再有 estimated_time / priority / difficulty 字段
    assert "estimated_time" not in out
    assert "priority" not in out
    assert "difficulty" not in out


def test_todo_suggestion_preserves_provided_estimated_time():
    """v0.4.13: 即使旧数据 it 带了 estimated_time,精简格式也忽略它(只写 title)。
    保留测试名以维持回归覆盖,断言更新为验证精简行为。
    """
    it = {
        "title": "测试 todo",
        "estimated_time": "30min",  # 旧字段,精简后应被忽略
    }
    out = kb._format_todo_suggestion("src_20260101_x", {"source_type": "web"}, it, "2026-07-21")
    assert "## Todo Suggestion: 测试 todo" in out
    # 精简格式不输出 estimated_time
    assert "estimated_time" not in out


# —— _replace_status_in_block ——

def test_replace_status_in_block_basic():
    block = "## Idea Suggestion: X\n\n- id: i1\n- status: pending_review\n\nbody\n"
    out = kb._replace_status_in_block(block, "pending_review", "accepted_research")
    assert "status: accepted_research" in out
    assert "status: pending_review" not in out
    # 其他内容保留
    assert "## Idea Suggestion: X" in out
    assert "body" in out


def test_replace_status_in_block_only_matches_status_line():
    """正则只匹配 status 行,body 里的 'pending_review' 字样不应被替换。"""
    block = (
        "## Idea Suggestion: X\n\n"
        "- id: i1\n"
        "- status: pending_review\n\n"
        "正文提到 pending_review 不应被改\n"
    )
    out = kb._replace_status_in_block(block, "pending_review", "moved")
    # body 里的 pending_review 应保留
    assert "正文提到 pending_review 不应被改" in out
    # status 行应被替换
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("- status:")]
    assert len(lines) == 1
    assert lines[0].strip() == "- status: moved"


def test_replace_status_in_block_no_match_returns_unchanged():
    """old_status 在块里不存在时,块原样返回。"""
    block = "## X\n\n- status: pending_review\n"
    out = kb._replace_status_in_block(block, "accepted_research", "moved")
    assert out == block


# —— _append_section ——

def test_append_section_creates_parent(tmp_path):
    """_append_section 应自动创建父目录。"""
    target = tmp_path / "deep" / "nested" / "file.md"
    kb._append_section(target, "## Section\n\ncontent\n")
    assert target.exists()
    assert "## Section" in target.read_text(encoding="utf-8")


def test_append_section_appends_not_overwrites(tmp_path):
    target = tmp_path / "file.md"
    target.write_text("# Original\n\n原有内容\n", encoding="utf-8")
    kb._append_section(target, "## New\n\n新内容\n")
    text = target.read_text(encoding="utf-8")
    assert "原有内容" in text
    assert "新内容" in text
