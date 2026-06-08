"""
Tests for customfmt.symbols.resolver (hardened version).

New in this version:
  TestExceptAlias — except-as with global/nonlocal
  TestAugAssignReadWrite — augmented assignment read+write

TestScopeIds
   TestDeterministicScopeIds
   TestScopeIdsStableAcrossRuns
   TestModuleScopeIdContainsFileHash
   TestFunctionScopeIdContainsQualName

TestGlobalNonlocal
   TestGlobalDeclarationRecorded
   TestNonlocalDeclarationRecorded
   TestGlobalWriteResolvesToModuleScope
   TestGlobalReadResolvesToModuleScope
   TestNonlocalReadResolvesToOuterFunction
   TestNonlocalWriteRecordedInNonlocalScope
   TestGlobalUnresolvedWhenNotAtModuleLevel

TestGlobalNonlocalWrites
   TestGlobalAssignNoLocalDef
   TestGlobalWriteRefResolvesToModuleCounter
   TestGlobalReadRefResolvesToModuleCounter
   TestNonlocalAssignNoLocalDef
   TestNonlocalWriteRefResolvesToOuterTotal
   TestNonlocalReadRefResolvesToOuterTotal
   TestNormalLocalAssignStillCreatesLocalWrite
   TestWriteRefKindInToDict

TestClassBases
   TestBaseClassReferenceRecorded
   TestBaseClassResolvesWhenImported
   TestBaseClassUnresolvedWhenCrossFile
   TestMetaclassKeywordReferenceRecorded
   TestMultipleBasesAllRecorded

TestDecorators
   TestBareDecoratorRecorded
   TestDecoratorCallRecorded
   TestDecoratorCallWithArgRecorded
   TestMethodDecoratorRecorded
   TestClassDecoratorRecorded
   TestDecoratorRecordedInOuterScope

TestAnnotations
   TestParameterAnnotationRecorded
   TestReturnAnnotationRecorded
   TestAnnAssignAnnotationRecorded
   TestClassBodyAnnotationRecorded
   TestGenericAnnotationNamesRecorded
   TestOptionalAnnotationRecorded
   TestAnnotationKindIsAnnotation

TestResolverExisting
   TestLocalVariableResolvesToLocalAssignment
   TestParameterResolvesToParameter
   TestLocalShadowsImport
   TestLocalShadowsModuleVariable
   TestFunctionCallResolvesToLocalFunctionDef
   TestClassConstructorResolvesToClassDef
   TestImportedNameResolvesToImportEntry
   TestImportFromResolvesToImportEntry
   TestUnresolvedNameMarkedUnresolved
   TestNestedFunctionScopeResolvesCorrectly
   TestOuterVariableVisibleInInnerFunction
   TestMethodScopeResolvesSelfParameter
   TestSelfXNotResolved
   TestAttrCallMarkedDynamic

TestCLI
   TestResolveSubcommandOutputIsJson
   TestResolveIndexAliasWorks
   TestResolvePrettyWorks
   TestResolveOutputFileWorks
   TestResolveSyntaxErrorInErrors
   TestResolveInvalidUtf8InErrors
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main, MainResolve
from customfmt.symbols.resolver import ResolveFile, ResolveResult
from customfmt.symbols.scopes import DefKind, RefKind, ScopeKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Src(text: str) -> str:
   return textwrap.dedent(text)


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def WriteBytes(path: Path, data: bytes) -> Path:
   path.write_bytes(data)
   return path


def RunMain(*args: str) -> int:
   return Main(list(args))


def RunResolve(*args: str) -> int:
   return MainResolve(list(args))


def Defs(result, name: str):
   return [d for d in result.Definitions if d.Name == name]


def Refs(result, name: str):
   return [r for r in result.References if r.Name == name]


def ResolvedRefs(result, name: str):
   return [
      r for r in result.References
      if r.Name == name and r.ResolvedTo is not None
   ]


def UnresolvedRefs(result, name: str):
   return [
      r for r in result.References
      if r.Name == name and r.IsUnresolved
   ]


def WriteRefs(result, name: str):
   return [
      r for r in result.References
      if r.Name == name and r.Kind == RefKind.Write
   ]


def AnnRefs(result, name: str):
   return [
      r for r in result.References
      if r.Name == name and r.Kind == RefKind.Annotation
   ]


class TestMethodOwnerMetadata:
   def TestMethodDefinitionHasOwnerMetadata(self, tmp_path):
      src = Src("""\
         class Repo:
            def GetByID(self):
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      method = next(d for d in Defs(result, "GetByID") if d.Kind == DefKind.MethodDef)
      assert method.Extra["owner_class_name"] == "Repo"
      assert method.Extra["owner_class_qualified_name"] == "Repo"
      assert method.Extra["owner_class_file"] == str(f)
      assert method.Extra["owner_class_line"] == 1
      assert method.Extra["owner_class_col"] == 0
      assert method.Extra["method_name"] == "GetByID"
      assert method.Extra["is_async"] is False

   def TestAsyncMethodDefinitionHasOwnerMetadata(self, tmp_path):
      src = Src("""\
         class Repo:
            async def Fetch(self):
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      method = next(d for d in Defs(result, "Fetch") if d.Kind == DefKind.MethodDef)
      assert method.Extra["owner_class_name"] == "Repo"
      assert method.Extra["method_name"] == "Fetch"
      assert method.Extra["is_async"] is True

   def TestNestedFunctionInsideMethodHasNoOwnerMetadata(self, tmp_path):
      src = Src("""\
         class Repo:
            def Outer(self):
               def Inner():
                  pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner = next(d for d in Defs(result, "Inner") if d.Kind == DefKind.FunctionDef)
      assert "owner_class_name" not in inner.Extra

   def TestSameMethodNameDifferentOwnerMetadata(self, tmp_path):
      src = Src("""\
         class RepoA:
            def Render(self):
               pass
         class RepoB:
            def Render(self):
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      methods = [d for d in Defs(result, "Render") if d.Kind == DefKind.MethodDef]
      owners = {m.Extra["owner_class_qualified_name"] for m in methods}
      assert owners == {"RepoA", "RepoB"}


# ---------------------------------------------------------------------------
# TestScopeIds
# ---------------------------------------------------------------------------


class TestScopeIds:
   def TestDeterministicScopeIds(self, tmp_path):
      """Same file resolved twice must produce identical scope IDs."""
      f = Write(tmp_path / "f.py", "def Foo():\n   pass\n")
      result_a = ResolveFile(f)
      result_b = ResolveFile(f)
      ids_a = {s.ScopeId for s in result_a.Tree.AllScopes}
      ids_b = {s.ScopeId for s in result_b.Tree.AllScopes}
      assert ids_a == ids_b

   def TestScopeIdsStableAcrossRuns(self, tmp_path):
      """Scope IDs must not contain process-specific data (e.g. object id)."""
      f = Write(tmp_path / "f.py", "def Bar():\n   pass\n")
      result = ResolveFile(f)
      for scope in result.Tree.AllScopes:
         # IDs must not look like Python object addresses (no 0x...)
         assert "0x" not in scope.ScopeId

   def TestModuleScopeIdContainsFileHash(self, tmp_path):
      """Module scope ID must embed a hash of the file path."""
      f = Write(tmp_path / "my_module.py", "X = 1\n")
      result = ResolveFile(f)
      root_id = result.Tree.Root.ScopeId
      # Format: <8-char hash>:module:<line>
      parts = root_id.split(":")
      assert len(parts) == 3
      assert len(parts[0]) == 8   # 8-char hex hash
      assert parts[1] == "module"
      assert parts[2] == "1"

   def TestFunctionScopeIdContainsQualName(self, tmp_path):
      """Function scope ID must embed the qualified name."""
      f = Write(tmp_path / "f.py", "def Foo():\n   pass\n")
      result = ResolveFile(f)
      foo_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Foo"
      )
      assert "Foo" in foo_scope.ScopeId

   def TestNestedScopeIdContainsDottedPath(self, tmp_path):
      f = Write(tmp_path / "f.py", "class A:\n   def Foo(self):\n      pass\n")
      result = ResolveFile(f)
      foo_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Foo"
      )
      assert "A.Foo" in foo_scope.ScopeId


# ---------------------------------------------------------------------------
# TestGlobalNonlocal
# ---------------------------------------------------------------------------


class TestGlobalNonlocal:
   def TestGlobalDeclarationRecorded(self, tmp_path):
      src = Src("""\
         Counter = 0
         def Increment():
            global Counter
            Counter = Counter + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Increment"
      )
      assert "Counter" in fn_scope.GlobalNames

   def TestNonlocalDeclarationRecorded(self, tmp_path):
      src = Src("""\
         def Outer():
            x = 0
            def Inner():
               nonlocal x
               x = x + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Inner"
      )
      assert "x" in inner_scope.NonlocalNames

   def TestGlobalWriteResolvesToModuleScope(self, tmp_path):
      """A write to a global name inside a function must resolve to module."""
      src = Src("""\
         Counter = 0
         def Increment():
            global Counter
            Counter = Counter + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      # The read of Counter inside Increment must resolve to module-level def
      reads = [
         r for r in ResolvedRefs(result, "Counter")
         if r.ScopeRef.Kind == ScopeKind.Function
      ]
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestGlobalReadResolvesToModuleScope(self, tmp_path):
      src = Src("""\
         Config = "default"
         def GetConfig():
            global Config
            return Config
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = [
         r for r in ResolvedRefs(result, "Config")
         if r.ScopeRef.Kind == ScopeKind.Function
      ]
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestNonlocalReadResolvesToOuterFunction(self, tmp_path):
      src = Src("""\
         def Outer():
            count = 0
            def Inner():
               nonlocal count
               return count
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner_reads = [
         r for r in ResolvedRefs(result, "count")
         if r.ScopeRef.Name == "Inner"
      ]
      assert inner_reads
      assert inner_reads[0].ResolvedTo.Kind == DefKind.LocalWrite
      assert inner_reads[0].ResolvedTo.ScopeRef.Name == "Outer"

   def TestNonlocalWriteRecordedInNonlocalScope(self, tmp_path):
      """After nonlocal x, a write to x in Inner resolves to Outer's def."""
      src = Src("""\
         def Outer():
            total = 0
            def Inner():
               nonlocal total
               total = total + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      # total read inside Inner resolves to Outer's definition
      inner_reads = [
         r for r in ResolvedRefs(result, "total")
         if r.ScopeRef.Name == "Inner"
      ]
      assert inner_reads
      assert inner_reads[0].ResolvedTo.ScopeRef.Name == "Outer"

   def TestGlobalUnresolvedWhenNotAtModuleLevel(self, tmp_path):
      """global x where x is not at module level -> unresolved."""
      src = Src("""\
         def Foo():
            global missing_var
            return missing_var
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      unresolved = UnresolvedRefs(result, "missing_var")
      assert unresolved


# ---------------------------------------------------------------------------
# TestGlobalNonlocalWrites
# ---------------------------------------------------------------------------


class TestGlobalNonlocalWrites:
   def TestGlobalAssignNoLocalDef(self, tmp_path):
      """global Counter; Counter = ... must NOT create a LocalWrite in Increment."""
      src = Src("""\
         Counter = 0
         def Increment():
            global Counter
            Counter = Counter + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Increment"
      )
      # Counter must NOT appear as a LocalWrite definition inside Increment
      local_counter = [
         d for d in result.Definitions
         if d.Name == "Counter" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is fn_scope
      ]
      assert not local_counter, "global Counter must not create LocalWrite in Increment"

   def TestGlobalWriteRefResolvesToModuleCounter(self, tmp_path):
      """Write reference for global Counter resolves to module-level Counter."""
      src = Src("""\
         Counter = 0
         def Increment():
            global Counter
            Counter = Counter + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      write_refs = WriteRefs(result, "Counter")
      assert write_refs, "expected a write reference for Counter"
      assert write_refs[0].ResolvedTo is not None
      assert write_refs[0].ResolvedTo.Kind == DefKind.ModuleDecl
      assert write_refs[0].ResolvedTo.ScopeRef.Kind == ScopeKind.Module

   def TestGlobalReadRefResolvesToModuleCounter(self, tmp_path):
      """Read reference for global Counter (RHS) resolves to module Counter."""
      src = Src("""\
         Counter = 0
         def Increment():
            global Counter
            Counter = Counter + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = [
         r for r in ResolvedRefs(result, "Counter")
         if r.ScopeRef.Kind == ScopeKind.Function
      ]
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestNonlocalAssignNoLocalDef(self, tmp_path):
      """nonlocal Total; Total = ... must NOT create a LocalWrite in Inner."""
      src = Src("""\
         def Outer():
            total = 0
            def Inner():
               nonlocal total
               total = total + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Inner"
      )
      local_total = [
         d for d in result.Definitions
         if d.Name == "total" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is inner_scope
      ]
      assert not local_total, "nonlocal total must not create LocalWrite in Inner"

   def TestNonlocalWriteRefResolvesToOuterTotal(self, tmp_path):
      """Write reference for nonlocal Total resolves to Outer.Total."""
      src = Src("""\
         def Outer():
            total = 0
            def Inner():
               nonlocal total
               total = total + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      write_refs = WriteRefs(result, "total")
      assert write_refs, "expected a write reference for total"
      assert write_refs[0].ResolvedTo is not None
      assert write_refs[0].ResolvedTo.ScopeRef.Name == "Outer"

   def TestNonlocalReadRefResolvesToOuterTotal(self, tmp_path):
      """Read reference for nonlocal Total (RHS) resolves to Outer.Total."""
      src = Src("""\
         def Outer():
            total = 0
            def Inner():
               nonlocal total
               total = total + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner_reads = [
         r for r in ResolvedRefs(result, "total")
         if r.ScopeRef.Name == "Inner"
      ]
      assert inner_reads
      assert inner_reads[0].ResolvedTo.ScopeRef.Name == "Outer"

   def TestNormalLocalAssignStillCreatesLocalWrite(self, tmp_path):
      """A plain assignment (no global/nonlocal) must still create a LocalWrite."""
      src = Src("""\
         def Foo():
            result = 1
            return result
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(s for s in result.Tree.AllScopes if s.Name == "Foo")
      local_result = [
         d for d in result.Definitions
         if d.Name == "result" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is fn_scope
      ]
      assert local_result, "normal local assignment must create LocalWrite"

   def TestWriteRefKindInToDict(self, tmp_path):
      """RefKind.Write must serialize as 'write' in JSON output."""
      src = Src("""\
         Counter = 0
         def Increment():
            global Counter
            Counter = Counter + 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      ref_dicts = [r.ToDict() for r in WriteRefs(result, "Counter")]
      assert ref_dicts
      assert ref_dicts[0]["kind"] == "write"


# ---------------------------------------------------------------------------
# TestClassBases
# ---------------------------------------------------------------------------


class TestClassBases:
   def TestBaseClassReferenceRecorded(self, tmp_path):
      src = Src("""\
         class Child(Parent):
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = Refs(result, "Parent")
      assert reads

   def TestBaseClassResolvesWhenImported(self, tmp_path):
      src = Src("""\
         from models import BaseModel
         class UserModel(BaseModel):
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "BaseModel")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestBaseClassUnresolvedWhenCrossFile(self, tmp_path):
      src = Src("""\
         class Child(SomeExternalBase):
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      unresolved = UnresolvedRefs(result, "SomeExternalBase")
      assert unresolved

   def TestMetaclassKeywordReferenceRecorded(self, tmp_path):
      src = Src("""\
         from meta import AllOptional
         class Model(metaclass=AllOptional):
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "AllOptional")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestMultipleBasesAllRecorded(self, tmp_path):
      src = Src("""\
         from meta import AllOptional
         from base import BaseModelExtension
         class Model(BaseModelExtension, metaclass=AllOptional):
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      assert ResolvedRefs(result, "BaseModelExtension")
      assert ResolvedRefs(result, "AllOptional")


# ---------------------------------------------------------------------------
# TestDecorators
# ---------------------------------------------------------------------------


class TestDecorators:
   def TestBareDecoratorRecorded(self, tmp_path):
      src = Src("""\
         from functools import wraps
         @wraps
         def Foo():
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "wraps")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestDecoratorCallRecorded(self, tmp_path):
      src = Src("""\
         from flask import route
         @route("/")
         def Index():
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      calls = [r for r in Refs(result, "route") if r.Kind == RefKind.Call]
      assert calls
      assert calls[0].ResolvedTo is not None

   def TestDecoratorCallWithArgRecorded(self, tmp_path):
      src = Src("""\
         from app import Route
         @Route("/users", methods=["GET"])
         def GetUsers():
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      calls = [r for r in Refs(result, "Route") if r.Kind == RefKind.Call]
      assert calls

   def TestMethodDecoratorRecorded(self, tmp_path):
      src = Src("""\
         class MyClass:
            @staticmethod
            def Helper():
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      assert Refs(result, "staticmethod")

   def TestClassDecoratorRecorded(self, tmp_path):
      src = Src("""\
         from dataclasses import dataclass
         @dataclass
         class Point:
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "dataclass")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestDecoratorRecordedInOuterScope(self, tmp_path):
      """Decorator refs must be recorded in the scope that contains the def."""
      src = Src("""\
         from app import login_required
         class View:
            @login_required
            def GetPage(self):
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "login_required")
      assert resolved
      # login_required should be resolved in the class scope (outer to method)
      assert resolved[0].ResolvedTo.Kind == DefKind.ImportFrom


# ---------------------------------------------------------------------------
# TestAnnotations
# ---------------------------------------------------------------------------


class TestAnnotations:
   def TestParameterAnnotationRecorded(self, tmp_path):
      src = Src("""\
         from decimal import Decimal
         def CalcTotal(amount: Decimal) -> Decimal:
            return amount
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      ann_refs = AnnRefs(result, "Decimal")
      assert ann_refs
      # Both the param annotation and return annotation should appear
      assert len(ann_refs) >= 2
      # All annotation refs should resolve to the import
      for ref in ann_refs:
         assert ref.ResolvedTo is not None
         assert ref.ResolvedTo.Kind == DefKind.ImportFrom

   def TestReturnAnnotationRecorded(self, tmp_path):
      src = Src("""\
         from models import UserModel
         def GetUser(user_id: int) -> UserModel:
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      ann_refs = AnnRefs(result, "UserModel")
      assert ann_refs
      assert ann_refs[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestAnnAssignAnnotationRecorded(self, tmp_path):
      src = Src("""\
         from decimal import Decimal
         def Foo():
            price: Decimal = Decimal("0")
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      ann_refs = AnnRefs(result, "Decimal")
      assert ann_refs

   def TestClassBodyAnnotationRecorded(self, tmp_path):
      src = Src("""\
         from models import ArtikelModel
         class Repo:
            Model: ArtikelModel
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      ann_refs = AnnRefs(result, "ArtikelModel")
      assert ann_refs
      assert ann_refs[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestGenericAnnotationNamesRecorded(self, tmp_path):
      """list[UserModel] must record both 'list' and 'UserModel'."""
      src = Src("""\
         from models import UserModel
         def GetAll() -> list[UserModel]:
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      user_ann = AnnRefs(result, "UserModel")
      assert user_ann
      list_ann = AnnRefs(result, "list")
      assert list_ann

   def TestOptionalAnnotationRecorded(self, tmp_path):
      """Optional[UserModel] must record both 'Optional' and 'UserModel'."""
      src = Src("""\
         from typing import Optional
         from models import UserModel
         def MaybeGet() -> Optional[UserModel]:
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      assert AnnRefs(result, "Optional")
      assert AnnRefs(result, "UserModel")

   def TestAnnotationKindIsAnnotation(self, tmp_path):
      """Annotation references must have RefKind.Annotation, not Read."""
      src = Src("""\
         from decimal import Decimal
         def Foo(x: Decimal) -> Decimal:
            pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      ann_refs = [
         r for r in Refs(result, "Decimal")
         if r.Kind == RefKind.Annotation
      ]
      read_refs = [
         r for r in Refs(result, "Decimal")
         if r.Kind == RefKind.Read
      ]
      assert ann_refs
      assert not read_refs


# ---------------------------------------------------------------------------
# TestResolverExisting — regression suite for original resolution tests
# ---------------------------------------------------------------------------


class TestResolverExisting:
   def TestLocalVariableResolvesToLocalAssignment(self, tmp_path):
      src = "def Foo():\n   result = 1\n   return result\n"
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "result")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestParameterResolvesToParameter(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Foo(user_id):\n   return user_id\n")
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "user_id")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.Parameter

   def TestLocalShadowsImport(self, tmp_path):
      src = Src("""\
         from os import path
         def Foo():
            path = "/tmp"
            return path
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner = [
         r for r in ResolvedRefs(result, "path")
         if r.ScopeRef.Kind == ScopeKind.Function
      ]
      assert inner
      assert inner[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestLocalShadowsModuleVariable(self, tmp_path):
      src = Src("""\
         Config = "global"
         def Foo():
            Config = "local"
            return Config
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner = [
         r for r in ResolvedRefs(result, "Config")
         if r.ScopeRef.Kind == ScopeKind.Function
      ]
      assert inner
      assert inner[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestFunctionCallResolvesToLocalFunctionDef(self, tmp_path):
      src = Src("""\
         def Helper():
            return 1
         def Foo():
            return Helper()
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      calls = [
         r for r in result.References
         if r.Name == "Helper" and r.Kind == RefKind.Call
      ]
      assert calls
      assert calls[0].ResolvedTo.Kind == DefKind.FunctionDef

   def TestClassConstructorResolvesToClassDef(self, tmp_path):
      src = Src("""\
         class MyModel:
            pass
         def Foo():
            return MyModel()
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      calls = [
         r for r in result.References
         if r.Name == "MyModel" and r.Kind == RefKind.Call
      ]
      assert calls
      assert calls[0].ResolvedTo.Kind == DefKind.ClassDef

   def TestImportedNameResolvesToImportEntry(self, tmp_path):
      src = Src("""\
         import os
         def Foo():
            return os.path
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = [
         r for r in result.References
         if r.Name == "os" and r.Kind == RefKind.Read
      ]
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.Import

   def TestImportFromResolvesToImportEntry(self, tmp_path):
      src = Src("""\
         from pathlib import Path
         def Foo():
            return Path(".")
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      calls = [
         r for r in result.References
         if r.Name == "Path" and r.Kind == RefKind.Call
      ]
      assert calls
      assert calls[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestUnresolvedNameMarkedUnresolved(self, tmp_path):
      src = "def Foo():\n   return SomeUndefinedName()\n"
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      assert UnresolvedRefs(result, "SomeUndefinedName")

   def TestNestedFunctionScopeResolvesCorrectly(self, tmp_path):
      src = Src("""\
         def Outer():
            x = 1
            def Inner():
               return x
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner_read = [
         r for r in ResolvedRefs(result, "x")
         if r.ScopeRef.Name == "Inner"
      ]
      assert inner_read
      assert inner_read[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestOuterVariableVisibleInInnerFunction(self, tmp_path):
      src = Src("""\
         COUNT = 10
         def Foo():
            return COUNT
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = [
         r for r in ResolvedRefs(result, "COUNT")
         if r.ScopeRef.Kind == ScopeKind.Function
      ]
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestMethodScopeResolvesSelfParameter(self, tmp_path):
      src = Src("""\
         class Repo:
            def GetName(self):
               return self
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = ResolvedRefs(result, "self")
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.Parameter

   def TestSelfXNotResolved(self, tmp_path):
      src = Src("""\
         class Repo:
            def GetName(self):
               return self.Name
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved_name = [
         r for r in ResolvedRefs(result, "Name") if not r.IsDynamic
      ]
      assert not resolved_name

   def TestAttrCallMarkedDynamic(self, tmp_path):
      src = Src("""\
         def Foo(obj):
            return obj.Method()
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      dynamic = [
         r for r in result.References
         if r.IsDynamic and r.Name == "Method"
      ]
      assert dynamic


# ---------------------------------------------------------------------------
# TestExceptAlias — except-as target global/nonlocal awareness
# ---------------------------------------------------------------------------


class TestExceptAlias:
   def TestExceptAliasNormalLocal(self, tmp_path):
      """Normal except-as target must create a LocalWrite in the function scope."""
      src = Src("""         def Foo():
            try:
               pass
            except Exception as err:
               return err
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(s for s in result.Tree.AllScopes if s.Name == "Foo")
      local_err = [
         d for d in result.Definitions
         if d.Name == "err" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is fn_scope
      ]
      assert local_err, "err must be a LocalWrite in Foo"
      read_err = [
         r for r in ResolvedRefs(result, "err")
         if r.ScopeRef is fn_scope
      ]
      assert read_err
      assert read_err[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestExceptAliasGlobal(self, tmp_path):
      """global err; except ... as err: must emit Write ref, not LocalWrite."""
      src = Src("""         err = None
         def Foo():
            global err
            try:
               pass
            except Exception as err:
               return err
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(s for s in result.Tree.AllScopes if s.Name == "Foo")
      # No LocalWrite for err inside Foo
      local_err = [
         d for d in result.Definitions
         if d.Name == "err" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is fn_scope
      ]
      assert not local_err, "global err must not create LocalWrite inside Foo"
      # Write ref resolves to module err
      write_err = WriteRefs(result, "err")
      assert write_err
      assert write_err[0].ResolvedTo is not None
      assert write_err[0].ResolvedTo.Kind == DefKind.ModuleDecl
      # Read ref (return err) resolves to module err
      read_err = [
         r for r in ResolvedRefs(result, "err")
         if r.ScopeRef is fn_scope and r.Kind == RefKind.Read
      ]
      assert read_err
      assert read_err[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestExceptAliasNonlocal(self, tmp_path):
      """nonlocal err; except ... as err: must emit Write ref, not LocalWrite."""
      src = Src("""         def Outer():
            err = None
            def Inner():
               nonlocal err
               try:
                  pass
               except Exception as err:
                  return err
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner_scope = next(s for s in result.Tree.AllScopes if s.Name == "Inner")
      # No LocalWrite for err inside Inner
      local_err = [
         d for d in result.Definitions
         if d.Name == "err" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is inner_scope
      ]
      assert not local_err, "nonlocal err must not create LocalWrite inside Inner"
      # Write ref resolves to Outer's err
      write_err = WriteRefs(result, "err")
      assert write_err
      assert write_err[0].ResolvedTo.ScopeRef.Name == "Outer"
      # Read ref resolves to Outer's err
      read_err = [
         r for r in ResolvedRefs(result, "err")
         if r.ScopeRef is inner_scope and r.Kind == RefKind.Read
      ]
      assert read_err
      assert read_err[0].ResolvedTo.ScopeRef.Name == "Outer"


# ---------------------------------------------------------------------------
# TestAugAssignReadWrite — augmented assignment models read + write
# ---------------------------------------------------------------------------


class TestAugAssignReadWrite:
   def TestAugAssignGlobalReadAndWrite(self, tmp_path):
      """Counter += 1 with global Counter: Read and Write refs, no LocalWrite."""
      src = Src("""         Counter = 0
         def Increment():
            global Counter
            Counter += 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(s for s in result.Tree.AllScopes if s.Name == "Increment")
      # No LocalWrite for Counter inside Increment
      local_counter = [
         d for d in result.Definitions
         if d.Name == "Counter" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is fn_scope
      ]
      assert not local_counter, "global Counter must not create LocalWrite"
      # Write ref resolves to module Counter
      write_refs = [
         r for r in WriteRefs(result, "Counter")
         if r.ScopeRef is fn_scope
      ]
      assert write_refs
      assert write_refs[0].ResolvedTo is not None
      assert write_refs[0].ResolvedTo.Kind == DefKind.ModuleDecl
      # Read ref resolves to module Counter
      read_refs = [
         r for r in ResolvedRefs(result, "Counter")
         if r.ScopeRef is fn_scope and r.Kind == RefKind.Read
      ]
      assert read_refs
      assert read_refs[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestAugAssignLocalReadAndWrite(self, tmp_path):
      """Local Counter += 1: LocalWrite definition, read resolves to it."""
      src = Src("""         def Increment():
            Counter = 0
            Counter += 1
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_scope = next(s for s in result.Tree.AllScopes if s.Name == "Increment")
      # LocalWrite Counter exists
      local_counter = [
         d for d in result.Definitions
         if d.Name == "Counter" and d.Kind == DefKind.LocalWrite
         and d.ScopeRef is fn_scope
      ]
      assert local_counter, "normal local assignment must create LocalWrite"
      # Read ref from the augmented assignment resolves to local Counter
      read_refs = [
         r for r in ResolvedRefs(result, "Counter")
         if r.ScopeRef is fn_scope and r.Kind == RefKind.Read
      ]
      assert read_refs
      assert read_refs[0].ResolvedTo.Kind == DefKind.LocalWrite
      assert read_refs[0].ResolvedTo.ScopeRef is fn_scope


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------


class TestCLI:
   def TestResolveSubcommandOutputIsJson(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      rc = RunMain("resolve", str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "files" in data
      assert "errors" in data

   def TestResolveIndexAliasWorks(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      rc = RunResolve(str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "files" in data

   def TestResolvePrettyWorks(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      RunMain("resolve", "--pretty", str(tmp_path))
      out = capsys.readouterr().out
      assert "\n  " in out
      json.loads(out)  # must still be valid JSON

   def TestResolveOutputFileWorks(self, tmp_path):
      Write(tmp_path / "f.py", "X = 1\n")
      out_file = tmp_path / "resolve.json"
      rc = RunMain("resolve", "--output", str(out_file), str(tmp_path))
      assert rc == 0
      assert out_file.exists()
      content = out_file.read_text(encoding="utf-8")
      assert not content.startswith("\xef\xbb\xbf")  # no BOM
      data = json.loads(content)
      assert "files" in data

   def TestResolveSyntaxErrorInErrors(self, tmp_path, capsys):
      Write(tmp_path / "good.py", "X = 1\n")
      Write(tmp_path / "broken.py", "def Broken(\n")
      RunMain("resolve", str(tmp_path))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert len(data["files"]) == 1
      assert len(data["errors"]) == 1
      assert data["errors"][0]["file"].endswith("broken.py")
      assert "syntax" in data["errors"][0]["error"].lower()

   def TestResolveInvalidUtf8InErrors(self, tmp_path, capsys):
      Write(tmp_path / "good.py", "X = 1\n")
      WriteBytes(tmp_path / "bad.py", b"x = \xff\n")
      RunMain("resolve", str(tmp_path))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert len(data["files"]) == 1
      assert len(data["errors"]) == 1
      assert data["errors"][0]["file"].endswith("bad.py")

   def TestImportFromDefinitionMetadataIncludesAliasAndLevel(self, tmp_path):
      f = Write(
         tmp_path / "f.py",
         Src("from .models import UserModel as Model\n"),
      )

      result = ResolveFile(f)
      assert isinstance(result, ResolveResult)
      import_defs = [d for d in result.Definitions if d.Kind == DefKind.ImportFrom]

      assert import_defs
      assert import_defs[0].Extra["module"] == "models"
      assert import_defs[0].Extra["name"] == "UserModel"
      assert import_defs[0].Extra["asname"] == "Model"
      assert import_defs[0].Extra["level"] == 1
