"""日期识别 —— 纯函数层(kb_date.py)。固定参考日保证断言确定性。"""
from datetime import date

import kb_date

REF = date(2026, 7, 15)


def test_cn_full_date():
    res = kb_date.detect_dates("活动在2026年8月1日举行", REF)
    assert len(res) == 1
    assert res[0]["normalized_date"] == "2026-08-01"
    assert res[0]["is_future"] is True


def test_numeric_full_with_deadline():
    res = kb_date.detect_dates("报名截止2026-08-01", REF)
    assert res[0]["event_type"] == "deadline"
    assert res[0]["priority"] == 3


def test_partial_year_inference_future():
    res = kb_date.detect_dates("会议在8月1日召开", REF)
    assert res[0]["normalized_date"] == "2026-08-01"


def test_range_uses_end():
    res = kb_date.detect_dates("活动8月1日至8月10日", REF)
    assert res[0]["normalized_date"] == "2026-08-10"


def test_relative_tomorrow():
    res = kb_date.detect_dates("明天交作业", REF)
    assert res[0]["normalized_date"] == "2026-07-16"


def test_relative_next_month():
    res = kb_date.detect_dates("下个月发布新版", REF)
    assert res[0]["normalized_date"] == "2026-08-01"


def test_fuzzy_month_end():
    res = kb_date.detect_dates("7月底截止", REF)
    assert res[0]["normalized_date"] == "2026-07-31"


def test_false_positive_version():
    assert kb_date.detect_dates("Python 3.12.1 发布了", REF) == []


def test_false_positive_price():
    assert kb_date.detect_dates("售价8.1元", REF) == []


def test_false_positive_ip():
    assert kb_date.detect_dates("服务器192.168.1.1", REF) == []


def test_normalize_past_year_plus1():
    d, conf = kb_date.normalize_date(None, 3, 1, REF)
    assert d == date(2027, 3, 1)  # 3/1 在 2026 已过去 -> 推断下一年
    assert conf == "medium"


def test_rank_future_before_past():
    future = {"is_future": True, "priority": 0, "confidence": "low", "is_approximate": False}
    past = {"is_future": False, "priority": 3, "confidence": "high", "is_approximate": False}
    ranked = kb_date.rank_dates([past, future], REF)
    assert ranked[0]["is_future"] is True


def test_recommend_none_when_all_past():
    assert kb_date.recommend_date("已于2020年1月1日结束", REF) is None
