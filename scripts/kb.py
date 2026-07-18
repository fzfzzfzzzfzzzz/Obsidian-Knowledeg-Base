#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Obsidian 本地知识库 CLI —— MVP Phase 0 + Phase 1

依据 obsidian_kb_codex_implementation_plan.md 第 15 节实现。

命令:
    python scripts/kb.py init          创建 vault 目录结构 / 模板 / 空文件 / state.json
    python scripts/kb.py ingest        解析 00_Inbox/inbox.md 中的 KB_ITEM block,生成 source note
    python scripts/kb.py status        输出当前知识库状态统计
    python scripts/kb.py make-prompts  [Phase 2 占位] 未实现
    python scripts/kb.py accept-ideas  [Phase 4 占位] 未实现
    python scripts/kb.py accept-todos  [Phase 4 占位] 未实现

设计原则(对应 plan.md 第 13 节 Codex 工作规则):
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
import re
import sys
from datetime import date
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
VAULT_ROOT = Path(__file__).resolve().parent.parent

# 机器运行目录(可被 Obsidian 隐藏)
KB_DIR = VAULT_ROOT / ".kb"
STATE_FILE = KB_DIR / "state.json"
CALENDAR_FILE = KB_DIR / "calendar.json"
RAW_TEXT_DIR = KB_DIR / "raw_text"
LOGS_DIR = KB_DIR / "logs"

# 常用编码
ENC = "utf-8"

# 支持的来源类型(决定 source note 写入哪个子目录)
# 注意:与 plan.md 第 4 节 inbox 格式一致,使用 gpt_chat(而非目录名 gpt)
SOURCE_TYPES = ("github", "x", "wechat", "douyin", "gpt_chat", "web", "manual")

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str) -> None:
    """以 UTF-8 写入文件,自动创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=ENC, newline="\n")


def read_text(path: Path) -> str:
    """以 UTF-8 读取文件。"""
    return path.read_text(encoding=ENC)


def load_state() -> dict:
    """读取 .kb/state.json,不存在则返回空骨架。"""
    if not STATE_FILE.exists():
        return {
            "version": 1,
            "created_at": date.today().isoformat(),
            "sources": {},  # source_id -> {path, source_type, source_title, created_at, ingested_at}
        }
    try:
        return json.loads(read_text(STATE_FILE))
    except (json.JSONDecodeError, OSError):
        return {
            "version": 1,
            "created_at": date.today().isoformat(),
            "sources": {},
        }


def save_state(state: dict) -> None:
    write_text(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))


def load_calendar() -> dict:
    """读取 .kb/calendar.json,不存在则返回空骨架。"""
    if not CALENDAR_FILE.exists():
        return {"version": 1, "items": {}}
    try:
        return json.loads(read_text(CALENDAR_FILE))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "items": {}}


def save_calendar(cal: dict) -> None:
    write_text(CALENDAR_FILE, json.dumps(cal, ensure_ascii=False, indent=2))


def append_log(message: str) -> None:
    """追加一行到 .kb/logs/kb.log。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = date.today().isoformat()
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


def make_source_filename(source_id: str, created_at: str, title: str) -> str:
    """生成可读文件名:source_YYYYMMDD_<可读标题>.md。

    幂等性不靠文件名(靠 source_id),所以文件名只追求可读性。
    标题做 slug 处理,无标题时回退到 source_id 的 hash 段。
    """
    date_compact = created_at.replace("-", "")
    slug = make_slug(title, max_len=40)
    if not slug:
        # 无标题:用 source_id 的 hash 段保证唯一性
        hash_part = source_id.replace("source_ff_", "").replace("source_", "")
        slug = f"untitled_{hash_part[:6]}"
    return f"source_{date_compact}_{slug}.md"


def make_summary_filename(source_id: str, created_at: str, title: str) -> str:
    """生成可读 summary 文件名:summary_YYYYMMDD_<可读标题>.md。"""
    date_compact = created_at.replace("-", "")
    slug = make_slug(title, max_len=40)
    if not slug:
        hash_part = source_id.replace("source_ff_", "").replace("source_", "")
        slug = f"untitled_{hash_part[:6]}"
    return f"summary_{date_compact}_{slug}.md"


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
    body_start = 0
    in_header = True
    cleaned: list[str] = []
    for line in lines:
        if in_header:
            stripped = line.strip()
            if stripped == "" or _INBOX_HEADER_RE.match(stripped):
                continue
            in_header = False
        cleaned.append(line)

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
    body_lines = []
    in_header = True
    for line in inbox_text.splitlines():
        if in_header:
            stripped = line.strip()
            if stripped == "" or _INBOX_HEADER_RE.match(stripped):
                continue
            in_header = False
        body_lines.append(line)
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
    today = date.today().isoformat()
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


# 顶层文档
AGENTS_MD = """# AGENTS.md

## Project Goal

Build a local-first Obsidian knowledge base for summarizing frontier technical materials, extracting idea suggestions, and generating weekly/monthly todo suggestions.

## Hard Rules

- Markdown files are the primary data layer.
- Do not silently overwrite user-authored notes.
- AI-generated ideas and todos must go into suggestion files first.
- Only user-accepted suggestions may be moved into formal idea lists or weekly/monthly todo files.
- MVP must not require external LLM APIs.
- MVP must support manually pasted text in Inbox.

## MVP Commands

- Initialize vault structure: `python scripts/kb.py init`
- Parse inbox: `python scripts/kb.py ingest`
- Generate manual LLM prompts: `python scripts/kb.py make-prompts`
- Move accepted ideas: `python scripts/kb.py accept-ideas`
- Move accepted todos: `python scripts/kb.py accept-todos`
- Show status: `python scripts/kb.py status`

## Completion Criteria

A task is complete only if:

1. It preserves existing user content.
2. It creates readable Markdown output.
3. It updates status fields consistently.
4. It includes a short usage note.
5. It has been tested with at least one sample Inbox item.

## Current Phase Status

- Phase 0 (init): **done**
- Phase 1 (ingest parser): **done**(支持自由文本 + KB_ITEM 双格式,可接 LLM)
- Phase 2 (make-prompts): pending
- Phase 3 (manual output import): pending
- Phase 4 (accept-ideas / accept-todos): pending
- Phase 5 (status dashboard): **done** (basic version)
"""


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
                "created_at": date.today().isoformat(),
                "sources": {},
            }
        )
        created_files.append(".kb/state.json")

    # ---- .kb/calendar.json ----
    if not CALENDAR_FILE.exists():
        save_calendar({"version": 1, "items": {}})
        created_files.append(".kb/calendar.json")

    # ---- 顶层文档(只创建缺失的)----
    agents = VAULT_ROOT / "AGENTS.md"
    if not agents.exists():
        write_text(agents, AGENTS_MD)
        created_files.append("AGENTS.md")

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
    today = date.today().isoformat()

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


def _strip_inbox_header(text: str) -> str:
    """去掉文本开头的 inbox 头部说明区(以 # 或 > 开头的连续行 + 空行)。"""
    lines = text.splitlines()
    out: list[str] = []
    in_header = True
    for line in lines:
        if in_header:
            stripped = line.strip()
            if stripped == "" or _INBOX_HEADER_RE.match(stripped):
                continue
            in_header = False
        out.append(line)
    return "\n".join(out)


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
    idea_pending = (
        read_text(idea_sug).count("status: pending_review")
        if idea_sug.exists()
        else 0
    )
    todo_pending = (
        read_text(todo_sug).count("status: pending_review")
        if todo_sug.exists()
        else 0
    )
    idea_accepted = (
        read_text(idea_sug).count("status: accepted_")
        if idea_sug.exists()
        else 0
    )
    todo_accepted = (
        read_text(todo_sug).count("status: accepted_")
        if todo_sug.exists()
        else 0
    )
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


def cmd_not_implemented(name: str, phase: str) -> int:
    print(f"[{name}] 该命令属于 {phase},当前 MVP(Phase 0+1)尚未实现。")
    print(f"[{name}] 参见 obsidian_kb_codex_implementation_plan.md 第 15 节。")
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
            today = date.today().isoformat()
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

    save_state(state)
    append_log(
        f"extract-suggestions: sources={len(targets)} ideas={total_ideas} todos={total_todos}"
    )
    print(f"\n[extract-suggestions] 完成。共抽取 idea 候选 {total_ideas} 个,todo 候选 {total_todos} 个。")
    if total_ideas or total_todos:
        print("[extract-suggestions] 候选已进入 review 队列:")
        print("  - 03_Ideas/idea_suggestions.md")
        print("  - 04_Plans/todo_suggestions.md")
        print("  用户确认后改 status 为 accepted_*,再运行 accept-ideas / accept-todos。")
    return 0


def cmd_accept_ideas(args):
    """Phase 4:把 accepted 的 idea suggestion 移到正式 idea list。"""
    sug_file = VAULT_ROOT / "03_Ideas" / "idea_suggestions.md"
    if not sug_file.exists():
        print("[accept-ideas] idea_suggestions.md 不存在。")
        return 1

    text = read_text(sug_file)
    blocks = _split_suggestion_blocks(text, "Idea Suggestion")
    if not blocks:
        print("[accept-ideas] 没有找到 idea suggestion 块。")
        return 0

    moved = 0
    skipped = 0
    new_blocks: list[str] = []  # 用于回写 sug 文件

    for raw, meta, body in blocks:
        status = meta.get("status", "").strip()
        if status.startswith("accepted_"):
            # 决定目标文件
            area = status.removeprefix("accepted_")  # research / productivity
            target = VAULT_ROOT / "03_Ideas" / f"{area}_ideas.md"
            if not target.exists():
                # 不支持的 area,创建一个通用的
                target = VAULT_ROOT / "03_Ideas" / f"{area}_ideas.md"
            formal = _format_formal_idea(meta, body, area)
            _append_section(target, formal)
            moved += 1
            print(f"  → {meta.get('title', meta.get('id','?'))} → {target.relative_to(VAULT_ROOT)}")
            # 标记原块为 moved
            moved_block = _replace_status_in_block(raw, status, "moved")
            new_blocks.append(moved_block)
        else:
            skipped += 1
            new_blocks.append(raw)

    # 回写 sug 文件(更新过的块 + 头部)
    if moved > 0:
        header = _suggestion_header("Idea Suggestions (Review Queue)", "idea")
        write_text(sug_file, header + "\n".join(new_blocks) + "\n")

    append_log(f"accept-ideas: moved={moved} skipped={skipped}")
    print(f"\n[accept-ideas] 移动 {moved} 个,跳过 {skipped} 个(非 accepted 状态)。")
    if moved:
        print("[accept-ideas] 正式 idea list 已更新,原 suggestion 标记为 moved。")
    return 0


def cmd_accept_todos(args):
    """Phase 4:把 accepted 的 todo suggestion 移到 weekly/monthly/someday。"""
    sug_file = VAULT_ROOT / "04_Plans" / "todo_suggestions.md"
    if not sug_file.exists():
        print("[accept-todos] todo_suggestions.md 不存在。")
        return 1

    text = read_text(sug_file)
    blocks = _split_suggestion_blocks(text, "Todo Suggestion")
    if not blocks:
        print("[accept-todos] 没有找到 todo suggestion 块。")
        return 0

    moved = 0
    skipped = 0
    new_blocks: list[str] = []

    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week_tag = f"{iso_year}-W{iso_week:02d}"
    month_tag = today.strftime("%Y-%m")

    for raw, meta, body in blocks:
        status = meta.get("status", "").strip()
        if status.startswith("accepted_"):
            plan = status.removeprefix("accepted_")  # weekly/monthly/someday
            if plan == "weekly":
                target = VAULT_ROOT / "04_Plans" / "Weekly" / f"{week_tag}.md"
                _ensure_weekly_file(target, week_tag)
            elif plan == "monthly":
                target = VAULT_ROOT / "04_Plans" / "Monthly" / f"{month_tag}.md"
                _ensure_monthly_file(target, month_tag)
            else:  # someday
                target = VAULT_ROOT / "04_Plans" / "someday.md"
                if not target.exists():
                    write_text(target, "# Someday Todo\n\n> 暂存,有空再做。\n\n")
            task = _format_weekly_task(meta, body)
            _append_section(target, task)
            moved += 1
            print(f"  → {meta.get('title', meta.get('id','?'))} → {target.relative_to(VAULT_ROOT)}")
            moved_block = _replace_status_in_block(raw, status, "moved")
            new_blocks.append(moved_block)
        else:
            skipped += 1
            new_blocks.append(raw)

    if moved > 0:
        header = _suggestion_header("Todo Suggestions (Review Queue)", "todo")
        write_text(sug_file, header + "\n".join(new_blocks) + "\n")

    append_log(f"accept-todos: moved={moved} skipped={skipped}")
    print(f"\n[accept-todos] 移动 {moved} 个,跳过 {skipped} 个(非 accepted 状态)。")
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
    """从 summary 文件提取正文(去 frontmatter)。"""
    return re.sub(r"^---.*?---\s*", "", summary_text, flags=re.DOTALL).strip()


def _write_summary(sid: str, info: dict, body: str) -> Path:
    """把 LLM 生成的 summary body 包装成完整文件写入 02_Summaries/。返回路径。

    文件名用可读格式(日期+标题);frontmatter 里 source_id 是幂等键(纯 hash)。
    """
    today = date.today().isoformat()
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
    outline = kb_llm._summary_outline(info["source_type"])
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
    """把 LLM 抽取的 idea dict 格式化成 idea_suggestion 模板格式的块。"""
    slug = make_slug(it.get("title", "untitled")) or "untitled"
    iid = f"idea_suggestion_{today.replace('-', '')}_{slug}"
    src_summary = f"[[summary_{source_id}]]"
    return f"""
## Idea Suggestion: {it['title']}

- id: {iid}
- status: pending_review
- recommended_area: {it['recommended_area']}
- source_summary: {src_summary}
- priority: {it['priority']}
- feasibility: {it['feasibility']}
- novelty: {it['novelty']}
- estimated_investment: {it.get('estimated_investment', '')}

### 推荐理由

{it.get('reason', '')}

### 这个 idea 是什么

{it.get('what', '')}

### 主要难点

{it.get('challenges', '')}
"""


def _format_todo_suggestion(source_id: str, info: dict, it: dict, today: str) -> str:
    """把 LLM 抽取的 todo dict 格式化成 todo_suggestion 模板格式的块。"""
    slug = make_slug(it.get("title", "untitled")) or "untitled"
    tid = f"todo_suggestion_{today.replace('-', '')}_{slug}"
    src_summary = f"[[summary_{source_id}]]"
    return f"""
## Todo Suggestion: {it['title']}

- id: {tid}
- status: pending_review
- source_summary: {src_summary}
- recommended_plan: {it['recommended_plan']}
- priority: {it['priority']}
- estimated_time: {it.get('estimated_time', '2-4h')}
- difficulty: {it['difficulty']}

### 为什么值得做

{it.get('why', '')}

### 具体要做什么

{it.get('what', '')}

### 主要难点

{it.get('challenges', '')}

### 验收标准

{it.get('acceptance', '')}
"""


def _format_formal_idea(meta: dict, body: str, area: str) -> str:
    """把 accepted idea suggestion 转成正式 idea list 条目(idea_template 格式)。"""
    title = meta.get("title", meta.get("id", "untitled"))
    today = date.today().isoformat()
    slug = make_slug(title) or "untitled"
    iid = f"idea_{today.replace('-', '')}_{slug}"
    return f"""

## Idea: {title}

- id: {iid}
- status: candidate
- maturity: spark
- priority: {meta.get('priority', 'P2')}
- sources:
  - {meta.get('source_summary', '')}
- estimated_investment: {meta.get('estimated_investment', '')}
- main_challenges:
  - {meta.get('feasibility', '')} 可行性 / {meta.get('novelty', '')} 新颖度

{body or '（待补充）'}
"""


def _format_weekly_task(meta: dict, body: str) -> str:
    """把 accepted todo suggestion 转成 weekly/monthly task 格式(plan.md 11.1)。"""
    title = meta.get("title", meta.get("id", "untitled"))
    return f"""

- [ ] {title}
  - 来源:{meta.get('source_summary', '')}
  - 预计时间:{meta.get('estimated_time', '')}
  - 难度:{meta.get('difficulty', '')}
  - 难点:{meta.get('challenges', '') if 'challenges' in meta else '见 suggestion'}
"""


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

    print(
        f"[clean-x] 共 {len(files)} 个 X source,本次修改 {changed} 个;"
        f"正文 {total_before} -> {total_after}"
        f"(-{100 * (1 - total_after / total_before):.0f}%)"
        + (" [dry-run,未写入]" if dry else "")
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """启动知识库阅读前端(FastAPI)。

    浏览器访问 http://127.0.0.1:<port> 查看卡片仪表盘。
    """
    print(f"[serve] 启动知识库阅读前端...")
    print(f"[serve] vault = {VAULT_ROOT}")
    print(f"[serve] 监听 http://{args.host}:{args.port}")
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

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
