"""
customfmt CLI (argparse).

Commands
--------
  customfmt fix [--check] [--diff] [--quiet] <paths...>
  customfmt check [--quiet] [--json] <paths...>
  customfmt rename [--check | --diff | --apply] <paths...>
  customfmt index   [--pretty] [--output PATH] <paths...>
  customfmt resolve [--pretty] [--output PATH] <paths...>
  customfmt refs [--name NAME | --symbol PATH:LINE:COL] [--pretty] [--output PATH] <paths...>
  customfmt rename-symbol [--name NAME | --symbol PATH:LINE:COL] --to NAME [--pretty] [--output PATH] [--diff | --apply] <paths...>

Aliases (console_scripts)
--------------------------
  try-auto-format  →  customfmt fix
  check-format     →  customfmt check
  create-index     →  customfmt index
  resolve-index    →  customfmt resolve

Exit codes
----------
  0  success
  1  formatting / check violations found
  2  tool / runtime error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

from customfmt import __version__
from customfmt.checker import CheckFile
from customfmt.discovery import CollectFiles
from customfmt.formatter import ProcessFile
from customfmt.indexer import IndexPaths
from customfmt.io import WriteUtf8Lf
from customfmt.rename_plan import PlanFile
from customfmt.rename_symbol_plan import PlanRenameSymbol
from customfmt.rename_symbol_render import RenderPlanDiff, RenderPlanTextByFile
from customfmt.symbols.project_graph import FindRefsByName, FindRefsBySymbol
from customfmt.symbols.resolver import ResolveFile, ResolveResultSet
from customfmt.types import Violation

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Ignore-code helpers
# ---------------------------------------------------------------------------

def ParseIgnoreCodes(values: list[str]) -> frozenset[str]:
   """
   Parse the list of raw --ignore values into a normalised frozenset of
   uppercase rule codes.

   Each value may be a single code ("CF014"), a comma-separated list
   ("CF014,CF015"), a semicolon-separated list ("CF014;CF015"), or mixed.
   Repeated --ignore flags produce multiple entries in the input list.
   All codes are uppercased; surrounding whitespace is stripped.
   """
   codes: set[str] = set()
   for raw in values:
      for part in re.split(r"[,;]", raw):
         code = part.strip().upper()
         if code:
            codes.add(code)
   return frozenset(codes)


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
   fix_p.add_argument(
      "--ignore", metavar="RULES", action="append", default=[],
      help="Rule codes to ignore, comma/semicolon-separated (e.g. CF013,CF009). May be repeated.",
   )

   # -- check ----------------------------------------------------------------
   chk_p = sub.add_parser(
      "check",
      help="Check all custom rules (CF001–CF019).",
      description="Check files against all custom rules (CF001–CF019). Does not modify files.",
   )
   chk_p.add_argument("paths", nargs="+", metavar="PATH", help="Files or directories to process.")
   chk_p.add_argument("--quiet", "-q", action="store_true", help="Suppress per-violation output.")
   chk_p.add_argument(
      "--json",
      action="store_true",
      dest="json_out",
      help="Output violations as JSON.",
   )
   chk_p.add_argument(
      "--ignore", metavar="RULES", action="append", default=[],
      help="Rule codes to ignore, comma/semicolon-separated (e.g. CF014,CF015). May be repeated.",
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
   ren_p.add_argument(
      "--json",
      action="store_true",
      dest="json_out",
      help="Output the rename plan as JSON.",
   )

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
   # Output is always JSON; no --json flag needed.
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

   # -- resolve --------------------------------------------------------------
   res_p = sub.add_parser(
      "resolve",
      help="Build a per-file resolved symbol graph.",
      description=(
         "Walk Python files, build a scope tree, and resolve name references "
         "to their definitions within each file. Does not modify any files."
      ),
   )
   res_p.add_argument(
      "paths", nargs="+", metavar="PATH", help="Files or directories to resolve."
   )
   res_p.add_argument(
      "--pretty",
      action="store_true",
      help="Pretty-print JSON with indentation.",
   )
   res_p.add_argument(
      "--output",
      metavar="PATH",
      default=None,
      help="Write JSON to PATH instead of stdout.",
   )

   # -- refs -----------------------------------------------------------------
   refs_p = sub.add_parser(
      "refs",
      help="Find read-only project references for a name or symbol.",
      description=(
         "Walk Python files, resolve per-file names, and conservatively "
         "resolve import references between files. Does not modify any files."
      ),
   )
   refs_p.add_argument(
      "paths", nargs="+", metavar="PATH", help="Files or directories to inspect."
   )
   query = refs_p.add_mutually_exclusive_group(required=True)
   query.add_argument(
      "--name",
      metavar="NAME",
      default=None,
      help="Find definitions and references matching NAME.",
   )
   query.add_argument(
      "--symbol",
      metavar="PATH:LINE:COL",
      default=None,
      help="Find references to the definition or reference at PATH:LINE:COL.",
   )
   refs_p.add_argument(
      "--pretty",
      action="store_true",
      help="Pretty-print JSON with indentation.",
   )
   refs_p.add_argument(
      "--output",
      metavar="PATH",
      default=None,
      help="Write JSON to PATH instead of stdout.",
   )

   # -- rename-symbol --------------------------------------------------------
   sym_p = sub.add_parser(
      "rename-symbol",
      help="Plan a read-only project-wide symbol rename.",
      description=(
         "Walk Python files, find safe project references for one symbol, "
         "and emit JSON, render a unified diff, or apply guarded token edits."
      ),
   )
   sym_p.add_argument(
      "paths", nargs="+", metavar="PATH", help="Files or directories to inspect."
   )
   sym_query = sym_p.add_mutually_exclusive_group(required=True)
   sym_query.add_argument(
      "--symbol",
      metavar="PATH:LINE:COL",
      default=None,
      help="Plan rename for the definition or reference at PATH:LINE:COL.",
   )
   sym_query.add_argument(
      "--name",
      metavar="NAME",
      default=None,
      help="Plan rename for NAME if it resolves to exactly one definition.",
   )
   sym_p.add_argument(
      "--to",
      metavar="NewName",
      required=True,
      dest="new_name",
      help="New symbol name to use in the read-only plan.",
   )
   sym_p.add_argument(
      "--pretty",
      action="store_true",
      help="Pretty-print JSON with indentation (ignored with --diff).",
   )
   sym_p.add_argument(
      "--output",
      metavar="PATH",
      default=None,
      help="Write JSON to PATH instead of stdout.",
   )
   sym_p.add_argument(
      "--diff",
      action="store_true",
      help="Print a unified diff from the rename plan without writing files.",
   )
   sym_p.add_argument(
      "--apply",
      action="store_true",
      help="Apply guarded token edits from the rename plan.",
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
   ignore_codes = ParseIgnoreCodes(args.ignore)
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
            ignore_codes=ignore_codes,
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
   ignore_codes = ParseIgnoreCodes(args.ignore)
   all_violations: list[Violation] = []

   for path in files:
      try:
         viols = CheckFile(path, ignore_codes=ignore_codes)
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
   import json as _json

   from customfmt.symbols.model import FileError

   try:
      files = CollectFiles(args.paths)
   except FileNotFoundError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if not files:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   quiet: bool   = args.quiet
   json_out: bool = getattr(args, "json_out", False)
   any_candidate = False
   all_plans     = []

   for path in files:
      plan = PlanFile(path)
      if isinstance(plan, FileError):
         print(f"customfmt: error: {path}: {plan.Error}", file=sys.stderr)
         return 2

      if not plan.Items:
         continue

      any_candidate = True
      all_plans.append(plan)

      if not json_out:
         if args.diff:
            print(plan.UnifiedDiff(path), end="")
         elif not quiet:
            for v in plan.Violations(path):
               print(v)

      if args.apply:
         plan.Apply(path)
         if not quiet and not json_out:
            print(f"renamed {path}")

   if json_out:
      payload = [p.ToDict() for p in all_plans]
      print(_json.dumps(payload, indent=2))

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


def _CmdResolve(args: argparse.Namespace) -> int:
   import json as _json

   try:
      files = CollectFiles(args.paths)
   except FileNotFoundError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if not files:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   result_set = ResolveResultSet()
   for path in files:
      result = ResolveFile(path)
      from customfmt.symbols.model import FileError
      if isinstance(result, FileError):
         result_set.Errors.append(result)
      else:
         result_set.Files.append(result)

   indent = 2 if args.pretty else None
   serialised = _json.dumps(result_set.ToDict(), indent=indent)

   if args.output:
      try:
         WriteUtf8Lf(Path(args.output), serialised + "\n")
      except OSError as exc:
         print(f"customfmt: error writing {args.output}: {exc}", file=sys.stderr)
         return 2
   else:
      print(serialised)

   return 0


def _CmdRefs(args: argparse.Namespace) -> int:
   import json as _json

   try:
      if args.name is not None:
         result, disc_errors = FindRefsByName(args.paths, args.name)
      else:
         result, disc_errors = FindRefsBySymbol(args.paths, args.symbol)
   except ValueError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if disc_errors:
      for err in disc_errors:
         print(f"customfmt: error: {err}", file=sys.stderr)
      return 2

   if result is None:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   indent = 2 if args.pretty else None
   serialised = _json.dumps(result.ToDict(), indent=indent)

   if args.output:
      try:
         WriteUtf8Lf(Path(args.output), serialised + "\n")
      except OSError as exc:
         print(f"customfmt: error writing {args.output}: {exc}", file=sys.stderr)
         return 2
   else:
      print(serialised)

   return 0


def _CmdRenameSymbol(args: argparse.Namespace) -> int:
   import json as _json

   if args.diff and args.apply:
      print("customfmt: error: --apply cannot be combined with --diff", file=sys.stderr)
      return 2
   if args.diff and args.output:
      print("customfmt: error: --diff cannot be combined with --output", file=sys.stderr)
      return 2
   if args.apply and args.output:
      print("customfmt: error: --apply cannot be combined with --output", file=sys.stderr)
      return 2
   if args.apply and args.pretty:
      print("customfmt: error: --apply cannot be combined with --pretty", file=sys.stderr)
      return 2

   try:
      plan, disc_errors = PlanRenameSymbol(
         args.paths,
         symbol=args.symbol,
         name=args.name,
         new_name=args.new_name,
      )
   except ValueError as exc:
      print(f"customfmt: error: {exc}", file=sys.stderr)
      return 2

   if disc_errors:
      for err in disc_errors:
         print(f"customfmt: error: {err}", file=sys.stderr)
      return 2

   if plan is None:
      print("customfmt: no Python files found.", file=sys.stderr)
      return 2

   if args.diff:
      try:
         print(RenderPlanDiff(plan), end="")
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         print(f"customfmt: error: {exc}", file=sys.stderr)
         return 2
      return 0

   if args.apply:
      try:
         rendered_by_file = RenderPlanTextByFile(plan)
      except (OSError, UnicodeDecodeError, ValueError) as exc:
         print(f"customfmt: error: {exc}", file=sys.stderr)
         return 2
      try:
         for path, rewritten in rendered_by_file.items():
            WriteUtf8Lf(path, rewritten)
      except OSError as exc:
         print(f"customfmt: error writing renamed file: {exc}", file=sys.stderr)
         return 2
      for path in rendered_by_file:
         print(f"renamed {path}")
      return 0

   indent = 2 if args.pretty else None
   serialised = _json.dumps(plan.ToDict(), indent=indent)

   if args.output:
      try:
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
      elif args.command == "resolve":
         return _CmdResolve(args)
      elif args.command == "refs":
         return _CmdRefs(args)
      elif args.command == "rename-symbol":
         return _CmdRenameSymbol(args)
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


def MainResolve(argv: list[str] | None = None) -> int:
   """Entry point for ``resolve-index`` alias."""
   effective = ["resolve"] + (sys.argv[1:] if argv is None else argv)
   return Main(effective, prog="resolve-index")


def _EntryResolve() -> None:
   sys.exit(MainResolve())
