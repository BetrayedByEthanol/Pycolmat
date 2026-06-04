"""Read-only renderers for project-wide rename-symbol plans."""

from __future__ import annotations

import difflib
import io
import tokenize
from pathlib import Path

from customfmt.io import ReadUtf8Text
from customfmt.rename_symbol_plan import RenameSymbolEdit, RenameSymbolPlan


def RenderPlanDiff(plan: RenameSymbolPlan) -> str:
   """Render *plan* as a unified diff without writing files."""
   chunks: list[str] = []
   for file_path in sorted({edit.FilePath for edit in plan.Edits}):
      path = Path(file_path)
      original = ReadUtf8Text(path)
      rewritten = RenderPlanTextForFile(plan, path)
      if original == rewritten:
         continue
      chunks.append(
         "".join(
            difflib.unified_diff(
               original.splitlines(keepends=True),
               rewritten.splitlines(keepends=True),
               fromfile=f"a/{path}",
               tofile=f"b/{path}",
            )
         )
      )
   return "".join(chunks)


def RenderPlanTextForFile(plan: RenameSymbolPlan, path: Path) -> str:
   """Return rewritten text for *path* using only exact token edits from *plan*."""
   original = ReadUtf8Text(path)
   edits = _EditsForFile(plan, path)
   if not edits:
      return original

   edit_map = _BuildEditMap(edits)
   seen_positions: set[tuple[int, int]] = set()
   rendered_tokens: list[tokenize.TokenInfo] = []

   for token in tokenize.generate_tokens(io.StringIO(original).readline):
      position = token.start
      edit = edit_map.get(position)
      if edit is None:
         rendered_tokens.append(token)
         continue

      _ValidateTokenForEdit(path, token, edit)
      seen_positions.add(position)
      rendered_tokens.append(token._replace(string=edit.New))

   missing = sorted(set(edit_map) - seen_positions)
   if missing:
      line, col = missing[0]
      raise ValueError(f"{path}:{line}:{col}: planned edit does not match a token")

   return tokenize.untokenize(rendered_tokens)


def _EditsForFile(plan: RenameSymbolPlan, path: Path) -> list[RenameSymbolEdit]:
   path_text = str(path)
   return sorted(
      (edit for edit in plan.Edits if edit.FilePath == path_text),
      key=lambda edit: (edit.Line, edit.Col, edit.Kind, edit.Old, edit.New),
   )


def _BuildEditMap(edits: list[RenameSymbolEdit]) -> dict[tuple[int, int], RenameSymbolEdit]:
   edit_map: dict[tuple[int, int], RenameSymbolEdit] = {}
   for edit in edits:
      position = (edit.Line, edit.Col)
      existing = edit_map.get(position)
      if existing is None:
         edit_map[position] = edit
         continue
      if existing.Old == edit.Old and existing.New == edit.New:
         continue
      raise ValueError(
         f"{edit.FilePath}:{edit.Line}:{edit.Col}: duplicate conflicting rename-symbol edits"
      )
   return edit_map


def _ValidateTokenForEdit(path: Path, token: tokenize.TokenInfo, edit: RenameSymbolEdit) -> None:
   if token.type != tokenize.NAME:
      raise ValueError(
         f"{path}:{edit.Line}:{edit.Col}: planned edit targets {tokenize.tok_name[token.type]}, not NAME"
      )
   if token.string != edit.Old:
      raise ValueError(
         f"{path}:{edit.Line}:{edit.Col}: planned edit expected {edit.Old!r}, found {token.string!r}"
      )
