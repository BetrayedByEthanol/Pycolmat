"""
Top-level indexer facade used by the CLI.

IndexPaths(paths) -> IndexResult

Collects files via the standard discovery mechanism, runs IndexFile on
each, and aggregates results into an IndexResult.
"""

from __future__ import annotations

from pathlib import Path

from customfmt.discovery import CollectFiles
from customfmt.symbols.ast_indexer import IndexFile
from customfmt.symbols.model import FileError, FileIndex, IndexResult


def IndexPaths(paths: list[str]) -> tuple[IndexResult, list[str]]:
   """
   Discover and index all .py files under *paths*.

   Returns
   -------
   (result, discovery_errors)
     result            – IndexResult with Files and Errors populated
     discovery_errors  – list of human-readable strings for path-not-found etc.
   """
   discovery_errors: list[str] = []
   try:
      files = CollectFiles(paths)
   except FileNotFoundError as exc:
      discovery_errors.append(str(exc))
      return IndexResult(), discovery_errors

   result = IndexResult()
   for path in files:
      entry = IndexFile(path)
      if isinstance(entry, FileError):
         result.Errors.append(entry)
      else:
         result.Files.append(entry)

   return result, discovery_errors
