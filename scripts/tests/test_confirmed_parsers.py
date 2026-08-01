"""已确定 idea/todo 的解析器测试。

用隔离 vault 写入模拟的正式清单文件(格式同 _format_formal_idea / _format_weekly_task 落盘),
验证 _parse_formal_ideas / _parse_formal_plans 正确解析 + API 返回。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    return TestClient(kb_web.app), tmp_path

# 模拟正式 idea 文件(格式同 kb._format_formal_idea)
FORMAL_IDEA = """# Research Ideas

## Idea: 多模型 Agent 调度

- id: idea_20260717_多模型agent调度
- status: candidate
- maturity: spark
- priority: P1
- sources:
  - [[summary_source_test]]
- estimated_investment: 3-5 days
- main_challenges:
  - medium 可行性 / high 新颖度

这是 idea 的正文。
可以有多段。

## Idea: 并行编辑器插件

- id: idea_20260717_并行编辑器插件
- status: thinking
- maturity: rough
- priority: P2
- sources:
  - [[summary_source_test2]]

正文2。
"""

# 模拟 weekly 文件(格式同 kb._ensure_weekly_file + _format_weekly_task)
WEEKLY_FILE = """# Weekly Plan: 2026-W29

## 本周重点

- [ ] 跑通 Zed 编辑器 demo
  - 来源:[[summary_source_test]]
  - 预计时间:2-4h
  - 难度:medium
  - 难点:配置复杂

## Research

- [x] 读 ACP 协议文档
  - 来源:[[summary_source_test2]]
  - 预计时间:1h

## Review

- [ ] Review pending summaries
"""

SOMEDAY_FILE = """# Someday Plan

> 暂存,有空再做。

- [ ] 学 Rust
  - 难度:high
"""

def test_parse_formal_ideas_basic(client):
    c, tmp = client
    ideas_dir = tmp / "03_Ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "research_ideas.md").write_text(FORMAL_IDEA, encoding="utf-8")
    # review 队列文件应被排除
    (ideas_dir / "idea_suggestions.md").write_text("# ignore\n", encoding="utf-8")

    items = kb_web._parse_formal_ideas()
    assert len(items) == 2
    titles = [i["title"] for i in items]
    assert "多模型 Agent 调度" in titles
    assert "并行编辑器插件" in titles
    # area 从文件名推断
    assert all(i["area"] == "research" for i in items)
    # 字段解析
    first = next(i for i in items if "多模型" in i["title"])
    assert first["priority"] == "P1"
    assert first["maturity"] == "spark"
    assert first["status"] == "candidate"
    assert "正文" in first["body"]

def test_parse_formal_ideas_empty_when_no_dir(client):
    c, tmp = client
    # 没建 03_Ideas 目录
    assert kb_web._parse_formal_ideas() == []

def test_parse_formal_ideas_empty_file(client):
    c, tmp = client
    ideas_dir = tmp / "03_Ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "research_ideas.md").write_text("# Research Ideas\n\n", encoding="utf-8")
    assert kb_web._parse_formal_ideas() == []

def test_parse_formal_plans_empty(client):
    c, tmp = client
    # 没建任何文件
    assert kb_web._parse_formal_plans() == []

def test_api_ideas_confirmed(client):
    c, tmp = client
    ideas_dir = tmp / "03_Ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "research_ideas.md").write_text(FORMAL_IDEA, encoding="utf-8")

    r = c.get("/api/ideas/confirmed")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["area"] == "research"

def test_api_confirmed_empty_when_no_files(client):
    c, tmp = client
    # 没有任何正式清单文件
    assert c.get("/api/ideas/confirmed").json()["items"] == []
    assert c.get("/api/plans/confirmed").json()["items"] == []
