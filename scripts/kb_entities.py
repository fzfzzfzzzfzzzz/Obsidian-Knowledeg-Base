#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kb_entities.py —— 业务实体(task / event / market)的存储层。

历史:这三类实体的"七件套"(make_id / file_path / find / format / load / scan /
write / sync)原本都堆在 kb.py 里(各 ~230 行,三份近乎照抄),导致 kb.py 涨到
3500+ 行。本模块把它们抽出来,共享真正重复的骨架(find 的"快路径+兜底扫"、
scan 的"glob+_log_scan_error+sort"、损坏备份逻辑),同时保留各实体的字段差异
(task 的 checklist JSON / pinned 布尔、market 的 ticker、event 的对称 completed_at)。

设计要点(详见 AGENTS.md「Module Ownership」):
  - **绝不 import-time 拷贝 kb 的路径常量**。tests/conftest.py 的 isolate_vault fixture
    通过 monkeypatch.setattr(kb, "VAULT_ROOT", ...) 隔离测试 vault;若本模块在 import 时
    `from kb import VAULT_ROOT`,会拿到一个不会被 patch 的副本,测试就会污染真实 vault。
    因此本模块一律 `import kb`,运行时读 kb.VAULT_ROOT / kb.STATE_FILE / kb.EVENT_DIR_NAME 等。
  - kb.py 通过末尾 re-export 段把本模块的函数再暴露成 kb._find_task_file 等"私有"名,
    保证 web 层和 tests 的 20+ 处旧调用零修改(向后兼容)。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

# 运行时获取 kb 模块(不在顶部 `import kb`,因为当 kb.py 作为 __main__ 被直接运行时,
# 顶部 import 会触发循环:kb.py 执行到 re-export 段 → import kb_entities → kb_entities
# 顶部 import kb → kb.py 作为 'kb' 模块被重新执行 → 又到 re-export 段... 死循环)。
# 用 sys.modules 查找既覆盖 `import kb`(测试/web 场景)也覆盖 `python kb.py`(__main__ 场景)。
# 每次 _kb() 调用都现取,保证 monkeypatch.setattr(kb, "VAULT_ROOT", ...) 在测试中实时生效。


def _kb():
    """运行时返回 kb 模块对象(import kb 或 python kb.py 的 __main__)。"""
    return sys.modules.get("kb") or sys.modules.get("__main__")


# ---------------------------------------------------------------------------
# 共享基础设施:损坏备份 + 日志 + 路径判断
# ---------------------------------------------------------------------------

def _backup_corrupt(src: Path, stem: str, ext: str) -> str:
    """把损坏的 src 文件备份到 .kb/logs/<stem>_<ts>.<ext>,返回中文提示消息。

    被三个 load_*_json_store 和 _log_scan_error 共用(原 kb.py 里四份拷贝的逻辑)。
    备份失败不抛,返回"备份失败"提示。
    """
    kb = _kb()
    try:
        backup_dir = kb.LOGS_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        corrupt_backup = backup_dir / f"{stem}_{ts}.{ext}"
        shutil.copy2(src, corrupt_backup)
        return f"(已备份到 {corrupt_backup.name})"
    except Exception as be:
        return f"(备份失败: {be})"


def _load_json_store(path: Path, empty_skeleton: dict, store_name: str) -> dict:
    """读取一个 JSON store(state/calendar/workspace_state),不存在返回空骨架。

    损坏(JSONDecodeError / OSError)时:备份 + 记日志 + 返回空骨架带 _corrupt 标记,
    调用方可通过 kb._check_corrupt(...) 识别并拒绝写(防 rebuild-index 掩盖数据丢失)。

    原本 kb.py 的 load_state / load_calendar / load_workspace_state 三份逐字拷贝,
    现统一到这里;三个函数各自只剩"声明空骨架形状 + 转发"的一行。
    """
    kb = _kb()
    if not path.exists():
        return dict(empty_skeleton)  # 不带 _corrupt
    try:
        return json.loads(kb.read_text(path))
    except (json.JSONDecodeError, OSError) as e:
        backup_msg = _backup_corrupt(path, f"corrupt_{store_name}", "json")
        try:
            kb.append_log(f"WARNING: {path.name} 损坏({type(e).__name__}: {e}) {backup_msg}")
        except Exception:
            pass  # 日志本身失败不能影响主流程
        result = dict(empty_skeleton)
        result["_corrupt"] = True
        result["_corrupt_error"] = str(e)
        return result


def _is_relative(path: Path) -> bool:
    """判断 path 是否在 VAULT_ROOT 下(用于决定 load_*_file 输出相对路径还是绝对路径)。"""
    kb = _kb()
    try:
        path.relative_to(kb.VAULT_ROOT)
        return True
    except ValueError:
        return False


def _log_scan_error(path: Path, err: Exception) -> None:
    """scan_* 遇到损坏文件时备份 + 记日志,不抛(调用方继续扫下一个)。

    与 _load_json_store 的损坏策略一致,只是目标是 .md 而非 .json。
    """
    kb = _kb()
    backup_msg = _backup_corrupt(path, f"corrupt_{path.stem}", "md")
    try:
        kb.append_log(f"WARNING: {path.name} 解析失败({type(err).__name__}: {err}) {backup_msg}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 共享骨架:find(快路径 + 兜底扫)+ scan(glob + 错误隔离 + sort)
# ---------------------------------------------------------------------------

def _find_entity_file(entity_id: str, dir_name: str, glob_pattern: str,
                      file_path_fn) -> Path | None:
    """扫描 <VAULT_ROOT>/<dir_name>/ 找 frontmatter id == entity_id 的文件。

    两段式:先走 file_path_fn(entity_id) 的文件名直查(快路径),命中即返回;
    再兜底 glob 所有匹配文件,逐个 parsefrontmatter 校验 id(文件名可能被手改)。
    三个 _find_*_file 原本各自重复这套逻辑,现统一。
    """
    kb = _kb()
    entity_dir = kb.VAULT_ROOT / dir_name
    if not entity_dir.exists():
        return None
    direct = file_path_fn(entity_id)
    if direct.exists():
        return direct
    for path in entity_dir.glob(glob_pattern):
        try:
            meta, _ = kb.parsefrontmatter(kb.read_text(path))
            if meta.get("id", "").strip() == entity_id:
                return path
        except Exception:
            continue
    return None


def _scan_entities(dir_name: str, glob_pattern: str, loader, sort_key) -> list[dict]:
    """扫描 <VAULT_ROOT>/<dir_name>/<glob_pattern>,逐个 loader 加载,sort_key 排序。

    单个文件解析失败隔离(_log_scan_error 备份 + 记日志,不阻断扫描)。
    三个 scan_* 原本各自重复这套 glob+try/_log_scan_error 骨架,现统一。
    sort_key 是个函数,接收 dict 返回排序键(各实体排序规则不同)。
    """
    kb = _kb()
    entity_dir = kb.VAULT_ROOT / dir_name
    if not entity_dir.exists():
        return []
    results: list[dict] = []
    for path in sorted(entity_dir.glob(glob_pattern)):
        try:
            results.append(loader(path))
        except Exception as e:
            _log_scan_error(path, e)
    results.sort(key=sort_key)
    return results


# ---------------------------------------------------------------------------
# Event(事件)管理 —— 06_Events/event_*.md
# ---------------------------------------------------------------------------

def make_event_id(title: str) -> str:
    """生成稳定事件 id:event_<8位hash>。基于标题+当前时刻,保证新建不冲突。"""
    kb = _kb()
    raw = f"{title}|{time.time_ns()}"
    return f"event_{kb.content_hash(raw)}"


def _event_file_path(event_id: str) -> Path:
    """由 event_id 推导对应的 markdown 文件路径。"""
    kb = _kb()
    slug_part = event_id.removeprefix("event_")
    return kb.VAULT_ROOT / kb.EVENT_DIR_NAME / f"event_{slug_part}.md"


def _find_event_file(event_id: str) -> Path | None:
    """扫描 06_Events/ 找到 frontmatter id == event_id 的文件。返回路径或 None。"""
    return _find_entity_file(event_id, _kb().EVENT_DIR_NAME, "event_*.md", _event_file_path)


def _format_event_file(meta: dict, body: str) -> str:
    """把事件 meta dict + 正文格式化成完整 markdown 文件内容(frontmatter + body)。

    所有字段用单行字符串;synced_calendar_ids 用逗号分隔(避免 YAML 列表解析复杂度)。
    v0.4.12: 新增 completed_at 字段(与 task 对称,供事件完成时间统计)。
    """
    lines = ["---"]
    for key in ("id", "title", "date", "category", "note", "status",
                "related_source", "synced_calendar_ids", "created_at", "updated_at",
                "completed_at"):
        val = meta.get(key, "")
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无描述）")
    return "\n".join(lines) + "\n"


def load_event_file(path: Path) -> dict:
    """读事件 markdown 文件,返回完整字段 dict(含 body)。

    synced_calendar_ids 解析成 list[str](逗号分隔),其余字段为字符串。
    """
    kb = _kb()
    text = kb.read_text(path)
    meta, body = kb.parsefrontmatter(text)
    synced_raw = meta.get("synced_calendar_ids", "")
    synced = [s.strip() for s in synced_raw.split(",") if s.strip()] if synced_raw else []
    return {
        "id": meta.get("id", "").strip(),
        "title": meta.get("title", "").strip(),
        "date": meta.get("date", "").strip(),
        "category": meta.get("category", "其他").strip() or "其他",
        "note": meta.get("note", "").strip(),
        "status": meta.get("status", "active").strip() or "active",
        "related_source": meta.get("related_source", "").strip(),
        "synced_calendar_ids": synced,
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "completed_at": meta.get("completed_at", "").strip(),
        "body": body,
        "path": path.relative_to(kb.VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_events() -> list[dict]:
    """扫描 06_Events/event_*.md,返回按日期升序排列的事件列表(无日期排末尾)。

    loader 走 kb.load_event_file(而非本模块直接引用),保证 tests 用
    monkeypatch.setattr(kb, "load_event_file", ...) 注入故障时能生效。
    """
    return _scan_entities(
        _kb().EVENT_DIR_NAME, "event_*.md", _kb().load_event_file,
        sort_key=lambda e: e.get("date", "") or "9999",
    )


def write_event_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """原子写事件文件。新建时补 created_at,更新时刷新 updated_at。

    completed_at 生命周期(v0.4.12,与 task 对称):status==done 且无值时写入,
    非 done 清空。旧文件缺该字段时首次标 done 补当天。
    """
    kb = _kb()
    now = kb.now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    if meta.get("status") == "done":
        if not meta.get("completed_at"):
            meta["completed_at"] = now
    else:
        meta["completed_at"] = ""
    meta["updated_at"] = now
    kb.write_text(path, _format_event_file(meta, body))


def sync_event_to_calendar(event_id: str) -> dict:
    """把单个事件单向推送到日历(创建一条 calendar item,回指 event_id)。

    幂等:若该事件已有存活的 calendar item(synced_calendar_ids 里仍有在日历中的),
    不重复创建。日历项被删后允许重新推送。
    """
    import uuid as _uuid
    kb = _kb()

    path = _find_event_file(event_id)
    if path is None:
        return {"synced": False, "event_id": event_id, "reason": "event_not_found"}

    event = load_event_file(path)
    if not event["date"]:
        return {"synced": False, "event_id": event_id, "reason": "event_has_no_date"}

    cal = kb.load_calendar()
    items = cal.get("items", {})

    # 幂等:检查已有同步项是否仍存活
    for existing_id in event["synced_calendar_ids"]:
        if existing_id in items:
            return {
                "synced": False, "event_id": event_id,
                "calendar_id": existing_id, "reason": "already_synced",
            }

    # 创建新日历项(回指 event,source_type=event 供前端识别来源)
    item_id = f"cal_{_uuid.uuid4().hex[:12]}"
    now = kb.now_ts()
    item = {
        "id": item_id,
        "title": event["title"],
        "date": event["date"],
        "note": event["note"],
        "source_id": "",          # 不关联文章,关联的是事件
        "source_type": "event",
        "source_title": event["title"],
        "event_id": event_id,     # 回指事件(日历项来源关联)
        "category": event["category"],
        "date_source": "manual",
        "date_confidence": "",
        "created_at": now,
        "updated_at": now,
    }
    items[item_id] = item
    cal["items"] = items
    kb.save_calendar(cal)

    # 把新 item id 追加进 event 的 synced_calendar_ids 写回 frontmatter
    new_synced = event["synced_calendar_ids"] + [item_id]
    meta = {k: v for k, v in event.items() if k not in ("body", "path")}
    meta["synced_calendar_ids"] = ",".join(new_synced)
    write_event_file(path, meta, event["body"], is_new=False)

    return {
        "synced": True, "event_id": event_id,
        "calendar_id": item_id, "reason": "created",
    }


# ---------------------------------------------------------------------------
# Market(市场)管理 —— 08_Market/market_*.md
# 仅 watchlist=自选股/赛道(alert 异动已合并到 event 系统,不再单独管理)
# ---------------------------------------------------------------------------

# ticker 规范化存储为 "<MARKET>:<CODE>"(如 SH:600519 / HK:0700 / US:AAPL),
# 中立可读、不绑定具体 API。校验只做格式判断(离线优先),不联网查重。
# 覆盖:A股(沪 SH / 深 SZ / 北交所 BJ)、港股 HK、美股 US;ETF 归入 SH/SZ。
MARKET_CODES = ("SH", "SZ", "BJ", "HK", "US")

# A 股各交易所合法前缀(6 位数字的前 2-3 位)
MARKET_CODE_PREFIXES: dict[str, tuple[str, ...]] = {
    "SH": ("600", "601", "603", "605", "688", "690", "70", "11", "13", "50", "51", "52", "56", "58"),
    #  沪:主板(600/601/603/605)、科创板(688/690)、B股(900)、沪市ETF/基金(5开头)、转债(11)
    "SZ": ("000", "001", "002", "003", "300", "301", "159", "184", "128", "123"),
    #  深:主板(000/001/002/003)、创业板(300/301)、深市ETF(159)、可转债(123/128)
    "BJ": ("43", "83", "87", "88", "92", "82", "88"),  # 北交所:4/8 开头
}
MARKET_CODE_LABELS: dict[str, str] = {  # 中文显示名(供前端卡片展示)
    "SH": "沪", "SZ": "深", "BJ": "京", "HK": "港", "US": "美",
}

_US_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")  # 美股:1-5 大写字母,可一个 . 后接1-2字母


def validate_ticker(market: str, code: str) -> str | None:
    """校验「市场 + 原始代码」组合是否可能存在。

    返回 None = 合法;返回非空字符串 = 中文错误描述(直接当 HTTPException detail)。
    code 为空时视为合法(代码非必填,只校验「填了就必须对」)。
    """
    code = (code or "").strip()
    if not code:
        return None  # 代码非必填
    mkt = (market or "").strip().upper()
    if mkt not in MARKET_CODES:
        return f"未知市场:{market}(支持 {', '.join(MARKET_CODES)})"
    if mkt == "US":
        # 美股:大小写不敏感校验(normalize 时统一转大写),否则小写 aapl 会被误拒
        if not _US_TICKER_RE.match(code.upper()):
            return f"美股代码格式错误:{code}(应为 1-5 位字母,可含一个点如 BRK.B)"
        return None
    # 数字类市场(SH/SZ/BJ/HK):必须纯数字
    if not code.isdigit():
        return f"{MARKET_CODE_LABELS.get(mkt, mkt)}股代码必须为数字:{code}"
    if mkt == "HK":
        if not (1 <= len(code) <= 5):
            return f"港股代码应为 1-5 位数字:{code}"
        return None
    # A 股(SH/SZ/BJ):必须 6 位数字
    if len(code) != 6:
        return f"A股代码应为 6 位数字:{code}"
    prefixes = MARKET_CODE_PREFIXES.get(mkt, ())
    if not any(code.startswith(p) for p in prefixes):
        return f"{MARKET_CODE_LABELS.get(mkt, mkt)}股代码前缀不合法:{code}({mkt} 常见前缀:{', '.join(prefixes[:5])}…)"
    return None


def normalize_ticker(market: str, raw: str) -> str:
    """市场 + 原始代码 → 规范化 'MARKET:CODE'。非法组合抛 ValueError。

    raw 已含冒号(如 'SH:600519')时,以 market 参数为准重新拼装。
    raw 为空时返回空串(代码非必填)。
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    mkt = (market or "").strip().upper()
    # 去掉 raw 里可能自带的市场前缀
    code = raw.split(":", 1)[-1].strip() if ":" in raw else raw
    # 美股统一大写
    if mkt == "US":
        code = code.upper()
    err = validate_ticker(mkt, code)
    if err:
        raise ValueError(err)
    return f"{mkt}:{code}"


def parse_ticker(stored: str) -> tuple[str, str]:
    """规范化 ticker 'SH:600519' → ('SH', '600519')。

    无冒号(旧裸数据)时尝试自动识别:6 位数字按前缀判 SH/SZ/BJ,纯字母判 US,
    其他数字判 HK,识别不出返回 ('', 原值) 不报错(向后兼容)。
    """
    s = (stored or "").strip()
    if not s:
        return ("", "")
    if ":" in s:
        mkt, code = s.split(":", 1)
        return (mkt.strip().upper(), code.strip())
    # 旧数据自动识别
    if s.isdigit():
        if len(s) == 6:
            for mkt, prefixes in MARKET_CODE_PREFIXES.items():
                if any(s.startswith(p) for p in prefixes):
                    return (mkt, s)
            return ("", s)  # 6 位数字但前缀不匹配,保留原样
        if 1 <= len(s) <= 5:
            return ("HK", s)
        return ("", s)
    if _US_TICKER_RE.match(s):
        return ("US", s)
    return ("", s)


def make_market_id(title: str, kind: str) -> str:
    """生成稳定市场条目 id:market_<kind>_<8位hash>。基于标题+kind+当前时刻。"""
    kb = _kb()
    raw = f"{kind}|{title}|{time.time_ns()}"
    return f"market_{kind}_{kb.content_hash(raw)}"


def _market_file_path(market_id: str) -> Path:
    """由 market_id 推导对应 markdown 文件路径。"""
    kb = _kb()
    slug_part = market_id.removeprefix("market_")
    return kb.VAULT_ROOT / kb.MARKET_DIR_NAME / f"market_{slug_part}.md"


def _find_market_file(market_id: str) -> Path | None:
    """扫描 08_Market/ 找到 frontmatter id == market_id 的文件。返回路径或 None。"""
    return _find_entity_file(market_id, _kb().MARKET_DIR_NAME, "market_*.md", _market_file_path)


def _format_market_file(meta: dict, body: str) -> str:
    """把 market meta dict + 正文格式化成完整 markdown 文件(frontmatter + body)。

    字段:watchlist 用 ticker/sector + 持仓位置(cost_price/shares/target_price/
    stop_price),不适用的字段写空串。所有字段单行字符串。
    """
    lines = ["---"]
    for key in ("id", "kind", "title", "market", "ticker", "sector",
                "cost_price", "shares", "target_price", "stop_price",
                "note", "status",
                "created_at", "updated_at"):
        val = meta.get(key, "")
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无描述）")
    return "\n".join(lines) + "\n"


def load_market_file(path: Path) -> dict:
    """读市场条目 markdown 文件,返回完整字段 dict(含 body)。"""
    kb = _kb()
    text = kb.read_text(path)
    meta, body = kb.parsefrontmatter(text)
    return {
        "id": meta.get("id", "").strip(),
        "kind": meta.get("kind", "watchlist").strip() or "watchlist",
        "title": meta.get("title", "").strip(),
        "market": meta.get("market", "").strip(),
        "ticker": meta.get("ticker", "").strip(),
        "sector": meta.get("sector", "").strip(),
        "cost_price": meta.get("cost_price", "").strip(),
        "shares": meta.get("shares", "").strip(),
        "target_price": meta.get("target_price", "").strip(),
        "stop_price": meta.get("stop_price", "").strip(),
        "note": meta.get("note", "").strip(),
        "status": meta.get("status", "active").strip() or "active",
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "body": body,
        "path": path.relative_to(kb.VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_market(kind: str | None = None) -> list[dict]:
    """扫描 08_Market/market_*.md,可选按 kind 过滤。

    按标题字母序。目录不存在或无文件返回 []。损坏文件备份 + 记日志(与 scan_events 同款)。

    loader 走 kb.load_market_file(而非本模块直接引用),保证 tests 用
    monkeypatch.setattr(kb, "load_market_file", ...) 注入故障时能生效。
    """
    kb = _kb()
    results = _scan_entities(
        kb.MARKET_DIR_NAME, "market_*.md", kb.load_market_file,
        sort_key=lambda r: r.get("title", ""),
    )
    if kind:
        results = [r for r in results if r.get("kind") == kind]
    return results


def write_market_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """原子写市场条目文件。新建时补 created_at,更新时刷新 updated_at。"""
    kb = _kb()
    now = kb.now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    meta["updated_at"] = now
    kb.write_text(path, _format_market_file(meta, body))


# ---------------------------------------------------------------------------
# Market judgment(个人判断) —— 08_Market/judgment_*.md
# ---------------------------------------------------------------------------

def _fm_json_text(raw) -> str:
    """Return a frontmatter-safe JSON string scalar."""
    return json.dumps("" if raw is None else str(raw), ensure_ascii=False)


def _read_fm_json_text(raw) -> str:
    """Read a string written by _fm_json_text, with plain-text legacy fallback."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        val = json.loads(raw)
        if isinstance(val, str):
            return val
    except (json.JSONDecodeError, TypeError):
        pass
    return raw


def make_market_judgment_id(title: str) -> str:
    """Generate a market judgment id: judgment_<hash>."""
    kb = _kb()
    raw = f"{title}|{time.time_ns()}"
    return f"judgment_{kb.content_hash(raw)}"


def _market_judgment_file_path(judgment_id: str) -> Path:
    """Return the markdown path for a market judgment id."""
    kb = _kb()
    slug_part = judgment_id.removeprefix("judgment_")
    return kb.VAULT_ROOT / kb.MARKET_DIR_NAME / f"judgment_{slug_part}.md"


def _find_market_judgment_file(judgment_id: str) -> Path | None:
    """Find a market judgment markdown file by frontmatter id."""
    return _find_entity_file(
        judgment_id, _kb().MARKET_DIR_NAME, "judgment_*.md", _market_judgment_file_path
    )


def _format_market_judgment_file(meta: dict, body: str) -> str:
    """Format market judgment metadata + markdown body."""
    lines = ["---"]
    for key in ("id", "title", "target", "judgment", "judged_at", "horizon",
                "verdict", "actual_result", "reviewed_at",
                "created_at", "updated_at"):
        val = meta.get(key, "")
        if key in ("title", "target", "judgment", "horizon", "actual_result"):
            val = _fm_json_text(val)
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无补充）")
    return "\n".join(lines) + "\n"


def load_market_judgment_file(path: Path) -> dict:
    """Read a market judgment markdown file."""
    kb = _kb()
    text = kb.read_text(path)
    meta, body = kb.parsefrontmatter(text)
    return {
        "id": meta.get("id", "").strip(),
        "title": _read_fm_json_text(meta.get("title", "")),
        "target": _read_fm_json_text(meta.get("target", "")),
        "judgment": _read_fm_json_text(meta.get("judgment", "")),
        "judged_at": meta.get("judged_at", "").strip(),
        "horizon": _read_fm_json_text(meta.get("horizon", "")),
        "verdict": meta.get("verdict", "pending").strip() or "pending",
        "actual_result": _read_fm_json_text(meta.get("actual_result", "")),
        "reviewed_at": meta.get("reviewed_at", "").strip(),
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "body": body,
        "path": path.relative_to(kb.VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_market_judgments() -> list[dict]:
    """Scan market judgments, newest judged_at first."""
    kb = _kb()
    results = _scan_entities(
        kb.MARKET_DIR_NAME, "judgment_*.md", kb.load_market_judgment_file,
        sort_key=lambda r: r.get("judged_at", ""),
    )
    results.reverse()
    return results


def write_market_judgment_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """Atomically write a market judgment markdown file."""
    kb = _kb()
    now = kb.now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    meta["updated_at"] = now
    kb.write_text(path, _format_market_judgment_file(meta, body))


# ---------------------------------------------------------------------------
# Market simulation(模拟盘) —— 08_Market/simulation_*.md
# ---------------------------------------------------------------------------

def make_market_simulation_id(title: str) -> str:
    """Generate a market simulation id: simulation_<hash>."""
    kb = _kb()
    raw = f"{title}|{time.time_ns()}"
    return f"simulation_{kb.content_hash(raw)}"


def _market_simulation_file_path(simulation_id: str) -> Path:
    """Return the markdown path for a market simulation id."""
    kb = _kb()
    slug_part = simulation_id.removeprefix("simulation_")
    return kb.VAULT_ROOT / kb.MARKET_DIR_NAME / f"simulation_{slug_part}.md"


def _find_market_simulation_file(simulation_id: str) -> Path | None:
    """Find a market simulation markdown file by frontmatter id."""
    return _find_entity_file(
        simulation_id, _kb().MARKET_DIR_NAME, "simulation_*.md", _market_simulation_file_path
    )


def _format_market_simulation_file(meta: dict, body: str) -> str:
    """Format market simulation metadata + markdown body."""
    lines = ["---"]
    for key in ("id", "title", "market", "ticker", "sector",
                "entry_price", "shares", "entry_date",
                "target_price", "stop_price",
                "status", "exit_price", "exit_date", "note",
                "created_at", "updated_at"):
        val = meta.get(key, "")
        if key in ("title", "sector", "note"):
            val = _fm_json_text(val)
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无补充）")
    return "\n".join(lines) + "\n"


def load_market_simulation_file(path: Path) -> dict:
    """Read a market simulation markdown file."""
    kb = _kb()
    text = kb.read_text(path)
    meta, body = kb.parsefrontmatter(text)
    return {
        "id": meta.get("id", "").strip(),
        "title": _read_fm_json_text(meta.get("title", "")),
        "market": meta.get("market", "").strip(),
        "ticker": meta.get("ticker", "").strip(),
        "sector": _read_fm_json_text(meta.get("sector", "")),
        "entry_price": meta.get("entry_price", "").strip(),
        "shares": meta.get("shares", "").strip(),
        "entry_date": meta.get("entry_date", "").strip(),
        "target_price": meta.get("target_price", "").strip(),
        "stop_price": meta.get("stop_price", "").strip(),
        "status": meta.get("status", "active").strip() or "active",
        "exit_price": meta.get("exit_price", "").strip(),
        "exit_date": meta.get("exit_date", "").strip(),
        "note": _read_fm_json_text(meta.get("note", "")),
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "body": body,
        "path": path.relative_to(kb.VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_market_simulations(status: str | None = None) -> list[dict]:
    """Scan market simulations, newest entry_date/created_at first."""
    kb = _kb()
    results = _scan_entities(
        kb.MARKET_DIR_NAME, "simulation_*.md", kb.load_market_simulation_file,
        sort_key=lambda r: (r.get("entry_date", ""), r.get("created_at", ""), r.get("title", "")),
    )
    results.reverse()
    if status:
        results = [r for r in results if r.get("status") == status]
    return results


def write_market_simulation_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """Atomically write a market simulation markdown file."""
    kb = _kb()
    now = kb.now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    meta["updated_at"] = now
    kb.write_text(path, _format_market_simulation_file(meta, body))


# ---------------------------------------------------------------------------
# Task(任务)管理 —— 07_Tasks/task_*.md
# 与 04_Plans/plan_suggestions.md(从文章抽取的计划建议)是完全不同的系统。
# 新增 checklist(JSON 结构化)+ deadline + blocker + pinned 字段。
# ---------------------------------------------------------------------------

def make_task_id(title: str) -> str:
    """生成稳定任务 id:task_<8位hash>。基于标题+当前时刻,保证新建不冲突。"""
    kb = _kb()
    raw = f"{title}|{time.time_ns()}"
    return f"task_{kb.content_hash(raw)}"


def _task_file_path(task_id: str) -> Path:
    """由 task_id 推导对应的 markdown 文件路径。"""
    kb = _kb()
    slug_part = task_id.removeprefix("task_")
    return kb.VAULT_ROOT / kb.TASK_DIR_NAME / f"task_{slug_part}.md"


def _find_task_file(task_id: str) -> Path | None:
    """扫描 07_Tasks/ 找到 frontmatter id == task_id 的文件。返回路径或 None。"""
    return _find_entity_file(task_id, _kb().TASK_DIR_NAME, "task_*.md", _task_file_path)


def _format_task_file(meta: dict, body: str) -> str:
    """把任务 meta dict + 正文格式化成完整 markdown 文件内容(frontmatter + body)。

    checklist 存为 JSON 字符串(单行),load 时 json.loads 还原成 list[dict]。
    synced_calendar_ids 用逗号分隔(避免 YAML 列表解析复杂度)。
    """
    kb = _kb()
    cl = meta.get("checklist", [])
    if isinstance(cl, list):
        cl = json.dumps(cl, ensure_ascii=False)
    lines = ["---"]
    for key in ("id", "title", "category", "project", "status",
                "deadline", "blocker", "next_action", "checklist",
                "related_source", "synced_calendar_ids",
                "created_at", "updated_at", "completed_at", "pinned", "pinned_at"):
        val = meta.get(key, "")
        # checklist 字段用 JSON 字符串,其余字段原样输出
        if key == "checklist":
            val = cl if cl else "[]"
        elif key == "pinned":
            # 布尔统一输出 true/false(避免 Python True 被写成 "True")
            val = "true" if kb._parse_bool(val) else "false"
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无描述）")
    return "\n".join(lines) + "\n"


def load_task_file(path: Path) -> dict:
    """读任务 markdown 文件,返回完整字段 dict(含 body)。

    checklist 解析成 list[dict](JSON 反序列化),synced_calendar_ids 解析成 list[str]。
    """
    kb = _kb()
    text = kb.read_text(path)
    meta, body = kb.parsefrontmatter(text)
    # checklist:JSON 字符串 → list[dict]
    cl_raw = meta.get("checklist", "[]") or "[]"
    if isinstance(cl_raw, list):
        checklist = cl_raw
    else:
        try:
            checklist = json.loads(cl_raw) if cl_raw else []
        except (json.JSONDecodeError, TypeError):
            checklist = []
    # 兼容旧数据:确保每项有 id/text/done
    for item in checklist:
        if not isinstance(item, dict):
            continue
        item.setdefault("id", "")
        item.setdefault("text", "")
        item.setdefault("done", False)
    synced_raw = meta.get("synced_calendar_ids", "")
    synced = [s.strip() for s in synced_raw.split(",") if s.strip()] if synced_raw else []
    return {
        "id": meta.get("id", "").strip(),
        "title": meta.get("title", "").strip(),
        "category": meta.get("category", "其他").strip() or "其他",
        "project": meta.get("project", "").strip(),
        "status": meta.get("status", "active").strip() or "active",
        "deadline": meta.get("deadline", "").strip(),
        "blocker": meta.get("blocker", "").strip(),
        "next_action": meta.get("next_action", "").strip(),
        "checklist": checklist,
        "related_source": meta.get("related_source", "").strip(),
        "synced_calendar_ids": synced,
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "completed_at": meta.get("completed_at", "").strip(),
        "pinned": kb._parse_bool(meta.get("pinned", "false")),  # 旧文件无此字段默认 false
        "pinned_at": meta.get("pinned_at", "").strip(),  # 置顶时间戳;组内按此倒序(最近置顶在前)
        "body": body,
        "path": path.relative_to(kb.VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_tasks() -> list[dict]:
    """扫描 07_Tasks/task_*.md,返回按 deadline 升序排列的任务列表。

    无 deadline 的排末尾(用 9999 sentinel)。

    loader 走 kb.load_task_file(而非本模块直接引用),保证 tests 用
    monkeypatch.setattr(kb, "load_task_file", ...) 注入故障时能生效。
    """
    return _scan_entities(
        _kb().TASK_DIR_NAME, "task_*.md", _kb().load_task_file,
        sort_key=lambda t: t.get("deadline", "") or "9999",
    )


def write_task_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """原子写任务文件。新建时补 created_at,更新时刷新 updated_at。

    completed_at 生命周期(v0.4.11 工作台本周概览需要):
    - status==done 且无 completed_at → 写当前时间(首次完成)
    - status==done 且已有 completed_at → 保留(重复打 done 不覆盖首次完成时间)
    - status!=done → 清空(任务被重新激活)
    旧任务文件无此字段时,首次标记 done 会补当天时间(历史完成时间已丢失,无法回溯)。
    """
    kb = _kb()
    now = kb.now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    if meta.get("status") == "done":
        if not meta.get("completed_at"):
            meta["completed_at"] = now
    else:
        meta["completed_at"] = ""
    meta["updated_at"] = now
    kb.write_text(path, _format_task_file(meta, body))


def sync_task_to_calendar(task_id: str) -> dict:
    """把单个任务单向推送到日历(创建一条 calendar item,回指 task_id)。

    幂等:若该任务已有存活的 calendar item,不重复创建。日历项被删后允许重新推送。
    """
    import uuid as _uuid
    kb = _kb()

    path = _find_task_file(task_id)
    if path is None:
        return {"synced": False, "task_id": task_id, "reason": "task_not_found"}

    task = load_task_file(path)
    if not task["deadline"]:
        return {"synced": False, "task_id": task_id, "reason": "task_has_no_deadline"}

    cal = kb.load_calendar()
    items = cal.get("items", {})

    for existing_id in task["synced_calendar_ids"]:
        if existing_id in items:
            return {
                "synced": False, "task_id": task_id,
                "calendar_id": existing_id, "reason": "already_synced",
            }

    item_id = f"cal_{_uuid.uuid4().hex[:12]}"
    now = kb.now_ts()
    item = {
        "id": item_id,
        "title": task["title"],
        "date": task["deadline"],
        "note": task["blocker"] or "",
        "source_id": "",
        "source_type": "task",
        "source_title": task["title"],
        "task_id": task_id,
        "category": "截止日期",
        "date_source": "manual",
        "date_confidence": "",
        "created_at": now,
        "updated_at": now,
    }
    items[item_id] = item
    cal["items"] = items
    kb.save_calendar(cal)

    new_synced = task["synced_calendar_ids"] + [item_id]
    meta = {k: v for k, v in task.items() if k not in ("body", "path")}
    meta["synced_calendar_ids"] = ",".join(new_synced)
    write_task_file(path, meta, task["body"], is_new=False)

    return {
        "synced": True, "task_id": task_id,
        "calendar_id": item_id, "reason": "created",
    }


# ---------------------------------------------------------------------------
# Plan(计划)实体:每条独立文件,带 deadline 字段(v0.4.23 重构,废弃 weekly/monthly/someday 分桶)
# 照搬 task 模式,字段更精简(无 checklist/category/project/blocker/pinned)。
# ---------------------------------------------------------------------------

def make_plan_id(title: str) -> str:
    """生成稳定 plan id:plan_<8位hash>。基于标题+当前时刻,保证新建不冲突。"""
    import time
    kb = _kb()
    raw = f"{title}|{time.time_ns()}"
    return f"plan_{kb.content_hash(raw)}"


def _plan_file_path(plan_id: str) -> Path:
    """由 plan_id 推导对应的 markdown 文件路径。"""
    slug_part = plan_id.removeprefix("plan_")
    kb = _kb()
    return kb.VAULT_ROOT / kb.PLAN_DIR_NAME / f"plan_{slug_part}.md"


def _find_plan_file(plan_id: str) -> Path | None:
    """扫描 04_Plans/ 找到 frontmatter id == plan_id 的文件。返回路径或 None。"""
    return _find_entity_file(plan_id, _kb().PLAN_DIR_NAME, "plan_*.md", _plan_file_path)


def _format_plan_file(meta: dict, body: str) -> str:
    """把 plan meta dict + 正文格式化成完整 markdown 文件(frontmatter + body)。

    synced_calendar_ids 用逗号分隔(避免 YAML 列表解析复杂度)。
    """
    lines = ["---"]
    for key in ("id", "title", "deadline", "status", "source_summary",
                "related_source", "synced_calendar_ids",
                "created_at", "updated_at", "completed_at"):
        val = meta.get(key, "")
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无描述）")
    return "\n".join(lines) + "\n"


def load_plan_file(path: Path) -> dict:
    """读 plan markdown 文件,返回完整字段 dict(含 body)。

    synced_calendar_ids 解析成 list[str]。
    """
    kb = _kb()
    text = kb.read_text(path)
    meta, body = kb.parsefrontmatter(text)
    synced_raw = meta.get("synced_calendar_ids", "")
    synced = [s.strip() for s in synced_raw.split(",") if s.strip()] if synced_raw else []
    return {
        "id": meta.get("id", "").strip(),
        "title": meta.get("title", "").strip(),
        "deadline": meta.get("deadline", "").strip(),
        "status": meta.get("status", "active").strip() or "active",
        "source_summary": meta.get("source_summary", "").strip(),
        "related_source": meta.get("related_source", "").strip(),
        "synced_calendar_ids": synced,
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "completed_at": meta.get("completed_at", "").strip(),
        "body": body,
        "path": path.relative_to(kb.VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_plans() -> list[dict]:
    """扫描 04_Plans/plan_*.md,返回按 deadline 升序排列的 plan 列表。

    无 deadline 的排末尾(用 9999 sentinel)。每个元素是 load_plan_file 的返回 dict。
    v0.4.23: 不再扫 Weekly/Monthly/someday 分桶(已废弃)。
    注意:排除 plan_suggestions.md(review 队列文件,也匹配 plan_*.md 但不是独立 plan)。
    """
    kb = _kb()
    entity_dir = kb.VAULT_ROOT / kb.PLAN_DIR_NAME
    if not entity_dir.exists():
        return []
    results: list[dict] = []
    for path in sorted(entity_dir.glob("plan_*.md")):
        if path.name == "plan_suggestions.md":  # review 队列,非独立 plan
            continue
        try:
            results.append(load_plan_file(path))
        except Exception as e:
            _log_scan_error(path, e)
    results.sort(key=lambda t: t.get("deadline", "") or "9999")
    return results


def write_plan_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """原子写 plan 文件。新建时补 created_at,更新时刷新 updated_at。

    completed_at 生命周期(与 task 一致):
    - status==done 且无 completed_at → 写当前时间(首次完成)
    - status==done 且已有 completed_at → 保留
    - status!=done → 清空
    """
    kb = _kb()
    now = kb.now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    if meta.get("status") == "done":
        if not meta.get("completed_at"):
            meta["completed_at"] = now
    else:
        meta["completed_at"] = ""
    meta["updated_at"] = now
    kb.write_text(path, _format_plan_file(meta, body))


def sync_plan_to_calendar(plan_id: str) -> dict:
    """把单个 plan 单向推送到日历(创建一条 calendar item,回指 plan_id)。

    幂等:若该 plan 已有存活的 calendar item,不重复创建。日历项被删后允许重新推送。
    plan 无 deadline 返回 400(与 task 同语义)。
    """
    import uuid as _uuid
    kb = _kb()

    path = _find_plan_file(plan_id)
    if path is None:
        return {"synced": False, "plan_id": plan_id, "reason": "plan_not_found"}

    plan = load_plan_file(path)
    if not plan["deadline"]:
        return {"synced": False, "plan_id": plan_id, "reason": "plan_has_no_deadline"}

    cal = kb.load_calendar()
    items = cal.get("items", {})

    for existing_id in plan["synced_calendar_ids"]:
        if existing_id in items:
            return {
                "synced": False, "plan_id": plan_id,
                "calendar_id": existing_id, "reason": "already_synced",
            }

    item_id = f"cal_{_uuid.uuid4().hex[:12]}"
    now = kb.now_ts()
    item = {
        "id": item_id,
        "title": plan["title"],
        "date": plan["deadline"],
        "note": "",
        "source_id": "",
        "source_type": "plan",
        "source_title": plan["title"],
        "plan_id": plan_id,
        "category": "截止日期",
        "date_source": "manual",
        "date_confidence": "",
        "created_at": now,
        "updated_at": now,
    }
    items[item_id] = item
    cal["items"] = items
    kb.save_calendar(cal)

    new_synced = plan["synced_calendar_ids"] + [item_id]
    meta = {k: v for k, v in plan.items() if k not in ("body", "path")}
    meta["synced_calendar_ids"] = ",".join(new_synced)
    write_plan_file(path, meta, plan["body"], is_new=False)

    return {
        "synced": True, "plan_id": plan_id,
        "calendar_id": item_id, "reason": "created",
    }


# ---------------------------------------------------------------------------
# 悬空引用清理(v0.4.12 修复 M5)
# ---------------------------------------------------------------------------
# 删除 calendar item / task / event / 文章后,frontmatter 里的回指字段
# (synced_calendar_ids / related_source)不会自动清理,长期累积成悬空指针。
# 以下函数扫 markdown 文件清理这些引用。失败静默(清理不应阻断主操作)。

def _cleanup_ref_field(field_name: str, target_value: str) -> int:
    """通用骨架:遍历 task/event 文件,清空等于 target_value 的回指字段。

    field_name: 'synced_calendar_ids' 或 'related_source'
    target_value: 要清除的值(cal_id 或 source_id)
    返回改写的文件数。

    两字段的语义差异在这里处理:synced_calendar_ids 是 list(过滤掉目标值),
    related_source 是字符串(直接清空)。
    """
    kb = _kb()
    n = 0
    for loader, finder_all, writer in (
        (load_task_file, lambda: (kb.VAULT_ROOT / kb.TASK_DIR_NAME).glob("task_*.md"), write_task_file),
        (load_event_file, lambda: (kb.VAULT_ROOT / kb.EVENT_DIR_NAME).glob("event_*.md"), write_event_file),
        (load_plan_file, lambda: (kb.VAULT_ROOT / kb.PLAN_DIR_NAME).glob("plan_*.md"), write_plan_file),
    ):
        try:
            for path in finder_all():
                try:
                    rec = loader(path)
                except Exception:
                    continue
                current = rec.get(field_name, [])
                if field_name == "synced_calendar_ids":
                    if not isinstance(current, list) or target_value not in current:
                        continue
                    new_val = [x for x in current if x != target_value]
                    joined = ",".join(new_val)
                else:  # related_source
                    if not isinstance(current, str) or current.strip() != target_value:
                        continue
                    joined = ""
                meta = {k: v for k, v in rec.items() if k not in ("body", "path")}
                meta[field_name] = joined
                writer(path, meta, rec.get("body", ""), is_new=False)
                n += 1
        except Exception:
            continue
    return n


def cleanup_calendar_ref(cal_id: str) -> int:
    """从所有 task/event 的 synced_calendar_ids 里移除指定 cal_id。

    返回清理的文件数。失败静默返回 0。
    """
    return _cleanup_ref_field("synced_calendar_ids", cal_id)


def cleanup_source_ref(source_id: str) -> int:
    """从所有 task/event 的 related_source 字段清空(指向该 source 的)。

    删除文章后调用,避免 related_source 悬空 404。返回清理的文件数。
    """
    return _cleanup_ref_field("related_source", source_id)


def cleanup_dead_calendar_items() -> int:
    """删除回指已不存在的 task/event 的孤儿日历项(M6)。

    供 CLI reconcile 命令调用。返回删除的孤儿项数。
    """
    kb = _kb()
    cal = kb.load_calendar()
    items = cal.get("items", {})
    dead = []
    for cal_id, item in list(items.items()):
        src_type = item.get("source_type", "")
        ref_id = item.get("task_id", "") or item.get("event_id", "")
        if src_type == "task" and ref_id:
            if _find_task_file(ref_id) is None:
                dead.append(cal_id)
        elif src_type == "event" and ref_id:
            if _find_event_file(ref_id) is None:
                dead.append(cal_id)
    for cal_id in dead:
        del items[cal_id]
    if dead:
        cal["items"] = items
        kb.save_calendar(cal)
    return len(dead)
