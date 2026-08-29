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
