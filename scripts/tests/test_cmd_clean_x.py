"""cmd_clean_x 命令(v0.4.6)—— 纯逻辑测试,无 LLM mock。

clean_x_text 是纯文本处理(正则去噪),不调 LLM,可直接测端到端。
"""
import argparse

import kb


def _make_x_source(tmp_path, name, raw_body):
    """建一个 X source note,含「原始内容」段。"""
    x_dir = tmp_path / "01_Sources" / "x"
    x_dir.mkdir(parents=True, exist_ok=True)
    f = x_dir / f"{name}.md"
    f.write_text(
        "---\n"
        f"source_id: {name}\n"
        "source_type: x\n"
        "---\n\n"
        "## 原始内容\n\n"
        f"{raw_body}\n",
        encoding="utf-8",
    )
    return f


def test_cmd_clean_x_missing_dir(isolate_vault):
    """01_Sources/x 不存在时返回 1。"""
    rc = kb.cmd_clean_x(argparse.Namespace(dry_run=False))
    assert rc == 1


def test_cmd_clean_x_empty_dir(isolate_vault):
    """目录存在但无文件返回 0。"""
    tmp_path = isolate_vault
    (tmp_path / "01_Sources" / "x").mkdir(parents=True)
    rc = kb.cmd_clean_x(argparse.Namespace(dry_run=False))
    assert rc == 0


def test_cmd_clean_x_dry_run_no_write(isolate_vault):
    """dry-run 不写文件。"""
    tmp_path = isolate_vault
    raw = "正文内容 Name @handle Views 1234 Show more"
    f = _make_x_source(tmp_path, "source_test1", raw)
    original = f.read_text(encoding="utf-8")

    rc = kb.cmd_clean_x(argparse.Namespace(dry_run=True))
    assert rc == 0
    # 文件未变
    assert f.read_text(encoding="utf-8") == original


def test_cmd_clean_x_skips_no_raw_section(isolate_vault):
    """无「原始内容」段的文件被跳过。"""
    tmp_path = isolate_vault
    x_dir = tmp_path / "01_Sources" / "x"
    x_dir.mkdir(parents=True)
    f = x_dir / "source_no_raw.md"
    f.write_text(
        "---\nsource_id: source_no_raw\n---\n\n"
        "## 别的标题\n\n正文\n",
        encoding="utf-8",
    )
    original = f.read_text(encoding="utf-8")

    rc = kb.cmd_clean_x(argparse.Namespace(dry_run=False))
    assert rc == 0
    # 文件未动
    assert f.read_text(encoding="utf-8") == original


def test_cmd_clean_x_idempotent(isolate_vault):
    """清洗后再跑一次应无变化(幂等)。"""
    tmp_path = isolate_vault
    raw = "正文 Name @handle Views 1234 Show more\n\n" * 3
    f = _make_x_source(tmp_path, "source_idem", raw)

    # 第一次清洗
    kb.cmd_clean_x(argparse.Namespace(dry_run=False))
    after_first = f.read_text(encoding="utf-8")

    # 第二次应无变化
    kb.cmd_clean_x(argparse.Namespace(dry_run=False))
    after_second = f.read_text(encoding="utf-8")
    assert after_first == after_second


def test_cmd_clean_x_preserves_frontmatter(isolate_vault):
    """清洗不破坏 frontmatter 和「## 原始内容」标题。"""
    tmp_path = isolate_vault
    raw = "正文 Views 12345"
    f = _make_x_source(tmp_path, "source_fm", raw)

    kb.cmd_clean_x(argparse.Namespace(dry_run=False))
    text = f.read_text(encoding="utf-8")
    # frontmatter 保留
    assert "source_id: source_fm" in text
    assert "source_type: x" in text
    # 「## 原始内容」段标题保留
    assert "## 原始内容" in text
