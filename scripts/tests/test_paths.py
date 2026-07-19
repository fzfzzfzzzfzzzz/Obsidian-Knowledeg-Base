"""路径配置 —— 环境变量覆盖派生路径,云端部署用。

注意:kb.py 的常量在 import 时算定,所以测试用 importlib.reload 强制重新读取 env。
"""
import importlib
import os
from pathlib import Path

import kb


def _reload_kb_with_env(env: dict):
    """用指定 env 重新 import kb,返回新模块对象。"""
    old_values = {}
    for k in list(env.keys()) + [
        "KB_VAULT_ROOT", "KB_DIR", "KB_STATE_FILE",
        "KB_CALENDAR_FILE", "KB_RAW_TEXT_DIR", "KB_LOGS_DIR",
    ]:
        old_values[k] = os.environ.get(k)
    # 清掉所有 KB_*_*
    for k in ["KB_VAULT_ROOT", "KB_DIR", "KB_STATE_FILE",
              "KB_CALENDAR_FILE", "KB_RAW_TEXT_DIR", "KB_LOGS_DIR"]:
        os.environ.pop(k, None)
    # 应用新 env
    for k, v in env.items():
        if v is not None:
            os.environ[k] = v
    try:
        importlib.reload(kb)
        yield kb
    finally:
        # 还原
        for k in ["KB_VAULT_ROOT", "KB_DIR", "KB_STATE_FILE",
                  "KB_CALENDAR_FILE", "KB_RAW_TEXT_DIR", "KB_LOGS_DIR"]:
            os.environ.pop(k, None)
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v
        importlib.reload(kb)


def test_defaults_when_no_env(monkeypatch):
    """无环境变量时,路径回到 scripts/ 的父目录布局(向后兼容)。"""
    for k in ["KB_VAULT_ROOT", "KB_DIR", "KB_STATE_FILE",
              "KB_CALENDAR_FILE", "KB_RAW_TEXT_DIR", "KB_LOGS_DIR"]:
        monkeypatch.delenv(k, raising=False)
    # 重新加载 kb 使新 env 生效
    importlib.reload(kb)
    try:
        expected_root = Path(kb.__file__).resolve().parent.parent
        assert kb.VAULT_ROOT == expected_root
        assert kb.KB_DIR == expected_root / ".kb"
        assert kb.STATE_FILE == expected_root / ".kb" / "state.json"
        assert kb.CALENDAR_FILE == expected_root / ".kb" / "calendar.json"
        assert kb.RAW_TEXT_DIR == expected_root / ".kb" / "raw_text"
        assert kb.LOGS_DIR == expected_root / ".kb" / "logs"
    finally:
        importlib.reload(kb)


def test_env_overrides_vault_root(monkeypatch, tmp_path):
    """KB_VAULT_ROOT 覆盖根,所有派生路径跟着走。"""
    monkeypatch.setenv("KB_VAULT_ROOT", str(tmp_path))
    for k in ["KB_DIR", "KB_STATE_FILE", "KB_CALENDAR_FILE",
              "KB_RAW_TEXT_DIR", "KB_LOGS_DIR"]:
        monkeypatch.delenv(k, raising=False)
    importlib.reload(kb)
    try:
        assert kb.VAULT_ROOT == tmp_path
        assert kb.KB_DIR == tmp_path / ".kb"
        assert kb.STATE_FILE == tmp_path / ".kb" / "state.json"
        assert kb.LOGS_DIR == tmp_path / ".kb" / "logs"
    finally:
        importlib.reload(kb)


def test_env_overrides_individual_paths(monkeypatch, tmp_path):
    """每个派生路径可独立覆盖(如云端把 state.json 单独挂卷)。"""
    custom_dir = tmp_path / "custom_kb"
    custom_state = tmp_path / "elsewhere" / "state.json"
    custom_logs = tmp_path / "var" / "log" / "kb"
    monkeypatch.setenv("KB_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("KB_DIR", str(custom_dir))
    monkeypatch.setenv("KB_STATE_FILE", str(custom_state))
    monkeypatch.setenv("KB_LOGS_DIR", str(custom_logs))
    for k in ["KB_CALENDAR_FILE", "KB_RAW_TEXT_DIR"]:
        monkeypatch.delenv(k, raising=False)
    importlib.reload(kb)
    try:
        assert kb.KB_DIR == custom_dir
        # KB_DIR 被覆盖后,未覆盖的 CALENDAR_FILE 派生自新的 KB_DIR
        assert kb.CALENDAR_FILE == custom_dir / "calendar.json"
        assert kb.RAW_TEXT_DIR == custom_dir / "raw_text"
        # STATE_FILE 和 LOGS_DIR 完全独立
        assert kb.STATE_FILE == custom_state
        assert kb.LOGS_DIR == custom_logs
    finally:
        importlib.reload(kb)


def test_kb_web_vault_root_follows_kb(monkeypatch, tmp_path):
    """kb_web 在 import 时复制 kb.VAULT_ROOT;reload kb 后重新 import kb_web 应同步。"""
    monkeypatch.setenv("KB_VAULT_ROOT", str(tmp_path))
    for k in ["KB_DIR", "KB_STATE_FILE", "KB_CALENDAR_FILE",
              "KB_RAW_TEXT_DIR", "KB_LOGS_DIR"]:
        monkeypatch.delenv(k, raising=False)
    importlib.reload(kb)
    try:
        import kb_web
        importlib.reload(kb_web)
        assert kb_web.VAULT_ROOT == tmp_path
    finally:
        importlib.reload(kb)
        try:
            import kb_web
            importlib.reload(kb_web)
        except Exception:
            pass
