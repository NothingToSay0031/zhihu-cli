"""Split large Markdown documents into Zhihu-publishable parts."""

from __future__ import annotations

import re

from . import config

_FENCE_RE = re.compile(r"^```|^~~~")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")


def part_title(base: str, index: int, total: int) -> str:
    """Build a Zhihu title, appending ``（Part i/n）`` when split."""
    if total <= 1:
        return _clip_title(base)
    suffix = f"（Part {index}/{total}）"
    budget = config.ZHIHU_TITLE_MAX - len(suffix)
    if budget < 8:
        return _clip_title(f"{index}/{total} {base}")
    return _clip_title(base, budget) + suffix


def series_lead(base_title: str, index: int, total: int) -> str:
    """Short blockquote prepended to each part so readers know the series."""
    if total <= 1:
        return ""
    return f"> 本文为《{base_title}》第 {index} / {total} 篇。\n\n"


def split_markdown(text: str, max_chars: int | None = None) -> list[str]:
    """Split Markdown into parts of at most ``max_chars`` characters.

    Prefers ATX headings (``#`` / ``##`` / ``###``), then blank-line
    paragraphs, then line boundaries. Fenced code and ``$$`` display-math
    blocks are kept intact unless a single block exceeds the limit.
    """
    if max_chars is None:
        max_chars = config.MAX_PART_CHARS
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return [text]
    return _split_deeper(text, max_chars, start_level=1)


def _clip_title(title: str, max_len: int | None = None) -> str:
    if max_len is None:
        max_len = config.ZHIHU_TITLE_MAX
    if len(title) <= max_len:
        return title
    if max_len <= 1:
        return title[:max_len]
    return title[: max_len - 1] + "…"


class _Scan:
    """Track fenced-code / display-math so we do not cut inside them."""

    def __init__(self) -> None:
        self.in_fence = False
        self.in_math = False

    @property
    def protected(self) -> bool:
        return self.in_fence or self.in_math

    def observe(self, line: str) -> None:
        stripped = line.strip()
        if self.in_fence:
            if _FENCE_RE.match(stripped):
                self.in_fence = False
            return
        if _FENCE_RE.match(stripped):
            self.in_fence = True
            return
        if self.in_math:
            if "$$" in stripped:
                self.in_math = False
            return
        if stripped.startswith("$$") and "$$" not in stripped[2:]:
            self.in_math = True


def _is_heading_cut(line: str, scan: _Scan, level: int) -> bool:
    if scan.protected:
        return False
    m = _HEADING_RE.match(line)
    return bool(m) and len(m.group(1)) == level


def _split_at_headings(text: str, level: int) -> list[str]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return [text]
    scan = _Scan()
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if current and _is_heading_cut(line, scan, level):
            groups.append(current)
            current = [line]
        else:
            current.append(line)
        scan.observe(line)
    if current:
        groups.append(current)
    return ["".join(g) for g in groups]


def _pack(chunks: list[str], max_chars: int, resplit) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for chunk in chunks:
        if not chunk:
            continue
        if len(chunk) > max_chars:
            if buf:
                parts.append("".join(buf))
                buf, buf_len = [], 0
            parts.extend(resplit(chunk))
            continue
        if buf and buf_len + len(chunk) > max_chars:
            parts.append("".join(buf))
            buf, buf_len = [chunk], len(chunk)
        else:
            buf.append(chunk)
            buf_len += len(chunk)
    if buf:
        parts.append("".join(buf))
    return parts or [""]


def _split_deeper(text: str, max_chars: int, start_level: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    for level in range(start_level, 4):
        chunks = _split_at_headings(text, level)
        if len(chunks) <= 1:
            continue
        return _pack(
            chunks,
            max_chars,
            lambda c, lv=level: _split_deeper(c, max_chars, lv + 1),
        )
    return _split_paragraphs(text, max_chars)


def _atomic_blocks(text: str) -> list[str]:
    """Fence, display-math, or blank-line-separated paragraphs."""
    lines = text.splitlines(keepends=True)
    n = len(lines)
    blocks: list[str] = []
    i = 0
    while i < n:
        stripped = lines[i].strip()
        if _FENCE_RE.match(stripped):
            j = i + 1
            while j < n and not _FENCE_RE.match(lines[j].strip()):
                j += 1
            j = min(j + 1, n)
            blocks.append("".join(lines[i:j]))
            i = j
            continue
        if stripped.startswith("$$") and "$$" not in stripped[2:]:
            j = i + 1
            while j < n and "$$" not in lines[j]:
                j += 1
            j = min(j + 1, n)
            blocks.append("".join(lines[i:j]))
            i = j
            continue
        j = i + 1
        while j < n and lines[j].strip():
            nxt = lines[j].strip()
            if _FENCE_RE.match(nxt) or (
                nxt.startswith("$$") and "$$" not in nxt[2:]
            ):
                break
            j += 1
        while j < n and not lines[j].strip():
            j += 1
        blocks.append("".join(lines[i:j]))
        i = j
    return blocks


def _hard_cut(text: str, max_chars: int) -> list[str]:
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _split_raw_lines(text: str, max_chars: int) -> list[str]:
    lines = text.splitlines(keepends=True)
    scan = _Scan()
    parts: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for line in lines:
        if buf and buf_len + len(line) > max_chars and not scan.protected:
            parts.append("".join(buf))
            buf, buf_len = [line], len(line)
        else:
            buf.append(line)
            buf_len += len(line)
        scan.observe(line)
    if buf:
        parts.append("".join(buf))
    out: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            out.append(part)
        else:
            out.extend(_hard_cut(part, max_chars))
    return out or [text]


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    chunks = _atomic_blocks(text)
    if len(chunks) <= 1:
        return _split_raw_lines(text, max_chars)
    return _pack(chunks, max_chars, lambda c: _split_raw_lines(c, max_chars))
