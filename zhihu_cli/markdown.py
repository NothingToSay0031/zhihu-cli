"""Minimal Markdown-to-HTML converter for publishing articles."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+?)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_UL_RE = re.compile(r"^\s*[-*+]\s+(.*)")
_OL_RE = re.compile(r"^\s*\d+[.、]\s+(.*)")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)")
_HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\|?[\s:\-|]+\|?\s*$")
_FENCE_RE = re.compile(r"^```|^~~~")
_DISPLAY_MATH_RE = re.compile(r"\$\$([\s\S]+?)\$\$")
_INLINE_MATH_RE = re.compile(
    r"(?<!\$)\$(?!\$)([^\s$](?:[^$\n]*[^\s$])?)\$(?!\$)"
)
_SLOT_RE = re.compile(r"@@@ZHIHU_PH_(\d+)@@@")


def extract_local_images(md_text: str, base_dir: Path) -> dict[str, Path]:
    """Collect local image references: raw ref string -> resolved absolute path."""
    out: dict[str, Path] = {}
    for m in _IMAGE_RE.finditer(md_text):
        ref = m.group(2)
        if re.match(r"^https?://", ref):
            continue
        p = Path(ref)
        if not p.is_absolute():
            p = base_dir / p
        if p.is_file():
            out[ref] = p
    return out


def _img_tag(src: str, alt: str, width: int = 0, height: int = 0) -> str:
    return (
        f'<img src="{src}" data-caption="{alt}" data-size="normal"'
        f' data-rawwidth="{width}" data-rawheight="{height}"/>'
    )


def _normalize_tex(tex: str) -> str:
    return re.sub(r"\s+", " ", tex.strip())


def _formula_img(tex: str, *, display: bool = False) -> str:
    """Zhihu keeps ``img[eeimg]`` formula nodes; empty ``ztext-math`` spans are stripped."""
    tex = _normalize_tex(tex)
    encoded = quote(tex, safe="")
    alt = html.escape(tex, quote=True)
    eeimg = "2" if display else "1"
    return (
        f'<img src="https://www.zhihu.com/equation?tex={encoded}" '
        f'alt="{alt}" class="ee_img tr_noresize" eeimg="{eeimg}">'
    )


def _consume_display_math(
    lines: list[str], i: int, n: int
) -> tuple[str, int] | None:
    """Parse a ``$$...$$`` block starting at lines[i]. Returns (html, next_i)."""
    stripped = lines[i].strip()
    if not stripped.startswith("$$"):
        return None
    rest = stripped[2:]
    close_at = rest.find("$$")
    if close_at >= 0:
        inner = rest[:close_at]
        if not _normalize_tex(inner):
            return None
        return f"<p>{_formula_img(inner, display=True)}</p>", i + 1
    buf = [rest] if rest.strip() else []
    j = i + 1
    while j < n:
        ts = lines[j].strip()
        close_at = ts.find("$$")
        if close_at >= 0:
            before = ts[:close_at]
            if before.strip():
                buf.append(before)
            inner = "\n".join(buf)
            if not _normalize_tex(inner):
                return None
            return f"<p>{_formula_img(inner, display=True)}</p>", j + 1
        buf.append(lines[j].rstrip())
        j += 1
    return None


def _inline(text: str, image_map: dict[str, dict]) -> str:
    slots: list[tuple[str, str]] = []

    def stash(kind: str, raw: str) -> str:
        slots.append((kind, raw))
        return f"@@@ZHIHU_PH_{len(slots) - 1}@@@"

    text = _CODE_RE.sub(lambda m: stash("code", m.group(1)), text)
    text = _DISPLAY_MATH_RE.sub(lambda m: stash("math-display", m.group(1)), text)
    text = _INLINE_MATH_RE.sub(lambda m: stash("math-inline", m.group(1)), text)
    text = html.escape(text, quote=False)

    def img_repl(m: re.Match) -> str:
        alt, ref = m.group(1), m.group(2)
        if ref in image_map:
            info = image_map[ref]
            return _img_tag(
                info["src"], alt, info.get("width", 0), info.get("height", 0)
            )
        if re.match(r"^https?://", ref):
            return _img_tag(ref, alt)
        return alt

    text = _IMAGE_RE.sub(img_repl, text)
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)

    def restore(m: re.Match) -> str:
        kind, raw = slots[int(m.group(1))]
        if kind == "code":
            return f"<code>{html.escape(raw, quote=False)}</code>"
        return _formula_img(raw, display=kind == "math-display")

    return _SLOT_RE.sub(restore, text)


def _fence_then_item(
    lines: list[str], j: int, n: int, is_item, other_item, base_indent: int
) -> bool:
    """True if the fenced block at lines[j] is followed (after its closing
    fence) by a list item that resumes the current list."""
    k = j + 1
    while k < n:
        if not lines[k].strip():
            k += 1
            continue
        if _FENCE_RE.match(lines[k].strip()):
            k += 1
            break
        k += 1
    while k < n:
        line = lines[k].rstrip()
        if not line.strip():
            k += 1
            continue
        if len(line) - len(line.lstrip()) < base_indent:
            return False
        return bool(is_item(line) or other_item(line))
    return False


def _emit_list(
    out: list[str],
    lines: list[str],
    i: int,
    n: int,
    ordered: bool,
    image_map: dict[str, dict],
) -> int:
    """Emit a whole list (ordered or unordered) starting at lines[i].

    Consecutive list items (possibly separated by blank lines, nested
    blockquotes, fenced code blocks or nested lists) are kept inside a
    single <ol>/<ul> so Zhihu renders the numbering correctly.
    Returns the index of the first line after the list.
    """
    is_item = _OL_RE.match if ordered else _UL_RE.match
    other_item = _UL_RE.match if ordered else _OL_RE.match
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>")
    segments: list[tuple[str, str]] = []
    nested: list[str] = []
    base_indent: int | None = None

    def flush_li() -> None:
        nonlocal segments, nested
        if not segments and not nested:
            return
        inner = "".join(
            _inline(txt, image_map) if kind == "text" else txt
            for kind, txt in segments
        )
        if nested:
            inner += "".join(nested)
        out.append(f"<li>{inner}</li>")
        segments = []
        nested = []

    while i < n:
        line = lines[i].rstrip()
        if base_indent is None:
            base_indent = len(line) - len(line.lstrip())
        if not line.strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j >= n:
                i = j
                break
            nxt = lines[j].rstrip()
            nxt_indent = len(nxt) - len(nxt.lstrip())
            if nxt_indent >= base_indent and (
                is_item(nxt)
                or other_item(nxt)
                or (nxt_indent > base_indent and _QUOTE_RE.match(nxt))
                or _is_li_continuation(nxt)
                or (
                    _FENCE_RE.match(nxt.strip())
                    and _fence_then_item(lines, j, n, is_item, other_item, base_indent)
                )
            ):
                i = j
                continue
            break

        indent = len(line) - len(line.lstrip())
        m = is_item(line)
        if m:
            if indent > base_indent:
                sub: list[str] = []
                i = _emit_list(sub, lines, i, n, ordered, image_map)
                nested.append("".join(sub))
                continue
            flush_li()
            segments.append(("text", m.group(1).strip()))
            i += 1
            continue
        m2 = other_item(line)
        if m2:
            if indent > base_indent:
                sub = []
                i = _emit_list(sub, lines, i, n, not ordered, image_map)
                nested.append("".join(sub))
                continue
            break
        if _FENCE_RE.match(line.strip()):
            if _fence_then_item(lines, i, n, is_item, other_item, base_indent):
                fence = line.strip()
                lang = fence[3:].strip()
                buf: list[str] = []
                i += 1
                while i < n and not _FENCE_RE.match(lines[i].strip()):
                    buf.append(lines[i])
                    i += 1
                i += 1
                code = html.escape("\n".join(buf))
                lang_attr = f' lang="{lang}"' if lang else ""
                pre = f"<pre{lang_attr}>{code}</pre>"
                if nested:
                    nested.append(pre)
                else:
                    segments.append(("html", pre))
                continue
            break
        q = _QUOTE_RE.match(line)
        if q:
            buf = [q.group(1).strip()]
            i += 1
            while i < n:
                q2 = _QUOTE_RE.match(lines[i].rstrip())
                if q2:
                    buf.append(q2.group(1).strip())
                    i += 1
                else:
                    break
            segments.append(
                (
                    "html",
                    '<blockquote data-draft-node="block" data-draft-type="blockquote">'
                    + _inline(" ".join(buf), image_map)
                    + "</blockquote>",
                )
            )
            continue
        if _is_li_continuation(line):
            if segments and segments[-1][0] == "text":
                segments[-1] = ("text", segments[-1][1] + " " + line.strip())
            else:
                segments.append(("text", line.strip()))
            i += 1
            continue
        break
    flush_li()
    out.append(f"</{tag}>")
    return i


def _is_li_continuation(line: str) -> bool:
    """Indented text that belongs to the current list item (continuation)."""
    s = line.lstrip()
    return (
        bool(re.match(r"^\s+\S", line))
        and not _HEADING_RE.match(s)
        and not _FENCE_RE.match(s)
        and not _HR_RE.match(s)
        and not s.startswith("|")
        and not s.startswith("$$")
        and not _UL_RE.match(s)
        and not _OL_RE.match(s)
    )


def md_to_html(md_text: str, image_map: dict[str, dict] | None = None) -> str:
    """Convert markdown text to HTML for Zhihu article publishing.

    image_map: raw image ref -> upload info dict (src, width, height).
    """
    image_map = image_map or {}
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    in_table = False

    def close_table() -> None:
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False
    while i < n:
        line = lines[i].rstrip()
        if not line.strip():
            close_table()
            i += 1
            continue

        if _FENCE_RE.match(line.strip()):
            close_table()
            lang = line.strip()[3:].strip()
            buf: list[str] = []
            i += 1
            while i < n and not _FENCE_RE.match(lines[i].strip()):
                buf.append(lines[i])
                i += 1
            i += 1
            code = html.escape("\n".join(buf))
            lang_attr = f' lang="{lang}"' if lang else ""
            out.append(f"<pre{lang_attr}>{code}</pre>")
            continue

        math = _consume_display_math(lines, i, n)
        if math is not None:
            close_table()
            html_block, nxt = math
            out.append(html_block)
            i = nxt
            continue

        if _HR_RE.match(line):
            close_table()
            out.append("<hr>")
            i += 1
            continue

        if line.startswith("|") and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            close_table()
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append(
                '<table data-draft-node="block" data-draft-type="table" '
                'data-size="normal"><tbody><tr>'
            )
            out.extend(f"<th>{_inline(h, image_map)}</th>" for h in header)
            out.append("</tr>")
            in_table = True
            i += 2
            continue

        if line.startswith("|") and in_table:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            row = "".join(f"<td>{_inline(c, image_map)}</td>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            i += 1
            continue

        m = _HEADING_RE.match(line)
        if m:
            close_table()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2), image_map)}</h{lvl}>")
            i += 1
            continue

        q = _QUOTE_RE.match(line)
        if q:
            close_table()
            buf = [q.group(1).strip()]
            i += 1
            while i < n:
                q2 = _QUOTE_RE.match(lines[i].rstrip())
                if q2:
                    buf.append(q2.group(1).strip())
                    i += 1
                else:
                    break
            out.append(
                '<blockquote data-draft-node="block" data-draft-type="blockquote">'
                + _inline(" ".join(buf), image_map)
                + "</blockquote>"
            )
            continue

        m = _UL_RE.match(line)
        if m:
            close_table()
            i = _emit_list(out, lines, i, n, False, image_map)
            continue

        m = _OL_RE.match(line)
        if m:
            close_table()
            i = _emit_list(out, lines, i, n, True, image_map)
            continue

        close_table()
        buf = [line.strip()]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not _QUOTE_RE.match(lines[i])
            and not lines[i].lstrip().startswith(("#", "|", ">", "```", "~~~", "$$"))
            and not _UL_RE.match(lines[i])
            and not _OL_RE.match(lines[i])
            and not _HR_RE.match(lines[i].strip())
        ):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(buf), image_map)}</p>")

    close_table()
    return "\n".join(out)
