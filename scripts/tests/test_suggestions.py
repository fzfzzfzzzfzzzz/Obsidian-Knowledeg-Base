"""suggestion 候选流 —— 纯函数层(切块 / 格式化 / status 替换)。"""
import kb


def _sample_sug_file():
    return """# Idea Suggestions (Review Queue)

> 说明

## Idea Suggestion: 标题A

- id: idea_1
- status: pending_review
- recommended_area: research

正文A 内容

## Idea Suggestion: 标题B

- id: idea_2
- status: accepted_research

正文B 内容
"""


def test_split_suggestion_blocks():
    blocks = kb._split_suggestion_blocks(_sample_sug_file(), "Idea Suggestion")
    assert len(blocks) == 2
    titles = [b[1]["title"] for b in blocks]
    assert "标题A" in titles and "标题B" in titles
    assert "正文A 内容" in blocks[0][2]
    assert blocks[0][1]["status"] == "pending_review"


def test_split_nested_h2_regression():
    # 回归:body 里出现 "## 子标题" 时,切块前瞻不应提前截断
    text = (
        "## Idea Suggestion: 标题A\n\n"
        "- id: idea_1\n- status: pending_review\n\n"
        "开头\n\n## 子标题\n\n结尾\n\n"
        "## Idea Suggestion: 标题B\n\n"
        "- id: idea_2\n- status: pending_review\n\n正文B\n"
    )
    blocks = kb._split_suggestion_blocks(text, "Idea Suggestion")
    assert len(blocks) == 2
    assert "结尾" in blocks[0][2]


def test_split_ignores_other_kind_header():
    # 切 Idea 块时,body 里的 "## Todo Suggestion:" 不应作为 Idea 块边界
    text = (
        "## Idea Suggestion: A\n\n正文\n\n"
        "## Todo Suggestion: B\n\n其它\n\n"
        "## Idea Suggestion: C\n\n收尾\n"
    )
    blocks = kb._split_suggestion_blocks(text, "Idea Suggestion")
    assert len(blocks) == 2
    assert "## Todo Suggestion: B" in blocks[0][2]


def test_replace_status_in_block():
    block = "## Idea Suggestion: X\n\n- id: i1\n- status: pending_review\n\nbody\n"
    out = kb._replace_status_in_block(block, "pending_review", "accepted_research")
    assert "status: accepted_research" in out
    assert "status: pending_review" not in out


def test_format_idea_suggestion_fields():
    it = {
        "title": "想法",
        "recommended_area": "research",
        "priority": "P1",
        "feasibility": "high",
        "novelty": "medium",
        "estimated_investment": "3d",
        "reason": "r",
        "what": "w",
        "challenges": "c",
    }
    block = kb._format_idea_suggestion(
        "source_ff_aa", {"source_title": "T"}, it, "2026-07-15"
    )
    assert "## Idea Suggestion: 想法" in block
    assert "status: pending_review" in block
    assert "recommended_area: research" in block
