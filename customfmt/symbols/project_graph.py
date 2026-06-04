"""
Project-level read-only reference discovery foundation.

This module builds on the per-file resolver and adds a conservative import
resolution layer for reference lookup.  It does not rewrite files and it does
not plan project-wide renames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from customfmt.discovery import CollectFiles
from customfmt.symbols.model import FileError
from customfmt.symbols.resolver import ResolveFile, ResolveResult
from customfmt.symbols.scopes import Definition, DefKind, Reference

CONF_LOCAL_RESOLVED  = "local_resolved"
CONF_IMPORT_RESOLVED = "import_resolved"
CONF_UNRESOLVED      = "unresolved"
CONF_DYNAMIC         = "dynamic"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProjectDefinition:
   """One project-level definition or import binding."""

   Name          : str
   Kind          : str
   FilePath      : str
   Line          : int
   Col           : int
   ScopeId       : str
   ScopeName     : str
   Confidence    : str
   QualifiedName : str  = ""
   Extra         : dict = field(default_factory=dict)

   def ToDict(self) -> dict:
      return {
         "name":           self.Name,
         "kind":           self.Kind,
         "file":           self.FilePath,
         "line":           self.Line,
         "col":            self.Col,
         "scope_id":       self.ScopeId,
         "scope":          self.ScopeName,
         "qualified_name": self.QualifiedName,
         "confidence":     self.Confidence,
         "extra":          self.Extra,
      }


@dataclass
class ProjectReference:
   """One project-level reference lookup result."""

   Name       : str
   Kind       : str
   FilePath   : str
   Line       : int
   Col        : int
   ScopeId    : str
   ScopeName  : str
   Confidence : str
   ResolvedTo : ProjectDefinition | None = None
   Extra      : dict                     = field(default_factory=dict)

   def ToDict(self) -> dict:
      return {
         "name":        self.Name,
         "kind":        self.Kind,
         "file":        self.FilePath,
         "line":        self.Line,
         "col":         self.Col,
         "scope_id":    self.ScopeId,
         "scope":       self.ScopeName,
         "confidence":  self.Confidence,
         "resolved_to": (
            self.ResolvedTo.ToDict() if self.ResolvedTo is not None else None
         ),
         "extra":       self.Extra,
      }


@dataclass
class RefsResult:
   """JSON container for one reference lookup."""

   Query                : dict
   Definitions          : list[ProjectDefinition] = field(default_factory=list)
   References           : list[ProjectReference]  = field(default_factory=list)
   UnresolvedReferences : list[ProjectReference]  = field(default_factory=list)
   DynamicReferences    : list[ProjectReference]  = field(default_factory=list)
   Errors               : list[FileError]         = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "query":                 self.Query,
         "definitions":           [d.ToDict() for d in self.Definitions],
         "references":            [r.ToDict() for r in self.References],
         "unresolved_references":  [r.ToDict() for r in self.UnresolvedReferences],
         "dynamic_references":     [r.ToDict() for r in self.DynamicReferences],
         "errors":                [e.ToDict() for e in self.Errors],
         "summary": {
            "definitions":          len(self.Definitions),
            "references":           len(self.References),
            "unresolved_references": len(self.UnresolvedReferences),
            "dynamic_references":    len(self.DynamicReferences),
            "errors":               len(self.Errors),
         },
      }


# ---------------------------------------------------------------------------
# Graph internals
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _SymbolLocation:
   FilePath : str
   Line     : int
   Col      : int
   Name     : str
   Kind     : str


@dataclass
class _ImportTarget:
   Confidence : str
   Target     : Definition | None = None
   Module     : str               = ""
   Reason     : str               = ""


class ProjectGraph:
   """Conservative project-level graph for read-only reference lookup."""

   def __init__(self, results: list[ResolveResult], errors: list[FileError]) -> None:
      self.Results = results
      self.Errors  = errors
      self._ModuleMap    : dict[str, ResolveResult] = {}
      self._ModuleDefs   : dict[tuple[str, str], Definition] = {}
      self._ImportCache  : dict[_SymbolLocation, _ImportTarget] = {}
      self._BuildModuleMap()
      self._BuildModuleDefs()

   # -----------------------------------------------------------------------
   # Build helpers
   # -----------------------------------------------------------------------

   def _BuildModuleMap(self) -> None:
      paths = [Path(r.FilePath) for r in self.Results]
      for result in self.Results:
         for name in _ModuleCandidates(Path(result.FilePath), paths):
            self._ModuleMap.setdefault(name, result)

   def _BuildModuleDefs(self) -> None:
      export_kinds = {
         DefKind.ClassDef,
         DefKind.FunctionDef,
         DefKind.ModuleDecl,
      }
      for module_name, result in self._ModuleMap.items():
         for defn in result.Definitions:
            if defn.ScopeRef.Parent is None and defn.Kind in export_kinds:
               key = (module_name, defn.Name)
               self._ModuleDefs.setdefault(key, defn)

   # -----------------------------------------------------------------------
   # Lookup API
   # -----------------------------------------------------------------------

   def FindByName(self, name: str) -> RefsResult:
      output = RefsResult(Query={"type": "name", "name": name})
      output.Errors.extend(self.Errors)

      target_locs: set[_SymbolLocation] = set()
      for defn in self._AllDefinitions():
         project_def = self._ProjectDefinition(defn)
         import_target = None
         if defn.Kind in (DefKind.Import, DefKind.ImportFrom):
            import_target = self._ResolveImportDefinition(defn)
            project_def.Confidence = import_target.Confidence
            project_def.Extra = {
               **project_def.Extra,
               "import_target": self._ImportTargetDict(import_target),
            }
         if defn.Name == name:
            output.Definitions.append(project_def)
            if import_target is not None and import_target.Target is not None:
               target_locs.add(self._DefLocation(import_target.Target))
            else:
               target_locs.add(self._DefLocation(defn))
         elif import_target is not None and import_target.Target is not None:
            if import_target.Target.Name == name:
               output.Definitions.append(project_def)
               target_locs.add(self._DefLocation(import_target.Target))

      for ref in self._AllReferences():
         project_ref = self._ProjectReference(ref)
         target = project_ref.ResolvedTo
         if ref.Name == name or (
            target is not None and target.Name == name
         ):
            self._AppendReference(output, project_ref)
            if target is not None:
               target_locs.add(self._ProjectDefLocation(target))

      self._AddTargetDefinitions(output, target_locs)
      return output

   def FindBySymbol(self, symbol: str) -> RefsResult:
      file_path, line, col = ParseSymbol(symbol)
      output = RefsResult(Query={
         "type": "symbol",
         "symbol": symbol,
         "file": file_path,
         "line": line,
         "col": col,
      })
      output.Errors.extend(self.Errors)

      selected_def = self._FindDefinitionAt(file_path, line, col)
      selected_ref = self._FindReferenceAt(file_path, line, col)

      target_locs: set[_SymbolLocation] = set()
      if selected_def is not None:
         target_locs.add(self._DefLocation(selected_def))
         if selected_def.Kind in (DefKind.Import, DefKind.ImportFrom):
            import_target = self._ResolveImportDefinition(selected_def)
            if import_target.Target is not None:
               target_locs.add(self._DefLocation(import_target.Target))
      elif selected_ref is not None:
         selected_project_ref = self._ProjectReference(selected_ref)
         self._AppendReference(output, selected_project_ref)
         if selected_project_ref.ResolvedTo is not None:
            target_locs.add(self._ProjectDefLocation(selected_project_ref.ResolvedTo))

      self._AddTargetDefinitions(output, target_locs)
      for ref in self._AllReferences():
         project_ref = self._ProjectReference(ref)
         target = project_ref.ResolvedTo
         if target is not None and self._ProjectDefLocation(target) in target_locs:
            self._AppendReference(output, project_ref)

      return output

   # -----------------------------------------------------------------------
   # Reference projection
   # -----------------------------------------------------------------------

   def _ProjectReference(self, ref: Reference) -> ProjectReference:
      confidence = CONF_UNRESOLVED
      target = None
      extra = dict(ref.Extra)

      if ref.IsDynamic:
         import_target = self._ResolveDynamicImportAttribute(ref)
         if import_target is not None and import_target.Target is not None:
            extra["import_target"] = self._ImportTargetDict(import_target)
            confidence = CONF_IMPORT_RESOLVED
            target = self._ProjectDefinition(
               import_target.Target,
               confidence=CONF_IMPORT_RESOLVED,
            )
         else:
            confidence = CONF_DYNAMIC
      elif ref.ResolvedTo is not None:
         defn = ref.ResolvedTo
         if defn.Kind in (DefKind.Import, DefKind.ImportFrom):
            import_target = self._ResolveImportDefinition(defn)
            extra["import_target"] = self._ImportTargetDict(import_target)
            confidence = import_target.Confidence
            if import_target.Target is not None:
               target = self._ProjectDefinition(
                  import_target.Target,
                  confidence=CONF_IMPORT_RESOLVED,
               )
            else:
               target = self._ProjectDefinition(defn, confidence=confidence)
         else:
            confidence = CONF_LOCAL_RESOLVED
            target = self._ProjectDefinition(defn, confidence=confidence)

      return ProjectReference(
         Name       = ref.Name,
         Kind       = ref.Kind.value,
         FilePath   = ref.ScopeRef.FilePath,
         Line       = ref.Line,
         Col        = ref.Col,
         ScopeId    = ref.ScopeRef.ScopeId,
         ScopeName  = ref.ScopeRef.QualName,
         Confidence = confidence,
         ResolvedTo = target,
         Extra      = extra,
      )

   def _AppendReference(self, output: RefsResult, ref: ProjectReference) -> None:
      if not _HasReference(output.References, ref):
         output.References.append(ref)
      if ref.Confidence == CONF_UNRESOLVED:
         if not _HasReference(output.UnresolvedReferences, ref):
            output.UnresolvedReferences.append(ref)
      elif ref.Confidence == CONF_DYNAMIC:
         if not _HasReference(output.DynamicReferences, ref):
            output.DynamicReferences.append(ref)

   # -----------------------------------------------------------------------
   # Definition projection
   # -----------------------------------------------------------------------

   def _ProjectDefinition(
      self, defn: Definition, confidence: str = CONF_LOCAL_RESOLVED
   ) -> ProjectDefinition:
      scope = defn.ScopeRef
      qual_name = f"{scope.QualName}.{defn.Name}" if scope.QualName else defn.Name
      return ProjectDefinition(
         Name          = defn.Name,
         Kind          = defn.Kind.value,
         FilePath      = scope.FilePath,
         Line          = defn.Line,
         Col           = defn.Col,
         ScopeId       = scope.ScopeId,
         ScopeName     = scope.QualName,
         QualifiedName = qual_name,
         Confidence    = confidence,
         Extra         = dict(defn.Extra),
      )

   def _AddTargetDefinitions(
      self, output: RefsResult, target_locs: set[_SymbolLocation]
   ) -> None:
      for defn in self._AllDefinitions():
         if self._DefLocation(defn) in target_locs:
            project_def = self._ProjectDefinitionForOutput(defn)
            if not _HasDefinition(output.Definitions, project_def):
               output.Definitions.append(project_def)

   def _ProjectDefinitionForOutput(self, defn: Definition) -> ProjectDefinition:
      project_def = self._ProjectDefinition(defn)
      if defn.Kind in (DefKind.Import, DefKind.ImportFrom):
         import_target = self._ResolveImportDefinition(defn)
         project_def.Confidence = import_target.Confidence
         project_def.Extra = {
            **project_def.Extra,
            "import_target": self._ImportTargetDict(import_target),
         }
      return project_def

   # -----------------------------------------------------------------------
   # Import resolution
   # -----------------------------------------------------------------------


   def _ResolveDynamicImportAttribute(self, ref: Reference) -> _ImportTarget | None:
      full = ref.Extra.get("full")
      if not isinstance(full, str) or "." not in full:
         return None
      base_name = full.split(".", 1)[0]
      prefix = full.rsplit(".", 1)[0]
      defn = ref.ScopeRef.ResolveName(base_name)
      if defn is None or defn.Kind != DefKind.Import:
         return None
      module = str(defn.Extra.get("module", ""))
      if prefix not in (defn.Name, module):
         return None
      import_target = self._ResolveImportDefinition(defn)
      if import_target.Confidence != CONF_IMPORT_RESOLVED:
         return None
      target = self._ModuleDefs.get((import_target.Module, ref.Name))
      if target is None:
         return None
      return _ImportTarget(
         Confidence=CONF_IMPORT_RESOLVED,
         Target=target,
         Module=import_target.Module,
         Reason="module_attribute_found",
      )

   def _ResolveImportDefinition(self, defn: Definition) -> _ImportTarget:
      loc = self._DefLocation(defn)
      cached = self._ImportCache.get(loc)
      if cached is not None:
         return cached

      if defn.Kind == DefKind.ImportFrom:
         target = self._ResolveImportFrom(defn)
      elif defn.Kind == DefKind.Import:
         target = self._ResolveImport(defn)
      else:
         target = _ImportTarget(Confidence=CONF_UNRESOLVED, Reason="not_import")

      self._ImportCache[loc] = target
      return target

   def _ResolveImportFrom(self, defn: Definition) -> _ImportTarget:
      extra = defn.Extra
      if extra.get("level", 0):
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=str(extra.get("module", "")),
            Reason="relative_import_unresolved",
         )
      module = str(extra.get("module", ""))
      name = str(extra.get("name", defn.Name))
      target = self._ModuleDefs.get((module, name))
      if target is None:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="module_or_name_not_found",
         )
      return _ImportTarget(
         Confidence=CONF_IMPORT_RESOLVED,
         Target=target,
         Module=module,
      )

   def _ResolveImport(self, defn: Definition) -> _ImportTarget:
      module = str(defn.Extra.get("module", ""))
      if module in self._ModuleMap:
         return _ImportTarget(
            Confidence=CONF_IMPORT_RESOLVED,
            Module=module,
            Reason="module_found",
         )
      return _ImportTarget(
         Confidence=CONF_UNRESOLVED,
         Module=module,
         Reason="module_not_found",
      )

   def _ImportTargetDict(self, target: _ImportTarget) -> dict:
      return {
         "confidence": target.Confidence,
         "module":     target.Module,
         "reason":     target.Reason,
         "definition": (
            self._ProjectDefinition(target.Target).ToDict()
            if target.Target is not None else None
         ),
      }

   # -----------------------------------------------------------------------
   # Iteration and identity helpers
   # -----------------------------------------------------------------------

   def _AllDefinitions(self) -> list[Definition]:
      return [d for result in self.Results for d in result.Definitions]

   def _AllReferences(self) -> list[Reference]:
      return [r for result in self.Results for r in result.References]

   def _FindDefinitionAt(
      self, file_path: str, line: int, col: int
   ) -> Definition | None:
      for defn in self._AllDefinitions():
         if _SamePath(defn.ScopeRef.FilePath, file_path):
            if defn.Line == line and defn.Col == col:
               return defn
      return None

   def _FindReferenceAt(
      self, file_path: str, line: int, col: int
   ) -> Reference | None:
      for ref in self._AllReferences():
         if _SamePath(ref.ScopeRef.FilePath, file_path):
            if ref.Line == line and ref.Col == col:
               return ref
      return None

   def _DefLocation(self, defn: Definition) -> _SymbolLocation:
      return _SymbolLocation(
         FilePath = str(Path(defn.ScopeRef.FilePath).resolve()),
         Line     = defn.Line,
         Col      = defn.Col,
         Name     = defn.Name,
         Kind     = defn.Kind.value,
      )

   def _ProjectDefLocation(self, defn: ProjectDefinition) -> _SymbolLocation:
      return _SymbolLocation(
         FilePath = str(Path(defn.FilePath).resolve()),
         Line     = defn.Line,
         Col      = defn.Col,
         Name     = defn.Name,
         Kind     = defn.Kind,
      )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def BuildProjectGraph(paths: list[str]) -> tuple[ProjectGraph | None, list[str]]:
   """Collect files, run the per-file resolver, and build a project graph."""
   discovery_errors: list[str] = []
   try:
      files = CollectFiles(paths)
   except FileNotFoundError as exc:
      discovery_errors.append(str(exc))
      return None, discovery_errors

   if not files:
      return None, discovery_errors

   results: list[ResolveResult] = []
   errors: list[FileError] = []
   for path in files:
      result = ResolveFile(path)
      if isinstance(result, FileError):
         errors.append(result)
      else:
         results.append(result)

   return ProjectGraph(results, errors), discovery_errors


def FindRefsByName(paths: list[str], name: str) -> tuple[RefsResult | None, list[str]]:
   """Return project-level refs for a bare symbol name."""
   graph, discovery_errors = BuildProjectGraph(paths)
   if graph is None:
      return None, discovery_errors
   return graph.FindByName(name), discovery_errors


def FindRefsBySymbol(paths: list[str], symbol: str) -> tuple[RefsResult | None, list[str]]:
   """Return project-level refs for PATH:LINE:COL."""
   graph, discovery_errors = BuildProjectGraph(paths)
   if graph is None:
      return None, discovery_errors
   return graph.FindBySymbol(symbol), discovery_errors


def ParseSymbol(symbol: str) -> tuple[str, int, int]:
   """Parse a PATH:LINE:COL symbol specifier."""
   parts = symbol.rsplit(":", 2)
   if len(parts) != 3:
      raise ValueError("symbol must use PATH:LINE:COL")
   file_path, line_raw, col_raw = parts
   try:
      line = int(line_raw)
      col  = int(col_raw)
   except ValueError as exc:
      raise ValueError("symbol line and col must be integers") from exc
   if line < 1 or col < 0:
      raise ValueError("symbol line must be >= 1 and col must be >= 0")
   return file_path, line, col


# ---------------------------------------------------------------------------
# Module-name helpers
# ---------------------------------------------------------------------------

def _ModuleCandidates(path: Path, all_paths: list[Path]) -> list[str]:
   del all_paths
   candidates: list[str] = []
   stem = path.stem
   if stem != "__init__":
      candidates.append(stem)

   parts: list[str] = []
   cur = path.parent
   while (cur / "__init__.py").exists():
      parts.append(cur.name)
      cur = cur.parent

   if parts:
      package = ".".join(reversed(parts))
      if stem == "__init__":
         candidates.append(package)
      else:
         candidates.append(f"{package}.{stem}")

   return list(dict.fromkeys(candidates))


def _SamePath(left: str, right: str) -> bool:
   try:
      return Path(left).resolve() == Path(right).resolve()
   except OSError:
      return left == right


def _HasDefinition(items: list[ProjectDefinition], item: ProjectDefinition) -> bool:
   return any(
      _SamePath(existing.FilePath, item.FilePath)
      and existing.Line == item.Line
      and existing.Col == item.Col
      and existing.Name == item.Name
      and existing.Kind == item.Kind
      for existing in items
   )


def _HasReference(items: list[ProjectReference], item: ProjectReference) -> bool:
   return any(
      _SamePath(existing.FilePath, item.FilePath)
      and existing.Line == item.Line
      and existing.Col == item.Col
      and existing.Name == item.Name
      and existing.Kind == item.Kind
      for existing in items
   )
