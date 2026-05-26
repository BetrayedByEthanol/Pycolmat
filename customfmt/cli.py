"""
customfmt CLI (argparse).

Commands
--------
  customfmt fix [--check] [--diff] [--quiet] <paths...>
  customfmt check [--quiet] [--json] <paths...>
  customfmt rename [--check | --diff | --apply] <paths...>
  customfmt index  [--json] [--pretty] [--output PATH] <paths...>

Aliases (console_scripts)
--------------------------
  try-auto-format  →  customfmt fix
  check-format     →  customfmt check
  create-index     →  customfmt index

Exit codes
----------
  0  success
  1  formatting / check violations found
  2  tool / runtime error
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

from customfmt import __version__
from customfmt.checker import CheckFile
from customfmt.discovery import CollectFiles
from customfmt.formatter import ProcessFile
from customfmt.indexer import IndexPaths
from customfmt.io import WriteUtf8Lf
from customfmt.renamer import AnalyseFile
from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _BuildParser(prog: str = "customfmt") -> argparse.ArgumentParser:
   parser = argparse.ArgumentParser(
      prog=prog,
      description="Project-specific Python style formatter and checker.",
      formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog=textwrap.dedent(
         """
         Exit codes:
           0  success (fix: all done; check: no violations)
           1  violations found (check / fix --check only)
           2  tool / runtime error
         """
      ),
   )
   parser.add_argument("--version", action="version", version=f"customfmt {__version__}")

   sub = parser.add_subparsers(dest="command", metavar="COMMAND")
   sub.required = True

   # -- fix ------------------------------------------------------------------
   fix_p = sub.add_parser(
      "fix",
      help="Auto-format files in place.",
      description="Apply safe automatic formatting rules.",
   )
   fix_p.add_argument("paths", nargs="+", metavar="PATH", help="Files or directories to process.")
   fix_p.add_argument(
      "--check",
      action="store_true",
      help="Do not write files; exit 1 if any changes would be made.",
   )
   fix_p.add_argument(
      "--diff",
      action="store_true",
      help="Show unified diff of proposed changes without writing files.",
   )
   fix_p.add_argument("--quiet", "-q", action="store_true", help="Suppress per-file output.")

   # -- check ----------------------------------------------------------------
   chk_p = sub.add_parser(
      "check",
      help="Check all custom rules (CF001–CF012).",
      description="Check files against all custom rules (CF001–CF012). Does not modify files.",
   )
   chk_p.add_argument("paths", nargs="+", metavar="PATH", help="Files or directories to process.")
   chk_p.add_argument("--quiet", "-q", action="store_true", help="Suppress per-violation output.")
   chk_p.add_argument(
      "--json",
      action="store_true",
      dest="json_out",
      help="Output violations as JSON.",
   )

   # -- rename ---------------------------------------------------------------
   ren_p = sub.add_parser(
      "rename",
      help="Safe local variable rename (CF005).",
      description=(
         "Find and rename non-snake_case local variables to snake_case. "
         "Does not rename functions, parameters, constants, or attributes."
      ),
   )
   ren_p.add_argument("paths", nargs="+", metavar="PATH", help="Files or directories to process.")
   mode = ren_p.add_mutually_exclusive_group(required=True)
   mode.add_argument(
      "--check",
      action="store_true",
      help="Report rename candidates; exit 1 if any found.",
   )
   mode.add_argument(
      "--diff",
      action="store_true",
      help="Print unified diff of proposed renames without writing; exit 0.",
   )
   mode.add_argument(
      "--apply",
      action="store_true",
      help="Apply renames in place; exit 0.",
   )
   ren_p.add_argument("--quiet", "-q", action="store_true", help="Suppress per-rename output.")

   # -- index ----------------------------------------------------------------
   idx_p = sub.add_parser(
      "index",
      help="Build a read-only AST-based symbol index.",
      description=(
         "Walk Python files and emit a JSON symbol index. "
         "Does not modify any files."
      ),
   )
   idx_p.add_argument(
      "paths", nargs="+", metavar="PATH", help="Files or directories to index."
   )
   idx_p.add_argument(
      "--json",
      action="store_true",
      dest="json_out",
      default=True,
      help="Output as JSON (default).",
   )
   idx_p.add_argument(
      "--pretty",
      action="store_true",
      help="Pretty-print JSON with indentation.",
   )
   idx_p.add_argument(
      "--output",
      metavar="PATH",
      default=None,
      help="Write JSON to PATH instead of stdout.",
   )

   return parser


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _CmdFix(args: argparse.Namespace) -> int:
   try:
      files = CollectFiles(args.paths)
   except FileNotFoundError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if not files:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   check_only: bool = args.check
   show_diff: bool = args.diff
   quiet: bool = args.quiet
   any_change = False

   for path in files:
      # When --diff or --check: read-only (don't write files).
      # Otherwise ProcessFile writes in place.
      read_only = check_only or show_diff
      try:
         changed, diff_text, _ = ProcessFile(
            path,
            check_only=read_only,
            diff=show_diff,
         )
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         print(f"customfmt: error: {path}: {exc}", file=sys.stderr)
         return 2

      if changed:
         any_change = True
         if not quiet:
            if show_diff:
               print(diff_text, end="")
            elif check_only:
               print(f"would reformat {path}")
            else:
               print(f"reformatted {path}")

   # Exit code rules:
   #   --check alone or --check --diff  : exit 1 when changes would be made
   #   --diff alone                     : always exit 0 (diff is informational)
   #   neither                          : always exit 0 (fix mode)
   if check_only:
      return 1 if any_change else 0
   return 0


def _CmdCheck(args: argparse.Namespace) -> int:
   try:
      files = CollectFiles(args.paths)
   except FileNotFoundError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if not files:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   quiet: bool = args.quiet
   json_out: bool = args.json_out
   all_violations: list[Violation] = []

   for path in files:
      try:
         viols = CheckFile(path)
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         print(f"customfmt: error: {path}: {exc}", file=sys.stderr)
         return 2
      all_violations.extend(viols)

   if json_out:
      print(json.dumps([v.ToDict() for v in all_violations], indent=2))
      return 1 if all_violations else 0

   if not quiet:
      for v in all_violations:
         print(v)

   if all_violations:
      count = len(all_violations)
      file_count = len({v.path for v in all_violations})
      if not quiet:
         print(
            f"\n{count} violation{'s' if count != 1 else ''} found "
            f"in {file_count} file{'s' if file_count != 1 else ''}."
         )
      return 1

   if not quiet:
      print(f"All {len(files)} file(s) passed.")
   return 0


def _CmdRename(args: argparse.Namespace) -> int:
   try:
      files = CollectFiles(args.paths)
   except FileNotFoundError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if not files:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   quiet: bool = args.quiet
   any_candidate = False

   for path in files:
      try:
         result = AnalyseFile(path)
      except SyntaxError as exc:
         print(f"customfmt: syntax error in {path}: {exc}", file=sys.stderr)
         continue
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         print(f"customfmt: error: {path}: {exc}", file=sys.stderr)
         return 2

      if not result.candidates:
         continue

      any_candidate = True

      if args.diff:
         print(result.UnifiedDiff(), end="")
      elif not quiet:
         for v in result.Violations():
            print(v)

      if args.apply:
         WriteUtf8Lf(path, result.rewritten)
         if not quiet:
            print(f"renamed {path}")

   if args.check:
      return 1 if any_candidate else 0
   return 0


def _CmdIndex(args: argparse.Namespace) -> int:
   import json as _json


   result, disc_errors = IndexPaths(args.paths)

   if disc_errors:
      for err in disc_errors:
         print(f"customfmt: error: {err}", file=sys.stderr)
      return 2

   if not result.Files and not result.Errors:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   indent = 2 if args.pretty else None
   output = result.ToDict()
   serialised = _json.dumps(output, indent=indent)

   if args.output:
      try:
         from customfmt.io import WriteUtf8Lf
         WriteUtf8Lf(Path(args.output), serialised + "\n")
      except OSError as exc:
         print(f"customfmt: error writing {args.output}: {exc}", file=sys.stderr)
         return 2
   else:
      print(serialised)

   return 0


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def Main(argv: list[str] | None = None, *, prog: str = "customfmt") -> int:
   parser = _BuildParser(prog=prog)
   args = parser.parse_args(argv)

   try:
      if args.command == "fix":
         return _CmdFix(args)
      elif args.command == "check":
         return _CmdCheck(args)
      elif args.command == "rename":
         return _CmdRename(args)
      elif args.command == "index":
         return _CmdIndex(args)
      else:  # pragma: no cover
         parser.print_help()
         return 2
   except KeyboardInterrupt:
      return 2


def MainFix(argv: list[str] | None = None) -> int:
   """Entry point for ``try-auto-format`` alias."""
   # Prepend "fix" so argparse sees the right sub-command.
   effective = ["fix"] + (sys.argv[1:] if argv is None else argv)
   return Main(effective, prog="try-auto-format")


def MainCheck(argv: list[str] | None = None) -> int:
   """Entry point for ``check-format`` alias."""
   effective = ["check"] + (sys.argv[1:] if argv is None else argv)
   return Main(effective, prog="check-format")


# Wrappers that call sys.exit so they work as console_scripts.
def _EntryMain() -> None:
   sys.exit(Main())


def _EntryFix() -> None:
   sys.exit(MainFix())


def _EntryCheck() -> None:
   sys.exit(MainCheck())


def MainIndex(argv: list[str] | None = None) -> int:
   """Entry point for ``create-index`` alias."""
   effective = ["index"] + (sys.argv[1:] if argv is None else argv)
   return Main(effective, prog="create-index")


def _EntryIndex() -> None:
   sys.exit(MainIndex())
