"""summary / source note HTML 消毒(v0.4.6)。

验证后端 sanitize_html 在 cards.py 两处 md.markdown 调用后生效,
用户投稿含 <script>/<img onerror>/javascript: 等危险标签时被剥离。
"""
import json

import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离 vault,预置 state + summary 文件。"""
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb, "RAW_TEXT_DIR", kb_dir / "raw_text")
    monkeypatch.setattr(kb, "LOGS_DIR", kb_dir / "logs")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    return TestClient(kb_web.app), tmp_path


def _seed_source_with_summary(tmp_path, sid, summary_body):
    """建一个 source + summary,summary 正文用 summary_body。"""
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "sources": {
            sid: {
                "source_id": sid,
                "path": f"01_Sources/x/{sid}.md",
                "source_type": "x",
                "source_title": "测试 source",
                "created_at": "2026-07-20",
                "summary_path": f"02_Summaries/x/summary_{sid}.md",
            }
        },
    }
    (kb_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    sum_path = tmp_path / "02_Summaries" / "x" / f"summary_{sid}.md"
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    sum_path.write_text(
        f"---\nsource_id: {sid}\nsource_title: 测试\n---\n\n{summary_body}\n",
        encoding="utf-8",
    )


# —— summary HTML 消毒 ——

def test_summary_html_strips_script_tag(client):
    """summary 含 <script> → 渲染后 html_body 不含 script。"""
    c, tmp = client
    sid = "source_ff_sanitize1"
    _seed_source_with_summary(tmp, sid, "正常文本\n\n<script>alert(1)</script>\n\n后续")
    r = c.get(f"/api/summary/{sid}")
    assert r.status_code == 200
    html = r.json()["html_body"]
    assert "<script>" not in html.lower()
    assert "<script" not in html.lower()
    # 正文文本保留
    assert "正常文本" in html
    assert "后续" in html


def test_summary_html_strips_onerror(client):
    """summary 含 <img onerror=...> → onerror 属性被剥离。"""
    c, tmp = client
    sid = "source_ff_sanitize2"
    _seed_source_with_summary(tmp, sid, '<img src=x onerror=alert(1)>')
    r = c.get(f"/api/summary/{sid}")
    html = r.json()["html_body"]
    assert "onerror" not in html.lower()
    # img 标签本身可能保留(src 是无害属性),但无 onerror
    assert "alert(1)" not in html


def test_summary_html_strips_javascript_protocol(client):
    """<a href="javascript:..."> → href 被剥离(javascript 协议不在白名单)。"""
    c, tmp = client
    sid = "source_ff_sanitize3"
    _seed_source_with_summary(tmp, sid, '<a href="javascript:alert(1)">click me</a>')
    r = c.get(f"/api/summary/{sid}")
    html = r.json()["html_body"]
    assert "javascript:" not in html.lower()
    assert "alert(1)" not in html


def test_summary_html_strips_iframe(client):
    """<iframe> 不在白名单 → 被剥离。"""
    c, tmp = client
    sid = "source_ff_sanitize4"
    _seed_source_with_summary(tmp, sid, '<iframe src="http://evil.com"></iframe>')
    r = c.get(f"/api/summary/{sid}")
    html = r.json()["html_body"]
    assert "<iframe" not in html.lower()
    assert "evil.com" not in html


def test_summary_html_preserves_safe_tags(client):
    """正常 markdown 标签(p/strong/a/pre/code)应保留。"""
    c, tmp = client
    sid = "source_ff_sanitize5"
    body = "## 标题\n\n**加粗** 和 *斜体*\n\n[链接](https://example.com)\n\n```\ncode\n```"
    _seed_source_with_summary(tmp, sid, body)
    r = c.get(f"/api/summary/{sid}")
    html = r.json()["html_body"]
    assert "<h2>" in html  # markdown ## 渲染
    assert "<strong>" in html
    assert "<a href=\"https://example.com\"" in html
    assert "<pre>" in html or "<code>" in html


# —— 回退分支:source note 原始内容 ——

def test_source_note_html_strips_script(client):
    """无 summary 时回退读 source note 的「原始内容」段,同样消毒。"""
    c, tmp = client
    sid = "source_ff_sanitize6"
    # 不写 summary(回退走 source note 路径)
    kb_dir = tmp / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "sources": {
            sid: {
                "source_id": sid,
                "path": f"01_Sources/x/{sid}.md",
                "source_type": "x",
                "source_title": "测试 source",
                "created_at": "2026-07-20",
                # 无 summary_path → 触发回退
            }
        },
    }
    (kb_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    # source note 含危险内容
    src_path = tmp / "01_Sources" / "x" / f"{sid}.md"
    src_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.write_text(
        f"---\nsource_id: {sid}\n---\n\n## 原始内容\n\n<script>evil()</script>\n正文\n",
        encoding="utf-8",
    )
    r = c.get(f"/api/summary/{sid}")
    assert r.status_code == 200
    html = r.json()["html_body"]
    assert "<script" not in html.lower()
    assert "正文" in html
