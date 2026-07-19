"""rebuild-index —— state.json ↔ summary frontmatter 自愈。

范式:isolate_vault + 手工构造 state.json 和 summary 文件 + 调 cmd_rebuild_index。
"""
import argparse
import json

import kb


def _write_state(tmp_path, sources_dict):
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "created_at": "2026-07-19",
        "sources": sources_dict,
    }
    (kb_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_summary(tmp_path, sid, source_type="web", tags=None, title="测试总结"):
    """写一个 summary 文件,frontmatter 含 source_id 和可选 tags。"""
    sum_path = tmp_path / "02_Summaries" / source_type / f"summary_{sid}.md"
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    tags_str = "[" + ", ".join(tags or []) + "]" if tags is not None else "[]"
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
        f"tags: {tags_str}\n"
        "---\n\n## 一句话结论\n\n内容\n",
        encoding="utf-8",
    )
    return sum_path


def _base_source(sid, source_type="web"):
    return {
        "source_id": sid,
        "path": f"01_Sources/{source_type}/source_xxx.md",
        "source_type": source_type,
        "source_title": "测试",
        "created_at": "2026-07-19",
        "ingested_at": "2026-07-19",
        "metadata_source": "llm",
    }


# —— summary_path 回填 ——

def test_rebuild_backfills_missing_summary_path(isolate_vault):
    tmp_path = isolate_vault
    sid = "source_ff_backfill_test"
    _write_state(tmp_path, {sid: _base_source(sid)})  # 无 summary_path
    sum_path = _write_summary(tmp_path, sid)
    expected_rel = sum_path.relative_to(tmp_path).as_posix()

    rc = kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                                  summary_path_only=False, verbose=False))
    assert rc == 0
    state = kb.load_state()
    assert state["sources"][sid]["summary_path"] == expected_rel


def test_rebuild_corrects_mismatched_summary_path(isolate_vault):
    """state 里 summary_path 指向错误位置,frontmatter 扫盘为正确 → 修正。"""
    tmp_path = isolate_vault
    sid = "source_ff_mismatch"
    src = _base_source(sid)
    src["summary_path"] = "02_Summaries/wrong/wrong.md"  # 错误路径
    _write_state(tmp_path, {sid: src})
    correct = _write_summary(tmp_path, sid)
    correct_rel = correct.relative_to(tmp_path).as_posix()

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    assert state["sources"][sid]["summary_path"] == correct_rel


# —— tags 同步 ——

def test_rebuild_syncs_tags_from_frontmatter(isolate_vault):
    """state 无 tags,frontmatter 有 → 补到 state。"""
    tmp_path = isolate_vault
    sid = "source_ff_tags1"
    src = _base_source(sid)
    _write_state(tmp_path, {sid: src})
    _write_summary(tmp_path, sid, tags=["ai", "agent"])

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    assert state["sources"][sid].get("tags") == ["ai", "agent"]


def test_rebuild_overrides_state_tags_with_frontmatter(isolate_vault):
    """state 和 frontmatter 都有 tags 但不一致 → 以 frontmatter 为准。"""
    tmp_path = isolate_vault
    sid = "source_ff_tags2"
    src = _base_source(sid)
    src["tags"] = ["旧", "标签"]
    _write_state(tmp_path, {sid: src})
    _write_summary(tmp_path, sid, tags=["新", "tags"])

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    assert state["sources"][sid]["tags"] == ["新", "tags"]


def test_rebuild_preserves_user_added_tags_when_frontmatter_empty(isolate_vault):
    """frontmatter 无 tags(state 有) → 不删,保留用户可能手加的。"""
    tmp_path = isolate_vault
    sid = "source_ff_tags3"
    src = _base_source(sid)
    src["tags"] = ["用户手加"]
    _write_state(tmp_path, {sid: src})
    _write_summary(tmp_path, sid, tags=[])  # frontmatter 无 tags

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    assert state["sources"][sid]["tags"] == ["用户手加"]


# —— 用户行为数据保护 ——

def test_rebuild_preserves_user_reading_state(isolate_vault):
    """rebuild 不应碰 is_favorite / read_count / collection_ids 等用户数据。"""
    tmp_path = isolate_vault
    sid = "source_ff_preserve"
    src = _base_source(sid)
    src.update({
        "is_favorite": True,
        "read_count": 5,
        "last_read_at": "2026-07-18T10:00:00",
        "collection_ids": ["col_1", "col_2"],
        "reading_status": "read",
        "read_later": True,
        "detected_dates": [{"date": "2026-07-20", "label": "deadline"}],
    })
    _write_state(tmp_path, {sid: src})
    _write_summary(tmp_path, sid, tags=["test"])

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    rec = state["sources"][sid]
    # 所有用户行为字段应原封不动
    assert rec["is_favorite"] is True
    assert rec["read_count"] == 5
    assert rec["last_read_at"] == "2026-07-18T10:00:00"
    assert rec["collection_ids"] == ["col_1", "col_2"]
    assert rec["reading_status"] == "read"
    assert rec["read_later"] is True
    assert rec["detected_dates"] == [{"date": "2026-07-20", "label": "deadline"}]
    # 同时 tags 被补上
    assert rec["tags"] == ["test"]


# —— dry-run ——

def test_rebuild_dry_run_does_not_write(isolate_vault):
    """--dry-run 不修改 state.json。"""
    tmp_path = isolate_vault
    sid = "source_ff_dryrun"
    _write_state(tmp_path, {sid: _base_source(sid)})  # 无 summary_path
    _write_summary(tmp_path, sid, tags=["should_not_be_written"])

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=True, tags_only=False,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    # 应保持原状
    assert "summary_path" not in state["sources"][sid]
    assert "tags" not in state["sources"][sid]


# —— 备份 ——

def test_rebuild_backs_up_state(isolate_vault):
    """rebuild 写前应备份 state 到 .kb/logs/web_backups/。"""
    tmp_path = isolate_vault
    sid = "source_ff_backup"
    _write_state(tmp_path, {sid: _base_source(sid)})
    _write_summary(tmp_path, sid)

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=False, verbose=False))
    backup_dir = tmp_path / ".kb" / "logs" / "web_backups"
    backups = list(backup_dir.glob("state_rebuild_*.json.bak"))
    assert len(backups) >= 1
    # 备份内容应是原 state(无 summary_path)
    import json as _json
    backed = _json.loads(backups[0].read_text(encoding="utf-8"))
    assert "summary_path" not in backed["sources"][sid]


# —— 孤儿报告 ——

def test_rebuild_reports_orphan_summary_path(isolate_vault):
    """state 里有 summary_path 但 02_Summaries/ 找不到对应文件 → 报告孤儿。"""
    tmp_path = isolate_vault
    sid = "source_ff_orphan"
    src = _base_source(sid)
    src["summary_path"] = "02_Summaries/web/summary_source_ff_orphan.md"
    _write_state(tmp_path, {sid: src})
    # 不写 summary 文件
    stats = kb._rebuild_state_index(dry_run=True)
    assert stats["orphans_in_state"] == 1


# —— 过滤参数 ——

def test_rebuild_tags_only_skips_summary_path(isolate_vault):
    """--tags-only 时不动 summary_path。"""
    tmp_path = isolate_vault
    sid = "source_ff_tagsonly"
    src = _base_source(sid)  # 无 summary_path
    _write_state(tmp_path, {sid: src})
    _write_summary(tmp_path, sid, tags=["x"])

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=True,
                                            summary_path_only=False, verbose=False))
    state = kb.load_state()
    # tags 应补上
    assert state["sources"][sid].get("tags") == ["x"]
    # summary_path 不应被回填
    assert "summary_path" not in state["sources"][sid]


def test_rebuild_summary_path_only_skips_tags(isolate_vault):
    """--summary-path-only 时不动 tags。"""
    tmp_path = isolate_vault
    sid = "source_ff_sponly"
    src = _base_source(sid)
    _write_state(tmp_path, {sid: src})
    _write_summary(tmp_path, sid, tags=["x"])

    kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                            summary_path_only=True, verbose=False))
    state = kb.load_state()
    # summary_path 应被回填
    assert state["sources"][sid].get("summary_path")
    # tags 不应被补
    assert "tags" not in state["sources"][sid]


# —— 边界 ——

def test_rebuild_no_summaries_dir(isolate_vault):
    """02_Summaries 不存在时返回 0(优雅)。"""
    tmp_path = isolate_vault
    _write_state(tmp_path, {"source_ff_any": _base_source("source_ff_any")})
    rc = kb.cmd_rebuild_index(argparse.Namespace(dry_run=False, tags_only=False,
                                                  summary_path_only=False, verbose=False))
    assert rc == 0


def test_rebuild_no_changes_no_write(isolate_vault):
    """state 和 frontmatter 完全一致时不应写文件,也不备份。"""
    tmp_path = isolate_vault
    sid = "source_ff_clean"
    sum_path = _write_summary(tmp_path, sid, tags=["aligned"])
    src = _base_source(sid)
    src["summary_path"] = sum_path.relative_to(tmp_path).as_posix()
    src["tags"] = ["aligned"]
    _write_state(tmp_path, {sid: src})

    stats = kb._rebuild_state_index(dry_run=False)
    assert stats["written"] is False
    assert stats["summary_path_backfilled"] == 0
    assert stats["tags_added"] == 0
