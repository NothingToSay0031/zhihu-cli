"""Tests for Markdown splitting used by publish-md."""

from __future__ import annotations

from zhihu_cli.split import part_title, series_lead, split_markdown


def test_short_text_is_not_split():
    text = "# Hello\n\nworld\n"
    assert split_markdown(text, max_chars=1000) == [text]


def test_split_at_h1_and_roundtrip():
    a = "# A\n\n" + ("a" * 40) + "\n"
    b = "# B\n\n" + ("b" * 40) + "\n"
    parts = split_markdown(a + b, max_chars=60)
    assert len(parts) == 2
    assert parts[0].startswith("# A")
    assert parts[1].startswith("# B")
    assert "".join(parts) == a + b


def test_packs_small_h1_sections():
    text = "".join(f"# H{i}\n\nx\n\n" for i in range(4))
    parts = split_markdown(text, max_chars=30)
    assert len(parts) >= 2
    assert "".join(parts) == text


def test_does_not_split_inside_fence():
    fence = "```\n# not a heading\nxx\n```\n"
    body = "# Real\n\n" + ("y" * 30) + "\n"
    text = fence + body
    parts = split_markdown(text, max_chars=40)
    assert any("# not a heading" in p and "```" in p for p in parts)
    assert "".join(parts) == text
    assert all(p.count("```") % 2 == 0 for p in parts)


def test_does_not_split_inside_display_math():
    math = "$$\n# not a heading\nxx\n$$\n"
    body = "# Real\n\n" + ("y" * 30) + "\n"
    text = math + body
    parts = split_markdown(text, max_chars=40)
    assert "".join(parts) == text
    assert any("# not a heading" in p and "$$" in p for p in parts)


def test_oversized_section_falls_back_to_h2():
    text = "# Big\n\n" + "## One\n\n" + ("a" * 40) + "\n\n## Two\n\n" + ("b" * 40) + "\n"
    parts = split_markdown(text, max_chars=50)
    assert len(parts) >= 2
    assert "".join(parts) == text


def test_paragraph_fallback_without_headings():
    text = ("para one " * 10 + "\n\n") + ("para two " * 10 + "\n\n")
    parts = split_markdown(text, max_chars=40)
    assert len(parts) >= 2
    assert "".join(parts) == text


def test_part_title_single():
    assert part_title("Hello", 1, 1) == "Hello"


def test_part_title_series():
    assert part_title("Hello", 2, 5) == "Hello（Part 2/5）"


def test_part_title_clips_long_base():
    base = "字" * 120
    title = part_title(base, 1, 3)
    assert title.endswith("（Part 1/3）")
    assert len(title) <= 100


def test_series_lead():
    assert series_lead("T", 1, 1) == ""
    lead = series_lead("T", 1, 3)
    assert "第 1 / 3 篇" in lead
    assert lead.startswith(">")
