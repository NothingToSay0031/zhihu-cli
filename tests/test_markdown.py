"""Tests for the markdown-to-HTML converter used by publish commands."""

from __future__ import annotations

from zhihu_cli.markdown import md_to_html


def test_simple_ordered_list_single_ol():
    html = md_to_html("1. a\n2. b\n3. c\n")
    assert html.count("<ol>") == 1
    assert html.count("<li>") == 3
    assert "<li>a</li>" in html
    assert "<li>b</li>" in html
    assert "<li>c</li>" in html


def test_ordered_list_with_code_fence_keeps_numbering():
    md = (
        "1. cancel a pre-wait thread\n"
        "2. pop from waiting stack:\n"
        "\n"
        "```cpp\n"
        "// Signaling can be very costly\n"
        "```\n"
        "\n"
        "3. start a new thread if stack is empty\n"
    )
    html = md_to_html(md)
    assert html.count("<ol>") == 1
    assert html.count("<li>") == 3
    assert '<pre lang="cpp">// Signaling can be very costly</pre>' in html
    assert html.index("<ol>") < html.index('<pre lang="cpp">') < html.index("</ol>")


def test_ordered_list_with_nested_unordered_list():
    md = (
        "1. Launch creates the task\n"
        "2. Schedule dispatches:\n"
        "   - named thread tasks -> stalling queue\n"
        "   - otherwise -> scheduler queue\n"
        "3. TryPrepareLaunch then enqueue\n"
        "4. worker wakes and steals\n"
    )
    html = md_to_html(md)
    assert html.count("<ol>") == 1
    assert html.count("<ul>") == 1
    assert html.count("<li>") == 6
    ol = html.index("<ol>")
    li2 = html.index("<li>Schedule dispatches:")
    ul = html.index("<ul>")
    li3 = html.index("<li>TryPrepareLaunch then enqueue")
    assert ol < li2 < ul < li3


def test_fence_after_list_not_absorbed():
    md = "1. item\n\n```\ncode\n```\n\nafter\n"
    html = md_to_html(md)
    assert html.count("<ol>") == 1
    assert html.count("<pre>") == 1
    assert html.index("</ol>") < html.index("<pre>")


def test_nested_list_in_unordered_list():
    md = "- a\n- b:\n  1. one\n  2. two\n- c\n"
    html = md_to_html(md)
    assert html.count("<ul>") == 1
    assert html.count("<ol>") == 1
    assert html.count("<li>") == 5
    assert html.index("</ol>") < html.index("<li>c</li>")


def test_margin_quote_after_blank_line_stays_out_of_list():
    md = (
        "- 在动手做出有趣东西的过程中，你能够：\n"
        "  - 真正理解软件工程；\n"
        "  - 做出真实作品。\n"
        "\n"
        "> 教授观点：一篇已发表的论文只是“加分项”。\n"
        "\n"
        "---\n"
        "\n"
        "### 下一节\n"
    )
    html = md_to_html(md)
    ul_end = html.index("</ul>")
    quote = html.index("教授观点")
    hr = html.index("<hr>")
    assert html.count("<ul>") == 2  # outer list + nested sublist
    assert ul_end < quote < hr


def test_indented_quote_after_blank_line_stays_in_item():
    md = (
        "- 老师的整个配置过程只用了**一个 prompt**，大意是：\n"
        "\n"
        "  > “帮我把命令行终端配置成现代的样子。”\n"
        "\n"
        "- 用的模型依然只是 DeepSeek V4 Flash；\n"
    )
    html = md_to_html(md)
    assert html.count("<ul>") == 1
    assert html.count("<li>") == 2
    first_li_end = html.index("</li>")
    assert html.index("帮我把命令行终端") < first_li_end


def test_display_math_single_line_becomes_equation_image():
    html = md_to_html(
        r"$$ C = C_{\text{system}} + C_{\text{project}} + C_{\text{user}} $$"
    )
    assert "$$" not in html
    assert 'eeimg="2"' in html
    assert "https://www.zhihu.com/equation?tex=" in html
    assert "%2B" in html
    assert r"C_{\text{system}}" in html
    assert html.startswith("<p><img ")
    assert html.strip().endswith("></p>")


def test_display_math_multiline_collapses_to_one_formula():
    md = (
        "$$\n"
        r"\text{Agent Context}"
        "\n=\n"
        r"\text{System Prompt}"
        "\n+\n"
        r"\text{User Messages}"
        "\n$$"
    )
    html = md_to_html(md)
    assert "$$" not in html
    assert html.count("equation?tex=") == 1
    assert r"\text{Agent Context}" in html
    assert r"\text{User Messages}" in html


def test_inline_math_in_paragraph_and_list():
    html = md_to_html("* $x_0$：最初的尝试；\n* $x^*$：最终解。\n")
    assert "$x_0$" not in html
    assert "$x^*$" not in html
    assert html.count("equation?tex=") == 2
    assert 'eeimg="1"' in html
    assert "<li>" in html


def test_math_inside_inline_code_and_fence_stays_literal():
    html = md_to_html("use `$x_0$` plus:\n\n```\n$$\nA = B\n$$\n```\n")
    assert "<code>$x_0$</code>" in html
    assert "equation?tex=" not in html
    assert "$$" in html


def test_text_then_display_math_not_merged():
    html = md_to_html("前文\n$$\nE = mc^2\n$$\n后文\n")
    assert html.index("前文") < html.index("equation?tex=") < html.index("后文")
    assert "$$" not in html
    assert "<p>前文</p>" in html
    assert "<p>后文</p>" in html
