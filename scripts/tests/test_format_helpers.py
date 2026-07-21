"""format helper 纯函数 —— 把 suggestion 块转成正式清单格式。

范式参考 test_suggestions.py:不碰磁盘,字面量输入 + 子串断言。
"""
import kb


# —— _format_formal_idea ——

def test_format_formal_idea_required_fields():
    meta = {
        "title": "测试想法",
        "priority": "P1",
        "feasibility": "high",
        "novelty": "medium",
        "estimated_investment": "3d",
        "source_summary": "02_Summaries/x/summary_xx.md",
    }
    out = kb._format_formal_idea(meta, "正文内容", "research")
    assert "## Idea: 测试想法" in out
    assert "status: candidate" in out
    assert "maturity: spark" in out
    assert "priority: P1" in out
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
    assert "priority: P2" in out  # 默认 priority


# —— _format_weekly_task ——

def test_format_weekly_task_uses_metadata():
    meta = {
        "title": "周任务",
        "estimated_time": "2-4h",
        "difficulty": "medium",
        "source_summary": "02_Summaries/x/summary_xx.md",
    }
    out = kb._format_weekly_task(meta, "正文")
    assert "- [ ] 周任务" in out
    assert "2-4h" in out
    assert "medium" in out
    assert "02_Summaries/x/summary_xx.md" in out


def test_format_weekly_task_handles_missing_meta():
    out = kb._format_weekly_task({}, "")
    assert "- [ ]" in out


# —— _format_todo_suggestion ——

def test_format_todo_suggestion_empty_estimated_time():
    """LLM 没给 estimated_time 时,格式化输出应留空,不伪造 "2-4h"(v0.4.7, ROADMAP P1-#6)。

    修复前:kb.py 用 it.get('estimated_time', '2-4h') 兜底,
    和 kb_llm.py 的 or "2-4h" 一样会伪造数据。
    """
    it = {
        "title": "测试 todo",
        "recommended_plan": "weekly",
        "priority": "P1",
        "difficulty": "low",
        # 故意不传 estimated_time
    }
    out = kb._format_todo_suggestion("src_20260101_x", {"source_type": "web"}, it, "2026-07-21")
    # estimated_time 行存在但值为空
    assert "- estimated_time:" in out
    # 关键:不应出现伪造的 "2-4h"
    assert "2-4h" not in out


def test_todo_suggestion_preserves_provided_estimated_time():
    """LLM 给了 estimated_time 时正常写入(对照测试,确认修复没误伤合法值)。"""
    it = {
        "title": "测试 todo",
        "recommended_plan": "weekly",
        "priority": "P1",
        "estimated_time": "30min",
        "difficulty": "low",
    }
    out = kb._format_todo_suggestion("src_20260101_x", {"source_type": "web"}, it, "2026-07-21")
    assert "- estimated_time: 30min" in out


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
