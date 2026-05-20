"""
Shared types used across customfmt rules and the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class Violation:
   """A single rule violation."""

   path: Path
   line: int  # 1-based
   col: int  # 1-based (0 when not applicable)
   code: str  # e.g. "CF001"
   message: str  # human-readable description

   def __str__(self) -> str:
      return f"{self.path}:{self.line}:{self.col} {self.code} {self.message}"

   def to_dict(self) -> dict:
      return {
         "path": str(self.path),
         "line": self.line,
         "col": self.col,
         "code": self.code,
         "message": self.message,
      }
