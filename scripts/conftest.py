"""pytest 配置:把 scripts/ 加入 sys.path,使测试能 import 同级的 kb / kb_web。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import kb


@pytest.fixture
def isolate_vault(tmp_path, monkeypatch):
    """把 kb 的全部 vault 相关路径隔离到 tmp_path,避免触碰真实 vault / state.json。

    load_state/save_state 等使用的是模块级预计算的 STATE_FILE(基于 VAULT_ROOT 在导入时算出),
    因此只 monkeypatch VAULT_ROOT 不够,必须把所有衍生路径一并重定向。
    同时也重定向 kb_web.VAULT_ROOT(它从 kb 复制了 import-time 副本),让 Web 路由
    测试也能用同一个 fixture。
    """
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb, "CALENDAR_FILE", kb_dir / "calendar.json")
    monkeypatch.setattr(kb, "RAW_TEXT_DIR", kb_dir / "raw_text")
    monkeypatch.setattr(kb, "LOGS_DIR", kb_dir / "logs")
    # kb_web 在 import 时拷贝了 kb.VAULT_ROOT,需要单独 patch(若已被 import)
    kb_web = sys.modules.get("kb_web")
    if kb_web is not None:
        monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    return tmp_path

