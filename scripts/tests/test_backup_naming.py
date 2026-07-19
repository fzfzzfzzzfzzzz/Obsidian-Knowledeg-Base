"""备份命名带时分秒(v0.4.5 修复)—— 同日多次备份不会互相覆盖。

修复前:state_2026-07-19.json.bak 命名只到日,同一天第二次备份覆盖第一次。
修复后:state_20260719_153012.bak 命名到秒。
"""
import time
from pathlib import Path

import kb
from web.utils import backup_file


def test_backup_naming_includes_timestamp(isolate_vault):
    """备份文件名含时分秒,不只是日期。"""
    tmp_path = isolate_vault
    src = tmp_path / "fake_state.json"
    src.write_text('{"version": 1}', encoding="utf-8")

    result = backup_file(src, "state")
    assert result is not None
    name = result.name
    # 应形如 state_YYYYMMDD_HHMMSS.bak
    assert name.startswith("state_")
    assert name.endswith(".bak")
    # 中间应有 8 位日期 + 下划线 + 6 位时间
    stem = name[len("state_"):-len(".bak")]
    parts = stem.split("_")
    assert len(parts) == 2
    assert len(parts[0]) == 8  # YYYYMMDD
    assert len(parts[1]) == 6  # HHMMSS


def test_backup_same_day_twice_not_overwrite(isolate_vault):
    """同一天(甚至同一秒附近)调两次 backup,两个文件都在。"""
    tmp_path = isolate_vault
    src = tmp_path / "fake_state.json"
    src.write_text('{"version": 1, "n": 1}', encoding="utf-8")

    b1 = backup_file(src, "state")
    # 改内容后再备份
    time.sleep(1.1)  # 跨过秒边界,确保时间戳不同
    src.write_text('{"version": 1, "n": 2}', encoding="utf-8")
    b2 = backup_file(src, "state")

    assert b1 is not None and b2 is not None
    assert b1 != b2  # 路径不同
    assert b1.exists() and b2.exists()
    # 内容也应是各自的版本
    assert b1.read_text(encoding="utf-8") != b2.read_text(encoding="utf-8")


def test_backup_nonexistent_src_returns_none(isolate_vault):
    """src 不存在时返回 None,不抛错。"""
    tmp_path = isolate_vault
    result = backup_file(tmp_path / "no_such_file.json", "state")
    assert result is None


def test_backup_creates_web_backups_dir(isolate_vault):
    """备份目录 .kb/logs/web_backups/ 自动创建。"""
    tmp_path = isolate_vault
    src = tmp_path / "fake.json"
    src.write_text("x", encoding="utf-8")

    backup_dir = tmp_path / ".kb" / "logs" / "web_backups"
    assert not backup_dir.exists()

    backup_file(src, "test")

    assert backup_dir.exists()
    assert len(list(backup_dir.glob("test_*.bak"))) == 1
