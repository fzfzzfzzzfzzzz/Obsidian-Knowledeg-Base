"""make-prompts 命令 —— 重点是 --reconcile 回填路径(无 LLM 依赖)。

--auto 模式依赖真实 LLM,不做单测(集成层)。
手动模式的 prompt 生成逻辑也值得测,但它依赖 LLM 配置检查,先聚焦 reconcile。
"""
import argparse

import kb


def _setup_state_with_source(tmp_path, sid="source_ff_abc123", source_type="web",
                              summary_path=None, action_status="undecided"):
    """构造 state:有一个 source,可选 summary_path。"""
    state = {
        "version": 1,
        "created_at": "2026-07-19",
        "sources": {
            sid: {
                "source_id": sid,
                "path": f"01_Sources/{source_type}/source_xxx.md",
                "source_type": source_type,
                "source_title": "测试 source",
                "created_at": "2026-07-19",
                "ingested_at": "2026-07-19",
                "metadata_source": "llm",
                "action_status": action_status,
            }
        },
    }
    if summary_path is not None:
        state["sources"][sid]["summary_path"] = summary_path
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / "state.json").write_text(
        __import__("json").dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 同时建一个最小的 source note 供 _backfill_source_note 调用
    src_note = tmp_path / "01_Sources" / source_type / "source_xxx.md"
    src_note.parent.mkdir(parents=True, exist_ok=True)
    src_note.write_text(
        "---\n"
        "source_id: " + sid + "\n"
        "status: ingested\n"
        "summary_location: \n"
        "---\n\n"
        "## 原始内容\n\n正文\n",
        encoding="utf-8",
    )


def _write_summary_file(tmp_path, sid, source_type="web", title="测试总结"):
    sum_path = tmp_path / "02_Summaries" / source_type / f"summary_{sid}.md"
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    sum_path.write_text(
        "---\n"
        f"id: summary_{sid}\n"
        f"source_id: {sid}\n"
        "kind: summary\n"
        f"source_type: {source_type}\n"
        f"source_title: {title}\n"
        "area: \n"
        "created_at: 2026-07-19\n"
        "summarized_at: 2026-07-19\n"
        "status: summarized\n"
        "action_status: undecided\n"
        "tags: []\n"
        "---\n\n"
        "## 一句话结论\n\n这是测试总结。\n",
        encoding="utf-8",
    )
    return sum_path


def test_make_prompts_reconcile_backfills_summary_path(isolate_vault):
    """state 里 source 无 summary_path,02_Summaries 下有对应文件 → 回填。"""
    tmp_path = isolate_vault
    sid = "source_ff_backfill1"
    _setup_state_with_source(tmp_path, sid=sid, summary_path=None)
    _write_summary_file(tmp_path, sid)

    args = argparse.Namespace(reconcile=True)
    assert kb.cmd_make_prompts(args) == 0

    state = kb.load_state()
    assert state["sources"][sid].get("summary_path"), "summary_path 应被回填"
    assert "summary_backfill1" in state["sources"][sid]["summary_path"] or \
           sid in state["sources"][sid]["summary_path"]


def test_make_prompts_reconcile_skips_already_filled(isolate_vault):
    """state 里已有 summary_path 且匹配 → 不重复回填(quiet 路径)。"""
    tmp_path = isolate_vault
    sid = "source_ff_already1"
    sum_path = _write_summary_file(tmp_path, sid)
    rel = sum_path.relative_to(tmp_path).as_posix()
    _setup_state_with_source(tmp_path, sid=sid, summary_path=rel)

    # 第二次 reconcile:summary_path 已正确,不应变更
    assert kb.cmd_make_prompts(argparse.Namespace(reconcile=True)) == 0
    state = kb.load_state()
    assert state["sources"][sid]["summary_path"] == rel


def test_make_prompts_reconcile_sets_action_status(isolate_vault):
    """回填时 action_status 应被设为 undecided(若此前缺失)。"""
    tmp_path = isolate_vault
    sid = "source_ff_action1"
    _setup_state_with_source(tmp_path, sid=sid, summary_path=None, action_status="undecided")
    _write_summary_file(tmp_path, sid)

    kb.cmd_make_prompts(argparse.Namespace(reconcile=True))
    state = kb.load_state()
    # setdefault 逻辑:已有值不变,缺失补 undecided
    assert state["sources"][sid].get("action_status") == "undecided"


def test_make_prompts_reconcile_no_summaries_dir(isolate_vault):
    """02_Summaries 不存在时优雅返回 0。"""
    tmp_path = isolate_vault
    _setup_state_with_source(tmp_path)
    # 不写 summary 文件,不建 02_Summaries
    rc = kb.cmd_make_prompts(argparse.Namespace(reconcile=True))
    assert rc == 0


def test_make_prompts_reconcile_ignores_unknown_source_id(isolate_vault):
    """summary frontmatter 里的 source_id 在 state 里不存在时跳过。"""
    tmp_path = isolate_vault
    _setup_state_with_source(tmp_path, sid="source_ff_known")
    # 写一个 state 里没有的 summary
    _write_summary_file(tmp_path, sid="source_ff_orphan")
    rc = kb.cmd_make_prompts(argparse.Namespace(reconcile=True))
    assert rc == 0
    state = kb.load_state()
    # state 不应新增 source
    assert "source_ff_orphan" not in state["sources"]
