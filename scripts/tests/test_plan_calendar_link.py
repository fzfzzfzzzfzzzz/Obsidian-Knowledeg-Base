"""已确认 todo → 日历链接功能测试。

聚焦:
- todo 确定性 id 稳定(重新解析不变)
- POST /api/calendar 用 todo id 作 source_id 创建事项 + 去重
- /api/plans/confirmed 返回的 item 带 id 字段
"""
import hashlib

import kb
import kb_web
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "CALENDAR_FILE", kb_dir / "calendar.json")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    return TestClient(kb_web.app), tmp_path

WEEKLY_FILE = """# Weekly Plan: 2026-W29

## 本周重点

- [ ] 测试 todo
  - 来源:[[s]]
  - 预计时间:2-4h
"""

