"""POST /api/shutdown 端点测试。

验证三件事:
1. 端点已注册到 OpenAPI schema(回归护栏)
2. 调用返回 {ok:true},且确实调度了延迟退出(monkeypatch _schedule_exit 防真退出进程)
3. 走 router 级 _maybe_auth:配置 Basic Auth 时未授权 → 401(云端场景同样受保护)

v0.4.7 新增:host 白名单校验 ——
4. _shutdown_allowed 纯函数覆盖 4 种 bind/client 组合
5. 服务绑定非 loopback 时端点返回 403(本地 client=127.0.0.1 也拒绝)

注意:绝对不能让测试真的 os._exit(),否则整个 pytest 进程被杀。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient

import web.routers.dashboard as dashboard


@pytest.fixture
def client_no_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("KB_WEB_USER", raising=False)
    monkeypatch.delenv("KB_WEB_PASSWORD", raising=False)
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    # 防御性:即便测试忘了 patch _schedule_exit,也绝不能真 os._exit
    called = {"n": 0}
    def _fake(delay=0.5):
        called["n"] += 1
    monkeypatch.setattr(dashboard, "_schedule_exit", _fake)
    # client=("127.0.0.1", ...):让 TestClient 的 request.client.host 进 loopback 白名单
    # (默认是 "testclient",不在白名单,无法测放行路径)
    c = TestClient(kb_web.app, client=("127.0.0.1", 50000))
    c._shutdown_calls = called  # type: ignore[attr-defined]
    # 默认本地绑定(127.0.0.1),白名单校验放行
    c.app.state.bind_host = "127.0.0.1"
    return c


def test_shutdown_registered_in_openapi():
    """/api/shutdown 出现在 OpenAPI schema —— 注册回归护栏。"""
    paths = set(kb_web.app.openapi()["paths"].keys())
    assert "/api/shutdown" in paths


def test_shutdown_returns_ok_and_schedules_exit(client_no_auth):
    """POST /api/shutdown → 200 {ok:true},且调度了延迟退出函数(但不会真退出)。"""
    r = client_no_auth.post("/api/shutdown")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "message" in body
    # _schedule_exit 被调用一次(且因为是 monkeypatch 的假函数,进程没被杀)
    assert client_no_auth._shutdown_calls["n"] == 1


def test_shutdown_uses_real_schedule_exit_when_not_patched(tmp_path, monkeypatch):
    """_schedule_exit 本身确实创建了 threading.Timer(验证真实现没被改动坏)。

    用 monkeypatch 替换 Timer 的回调目标 os._exit,确保 Timer 触发也不杀进程。
    """
    import os
    import threading

    monkeypatch.delenv("KB_WEB_USER", raising=False)
    monkeypatch.delenv("KB_WEB_PASSWORD", raising=False)
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)

    # 替换 os._exit 为计数器,Timer 触发时只计数不退出
    exit_calls = {"n": 0}
    monkeypatch.setattr(os, "_exit", lambda code=0: exit_calls.__setitem__("n", exit_calls["n"] + 1))

    # 用极短 delay 直接测真实 _schedule_exit
    dashboard._schedule_exit(0.05)
    # 等 Timer 触发
    import time
    time.sleep(0.2)
    assert exit_calls["n"] == 1


def test_shutdown_requires_auth_when_configured(tmp_path, monkeypatch):
    """配置 Basic Auth 后,/api/shutdown 同样受保护 → 无凭证 401。"""
    monkeypatch.setenv("KB_WEB_USER", "admin")
    monkeypatch.setenv("KB_WEB_PASSWORD", "secret")
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    called = {"n": 0}
    monkeypatch.setattr(dashboard, "_schedule_exit", lambda delay=0.5: called.__setitem__("n", called["n"] + 1))
    c = TestClient(kb_web.app)
    r = c.post("/api/shutdown")
    assert r.status_code == 401
    # 未授权 → 根本没走到 _schedule_exit
    assert called["n"] == 0


def test_shutdown_passes_with_correct_credentials(tmp_path, monkeypatch):
    """凭证正确 → 200,且调度了退出。"""
    monkeypatch.setenv("KB_WEB_USER", "admin")
    monkeypatch.setenv("KB_WEB_PASSWORD", "secret")
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    called = {"n": 0}
    monkeypatch.setattr(dashboard, "_schedule_exit", lambda delay=0.5: called.__setitem__("n", called["n"] + 1))
    c = TestClient(kb_web.app, client=("127.0.0.1", 50000))
    c.app.state.bind_host = "127.0.0.1"
    r = c.post("/api/shutdown", auth=("admin", "secret"))
    assert r.status_code == 200
    assert called["n"] == 1


# ---------------------------------------------------------------------------
# v0.4.7:host 白名单校验
# ---------------------------------------------------------------------------

def test_shutdown_allowed_pure_function():
    """_shutdown_allowed 纯函数:bind+client 都 loopback 才放行。"""
    # 都 loopback → True
    assert dashboard._shutdown_allowed("127.0.0.1", "127.0.0.1") is True
    assert dashboard._shutdown_allowed("localhost", "127.0.0.1") is True
    assert dashboard._shutdown_allowed("::1", "::1") is True
    # bind 非 loopback → False(即便 client 是 loopback,防反向代理/隧道)
    assert dashboard._shutdown_allowed("0.0.0.0", "127.0.0.1") is False
    assert dashboard._shutdown_allowed("192.168.1.5", "127.0.0.1") is False
    # client 非 loopback → False
    assert dashboard._shutdown_allowed("127.0.0.1", "10.0.0.5") is False
    # 都非 loopback → False
    assert dashboard._shutdown_allowed("0.0.0.0", "8.8.8.8") is False


def test_shutdown_403_when_bound_to_non_loopback(client_no_auth):
    """服务绑定 0.0.0.0(暴露外网)时,即便 client=127.0.0.1 也 403,不调度退出。"""
    client_no_auth.app.state.bind_host = "0.0.0.0"
    r = client_no_auth.post("/api/shutdown")
    assert r.status_code == 403
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "shutdown_not_allowed"
    # 关键:没有调度退出
    assert client_no_auth._shutdown_calls["n"] == 0


def test_shutdown_allowed_when_default_local_bind(client_no_auth):
    """默认本地绑定(bind=127.0.0.1, client=127.0.0.1)→ 200,调度退出。

    显式设 bind_host 保证不依赖隐式默认值,锁死白名单放行路径。
    """
    client_no_auth.app.state.bind_host = "127.0.0.1"
    r = client_no_auth.post("/api/shutdown")
    assert r.status_code == 200
    assert client_no_auth._shutdown_calls["n"] == 1
