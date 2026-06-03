"""
Deprecated safe local-variable renamer for customfmt.

rename_plan.py is the authoritative implementation for current rename
planning.  This module is retained only for legacy imports/tests.

Implements ``customfmt rename``:
  --check   report candidates, exit 1 if any
  --diff    print unified diff, exit 0
  --apply   write changes, exit 0

Scope
-----
Only renames CF005 violations: non-snake_case *local* variables defined
inside a function or method body.  Specifically:
  - simple assignment targets  (x = ...)
  - for-loop targets           (for x in ...)
  - with-as targets            (with ... as x)
  - except-as targets          (except E as x)

Does NOT rename: functions, methods, classes, parameters, constants,
instance attributes, imports, globals, or nonlocals.

Safety checks (per function scope)
-----------------------------------
Skip the entire function if it contains:
  - a ``global`` or ``nonlocal`` statement
  - a call to bare locals(), globals(), vars(), eval(), or exec()
    (attribute calls like obj.locals() are NOT flagged)

Skip a specific rename if:
  - the snake_case target name already exists as a local, parameter,
    imported name, or builtin used in the function
  - two different bad names would map to the same snake_case name

Nested functions / classes are not entered; each top-level function
scope is processed independently.

Implementation
--------------
1. Token pre-pass: build a set of all NAME token positions in the source,
   keyed by (name_string, line, col), so we can resolve exact positions
   for AST nodes (especially ExceptHandler.name which has no Name node).
2. AST pass: collect definition sites and all reference sites for each
   local name in each function, applying all safety checks.
3. Token rewrite: rewrite only NAME tokens whose (line, col) is in the
   set of known definition + reference sites.  No string or comment
   content is ever touched.
"""

from __future__ import annotations

import ast
import builtins
import difflib
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from customfmt.io import ReadUtf8Text
from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$|^[a-z]$")
_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins))
# Only bare-name calls trigger the safety guard, NOT attribute calls like obj.locals()
_UNSAFE_BARE_CALLS: frozenset[str] = frozenset({"locals", "globals", "vars", "eval", "exec"})


def _IsSnake(name: str) -> bool:
   return bool(_SNAKE_RE.match(name))


def _ToSnake(name: str) -> str:
   """Convert a PascalCase or camelCase name to snake_case."""
   s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
   s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
   return s.lower()


# ---------------------------------------------------------------------------
# Token position map
# ---------------------------------------------------------------------------

def _BuildTokenPositionMap(source: str) -> dict[tuple[str, int, int], bool]:
   """
   Tokenise *source* and return a set of (name, line, col) for every
   NAME token, as a dict keyed by (name, line, col) -> True.
   Lines are 1-based; cols are 0-based (matching AST convention).
   """
   pos_map: dict[tuple[str, int, int], bool] = {}
   try:
      for tok in tokenize.generate_tokens(io.StringIO(source).readline):
         if tok.type == tokenize.NAME:
            pos_map[(tok.string, tok.start[0], tok.start[1])] = True
   except tokenize.TokenError:
      pass
   return pos_map


def _FindNameToken(
   pos_map: dict[tuple[str, int, int], bool],
   name: str,
   hint_line: int,
) -> tuple[int, int] | None:
   """
   Find the first token for *name* on *hint_line*.
   Returns (line, col) or None if not found.
   """
   # Scan all cols on the hint line
   candidates = [
      (ln, co) for (nm, ln, co) in pos_map if nm == name and ln == hint_line
   ]
   if candidates:
      return min(candidates)
   return None


# ---------------------------------------------------------------------------
# AST analysis
# ---------------------------------------------------------------------------

@dataclass
class _RenameCandidate:
   """One rename within one function scope."""
   old_name : str
   new_name : str
   sites    : set[tuple[int, int]]  # (line, col) of every NAME token to rewrite


@dataclass
class _FunctionAnalysis:
   """Result of analysing one function scope."""
   candidates : list[_RenameCandidate]     = field(default_factory=list)
   patch_map  : dict[tuple[int, int], str] = field(default_factory=dict)


def _CollectLocalDefs(
   fn: ast.FunctionDef | ast.AsyncFunctionDef,
   pos_map: dict[tuple[str, int, int], bool],
) -> dict[str, list[tuple[int, int]]]:
   """
   Walk *fn* (not nested scopes) and return each locally-defined name
   mapped to its definition (line, col) sites.

   ExceptHandler.name positions are resolved via *pos_map* because the
   AST does not provide a Name node for the bound exception variable.
   """
   defs: dict[str, list[tuple[int, int]]] = {}

   def _Add(name: str, line: int, col: int) -> None:
      defs.setdefault(name, []).append((line, col))

   def _WalkTarget(node: ast.expr) -> None:
      match node:
         case ast.Name(id=nm, lineno=ln, col_offset=co):
            _Add(nm, ln, co)
         case ast.Tuple(elts=elts) | ast.List(elts=elts):
            for e in elts:
               _WalkTarget(e)
         case ast.Starred(value=v):
            _WalkTarget(v)

   for node in ast.walk(fn):
      if node is not fn and isinstance(
         node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
      ):
         continue
      match node:
         case ast.Assign(targets=targets):
            for tgt in targets:
               _WalkTarget(tgt)
         case ast.AugAssign(target=target):
            _WalkTarget(target)
         case ast.For(target=target):
            _WalkTarget(target)
         case ast.With(items=items):
            for item in items:
               if item.optional_vars is not None:
                  _WalkTarget(item.optional_vars)
         case ast.ExceptHandler(name=nm, lineno=ln) if nm:
            # Resolve the exact token position of the bound name.
            pos = _FindNameToken(pos_map, nm, ln)
            if pos:
               _Add(nm, pos[0], pos[1])
            else:
               _Add(nm, ln, 0)  # fallback (should rarely occur)

   return defs


def _CollectAllRefs(
   fn: ast.FunctionDef | ast.AsyncFunctionDef,
   name: str,
   pos_map: dict[tuple[str, int, int], bool],
) -> set[tuple[int, int]]:
   """
   Collect every (line, col) position of NAME tokens for *name* inside
   *fn* (excluding nested scopes).  Uses the AST for Name nodes and
   supplements with the token map for ExceptHandler bindings.
   """
   sites: set[tuple[int, int]] = set()

   for node in ast.walk(fn):
      if node is not fn and isinstance(
         node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
      ):
         continue
      if isinstance(node, ast.Name) and node.id == name:
         sites.add((node.lineno, node.col_offset))
      # ExceptHandler bound name is not an ast.Name node — use token map
      if isinstance(node, ast.ExceptHandler) and node.name == name:
         pos = _FindNameToken(pos_map, name, node.lineno)
         if pos:
            sites.add(pos)

   return sites


def _HasUnsafeGlobalNonlocal(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
   for node in ast.walk(fn):
      if node is not fn and isinstance(
         node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
      ):
         continue
      if isinstance(node, (ast.Global, ast.Nonlocal)):
         return True
   return False


def _HasUnsafeBareCall(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
   """
   Return True only if *fn* contains a bare-name call to a dangerous
   function (locals, globals, vars, eval, exec).
   Attribute calls like obj.locals() are NOT flagged.
   """
   for node in ast.walk(fn):
      if node is not fn and isinstance(
         node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
      ):
         continue
      if isinstance(node, ast.Call):
         if isinstance(node.func, ast.Name) and node.func.id in _UNSAFE_BARE_CALLS:
            return True
   return False


def _ParameterNames(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
   args = fn.args
   return {
      a.arg
      for a in (
         args.posonlyargs
         + args.args
         + args.kwonlyargs
         + ([args.vararg] if args.vararg else [])
         + ([args.kwarg]  if args.kwarg  else [])
      )
   }


def _ImportedNames(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
   names: set[str] = set()
   for node in ast.walk(fn):
      if node is not fn and isinstance(
         node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
      ):
         continue
      match node:
         case ast.Import(names=aliases):
            for a in aliases:
               names.add(a.asname if a.asname else a.name.split(".")[0])
         case ast.ImportFrom(names=aliases):
            for a in aliases:
               names.add(a.asname if a.asname else a.name)
   return names


def _AnalyseFunction(
   fn: ast.FunctionDef | ast.AsyncFunctionDef,
   pos_map: dict[tuple[str, int, int], bool],
) -> _FunctionAnalysis:
   result = _FunctionAnalysis()

   if _HasUnsafeGlobalNonlocal(fn) or _HasUnsafeBareCall(fn):
      return result

   local_defs = _CollectLocalDefs(fn, pos_map)
   params     = _ParameterNames(fn)
   imports    = _ImportedNames(fn)
   all_locals = set(local_defs.keys())

   forbidden: set[str] = all_locals | params | imports | _BUILTIN_NAMES

   # Map bad names to desired snake_case names
   bad: dict[str, str] = {}
   for name in local_defs:
      if name.startswith("_"):
         continue
      if _IsSnake(name):
         continue
      new = _ToSnake(name)
      if new == name:
         continue
      bad[name] = new

   # Skip if two bad names map to the same target
   new_name_counts: dict[str, int] = {}
   for new in bad.values():
      new_name_counts[new] = new_name_counts.get(new, 0) + 1
   colliding_new = {n for n, c in new_name_counts.items() if c > 1}

   for old_name, new_name in bad.items():
      if new_name in colliding_new:
         continue
      forbidden_for_this = forbidden - {old_name}
      if new_name in forbidden_for_this:
         continue
      all_sites = _CollectAllRefs(fn, old_name, pos_map)
      if not all_sites:
         continue
      result.candidates.append(
         _RenameCandidate(old_name=old_name, new_name=new_name, sites=all_sites)
      )
      for site in all_sites:
         result.patch_map[site] = new_name

   return result


# ---------------------------------------------------------------------------
# Token-level rewriter
# ---------------------------------------------------------------------------

def _RewriteTokens(source: str, patch_map: dict[tuple[int, int], str]) -> str:
   """
   Rewrite NAME tokens whose (line, col) appears in *patch_map*.
   All other tokens are reproduced verbatim from the original source.
   (line, col) are 1-based line, 0-based col — matching AST convention.
   """
   if not patch_map:
      return source

   tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
   out = io.StringIO()
   prev_end = (1, 0)

   for tok in tokens:
      tok_type, tok_string, tok_start, tok_end, _ = tok
      start_line, start_col = tok_start

      if tok_start != prev_end:
         src_lines = source.splitlines(keepends=True)
         gap = _ExtractGap(src_lines, prev_end, tok_start)
         out.write(gap)

      if tok_type == tokenize.NAME and (start_line, start_col) in patch_map:
         out.write(patch_map[(start_line, start_col)])
      else:
         out.write(tok_string)

      prev_end = tok_end

   return out.getvalue()


def _ExtractGap(
   src_lines: list[str],
   prev_end: tuple[int, int],
   tok_start: tuple[int, int],
) -> str:
   """Return the verbatim source text between *prev_end* and *tok_start*."""
   pe_line, pe_col = prev_end
   ts_line, ts_col = tok_start

   if pe_line == ts_line:
      line = src_lines[pe_line - 1] if pe_line <= len(src_lines) else ""
      return line[pe_col:ts_col]

   parts: list[str] = []
   if pe_line <= len(src_lines):
      parts.append(src_lines[pe_line - 1][pe_col:])
   for ln in range(pe_line + 1, ts_line):
      if ln <= len(src_lines):
         parts.append(src_lines[ln - 1])
   if ts_line <= len(src_lines):
      parts.append(src_lines[ts_line - 1][:ts_col])
   return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class RenameResult:
   """Result of processing one file."""
   path       : Path
   candidates : list[_RenameCandidate]
   original   : str
   rewritten  : str

   @property
   def Changed(self) -> bool:
      return self.rewritten != self.original

   def Violations(self) -> list[Violation]:
      viols: list[Violation] = []
      for cand in self.candidates:
         line, col = min(cand.sites)
         viols.append(
            Violation(
               self.path,
               line,
               col + 1,
               "RENAME",
               f"local variable {cand.old_name!r} -> {cand.new_name!r}",
            )
         )
      return sorted(viols)

   def UnifiedDiff(self) -> str:
      return "".join(
         difflib.unified_diff(
            self.original.splitlines(keepends=True),
            self.rewritten.splitlines(keepends=True),
            fromfile=f"a/{self.path}",
            tofile=f"b/{self.path}",
         )
      )


def AnalyseFile(path: Path) -> RenameResult:
   """
   Parse *path*, find all safe rename candidates, and compute the rewritten
   source.  Does not write anything.

   Raises
   ------
   ValueError          if the file has a UTF-8 BOM.
   UnicodeDecodeError  if the file is not valid UTF-8.
   SyntaxError         if the file cannot be parsed as Python.
   OSError             on I/O failure.
   """
   source = ReadUtf8Text(path)
   tree = ast.parse(source, filename=str(path))
   ast.fix_missing_locations(tree)

   pos_map = _BuildTokenPositionMap(source)

   all_candidates: list[_RenameCandidate] = []
   combined_patch: dict[tuple[int, int], str] = {}

   for node in ast.walk(tree):
      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
         analysis = _AnalyseFunction(node, pos_map)
         all_candidates.extend(analysis.candidates)
         combined_patch.update(analysis.patch_map)

   rewritten = _RewriteTokens(source, combined_patch)

   return RenameResult(
      path=path,
      candidates=all_candidates,
      original=source,
      rewritten=rewritten,
   )
