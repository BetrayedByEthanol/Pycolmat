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
- Skips any block where ANY line's RHS starts a multi-line expression,
  i.e. where the RHS (stripped of inline comment) ends with (, [, {, or backslash.
"""

from __future__ import annotations

import re
from pathlib import Path

from customfmt.types import Violation

# Matches:  <indent>self.<attr> = <rhs>
# Does NOT match augmented assigns (+=, -=, …) or == comparisons.
_RE = re.compile(r"^( *)(self\.[A-Za-z_][A-Za-z0-9_]*) *(=(?!=)) *(.*)")

RULE_CODE = "CF009"

# Characters at the end of a stripped RHS that indicate the expression
# continues on the next line — we must not align such blocks.
_MULTILINE_OPENERS = frozenset("([{\\")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _Parse(line: str) -> re.Match | None:
   return _RE.match(line)


def _RhsIsMultilineOpener(rhs: str) -> bool:
   """
   Return True if *rhs* (the right-hand side text captured from the regex)
   appears to open a multi-line expression.

   We strip inline comments before checking, then look at the last
   non-whitespace character.  Endings of (, [, {, or \\ are treated as
   multi-line openers.
   """
   # Strip a trailing inline comment:  anything after an unquoted '#'.
   # A simple heuristic: find the first # not inside a string.
   # For safety we use a conservative approach: strip from the last '#'
   # only when it is preceded by whitespace (i.e. clearly a comment).
   rhs_stripped = rhs.rstrip()
   # Remove a trailing "  # comment" portion
   comment_pos = _FindCommentStart(rhs_stripped)
   if comment_pos is not None:
      rhs_stripped = rhs_stripped[:comment_pos].rstrip()
   return bool(rhs_stripped) and rhs_stripped[-1] in _MULTILINE_OPENERS


def _FindCommentStart(text: str) -> int | None:
   """
   Return the index of the first '#' that starts an inline comment
   (i.e. preceded by whitespace or is at position 0 after stripping),
   or None if no such '#' exists.

   This is deliberately conservative — if a '#' is inside a string we
   might miss it, but false negatives here just mean we conservatively
   skip alignment, which is safe.
   """
   in_single = False
   in_double = False
   i = 0
   while i < len(text):
      c = text[i]
      if c == "'" and not in_double:
         in_single = not in_single
      elif c == '"' and not in_single:
         in_double = not in_double
      elif c == "#" and not in_single and not in_double:
         return i
      i += 1
   return None


def _BlockHasMultilineOpener(lines: list[str], start: int, end: int) -> bool:
   """Return True if any line in the block starts a multi-line expression."""
   for i in range(start, end + 1):
      m = _Parse(lines[i])
      if m and _RhsIsMultilineOpener(m.group(4)):
         return True
   return False


def _IterBlocks(lines: list[str]) -> list[tuple[int, int]]:
   """
   Return (start, end) index pairs (inclusive, 0-based) for every
   contiguous run of self-assignment lines sharing the same indent.
   Blocks where any RHS opens a multi-line expression are excluded.
   """
   blocks: list[tuple[int, int]] = []
   i = 0
   n = len(lines)
   while i < n:
      m = _Parse(lines[i])
      if not m:
         i += 1
         continue
      indent = m.group(1)
      start = i
      j = i + 1
      while j < n:
         m2 = _Parse(lines[j])
         if m2 and m2.group(1) == indent:
            j += 1
         else:
            break
      end = j - 1
      # Only include the block if no line opens a multi-line expression.
      if not _BlockHasMultilineOpener(lines, start, end):
         blocks.append((start, end))
      i = j
   return blocks


def _AlignedBlock(lines: list[str], start: int, end: int) -> list[str]:
   """Return the slice lines[start..end] with = signs column-aligned."""
   block = lines[start : end + 1]
   parsed = [_Parse(line) for line in block]  # all match
   max_lhs = max(
      len(m.group(1)) + len(m.group(2))
      for m in parsed  # type: ignore[union-attr]
   )

   result = []
   for m in parsed:
      indent = m.group(1)  # type: ignore[union-attr]
      attr = m.group(2)  # type: ignore[union-attr]
      rhs = m.group(4)  # type: ignore[union-attr]
      pad = " " * (max_lhs - len(indent) - len(attr))
      result.append(f"{indent}{attr}{pad} = {rhs}\n")
   return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def Check(lines: list[str], path: Path) -> list[Violation]:
   """Return CF009 violations (misaligned blocks).

   Uses the same block-detection logic as fix(), so CF009 is only reported
   for blocks that fix() would actually touch.
   """
   violations: list[Violation] = []
   for start, end in _IterBlocks(lines):
      if start == end:
         continue  # single-line block: nothing to align
      aligned = _AlignedBlock(lines, start, end)
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


def Fix(lines: list[str]) -> list[str]:
   """Return a new list of lines with all self-assign blocks aligned."""
   result = list(lines)
   for start, end in _IterBlocks(result):
      if start == end:
         continue
      aligned = _AlignedBlock(result, start, end)
      result[start : end + 1] = aligned
   return result
