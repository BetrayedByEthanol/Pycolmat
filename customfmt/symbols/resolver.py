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
  ✓ global / nonlocal declarations — redirects lookup appropriately
  ✓ class base expressions and metaclass keyword
  ✓ decorator expressions (@deco, @deco(...))
  ✓ type annotations (parameters, return, AnnAssign)
  ✗ self.X attribute access  (marked dynamic)
  ✗ dynamic calls via computed expressions

Unresolved references
---------------------
A reference is marked unresolved when no definition is found anywhere in
the scope chain.  This typically means it refers to a builtin, a global
injected at runtime, or a cross-file name.
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
# ResolveResultSet
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

      self._ModuleScope = Scope(
         Kind     = ScopeKind.Module,
         Name     = "",
         QualName = "",
         Line     = 1,
         Parent   = None,
         FilePath = file_path,
      )
      self._AllScopes  : list[Scope]      = [self._ModuleScope]
      self._ScopeStack : list[Scope]      = [self._ModuleScope]
      self._AllDefs    : list[Definition] = []
      self._AllRefs    : list[Reference]  = []
      self._CallSites  : set[tuple[int, int]] = set()

   # -----------------------------------------------------------------------
   # Scope helpers
   # -----------------------------------------------------------------------

   @property
   def _Current(self) -> Scope:
      return self._ScopeStack[-1]

   def _PushScope(
      self, kind: ScopeKind, name: str, line: int
   ) -> Scope:
      parent = self._Current
      qual = f"{parent.QualName}.{name}" if parent.QualName else name
      scope = Scope(
         Kind     = kind,
         Name     = name,
         QualName = qual,
         Line     = line,
         Parent   = parent,
         FilePath = self._FilePath,
      )
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
         Name      = name,
         Kind      = kind,
         Line      = line,
         Col       = col,
         ScopeRef  = self._Current,
         IsDynamic = dynamic,
         Extra     = extra or {},
      )
      self._Current.Refs.append(ref)
      self._AllRefs.append(ref)
      return ref

   # -----------------------------------------------------------------------
   # Write-target helpers
   # -----------------------------------------------------------------------

   def _IsGlobalOrNonlocal(self, name: str) -> bool:
      """
      Return True if *name* is declared global or nonlocal in the current
      function scope.  Always False at module or class scope.
      """
      cur = self._Current
      if cur.Kind != ScopeKind.Function:
         return False
      return name in cur.GlobalNames or name in cur.NonlocalNames

   def _RecordWriteName(
      self, name: str, line: int, col: int, normal_kind: DefKind
   ) -> None:
      """
      Record a single name as a write target.

      - If *name* is declared global/nonlocal in the current function scope,
        emit a RefKind.Write reference (no local definition is created).
      - Otherwise emit a local definition with *normal_kind*.

      This is the single point of truth used by _RecordWriteTarget,
      visit_AnnAssign, visit_AugAssign, and visit_ExceptHandler.
      """
      if self._IsGlobalOrNonlocal(name):
         self._AddRef(name, RefKind.Write, line, col)
      else:
         self._AddDef(name, normal_kind, line, col)

   def _RecordWriteTarget(
      self, target: ast.expr, normal_kind: DefKind
   ) -> None:
      """
      Record a (potentially composite) assignment target, routing each
      leaf Name node through _RecordWriteName for global/nonlocal awareness.
      """
      match target:
         case ast.Name(id=name, lineno=ln, col_offset=co):
            self._RecordWriteName(name, ln, co, normal_kind)
         case ast.Tuple(elts=elts) | ast.List(elts=elts):
            for elt in elts:
               self._RecordWriteTarget(elt, normal_kind)
         case ast.Starred(value=v):
            self._RecordWriteTarget(v, normal_kind)
         case _:
            pass

   # -----------------------------------------------------------------------
   # Imports
   # -----------------------------------------------------------------------

   def visit_Import(self, node: ast.Import) -> None:
      for alias in node.names:
         bound = alias.asname if alias.asname else alias.name.split(".")[0]
         extra = {"module": alias.name, "asname": alias.asname}
         self._AddDef(
            bound, DefKind.Import, node.lineno, node.col_offset, extra
         )

   def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
      module = node.module or ""
      for alias in node.names:
         bound = alias.asname if alias.asname else alias.name
         extra = {"module": module, "name": alias.name, "level": node.level}
         self._AddDef(
            bound, DefKind.ImportFrom, node.lineno, node.col_offset, extra
         )

   # -----------------------------------------------------------------------
   # Global / nonlocal declarations
   # -----------------------------------------------------------------------

   def visit_Global(self, node: ast.Global) -> None:
      """Record global declarations so resolution can redirect to module scope."""
      for name in node.names:
         self._Current.GlobalNames.add(name)

   def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
      """Record nonlocal declarations so resolution skips the current scope."""
      for name in node.names:
         self._Current.NonlocalNames.add(name)

   # -----------------------------------------------------------------------
   # Annotations helper
   # -----------------------------------------------------------------------

   def _RecordAnnotation(self, ann: ast.expr | None) -> None:
      """
      Walk a type annotation expression and emit RefKind.Annotation references
      for every Name node found.  Complex annotations like list[UserModel]
      and Optional[UserModel] are walked recursively so all name components
      are captured.
      """
      if ann is None:
         return
      for child in ast.walk(ann):
         if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            self._AddRef(
               child.id, RefKind.Annotation,
               child.lineno, child.col_offset,
            )

   # -----------------------------------------------------------------------
   # Decorators helper
   # -----------------------------------------------------------------------

   def _RecordDecorators(
      self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
   ) -> None:
      """
      Emit references for all decorators.  A bare decorator @deco produces a
      Call reference; @deco(...) produces a Call for the outer call and the
      inner expression is walked for further reads.
      """
      for dec in node.decorator_list:
         self._WalkExprForRefs(dec)

   # -----------------------------------------------------------------------
   # Assignments
   # -----------------------------------------------------------------------

   def visit_Assign(self, node: ast.Assign) -> None:
      cur = self._Current
      if cur.Kind in (ScopeKind.Module, ScopeKind.Class):
         kind = (
            DefKind.ModuleDecl if cur.Kind == ScopeKind.Module
            else DefKind.ClassDecl
         )
         for tgt in node.targets:
            if isinstance(tgt, ast.Name):
               self._AddDef(tgt.id, kind, tgt.lineno, tgt.col_offset)
         self._WalkExprForRefs(node.value)
      else:
         for tgt in node.targets:
            self._RecordWriteTarget(tgt, DefKind.LocalWrite)
         self._WalkExprForRefs(node.value)

   def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
      cur = self._Current
      if cur.Kind in (ScopeKind.Module, ScopeKind.Class):
         kind = (
            DefKind.ModuleDecl if cur.Kind == ScopeKind.Module
            else DefKind.ClassDecl
         )
         if isinstance(node.target, ast.Name):
            self._AddDef(
               node.target.id, kind,
               node.target.lineno, node.target.col_offset,
            )
      else:
         if isinstance(node.target, ast.Name):
            self._RecordWriteName(
               node.target.id,
               node.target.lineno,
               node.target.col_offset,
               DefKind.LocalWrite,
               )
      # Always walk the annotation and the RHS value.
      self._RecordAnnotation(node.annotation)
      if node.value is not None:
         self._WalkExprForRefs(node.value)

   def visit_AugAssign(self, node: ast.AugAssign) -> None:
      # Augmented assignment (x += ...) is both a read and a write of the target.
      # For ast.Name targets we emit:
      #   1. A RefKind.Read  — the implicit read of the current value.
      #   2. A write via _RecordWriteName — global/nonlocal-aware write handling.
      # For complex targets (subscript, attribute) we keep conservative behaviour
      # and just walk for refs without emitting a read.
      if isinstance(node.target, ast.Name):
         name = node.target.id
         ln   = node.target.lineno
         co   = node.target.col_offset
         # Emit the implicit read before the write.
         if (ln, co) not in self._CallSites:
            self._AddRef(name, RefKind.Read, ln, co)
         # Emit the write (respects global/nonlocal).
         self._RecordWriteName(name, ln, co, DefKind.LocalWrite)
      else:
         self._RecordWriteTarget(node.target, DefKind.LocalWrite)
      self._WalkExprForRefs(node.value)

   # -----------------------------------------------------------------------
   # For / with / except
   # -----------------------------------------------------------------------

   def visit_For(self, node: ast.For) -> None:
      self._RecordWriteTarget(node.target, DefKind.LocalWrite)
      self._WalkExprForRefs(node.iter)
      for stmt in node.body + node.orelse:
         self.visit(stmt)

   def visit_With(self, node: ast.With) -> None:
      for item in node.items:
         self._WalkExprForRefs(item.context_expr)
         if item.optional_vars is not None:
            self._RecordWriteTarget(item.optional_vars, DefKind.LocalWrite)
      for stmt in node.body:
         self.visit(stmt)

   def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
      if node.name:
         # Use _RecordWriteName so global/nonlocal-declared names get a Write
         # reference instead of a spurious LocalWrite definition.
         self._RecordWriteName(
            node.name, node.lineno, node.col_offset, DefKind.LocalWrite
         )
      self.generic_visit(node)

   # -----------------------------------------------------------------------
   # Functions / methods
   # -----------------------------------------------------------------------

   def _VisitFuncDef(
      self, node: ast.FunctionDef | ast.AsyncFunctionDef
   ) -> None:
      cur = self._Current
      is_method = cur.Kind == ScopeKind.Class
      kind = DefKind.MethodDef if is_method else DefKind.FunctionDef
      is_async = {"is_async": isinstance(node, ast.AsyncFunctionDef)}
      self._AddDef(node.name, kind, node.lineno, node.col_offset, is_async)
      # Decorators are walked in the OUTER scope before pushing.
      self._RecordDecorators(node)
      self._PushScope(ScopeKind.Function, node.name, node.lineno)
      # Parameters (including annotations) — recorded inside the function scope.
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
         self._RecordAnnotation(arg.annotation)
      # Return annotation.
      self._RecordAnnotation(node.returns)
      # Body.
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
      bases_extra = {"bases": [ast.unparse(b) for b in node.bases]}
      self._AddDef(
         node.name, DefKind.ClassDef, node.lineno, node.col_offset, bases_extra
      )
      # Decorators in the outer scope.
      self._RecordDecorators(node)
      # Base class expressions — emit references in the outer scope.
      for base in node.bases:
         self._WalkExprForRefs(base)
      # Keyword arguments, e.g. metaclass=AllOptional.
      for kw in node.keywords:
         self._WalkExprForRefs(kw.value)
      self._PushScope(ScopeKind.Class, node.name, node.lineno)
      for stmt in node.body:
         self.visit(stmt)
      self._PopScope()

   # -----------------------------------------------------------------------
   # Expression walkers
   # -----------------------------------------------------------------------

   def _WalkExprForRefs(self, node: ast.expr | None) -> None:
      """Walk an expression subtree and emit Read/Call/AttrCall references."""
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
   # Statement fallbacks
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
      Second pass: resolve each non-dynamic reference using ResolveName.
      global/nonlocal semantics are handled inside Scope.ResolveName.
      """
      for ref in self._AllRefs:
         if ref.IsDynamic:
            continue
         # Write refs (global/nonlocal assignments) are resolved
         # the same way as reads — through the scope chain.
         defn = ref.ScopeRef.ResolveName(ref.Name)
         if defn is not None:
            ref.ResolvedTo = defn
         else:
            ref.IsUnresolved = True

   # -----------------------------------------------------------------------
   # Build
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
