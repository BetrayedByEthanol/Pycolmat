"""
Scope model for the customfmt symbol resolver.

A Scope represents one lexical scope in a Python file:
  - module scope    (exactly one per file)
  - class scope     (one per ClassDef)
  - function scope  (one per FunctionDef / AsyncFunctionDef)

Scopes form a tree: every non-module scope has a parent.

Each scope holds:
  - Definitions : name -> list[Definition]  (a name can be defined multiple times,
                  e.g. assigned in both branches of an if; we keep all sites)
  - Children    : list[Scope]

Lookup
------
ResolveName(name) walks from the innermost scope outward, returning the
innermost Definition that covers the name.  This implements Python's
LEGB lookup (Local, Enclosing, Global, Builtin) without the B layer
(builtins are left as unresolved for now).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Scope kinds
# ---------------------------------------------------------------------------

_SCOPE_COUNTER: list[int] = [0]


def _NextScopeId() -> str:
   _SCOPE_COUNTER[0] += 1
   return f"scope_{_SCOPE_COUNTER[0]}"


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
   Line     : int      # 1-based
   Col      : int      # 0-based
   ScopeRef : Scope    # the scope that owns this definition
   Extra    : dict                                           = field(default_factory=dict)

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
   Read     = "read"
   Call     = "call"
   AttrCall = "attribute_call"


@dataclass
class Reference:
   """One use of a name within a scope."""

   Name         : str
   Kind         : RefKind
   Line         : int
   Col          : int
   ScopeRef     : Scope
   ResolvedTo   : Definition | None = None     # set by resolver
   IsUnresolved : bool              = False    # set by resolver when lookup fails
   IsDynamic    : bool              = False    # set for attr calls / dynamic use
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




@dataclass
class Scope:
   """One lexical scope."""

   Kind     : ScopeKind
   Name     : str          # "" for module, else class/function name
   QualName : str          # dotted qualified name
   Line     : int          # first line of the scope (1-based)
   Parent   : Scope | None
   ScopeId  : str                                                    = field(default_factory=_NextScopeId)
   Children : list[Scope]                                            = field(default_factory=list)
   # name -> list of definitions (all sites)
   Defs       : dict[str, list[Definition]] = field(default_factory=dict)
   # All references recorded in this scope (not children)
   Refs       : list[Reference] = field(default_factory=list)

   def AddDef(self, defn: Definition) -> None:
      self.Defs.setdefault(defn.Name, []).append(defn)

   def AddChild(self, child: Scope) -> None:
      self.Children.append(child)

   def ResolveName(self, name: str) -> Definition | None:
      """
      Look up *name* in this scope and then outward through parent scopes.

      Class scopes are transparent for LEGB lookup: Python does not make
      class-body names visible inside methods defined in that class without
      explicit qualification.  We skip class scopes when searching from a
      child function scope.
      """
      scope: Scope | None = self
      came_from_function = False
      while scope is not None:
         # Skip class scope when searching outward from a function —
         # matches Python's actual LEGB semantics.
         if scope.Kind == ScopeKind.Class and came_from_function:
            scope = scope.Parent
            continue
         if name in scope.Defs:
            # Return the first (earliest) definition at this scope level.
            return scope.Defs[name][0]
         came_from_function = scope.Kind == ScopeKind.Function
         scope = scope.Parent
      return None

   def ToDict(self, *, include_children: bool = True) -> dict:
      d: dict = {
         "scope_id":  self.ScopeId,
         "kind":      self.Kind.value,
         "name":      self.Name,
         "qual_name": self.QualName,
         "line":      self.Line,
         "parent_id": self.Parent.ScopeId if self.Parent else None,
         "defs":      {
            n: [df.ToDict() for df in dfl]
            for n, dfl in self.Defs.items()
         },
         "refs":      [r.ToDict() for r in self.Refs],
      }
      if include_children:
         d["children"] = [c.ScopeId for c in self.Children]
      return d


# ---------------------------------------------------------------------------
# ScopeTree  — container for the whole file
# ---------------------------------------------------------------------------

@dataclass
class ScopeTree:
   """The complete scope tree for one file."""

   FilePath  : str
   Root      : Scope          # the module scope
   AllScopes : list[Scope]                       = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "file":       self.FilePath,
         "root_id":    self.Root.ScopeId,
         "scopes":     [s.ToDict() for s in self.AllScopes],
      }
