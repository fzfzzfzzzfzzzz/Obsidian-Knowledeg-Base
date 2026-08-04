#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_plans.py —— Plan(计划)独立文件 + deadline 字段测试。

v0.4.23 重构:plan 不再按 weekly/monthly/someday 分桶,改为独立文件 + deadline。
测试覆盖:make_plan_id / _plan_file_path / write_plan_file / load_plan_file /
scan_plans / _find_plan_file / sync_plan_to_calendar / move_accepted_plan(Web 路径)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kb
import kb_entities
import kb_web


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


# ---- roundtrip:write + load 完整字段 ----

def test_write_load_plan_roundtrip(isolate_vault):
    """plan frontmatter 写入 + 读回全字段。"""
    tmp = isolate_vault
    path = tmp / "04_Plans" / "plan_test01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": "plan_test01",
        "title": "测试 plan",
        "deadline": "2026-08-15",
        "status": "active",
        "source_summary": "[[summary_xxx]]",
        "related_source": "source_ff_abc",
        "synced_calendar_ids": "cal_x1,cal_x2",
        "created_at": "2026-08-01T10:00:00",
        "updated_at": "2026-08-01T10:00:00",
    }
    kb.write_plan_file(path, meta, "plan 描述正文", is_new=True)
    assert path.exists()

    loaded = kb.load_plan_file(path)
    assert loaded["id"] == "plan_test01"
    assert loaded["title"] == "测试 plan"
    assert loaded["deadline"] == "2026-08-15"
    assert loaded["status"] == "active"
    assert loaded["source_summary"] == "[[summary_xxx]]"
    assert loaded["related_source"] == "source_ff_abc"
    assert loaded["synced_calendar_ids"] == ["cal_x1", "cal_x2"]
    assert loaded["body"] == "plan 描述正文"
    # is_new=True 应自动补 created_at
    assert loaded["created_at"]  # 非空


def test_load_plan_file_deadline_defaults_empty(isolate_vault):
    """旧 plan 文件无 deadline 字段,load 后默认空串(不报错)。"""
    tmp = isolate_vault
    path = tmp / "04_Plans" / "plan_legacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        "id: plan_legacy\n"
        "title: 老 plan\n"
        "status: active\n"
        "source_summary: ''\n"
        "related_source: ''\n"
        "synced_calendar_ids: ''\n"
        "created_at: ''\n"
        "updated_at: ''\n"
        "completed_at: ''\n"
        "---\n\n正文\n"
    )
    path.write_text(content, encoding="utf-8")
    loaded = kb.load_plan_file(path)
    assert loaded["deadline"] == ""
    assert loaded["status"] == "active"


def test_write_plan_file_completed_at_lifecycle(isolate_vault):
    """completed_at 生命周期:首次 done 写入,重复 done 不覆盖,重新激活清空。"""
    tmp = isolate_vault
    path = tmp / "04_Plans" / "plan_lifecycle.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"id": "plan_lifecycle", "title": "生命周期", "status": "done", "deadline": ""}
    kb.write_plan_file(path, meta, "", is_new=True)
    loaded1 = kb.load_plan_file(path)
    assert loaded1["completed_at"]  # 首次 done 自动写
    first_done = loaded1["completed_at"]
    # 重复标 done,completed_at 不覆盖
    kb.write_plan_file(path, {**meta, "status": "done"}, "", is_new=False)
    loaded2 = kb.load_plan_file(path)
    assert loaded2["completed_at"] == first_done
    # 重新激活,completed_at 清空
    kb.write_plan_file(path, {**meta, "status": "active"}, "", is_new=False)
    loaded3 = kb.load_plan_file(path)
    assert loaded3["completed_at"] == ""


# ---- make_plan_id / _find_plan_file / scan_plans ----

def test_make_plan_id_prefix_and_unique(isolate_vault):
    """make_plan_id 返回 plan_<hash>,两次生成不重复。"""
    id1 = kb.make_plan_id("标题A")
    id2 = kb.make_plan_id("标题B")
    assert id1.startswith("plan_")
    assert id2.startswith("plan_")
    assert id1 != id2


def test_scan_plans_returns_sorted_by_deadline(isolate_vault):
    """scan_plans 按 deadline 升序,无 deadline 的排末尾。"""
    tmp = isolate_vault
    plans_dir = tmp / "04_Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    # 三条 plan:deadline 2026-09-01、2026-08-01、无 deadline
    for fname, dl in [("plan_001.md", "2026-09-01"),
                      ("plan_002.md", "2026-08-01"),
                      ("plan_003.md", "")]:
        meta = {"id": fname.replace(".md", ""), "title": fname,
                "deadline": dl, "status": "active"}
        kb.write_plan_file(plans_dir / fname, meta, "", is_new=True)
    result = kb.scan_plans()
    assert len(result) == 3
    assert result[0]["deadline"] == "2026-08-01"
    assert result[1]["deadline"] == "2026-09-01"
    assert result[2]["deadline"] == ""  # 无 deadline 排末尾


def test_scan_plans_excludes_suggestions(isolate_vault):
    """scan_plans 排除 plan_suggestions.md(review 队列,不是独立 plan)。"""
    tmp = isolate_vault
    plans_dir = tmp / "04_Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    # 写一个 review 队列文件(也匹配 plan_*.md glob)
    sug = plans_dir / "plan_suggestions.md"
    sug.write_text("# Plan Suggestions\n\n## Plan Suggestion: x\n\n- id: foo\n- status: pending_review\n", encoding="utf-8")
    # 写一个真正的 plan 文件
    meta = {"id": "plan_real01", "title": "真 plan", "status": "active", "deadline": ""}
    kb.write_plan_file(plans_dir / "plan_real01.md", meta, "", is_new=True)
    result = kb.scan_plans()
    assert len(result) == 1
    assert result[0]["id"] == "plan_real01"


def test_find_plan_file_by_id(isolate_vault):
    """_find_plan_file 通过 frontmatter id 找到文件。"""
    tmp = isolate_vault
    plans_dir = tmp / "04_Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    meta = {"id": "plan_findme", "title": "找得到吗", "status": "active", "deadline": ""}
    kb.write_plan_file(plans_dir / "plan_findme.md", meta, "", is_new=True)
    found = kb._find_plan_file("plan_findme")
    assert found is not None
    assert found.name == "plan_findme.md"


def test_find_plan_file_not_found(isolate_vault):
    """_find_plan_file 找不到返回 None。"""
    assert kb._find_plan_file("plan_nonexistent") is None


# ---- Web 路径:accept + move_accepted_plan ----

def _create_plan_suggestion(isolate_vault, title="测试 plan suggestion"):
    """在 plan_suggestions.md 里追加一条 pending_review 的 plan suggestion。"""
    tmp = isolate_vault
    sug_path = tmp / "04_Plans" / "plan_suggestions.md"
    sug_path.parent.mkdir(parents=True, exist_ok=True)
    item_id = f"plan_sug_{title[:6]}"
    block = (
        f"\n## Plan Suggestion: {title}\n\n"
        f"- id: {item_id}\n"
        f"- status: pending_review\n"
        f"- source_summary: [[summary_xxx]]\n\n"
        f"描述正文\n"
    )
    with sug_path.open("a", encoding="utf-8") as fh:
        fh.write(block)
    return item_id


def test_move_accepted_plan_creates_independent_file(isolate_vault):
    """move_accepted_plan:accepted 状态 → 创建独立 plan_*.md 文件,deadline 落盘。"""
    item_id = _create_plan_suggestion(isolate_vault, title="接受后独立")
    # 手动标 accepted
    sug_path = isolate_vault / "04_Plans" / "plan_suggestions.md"
    text = sug_path.read_text(encoding="utf-8")
    text = text.replace("status: pending_review", "status: accepted")
    sug_path.write_text(text, encoding="utf-8")
    # 调 move
    result = kb.move_accepted_plan(item_id, deadline="2026-09-01")
    assert result["moved"] is True
    assert result["plan_id"].startswith("plan_")
    # 独立文件存在 + deadline 正确
    plan_path = isolate_vault / result["target"]
    assert plan_path.exists()
    plan = kb.load_plan_file(plan_path)
    assert plan["deadline"] == "2026-09-01"
    assert plan["status"] == "active"
    # 原 suggestion 标 moved
    new_sug = sug_path.read_text(encoding="utf-8")
    assert "status: moved" in new_sug


def test_move_accepted_plan_no_deadline(isolate_vault):
    """move_accepted_plan 不填 deadline → 生成独立文件,deadline 为空。"""
    item_id = _create_plan_suggestion(isolate_vault, title="无截止")
    sug_path = isolate_vault / "04_Plans" / "plan_suggestions.md"
    text = sug_path.read_text(encoding="utf-8").replace("status: pending_review", "status: accepted")
    sug_path.write_text(text, encoding="utf-8")
    result = kb.move_accepted_plan(item_id, deadline="")
    assert result["moved"] is True
    plan = kb.load_plan_file(isolate_vault / result["target"])
    assert plan["deadline"] == ""


def test_move_accepted_plan_idempotent(isolate_vault):
    """已经 moved 的 suggestion 不重复搬。"""
    item_id = _create_plan_suggestion(isolate_vault, title="幂等")
    sug_path = isolate_vault / "04_Plans" / "plan_suggestions.md"
    text = sug_path.read_text(encoding="utf-8")
    text = text.replace("status: pending_review", "status: accepted")
    sug_path.write_text(text, encoding="utf-8")
    r1 = kb.move_accepted_plan(item_id, deadline="2026-09-01")
    assert r1["moved"] is True
    # 第二次:状态已是 moved,不再搬
    r2 = kb.move_accepted_plan(item_id, deadline="2026-09-01")
    assert r2["moved"] is False
    assert r2["reason"] == "not_found_or_not_accepted"


def test_move_accepted_plan_not_found(isolate_vault):
    """item_id 不在 accepted 列表 → 不搬。"""
    r = kb.move_accepted_plan("plan_sug_nonexistent", deadline="2026-09-01")
    assert r["moved"] is False
    assert r["reason"] == "not_found_or_not_accepted"


def test_api_plan_confirmed_returns_scan_plans(client, isolate_vault):
    """GET /api/plans/confirmed 返回独立 plan 文件列表(带 deadline)。"""
    # 写一个真实 plan 文件
    plans_dir = isolate_vault / "04_Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    meta = {"id": "plan_api01", "title": "API 测试 plan",
            "deadline": "2026-09-15", "status": "active", "source_summary": ""}
    kb.write_plan_file(plans_dir / "plan_api01.md", meta, "正文", is_new=True)
    r = client.get("/api/plans/confirmed")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "plan_api01"
    assert items[0]["deadline"] == "2026-09-15"


def test_api_plan_accept_creates_file(client, isolate_vault):
    """POST /api/plan/{id}/status 接受 → 创建独立 plan 文件。"""
    item_id = _create_plan_suggestion(isolate_vault, title="Web 接受")
    r = client.post(f"/api/plan/{item_id}/status", json={
        "status": "accepted", "deadline": "2026-10-01"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["moved"] is True
    assert "plan_" in data.get("moved_to", "") or Path(data.get("moved_to", "")).name.startswith("plan_")
    # scan_plans 应能扫到
    plans = kb.scan_plans()
    assert len(plans) == 1
    assert plans[0]["deadline"] == "2026-10-01"


# ---- 手动新建 plan(POST /api/plans → 进待定队列)----

def test_api_plans_create_appends_to_suggestions(client, isolate_vault):
    """POST /api/plans 手动新建 → 追加到 plan_suggestions.md,GET /api/plans 能读回。"""
    r = client.post("/api/plans", json={"title": "手动新建的 plan"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["title"] == "手动新建的 plan"
    assert data["id"].startswith("plan_suggestion_")
    # 文件确实写入了
    sug_path = isolate_vault / "04_Plans" / "plan_suggestions.md"
    assert sug_path.exists()
    content = sug_path.read_text(encoding="utf-8")
    assert "## Plan Suggestion: 手动新建的 plan" in content
    assert "status: pending_review" in content
    # GET /api/plans 能解析回来,且包含这条
    items = client.get("/api/plans").json()["items"]
    titles = [it.get("title") for it in items]
    assert "手动新建的 plan" in titles


def test_api_plans_create_empty_title_400(client, isolate_vault):
    """空标题 → 400。"""
    r = client.post("/api/plans", json={"title": "   "})
    assert r.status_code == 400


def test_api_plans_create_id_unique(client, isolate_vault):
    """连续新建两条 → id 不同(随机后缀防撞)。"""
    r1 = client.post("/api/plans", json={"title": "相同标题"})
    r2 = client.post("/api/plans", json={"title": "相同标题"})
    assert r1.json()["id"] != r2.json()["id"]
