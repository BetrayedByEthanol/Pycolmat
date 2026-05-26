"""
Rule: class-body declaration alignment (auto-fix + CF013 check-only).

Aligns contiguous blocks of DIRECT ClassDef.body declarations so that
the name, colon, annotation, and equals-sign columns all line up.

Supported declaration forms
---------------------------
  Assign    :  Name = value
  AnnAssign :  Name: Type
  AnnAssign :  Name: Type = value

Block detection
---------------
The rule uses ast.parse to identify which source lines belong to a direct
ClassDef.body (i.e. not inside a nested function or class).  Only those
line ranges are considered.  Within each class body, contiguous runs of
Assign / AnnAssign nodes whose targets are simple Names form a block.

A block is split by:
  - blank lines or comment-only lines between declarations
  - any other statement (def, pass, …)

Safety exclusions
-----------------
- Multiline declarations (ann or value text ends with (, [, {, backslash):  skipped.
- self.X patterns: excluded by name-target check (dots excluded).
- Nested function / class bodies: excluded by AST scope check.
- Single-node blocks: never a violation.

Formatting rules
----------------
CASE A — assignment-only block (no AnnAssign in block):
  <indent><name padded to max_name_width> = <value>

CASE B — typed or mixed block (at least one AnnAssign):
  AnnAssign without value:
    <indent><name padded> : <annotation>
  AnnAssign with value:
    <indent><name padded> : <annotation padded to max_ann_width> = <value>
  Assign (no annotation) inside a typed block:
    <indent><name padded><3 + max_ann_width spaces> = <value>
  So all ":" align and all "=" align.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from customfmt.types import Violation

RULE_CODE = "CF013"

_MULTILINE_OPENERS = frozenset("([{\\")


_RE_ASSIGN_VALUE = re.compile(r"^[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]+=[ \t]+(.+)")
_RE_ANN_VAL_PARTS = re.compile(r"^[ \t]*[A-Za-z_][A-Za-z0-9_]*\s*:\s*([^=\n]+?)\s*=\s*(.+)")
_RE_ANN_ONLY_PARTS = re.compile(r"^[ \t]*[A-Za-z_][A-Za-z0-9_]*\s*:\s*([^=\n]+?)\s*$")


def _EndsWithOpener(text: str) -> bool:
   stripped = text.rstrip()
   return bool(stripped) and stripped[-1] in _MULTILINE_OPENERS


# ---------------------------------------------------------------------------
# Parsed declaration
# ---------------------------------------------------------------------------


class _Decl:
   """One parsed class-body declaration line."""

   def __init__(
      self,
      kind: str,
      indent: str,
      name: str,
      ann: str,
      value: str,
      lineno: int,
      raw_line: str,
   ) -> None:
      self.Kind    = kind  # "assign" | "ann_only" | "ann_val"
      self.Indent  = indent
      self.Name    = name
      self.Ann     = ann
      self.Value   = value
      self.Lineno  = lineno  # 1-based
      self.RawLine = raw_line


# ---------------------------------------------------------------------------
# AST-based block discovery
# ---------------------------------------------------------------------------


def _GetDirectClassBodyRanges(
   source: str,
) -> list[tuple[int, int]]:
   """
   Return (start_lineno, end_lineno) pairs (1-based, inclusive) for every
   direct ClassDef.body.  Lines inside nested functions or nested classes
   are NOT included.
   """
   try:
      tree = ast.parse(source)
   except SyntaxError:
      return []

   ranges: list[tuple[int, int]] = []

   def _Visit(node: ast.AST, in_function: bool) -> None:
      if isinstance(node, ast.ClassDef) and not in_function:
         # Collect the range of direct body statements.
         for stmt in node.body:
            lo = stmt.lineno
            hi = stmt.end_lineno or stmt.lineno  # type: ignore[attr-defined]
            ranges.append((lo, hi))
         # Recurse into the class body, marking nested functions.
         for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
               _Visit(stmt, in_function=True)
            elif isinstance(stmt, ast.ClassDef):
               _Visit(stmt, in_function=False)
      elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
         # Recurse into function body — any class defined here is still
         # handled, but its body lines stay excluded from class-body ranges.
         for child in ast.walk(node):
            if child is node:
               continue
            if isinstance(child, ast.ClassDef):
               _Visit(child, in_function=True)
      else:
         for child in ast.iter_child_nodes(node):
            _Visit(child, in_function=in_function)

   _Visit(tree, in_function=False)
   return ranges


def _ParseDeclFromNode(
   node: ast.stmt,
   lines: list[str],
) -> _Decl | None:
   """
   Try to parse *node* as a class-body declaration.
   Returns None if:
   - node is not Assign or AnnAssign
   - target is not a simple Name (or has a dot)
   - declaration spans multiple source lines
   - annotation or value ends with a multiline opener
   """
   line_idx = node.lineno - 1  # 0-based index into lines[]
   end_line = getattr(node, "end_lineno", node.lineno)

   # Only single-line declarations
   if end_line != node.lineno:
      return None

   raw = lines[line_idx] if line_idx < len(lines) else ""
   indent = raw[: len(raw) - len(raw.lstrip())]

   if isinstance(node, ast.Assign):
      # Must be a single simple Name target (no dots, no tuples)
      if len(node.targets) != 1:
         return None
      tgt = node.targets[0]
      if not isinstance(tgt, ast.Name):
         return None
      name = tgt.id
      # Extract value text from source line
      value = _ExtractAssignValue(raw, name)
      if value is None or _EndsWithOpener(value):
         return None
      return _Decl("assign", indent, name, "", value, node.lineno, raw)

   if isinstance(node, ast.AnnAssign):
      # Target must be a simple Name
      if not isinstance(node.target, ast.Name):
         return None
      name = node.target.id
      ann_text, value_text = _ExtractAnnParts(raw, name)
      if ann_text is None:
         return None
      if _EndsWithOpener(ann_text):
         return None
      if value_text is not None and _EndsWithOpener(value_text):
         return None
      if value_text is None:
         return _Decl("ann_only", indent, name, ann_text, "", node.lineno, raw)
      return _Decl("ann_val", indent, name, ann_text, value_text, node.lineno, raw)

   return None


def _ExtractAssignValue(raw: str, name: str) -> str | None:
   m = _RE_ASSIGN_VALUE.match(raw)
   if not m:
      return None
   return m.group(1).rstrip("\n").rstrip()


def _ExtractAnnParts(raw: str, name: str) -> tuple[str | None, str | None]:
   """Return (annotation_text, value_text_or_None)."""
   m = _RE_ANN_VAL_PARTS.match(raw)
   if m:
      return m.group(1).strip(), m.group(2).rstrip("\n").rstrip()
   m = _RE_ANN_ONLY_PARTS.match(raw)
   if m:
      return m.group(1).strip(), None
   return None, None


# ---------------------------------------------------------------------------
# Block grouping within a class body
# ---------------------------------------------------------------------------


def _GroupIntoBlocks(
   stmts: list[ast.stmt],
   lines: list[str],
) -> list[list[_Decl]]:
   """
   Walk the direct body statements in order.  Group consecutive parseable
   single-line declarations into blocks; any non-matching statement or gap
   caused by blank/comment lines breaks the current block.
   """
   blocks: list[list[_Decl]] = []
   current: list[_Decl] = []
   prev_lineno: int | None = None

   for stmt in stmts:
      decl = _ParseDeclFromNode(stmt, lines)
      if decl is None:
         if current:
            blocks.append(current)
            current = []
         prev_lineno = None
         continue

      # Check for blank/comment lines between this and previous decl
      if prev_lineno is not None:
         gap_start = prev_lineno  # 0-based index after previous decl
         gap_end = stmt.lineno - 1  # 0-based index of this stmt
         for li in range(gap_start, gap_end):
            line = lines[li].strip()
            if line == "" or line.startswith("#"):
               # Gap contains blank/comment — break the block
               if current:
                  blocks.append(current)
                  current = []
               prev_lineno = None
               break

      current.append(decl)
      prev_lineno = stmt.lineno

   if current:
      blocks.append(current)

   # Only multi-declaration blocks need alignment
   return [b for b in blocks if len(b) > 1]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _FormatBlock(decls: list[_Decl]) -> list[str]:
   """Return formatted lines for *decls*."""
   indent = decls[0].Indent
   has_typed = any(d.Kind in ("ann_only", "ann_val") for d in decls)

   max_name = max(len(d.Name) for d in decls)
   max_ann = max((len(d.Ann) for d in decls if d.Ann), default=0) if has_typed else 0

   result: list[str] = []

   if not has_typed:
      # CASE A: assignment-only
      for d in decls:
         pad = " " * (max_name - len(d.Name))
         result.append(f"{indent}{d.Name}{pad} = {d.Value}\n")
      return result

   # CASE B: typed or mixed
   for d in decls:
      name_pad = " " * (max_name - len(d.Name))
      if d.Kind == "ann_only":
         result.append(f"{indent}{d.Name}{name_pad} : {d.Ann}\n")
      elif d.Kind == "ann_val":
         ann_pad = " " * (max_ann - len(d.Ann))
         result.append(f"{indent}{d.Name}{name_pad} : {d.Ann}{ann_pad} = {d.Value}\n")
      else:
         # Plain assign: skip annotation column so "=" aligns with ann_val
         ann_col = " " * (3 + max_ann)
         result.append(f"{indent}{d.Name}{name_pad}{ann_col} = {d.Value}\n")

   return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _GetBlocks(
   lines: list[str],
) -> list[tuple[list[_Decl], list[str]]]:
   """
   Return (decls, formatted_lines) pairs for every alignment block.
   """
   source = "".join(lines)
   pairs: list[tuple[list[_Decl], list[str]]] = []

   try:
      tree = ast.parse(source)
   except SyntaxError:
      return pairs

   def _ProcessClass(class_node: ast.ClassDef, in_function: bool) -> None:
      if in_function:
         return
      blocks = _GroupIntoBlocks(class_node.body, lines)
      for block in blocks:
         pairs.append((block, _FormatBlock(block)))
      # Recurse into nested classes (not inside functions)
      for stmt in class_node.body:
         if isinstance(stmt, ast.ClassDef):
            _ProcessClass(stmt, in_function=False)

   def _Walk(node: ast.AST, in_function: bool) -> None:
      if isinstance(node, ast.ClassDef):
         _ProcessClass(node, in_function=in_function)
      elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
         for child in ast.walk(node):
            if child is node:
               continue
            if isinstance(child, ast.ClassDef):
               _ProcessClass(child, in_function=True)
      else:
         for child in ast.iter_child_nodes(node):
            _Walk(child, in_function)

   _Walk(tree, in_function=False)
   return pairs


def Check(lines: list[str], path: Path) -> list[Violation]:
   """Return CF013 violations (misaligned class-body declaration blocks)."""
   violations: list[Violation] = []
   for decls, formatted in _GetBlocks(lines):
      for decl, fmt_line in zip(decls, formatted):
         if decl.RawLine != fmt_line:
            msg = "class declaration block is not aligned"
            violations.append(Violation(path, decl.Lineno, 1, RULE_CODE, msg))
   return violations


def Fix(lines: list[str]) -> list[str]:
   """Return a new list of lines with all class-body declaration blocks aligned."""
   result = list(lines)
   for decls, formatted in _GetBlocks(lines):
      for decl, fmt_line in zip(decls, formatted):
         result[decl.Lineno - 1] = fmt_line
   return result
