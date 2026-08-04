"""BaoStock / AKShare market data normalization."""
import kb_quote


def test_to_float_handles_commas_and_percent_suffix():
    assert kb_quote._to_float("1,234.50") == 1234.5
    assert kb_quote._to_float("1.23%") == 1.23
    assert kb_quote._to_float("") is None


def test_baostock_volume_is_already_shares_and_adjustflag_maps_to_qfq():
    row = {
        "date": "2026-08-01",
        "open": "10",
        "high": "11",
        "low": "9",
        "close": "10.5",
        "preclose": "10",
        "volume": "1000",
        "amount": "10500",
        "adjustflag": "2",
        "turn": "1.23",
        "tradestatus": "1",
        "pctChg": "5.0",
        "isST": "0",
    }

    item = kb_quote._normalize_baostock_row(row, "SH", "600519")

    assert item["volume_shares"] == 1000
    assert item["amount"] == 10500
    assert item["change_pct"] == 5.0
    assert item["turnover"] == 1.23
    assert item["adjust"] == "qfq"
    assert item["currency"] == "CNY"


def test_baostock_adjustflag_maps_none_and_hfq():
    base = {
        "date": "2026-08-01",
        "open": "10",
        "high": "11",
        "low": "9",
        "close": "10.5",
        "preclose": "10",
        "volume": "1000",
        "amount": "10500",
        "turn": "1.23",
        "tradestatus": "1",
        "pctChg": "5.0",
        "isST": "0",
    }

    assert kb_quote._normalize_baostock_row({**base, "adjustflag": "3"}, "SH", "600519")["adjust"] == "none"
    assert kb_quote._normalize_baostock_row({**base, "adjustflag": "1"}, "SH", "600519")["adjust"] == "hfq"


def test_akshare_a_share_volume_lot_converts_to_shares_and_percent_remains_percent():
    row = {
        "日期": "2026-08-01",
        "开盘": 10,
        "最高": 11,
        "最低": 9,
        "收盘": 10.5,
        "成交量": 1000,
        "成交额": 10500,
        "振幅": 2.5,
        "涨跌幅": 5.0,
        "涨跌额": 0.5,
        "换手率": 1.23,
    }

    item = kb_quote._normalize_akshare_row(row, "SH", "600519", "qfq")

    assert item["volume_shares"] == 100000
    assert item["amount"] == 10500
    assert item["change_pct"] == 5.0
    assert item["turnover"] == 1.23
    assert item["adjust"] == "qfq"


def test_akshare_hk_us_volume_keeps_share_units():
    row = {"日期": "2026-08-01", "收盘": 10.5, "成交量": 1000, "涨跌幅": 5.0}

    hk = kb_quote._normalize_akshare_row(row, "HK", "00700", "qfq")
    us = kb_quote._normalize_akshare_row(row, "US", "AAPL", "qfq")

    assert hk["volume_shares"] == 1000
    assert hk["currency"] == "HKD"
    assert us["volume_shares"] == 1000
    assert us["currency"] == "USD"
