"""任务(Task)功能测试 —— CRUD + checklist 单项打勾 + 同步到日历 + Web API。

范式照搬 test_events.py:纯函数层(直接调 kb.*)+ Web API 层(TestClient)。
用 isolate_vault fixture 隔离真实 vault。
重点测试 checklist 的 JSON 序列化/反序列化 + 单项打勾端点(events 没有的新模式)。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


# —— 纯函数层:直接调 kb.* ——

def test_make_task_id_stable_prefix(isolate_vault):
    tid = kb.make_task_id("写综述初稿")
    assert tid.startswith("task_")
    assert len(tid) > len("task_")
    tid2 = kb.make_task_id("另一个任务")
    assert tid != tid2


def test_write_and_load_task_file_roundtrip(isolate_vault):
    """写 → 读 roundtrip,重点验证 checklist JSON 序列化/反序列化。"""
    tmp = isolate_vault
    path = tmp / "07_Tasks" / "task_abc12345.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": "task_abc12345",
        "title": "写综述初稿",
        "category": "写作",
        "status": "active",
        "deadline": "2026-08-15",
        "blocker": "缺参考文献",
        "checklist": [
            {"id": "cli_1", "text": "列大纲", "done": True},
            {"id": "cli_2", "text": "写引言", "done": False},
        ],
        "related_source": "",
        "synced_calendar_ids": "cal_x1,cal_x2",
        "created_at": "2026-07-22T10:00:00",
        "updated_at": "2026-07-22T10:00:00",
    }
    kb.write_task_file(path, meta, "任务背景", is_new=False)
    assert path.exists()

    loaded = kb.load_task_file(path)
    assert loaded["id"] == "task_abc12345"
    assert loaded["title"] == "写综述初稿"
    assert loaded["category"] == "写作"
    assert loaded["status"] == "active"
    assert loaded["deadline"] == "2026-08-15"
    assert loaded["blocker"] == "缺参考文献"
    # checklist 解析回 list[dict]
    assert isinstance(loaded["checklist"], list)
    assert len(loaded["checklist"]) == 2
    assert loaded["checklist"][0] == {"id": "cli_1", "text": "列大纲", "done": True}
    assert loaded["checklist"][1]["done"] is False
    # synced_calendar_ids 解析回 list
    assert loaded["synced_calendar_ids"] == ["cal_x1", "cal_x2"]
    assert loaded["body"] == "任务背景"


def test_load_task_file_empty_checklist(isolate_vault):
    """无 checklist 的任务,load 后 checklist 为空 list(不报错)。"""
    tmp = isolate_vault
    path = tmp / "07_Tasks" / "task_empty.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": "task_empty", "title": "简单任务", "category": "其他",
        "status": "active", "deadline": "", "blocker": "",
        "checklist": [], "related_source": "", "synced_calendar_ids": "",
        "created_at": "", "updated_at": "",
    }
    kb.write_task_file(path, meta, "", is_new=False)
    loaded = kb.load_task_file(path)
    assert loaded["checklist"] == []
    assert loaded["deadline"] == ""


def test_load_task_file_corrupt_checklist_fallback(isolate_vault):
    """checklist JSON 损坏时,降级为空 list(不抛异常)。"""
    tmp = isolate_vault
    path = tmp / "07_Tasks" / "task_bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 手写一个 checklist 字段是非法 JSON 的文件
    content = (
        "---\n"
        "id: task_bad\n"
        "title: 坏任务\n"
        "category: 其他\n"
        "status: active\n"
        "deadline: ''\n"
        "blocker: ''\n"
        "checklist: {这不是合法json\n"
        "related_source: ''\n"
        "synced_calendar_ids: ''\n"
        "created_at: ''\n"
        "updated_at: ''\n"
        "---\n\n正文\n"
    )
    (tmp / "07_Tasks" / "task_bad.md").write_text(content, encoding="utf-8")
    loaded = kb.load_task_file(path)
    assert loaded["checklist"] == []  # 降级,不抛


def test_scan_tasks_sorts_by_deadline(isolate_vault):
    """scan_tasks 按 deadline 升序,无 deadline 排末尾。"""
    tmp = isolate_vault
    d = tmp / "07_Tasks"
    d.mkdir(parents=True, exist_ok=True)
    for tid, dl in [("task_a", "2026-09-01"), ("task_b", "2026-08-01"), ("task_c", "")]:
        meta = {"id": tid, "title": tid, "category": "其他", "status": "active",
                "deadline": dl, "blocker": "", "checklist": [],
                "related_source": "", "synced_calendar_ids": "", "created_at": "", "updated_at": ""}
        kb.write_task_file(d / f"{tid}.md", meta, "", is_new=False)
    tasks = kb.scan_tasks()
    titles = [t["title"] for t in tasks]
    assert titles == ["task_b", "task_a", "task_c"]  # 8月 < 9月 < 无deadline


def test_find_task_file_frontmatter_fallback(isolate_vault):
    """文件名不含 task_id 但 frontmatter id 匹配时,扫描兜底找到。"""
    tmp = isolate_vault
    d = tmp / "07_Tasks"
    d.mkdir(parents=True, exist_ok=True)
    # 文件名是 task_xyz.md 但 frontmatter id 是 task_real
    content = (
        "---\n"
        "id: task_real\n"
        "title: 测试\n"
        "category: 其他\n"
        "status: active\n"
        "deadline: ''\n"
        "blocker: ''\n"
        "checklist: []\n"
        "related_source: ''\n"
        "synced_calendar_ids: ''\n"
        "created_at: ''\n"
        "updated_at: ''\n"
        "---\n\nx\n"
    )
    (d / "task_xyz.md").write_text(content, encoding="utf-8")
    found = kb._find_task_file("task_real")
    assert found is not None
    assert found.name == "task_xyz.md"


def test_sync_task_to_calendar_no_deadline(isolate_vault):
    """无 deadline 的任务同步返回 task_has_no_deadline。"""
    tmp = isolate_vault
    d = tmp / "07_Tasks"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": "task_nodl", "title": "无截止", "category": "其他", "status": "active",
            "deadline": "", "blocker": "", "checklist": [],
            "related_source": "", "synced_calendar_ids": "", "created_at": "", "updated_at": ""}
    kb.write_task_file(d / "task_nodl.md", meta, "", is_new=False)
    result = kb.sync_task_to_calendar("task_nodl")
    assert result["synced"] is False
    assert result["reason"] == "task_has_no_deadline"


def test_sync_task_to_calendar_creates_item(isolate_vault):
    """有 deadline 的任务同步成功,创建日历项,回指 task_id,幂等。"""
    tmp = isolate_vault
    d = tmp / "07_Tasks"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": "task_dl", "title": "有截止", "category": "写作", "status": "active",
            "deadline": "2026-09-01", "blocker": "", "checklist": [],
            "related_source": "", "synced_calendar_ids": "", "created_at": "", "updated_at": ""}
    kb.write_task_file(d / "task_dl.md", meta, "", is_new=False)

    r1 = kb.sync_task_to_calendar("task_dl")
    assert r1["synced"] is True
    assert r1["reason"] == "created"
    cal_id = r1["calendar_id"]
    assert cal_id.startswith("cal_")

    # 日历项有 task_id 回指 + source_type=task
    cal = kb.load_calendar()
    item = cal["items"][cal_id]
    assert item["source_type"] == "task"
    assert item["task_id"] == "task_dl"
    assert item["date"] == "2026-09-01"
    assert item["category"] == "截止日期"

    # 幂等:再同步不重复创建
    r2 = kb.sync_task_to_calendar("task_dl")
    assert r2["synced"] is False
    assert r2["reason"] == "already_synced"
    assert r2["calendar_id"] == cal_id


# —— Web API 层:TestClient ——

@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


def _create_task_via_api(client, title="测试任务", **kw):
    payload = {"title": title, "category": "开发", "status": "active",
               "deadline": "2026-09-01", "blocker": "", "body": "描述", "checklist": []}
    payload.update(kw)
    r = client.post("/api/tasks", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["task"]


def test_api_create_task(client):
    t = _create_task_via_api(client, title="API任务", checklist=[
        {"id": "c1", "text": "步骤一", "done": False}])
    assert t["id"].startswith("task_")
    assert t["title"] == "API任务"
    assert len(t["checklist"]) == 1
    assert t["checklist"][0]["text"] == "步骤一"


def test_api_create_task_empty_title_400(client):
    r = client.post("/api/tasks", json={"title": "  "})
    assert r.status_code == 400


def test_api_create_task_bad_deadline_400(client):
    r = client.post("/api/tasks", json={"title": "x", "deadline": "not-a-date"})
    assert r.status_code == 400


def test_api_create_task_bad_status_400(client):
    r = client.post("/api/tasks", json={"title": "x", "status": "invalid"})
    assert r.status_code == 400


def test_api_get_update_delete_task(client):
    t = _create_task_via_api(client, title="待改")
    tid = t["id"]
    # GET
    r = client.get(f"/api/tasks/{tid}")
    assert r.status_code == 200
    assert r.json()["title"] == "待改"
    # PATCH(改标题 + blocker)
    r = client.patch(f"/api/tasks/{tid}", json={"title": "改后", "blocker": "卡住了"})
    assert r.status_code == 200
    assert r.json()["task"]["title"] == "改后"
    assert r.json()["task"]["blocker"] == "卡住了"
    # DELETE
    r = client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 200
    # 再 GET 应 404
    assert client.get(f"/api/tasks/{tid}").status_code == 404


def test_api_get_task_404(client):
    assert client.get("/api/tasks/task_notexist").status_code == 404


def test_api_checklist_toggle_single(client):
    """单项打勾端点:只改一个 checklist 项的 done,不碰其他。"""
    t = _create_task_via_api(client, title="带清单", checklist=[
        {"id": "i1", "text": "A", "done": False},
        {"id": "i2", "text": "B", "done": False}])
    tid = t["id"]
    # 打勾 i1
    r = client.patch(f"/api/tasks/{tid}/checklist/i1", json={"done": True})
    assert r.status_code == 200
    cl = r.json()["task"]["checklist"]
    assert cl[0]["done"] is True
    assert cl[1]["done"] is False  # i2 不受影响
    # 取消 i1
    r = client.patch(f"/api/tasks/{tid}/checklist/i1", json={"done": False})
    assert r.json()["task"]["checklist"][0]["done"] is False
    # 不存在的 item_id → 404
    r = client.patch(f"/api/tasks/{tid}/checklist/nope", json={"done": True})
    assert r.status_code == 404


def test_api_checklist_toggle_404_task(client):
    r = client.patch("/api/tasks/task_none/checklist/x", json={"done": True})
    assert r.status_code == 404


def test_api_sync_calendar_idempotent(client):
    """Web 同步日历:成功后幂等。"""
    t = _create_task_via_api(client, title="要同步", deadline="2026-10-01")
    tid = t["id"]
    r1 = client.post(f"/api/tasks/{tid}/sync-calendar")
    assert r1.status_code == 200
    assert r1.json()["reason"] == "created"
    r2 = client.post(f"/api/tasks/{tid}/sync-calendar")
    assert r2.json()["reason"] == "already_synced"


def test_api_sync_calendar_no_deadline_400(client):
    t = _create_task_via_api(client, title="无截止", deadline="")
    r = client.post(f"/api/tasks/{t['id']}/sync-calendar")
    assert r.status_code == 400


def test_task_pages_render_200(client):
    """列表页 + 详情页渲染 200。"""
    assert client.get("/tasks").status_code == 200
    t = _create_task_via_api(client, title="详情测试")
    r = client.get(f"/task/{t['id']}")
    assert r.status_code == 200
    assert "详情测试" in r.text or "task-detail" in r.text


def test_task_detail_404(client):
    assert client.get("/task/task_notexist").status_code == 404


def test_api_tasks_list(client):
    _create_task_via_api(client, title="T1")
    _create_task_via_api(client, title="T2")
    r = client.get("/api/tasks")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 2
    titles = [t["title"] for t in items]
    assert "T1" in titles and "T2" in titles
