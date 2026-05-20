"""
customfmt CLI (argparse).

Commands
--------
  customfmt fix [--check] [--diff] [--quiet] <paths...>
  customfmt check [--quiet] [--json] <paths...>

Aliases (console_scripts)
--------------------------
  try-auto-format  →  customfmt fix
  check-format     →  customfmt check

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

from customfmt import __version__
from customfmt.checker import check_file
from customfmt.discovery import collect_files
from customfmt.formatter import process_file
from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser(prog: str = "customfmt") -> argparse.ArgumentParser:
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
      help="Check all custom rules (CF001–CF010).",
      description="Check files against all custom rules. Does not modify files.",
   )
   chk_p.add_argument("paths", nargs="+", metavar="PATH", help="Files or directories to process.")
   chk_p.add_argument("--quiet", "-q", action="store_true", help="Suppress per-violation output.")
   chk_p.add_argument(
      "--json",
      action="store_true",
      dest="json_out",
      help="Output violations as JSON.",
   )

   return parser


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _cmd_fix(args: argparse.Namespace) -> int:
   try:
      files = collect_files(args.paths)
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
      # When --diff or --check: read-only. Otherwise process_file writes in place.
      read_only = check_only or show_diff
      try:
         changed, diff_text, _ = process_file(
            path,
            check_only=read_only,
            diff=show_diff,
         )
      except OSError as exc:
         print(f"customfmt: error reading {path}: {exc}", file=sys.stderr)
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

   if check_only or show_diff:
      return 1 if any_change else 0
   return 0


def _cmd_check(args: argparse.Namespace) -> int:
   try:
      files = collect_files(args.paths)
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
         viols = check_file(path)
      except OSError as exc:
         print(f"customfmt: error reading {path}: {exc}", file=sys.stderr)
         return 2
      all_violations.extend(viols)

   if json_out:
      print(json.dumps([v.to_dict() for v in all_violations], indent=2))
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


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, prog: str = "customfmt") -> int:
   parser = _build_parser(prog=prog)
   args = parser.parse_args(argv)

   try:
      if args.command == "fix":
         return _cmd_fix(args)
      elif args.command == "check":
         return _cmd_check(args)
      else:  # pragma: no cover
         parser.print_help()
         return 2
   except KeyboardInterrupt:
      return 2


def main_fix(argv: list[str] | None = None) -> int:
   """Entry point for ``try-auto-format`` alias."""
   # Prepend "fix" so argparse sees the right sub-command.
   effective = ["fix"] + (sys.argv[1:] if argv is None else argv)
   return main(effective, prog="try-auto-format")


def main_check(argv: list[str] | None = None) -> int:
   """Entry point for ``check-format`` alias."""
   effective = ["check"] + (sys.argv[1:] if argv is None else argv)
   return main(effective, prog="check-format")


# Wrappers that call sys.exit so they work as console_scripts.
def _entry_main() -> None:
   sys.exit(main())


def _entry_fix() -> None:
   sys.exit(main_fix())


def _entry_check() -> None:
   sys.exit(main_check())
