"""
Naming rules (AST-based):

CF001  file name must be snake_case.py
CF002  class name must be PascalCase
CF003  function and method names must be PascalCase
         Exempt: dunder methods matching ^__[A-Za-z0-9_]+__$
CF004  parameter names must be snake_case
         self/cls are only exempt when they are the FIRST positional
         parameter of a method defined directly inside a class body.
CF005  local variable names must be snake_case
CF006  instance attributes assigned as self.X must be PascalCase
CF007  global constants must be UPPER_CASE
CF008  class constants must be UPPER_CASE

Naming conventions
------------------
snake_case  : lowercase letters, digits, underscores; must not start/end with _.
PascalCase  : starts with an uppercase letter; no underscores; letters and digits only.
UPPER_CASE  : uppercase letters, digits, underscores; must not start/end with _.

Constant detection
------------------
An assignment is treated as a constant when it is:
  - At module level (CF007) or directly in a class body (CF008), AND
  - The right-hand side is a *literal* value:
      str / int / float / bool / None /
      tuple/list/dict/set whose elements are themselves literals.
Function calls and object constructions are NOT constants.

Local variable detection (CF005)
---------------------------------
  - Simple ``name = value`` assignments inside functions/methods.
  - for-loop target names.
  - with-as target names.
  - except-as target names.
  - Does NOT include imported names.
  - Does NOT include attributes (self.X handled by CF006).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------------

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$|^[a-z]$")
_PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$|^[A-Z]$")
_SNAKE_FILE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*\.py$|^[a-z]\.py$")
_DUNDER_RE = re.compile(r"^__[A-Za-z0-9_]+__$")


def _IsSnake(name: str) -> bool:
   return bool(_SNAKE_RE.match(name))


def _IsPascal(name: str) -> bool:
   """Return True if name is PascalCase, allowing leading underscores (_Foo, __Foo)."""
   stripped = name.lstrip("_")
   if not stripped:
      return False
   return bool(_PASCAL_RE.match(stripped))


def _IsUpper(name: str) -> bool:
   return bool(_UPPER_RE.match(name))


def _IsSnakeFilename(name: str) -> bool:
   return bool(_SNAKE_FILE_RE.match(name))


def _IsDunder(name: str) -> bool:
   """Return True for names like __init__, __str__, __repr__, etc."""
   return bool(_DUNDER_RE.match(name))


# ---------------------------------------------------------------------------
# Literal detection
# ---------------------------------------------------------------------------


def _IsLiteral(node: ast.expr) -> bool:
   """Return True if *node* is a compile-time literal constant."""
   match node:
      case ast.Constant():
         return True
      case ast.Tuple(elts=elts) | ast.List(elts=elts) | ast.Set(elts=elts):
         return all(_IsLiteral(e) for e in elts)
      case ast.Dict(keys=keys, values=values):
         return all((k is None or _IsLiteral(k)) and _IsLiteral(v) for k, v in zip(keys, values))
      case _:
         return False


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------


def _FunctionNodes(
   tree: ast.Module,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
   """Yield all function/method definition nodes anywhere in the tree."""
   for node in ast.walk(tree):
      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
         yield node


def _ClassMethodSet(tree: ast.Module) -> set[int]:
   """
   Return the set of AST node ids for functions that are *direct* methods
   of a class (i.e. appear in a ClassDef.body, not in nested functions).
   """
   method_ids: set[int] = set()
   for node in ast.walk(tree):
      if isinstance(node, ast.ClassDef):
         for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
               method_ids.add(id(stmt))
   return method_ids


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------


def Check(lines: list[str], path: Path) -> list[Violation]:
   source = "".join(lines)
   violations: list[Violation] = []

   # CF001 — file name  (line=1, col=1 per spec)
   # Exempt dunder filenames like __init__.py and __main__.py — these are
   # required Python conventions that cannot be renamed.
   if not _IsSnakeFilename(path.name) and not _IsDunder(path.stem):
      violations.append(
         Violation(
            path,
            1,
            1,
            "CF001",
            f"file name must be snake_case.py: {path.name!r}",
         )
      )

   try:
      tree = ast.parse(source, filename=str(path))
   except SyntaxError:
      # Can't run AST rules on unparseable source.
      return violations

   ast.fix_missing_locations(tree)

   # Pre-compute which function nodes are direct class methods (for CF004).
   class_methods = _ClassMethodSet(tree)

   # CF002 — class names
   for node in ast.walk(tree):
      if isinstance(node, ast.ClassDef):
         if not _IsPascal(node.name):
            violations.append(
               Violation(
                  path,
                  node.lineno,
                  node.col_offset + 1,
                  "CF002",
                  f"class name must be PascalCase: {node.name!r}",
               )
            )

   # CF003 — function/method names (dunders are exempt)
   for node in _FunctionNodes(tree):
      if _IsDunder(node.name):
         continue
      if not _IsPascal(node.name):
         violations.append(
            Violation(
               path,
               node.lineno,
               node.col_offset + 1,
               "CF003",
               f"function name must be PascalCase: {node.name!r}",
            )
         )

   # CF004 — parameter names
   # self/cls are exempt ONLY when they are the first positional argument of
   # a direct class method.  In any other position they must be treated as
   # ordinary parameter names.
   #
   # Note: "self" and "cls" ARE valid snake_case, so we must explicitly flag
   # them when they appear outside the exempt position.
   for fn in _FunctionNodes(tree):
      is_class_method = id(fn) in class_methods
      args = fn.args
      # Ordered list of all positional args (posonlyargs first, then args).
      positional = args.posonlyargs + args.args
      # All args that need checking: positional + kwonly + *vararg + **kwarg.
      all_args = (
         positional
         + args.kwonlyargs
         + ([args.vararg] if args.vararg else [])
         + ([args.kwarg] if args.kwarg else [])
      )
      first_positional_name = positional[0].arg if positional else None
      for arg in all_args:
         name = arg.arg
         # Determine whether this is the exempt self/cls slot.
         is_exempt_self_cls = (
            is_class_method and name in ("self", "cls") and name == first_positional_name
         )
         if is_exempt_self_cls:
            continue
         # self/cls in a non-exempt position must be flagged explicitly
         # (they are valid snake_case but should not appear here).
         if name in ("self", "cls") and not is_exempt_self_cls:
            violations.append(
               Violation(
                  path,
                  arg.lineno,
                  arg.col_offset + 1,
                  "CF004",
                  f"parameter name must be snake_case: {name!r}",
               )
            )
            continue
         if not _IsSnake(name):
            violations.append(
               Violation(
                  path,
                  arg.lineno,
                  arg.col_offset + 1,
                  "CF004",
                  f"parameter name must be snake_case: {name!r}",
               )
            )

   # CF005 — local variable names (inside functions)
   for fn in _FunctionNodes(tree):
      for node in ast.walk(fn):
         # Simple assignments: x = …  (skip self.X, obj.attr, etc.)
         if isinstance(node, ast.Assign):
            for target in node.targets:
               _CheckStoreTargets(target, path, violations)
         elif isinstance(node, ast.AugAssign):
            _CheckStoreTargets(node.target, path, violations)
         elif isinstance(node, ast.For):
            _CheckStoreTargets(node.target, path, violations)
         elif isinstance(node, ast.With):
            for item in node.items:
               if item.optional_vars is not None:
                  _CheckStoreTargets(item.optional_vars, path, violations)
         elif isinstance(node, ast.ExceptHandler):
            if node.name and not _IsSnake(node.name):
               violations.append(
                  Violation(
                     path,
                     node.lineno,
                     node.col_offset + 1,
                     "CF005",
                     f"local variable name must be snake_case: {node.name!r}",
                  )
               )

   # CF006 — instance attribute names (self.X)
   for fn in _FunctionNodes(tree):
      for node in ast.walk(fn):
         if not isinstance(node, ast.Assign):
            continue
         for target in node.targets:
            for attr_node in _IterSelfAttrs(target):
               if not _IsPascal(attr_node.attr):
                  violations.append(
                     Violation(
                        path,
                        attr_node.lineno,
                        attr_node.col_offset + 1,
                        "CF006",
                        f"instance attribute must be PascalCase: {attr_node.attr!r}",
                     )
                  )

   # CF007 — global constants (module-level)
   # Exempt dunder names (__version__, __all__, __author__, etc.) — these
   # are Python ecosystem conventions that cannot be renamed.
   for node in tree.body:
      if isinstance(node, ast.Assign) and _IsLiteral(node.value):
         for target in node.targets:
            if isinstance(target, ast.Name):
               if _IsDunder(target.id):
                  continue
               if not _IsUpper(target.id):
                  violations.append(
                     Violation(
                        path,
                        target.lineno,
                        target.col_offset + 1,
                        "CF007",
                        f"global constant must be UPPER_CASE: {target.id!r}",
                     )
                  )

   # CF008 — class constants (class-body level)
   for node in ast.walk(tree):
      if not isinstance(node, ast.ClassDef):
         continue
      for stmt in node.body:
         if isinstance(stmt, ast.Assign) and _IsLiteral(stmt.value):
            for target in stmt.targets:
               if isinstance(target, ast.Name):
                  if not _IsUpper(target.id):
                     violations.append(
                        Violation(
                           path,
                           target.lineno,
                           target.col_offset + 1,
                           "CF008",
                           f"class constant must be UPPER_CASE: {target.id!r}",
                        )
                     )

   return sorted(violations)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _CheckStoreTargets(
   target: ast.expr,
   path: Path,
   violations: list[Violation],
) -> None:
   """
   Walk an assignment target and emit CF005 for non-snake_case Name nodes.
   Attribute accesses (self.X) are skipped here (handled by CF006).
   """
   match target:
      case ast.Name(id=name):
         # Skip dunders and single-char throwaways like _ or __
         if name.startswith("_"):
            return
         if not _IsSnake(name):
            violations.append(
               Violation(
                  path,
                  target.lineno,
                  target.col_offset + 1,
                  "CF005",
                  f"local variable name must be snake_case: {name!r}",
               )
            )
      case ast.Tuple(elts=elts) | ast.List(elts=elts):
         for elt in elts:
            _CheckStoreTargets(elt, path, violations)
      case ast.Starred(value=value):
         _CheckStoreTargets(value, path, violations)
      case ast.Attribute():
         pass
      case _:
         pass


def _IterSelfAttrs(target: ast.expr) -> Iterator[ast.Attribute]:
   """Yield Attribute nodes that are direct self.X accesses."""
   match target:
      case ast.Attribute(value=ast.Name(id="self")) as attr:
         yield attr
      case ast.Tuple(elts=elts) | ast.List(elts=elts):
         for elt in elts:
            yield from _IterSelfAttrs(elt)
      case _:
         return
