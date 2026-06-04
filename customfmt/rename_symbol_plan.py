"""Read-only project-wide rename-symbol planning."""

from __future__ import annotations

import io
import keyword
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from customfmt.io import ReadUtf8Text
from customfmt.symbols.project_graph import (
   CONF_IMPORT_RESOLVED,
   CONF_LOCAL_RESOLVED,
   BuildProjectGraph,
   ProjectDefinition,
   ProjectReference,
   RefsResult,
)
from customfmt.symbols.scopes import DefKind

SUPPORTED_TARGET_KINDS = {
   DefKind.ClassDef.value,
   DefKind.FunctionDef.value,
   DefKind.ModuleDecl.value,
}
SUPPORTED_IMPORT_KINDS = {
   DefKind.ImportFrom.value,
}
SAFE_CONFIDENCES = {
   CONF_LOCAL_RESOLVED,
   CONF_IMPORT_RESOLVED,
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RenameSymbolEdit:
   FilePath : str
   Line     : int
   Col      : int
   Old      : str
   New      : str
   Kind     : str

   def ToDict(self) -> dict:
      return {
         "file": self.FilePath,
         "line": self.Line,
         "col":  self.Col,
         "old":  self.Old,
         "new":  self.New,
         "kind": self.Kind,
      }


@dataclass
class RenameSymbolPlan:
   Query                : dict
   Target               : ProjectDefinition | None
   NewName              : str
   Edits                : list[RenameSymbolEdit]   = field(default_factory=list)
   Skipped              : list[dict]               = field(default_factory=list)
   Warnings             : list[dict]               = field(default_factory=list)
   UnresolvedReferences : list[dict]               = field(default_factory=list)
   DynamicReferences    : list[dict]               = field(default_factory=list)

   def ToDict(self) -> dict:
      files = sorted({e.FilePath for e in self.Edits})
      return {
         "query":                 self.Query,
         "target":                self.Target.ToDict() if self.Target else None,
         "new_name":              self.NewName,
         "files_affected":        files,
         "edits":                 [e.ToDict() for e in self.Edits],
         "skipped":               self.Skipped,
         "unresolved_references": self.UnresolvedReferences,
         "dynamic_references":    self.DynamicReferences,
         "warnings":              self.Warnings,
         "summary": {
            "edits":                 len(self.Edits),
            "files_affected":        len(files),
            "skipped":               len(self.Skipped),
            "unresolved_references": len(self.UnresolvedReferences),
            "dynamic_references":    len(self.DynamicReferences),
            "warnings":              len(self.Warnings),
         },
      }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def PlanRenameSymbol(
   paths: list[str], *, symbol: str | None, name: str | None, new_name: str
) -> tuple[RenameSymbolPlan | None, list[str]]:
   """Build a read-only project-wide rename plan."""
   graph, discovery_errors = BuildProjectGraph(paths)
   if graph is None:
      return None, discovery_errors

   if symbol is not None:
      refs = graph.FindBySymbol(symbol)
   elif name is not None:
      refs = graph.FindByName(name)
   else:
      raise ValueError("either --symbol or --name is required")

   target = _ChooseTarget(refs, symbol=symbol, name=name)
   _ValidateTarget(target)
   _ValidateNewName(target, new_name)

   plan = RenameSymbolPlan(
      Query   = refs.Query,
      Target  = target,
      NewName = new_name,
   )

   old_name = target.Name
   for ref in refs.UnresolvedReferences:
      plan.UnresolvedReferences.append(_SkippedRef(ref, "unresolved"))
   for ref in refs.DynamicReferences:
      plan.DynamicReferences.append(_SkippedRef(ref, "dynamic"))

   _AddDefinitionEdit(plan, target, old_name, new_name)
   for defn in refs.Definitions:
      if _ShouldRenameImportBindingDefinition(defn, target, old_name):
         _AddDefinitionEdit(plan, defn, old_name, new_name)
      elif defn.Kind in (DefKind.Import.value, DefKind.ImportFrom.value):
         if not _SameDefinition(defn, target):
            plan.Skipped.append(_SkippedDefinition(defn, "import_not_safely_resolved"))

   for ref in refs.References:
      if not _ShouldRenameReference(ref, target, old_name):
         if ref.Confidence not in SAFE_CONFIDENCES:
            continue
         plan.Skipped.append(_SkippedRef(ref, "not_target_reference"))
         continue
      _AddReferenceEdit(plan, ref, old_name, new_name)

   _DetectDefinitionCollisions(plan, graph.Results, target, new_name)
   _DetectEditConflicts(plan)
   plan.Edits.sort(key=lambda e: (e.FilePath, e.Line, e.Col, e.Kind))
   return plan, discovery_errors


# ---------------------------------------------------------------------------
# Target selection and validation
# ---------------------------------------------------------------------------

def _ChooseTarget(
   refs: RefsResult, *, symbol: str | None, name: str | None
) -> ProjectDefinition:
   if symbol is not None:
      selected = _DefinitionMatchingQuerySymbol(refs)
      if selected is not None and _IsSupportedImportAlias(selected):
         return selected
      canonical = _CanonicalTargets(refs)
      if selected is not None and selected.Kind in SUPPORTED_TARGET_KINDS:
         return selected
      if len(canonical) == 1:
         return canonical[0]
      raise ValueError("symbol does not identify a supported project symbol")

   del name
   canonical = _CanonicalTargets(refs)
   if not canonical:
      raise ValueError("--name did not match a supported project symbol")
   if len(canonical) > 1:
      names = ", ".join(_FormatDefinition(d) for d in canonical)
      raise ValueError(f"--name is ambiguous; use --symbol ({names})")
   return canonical[0]


def _DefinitionMatchingQuerySymbol(refs: RefsResult) -> ProjectDefinition | None:
   file_path = str(refs.Query.get("file", ""))
   line = refs.Query.get("line")
   col = refs.Query.get("col")
   for defn in refs.Definitions:
      if _SamePath(defn.FilePath, file_path) and defn.Line == line and defn.Col == col:
         return defn
   return None


def _CanonicalTargets(refs: RefsResult) -> list[ProjectDefinition]:
   targets: list[ProjectDefinition] = []
   for defn in refs.Definitions:
      if defn.Kind in SUPPORTED_TARGET_KINDS:
         _AppendUniqueDefinition(targets, defn)
   return targets


def _ValidateTarget(target: ProjectDefinition) -> None:
   if target.Kind in SUPPORTED_TARGET_KINDS:
      return
   if _IsSupportedImportAlias(target):
      return
   raise ValueError(f"unsupported symbol kind for project rename: {target.Kind}")


def _IsSupportedImportAlias(defn: ProjectDefinition) -> bool:
   if defn.Kind not in SUPPORTED_IMPORT_KINDS:
      return False
   asname = defn.Extra.get("asname")
   return isinstance(asname, str) and bool(asname)


def _ValidateNewName(target: ProjectDefinition, new_name: str) -> None:
   if not new_name.isidentifier() or keyword.iskeyword(new_name):
      raise ValueError("NewName must be a valid Python identifier")
   if target.Kind in (DefKind.ClassDef.value, DefKind.ImportFrom.value):
      if not _IsPascalCase(new_name):
         raise ValueError("NewName must be PascalCase for this target")
   elif target.Kind == DefKind.FunctionDef.value:
      if not _IsPascalCase(new_name):
         raise ValueError("NewName must be PascalCase for function targets")
   elif target.Kind == DefKind.ModuleDecl.value:
      if not (_IsPascalCase(new_name) or new_name.isupper()):
         raise ValueError(
            "NewName must be PascalCase or UPPER_CASE for declarations"
         )


# ---------------------------------------------------------------------------
# Edit collection
# ---------------------------------------------------------------------------

def _AddDefinitionEdit(
   plan: RenameSymbolPlan, target: ProjectDefinition, old_name: str, new_name: str
) -> None:
   token_col = _FindTokenCol(
      target.FilePath, target.Line, old_name,
      preferred_col=target.Col,
      kind=target.Kind,
   )
   if token_col is None:
      plan.Skipped.append(_SkippedDefinition(target, "token_not_found"))
      return
   plan.Edits.append(RenameSymbolEdit(
      FilePath = target.FilePath,
      Line     = target.Line,
      Col      = token_col,
      Old      = old_name,
      New      = new_name,
      Kind     = f"definition:{target.Kind}",
   ))


def _AddReferenceEdit(
   plan: RenameSymbolPlan, ref: ProjectReference, old_name: str, new_name: str
) -> None:
   token_col = _FindTokenCol(
      ref.FilePath, ref.Line, old_name,
      preferred_col=ref.Col,
      kind=ref.Kind,
   )
   if token_col is None:
      plan.Skipped.append(_SkippedRef(ref, "token_not_found"))
      return
   plan.Edits.append(RenameSymbolEdit(
      FilePath = ref.FilePath,
      Line     = ref.Line,
      Col      = token_col,
      Old      = old_name,
      New      = new_name,
      Kind     = f"reference:{ref.Kind}",
   ))


def _ShouldRenameImportBindingDefinition(
   defn: ProjectDefinition, target: ProjectDefinition, old_name: str
) -> bool:
   if _SameDefinition(defn, target):
      return False
   if defn.Kind != DefKind.ImportFrom.value:
      return False
   if defn.Extra.get("asname") is not None:
      return False
   if defn.Name != old_name:
      return False
   import_target = defn.Extra.get("import_target", {})
   resolved = import_target.get("definition")
   if not isinstance(resolved, dict):
      return False
   return _SameDefinitionDict(resolved, target)


def _ShouldRenameReference(
   ref: ProjectReference, target: ProjectDefinition, old_name: str
) -> bool:
   if ref.Confidence not in SAFE_CONFIDENCES:
      return False
   if _IsSupportedImportAlias(target):
      return ref.Name == old_name
   if ref.ResolvedTo is None:
      return False
   return _SameDefinition(ref.ResolvedTo, target) and ref.Name == old_name


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def _DetectDefinitionCollisions(
   plan: RenameSymbolPlan, results, target: ProjectDefinition, new_name: str
) -> None:
   for result in results:
      for defn in result.Definitions:
         if not _SamePath(defn.ScopeRef.FilePath, target.FilePath):
            continue
         if defn.ScopeRef.ScopeId != target.ScopeId:
            continue
         if defn.Name != new_name:
            continue
         plan.Warnings.append({
            "kind":   "collision",
            "reason": "same_scope_definition_exists",
            "file":   defn.ScopeRef.FilePath,
            "line":   defn.Line,
            "col":    defn.Col,
            "name":   new_name,
         })

      if not any(_SamePath(e.FilePath, result.FilePath) for e in plan.Edits):
         continue
      for defn in result.Definitions:
         if defn.Name != new_name:
            continue
         if defn.ScopeRef.ScopeId == target.ScopeId:
            continue
         if defn.Kind in (DefKind.Import.value, DefKind.ImportFrom.value):
            plan.Warnings.append({
               "kind":   "collision",
               "reason": "importing_file_already_binds_new_name",
               "file":   defn.ScopeRef.FilePath,
               "line":   defn.Line,
               "col":    defn.Col,
               "name":   new_name,
            })


def _DetectEditConflicts(plan: RenameSymbolPlan) -> None:
   seen: dict[tuple[str, int, int], RenameSymbolEdit] = {}
   unique: list[RenameSymbolEdit] = []
   for edit in plan.Edits:
      key = (str(Path(edit.FilePath).resolve()), edit.Line, edit.Col)
      existing = seen.get(key)
      if existing is None:
         seen[key] = edit
         unique.append(edit)
      elif existing.Old != edit.Old or existing.New != edit.New:
         plan.Warnings.append({
            "kind":   "edit_conflict",
            "reason": "two_edit_sites_conflict",
            "file":   edit.FilePath,
            "line":   edit.Line,
            "col":    edit.Col,
         })
   plan.Edits = unique


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _FindTokenCol(
   file_path: str, line: int, old_name: str, *, preferred_col: int, kind: str
) -> int | None:
   try:
      text = ReadUtf8Text(Path(file_path))
   except OSError:
      return None
   tokens = _LineNameTokens(text, line, old_name)
   if not tokens:
      return None
   exact = [col for col in tokens if col == preferred_col]
   if exact:
      return exact[0]
   after = [col for col in tokens if col >= preferred_col]
   if not after:
      return None
   if kind == "attribute_call":
      return after[-1]
   return after[0]


def _LineNameTokens(text: str, line: int, name: str) -> list[int]:
   cols: list[int] = []
   reader = io.StringIO(text).readline
   try:
      for tok in tokenize.generate_tokens(reader):
         if tok.type != tokenize.NAME:
            continue
         if tok.string != name:
            continue
         if tok.start[0] == line:
            cols.append(tok.start[1])
   except tokenize.TokenError:
      return []
   return cols


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _SkippedRef(ref: ProjectReference, reason: str) -> dict:
   return {
      "reason":     reason,
      "file":       ref.FilePath,
      "line":       ref.Line,
      "col":        ref.Col,
      "name":       ref.Name,
      "kind":       ref.Kind,
      "confidence": ref.Confidence,
   }


def _SkippedDefinition(defn: ProjectDefinition, reason: str) -> dict:
   return {
      "reason": reason,
      "file":   defn.FilePath,
      "line":   defn.Line,
      "col":    defn.Col,
      "name":   defn.Name,
      "kind":   defn.Kind,
   }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _IsPascalCase(name: str) -> bool:
   return bool(name) and name[0].isupper() and "_" not in name


def _SamePath(left: str, right: str) -> bool:
   try:
      return Path(left).resolve() == Path(right).resolve()
   except OSError:
      return left == right


def _SameDefinition(left: ProjectDefinition, right: ProjectDefinition) -> bool:
   return (
      _SamePath(left.FilePath, right.FilePath)
      and left.Line == right.Line
      and left.Col == right.Col
      and left.Name == right.Name
      and left.Kind == right.Kind
   )


def _SameDefinitionDict(left: dict, right: ProjectDefinition) -> bool:
   return (
      _SamePath(str(left.get("file", "")), right.FilePath)
      and left.get("line") == right.Line
      and left.get("col") == right.Col
      and left.get("name") == right.Name
      and left.get("kind") == right.Kind
   )


def _AppendUniqueDefinition(
   items: list[ProjectDefinition], defn: ProjectDefinition
) -> None:
   if not any(_SameDefinition(existing, defn) for existing in items):
      items.append(defn)


def _FormatDefinition(defn: ProjectDefinition) -> str:
   return f"{defn.FilePath}:{defn.Line}:{defn.Col} {defn.Name}"
