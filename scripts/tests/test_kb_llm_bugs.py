"""kb_llm bug 修复回归测试(v0.4.5)。

覆盖:
- _html_to_text 重复输出 bug(非 keep 标签的文本被写两遍)
- _extract_json_list 死代码(返回 [] 而非 None,调用方 if items is None 永远走不到)
"""
import kb_llm


# —— _html_to_text ——

def test_html_to_text_no_duplicate_for_div():
    """div 包裹的文本只输出一次(修复前会输出两次)。"""
    out = kb_llm._html_to_text("<div>裸文本</div>")
    assert out == "裸文本"


def test_html_to_text_mixed_keep_and_non_keep():
    """div + p + div 混合:每段文本只出现一次。"""
    html = "<div>外层文本 foo</div><p>段落 bar</p><div>尾部 baz</div>"
    out = kb_llm._html_to_text(html)
    assert out == "外层文本 foo 段落 bar 尾部 baz"
    # 关键:不能重复
    assert out.count("外层文本") == 1
    assert out.count("段落 bar") == 1
    assert out.count("尾部 baz") == 1


def test_html_to_text_keep_tag_content_preserved():
    """keep 标签(p/li/h/pre)内容完整保留。"""
    out = kb_llm._html_to_text("<p>段落A</p><p>段落B</p>")
    assert out == "段落A 段落B"


def test_html_to_text_pre_block():
    """pre 块内容保留(代码块场景)。"""
    out = kb_llm._html_to_text("<pre>代码块\n多行</pre>")
    assert "代码块" in out
    assert "多行" in out


def test_html_to_text_skip_tags_excluded():
    """script/style/nav 等噪声标签内容不出现。"""
    html = "<nav>导航</nav><p>正文</p><script>alert(1)</script>"
    out = kb_llm._html_to_text(html)
    assert "正文" in out
    assert "导航" not in out
    assert "alert" not in out


def test_html_to_text_empty():
    assert kb_llm._html_to_text("") == ""


# —— _extract_json_list ——

def test_extract_json_list_valid_array():
    """合法 JSON 数组正常解析。"""
    out = kb_llm._extract_json_list('[{"title": "a"}, {"title": "b"}]')
    assert out is not None
    assert len(out) == 2
    assert out[0]["title"] == "a"


def test_extract_json_list_empty_array_is_valid():
    """合法的空数组 [] 不是失败(表示 LLM 真的没抽到候选)。"""
    out = kb_llm._extract_json_list("[]")
    assert out == []
    # 注意:out is not None,与"解析失败"区分
    assert out is not None


def test_extract_json_list_garbage_returns_none():
    """垃圾文本无法解析时返回 None(不是 [])。

    修复前:返回 [],导致调用方 if items is None 永远 False,raise 走不到。
    """
    out = kb_llm._extract_json_list("这不是 JSON")
    assert out is None


def test_extract_json_list_empty_string_returns_none():
    out = kb_llm._extract_json_list("")
    assert out is None


def test_extract_json_list_markdown_code_block():
    """```json 代码块包裹的数组能解析。"""
    text = """这是回复:
```json
[{"title": "x"}]
```"""
    out = kb_llm._extract_json_list(text)
    assert out is not None
    assert len(out) == 1
    assert out[0]["title"] == "x"


def test_extract_json_list_filters_non_dict_elements():
    """数组里混入非 dict 元素(字符串/数字)会被过滤。"""
    out = kb_llm._extract_json_list('[{"a": 1}, "str", 42, {"b": 2}]')
    assert out is not None
    assert len(out) == 2  # 只保留两个 dict


def test_extract_json_list_explanation_text_then_array():
    """LLM 输出"以下是候选:[...]"格式也能从正文提取数组。"""
    text = "好的,以下是抽取的 idea:\n[{\"title\": \"a\"}]"
    out = kb_llm._extract_json_list(text)
    assert out is not None
    assert len(out) == 1


# —— _extract_json(单对象) ——

def test_extract_json_valid_dict():
    """合法 JSON 对象正常解析。"""
    out = kb_llm._extract_json('{"source_type": "github", "title": "x"}')
    assert out == {"source_type": "github", "title": "x"}


def test_extract_json_returns_none_for_array():
    """JSON 数组不是 dict,应返回 None(类型不符)。"""
    out = kb_llm._extract_json('[1, 2, 3]')
    assert out is None


def test_extract_json_returns_none_for_garbage():
    out = kb_llm._extract_json("这不是 JSON")
    assert out is None


def test_extract_json_returns_none_for_empty():
    assert kb_llm._extract_json("") is None


def test_extract_json_markdown_code_block():
    """```json 代码块包裹的 dict。"""
    text = "好的:\n```json\n{\"a\": 1}\n```"
    out = kb_llm._extract_json(text)
    assert out == {"a": 1}


def test_extract_json_explanation_then_braces():
    """解释文本里嵌入 {...}。"""
    text = "结果如下:{\"source_type\": \"x\"} 以上"
    out = kb_llm._extract_json(text)
    assert out == {"source_type": "x"}


# —— _parse_env_file ——

def test_parse_env_file_basic(tmp_path):
    """KEY=VALUE 基本解析。"""
    f = tmp_path / ".env"
    f.write_text(
        "ZHIPU_API_KEY=abc123\n"
        "KB_LLM_MODEL=glm-4-flash\n",
        encoding="utf-8",
    )
    out = kb_llm._parse_env_file(f)
    assert out["ZHIPU_API_KEY"] == "abc123"
    assert out["KB_LLM_MODEL"] == "glm-4-flash"


def test_parse_env_file_strips_quotes(tmp_path):
    """值两端的引号被去掉。"""
    f = tmp_path / ".env"
    f.write_text(
        'KEY1="value1"\n'
        "KEY2='value2'\n",
        encoding="utf-8",
    )
    out = kb_llm._parse_env_file(f)
    assert out["KEY1"] == "value1"
    assert out["KEY2"] == "value2"


def test_parse_env_file_ignores_comments(tmp_path):
    """# 注释和空行被忽略。"""
    f = tmp_path / ".env"
    f.write_text(
        "# 这是注释\n"
        "\n"
        "KEY=val\n"
        "  # 带缩进的注释\n",
        encoding="utf-8",
    )
    out = kb_llm._parse_env_file(f)
    assert out == {"KEY": "val"}


def test_parse_env_file_skips_lines_without_equals(tmp_path):
    """没有 = 的行被跳过(不抛错)。"""
    f = tmp_path / ".env"
    f.write_text("orphan_line\nKEY=val\n", encoding="utf-8")
    out = kb_llm._parse_env_file(f)
    assert out == {"KEY": "val"}


def test_parse_env_file_nonexistent_returns_empty(tmp_path):
    """文件不存在时返回空 dict。"""
    out = kb_llm._parse_env_file(tmp_path / "no_such.env")
    assert out == {}


def test_parse_env_file_empty_file(tmp_path):
    """空文件返回空 dict。"""
    f = tmp_path / ".env"
    f.write_text("", encoding="utf-8")
    assert kb_llm._parse_env_file(f) == {}


# —— estimated_time 不再硬兜底 "2-4h"(v0.4.7, ROADMAP P1-#6) ——

def test_extract_todos_no_estimated_time_stays_empty(monkeypatch):
    """LLM 没返回 estimated_time 时,结果应保持空字符串,而不是伪造 "2-4h"。

    修复前:kb_llm.py 用 `str(it.get("estimated_time", "")).strip() or "2-4h"`,
    把 LLM 漏填的字段伪造一个值,污染 review 队列。
    修复后:对照 extract_ideas_from_summary 的 estimated_investment 写法,留空。
    """
    # fake LLM:返回的 todo 没有 estimated_time 字段
    def fake_chat(messages, **kwargs):
        return {"content": '[{"title": "测试 todo", "recommended_plan": "weekly", "priority": "P1", "difficulty": "low"}]'}

    monkeypatch.setattr(kb_llm, "chat", fake_chat)
    todos = kb_llm.extract_todos_from_summary("一段 summary 正文")
    assert len(todos) == 1
    # 关键断言:estimated_time 是空字符串,不是 "2-4h"
    assert todos[0]["estimated_time"] == ""
    assert todos[0]["estimated_time"] != "2-4h"
