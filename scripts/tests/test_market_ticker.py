"""自选股代码校验测试(v0.4.21)—— 纯函数 + Web API 拒绝非法组合。

校验规则覆盖:A股(沪 SH / 深 SZ / 北交所 BJ)、港股 HK、美股 US。
ticker 规范化存储为 'MARKET:CODE'。范式参考 test_events.py。
"""
import kb
import kb_web
import pytest
import web.routers.market as market_router
from fastapi.testclient import TestClient


# —— 纯函数层:validate_ticker ——

@pytest.mark.parametrize("market,code", [
    # A 股沪市:主板 / 科创板 / ETF / 转债
    ("SH", "600519"), ("SH", "601111"), ("SH", "688981"), ("SH", "510300"),
    # A 股深市:主板 / 创业板 / ETF
    ("SZ", "000001"), ("SZ", "002415"), ("SZ", "300750"), ("SZ", "159915"),
    # 北交所
    ("BJ", "830799"), ("BJ", "430047"),
    # 港股:1-5 位
    ("HK", "700"), ("HK", "9988"), ("HK", "00700"),
    # 美股:含 share class
    ("US", "AAPL"), ("US", "BRK.B"), ("US", "B"),
    # 美股小写应接受(规范化时转大写)
    ("US", "aapl"), ("US", "brk.b"),
    # 空代码非必填
    ("SH", ""), ("US", ""),
])
def test_validate_ticker_legal(market, code, isolate_vault):
    assert kb.validate_ticker(market, code) is None


@pytest.mark.parametrize("market,code", [
    ("SH", "60051"),       # 位数错(5 位)
    ("SH", "699999"),      # 6 位但前缀不在白名单
    ("SH", "60051A"),      # 含字母
    ("SZ", "600519"),      # 沪市代码填到深市
    ("BJ", "123456"),      # 北交所前缀错(1 开头)
    ("HK", "123456"),      # 港股超过 5 位
    ("HK", "700A"),        # 港股含字母
    ("US", "AAPPLMN"),     # 美股超过 5 位
    ("US", "A.B.C"),       # 美股两个点
    ("US", "1234"),        # 美股填数字
    ("XX", "123"),         # 未知市场
])
def test_validate_ticker_illegal(market, code, isolate_vault):
    err = kb.validate_ticker(market, code)
    assert err is not None, f"应拒绝 {market}:{code} 但通过了"
    assert isinstance(err, str) and len(err) > 0


# —— normalize_ticker ——

def test_normalize_ticker_prepends_market(isolate_vault):
    assert kb.normalize_ticker("SH", "600519") == "SH:600519"
    assert kb.normalize_ticker("HK", "700") == "HK:700"

def test_normalize_ticker_uppercases_us(isolate_vault):
    assert kb.normalize_ticker("US", "aapl") == "US:AAPL"
    assert kb.normalize_ticker("US", "brk.b") == "US:BRK.B"

def test_normalize_ticker_strips_existing_prefix(isolate_vault):
    # raw 已含冒号,以 market 参数为准重新拼装
    assert kb.normalize_ticker("SH", "SZ:600519") == "SH:600519"

def test_normalize_ticker_empty_returns_empty(isolate_vault):
    assert kb.normalize_ticker("SH", "") == ""

def test_normalize_ticker_illegal_raises(isolate_vault):
    with pytest.raises(ValueError):
        kb.normalize_ticker("SH", "699999")


# —— parse_ticker(读出市场+代码,旧裸数据自动识别)——

def test_parse_ticker_with_prefix(isolate_vault):
    assert kb.parse_ticker("SH:600519") == ("SH", "600519")
    assert kb.parse_ticker("US:AAPL") == ("US", "AAPL")

def test_parse_ticker_bare_a_stock(isolate_vault):
    # 6 位数字按前缀自动判 SH/SZ/BJ
    assert kb.parse_ticker("600519") == ("SH", "600519")
    assert kb.parse_ticker("000001") == ("SZ", "000001")
    assert kb.parse_ticker("830799") == ("BJ", "830799")

def test_parse_ticker_bare_hk(isolate_vault):
    # 1-5 位纯数字判 HK
    assert kb.parse_ticker("700") == ("HK", "700")
    assert kb.parse_ticker("9988") == ("HK", "9988")

def test_parse_ticker_bare_us(isolate_vault):
    assert kb.parse_ticker("AAPL") == ("US", "AAPL")

def test_parse_ticker_empty(isolate_vault):
    assert kb.parse_ticker("") == ("", "")
    assert kb.parse_ticker(None) == ("", "")


# —— Web API:POST 拒绝非法 ticker ——

@pytest.fixture
def client(isolate_vault):
    return TestClient(kb_web.app)


def test_api_create_watchlist_legal(client, isolate_vault):
    """合法 ticker 应入库,且规范化为 MARKET:CODE。"""
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "茅台", "market": "SH", "ticker": "600519"
    })
    assert r.status_code == 200, r.text
    m = r.json()["market"]
    assert m["ticker"] == "SH:600519"
    assert m["market"] == "SH"
    # 清理
    client.delete("/api/market/" + m["id"])


def test_api_create_watchlist_us_uppercased(client, isolate_vault):
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "苹果", "market": "US", "ticker": "aapl"
    })
    assert r.status_code == 200
    assert r.json()["market"]["ticker"] == "US:AAPL"
    client.delete("/api/market/" + r.json()["market"]["id"])


def test_api_market_quote_batch_keeps_partial_failures(client, isolate_vault, monkeypatch):
    """行情源单只失败时,批量接口仍返回所有自选股和成功/失败计数。"""
    r1 = client.post("/api/market", json={
        "kind": "watchlist", "title": "茅台", "market": "SH", "ticker": "600519"
    })
    r2 = client.post("/api/market", json={
        "kind": "watchlist", "title": "苹果", "market": "US", "ticker": "aapl"
    })
    assert r1.status_code == 200
    assert r2.status_code == 200

    def fake_get_quote(market, code, days):
        if code == "600519":
            return {
                "ok": True, "market": market, "code": code,
                "price": 123.4, "change_pct": 1.2,
                "kline": [{"date": "2026-08-01", "close": 123.4}],
                "kline_days": 1, "date": "2026-08-01",
            }
        return {
            "ok": False, "market": market, "code": code,
            "error": "行情源连接失败,请稍后重试",
        }

    monkeypatch.setattr(market_router.kb_quote, "get_quote", fake_get_quote)

    r = client.get("/api/market/quote?days=30")
    assert r.status_code == 200
    d = r.json()
    assert d["ok_count"] == 1
    assert d["fail_count"] == 1
    assert len(d["items"]) == 2
    assert {it["title"] for it in d["items"]} == {"茅台", "苹果"}


@pytest.mark.parametrize("market,code", [
    ("SH", "700"),       # 港股代码填到沪市
    ("US", "1234"),      # 美股填数字
    ("SH", "699999"),    # 前缀不合法
    ("HK", "123456"),    # 港股超长
    ("XX", "123"),       # 未知市场
])
def test_api_create_watchlist_rejects_illegal(client, isolate_vault, market, code):
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "t", "market": market, "ticker": code
    })
    assert r.status_code == 400, f"{market}:{code} 应被拒绝"
    assert r.json().get("detail"), "应返回可读错误描述"


# —— Web API:PATCH 更新时联合校验 ——

def test_api_patch_watchlist_validates_final_combo(client, isolate_vault):
    """改 market 后,以最终 market 重新校验 ticker。"""
    # 先建一个合法的
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "茅台", "market": "SH", "ticker": "600519"
    })
    mid = r.json()["market"]["id"]
    # 改 market 为 HK 但 ticker 不动(600519 对港股超长)→ 应 400
    r = client.patch("/api/market/" + mid, json={"market": "HK"})
    assert r.status_code == 400
    # 改 market 为 HK 且 ticker 也改成合法港股 → 应 200
    r = client.patch("/api/market/" + mid, json={"market": "HK", "ticker": "700"})
    assert r.status_code == 200
    assert r.json()["market"]["ticker"] == "HK:700"
    client.delete("/api/market/" + mid)


# —— 旧数据兼容(load 时自动识别 market)——

def test_legacy_bare_ticker_loads_without_market(isolate_vault):
    """旧数据 ticker 是裸代码(无 MARKET: 前缀),load_market_file 不报错,
    parse_ticker 能自动识别市场。"""
    tmp = isolate_vault
    path = tmp / "08_Market" / "market_watchlist_legacy1234.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 手写一个旧格式文件(ticker 裸代码,无 market 字段)
    content = """---
id: market_watchlist_legacy1234
kind: watchlist
title: 旧数据苹果
ticker: AAPL
sector: 科技
status: active
created_at: 2026-07-20T00:00:00
updated_at: 2026-07-20T00:00:00
---
旧数据
"""
    path.write_text(content, encoding="utf-8")
    m = kb.load_market_file(path)
    assert m["ticker"] == "AAPL"   # 原样读出
    assert m["market"] == ""        # 旧数据 market 字段空
    # parse_ticker 自动识别为美股
    mkt, code = kb.parse_ticker(m["ticker"])
    assert mkt == "US"
    assert code == "AAPL"


# —— v0.4.22:持仓位置字段(watchlist)——

def test_watchlist_position_roundtrip(isolate_vault):
    """watchlist 的 4 个持仓字段写读一致(纯 str,避免浮点精度)。"""
    path = kb._market_file_path("market_watchlist_postest01")
    meta = {
        "id": "market_watchlist_postest01", "kind": "watchlist", "title": "茅台",
        "market": "SH", "ticker": "SH:600519", "sector": "消费",
        "cost_price": "1680.5", "shares": "100",
        "target_price": "1900", "stop_price": "1550",
        "note": "", "status": "active",
    }
    kb.write_market_file(path, meta, "", is_new=True)
    m = kb.load_market_file(path)
    assert m["cost_price"] == "1680.5"
    assert m["shares"] == "100"
    assert m["target_price"] == "1900"
    assert m["stop_price"] == "1550"


def test_api_create_watchlist_with_position(client, isolate_vault):
    """POST 创建 watchlist 带持仓字段,返回值含这些字段。"""
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "茅台", "market": "SH", "ticker": "600519",
        "cost_price": "1680.5", "shares": "100", "target_price": "1900", "stop_price": "1550",
    })
    assert r.status_code == 200, r.text
    m = r.json()["market"]
    assert m["cost_price"] == "1680.5"
    assert m["shares"] == "100"
    assert m["target_price"] == "1900"
    assert m["stop_price"] == "1550"
    client.delete("/api/market/" + m["id"])


def test_api_patch_position(client, isolate_vault):
    """PATCH 能更新持仓字段。"""
    # 建一个空 watchlist
    r = client.post("/api/market", json={
        "kind": "watchlist", "title": "茅台", "market": "SH", "ticker": "600519",
    })
    wid = r.json()["market"]["id"]
    # 补持仓字段
    r = client.patch("/api/market/" + wid, json={"cost_price": "1700", "shares": "200"})
    assert r.status_code == 200
    m = r.json()["market"]
    assert m["cost_price"] == "1700"
    assert m["shares"] == "200"
    client.delete("/api/market/" + wid)


def test_load_legacy_market_without_position_fields(isolate_vault):
    """旧数据(无持仓字段)load 时不报错,持仓字段默认空串。"""
    tmp = isolate_vault
    path = tmp / "08_Market" / "market_watchlist_legacy_newfld.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = """---
id: market_watchlist_legacy_newfld
kind: watchlist
title: 旧数据茅台
ticker: SH:600519
status: active
created_at: 2026-07-20T00:00:00
updated_at: 2026-07-20T00:00:00
---
旧数据
"""
    path.write_text(content, encoding="utf-8")
    m = kb.load_market_file(path)
    assert m["cost_price"] == ""
    assert m["shares"] == ""
