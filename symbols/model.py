"""
Data model for the customfmt symbol index.

Every indexed item is a SymbolEntry dataclass.  The ``kind`` field uses
one of the KIND_* string constants defined below.

Serialisation
-------------
SymbolEntry.ToDict() produces a plain dict safe for json.dumps().
FileIndex.ToDict() produces the per-file container.
IndexResult.ToDict() produces the full index, including file-level errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Kind constants
# ---------------------------------------------------------------------------

KIND_IMPORT        = "import"
KIND_IMPORT_FROM   = "import_from"
KIND_MODULE_DECL   = "module_declaration"
KIND_CLASS         = "class"
KIND_CLASS_DECL    = "class_declaration"
KIND_FUNCTION      = "function"
KIND_METHOD        = "method"
KIND_PARAMETER     = "parameter"
KIND_LOCAL_WRITE   = "local_write"
KIND_NAME_READ     = "name_read"
KIND_CALL          = "call"
KIND_ATTR_CALL     = "attribute_call"


# ---------------------------------------------------------------------------
# SymbolEntry
# ---------------------------------------------------------------------------

@dataclass
class SymbolEntry:
   """One indexed symbol."""

   Kind          : str            # one of the KIND_* constants
   Name          : str            # bare name (e.g. "GetByID")
   QualifiedName : str            # dotted path (e.g. "UserRepo.GetByID")
   FilePath      : str            # str(path) — JSON-serialisable
   Line          : int            # 1-based
   Col           : int            # 0-based (AST convention)
   Scope         : str            # e.g. "" | "UserRepo" | "UserRepo.GetByID"
   Extra         : dict           # kind-specific metadata

   def ToDict(self) -> dict:
      return {
         "kind":           self.Kind,
         "name":           self.Name,
         "qualified_name": self.QualifiedName,
         "file":           self.FilePath,
         "line":           self.Line,
         "col":            self.Col,
         "scope":          self.Scope,
         "extra":          self.Extra,
      }


# ---------------------------------------------------------------------------
# FileIndex
# ---------------------------------------------------------------------------

@dataclass
class FileIndex:
   """Symbol index for one successfully parsed file."""

   FilePath : str
   Symbols  : list[SymbolEntry] = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "file":    self.FilePath,
         "symbols": [s.ToDict() for s in self.Symbols],
      }


# ---------------------------------------------------------------------------
# FileError
# ---------------------------------------------------------------------------

@dataclass
class FileError:
   """Structured error for a file that could not be indexed."""

   FilePath : str
   Error    : str   # human-readable description

   def ToDict(self) -> dict:
      return {
         "file":  self.FilePath,
         "error": self.Error,
      }


# ---------------------------------------------------------------------------
# IndexResult
# ---------------------------------------------------------------------------

@dataclass
class IndexResult:
   """Complete symbol index for one run."""

   Files  : list[FileIndex] = field(default_factory=list)
   Errors : list[FileError] = field(default_factory=list)

   def ToDict(self) -> dict:
      return {
         "files":  [f.ToDict() for f in self.Files],
         "errors": [e.ToDict() for e in self.Errors],
      }
