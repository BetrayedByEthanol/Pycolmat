"""
Rename planner for customfmt — v1: safe local-variable renames only.

Architecture
------------
analyse → build RenamePlan → render diff / apply

The planner uses ResolveFile() to obtain per-scope definitions and
references, applies all safety checks, then computes a token-level
patch map.  It does NOT rewrite files; that is left to the CLI.

Scope for v1
------------
- Only DefKind.LocalWrite definitions inside FunctionDef / AsyncFunctionDef
  scopes.
- Rename non-snake_case names to snake_case.
- Rename ALL read/write references resolved to the same local definition.
- Covers Assign, AnnAssign, AugAssign, For, With-as, ExceptHandler-as
  targets (via the resolver).

Safety rules
------------
Function scope is skipped entirely if:
  - it has any GlobalNames or NonlocalNames declared
  - it calls bare locals(), globals(), vars(), eval(), or exec()

Individual rename is skipped if:
  - proposed snake_case name collides with any visible local, parameter,
    import, parent/module declaration, or builtin name
  - two different bad names map to the same snake_case target
  - another rename wants to patch the same token to a different name

Nested functions are handled independently; each function scope is
processed without crossing into child or parent scopes.

Token rewriting
---------------
Exact (line, col) positions are resolved via a token pre-pass so that
string literals and comments are never touched.
"""

from __future__ import annotations

import builtins
import difflib
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from customfmt.io import ReadUtf8Text, WriteUtf8Lf
from customfmt.symbols.model import FileError
from customfmt.symbols.resolver import ResolveFile, ResolveResult
from customfmt.symbols.scopes import DefKind, RefKind, Scope, ScopeKind
from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$|^[a-z]$")
_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins))
_UNSAFE_BARE_CALLS: frozenset[str] = frozenset(
   {"locals", "globals", "vars", "eval", "exec"}
)


def _IsSnake(name: str) -> bool:
   return bool(_SNAKE_RE.match(name))


def _ToSnake(name: str) -> str:
   """Convert PascalCase / camelCase to snake_case."""
   s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
   s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
   return s.lower()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class SourcePos:
   """A (line, col) position in source, both 1-based col for display."""

   Line : int   # 1-based
   Col  : int   # 0-based (AST convention); display as Col+1

   def ToDict(self) -> dict:
      return {"line": self.Line, "col": self.Col}


@dataclass
class RenameItem:
   """One safe rename candidate inside a function scope."""

   OldName         : str
   NewName         : str
   ScopeQual       : str              # dotted qualified name of the function scope
   DefinitionSites : list[SourcePos]  # local definition token positions
   ReadSites       : list[SourcePos]  # resolved read token positions
   WriteSites      : list[SourcePos]  # local/resolved write token positions
   DefLine         : int              # line of the first definition site

   @property
   def AllSites(self) -> list[SourcePos]:
      """All token positions to rewrite, de-duplicated and sorted."""
      return sorted({
         *self.DefinitionSites,
         *self.ReadSites,
         *self.WriteSites,
      })

   @property
   def Sites(self) -> list[SourcePos]:
      """Backward-compatible alias for all token positions to rewrite."""
      return self.AllSites

   def ToDict(self) -> dict:
      return {
         "old_name":         self.OldName,
         "new_name":         self.NewName,
         "scope":            self.ScopeQual,
         "def_line":         self.DefLine,
         "sites":            [s.ToDict() for s in self.AllSites],
         "definition_sites": [s.ToDict() for s in self.DefinitionSites],
         "read_sites":       [s.ToDict() for s in self.ReadSites],
         "write_sites":      [s.ToDict() for s in self.WriteSites],
         "all_sites":        [s.ToDict() for s in self.AllSites],
      }

   def AsViolation(self, path: Path) -> Violation:
      return Violation(
         path,
         self.DefLine,
         self.AllSites[0].Col + 1 if self.AllSites else 1,
         "RENAME",
         f"local variable {self.OldName!r} -> {self.NewName!r}",
      )


@dataclass
class RenameSkip:
   """Record of a skipped scope or skipped individual rename."""

   ScopeQual : str
   Reason    : str
   Name      : str = ""   # empty when the whole scope is skipped

   def ToDict(self) -> dict:
      return {
         "scope":  self.ScopeQual,
         "name":   self.Name,
         "reason": self.Reason,
      }


@dataclass
class RenamePlan:
   """
   Complete rename plan for one file.

   Build with ``PlanFile(path)``.  Render with ``UnifiedDiff()`` or
   apply with ``Apply()``.
   """

   FilePath  : str
   Items     : list[RenameItem]           = field(default_factory=list)
   Skipped   : list[RenameSkip]           = field(default_factory=list)
   Original  : str                        = ""
   Rewritten : str                        = ""
   PatchMap  : dict[tuple[int, int], str] = field(default_factory=dict)

   @property
   def Changed(self) -> bool:
      return self.Rewritten != self.Original

   def Violations(self, path: Path) -> list[Violation]:
      return sorted(item.AsViolation(path) for item in self.Items)

   def UnifiedDiff(self, path: Path) -> str:
      return "".join(
         difflib.unified_diff(
            self.Original.splitlines(keepends=True),
            self.Rewritten.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
         )
      )

   def Apply(self, path: Path) -> None:
      """Write the rewritten source to *path* as UTF-8 LF."""
      WriteUtf8Lf(path, self.Rewritten)

   def ToDict(self) -> dict:
      return {
         "file":     self.FilePath,
         "items":    [i.ToDict() for i in self.Items],
         "skipped":  [s.ToDict() for s in self.Skipped],
         "changed":  self.Changed,
      }


# ---------------------------------------------------------------------------
# Safety checks on a resolved function scope
# ---------------------------------------------------------------------------

def _HasUnsafeDecl(scope: Scope) -> bool:
   """Return True if the scope has any global/nonlocal declarations."""
   return bool(scope.GlobalNames or scope.NonlocalNames)


def _HasUnsafeBareCall(scope: Scope) -> bool:
   """
   Return True if the scope contains a bare call to a dangerous function.
   Only ast.Name-style calls are checked; attribute calls (obj.locals())
   are not flagged.
   """
   for ref in scope.Refs:
      if (
         ref.Kind == RefKind.Call
         and ref.Name in _UNSAFE_BARE_CALLS
      ):
         return True
   return False


def _HasVisibleCollision(scope: Scope, name: str) -> bool:
   """Return True if *name* already resolves from *scope* or is a builtin."""
   if name in _BUILTIN_NAMES:
      return True
   return scope.ResolveName(name) is not None


def _FindNameToken(
   pos_map: dict[tuple[str, int, int], bool],
   name: str,
   line: int,
   fallback_col: int,
) -> tuple[int, int]:
   """Find the real NAME token for AST sites with imprecise columns."""
   if (name, line, fallback_col) in pos_map:
      return (line, fallback_col)
   candidates = [
      (ln, co) for token_name, ln, co in pos_map
      if token_name == name and ln == line
   ]
   if candidates:
      return min(candidates)
   return (line, fallback_col)


# ---------------------------------------------------------------------------
# Per-scope rename analysis
# ---------------------------------------------------------------------------

def _AnalyseScope(
   scope: Scope,
   resolve: ResolveResult,
   pos_map: dict[tuple[str, int, int], bool],
) -> tuple[list[RenameItem], list[RenameSkip]]:
   """
   Analyse one function scope and return (items, skips).

   Only DefKind.LocalWrite definitions are considered.
   The scope is skipped entirely on safety violations.
   """
   items: list[RenameItem] = []
   skips: list[RenameSkip] = []
   qual  = scope.QualName

   # Whole-scope safety checks
   if _HasUnsafeDecl(scope):
      skips.append(RenameSkip(qual, "global/nonlocal declarations present"))
      return items, skips

   if _HasUnsafeBareCall(scope):
      skips.append(
         RenameSkip(qual, "bare call to locals/globals/vars/eval/exec")
      )
      return items, skips

   # Collect all local-write definitions in this scope
   bad_defs: dict[str, list[tuple[int, int]]] = {}
   for name, defs in scope.Defs.items():
      if name.startswith("_"):
         continue
      local_defs = [d for d in defs if d.Kind == DefKind.LocalWrite]
      if not local_defs:
         continue
      if _IsSnake(name):
         continue
      new_name = _ToSnake(name)
      if new_name == name:
         continue
      bad_defs[name] = [
         _FindNameToken(pos_map, name, d.Line, d.Col)
         for d in local_defs
      ]

   if not bad_defs:
      return items, skips

   # Compute proposed new names and check for inter-collision
   proposed: dict[str, str] = {old: _ToSnake(old) for old in bad_defs}
   new_name_counts: dict[str, int] = {}
   for new in proposed.values():
      new_name_counts[new] = new_name_counts.get(new, 0) + 1
   colliding_new = {n for n, c in new_name_counts.items() if c > 1}

   for old_name, def_sites in bad_defs.items():
      new_name = proposed[old_name]

      if new_name in colliding_new:
         skips.append(RenameSkip(
            qual, "two bad names map to same snake_case target", old_name
         ))
         continue

      if _HasVisibleCollision(scope, new_name):
         skips.append(RenameSkip(
            qual,
            f"proposed name {new_name!r} collides with existing name",
            old_name,
         ))
         continue

      # Collect all reference sites (reads and writes) that resolve to a
      # LocalWrite definition of this name inside this scope.
      local_def_set = {
         id(d)
         for d in scope.Defs[old_name]
         if d.Kind == DefKind.LocalWrite
      }
      definition_sites: set[tuple[int, int]] = set(def_sites)
      read_sites      : set[tuple[int, int]] = set()
      write_sites     : set[tuple[int, int]] = set(def_sites)

      # Reference sites (read and write refs resolved to this local)
      for ref in resolve.References:
         if ref.ScopeRef is not scope:
            continue
         if ref.Name != old_name:
            continue
         if ref.ResolvedTo is None:
            continue
         if id(ref.ResolvedTo) not in local_def_set:
            continue
         if ref.Kind == RefKind.Read:
            read_sites.add((ref.Line, ref.Col))
         elif ref.Kind == RefKind.Write:
            write_sites.add((ref.Line, ref.Col))

      sorted_def_sites = sorted(SourcePos(ln, co) for ln, co in definition_sites)
      sorted_read_sites = sorted(SourcePos(ln, co) for ln, co in read_sites)
      sorted_write_sites = sorted(SourcePos(ln, co) for ln, co in write_sites)
      first_def = min(line for line, _ in def_sites)
      items.append(
         RenameItem(
            OldName         = old_name,
            NewName         = new_name,
            ScopeQual       = qual,
            DefinitionSites = sorted_def_sites,
            ReadSites       = sorted_read_sites,
            WriteSites      = sorted_write_sites,
            DefLine         = first_def,
         )
      )

   return items, skips


def _FilterDuplicatePatchSites(
   items: list[RenameItem],
) -> tuple[list[RenameItem], list[RenameSkip]]:
   """Skip items that would patch one token position to different names."""
   names_by_site: dict[tuple[int, int], dict[str, list[RenameItem]]] = {}
   for item in items:
      for site in item.AllSites:
         by_name = names_by_site.setdefault((site.Line, site.Col), {})
         by_name.setdefault(item.NewName, []).append(item)

   blocked: set[int] = set()
   skips: list[RenameSkip] = []
   for (line, col), by_name in names_by_site.items():
      if len(by_name) <= 1:
         continue
      reason = (
         f"duplicate patch site at line {line}, col {col} "
         "has conflicting target names"
      )
      for same_name_items in by_name.values():
         for item in same_name_items:
            blocked.add(id(item))
            skips.append(RenameSkip(item.ScopeQual, reason, item.OldName))

   if not blocked:
      return items, skips
   return [item for item in items if id(item) not in blocked], skips

# ---------------------------------------------------------------------------
# Token rewriter
# ---------------------------------------------------------------------------

def _BuildTokenPosMap(
   source: str,
) -> dict[tuple[str, int, int], bool]:
   pos_map: dict[tuple[str, int, int], bool] = {}
   try:
      for tok in tokenize.generate_tokens(io.StringIO(source).readline):
         if tok.type == tokenize.NAME:
            pos_map[(tok.string, tok.start[0], tok.start[1])] = True
   except tokenize.TokenError:
      pass
   return pos_map


def _RewriteTokens(
   source: str,
   patch_map: dict[tuple[int, int], str],
) -> str:
   if not patch_map:
      return source
   tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
   out    = io.StringIO()
   prev   = (1, 0)
   src_lines = source.splitlines(keepends=True)

   for tok in tokens:
      tok_type, tok_string, tok_start, tok_end, _ = tok
      if tok_start != prev:
         out.write(_ExtractGap(src_lines, prev, tok_start))
      if tok_type == tokenize.NAME and tok_start in patch_map:
         out.write(patch_map[tok_start])
      else:
         out.write(tok_string)
      prev = tok_end

   return out.getvalue()


def _ExtractGap(
   src_lines: list[str],
   prev_end: tuple[int, int],
   tok_start: tuple[int, int],
) -> str:
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

def PlanFile(path: Path) -> RenamePlan | FileError:
   """
   Build a RenamePlan for *path*.

   Returns a RenamePlan (which may have zero items) on success, or a
   FileError when the file cannot be read or parsed.

   Never raises.
   """
   path_str = str(path)

   resolve = ResolveFile(path)
   if isinstance(resolve, FileError):
      return resolve

   source = resolve.Tree.Root.FilePath  # already read; re-read for safety
   try:
      source = ReadUtf8Text(path)
   except (UnicodeDecodeError, ValueError, OSError) as exc:
      return FileError(FilePath=path_str, Error=str(exc))

   all_items  : list[RenameItem] = []
   all_skips  : list[RenameSkip] = []
   patch_map  : dict[tuple[int, int], str] = {}
   pos_map = _BuildTokenPosMap(source)

   # Analyse every function/method scope independently
   for scope in resolve.Tree.AllScopes:
      if scope.Kind != ScopeKind.Function:
         continue
      items, skips = _AnalyseScope(scope, resolve, pos_map)
      all_items.extend(items)
      all_skips.extend(skips)

   all_items, duplicate_skips = _FilterDuplicatePatchSites(all_items)
   all_skips.extend(duplicate_skips)

   for item in all_items:
      for site in item.AllSites:
         patch_map[(site.Line, site.Col)] = item.NewName

   rewritten = _RewriteTokens(source, patch_map)

   return RenamePlan(
      FilePath  = path_str,
      Items     = all_items,
      Skipped   = all_skips,
      Original  = source,
      Rewritten = rewritten,
      PatchMap  = patch_map,
   )
