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
        # X 登录态(抓 X Article 长文用;从浏览器开发者工具复制 cookie)。
        # auth_token 是登录主凭证,ct0 是 CSRF token(两者都在 x.com 的 cookie 里)。
        "x_auth_token": (os.environ.get("X_AUTH_TOKEN") or env.get("X_AUTH_TOKEN", "")).strip(),
        "x_ct0": (os.environ.get("X_CT0") or env.get("X_CT0", "")).strip(),
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
            if not text:
                return
            if self.owner._in_keep > 0:
                # 在 keep 标签(p/li/h/pre/blockquote/td)内:暂存到 _buf,
                # 等 endtag 时 flush 到 parts(保持块级边界)
                self.owner._buf.append(text)
            else:
                # 非 keep 标签(裸 div/span 等):直接进 parts,不暂存 _buf
                # (避免收尾时 _buf 残留导致重复输出)
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


# ---------------------------------------------------------------------------
# X / Twitter 粘贴正文清洗
# ---------------------------------------------------------------------------
# 用户从 X 网页复制推文时,会把站点导航/交互数据/页脚噪声一起粘进来,且
# 同一条推文会出现两遍(<title> 渲染版 + 正文渲染版)。这里做确定性清洗,
# 不调 LLM,只去站点噪声和重复段,保留推文正文与引用评论楼层。
#
# 实测噪声结构(见 01_Sources/x/ 下样本):
#   1. 重复:`XX on X: "..." / X  XX on X: "..." / X` + `Post Log in Sign up...`
#      + `XX @handle 正文...(正文渲染版)` —— 正文版信息更全,保留它
#   2. 导航:`Post Log in Sign up Log inSign upPost`
#   3. 时间戳:`22:40 · 2026年6月28日`
#   4. 交互数据:`14.5万 Views`、`Read 8 replies`、`Show more`、纯数字计数串
#   5. 页脚:`Don't miss what's happening ... Trending now`(结尾固定)


def _strip_x_noise(text: str) -> str:
    """对单段 X 文本做正则去噪(内部用)。"""
    # HTML 实体(X 的 title 经 HTML 转义,&quot; 很常见)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")

    # 页脚固定块(贪心匹配到结尾)——先删,避免它干扰后续判断
    text = re.sub(
        r"Don't miss what's happening.*?Trending now",
        " ",
        text,
        flags=re.DOTALL,
    )
    # 结尾常残留的孤立导航
    text = re.sub(r"Log ?in\s*Sign ?up.*$", " ", text, flags=re.DOTALL)

    # 导航噪声
    text = re.sub(r"Post\s*Log ?in\s*Sign ?up\s*(Log ?in\s*Sign ?up\s*)?Post", " ", text)
    text = re.sub(r"Log ?inSign ?up", " ", text)

    # 时间戳:`22:40 · 2026年6月28日` / `13:02 · 2026年6月29日` / `17:09 · 2026 ...`(压缩版年份后可能断开)
    # 前缀用 (?<![\d:]) 避免匹配时间片段里的小时,也兼容粘连到字母后的情形(com14:48)
    text = re.sub(r"(?<![\d:])\d{1,2}:\d{2}\s*[·•・]?\s*\d{4}(?:年[-]?\s*\d{1,2}(?:月\d{1,2}日?)?)?", " ", text)
    # 时间戳粘连(如 `Show more13:02 · 2026年6月29日` 残留)
    text = re.sub(r"(?<![\d:])\d{1,2}:\d{2}\s*[·•・]?\s*\d{4}年\d+月\d+日", " ", text)
    # 残留的中文月日碎片:`月28日`、`月15日`、以及单独的 `年7` 这种被切断的年份碎片
    text = re.sub(r"月\d{1,2}日", " ", text)
    text = re.sub(r"年\d{1,2}(?!月|日)", " ", text)

    # 交互数据
    text = re.sub(r"\d+(?:\.\d+)?万?\s*Views", " ", text)
    text = re.sub(r"Read\s+\d+\s+repl(?:y|ies)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bShow more\b", " ", text, flags=re.IGNORECASE)
    # 中文互动计数:`557070702811281281557557` 这种粘连数字串
    text = re.sub(r"\b\d{10,}\b", " ", text)
    # 粘连的大数字+K/M 计数(如 `353587872.3K`)
    text = re.sub(r"\b\d{6,}(?:\.\d+)?[KMkm]\b", " ", text)
    # 互动计数串:连续被空格分隔的短数字/带 K.M 后缀的计数(评论/转发/点赞/收藏)
    # 形如 `5 7 0 70 2 8 1 281` / `6 . 4 K 6.4K` / `8 6 9 69 3 1 5 315 3 9 399`
    text = re.sub(r"(?:\b\d+(?:\.\d+)?[KMkm]?\b\s*\.?\s*){4,}", " ", text)

    return text


def clean_x_text(text: str) -> str:
    """清洗 X 推文正文(用户粘贴 / 系统抓取两种来源),去站点噪声与重复段,保留正文和引用评论。

    X 文本的重复结构(来源不同,份数不同):
      - 用户粘贴:通常 2 份 —— title 版(`XX on X: "..." / X`)+ 正文版(`@handle 正文`)
      - 系统抓取:通常 3 份 —— title 版 + 正文版 + 压缩版(`名字@handle正文` 无空格)
      正文版信息最全(带空格、@handle、楼层),保留它;其余重复份去掉。

    算法(保守,只删重复/噪声,不删正文):
        1. 提取可选的 `URL:/标题:/正文:` 头部(ingest 拼的),清洗后拼回。
        2. 定位「正文版」:第一个形如 `@handle `(带空格)的位置,丢弃它之前的 title 段。
           若无此特征(如纯 title),保留原文。
        3. 正则去导航 / 时间戳 / 交互数据 / 页脚。
        4. 去压缩版重复:按 @handle 分段,用去空白指纹比对,删掉是已保留段子串的重复段。
        5. 折叠多余空白。

    幂等:对已清洗文本再跑一次,结果不变。
    """
    if not text or not text.strip():
        return text

    body = text

    # —— 1. 提取可选 header ——
    header = ""
    m_head = re.match(r"(URL:\s*\S+\s*\n标题:[^\n]*\n*\n正文:\s*)", body)
    if m_head:
        header = m_head.group(1)
        body = body[m_head.end():]

    # —— 2. 定位正文版,丢弃前导 title 段 ——
    # 正文版特征:`@handle ` 后接空格(title 版是 `XX on X:`,压缩版是 `名字@handle` 无空格)。
    # 找第一个 `@handle `(@ 后词字符 + 紧跟空格),它标记正文版起点。
    body = _drop_x_title_prefix(body)

    # —— 3. 去站点噪声 ——
    body = _strip_x_noise(body)

    # —— 4. 去压缩版/重复段 ——
    body = _dedupe_x_segments(body)

    # —— 5. 折叠空白 ——
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.strip()

    return (header + body) if header else body


def _drop_x_title_prefix(body: str) -> str:
    """丢弃正文版之前的 title 段(`XX on X: "..." / X ... Post Log in...`)。

    正文版的可靠特征:出现 `@handle`(词字符)且其后紧跟空格(title 版里的 @ 在引号内、
    无此空格;压缩版的 @ 前紧贴名字、@ 后无空格)。定位第一个这样的 @handle,截取其后。
    若找不到(纯 title 或已清洗),原样返回。
    """
    # @handle 后紧跟空格 = 正文版锚点。允许多种 handle 字符。
    m = re.search(r"@([A-Za-z0-9_]{2,})\s", body)
    if not m:
        return body
    # 只在 @handle 前面确实存在 title 段特征时才截取,避免误删正文开头
    prefix = body[: m.start()]
    if "on X:" in prefix or "/ X" in prefix or "Post" in prefix or "Log in" in prefix:
        return body[m.start():]
    return body


def _dedupe_x_segments(text: str) -> str:
    """去掉 X 的重复段(压缩版 / 多份渲染)。

    X 页面会把同一条推文渲染多份,其中一份是「正文版」(带空格、最完整),其余是
    压缩版或 title 残留。按 @handle 把文本切段,对每段算去空白指纹;若某段指纹是
    已保留段指纹的子串(或反过来),判为重复,删除。第一段总是保留。
    """
    # 按 @handle 切段(连同其前面的「名字」一起归入该段,避免名字碎片)
    # 用 finditer 找所有 @handle 位置,在每两个 @handle 之间断开
    at_positions = [m.start() for m in re.finditer(r"@[A-Za-z0-9_]{2,}", text)]
    if len(at_positions) < 2:
        return text  # 只有一段(或没有),无需去重

    # 切段:第一段 = 开头到第二个 @handle 前;之后每段从一个 @handle 到下一个
    segments = []
    # 第一个 @handle 之前若有内容,并入第一段
    first_at = at_positions[0]
    segments.append(text[:at_positions[1]])  # 含两个 @handle 之间的部分作为第一段
    for i in range(1, len(at_positions)):
        end = at_positions[i + 1] if i + 1 < len(at_positions) else len(text)
        segments.append(text[at_positions[i]:end])

    def fp(s: str) -> str:
        return re.sub(r"\s+", "", s)

    kept = [segments[0]]
    kept_fps = [fp(segments[0])]
    for seg in segments[1:]:
        f = fp(seg)
        if len(f) < 8:
            # 太短的名字碎片:若它紧贴前一段(去空白后是前段尾缀),跳过
            if any(kf.endswith(f) or f in kf[-len(f) * 2:] for kf in kept_fps if kf):
                continue
            kept.append(seg)
            kept_fps.append(f)
            continue
        # 是已保留任一段的子串,或已保留段是它的子串 → 重复
        is_dup = any(f in kf or kf in f for kf in kept_fps)
        if not is_dup:
            kept.append(seg)
            kept_fps.append(f)
    return "".join(kept)


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
    # X / Twitter 页面 HTML 会把同一条推文在 <title>、<noscript>、JSON-LD 等多处
    # 重复渲染,且带站点导航/交互数据噪声。在抓取源头就清洗掉,保证 enriched text、
    # raw_text、source note 全是干净的(只对 X URL 生效,不影响 web/wechat/github)。
    # 先从原始 HTML 提取 t.co 短链(清洗后的 text 会丢掉 a 标签里的链接),
    # 供「纯链接推文」场景跟踪外部正文用。
    tco_links: list[str] = []
    if _is_x_url(url) or _is_x_url(resp.url):
        for sl in re.findall(r"https?://t\.co/[A-Za-z0-9]+", html):
            if sl not in tco_links:
                tco_links.append(sl)
        text = clean_x_text(text)
    # 截断,避免过长
    if len(text) > FETCH_MAX_CHARS:
        text = text[:FETCH_MAX_CHARS]

    return {
        "url": resp.url,
        "title": title,
        "text": text,
        "ok": bool(text and len(text) > 80),  # 太短视为没抓到正文
        "tco_links": tco_links,
    }


def _is_x_url(url: str) -> bool:
    """判断 URL 是否为 X / Twitter(X 需登录但公开推文可抓,且页面有固定重复结构)。"""
    if not url:
        return False
    u = url.lower()
    return "://x.com/" in u or "://twitter.com/" in u or "://www.x.com/" in u or "://www.twitter.com/" in u


# ---------------------------------------------------------------------------
# Playwright 兜底抓取(requests 拿不到足够正文时降级用浏览器渲染 JS)
# ---------------------------------------------------------------------------
# 单例化:浏览器启动开销大(秒级),复用同一个 browser/context,避免每次抓取都重启。
# 进程结束时由 atexit 关闭。首次调用时 lazy init。
_PW_PLAYWRIGHT = None  # sync_playwright().start() 返回的上下文
_PW_BROWSER = None     # Browser 实例


def _get_pw_browser():
    """惰性初始化并复用 playwright 的 browser 实例。返回 (playwright_ctx, browser)。
    未安装 playwright 时抛 LLMError,调用方负责降级。"""
    global _PW_PLAYWRIGHT, _PW_BROWSER
    if _PW_BROWSER is not None:
        return _PW_PLAYWRIGHT, _PW_BROWSER
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as e:
        raise LLMError(
            "playwright 未安装。运行: pip install playwright && playwright install chromium"
        ) from e
    _PW_PLAYWRIGHT = sync_playwright().start()
    _PW_BROWSER = _PW_PLAYWRIGHT.chromium.launch(headless=True)
    return _PW_PLAYWRIGHT, _PW_BROWSER


import atexit as _atexit


def _close_pw():
    global _PW_PLAYWRIGHT, _PW_BROWSER
    try:
        if _PW_BROWSER:
            _PW_BROWSER.close()
        if _PW_PLAYWRIGHT:
            _PW_PLAYWRIGHT.stop()
    except Exception:
        pass
    _PW_BROWSER = None
    _PW_PLAYWRIGHT = None


_atexit.register(_close_pw)


def fetch_url_playwright(url: str, *, timeout: int = 30) -> dict[str, str]:
    """用 playwright(headless chromium)抓取 URL,等 JS 渲染后取正文。

    用于 requests 抓不到足够正文(JS 渲染站点)的兜底。复用单例 browser,
    每次 new_context + new_page(隔离 cookie/状态,避免串扰)。

    返回格式同 fetch_url_text。失败抛 LLMError,调用方负责回退。
    """
    _, browser = _get_pw_browser()
    context = browser.new_context(
        user_agent=_FETCH_HEADERS["User-Agent"],
        locale="zh-CN",
    )
    # X 登录态注入(抓 X Article 长文必须登录):若配了 cookie 且是 X URL,注入。
    cfg = load_config()
    if (_is_x_url(url)) and cfg.get("x_auth_token"):
        cookies = [
            {"name": "auth_token", "value": cfg["x_auth_token"],
             "domain": ".x.com", "path": "/"},
            {"name": "ct0", "value": cfg["x_ct0"], "domain": ".x.com", "path": "/"},
        ]
        try:
            context.add_cookies(cookies)
        except Exception:
            pass
    page = context.new_page()
    try:
        # X 带登录态时,直接深链访问 article 会被反爬拦("Something went wrong")。
        # 先访问 home 暖会话(激活 cookie / 建立 CSRF 上下文),再 goto 目标。
        if _is_x_url(url) and cfg.get("x_auth_token"):
            try:
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1500)
            except Exception:
                pass
        # 用 domcontentloaded 而非 networkidle:X/微信等站点有持续网络活动,
        # networkidle 会一直等不到而超时。DOM 就绪后短暂等待让 JS 渲染正文。
        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        try:
            page.wait_for_timeout(2500)  # 给 JS 渲染/懒加载时间
        except Exception:
            pass
        html = page.content()
        final_url = page.url
        title = page.title() or ""
    finally:
        context.close()

    text = _html_to_text(html)
    tco_links: list[str] = []
    if _is_x_url(url) or _is_x_url(final_url):
        for sl in re.findall(r"https?://t\.co/[A-Za-z0-9]+", html):
            if sl not in tco_links:
                tco_links.append(sl)
        text = clean_x_text(text)
    if len(text) > FETCH_MAX_CHARS:
        text = text[:FETCH_MAX_CHARS]
    return {
        "url": final_url,
        "title": title,
        "text": text,
        "ok": bool(text and len(text) > 80),
        "tco_links": tco_links,
    }


def _is_likely_preview(text: str) -> bool:
    """判断抓到的正文是否疑似「预览/截断」(不够完整,值得降级或跟踪短链)。

    信号:1) 过短;2) 以省略号/截断符结尾(X 的 line-clamp 预览常以 ... 结尾)。
    """
    if not text:
        return True
    t = text.strip()
    if len(t) < 200:
        return True
    # 结尾是省略号(中英文)或被截断的 t.co 残留
    if t.endswith(("...", "…", "… ", ". . .")) or re.search(r"https?://t\.co/\S*$", t):
        return True
    return False


def _resolve_tco_and_fetch(tco_links: list[str]) -> dict[str, str] | None:
    """对 t.co 短链解析重定向目标,抓取真实外部正文。

    用于「纯链接推文」(推文正文就是个链接):X 页面只显示链接卡片预览,
    真正的正文在 t.co 跳转后的目标。返回抓取结果,无有效目标/抓失败返回 None。

    t.co 常用 JS 重定向(location.replace),requests 跟不上;但响应 body 的
    <noscript>/<title> 里暴露了真实目标,这里 GET 后正则解析。
    目标可能是外部文章(直接抓),也可能是 X Article(x.com/i/article/,需登录,
    会递归走 fetch_url_with_fallback → playwright 带 cookie)。
    """
    requests = _import_requests()
    for sl in tco_links:
        try:
            # GET 而非 HEAD:t.co 常用 JS 跳转,HEAD 拿不到目标;GET body 里有真实 URL
            r = requests.get(sl, headers=_FETCH_HEADERS, timeout=15, allow_redirects=True)
            target = r.url
            if "t.co" in target:
                # 没发生 HTTP 重定向(JS 跳转),从 body 解析真实目标
                body = r.text or ""
                m = re.search(
                    r"https?://[^\s\"'<>]+/(?:i/article/|statuses/|status/)?[^\s\"'<>]*",
                    body,
                )
                # 优先匹配 noscript meta refresh / title 里的 URL
                m2 = re.search(r"(?:URL=|<title>)(https?://[^\s\"'<>]+)", body)
                target = (m2.group(1) if m2 else (m.group(0) if m else target))
            if target and "t.co" not in target:
                # 递归抓(外部站走 requests/playwright;X Article 走带 cookie 的 playwright)
                return fetch_url_with_fallback(target)
        except Exception:
            continue
    return None


def _is_x_article_url(url: str) -> bool:
    """X Article 长文 URL(x.com/i/article/... 或 x.com/<user>/article/...)。
    这类 URL 强制登录,requests 抓不到(还会触发反爬污染后续 playwright),
    必须直接用带 cookie 的 playwright。"""
    if not url:
        return False
    u = url.lower()
    return ("/i/article/" in u) or ("/article/" in u and ("x.com" in u or "twitter.com" in u))


def fetch_url_with_fallback(url: str, *, timeout: int = 20) -> dict[str, str]:
    """抓取统一入口:requests 为主,正文不够时依次尝试 ① t.co 跟踪 ② playwright。

    判定「正文够不够」见 _is_likely_preview。返回值同 fetch_url_text,
    额外字段 fetched_via(“requests”/“tco”/“playwright”)记录实际用的路径。

    例外:X Article URL 强制登录,跳过 requests 直接用带 cookie 的 playwright
    (requests 抓会触发反爬,污染后续 playwright 请求)。
    """
    # 0. X Article → 直接 playwright(带 cookie),不走 requests
    if _is_x_article_url(url):
        try:
            pw_page = fetch_url_playwright(url, timeout=30)
            if pw_page["ok"]:
                pw_page["fetched_via"] = "playwright"
                return pw_page
        except LLMError:
            pass  # playwright 失败则继续走下面的常规流程

    # 1. requests 抓
    try:
        page = fetch_url_text(url, timeout=timeout)
    except LLMError:
        page = {"url": url, "title": "", "text": "", "ok": False}

    if page["ok"] and not _is_likely_preview(page["text"]):
        page["fetched_via"] = "requests"
        return page

    # 2. requests 不够 → 纯链接推文?尝试 t.co 跟踪外部文章
    if _is_x_url(url):
        try:
            tco_page = _resolve_tco_and_fetch(page.get("tco_links") or [])
            if tco_page and tco_page.get("ok") and not _is_likely_preview(tco_page["text"]):
                tco_page["fetched_via"] = "tco"
                return tco_page
        except Exception:
            pass

    # 3. 仍不够 → playwright 兜底(渲染 JS)
    try:
        pw_page = fetch_url_playwright(url, timeout=30)
        # playwright 比 requests 好(更长/非预览)才用它,否则保留 requests 的结果
        if pw_page["ok"] and len(pw_page["text"]) > len(page["text"]) + 50:
            pw_page["fetched_via"] = "playwright"
            return pw_page
    except LLMError:
        pass  # playwright 不可用,回退

    # 4. 都不行,返回 requests 的结果(可能是预览,但总比空好)
    page["fetched_via"] = "requests"
    return page


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    retries: int = 1,
    thinking: str = "disabled",
) -> dict[str, Any]:
    """调用 chat completions,返回标准化结果。

    参数:
        messages: OpenAI 格式 [{"role": "...", "content": "..."}]
        temperature: 采样温度,默认 0.3(识别任务偏确定性)
        max_tokens: 可选上限
        retries: 网络错误重试次数(默认 1 次)
        thinking: 思考模式开关。默认 "disabled"(关闭思考)。
            GLM-4.7-flash 是思考模型,默认关掉以:省 token、加速、避免思考
            把 max_tokens 吃光导致输出空内容。可选 "enabled" 开启思考。
            仅对支持 thinking 参数的 GLM 模型生效,旧模型忽略此字段。

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
        "thinking": {"type": thinking},
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
            page = fetch_url_with_fallback(url)
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
        "# 值得尝试的地方\n\n# 风险 / 局限"
    ),
    "web": (
        "# 一句话结论\n\n# 文章主要讲什么\n\n# 背景问题\n\n# 核心观点\n\n"
        "# 详细内容总结"
    ),
    "douyin": (
        "# 一句话结论\n\n# 视频内容概括\n\n# 关键信息点\n\n"
        "# 展示的工具 / 方法 / 项目\n\n# 是否值得进一步验证"
    ),
    "x": (
        "# 一句话结论\n\n# 推文核心内容\n\n"
        "# 展示的工具 / 项目 / 方法\n\n# 关键细节(数据、参数、链接)\n\n"
        "# 是否值得跟进 / 验证\n\n# 相关链接"
    ),
    "gpt_chat": (
        "# 一句话结论\n\n# 这段对话讨论了什么\n\n# 已经形成的结论\n\n"
        "# 仍然不确定的问题\n\n# 可以沉淀为长期知识的内容\n\n"
        "# 需要后续追问 / 验证的地方"
    ),
    "wechat": (
        "# 一句话结论\n\n# 文章主要讲什么\n\n# 核心观点\n\n# 详细内容总结"
    ),
    "manual": (
        "# 一句话结论\n\n# 主要内容"
    ),
}

SUMMARY_SYSTEM_PROMPT = """你是一个技术内容整理助手。用户会给你一段资料原文,你需要按指定的章节结构输出一份详细的结构化中文笔记(不是抽象概括)。

核心原则 —— 尽量保留原文的有用信息,写详细笔记而不是简短概括:
1. 严格按照给出的章节标题顺序输出,每个标题用 markdown # 一级标题。
2. 「一句话结论」必须是 1 句话,点明这个东西/文章的核心价值。
3. 保留原文的关键事实、数据、项目名、步骤、论据、定义、对比、原文措辞中的要点。不要压缩成抽象概括,不要用「介绍了几个工具」「讲了若干方法」这种空话。
4. 列举类内容(多个项目 / 步骤 / 特性 / 配置项 / 命令)要逐项保留,带上原文给出的具体数据(star 数、版本号、参数、链接、价格、性能指标等)。每个项目至少写 2-3 句,不要只写一个名字。
5. 每个章节用充实的段落或要点列表。目标是:summary 的长度至少达到原文的 40-50%。宁可多写也不要漏掉信息。如果原文某个方面信息丰富,就多写一些。
6. 只过滤以下内容:广告、网站导航、页脚版权、重复出现的段落、与主题明显无关的闲聊。
7. 不要瞎编原文没有的内容。如果某个章节原文没涉及,就明确写「原文未涉及」,不要编。
8. 全程用中文(原文的专有名词/代码/命令可保留英文),客观、克制,不要营销腔。
9. 链接必须完整保留:原文里出现的所有 URL(github / 官网 / 文档 / 论文 / 参考资料 等)都要原样写进 summary,用 markdown 链接语法 [文字](完整URL)。绝对不要用「...」「…」省略链接,不要写「github.com/xxx/yyy…」这种残缺形式,必须是完整的 https:// 开头的 URL。如果链接很多,集中放到相关章节或单列一个「相关链接」要点。
"""


def summary_outline(source_type: str) -> str:
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

    outline = summary_outline(source_type)
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
- 如果用户在消息开头提供了【用户偏好】,请优先体现,但每条候选仍可根据自身性质独立定级,不强制套用到所有候选。
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
- 如果用户在消息开头提供了【用户偏好】,请优先体现,但每条候选仍可根据自身性质独立定级,不强制套用到所有候选。
"""


def _with_hint(summary_text: str, hint: str | None) -> str:
    """把用户引导拼到 summary 文本头部,作为 user message。

    hint 为空或仅空白时,直接返回截断后的 summary(维持原行为)。
    """
    truncated = summary_text[:50000]  # glm-4.7-flash 200K 上下文,安全上限
    if hint and hint.strip():
        return (
            f"【用户偏好(参考,不强制)】\n{hint.strip()}\n\n"
            f"--- 以下是文章 summary ---\n{truncated}"
        )
    return truncated


def _extract_json_list(text: str) -> list[dict[str, Any]] | None:
    """从模型回复里容错提取 JSON 数组。

    返回值:
        list[dict] - 成功解析(可能为空 [],表示 LLM 合法地没抽到候选)
        None       - 三种容错路径都解析失败(LLM 输出格式错误,调用方应抛错或记日志)
    """
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
    return None


def extract_ideas_from_summary(
    summary_text: str, hint: str | None = None
) -> list[dict[str, str]]:
    """从 summary 提炼 idea 候选。

    参数:
        summary_text: summary 正文
        hint: 用户引导(可选)。非空时拼到 user message 头部,作为偏好提示;
              为空时维持原行为,向后兼容现有调用方。

    返回 list[dict],每个 dict 字段均为字符串:
        title, recommended_area, priority, feasibility, novelty,
        estimated_investment, reason, what, challenges
    字段名统一(不带前缀),调用方负责包装成模板格式。

    异常:
        LLMError: 调用失败或输出无法解析
    """
    if not summary_text.strip():
        raise LLMError("空 summary,无法抽取 idea")

    user_msg = _with_hint(summary_text, hint)
    result = chat(
        [
            {"role": "system", "content": IDEA_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
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


def extract_todos_from_summary(
    summary_text: str, hint: str | None = None
) -> list[dict[str, str]]:
    """从 summary 提炼 todo 候选。

    参数:
        summary_text: summary 正文
        hint: 用户引导(可选)。非空时拼到 user message 头部,作为偏好提示;
              为空时维持原行为,向后兼容现有调用方。

    返回 list[dict],字段均为字符串:
        title, recommended_plan, priority, estimated_time, difficulty,
        why, what, challenges, acceptance
    """
    if not summary_text.strip():
        raise LLMError("空 summary,无法抽取 todo")

    user_msg = _with_hint(summary_text, hint)
    result = chat(
        [
            {"role": "system", "content": TODO_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
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


# ---------------------------------------------------------------------------
# 图片 OCR(GLM-4V-Flash 视觉模型)
# ---------------------------------------------------------------------------

VISION_MODEL = "glm-4v-flash"

OCR_SYSTEM_PROMPT = """你是一个 OCR 文字提取助手。用户会给你一张图片(通常是推文截图、技术文章截图、PPT 截图等),你需要:

1. 提取图片中的所有文字内容,保持原始的段落结构和格式。
2. 如果图片里有链接(URL),完整保留。
3. 如果图片里有代码,保持代码格式。
4. 如果图片里有表格,尽量还原为文本表格。
5. 不要添加任何解释、评论或额外内容。只输出提取的文字。
6. 如果图片里没有文字(纯图片/表情),返回"[图片中未检测到文字]"。
"""


def chat_vision(
    text_prompt: str,
    image_base64: str,
    *,
    image_mime: str = "image/jpeg",
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> str:
    """调用 GLM-4V-Flash 视觉模型。

    参数:
        text_prompt: 给模型的文字指令
        image_base64: 图片的 base64 编码(不含 data: 前缀)
        image_mime: 图片 MIME 类型(image/jpeg / image/png)
        temperature: 采样温度
        max_tokens: 最大输出 token(GLM-4V-Flash 上限 1024)

    返回: 模型的文字回复
    异常: LLMError
    """
    cfg = load_config()
    if not cfg["available"]:
        raise LLMError(
            "未配置 API key。请复制 .env.example 为 .env 并填入 ZHIPU_API_KEY。"
        )

    requests = _import_requests()
    url = cfg["base_url"] + "chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    data_uri = f"data:{image_mime};base64,{image_base64}"
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": OCR_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=cfg["timeout"])
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
                msg = err_body.get("error", {}).get("message", "") or str(err_body)
            except (ValueError, json.JSONDecodeError):
                msg = resp.text[:300]
            raise LLMError(f"Vision API 返回 HTTP {resp.status_code}: {msg}")
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content.strip()
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"Vision API 请求失败: {e}") from e


def ocr_image(image_base64: str, image_mime: str = "image/jpeg") -> str:
    """对图片做 OCR,提取全部文字。

    参数:
        image_base64: 图片的 base64 编码(不含 data: 前缀)
        image_mime: 图片 MIME 类型

    返回: 提取的文字
    异常: LLMError
    """
    return chat_vision(
        "请提取这张图片中的所有文字内容。",
        image_base64,
        image_mime=image_mime,
        temperature=0.1,
        max_tokens=1024,
    )
