"""
Declaration hoisting checks (check-only, no auto-fix).

CF014  Top-level variable/constant declarations must appear before any
       top-level class or function definition.

CF015  Class-body variable/annotation declarations must appear before
       any method or nested class definition.

Algorithm
---------
Both rules use the same two-phase scan on a direct body statement list:

  Phase 1 – scan forward; record the first lineno where a "barrier" node
             (ClassDef / FunctionDef / AsyncFunctionDef for CF014; the same
             plus nested ClassDef for CF015) appears.
  Phase 2 – any Assign / AnnAssign whose lineno is AFTER the barrier is
             a violation.

Special cases
-------------
- Imports (Import, ImportFrom) are transparent for CF014: they may appear
  anywhere without triggering the barrier or being flagged.
- ``if __name__ == "__main__":`` blocks are transparent: they are neither
  declarations nor barriers.
- Blank lines and comment lines do not appear as AST statements, so they
  are naturally ignored.
- Only *direct* body nodes are inspected (not assignments inside functions).
- AnnAssign with a None value (bare annotation ``x: int`` with no =)
  counts as a declaration for both CF014 and CF015.
"""

from __future__ import annotations

import ast
from pathlib import Path

from customfmt.types import Violation

RULE_CF014 = "CF014"
RULE_CF015 = "CF015"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _IsMainGuard(node: ast.stmt) -> bool:
   """
   Return True if *node* is an ``if __name__ == "__main__":`` block.
   We recognise both orderings of the comparison.
   """
   if not isinstance(node, ast.If):
      return False
   test = node.test
   if not isinstance(test, ast.Compare):
      return False
   if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
      return False
   operands = [test.left, *test.comparators]
   names = {o.id if isinstance(o, ast.Name) else None for o in operands}
   strings = {
      o.value if isinstance(o, ast.Constant) and isinstance(o.value, str) else None
      for o in operands
   }
   return "__name__" in names and "__main__" in strings


def _IsDeclaration(node: ast.stmt) -> bool:
   """Return True if *node* is an Assign or AnnAssign."""
   return isinstance(node, (ast.Assign, ast.AnnAssign))


def _IsBarrierCF014(node: ast.stmt) -> bool:
   """
   Return True if *node* is a top-level barrier for CF014:
   a ClassDef, FunctionDef, or AsyncFunctionDef.
   Imports and __name__ guards are transparent.
   """
   return isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))


def _IsBarrierCF015(node: ast.stmt) -> bool:
   """
   Return True if *node* is a class-body barrier for CF015:
   a FunctionDef, AsyncFunctionDef, or nested ClassDef.
   """
   return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))


def _DeclarationName(node: ast.stmt) -> str:
   """Return a human-readable name for a declaration node."""
   if isinstance(node, ast.Assign):
      targets = []
      for t in node.targets:
         if isinstance(t, ast.Name):
            targets.append(t.id)
         else:
            targets.append("?")
      return ", ".join(targets)
   if isinstance(node, ast.AnnAssign):
      if isinstance(node.target, ast.Name):
         return node.target.id
      return "?"
   return "?"


# ---------------------------------------------------------------------------
# CF014 – module-level hoisting
# ---------------------------------------------------------------------------


def _CheckModuleLevel(tree: ast.Module, path: Path) -> list[Violation]:
   """
   Scan tree.body for CF014 violations.
   """
   violations: list[Violation] = []
   barrier_lineno: int | None = None

   for node in tree.body:
      # Imports and __name__ guards are transparent — skip both directions.
      if isinstance(node, (ast.Import, ast.ImportFrom)):
         continue
      if _IsMainGuard(node):
         continue

      if _IsBarrierCF014(node):
         if barrier_lineno is None:
            barrier_lineno = node.lineno
         continue

      if _IsDeclaration(node) and barrier_lineno is not None:
         name = _DeclarationName(node)
         violations.append(
            Violation(
               path,
               node.lineno,
               node.col_offset + 1,
               RULE_CF014,
               f"top-level declaration {name!r} must appear before "
               f"class/function definitions (first definition at line "
               f"{barrier_lineno})",
            )
         )

   return violations


# ---------------------------------------------------------------------------
# CF015 – class-body hoisting
# ---------------------------------------------------------------------------


def _CheckClassBody(class_node: ast.ClassDef, path: Path) -> list[Violation]:
   """
   Scan class_node.body for CF015 violations.
   """
   violations: list[Violation] = []
   barrier_lineno: int | None = None

   for node in class_node.body:
      if _IsBarrierCF015(node):
         if barrier_lineno is None:
            barrier_lineno = node.lineno
         continue

      if _IsDeclaration(node) and barrier_lineno is not None:
         name = _DeclarationName(node)
         violations.append(
            Violation(
               path,
               node.lineno,
               node.col_offset + 1,
               RULE_CF015,
               f"class declaration {name!r} must appear before "
               f"methods/nested classes (first method/class at line "
               f"{barrier_lineno})",
            )
         )

   return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def Check(lines: list[str], path: Path) -> list[Violation]:
   """
   Run CF014 and CF015 checks and return all violations.

   Parameters
   ----------
   lines : source lines (used only to reconstruct source for parsing).
   path  : used for Violation path fields and ast.parse filename.
   """
   source = "".join(lines)
   try:
      tree = ast.parse(source, filename=str(path))
   except SyntaxError:
      return []

   violations: list[Violation] = []

   # CF014 — module level
   violations.extend(_CheckModuleLevel(tree, path))

   # CF015 — every direct ClassDef in the module (top-level only;
   # we do NOT recurse into classes inside functions)
   for node in tree.body:
      if isinstance(node, ast.ClassDef):
         violations.extend(_CheckClassBody(node, path=path))

   return sorted(violations)
