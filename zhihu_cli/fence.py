"""Shared fenced-code detection following CommonMark rules.

A fenced block is opened by a run of 3+ backticks or tildes and closed by a
run of the SAME character with length >= the opener and no trailing text.
Keeping this in one place avoids the classic bug where a '~~~~~' line inside a
``` block is mistaken for a closing fence.
"""

from __future__ import annotations

import re

FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})(.*)$", re.S)
FENCE_CLOSE_RE = re.compile(r"^(`{3,}|~{3,})\s*$")


def fence_open(line: str):
    """Return (char, length, info) if `line` opens a fence, else None."""
    m = FENCE_OPEN_RE.match(line.strip())
    if not m:
        return None
    return m.group(1)[0], len(m.group(1)), m.group(2).strip()


def is_fence_open(line: str) -> bool:
    return fence_open(line) is not None


def is_fence_close(line: str, open_char: str, open_len: int) -> bool:
    """True if line closes a fence opened with `open_char`/`open_len`."""
    m = FENCE_CLOSE_RE.match(line.strip())
    if not m:
        return False
    fence = m.group(1)
    return fence[0] == open_char and len(fence) >= open_len
