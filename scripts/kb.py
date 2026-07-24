#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Obsidian 本地知识库 CLI

本地优先的 Markdown 知识库:采集 → 总结 → idea/todo 建议 → 用户确认 → 正式清单。

命令:
    python scripts/kb.py init                 创建 vault 目录结构 / 模板 / 空文件 / state.json
    python scripts/kb.py ingest               解析 00_Inbox/inbox.md(自由文本或 KB_ITEM),生成 source note
    python scripts/kb.py status               输出当前知识库状态统计
    python scripts/kb.py llm-test             测试 LLM API 连通性
    python scripts/kb.py make-prompts         生成 summary 提示(手动 / --auto 自动调 LLM / --reconcile 回填)
    python scripts/kb.py extract-suggestions  从已生成的 summary 抽 idea/todo 候选,append 到 review 队列
    python scripts/kb.py accept-ideas         把 accepted 的 idea suggestion 搬到正式 idea list
    python scripts/kb.py accept-todos         把 accepted 的 todo suggestion 搬到 weekly/monthly/someday
    python scripts/kb.py clean-x              清洗已入库 X source 正文(就地重写「## 原始内容」段)
    python scripts/kb.py serve                启动 FastAPI 阅读前端(uvicorn)

设计原则:
    - 核心逻辑用标准库;网页抓取在 requests 不足时用 playwright 兜底
    - 所有路径相对 vault 根,不硬编码
    - 文件读写一律 UTF-8(避免 Windows 下中文乱码)
    - destructive 操作只 append / 移动到 processed.md,绝不删除用户原文
    - source_id 幂等:重复 ingest 同一段文本不会生成重复 source note
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import threading
from datetime import date, datetime
from pathlib import Path

# 同目录导入 LLM 模块(延迟引用,缺失时降级)
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import kb_llm  # type: ignore
    from kb_llm import LLMError  # type: ignore
    _LLM_AVAILABLE = True
except Exception:  # kb_llm 不可用(requests 缺失等)时仍可离线运行
    kb_llm = None
    LLMError = Exception  # type: ignore
    _LLM_AVAILABLE = False

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------

# vault 根目录 = kb.py 所在目录的上一级 (scripts/ 的父目录)
# 云端部署时可用环境变量 KB_VAULT_ROOT 覆盖（指向挂载的 vault 卷）。
VAULT_ROOT = Path(os.environ.get('KB_VAULT_ROOT') or Path(__file__).resolve().parent.parent)

# 机器运行目录(可被 Obsidian 隐藏)
# 每个派生路径都支持独立环境变量覆盖,便于云端部署时把 state/raw/logs 分卷挂载。
KB_DIR = Path(os.environ.get('KB_DIR') or (VAULT_ROOT / ".kb"))
STATE_FILE = Path(os.environ.get('KB_STATE_FILE') or (KB_DIR / "state.json"))
CALENDAR_FILE = Path(os.environ.get('KB_CALENDAR_FILE') or (KB_DIR / "calendar.json"))
WORKSPACE_STATE_FILE = Path(os.environ.get('KB_WORKSPACE_STATE_FILE') or (KB_DIR / "workspace_state.json"))
RAW_TEXT_DIR = Path(os.environ.get('KB_RAW_TEXT_DIR') or (KB_DIR / "raw_text"))
LOGS_DIR = Path(os.environ.get('KB_LOGS_DIR') or (KB_DIR / "logs"))

# 常用编码
ENC = "utf-8"

# 支持的来源类型(决定 source note 写入哪个子目录)
# 注意:与 plan.md 第 4 节 inbox 格式一致,使用 gpt_chat(而非目录名 gpt)
SOURCE_TYPES = ("github", "x", "wechat", "douyin", "gpt_chat", "web", "manual")

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str) -> None:
    """以 UTF-8 写入文件,自动创建父目录。

    v0.4.5: 改为原子写(写临时文件 + os.replace)。
    优点:并发读时不会读到截断内容(写入中途被读要么是旧版要么是新版)。
    限制:os.replace 在同一文件系统内是原子的;跨文件系统可能 fallback 为 copy+remove,
    但我们的临时文件与目标在同一目录,必然同文件系统。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # 用同目录临时文件,保证 os.replace 是真原子(不跨卷)
    tmp = path.with_suffix(path.suffix + f".tmp_{os.getpid()}_{threading.get_ident()}")
    try:
        with tmp.open("w", encoding=ENC, newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())  # 确保数据落盘
        os.replace(tmp, path)  # 原子替换
    except Exception:
        # 任何异常都要清理临时文件,避免残留
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def read_text(path: Path) -> str:
    """以 UTF-8 读取文件。"""
    return path.read_text(encoding=ENC)


# ---------------------------------------------------------------------------
# 文件锁(跨平台,零外部依赖)
# ---------------------------------------------------------------------------
# 用于串行化对 state.json / calendar.json / suggestion 文件的 read-modify-write。
# Unix: fcntl.flock(建议锁,只在同进程/协作进程间有效)
# Windows: msvcrt.locking(强制锁,但同一进程内对同一文件多次加锁会失败,所以用 os.open + 句柄)
#
# 设计要点:
# - 锁文件单独存放(<path>.lock),不污染数据文件
# - timeout 内重试,超时抛 TimeoutError,不无限等待
# - 同进程内可重入(用 threading.local 记录持有者)


import contextlib


@contextlib.contextmanager
def _file_lock(lock_path: Path, timeout: float = 5.0):
    """获取 lock_path 上的独占文件锁,超时抛 TimeoutError。

    跨平台:Unix 用 fcntl.flock,Windows 用 msvcrt.locking。
    锁随 with 退出自动释放(包括异常)。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                _try_lock(fd)
                break  # 拿到锁
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"等待文件锁超时({timeout}s):{lock_path}"
                    )
                time.sleep(0.05)
        yield
    finally:
        try:
            _release_lock(fd)
        finally:
            os.close(fd)


def _try_lock(fd: int) -> None:
    """尝试对 fd 加独占锁。失败抛 OSError。"""
    if sys.platform == "win32":
        # Windows: msvcrt.locking 对文件区域加锁
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            raise
    else:
        # Unix: fcntl.flock
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_lock(fd: int) -> None:
    """释放 fd 上的锁。"""
    if sys.platform == "win32":
        import msvcrt
        try:
            # 释放前要把指针回到加锁位置(0)
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


import time  # noqa: E402  (延迟 import 避免顶部过于拥挤)


# ---------------------------------------------------------------------------
# 时区感知时间戳(v0.4.12)
# ---------------------------------------------------------------------------
# 历史问题:全仓 datetime.now()(无时区)与 kb_date._today()(KB_TZ 感知)混用,
# 云端 UTC 服务器设 KB_TZ=Asia/Shanghai 时,写入时间戳偏一天,本周统计错乱。
# 统一入口:now_ts() / today_iso() 都尊重 KB_TZ,与 kb_date._today() 同款语义。
# 未设 KB_TZ(本地开发)时退回系统本地时间,行为与原 datetime.now() 完全一致。

def _tz():
    """返回当前时区的 ZoneInfo,或 None(系统本地时区)。"""
    tz_name = os.environ.get("KB_TZ")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception:
            return None
    return None


def now_ts() -> str:
    """当前时间的 ISO8601 字符串(秒精度,无时区后缀,与历史格式一致)。

    尊重 KB_TZ;未设时用系统本地时间。格式与原 now_ts()
    完全一致,保证旧数据可比对。
    """
    tz = _tz()
    dt = datetime.now(tz) if tz else datetime.now()
    # 去掉时区后缀,统一成无 tz 的 YYYY-MM-DDTHH:MM:SS(与历史存量一致)
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")


def today_iso() -> str:
    """今天的日期 YYYY-MM-DD,尊重 KB_TZ(与 kb_date._today() 同款)。"""
    tz = _tz()
    dt = datetime.now(tz) if tz else datetime.now()
    return dt.date().isoformat()


# ---------------------------------------------------------------------------
# state/calendar 读写锁(v0.4.12 修复 S1:跨进程并发丢更新)
# ---------------------------------------------------------------------------
# _file_lock 已实现跨进程锁,但历史上几乎没被调用,导致所有 load→改→save 裸跑。
# 这里提供专用上下文管理器,锁文件固定在 .kb/logs/,web 进程与 CLI 进程共用同一锁路径,
# 保证跨进程 read-modify-write 串行化。
#
# 用法:
#     with kb.state_lock():
#         state = kb.load_state()
#         ... 改 state ...
#         kb.save_state(state)


@contextlib.contextmanager
def state_lock(timeout: float = 5.0):
    """state.json 的跨进程独占锁(包住 load+save 整个 RMW)。"""
    lock_path = LOGS_DIR / "state.lock"
    with _file_lock(lock_path, timeout=timeout):
        yield


@contextlib.contextmanager
def calendar_lock(timeout: float = 5.0):
    """calendar.json 的跨进程独占锁(包住 load+save 整个 RMW)。"""
    lock_path = LOGS_DIR / "calendar.lock"
    with _file_lock(lock_path, timeout=timeout):
        yield


def _check_corrupt(store: dict, store_name: str) -> None:
    """若 load_state/load_calendar 返回的 dict 带 _corrupt 标记,抛 503。

    供 web 写路径调用:损坏后拿到的空骨架不应被 save 覆盖。
    """
    if isinstance(store, dict) and store.get("_corrupt"):
        raise CorruptStoreError(store_name)


class CorruptStoreError(RuntimeError):
    """state.json / calendar.json 损坏(已备份),拒绝基于空骨架写回。"""


def load_state() -> dict:
    """读取 .kb/state.json,不存在则返回空骨架。

    v0.4.5: state.json 损坏(JSONDecodeError / OSError)时不再静默返回空骨架。
    而是:
      1. 把损坏文件备份到 .kb/logs/corrupt_state_<ts>.json
      2. 记日志(append_log)
      3. 返回空骨架 + 加 "_corrupt": True 标记,调用方可识别
    防止 rebuild-index 等命令误以为"state 已是最新"而掩盖数据丢失。
    """
    if not STATE_FILE.exists():
        return {
            "version": 1,
            "created_at": today_iso(),
            "sources": {},  # source_id -> {path, source_type, source_title, created_at, ingested_at}
        }
    try:
        return json.loads(read_text(STATE_FILE))
    except (json.JSONDecodeError, OSError) as e:
        # 备份损坏文件,便于事后分析
        try:
            backup_dir = LOGS_DIR
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            corrupt_backup = backup_dir / f"corrupt_state_{ts}.json"
            shutil.copy2(STATE_FILE, corrupt_backup)
            backup_msg = f"(已备份到 {corrupt_backup.name})"
        except Exception as be:
            backup_msg = f"(备份失败: {be})"
        # 记日志,避免静默吞错
        try:
            append_log(f"WARNING: state.json 损坏({type(e).__name__}: {e}) {backup_msg}")
        except Exception:
            pass  # 日志本身失败不能再影响主流程
        # 返回空骨架 + 损坏标记
        return {
            "version": 1,
            "created_at": today_iso(),
            "sources": {},
            "_corrupt": True,
            "_corrupt_error": str(e),
        }


def save_state(state: dict) -> None:
    write_text(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))


def load_calendar() -> dict:
    """读取 .kb/calendar.json,不存在则返回空骨架。

    v0.4.5: 损坏时备份 + 记日志 + 加 _corrupt 标记(与 load_state 同款)。
    """
    if not CALENDAR_FILE.exists():
        return {"version": 1, "items": {}}
    try:
        return json.loads(read_text(CALENDAR_FILE))
    except (json.JSONDecodeError, OSError) as e:
        try:
            backup_dir = LOGS_DIR
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            corrupt_backup = backup_dir / f"corrupt_calendar_{ts}.json"
            shutil.copy2(CALENDAR_FILE, corrupt_backup)
            backup_msg = f"(已备份到 {corrupt_backup.name})"
        except Exception as be:
            backup_msg = f"(备份失败: {be})"
        try:
            append_log(f"WARNING: calendar.json 损坏({type(e).__name__}: {e}) {backup_msg}")
        except Exception:
            pass
        return {"version": 1, "items": {}, "_corrupt": True, "_corrupt_error": str(e)}


def save_calendar(cal: dict) -> None:
    write_text(CALENDAR_FILE, json.dumps(cal, ensure_ascii=False, indent=2))


def load_workspace_state() -> dict:
    """读取 .kb/workspace_state.json,不存在则返回空骨架。

    与 load_calendar 同款损坏备份逻辑。
    """
    if not WORKSPACE_STATE_FILE.exists():
        return {"version": 1, "current_task_id": ""}
    try:
        return json.loads(read_text(WORKSPACE_STATE_FILE))
    except (json.JSONDecodeError, OSError) as e:
        try:
            backup_dir = LOGS_DIR
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            corrupt_backup = backup_dir / f"corrupt_workspace_state_{ts}.json"
            shutil.copy2(WORKSPACE_STATE_FILE, corrupt_backup)
            backup_msg = f"(已备份到 {corrupt_backup.name})"
        except Exception as be:
            backup_msg = f"(备份失败: {be})"
        try:
            append_log(f"WARNING: workspace_state.json 损坏({type(e).__name__}: {e}) {backup_msg}")
        except Exception:
            pass
        return {
            "version": 1,
            "current_task_id": "",
            "_corrupt": True,
            "_corrupt_error": str(e),
        }


def save_workspace_state(state: dict) -> None:
    write_text(WORKSPACE_STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))


def append_log(message: str) -> None:
    """追加一行到 .kb/logs/kb.log。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = today_iso()
    with (LOGS_DIR / "kb.log").open("a", encoding=ENC) as fh:
        fh.write(f"[{ts}] {message}\n")


def make_slug(text: str, max_len: int = 40) -> str:
    """把 title / 正文片段转成 slug:小写、去特殊字符、空格转下划线、截断。"""
    if not text:
        return ""
    # 去掉 markdown / 特殊符号,保留字母数字中文下划线连字符
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", text.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    return cleaned[:max_len]


def content_hash(text: str) -> str:
    """正文 SHA1 前 8 位,用于 source_id 幂等。"""
    return hashlib.sha1(text.encode(ENC)).hexdigest()[:8]


def make_source_id(body: str) -> str:
    """生成稳定 source_id(幂等键):source_ff_<内容hash前8位>。

    source_id 永远只基于正文 hash,不含日期/标题,保证:
      - 同一内容无论何时 ingest,source_id 一致(幂等)
      - 与文件名解耦(文件名可读,可随标题变化)
    """
    return f"source_ff_{content_hash(body)}"


def parsefrontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 markdown frontmatter,返回 (metadata_dict, body)。

    只在文档开头的 `---` 与紧随其后的第一个 `---` 之间解析元数据;
    body 为剩余的全部内容 —— 即使其中含 `---`(Markdown 水平分隔线)也完整保留,
    不会被当作 frontmatter 结束(关键回归:详情页/搜索内容不可截断)。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([\w_]+)\s*:\s*(.*)$", line.strip())
        if mm:
            meta[mm.group(1)] = mm.group(2).strip()
    return meta, m.group(2).strip()


def append_to_inbox(items: list[str]) -> None:
    """把若干文本片段增量追加到 inbox.md(用 `---` 分隔),不破坏已有内容。

    用于 web / 命令行投稿。与 cmd_ingest 的增量逻辑一致:
    先去掉 inbox 头部说明区再合并,避免覆盖用户已在 inbox 中、尚未处理的内容。

    若 items 全为空,直接返回(不创建/不改动文件)。
    """
    inbox_path = VAULT_ROOT / "00_Inbox" / "inbox.md"
    header = _INBOX_HEADER_BLOCK()
    if inbox_path.exists():
        existing = _strip_inbox_header(read_text(inbox_path)).strip()
    else:
        existing = ""
    new_body = "\n\n---\n\n".join(i.strip() for i in items if i and i.strip())
    if not new_body:
        return
    combined = (existing + "\n\n---\n\n" + new_body) if existing else new_body
    write_text(inbox_path, header.rstrip() + "\n\n" + combined.strip() + "\n")


def hash_from_source_id(sid: str) -> str:
    """从 source_id 提取可读 hash 段(去掉 source_ff_ / source_ 前缀)。

    用于无标题时生成文件名唯一后缀。替代散落在 make_source_filename /
    make_summary_filename 等处的魔法 replace 链。
    """
    return sid.replace("source_ff_", "").replace("source_", "")


def make_note_filename(prefix: str, source_id: str, created_at: str, title: str) -> str:
    """生成可读笔记文件名:<prefix>_YYYYMMDD_<slug>.md。

    prefix 为 'source' 或 'summary'。标题做 slug 处理;无标题时回退到
    source_id 的 hash 段保证唯一性。幂等性靠 source_id,文件名只追求可读性。
    """
    date_compact = created_at.replace("-", "")
    slug = make_slug(title, max_len=40)
    if not slug:
        slug = f"untitled_{hash_from_source_id(source_id)[:6]}"
    return f"{prefix}_{date_compact}_{slug}.md"


def make_source_filename(source_id: str, created_at: str, title: str) -> str:
    """生成可读文件名:source_YYYYMMDD_<可读标题>.md(见 make_note_filename)。"""
    return make_note_filename("source", source_id, created_at, title)


def make_summary_filename(source_id: str, created_at: str, title: str) -> str:
    """生成可读 summary 文件名:summary_YYYYMMDD_<可读标题>.md(见 make_note_filename)。"""
    return make_note_filename("summary", source_id, created_at, title)


# ---------------------------------------------------------------------------
# Inbox 解析(Phase 1 核心)
# ---------------------------------------------------------------------------

# 匹配 <!-- KB_ITEM_START --> ... <!-- KB_ITEM_END --> 的整块
ITEM_BLOCK_RE = re.compile(
    r"<!--\s*KB_ITEM_START\s*-->(.*?)<!--\s*KB_ITEM_END\s*-->",
    re.DOTALL,
)

# 匹配 metadata 行: key: value(value 可空)
META_LINE_RE = re.compile(r"^([\w_]+)\s*:\s*(.*?)\s*$")

# 已知的 metadata 字段
KNOWN_META = (
    "source_type",
    "source_url",
    "source_title",
    "area",
    "user_intent",
    "created_at",
)


def parse_inbox_items(inbox_text: str) -> list[dict]:
    """从 inbox.md 文本中解析出所有 KB_ITEM block。

    返回 list[dict],每个 dict 含:
        meta: dict  (已知的 metadata 字段)
        body: str   (block 内 metadata 之后的所有正文)
        raw:  str   (整个 block 原文,含分隔符,用于从 inbox 中移除)
    """
    items = []
    for m in ITEM_BLOCK_RE.finditer(inbox_text):
        block_inner = m.group(1)
        raw = m.group(0)

        meta = {}
        body_lines = []
        in_frontmatter = True  # 还在 metadata 区;遇到首个非 metadata 的非空行后转正文区

        for line in block_inner.splitlines():
            stripped = line.strip()
            if in_frontmatter:
                mm = META_LINE_RE.match(stripped)
                if mm:
                    if mm.group(1) in KNOWN_META:
                        meta[mm.group(1)] = mm.group(2).strip()
                    # 未知 meta 字段:忽略,但仍处于 frontmatter 区继续扫描,
                    # 不能把它当成「正文起点」,否则后面的已知字段会丢失。
                    continue
                # metadata 区内的空行:直接跳过(容忍 START 标记后的换行,
                # 以及 metadata 与正文之间的分隔空行)
                if stripped == "":
                    continue
                # 非空且非 metadata 行 -> 进入正文区(本行要保留)
                in_frontmatter = False
            body_lines.append(line)

        body = "\n".join(body_lines).strip()
        items.append({"meta": meta, "body": body, "raw": raw})
    return items


# ---------------------------------------------------------------------------
# 自由文本 inbox 解析(无 KB_ITEM 标记时使用)
# ---------------------------------------------------------------------------

# inbox.md 的头部说明区(以 # 或 > 开头的行)和分隔符不算 item 内容
_INBOX_HEADER_RE = re.compile(r"^[#>]")

# 用 3 个以上 - 或 * 组成的水平分隔线拆分自由文本
_HR_RE = re.compile(r"^\s*([-*])\1{2,}\s*$")


def parse_freeform_items(inbox_text: str) -> list[dict]:
    """从自由文本 inbox.md 中切出多个 item。

    规则:
        1. 跳过文件头部说明区(以 # 或 > 开头的行,直到遇到第一个非空非说明行)
        2. 优先用水平分隔线 --- 拆分多个 item
        3. 没有分隔线时,把整段非空非说明文本视为单个 item
        4. 单个 item 内部连续空行压缩成一个

    返回 list[dict],每个 dict:
        body: str   (item 正文)
        raw:  str   (同 body,用于 processed.md 留底)
    """
    lines = inbox_text.splitlines()
    # 去掉头部说明区
    cleaned = _strip_inbox_header_lines(lines)

    text = "\n".join(cleaned).strip()
    if not text:
        return []

    # 按 --- 水平线分块
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if _HR_RE.match(line):
            block = "\n".join(current).strip()
            if block:
                chunks.append(block)
            current = []
        else:
            current.append(line)
    block = "\n".join(current).strip()
    if block:
        chunks.append(block)

    return [{"body": c, "raw": c} for c in chunks if c.strip()]


def has_kb_item_markers(inbox_text: str) -> bool:
    """inbox.md 是否含真正的 KB_ITEM HTML 注释标记(决定走旧解析还是自由文本)。

    注意:
        - 匹配完整的 <!-- KB_ITEM_START --> 注释,不是裸字符串
        - 必须先剥离头部说明区(以 # / > 开头的行 + 反引号代码片段),
          否则说明文字里展示的格式范例会污染检测
    """
    # 逐行过滤掉头部说明区(以 # 或 > 开头)
    body_lines = _strip_inbox_header_lines(inbox_text.splitlines())
    body = "\n".join(body_lines)
    return bool(re.search(r"<!--\s*KB_ITEM_START\s*-->", body))


def looks_like_url_line(line: str) -> str:
    """若该行是单个 URL,返回它;否则返回空串。"""
    s = line.strip()
    if s.startswith(("http://", "https://")) and " " not in s:
        return s
    return ""


def build_source_note(source_id: str, meta: dict, body: str, metadata_source: str = "inline") -> str:
    """按 plan.md 6.1 schema 生成 source note 的完整 Markdown。

    metadata_source: "inline"(KB_ITEM 内嵌)| "llm"(LLM 识别)| "manual"
    """
    today = today_iso()
    source_type = meta.get("source_type", "manual").strip() or "manual"
    safe_type = source_type if source_type in SOURCE_TYPES else "manual"

    fm = []
    fm.append("---")
    fm.append(f"id: {source_id}")
    fm.append(f"content_hash: {source_id.replace('source_ff_', '').replace('source_', '')}")
    fm.append("kind: source")
    fm.append(f"source_type: {safe_type}")
    fm.append(f"source_url: {meta.get('source_url', '').strip()}")
    fm.append(f"source_title: {meta.get('source_title', '').strip()}")
    fm.append(f"area: {meta.get('area', '').strip()}")
    fm.append(f"created_at: {meta.get('created_at', today).strip()}")
    fm.append(f"ingested_at: {today}")
    fm.append("status: source_created")
    fm.append(f"raw_location: .kb/raw_text/{source_id}.txt")
    fm.append("summary_location:")
    fm.append("related_ideas: []")
    fm.append("related_todos: []")
    fm.append(f"metadata_source: {metadata_source}")
    fm.append("---")
    fm.append("")
    fm.append(f"# {meta.get('source_title', source_id).strip() or source_id}")
    fm.append("")
    fm.append("> 本文件由 `python scripts/kb.py ingest` 自动生成。请勿手动修改 frontmatter。")
    fm.append("")
    fm.append("## 元信息")
    fm.append("")
    fm.append(f"- source_type: `{safe_type}`")
    fm.append(f"- area: `{meta.get('area', '').strip()}`")
    fm.append(f"- user_intent: `{meta.get('user_intent', '').strip()}`")
    fm.append(f"- created_at: {meta.get('created_at', today).strip()}")
    fm.append(f"- metadata_source: `{metadata_source}`")
    fm.append("")
    fm.append("## 原始内容")
    fm.append("")
    fm.append(body if body else "_(无正文)_")
    fm.append("")

    return "\n".join(fm)


# ---------------------------------------------------------------------------
# 模板与目录的初始化数据(Phase 0)
# ---------------------------------------------------------------------------
# 所有模板内容集中在此,init 时写入 90_Templates/。
# 模板取自 plan.md 第 7-11 节。


TEMPLATES: dict[str, str] = {
    "source_note_template.md": """---
id: source_YYYYMMDD_slug
kind: source
source_type: github | x | wechat | douyin | gpt_chat | web | manual
source_url:
source_title:
area:
created_at:
ingested_at:
status: source_created
raw_location:
summary_location:
related_ideas: []
related_todos: []
---

# {{source_title}}

## 元信息

- source_type:
- area:
- user_intent: summarize | extract_idea | evaluate_try | archive_only
- created_at:

## 原始内容

(原文粘贴在此)
""",
    "summary_github.md": """---
kind: summary
source_type: github
---

# 一句话结论

# 这个 repo 是什么

# 它解决的问题

# 核心功能

# 技术路线 / 架构

# 安装与运行难度

# 依赖条件

# 值得尝试的地方

# 风险 / 局限
""",
    "summary_article.md": """---
kind: summary
source_type: web
---

# 一句话结论

# 文章主要讲什么

# 背景问题

# 核心观点

# 详细内容总结
""",
    "summary_video.md": """---
kind: summary
source_type: douyin | video
---

# 一句话结论

# 视频内容概括

# 关键信息点

# 展示的工具 / 方法 / 项目

# 是否值得进一步验证
""",
    "summary_gpt_chat.md": """---
kind: summary
source_type: gpt_chat
---

# 一句话结论

# 这段对话讨论了什么

# 已经形成的结论

# 仍然不确定的问题

# 可以沉淀为长期知识的内容

# 需要后续追问 / 验证的地方
""",
    "summary_manual.md": """---
kind: summary
source_type: manual
---

# 一句话结论

# 主要内容
""",
    "idea_template.md": """---
id: idea_YYYYMMDD_slug
kind: idea
area: research | productivity | product | ai_agent | web_design | other
status: candidate | thinking | validated | active | paused | rejected | archived
maturity: spark | rough | structured | validated | project
priority: P0 | P1 | P2 | P3
sources: []
related_todos: []
created_at:
updated_at:
---

## 我的想法

## 可行性判断

## 下一步 todo

- [ ] ...
""",
    "idea_suggestion_template.md": """## Idea Suggestion: <title>

- id: idea_suggestion_YYYYMMDD_slug
- status: pending_review
- recommended_area: research | productivity | product | ai_agent | web_design | other
- source_summary: [[...]]
- priority: P0 | P1 | P2 | P3
- feasibility: high | medium | low
- novelty: high | medium | low
- estimated_investment: 3-5 days

### 推荐理由

### 这个 idea 是什么

### 为什么和我有关

### 可以怎么做 MVP

### 主要难点

### 风险 / 不确定性

### 如果接受，下一步 todo 候选

- [ ] ...
""",
    "todo_suggestion_template.md": """## Todo Suggestion: <title>

- id: todo_suggestion_YYYYMMDD_slug
- status: pending_review
- source_summary: [[...]]
- related_idea: [[...]]
- recommended_plan: weekly | monthly | someday
- priority: P0 | P1 | P2 | P3
- estimated_time: 2-4h
- difficulty: low | medium | high

### 为什么值得做

### 具体要做什么

### 主要难点

### 依赖条件

### 验收标准

### 建议加入的任务

- [ ] ...
""",
    "weekly_template.md": """# Weekly Todo: YYYY-Www

## 本周重点

1.
2.
3.

## Research

- [ ] <task>
  - 来源：[[...]]
  - 预计时间：
  - 难度：
  - 难点：

## Productivity

- [ ] <task>
  - 来源：[[...]]
  - 预计时间：
  - 难度：
  - 难点：

## Review

- [ ] Review pending summaries
- [ ] Review idea suggestions
- [ ] Review todo suggestions
""",
    "monthly_template.md": """# Monthly Todo: YYYY-MM

## 本月目标

## Research

## Productivity

## 要尝试的工具 / repo

## 暂缓事项

## 月末复盘
""",
}


ENV_EXAMPLE_CONTENT = """# Obsidian KB —— LLM 配置
# 复制本文件为 .env,填入你的真实 API key。.env 不会入库(.gitignore 已忽略)。

# 智谱 GLM API key (在 https://open.bigmodel.cn 控制台获取)
ZHIPU_API_KEY=

# 模型名(glm-4-flash 免费;glm-4.7-flash 最新更强;glm-4-plus 付费高质量)
KB_LLM_MODEL=glm-4-flash

# API base url(智谱官方,OpenAI 兼容格式)
KB_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/

# 请求超时(秒)
KB_LLM_TIMEOUT=60
"""


GITIGNORE_CONTENT = """# —— 凭证(绝不入库)——
.env

# —— 机器运行数据 ——
.kb/

# —— Python ——
__pycache__/
*.pyc
*.pyo
.venv/
venv/

# —— 系统 ——
.DS_Store
Thumbs.db
"""


def inbox_seed_content() -> str:
    """生成 00_Inbox/inbox.md 的初始内容,内置自由文本示例供 Phase 1 验证。"""
    return """# Inbox

> 把看到的前沿技术内容贴在这里。
> - 自由文本模式(推荐):直接粘贴正文,无需任何格式。多个内容之间用 `---` 分隔。
>   运行 `python scripts/kb.py ingest` 时会自动调用 LLM 识别来源/类型/意图。
> - 结构化模式:用 `<!-- KB_ITEM_START --> ... <!-- KB_ITEM_END -->` 包裹(见 plan.md 第 4 节)。
> 已处理的 item 会被移动到 `processed.md`。

我和 GPT 讨论了本地知识库的架构,核心结论是 local-first:所有重要内容必须以 Markdown 文件形式存在,不能只存在 SQLite 或外部服务里。inbox 接收用户从各渠道粘贴的文本,生成 source note 后,idea 和 todo suggestion 必须先进 review 区,由用户确认才能进正式计划。这个原则保证了系统透明、可控、可审计。

---

https://github.com/langchain-ai/langgraph

这个 repo 是 LangChain 出的图式 agent 编排框架,用状态机定义节点和边来组织多步 LLM 调用。看起来比我之前用的链式调用更灵活,支持循环、条件分支、人机协同中断。我在评估是否值得在下一个 agent 项目里用它替代手写的编排逻辑,主要担心学习曲线和调试难度。

---

抖音上看到一个介绍 Whisper 本地部署的教程视频。博主用 faster-whisper 在单卡 4060 上跑 large-v3 模型,实时转录延迟大概 300ms,效果接近 OpenAI API。还演示了怎么把它接到 Obsidian 做会议录音自动转笔记。我觉得这个思路可以借鉴,把语音直接变成 inbox 的一个输入源。
"""


def processed_seed_content() -> str:
    return """# Processed Inbox Items

> 已被 `kb.py ingest` 处理的 inbox item 会追加到本文件底部,作为追溯备份。
> inbox.md 中的对应内容会被移除,本文件**不删除**,保留全部历史。

"""


def empty_md(title: str, body: str = "") -> str:
    return f"# {title}\n\n{body}\n"


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Phase 0:创建 vault 目录结构、模板、空文件、state.json。"""
    print(f"[init] vault root = {VAULT_ROOT}")
    created_dirs: list[str] = []
    created_files: list[str] = []

    # ---- 目录 ----
    dirs = [
        "00_Inbox",
        "01_Sources/raw",
        *[f"01_Sources/{t}" for t in SOURCE_TYPES],
        *[f"02_Summaries/{t}" for t in SOURCE_TYPES],
        "03_Ideas",
        "04_Plans/Weekly",
        "04_Plans/Monthly",
        "05_Projects",
        "06_Events",
        "07_Tasks",
        "90_Templates",
        "99_System",
        ".kb/cache",
        ".kb/raw_text",
        ".kb/prompts",
        ".kb/outputs",
        ".kb/logs",
        "scripts",
    ]
    for d in dirs:
        p = VAULT_ROOT / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created_dirs.append(d)

    # ---- 模板文件(已存在则跳过,绝不覆盖)----
    for name, content in TEMPLATES.items():
        p = VAULT_ROOT / "90_Templates" / name
        if not p.exists():
            write_text(p, content)
            created_files.append(f"90_Templates/{name}")

    # ---- Inbox 文件 ----
    inbox = VAULT_ROOT / "00_Inbox" / "inbox.md"
    if not inbox.exists():
        write_text(inbox, inbox_seed_content())
        created_files.append("00_Inbox/inbox.md")

    processed = VAULT_ROOT / "00_Inbox" / "processed.md"
    if not processed.exists():
        write_text(processed, processed_seed_content())
        created_files.append("00_Inbox/processed.md")

    for name in ("gpt_chats.md", "clips.md"):
        p = VAULT_ROOT / "00_Inbox" / name
        if not p.exists():
            write_text(p, empty_md(name.replace(".md", "").title()))
            created_files.append(f"00_Inbox/{name}")

    # ---- 03_Ideas ----
    ideas_files = {
        "research_ideas.md": "# Research Ideas\n\n",
        "productivity_ideas.md": "# Productivity Ideas\n\n",
        "idea_suggestions.md": "# Idea Suggestions (Review Queue)\n\n> AI / Codex 生成的 idea 先进入这里。用户确认后改 status 为 `accepted_research` / `accepted_productivity`,再运行 `accept-ideas`。\n\n",
        "archived_ideas.md": "# Archived Ideas\n\n",
    }
    for name, content in ideas_files.items():
        p = VAULT_ROOT / "03_Ideas" / name
        if not p.exists():
            write_text(p, content)
            created_files.append(f"03_Ideas/{name}")

    # ---- 04_Plans ----
    plans_files = {
        "todo_suggestions.md": "# Todo Suggestions (Review Queue)\n\n> AI / Codex 生成的 todo 先进入这里。用户确认后改 status 为 `accepted_weekly` / `accepted_monthly` / `accepted_someday`,再运行 `accept-todos`。\n\n",
        "completed_todos.md": "# Completed Todos\n\n",
    }
    for name, content in plans_files.items():
        p = VAULT_ROOT / "04_Plans" / name
        if not p.exists():
            write_text(p, content)
            created_files.append(f"04_Plans/{name}")

    # ---- 05_Projects ----
    proj = VAULT_ROOT / "05_Projects" / "obsidian_kb_project.md"
    if not proj.exists():
        write_text(
            proj,
            empty_md(
                "Obsidian KB Project",
                "本项目自身的进度记录。\n\n- [x] Phase 0: 项目初始化\n- [x] Phase 1: Inbox parser\n- [ ] Phase 2: make-prompts\n- [ ] Phase 3: manual output import\n- [ ] Phase 4: accept-ideas / accept-todos\n",
            ),
        )
        created_files.append("05_Projects/obsidian_kb_project.md")

    # ---- 99_System ----
    sys_files = {
        "schema.md": "# Schema\n\n数据结构定义见 `obsidian_kb_codex_implementation_plan.md` 第 5、6 节。\n",
        "prompt_library.md": "# Prompt Library\n\n> Phase 2 (`make-prompts`) 生成 prompt 时复用的片段放这里。\n\n",
        "processing_log.md": "# Processing Log\n\n> ingest / accept 等操作的人工审计日志(机器日志在 `.kb/logs/kb.log`)。\n\n",
        "settings.md": "# Settings\n\n```\nvault_root: .\nencoding: utf-8\nstate_file: .kb/state.json\n```\n",
    }
    for name, content in sys_files.items():
        p = VAULT_ROOT / "99_System" / name
        if not p.exists():
            write_text(p, content)
            created_files.append(f"99_System/{name}")

    # ---- .kb/state.json ----
    if not STATE_FILE.exists():
        save_state(
            {
                "version": 1,
                "created_at": today_iso(),
                "sources": {},
            }
        )
        created_files.append(".kb/state.json")

    # ---- .kb/calendar.json ----
    if not CALENDAR_FILE.exists():
        save_calendar({"version": 1, "items": {}})
        created_files.append(".kb/calendar.json")

    # ---- 顶层文档(只创建缺失的)----
    # AGENTS.md 是仓库根目录已有的权威文件,不在代码里内嵌副本(避免双源真理)。
    # 若用户在空 vault 里 init 导致缺失,给出提示。
    agents = VAULT_ROOT / "AGENTS.md"
    if not agents.exists():
        created_files.append("AGENTS.md (skipped: see repo root for canonical content)")

    # ---- LLM 配置文件(只创建缺失的)----
    env_example = VAULT_ROOT / ".env.example"
    if not env_example.exists():
        write_text(env_example, ENV_EXAMPLE_CONTENT)
        created_files.append(".env.example")

    gitignore = VAULT_ROOT / ".gitignore"
    if not gitignore.exists():
        write_text(gitignore, GITIGNORE_CONTENT)
        created_files.append(".gitignore")

    requirements = VAULT_ROOT / "requirements.txt"
    if not requirements.exists():
        write_text(requirements, "requests>=2.28\n")
        created_files.append("requirements.txt")

    # ---- 汇总 ----
    print(f"[init] created {len(created_dirs)} dirs, {len(created_files)} files")
    if args.verbose:
        for d in created_dirs:
            print(f"  + dir  {d}")
        for f in created_files:
            print(f"  + file {f}")
    print("[init] done. 已存在的文件/目录已跳过,未覆盖任何用户内容。")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Phase 1:解析 inbox.md,生成 source note + raw_text + 更新 state + 移动 item 到 processed.md。

    支持两种 inbox 格式:
        - 旧格式 KB_ITEM_START/END:用内嵌 metadata,不调 LLM(metadata_source=inline)
        - 自由文本:无 metadata,调 LLM 识别(metadata_source=llm)

    --no-llm:强制离线,只接受 KB_ITEM 格式;遇到自由文本会报错。
    """
    inbox_path = VAULT_ROOT / "00_Inbox" / "inbox.md"
    processed_path = VAULT_ROOT / "00_Inbox" / "processed.md"

    if not inbox_path.exists():
        print(f"[ingest] 错误:找不到 {inbox_path}")
        print("        请先运行 `python scripts/kb.py init`")
        return 1

    inbox_text = read_text(inbox_path)
    use_llm = not args.no_llm
    has_markers = has_kb_item_markers(inbox_text)

    # 统一解析成 normalized items:每个含 meta / body / raw / metadata_source
    if has_markers:
        # —— 旧 KB_ITEM 格式 ——
        parsed = parse_inbox_items(inbox_text)
        norm_items = []
        for it in parsed:
            norm_items.append(
                {
                    "meta": it["meta"],
                    "body": it["body"],
                    "raw": it["raw"],
                    "metadata_source": "inline",
                }
            )
        # 从 inbox 移除时用 ITEM_BLOCK_RE
        removal_strategy = "markers"
    else:
        # —— 自由文本格式 ——
        if not use_llm:
            print("[ingest] 错误:inbox.md 是自由文本格式,但启用了 --no-llm。")
            print("        自由文本需要 LLM 识别 metadata。请去掉 --no-llm,")
            print("        或改用 KB_ITEM_START/END 格式。")
            return 1
        if not _LLM_AVAILABLE:
            print("[ingest] 错误:inbox.md 是自由文本,但 LLM 模块不可用。")
            print("        可能缺少 requests 库。请运行:  pip install -r requirements.txt")
            return 1
        parsed = parse_freeform_items(inbox_text)
        norm_items = []
        for it in parsed:
            norm_items.append(
                {
                    "meta": None,  # 待 LLM 填充
                    "body": it["body"],
                    "raw": it["raw"],
                    "metadata_source": "llm",
                }
            )
        removal_strategy = "freeform"

    if not norm_items:
        print("[ingest] inbox.md 中没有可处理的内容。无事可做。")
        return 0

    state = load_state()
    today = today_iso()

    created: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    # 预读 LLM 配置(只读一次,用于日志和提示)
    llm_cfg = kb_llm.load_config() if (_LLM_AVAILABLE and use_llm) else None

    for idx, item in enumerate(norm_items, 1):
        body = item["body"]
        raw = item["raw"]

        # —— 自由文本:先算 source_id 查重,命中就跳过 LLM 调用(省 token)——
        if item["meta"] is None:
            sid_check = make_source_id(body or raw)
            if sid_check in state["sources"]:
                print(f"[ingest] item #{idx}: 内容已存在({sid_check}),跳过 LLM 调用。")
                skipped.append(sid_check)
                item["_source_id"] = sid_check
                item["_dedup"] = True
                continue

        # 自由文本:调 LLM 识别 metadata
        if item["meta"] is None:
            if not llm_cfg or not llm_cfg.get("available"):
                print(
                    f"[ingest] item #{idx}: 未配置 API key,无法识别自由文本 metadata。跳过。"
                )
                print(
                    "          请复制 .env.example 为 .env 并填入 ZHIPU_API_KEY,"
                    "或改用 KB_ITEM 格式。"
                )
                failed.append(f"item#{idx}(no-key)")
                continue
            try:
                print(f"[ingest] item #{idx}: 调用 LLM 识别 metadata...")
                meta, fetch_info, enriched_text = kb_llm.extract_metadata_smart(body)
                item["meta"] = meta
                # 抓取详情
                if fetch_info["fetched"]:
                    if fetch_info["fetch_ok"]:
                        print(
                            f"          抓取正文成功:{fetch_info['fetched_chars']} 字,"
                            f"<title>={fetch_info['fetched_title'][:40]}"
                        )
                        # 抓取成功:用富文本(含正文)替代原始 body 存进 source note
                        item["body"] = enriched_text
                        item["raw"] = enriched_text
                        item["_content_status"] = "fetched"
                    else:
                        print(
                            f"          抓取失败({fetch_info['fetch_error']}),"
                            f"退回用原 URL 识别"
                        )
                        # 抓取失败:明确标注"仅 URL,无正文",防止下游 summary 瞎编
                        url_line = meta.get("source_url", "") or body.strip()
                        item["body"] = (
                            f"> ⚠️ **content_status: url_only**\n"
                            f"> 网页抓取失败({fetch_info['fetch_error']})。\n"
                            f"> 本 source 仅有 URL,没有正文内容。\n"
                            f"> 后续生成 summary 前请手动补充正文,或重新抓取。\n\n"
                            f"URL: {url_line}"
                        )
                        item["_content_status"] = "url_only"
                else:
                    item["_content_status"] = "text"
                print(
                    f"          -> source_type={meta['source_type']}, "
                    f"area={meta['area']}, title={meta['source_title'][:40]}"
                )
                item["_fetch_info"] = fetch_info
            except LLMError as e:
                print(f"[ingest] item #{idx}: LLM 识别失败: {e}")
                print("          跳过此项(原文保留在 inbox,不会被移动)。")
                failed.append(f"item#{idx}(llm-fail)")
                continue

        meta = item["meta"]
        created_at = meta.get("created_at", today).strip() or today
        # source_id 是纯 hash 幂等键(与文件名解耦)
        source_id = make_source_id(item["body"] or body or raw)
        title = meta.get("source_title", "").strip()

        # 幂等:已存在的 source 跳过(但要从 inbox 移除)
        if source_id in state["sources"]:
            skipped.append(source_id)
            item["_source_id"] = source_id
            item["_dedup"] = True
            continue

        # 文件名:可读(日期+标题),与 source_id 解耦
        source_type = (meta.get("source_type", "manual").strip() or "manual").lower()
        if source_type not in SOURCE_TYPES:
            source_type = "manual"
        # X 推文去噪:用户从 X 网页粘贴会带站点导航/交互数据/压缩重复段,
        # 在入库时清洗掉(原始文本仍保留在 item["raw"] → processed.md 供追溯)
        if source_type == "x" and _LLM_AVAILABLE:
            try:
                cleaned = kb_llm.clean_x_text(item["body"])
                if cleaned.strip():
                    item["body"] = cleaned
            except Exception as e:
                print(f"[ingest] item #{idx}: X 去噪失败({e}),保留原文")
        filename = make_source_filename(source_id, created_at, title)
        note_path = VAULT_ROOT / "01_Sources" / source_type / filename
        write_text(note_path, build_source_note(source_id, meta, item["body"], item["metadata_source"]))
        created.append(f"01_Sources/{source_type}/{filename}")

        # 保存 raw text(文件名用 source_id,因为是机器目录)
        raw_path = RAW_TEXT_DIR / f"{source_id}.txt"
        write_text(raw_path, item["body"] if item["body"] else "(empty)")

        # 更新 state(同时记录 source_id 和 filename,便于追溯)
        source_record = {
            "source_id": source_id,
            "path": f"01_Sources/{source_type}/{filename}",
            "source_type": source_type,
            "source_title": title,
            "created_at": created_at,
            "ingested_at": today,
            "metadata_source": item["metadata_source"],
        }
        if llm_cfg and item["metadata_source"] == "llm":
            source_record["llm_model"] = llm_cfg.get("model", "")
        state["sources"][source_id] = source_record
        item["_source_id"] = source_id
        item["_dedup"] = False

    save_state(state)

    # —— 从 inbox.md 移除已「成功处理」的 item ——
    # 注意:LLM 失败的 item 保留在 inbox,不移动。
    processed_items = [it for it in norm_items if "_source_id" in it]

    if removal_strategy == "markers":
        # 旧格式:删除所有 KB_ITEM block(无论是否去重,都算已处理)
        new_inbox = ITEM_BLOCK_RE.sub("<!-- KB_ITEM_PROCESSED -->", inbox_text)
        new_inbox = re.sub(
            r"(<!-- KB_ITEM_PROCESSED -->\s*)+", "", new_inbox
        ).rstrip()
    else:
        # 自由文本:只移除成功处理的 item,失败的留下
        new_text = inbox_text
        for it in processed_items:
            # 用 raw 文本精确替换为空(escape 正则特殊字符,用字符串替换更稳)
            if it["raw"] in new_text:
                new_text = new_text.replace(it["raw"], "", 1)
        # 清理残留:
        #   1. 去掉孤立的 --- 分隔线(该行只有分隔线 + 空白,内容已被移除后常见)
        #   2. 连续空行压成最多 2 个换行
        new_text = re.sub(r"(?m)^\s*([-*])\1{2,}\s*$\n?", "", new_text)
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)
        # 去掉首部残留的说明区后内容为空时,保留说明区
        new_inbox = new_text.rstrip()

    # 重建 inbox.md:保留头部说明 + 剩余内容
    header = _INBOX_HEADER_BLOCK()
    remaining_body = new_inbox
    # 去掉残留的旧 header(防止重复)
    remaining_body = _strip_inbox_header(remaining_body)
    final_inbox = header.rstrip() + "\n\n" + remaining_body.strip() + "\n"
    write_text(inbox_path, final_inbox)

    # —— 已处理 item 追加到 processed.md ——
    processed_append = []
    for it in processed_items:
        processed_append.append(
            f"\n---\n_processed_at: {today}_\n_source_id: {it['_source_id']}_\n"
            f"_metadata_source: {it['metadata_source']}_\n\n{it['raw']}\n"
        )
    if processed_append:
        with processed_path.open("a", encoding=ENC) as fh:
            fh.write("".join(processed_append))

    append_log(
        f"ingest: created={len(created)} skipped={len(skipped)} "
        f"failed={len(failed)} strategy={removal_strategy} llm={use_llm}"
    )

    # —— 汇总输出 ——
    print(f"[ingest] 共 {len(norm_items)} 个 item")
    print(f"[ingest] 新建 source note: {len(created)}")
    for c in created:
        print(f"  + {c}")
    if skipped:
        print(f"[ingest] 跳过(内容重复): {len(skipped)}")
        for s in skipped:
            print(f"  ~ {s}")
    if failed:
        print(f"[ingest] 失败(保留在 inbox): {len(failed)}")
        for f in failed:
            print(f"  ! {f}")
    if processed_items:
        print(
            f"[ingest] 已处理 item 移动到 {processed_path.relative_to(VAULT_ROOT)}"
        )
    print("[ingest] done.")
    return 0


def _INBOX_HEADER_BLOCK() -> str:
    """inbox.md 的固定头部说明(每次 ingest 后重建时复用)。"""
    return """# Inbox

> 把看到的前沿技术内容贴在这里。
> - 自由文本模式(推荐):直接粘贴正文,无需任何格式。多个内容之间用 `---` 分隔。
>   运行 `python scripts/kb.py ingest` 时会自动调用 LLM 识别来源/类型/意图。
> - 结构化模式:用 `<!-- KB_ITEM_START --> ... <!-- KB_ITEM_END -->` 包裹(见 plan.md 第 4 节)。
> 已处理的 item 会被移动到 `processed.md`。
"""


def _strip_inbox_header_lines(lines: list[str]) -> list[str]:
    """去掉文本开头的 inbox 头部说明区(以 # / > 开头的连续行 + 空行),返回剩余行。

    头部区判定:从首行开始,凡是空行或匹配 _INBOX_HEADER_RE 的行都跳过,
    直到遇到第一个非说明行;之后的所有行(含其后的空行)全部保留。
    这是 parse_freeform_items / has_kb_item_markers / _strip_inbox_header 三处
    共用的剥离逻辑,集中在此避免重复。
    """
    out: list[str] = []
    in_header = True
    for line in lines:
        if in_header:
            stripped = line.strip()
            if stripped == "" or _INBOX_HEADER_RE.match(stripped):
                continue
            in_header = False
        out.append(line)
    return out


def _strip_inbox_header(text: str) -> str:
    """去掉文本开头的 inbox 头部说明区(以 # 或 > 开头的连续行 + 空行)。"""
    return "\n".join(_strip_inbox_header_lines(text.splitlines()))


def _count_status_in_file(path, prefix: str) -> int:
    """统计 suggestion 文件中含 `status: <prefix>` 的行数(文件不存在返回 0)。

    替代 cmd_status 中 4 段重复的 read_text(...).count(...) 写法。
    """
    if not path.exists():
        return 0
    return read_text(path).count(f"status: {prefix}")


def cmd_status(args: argparse.Namespace) -> int:
    """Phase 5(基础版):输出当前知识库状态。"""
    state = load_state()
    sources = state.get("sources", {})

    inbox_path = VAULT_ROOT / "00_Inbox" / "inbox.md"
    if inbox_path.exists():
        inbox_text = read_text(inbox_path)
        # 与 ingest 一致:先判断格式,再统计。自由文本也要算 pending。
        if has_kb_item_markers(inbox_text):
            pending = len(parse_inbox_items(inbox_text))
        else:
            pending = len(parse_freeform_items(inbox_text))
    else:
        pending = 0

    print("=" * 50)
    print(" Obsidian KB Status")
    print("=" * 50)
    print(f" Vault root          : {VAULT_ROOT}")
    print(f" Pending inbox items : {pending}")
    print(f" Sources created     : {len(sources)}")
    if sources and args.verbose:
        by_type: dict[str, int] = {}
        for sid, info in sources.items():
            t = info.get("source_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        print("   by source_type:")
        for t, n in sorted(by_type.items()):
            print(f"     {t:10s}: {n}")

    # 统计待 review 的 suggestion
    idea_sug = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    todo_sug = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    idea_pending = _count_status_in_file(idea_sug, "pending_review")
    todo_pending = _count_status_in_file(todo_sug, "pending_review")
    idea_accepted = _count_status_in_file(idea_sug, "accepted_")
    todo_accepted = _count_status_in_file(todo_sug, "accepted_")
    print(f" Idea suggestions pending review : {idea_pending}")
    print(f" Todo suggestions pending review  : {todo_pending}")
    if idea_accepted or todo_accepted:
        print(f" Idea suggestions accepted (待 accept) : {idea_accepted}")
        print(f" Todo suggestions accepted (待 accept)  : {todo_accepted}")
    # summary 维度
    summarized = sum(
        1 for s in sources.values() if s.get("summary_path")
    )
    print(f" Summaries generated              : {summarized} / {len(sources)}")
    print("=" * 50)
    return 0


def cmd_llm_test(args: argparse.Namespace) -> int:
    """测试 LLM API 连通性:发一句话,打印模型回复和配置摘要。"""
    if not _LLM_AVAILABLE:
        print("[llm-test] LLM 模块不可用。请运行:  pip install -r requirements.txt")
        return 1
    cfg = kb_llm.load_config()
    print("[llm-test] 配置摘要:")
    print(f"  model    : {cfg['model']}")
    print(f"  base_url : {cfg['base_url']}")
    print(f"  timeout  : {cfg['timeout']}s")
    print(f"  api_key  : {'已配置 (' + cfg['api_key'][:4] + '****)' if cfg['available'] else '未配置'}")
    if not cfg["available"]:
        print("[llm-test] 错误:未配置 API key。")
        print("          请复制 .env.example 为 .env 并填入 ZHIPU_API_KEY。")
        return 1
    print("\n[llm-test] 发送测试请求...")
    try:
        result = kb_llm.chat(
            [
                {"role": "system", "content": "你是一个测试助手,只回复一句话。"},
                {"role": "user", "content": "请用一句话确认你能正常工作,并说明你是哪个模型。"},
            ],
            temperature=0.3,
            max_tokens=100,
        )
        print(f"[llm-test] 模型回复: {result['content']}")
        if result.get("usage"):
            u = result["usage"]
            print(
                f"[llm-test] token 用量: prompt={u.get('prompt_tokens')}, "
                f"completion={u.get('completion_tokens')}, total={u.get('total_tokens')}"
            )
        print("[llm-test] ✓ API 连通正常。")
        return 0
    except LLMError as e:
        print(f"[llm-test] ✗ 调用失败: {e}")
        return 1


def cmd_make_prompts(args):
    """Phase 2:为 source 生成 summary。

    三种模式:
        默认(手动):生成 .kb/prompts/<id>_summary_prompt.md,供用户粘贴到 ChatGPT
        --auto      :直接调 LLM 生成,写入 02_Summaries/<type>/<id>.md
        --reconcile :扫描 02_Summaries/,把已有 summary 回填到 source note 和 state
    """
    if args.reconcile:
        return _make_prompts_reconcile()

    if not _LLM_AVAILABLE:
        print("[make-prompts] LLM 模块不可用。请运行:  pip install -r requirements.txt")
        return 1

    state = load_state()
    sources = state.get("sources", {})
    if not sources:
        print("[make-prompts] state 里没有 source。请先运行 ingest。")
        return 0

    # 筛选待处理的 source
    pending: list[tuple[str, dict]] = []
    for sid, info in sources.items():
        if args.source and sid != args.source:
            continue
        already = bool(info.get("summary_path"))
        # fallback:summary_path 没记录时,扫描 summary 目录看有没有匹配 source_id 的文件
        if not already:
            sum_dir = VAULT_ROOT / "02_Summaries" / info["source_type"]
            if sum_dir.exists():
                already = any(
                    sid in f.name for f in sum_dir.glob("*.md")
                )
        if already and not args.force:
            continue
        pending.append((sid, info))

    if not pending:
        print("[make-prompts] 没有待总结的 source(全部已有 summary)。")
        print("                 用 --force 可强制重新生成。")
        return 0

    print(f"[make-prompts] 待处理 source: {len(pending)} 个,模式={'auto' if args.auto else 'manual'}")

    generated = 0
    failed = 0
    skipped_url = 0
    for sid, info in pending:
        source_note = VAULT_ROOT / info["path"]
        if not source_note.exists():
            print(f"  ! {sid}: source note 不存在({info['path']}),跳过")
            failed += 1
            continue
        source_text = _extract_source_body(read_text(source_note))
        if not source_text.strip():
            print(f"  ! {sid}: source 正文为空,跳过")
            failed += 1
            continue

        # 检测 url_only(抓取失败、仅存 URL 的 source)——跳过避免瞎编
        if "content_status: url_only" in source_text:
            skipped_url += 1
            print(f"  ⚠ {sid}: 仅 URL 无正文(抓取失败),跳过 summary 生成")
            print(f"      处理方式:手动在 source note 补正文后,用 --force --source {sid} 重跑")
            continue

        if args.auto:
            # —— 自动模式:调 LLM ——
            cfg = kb_llm.load_config()
            if not cfg.get("available"):
                print(f"  ! {sid}: 未配置 API key,跳过自动生成")
                failed += 1
                continue
            try:
                print(f"  → {sid}: 调用 LLM 生成 summary...")
                body = kb_llm.generate_summary(source_text, info["source_type"])
                # 检查 LLM 是否返回空内容(思考模型可能 token 全用在思考上)
                if not body or not body.strip():
                    print(f"    ✗ LLM 返回空内容(可能是思考模型超时或 token 不足)")
                    failed += 1
                    continue
                summary_path = _write_summary(sid, info, body)
                _backfill_source_note(source_note, sid, summary_path, "summarized")
                info["summary_path"] = summary_path.relative_to(VAULT_ROOT).as_posix()
                info["action_status"] = "undecided"
                generated += 1
                print(f"    ✓ 写入 {summary_path.relative_to(VAULT_ROOT)}")
            except LLMError as e:
                print(f"    ✗ LLM 失败: {e}")
                failed += 1
        else:
            # —— 手动模式:生成 prompt 文件 ——
            prompt_path = _write_prompt_file(sid, info, source_text)
            generated += 1
            print(f"  → {sid}: prompt 写入 {prompt_path.relative_to(VAULT_ROOT)}")

    save_state(state)
    append_log(
        f"make-prompts: mode={'auto' if args.auto else 'manual'} "
        f"generated={generated} failed={failed} skipped_url_only={skipped_url}"
    )

    print(f"\n[make-prompts] 完成。生成 {generated} 个,失败 {failed} 个。")
    if skipped_url > 0:
        print(f"[make-prompts] 跳过 {skipped_url} 个仅 URL 无正文的 source(抓取失败)。")
        print("[make-prompts] 补救:在 source note 的「原始内容」区手动补正文,再运行")
        print(f"                 `python scripts/kb.py make-prompts --auto --force --source <id>`")
    if not args.auto and generated > 0:
        print("[make-prompts] 手动模式:把 .kb/prompts/ 下的 prompt 复制到 ChatGPT/Codex 运行,")
        print("                 结果保存到 02_Summaries/<source_type>/<source_id>.md,")
        print("                 然后运行 `python scripts/kb.py make-prompts --reconcile` 回填。")
    return 0


def cmd_extract_suggestions(args):
    """从 summary 抽取 idea/todo 候选,append 到 review 队列。"""
    if not _LLM_AVAILABLE:
        print("[extract-suggestions] LLM 模块不可用。")
        return 1
    cfg = kb_llm.load_config()
    if not cfg.get("available"):
        print("[extract-suggestions] 未配置 API key。")
        return 1

    state = load_state()
    sources = state.get("sources", {})

    # 找有待抽取的 summary(action_status == undecided 或未抽取)
    targets: list[tuple[str, dict]] = []
    for sid, info in sources.items():
        if args.source and sid != args.source:
            continue
        sp = info.get("summary_path")
        if not sp:
            continue
        status = info.get("action_status", "undecided")
        if status not in ("undecided", "idea_extracted"):
            # 已是 todo_suggested / reviewed,跳过
            continue
        targets.append((sid, info))

    if not targets:
        print("[extract-suggestions] 没有待抽取的 summary。")
        print("                         先运行 `make-prompts --auto` 生成 summary。")
        return 0

    print(f"[extract-suggestions] 待抽取 summary: {len(targets)} 个")

    idea_sug_file = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    todo_sug_file = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"

    total_ideas = 0
    total_todos = 0
    failed = 0  # LLM 抽取失败的 source 数(可观测性:进 kb.log,action_status 留 undecided 下次重试)
    for sid, info in targets:
        summary_path = VAULT_ROOT / info["summary_path"]
        if not summary_path.exists():
            print(f"  ! {sid}: summary 文件不存在,跳过")
            continue
        summary_text = _extract_summary_body(read_text(summary_path))
        if not summary_text.strip():
            print(f"  ! {sid}: summary 正文为空,跳过")
            continue

        try:
            print(f"  → {sid}: 抽取 idea/todo 候选...")
            ideas = kb_llm.extract_ideas_from_summary(summary_text)
            todos = kb_llm.extract_todos_from_summary(summary_text)
            today = today_iso()
            # 写 idea suggestions
            for it in ideas:
                block = _format_idea_suggestion(sid, info, it, today)
                _append_section(idea_sug_file, block)
            for it in todos:
                block = _format_todo_suggestion(sid, info, it, today)
                _append_section(todo_sug_file, block)
            info["action_status"] = "todo_suggested"
            total_ideas += len(ideas)
            total_todos += len(todos)
            print(f"    ✓ idea 候选 {len(ideas)} 个,todo 候选 {len(todos)} 个")
        except LLMError as e:
            print(f"    ✗ 抽取失败: {e}")
            append_log(f"extract-suggestions FAILED source={sid}: {e}")
            failed += 1

    save_state(state)
    append_log(
        f"extract-suggestions: sources={len(targets)} ideas={total_ideas} todos={total_todos} failed={failed}"
    )
    print(f"\n[extract-suggestions] 完成。共抽取 idea 候选 {total_ideas} 个,todo 候选 {total_todos} 个。")
    if total_ideas or total_todos:
        print("[extract-suggestions] 候选已进入 review 队列:")
        print("  - 03_Ideas/idea_suggestions.md")
        print("  - 04_Plans/todo_suggestions.md")
        print("  用户确认后改 status 为 accepted_*,再运行 accept-ideas / accept-todos。")
    return 0


def _list_accepted_suggestion_ids(kind: str) -> list[tuple[str, str, dict, str, str]]:
    """扫描 review 队列文件,返回所有 accepted_* 块的元信息。

    kind: "Idea Suggestion" 或 "Todo Suggestion"
    返回 [(item_id, status, meta, body, raw_block), ...]
    item_id 优先用 meta["id"],否则用 title slug。
    """
    if "Idea" in kind:
        sug_file = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
        header_kind = "idea"
    else:
        sug_file = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
        header_kind = "todo"
    if not sug_file.exists():
        return []
    text = read_text(sug_file)
    blocks = _split_suggestion_blocks(text, kind)
    out = []
    for raw, meta, body in blocks:
        status = meta.get("status", "").strip()
        # v0.4.12: todo 新态为 accepted(无下划线);旧态 accepted_* 仍兼容
        if status == "accepted" or status.startswith("accepted_"):
            item_id = meta.get("id", "").strip() or meta.get("title", "")
            out.append((item_id, status, meta, body, raw))
    return out


def _rewrite_suggestion_file(kind: str, item_ids_to_moved: dict[str, str]) -> None:
    """回写 suggestion 文件:把指定 item_id 的块 status 替换为新值(通常 "moved")。

    item_ids_to_moved: {item_id: new_status}
    """
    if "Idea" in kind:
        sug_file = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
        header_kind = "idea"
        header_title = "Idea Suggestions (Review Queue)"
    else:
        sug_file = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
        header_kind = "todo"
        header_title = "Todo Suggestions (Review Queue)"
    if not sug_file.exists():
        return
    text = read_text(sug_file)
    blocks = _split_suggestion_blocks(text, kind)
    new_blocks = []
    for raw, meta, body in blocks:
        item_id = meta.get("id", "").strip() or meta.get("title", "")
        if item_id in item_ids_to_moved:
            old_status = meta.get("status", "").strip()
            new_status = item_ids_to_moved[item_id]
            new_blocks.append(_replace_status_in_block(raw, old_status, new_status))
        else:
            new_blocks.append(raw)
    header = _suggestion_header(header_title, header_kind)
    write_text(sug_file, header + "\n".join(new_blocks) + "\n")


def move_accepted_idea(item_id: str, deadline: str = "") -> dict:
    """把单个 accepted_* 的 idea suggestion 搬到正式 idea list。

    幂等:已是 moved 状态的不重复搬;非 accepted_* 的不搬。
    (deadline 参数仅为与 move_accepted_todo 同签名而保留,idea 搬运不使用。)
    返回:
        {moved: bool, item_id, area, target, reason}
        reason 描述跳过原因(如 "not_accepted" / "already_moved" / "not_found")。
    """
    accepted = _list_accepted_suggestion_ids("Idea Suggestion")
    target_for = None
    target_meta = None
    target_body = None
    target_status = None
    for iid, status, meta, body, raw in accepted:
        if iid == item_id or iid.endswith(item_id):
            target_for = iid
            target_meta = meta
            target_body = body
            target_status = status
            break
    if target_for is None:
        return {"moved": False, "item_id": item_id,
                "reason": "not_found_or_not_accepted"}

    area = target_status.removeprefix("accepted_")  # research / productivity
    target_file = VAULT_ROOT / "03_Ideas" / f"{area}_ideas.md"
    formal = _format_formal_idea(target_meta, target_body, area)
    _append_section(target_file, formal)
    # 把原 suggestion 块标 moved
    _rewrite_suggestion_file("Idea Suggestion", {target_for: "moved"})
    return {
        "moved": True,
        "item_id": target_for,
        "area": area,
        "target": target_file.relative_to(VAULT_ROOT).as_posix(),
    }


def move_accepted_todo(item_id: str, deadline: str = "") -> dict:
    """把单个 accepted 的 todo suggestion 搬到 weekly/monthly/someday。

    v0.4.12 起去向由 deadline 决定(不再让用户在 UI 里手选三态):
      - 本周内(到本周日) → 04_Plans/Weekly/{年}-W{周}.md
      - 本月内(到月末)   → 04_Plans/Monthly/{年}-{月}.md
      - 更远 / 未填 deadline → 04_Plans/someday.md
    兼容:旧数据 status 仍可能带 accepted_weekly/monthly/someday 后缀,此时按后缀归类。

    幂等:已是 moved 状态的不重复搬;非 accepted 的不搬。
    返回:{moved, item_id, plan, target, reason}
    """
    accepted = _list_accepted_suggestion_ids("Todo Suggestion")
    target_for = None
    target_meta = None
    target_body = None
    target_status = None
    for iid, status, meta, body, raw in accepted:
        if iid == item_id or iid.endswith(item_id):
            target_for = iid
            target_meta = meta
            target_body = body
            target_status = status
            break
    if target_for is None:
        return {"moved": False, "item_id": item_id,
                "reason": "not_found_or_not_accepted"}

    import kb_date
    today = kb_date._today()
    iso_year, iso_week, iso_weekday = today.isocalendar()
    week_tag = f"{iso_year}-W{iso_week:02d}"
    month_tag = today.strftime("%Y-%m")

    # 决定去向 plan:旧态后缀优先(兼容历史),否则按 deadline 归类
    legacy_plan = ""
    if target_status.startswith("accepted_"):
        legacy_plan = target_status.removeprefix("accepted_")  # weekly/monthly/someday

    if legacy_plan:
        plan = legacy_plan
    else:
        plan = _todo_plan_from_deadline(deadline, today)

    if plan == "weekly":
        target_file = VAULT_ROOT / "04_Plans" / "Weekly" / f"{week_tag}.md"
        _ensure_weekly_file(target_file, week_tag)
    elif plan == "monthly":
        target_file = VAULT_ROOT / "04_Plans" / "Monthly" / f"{month_tag}.md"
        _ensure_monthly_file(target_file, month_tag)
    else:  # someday
        target_file = VAULT_ROOT / "04_Plans" / "someday.md"
        if not target_file.exists():
            write_text(target_file, "# Someday Todo\n\n> 暂存,有空再做。\n\n")
    # 把用户填的 deadline 落进 meta,供 _format_weekly_task 渲染
    if deadline:
        if target_meta is None:
            target_meta = {}
        target_meta = dict(target_meta)
        target_meta["deadline"] = deadline
    task = _format_weekly_task(target_meta, target_body)
    _append_section(target_file, task)
    _rewrite_suggestion_file("Todo Suggestion", {target_for: "moved"})
    return {
        "moved": True,
        "item_id": target_for,
        "plan": plan,
        "target": target_file.relative_to(VAULT_ROOT).as_posix(),
    }


def _todo_plan_from_deadline(deadline: str, today) -> str:
    """根据 deadline 日期归类到 weekly/monthly/someday。

    - 无 deadline / 解析失败 → someday
    - 截止日在本周(本周一..本周日)内 → weekly
    - 截止日在本月内(但不在本周) → monthly
    - 更远 → someday
    """
    if not deadline:
        return "someday"
    try:
        from datetime import date as _date
        d = _date.fromisoformat(deadline)
    except (ValueError, TypeError):
        return "someday"
    iso_year, iso_week, iso_weekday = today.isocalendar()
    # 本周的范围:周一(iso_weekday=1)到周日(iso_weekday=7)
    monday = today.fromisocalendar(iso_year, iso_week, 1)
    sunday = today.fromisocalendar(iso_year, iso_week, 7)
    if monday <= d <= sunday:
        return "weekly"
    # 本月范围
    if d.year == today.year and d.month == today.month:
        return "monthly"
    return "someday"


def cmd_accept_ideas(args):
    """Phase 4:把 accepted 的 idea suggestion 移到正式 idea list。

    遍历 review 队列里所有 accepted_* 块,逐个调 move_accepted_idea。
    """
    sug_file = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    if not sug_file.exists():
        print("[accept-ideas] idea_suggestions.md 不存在。")
        return 1

    accepted = _list_accepted_suggestion_ids("Idea Suggestion")
    if not accepted:
        print("[accept-ideas] 没有 accepted_* 状态的 idea suggestion(可能都已 moved)。")
        return 0

    # 持 suggestion 文件锁整个搬运(v0.4.12 S2):与 web accept_and_move 共用同一锁路径,
    # 防 CLI 与 web 并发 accept 同一文件导致 status 改写/搬运交错。
    lock_path = LOGS_DIR / f"sug_{sug_file.stem}.lock"
    moved = 0
    failed = 0
    try:
        with _file_lock(lock_path, timeout=30.0):
            for item_id, status, meta, body, raw in accepted:
                result = move_accepted_idea(item_id)
                if result.get("moved"):
                    moved += 1
                    print(f"  → {meta.get('title', item_id)} → {result['target']}")
                else:
                    failed += 1
                    print(f"  ! {item_id}: {result.get('reason')}")
    except TimeoutError as e:
        print(f"[accept-ideas] 等待文件锁超时(可能 web 正在操作):{e}")
        return 1

    append_log(f"accept-ideas: moved={moved} failed={failed}")
    print(f"\n[accept-ideas] 移动 {moved} 个" + (f",失败 {failed} 个" if failed else "") + "。")
    if moved:
        print("[accept-ideas] 正式 idea list 已更新,原 suggestion 标记为 moved。")
    return 0


def cmd_accept_todos(args):
    """Phase 4:把 accepted 的 todo suggestion 移到 weekly/monthly/someday。

    遍历 review 队列里所有 accepted_* 块,逐个调 move_accepted_todo。
    """
    sug_file = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    if not sug_file.exists():
        print("[accept-todos] todo_suggestions.md 不存在。")
        return 1

    accepted = _list_accepted_suggestion_ids("Todo Suggestion")
    if not accepted:
        print("[accept-todos] 没有 accepted_* 状态的 todo suggestion(可能都已 moved)。")
        return 0

    # 持 suggestion 文件锁整个搬运(v0.4.12 S2):与 web accept_and_move 共用同一锁路径。
    lock_path = LOGS_DIR / f"sug_{sug_file.stem}.lock"
    moved = 0
    failed = 0
    try:
        with _file_lock(lock_path, timeout=30.0):
            for item_id, status, meta, body, raw in accepted:
                result = move_accepted_todo(item_id)
                if result.get("moved"):
                    moved += 1
                    print(f"  → {meta.get('title', item_id)} → {result['target']}")
                else:
                    failed += 1
                    print(f"  ! {item_id}: {result.get('reason')}")
    except TimeoutError as e:
        print(f"[accept-todos] 等待文件锁超时(可能 web 正在操作):{e}")
        return 1

    append_log(f"accept-todos: moved={moved} failed={failed}")
    print(f"\n[accept-todos] 移动 {moved} 个" + (f",失败 {failed} 个" if failed else "") + "。")
    if moved:
        print("[accept-todos] weekly/monthly/someday 已更新,原 suggestion 标记为 moved。")
    return 0


# ---------------------------------------------------------------------------
# Phase 2/4 辅助函数
# ---------------------------------------------------------------------------


def _extract_source_body(note_text: str) -> str:
    """从 source note 提取「## 原始内容」之后的正文。"""
    m = re.search(r"##\s*原始内容\s*\n(.*)", note_text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback:去 frontmatter 后全部
    return re.sub(r"^---.*?---\s*", "", note_text, flags=re.DOTALL).strip()


def _extract_summary_body(summary_text: str) -> str:
    """从 summary 文件提取正文(去 frontmatter),复用 parsefrontmatter。"""
    return parsefrontmatter(summary_text)[1]


def _write_summary(sid: str, info: dict, body: str) -> Path:
    """把 LLM 生成的 summary body 包装成完整文件写入 02_Summaries/。返回路径。

    文件名用可读格式(日期+标题);frontmatter 里 source_id 是幂等键(纯 hash)。
    """
    today = today_iso()
    source_type = info["source_type"]
    title = info.get("source_title", "")
    created_at = info.get("created_at", today)
    fm = [
        "---",
        f"id: summary_{sid}",
        f"source_id: {sid}",
        "kind: summary",
        f"source_type: {source_type}",
        f"source_title: {title}",
        f"area: {info.get('area', '')}",
        f"created_at: {created_at}",
        f"summarized_at: {today}",
        "status: summarized",
        "action_status: undecided",
        "priority: P2",
        "confidence: medium",
        "idea_extracted: false",
        "todo_extracted: false",
        "related_ideas: []",
        "related_todos: []",
        "tags: []",
        "---",
        "",
    ]
    filename = make_summary_filename(sid, created_at, title)
    path = VAULT_ROOT / "02_Summaries" / source_type / filename
    write_text(path, "\n".join(fm) + body.strip() + "\n")
    return path


def _backfill_source_note(note_path: Path, sid: str, summary_path: Path, new_status: str) -> None:
    """回填 source note 的 summary_location 和 status 字段。"""
    text = read_text(note_path)
    rel = summary_path.relative_to(VAULT_ROOT).as_posix()
    text = re.sub(r"summary_location:.*", f"summary_location: {rel}", text)
    text = re.sub(r"^status:.*", f"status: {new_status}", text, flags=re.MULTILINE)
    write_text(note_path, text)


def _write_prompt_file(sid: str, info: dict, source_text: str) -> Path:
    """手动模式:生成 prompt 文件供用户粘贴到 ChatGPT。"""
    prompts_dir = KB_DIR / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    path = prompts_dir / f"{sid}_summary_prompt.md"
    outline = kb_llm.summary_outline(info["source_type"])
    content = f"""# Summary Prompt for {sid}

> 把本文件全部内容复制到 ChatGPT / GLM 运行,把模型输出保存到
> `02_Summaries/{info['source_type']}/{sid}.md`(可在顶部加 frontmatter)。
> 然后运行 `python scripts/kb.py make-prompts --reconcile` 回填。

## System Prompt

{kb_llm.SUMMARY_SYSTEM_PROMPT}

## 要求的输出章节结构

{outline}

## 资料元信息

- source_type: {info['source_type']}
- source_title: {info.get('source_title', '')}
- area: {info.get('area', '')}

## 资料原文

{source_text[:8000]}
"""
    write_text(path, content)
    return path


def _make_prompts_reconcile() -> int:
    """扫描 02_Summaries/,把已有 summary 回填到 source note 和 state。"""
    state = load_state()
    sources = state.get("sources", {})
    summaries_dir = VAULT_ROOT / "02_Summaries"
    if not summaries_dir.exists():
        print("[make-prompts] 02_Summaries/ 不存在。")
        return 0

    reconciled = 0
    for sub in summaries_dir.iterdir():
        if not sub.is_dir():
            continue
        for sf in sub.glob("*.md"):
            # 文件名是可读格式,source_id 要从 frontmatter 读
            content = read_text(sf)
            m = re.search(r"^source_id:\s*(\S+)", content, re.MULTILINE)
            if not m:
                continue
            sid = m.group(1).strip()
            if sid not in sources:
                continue
            info = sources[sid]
            rel = sf.relative_to(VAULT_ROOT).as_posix()
            already = info.get("summary_path") == rel
            source_note = VAULT_ROOT / info["path"]
            if source_note.exists():
                _backfill_source_note(source_note, sid, sf, "summarized")
            info["summary_path"] = rel
            info.setdefault("action_status", "undecided")
            if not already:
                reconciled += 1
                print(f"  → {sid}: 回填 {rel}")

    save_state(state)
    append_log(f"make-prompts reconcile: updated={reconciled}")
    print(f"\n[make-prompts] reconcile 完成,更新 {reconciled} 个 source 的 summary_location。")
    return 0


# ---------------------------------------------------------------------------
# rebuild-index:state.json ↔ summary frontmatter 自愈
# ---------------------------------------------------------------------------


def _parse_frontmatter_tags(raw: str) -> list[str]:
    """把 frontmatter 里 `tags: [a, b, c]` 的字面串解析为 list。

    与 kb_web._read_summary_frontmatter_tags 行为一致,但接受已解析出的字符串值
    (避免 kb.py 反向依赖 kb_web)。
    """
    if not raw:
        return []
    cleaned = raw.strip().strip("[]").strip()
    if not cleaned:
        return []
    return [t.strip().strip('"').strip("'") for t in cleaned.split(",") if t.strip()]


def _scan_summary_frontmatter() -> list[dict]:
    """扫描 02_Summaries/**/*.md,返回每个 summary 的 {source_id, summary_relpath, tags}。

    文件名约定:`summary_<source_id>.md`(source_id 是 source_/source_ff_ 前缀的 hash)。
    source_id 从 frontmatter 的 `source_id:` 字段读;缺失则尝试从文件名提取。
    tags 从 `tags:` 字段读(可能不存在)。
    """
    summaries_dir = VAULT_ROOT / "02_Summaries"
    if not summaries_dir.exists():
        return []
    out: list[dict] = []
    for sf in summaries_dir.rglob("*.md"):
        try:
            content = read_text(sf)
        except OSError:
            continue
        meta, _ = parsefrontmatter(content)
        sid = meta.get("source_id", "").strip()
        if not sid:
            # fallback:从文件名提取 source_/source_ff_ 前缀
            m = re.search(r"(source_(?:ff_)?[a-f0-9]+)", sf.stem)
            if not m:
                continue
            sid = m.group(1)
        rel = sf.relative_to(VAULT_ROOT).as_posix()
        tags = _parse_frontmatter_tags(meta.get("tags", ""))
        out.append({"source_id": sid, "summary_relpath": rel, "tags": tags})
    return out


def _rebuild_state_index(
    dry_run: bool = False,
    tags_only: bool = False,
    summary_path_only: bool = False,
) -> dict:
    """核心重建逻辑(纯函数,无 print)。

    数据流向:summary frontmatter → state.json(frontmatter 为准)。
    - summary_path:state 无 → 补;state 有但不一致 → 以扫盘结果为准
    - tags:state 无 frontmatter 有 → 补;state 有 frontmatter 无 → 不删(保留用户手加);
            两者不一致 → 以 frontmatter 为准
    - 不碰 is_favorite / read_count / last_read_at / collection_ids / detected_dates 等用户行为数据
    - has_summary 不持久化(保持运行时派生),仅在 orphans 报告里列出

    返回统计 dict:
        {scanned, summary_path_backfilled, summary_path_corrected, tags_added,
         tags_updated, orphans_in_state, written: bool, backup_path}
    """
    state = load_state()
    sources = state.get("sources", {})
    summaries = _scan_summary_frontmatter()
    sum_by_sid = {s["source_id"]: s for s in summaries}

    stats = {
        "scanned": len(summaries),
        "summary_path_backfilled": 0,
        "summary_path_corrected": 0,
        "tags_added": 0,
        "tags_updated": 0,
        "orphans_in_state": 0,
        "details": [],
        "written": False,
        "backup_path": None,
    }

    changed = False
    for sid, info in sources.items():
        sum_info = sum_by_sid.get(sid)
        if sum_info is None:
            # state 里有 source_id 但 frontmatter 里没有 → 孤儿(可能 summary 被删)
            # 不修改 state,只在报告里标记
            if info.get("summary_path"):
                stats["orphans_in_state"] += 1
                stats["details"].append(
                    {"source_id": sid, "issue": "orphan_summary_path",
                     "current": info.get("summary_path")}
                )
            continue

        # —— summary_path ——
        if not tags_only:  # 即处理 summary_path
            current_sp = info.get("summary_path")
            correct_sp = sum_info["summary_relpath"]
            if not current_sp:
                info["summary_path"] = correct_sp
                stats["summary_path_backfilled"] += 1
                stats["details"].append(
                    {"source_id": sid, "issue": "summary_path_missing",
                     "fixed_to": correct_sp}
                )
                changed = True
            elif current_sp != correct_sp:
                info["summary_path"] = correct_sp
                stats["summary_path_corrected"] += 1
                stats["details"].append(
                    {"source_id": sid, "issue": "summary_path_mismatch",
                     "from": current_sp, "to": correct_sp}
                )
                changed = True

        # —— tags ——
        if not summary_path_only:
            frontmatter_tags = sum_info["tags"]
            state_tags = list(info.get("tags", []))
            if frontmatter_tags and not state_tags:
                # state 无,frontmatter 有 → 补
                info["tags"] = list(frontmatter_tags)
                stats["tags_added"] += 1
                stats["details"].append(
                    {"source_id": sid, "issue": "tags_missing_in_state",
                     "added": frontmatter_tags}
                )
                changed = True
            elif frontmatter_tags and state_tags and state_tags != frontmatter_tags:
                # 两者都有但不一致 → 以 frontmatter 为准
                info["tags"] = list(frontmatter_tags)
                stats["tags_updated"] += 1
                stats["details"].append(
                    {"source_id": sid, "issue": "tags_mismatch",
                     "from": state_tags, "to": frontmatter_tags}
                )
                changed = True
            # frontmatter 无 tags 但 state 有 → 保留(用户可能手加),不动

    if changed and not dry_run:
        # 备份原 state(命名带时分秒,避免同日多次 rebuild 覆盖)
        if STATE_FILE.exists():
            backup_dir = LOGS_DIR / "web_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime as _dt
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"state_rebuild_{ts}.json.bak"
            shutil.copy2(STATE_FILE, backup)
            stats["backup_path"] = str(backup)
        save_state(state)
        stats["written"] = True

    return stats


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    """rebuild-index:从 summary frontmatter 重建 state.json 的 tags / summary_path。

    数据流向:frontmatter → state(frontmatter 为准)。
    不碰用户行为数据(is_favorite / read_count / collection_ids 等)。

    v0.4.5: 检测 state.json 损坏(_corrupt 标记),明确报告而非静默吞错。
    """
    # 先检查 state 是否损坏(load_state 已备份损坏文件)
    pre_check = load_state()
    if pre_check.get("_corrupt"):
        print(f"[rebuild-index] ⚠ state.json 损坏!({pre_check.get('_corrupt_error', '未知错误')})")
        print(f"[rebuild-index] 损坏的文件已备份到 {LOGS_DIR}/corrupt_state_*.json")
        print(f"[rebuild-index] 当前 state 为空骨架,继续 rebuild 只能从 summary 重建 tags/summary_path,")
        print(f"[rebuild-index] sources 的核心字段(path/source_type/created_at 等)无法恢复,")
        print(f"[rebuild-index] 用户行为数据(is_favorite/read_count/collection_ids 等)已永久丢失。")
        print(f"[rebuild-index] 建议手动从 .kb/logs/corrupt_state_*.json 修复,或确认接受损失后再继续。")
        return 2  # 退出码 2 = state 损坏,需要人工确认

    print(f"[rebuild-index] 扫描 {VAULT_ROOT / '02_Summaries'} ...")
    stats = _rebuild_state_index(
        dry_run=args.dry_run,
        tags_only=args.tags_only,
        summary_path_only=args.summary_path_only,
    )

    print(f"[rebuild-index] 扫描到 {stats['scanned']} 个 summary 文件")
    print(f"[rebuild-index] summary_path 回填 {stats['summary_path_backfilled']} 个,"
          f"修正 {stats['summary_path_corrected']} 个")
    print(f"[rebuild-index] tags 补 {stats['tags_added']} 个,更新 {stats['tags_updated']} 个")
    if stats["orphans_in_state"]:
        print(f"[rebuild-index] ⚠ {stats['orphans_in_state']} 个 source 在 state 里有"
              f" summary_path 但 02_Summaries/ 找不到对应文件(可能被手动删除)")

    if args.verbose and stats["details"]:
        print("\n[rebuild-index] 明细:")
        for d in stats["details"]:
            print(f"  - {d['source_id']}: {d['issue']}")
            for k, v in d.items():
                if k != "source_id" and k != "issue":
                    print(f"      {k}: {v}")

    if args.dry_run:
        print("\n[rebuild-index] --dry-run 模式,未写文件。去掉 --dry-run 实际执行。")
        append_log(
            f"rebuild-index dry-run: scanned={stats['scanned']} "
            f"backfill={stats['summary_path_backfilled']} "
            f"corrected={stats['summary_path_corrected']} "
            f"tags_added={stats['tags_added']} tags_updated={stats['tags_updated']}"
        )
    elif stats["written"]:
        print(f"\n[rebuild-index] ✓ state.json 已更新。备份: {stats['backup_path']}")
        append_log(
            f"rebuild-index: scanned={stats['scanned']} "
            f"backfill={stats['summary_path_backfilled']} "
            f"corrected={stats['summary_path_corrected']} "
            f"tags_added={stats['tags_added']} tags_updated={stats['tags_updated']} "
            f"orphans={stats['orphans_in_state']}"
        )
    else:
        print("\n[rebuild-index] 无需更新,state 已是最新。")

    return 0


# —— suggestion 块解析与格式化 ——


def _split_suggestion_blocks(text: str, kind: str) -> list[tuple[str, dict, str]]:
    """把 review 队列文件按「## {kind}: <title>」切成块。

    返回 [(raw_block, meta_dict, body_text), ...]
    meta 从块内的 `- key: value` 行提取;body 是字段之后的自由文本。
    """
    # 匹配每个 ## 标题作为块起点。
    # 前瞻只在「同类型标题(## {kind}:)」或文末处切分,避免把 body 里的任意
    # 「## 子标题」误判为块边界(此前用 (?=\n##\s|\Z) 会在任何二级标题处截断)。
    pattern = re.compile(
        rf"(^|\n)(##\s*{re.escape(kind)}:\s*.+?)"
        rf"(?=\n##\s*{re.escape(kind)}:\s*|\Z)",
        re.DOTALL,
    )
    results: list[tuple[str, dict, str]] = []
    for m in pattern.finditer(text):
        block = m.group(2).strip()
        # 第一行是标题,提取 title
        lines = block.splitlines()
        title_line = lines[0] if lines else ""
        title = re.sub(rf"^##\s*{re.escape(kind)}:\s*", "", title_line).strip()
        meta: dict[str, str] = {"title": title}
        body_lines: list[str] = []
        in_body = False
        for ln in lines[1:]:
            stripped = ln.strip()
            if not in_body:
                mm = re.match(r"^-\s*([\w_]+)\s*:\s*(.*)$", stripped)
                if mm:
                    meta[mm.group(1)] = mm.group(2).strip()
                    continue
                if stripped == "":
                    continue
                in_body = True
            body_lines.append(ln)
        body = "\n".join(body_lines).strip()
        results.append((block, meta, body))
    return results


def _format_idea_suggestion(source_id: str, info: dict, it: dict, today: str) -> str:
    """把 LLM 抽取的 idea dict 格式化成 idea_suggestion 模板格式的块。

    v0.4.13: 简化为只写 title + id + status + source(保留 source 追溯来源文章)。
    LLM 抽取现在只返回 title;旧数据若带其他字段则忽略(向后兼容)。
    """
    slug = make_slug(it.get("title", "untitled")) or "untitled"
    # v0.4.12: 加 4 字节随机后缀(8 hex),防同日同标题撞 id。
    import secrets
    suffix = secrets.token_hex(4)
    iid = f"idea_suggestion_{today.replace('-', '')}_{slug}_{suffix}"
    src_summary = f"[[summary_{source_id}]]"
    return f"""
## Idea Suggestion: {it.get('title', 'untitled')}

- id: {iid}
- status: pending_review
- source_summary: {src_summary}
"""


def _format_todo_suggestion(source_id: str, info: dict, it: dict, today: str) -> str:
    """把 LLM 抽取的 todo dict 格式化成 todo_suggestion 模板格式的块。

    v0.4.13: 简化为只写 title + id + status + source(保留 source 追溯来源文章)。
    LLM 抽取现在只返回 title;旧数据若带其他字段则忽略(向后兼容)。
    """
    slug = make_slug(it.get("title", "untitled")) or "untitled"
    # v0.4.12: 加 4 字节随机后缀(8 hex),防同日同标题撞 id。
    import secrets
    suffix = secrets.token_hex(4)
    tid = f"todo_suggestion_{today.replace('-', '')}_{slug}_{suffix}"
    src_summary = f"[[summary_{source_id}]]"
    return f"""
## Todo Suggestion: {it.get('title', 'untitled')}

- id: {tid}
- status: pending_review
- source_summary: {src_summary}
"""


def _format_formal_idea(meta: dict, body: str, area: str) -> str:
    """把 accepted idea suggestion 转成正式 idea list 条目(idea_template 格式)。

    v0.4.13: 简化为只写 title + id + status + source(与抽取简化一致)。
    保留 sources 追溯来源文章。
    """
    title = meta.get("title", meta.get("id", "untitled"))
    today = today_iso()
    slug = make_slug(title) or "untitled"
    iid = f"idea_{today.replace('-', '')}_{slug}"
    return f"""

## Idea: {title}

- id: {iid}
- status: candidate
- maturity: spark
- sources:
  - {meta.get('source_summary', '')}

{body or '（待补充）'}
"""


def _format_weekly_task(meta: dict, body: str) -> str:
    """把 accepted todo suggestion 转成 weekly/monthly task 格式(plan.md 11.1)。

    v0.4.13: 简化为只写 title + 来源 + 截止日期(若有)。
    """
    title = meta.get("title", meta.get("id", "untitled"))
    deadline = meta.get("deadline", "") if meta else ""
    deadline_line = f"  - 截止日期:{deadline}\n" if deadline else ""
    return f"""

- [ ] {title}
  - 来源:{meta.get('source_summary', '')}
{deadline_line}"""


def _append_section(path: Path, section: str) -> None:
    """把 section 追加到文件末尾(自动创建父目录)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding=ENC) as fh:
        fh.write(section.rstrip() + "\n")


def _replace_status_in_block(block: str, old_status: str, new_status: str) -> str:
    """把块里的 status 行替换为新状态。"""
    return re.sub(
        r"^(-\s*status:\s*)" + re.escape(old_status) + r"\s*$",
        rf"\g<1>{new_status}",
        block,
        flags=re.MULTILINE,
    )


def _suggestion_header(title: str, kind: str) -> str:
    """review 队列文件的头部说明。"""
    accept_val = "accepted_research" if kind == "idea" else "accepted_weekly"
    return f"""# {title}

> AI / Codex 生成的候选先进入这里。用户确认后改 status 为 `{accept_val}` 等,
> 再运行 `python scripts/kb.py accept-{'ideas' if kind == 'idea' else 'todos'}`。
> 已移动的候选 status 会变成 `moved`,保留作追溯。

"""


def _ensure_weekly_file(path: Path, week_tag: str) -> None:
    """确保 weekly 文件存在,不存在则用模板创建。"""
    if path.exists():
        return
    content = f"""# Weekly Todo: {week_tag}

## 本周重点

## Research

## Productivity

## Review

- [ ] Review pending summaries
- [ ] Review idea suggestions
- [ ] Review todo suggestions
"""
    write_text(path, content)


def _ensure_monthly_file(path: Path, month_tag: str) -> None:
    """确保 monthly 文件存在。"""
    if path.exists():
        return
    content = f"""# Monthly Todo: {month_tag}

## 本月目标

## Research

## Productivity

## 要尝试的工具 / repo

## 暂缓事项

## 月末复盘
"""
    write_text(path, content)


# ---------------------------------------------------------------------------
# Event(事件)管理 —— 用户主动创建并关注的事件(比赛/会议/财报发布等)
# 单日期 + Markdown 文件存储(06_Events/event_*.md),支持单向同步到日历。
# 不走 review 队列(纯手动创建),frontmatter 全用字符串字段(parsefrontmatter 兼容)。
# ---------------------------------------------------------------------------

EVENT_DIR_NAME = "06_Events"
# 事件 category 与日历共享(同步时直接透传给 calendar item)
EVENT_CATEGORIES = ("会议", "财报", "截止日期", "发布", "比赛", "其他")


def make_event_id(title: str) -> str:
    """生成稳定事件 id:event_<8位hash>。基于标题+当前时刻,保证新建不冲突。"""
    import time
    raw = f"{title}|{time.time_ns()}"
    return f"event_{content_hash(raw)}"


def _event_file_path(event_id: str) -> Path:
    """由 event_id 推导对应的 markdown 文件路径。"""
    slug_part = event_id.removeprefix("event_")
    return VAULT_ROOT / EVENT_DIR_NAME / f"event_{slug_part}.md"


def _find_event_file(event_id: str) -> Path | None:
    """扫描 06_Events/ 找到 frontmatter id == event_id 的文件。返回路径或 None。

    文件名含 event_id 的 hash 段,但保险起见仍校验 frontmatter id(文件名可能被改)。
    """
    events_dir = VAULT_ROOT / EVENT_DIR_NAME
    if not events_dir.exists():
        return None
    # 先试文件名直查(快路径)
    direct = _event_file_path(event_id)
    if direct.exists():
        return direct
    # 兜底:扫描所有 event_*.md 校验 frontmatter id
    for path in events_dir.glob("event_*.md"):
        try:
            meta, _ = parsefrontmatter(read_text(path))
            if meta.get("id", "").strip() == event_id:
                return path
        except Exception:
            continue
    return None


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
    text = read_text(path)
    meta, body = parsefrontmatter(text)
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
        "path": path.relative_to(VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def _is_relative(path: Path) -> bool:
    """判断 path 是否在 VAULT_ROOT 下(用于决定是否输出相对路径)。"""
    try:
        path.relative_to(VAULT_ROOT)
        return True
    except ValueError:
        return False


def _log_scan_error(path: Path, err: Exception) -> None:
    """scan_tasks/scan_events 遇到损坏文件时备份 + 记日志(v0.4.12 M3)。

    与 load_state 损坏策略一致:备份到 .kb/logs/,记 WARNING 日志,不抛(调用方继续扫下一个)。
    """
    try:
        backup_dir = LOGS_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        corrupt_backup = backup_dir / f"corrupt_{path.stem}_{ts}.md"
        shutil.copy2(path, corrupt_backup)
        backup_msg = f"(已备份到 {corrupt_backup.name})"
    except Exception as be:
        backup_msg = f"(备份失败: {be})"
    try:
        append_log(f"WARNING: {path.name} 解析失败({type(err).__name__}: {err}) {backup_msg}")
    except Exception:
        pass


def scan_events() -> list[dict]:
    """扫描 06_Events/event_*.md,返回按日期升序排列的事件列表。

    每个元素是 load_event_file 的返回 dict。目录不存在或无文件返回 []。
    v0.4.12: 损坏文件备份 + 记日志(不再静默 continue),与 load_state 同款策略。
    """
    events_dir = VAULT_ROOT / EVENT_DIR_NAME
    if not events_dir.exists():
        return []
    results: list[dict] = []
    for path in sorted(events_dir.glob("event_*.md")):
        try:
            results.append(load_event_file(path))
        except Exception as e:
            _log_scan_error(path, e)
    results.sort(key=lambda e: e.get("date", "") or "9999")
    return results


def write_event_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """原子写事件文件。新建时补 created_at,更新时刷新 updated_at。

    completed_at 生命周期(v0.4.12,与 task 对称):status==done 且无值时写入,
    非 done 清空。旧文件缺该字段时首次标 done 补当天。
    """
    now = now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    if meta.get("status") == "done":
        if not meta.get("completed_at"):
            meta["completed_at"] = now
    else:
        meta["completed_at"] = ""
    meta["updated_at"] = now
    write_text(path, _format_event_file(meta, body))


def sync_event_to_calendar(event_id: str) -> dict:
    """把单个事件单向推送到日历(创建一条 calendar item,回指 event_id)。

    幂等:若该事件已有存活的 calendar item(synced_calendar_ids 里仍有在日历中的),
    不重复创建。日历项被删后允许重新推送。

    返回:
        {synced: bool, event_id, calendar_id, reason}
        synced=True 时 calendar_id 是新建/已有的日历项 id。
    """
    import uuid as _uuid

    path = _find_event_file(event_id)
    if path is None:
        return {"synced": False, "event_id": event_id, "reason": "event_not_found"}

    event = load_event_file(path)
    if not event["date"]:
        return {"synced": False, "event_id": event_id, "reason": "event_has_no_date"}

    cal = load_calendar()
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
    now = now_ts()
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
    save_calendar(cal)

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
# Task(任务)管理 —— 用户主动创建的任务(带 checklist/截止日期/阻塞点)
# 单文件存储(07_Tasks/task_*.md),YAML frontmatter + Markdown 正文。
# 与 04_Plans/todo_suggestions.md(从文章抽取的待办建议)是完全不同的系统。
# 模式照搬 06_Events(events_*),新增 checklist(JSON 结构化)+ deadline + blocker 字段。
# ---------------------------------------------------------------------------

TASK_DIR_NAME = "07_Tasks"
# 任务分类(建议集,允许自定义,不强制白名单)
TASK_CATEGORIES = ("开发", "调研", "写作", "阅读", "整理", "其他")


def make_task_id(title: str) -> str:
    """生成稳定任务 id:task_<8位hash>。基于标题+当前时刻,保证新建不冲突。"""
    import time
    raw = f"{title}|{time.time_ns()}"
    return f"task_{content_hash(raw)}"


def _task_file_path(task_id: str) -> Path:
    """由 task_id 推导对应的 markdown 文件路径。"""
    slug_part = task_id.removeprefix("task_")
    return VAULT_ROOT / TASK_DIR_NAME / f"task_{slug_part}.md"


def _find_task_file(task_id: str) -> Path | None:
    """扫描 07_Tasks/ 找到 frontmatter id == task_id 的文件。返回路径或 None。

    文件名含 task_id 的 hash 段,但保险起见仍校验 frontmatter id(文件名可能被改)。
    """
    tasks_dir = VAULT_ROOT / TASK_DIR_NAME
    if not tasks_dir.exists():
        return None
    direct = _task_file_path(task_id)
    if direct.exists():
        return direct
    for path in tasks_dir.glob("task_*.md"):
        try:
            meta, _ = parsefrontmatter(read_text(path))
            if meta.get("id", "").strip() == task_id:
                return path
        except Exception:
            continue
    return None


def _format_task_file(meta: dict, body: str) -> str:
    """把任务 meta dict + 正文格式化成完整 markdown 文件内容(frontmatter + body)。

    checklist 存为 JSON 字符串(单行),load 时 json.loads 还原成 list[dict]。
    synced_calendar_ids 用逗号分隔(避免 YAML 列表解析复杂度)。
    """
    cl = meta.get("checklist", [])
    if isinstance(cl, list):
        cl = json.dumps(cl, ensure_ascii=False)
    lines = ["---"]
    for key in ("id", "title", "category", "project", "status",
                "deadline", "blocker", "checklist",
                "related_source", "synced_calendar_ids",
                "created_at", "updated_at", "completed_at"):
        val = meta.get(key, "")
        # checklist 字段用 JSON 字符串,其余字段原样输出
        if key == "checklist":
            val = cl if cl else "[]"
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() if body else "（暂无描述）")
    return "\n".join(lines) + "\n"


def load_task_file(path: Path) -> dict:
    """读任务 markdown 文件,返回完整字段 dict(含 body)。

    checklist 解析成 list[dict](JSON 反序列化),synced_calendar_ids 解析成 list[str]。
    """
    text = read_text(path)
    meta, body = parsefrontmatter(text)
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
        "checklist": checklist,
        "related_source": meta.get("related_source", "").strip(),
        "synced_calendar_ids": synced,
        "created_at": meta.get("created_at", "").strip(),
        "updated_at": meta.get("updated_at", "").strip(),
        "completed_at": meta.get("completed_at", "").strip(),
        "body": body,
        "path": path.relative_to(VAULT_ROOT).as_posix() if _is_relative(path) else str(path),
    }


def scan_tasks() -> list[dict]:
    """扫描 07_Tasks/task_*.md,返回按 deadline 升序排列的任务列表。

    无 deadline 的排末尾(用 9999 sentinel)。每个元素是 load_task_file 的返回 dict。
    v0.4.12: 损坏文件备份 + 记日志(不再静默 continue),与 load_state 同款策略。
    """
    tasks_dir = VAULT_ROOT / TASK_DIR_NAME
    if not tasks_dir.exists():
        return []
    results: list[dict] = []
    for path in sorted(tasks_dir.glob("task_*.md")):
        try:
            results.append(load_task_file(path))
        except Exception as e:
            _log_scan_error(path, e)
    results.sort(key=lambda t: t.get("deadline", "") or "9999")
    return results


def write_task_file(path: Path, meta: dict, body: str, *, is_new: bool = False) -> None:
    """原子写任务文件。新建时补 created_at,更新时刷新 updated_at。

    completed_at 生命周期(v0.4.11 工作台本周概览需要):
    - status==done 且无 completed_at → 写当前时间(首次完成)
    - status==done 且已有 completed_at → 保留(重复打 done 不覆盖首次完成时间)
    - status!=done → 清空(任务被重新激活)
    旧任务文件无此字段时,首次标记 done 会补当天时间(历史完成时间已丢失,无法回溯)。
    """
    now = now_ts()
    if is_new and not meta.get("created_at"):
        meta["created_at"] = now
    if meta.get("status") == "done":
        if not meta.get("completed_at"):
            meta["completed_at"] = now
    else:
        meta["completed_at"] = ""
    meta["updated_at"] = now
    write_text(path, _format_task_file(meta, body))


def sync_task_to_calendar(task_id: str) -> dict:
    """把单个任务单向推送到日历(创建一条 calendar item,回指 task_id)。

    幂等:若该任务已有存活的 calendar item,不重复创建。日历项被删后允许重新推送。
    """
    import uuid as _uuid

    path = _find_task_file(task_id)
    if path is None:
        return {"synced": False, "task_id": task_id, "reason": "task_not_found"}

    task = load_task_file(path)
    if not task["deadline"]:
        return {"synced": False, "task_id": task_id, "reason": "task_has_no_deadline"}

    cal = load_calendar()
    items = cal.get("items", {})

    for existing_id in task["synced_calendar_ids"]:
        if existing_id in items:
            return {
                "synced": False, "task_id": task_id,
                "calendar_id": existing_id, "reason": "already_synced",
            }

    item_id = f"cal_{_uuid.uuid4().hex[:12]}"
    now = now_ts()
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
    save_calendar(cal)

    new_synced = task["synced_calendar_ids"] + [item_id]
    meta = {k: v for k, v in task.items() if k not in ("body", "path")}
    meta["synced_calendar_ids"] = ",".join(new_synced)
    write_task_file(path, meta, task["body"], is_new=False)

    return {
        "synced": True, "task_id": task_id,
        "calendar_id": item_id, "reason": "created",
    }


# ---------------------------------------------------------------------------
# 悬空引用清理(v0.4.12 修复 M5)
# ---------------------------------------------------------------------------
# 删除 calendar item / task / event / 文章后,frontmatter 里的回指字段
# (synced_calendar_ids / related_source)不会自动清理,长期累积成悬空指针。
# 以下函数扫 markdown 文件清理这些引用。失败静默(清理不应阻断主操作)。

def cleanup_calendar_ref(cal_id: str) -> int:
    """从所有 task/event 的 synced_calendar_ids 里移除指定 cal_id。

    返回清理的文件数。失败静默返回 0。
    """
    n = 0
    for loader, finder_all, writer in (
        # (load单文件函数, 扫描全部函数, 写函数) —— task
        (load_task_file, lambda: (VAULT_ROOT / TASK_DIR_NAME).glob("task_*.md"), write_task_file),
        (load_event_file, lambda: (VAULT_ROOT / EVENT_DIR_NAME).glob("event_*.md"), write_event_file),
    ):
        try:
            for path in finder_all():
                try:
                    rec = loader(path)
                except Exception:
                    continue
                synced = rec.get("synced_calendar_ids", [])
                if cal_id in synced:
                    new_synced = [x for x in synced if x != cal_id]
                    meta = {k: v for k, v in rec.items() if k not in ("body", "path")}
                    meta["synced_calendar_ids"] = ",".join(new_synced)
                    writer(path, meta, rec.get("body", ""), is_new=False)
                    n += 1
        except Exception:
            continue
    return n


def cleanup_source_ref(source_id: str) -> int:
    """从所有 task/event 的 related_source 字段清空(指向该 source 的)。

    删除文章后调用,避免 related_source 悬空 404。返回清理的文件数。
    """
    n = 0
    for loader, finder_all, writer in (
        (load_task_file, lambda: (VAULT_ROOT / TASK_DIR_NAME).glob("task_*.md"), write_task_file),
        (load_event_file, lambda: (VAULT_ROOT / EVENT_DIR_NAME).glob("event_*.md"), write_event_file),
    ):
        try:
            for path in finder_all():
                try:
                    rec = loader(path)
                except Exception:
                    continue
                if rec.get("related_source", "").strip() == source_id:
                    meta = {k: v for k, v in rec.items() if k not in ("body", "path")}
                    meta["related_source"] = ""
                    writer(path, meta, rec.get("body", ""), is_new=False)
                    n += 1
        except Exception:
            continue
    return n


def cleanup_dead_calendar_items() -> int:
    """删除回指已不存在的 task/event 的孤儿日历项(M6)。

    供 CLI reconcile 命令调用。返回删除的孤儿项数。
    """
    cal = load_calendar()
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
        save_calendar(cal)
    return len(dead)


def cmd_clean_x(args: argparse.Namespace) -> int:
    """清洗已入库的 X source 正文(就地重写「## 原始内容」段,frontmatter 不动)。

    供修复历史数据用:ingest 阶段的 X 去噪只对新入库生效,本命令把存量 X source
    也洗一遍。幂等——已清洗的再跑不变。

    用法:
        python scripts/kb.py clean-x            # 实际清洗
        python scripts/kb.py clean-x --dry-run  # 只打印效果,不写文件
    """
    if not _LLM_AVAILABLE:
        print("[clean-x] 需要 kb_llm 模块,无法运行。")
        return 1

    x_dir = VAULT_ROOT / "01_Sources" / "x"
    if not x_dir.exists():
        print(f"[clean-x] 目录不存在:{x_dir}")
        return 1

    files = sorted(x_dir.glob("*.md"))
    if not files:
        print("[clean-x] 没有 X source 文件。")
        return 0

    dry = bool(getattr(args, "dry_run", False))
    total_before = total_after = changed = 0
    for f in files:
        text = read_text(f)
        # 定位「## 原始内容」段
        m = re.search(r"(##\s*原始内容\s*\n)(.*)", text, re.DOTALL)
        if not m:
            print(f"  跳过(无「原始内容」段):{f.name}")
            continue
        head_marker, body = m.group(1), m.group(2).strip()
        cleaned = kb_llm.clean_x_text(body)
        total_before += len(body)
        total_after += len(cleaned)
        if cleaned == body:
            continue  # 无变化
        changed += 1
        # 重写:替换「原始内容」之后的全部内容
        prefix = text[: m.start()] + head_marker
        new_text = prefix + cleaned + "\n"
        if dry:
            print(f"  [dry-run] {f.name}: {len(body)} -> {len(cleaned)}")
        else:
            write_text(f, new_text)
            print(f"  ✓ {f.name}: {len(body)} -> {len(cleaned)}")

    pct = f"(-{100 * (1 - total_after / total_before):.0f}%)" if total_before > 0 else ""
    print(
        f"[clean-x] 共 {len(files)} 个 X source,本次修改 {changed} 个;"
        f"正文 {total_before} -> {total_after}"
        f"{pct}"
        + (" [dry-run,未写入]" if dry else "")
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """启动知识库阅读前端(FastAPI)。

    浏览器访问 http://127.0.0.1:<port> 查看卡片仪表盘。

    v0.4.6 安全加固:
    - host 非 loopback 时打印警告,要求 KB_SERVE_CONFIRM_EXPOSE=1 才继续
    - 建议设 KB_WEB_USER / KB_WEB_PASSWORD 启用 Basic Auth(见 kb_web.py)
    """
    print(f"[serve] 启动知识库阅读前端...")
    print(f"[serve] vault = {VAULT_ROOT}")

    # 安全检查:host 暴露到外网时要求显式确认
    safe_hosts = {"127.0.0.1", "localhost", "::1", ""}
    if args.host not in safe_hosts:
        print()
        print("=" * 60)
        print(f"[serve] ⚠ 警告:host={args.host} 将暴露到外网!")
        print(f"[serve] 当前 FastAPI 实例{'已启用 Basic Auth' if os.environ.get('KB_WEB_USER') else '无任何认证(裸奔)'}。")
        if not os.environ.get('KB_WEB_USER'):
            print(f"[serve] 强烈建议设置环境变量 KB_WEB_USER / KB_WEB_PASSWORD 启用 Basic Auth。")
        print(f"[serve] 确认要继续暴露,请设环境变量 KB_SERVE_CONFIRM_EXPOSE=1 后重跑。")
        print("=" * 60)
        if os.environ.get('KB_SERVE_CONFIRM_EXPOSE') != '1':
            print(f"[serve] 已阻止启动(未确认)。如确需暴露,设置 KB_SERVE_CONFIRM_EXPOSE=1。")
            return 1
        print(f"[serve] 已确认暴露风险,继续启动。")

    print(f"[serve] 监听 http://{args.host}:{args.port}")
    if os.environ.get('KB_WEB_USER'):
        print(f"[serve] Basic Auth 已启用(user={os.environ.get('KB_WEB_USER')})")
    print(f"[serve] 按 Ctrl+C 停止")
    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("[serve] 错误:缺少 uvicorn。请运行:  pip install -r requirements.txt")
        return 1
    try:
        import kb_web  # type: ignore
    except ImportError as e:
        print(f"[serve] 错误:无法加载 kb_web 模块({e})。")
        print("       请确保 scripts/kb_web.py 存在且依赖已安装。")
        return 1
    # 把绑定 host 暴露给请求层,/api/shutdown 用它做 loopback 白名单校验
    kb_web.app.state.bind_host = args.host
    uvicorn.run(
        kb_web.app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kb.py",
        description="Obsidian 本地知识库 CLI(Phase 0-2 + 4,支持 LLM)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="创建 vault 目录结构 / 模板 / 空文件 / state.json")
    p_init.add_argument("-v", "--verbose", action="store_true", help="列出创建的每个文件/目录")
    p_init.set_defaults(func=cmd_init)

    p_ingest = sub.add_parser("ingest", help="解析 00_Inbox/inbox.md,生成 source note")
    p_ingest.add_argument(
        "--no-llm",
        action="store_true",
        help="离线模式:只接受 KB_ITEM 格式,不调用 LLM",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_status = sub.add_parser("status", help="输出当前知识库状态统计")
    p_status.add_argument("-v", "--verbose", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_llm = sub.add_parser("llm-test", help="测试 LLM API 连通性")
    p_llm.set_defaults(func=cmd_llm_test)

    p_mp = sub.add_parser("make-prompts", help="Phase 2:为 source 生成 summary")
    p_mp.add_argument("--auto", action="store_true", help="直接调 LLM 生成 summary(默认生成 prompt 文件)")
    p_mp.add_argument("--reconcile", action="store_true", help="回填已有 summary 到 source/state")
    p_mp.add_argument("--source", help="只处理指定 source_id")
    p_mp.add_argument("--force", action="store_true", help="强制重新生成已存在的 summary")
    p_mp.set_defaults(func=cmd_make_prompts)

    p_es = sub.add_parser("extract-suggestions", help="从 summary 抽取 idea/todo 候选到 review 队列")
    p_es.add_argument("--source", help="只处理指定 source_id")
    p_es.set_defaults(func=cmd_extract_suggestions)

    p_ai = sub.add_parser("accept-ideas", help="Phase 4:把 accepted idea 移到正式 idea list")
    p_ai.set_defaults(func=cmd_accept_ideas)

    p_at = sub.add_parser("accept-todos", help="Phase 4:把 accepted todo 移到 weekly/monthly/someday")
    p_at.set_defaults(func=cmd_accept_todos)

    p_serve = sub.add_parser("serve", help="启动知识库阅读前端(FastAPI)")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址(默认 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=5173, help="监听端口(默认 5173)")
    p_serve.add_argument("--reload", action="store_true", help="开发模式(代码变更自动重载)")
    p_serve.set_defaults(func=cmd_serve)

    p_cx = sub.add_parser("clean-x", help="清洗已入库的 X source 正文(去站点噪声/压缩重复)")
    p_cx.add_argument("--dry-run", action="store_true", help="只预览效果,不写文件")
    p_cx.set_defaults(func=cmd_clean_x)

    p_ri = sub.add_parser(
        "rebuild-index",
        help="从 summary frontmatter 重建 state.json 的 tags / summary_path",
    )
    p_ri.add_argument("--dry-run", action="store_true", help="只报告差异,不写文件")
    p_ri.add_argument("--tags-only", action="store_true", help="只同步 tags,不动 summary_path")
    p_ri.add_argument("--summary-path-only", action="store_true", help="只回填 summary_path,不动 tags")
    p_ri.add_argument("-v", "--verbose", action="store_true", help="列出每条变更明细")
    p_ri.set_defaults(func=cmd_rebuild_index)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
