"""
Scope model for the customfmt symbol resolver.

A Scope represents one lexical scope in a Python file:
  - module scope    (exactly one per file)
  - class scope     (one per ClassDef)
  - function scope  (one per FunctionDef / AsyncFunctionDef)

Scopes form a tree: every non-module scope has a parent.

Each scope holds:
  - Defs          : name -> list[Definition]
  - Refs          : list[Reference]
  - GlobalNames   : set[str]   — names declared global in this function scope
  - NonlocalNames : set[str]   — names declared nonlocal in this function scope
  - Children      : list[Scope]

Scope IDs
---------
IDs are deterministic: ``<file_hash>:<qual_name>:<line>`` so that they are
stable across runs and useful for snapshot tests.

Lookup
------
ResolveName(name) walks from the innermost scope outward, implementing
Python's LEGB lookup:
  - global declarations redirect lookup to module scope immediately.
  - nonlocal declarations skip the current scope and search outward from
    the nearest enclosing function scope.
  - Class scopes are transparent when searching from a function scope
    (Python semantics: class-body names are not visible in methods).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Scope kinds
# ---------------------------------------------------------------------------

class ScopeKind(StrEnum):
   Module   = "module"
   Class    = "class"
   Function = "function"


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------

class DefKind(StrEnum):
   Import      = "import"
   ImportFrom  = "import_from"
   ModuleDecl  = "module_declaration"
   ClassDef    = "class"
   FunctionDef = "function"
   MethodDef   = "method"
   Parameter   = "parameter"
   LocalWrite  = "local_write"
   ClassDecl   = "class_declaration"


@dataclass
class Definition:
   """One definition site for a name within a scope."""

   Name     : str
   Kind     : DefKind
   Line     : int
   Col      : int
   ScopeRef : Scope
   Extra    : dict    = field(default_factory=dict)

   def ToDict(self) -> dict:
      return {
         "name":       self.Name,
         "kind":       self.Kind.value,
         "line":       self.Line,
         "col":        self.Col,
         "scope_id":   self.ScopeRef.ScopeId,
         "extra":      self.Extra,
      }


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------

class RefKind(StrEnum):
   Read       = "read"
   Write      = "write"
   Call       = "call"
   AttrCall   = "attribute_call"
   Annotation = "annotation"


@dataclass
class Reference:
   """One use of a name within a scope."""

   Name         : str
   Kind         : RefKind
   Line         : int
   Col          : int
   ScopeRef     : Scope
   ResolvedTo   : Definition | None = None
   IsUnresolved : bool              = False
   IsDynamic    : bool              = False
   Extra        : dict              = field(default_factory=dict)

   def ToDict(self) -> dict:
      resolved = None
      if self.ResolvedTo is not None:
         resolved = {
            "name":     self.ResolvedTo.Name,
            "kind":     self.ResolvedTo.Kind.value,
            "line":     self.ResolvedTo.Line,
            "scope_id": self.ResolvedTo.ScopeRef.ScopeId,
         }
      return {
         "name":        self.Name,
         "kind":        self.Kind.value,
         "line":        self.Line,
         "col":         self.Col,
         "scope_id":    self.ScopeRef.ScopeId,
         "resolved_to": resolved,
         "unresolved":  self.IsUnresolved,
         "dynamic":     self.IsDynamic,
         "extra":       self.Extra,
      }


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

def _MakeScopeId(file_path: str, qual_name: str, line: int) -> str:
   """
   Deterministic, snapshot-friendly scope ID.
   Format: ``<8-char file hash>:<qual_name or 'module'>:<line>``.
   """
   file_hash = hashlib.sha1(file_path.encode()).hexdigest()[:8]
   label = qual_name if qual_name else "module"
   return f"{file_hash}:{label}:{line}"


@dataclass
class Scope:
   """One lexical scope."""

   Kind          : ScopeKind
   Name          : str
   QualName      : str
   Line          : int
   Parent        : Scope | None
   Col           : int                         = 0
   FilePath      : str                         = ""
   ScopeId       : str                         = ""
   Children      : list[Scope]                 = field(default_factory=list)
   Defs          : dict[str, list[Definition]] = field(default_factory=dict)
   Refs          : list[Reference]             = field(default_factory=list)
   GlobalNames   : set[str]                    = field(default_factory=set)
   NonlocalNames : set[str]                    = field(default_factory=set)

   def __post_init__(self) -> None:
      if not self.ScopeId:
         self.ScopeId = _MakeScopeId(self.FilePath, self.QualName, self.Line)

   def AddDef(self, defn: Definition) -> None:
      self.Defs.setdefault(defn.Name, []).append(defn)

   def AddChild(self, child: Scope) -> None:
      self.Children.append(child)

   def ResolveName(self, name: str) -> Definition | None:
      """
      Look up *name* starting from this scope, walking outward.

      Semantics
      ---------
      - If this function scope declares ``global name``, jump directly to the
        module scope.
      - If this function scope declares ``nonlocal name``, skip this scope and
        search outward from the parent (skipping class scopes as usual).
      - Class scopes are transparent when searching from a child function
        scope (Python's LEGB rule).
      """
      return self._ResolveFrom(name, came_from_function=False)

   def _ResolveFrom(
      self, name: str, *, came_from_function: bool
   ) -> Definition | None:
      # Skip class scope when the search came from a nested function.
      if self.Kind == ScopeKind.Class and came_from_function:
         if self.Parent:
            return self.Parent._ResolveFrom(
               name, came_from_function=came_from_function
            )
         return None

      if self.Kind == ScopeKind.Function:
         # ``global name`` — redirect to module scope.
         if name in self.GlobalNames:
            return self._FindModuleScope()._LookupHere(name)
         # ``nonlocal name`` — skip this scope entirely.
         if name in self.NonlocalNames:
            if self.Parent:
               return self.Parent._ResolveFrom(name, came_from_function=True)
            return None

      # Look up in this scope first, then walk outward.
      hit = self._LookupHere(name)
      if hit is not None:
         return hit
      if self.Parent:
         return self.Parent._ResolveFrom(
            name, came_from_function=self.Kind == ScopeKind.Function
         )
      return None

   def _LookupHere(self, name: str) -> Definition | None:
      defs = self.Defs.get(name)
      return defs[0] if defs else None

   def _FindModuleScope(self) -> Scope:
      scope: Scope = self
      while scope.Parent is not None:
         scope = scope.Parent
      return scope

   def ToDict(self, *, include_children: bool = True) -> dict:
      d: dict = {
         "scope_id":      self.ScopeId,
         "kind":          self.Kind.value,
         "name":          self.Name,
         "qual_name":     self.QualName,
         "line":          self.Line,
         "parent_id":     self.Parent.ScopeId if self.Parent else None,
         "global_names":  sorted(self.GlobalNames),
         "nonlocal_names": sorted(self.NonlocalNames),
         "defs": {
            n: [df.ToDict() for df in dfl]
            for n, dfl in self.Defs.items()
         },
         "refs": [r.ToDict() for r in self.Refs],
      }
      if include_children:
         d["children"] = [c.ScopeId for c in self.Children]
      return d


# ---------------------------------------------------------------------------
# ScopeTree
# ---------------------------------------------------------------------------

@dataclass
class ScopeTree:
   """The complete scope tree for one file."""

   FilePath  : str
   Root      : Scope
   AllScopes : list[Scope] = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "file":     self.FilePath,
         "root_id":  self.Root.ScopeId,
         "scopes":   [s.ToDict() for s in self.AllScopes],
      }
