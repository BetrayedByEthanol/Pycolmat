"""
Read-only project diagnostics for customfmt.

DoctorPaths(paths) inspects discovered Python files without modifying them and
returns a structured readiness report for style, formatting, symbol tooling, and
package/import support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from customfmt.checker import CheckFile
from customfmt.discovery import CollectFiles
from customfmt.formatter import ProcessFile
from customfmt.indexer import IndexPaths
from customfmt.io import UTF8_BOM, ReadUtf8Bytes
from customfmt.symbols.model import FileError
from customfmt.symbols.project_graph import _ModuleCandidates, _ScanRoots
from customfmt.symbols.resolver import ResolveFile
from customfmt.types import Violation

AUTO_FIX_CODES: tuple[str, ...] = ("CF009", "CF011", "CF013", "CF018", "CF019")
EXAMPLE_LIMIT = 5


@dataclass
class RuleSummary:
   """Summary for one customfmt rule code."""

   Code     : str
   Count    : int        = 0
   Examples : list[dict] = field(default_factory=list)

   def Add(self, violation: Violation) -> None:
      self.Count += 1
      if len(self.Examples) < EXAMPLE_LIMIT:
         self.Examples.append(violation.ToDict())

   def ToDict(self) -> dict:
      return {
         "code":     self.Code,
         "count":    self.Count,
         "examples": self.Examples,
      }


@dataclass
class DoctorReport:
   """Complete customfmt doctor report."""

   Paths            : list[str]
   PythonFiles      : list[str]
   DiscoveryErrors  : list[str] = field(default_factory=list)
   Encoding         : dict      = field(default_factory=dict)
   RuleStatus       : dict      = field(default_factory=dict)
   AutoFixReadiness : dict      = field(default_factory=dict)
   SymbolReadiness  : dict      = field(default_factory=dict)
   PackageReadiness : dict      = field(default_factory=dict)
   ExitCode         : int       = 0

   def ToDict(self) -> dict:
      return {
         "paths":                self.Paths,
         "python_file_count":    len(self.PythonFiles),
         "python_files":         self.PythonFiles,
         "discovery_errors":     self.DiscoveryErrors,
         "encoding":             self.Encoding,
         "customfmt_rules":      self.RuleStatus,
         "auto_fix_readiness":   self.AutoFixReadiness,
         "symbol_readiness":     self.SymbolReadiness,
         "package_readiness":    self.PackageReadiness,
         "exit_code":            self.ExitCode,
      }


def DoctorPaths(paths: list[str]) -> DoctorReport:
   """Inspect *paths* and return a read-only diagnostics report."""
   report = DoctorReport(Paths=list(paths), PythonFiles=[])

   try:
      files = CollectFiles(paths)
   except FileNotFoundError as exc:
      report.DiscoveryErrors.append(str(exc))
      report.ExitCode = 2
      _FillEmptySections(report)
      return report

   report.PythonFiles = [str(p) for p in files]
   if not files:
      report.ExitCode = 2
      _FillEmptySections(report)
      return report

   report.Encoding         = _InspectEncoding(files)
   checker_errors          = _InspectRules(files, report)
   report.AutoFixReadiness = _InspectAutoFixReadiness(files)
   report.SymbolReadiness  = _InspectSymbolReadiness(paths, files)
   report.PackageReadiness = _InspectPackages(paths, files)

   blocking = bool(
      report.Encoding["non_utf8_count"]
      or report.Encoding["io_error_count"]
      or report.Encoding["utf8_bom_count"]
      or report.SymbolReadiness["index_errors"]
      or report.SymbolReadiness["resolver_errors"]
      or checker_errors
   )
   style_issues = bool(
      report.RuleStatus["total_violations"]
      or report.AutoFixReadiness["would_change_count"]
   )

   if blocking:
      report.ExitCode = 2
   elif style_issues:
      report.ExitCode = 1
   else:
      report.ExitCode = 0
   return report


def FormatHuman(report: DoctorReport) -> str:
   """Render a DoctorReport as human-readable text."""
   lines: list[str] = []
   lines.append("customfmt doctor")
   lines.append("")

   lines.append("Python file discovery")
   lines.append(f"  files: {report.ToDict()['python_file_count']}")
   if not report.PythonFiles:
      lines.append("  status: no Python files found")
   for err in report.DiscoveryErrors:
      lines.append(f"  error: {err}")
   lines.append("")

   enc = report.Encoding
   lines.append("Encoding / line endings")
   lines.append(f"  non_utf8: {enc.get('non_utf8_count', 0)}")
   lines.append(f"  io_errors: {enc.get('io_error_count', 0)}")
   lines.append(f"  utf8_bom: {enc.get('utf8_bom_count', 0)}")
   lines.append(f"  crlf: {enc.get('crlf_count', 0)}")
   lines.append(f"  bare_cr: {enc.get('bare_cr_count', 0)}")
   _AppendFileExamples(lines, enc.get("non_utf8_files", []), "non_utf8_files")
   _AppendFileExamples(lines, enc.get("io_error_files", []), "io_error_files")
   _AppendFileExamples(lines, enc.get("utf8_bom_files", []), "utf8_bom_files")
   _AppendFileExamples(lines, enc.get("crlf_files", []), "crlf_files")
   _AppendFileExamples(lines, enc.get("bare_cr_files", []), "bare_cr_files")
   lines.append("")

   rules = report.RuleStatus
   lines.append("customfmt rule status")
   lines.append(f"  violations: {rules.get('total_violations', 0)}")
   by_rule = rules.get("by_rule", {})
   if by_rule:
      for code in sorted(by_rule):
         item = by_rule[code]
         lines.append(f"  {code}: {item['count']}")
         for ex in item["examples"]:
            lines.append(
               f"    {ex['path']}:{ex['line']}:{ex['col']} {ex['message']}"
            )
   else:
      lines.append("  no rule violations")
   lines.append("")

   fix = report.AutoFixReadiness
   lines.append("Auto-fix readiness")
   lines.append(f"  files that would change: {fix.get('would_change_count', 0)}")
   for code in AUTO_FIX_CODES:
      lines.append(f"  {code}: {fix.get('by_rule', {}).get(code, 0)}")
   _AppendFileExamples(lines, fix.get("would_change_files", []), "would_change_files")
   lines.append("")

   sym = report.SymbolReadiness
   lines.append("Symbol tooling readiness")
   lines.append(f"  indexed_files: {sym.get('indexed_files', 0)}")
   lines.append(f"  resolved_files: {sym.get('resolved_files', 0)}")
   lines.append(f"  index_errors: {len(sym.get('index_errors', []))}")
   lines.append(f"  resolver_errors: {len(sym.get('resolver_errors', []))}")
   lines.append(f"  unresolved_refs: {sym.get('unresolved_refs', 0)}")
   lines.append(f"  dynamic_refs: {sym.get('dynamic_refs', 0)}")
   for err in sym.get("index_errors", [])[:EXAMPLE_LIMIT]:
      lines.append(f"    index error: {err['file']}: {err['error']}")
   for err in sym.get("resolver_errors", [])[:EXAMPLE_LIMIT]:
      lines.append(f"    resolver error: {err['file']}: {err['error']}")
   lines.append("")

   pkg = report.PackageReadiness
   lines.append("Package / import readiness")
   lines.append(f"  packages: {pkg.get('package_count', 0)}")
   lines.append(f"  namespace_like_dirs: {pkg.get('namespace_like_count', 0)}")
   lines.append(
      "  namespace_support: conservative inside scanned roots when ancestry "
      "is unambiguous"
   )
   if pkg.get("warnings"):
      for warning in pkg["warnings"]:
         lines.append(f"  warning: {warning}")
   lines.append("")

   lines.append(f"Overall: {_StatusText(report.ExitCode)}")
   return "\n".join(lines) + "\n"


def _FillEmptySections(report: DoctorReport) -> None:
   report.Encoding = {
      "non_utf8_count":   0,
      "non_utf8_files":   [],
      "io_error_count":  0,
      "io_error_files":  [],
      "utf8_bom_count":  0,
      "utf8_bom_files": [],
      "crlf_count":     0,
      "crlf_files":     [],
      "bare_cr_count":  0,
      "bare_cr_files":  [],
   }
   report.RuleStatus = {
      "total_violations": 0,
      "by_rule":          {},
      "checker_errors":   [],
   }
   report.AutoFixReadiness = {
      "would_change_count": 0,
      "would_change_files": [],
      "by_rule":            {code: 0 for code in AUTO_FIX_CODES},
      "errors":             [],
   }
   report.SymbolReadiness = {
      "indexed_files":    0,
      "resolved_files":   0,
      "index_errors":     [],
      "resolver_errors":  [],
      "unresolved_refs":  0,
      "dynamic_refs":     0,
   }
   report.PackageReadiness = {
      "package_count":        0,
      "packages":             [],
      "namespace_like_count": 0,
      "namespace_like_dirs":        [],
      "ambiguous_namespace_modules": [],
      "namespace_support":          (
         "namespace-package-like directories are supported conservatively "
         "inside scanned roots when ancestry is unambiguous"
      ),
      "warnings":                   [],
   }


def _InspectEncoding(files: list[Path]) -> dict:
   non_utf8_files: list[str] = []
   io_error_files: list[str] = []
   bom_files: list[str] = []
   crlf_files: list[str] = []
   bare_cr_files: list[str] = []

   for path in files:
      try:
         raw = ReadUtf8Bytes(path)
      except OSError:
         io_error_files.append(str(path))
         continue
      check_raw = raw
      if raw.startswith(UTF8_BOM):
         bom_files.append(str(path))
         check_raw = raw[len(UTF8_BOM):]
      try:
         check_raw.decode("utf-8")
      except UnicodeDecodeError:
         non_utf8_files.append(str(path))
         continue
      if b"\r\n" in check_raw:
         crlf_files.append(str(path))
      bare_count = check_raw.replace(b"\r\n", b"").count(b"\r")
      if bare_count:
         bare_cr_files.append(str(path))

   return {
      "non_utf8_count":   len(non_utf8_files),
      "non_utf8_files":   non_utf8_files,
      "io_error_count":  len(io_error_files),
      "io_error_files":  io_error_files,
      "utf8_bom_count":  len(bom_files),
      "utf8_bom_files": bom_files,
      "crlf_count":     len(crlf_files),
      "crlf_files":     crlf_files,
      "bare_cr_count":  len(bare_cr_files),
      "bare_cr_files":  bare_cr_files,
   }


def _InspectRules(files: list[Path], report: DoctorReport) -> list[dict]:
   summaries: dict[str, RuleSummary] = {}
   checker_errors: list[dict] = []

   for path in files:
      try:
         violations = CheckFile(path)
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         checker_errors.append({"file": str(path), "error": str(exc)})
         continue
      for violation in violations:
         item = summaries.setdefault(violation.code, RuleSummary(Code=violation.code))
         item.Add(violation)

   report.RuleStatus = {
      "total_violations": sum(item.Count for item in summaries.values()),
      "by_rule":          {code: summaries[code].ToDict() for code in sorted(summaries)},
      "checker_errors":   checker_errors,
   }
   return checker_errors


def _InspectAutoFixReadiness(files: list[Path]) -> dict:
   by_rule = {code: 0 for code in AUTO_FIX_CODES}
   would_change_files: list[str] = []
   errors: list[dict] = []

   for path in files:
      try:
         changed, _diff_text, violations = ProcessFile(path, check_only=True)
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         errors.append({"file": str(path), "error": str(exc)})
         continue
      if changed:
         would_change_files.append(str(path))
      for violation in violations:
         if violation.code in by_rule:
            by_rule[violation.code] += 1

   return {
      "would_change_count": len(would_change_files),
      "would_change_files": would_change_files,
      "by_rule":            by_rule,
      "errors":             errors,
   }


def _InspectSymbolReadiness(paths: list[str], files: list[Path]) -> dict:
   index_result, disc_errors = IndexPaths(paths)
   index_errors = [e.ToDict() for e in index_result.Errors]
   for err in disc_errors:
      index_errors.append({"file": "", "error": err})

   resolver_errors: list[dict] = []
   resolved_files = 0
   unresolved_refs = 0
   dynamic_refs = 0

   for path in files:
      result = ResolveFile(path)
      if isinstance(result, FileError):
         resolver_errors.append(result.ToDict())
         continue
      resolved_files += 1
      unresolved_refs += len(result.Unresolved)
      dynamic_refs += len(result.Dynamic)

   return {
      "indexed_files":   len(index_result.Files),
      "resolved_files":  resolved_files,
      "index_errors":    index_errors,
      "resolver_errors": resolver_errors,
      "unresolved_refs": unresolved_refs,
      "dynamic_refs":    dynamic_refs,
   }


def _InspectPackages(paths: list[str], files: list[Path]) -> dict:
   dirs_with_py = {path.parent for path in files}
   package_dirs = sorted(d for d in dirs_with_py if (d / "__init__.py").exists())
   namespace_like = sorted(d for d in dirs_with_py if d not in package_dirs)
   ambiguous_modules = _AmbiguousNamespaceModules(paths, files, namespace_like)
   warnings: list[str] = []
   if ambiguous_modules:
      modules = ", ".join(ambiguous_modules[:EXAMPLE_LIMIT])
      warnings.append(
         "namespace-package-like directories are supported conservatively when "
         "scanned roots make module ancestry unambiguous; ambiguous namespace "
         f"modules remain unresolved: {modules}"
      )
   return {
      "package_count":              len(package_dirs),
      "packages":                   [str(d) for d in package_dirs],
      "namespace_like_count":       len(namespace_like),
      "namespace_like_dirs":        [str(d) for d in namespace_like],
      "ambiguous_namespace_modules": ambiguous_modules,
      "namespace_support":          (
         "namespace-package-like directories are supported conservatively "
         "inside scanned roots when ancestry is unambiguous"
      ),
      "warnings":                   warnings,
   }


def _AmbiguousNamespaceModules(
   paths: list[str], files: list[Path], namespace_like: list[Path]
) -> list[str]:
   namespace_set = set(namespace_like)
   scan_roots = _ScanRoots(paths)
   seen: dict[str, Path] = {}
   ambiguous: set[str] = set()
   for path in files:
      if path.parent not in namespace_set:
         continue
      for module in _ModuleCandidates(path, scan_roots):
         existing = seen.get(module)
         if existing is None:
            seen[module] = path
         elif existing != path:
            ambiguous.add(module)
   return sorted(ambiguous)


def _AppendFileExamples(lines: list[str], paths: list[str], label: str) -> None:
   if not paths:
      return
   lines.append(f"  {label}:")
   for path in paths[:EXAMPLE_LIMIT]:
      lines.append(f"    {path}")
   if len(paths) > EXAMPLE_LIMIT:
      lines.append(f"    ... {len(paths) - EXAMPLE_LIMIT} more")


def _StatusText(exit_code: int) -> str:
   if exit_code == 0:
      return "healthy"
   if exit_code == 1:
      return "style/format issues found"
   return "blocking issues found"
