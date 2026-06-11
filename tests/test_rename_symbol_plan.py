"""Tests for read-only project-wide rename-symbol planning."""

from __future__ import annotations

import contextlib
import json
import textwrap
from io import StringIO
from pathlib import Path

from customfmt.cli import Main
from customfmt.rename_symbol_plan import RenameSymbolEdit, RenameSymbolPlan
from customfmt.symbols.project_graph import ProjectDefinition

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
   path_args = paths if isinstance(paths, list) else [str(paths)]
   with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
      rc = Main(["rename-symbol", *path_args, *args])
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

   def TestMethodRenamePlanIncludesDefinition(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class UserModel:
               def BuildValue(self):
                  return 1
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert err == ""
      assert data["target"]["kind"] == "method"
      assert [e["kind"] for e in data["edits"]] == ["definition:method"]

   def TestMethodRenameWithSameClassSelfReferencePlansDefinitionAndSelfRef(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class UserModel:
               def BuildValue(self):
                  return self.Helper()

               def Helper(self):
                  return 1
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Helper", "--to", "MakeValue")
      edits = {(e["line"], e["col"], e["old"], e["kind"]) for e in data["edits"]}

      assert rc == 0
      assert err == ""
      assert data["target"]["kind"] == "method"
      assert (4, 18, "Helper", "reference:attribute_call") in edits
      assert (6, 7, "Helper", "definition:method") in edits

   def TestMethodRenameWithClassMethodReferencePlansDefinitionAndClassRef(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               def BuildValue(self):
                  return 1

            def Run(user):
               return UserModel.BuildValue(user)
            """
         ),
      )

      rc, data, err = RunPlan(f, "--name", "BuildValue", "--to", "MakeValue")
      edits = {(e["line"], e["col"], e["old"], e["kind"]) for e in data["edits"]}

      assert rc == 0
      assert err == ""
      assert data["target"]["kind"] == "method"
      assert (3, 7, "BuildValue", "definition:method") in edits
      assert (7, 20, "BuildValue", "reference:attribute_call") in edits

   def TestMethodRenameWithClsReferencePlansDefinitionAndClsRef(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               @classmethod
               def BuildValue(cls):
                  return cls.Helper()

               @classmethod
               def Helper(cls):
                  return 1
            """
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Helper", "--to", "MakeValue")
      edits = {(e["line"], e["col"], e["old"], e["kind"]) for e in data["edits"]}

      assert rc == 0
      assert err == ""
      assert data["target"]["kind"] == "method"
      assert (5, 17, "Helper", "reference:attribute_call") in edits
      assert (8, 7, "Helper", "definition:method") in edits

   def TestMethodRenameBySymbolPlansDefinition(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class UserModel:
               def BuildValue(self):
                  return 1
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--symbol", f"{f}:3:3", "--to", "MakeValue")

      assert rc == 0
      assert err == ""
      assert data["target"]["kind"] == "method"
      assert data["target"]["name"] == "BuildValue"
      assert data["edits"][0]["kind"] == "definition:method"

   def TestMethodRenameByNameWithDuplicateMethodNamesIsAmbiguous(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class Repo:
               def Build(self):
                  return 1

            class OtherRepo:
               def Build(self):
                  return 2
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert data == {}
      assert "--name is ambiguous" in err
      assert "use --symbol" in err

   def TestMethodRenameBySymbolWithDuplicateMethodNamesSelectsOneMethod(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class Repo:
               def Build(self):
                  return 1

            class OtherRepo:
               def Build(self):
                  return 2
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--symbol", f"{f}:3:3", "--to", "Make")

      assert rc == 0
      assert err == ""
      assert data["target"]["qualified_name"] == "Repo.Build"
      assert [e["line"] for e in data["edits"]] == [3]

   def TestMethodMetadataEnablesMethodRenameBySymbol(self, tmp_path):
      original = "class Repo:\n   def GetByID(self):\n      pass\n"
      f = Write(tmp_path / "main.py", original)
      out = StringIO()
      err = StringIO()

      with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
         rc = Main(["rename-symbol", str(f), "--symbol", f"{f}:2:3", "--to", "FindByID"])

      assert rc == 0
      assert err.getvalue() == ""
      assert '"kind": "method"' in out.getvalue()
      assert f.read_text(encoding="utf-8") == original


   def TestImportedMethodRenameByNamePlansDefinitionAndImportedClassRef(self, tmp_path):
      pkg = tmp_path / "pkg"
      Write(pkg / "__init__.py", "")
      Write(
         pkg / "models.py",
         Src(
            """
            class Repo:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import Repo

            def Run(repo):
               return Repo.Build(repo)
            """
         ),
      )

      rc, data, err = RunPlan(pkg, "--name", "Build", "--to", "Make")
      edits = {
         (Path(e["file"]).name, e["line"], e["col"], e["old"], e["kind"])
         for e in data["edits"]
      }

      assert rc == 0
      assert err == ""
      assert data["target"]["kind"] == "method"
      assert ("models.py", 3, 7, "Build", "definition:method") in edits
      assert ("main.py", 5, 15, "Build", "reference:attribute_call") in edits

   def TestMethodRenameWithDynamicObjReferenceIsRejected(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Repo:
               def Build(self):
                  return 1

            def Run(obj):
               return obj.Build()
            """
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert data == {}
      assert "method rename plan is incomplete" in err
      assert "dynamic reference" in err

   def TestMethodRenameCollisionWithSameClassMethodIsRejected(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class Repo:
               def ExistingMethod(self):
                  return 1

               def Helper(self):
                  return 2
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Helper", "--to", "ExistingMethod")

      assert rc == 2
      assert data == {}
      assert "method rename plan is incomplete" in err
      assert "warning" in err

   def TestMethodRenameInheritedMethodReferenceStaysDynamicAndRejected(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class Base:
               def Build(self):
                  return 1

            class Child(Base):
               pass

            def Run():
               return Child.Build()
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert data == {}
      assert "method rename plan is incomplete" in err
      assert "dynamic reference" in err

   def TestMethodRenameGetattrStringReferenceIsDynamicAndRejected(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class Repo:
               def Build(self):
                  return 1

            def Run(obj):
               return getattr(obj, "Build")()
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert data == {}
      assert "method rename plan is incomplete" in err
      assert "dynamic reference" in err
      assert f.read_text(encoding="utf-8").count("Build") == 2

   def TestMethodRenameWithAmbiguousImportedClassReferenceIsRejected(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      Write(first / "ns" / "models.py", "class Repo:\n   def Build(self):\n      return 1\n")
      Write(second / "ns" / "models.py", "class Repo:\n   def Build(self):\n      return 2\n")
      Write(
         first / "ns" / "main.py",
         Src(
            """
            from ns.models import Repo

            def Run(repo):
               return Repo.Build(repo)
            """
         ),
      )
      symbol = f"{first / 'ns' / 'models.py'}:2:3"

      rc, data, err = RunPlan([str(first), str(second)], "--symbol", symbol, "--to", "Make")

      assert rc == 2
      assert data == {}
      assert "method rename plan is incomplete" in err
      assert "dynamic reference" in err

   def TestMethodRenameWithExternalImportedClassReferenceIsRejected(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Repo:
               def Build(self):
                  return 1

            from external.models import Repo as ExternalRepo

            def Run(repo):
               return ExternalRepo.Build(repo)
            """
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert data == {}
      assert "method rename plan is incomplete" in err
      assert "dynamic reference" in err

   def TestClassAttributeRenameRejected(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class UserModel:
               Status = 1
            '''
         ),
      )

      rc, data, err = RunPlan(f, "--name", "Status", "--to", "State")

      assert rc == 2
      assert data == {}
      assert "supported project symbol" in err

   def TestRelativeImportBindingIsPlannedWhenResolved(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            '''
            from .models import UserModel

            def Build():
               return UserModel()
            '''
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "UserModel", "--to", "AccountModel")
      import_edits = [
         e for e in data["edits"]
         if e["file"] == str(main) and e["kind"] == "definition:import_from"
      ]

      assert rc == 0
      assert import_edits
      assert import_edits[0]["old"] == "UserModel"
      assert not data["unresolved_references"]

   def TestRelativeModuleImportAttributeIsPlannedWhenResolved(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      main = Write(
         pkg / "main.py",
         Src(
            '''
            from . import utils

            def Run():
               return utils.BuildValue()
            '''
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "BuildValue", "--to", "MakeValue")
      main_edits = [e for e in data["edits"] if e["file"] == str(main)]

      assert rc == 0
      assert any(e["old"] == "BuildValue" for e in main_edits)
      assert any(e["file"] == str(utils) for e in data["edits"])
      assert not data["unresolved_references"]

   def TestUnresolvedRelativeImportStaysUnresolvedInPlan(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         pkg / "main.py",
         Src(
            '''
            from .missing import UserModel

            def Build():
               return UserModel()
            '''
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "UserModel", "--to", "AccountModel")
      reasons = [item["reason"] for item in data["unresolved_references"]]

      assert rc == 0
      assert "unresolved" in reasons

   def TestWildcardImportReferenceStaysUnresolvedInPlan(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         pkg / "main.py",
         Src(
            '''
            from pkg.models import *

            def Build():
               return UserModel()
            '''
         ),
      )

      rc, data, _ = RunPlan(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert data["unresolved_references"]
      assert data["unresolved_references"][0]["name"] == "UserModel"

   def TestStringAndCommentReferencesAreNotPlanned(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class UserModel:
               pass

            MESSAGE = "UserModel"
            # UserModel stays in comments
            '''
         ),
      )

      rc, data, _ = RunPlan(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert len(data["edits"]) == 1
      assert data["edits"][0]["kind"] == "definition:class"

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


class TestRenameSymbolDiff:
   def RunDiff(self, paths, *args: str) -> tuple[int, str, str]:
      out = StringIO()
      err = StringIO()
      with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
         rc = Main(["rename-symbol", str(paths), *args, "--diff"])
      return rc, out.getvalue(), err.getvalue()

   def TestDiffOutputsUnifiedDiffAndDoesNotModifyFiles(self, tmp_path):
      original = "class UserModel:\n   pass\n\ndef Build():\n   return UserModel()\n"
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert f"--- a/{f}" in out
      assert f"+++ b/{f}" in out
      assert "-class UserModel:" in out
      assert "+class AccountModel:" in out
      assert "-   return UserModel()" in out
      assert "+   return AccountModel()" in out
      assert f.read_text(encoding="utf-8") == original

   def TestMethodDiffRenamesDefinitionAndSelfReference(self, tmp_path):
      original = Src(
         """
         class Repo:
            def Run(self):
               return self.Build()

            def Build(self):
               return 1
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunDiff(f, "--name", "Build", "--to", "Make")

      assert rc == 0
      assert err == ""
      assert "-      return self.Build()" in out
      assert "+      return self.Make()" in out
      assert "-   def Build(self):" in out
      assert "+   def Make(self):" in out
      assert f.read_text(encoding="utf-8") == original

   def TestDiffIncludesNamespaceAbsoluteImportBindingAndCallSite(self, tmp_path):
      ns = tmp_path / "ns"
      Write(ns / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         ns / "main.py",
         Src(
            """
            from ns.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      rc, out, err = self.RunDiff(tmp_path, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert "-class UserModel:" in out
      assert "+class AccountModel:" in out
      assert "-from ns.models import UserModel" in out
      assert "+from ns.models import AccountModel" in out
      assert "-   return UserModel()" in out
      assert "+   return AccountModel()" in out
      assert "UserModel" in main.read_text(encoding="utf-8")

   def TestDiffIncludesNamespaceRelativeImportBindingAndCallSite(self, tmp_path):
      ns = tmp_path / "ns"
      Write(ns / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         ns / "main.py",
         Src(
            """
            from .models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      rc, out, err = self.RunDiff(tmp_path, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert "-class UserModel:" in out
      assert "+class AccountModel:" in out
      assert "-from .models import UserModel" in out
      assert "+from .models import AccountModel" in out
      assert "-   return UserModel()" in out
      assert "+   return AccountModel()" in out
      assert "UserModel" in main.read_text(encoding="utf-8")

   def TestDiffOutputIsRejectedAndDoesNotWriteFile(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      out_path = tmp_path / "rename.diff"

      rc, out, err = self.RunDiff(
         f, "--name", "UserModel", "--to", "AccountModel", "--output", str(out_path)
      )

      assert rc == 2
      assert out == ""
      assert "--diff cannot be combined with --output" in err
      assert not out_path.exists()

   def TestDiffRejectsAllowIncompleteForMethodPlan(self, tmp_path):
      f = Write(tmp_path / "main.py", "class Repo:\n   def Build(self):\n      return 1\n")

      rc, out, err = self.RunDiff(f, "--name", "Build", "--to", "Make", "--allow-incomplete")

      assert rc == 2
      assert out == ""
      assert "--allow-incomplete requires --apply" in err

   def TestDiffPrettySucceedsWithNormalDiff(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")

      rc, out, err = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel", "--pretty")

      assert rc == 0
      assert err == ""
      assert "--- a/" in out
      assert "+class AccountModel:" in out
      assert '"query"' not in out

   def TestDiffPreservesAlignedClassBodySpacing(self, tmp_path):
      original = Src(
         """
         class UserModel:
            ID          : int
            Name        : str = ""
            Description : str
            Enabled           = True

         def Build():
            return UserModel()
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, _ = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert "+class AccountModel:" in out
      assert " ID          : int" in out
      assert " Name        : str = \"\"" in out
      assert " Description : str" in out
      assert " Enabled           = True" in out
      assert f.read_text(encoding="utf-8") == original

   def TestClassRenameDiffIncludesDefinitionAndConstructorCall(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            def Build():
               return UserModel()
            """
         ),
      )

      rc, out, _ = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert "+class AccountModel:" in out
      assert "+   return AccountModel()" in out

   def TestFunctionRenameDiffAcrossFiles(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.utils import BuildValue

            def Run():
               return BuildValue()
            """
         ),
      )

      rc, out, _ = self.RunDiff(pkg, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert "def MakeValue():" in out
      assert "from pkg.utils import MakeValue" in out
      assert "return MakeValue()" in out

   def TestImportFromBindingDiff(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(pkg / "main.py", "from pkg.models import UserModel\n")

      rc, out, _ = self.RunDiff(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert "-from pkg.models import UserModel" in out
      assert "+from pkg.models import AccountModel" in out

   def TestRelativeImportFromBindingDiff(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            """
            from .models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )
      main_original = main.read_text(encoding="utf-8")

      rc, out, _ = self.RunDiff(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert "-from .models import UserModel" in out
      assert "+from .models import AccountModel" in out
      assert "-   return UserModel()" in out
      assert "+   return AccountModel()" in out
      assert main.read_text(encoding="utf-8") == main_original

   def TestRelativeModuleImportAttributeDiff(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from . import utils

            def Run():
               return utils.BuildValue()
            """
         ),
      )

      rc, out, _ = self.RunDiff(pkg, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert "def MakeValue():" in out
      assert "from . import utils" in out
      assert "utils.MakeValue()" in out

   def TestModuleAttributeDiffEditsOnlyAttributeToken(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         pkg / "main.py",
         Src(
            """
            import pkg.utils

            def Run():
               return pkg.utils.BuildValue()
            """
         ),
      )

      rc, out, _ = self.RunDiff(pkg, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert "pkg.utils.MakeValue()" in out
      assert "import pkg.utils" in out
      assert "pkg.MakeValue" not in out

   def TestAnnotationsDiff(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            def Build(user: UserModel) -> UserModel:
               return user
            """
         ),
      )

      rc, out, _ = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert "user: AccountModel" in out
      assert "-> AccountModel" in out

   def TestTokenMismatchProducesExitTwo(self, tmp_path, monkeypatch):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      plan = RenameSymbolPlan(Query={}, Target=None, NewName="AccountModel")
      plan.Edits.append(
         RenameSymbolEdit(str(f), 1, 6, "OtherModel", "AccountModel", "definition:class")
      )
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, out, err = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "expected 'OtherModel'" in err

   def TestNoEditsProducesEmptyDiffAndExitZero(self, tmp_path, monkeypatch):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      plan = RenameSymbolPlan(Query={}, Target=None, NewName="AccountModel")
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, out, err = self.RunDiff(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert out == ""
      assert err == ""

class TestRenameSymbolApply:
   def RunApply(self, paths, *args: str) -> tuple[int, str, str]:
      out = StringIO()
      err = StringIO()
      path_args = paths if isinstance(paths, list) else [str(paths)]
      with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
         rc = Main(["rename-symbol", *path_args, *args, "--apply"])
      return rc, out.getvalue(), err.getvalue()


   def TestApplySafeSelfMethodWritesDefinitionAndSelfReference(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Repo:
               def Run(self):
                  return self.Build()

               def Build(self):
                  return 1
            """
         ),
      )

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 0
      assert err == ""
      assert f"renamed {f}" in out
      text = f.read_text(encoding="utf-8")
      assert "return self.Make()" in text
      assert "def Make(self):" in text
      assert "Build" not in text

   def TestApplySafeClsMethodWritesDefinitionAndClsReference(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Repo:
               @classmethod
               def Run(cls):
                  return cls.Build()

               @classmethod
               def Build(cls):
                  return 1
            """
         ),
      )

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 0
      assert err == ""
      assert f"renamed {f}" in out
      text = f.read_text(encoding="utf-8")
      assert "return cls.Make()" in text
      assert "def Make(cls):" in text
      assert "Build" not in text

   def TestApplySafeSameFileClassMethodWritesDefinitionAndClassReference(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Repo:
               def Build(self):
                  return 1

            def Run(repo):
               return Repo.Build(repo)
            """
         ),
      )

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 0
      assert err == ""
      assert f"renamed {f}" in out
      text = f.read_text(encoding="utf-8")
      assert "def Make(self):" in text
      assert "return Repo.Make(repo)" in text
      assert "Build" not in text

   def TestApplySafeImportedClassMethodWritesDefinitionAndImportedReference(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(
         pkg / "models.py",
         Src(
            """
            class Repo:
               def Build(self):
                  return 1
            """
         ),
      )
      main = Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import Repo

            def Run(repo):
               return Repo.Build(repo)
            """
         ),
      )

      rc, out, err = self.RunApply(pkg, "--name", "Build", "--to", "Make")

      assert rc == 0
      assert err == ""
      assert f"renamed {model}" in out
      assert f"renamed {main}" in out
      assert "def Make(self):" in model.read_text(encoding="utf-8")
      main_text = main.read_text(encoding="utf-8")
      assert "return Repo.Make(repo)" in main_text
      assert "Build" not in main_text

   def TestApplyMethodWriteFailureRollsBackAllFiles(self, tmp_path, monkeypatch):
      pkg = Package(tmp_path)
      model_original = Src(
         """
         class Repo:
            def Build(self):
               return 1
         """
      )
      main_original = Src(
         """
         from pkg.models import Repo

         def Run(repo):
            return Repo.Build(repo)
         """
      )
      model = Write(pkg / "models.py", model_original)
      main = Write(pkg / "main.py", main_original)
      calls = {"count": 0}

      def FailSecondWrite(path, text):
         calls["count"] += 1
         if calls["count"] == 2:
            raise OSError("simulated write failure")
         path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")

      monkeypatch.setattr("customfmt.cli.WriteUtf8Lf", FailSecondWrite)

      rc, out, err = self.RunApply(pkg, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert out == ""
      assert "simulated write failure" in err
      assert model.read_text(encoding="utf-8") == model_original
      assert main.read_text(encoding="utf-8") == main_original

   def TestApplyIncompleteMethodPlanRefusesAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class Repo:
            def Build(self):
               return 1

         def Run(obj):
            return obj.Build()
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert out == ""
      assert "method rename plan is incomplete" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyMethodCollisionRefusesAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class Repo:
            def ExistingMethod(self):
               return 1

            def Helper(self):
               return 2
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "Helper", "--to", "ExistingMethod")

      assert rc == 2
      assert out == ""
      assert "method rename plan is incomplete" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyMethodTokenMismatchRefusesAndWritesNothing(self, tmp_path, monkeypatch):
      original = "class Repo:\n   def Build(self):\n      return 1\n"
      f = Write(tmp_path / "main.py", original)
      target = ProjectDefinition(
         Name          = "Build",
         Kind          = "method",
         FilePath      = str(f),
         Line          = 2,
         Col           = 3,
         ScopeId       = "repo",
         ScopeName     = "Repo",
         Confidence    = "local_resolved",
         QualifiedName = "Repo.Build",
         Extra         = {"owner_class_name": "Repo"},
      )
      plan = RenameSymbolPlan(Query={}, Target=target, NewName="Make")
      plan.Edits.append(RenameSymbolEdit(str(f), 2, 7, "Other", "Make", "definition:method"))
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert out == ""
      assert "expected 'Other'" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyDynamicObjMethodRefusesAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class Repo:
            def Build(self):
               return 1

         def Run(obj):
            return obj.Build()
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert out == ""
      assert "dynamic reference" in err
      assert "--allow-incomplete cannot apply incomplete method plans" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAmbiguousImportedMethodRefusesAndWritesNothing(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      model_original = "class Repo:\n   def Build(self):\n      return 1\n"
      main_original = Src(
         """
         from ns.models import Repo

         def Run(repo):
            return Repo.Build(repo)
         """
      )
      model = Write(first / "ns" / "models.py", model_original)
      Write(second / "ns" / "models.py", "class Repo:\n   def Build(self):\n      return 2\n")
      main = Write(first / "ns" / "main.py", main_original)
      symbol = f"{model}:2:3"

      rc, out, err = self.RunApply([str(first), str(second)], "--symbol", symbol, "--to", "Make")

      assert rc == 2
      assert out == ""
      assert "method rename plan is incomplete" in err
      assert model.read_text(encoding="utf-8") == model_original
      assert main.read_text(encoding="utf-8") == main_original

   def TestApplyExternalImportedMethodRefusesAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class Repo:
            def Build(self):
               return 1

         from external.models import Repo as ExternalRepo

         def Run(repo):
            return ExternalRepo.Build(repo)
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "Build", "--to", "Make")

      assert rc == 2
      assert out == ""
      assert "method rename plan is incomplete" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAllowIncompleteDoesNotPermitIncompleteMethodApply(self, tmp_path):
      original = Src(
         """
         class Repo:
            def Build(self):
               return 1

         def Run(obj):
            return obj.Build()
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(
         f, "--name", "Build", "--to", "Make", "--allow-incomplete"
      )

      assert rc == 2
      assert out == ""
      assert "method rename plan is incomplete" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAllowIncompleteStillRefusesMonkeypatchedIncompleteMethodPlan(
      self, tmp_path, monkeypatch
   ):
      original = "class Repo:\n   def Build(self):\n      return 1\n"
      f = Write(tmp_path / "main.py", original)
      target = ProjectDefinition(
         Name          = "Build",
         Kind          = "method",
         FilePath      = str(f),
         Line          = 2,
         Col           = 3,
         ScopeId       = "repo",
         ScopeName     = "Repo",
         Confidence    = "local_resolved",
         QualifiedName = "Repo.Build",
         Extra         = {"owner_class_name": "Repo"},
      )
      plan = RenameSymbolPlan(Query={}, Target=target, NewName="Make")
      plan.Edits.append(RenameSymbolEdit(str(f), 2, 7, "Build", "Make", "definition:method"))
      plan.DynamicReferences.append({
         "reason":     "dynamic",
         "file":       str(f),
         "line":       10,
         "col":        10,
         "name":       "Build",
         "kind":       "call",
         "confidence": "dynamic",
      })
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, out, err = self.RunApply(
         f, "--name", "Build", "--to", "Make", "--allow-incomplete"
      )

      assert rc == 2
      assert out == ""
      assert "--allow-incomplete cannot apply method rename plans" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyUpdatesSafeNamespacePackageCase(self, tmp_path):
      ns = tmp_path / "ns"
      model = Write(ns / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         ns / "main.py",
         Src(
            """
            from .models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      rc, out, err = self.RunApply(tmp_path, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert f"renamed {model}" in out
      assert f"renamed {main}" in out
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      main_text = main.read_text(encoding="utf-8")
      assert "from .models import AccountModel" in main_text
      assert "return AccountModel()" in main_text

   def TestApplyRejectsAmbiguousNamespacePackageByDefault(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      model = Write(first / "ns" / "models.py", "class UserModel:\n   pass\n")
      other = Write(second / "ns" / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         first / "ns" / "main.py",
         Src(
            """
            from ns.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )
      original_model = model.read_text(encoding="utf-8")
      original_other = other.read_text(encoding="utf-8")
      original_main = main.read_text(encoding="utf-8")
      symbol = f"{model}:1:0"

      rc, _out, err = self.RunApply(
         [str(first), str(second)], "--symbol", symbol, "--to", "AccountModel"
      )

      assert rc == 2
      assert "refused incomplete plan" in err
      assert model.read_text(encoding="utf-8") == original_model
      assert other.read_text(encoding="utf-8") == original_other
      assert main.read_text(encoding="utf-8") == original_main

   def TestApplyAllowIncompleteOnlyAppliesSafeAmbiguousNamespaceEdits(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      model = Write(first / "ns" / "models.py", "class UserModel:\n   pass\n")
      other = Write(second / "ns" / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         first / "ns" / "main.py",
         Src(
            """
            from ns.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )
      original_other = other.read_text(encoding="utf-8")
      original_main = main.read_text(encoding="utf-8")
      symbol = f"{model}:1:0"

      rc, out, err = self.RunApply(
         [str(first), str(second)],
         "--symbol", symbol,
         "--to", "AccountModel",
         "--allow-incomplete",
      )

      assert rc == 0
      assert err == ""
      assert f"renamed {model}" in out
      assert f"renamed {main}" not in out
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      assert other.read_text(encoding="utf-8") == original_other
      assert main.read_text(encoding="utf-8") == original_main

   def TestApplyUpdatesOneFile(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            def Build():
               return UserModel()
            """
         ),
      )

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert out == f"renamed {f}\n"
      text = f.read_text(encoding="utf-8")
      assert "class AccountModel:" in text
      assert "return AccountModel()" in text
      assert "UserModel" not in text

   def TestApplyUpdatesMultipleFiles(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      main = Write(
         pkg / "main.py",
         Src(
            """
            from pkg.utils import BuildValue

            def Run():
               return BuildValue()
            """
         ),
      )

      rc, out, err = self.RunApply(pkg, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert err == ""
      assert f"renamed {main}" in out
      assert f"renamed {utils}" in out
      assert "def MakeValue():" in utils.read_text(encoding="utf-8")
      main_text = main.read_text(encoding="utf-8")
      assert "from pkg.utils import MakeValue" in main_text
      assert "return MakeValue()" in main_text

   def TestApplyUsesImportFromBindingEdits(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(pkg / "main.py", "from pkg.models import UserModel\n")

      rc, out, err = self.RunApply(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert f"renamed {model}" in out
      assert f"renamed {main}" in out
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      assert main.read_text(encoding="utf-8") == "from pkg.models import AccountModel\n"

   def TestApplyUsesRelativeImportFromBindingEdits(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(pkg / "main.py", "from .models import UserModel\n")

      rc, out, err = self.RunApply(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert f"renamed {model}" in out
      assert f"renamed {main}" in out
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      assert main.read_text(encoding="utf-8") == "from .models import AccountModel\n"

   def TestApplyHandlesModuleAttributeEdits(self, tmp_path):
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

      rc, _, err = self.RunApply(pkg, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert err == ""
      text = main.read_text(encoding="utf-8")
      assert "import pkg.utils" in text
      assert "pkg.utils.MakeValue()" in text
      assert "pkg.MakeValue" not in text

   def TestApplyHandlesAnnotationEdits(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            def Build(user: UserModel) -> UserModel:
               return user
            """
         ),
      )

      rc, _, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      text = f.read_text(encoding="utf-8")
      assert "user: AccountModel" in text
      assert "-> AccountModel" in text

   def TestApplyNoEditsWritesNothingAndPrintsNothing(self, tmp_path, monkeypatch):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      original = f.read_text(encoding="utf-8")
      plan = RenameSymbolPlan(Query={}, Target=None, NewName="AccountModel")
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert out == ""
      assert err == ""
      assert f.read_text(encoding="utf-8") == original

   def TestApplyDoesNotPrintJson(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert out.startswith("renamed ")
      assert '"query"' not in out
      assert '"edits"' not in out

   def TestApplyRejectsDiff(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      out = StringIO()
      err = StringIO()
      with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
         rc = Main([
            "rename-symbol", str(f), "--name", "UserModel", "--to", "AccountModel",
            "--apply", "--diff",
         ])

      assert rc == 2
      assert out.getvalue() == ""
      assert "--apply cannot be combined with --diff" in err.getvalue()

   def TestApplyRejectsOutput(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      out_path = tmp_path / "plan.json"
      rc, out, err = self.RunApply(
         f, "--name", "UserModel", "--to", "AccountModel", "--output", str(out_path)
      )

      assert rc == 2
      assert out == ""
      assert "--apply cannot be combined with --output" in err
      assert not out_path.exists()

   def TestApplyRejectsPretty(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel", "--pretty")

      assert rc == 2
      assert out == ""
      assert "--apply cannot be combined with --pretty" in err

   def TestApplyTokenMismatchDoesNotPartiallyModifyFiles(self, tmp_path, monkeypatch):
      first = Write(tmp_path / "first.py", "class UserModel:\n   pass\n")
      second = Write(tmp_path / "second.py", "class UserModel:\n   pass\n")
      first_original = first.read_text(encoding="utf-8")
      second_original = second.read_text(encoding="utf-8")
      plan = RenameSymbolPlan(Query={}, Target=None, NewName="AccountModel")
      plan.Edits.append(
         RenameSymbolEdit(str(first), 1, 6, "UserModel", "AccountModel", "definition:class")
      )
      plan.Edits.append(
         RenameSymbolEdit(str(second), 1, 6, "OtherModel", "AccountModel", "definition:class")
      )

      def FailIfWriteStarts(path, text):
         raise AssertionError(f"write should not start for {path}")

      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))
      monkeypatch.setattr("customfmt.cli.WriteUtf8Lf", FailIfWriteStarts)

      rc, out, err = self.RunApply(tmp_path, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "expected 'OtherModel'" in err
      assert first.read_text(encoding="utf-8") == first_original
      assert second.read_text(encoding="utf-8") == second_original

   def TestApplyRejectsCollisionWarningAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class UserModel:
            pass

         class AccountModel:
            pass
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "warning(s)" in err
      assert "--allow-incomplete" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAllowIncompleteWithCollisionWarningEditsSafeSites(self, tmp_path):
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

      rc, _, err = self.RunApply(
         f, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 0
      assert err == ""
      assert f.read_text(encoding="utf-8").count("class AccountModel:") == 2

   def TestApplyRejectsDynamicReferenceAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class UserModel:
            pass

         def Run(obj):
            return obj.UserModel()
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "dynamic reference(s)" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAllowIncompleteWithDynamicReferenceEditsOnlySafeSites(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            def Run(obj):
               return obj.UserModel()
            """
         ),
      )

      rc, _, err = self.RunApply(
         f, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 0
      assert err == ""
      text = f.read_text(encoding="utf-8")
      assert "class AccountModel:" in text
      assert "return obj.UserModel()" in text

   def TestApplyRejectsUnresolvedReferenceAndWritesNothing(self, tmp_path, monkeypatch):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      original = f.read_text(encoding="utf-8")
      plan = RenameSymbolPlan(Query={}, Target=None, NewName="AccountModel")
      plan.Edits.append(
         RenameSymbolEdit(str(f), 1, 6, "UserModel", "AccountModel", "definition:class")
      )
      plan.UnresolvedReferences.append({
         "reason":     "unresolved",
         "file":       str(f),
         "line":       10,
         "col":        3,
         "name":       "UserModel",
         "kind":       "call",
         "confidence": "unresolved",
      })
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "unresolved reference(s)" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAllowIncompleteWithUnresolvedReferenceEditsSafeSites(
      self, tmp_path, monkeypatch
   ):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")
      plan = RenameSymbolPlan(Query={}, Target=None, NewName="AccountModel")
      plan.Edits.append(
         RenameSymbolEdit(str(f), 1, 6, "UserModel", "AccountModel", "definition:class")
      )
      plan.UnresolvedReferences.append({
         "reason":     "unresolved",
         "file":       str(f),
         "line":       10,
         "col":        3,
         "name":       "UserModel",
         "kind":       "call",
         "confidence": "unresolved",
      })
      monkeypatch.setattr("customfmt.cli.PlanRenameSymbol", lambda *args, **kwargs: (plan, []))

      rc, _, err = self.RunApply(
         f, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 0
      assert err == ""


   def TestApplyRejectsUnresolvedRelativeImportAndWritesNothing(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            '''
            from .missing import UserModel

            def Build():
               return UserModel()
            '''
         ),
      )
      model_original = model.read_text(encoding="utf-8")
      main_original = main.read_text(encoding="utf-8")

      rc, out, err = self.RunApply(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "unresolved reference(s)" in err
      assert model.read_text(encoding="utf-8") == model_original
      assert main.read_text(encoding="utf-8") == main_original

   def TestApplyAllowIncompleteWithUnresolvedRelativeImportEditsSafeSites(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            '''
            from .missing import UserModel

            def Build():
               return UserModel()
            '''
         ),
      )

      rc, _, err = self.RunApply(
         pkg, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 0
      assert err == ""
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      assert "from .missing import UserModel" in main.read_text(encoding="utf-8")
      assert "return UserModel()" in main.read_text(encoding="utf-8")

   def TestApplyResolvedRelativeImportUpdatesFiles(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            """
            from .models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      rc, out, err = self.RunApply(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      assert f"renamed {model}" in out
      assert f"renamed {main}" in out
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      main_text = main.read_text(encoding="utf-8")
      assert "from .models import AccountModel" in main_text
      assert "return AccountModel()" in main_text
      assert "UserModel" not in main_text

   def TestApplyParentRelativeModuleImportAttributeUpdatesFiles(self, tmp_path):
      pkg = Package(tmp_path)
      sub = pkg / "sub"
      Write(sub / "__init__.py", "")
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      main = Write(
         sub / "main.py",
         Src(
            '''
            from .. import utils

            def Run():
               return utils.BuildValue()
            '''
         ),
      )

      rc, out, err = self.RunApply(pkg, "--name", "BuildValue", "--to", "MakeValue")

      assert rc == 0
      assert err == ""
      assert f"renamed {utils}" in out
      assert f"renamed {main}" in out
      assert "def MakeValue():" in utils.read_text(encoding="utf-8")
      main_text = main.read_text(encoding="utf-8")
      assert "from .. import utils" in main_text
      assert "return utils.MakeValue()" in main_text

   def TestApplyRejectsWildcardImportAndWritesNothing(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main_original = Src(
         '''
         from pkg.models import *

         def Build():
            return UserModel()
         '''
      )
      main = Write(pkg / "main.py", main_original)

      rc, out, err = self.RunApply(pkg, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "unresolved reference(s)" in err
      assert main.read_text(encoding="utf-8") == main_original

   def TestApplyAllowIncompleteWithWildcardImportEditsOnlySafeSites(self, tmp_path):
      pkg = Package(tmp_path)
      model = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            '''
            from pkg.models import *

            def Build():
               return UserModel()
            '''
         ),
      )

      rc, _, err = self.RunApply(
         pkg, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 0
      assert err == ""
      assert "class AccountModel:" in model.read_text(encoding="utf-8")
      assert "return UserModel()" in main.read_text(encoding="utf-8")

   def TestApplyDoesNotEditStringsOrComments(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            '''
            class UserModel:
               pass

            MESSAGE = "UserModel"
            # UserModel stays in comments
            '''
         ),
      )

      rc, _, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 0
      assert err == ""
      text = f.read_text(encoding="utf-8")
      assert "class AccountModel:" in text
      assert 'MESSAGE = "UserModel"' in text
      assert "# UserModel stays in comments" in text

   def TestApplyRejectsSkippedReferenceAndWritesNothing(self, tmp_path):
      original = Src(
         """
         class UserModel:
            pass

         from external.pkg import UserModel
         """
      )
      f = Write(tmp_path / "main.py", original)

      rc, out, err = self.RunApply(f, "--name", "UserModel", "--to", "AccountModel")

      assert rc == 2
      assert out == ""
      assert "skipped reference(s)" in err
      assert f.read_text(encoding="utf-8") == original

   def TestApplyAllowIncompleteWithSkippedReferenceEditsOnlySafeSites(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class UserModel:
               pass

            from external.pkg import UserModel
            """
         ),
      )

      rc, _, err = self.RunApply(
         f, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 0
      assert err == ""
      text = f.read_text(encoding="utf-8")
      assert "class AccountModel:" in text
      assert "from external.pkg import UserModel" in text

   def TestAllowIncompleteWithoutApplyIsRejected(self, tmp_path):
      f = Write(tmp_path / "main.py", "class UserModel:\n   pass\n")

      rc, data, err = RunPlan(
         f, "--name", "UserModel", "--to", "AccountModel", "--allow-incomplete"
      )

      assert rc == 2
      assert data == {}
      assert "--allow-incomplete requires --apply" in err

   def TestAllowIncompleteWithoutApplyIsRejectedForMethodJsonPlan(self, tmp_path):
      f = Write(tmp_path / "main.py", "class Repo:\n   def Build(self):\n      return 1\n")

      rc, data, err = RunPlan(f, "--name", "Build", "--to", "Make", "--allow-incomplete")

      assert rc == 2
      assert data == {}
      assert "--allow-incomplete requires --apply" in err
