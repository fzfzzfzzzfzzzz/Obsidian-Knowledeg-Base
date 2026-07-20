"""chat() HTTP 重试逻辑(v0.4.6)—— mock requests.post + time.sleep。

覆盖:
- 配置缺失直接抛(不发请求)
- 网络错误重试 N 次后成功
- HTTP 4xx 不重试(LLMError 立即抛)
- 退避间隔验证(time.sleep 调用次数)
"""
import json

import kb_llm
import pytest


def _make_chat_response(content="hi", status=200, err_msg=None):
    """构造一个 fake requests.Response。"""
    class FakeResp:
        def __init__(self):
            self.status_code = status
            if status >= 400:
                self._err = {"error": {"message": err_msg or "fail"}}
                self.text = json.dumps(self._err)
            else:
                self._ok = {
                    "choices": [{"message": {"content": content}}],
                    "model": "test-model",
                    "usage": {"total_tokens": 10},
                }
        def json(self):
            return self._err if self.status_code >= 400 else self._ok
    return FakeResp()


@pytest.fixture
def patched_chat_deps(monkeypatch):
    """patch load_config 返回可用 + fake requests。"""
    monkeypatch.setattr(kb_llm, "load_config", lambda: {
        "available": True,
        "api_key": "test-key",
        "model": "test-model",
        "base_url": "http://test.local/v1/",
        "timeout": 5,
    })
    return monkeypatch


def test_chat_unavailable_config_raises(monkeypatch):
    """配置不可用直接抛,不发请求。"""
    monkeypatch.setattr(kb_llm, "load_config", lambda: {"available": False})
    with pytest.raises(kb_llm.LLMError, match="未配置"):
        kb_llm.chat([{"role": "user", "content": "x"}])


def test_chat_success_first_try(patched_chat_deps):
    """第一次成功,无重试。"""
    calls = []

    def fake_post(*a, **kw):
        calls.append(1)
        return _make_chat_response(content="hello")

    fake_requests = type("R", (), {"post": staticmethod(fake_post)})
    patched_chat_deps.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    result = kb_llm.chat([{"role": "user", "content": "x"}])
    assert result["content"] == "hello"
    assert len(calls) == 1


def test_chat_retries_on_network_error(patched_chat_deps, monkeypatch):
    """网络错误重试后成功。"""
    sleeps = []
    monkeypatch.setattr(kb_llm.time, "sleep", lambda s: sleeps.append(s))

    attempts = {"n": 0}

    def fake_post(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("network down")
        return _make_chat_response(content="recovered")

    fake_requests = type("R", (), {"post": staticmethod(fake_post)})
    patched_chat_deps.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    result = kb_llm.chat([{"role": "user", "content": "x"}], retries=3)
    assert result["content"] == "recovered"
    assert attempts["n"] == 3
    # 重试了 2 次,每次都 sleep
    assert len(sleeps) == 2


def test_chat_no_retry_on_llm_error(patched_chat_deps, monkeypatch):
    """HTTP 4xx 抛 LLMError,不重试。"""
    sleeps = []
    monkeypatch.setattr(kb_llm.time, "sleep", lambda s: sleeps.append(s))

    def fake_post(*a, **kw):
        return _make_chat_response(status=401, err_msg="bad key")

    fake_requests = type("R", (), {"post": staticmethod(fake_post)})
    patched_chat_deps.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    with pytest.raises(kb_llm.LLMError, match="HTTP 401"):
        kb_llm.chat([{"role": "user", "content": "x"}], retries=3)
    # 不应该 sleep(LLMError 不重试)
    assert sleeps == []


def test_chat_exhausts_retries(patched_chat_deps, monkeypatch):
    """所有重试用完后抛。"""
    sleeps = []
    monkeypatch.setattr(kb_llm.time, "sleep", lambda s: sleeps.append(s))

    def fake_post(*a, **kw):
        raise OSError("network always down")

    fake_requests = type("R", (), {"post": staticmethod(fake_post)})
    patched_chat_deps.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    with pytest.raises(kb_llm.LLMError, match="重试"):
        kb_llm.chat([{"role": "user", "content": "x"}], retries=2)
    # 总尝试 3 次(retries=2 + 初次),sleep 2 次
    assert len(sleeps) == 2


def test_chat_backoff_intervals(patched_chat_deps, monkeypatch):
    """退避间隔是 1.5 * (attempt+1)。"""
    sleeps = []
    monkeypatch.setattr(kb_llm.time, "sleep", lambda s: sleeps.append(s))

    def fake_post(*a, **kw):
        raise OSError("down")

    fake_requests = type("R", (), {"post": staticmethod(fake_post)})
    patched_chat_deps.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    with pytest.raises(kb_llm.LLMError):
        kb_llm.chat([{"role": "user", "content": "x"}], retries=2)
    # 第 1 次失败后 sleep(1.5 * (0+1)) = 1.5
    # 第 2 次失败后 sleep(1.5 * (1+1)) = 3.0
    assert sleeps == [1.5, 3.0]


def test_chat_returns_usage(patched_chat_deps):
    """成功响应含 token usage。"""
    def fake_post(*a, **kw):
        return _make_chat_response()

    fake_requests = type("R", (), {"post": staticmethod(fake_post)})
    patched_chat_deps.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    result = kb_llm.chat([{"role": "user", "content": "x"}])
    assert result["usage"]["total_tokens"] == 10
    assert result["model"] == "test-model"
