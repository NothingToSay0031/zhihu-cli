"""Minimal Markdown-to-HTML converter for publishing articles."""

from __future__ import annotations

import html
import re
from pathlib import Path

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+?)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_UL_RE = re.compile(r"^\s*[-*+]\s+(.*)")
_OL_RE = re.compile(r"^\s*\d+[.、]\s+(.*)")
_HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\|?[\s:\-|]+\|?\s*$")
_FENCE_RE = re.compile(r"^```|^~~~")


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


def _inline(text: str, image_map: dict[str, dict]) -> str:
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
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    return text


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

        if line.startswith("> "):
            close_table()
            buf = []
            while i < n and lines[i].startswith("> "):
                buf.append(lines[i][2:].strip())
                i += 1
            out.append("<blockquote>" + _inline(" ".join(buf), image_map) + "</blockquote>")
            continue

        m = _UL_RE.match(line)
        if m:
            close_table()
            out.append("<ul>")
            while i < n and _UL_RE.match(lines[i]):
                item = _UL_RE.match(lines[i]).group(1).strip()
                out.append(f"<li>{_inline(item, image_map)}</li>")
                i += 1
            out.append("</ul>")
            continue

        m = _OL_RE.match(line)
        if m:
            close_table()
            out.append("<ol>")
            while i < n and _OL_RE.match(lines[i]):
                item = _OL_RE.match(lines[i]).group(1).strip()
                out.append(f"<li>{_inline(item, image_map)}</li>")
                i += 1
            out.append("</ol>")
            continue

        close_table()
        buf = [line.strip()]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not lines[i].startswith(("#", "|", ">", "```", "~~~"))
            and not _UL_RE.match(lines[i])
            and not _OL_RE.match(lines[i])
            and not _HR_RE.match(lines[i].strip())
        ):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(buf), image_map)}</p>")

    close_table()
    return "\n".join(out)
