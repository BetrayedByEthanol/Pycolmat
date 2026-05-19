"""
Rule: self-assignment alignment (auto-fix + CF009 check-only).

Aligns contiguous blocks of ``self.X = value`` assignments that share
the same indentation level so the ``=`` signs line up vertically.

Constraints
-----------
- Only plain ``self.Attr = value`` lines (no augmented assignment).
- All lines in a block must have identical leading whitespace.
- A blank line, a comment line, or any non-self-assign line breaks the block.
- Single-line blocks are never a violation.
- Does NOT touch dicts, kwargs, ordinary assignments, or augmented assigns.
- Does NOT change Python semantics.
- Handles both LF and CRLF line endings without mixing them.
"""

from __future__ import annotations

import re
from pathlib import Path

from customfmt.types import Violation

# Matches:  <indent>self.<attr> = <rhs>
# Does NOT match augmented assigns (+=, -=, …) or == comparisons.
# Group 4 captures the rhs *without* any trailing \r or \n.
_RE = re.compile(r"^( *)(self\.[A-Za-z_][A-Za-z0-9_]*) *(=(?!=)) *(.*?)\r?\n?$")

RULE_CODE = "CF009"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse(line: str) -> re.Match | None:
    return _RE.match(line)


def _iter_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """
    Return (start, end) index pairs (inclusive, 0-based) for every
    contiguous run of self-assignment lines sharing the same indent.
    """
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _parse(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        start = i
        j = i + 1
        while j < n:
            m2 = _parse(lines[j])
            if m2 and m2.group(1) == indent:
                j += 1
            else:
                break
        blocks.append((start, j - 1))
        i = j
    return blocks


def _line_ending(line: str) -> str:
    """Return the line ending (``\r\n`` or ``\n``) of *line*, defaulting to ``\n``."""
    if line.endswith("\r\n"):
        return "\r\n"
    return "\n"


def _aligned_block(lines: list[str], start: int, end: int) -> list[str]:
    """Return the slice lines[start..end] with = signs column-aligned."""
    block = lines[start : end + 1]
    parsed = [_parse(line) for line in block]  # all match
    max_lhs = max(len(m.group(1)) + len(m.group(2)) for m in parsed)  # type: ignore[union-attr]

    result = []
    for orig_line, m in zip(block, parsed):
        indent = m.group(1)  # type: ignore[union-attr]
        attr = m.group(2)  # type: ignore[union-attr]
        rhs = m.group(4)  # type: ignore[union-attr]  — stripped of \r\n by regex
        pad = " " * (max_lhs - len(indent) - len(attr))
        ending = _line_ending(orig_line)
        result.append(f"{indent}{attr}{pad} = {rhs}{ending}")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(lines: list[str], path: Path) -> list[Violation]:
    """Return CF009 violations (misaligned blocks)."""
    violations: list[Violation] = []
    for start, end in _iter_blocks(lines):
        if start == end:
            continue  # single-line block: nothing to align
        aligned = _aligned_block(lines, start, end)
        for offset in range(end - start + 1):
            if lines[start + offset] != aligned[offset]:
                violations.append(
                    Violation(
                        path,
                        start + offset + 1,  # 1-based
                        1,
                        RULE_CODE,
                        "self-assignment block is not aligned",
                    )
                )
    return violations


def fix(lines: list[str]) -> list[str]:
    """Return a new list of lines with all self-assign blocks aligned."""
    result = list(lines)
    for start, end in _iter_blocks(result):
        if start == end:
            continue
        aligned = _aligned_block(result, start, end)
        result[start : end + 1] = aligned
    return result
