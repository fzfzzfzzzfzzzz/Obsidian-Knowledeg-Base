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


# —— v0.4.5 修复的 bug 回归 ——

def test_xiayuedi_next_month_end():
    """下月底:下月最后一天(不是 1 号)。修复 +32 算式错误。

    同时覆盖"下个月底"4 字写法(同一条正则 kb_date.py:101),不单独测。
    """
    res = kb_date.detect_dates("下月底截止", REF)
    assert res[0]["normalized_date"] == "2026-08-31"
    assert res[0]["raw_text"] == "下月底"


def test_xiayuedi_february_non_leap():
    """下月底遇 2 月非闰年:28 号。"""
    res = kb_date.detect_dates("下月底截止", date(2026, 1, 15))
    assert res[0]["normalized_date"] == "2026-02-28"


def test_xiayuedi_february_leap():
    """下月底遇 2 月闰年:29 号。

    2 月是 +32 算式唯一有真实 bug 风险的边界(其余月份由 calendar.monthrange
    保证,属标准库职责,不重复测)。
    """
    res = kb_date.detect_dates("下月底截止", date(2024, 1, 15))
    assert res[0]["normalized_date"] == "2024-02-29"


def test_benzhoumo_on_saturday():
    """本周末在周六 = 今天(本周的周末已在进行)。修复 <=0 推到下周的 bug。"""
    res = kb_date.detect_dates("本周末截止", date(2026, 7, 18))  # 周六
    assert res[0]["normalized_date"] == "2026-07-18"


def test_benzhoumo_on_sunday():
    """本周末在周日 = 今天。"""
    res = kb_date.detect_dates("本周末截止", date(2026, 7, 19))  # 周日
    assert res[0]["normalized_date"] == "2026-07-19"


def test_benzhoumo_on_weekday():
    """本周末在工作日 = 本周六。"""
    res = kb_date.detect_dates("本周末截止", date(2026, 7, 15))  # 周三
    assert res[0]["normalized_date"] == "2026-07-18"


def test_xiayuechu_long_form():
    """下个月初(4 字):与下月初语义一致。"""
    res = kb_date.detect_dates("下个月初截止", REF)
    assert res[0]["normalized_date"] == "2026-08-01"


def test_xiayue_alone_not_swallowed():
    """下月 单用不应被下月底/下月初的正则吞掉。

    同时覆盖"下个月/下个月初"4 字写法(同一组正则),不单独测。
    """
    res = kb_date.detect_dates("下月截止", REF)
    assert res[0]["normalized_date"] == "2026-08-01"
    assert res[0]["raw_text"] == "下月"
