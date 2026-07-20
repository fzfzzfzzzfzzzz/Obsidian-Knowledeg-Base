"""serve 安全警告 + Basic Auth + 时区(v0.4.6)。"""
import argparse
import json
import os
from datetime import date

import kb
import kb_date
import kb_web
import pytest
from fastapi.testclient import TestClient


# —— serve 警告 ——

def test_serve_blocks_expose_without_confirm(monkeypatch):
    """host=0.0.0.0 且无 KB_SERVE_CONFIRM_EXPOSE → 返回 1。"""
    monkeypatch.delenv("KB_SERVE_CONFIRM_EXPOSE", raising=False)
    monkeypatch.delenv("KB_WEB_USER", raising=False)
    args = argparse.Namespace(host="0.0.0.0", port=5173, reload=False)
    rc = kb.cmd_serve(args)
    assert rc == 1


def test_serve_proceeds_with_confirm_env(monkeypatch):
    """host=0.0.0.0 且 KB_SERVE_CONFIRM_EXPOSE=1 → 继续(应真到 uvicorn 才停)。"""
    monkeypatch.setenv("KB_SERVE_CONFIRM_EXPOSE", "1")
    # mock uvicorn.run 避免真启动
    def fake_run(*a, **kw):
        pass
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_run)
    args = argparse.Namespace(host="0.0.0.0", port=5173, reload=False)
    rc = kb.cmd_serve(args)
    assert rc == 0


def test_serve_localhost_no_warning(monkeypatch):
    """host=127.0.0.1 不需要确认。"""
    monkeypatch.delenv("KB_SERVE_CONFIRM_EXPOSE", raising=False)
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
    args = argparse.Namespace(host="127.0.0.1", port=5173, reload=False)
    rc = kb.cmd_serve(args)
    assert rc == 0


# —— Basic Auth ——

@pytest.fixture
def client_no_auth(tmp_path, monkeypatch):
    """未配置 auth。"""
    monkeypatch.delenv("KB_WEB_USER", raising=False)
    monkeypatch.delenv("KB_WEB_PASSWORD", raising=False)
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text(
        json.dumps({"version": 1, "sources": {}}), encoding="utf-8"
    )
    return TestClient(kb_web.app)


@pytest.fixture
def client_with_auth(tmp_path, monkeypatch):
    """配置了 auth。"""
    monkeypatch.setenv("KB_WEB_USER", "admin")
    monkeypatch.setenv("KB_WEB_PASSWORD", "secret")
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "state.json").write_text(
        json.dumps({"version": 1, "sources": {}}), encoding="utf-8"
    )
    return TestClient(kb_web.app)


def test_no_auth_passes(client_no_auth):
    """未配置 auth 时,请求直接通过(本地默认场景)。"""
    r = client_no_auth.get("/api/health")
    assert r.status_code == 200


def test_auth_required_returns_401(client_with_auth):
    """配置了 auth 但未提供凭证 → 401。"""
    r = client_with_auth.get("/api/health")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_auth_wrong_credentials_401(client_with_auth):
    """凭证错误 → 401。"""
    r = client_with_auth.get(
        "/api/health",
        auth=("admin", "wrong"),
    )
    assert r.status_code == 401


def test_auth_correct_credentials_passes(client_with_auth):
    """凭证正确 → 200。"""
    r = client_with_auth.get(
        "/api/health",
        auth=("admin", "secret"),
    )
    assert r.status_code == 200


# —— 时区 ——

def test_today_default_uses_system_tz(monkeypatch):
    """无 KB_TZ 时,_today() 用系统时区(与 date.today() 一致)。"""
    monkeypatch.delenv("KB_TZ", raising=False)
    assert kb_date._today() == date.today()


def test_today_respects_tz_env(monkeypatch):
    """KB_TZ=UTC 时,_today() 用 UTC 日期。

    注意:UTC 与本地时区可能跨日,只在差一天时断言。
    本测试选 UTC 是因为它和任何本地时区都有可预测的差异。
    """
    monkeypatch.setenv("KB_TZ", "UTC")
    from datetime import datetime, timezone
    utc_today = datetime.now(timezone.utc).date()
    # _today() 应返回 UTC 日期
    assert kb_date._today() == utc_today


def test_today_invalid_tz_falls_back(monkeypatch):
    """KB_TZ 是无效时区名时,退回系统默认(不抛错)。"""
    monkeypatch.setenv("KB_TZ", "Invalid/NotReal")
    # 不抛错
    result = kb_date._today()
    assert isinstance(result, date)


def test_detect_dates_uses_configured_tz(monkeypatch):
    """detect_dates 的相对日期(今天/明天)用配置的时区。"""
    monkeypatch.setenv("KB_TZ", "UTC")
    from datetime import datetime, timezone
    utc_today = datetime.now(timezone.utc).date()
    res = kb_date.detect_dates("今天截止")
    assert len(res) == 1
    assert res[0]["normalized_date"] == utc_today.isoformat()
