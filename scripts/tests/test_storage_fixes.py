"""v0.4.12 存储层修复的回归测试。

覆盖审查发现并修复的问题:
- S1: state/calendar 锁 + web 端点不嵌套死锁
- S3: _corrupt 拒绝写
- M1: now_ts / today_iso 时区感知
- M2: event completed_at 生命周期
- M3: scan 损坏文件备份+日志(不静默)
- M4: suggestion block id 唯一性
- M5: cleanup_calendar_ref / cleanup_source_ref 清理悬空引用
- toggle 持久化回归(修复 _ensure_reading_fields 副本不写回的 bug)
"""
import re

import pytest
from fastapi.testclient import TestClient

import kb
import kb_web


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


# ---------------------------------------------------------------------------
# S3: _corrupt 拒绝写(防用空骨架覆盖损坏文件)
# ---------------------------------------------------------------------------

def test_check_corrupt_raises(isolate_vault):
    """带 _corrupt 标记的 store 应抛 CorruptStoreError(正常 dict 不抛,由 web 集成测试覆盖)。"""
    with pytest.raises(kb.CorruptStoreError):
        kb._check_corrupt({"_corrupt": True, "_corrupt_error": "x"}, "state")


def test_web_write_rejects_corrupt_state(isolate_vault):
    """state 损坏时,web 写路径应 503 而非用空骨架覆盖。"""
    kb.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    kb.STATE_FILE.write_text("{这不是合法json", encoding="utf-8")
    with TestClient(kb_web.app) as c:
        r = c.post("/api/collections", json={"name": "夹"})
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# M1: 时区感知时间戳
# ---------------------------------------------------------------------------

def test_now_ts_format(isolate_vault):
    ts = kb.now_ts()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", ts), f"格式错: {ts}"


def test_today_iso_format(isolate_vault):
    d = kb.today_iso()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"格式错: {d}"


# ---------------------------------------------------------------------------
# M2: event completed_at 生命周期(与 task 对称)
# ---------------------------------------------------------------------------

def test_event_completed_at_lifecycle(isolate_vault):
    ev_dir = kb.VAULT_ROOT / "06_Events"
    ev_dir.mkdir(parents=True, exist_ok=True)
    path = ev_dir / "event_test01.md"
    meta = {
        "id": "ev1", "title": "会议", "date": "2026-07-22", "category": "会议",
        "note": "", "status": "active", "related_source": "", "synced_calendar_ids": "",
    }
    kb.write_event_file(path, meta, "", is_new=True)
    assert kb.load_event_file(path)["completed_at"] == ""

    # active → done:写 completed_at
    m = kb.load_event_file(path)
    m["status"] = "done"
    kb.write_event_file(path, m, "", is_new=False)
    first = kb.load_event_file(path)["completed_at"]
    assert first, "done 应有 completed_at"

    # 重复 done:保留首次
    m = kb.load_event_file(path)
    m["title"] = "改名"
    kb.write_event_file(path, m, "", is_new=False)
    assert kb.load_event_file(path)["completed_at"] == first

    # done → active:清空
    m = kb.load_event_file(path)
    m["status"] = "active"
    kb.write_event_file(path, m, "", is_new=False)
    assert kb.load_event_file(path)["completed_at"] == ""


# ---------------------------------------------------------------------------
# M3: scan 损坏文件备份+日志(不静默 continue)
# ---------------------------------------------------------------------------

def test_log_scan_error_creates_backup_and_log(isolate_vault):
    """_log_scan_error 应备份损坏文件 + 记日志(M3)。"""
    tasks_dir = kb.VAULT_ROOT / "07_Tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    bad = tasks_dir / "task_bad.md"
    bad.write_text("损坏内容", encoding="utf-8")
    kb._log_scan_error(bad, ValueError("解析失败"))
    log_file = kb.LOGS_DIR / "kb.log"
    assert log_file.exists()
    assert "task_bad.md" in log_file.read_text(encoding="utf-8")
    backups = list(kb.LOGS_DIR.glob("corrupt_task_bad_*.md"))
    assert backups, "应有损坏文件备份"


def test_scan_swallows_load_error(isolate_vault, monkeypatch):
    """scan_tasks 对抛异常的文件应跳过(不崩),而非静默丢失整个列表(M3)。"""
    tasks_dir = kb.VAULT_ROOT / "07_Tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    # 一个正常 + 一个会让 load 抛异常的(通过 monkeypatch 模拟 IO/解析错误)
    good = tasks_dir / "task_good.md"
    kb.write_task_file(good, {
        "id": "g1", "title": "好任务", "category": "开发", "status": "active",
        "deadline": "", "blocker": "", "checklist": [], "related_source": "",
        "synced_calendar_ids": "",
    }, "", is_new=True)
    (tasks_dir / "task_bad.md").write_text("x", encoding="utf-8")

    real_load = kb.load_task_file
    call_count = {"n": 0}

    def flaky_load(path):
        call_count["n"] += 1
        if path.name == "task_bad.md":
            raise OSError("模拟 IO 错误")
        return real_load(path)

    monkeypatch.setattr(kb, "load_task_file", flaky_load)
    results = kb.scan_tasks()  # 不应抛
    assert len(results) == 1, "好任务应被收集,坏任务跳过"
    assert results[0]["id"] == "g1"


# ---------------------------------------------------------------------------
# M4: suggestion block id 唯一性(防同日同标题撞 id)
# ---------------------------------------------------------------------------

def test_suggestion_id_uniqueness(isolate_vault):
    info = {"source_type": "manual", "source_title": "T"}
    idea = {"title": "相同标题", "recommended_area": "research",
            "priority": "P1", "feasibility": "中", "novelty": "高"}
    ids = set()
    for _ in range(30):
        blk = kb._format_idea_suggestion("src1", info, idea, "2026-07-22")
        m = re.search(r"id: (idea_suggestion_\S+)", blk)
        ids.add(m.group(1))
    assert len(ids) == 30, f"30 次生成应有 30 个不同 id, 实际 {len(ids)}"


# ---------------------------------------------------------------------------
# M5: cleanup 清理悬空引用
# ---------------------------------------------------------------------------

def test_cleanup_calendar_ref(isolate_vault):
    tasks_dir = kb.VAULT_ROOT / "07_Tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / "task_t01.md"
    meta = {
        "id": "t01", "title": "任务", "category": "开发", "status": "active",
        "deadline": "2026-07-25", "blocker": "", "checklist": [],
        "related_source": "", "synced_calendar_ids": "cal_aaa,cal_bbb",
    }
    kb.write_task_file(path, meta, "", is_new=True)
    n = kb.cleanup_calendar_ref("cal_aaa")
    assert n >= 1
    synced = kb.load_task_file(path)["synced_calendar_ids"]
    assert "cal_aaa" not in synced
    assert "cal_bbb" in synced


def test_cleanup_source_ref(isolate_vault):
    tasks_dir = kb.VAULT_ROOT / "07_Tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / "task_t02.md"
    meta = {
        "id": "t02", "title": "任务2", "category": "开发", "status": "active",
        "deadline": "", "blocker": "", "checklist": [],
        "related_source": "source_del", "synced_calendar_ids": "",
    }
    kb.write_task_file(path, meta, "", is_new=True)
    n = kb.cleanup_source_ref("source_del")
    assert n >= 1
    assert kb.load_task_file(path)["related_source"] == ""


# ---------------------------------------------------------------------------
# toggle 持久化回归(修复 _ensure_reading_fields 副本不写回的 bug)
# ---------------------------------------------------------------------------

def _seed_source(source_id="src1"):
    kb.save_state({"version": 1, "sources": {
        source_id: {"source_title": "T", "source_type": "manual", "created_at": "2026-07-22"}
    }})


def test_toggle_favorite_persists(client, isolate_vault):
    _seed_source()
    r1 = client.post("/api/article/src1/favorite")
    r2 = client.post("/api/article/src1/favorite")
    assert r1.json()["is_favorite"] is True
    assert r2.json()["is_favorite"] is False
    # 验证真的写进 state
    assert kb.load_state()["sources"]["src1"]["is_favorite"] is False


def test_toggle_read_later_persists(client, isolate_vault):
    _seed_source()
    r1 = client.post("/api/article/src1/read-later")
    r2 = client.post("/api/article/src1/read-later")
    assert r1.json()["read_later"] is True
    assert r2.json()["read_later"] is False
    assert kb.load_state()["sources"]["src1"]["read_later"] is False


# ---------------------------------------------------------------------------
# S1: 锁基础 + web 端点不嵌套死锁
# ---------------------------------------------------------------------------

def test_state_lock_basic(isolate_vault):
    with kb.state_lock(timeout=1):
        pass  # 能 acquire/release 即可


def test_web_locked_paths_no_deadlock(client, isolate_vault):
    """全部加锁写路径冒烟,验证无嵌套死锁(Windows msvcrt 对同进程不可重入)。"""
    _seed_source()
    client.post("/api/article/src1/favorite")
    client.post("/api/article/src1/read-later")
    assert client.post("/api/collections", json={"name": "夹"}).status_code == 200
    r = client.post("/api/calendar", json={"title": "事项", "date": "2026-07-25"})
    assert r.status_code == 200
    cal_id = r.json()["item"]["id"]
    assert client.patch(f"/api/calendar/{cal_id}", json={"title": "改"}).status_code == 200
    assert client.delete(f"/api/calendar/{cal_id}").status_code == 200
