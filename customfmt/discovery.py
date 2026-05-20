"""
File discovery for customfmt.

Walks paths supplied on the CLI, expands directories recursively,
and returns only .py files that are not inside ignored directories.
"""

from __future__ import annotations

import os
from pathlib import Path

IGNORED_DIRS: frozenset[str] = frozenset(
   {
      ".git",
      ".venv",
      "venv",
      "env",
      "__pycache__",
      ".mypy_cache",
      ".ruff_cache",
      ".pytest_cache",
      "build",
      "dist",
   }
)


def collect_files(paths: list[str]) -> list[Path]:
   """
   Expand *paths* into a sorted, deduplicated list of .py files.

   Rules
   -----
   - If a path is a file it is included directly (must be .py).
   - If a path is a directory it is walked recursively; any directory
     whose *name* appears in IGNORED_DIRS is skipped entirely.
   - Non-existent paths raise FileNotFoundError.
   - Non-.py files passed explicitly are silently skipped (callers that
     want a warning should check the suffix before calling).
   """
   seen: set[Path] = set()
   result: list[Path] = []

   for raw in paths:
      p = Path(raw)
      if not p.exists():
         raise FileNotFoundError(f"No such file or directory: {raw!r}")
      if p.is_file():
         if p.suffix == ".py" and p not in seen:
            seen.add(p)
            result.append(p)
      else:
         for dirpath, dirnames, filenames in os.walk(p):
            # Prune ignored directories in-place so os.walk skips them.
            dirnames[:] = [d for d in sorted(dirnames) if d not in IGNORED_DIRS]
            for fname in sorted(filenames):
               if fname.endswith(".py"):
                  fp = Path(dirpath) / fname
                  if fp not in seen:
                     seen.add(fp)
                     result.append(fp)

   return result
