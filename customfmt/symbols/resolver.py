"""
Per-file symbol resolver.

ResolveFile(path) -> ResolveResult | FileError

Builds a scope tree for one Python file, records every definition and
reference inside it, then resolves each reference to its definition where
possible.

Resolution targets (single-file only)
--------------------------------------
  ✓ local variables  (assignment, for, with, except targets)
  ✓ function parameters
  ✓ module-level declarations (Assign / AnnAssign)
  ✓ imported names (resolved to the import definition, not the source file)
  ✓ class and function definitions at module level
  ✓ class and method definitions inside class bodies
  ✗ self.X attribute access  (marked dynamic)
  ✗ dynamic calls via computed expressions

Unresolved references
---------------------
A reference is marked unresolved when no definition is found anywhere in
the scope chain (including the module scope).  This typically means it
refers to a builtin, a global injected at runtime, or a cross-file name.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from customfmt.io import ReadUtf8Text
from customfmt.symbols.model import FileError
from customfmt.symbols.scopes import (
   Definition,
   DefKind,
   Reference,
   RefKind,
   Scope,
   ScopeKind,
   ScopeTree,
)

# ---------------------------------------------------------------------------
# ResolveResult
# ---------------------------------------------------------------------------

@dataclass
class ResolveResult:
   """Resolved symbol graph for one file."""

   FilePath    : str
   Tree        : ScopeTree
   Definitions : list[Definition] = field(default_factory=list)
   References  : list[Reference]  = field(default_factory=list)

   @property
   def Unresolved(self) -> list[Reference]:
      return [r for r in self.References if r.IsUnresolved]

   @property
   def Dynamic(self) -> list[Reference]:
      return [r for r in self.References if r.IsDynamic]

   @property
   def Resolved(self) -> list[Reference]:
      return [r for r in self.References if r.ResolvedTo is not None]

   def ToDict(self) -> dict:
      return {
         "file":        self.FilePath,
         "scopes":      self.Tree.ToDict()["scopes"],
         "definitions": [d.ToDict() for d in self.Definitions],
         "references":  [r.ToDict() for r in self.References],
         "summary": {
            "total_refs":      len(self.References),
            "resolved":        len(self.Resolved),
            "unresolved":      len(self.Unresolved),
            "dynamic":         len(self.Dynamic),
         },
      }


# ---------------------------------------------------------------------------
# ResolveResultSet  — container for multi-file resolve run
# ---------------------------------------------------------------------------

@dataclass
class ResolveResultSet:
   """Results for all files in one resolve run."""

   Files  : list[ResolveResult] = field(default_factory=list)
   Errors : list[FileError]     = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "files":  [f.ToDict() for f in self.Files],
         "errors": [e.ToDict() for e in self.Errors],
      }


# ---------------------------------------------------------------------------
# AST-based scope builder + resolver
# ---------------------------------------------------------------------------

class _Resolver(ast.NodeVisitor):
   """
   Single-pass AST visitor that builds the scope tree, records all
   definitions and references, then resolves references in a second pass.
   """

   def __init__(self, file_path: str) -> None:
      self._FilePath = file_path
      # The module scope is created immediately.
      self._ModuleScope = Scope(
         Kind     = ScopeKind.Module,
         Name     = "",
         QualName = "",
         Line     = 1,
         Parent   = None,
      )
      self._AllScopes : list[Scope] = [self._ModuleScope]
      self._ScopeStack: list[Scope] = [self._ModuleScope]
      # Collected definitions and references (filled during visit).
      self._AllDefs : list[Definition] = []
      self._AllRefs : list[Reference]  = []
      # Track call positions to avoid double-emitting name_read + call.
      self._CallSites: set[tuple[int, int]] = set()

   # -----------------------------------------------------------------------
   # Scope helpers
   # -----------------------------------------------------------------------

   @property
   def _Current(self) -> Scope:
      return self._ScopeStack[-1]

   def _PushScope(self, kind: ScopeKind, name: str, line: int) -> Scope:
      parent = self._Current
      qual = f"{parent.QualName}.{name}" if parent.QualName else name
      scope = Scope(Kind=kind, Name=name, QualName=qual, Line=line, Parent=parent)
      parent.AddChild(scope)
      self._AllScopes.append(scope)
      self._ScopeStack.append(scope)
      return scope

   def _PopScope(self) -> None:
      self._ScopeStack.pop()

   def _AddDef(
      self,
      name: str,
      kind: DefKind,
      line: int,
      col: int,
      extra: dict | None = None,
   ) -> Definition:
      defn = Definition(
         Name     = name,
         Kind     = kind,
         Line     = line,
         Col      = col,
         ScopeRef = self._Current,
         Extra    = extra or {},
      )
      self._Current.AddDef(defn)
      self._AllDefs.append(defn)
      return defn

   def _AddRef(
      self,
      name: str,
      kind: RefKind,
      line: int,
      col: int,
      dynamic: bool = False,
      extra: dict | None = None,
   ) -> Reference:
      ref = Reference(
         Name     = name,
         Kind     = kind,
         Line     = line,
         Col      = col,
         ScopeRef = self._Current,
         IsDynamic= dynamic,
         Extra    = extra or {},
      )
      self._Current.Refs.append(ref)
      self._AllRefs.append(ref)
      return ref

   # -----------------------------------------------------------------------
   # Imports
   # -----------------------------------------------------------------------

   def visit_Import(self, node: ast.Import) -> None:
      for alias in node.names:
         bound = alias.asname if alias.asname else alias.name.split(".")[0]
         extra = {"module": alias.name, "asname": alias.asname}
         self._AddDef(bound, DefKind.Import, node.lineno, node.col_offset, extra)
      self.generic_visit(node)

   def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
      module = node.module or ""
      for alias in node.names:
         bound = alias.asname if alias.asname else alias.name
         extra = {"module": module, "name": alias.name}
         self._AddDef(bound, DefKind.ImportFrom, node.lineno, node.col_offset, extra)
      self.generic_visit(node)

   # -----------------------------------------------------------------------
   # Module / class body declarations
   # -----------------------------------------------------------------------

   def _RecordDecl(self, node: ast.Assign | ast.AnnAssign) -> None:
      """Record an Assign or AnnAssign as a definition in the current scope."""
      if isinstance(node, ast.Assign):
         for tgt in node.targets:
            self._RecordTarget(tgt, DefKind.LocalWrite)
         # Walk the RHS for references
         self._WalkExprForRefs(node.value)
      elif isinstance(node, ast.AnnAssign):
         if isinstance(node.target, ast.Name):
            kind = (
               DefKind.ModuleDecl if self._Current.Kind == ScopeKind.Module
               else DefKind.ClassDecl if self._Current.Kind == ScopeKind.Class
               else DefKind.LocalWrite
            )
            self._AddDef(
               node.target.id, kind,
               node.target.lineno, node.target.col_offset,
            )
         if node.value is not None:
            self._WalkExprForRefs(node.value)

   def visit_Assign(self, node: ast.Assign) -> None:
      cur = self._Current
      if cur.Kind in (ScopeKind.Module, ScopeKind.Class):
         # Module / class body declaration
         kind = DefKind.ModuleDecl if cur.Kind == ScopeKind.Module else DefKind.ClassDecl
         for tgt in node.targets:
            if isinstance(tgt, ast.Name):
               self._AddDef(tgt.id, kind, tgt.lineno, tgt.col_offset)
         self._WalkExprForRefs(node.value)
      else:
         # Inside a function — local write
         for tgt in node.targets:
            self._RecordTarget(tgt, DefKind.LocalWrite)
         self._WalkExprForRefs(node.value)

   def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
      cur = self._Current
      if cur.Kind in (ScopeKind.Module, ScopeKind.Class):
         kind = DefKind.ModuleDecl if cur.Kind == ScopeKind.Module else DefKind.ClassDecl
         if isinstance(node.target, ast.Name):
            self._AddDef(
               node.target.id, kind,
               node.target.lineno, node.target.col_offset,
            )
      else:
         if isinstance(node.target, ast.Name):
            self._AddDef(
            node.target.id, DefKind.LocalWrite,
            node.target.lineno, node.target.col_offset,
         )
      if node.value is not None:
         self._WalkExprForRefs(node.value)

   def visit_AugAssign(self, node: ast.AugAssign) -> None:
      if isinstance(node.target, ast.Name):
         self._AddDef(
            node.target.id, DefKind.LocalWrite,
            node.target.lineno, node.target.col_offset,
         )
      self._WalkExprForRefs(node.value)

   # -----------------------------------------------------------------------
   # For / with / except
   # -----------------------------------------------------------------------

   def visit_For(self, node: ast.For) -> None:
      self._RecordTarget(node.target, DefKind.LocalWrite)
      self._WalkExprForRefs(node.iter)
      for stmt in node.body + node.orelse:
         self.visit(stmt)

   def visit_With(self, node: ast.With) -> None:
      for item in node.items:
         self._WalkExprForRefs(item.context_expr)
         if item.optional_vars is not None:
            self._RecordTarget(item.optional_vars, DefKind.LocalWrite)
      for stmt in node.body:
         self.visit(stmt)

   def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
      if node.name:
         self._AddDef(
            node.name, DefKind.LocalWrite,
            node.lineno, node.col_offset,
         )
      self.generic_visit(node)

   # -----------------------------------------------------------------------
   # Functions / methods
   # -----------------------------------------------------------------------

   def _VisitFuncDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
      cur = self._Current
      is_method = cur.Kind == ScopeKind.Class
      kind = DefKind.MethodDef if is_method else DefKind.FunctionDef
      is_async = {"is_async": isinstance(node, ast.AsyncFunctionDef)}
      self._AddDef(node.name, kind, node.lineno, node.col_offset, is_async)
      self._PushScope(ScopeKind.Function, node.name, node.lineno)
      # Parameters
      args = node.args
      all_args = (
         args.posonlyargs + args.args + args.kwonlyargs
         + ([args.vararg] if args.vararg else [])
         + ([args.kwarg]  if args.kwarg  else [])
      )
      for arg in all_args:
         ann_str = ast.unparse(arg.annotation) if arg.annotation else None
         param_extra = {"annotation": ann_str}
         self._AddDef(
            arg.arg, DefKind.Parameter,
            arg.lineno, arg.col_offset, param_extra,
         )
      # Body
      for stmt in node.body:
         self.visit(stmt)
      self._PopScope()

   def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
      self._VisitFuncDef(node)

   def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
      self._VisitFuncDef(node)

   # -----------------------------------------------------------------------
   # Classes
   # -----------------------------------------------------------------------

   def visit_ClassDef(self, node: ast.ClassDef) -> None:
      cur = self._Current
      _ = DefKind.MethodDef if cur.Kind == ScopeKind.Class else DefKind.ClassDef
      # Record the class itself as a definition in the parent scope
      bases_extra = {"bases": [ast.unparse(b) for b in node.bases]}
      self._AddDef(node.name, DefKind.ClassDef, node.lineno, node.col_offset, bases_extra)
      self._PushScope(ScopeKind.Class, node.name, node.lineno)
      for stmt in node.body:
         self.visit(stmt)
      self._PopScope()

   # -----------------------------------------------------------------------
   # Expression walkers — emit references
   # -----------------------------------------------------------------------

   def _WalkExprForRefs(self, node: ast.expr | None) -> None:
      """Walk an expression subtree and emit references for all names/calls."""
      if node is None:
         return
      for child in ast.walk(node):
         if isinstance(child, ast.Call):
            self._RecordCall(child)
         elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            pos = (child.lineno, child.col_offset)
            if pos not in self._CallSites:
               self._AddRef(
                  child.id, RefKind.Read,
                  child.lineno, child.col_offset,
               )

   def _RecordCall(self, node: ast.Call) -> None:
      match node.func:
         case ast.Name(id=name, lineno=ln, col_offset=co):
            call_extra = {"args": len(node.args)}
            self._AddRef(name, RefKind.Call, ln, co, extra=call_extra)
            self._CallSites.add((ln, co))
         case ast.Attribute(attr=attr, lineno=ln, col_offset=co):
            full = ast.unparse(node.func)
            attr_extra = {"full": full}
            self._AddRef(
               attr, RefKind.AttrCall, ln, co,
               dynamic=True, extra=attr_extra,
            )
            self._CallSites.add((ln, co))
         case _:
            pass

   def _RecordTarget(self, target: ast.expr, kind: DefKind) -> None:
      match target:
         case ast.Name(id=name, lineno=ln, col_offset=co):
            self._AddDef(name, kind, ln, co)
         case ast.Tuple(elts=elts) | ast.List(elts=elts):
            for elt in elts:
               self._RecordTarget(elt, kind)
         case ast.Starred(value=v):
            self._RecordTarget(v, kind)
         case _:
            pass

   # -----------------------------------------------------------------------
   # Statement fallback — walk children not handled above
   # -----------------------------------------------------------------------

   def visit_Return(self, node: ast.Return) -> None:
      if node.value:
         self._WalkExprForRefs(node.value)

   def visit_Expr(self, node: ast.Expr) -> None:
      self._WalkExprForRefs(node.value)

   def visit_If(self, node: ast.If) -> None:
      self._WalkExprForRefs(node.test)
      for stmt in node.body + node.orelse:
         self.visit(stmt)

   def visit_While(self, node: ast.While) -> None:
      self._WalkExprForRefs(node.test)
      for stmt in node.body + node.orelse:
         self.visit(stmt)

   def visit_Delete(self, node: ast.Delete) -> None:
      for tgt in node.targets:
         self._WalkExprForRefs(tgt)

   def visit_Assert(self, node: ast.Assert) -> None:
      self._WalkExprForRefs(node.test)
      if node.msg:
         self._WalkExprForRefs(node.msg)

   def visit_Raise(self, node: ast.Raise) -> None:
      if node.exc:
         self._WalkExprForRefs(node.exc)

   # -----------------------------------------------------------------------
   # Resolution pass
   # -----------------------------------------------------------------------

   def Resolve(self) -> None:
      """
      Second pass: for each reference, look up its name in the scope chain
      and set ResolvedTo or IsUnresolved.

      Attribute calls are marked dynamic and skipped (self.X is not resolved).
      """
      for ref in self._AllRefs:
         if ref.IsDynamic:
            continue  # already marked dynamic
         defn = ref.ScopeRef.ResolveName(ref.Name)
         if defn is not None:
            ref.ResolvedTo = defn
         else:
            ref.IsUnresolved = True

   # -----------------------------------------------------------------------
   # Build result
   # -----------------------------------------------------------------------

   def Build(self) -> ResolveResult:
      tree = ScopeTree(
         FilePath  = self._FilePath,
         Root      = self._ModuleScope,
         AllScopes = self._AllScopes,
      )
      return ResolveResult(
         FilePath    = self._FilePath,
         Tree        = tree,
         Definitions = self._AllDefs,
         References  = self._AllRefs,
      )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ResolveFile(path: Path) -> ResolveResult | FileError:
   """
   Parse and resolve one Python file.  Never raises.

   Returns a ResolveResult on success, or a FileError when the file
   cannot be read or parsed.
   """
   path_str = str(path)

   try:
      source = ReadUtf8Text(path)
   except (UnicodeDecodeError, ValueError) as exc:
      return FileError(FilePath=path_str, Error=f"encoding error: {exc}")
   except OSError as exc:
      return FileError(FilePath=path_str, Error=f"I/O error: {exc}")

   try:
      tree = ast.parse(source, filename=path_str)
   except SyntaxError as exc:
      err_msg = f"syntax error at line {exc.lineno}: {exc.msg}"
      return FileError(FilePath=path_str, Error=err_msg)

   resolver = _Resolver(path_str)
   resolver.visit(tree)
   resolver.Resolve()
   return resolver.Build()
