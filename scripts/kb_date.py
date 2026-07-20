#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kb_date.py —— 日期识别模块(v0.3 日历功能)

从知识内容正文中识别重要日期(截止/发布/活动等),
支持明确日期、相对日期、模糊日期,并按优先级排序推荐。

纯函数模块,不调 LLM(PRD 6.2.2 明确 MVP 用正则)。

主要接口:
    detect_dates(text, reference_date) -> list[dict]  识别全部日期
    recommend_date(text, reference_date) -> dict|None  推荐一个最佳日期

依据: docs/v0.3/knowledge_calendar_feature_PRD.md 第 6.2 节
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any

ENC = "utf-8"


def _today() -> date:
    """获取"今天",支持时区配置(v0.4.6)。

    读环境变量 KB_TZ(如 "Asia/Shanghai"、"UTC"):
    - 设置且有效 → 用该时区的当前日期
    - 未设置或无效 → 退回本地系统时区

    用于云端部署(服务器在 UTC,用户在东八区时避免日期偏一天)。
    """
    tz_name = os.environ.get("KB_TZ")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name)).date()
        except Exception:
            # 无效时区名/zoneinfo 不可用,退回系统默认
            pass
    return date.today()

# ---------------------------------------------------------------------------
# 关键词分级(PRD 6.2.7)
# ---------------------------------------------------------------------------

# 高优先级:截止/到期/提交
KEYWORDS_HIGH = [
    "截止", "截至", "结束", "到期", "提交", "报名截止", "申请截止",
    "最后日期", "deadline", "due", "expires", "最后一天", "末日",
]

# 中优先级:发布/上线/开放/举办
KEYWORDS_MEDIUM = [
    "发布", "上线", "开放", "开始", "举办", "召开", "开幕", "更新",
    "开源", "launch", "release", "start", "开播", "开售", "公测",
]

# 低优先级:预计/计划/可能
KEYWORDS_LOW = [
    "预计", "计划", "可能", "暂定", "大约", "左右", "或将", "有望",
]

# 日期范围关键词
RANGE_KEYWORDS = ["至", "到", "—", "-", "~", "至迟"]


# ---------------------------------------------------------------------------
# 正则模式(PRD 6.2.3 / 6.2.4 / 6.2.5)
# ---------------------------------------------------------------------------

# 明确日期格式(PRD 6.2.3)
# 2026年8月1日 / 2026 年 8 月 1 日
RE_CN_FULL = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 2026-08-01 / 2026/08/01 / 2026.08.01
RE_NUM_FULL = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
# 8月1日 / 08月01日(缺年份)
RE_CN_PARTIAL = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 8-1 / 8/1(缺年份,简写)
RE_NUM_PARTIAL = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)")

# 日期范围(PRD 6.2.9): X月X日至Y月Y日 / X月X日-X月X日
RE_RANGE = re.compile(
    r"(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[至到\-~—]+\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)

# 相对日期(PRD 6.2.4)
# 注意:顺序敏感!"下个月"正则不允许"个"可选,否则会抢先匹配"下月底"里的"下月"
# 子串(位置去重会让真正的"下月底"规则被丢弃)。"下月" 单用走单独的 "下月" key。
RE_RELATIVE = {
    "今天": re.compile(r"今天"),
    "明天": re.compile(r"明天"),
    "后天": re.compile(r"后天"),
    "本月底": re.compile(r"本月底"),
    "下个月": re.compile(r"下个月(?!底|初)"),  # 排除下个月底/下个月初
    "下月": re.compile(r"下月(?!底|初|个月)"),  # 下月 单用,排除下月底/下月初/下个月
    "下月初": re.compile(r"下(?:月|个月)初"),  # 匹配 下月初 和 下个月初
    "下月底": re.compile(r"下(?:月|个月)底"),  # 匹配 下月底 和 下个月底
    "本周末": re.compile(r"本周末"),
}

# 相对周日期: 下周X / 本周X
RE_NEXT_WEEK = re.compile(r"下周\s*([一二三四五六日天])")
RE_THIS_WEEK = re.compile(r"本周\s*([一二三四五六日天])")

# 模糊日期(PRD 6.2.5)
RE_FUZZY = {
    "月初": re.compile(r"(\d{1,2})\s*月(?:份)?\s*初"),
    "月中": re.compile(r"(\d{1,2})\s*月(?:份)?\s*(?:中旬|中)"),
    "月底": re.compile(r"(\d{1,2})\s*月(?:份)?\s*底"),
    "年底": re.compile(r"(?:今年\s*)?年底"),
    "预计某月": re.compile(r"预计\s*(\d{1,2})\s*月"),
}

# 需要排除的误匹配(PRD 12.2 / 12.3)
# 版本号: Python 3.12.1
RE_VERSION = re.compile(r"[A-Za-z]+\s*\d+\.\d+\.\d+")
# 价格: 8.1元 / 8.1 亿
RE_PRICE = re.compile(r"\d+[.．]\d+\s*(?:元|亿|万|美元|块|分)")
# IP 地址: 192.168.1.1
RE_IP = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

# 中文星期映射
WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


# ---------------------------------------------------------------------------
# 日期标准化(PRD 6.2.6 年份推断)
# ---------------------------------------------------------------------------


def _safe_date(year: int, month: int, day: int) -> date | None:
    """安全构造日期,无效日期返回 None。"""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def normalize_date(
    year: int | None, month: int, day: int, reference: date | None = None
) -> tuple[date | None, str]:
    """标准化日期为 date 对象 + 置信度。

    年份推断规则(PRD 6.2.6):
    - 有年份: 直接用
    - 无年份: 优先用 reference 年份;如果该日期已过去(早于 reference),推断为下一年
    - 推断年份的置信度为 medium

    返回 (date_obj, confidence)
    """
    ref = reference or _today()
    confidence = "high"

    if year is None:
        year = ref.year
        # 检查该日期是否已过去
        candidate = _safe_date(year, month, day)
        if candidate and candidate < ref:
            year += 1
        confidence = "medium"

    result = _safe_date(year, month, day)
    if result is None:
        return None, "low"

    return result, confidence


# ---------------------------------------------------------------------------
# 相对日期解析(PRD 6.2.4)
# ---------------------------------------------------------------------------


def _resolve_relative(match_text: str, reference: date) -> date | None:
    """解析相对日期文本为具体日期。"""
    if "今天" in match_text:
        return reference
    if "明天" in match_text:
        return reference + timedelta(days=1)
    if "后天" in match_text:
        return reference + timedelta(days=2)

    # 本月底
    if "本月底" in match_text:
        if reference.month == 12:
            return date(reference.year, 12, 31)
        next_month = reference.replace(day=1) + timedelta(days=32)
        return next_month.replace(day=1) - timedelta(days=1)

    # 下月初 / 下月底(必须先于"下月/下个月"判断,否则会被子串匹配抢先)
    # 同时识别 "下月X" 和 "下个月X" 两种写法
    # 下月初:下月 1 号
    if "下月初" in match_text or "下个月初" in match_text:
        nm = reference.month + 1
        ny = reference.year
        if nm > 12:
            nm = 1
            ny += 1
        return _safe_date(ny, nm, 1)
    # 下月底:下下月 1 号 - 1 天 = 下月最后一天(与"本月底"同款写法,避免 +32 算错大月/2月)
    if "下月底" in match_text or "下个月底" in match_text:
        nm = reference.month + 2  # 下下月
        ny = reference.year
        if nm > 12:
            nm -= 12
            ny += 1
        first_of_next_next = _safe_date(ny, nm, 1)
        if first_of_next_next:
            return first_of_next_next - timedelta(days=1)

    # 下个月 / 下月(兜底:下月 1 号)
    if "下个月" in match_text or "下月" in match_text:
        nm = reference.month + 1
        ny = reference.year
        if nm > 12:
            nm = 1
            ny += 1
        return _safe_date(ny, nm, 1)

    # 本周末(周六或周日)
    # 语义:工作日说"本周末"指本周六;周六/周日说"本周末"指今天(本周的周末已在进行)
    if "本周末" in match_text:
        wd = reference.weekday()
        if wd >= 5:  # 周六(5)或周日(6):本周末就是今天
            return reference
        days_ahead = 5 - wd  # 工作日:推到本周六
        return reference + timedelta(days=days_ahead)

    return None


def _resolve_weekday(weekday_char: str, reference: date, base: str) -> date | None:
    """解析"下周一"/"本周一"为具体日期。"""
    target_dow = WEEKDAY_MAP.get(weekday_char)
    if target_dow is None:
        return None
    current_dow = reference.weekday()
    if base == "下周":
        days_ahead = target_dow - current_dow
        if days_ahead <= 0:
            days_ahead += 7
        days_ahead += 7
    else:  # 本周
        days_ahead = target_dow - current_dow
        if days_ahead < 0:
            days_ahead += 7
    return reference + timedelta(days=days_ahead)


# ---------------------------------------------------------------------------
# 模糊日期解析(PRD 6.2.5)
# ---------------------------------------------------------------------------


def _resolve_fuzzy(month_str: str | None, fuzzy_type: str, reference: date) -> date | None:
    """解析模糊日期。返回推断的日期(低置信度)。"""
    ref = reference
    year = ref.year

    if month_str:
        month = int(month_str)
    else:
        month = ref.month

    if fuzzy_type == "月初":
        return _safe_date(year, month, 1)
    elif fuzzy_type in ("月中", "中"):
        return _safe_date(year, month, 15)
    elif fuzzy_type == "月底":
        if month == 12:
            return date(year, 12, 31)
        nm = month + 1
        ny = year
        if nm > 12:
            ny += 1
            nm = 1
        return _safe_date(ny, nm, 1) - timedelta(days=1) if _safe_date(ny, nm, 1) else None
    elif fuzzy_type == "年底":
        return _safe_date(year, 12, 31)
    elif fuzzy_type == "预计某月":
        return _safe_date(year, month, 1)
    return None


# ---------------------------------------------------------------------------
# 上下文分析(PRD 6.2.7)
# ---------------------------------------------------------------------------


def _analyze_context(text: str, match_start: int, match_end: int) -> dict[str, Any]:
    """分析日期前后的上下文,返回 {event_type, event_title, keyword_matched, keyword_priority}。"""
    # 取日期前后各 40 字符的上下文
    ctx_start = max(0, match_start - 40)
    ctx_end = min(len(text), match_end + 40)
    context = text[ctx_start:ctx_end]

    # 检查关键词
    for kw in KEYWORDS_HIGH:
        if kw in context:
            return {
                "event_type": "deadline",
                "event_title": _guess_title(context, kw),
                "keyword": kw,
                "priority": 3,
            }
    for kw in KEYWORDS_MEDIUM:
        if kw in context:
            return {
                "event_type": "release",
                "event_title": _guess_title(context, kw),
                "keyword": kw,
                "priority": 2,
            }
    for kw in KEYWORDS_LOW:
        if kw in context:
            return {
                "event_type": "other",
                "event_title": _guess_title(context, kw),
                "keyword": kw,
                "priority": 1,
            }
    return {"event_type": "other", "event_title": "", "keyword": "", "priority": 0}


def _guess_title(context: str, keyword: str) -> str:
    """从上下文猜一个事件标题。"""
    # 截止类:提取"XX截止"
    if keyword in ("截止", "报名截止", "申请截止"):
        if "报名" in context:
            return "报名截止"
        if "申请" in context:
            return "申请截止"
        return "截止日期"
    if keyword in ("到期", "expires"):
        return "到期"
    if keyword in ("提交", "due", "deadline"):
        return "提交截止"
    if keyword in ("发布", "release", "launch"):
        return "发布"
    if keyword in ("上线",):
        return "上线"
    if keyword in ("开放", "开始"):
        if "报名" in context:
            return "开放报名"
        return "开始"
    if keyword in ("举办", "召开", "开幕"):
        return "举办"
    return keyword


# ---------------------------------------------------------------------------
# 误匹配过滤(PRD 12.2 / 12.3)
# ---------------------------------------------------------------------------


def _is_false_positive(text: str, start: int, end: int) -> bool:
    """检查匹配是否是误匹配(版本号/价格/IP)。"""
    # 扩大范围检查
    ctx_start = max(0, start - 5)
    ctx_end = min(len(text), end + 5)
    snippet = text[ctx_start:ctx_end]

    # 版本号: Python 3.12.1
    for m in RE_VERSION.finditer(snippet):
        return True
    # 价格: 8.1元
    for m in RE_PRICE.finditer(snippet):
        return True
    # IP 地址
    for m in RE_IP.finditer(snippet):
        return True

    # 检查纯数字匹配是否其实是小数的一部分(如 3.12 被匹配为 3月12日)
    # 如果匹配前面是 . 且后面也是数字,可能是版本号
    if start > 0 and text[start - 1] == ".":
        return True

    return False


# ---------------------------------------------------------------------------
# 核心识别函数
# ---------------------------------------------------------------------------


def detect_dates(text: str, reference: date | None = None) -> list[dict[str, Any]]:
    """从文本中识别所有日期。

    返回 list[dict],每个 dict:
        raw_text, normalized_date (YYYY-MM-DD), context, event_type,
        event_title, confidence, is_future, is_approximate, priority

    参数:
        text: 要识别的正文
        reference: 参考日期(用于相对日期和年份推断),默认今天
    """
    ref = reference or _today()
    results: list[dict[str, Any]] = []
    seen_positions: set[int] = set()

    def _add(raw, d, start, end, confidence, is_approx, ctx_info):
        """添加一个识别结果(去重)。"""
        # 检查位置是否已被占用(避免重叠匹配)
        for p in range(start, end):
            if p in seen_positions:
                return
        # 误匹配过滤
        if _is_false_positive(text, start, end):
            return
        for p in range(start, min(end, len(text))):
            seen_positions.add(p)

        is_future = d >= ref if d else False
        results.append({
            "raw_text": raw,
            "normalized_date": d.isoformat() if d else None,
            "context": text[max(0, start - 30):min(len(text), end + 30)].strip(),
            "event_type": ctx_info.get("event_type", "other"),
            "event_title": ctx_info.get("event_title", ""),
            "confidence": confidence,
            "is_future": is_future,
            "is_approximate": is_approx,
            "priority": ctx_info.get("priority", 0),
        })

    # 1. 明确日期: 2026年8月1日
    for m in RE_CN_FULL.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        nd, conf = normalize_date(y, mo, d, ref)
        ctx = _analyze_context(text, m.start(), m.end())
        _add(m.group(0), nd, m.start(), m.end(), conf, False, ctx)

    # 2. 明确日期: 2026-08-01
    for m in RE_NUM_FULL.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        nd, conf = normalize_date(y, mo, d, ref)
        ctx = _analyze_context(text, m.start(), m.end())
        _add(m.group(0), nd, m.start(), m.end(), conf, False, ctx)

    # 3. 日期范围: X月X日至Y月Y日(PRD 6.2.9)
    for m in RE_RANGE.finditer(text):
        mo1, d1, mo2, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        # 范围结束日期更重要
        nd_end, conf = normalize_date(None, mo2, d2, ref)
        ctx = _analyze_context(text, m.start(), m.end())
        if "截止" in ctx.get("event_title", "") or "截止" in m.group(0):
            ctx["event_title"] = "截止"
            ctx["priority"] = max(ctx.get("priority", 0), 3)
        _add(m.group(0), nd_end, m.start(), m.end(), conf, False, ctx)

    # 4. 部分日期: 8月1日(缺年份)
    for m in RE_CN_PARTIAL.finditer(text):
        mo, d = int(m.group(1)), int(m.group(2))
        nd, conf = normalize_date(None, mo, d, ref)
        ctx = _analyze_context(text, m.start(), m.end())
        _add(m.group(0), nd, m.start(), m.end(), conf, False, ctx)

    # 5. 相对日期: 今天/明天/后天/下个月等
    for label, pattern in RE_RELATIVE.items():
        for m in pattern.finditer(text):
            d = _resolve_relative(m.group(0), ref)
            ctx = _analyze_context(text, m.start(), m.end())
            _add(m.group(0), d, m.start(), m.end(), "medium", False, ctx)

    # 6. 下周X / 本周X
    for m in RE_NEXT_WEEK.finditer(text):
        d = _resolve_weekday(m.group(1), ref, "下周")
        ctx = _analyze_context(text, m.start(), m.end())
        _add(m.group(0), d, m.start(), m.end(), "medium", False, ctx)
    for m in RE_THIS_WEEK.finditer(text):
        d = _resolve_weekday(m.group(1), ref, "本周")
        ctx = _analyze_context(text, m.start(), m.end())
        _add(m.group(0), d, m.start(), m.end(), "high", False, ctx)

    # 7. 模糊日期: 月初/月中/月底/年底/预计某月
    for ftype, pattern in RE_FUZZY.items():
        for m in pattern.finditer(text):
            month_str = m.group(1) if m.groups() else None
            d = _resolve_fuzzy(month_str, ftype, ref)
            ctx = _analyze_context(text, m.start(), m.end())
            _add(m.group(0), d, m.start(), m.end(), "low", True, ctx)

    return results


# ---------------------------------------------------------------------------
# 推荐排序(PRD 6.2.8)
# ---------------------------------------------------------------------------


def rank_dates(dates: list[dict], reference: date | None = None) -> list[dict]:
    """按优先级排序日期(PRD 6.2.8 八级排序)。

    排序规则(优先级从高到低):
    1. 与截止关键词关联的未来日期
    2. 日期范围的结束日期
    3. 与发布/活动关联的未来日期
    4. 明确的未来日期
    5. 只有月日的未来日期
    6. 模糊未来日期
    7. 普通正文日期
    8. 过去日期
    """
    ref = reference or _today()

    def sort_key(d):
        is_future = 0 if d.get("is_future") else 1
        priority = -d.get("priority", 0)  # 高 priority 排前
        confidence_order = {"high": 0, "medium": 1, "low": 2}
        conf = confidence_order.get(d.get("confidence", "low"), 2)
        is_approx = 0 if not d.get("is_approximate") else 1
        # 组合排序键: (是否未来, -优先级, 置信度, 是否模糊)
        return (is_future, priority, conf, is_approx)

    return sorted(dates, key=sort_key)


def recommend_date(text: str, reference: date | None = None) -> dict[str, Any] | None:
    """识别日期并推荐最佳的一个。

    返回推荐的日期 dict(含 normalized_date/event_title/confidence/context),
    或 None(无可靠日期)。
    """
    ref = reference or _today()
    detected = detect_dates(text, ref)
    if not detected:
        return None

    ranked = rank_dates(detected, ref)
    best = ranked[0]

    # 过去日期不推荐(PRD 6.2.8 第 8 条)
    if not best.get("is_future"):
        # 找有没有未来日期
        future = [d for d in ranked if d.get("is_future")]
        if future:
            best = future[0]
        else:
            # 全是过去日期,返回 None
            return None

    return {
        "normalized_date": best.get("normalized_date"),
        "event_title": best.get("event_title", ""),
        "confidence": best.get("confidence", "low"),
        "context": best.get("context", ""),
        "is_approximate": best.get("is_approximate", False),
    }
