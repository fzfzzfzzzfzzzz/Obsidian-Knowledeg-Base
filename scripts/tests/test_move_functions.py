"""move_accepted_idea / move_accepted_plan 纯函数 —— Web 自动搬运的核心。

这些函数也被 CLI cmd_accept_* 调用,行为通过 test_accept_commands.py 覆盖;
本文件聚焦单条 move 的边界(幂等、找不到、状态不符)。
"""
import kb

_IDEA_HEADER = """# Idea Suggestions (Review Queue)

> 说明

"""

_TODO_HEADER = """# Plan Suggestions (Review Queue)

> 说明

"""

def _write_idea_sug(tmp_path, blocks_text):
    sug = tmp_path / "03_Ideas" / "idea_suggestions.md"
    sug.parent.mkdir(parents=True, exist_ok=True)
    sug.write_text(_IDEA_HEADER + blocks_text, encoding="utf-8")

def _write_todo_sug(tmp_path, blocks_text):
    sug = tmp_path / "04_Plans" / "plan_suggestions.md"
    sug.parent.mkdir(parents=True, exist_ok=True)
    sug.write_text(_TODO_HEADER + blocks_text, encoding="utf-8")

# —— move_accepted_idea ——

def test_move_idea_single_accepted(isolate_vault):
    tmp_path = isolate_vault
    _write_idea_sug(tmp_path, """## Idea Suggestion: 标题X

- id: idea_move1
- status: accepted_research
- priority: P1
- source_summary: x.md

正文
""")
    result = kb.move_accepted_idea("idea_move1")
    assert result["moved"] is True
    assert result["area"] == "research"
    assert "research_ideas.md" in result["target"]
    # 正式文件存在并包含内容
    assert "标题X" in (tmp_path / "03_Ideas" / "research_ideas.md").read_text(encoding="utf-8")
    # 原 suggestion 标 moved
    sug = (tmp_path / "03_Ideas" / "idea_suggestions.md").read_text(encoding="utf-8")
    assert "status: moved" in sug

def test_move_idea_already_moved_is_noop(isolate_vault):
    """幂等:已是 moved 状态的不重复搬。"""
    tmp_path = isolate_vault
    _write_idea_sug(tmp_path, """## Idea Suggestion: 标题Y

- id: idea_moved1
- status: moved
- source_summary: x.md

正文
""")
    result = kb.move_accepted_idea("idea_moved1")
    assert result["moved"] is False
    assert "not_found_or_not_accepted" in result.get("reason", "")
    # 正式文件不应被创建
    assert not (tmp_path / "03_Ideas" / "research_ideas.md").exists()
    assert not (tmp_path / "03_Ideas" / "productivity_ideas.md").exists()

def test_move_idea_pending_is_noop(isolate_vault):
    """pending_review 状态不应触发搬运。"""
    tmp_path = isolate_vault
    _write_idea_sug(tmp_path, """## Idea Suggestion: 标题Z

- id: idea_pending1
- status: pending_review
- source_summary: x.md

正文
""")
    result = kb.move_accepted_idea("idea_pending1")
    assert result["moved"] is False

def test_move_idea_not_found(isolate_vault):
    """id 在 review 队列里不存在 → moved=False。"""
    tmp_path = isolate_vault
    _write_idea_sug(tmp_path, """## Idea Suggestion: 标题

- id: idea_exists
- status: accepted_research

正文
""")
    result = kb.move_accepted_idea("idea_does_not_exist")
    assert result["moved"] is False

def test_move_idea_no_suggestion_file(isolate_vault):
    """suggestion 文件不存在时优雅返回 moved=False。"""
    result = kb.move_accepted_idea("any_id")
    assert result["moved"] is False

def test_move_idea_productivity_area(isolate_vault):
    tmp_path = isolate_vault
    _write_idea_sug(tmp_path, """## Idea Suggestion: 标题P

- id: idea_prod1
- status: accepted_productivity
- source_summary: x.md

正文
""")
    result = kb.move_accepted_idea("idea_prod1")
    assert result["moved"] is True
    assert result["area"] == "productivity"
    assert "productivity_ideas.md" in result["target"]

# —— move_accepted_plan ——

