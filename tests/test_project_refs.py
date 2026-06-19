"""Tests for project-level read-only reference lookup."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main
from customfmt.symbols.project_graph import (
   FindRefsByName,
   FindRefsBySymbol,
   InspectProjectModules,
)

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


   def TestSameFileClassMethodRefResolves(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1

            def Run(worker):
               return Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "Build")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "local_resolved"
      assert refs[0]["resolved_to"]["kind"] == "method"
      assert refs[0]["extra"]["receiver_kind"] == "class"
      assert refs[0]["extra"]["owner_class_name"] == "Worker"
      assert refs[0]["extra"]["owner_class_qualified_name"] == "Worker"
      assert refs[0]["extra"]["method_name"] == "Build"
      assert refs[0]["extra"]["method_target"]["name"] == "Build"

   def TestImportedClassMethodRefResolves(self, tmp_path):
      pkg = Package(tmp_path)
      models = Write(
         pkg / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import Worker

            def Run(worker):
               return Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "Build")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)
      assert refs[0]["resolved_to"]["kind"] == "method"
      assert refs[0]["extra"]["receiver_kind"] == "class"
      assert refs[0]["extra"]["owner_class_name"] == "Worker"
      assert refs[0]["extra"]["method_name"] == "Build"

   def TestModuleAliasClassMethodRefResolves(self, tmp_path):
      pkg = Package(tmp_path)
      Write(
         pkg / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            import pkg.models as Models

            def Run(worker):
               return Models.Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "Build")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["kind"] == "method"
      assert refs[0]["extra"]["receiver_kind"] == "class"
      assert refs[0]["extra"]["owner_class_name"] == "Worker"

   def TestNamespaceImportedClassMethodRefResolves(self, tmp_path):
      ns = tmp_path / "ns"
      models = Write(
         ns / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         ns / "main.py",
         Src(
            """
            from ns.models import Worker

            def Run(worker):
               return Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(tmp_path)], "Build")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)
      assert refs[0]["resolved_to"]["kind"] == "method"
      assert refs[0]["extra"]["receiver_kind"] == "class"
      assert refs[0]["extra"]["owner_class_name"] == "Worker"

   def TestRelativeImportedClassMethodRefResolves(self, tmp_path):
      pkg = Package(tmp_path)
      Write(
         pkg / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            from .models import Worker

            def Run(worker):
               return Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "Build")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["kind"] == "method"
      assert refs[0]["extra"]["receiver_kind"] == "class"
      assert refs[0]["extra"]["owner_class_name"] == "Worker"


   def TestAmbiguousImportedClassMethodRemainsDynamic(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      Write(
         first / "ns" / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         second / "ns" / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 2
            """
         ),
      )
      Write(
         first / "ns" / "main.py",
         Src(
            """
            from ns.models import Worker

            def Run(worker):
               return Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(first), str(second)], "Build")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"
      assert dynamic[0]["resolved_to"] is None
      assert dynamic[0]["extra"]["full"] == "Worker.Build"

   def TestExternalImportedClassMethodRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            from external.pkg import Worker

            def Run(worker):
               return Worker.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "Build")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"
      assert dynamic[0]["resolved_to"] is None
      assert dynamic[0]["extra"]["full"] == "Worker.Build"

   def TestClassMissingMethodRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1

            def Run(worker):
               return Worker.MissingMethod(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "MissingMethod")
      data = result.ToDict()

      assert data["dynamic_references"]
      assert data["dynamic_references"][0]["confidence"] == "dynamic"
      assert data["dynamic_references"][0]["extra"]["full"] == "Worker.MissingMethod"

   def TestModuleAliasMissingClassMethodRemainsDynamic(self, tmp_path):
      pkg = Package(tmp_path)
      Write(
         pkg / "models.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            import pkg.models as Models

            def Run(worker):
               return Models.Worker.MissingMethod(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "MissingMethod")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"
      assert dynamic[0]["resolved_to"] is None
      assert dynamic[0]["extra"]["full"] == "Models.Worker.MissingMethod"

   def TestUnknownClassMethodRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            def Run(worker):
               return UnknownClass.Build(worker)
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "Build")
      data = result.ToDict()

      assert data["dynamic_references"]
      assert data["dynamic_references"][0]["confidence"] == "dynamic"
      assert data["dynamic_references"][0]["extra"]["full"] == "UnknownClass.Build"

   def TestObjMethodStillRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Worker:
               def Build(self):
                  return 1

            def Run(obj):
               return obj.Build()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "Build")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"
      assert dynamic[0]["extra"]["full"] == "obj.Build"

   def TestInstanceMethodSameFileConstructorReceiverResolves(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return 1

            def Run():
               builder = Builder()
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "local_resolved"
      assert refs[0]["resolved_to"]["kind"] == "method"
      assert refs[0]["extra"]["receiver_kind"] == "instance"
      assert refs[0]["extra"]["owner_class_name"] == "Builder"

   def TestInstanceMethodImportedConstructorReceiverResolves(self, tmp_path):
      pkg = Package(tmp_path)
      builder_file = Write(
         pkg / "builder.py",
         Src(
            """
            class Builder:
               def where(self):
                  return 1
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.builder import Builder

            def Run():
               builder = Builder()
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "where")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(builder_file)
      assert refs[0]["extra"]["receiver_kind"] == "instance"

   def TestInstanceMethodAnnotatedReceiverResolves(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return 1

            def Run():
               builder: Builder
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "local_resolved"
      assert refs[0]["extra"]["receiver_kind"] == "instance"

   def TestInstanceMethodReassignedReceiverRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return 1

            class Other:
               def where(self):
                  return 2

            def Run():
               builder = Builder()
               builder = Other()
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"

   def TestInstanceMethodUnknownReceiverRemainsDynamic(self, tmp_path):
      f = Write(tmp_path / "main.py", "def Run(builder):\n   return builder.where()\n")

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()

      assert data["dynamic_references"]
      assert data["dynamic_references"][0]["extra"]["full"] == "builder.where"

   def TestInstanceMethodGetattrStringRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return 1

            def Run():
               builder = Builder()
               return getattr(builder, "where")()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["extra"].get("dynamic_reason") == "getattr_string"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"

   def TestInstanceMethodInheritedMethodRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Base:
               def where(self):
                  return 1

            class Builder(Base):
               pass

            def Run():
               builder = Builder()
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]

      assert dynamic
      assert dynamic[0]["confidence"] == "dynamic"

   def TestInstanceMethodExternalImportRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            from external.builder import Builder

            def Run():
               builder = Builder()
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()

      assert data["dynamic_references"]
      assert data["dynamic_references"][0]["confidence"] == "dynamic"

   def TestStatementBuilderInstanceSmokeResolvesReadOnly(self, tmp_path):
      f = Write(
         tmp_path / "statement_builder.py",
         Src(
            """
            class StatementBuilder:
               def where(self, condition):
                  return self

            def Compose(condition):
               statement_builder = StatementBuilder()
               return statement_builder.where(condition)
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "local_resolved"
      assert refs[0]["extra"]["owner_class_name"] == "StatementBuilder"


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

   def TestSameFileSymbolReferenceLookup(self, tmp_path):
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
      symbol = f"{f}:6:10"

      result, _ = FindRefsBySymbol([str(f)], symbol)
      data = result.ToDict()

      assert data["query"]["symbol"] == symbol
      assert data["definitions"][0]["name"] == "Build"
      assert data["references"][0]["resolved_to"]["name"] == "Build"

   def TestImportFromClassAliasResolvesToTargetClass(self, tmp_path):
      pkg = Package(tmp_path)
      models = Write(pkg / "models.py", "class UserModel:\n   pass\n")
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

      result, _ = FindRefsByName([str(pkg)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "Model"]

      assert any(d["file"] == str(models) for d in data["definitions"])
      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["name"] == "UserModel"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestImportModuleAttributeRefs(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
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

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "BuildValue"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(utils)

   def TestImportModuleAttributeDoesNotGuessWrongPrefix(self, tmp_path):
      pkg = Package(tmp_path)
      Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         pkg / "main.py",
         Src(
            """
            import pkg.utils

            def Run(pkg):
               return pkg.BuildValue()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()

      assert data["dynamic_references"][0]["confidence"] == "dynamic"
      assert data["dynamic_references"][0]["extra"]["full"] == "pkg.BuildValue"

   def TestSymbolLookupOnImportFromIncludesTargetDefinition(self, tmp_path):
      pkg = Package(tmp_path)
      models = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      main = Write(
         pkg / "main.py",
         Src(
            """
            from pkg.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )
      symbol = f"{main}:2:0"

      result, _ = FindRefsBySymbol([str(pkg)], symbol)
      data = result.ToDict()
      definition_files = {d["file"] for d in data["definitions"]}

      assert str(main) in definition_files
      assert str(models) in definition_files
      assert any(r["resolved_to"]["file"] == str(models) for r in data["references"])

   def TestSamePackageRelativeImportResolves(self, tmp_path):
      pkg = Package(tmp_path)
      models = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         pkg / "main.py",
         Src(
            """
            from .models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestParentPackageRelativeImportResolves(self, tmp_path):
      pkg = Package(tmp_path)
      sub = pkg / "sub"
      Write(sub / "__init__.py", "")
      models = Write(pkg / "models.py", "class UserModel:\n   pass\n")
      Write(
         sub / "main.py",
         Src(
            """
            from ..models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestRelativeImportModuleAttributeResolves(self, tmp_path):
      pkg = Package(tmp_path)
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
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

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "BuildValue"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(utils)

   def TestParentRelativeImportModuleAttributeResolves(self, tmp_path):
      pkg = Package(tmp_path)
      sub = pkg / "sub"
      Write(sub / "__init__.py", "")
      utils = Write(pkg / "utils.py", "def BuildValue():\n   return 1\n")
      Write(
         sub / "main.py",
         Src(
            """
            from .. import utils

            def Run():
               return utils.BuildValue()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "BuildValue")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "BuildValue"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(utils)


   def TestNamespacePackageAbsoluteImportResolves(self, tmp_path):
      ns = tmp_path / "ns"
      models = Write(ns / "models.py", "class UserModel:\n   pass\n")
      Write(
         ns / "main.py",
         Src(
            """
            from ns.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(tmp_path)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestNamespacePackageRelativeImportResolves(self, tmp_path):
      ns = tmp_path / "ns"
      models = Write(ns / "models.py", "class UserModel:\n   pass\n")
      Write(
         ns / "main.py",
         Src(
            """
            from .models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(tmp_path)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestNestedNamespacePackageParentRelativeImportResolves(self, tmp_path):
      ns = tmp_path / "ns"
      models = Write(ns / "models.py", "class UserModel:\n   pass\n")
      Write(
         ns / "sub" / "main.py",
         Src(
            """
            from ..models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(tmp_path)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(models)

   def TestAmbiguousNamespaceModuleRemainsUnresolved(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      Write(first / "ns" / "models.py", "class UserModel:\n   pass\n")
      Write(second / "ns" / "models.py", "class UserModel:\n   pass\n")
      Write(
         first / "ns" / "main.py",
         Src(
            """
            from ns.models import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(first), str(second)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "unresolved"
      assert refs[0]["extra"]["import_target"]["reason"] == "module_ambiguous"

   def TestUnresolvedRelativeImportStaysUnresolved(self, tmp_path):
      pkg = Package(tmp_path)
      Write(
         pkg / "main.py",
         Src(
            """
            from .missing import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "unresolved"
      assert refs[0]["extra"]["import_target"]["reason"] == "module_not_found"

   def TestMissingRelativeImportWithOverlappingScanRootsIsNotAmbiguous(
      self, tmp_path
   ):
      ns = tmp_path / "ns"
      Write(
         ns / "main.py",
         Src(
            """
            from .missing import UserModel

            def Build():
               return UserModel()
            """
         ),
      )

      result, _ = FindRefsByName([str(tmp_path), str(ns)], "UserModel")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["name"] == "UserModel"]

      assert refs[0]["confidence"] == "unresolved"
      assert refs[0]["extra"]["import_target"]["reason"] == "module_not_found"


   def TestInspectProjectModulesReportsAmbiguity(self, tmp_path):
      first = tmp_path / "first"
      second = tmp_path / "second"
      first_model = Write(first / "ns" / "models.py", "class UserModel:\n   pass\n")
      second_model = Write(second / "ns" / "models.py", "class UserModel:\n   pass\n")

      result = InspectProjectModules([str(first), str(second)])

      assert "ns.models" in result["modules"]
      module_paths = {
         str(Path(p).resolve()) for p in result["modules"]["ns.models"]
      }
      assert module_paths == {
         str(first_model.resolve()),
         str(second_model.resolve()),
      }
      assert "ns.models" in result["ambiguous_modules"]
      scan_roots = {str(Path(p).resolve()) for p in result["scan_roots"]}
      assert scan_roots == {str(first.resolve()), str(second.resolve())}
      assert result["errors"] == []

   def TestPrettyOutputIsIndentedJson(self, tmp_path, capsys):
      f = Write(tmp_path / "main.py", "def Build():\n   return 1\n")

      rc = Main(["refs", str(f), "--name", "Build", "--pretty"])
      out = capsys.readouterr().out

      assert rc == 0
      assert '\n  "query": {' in out
      assert json.loads(out)["query"]["name"] == "Build"

   def TestInvalidSymbolReturnsExitTwo(self, tmp_path, capsys):
      f = Write(tmp_path / "main.py", "def Build():\n   return 1\n")

      rc = Main(["refs", str(f), "--symbol", "not-a-symbol"])
      err = capsys.readouterr().err

      assert rc == 2
      assert "symbol must use PATH:LINE:COL" in err

   def TestNoPythonFilesReturnsExitTwo(self, tmp_path, capsys):
      rc = Main(["refs", str(tmp_path), "--name", "Build"])
      err = capsys.readouterr().err

      assert rc == 2
      assert "no Python files found" in err

class TestHelperParameterReceiverInference:
   def TestSameFileHelperParameterReceiverResolvesReadOnly(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            def Run():
               builder = Builder()
               Helper(builder)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "local_resolved"
      assert refs[0]["extra"]["receiver_kind"] == "instance"
      assert refs[0]["extra"]["owner_class_name"] == "Builder"

   def TestImportedHelperParameterReceiverResolvesReadOnly(self, tmp_path):
      pkg = Package(tmp_path)
      Write(
         pkg / "helpers.py",
         Src(
            """
            def Helper(builder):
               return builder.where()
            """
         ),
      )
      builder_file = Write(
         pkg / "builder.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self
            """
         ),
      )
      Write(
         pkg / "main.py",
         Src(
            """
            from pkg.builder import Builder
            from pkg.helpers import Helper

            def Run():
               builder = Builder()
               Helper(builder)
            """
         ),
      )

      result, _ = FindRefsByName([str(pkg)], "where")
      data = result.ToDict()
      refs = [r for r in data["references"] if r["kind"] == "attribute_call"]

      assert refs
      assert refs[0]["confidence"] == "import_resolved"
      assert refs[0]["resolved_to"]["file"] == str(builder_file)

   def TestMultipleSameTypeHelperCallsResolve(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            def Run():
               builder1 = Builder()
               builder2 = Builder()
               Helper(builder1)
               Helper(builder2)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert [r for r in data["references"] if r["kind"] == "attribute_call"]

   def TestConflictingHelperArgumentTypesBlockResolution(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            class Other:
               def where(self):
                  return self

            def Run():
               builder = Builder()
               other = Other()
               Helper(builder)
               Helper(other)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      dynamic = [r for r in data["dynamic_references"] if r["kind"] == "attribute_call"]
      assert dynamic

   def TestUnknownHelperArgumentTypeBlocksResolution(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            def Run(builder):
               Helper(builder)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert data["dynamic_references"]

   def TestDynamicHelperCalleeBlocksResolution(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            def Run(fn):
               builder = Builder()
               fn(builder)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert data["dynamic_references"]

   def TestStarArgsHelperCallBlocksResolution(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            def Run(args):
               Helper(*args)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert data["dynamic_references"]

   def TestKwargsHelperCallBlocksResolution(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Builder:
               def where(self):
                  return self

            def Run(kwargs):
               Helper(**kwargs)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert data["dynamic_references"]

   def TestInheritedHelperParameterMethodRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            class Base:
               def where(self):
                  return self

            class Builder(Base):
               pass

            def Run():
               builder = Builder()
               Helper(builder)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert data["dynamic_references"]

   def TestExternalHelperParameterClassRemainsDynamic(self, tmp_path):
      f = Write(
         tmp_path / "main.py",
         Src(
            """
            from external.builder import Builder

            def Run():
               builder = Builder()
               Helper(builder)

            def Helper(builder):
               return builder.where()
            """
         ),
      )

      result, _ = FindRefsByName([str(f)], "where")
      data = result.ToDict()
      assert data["dynamic_references"]

   def TestStatementComposerHelperParameterSmoke(self, tmp_path):
      f = Write(
         tmp_path / "statement_composer.py",
         Src(
            """
            class StatementBuilder:
               def where(self, value):
                  return self
               def include(self, value):
                  return self
               def orderBy(self, value):
                  return self
               def select(self, value):
                  return self

            def ComposeStatement(repo, conditions):
               statement_builder = StatementBuilder()
               __BuildConditions(statement_builder, repo, conditions)
               __ChainConditions(statement_builder, repo, conditions)
               __AddSelectsFromTargetTable(statement_builder, repo)
               __AddJoinedTables(statement_builder, repo)
               return statement_builder

            def __BuildConditions(statement_builder, repo, conditions):
               statement_builder.where(conditions[0].field)
               repo.tableName

            def __ChainConditions(statement_builder, repo, conditions):
               statement_builder.orderBy(repo.pk)
               conditions[0].model

            def __AddSelectsFromTargetTable(statement_builder, repo):
               statement_builder.select(repo.model)

            def __AddJoinedTables(statement_builder, repo):
               statement_builder.include(repo.references)
            """
         ),
      )

      for name in ["where", "include", "orderBy", "select"]:
         result, _ = FindRefsByName([str(f)], name)
         data = result.ToDict()
         refs = [r for r in data["references"] if r["kind"] == "attribute_call"]
         assert refs
         assert refs[0]["confidence"] == "local_resolved"
         assert refs[0]["extra"]["owner_class_name"] == "StatementBuilder"

      for name in ["tableName", "pk", "model", "references", "field"]:
         result, _ = FindRefsByName([str(f)], name)
         data = result.ToDict()
         assert not data["references"]
