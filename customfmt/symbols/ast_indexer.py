"""
AST-based symbol indexer.

IndexFile(path) -> FileIndex | FileError

Walks the AST of one Python file and produces SymbolEntry records for:

  import          ast.Import aliases
  import_from     ast.ImportFrom aliases
  module_decl     direct ast.Assign / ast.AnnAssign in Module.body
  class           ast.ClassDef (top-level and nested)
  class_decl      direct ast.Assign / ast.AnnAssign in ClassDef.body
  function        ast.FunctionDef / ast.AsyncFunctionDef at module level
  method          ast.FunctionDef / ast.AsyncFunctionDef inside a class
  parameter       function/method arguments
  local_write     assignments inside function bodies
  name_read       ast.Name(ctx=Load) inside function bodies
  call            bare function calls  f(...)
  attribute_call  method calls         obj.attr(...)

Design notes
------------
- The indexer walks the tree using a scope stack so every symbol knows
  its containing class / function path.
- name_read records are emitted for Name nodes with Load context inside
  function bodies, excluding the function name in a call (that is captured
  as ``call`` instead) and attribute values (captured as ``attribute_call``).
- We do NOT cross-file reference resolution here.
"""

from __future__ import annotations

import ast
from pathlib import Path

from customfmt.io import ReadUtf8Text
from customfmt.symbols.model import (
   KIND_ATTR_CALL,
   KIND_CALL,
   KIND_CLASS,
   KIND_CLASS_DECL,
   KIND_FUNCTION,
   KIND_IMPORT,
   KIND_IMPORT_FROM,
   KIND_LOCAL_WRITE,
   KIND_METHOD,
   KIND_MODULE_DECL,
   KIND_NAME_READ,
   KIND_PARAMETER,
   FileError,
   FileIndex,
   SymbolEntry,
)

# ---------------------------------------------------------------------------
# Internal walker
# ---------------------------------------------------------------------------

class _Indexer(ast.NodeVisitor):
   """
   Recursive AST visitor that builds a list of SymbolEntry objects.

   The ``_scope`` stack contains the dotted names of enclosing class and
   function definitions, e.g. ["UserRepo", "GetByID"].
   """

   def __init__(self, file_path: str) -> None:
      self._File   = file_path
      self._scope  : list[str] = []
      self.Symbols : list[SymbolEntry] = []
      # Track whether the current scope element is a class or function
      # so we know whether a nested def is a method or a function.
      self._scope_kind: list[str] = []  # "class" | "function"

   # -----------------------------------------------------------------------
   # Helpers
   # -----------------------------------------------------------------------

   def _ScopeStr(self) -> str:
      return ".".join(self._scope)

   def _Qualified(self, name: str) -> str:
      s = self._ScopeStr()
      return f"{s}.{name}" if s else name

   def _Add(
      self,
      kind: str,
      name: str,
      line: int,
      col: int,
      extra: dict | None = None,
   ) -> None:
      self.Symbols.append(
         SymbolEntry(
            Kind          = kind,
            Name          = name,
            QualifiedName = self._Qualified(name),
            FilePath      = self._File,
            Line          = line,
            Col           = col,
            Scope         = self._ScopeStr(),
            Extra         = extra or {},
         )
      )

   def _InFunction(self) -> bool:
      return bool(self._scope_kind) and self._scope_kind[-1] == "function"

   def _InClass(self) -> bool:
      return bool(self._scope_kind) and self._scope_kind[-1] == "class"

   # -----------------------------------------------------------------------
   # Imports
   # -----------------------------------------------------------------------

   def _VisitImport(self, node: ast.Import) -> None:
      for alias in node.names:
         bound = alias.asname if alias.asname else alias.name.split(".")[0]
         extra = {"module": alias.name, "asname": alias.asname}
         self._Add(KIND_IMPORT, bound, node.lineno, node.col_offset, extra)
      self.generic_visit(node)

   def _VisitImportFrom(self, node: ast.ImportFrom) -> None:
      module = node.module or ""
      for alias in node.names:
         bound = alias.asname if alias.asname else alias.name
         extra = {
            "module": module, "name": alias.name,
            "asname": alias.asname, "level": node.level,
         }
         self._Add(KIND_IMPORT_FROM, bound, node.lineno, node.col_offset, extra)
      self.generic_visit(node)

   # -----------------------------------------------------------------------
   # Module-level declarations
   # -----------------------------------------------------------------------

   def _VisitModuleDecl(self, node: ast.Assign | ast.AnnAssign) -> None:
      """Emit module_declaration for direct Module.body assignments."""
      if self._scope:
         return  # not at module level
      if isinstance(node, ast.Assign):
         for tgt in node.targets:
            if isinstance(tgt, ast.Name):
               self._Add(KIND_MODULE_DECL, tgt.id, tgt.lineno, tgt.col_offset)
      elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
         self._Add(
            KIND_MODULE_DECL, node.target.id,
            node.target.lineno, node.target.col_offset,
         )

   # -----------------------------------------------------------------------
   # Classes
   # -----------------------------------------------------------------------

   def _VisitClassDef(self, node: ast.ClassDef) -> None:
      bases = {"bases": [ast.unparse(b) for b in node.bases]}
      self._Add(KIND_CLASS, node.name, node.lineno, node.col_offset, bases)
      self._scope.append(node.name)
      self._scope_kind.append("class")
      # Visit class body
      for stmt in node.body:
         self._VisitClassBodyDecl(stmt)
      self.generic_visit(node)
      self._scope.pop()
      self._scope_kind.pop()

   def _VisitClassBodyDecl(self, stmt: ast.stmt) -> None:
      """Emit class_declaration for direct ClassDef.body assignments."""
      if isinstance(stmt, ast.Assign):
         for tgt in stmt.targets:
            if isinstance(tgt, ast.Name):
               self._Add(KIND_CLASS_DECL, tgt.id, tgt.lineno, tgt.col_offset)
      elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
         self._Add(
            KIND_CLASS_DECL, stmt.target.id,
            stmt.target.lineno, stmt.target.col_offset,
         )

   # -----------------------------------------------------------------------
   # Functions / methods
   # -----------------------------------------------------------------------

   def _VisitFuncDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
      is_method = self._InClass()
      kind      = KIND_METHOD if is_method else KIND_FUNCTION
      is_async = {"is_async": isinstance(node, ast.AsyncFunctionDef)}
      self._Add(kind, node.name, node.lineno, node.col_offset, is_async)
      self._scope.append(node.name)
      self._scope_kind.append("function")
      # Parameters
      self._IndexParameters(node)
      # Body — local writes, reads, calls, and nested class/function dispatch.
      # We walk immediate children only; nested defs/classes are handed to
      # the visitor (visit_ClassDef / _VisitFuncDef) so they get their own
      # scope pushed correctly.
      for child in ast.iter_child_nodes(node):
         if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            self.visit(child)
         else:
            # For all other child subtrees, walk and emit body symbols.
            for descendant in ast.walk(child):
               self._IndexFunctionBodyNode(descendant)
      self._scope.pop()
      self._scope_kind.pop()

   def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
      self._VisitFuncDef(node)

   def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
      self._VisitFuncDef(node)

   def _IndexParameters(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
      args = fn.args
      all_args = (
         args.posonlyargs
         + args.args
         + args.kwonlyargs
         + ([args.vararg] if args.vararg else [])
         + ([args.kwarg]  if args.kwarg  else [])
      )
      for arg in all_args:
         ann_str = ast.unparse(arg.annotation) if arg.annotation else None
         extra = {"annotation": ann_str}
         self._Add(KIND_PARAMETER, arg.arg, arg.lineno, arg.col_offset, extra)

   # -----------------------------------------------------------------------
   # Function body nodes
   # -----------------------------------------------------------------------

   def _IndexFunctionBodyNode(self, node: ast.AST) -> None:
      """
      Emit local_write, name_read, call, and attribute_call entries for
      nodes encountered while walking a function body.

      Nested ClassDef / FunctionDef nodes are handled by normal visitor
      dispatch (visit_ClassDef / _VisitFuncDef) so we skip them here to
      avoid double-counting.
      """
      if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
         return  # handled by visitor dispatch

      # Local writes --------------------------------------------------------
      if isinstance(node, ast.Assign):
         for tgt in node.targets:
            self._IndexWriteTarget(tgt)
      elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
         tgt = node.target  # type: ignore[union-attr]
         self._IndexWriteTarget(tgt)
      elif isinstance(node, ast.For):
         self._IndexWriteTarget(node.target)
      elif isinstance(node, ast.With):
         for item in node.items:
            if item.optional_vars is not None:
               self._IndexWriteTarget(item.optional_vars)
      elif isinstance(node, ast.ExceptHandler) and node.name:
         self._Add(
            KIND_LOCAL_WRITE, node.name, node.lineno, node.col_offset
         )

      # Calls ---------------------------------------------------------------
      elif isinstance(node, ast.Call):
         self._IndexCall(node)

      # Name reads ----------------------------------------------------------
      elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
         self._Add(KIND_NAME_READ, node.id, node.lineno, node.col_offset)

   def _IndexWriteTarget(self, target: ast.expr) -> None:
      match target:
         case ast.Name(id=name, lineno=ln, col_offset=co):
            self._Add(KIND_LOCAL_WRITE, name, ln, co)
         case ast.Tuple(elts=elts) | ast.List(elts=elts):
            for elt in elts:
               self._IndexWriteTarget(elt)
         case ast.Starred(value=v):
            self._IndexWriteTarget(v)
         case _:
            pass

   def _IndexCall(self, node: ast.Call) -> None:
      match node.func:
         case ast.Name(id=name, lineno=ln, col_offset=co):
            call_extra = {"args": len(node.args), "kwargs": len(node.keywords)}
            self._Add(KIND_CALL, name, ln, co, call_extra)
         case ast.Attribute(attr=attr, lineno=ln, col_offset=co):
            # Build "obj.method" representation from the call target
            full = ast.unparse(node.func)
            attr_extra = {
               "full": full,
               "args": len(node.args),
               "kwargs": len(node.keywords),
            }
            self._Add(KIND_ATTR_CALL, attr, ln, co, attr_extra)
         case _:
            pass

   # -----------------------------------------------------------------------
   # Top-level dispatch for module body
   # -----------------------------------------------------------------------

   def _VisitModule(self, node: ast.Module) -> None:
      for stmt in node.body:
         self._VisitModuleDecl(stmt)
      self.generic_visit(node)


   # NodeVisitor dispatch shims — required names for ast.NodeVisitor.
   # Logic lives in the PascalCase _Visit* methods above.
   def visit_Import(self, node: ast.Import) -> None:
      self._VisitImport(node)

   def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
      self._VisitImportFrom(node)

   def visit_ClassDef(self, node: ast.ClassDef) -> None:
      self._VisitClassDef(node)

   def visit_Module(self, node: ast.Module) -> None:
      self._VisitModule(node)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def IndexFile(path: Path) -> FileIndex | FileError:
   """
   Index one Python file and return either a FileIndex or a FileError.

   Never raises — all errors are captured in FileError so the caller can
   continue with other files.
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

   indexer = _Indexer(path_str)
   indexer.visit(tree)

   return FileIndex(FilePath=path_str, Symbols=indexer.Symbols)
