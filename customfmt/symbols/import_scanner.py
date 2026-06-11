"""
Read-only import scanner for requirements.in generation.

ScanImports(paths) -> ImportScanResult

Walks the AST index for a set of Python files and produces a deduplicated
list of external (non-stdlib) import names, annotating each with:

  - whether it appears at module level or inside a function scope
  - whether the enclosing conditional references a platform check
  - a suggested sys_platform marker when one can be inferred

Platform detection
------------------
When an import lives inside a function scope, the scanner re-parses the
source file and walks the AST to find the nearest enclosing ast.If node.
If the test expression contains any of the known platform-check patterns
(sys.platform, platform.system(), os.name, sys.platform.startswith) the
value string is extracted and mapped to a PEP 508 sys_platform marker.

Known mappings
--------------
  sys.platform == "win32"       -> sys_platform == "win32"
  sys.platform == "linux"       -> sys_platform == "linux"
  sys.platform == "darwin"      -> sys_platform == "darwin"
  sys.platform.startswith("win")-> sys_platform == "win32"
  os.name == "nt"               -> sys_platform == "win32"
  os.name == "posix"            -> sys_platform != "win32"
  platform.system() == "Windows"-> sys_platform == "win32"
  platform.system() == "Linux"  -> sys_platform == "linux"
  platform.system() == "Darwin" -> sys_platform == "darwin"

Imports inside an else/elif branch get the negated or complementary marker
where unambiguous; otherwise they are flagged as needs_review.

Stdlib filtering
----------------
Uses sys.stdlib_module_names (Python 3.10+) plus a small hard-coded
supplement for older pythons.  The top-level package name is used for
matching (e.g. "email.mime.text" -> "email").
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

from customfmt.discovery import CollectFiles
from customfmt.io import ReadUtf8Text
from customfmt.symbols.ast_indexer import IndexFile
from customfmt.symbols.model import (
   KIND_IMPORT,
   KIND_IMPORT_FROM,
   FileError,
   FileIndex,
   SymbolEntry,
)

# ---------------------------------------------------------------------------
# Stdlib set
# ---------------------------------------------------------------------------

def _BuildStdlibSet() -> frozenset[str]:
   base: set[str] = set()
   if hasattr(sys, "stdlib_module_names"):
      base.update(sys.stdlib_module_names)
   # Supplement for common top-level names that may be missing on older pythons
   # or that are distribution-level packages confused with stdlib.
   base.update({
      "__future__", "_thread", "abc", "aifc", "argparse", "ast", "asynchat",
      "asyncio", "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
      "binhex", "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb",
      "chunk", "cmath", "cmd", "code", "codecs", "codeop", "colorsys",
      "compileall", "concurrent", "configparser", "contextlib", "contextvars",
      "copy", "copyreg", "cProfile", "csv", "ctypes", "curses", "dataclasses",
      "datetime", "dbm", "decimal", "difflib", "dis", "distutils", "doctest",
      "email", "encodings", "enum", "errno", "faulthandler", "fcntl",
      "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
      "gc", "getopt", "getpass", "gettext", "glob", "grp", "gzip", "hashlib",
      "heapq", "hmac", "html", "http", "idlelib", "imaplib", "imghdr",
      "importlib", "inspect", "io", "ipaddress", "itertools", "json",
      "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
      "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
      "modulefinder", "multiprocessing", "netrc", "nis", "nntplib", "numbers",
      "operator", "optparse", "os", "ossaudiodev", "pathlib", "pdb",
      "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib",
      "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty",
      "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random",
      "re", "readline", "reprlib", "resource", "rlcompleter", "runpy",
      "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil",
      "signal", "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
      "spwd", "sqlite3", "sre_compile", "sre_constants", "sre_parse", "ssl",
      "stat", "statistics", "string", "stringprep", "struct", "subprocess",
      "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
      "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
      "threading", "time", "timeit", "tkinter", "token", "tokenize", "tomllib",
      "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo",
      "types", "typing", "unicodedata", "unittest", "urllib", "uu", "uuid",
      "venv", "warnings", "wave", "weakref", "webbrowser", "winreg",
      "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
      "zipfile", "zipimport", "zlib", "zoneinfo",
   })
   return frozenset(base)


STDLIB: frozenset[str] = _BuildStdlibSet()

# ---------------------------------------------------------------------------
# Platform marker inference
# ---------------------------------------------------------------------------

# Map from (check_style, value_string) -> PEP 508 marker string.
# "negated" entries are for else-branch imports.
_PLATFORM_MAP: dict[tuple[str, str], str] = {
   ("sys.platform ==",    "win32"):   'sys_platform == "win32"',
   ("sys.platform ==",    "linux"):   'sys_platform == "linux"',
   ("sys.platform ==",    "darwin"):  'sys_platform == "darwin"',
   ("sys.platform ==",    "linux2"):  'sys_platform == "linux"',
   ("os.name ==",         "nt"):      'sys_platform == "win32"',
   ("os.name ==",         "posix"):   'sys_platform != "win32"',
   ("platform.system ==", "Windows"): 'sys_platform == "win32"',
   ("platform.system ==", "Linux"):   'sys_platform == "linux"',
   ("platform.system ==", "Darwin"):  'sys_platform == "darwin"',
}

_NEGATED_MAP: dict[str, str] = {
   'sys_platform == "win32"':  'sys_platform != "win32"',
   'sys_platform == "linux"':  'sys_platform != "linux"',
   'sys_platform == "darwin"': 'sys_platform != "darwin"',
   'sys_platform != "win32"':  'sys_platform == "win32"',
}


def _InferMarkerFromTest(test_node: ast.expr, negated: bool = False) -> str | None:
   """
   Try to infer a PEP 508 sys_platform marker from a single ast.If test node.
   Returns None when the pattern is not recognised.
   """
   marker: str | None = None

   match test_node:
      # sys.platform == "value"  /  "value" == sys.platform
      case ast.Compare(
         left=ast.Attribute(value=ast.Name(id="sys"), attr="platform"),
         ops=[ast.Eq()],
         comparators=[ast.Constant(value=str() as val)],
      ):
         marker = _PLATFORM_MAP.get(("sys.platform ==", val))

      case ast.Compare(
         left=ast.Constant(value=str() as val),
         ops=[ast.Eq()],
         comparators=[ast.Attribute(value=ast.Name(id="sys"), attr="platform")],
      ):
         marker = _PLATFORM_MAP.get(("sys.platform ==", val))

      # os.name == "value"
      case ast.Compare(
         left=ast.Attribute(value=ast.Name(id="os"), attr="name"),
         ops=[ast.Eq()],
         comparators=[ast.Constant(value=str() as val)],
      ):
         marker = _PLATFORM_MAP.get(("os.name ==", val))

      # platform.system() == "value"
      case ast.Compare(
         left=ast.Call(
            func=ast.Attribute(value=ast.Name(id="platform"), attr="system")
         ),
         ops=[ast.Eq()],
         comparators=[ast.Constant(value=str() as val)],
      ):
         marker = _PLATFORM_MAP.get(("platform.system ==", val))

      # sys.platform.startswith("win")
      case ast.Call(
         func=ast.Attribute(
            value=ast.Attribute(value=ast.Name(id="sys"), attr="platform"),
            attr="startswith",
         ),
         args=[ast.Constant(value=str() as val)],
      ):
         if val.startswith("win"):
            marker = 'sys_platform == "win32"'
         elif val.startswith("linux"):
            marker = 'sys_platform == "linux"'
         elif val.startswith("darwin"):
            marker = 'sys_platform == "darwin"'

      # not <expr>  — recurse with negation flipped
      case ast.UnaryOp(op=ast.Not(), operand=inner):
         return _InferMarkerFromTest(inner, negated=not negated)

      case _:
         return None

   if marker is None:
      return None
   if negated:
      return _NEGATED_MAP.get(marker)
   return marker


# ---------------------------------------------------------------------------
# AST helper: find enclosing If node for a given line
# ---------------------------------------------------------------------------

@dataclass
class _IfContext:
   """Records an If node and whether the import is in the else branch."""
   node:    ast.If
   negated: bool   # True when import is in orelse, not body


def _FindEnclosingIf(tree: ast.Module, target_line: int) -> _IfContext | None:
   """
   Walk *tree* and return the innermost ast.If whose body or orelse contains
   *target_line*.  Returns None if none found.
   """
   best: _IfContext | None = None

   def _Walk(node: ast.AST) -> None:
      nonlocal best
      for child in ast.iter_child_nodes(node):
         _Walk(child)
         if not isinstance(child, ast.If):
            continue
         # Check if target_line falls within the body subtree
         for stmt in child.body:
            for sub in ast.walk(stmt):
               if getattr(sub, "lineno", None) == target_line:
                  # Prefer deeper (later-found) matches
                  best = _IfContext(node=child, negated=False)
         # Check orelse
         for stmt in child.orelse:
            for sub in ast.walk(stmt):
               if getattr(sub, "lineno", None) == target_line:
                  best = _IfContext(node=child, negated=True)

   _Walk(tree)
   return best


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ImportEntry:
   """One deduplicated external import, with platform annotation."""

   PackageName   : str              # top-level pip package name (guessed)
   ImportedName  : str              # as written in source, e.g. "PIL.Image"
   Locations     : list[str]        # "file:line" strings
   IsConditional : bool             # inside a function / if scope
   PlatformMarker: str | None       # PEP 508 marker or None
   NeedsReview   : bool             # marker ambiguous — human must check

   def ToDict(self) -> dict:
      return {
         "package":        self.PackageName,
         "imported_as":    self.ImportedName,
         "locations":      self.Locations,
         "conditional":    self.IsConditional,
         "marker":         self.PlatformMarker,
         "needs_review":   self.NeedsReview,
      }

   def RequirementsLine(self) -> str:
      """Format one requirements.in line with optional marker comment."""
      if self.PlatformMarker:
         return f"{self.PackageName}; {self.PlatformMarker}"
      if self.NeedsReview:
         return f"{self.PackageName}  # REVIEW: conditional import — add marker manually"
      return self.PackageName


@dataclass
class ImportScanResult:
   """Result of scanning a set of Python files for external imports."""

   Imports : list[ImportEntry] = field(default_factory=list)
   Errors  : list[FileError]   = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "imports": [i.ToDict() for i in self.Imports],
         "errors":  [e.ToDict() for e in self.Errors],
      }

   def FormatRequirementsIn(self) -> str:
      """
      Render a requirements.in draft.

      Unconditional imports come first (sorted), then conditional ones
      grouped with a comment header.
      """
      lines: list[str] = []
      unconditional = sorted(
         [i for i in self.Imports if not i.IsConditional],
         key=lambda e: e.PackageName.lower(),
      )
      conditional = sorted(
         [i for i in self.Imports if i.IsConditional],
         key=lambda e: e.PackageName.lower(),
      )

      lines.append(
         "# requirements.in — generated by customfmt deps\n"
         "# Review before use: version pins are absent; add them after pip-compile.\n"
      )

      for entry in unconditional:
         lines.append(entry.RequirementsLine())

      if conditional:
         lines.append("")
         lines.append("# --- platform-conditional / deferred imports ---")
         for entry in conditional:
            lines.append(entry.RequirementsLine())

      return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Package name normalisation
# ---------------------------------------------------------------------------

# A small set of well-known import->package name mismatches.
_IMPORT_TO_PACKAGE: dict[str, str] = {
   "cv2":           "opencv-python",
   "PIL":           "Pillow",
   "sklearn":       "scikit-learn",
   "skimage":       "scikit-image",
   "bs4":           "beautifulsoup4",
   "yaml":          "PyYAML",
   "gi":            "PyGObject",
   "wx":            "wxPython",
   "Crypto":        "pycryptodome",
   "OpenSSL":       "pyOpenSSL",
   "usb":           "pyusb",
   "serial":        "pyserial",
   "dateutil":      "python-dateutil",
   "dotenv":        "python-dotenv",
   "jose":          "python-jose",
   "magic":         "python-magic",
   "slugify":       "python-slugify",
   "MySQLdb":       "mysqlclient",
   "apt":           "python-apt",
   "dbus":          "dbus-python",
   "gtk":           "PyGTK",
   "pkg_resources": "setuptools",
   "win32api":      "pywin32",
   "win32con":      "pywin32",
   "win32gui":      "pywin32",
   "pywintypes":    "pywin32",
   "winreg":        "",            # stdlib on Windows — filtered elsewhere
}


def _GuessPackageName(import_name: str) -> str:
   """
   Return a best-guess pip package name for *import_name*.

   Uses the known mismatch table, then falls back to the top-level module
   name (replacing underscores with hyphens as a heuristic).
   """
   top = import_name.split(".")[0]
   if top in _IMPORT_TO_PACKAGE:
      return _IMPORT_TO_PACKAGE[top]
   return top.replace("_", "-")


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def _IsStdlib(import_name: str) -> bool:
   top = import_name.split(".")[0]
   return top in STDLIB


def _ExtractModuleName(entry: SymbolEntry) -> str:
   """Return the dotted module name for an import or import_from symbol."""
   if entry.Kind == KIND_IMPORT:
      return entry.Extra.get("module", entry.Name)
   # import_from: use module field
   return entry.Extra.get("module", "")


def _ScanFile(
   path: Path,
   index: FileIndex,
) -> tuple[list[ImportEntry], FileError | None]:
   """
   Scan one indexed file and return ImportEntry items for external imports.

   Two passes:
   1. Index symbols (KIND_IMPORT / KIND_IMPORT_FROM at module level).
   2. Direct AST walk for imports inside function/method bodies, which the
      indexer intentionally does not capture.
   """
   entries: list[ImportEntry] = []

   # --- pass 1: module-level imports from the index -----------------------
   import_symbols = [
      s for s in index.Symbols
      if s.Kind in (KIND_IMPORT, KIND_IMPORT_FROM) and not s.Scope
   ]

   for sym in import_symbols:
      module_name = _ExtractModuleName(sym)
      if not module_name:
         continue
      if _IsStdlib(module_name):
         continue
      package_name = _GuessPackageName(module_name)
      if not package_name:
         continue
      location = f"{path}:{sym.Line}"
      entries.append(ImportEntry(
         PackageName    = package_name,
         ImportedName   = module_name,
         Locations      = [location],
         IsConditional  = False,
         PlatformMarker = None,
         NeedsReview    = False,
      ))

   # --- pass 2: function-body imports via direct AST walk -----------------
   try:
      src = ReadUtf8Text(path)
      tree = ast.parse(src, filename=str(path))
   except (OSError, UnicodeDecodeError, SyntaxError) as exc:
      return entries, FileError(FilePath=str(path), Error=str(exc))

   for node in ast.walk(tree):
      if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
         continue
      # Walk just the body of this function for import nodes.
      for child in ast.walk(node):
         if not isinstance(child, (ast.Import, ast.ImportFrom)):
            continue
         # Collect module names from this import node.
         if isinstance(child, ast.Import):
            names = [(alias.name, alias.name) for alias in child.names]
         else:
            module = child.module or ""
            names = [(module, module)]

         for module_name, _ in names:
            if not module_name or _IsStdlib(module_name):
               continue
            package_name = _GuessPackageName(module_name)
            if not package_name:
               continue

            ctx = _FindEnclosingIf(tree, child.lineno)
            if ctx is not None:
               marker = _InferMarkerFromTest(ctx.node.test, negated=ctx.negated)
               needs_review = marker is None
            else:
               marker = None
               needs_review = True

            location = f"{path}:{child.lineno}"
            entries.append(ImportEntry(
               PackageName    = package_name,
               ImportedName   = module_name,
               Locations      = [location],
               IsConditional  = True,
               PlatformMarker = marker,
               NeedsReview    = needs_review,
            ))

   return entries, None


def _MergeEntries(all_entries: list[ImportEntry]) -> list[ImportEntry]:
   """
   Deduplicate ImportEntry items by package name.

   Merging rules:
   - Locations are combined.
   - If any occurrence is unconditional the merged entry is unconditional.
   - PlatformMarker is kept only when all conditional occurrences agree on
     the same marker; otherwise NeedsReview is set.
   """
   by_package: dict[str, list[ImportEntry]] = {}
   for entry in all_entries:
      by_package.setdefault(entry.PackageName, []).append(entry)

   merged: list[ImportEntry] = []
   for package, group in by_package.items():
      all_locations = []
      for e in group:
         all_locations.extend(e.Locations)

      # If any occurrence is at module level, the package is not conditional.
      any_unconditional = any(not e.IsConditional for e in group)
      if any_unconditional:
         merged.append(ImportEntry(
            PackageName    = package,
            ImportedName   = group[0].ImportedName,
            Locations      = sorted(set(all_locations)),
            IsConditional  = False,
            PlatformMarker = None,
            NeedsReview    = False,
         ))
         continue

      # All conditional — try to agree on a single marker.
      markers = {e.PlatformMarker for e in group if e.PlatformMarker}
      any_review = any(e.NeedsReview for e in group)

      if len(markers) == 1 and not any_review:
         agreed_marker = next(iter(markers))
      else:
         agreed_marker = None
         any_review = True

      merged.append(ImportEntry(
         PackageName    = package,
         ImportedName   = group[0].ImportedName,
         Locations      = sorted(set(all_locations)),
         IsConditional  = True,
         PlatformMarker = agreed_marker,
         NeedsReview    = any_review,
      ))

   return merged


def ScanImports(paths: list[str]) -> tuple[ImportScanResult, list[str]]:
   """
   Scan *paths* for external imports and return an ImportScanResult.

   Returns (result, discovery_errors).  discovery_errors is a list of
   human-readable strings for paths that could not be collected.
   """
   disc_errors: list[str] = []
   try:
      files = CollectFiles(paths)
   except FileNotFoundError as exc:
      disc_errors.append(str(exc))
      return ImportScanResult(), disc_errors

   result = ImportScanResult()
   all_entries: list[ImportEntry] = []

   for path in files:
      index = IndexFile(path)
      if isinstance(index, FileError):
         result.Errors.append(index)
         continue
      entries, err = _ScanFile(path, index)
      if err:
         result.Errors.append(err)
         continue
      all_entries.extend(entries)

   result.Imports = _MergeEntries(all_entries)
   return result, disc_errors
