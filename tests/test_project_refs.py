"""Tests for project-level read-only reference lookup."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main
from customfmt.symbols.project_graph import FindRefsByName, FindRefsBySymbol

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


def RefNames(data: dict) -> list[str]:
   return [r["name"] for r in data["references"]]


# ---------------------------------------------------------------------------
# Project refs
# ---------------------------------------------------------------------------


class TestProjectRefs:
   def TestSameFileRefs(self, tmp_path):
      src = Src(
         """
         def Build():
            return 1

         def Use():
            return Build()
         """
      )
      f = Write(tmp_path / "same_file.py", src)

      result, errors = FindRefsByName([str(f)], "Build")
      data = result.ToDict()

      assert errors == []
      assert data["summary"]["definitions"] == 1
      assert data["references"][0]["confidence"] == "local_resolved"
      assert data["references"][0]["resolved_to"]["name"] == "Build"

   def TestImportedClassRefs(self, tmp_path):
      pkg = Package(tmp_path)
      models = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      use = Write(
         pkg / "use_models.py",
         Src(
            """
            from pkg.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["file"] == str(use)]

      assert any(d["file"] == str(models) for d in data["definitions"])
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestImportedFunctionRefs(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
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

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()
      imported = [
         r for r in data["references"]
         if r["confidence"] == "import_resolved"
      ]

      assert imported
      assert imported[0]["resolved_to"]["file"] == str(utils)

   def TestAliasImports(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.utils import BuildValue as MakeValue

            def Run():
               return MakeValue()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "MakeValue"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(utils)
      assert refs[0]["resolved_to"]["name"] == "BuildValue"


   def TestModuleAliasAttributeRefs(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         pkg / "main.py",
         Src(
            """
            import pkg.utils as Utils

            def Run():
               return Utils.BuildValue()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "BuildValue"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(utils)

   def TestUnresolvedExternalImports(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            from external.pkg import MissingThing

            def Run():
               return MissingThing()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "MissingThing")
      data = result.ToDict()

      assert data["references"][0]["confidence"] == "unresolved"
      assert data["unresolved_references"][0]["name"] == "MissingThing"

   def TestDynamicAttributeCallsSkipped(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            def Run(obj):
               return obj.BuildValue()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "BuildValue")
      data = result.ToDict()

      assert data["dynamic_references"][0]["confidence"] == "dynamic"
      assert data["dynamic_references"][0]["extra"]["full"] == "obj.BuildValue"

   def TestJsonOutputShape(self, tmp_path, capsys):
      f = Write(tmp_path / "main.py", "def Build():\n   return 1\n")

      rc = Main(["refs", str(f), "--name", "Build", "--pretty"])
      out = capsys.readouterr().out
      data = json.loads(out)

      assert rc == 0
      assert sorted(data.keys()) == [
         "definitions",
         "dynamic_references",
         "errors",
         "query",
         "references",
         "summary",
         "unresolved_references",
      ]
      assert data["query"] == {"type": "name", "name": "Build"}

   def TestOutputFile(self, tmp_path):
      f = Write(tmp_path / "main.py", "def Build():\n   return 1\n")
      out_path = tmp_path / "refs.json"

      rc = Main([
         "refs", str(f), "--name", "Build", "--output", str(out_path),
      ])
      data = json.loads(out_path.read_text(encoding="utf-8"))

      assert rc == 0
      assert data["query"]["name"] == "Build"

   def TestSymbolLookup(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            def Build():
               return 1

            def Run():
               return Build()
            """
         ),
      )
      symbol = f"{f}:2:0"

      result, _ = FindRefsBySymbol([str(f)], symbol)
      data = result.ToDict()

      assert data["query"]["symbol"] == symbol
      assert RefNames(data) == ["Build"]
