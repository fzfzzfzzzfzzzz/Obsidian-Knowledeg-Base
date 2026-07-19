"""accept-ideas / accept-todos 命令 —— 高风险改写正式清单的操作。

范式参考 test_ingest.py:用 isolate_vault 隔离真实 vault,直接调 kb.cmd_*(args)。
"""
import argparse

import kb


# —— 测试夹具:构造最小 review 队列文件 ——

_IDEA_SUG_HEADER = """# Idea Suggestions (Review Queue)

> 说明

"""

_TODO_SUG_HEADER = """# Todo Suggestions (Review Queue)

> 说明

"""


def _write_idea_suggestions(tmp_path, blocks_text):
    sug = tmp_path / "03_Ideas" / "idea_suggestions.md"
    sug.parent.mkdir(parents=True, exist_ok=True)
    sug.write_text(_IDEA_SUG_HEADER + blocks_text, encoding="utf-8")


def _write_todo_suggestions(tmp_path, blocks_text):
    sug = tmp_path / "04_Plans" / "todo_suggestions.md"
    sug.parent.mkdir(parents=True, exist_ok=True)
    sug.write_text(_TODO_SUG_HEADER + blocks_text, encoding="utf-8")


_IDEA_ACCEPTED = """## Idea Suggestion: 测试想法A

- id: idea_test_1
- status: accepted_research
- recommended_area: research
- priority: P1
- feasibility: high
- novelty: medium
- estimated_investment: 3d
- source_summary: 02_Summaries/x/summary_xxx.md

这是一个测试想法。
"""

_IDEA_PENDING = """## Idea Suggestion: 待定想法B

- id: idea_test_2
- status: pending_review
- recommended_area: productivity

待定。
"""


# —— accept-ideas ——

def test_accept_ideas_moves_accepted_block(isolate_vault):
    tmp_path = isolate_vault
    _write_idea_suggestions(tmp_path, _IDEA_ACCEPTED + _IDEA_PENDING)
    args = argparse.Namespace()
    assert kb.cmd_accept_ideas(args) == 0

    # 正式 research_ideas.md 应被创建并包含标题
    research = tmp_path / "03_Ideas" / "research_ideas.md"
    assert research.exists()
    rtext = research.read_text(encoding="utf-8")
    assert "测试想法A" in rtext
    assert "## Idea: 测试想法A" in rtext

    # 原 suggestion 文件里 accepted 块的 status 应变成 moved
    sug = (tmp_path / "03_Ideas" / "idea_suggestions.md").read_text(encoding="utf-8")
    assert "status: moved" in sug
    # pending 块不应被动
    assert "status: pending_review" in sug
    # productivity 文件不应被创建(没有 accepted_productivity 块)
    assert not (tmp_path / "03_Ideas" / "productivity_ideas.md").exists()


def test_accept_ideas_skips_all_pending(isolate_vault):
    tmp_path = isolate_vault
    _write_idea_suggestions(tmp_path, _IDEA_PENDING)
    rc = kb.cmd_accept_ideas(argparse.Namespace())
    assert rc == 0
    # 没有任何 accepted_*,不应创建正式文件
    assert not (tmp_path / "03_Ideas" / "research_ideas.md").exists()
    assert not (tmp_path / "03_Ideas" / "productivity_ideas.md").exists()


def test_accept_ideas_no_file_returns_1(isolate_vault):
    """idea_suggestions.md 不存在时返回 1(明确错误,而非静默成功)。"""
    rc = kb.cmd_accept_ideas(argparse.Namespace())
    assert rc == 1


def test_accept_ideas_productivity_area(isolate_vault):
    tmp_path = isolate_vault
    block = _IDEA_ACCEPTED.replace("accepted_research", "accepted_productivity")
    _write_idea_suggestions(tmp_path, block)
    assert kb.cmd_accept_ideas(argparse.Namespace()) == 0
    prod = tmp_path / "03_Ideas" / "productivity_ideas.md"
    assert prod.exists()
    assert "测试想法A" in prod.read_text(encoding="utf-8")


# —— accept-todos ——

_TODO_WEEKLY = """## Todo Suggestion: 周任务A

- id: todo_test_1
- status: accepted_weekly
- estimated_time: 2-4h
- difficulty: medium
- source_summary: 02_Summaries/x/summary_xxx.md

这是一个周任务。
"""

_TODO_MONTHLY = """## Todo Suggestion: 月任务B

- id: todo_test_2
- status: accepted_monthly
- estimated_time: 1d
- difficulty: hard
- source_summary: 02_Summaries/x/summary_xxx.md

月任务内容。
"""

_TODO_SOMEDAY = """## Todo Suggestion: 待办C

- id: todo_test_3
- status: accepted_someday
- source_summary: 02_Summaries/x/summary_xxx.md

暂存待办。
"""


def test_accept_todos_weekly(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_suggestions(tmp_path, _TODO_WEEKLY)
    assert kb.cmd_accept_todos(argparse.Namespace()) == 0
    # weekly 文件应自动创建在 04_Plans/Weekly/<week_tag>.md
    weekly_dir = tmp_path / "04_Plans" / "Weekly"
    assert weekly_dir.exists()
    weekly_files = list(weekly_dir.glob("*.md"))
    assert len(weekly_files) == 1
    wtext = weekly_files[0].read_text(encoding="utf-8")
    assert "周任务A" in wtext
    assert "[ ]" in wtext  # 任务格式


def test_accept_todos_monthly(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_suggestions(tmp_path, _TODO_MONTHLY)
    assert kb.cmd_accept_todos(argparse.Namespace()) == 0
    monthly_dir = tmp_path / "04_Plans" / "Monthly"
    assert monthly_dir.exists()
    monthly_files = list(monthly_dir.glob("*.md"))
    assert len(monthly_files) == 1
    assert "月任务B" in monthly_files[0].read_text(encoding="utf-8")


def test_accept_todos_someday(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_suggestions(tmp_path, _TODO_SOMEDAY)
    assert kb.cmd_accept_todos(argparse.Namespace()) == 0
    someday = tmp_path / "04_Plans" / "someday.md"
    assert someday.exists()
    assert "待办C" in someday.read_text(encoding="utf-8")


def test_accept_todos_marks_original_as_moved(isolate_vault):
    tmp_path = isolate_vault
    _write_todo_suggestions(tmp_path, _TODO_WEEKLY)
    kb.cmd_accept_todos(argparse.Namespace())
    sug = (tmp_path / "04_Plans" / "todo_suggestions.md").read_text(encoding="utf-8")
    assert "status: moved" in sug
    assert "status: accepted_weekly" not in sug


def test_accept_todos_no_file_returns_1(isolate_vault):
    rc = kb.cmd_accept_todos(argparse.Namespace())
    assert rc == 1


def test_accept_todos_idempotent_on_second_run(isolate_vault):
    """第二次跑应无 accepted 块可搬,跳过,返回 0,不创建新文件。"""
    tmp_path = isolate_vault
    _write_todo_suggestions(tmp_path, _TODO_WEEKLY)
    assert kb.cmd_accept_todos(argparse.Namespace()) == 0
    weekly_dir = tmp_path / "04_Plans" / "Weekly"
    n_after_first = len(list(weekly_dir.glob("*.md")))
    # 第二次跑:全部已 moved,无 accepted_*
    assert kb.cmd_accept_todos(argparse.Namespace()) == 0
    n_after_second = len(list(weekly_dir.glob("*.md")))
    assert n_after_first == n_after_second
