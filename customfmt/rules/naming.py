"""
Naming rules (AST-based):

CF001  file name must be snake_case.py
CF002  class name must be PascalCase
CF003  function and method names must be PascalCase
CF004  parameter names must be snake_case (except self/cls)
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
from pathlib import Path
from typing import Iterator

from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------------

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$|^[a-z]$")
_PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$|^[A-Z]$")
_SNAKE_FILE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*\.py$|^[a-z]\.py$")


def _is_snake(name: str) -> bool:
    return bool(_SNAKE_RE.match(name))


def _is_pascal(name: str) -> bool:
    return bool(_PASCAL_RE.match(name))


def _is_upper(name: str) -> bool:
    return bool(_UPPER_RE.match(name))


def _is_snake_filename(name: str) -> bool:
    return bool(_SNAKE_FILE_RE.match(name))


# ---------------------------------------------------------------------------
# Literal detection
# ---------------------------------------------------------------------------

def _is_literal(node: ast.expr) -> bool:
    """Return True if *node* is a compile-time literal constant."""
    match node:
        case ast.Constant():
            return True
        case ast.Tuple(elts=elts) | ast.List(elts=elts) | ast.Set(elts=elts):
            return all(_is_literal(e) for e in elts)
        case ast.Dict(keys=keys, values=values):
            return all(
                (k is None or _is_literal(k)) and _is_literal(v)
                for k, v in zip(keys, values)
            )
        case _:
            return False


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def _function_nodes(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield all function/method definition nodes anywhere in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------

def check(lines: list[str], path: Path) -> list[Violation]:
    source = "".join(lines)
    violations: list[Violation] = []

    # CF001 — file name
    if not _is_snake_filename(path.name):
        violations.append(
            Violation(path, 0, 0, "CF001",
                      f"file name must be snake_case.py: {path.name!r}")
        )

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        # Can't run AST rules on unparseable source.
        return violations

    ast.fix_missing_locations(tree)

    # CF002 — class names
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if not _is_pascal(node.name):
                violations.append(
                    Violation(path, node.lineno, node.col_offset + 1,
                              "CF002",
                              f"class name must be PascalCase: {node.name!r}")
                )

    # CF003 — function/method names
    for node in _function_nodes(tree):
        if not _is_pascal(node.name):
            violations.append(
                Violation(path, node.lineno, node.col_offset + 1,
                          "CF003",
                          f"function name must be PascalCase: {node.name!r}")
            )

    # CF004 — parameter names (except self/cls)
    for fn in _function_nodes(tree):
        args = fn.args
        all_args = (
            args.posonlyargs
            + args.args
            + args.kwonlyargs
            + ([args.vararg] if args.vararg else [])
            + ([args.kwarg] if args.kwarg else [])
        )
        for arg in all_args:
            if arg.arg in ("self", "cls"):
                continue
            if not _is_snake(arg.arg):
                violations.append(
                    Violation(path, arg.lineno, arg.col_offset + 1,
                              "CF004",
                              f"parameter name must be snake_case: {arg.arg!r}")
                )

    # CF005 — local variable names (inside functions)
    for fn in _function_nodes(tree):
        for node in ast.walk(fn):
            # Simple assignments: x = …  (skip self.X, obj.attr, etc.)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    _check_store_targets(target, path, violations)

            # Augmented assignments: x += …
            elif isinstance(node, ast.AugAssign):
                _check_store_targets(node.target, path, violations)

            # for x in …
            elif isinstance(node, ast.For):
                _check_store_targets(node.target, path, violations)

            # with … as x
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars is not None:
                        _check_store_targets(item.optional_vars, path, violations)

            # except … as x
            elif isinstance(node, ast.ExceptHandler):
                if node.name and not _is_snake(node.name):
                    violations.append(
                        Violation(path, node.lineno, node.col_offset + 1,
                                  "CF005",
                                  f"local variable name must be snake_case: {node.name!r}")
                    )

    # CF006 — instance attribute names (self.X)
    for fn in _function_nodes(tree):
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                for attr_node in _iter_self_attrs(target):
                    if not _is_pascal(attr_node.attr):
                        violations.append(
                            Violation(
                                path, attr_node.lineno, attr_node.col_offset + 1,
                                "CF006",
                                f"instance attribute must be PascalCase: {attr_node.attr!r}",
                            )
                        )

    # CF007 — global constants (module-level)
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_literal(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if not _is_upper(target.id):
                        violations.append(
                            Violation(
                                path, target.lineno, target.col_offset + 1,
                                "CF007",
                                f"global constant must be UPPER_CASE: {target.id!r}",
                            )
                        )

    # CF008 — class constants (class-body level)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and _is_literal(stmt.value):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if not _is_upper(target.id):
                            violations.append(
                                Violation(
                                    path, target.lineno, target.col_offset + 1,
                                    "CF008",
                                    f"class constant must be UPPER_CASE: {target.id!r}",
                                )
                            )

    return sorted(violations)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_store_targets(
    target: ast.expr,
    path: Path,
    violations: list[Violation],
) -> None:
    """
    Walk an assignment target node and emit CF005 for any plain Name nodes
    that are not snake_case.  Attribute accesses (self.X, obj.attr) are
    deliberately skipped here (handled by CF006).
    """
    match target:
        case ast.Name(id=name):
            # Skip dunders and single-char throwaways like _ or __
            if name.startswith("_"):
                return
            if not _is_snake(name):
                violations.append(
                    Violation(
                        path, target.lineno, target.col_offset + 1,
                        "CF005",
                        f"local variable name must be snake_case: {name!r}",
                    )
                )
        case ast.Tuple(elts=elts) | ast.List(elts=elts):
            for elt in elts:
                _check_store_targets(elt, path, violations)
        case ast.Starred(value=value):
            _check_store_targets(value, path, violations)
        case ast.Attribute():
            pass  # handled by CF006
        case _:
            pass


def _iter_self_attrs(target: ast.expr) -> Iterator[ast.Attribute]:
    """Yield Attribute nodes that are direct self.X accesses."""
    match target:
        case ast.Attribute(value=ast.Name(id="self")) as attr:
            yield attr
        case ast.Tuple(elts=elts) | ast.List(elts=elts):
            for elt in elts:
                yield from _iter_self_attrs(elt)
        case _:
            return
