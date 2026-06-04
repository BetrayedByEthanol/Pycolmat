"""Tests for read-only project-wide rename-symbol planning."""

from __future__ import annotations

import contextlib
import json
import textwrap
from io import StringIO
from pathlib import Path

from customfmt.cli import Main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Src(text: str) -> str:
   return textwrap.dedent(text)


def Write(path: Path, text: str) -> Path:
   path.parent.mkdir(parents=True, exist_ok=True)
   path.write_text(text, encoding="utf-8")
   return path


def Package(tmp_path: Path) -> Path:
   pkg = tmp_path / "pkg"
   Write(pkg / "__init__.py", "")
   return pkg


def RunPlan(paths, *args: str) -> tuple[int, dict, str]:
   out = StringIO()
   err = StringIO()
   with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
      rc = Main(["rename-symbol", str(paths), *args])
   data = json.loads(out.getvalue()) if out.getvalue().strip() else {}
   return rc, data, err.getvalue()


# ---------------------------------------------------------------------------
# Rename-symbol plan
# ---------------------------------------------------------------------------


class TestRenameSymbolPlan:
   def TestClassDefinitionIncludesDefinitionAndConstructorCalls(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "UserModel", "--to", "AccountModel")
      edits = {(e["file"], e["line"], e["old"], e["new"]) for e in data["edits"]}

      assert rc == 0
      assert data["target"]["kind"] == "class"
      assert any(line == 1 and old == "UserModel" for _, line, old, _ in edits)
      assert any(line == 5 and old == "UserModel" for _, line, old, _ in edits)

   def TestFunctionDefinitionIncludesDefinitionAndCalls(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            def BuildValue():
               return 1

            def Run():
               return BuildValue()
            """
         ),
      )

      rc, data, _ = RunPlan(f, "--symbol", f"{f}:2:0", "--to", "MakeValue")
      kinds = [e["kind"] for e in data["edits"]]

      assert rc == 0
      assert "definition:function" in kinds
      assert "reference:call" in kinds

   def TestFromImportClassUpdatesImportedBindingReferences(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "UserModel", "--to", "AccountModel")
      import_edits = [e for e in data["edits"] if e["kind"] == "definition:import_from"]

      assert rc == 0
      assert import_edits
      assert import_edits[0]["old"] == "UserModel"

   def TestFromImportAliasDoesNotRenameAliasWhenTargetRenamed(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import UserModel as Model

            def Build():
               return Model()
            """
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "UserModel", "--to", "AccountModel")
      names = [e["old"] for e in data["edits"]]

      assert rc == 0
      assert "UserModel" in names
      assert "Model" not in names

   def TestImportModuleAttributePlansOnlyAttributeToken(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      main = Write(
         pkg / "main.py",
         Src(
            """
            import pkg.utils

            def Run():
               return pkg.utils.BuildValue()
            """
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "BuildValue", "--to", "MakeValue")
      attr_edit = [e for e in data["edits"] if e["file"] == str(main)][0]

      assert rc == 0
      assert attr_edit["old"] == "BuildValue"
      assert attr_edit["col"] == 20

   def TestUnresolvedExternalImportsAreSkipped(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            from external.pkg import UserModel

            def Run():
               return UserModel()
            """
         ),
      )

      rc, data, _ = RunPlan(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert data["skipped"]
      assert data["skipped"][0]["reason"] == "import_not_safely_resolved"

   def TestDynamicMethodSkipped(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            def BuildValue():
               return 1

            def Run(obj):
               return obj.BuildValue()
            """
         ),
      )

      rc, data, _ = RunPlan(f, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert data["dynamic_references"]
      assert data["dynamic_references"][0]["confidence"] == "dynamic"

   def TestAmbiguousNameReturnsError(self, tmp_path):
      Write(tmp_path / "a.py", "class UserModel:\n   pass\n")
      Write(tmp_path / "b.py", "class UserModel:\n   pass\n")

      rc, data, err = RunPlan(tmp_path, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert data == {}
      assert "ambiguous" in err

   def TestInvalidNewNameReturnsError(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")

      rc, data, err = RunPlan(f, "--name", "UserModel", "--to", "account_model")

      assert rc == 2
      assert data == {}
      assert "PascalCase" in err

   def TestCollisionWithExistingSymbolWarns(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            class AccountModel:
               pass
            """
         ),
      )

      rc, data, _ = RunPlan(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert data["warnings"]
      assert data["warnings"][0]["reason"] == "same_scope_definition_exists"

   def TestPrettyOutputsIndentedJson(self, tmp_path, capsys):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")

      rc = Main([
         "rename-symbol", str(f), "--name", "UserModel", "--to", "AccountModel",
         "--pretty",
      ])
      out = capsys.readouterr().out

      assert rc == 0
      assert "\n  \"query\"" in out

   def TestOutputWritesJson(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      out_path = tmp_path / "plan.json"

      rc = Main([
         "rename-symbol", str(f), "--name", "UserModel", "--to", "AccountModel",
         "--output", str(out_path),
      ])
      data = json.loads(out_path.read_text(encoding="utf-8"))

      assert rc == 0
      assert data["new_name"] == "AccountModel"

   def TestCommandIsReadOnly(self, tmp_path):
      original = "class UserModel:\n   pass\n"
      f = Write(tmp_path / "main.py", original)

      rc, _, _ = RunPlan(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert f.read_text(encoding="utf-8") == original
