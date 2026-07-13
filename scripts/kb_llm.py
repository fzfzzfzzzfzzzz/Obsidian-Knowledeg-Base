#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
kb_llm.py —— 智谱 GLM API 封装(MVP Phase 0+1 的 LLM 扩展)

职责:
    1. 从 .env / 环境变量加载配置(api_key / model / base_url / timeout)
    2. 封装 OpenAI 兼容的 chat completions 调用(用 requests)
    3. extract_metadata_from_text():让 LLM 从自由文本识别
       {source_type, source_url, source_title, area, user_intent}

设计原则:
    - 不依赖官方 SDK,只用 requests(更可控、透明)
    - 所有错误抛 LLMAError,调用方负责降级处理
    - 密钥只从环境变量读,绝不打印
    - 调用结果(含 token 数)可记录到日志,便于成本审计
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

ENC = "utf-8"

# vault 根 = 本文件所在 scripts/ 的父目录
VAULT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = VAULT_ROOT / ".env"

# —— 智谱 GLM 默认配置 ——
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_MODEL = "glm-4-flash"
DEFAULT_TIMEOUT = 60


class LLMError(Exception):
    """LLM 调用相关错误的统一异常。"""


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def _parse_env_file(path: Path) -> dict[str, str]:
    """简易 .env 解析:KEY=VALUE,忽略注释和空行。不依赖 python-dotenv。"""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding=ENC).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # 去掉值两端的引号
        value = value.strip().strip('"').strip("'")
        result[key.strip()] = value
    return result


def load_config() -> dict[str, Any]:
    """加载配置:优先环境变量,其次 .env 文件,最后默认值。

    返回 dict 含:api_key, model, base_url, timeout, available(bool)
    """
    env = _parse_env_file(ENV_FILE)
    # 环境变量优先于 .env
    api_key = os.environ.get("ZHIPU_API_KEY") or env.get("ZHIPU_API_KEY", "")
    model = os.environ.get("KB_LLM_MODEL") or env.get("KB_LLM_MODEL", DEFAULT_MODEL)
    base_url = os.environ.get("KB_LLM_BASE_URL") or env.get(
        "KB_LLM_BASE_URL", DEFAULT_BASE_URL
    )
    timeout_raw = os.environ.get("KB_LLM_TIMEOUT") or env.get(
        "KB_LLM_TIMEOUT", str(DEFAULT_TIMEOUT)
    )
    try:
        timeout = int(timeout_raw)
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    return {
        "api_key": api_key.strip(),
        "model": model.strip(),
        "base_url": base_url.strip().rstrip("/") + "/",
        "timeout": timeout,
        "available": bool(api_key.strip()),
    }


# ---------------------------------------------------------------------------
# HTTP 调用
# ---------------------------------------------------------------------------


def _import_requests():
    """延迟导入 requests,缺失时给出清晰错误。"""
    try:
        import requests  # type: ignore

        return requests
    except ImportError as e:
        raise LLMError(
            "缺少 requests 库。请运行:  pip install -r requirements.txt"
        ) from e


# ---------------------------------------------------------------------------
# 网页抓取(URL → 正文文本,纯本地 requests,不消耗任何 MCP)
# ---------------------------------------------------------------------------

# 模拟浏览器的 UA,降低被简单反爬拒绝的概率
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 抓取正文的最大字数(glm-4.7-flash 200K 上下文,可容纳更长正文)
FETCH_MAX_CHARS = 50000


class _TextExtractor:
    """简易 HTML → 纯文本提取器。用标准库 html.parser,零依赖。

    策略:提取 <p> <li> <h1-3> <pre> <blockquote> 的文字,跳过
    <script> <style> <nav> <footer> <header> <aside> 等噪声标签。
    """

    def __init__(self) -> None:
        self.parts: list[str] = []
        self._skip_depth = 0
        self._in_keep = 0
        self._buf: list[str] = []
        self._parser_cls = _build_parser_class()

    def feed(self, html: str) -> str:
        p = self._parser_cls(self)
        p.feed(html)
        p.close()
        # 收尾:把残留 buf 也加进去
        if self._buf:
            chunk = "".join(self._buf).strip()
            if chunk:
                self.parts.append(chunk)
        text = " ".join(self.parts)
        text = re.sub(r"\s+", " ", text).strip()
        return text


_SKIP_TAGS_VALUE = {
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "noscript",
    "svg",
}
_KEEP_TAGS_VALUE = {"p", "li", "h1", "h2", "h3", "h4", "pre", "blockquote", "td"}


def _build_parser_class():
    """用标准库 html.parser 生成解析器类(延迟构建,避免顶层 import 问题)。"""
    from html.parser import HTMLParser

    class _P(HTMLParser):
        def __init__(self, owner: "_TextExtractor") -> None:
            super().__init__(convert_charrefs=True)
            self.owner = owner

        def handle_starttag(self, tag, attrs):
            tag = tag.lower()
            if tag in _SKIP_TAGS_VALUE:
                self.owner._skip_depth += 1
            elif tag in _KEEP_TAGS_VALUE:
                self.owner._in_keep += 1

        def handle_endtag(self, tag):
            tag = tag.lower()
            if tag in _SKIP_TAGS_VALUE and self.owner._skip_depth > 0:
                self.owner._skip_depth -= 1
            elif tag in _KEEP_TAGS_VALUE and self.owner._in_keep > 0:
                self.owner._in_keep -= 1
                # 块级标签结束,把缓冲追加到结果
                if self.owner._buf:
                    chunk = "".join(self.owner._buf).strip()
                    if chunk:
                        self.owner.parts.append(chunk)
                    self.owner._buf = []

        def handle_data(self, data):
            if self.owner._skip_depth > 0:
                return
            text = data.strip()
            if text:
                self.owner._buf.append(text)
                # 即使不在 keep 标签内,也收集(很多正文不在 <p> 里)
                if self.owner._in_keep == 0:
                    if len(self.owner.parts) == 0 or self.owner.parts[-1] != text:
                        self.owner.parts.append(text)

    return _P


def _html_to_text(html: str) -> str:
    """HTML 转纯文本(保留正文段落文字)。"""
    try:
        ext = _TextExtractor()
        return ext.feed(html)
    except Exception:
        # 解析失败时退化为粗暴去标签
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()


def fetch_url_text(url: str, *, timeout: int = 20) -> dict[str, str]:
    """抓取 URL 的网页正文。

    纯本地 HTTP 请求(requests),不消耗任何 MCP / 外部服务。
    微信公众号等需要登录的站点可能拿不到正文,调用方需处理返回的 text 为空的情况。

    返回:
        {
            "url": str,       # 实际请求的 URL(可能因重定向变化)
            "title": str,     # <title> 标签内容(可能为空)
            "text": str,      # 提取的正文纯文本(可能为空)
            "ok": bool,       # 是否成功抓到有意义正文
        }

    异常:
        LLMError: 网络/HTTP 错误
    """
    requests = _import_requests()
    try:
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise LLMError(f"抓取失败(网络错误): {e}")

    if resp.status_code >= 400:
        raise LLMError(f"抓取失败(HTTP {resp.status_code})")

    # 编码处理:优先 HTTP 头,其次网页 meta,最后 fallback
    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text

    # 提取 <title>
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()

    text = _html_to_text(html)
    # 截断,避免过长
    if len(text) > FETCH_MAX_CHARS:
        text = text[:FETCH_MAX_CHARS]

    return {
        "url": resp.url,
        "title": title,
        "text": text,
        "ok": bool(text and len(text) > 80),  # 太短视为没抓到正文
    }


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    retries: int = 1,
) -> dict[str, Any]:
    """调用 chat completions,返回标准化结果。

    参数:
        messages: OpenAI 格式 [{"role": "...", "content": "..."}]
        temperature: 采样温度,默认 0.3(识别任务偏确定性)
        max_tokens: 可选上限
        retries: 网络错误重试次数(默认 1 次)

    返回:
        {
            "content": str,          # 模型回复文本
            "model": str,            # 实际使用的模型
            "usage": {...} | None,   # token 用量(可能为空)
            "raw": dict,             # 原始响应 JSON
        }

    异常:
        LLMError: 配置缺失 / HTTP 错误 / 响应解析失败
    """
    cfg = load_config()
    if not cfg["available"]:
        raise LLMError(
            "未配置 API key。请复制 .env.example 为 .env 并填入 ZHIPU_API_KEY,"
            "或设置环境变量 ZHIPU_API_KEY。"
        )

    requests = _import_requests()

    url = cfg["base_url"] + "chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=cfg["timeout"]
            )
            # HTTP 错误统一处理
            if resp.status_code >= 400:
                # 尝试提取错误信息
                try:
                    err_body = resp.json()
                    msg = err_body.get("error", {}).get("message", "") or str(err_body)
                except (ValueError, json.JSONDecodeError):
                    msg = resp.text[:300]
                raise LLMError(
                    f"API 返回 HTTP {resp.status_code}: {msg}"
                )
            data = resp.json()
            content = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            return {
                "content": content,
                "model": data.get("model", cfg["model"]),
                "usage": data.get("usage"),
                "raw": data,
            }
        except LLMError:
            raise  # 业务错误不重试
        except Exception as e:  # 网络错误 / 超时
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))  # 简单退避
                continue
            raise LLMError(f"请求失败(重试 {retries} 次后仍出错): {e}") from e

    # 理论上不可达
    raise LLMError(f"请求失败: {last_err}")


# ---------------------------------------------------------------------------
# Metadata 提取(本阶段的核心 LLM 能力)
# ---------------------------------------------------------------------------

# 已知枚举值(必须与 kb.py 的 SOURCE_TYPES 等保持一致)
VALID_SOURCE_TYPES = ("github", "x", "wechat", "douyin", "gpt_chat", "web", "manual")
VALID_AREAS = (
    "research",
    "productivity",
    "product",
    "ai_agent",
    "web_design",
    "other",
)
VALID_INTENTS = ("summarize", "extract_idea", "evaluate_try", "archive_only")

METADATA_SYSTEM_PROMPT = """你是一个内容分类助手。用户会给你一段从网络/聊天/视频复制下来的文本,你需要识别它的元信息并严格输出 JSON。

只输出一个 JSON 对象,不要任何解释、不要 markdown 代码块标记。字段如下:

{
  "source_type": "github | x | wechat | douyin | gpt_chat | web | manual 之一",
  "source_url": "如果能从文本里识别出 URL 就填,否则留空字符串",
  "source_title": "为这段内容起一个简短中文标题(不超过 30 字)",
  "area": "research | productivity | product | ai_agent | web_design | other 之一",
  "user_intent": "summarize | extract_idea | evaluate_try | archive_only 之一"
}

判断规则:
- source_type: GitHub README/repo 链接 → github;X/Twitter 推文 → x;微信公众号文章 → wechat;抖音/短视频文案 → douyin;ChatGPT/GPT 对话记录 → gpt_chat;普通网页/技术博客 → web;无法判断或纯个人笔记 → manual。
- area: 科研/论文/算法 → research;效率工具/工作流 → productivity;产品想法 → product;AI agent 相关 → ai_agent;网页/前端设计 → web_design;其他 → other。
- user_intent: 看起来想深入了解/复现 → summarize;明显在找 idea 灵感 → extract_idea;在评估某个工具/repo 是否值得试 → evaluate_try;只是存档备查 → archive_only。无法判断时默认 summarize。
- source_title: 用中文概括核心主题,不要照搬原文首行。
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型回复里容错提取 JSON 对象。

    优先尝试整体解析;失败则找 ```json ... ``` 代码块;再失败找第一个 {...}。
    """
    text = text.strip()
    # 1. 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 2. ```json 块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 第一个 {...}(贪心到行尾的闭合)
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _clamp_enum(value: str, valid: tuple[str, ...], default: str) -> str:
    """把 LLM 输出的枚举值夹到合法集合里。"""
    v = (value or "").strip().lower()
    if v in valid:
        return v
    # 容错:gpt-chat / gptchat → gpt_chat
    v_norm = v.replace("-", "_").replace(" ", "")
    if v_norm in valid:
        return v_norm
    return default


def extract_metadata_from_text(text: str) -> dict[str, str]:
    """让 LLM 从自由文本识别 metadata。

    返回 dict: {source_type, source_url, source_title, area, user_intent}
    所有字段保证是字符串(可能为空),source_type 保证在 VALID_SOURCE_TYPES 内。

    异常:
        LLMError: 调用失败或输出无法解析
    """
    if not text.strip():
        raise LLMError("空文本,无法提取 metadata")

    result = chat(
        [
            {"role": "system", "content": METADATA_SYSTEM_PROMPT},
            {"role": "user", "content": text[:100000]},  # glm-4.7-flash 200K 上下文,安全上限 100K 字符
        ],
        temperature=0.1,  # 分类任务要确定性
        max_tokens=2000,  # 思考模型(glm-4.7-flash)需要更多空间思考
    )

    content = result["content"]
    obj = _extract_json(content)
    if obj is None:
        raise LLMError(f"LLM 输出无法解析为 JSON。原始回复前 200 字: {content[:200]}")

    return {
        "source_type": _clamp_enum(
            obj.get("source_type", ""), VALID_SOURCE_TYPES, "manual"
        ),
        "source_url": str(obj.get("source_url", "") or "").strip(),
        "source_title": str(obj.get("source_title", "") or "").strip(),
        "area": _clamp_enum(obj.get("area", ""), VALID_AREAS, "other"),
        "user_intent": _clamp_enum(
            obj.get("user_intent", ""), VALID_INTENTS, "summarize"
        ),
    }


def _extract_url(text: str) -> str:
    """从文本里找出第一个 http(s) URL,没有则返回空串。"""
    m = re.search(r"https?://[^\s<>\"']+", text)
    return m.group(0) if m else ""


def extract_metadata_smart(text: str) -> tuple[dict[str, str], dict[str, Any], str]:
    """智能 metadata 提取:URL-only 或正文过短时,先抓取网页正文再交给 LLM。

    流程:
        1. 如果文本里有 URL,且非 URL 正文部分很短(< 60 字),尝试抓取网页
        2. 抓取成功 → 把「抓到的正文 + 原 URL」交给 LLM 识别(质量高)
        3. 抓取失败 → 退回用原文本识别(可能泛化),并在返回的 fetch_info 里标注

    返回:
        (metadata_dict, fetch_info, enriched_text)
        - metadata_dict: 识别出的 metadata
        - fetch_info: 抓取统计(fetched/fetch_ok/fetch_error/fetched_title/fetched_chars)
        - enriched_text: 交给后续 summary 用的「富文本」。
          若抓取成功,是「原文本 + 抓到的正文」拼接;否则就是原文本。
          调用方应优先用 enriched_text 而非原始 text 去生成 summary。
    """
    fetch_info: dict[str, Any] = {
        "fetched": False,
        "fetch_ok": False,
        "fetch_error": "",
        "fetched_title": "",
        "fetched_chars": 0,
    }

    if not text.strip():
        raise LLMError("空文本,无法提取 metadata")

    url = _extract_url(text)
    # 去掉 URL 后剩余的正文
    non_url_text = re.sub(r"https?://[^\s<>\"']+", "", text).strip()

    # 触发抓取条件:有 URL 且正文很短(URL-only 场景)
    if url and len(non_url_text) < 60:
        fetch_info["fetched"] = True
        try:
            page = fetch_url_text(url)
            fetch_info["fetch_ok"] = page["ok"]
            fetch_info["fetched_title"] = page["title"]
            fetch_info["fetched_chars"] = len(page["text"])
            if page["ok"]:
                enriched = (
                    f"URL: {url}\n标题: {page['title']}\n\n正文:\n{page['text']}"
                )
                # 把抓到的正文交给 LLM 识别 metadata
                meta = extract_metadata_from_text(enriched)
                # 确保用真实 URL,不让 LLM 乱改
                meta["source_url"] = url
                # 如果 LLM 没给标题,用网页 title
                if not meta["source_title"] and page["title"]:
                    meta["source_title"] = page["title"]
                return meta, fetch_info, enriched
            else:
                fetch_info["fetch_error"] = "抓到内容过短或为空"
        except LLMError as e:
            fetch_info["fetch_error"] = str(e)
        # 抓取失败,退回用原文本

    # 普通路径:直接用原文本识别
    meta = extract_metadata_from_text(text)
    return meta, fetch_info, text


# ---------------------------------------------------------------------------
# Phase 2: Summary 生成
# ---------------------------------------------------------------------------

# source_type → 对应 summary 模板的章节骨架(用于约束 LLM 输出结构)
# 取自 90_Templates/summary_*.md,这里硬编码副本避免运行时读文件
_SUMMARY_OUTLINES: dict[str, str] = {
    "github": (
        "# 一句话结论\n\n# 这个 repo 是什么\n\n# 它解决的问题\n\n# 核心功能\n\n"
        "# 技术路线 / 架构\n\n# 安装与运行难度\n\n# 依赖条件\n\n"
        "# 和我当前项目的关系\n\n# 值得尝试的地方\n\n# 风险 / 局限"
    ),
    "web": (
        "# 一句话结论\n\n# 文章主要讲什么\n\n# 背景问题\n\n# 核心观点\n\n"
        "# 方法 / 框架 / 实现路径"
    ),
    "douyin": (
        "# 一句话结论\n\n# 视频内容概括\n\n# 关键信息点\n\n"
        "# 展示的工具 / 方法 / 项目\n\n# 是否值得进一步验证"
    ),
    "gpt_chat": (
        "# 一句话结论\n\n# 这段对话讨论了什么\n\n# 已经形成的结论\n\n"
        "# 仍然不确定的问题\n\n# 可以沉淀为长期知识的内容\n\n"
        "# 需要后续追问 / 验证的地方"
    ),
    "wechat": (
        "# 一句话结论\n\n# 文章主要讲什么\n\n# 核心观点\n\n# 方法 / 框架 / 实现路径"
    ),
    "manual": (
        "# 一句话结论\n\n# 主要内容"
    ),
}

SUMMARY_SYSTEM_PROMPT = """你是一个技术内容整理助手。用户会给你一段资料原文,你需要按指定的章节结构输出一份详细的结构化中文笔记(不是抽象概括)。

核心原则 —— 尽量保留原文的有用信息:
1. 严格按照给出的章节标题顺序输出,每个标题用 markdown # 一级标题。
2. 「一句话结论」必须是 1 句话,点明这个东西/文章的核心价值。
3. 保留原文的关键事实、数据、项目名、步骤、论据、定义、对比、原文措辞中的要点。不要压缩成抽象概括,不要用「介绍了几个工具」「讲了若干方法」这种空话。
4. 列举类内容(多个项目 / 步骤 / 特性 / 配置项 / 命令)要逐项保留,带上原文给出的具体数据(star 数、版本号、参数、链接、价格、性能指标等)。
5. 每个章节用充实的段落或要点列表,而不是一句话带过。如果原文某个方面信息丰富,就多写一些。
6. 只过滤以下内容:广告、网站导航、页脚版权、重复出现的段落、与主题明显无关的闲聊。
7. 不要瞎编原文没有的内容。如果某个章节原文没涉及,就明确写「原文未涉及」,不要编。
8. 全程用中文(原文的专有名词/代码/命令可保留英文),客观、克制,不要营销腔。
9. 链接必须完整保留:原文里出现的所有 URL(github / 官网 / 文档 / 论文 / 参考资料 等)都要原样写进 summary,用 markdown 链接语法 [文字](完整URL)。绝对不要用「...」「…」省略链接,不要写「github.com/xxx/yyy…」这种残缺形式,必须是完整的 https:// 开头的 URL。如果链接很多,集中放到相关章节或单列一个「相关链接」要点。
"""


def _summary_outline(source_type: str) -> str:
    """根据 source_type 取 summary 章节骨架,未知类型用 manual。"""
    return _SUMMARY_OUTLINES.get(source_type, _SUMMARY_OUTLINES["manual"])


def generate_summary(source_text: str, source_type: str) -> str:
    """让 LLM 按 summary 模板生成结构化总结。

    参数:
        source_text: 资料正文(可以是抓取到的网页正文 / GPT 对话 / README 等)
        source_type: 决定用哪个 summary 章节骨架

    返回:
        summary 的 Markdown 正文(不含 frontmatter,调用方自行包装)

    异常:
        LLMError: 调用失败
    """
    if not source_text.strip():
        raise LLMError("空文本,无法生成 summary")

    outline = _summary_outline(source_type)
    user_msg = (
        f"资料类型: {source_type}\n\n"
        f"请按下面的章节结构总结(标题必须完全一致,顺序不变):\n\n{outline}\n\n"
        f"--- 资料原文 ---\n{source_text[:100000]}"  # glm-4.7-flash 200K 上下文,安全上限 100K 字符
    )
    result = chat(
        [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=4000,
    )
    return result["content"].strip()


# ---------------------------------------------------------------------------
# Idea / Todo 抽取(从 summary 提炼候选)
# ---------------------------------------------------------------------------

IDEA_EXTRACT_SYSTEM_PROMPT = """你是一个研究/产品想法提炼助手。用户给你一份内容总结,你要从中提炼出值得长期跟进的 idea 候选。

只输出一个 JSON 数组(不要任何解释、不要 markdown 代码块标记),数组每个元素是一个对象,字段如下:

[
  {
    "title": "idea 的简短中文标题(不超过 25 字)",
    "recommended_area": "research | productivity | product | ai_agent | web_design | other 之一",
    "priority": "P0 | P1 | P2 | P3 之一",
    "feasibility": "high | medium | low 之一",
    "novelty": "high | medium | low 之一",
    "estimated_investment": "预估投入,例如 3-5 days / 1 周 / 2h",
    "reason": "为什么值得做(1-2 句)",
    "what": "这个 idea 具体是什么(1-2 句)",
    "challenges": "主要难点(1 句)"
  }
]

规则:
- 只提炼真正有价值的 idea,宁缺毋滥。如果总结里没有可转化的 idea,返回空数组 []。
- 不要编造总结里没有的内容。
- 优先提炼和 AI agent、本地工具、效率提升相关的 idea。
"""

TODO_EXTRACT_SYSTEM_PROMPT = """你是一个行动项提炼助手。用户给你一份内容总结,你要从中提炼出具体可执行的 todo 候选。

只输出一个 JSON 数组(不要任何解释、不要 markdown 代码块标记),数组每个元素是一个对象,字段如下:

[
  {
    "title": "todo 的简短中文标题(不超过 25 字)",
    "recommended_plan": "weekly | monthly | someday 之一",
    "priority": "P0 | P1 | P2 | P3 之一",
    "estimated_time": "预估时间,例如 30min / 1h / 2-4h / 半天 / 1-2 天",
    "difficulty": "low | medium | high 之一",
    "why": "为什么值得做(1 句)",
    "what": "具体要做什么(1-2 句)",
    "challenges": "主要难点(1 句)",
    "acceptance": "验收标准(1 句)"
  }
]

规则:
- 每个 todo 必须是具体可执行的动作(读文档、跑 demo、写脚本、做对比实验),不是抽象方向。
- 必须给出合理的 estimated_time 和 difficulty,不要全部填 low / 30min。
- 宁缺毋滥。如果总结里没有可转化的 todo,返回空数组 []。
- 不要编造总结里没有的内容。
"""


def _extract_json_list(text: str) -> list[dict[str, Any]]:
    """从模型回复里容错提取 JSON 数组。"""
    text = text.strip()
    # 1. 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    # 2. ```json 块
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    # 3. 第一个 [...] (非贪心,但要平衡简单嵌套)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []


def extract_ideas_from_summary(summary_text: str) -> list[dict[str, str]]:
    """从 summary 提炼 idea 候选。

    返回 list[dict],每个 dict 字段均为字符串:
        title, recommended_area, priority, feasibility, novelty,
        estimated_investment, reason, what, challenges
    字段名统一(不带前缀),调用方负责包装成模板格式。

    异常:
        LLMError: 调用失败或输出无法解析
    """
    if not summary_text.strip():
        raise LLMError("空 summary,无法抽取 idea")

    result = chat(
        [
            {"role": "system", "content": IDEA_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": summary_text[:50000]},  # glm-4.7-flash 200K 上下文,安全上限
        ],
        temperature=0.3,
        max_tokens=3000,
    )
    items = _extract_json_list(result["content"])
    if items is None:
        raise LLMError(
            f"LLM 输出无法解析为 JSON 数组。原始回复前 200 字: {result['content'][:200]}"
        )

    cleaned: list[dict[str, str]] = []
    for it in items:
        cleaned.append(
            {
                "title": str(it.get("title", "")).strip(),
                "recommended_area": _clamp_enum(
                    it.get("recommended_area", ""), VALID_AREAS, "other"
                ),
                "priority": _clamp_enum(
                    it.get("priority", ""), ("P0", "P1", "P2", "P3"), "P2"
                ),
                "feasibility": _clamp_enum(
                    it.get("feasibility", ""), ("high", "medium", "low"), "medium"
                ),
                "novelty": _clamp_enum(
                    it.get("novelty", ""), ("high", "medium", "low"), "medium"
                ),
                "estimated_investment": str(it.get("estimated_investment", "")).strip(),
                "reason": str(it.get("reason", "")).strip(),
                "what": str(it.get("what", "")).strip(),
                "challenges": str(it.get("challenges", "")).strip(),
            }
        )
    # 过滤掉没标题的
    return [c for c in cleaned if c["title"]]


def extract_todos_from_summary(summary_text: str) -> list[dict[str, str]]:
    """从 summary 提炼 todo 候选。

    返回 list[dict],字段均为字符串:
        title, recommended_plan, priority, estimated_time, difficulty,
        why, what, challenges, acceptance
    """
    if not summary_text.strip():
        raise LLMError("空 summary,无法抽取 todo")

    result = chat(
        [
            {"role": "system", "content": TODO_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": summary_text[:50000]},  # glm-4.7-flash 200K 上下文,安全上限
        ],
        temperature=0.3,
        max_tokens=3000,
    )
    items = _extract_json_list(result["content"])
    if items is None:
        raise LLMError(
            f"LLM 输出无法解析为 JSON 数组。原始回复前 200 字: {result['content'][:200]}"
        )

    cleaned: list[dict[str, str]] = []
    for it in items:
        cleaned.append(
            {
                "title": str(it.get("title", "")).strip(),
                "recommended_plan": _clamp_enum(
                    it.get("recommended_plan", ""),
                    ("weekly", "monthly", "someday"),
                    "someday",
                ),
                "priority": _clamp_enum(
                    it.get("priority", ""), ("P0", "P1", "P2", "P3"), "P2"
                ),
                "estimated_time": str(it.get("estimated_time", "")).strip()
                or "2-4h",
                "difficulty": _clamp_enum(
                    it.get("difficulty", ""), ("low", "medium", "high"), "medium"
                ),
                "why": str(it.get("why", "")).strip(),
                "what": str(it.get("what", "")).strip(),
                "challenges": str(it.get("challenges", "")).strip(),
                "acceptance": str(it.get("acceptance", "")).strip(),
            }
        )
    return [c for c in cleaned if c["title"]]


# ---------------------------------------------------------------------------
# AI 推荐标签
# ---------------------------------------------------------------------------

TAG_RECOMMEND_SYSTEM_PROMPT = """你是一个内容标签生成助手。用户会给你一篇文章的 summary,你需要基于内容生成 3-5 个主题标签。

只输出一个 JSON 数组(不要任何解释、不要 markdown 代码块标记),例如:
["agent", "benchmark", "tool-use"]

规则:
- 生成 3-5 个标签,不要过多。
- 标签用中英文均可,优先用英文(技术术语)。
- 标签要具体(如 "agent" "benchmark" "tool-use" "prompt-compression"),不要泛泛的(如 "AI" "技术")。
- 基于 summary 内容生成,不要瞎编。
- 每个标签是一个不带引号的纯字符串。
"""


def recommend_tags_from_summary(summary_text: str) -> list[str]:
    """让 LLM 基于 summary 生成 3-5 个标签。

    返回 list[str]。失败抛 LLMError。
    """
    if not summary_text.strip():
        raise LLMError("空 summary,无法推荐标签")

    result = chat(
        [
            {"role": "system", "content": TAG_RECOMMEND_SYSTEM_PROMPT},
            {"role": "user", "content": summary_text[:50000]},
        ],
        temperature=0.3,
        max_tokens=3000,
    )
    # 自己解析 JSON 数组(不能用 _extract_json_list,它只保留 dict 元素,会过滤掉纯字符串标签)
    content = result["content"].strip()
    tags: list[str] = []
    try:
        obj = json.loads(content)
        if isinstance(obj, list):
            for it in obj:
                if isinstance(it, str):
                    tags.append(it.strip())
                elif isinstance(it, dict):
                    t = it.get("tag") or it.get("name") or it.get("label") or ""
                    if t:
                        tags.append(str(t).strip())
    except json.JSONDecodeError:
        # 尝试提取 ```json 块
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, list):
                    for it in obj:
                        if isinstance(it, str):
                            tags.append(it.strip())
            except json.JSONDecodeError:
                pass
    return [t for t in tags if t][:5]
