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


@dataclass
class _ClassMethodTarget:
   Confidence : str
   Method     : Definition
   OwnerClass : Definition
   Module     : str        = ""
   Reason     : str        = ""


class ProjectGraph:
   """Conservative project-level graph for read-only reference lookup."""

   def __init__(
      self, results: list[ResolveResult], errors: list[FileError], scan_roots: list[Path]
   ) -> None:
      self.Results   = results
      self.Errors    = errors
      self.ScanRoots = scan_roots
      self._ModuleMap        : dict[str, ResolveResult] = {}
      self._AmbiguousModules : set[str]                  = set()
      self._ModuleDefs       : dict[tuple[str, str], Definition] = {}
      self._ImportCache      : dict[_SymbolLocation, _ImportTarget] = {}
      self._HelperParamTypes : dict[tuple[str, int, int, str], _ClassMethodTarget] | None = None
      self._BuildModuleMap()
      self._BuildModuleDefs()

   # -----------------------------------------------------------------------
   # Build helpers
   # -----------------------------------------------------------------------

   def _BuildModuleMap(self) -> None:
      module_paths = _InspectModulePaths(
         [Path(result.FilePath) for result in self.Results],
         self.ScanRoots,
      )
      result_by_path = {str(Path(result.FilePath).resolve()): result for result in self.Results}
      for module_name, paths in module_paths.items():
         self._ModuleMap[module_name] = result_by_path[str(Path(paths[0]).resolve())]
         if len(paths) > 1:
            self._AmbiguousModules.add(module_name)

   def _BuildModuleDefs(self) -> None:
      export_kinds = {
         DefKind.ClassDef,
         DefKind.FunctionDef,
         DefKind.ModuleDecl,
      }
      for module_name, result in self._ModuleMap.items():
         if module_name in self._AmbiguousModules:
            continue
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
      selected_name = ""
      if selected_def is not None:
         selected_name = selected_def.Name
         target_locs.add(self._DefLocation(selected_def))
         if selected_def.Kind in (DefKind.Import, DefKind.ImportFrom):
            import_target = self._ResolveImportDefinition(selected_def)
            if import_target.Target is not None:
               target_locs.add(self._DefLocation(import_target.Target))
      elif selected_ref is not None:
         selected_name = selected_ref.Name
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
         elif selected_name and ref.Name == selected_name:
            if project_ref.Confidence in (CONF_UNRESOLVED, CONF_DYNAMIC):
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
         class_method_target = self._ResolveDynamicReceiverMethodAttribute(ref)
         if class_method_target is None:
            class_method_target = self._ResolveDynamicClassMethodAttribute(ref)
         if class_method_target is not None:
            confidence = class_method_target.Confidence
            target = self._ProjectDefinition(
               class_method_target.Method,
               confidence=confidence,
            )
            extra = {
               **extra,
               "receiver_kind":              (
                  "instance"
                  if class_method_target.Reason == "receiver_type_found"
                  else "class"
               ),
               "owner_class_name":           class_method_target.OwnerClass.Name,
               "owner_class_qualified_name": self._ClassQualifiedName(
                  class_method_target.OwnerClass
               ),
               "method_name":                ref.Name,
               "method_target":              self._MethodTargetDict(
                  class_method_target.Method,
                  confidence=confidence,
               ),
            }
            if class_method_target.Module:
               extra["import_target"] = {
                  "confidence": class_method_target.Confidence,
                  "module":     class_method_target.Module,
                  "reason":     class_method_target.Reason,
                  "definition": self._ProjectDefinition(
                     class_method_target.OwnerClass,
                     confidence=class_method_target.Confidence,
                  ).ToDict(),
               }
         else:
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



   def _ResolveDynamicReceiverMethodAttribute(
      self, ref: Reference
   ) -> _ClassMethodTarget | None:
      receiver = ref.Extra.get("receiver_name")
      if not isinstance(receiver, str) or not receiver:
         return None
      param_target = self._InferredTargetForReceiver(ref, receiver)
      if param_target is not None:
         class_target = param_target
      else:
         type_name = self._ReceiverTypeName(ref, receiver)
         if type_name is None:
            return None
         class_target = self._ResolveSimpleClassName(ref, type_name)
         if class_target is None:
            return None
      method = self._DirectMethodForClass(class_target.OwnerClass, ref.Name)
      if method is None:
         return None
      return _ClassMethodTarget(
         Confidence = class_target.Confidence,
         Method     = method,
         OwnerClass = class_target.OwnerClass,
         Module     = class_target.Module,
         Reason     = "receiver_type_found",
      )

   def _ReceiverTypeName(self, ref: Reference, receiver: str) -> str | None:
      defs = [
         defn for defn in ref.ScopeRef.Defs.get(receiver, [])
         if defn.Line <= ref.Line
      ]
      if len(defs) != 1:
         return None
      type_name = defs[0].Extra.get("receiver_type_name")
      if isinstance(type_name, str) and type_name:
         return type_name
      return None

   def _InferredTargetForReceiver(
      self, ref: Reference, receiver: str
   ) -> _ClassMethodTarget | None:
      defs = [
         defn for defn in ref.ScopeRef.Defs.get(receiver, [])
         if defn.Line <= ref.Line
      ]
      if len(defs) != 1 or defs[0].Kind != DefKind.Parameter:
         return None
      return self._InferredHelperParamType(defs[0])

   def _InferredHelperParamType(self, defn: Definition) -> _ClassMethodTarget | None:
      if self._HelperParamTypes is None:
         self._HelperParamTypes = self._BuildHelperParamTypes()
      key = (
         str(Path(defn.ScopeRef.FilePath).resolve()),
         defn.ScopeRef.Line,
         defn.ScopeRef.Col,
         defn.Name,
      )
      return self._HelperParamTypes.get(key)

   def _BuildHelperParamTypes(self) -> dict[tuple[str, int, int, str], _ClassMethodTarget]:
      params_by_func: dict[tuple[str, int, int], list[Definition]] = {}
      for defn in self._AllDefinitions():
         if defn.Kind != DefKind.Parameter:
            continue
         scope = defn.ScopeRef
         params_by_func.setdefault((
            str(Path(scope.FilePath).resolve()), scope.Line, scope.Col,
         ), []).append(defn)

      candidates: dict[tuple[str, int, int, str], dict[_SymbolLocation, _ClassMethodTarget]] = {}
      blocked: set[tuple[str, int, int, str]] = set()
      function_calls: dict[tuple[str, int, int], list[Reference]] = {}
      for ref in self._AllReferences():
         if ref.Kind.value != "call" or ref.IsDynamic:
            continue
         callee = self._ResolveProjectFunctionCall(ref)
         if callee is None:
            continue
         loc = self._FunctionLocation(callee)
         if loc not in params_by_func:
            continue
         function_calls.setdefault(loc, []).append(ref)

      for func_loc, calls in function_calls.items():
         params = params_by_func.get(func_loc, [])
         for call in calls:
            if call.Extra.get("has_starargs") or call.Extra.get("has_kwargs"):
               for param in params:
                  blocked.add((*func_loc, param.Name))
               continue
            if call.Extra.get("keyword_names"):
               for param in params:
                  blocked.add((*func_loc, param.Name))
               continue
            arg_names = call.Extra.get("arg_names")
            if not isinstance(arg_names, list):
               continue
            for index, param in enumerate(params):
               key = (*func_loc, param.Name)
               if index >= len(arg_names) or not isinstance(arg_names[index], str):
                  blocked.add(key)
                  continue
               type_name = self._RawReceiverTypeName(call, arg_names[index])
               if type_name is None:
                  blocked.add(key)
                  continue
               class_target = self._ResolveSimpleClassName(call, type_name)
               if class_target is None:
                  blocked.add(key)
                  continue
               candidates.setdefault(key, {})[
                  self._DefLocation(class_target.OwnerClass)
               ] = class_target

      inferred: dict[tuple[str, int, int, str], _ClassMethodTarget] = {}
      for key, types in candidates.items():
         if key in blocked or len(types) != 1:
            continue
         inferred[key] = next(iter(types.values()))
      return inferred

   def _RawReceiverTypeName(self, ref: Reference, receiver: str) -> str | None:
      defs = [
         defn for defn in ref.ScopeRef.Defs.get(receiver, [])
         if defn.Line <= ref.Line
      ]
      if len(defs) != 1:
         return None
      type_name = defs[0].Extra.get("receiver_type_name")
      if not isinstance(type_name, str) or not type_name:
         return None
      return type_name

   def _ResolveProjectFunctionCall(self, ref: Reference) -> Definition | None:
      defn = ref.ResolvedTo or ref.ScopeRef.ResolveName(ref.Name)
      if defn is None:
         return None
      if defn.Kind == DefKind.FunctionDef:
         return defn
      if defn.Kind not in (DefKind.Import, DefKind.ImportFrom):
         return None
      import_target = self._ResolveImportDefinition(defn)
      if import_target.Confidence != CONF_IMPORT_RESOLVED:
         return None
      if import_target.Target is None or import_target.Target.Kind != DefKind.FunctionDef:
         return None
      return import_target.Target

   def _FunctionLocation(self, defn: Definition) -> tuple[str, int, int]:
      return (str(Path(defn.ScopeRef.FilePath).resolve()), defn.Line, defn.Col)

   def _ResolveDynamicClassMethodAttribute(
      self, ref: Reference
   ) -> _ClassMethodTarget | None:
      full = ref.Extra.get("full")
      if not isinstance(full, str) or "." not in full:
         return None
      owner_expr = full.rsplit(".", 1)[0]
      class_target = self._ResolveClassExpression(ref, owner_expr)
      if class_target is None:
         return None
      method = self._DirectMethodForClass(class_target.OwnerClass, ref.Name)
      if method is None:
         return None
      return _ClassMethodTarget(
         Confidence = class_target.Confidence,
         Method     = method,
         OwnerClass = class_target.OwnerClass,
         Module     = class_target.Module,
         Reason     = class_target.Reason,
      )

   def _ResolveClassExpression(
      self, ref: Reference, owner_expr: str
   ) -> _ClassMethodTarget | None:
      parts = owner_expr.split(".")
      if len(parts) == 1:
         return self._ResolveSimpleClassName(ref, parts[0])
      return self._ResolveImportedModuleClass(ref, parts)

   def _ResolveSimpleClassName(
      self, ref: Reference, name: str
   ) -> _ClassMethodTarget | None:
      defn = ref.ScopeRef.ResolveName(name)
      if defn is None:
         return None
      if defn.Kind == DefKind.ClassDef:
         return _ClassMethodTarget(
            Confidence = CONF_LOCAL_RESOLVED,
            Method     = defn,
            OwnerClass = defn,
            Reason     = "local_class_found",
         )
      if defn.Kind not in (DefKind.Import, DefKind.ImportFrom):
         return None
      import_target = self._ResolveImportDefinition(defn)
      if import_target.Confidence != CONF_IMPORT_RESOLVED:
         return None
      if import_target.Target is None:
         return None
      if import_target.Target.Kind != DefKind.ClassDef:
         return None
      return _ClassMethodTarget(
         Confidence = CONF_IMPORT_RESOLVED,
         Method     = import_target.Target,
         OwnerClass = import_target.Target,
         Module     = import_target.Module,
         Reason     = "imported_class_found",
      )

   def _ResolveImportedModuleClass(
      self, ref: Reference, parts: list[str]
   ) -> _ClassMethodTarget | None:
      base_def = ref.ScopeRef.ResolveName(parts[0])
      if base_def is None:
         return None
      if base_def.Kind not in (DefKind.Import, DefKind.ImportFrom):
         return None
      import_target = self._ResolveImportDefinition(base_def)
      if import_target.Confidence != CONF_IMPORT_RESOLVED:
         return None

      class_name = parts[-1]
      module_prefix = ".".join(parts[:-1])
      imported_module = str(base_def.Extra.get("module", ""))
      allowed_prefixes = {
         base_def.Name,
         imported_module,
         import_target.Module,
      }
      if module_prefix not in allowed_prefixes:
         return None
      class_def = self._ModuleDefs.get((import_target.Module, class_name))
      if class_def is None or class_def.Kind != DefKind.ClassDef:
         return None
      return _ClassMethodTarget(
         Confidence = CONF_IMPORT_RESOLVED,
         Method     = class_def,
         OwnerClass = class_def,
         Module     = import_target.Module,
         Reason     = "module_class_found",
      )

   def _DirectMethodForClass(
      self, class_def: Definition, method_name: str
   ) -> Definition | None:
      for defn in self._AllDefinitions():
         if defn.Kind != DefKind.MethodDef or defn.Name != method_name:
            continue
         owner_file = str(defn.Extra.get("owner_class_file", ""))
         if not _SamePath(owner_file, class_def.ScopeRef.FilePath):
            continue
         if defn.Extra.get("owner_class_line") != class_def.Line:
            continue
         if defn.Extra.get("owner_class_col") != class_def.Col:
            continue
         return defn
      return None

   def _ResolveDynamicImportAttribute(self, ref: Reference) -> _ImportTarget | None:
      full = ref.Extra.get("full")
      if not isinstance(full, str) or "." not in full:
         return None
      base_name = full.split(".", 1)[0]
      prefix = full.rsplit(".", 1)[0]
      defn = ref.ScopeRef.ResolveName(base_name)
      if defn is None or defn.Kind not in (DefKind.Import, DefKind.ImportFrom):
         return None
      module = str(defn.Extra.get("module", ""))
      import_target = self._ResolveImportDefinition(defn)
      if import_target.Confidence != CONF_IMPORT_RESOLVED:
         return None
      if prefix not in (defn.Name, module, import_target.Module):
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
      module = str(extra.get("module", ""))
      name = str(extra.get("name", defn.Name))
      level = int(extra.get("level", 0) or 0)
      if level:
         if module:
            module_target = self._ResolveRelativeModuleName(defn, level, module)
            if module_target.Confidence != CONF_IMPORT_RESOLVED:
               return module_target
            module = module_target.Module
         else:
            module_target = self._ResolveRelativeModuleName(defn, level, name)
            if module_target.Confidence == CONF_IMPORT_RESOLVED:
               return module_target
            package_target = self._ResolveRelativeModuleName(defn, level, "")
            if package_target.Confidence != CONF_IMPORT_RESOLVED:
               return package_target
            module = package_target.Module
      elif not module:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="module_not_found",
         )

      if module in self._AmbiguousModules:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="module_ambiguous",
         )
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
         Reason="module_name_found",
      )

   def _ResolveImport(self, defn: Definition) -> _ImportTarget:
      module = str(defn.Extra.get("module", ""))
      return self._ResolveAbsoluteModuleName(module)

   def _ResolveAbsoluteModuleName(self, module: str) -> _ImportTarget:
      if module in self._AmbiguousModules:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="module_ambiguous",
         )
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

   def _ResolveRelativeModuleName(
      self, defn: Definition, level: int, module: str
   ) -> _ImportTarget:
      packages = self._ImporterPackages(defn.ScopeRef.FilePath)
      if not packages:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="relative_import_outside_package",
         )

      targets: list[_ImportTarget] = []
      unresolved: list[_ImportTarget] = []
      up_count = level - 1
      for package in packages:
         package_parts = package.split(".") if package else []
         if up_count > len(package_parts):
            unresolved.append(_ImportTarget(
               Confidence=CONF_UNRESOLVED,
               Module=module,
               Reason="relative_import_beyond_top",
            ))
            continue
         base_parts = package_parts[:len(package_parts) - up_count]
         module_parts = module.split(".") if module else []
         resolved = ".".join([*base_parts, *module_parts])
         target = self._ResolveAbsoluteModuleName(resolved)
         targets.append(target)

      resolved_targets = [t for t in targets if t.Confidence == CONF_IMPORT_RESOLVED]
      modules = {t.Module for t in resolved_targets}
      if len(modules) == 1:
         return resolved_targets[0]
      if len(modules) > 1:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="namespace_package_ambiguous",
         )
      ambiguous_targets = [
         t for t in targets if t.Reason in ("module_ambiguous", "namespace_package_ambiguous")
      ]
      if ambiguous_targets:
         return _ImportTarget(
            Confidence=CONF_UNRESOLVED,
            Module=module,
            Reason="namespace_package_ambiguous",
         )
      if targets:
         return targets[0]
      if unresolved:
         return unresolved[0]
      return _ImportTarget(
         Confidence=CONF_UNRESOLVED,
         Module=module,
         Reason="module_not_found",
      )

   def _ImporterPackages(self, file_path: str) -> list[str]:
      path = Path(file_path)
      regular = _RegularPackageName(path)
      if regular is not None:
         return [regular]

      packages: list[str] = []
      for root in self.ScanRoots:
         rel_package = _NamespacePackageName(path.parent, root)
         if rel_package:
            packages.append(rel_package)
      return list(dict.fromkeys(packages))

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

   def _ClassQualifiedName(self, class_def: Definition) -> str:
      for scope in self._AllScopes():
         if not _SamePath(scope.FilePath, class_def.ScopeRef.FilePath):
            continue
         if scope.Kind.value != "class":
            continue
         if scope.Line == class_def.Line and scope.Col == class_def.Col:
            return scope.QualName
      return class_def.Name

   def _MethodTargetDict(self, defn: Definition, *, confidence: str) -> dict:
      project_def = self._ProjectDefinition(defn, confidence=confidence).ToDict()
      return {
         "name":           defn.Name,
         "kind":           defn.Kind.value,
         "file":           defn.ScopeRef.FilePath,
         "line":           defn.Line,
         "col":            defn.Col,
         "scope_id":       defn.ScopeRef.ScopeId,
         "qualified_name": project_def["qualified_name"],
         "definition":     project_def,
      }

   # -----------------------------------------------------------------------
   # Iteration and identity helpers
   # -----------------------------------------------------------------------

   def _AllDefinitions(self) -> list[Definition]:
      return [d for result in self.Results for d in result.Definitions]

   def _AllReferences(self) -> list[Reference]:
      return [r for result in self.Results for r in result.References]

   def _AllScopes(self) -> list:
      return [s for result in self.Results for s in result.Tree.AllScopes]

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

def InspectProjectModules(paths: list[str]) -> dict:
   """Return module candidates and ambiguity diagnostics for scanned paths."""
   errors: list[str] = []
   try:
      files = CollectFiles(paths)
   except FileNotFoundError as exc:
      errors.append(str(exc))
      files = []

   scan_roots = _ScanRoots(paths)
   modules = _InspectModulePaths(files, scan_roots)
   return {
      "modules":           {name: [str(p) for p in items] for name, items in modules.items()},
      "ambiguous_modules": sorted(
         name for name, items in modules.items() if len(items) > 1
      ),
      "scan_roots":        [str(root) for root in scan_roots],
      "errors":            errors,
   }


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

   scan_roots = _ScanRoots(paths)
   return ProjectGraph(results, errors, scan_roots), discovery_errors


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

def _InspectModulePaths(files: list[Path], scan_roots: list[Path]) -> dict[str, list[Path]]:
   modules: dict[str, list[Path]] = {}
   for path in files:
      for module_name in _ModuleCandidates(path, scan_roots):
         items = modules.setdefault(module_name, [])
         if not any(_SamePath(str(existing), str(path)) for existing in items):
            items.append(path)
   return {name: modules[name] for name in sorted(modules)}


def _ScanRoots(paths: list[str]) -> list[Path]:
   roots: list[Path] = []
   for raw in paths:
      path = Path(raw)
      root = path.parent if path.is_file() else path
      try:
         root = root.resolve()
      except OSError:
         pass
      if root not in roots:
         roots.append(root)
   return roots


def _ModuleCandidates(path: Path, scan_roots: list[Path]) -> list[str]:
   candidates: list[str] = []
   stem = path.stem
   if stem != "__init__":
      candidates.append(stem)

   regular = _RegularModuleName(path)
   if regular:
      candidates.append(regular)

   for root in scan_roots:
      relative = _NamespaceModuleName(path, root)
      if relative:
         candidates.append(relative)

   return list(dict.fromkeys(candidates))


def _RegularModuleName(path: Path) -> str:
   package = _RegularPackageName(path)
   if package is None:
      return ""
   if path.stem == "__init__":
      return package
   return f"{package}.{path.stem}" if package else path.stem


def _RegularPackageName(path: Path) -> str | None:
   if not (path.parent / "__init__.py").exists():
      return None

   parts: list[str] = []
   cur = path.parent
   while (cur / "__init__.py").exists():
      parts.append(cur.name)
      cur = cur.parent
   return ".".join(reversed(parts))


def _NamespaceModuleName(path: Path, root: Path) -> str:
   rel = _RelativePath(path, root)
   if rel is None or rel.suffix != ".py":
      return ""
   parts = list(rel.with_suffix("").parts)
   if not parts:
      return ""
   if parts[-1] == "__init__":
      parts = parts[:-1]
   return ".".join(parts)


def _NamespacePackageName(path: Path, root: Path) -> str:
   rel = _RelativePath(path, root)
   if rel is None:
      return ""
   parts = list(rel.parts)
   return ".".join(parts)


def _RelativePath(path: Path, root: Path) -> Path | None:
   try:
      return path.resolve().relative_to(root.resolve())
   except (OSError, ValueError):
      return None


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
