"""SSRF 防护(v0.4.6)—— fetch_url_text 拒绝内网/保留地址。

防止用户通过 /api/ingest 投稿恶意 URL 让服务端访问内网资源
(如云元数据 169.254.169.254、本机服务 127.0.0.1、内网 192.168.x.x)。
"""
import pytest

import kb_llm


# —— _check_url_safe 单元测试(不发网络) ——

def test_check_url_rejects_loopback_ipv4():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://127.0.0.1/")


def test_check_url_rejects_loopback_localhost():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://localhost/")


def test_check_url_rejects_private_192():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://192.168.1.1/")


def test_check_url_rejects_private_10():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://10.0.0.1/")


def test_check_url_rejects_private_172():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://172.16.0.1/")


def test_check_url_rejects_cloud_metadata():
    """云元数据端点(常见 SSRF 攻击目标)。"""
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://169.254.169.254/latest/meta-data/")


def test_check_url_rejects_non_http_scheme():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("file:///etc/passwd")


def test_check_url_rejects_gopher_scheme():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("gopher://evil.com/")


def test_check_url_rejects_missing_host():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http:///")


def test_check_url_allows_public_domain():
    """公网域名应通过(不抛)。"""
    kb_llm._check_url_safe("http://example.com/")  # 不抛即通过


def test_check_url_allows_https():
    kb_llm._check_url_safe("https://open.bigmodel.cn/api/paas/v4/")


def test_check_url_rejects_ipv6_loopback():
    with pytest.raises(kb_llm.LLMError):
        kb_llm._check_url_safe("http://[::1]/")


# —— fetch_url_text 集成测试(mock requests 验证不真发请求) ——

def test_fetch_url_text_rejects_ssrf_before_request(monkeypatch):
    """内网 URL 在发 requests.get 前就被拒(不发任何网络请求)。"""
    # 让 requests.get 永远抛(如果 SSRF 校验漏了,这里会暴露)
    called = {"count": 0}

    def fake_get(*a, **kw):
        called["count"] += 1
        raise RuntimeError("不应该真发请求!")

    fake_requests = type("R", (), {"get": staticmethod(fake_get)})()
    monkeypatch.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    with pytest.raises(kb_llm.LLMError):
        kb_llm.fetch_url_text("http://169.254.169.254/latest/meta-data/")
    assert called["count"] == 0, "SSRF 校验应在 requests.get 之前拦截"


def test_fetch_url_text_rejects_redirect_to_internal(monkeypatch):
    """重定向到内网地址也应被拒。"""
    # 模拟:第一次返回 302 重定向到 169.254.169.254
    class FakeResp:
        def __init__(self, status, location=None):
            self.status_code = status
            self.headers = {"Location": location} if location else {}
            self.url = "http://attacker.com/"
            self.encoding = "utf-8"
            self.text = ""
        @property
        def is_redirect(self):
            return 300 <= self.status_code < 400 and "Location" in self.headers
        @property
        def is_permanent_redirect(self):
            return self.status_code == 301

    calls = []
    def fake_get(url, *a, **kw):
        calls.append(url)
        if "attacker.com" in url:
            return FakeResp(302, location="http://169.254.169.254/")
        return FakeResp(200)

    # staticmethod 避免被当作绑定方法(self 吃掉第一个参数)
    fake_requests = type("R", (), {"get": staticmethod(fake_get)})()
    monkeypatch.setattr(kb_llm, "_import_requests", lambda: fake_requests)

    with pytest.raises(kb_llm.LLMError) as exc_info:
        kb_llm.fetch_url_text("http://attacker.com/redirect")
    # 错误信息应提到内部地址
    assert "内部" in str(exc_info.value) or "保留" in str(exc_info.value)
