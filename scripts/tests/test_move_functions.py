"""move_accepted_idea / move_accepted_todo 纯函数 —— Web 自动搬运的核心。

这些函数也被 CLI cmd_accept_* 调用,行为通过 test_accept_commands.py 覆盖;
本文件聚焦单条 move 的边界(幂等、找不到、状态不符)。
"""
import kb


_IDEA_HEADER = """# Idea Suggestions (Review Queue)

> 说明

"""

_TODO_HEADER = """# Todo Suggestions (Review Queue)

> 说明

"""


def _write_idea_sug(tmp_path, blocks_text):
    sug = tmp_path / "03_Ideas" / "idea_suggestions.md"
    sug.parent.mkdir(parents=True, exist_ok=True)
    sug.write_text(_IDEA_HEADER + blocks_text, encoding="utf-8")


def _write_todo_sug(tmp_path, blocks_text):
    sug = tmp_path / "04_Plans" / "todo_suggestions.md"
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


# —— move_accepted_todo ——

def test_move_todo_weekly(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_sug(tmp_path, """## Todo Suggestion: 周任务

- id: todo_w1
- status: accepted_weekly
- estimated_time: 2h
- source_summary: x.md

正文
""")
    result = kb.move_accepted_todo("todo_w1")
    assert result["moved"] is True
    assert result["plan"] == "weekly"
    assert "Weekly" in result["target"]
    weekly_files = list((tmp_path / "04_Plans" / "Weekly").glob("*.md"))
    assert len(weekly_files) == 1
    assert "周任务" in weekly_files[0].read_text(encoding="utf-8")


def test_move_todo_monthly(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_sug(tmp_path, """## Todo Suggestion: 月任务

- id: todo_m1
- status: accepted_monthly
- source_summary: x.md

正文
""")
    result = kb.move_accepted_todo("todo_m1")
    assert result["moved"] is True
    assert result["plan"] == "monthly"


def test_move_todo_someday(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_sug(tmp_path, """## Todo Suggestion: 待办

- id: todo_s1
- status: accepted_someday
- source_summary: x.md

正文
""")
    result = kb.move_accepted_todo("todo_s1")
    assert result["moved"] is True
    assert result["plan"] == "someday"
    assert "someday.md" in result["target"]


def test_move_todo_already_moved(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_sug(tmp_path, """## Todo Suggestion: 已搬

- id: todo_mv1
- status: moved
- source_summary: x.md

正文
""")
    result = kb.move_accepted_todo("todo_mv1")
    assert result["moved"] is False


def test_move_todo_idempotent_double_call(isolate_vault):
    """调两次:第二次应 no-op(因为已 moved)。"""
    tmp_path = isolate_vault
    _write_todo_sug(tmp_path, """## Todo Suggestion: 周任务

- id: todo_idem1
- status: accepted_weekly
- source_summary: x.md

正文
""")
    r1 = kb.move_accepted_todo("todo_idem1")
    assert r1["moved"] is True
    r2 = kb.move_accepted_todo("todo_idem1")
    assert r2["moved"] is False
    # weekly 文件不应被写两次
    weekly_files = list((tmp_path / "04_Plans" / "Weekly").glob("*.md"))
    assert len(weekly_files) == 1
    # 内容里 "周任务" 只应出现一次(在 task 标题里)
    content = weekly_files[0].read_text(encoding="utf-8")
    assert content.count("[ ] 周任务") == 1
