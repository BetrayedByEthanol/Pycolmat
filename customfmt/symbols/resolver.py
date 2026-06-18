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
      self, kind: ScopeKind, name: str, line: int, col: int
   ) -> Scope:
      parent = self._Current
      qual = f"{parent.QualName}.{name}" if parent.QualName else name
      scope = Scope(
         Kind     = kind,
         Name     = name,
         QualName = qual,
         Line     = line,
         Parent   = parent,
         Col      = col,
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

   def _MethodExtra(
      self, owner: Scope, method_name: str, is_async: bool
   ) -> dict:
      return {
         "is_async":                   is_async,
         "owner_class_name":           owner.Name,
         "owner_class_qualified_name": owner.QualName,
         "owner_class_file":           owner.FilePath,
         "owner_class_line":           owner.Line,
         "owner_class_col":            owner.Col,
         "method_name":                method_name,
      }

   def _SameClassMethodExtra(self, receiver: str, method_name: str) -> dict | None:
      cur = self._Current
      if cur.Kind != ScopeKind.Function:
         return None
      if cur.OwnerClassScope is None:
         return None
      if cur.FirstParamName != receiver:
         return None
      if receiver not in ("self", "cls"):
         return None
      owner = cur.OwnerClassScope
      return {
         "full":                       f"{receiver}.{method_name}",
         "receiver_kind":              receiver,
         "owner_class_name":           owner.Name,
         "owner_class_qualified_name": owner.QualName,
         "method_name":                method_name,
      }

   def _ClassQualifiedName(self, defn: Definition) -> str:
      scope = defn.ScopeRef
      return f"{scope.QualName}.{defn.Name}" if scope.QualName else defn.Name

   def _ClassMethodExtra(
      self, class_def: Definition, method_name: str
   ) -> dict:
      return {
         "full":                       f"{class_def.Name}.{method_name}",
         "receiver_kind":              "class",
         "owner_class_name":           class_def.Name,
         "owner_class_qualified_name": self._ClassQualifiedName(class_def),
         "method_name":                method_name,
      }

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
      self,
      name: str,
      line: int,
      col: int,
      normal_kind: DefKind,
      extra: dict | None = None,
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
         self._AddDef(name, normal_kind, line, col, extra)

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
         case ast.Subscript(value=value, slice=slice_node):
            self._WalkExprForRefs(value)
            self._WalkExprForRefs(slice_node)
         case ast.Attribute(value=value):
            self._WalkExprForRefs(value)
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
         extra = {
            "module": module, "name": alias.name,
            "asname": alias.asname, "level": node.level,
         }
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
            if isinstance(tgt, ast.Name):
               self._RecordWriteName(
                  tgt.id,
                  tgt.lineno,
                  tgt.col_offset,
                  DefKind.LocalWrite,
                  self._ReceiverTypeExtraFromValue(node.value),
               )
            else:
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
               self._ReceiverTypeExtraFromAnnotation(node.annotation),
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


   def _ReceiverTypeExtraFromValue(self, value: ast.expr) -> dict | None:
      if not isinstance(value, ast.Call):
         return None
      if isinstance(value.func, ast.Name):
         return {
            "receiver_type_source": "constructor",
            "receiver_type_name":   value.func.id,
         }
      return None

   def _ReceiverTypeExtraFromAnnotation(self, ann: ast.expr | None) -> dict | None:
      if isinstance(ann, ast.Name):
         return {
            "receiver_type_source": "annotation",
            "receiver_type_name":   ann.id,
         }
      return None

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
      is_async = isinstance(node, ast.AsyncFunctionDef)
      extra = (
         self._MethodExtra(cur, node.name, is_async)
         if is_method else {"is_async": is_async}
      )
      self._AddDef(node.name, kind, node.lineno, node.col_offset, extra)
      # Decorators are walked in the OUTER scope before pushing.
      self._RecordDecorators(node)
      func_scope = self._PushScope(
         ScopeKind.Function, node.name, node.lineno, node.col_offset
      )
      # Parameters (including annotations) — recorded inside the function scope.
      args = node.args
      positional_args = args.posonlyargs + args.args
      func_scope.OwnerClassScope = cur if is_method else None
      func_scope.FirstParamName = (
         positional_args[0].arg if positional_args else None
      )
      all_args = (
         positional_args + args.kwonlyargs
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
      self._PushScope(
         ScopeKind.Class, node.name, node.lineno, node.col_offset
      )
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
      lambda_attr_calls = self._LambdaAttributeCallPositions(node)
      for child in ast.walk(node):
         if isinstance(child, ast.Call):
            self._RecordCall(
               child,
               force_dynamic=self._CallPosition(child) in lambda_attr_calls,
            )
         elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            pos = (child.lineno, child.col_offset)
            if pos not in self._CallSites:
               self._AddRef(
                  child.id, RefKind.Read,
                  child.lineno, child.col_offset,
               )

   def _CallPosition(self, node: ast.Call) -> tuple[int, int]:
      func = node.func
      return (
         getattr(func, "lineno", node.lineno),
         getattr(func, "col_offset", node.col_offset),
      )

   def _LambdaAttributeCallPositions(self, node: ast.expr) -> set[tuple[int, int]]:
      positions: set[tuple[int, int]] = set()
      for child in ast.walk(node):
         if not isinstance(child, ast.Lambda):
            continue
         for lambda_child in ast.walk(child.body):
            if isinstance(lambda_child, ast.Call):
               if isinstance(lambda_child.func, ast.Attribute):
                  positions.add(self._CallPosition(lambda_child))
      return positions

   def _RecordCall(self, node: ast.Call, *, force_dynamic: bool = False) -> None:
      match node.func:
         case ast.Name(id=name, lineno=ln, col_offset=co):
            call_extra = {"args": len(node.args)}
            self._AddRef(name, RefKind.Call, ln, co, extra=call_extra)
            self._RecordGetattrStringReference(node, name)
            self._CallSites.add((ln, co))
         case ast.Attribute(
            attr=attr, value=ast.Name(id=receiver), lineno=ln, col_offset=co
         ):
            full = ast.unparse(node.func)
            attr_extra = {"full": full}
            safe_extra = (
               None if force_dynamic
               else self._SameClassMethodExtra(receiver, attr)
            )
            is_class_candidate = (
               not force_dynamic
               and safe_extra is None
               and receiver not in ("self", "cls")
            )
            if safe_extra is not None:
               attr_extra = safe_extra
            elif is_class_candidate:
               attr_extra["_receiver_name"] = receiver
               attr_extra["receiver_name"] = receiver
            self._AddRef(
               attr, RefKind.AttrCall, ln, co,
               dynamic=safe_extra is None and not is_class_candidate,
               extra=attr_extra,
            )
         case ast.Attribute(attr=attr, lineno=ln, col_offset=co):
            full = ast.unparse(node.func)
            attr_extra = {"full": full}
            self._AddRef(
               attr, RefKind.AttrCall, ln, co,
               dynamic=True, extra=attr_extra,
            )
         case _:
            pass


   def _RecordGetattrStringReference(self, node: ast.Call, name: str) -> None:
      if name != "getattr" or len(node.args) < 2:
         return
      attr_arg = node.args[1]
      if not isinstance(attr_arg, ast.Constant):
         return
      if not isinstance(attr_arg.value, str):
         return
      attr_name = attr_arg.value
      if not attr_name.isidentifier():
         return
      self._AddRef(
         attr_name, RefKind.AttrCall,
         attr_arg.lineno, attr_arg.col_offset + 1,
         dynamic=True,
         extra={"full": ast.unparse(node), "dynamic_reason": "getattr_string"},
      )

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
      method_map = self._DirectMethodMap()
      for ref in self._AllRefs:
         if ref.IsDynamic:
            continue
         if ref.Kind == RefKind.AttrCall:
            if self._ResolveAttrCall(ref, method_map):
               continue
            ref.IsDynamic = True
            continue
         # Write refs (global/nonlocal assignments) are resolved
         # the same way as reads — through the scope chain.
         defn = ref.ScopeRef.ResolveName(ref.Name)
         if defn is not None:
            ref.ResolvedTo = defn
         else:
            ref.IsUnresolved = True

   def _ResolveAttrCall(
      self, ref: Reference, method_map: dict[tuple[str, str], Definition]
   ) -> bool:
      owner_qual = str(ref.Extra.get("owner_class_qualified_name", ""))
      if owner_qual:
         method_def = method_map.get((owner_qual, ref.Name))
         if method_def is None:
            return False
         ref.ResolvedTo = method_def
         ref.Extra["method_target"] = self._MethodTargetExtra(method_def)
         return True

      receiver = ref.Extra.get("_receiver_name")
      if not isinstance(receiver, str):
         return False
      class_def = ref.ScopeRef.ResolveName(receiver)
      if class_def is None or class_def.Kind != DefKind.ClassDef:
         return False
      method_def = method_map.get((self._ClassQualifiedName(class_def), ref.Name))
      if method_def is None:
         return False
      ref.ResolvedTo = method_def
      ref.Extra = self._ClassMethodExtra(class_def, ref.Name)
      ref.Extra["method_target"] = self._MethodTargetExtra(method_def)
      return True

   def _DirectMethodMap(self) -> dict[tuple[str, str], Definition]:
      method_map: dict[tuple[str, str], Definition] = {}
      for defn in self._AllDefs:
         if defn.Kind != DefKind.MethodDef:
            continue
         method_map.setdefault((defn.ScopeRef.QualName, defn.Name), defn)
      return method_map

   def _MethodTargetExtra(self, defn: Definition) -> dict:
      return {
         "name":     defn.Name,
         "kind":     defn.Kind.value,
         "line":     defn.Line,
         "col":      defn.Col,
         "scope_id": defn.ScopeRef.ScopeId,
      }

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
