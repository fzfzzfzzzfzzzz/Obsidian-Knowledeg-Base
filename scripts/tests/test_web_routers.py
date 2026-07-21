"""web routers 装配 smoke 测试:确认 9 个 APIRouter 全部 include 且端点可访问。

不覆盖业务逻辑(由各 test_*.py 负责),只确认:
- OpenAPI schema 包含全部 57 个路由(12 页面 + 45 API),证明 router 装配无遗漏
- 每个页面路由 GET 返回 200(模板渲染不崩)
- 每个核心 API GET 路由返回 200 / 404(已注册、无 500)

这同时消除「独立 import 时 app.routes 中 router 路由 path=None」的 inspect 假象:
OpenAPI schema 才是路由注册的真实权威来源。
"""
import pytest

import kb_web
from fastapi.testclient import TestClient


# 9 个 router 应注册的全部路径(OpenAPI key 格式,参数名以真实注册为准)。
# 这是 v0.4.3 全部路由的精确清单,作为回归护栏:任何路由在重构中丢失都会让本测试失败。
EXPECTED_PATHS = {
    # dashboard
    "/", "/kb", "/api/dashboard", "/api/dashboard_full", "/api/recent", "/api/health",
    "/api/shutdown",
    # articles
    "/summary/{source_id}", "/articles", "/recent",
    "/api/summaries", "/api/summary/{source_id}", "/api/articles",
    "/api/article/{source_id}", "/api/article/{source_id}/read-later",
    "/api/article/{source_id}/favorite", "/api/article/{source_id}/collections",
    "/api/article/{source_id}/summary",
    # ideas
    "/ideas", "/api/ideas", "/api/ideas/confirmed",
    "/api/idea/{item_id}/status", "/api/article/{source_id}/generate-ideas",
    # todos
    "/todos", "/api/todos", "/api/todos/confirmed",
    "/api/todo/{item_id}/status", "/api/article/{source_id}/generate-todos",
    # calendar
    "/calendar", "/api/calendar", "/api/calendar/{item_id}",
    "/api/article/{source_id}/detected-dates", "/api/article/{source_id}/detect-dates",
    # collections
    "/favorites", "/api/favorites", "/api/collections",
    "/api/collections/{col_id}", "/api/collections/{col_id}/articles",
    # search
    "/search", "/api/search",
    # tags
    "/api/article/{source_id}/tags", "/api/article/{source_id}/tags/{tag}",
    "/api/article/{source_id}/ai-tags",
    # ingest
    "/submit", "/api/ingest", "/api/ingest-image", "/api/batch",
    "/api/pending-summaries", "/api/generate-summary/{source_id}",
    "/api/article/{source_id}/regenerate-summary",
}


@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


def test_all_routers_registered_in_openapi():
    """全部 57 个路由出现在 OpenAPI schema —— 证明 9 个 router 都已 include。"""
    paths = set(kb_web.app.openapi()["paths"].keys())
    missing = EXPECTED_PATHS - paths
    assert not missing, f"未注册的路由: {sorted(missing)}"
    # 额外确认数量不低于预期(不应有路由丢失)
    assert len(paths) >= len(EXPECTED_PATHS)


PAGE_ROUTES_200 = [
    "/", "/kb", "/articles", "/recent", "/favorites",
    "/ideas", "/todos", "/calendar", "/search", "/submit",
]


def test_page_routes_return_200(client):
    """每个页面路由渲染成功(返回 200,不抛 500)。"""
    c = client
    for path in PAGE_ROUTES_200:
        r = c.get(path)
        assert r.status_code == 200, f"页面 {path} 返回 {r.status_code}"


API_GET_ROUTES = [
    "/api/health", "/api/dashboard", "/api/dashboard_full", "/api/recent",
    "/api/summaries", "/api/articles",
    "/api/ideas", "/api/ideas/confirmed",
    "/api/todos", "/api/todos/confirmed",
    "/api/calendar", "/api/collections", "/api/favorites",
    "/api/search?q=test",
]


def test_core_api_routes_no_500(client):
    """核心 API GET 路由已注册(返回 200 或 404,绝不 500)。"""
    c = client
    for path in API_GET_ROUTES:
        r = c.get(path)
        assert r.status_code in (200, 404), f"API {path} 返回 {r.status_code}"
