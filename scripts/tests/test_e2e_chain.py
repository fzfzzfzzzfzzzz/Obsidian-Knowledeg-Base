"""端到端链路测试(v0.4.6)—— mock 全套 LLM,验证 ingest → make-prompts → accept → rebuild 完整流程。

之前所有 cmd_* 测试都是单命令隔离测,不验证跨命令的数据流一致性。
本测试用一个 tmp vault 跑完整链路,断言每步的数据正确传递。
"""
import argparse
import json

import kb
import kb_llm


def test_e2e_pipeline(isolate_vault, monkeypatch):
    """端到端:KB_ITEM ingest → 手动写 summary → reconcile → accept-ideas → rebuild-index。

    不调真 LLM(自由文本路径需要 LLM)。用结构化 KB_ITEM 入口绕过 LLM,
    手工写 summary 文件代替 make-prompts --auto,验证 reconcile + accept + rebuild。
    """
    tmp_path = isolate_vault

    # —— 步骤 1:ingest 一个 KB_ITEM(无 LLM)——
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "inbox.md").write_text(
        "# Inbox\n\n> 说明\n\n"
        "<!-- KB_ITEM_START -->\n"
        "source_type: github\n"
        "source_title: E2E 测试项目\n"
        "source_url: https://github.com/example/test\n\n"
        "项目正文内容\n"
        "<!-- KB_ITEM_END -->\n",
        encoding="utf-8",
    )

    # 禁用 LLM
    monkeypatch.setattr(kb_llm, "load_config", lambda: {"available": False})

    args = argparse.Namespace(no_llm=True)
    assert kb.cmd_ingest(args) == 0
    state = kb.load_state()
    assert len(state["sources"]) == 1
    sid = list(state["sources"].keys())[0]
    assert state["sources"][sid]["source_title"] == "E2E 测试项目"
    assert "summary_path" not in state["sources"][sid]  # 还没 summary

    # —— 步骤 2:手工写一个 summary 文件(模拟 make-prompts --auto 的输出)——
    sum_path = tmp_path / "02_Summaries" / "github" / f"summary_{sid}.md"
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    sum_path.write_text(
        "---\n"
        f"id: summary_{sid}\n"
        f"source_id: {sid}\n"
        "kind: summary\n"
        "source_type: github\n"
        "source_title: E2E 测试项目\n"
        "area: \n"
        "created_at: 2026-07-20\n"
        "summarized_at: 2026-07-20\n"
        "status: summarized\n"
        "action_status: undecided\n"
        "tags: [ai, agent]\n"
        "---\n\n"
        "## 一句话结论\n\n这是一个测试项目。\n",
        encoding="utf-8",
    )

    # —— 步骤 3:make-prompts --reconcile 回填 summary_path(注意:不回填 tags)——
    # tags 同步是 rebuild-index 的职责,不是 reconcile 的
    assert kb.cmd_make_prompts(argparse.Namespace(
        reconcile=True, auto=False, source=None, force=False, verbose=False
    )) == 0
    state = kb.load_state()
    assert state["sources"][sid].get("summary_path"), "summary_path 应被回填"
    assert "summary" in state["sources"][sid]["summary_path"]

    # —— 步骤 4:手工写 idea suggestion(模拟 extract-suggestions 输出),然后 accept——
    ideas_dir = tmp_path / "03_Ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    (ideas_dir / "idea_suggestions.md").write_text(
        "# Idea Suggestions (Review Queue)\n\n> 说明\n\n"
        "## Idea Suggestion: 来自 E2E 的想法\n\n"
        "- id: idea_e2e_1\n"
        "- status: accepted_research\n"
        "- recommended_area: research\n"
        "- source_summary: " + state["sources"][sid]["summary_path"] + "\n\n"
        "正文\n",
        encoding="utf-8",
    )

    assert kb.cmd_accept_ideas(argparse.Namespace()) == 0
    research = ideas_dir / "research_ideas.md"
    assert research.exists()
    assert "来自 E2E 的想法" in research.read_text(encoding="utf-8")
    # 原 suggestion 标 moved
    sug = (ideas_dir / "idea_suggestions.md").read_text(encoding="utf-8")
    assert "- status: moved" in sug

    # —— 步骤 5:rebuild-index 同步 tags(首次会从 frontmatter 补到 state)——
    stats = kb._rebuild_state_index(dry_run=False)
    # tags 应被同步(state 此前无 tags,frontmatter 有)
    assert stats["tags_added"] == 1, f"应同步 1 个 tags,实际 {stats['tags_added']}"
    state = kb.load_state()
    # tags 现在应保持
    assert state["sources"][sid].get("tags") == ["ai", "agent"]


def test_e2e_state_consistency_after_pipeline(isolate_vault, monkeypatch):
    """端到端后,state / summary / 正式清单 三者一致。"""
    tmp_path = isolate_vault

    # 简化版:只建 source + summary,rebuild 后 state 完整
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "inbox.md").write_text(
        "# Inbox\n\n> 说明\n\n"
        "<!-- KB_ITEM_START -->\n"
        "source_type: web\n"
        "source_title: 一致性测试\n\n"
        "正文\n"
        "<!-- KB_ITEM_END -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kb_llm, "load_config", lambda: {"available": False})
    kb.cmd_ingest(argparse.Namespace(no_llm=True))

    state = kb.load_state()
    sid = list(state["sources"].keys())[0]

    # 写 summary
    sum_path = tmp_path / "02_Summaries" / "web" / f"summary_{sid}.md"
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    sum_path.write_text(
        f"---\nsource_id: {sid}\nsource_title: 一致性测试\ntags: [test]\n---\n\n正文\n",
        encoding="utf-8",
    )

    # reconcile(只回填 summary_path,tags 由 rebuild 处理)
    kb.cmd_make_prompts(argparse.Namespace(
        reconcile=True, auto=False, source=None, force=False, verbose=False
    ))

    # 验证 state 关键字段
    state = kb.load_state()
    rec = state["sources"][sid]
    assert rec.get("source_title") == "一致性测试"
    assert rec.get("summary_path")

    # rebuild 后同步 tags
    kb.cmd_rebuild_index(argparse.Namespace(
        dry_run=False, tags_only=False, summary_path_only=False, verbose=False
    ))
    state = kb.load_state()
    rec = state["sources"][sid]
    assert rec.get("tags") == ["test"]
    assert rec.get("summary_path")
