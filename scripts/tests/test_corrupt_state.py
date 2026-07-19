"""state.json / calendar.json 损坏检测(v0.4.5)。

修复前:load_state 静默吞 JSONDecodeError,返回空骨架,
rebuild-index 跑出"无需更新"误导用户。
修复后:备份损坏文件 + 记日志 + 加 _corrupt 标记。
"""
import json

import kb


# —— load_state 损坏检测 ——

def test_load_state_corrupt_json_returns_empty_with_flag(isolate_vault):
    """损坏 JSON 时返回空骨架,且加 _corrupt=True 标记。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text("{invalid!!!", encoding="utf-8")

    state = kb.load_state()
    assert state.get("_corrupt") is True
    assert "_corrupt_error" in state
    assert state["sources"] == {}  # 空骨架


def test_load_state_corrupt_json_backs_up(isolate_vault):
    """损坏的原文件应被备份到 .kb/logs/corrupt_state_*.json。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text("{bad json", encoding="utf-8")

    kb.load_state()

    backups = list((kb_dir / "logs").glob("corrupt_state_*.json"))
    assert len(backups) == 1
    # 备份内容应是原损坏文件
    assert backups[0].read_text(encoding="utf-8") == "{bad json"


def test_load_state_corrupt_json_logs_warning(isolate_vault):
    """损坏事件应记入 .kb/logs/kb.log。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text("{bad", encoding="utf-8")

    kb.load_state()

    log = (kb_dir / "logs" / "kb.log").read_text(encoding="utf-8")
    assert "state.json 损坏" in log or "state.json" in log and "损坏" in log


def test_load_state_valid_json_no_corrupt_flag(isolate_vault):
    """合法 JSON 不应有 _corrupt 标记(回归保护)。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    valid_state = {"version": 1, "sources": {"sid1": {"path": "x"}}}
    (kb_dir / "state.json").write_text(
        json.dumps(valid_state, ensure_ascii=False), encoding="utf-8"
    )

    state = kb.load_state()
    assert "_corrupt" not in state
    assert "sid1" in state["sources"]


def test_load_state_missing_file_no_corrupt_flag(isolate_vault):
    """文件不存在时返回空骨架,但不应标 _corrupt(本来就没有,不算损坏)。"""
    state = kb.load_state()
    assert "_corrupt" not in state
    assert state["sources"] == {}


# —— load_calendar 同款 ——

def test_load_calendar_corrupt_json_returns_empty_with_flag(isolate_vault):
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "calendar.json").write_text("not json", encoding="utf-8")

    cal = kb.load_calendar()
    assert cal.get("_corrupt") is True
    assert cal["items"] == {}


def test_load_calendar_corrupt_backs_up(isolate_vault):
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "calendar.json").write_text("not json", encoding="utf-8")

    kb.load_calendar()

    backups = list((kb_dir / "logs").glob("corrupt_calendar_*.json"))
    assert len(backups) == 1


# —— rebuild-index 损坏报告 ——

def test_rebuild_index_reports_corrupt_state(isolate_vault):
    """state 损坏时,rebuild-index 应明确报告并返回非零。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text("{broken", encoding="utf-8")
    # 即使 02_Summaries 下有 summary 文件,rebuild 也应先提示损坏
    sum_dir = tmp_path / "02_Summaries" / "web"
    sum_dir.mkdir(parents=True)
    (sum_dir / "summary_xxx.md").write_text(
        "---\nsource_id: source_ff_xxx\n---\n\nbody\n", encoding="utf-8"
    )

    import argparse
    rc = kb.cmd_rebuild_index(argparse.Namespace(
        dry_run=False, tags_only=False, summary_path_only=False, verbose=False
    ))
    # 应返回 2(需确认)或 0(已 dry-run 安全),不应静默成功
    assert rc != 0, "损坏的 state 不应被静默 rebuild"


def test_rebuild_index_corrupt_dry_run(isolate_vault):
    """state 损坏 + dry-run 模式也应明确报告(不写)。"""
    tmp_path = isolate_vault
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text("{broken", encoding="utf-8")

    import argparse
    rc = kb.cmd_rebuild_index(argparse.Namespace(
        dry_run=True, tags_only=False, summary_path_only=False, verbose=False
    ))
    # 损坏情况下 dry-run 仍应警告(返回 2)
    assert rc == 2
