"""收藏夹文件夹(collections)功能测试。

覆盖:CRUD、文章入夹/移出、双向引用同步、默认夹迁移、删除文件夹清理引用。
"""
import kb
import kb_web
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    monkeypatch.setattr(kb, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb, "STATE_FILE", kb_dir / "state.json")
    monkeypatch.setattr(kb_web, "VAULT_ROOT", tmp_path)
    # 造两个 source(一个有 summary 一个没有)
    state = {"version": 1, "created_at": "2026-07-17", "sources": {
        "source_a": {"source_id": "source_a", "source_title": "文章A", "source_type": "web", "is_favorite": True},
        "source_b": {"source_id": "source_b", "source_title": "文章B", "source_type": "web", "is_favorite": False},
    }}
    kb.save_state(state)
    return TestClient(kb_web.app), tmp_path


def _col_id_by_name(c, name):
    items = c.get("/api/collections").json()["items"]
    return next((i["id"] for i in items if i["name"] == name), None)


def test_list_collections_empty_after_migration(client):
    """首次 GET 触发迁移:无 is_favorite=true 时 collections 为空列表(非报错)。"""
    c, tmp = client
    # source_a 是 is_favorite=True,应触发默认夹迁移
    items = c.get("/api/collections").json()["items"]
    names = [i["name"] for i in items]
    assert "默认收藏夹" in names
    # 默认夹里有 source_a
    default = next(i for i in items if i["name"] == "默认收藏夹")
    assert default["count"] == 1
    assert "source_a" in default["source_ids"]


def test_create_collection(client):
    c, tmp = client
    r = c.post("/api/collections", json={"name": "金融"})
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["name"] == "金融"
    assert item["id"].startswith("col_")
    assert item["source_ids"] == []


def test_create_collection_empty_name_400(client):
    c, tmp = client
    r = c.post("/api/collections", json={"name": "  "})
    assert r.status_code == 400


def test_rename_collection(client):
    c, tmp = client
    cid = c.post("/api/collections", json={"name": "旧名"}).json()["item"]["id"]
    r = c.patch("/api/collections/" + cid, json={"name": "新名"})
    assert r.status_code == 200
    assert r.json()["item"]["name"] == "新名"


def test_rename_not_found_404(client):
    c, tmp = client
    assert c.patch("/api/collections/col_nope", json={"name": "x"}).status_code == 404


def test_add_article_to_collections(client):
    """文章加入多个文件夹,双向引用同步。"""
    c, tmp = client
    cid1 = c.post("/api/collections", json={"name": "金融"}).json()["item"]["id"]
    cid2 = c.post("/api/collections", json={"name": "科研idea"}).json()["item"]["id"]

    r = c.post("/api/article/source_b/collections", json={"collection_ids": [cid1, cid2]})
    assert r.status_code == 200
    assert set(r.json()["collection_ids"]) == {cid1, cid2}

    # collection.source_ids 同步
    items = {i["id"]: i for i in c.get("/api/collections").json()["items"]}
    assert "source_b" in items[cid1]["source_ids"]
    assert "source_b" in items[cid2]["source_ids"]
    # source.collection_ids 同步
    state = kb.load_state()
    assert set(state["sources"]["source_b"]["collection_ids"]) == {cid1, cid2}


def test_collection_articles(client):
    c, tmp = client
    cid = c.post("/api/collections", json={"name": "金融"}).json()["item"]["id"]
    c.post("/api/article/source_a/collections", json={"collection_ids": [cid]})
    c.post("/api/article/source_b/collections", json={"collection_ids": [cid]})

    items = c.get("/api/collections/" + cid + "/articles").json()["items"]
    titles = {i["title"] for i in items}
    assert titles == {"文章A", "文章B"}


def test_remove_article_from_collection(client):
    """全量替换:取消勾选则从文件夹移出。"""
    c, tmp = client
    cid1 = c.post("/api/collections", json={"name": "金融"}).json()["item"]["id"]
    cid2 = c.post("/api/collections", json={"name": "科研"}).json()["item"]["id"]
    c.post("/api/article/source_a/collections", json={"collection_ids": [cid1, cid2]})
    # 移出 cid2
    c.post("/api/article/source_a/collections", json={"collection_ids": [cid1]})

    items = {i["id"]: i for i in c.get("/api/collections").json()["items"]}
    assert "source_a" in items[cid1]["source_ids"]
    assert "source_a" not in items[cid2]["source_ids"]
    state = kb.load_state()
    assert state["sources"]["source_a"]["collection_ids"] == [cid1]


def test_delete_collection_clears_references(client):
    """删除文件夹:从 collections 删 + 清理所有 source 的 collection_ids 引用。"""
    c, tmp = client
    cid = c.post("/api/collections", json={"name": "金融"}).json()["item"]["id"]
    c.post("/api/article/source_a/collections", json={"collection_ids": [cid]})
    c.post("/api/article/source_b/collections", json={"collection_ids": [cid]})

    r = c.delete("/api/collections/" + cid)
    assert r.status_code == 200
    # collections 里没了
    items = c.get("/api/collections").json()["items"]
    assert all(i["id"] != cid for i in items)
    # source 还在(没被删),只是 collection_ids 清理了
    state = kb.load_state()
    assert "source_a" in state["sources"]
    assert cid not in state["sources"]["source_a"].get("collection_ids", [])
    assert cid not in state["sources"]["source_b"].get("collection_ids", [])


def test_delete_collection_not_found_404(client):
    c, tmp = client
    assert c.delete("/api/collections/col_nope").status_code == 404


def test_article_collections_source_not_found_404(client):
    c, tmp = client
    cid = c.post("/api/collections", json={"name": "x"}).json()["item"]["id"]
    assert c.post("/api/article/source_nope/collections",
                  json={"collection_ids": [cid]}).status_code == 404


def test_migration_runs_once(client):
    """迁移只跑一次:第二次 GET 不再改 collections。"""
    c, tmp = client
    c.get("/api/collections")  # 第一次:迁移
    state1 = kb.load_state()
    names1 = sorted(col["name"] for col in state1["collections"].values())
    c.get("/api/collections")  # 第二次
    state2 = kb.load_state()
    names2 = sorted(col["name"] for col in state2["collections"].values())
    assert names1 == names2  # 不重复建默认夹
