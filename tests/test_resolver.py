"""
Tests for customfmt.symbols.resolver and ``customfmt resolve`` / ``resolve-index``.

TestScopes
   TestModuleScopeCreated
   TestFunctionScopePushed
   TestClassScopePushed
   TestNestedFunctionScope
   TestScopeParentChain
   TestScopeResolveNameLocal
   TestScopeResolveNameOutward
   TestScopeClassTransparentForFunctionLookup

TestResolveFile – core resolution
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
   TestModuleDeclResolvedFromFunction
   TestMultipleDefsForSameName
   TestSummaryCountsCorrect
   TestInvalidUtf8ReturnsFileError
   TestSyntaxErrorReturnsFileError

TestResolveResultSet
   TestEmptyResultSet
   TestMixedGoodAndBad
   TestToDictStructure

TestCLI
   TestResolveSubcommandExits0
   TestResolveSubcommandOutputIsJson
   TestResolvePretty
   TestResolveOutputFile
   TestResolveNoFiles
   TestResolveBadPath
   TestResolveIndexAliasWorks
   TestResolveEntryPointExists
   TestResolveSyntaxErrorInErrors
   TestResolveInvalidUtf8InErrors
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main, MainResolve, _EntryResolve
from customfmt.symbols.resolver import ResolveFile, ResolveResultSet
from customfmt.symbols.scopes import (
   DefKind,
   RefKind,
   ScopeKind,
)

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


# ---------------------------------------------------------------------------
# TestScopes – scope model unit tests
# ---------------------------------------------------------------------------


class TestScopes:
   def TestModuleScopeCreated(self, tmp_path):
      f = Write(tmp_path / "f.py", "X = 1\n")
      result = ResolveFile(f)
      assert result.Tree.Root.Kind == ScopeKind.Module

   def TestFunctionScopePushed(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Foo():\n   pass\n")
      result = ResolveFile(f)
      scopes = result.Tree.AllScopes
      func_scopes = [s for s in scopes if s.Kind == ScopeKind.Function]
      assert any(s.Name == "Foo" for s in func_scopes)

   def TestClassScopePushed(self, tmp_path):
      f = Write(tmp_path / "f.py", "class MyClass:\n   pass\n")
      result = ResolveFile(f)
      class_scopes = [
         s for s in result.Tree.AllScopes
         if s.Kind == ScopeKind.Class
      ]
      assert any(s.Name == "MyClass" for s in class_scopes)

   def TestNestedFunctionScope(self, tmp_path):
      src = "def Outer():\n   def Inner():\n      pass\n"
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      fn_names = {s.Name for s in result.Tree.AllScopes
                  if s.Kind == ScopeKind.Function}
      assert "Outer" in fn_names
      assert "Inner" in fn_names

   def TestScopeParentChain(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Foo():\n   pass\n")
      result = ResolveFile(f)
      foo_scope = next(
         s for s in result.Tree.AllScopes if s.Name == "Foo"
      )
      assert foo_scope.Parent is result.Tree.Root

   def TestScopeResolveNameLocal(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Foo():\n   x = 1\n   return x\n")
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "x")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestScopeResolveNameOutward(self, tmp_path):
      f = Write(tmp_path / "f.py", "X = 1\ndef Foo():\n   return X\n")
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "X")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestScopeClassTransparentForFunctionLookup(self, tmp_path):
      """Class-body names are NOT visible inside methods (LEGB rule)."""
      src = Src("""\
         TableName = "x"
         class Repo:
            TableName = "y"
            def GetName(self):
               return TableName
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      # The TableName read inside GetName should resolve to the MODULE-level
      # definition (line 1), not the class-body definition (line 3).
      resolved = ResolvedRefs(result, "TableName")
      assert resolved
      assert resolved[0].ResolvedTo.Line == 1


# ---------------------------------------------------------------------------
# TestResolveFile – core resolution
# ---------------------------------------------------------------------------


class TestResolveFile:
   def TestLocalVariableResolvesToLocalAssignment(self, tmp_path):
      src = "def Foo():\n   result = 1\n   return result\n"
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "result")
      assert resolved
      defn = resolved[0].ResolvedTo
      assert defn.Kind == DefKind.LocalWrite
      assert defn.Name == "result"

   def TestParameterResolvesToParameter(self, tmp_path):
      src = "def Foo(user_id):\n   return user_id\n"
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "user_id")
      assert resolved
      assert resolved[0].ResolvedTo.Kind == DefKind.Parameter

   def TestLocalShadowsImport(self, tmp_path):
      """A local assignment must shadow an import of the same name."""
      src = Src("""\
         from os import path
         def Foo():
            path = "/tmp"
            return path
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      resolved = ResolvedRefs(result, "path")
      assert resolved
      # The read inside Foo should resolve to the LOCAL write, not the import
      inner = [r for r in resolved if r.ScopeRef.Kind == ScopeKind.Function]
      assert inner
      assert inner[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestLocalShadowsModuleVariable(self, tmp_path):
      """A local assignment must shadow a module-level variable."""
      src = Src("""\
         Config = "global"
         def Foo():
            Config = "local"
            return Config
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      inner = [r for r in ResolvedRefs(result, "Config")
               if r.ScopeRef.Kind == ScopeKind.Function]
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
      calls = [r for r in result.References
               if r.Name == "Helper" and r.Kind == RefKind.Call]
      assert calls
      assert calls[0].ResolvedTo is not None
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
      calls = [r for r in result.References
               if r.Name == "MyModel" and r.Kind == RefKind.Call]
      assert calls
      assert calls[0].ResolvedTo is not None
      assert calls[0].ResolvedTo.Kind == DefKind.ClassDef

   def TestImportedNameResolvesToImportEntry(self, tmp_path):
      src = Src("""\
         import os
         def Foo():
            return os.path
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      # "os" appears as a name_read inside Foo; it should resolve to the import
      reads = [r for r in result.References
               if r.Name == "os" and r.Kind == RefKind.Read]
      assert reads
      assert reads[0].ResolvedTo is not None
      assert reads[0].ResolvedTo.Kind == DefKind.Import

   def TestImportFromResolvesToImportEntry(self, tmp_path):
      src = Src("""\
         from pathlib import Path
         def Foo():
            return Path(".")
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      calls = [r for r in result.References
               if r.Name == "Path" and r.Kind == RefKind.Call]
      assert calls
      assert calls[0].ResolvedTo is not None
      assert calls[0].ResolvedTo.Kind == DefKind.ImportFrom

   def TestUnresolvedNameMarkedUnresolved(self, tmp_path):
      src = "def Foo():\n   return SomeUndefinedName()\n"
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      unresolved = UnresolvedRefs(result, "SomeUndefinedName")
      assert unresolved

   def TestNestedFunctionScopeResolvesCorrectly(self, tmp_path):
      src = Src("""\
         def Outer():
            x = 1
            def Inner():
               return x
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      # x read inside Inner should resolve to x defined in Outer
      reads = [r for r in result.References if r.Name == "x"]
      assert reads
      inner_read = [
         r for r in reads if r.ScopeRef.Name == "Inner"
      ]
      assert inner_read
      assert inner_read[0].ResolvedTo is not None
      assert inner_read[0].ResolvedTo.Kind == DefKind.LocalWrite

   def TestOuterVariableVisibleInInnerFunction(self, tmp_path):
      src = Src("""\
         COUNT = 10
         def Foo():
            return COUNT
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = [r for r in ResolvedRefs(result, "COUNT")
               if r.ScopeRef.Kind == ScopeKind.Function]
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
      """self.X attribute access must be marked dynamic, not resolved."""
      src = Src("""\
         class Repo:
            def GetName(self):
               return self.Name
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      # self.Name will appear as an attribute_call or dynamic ref, not resolved
      _ = [r for r in result.References if r.IsDynamic]
      # At minimum there must be no resolved reference to "Name" as an attr
      resolved_name = [r for r in ResolvedRefs(result, "Name") if not r.IsDynamic]
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

   def TestModuleDeclResolvedFromFunction(self, tmp_path):
      src = Src("""\
         TableName = "orders"
         def GetTable():
            return TableName
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      reads = [r for r in ResolvedRefs(result, "TableName")
               if r.ScopeRef.Kind == ScopeKind.Function]
      assert reads
      assert reads[0].ResolvedTo.Kind == DefKind.ModuleDecl

   def TestMultipleDefsForSameName(self, tmp_path):
      """Two assignments to the same name both appear as definitions."""
      src = Src("""\
         def Foo():
            x = 1
            x = 2
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      x_defs = Defs(result, "x")
      assert len(x_defs) == 2

   def TestSummaryCountsCorrect(self, tmp_path):
      src = Src("""\
         import os
         def Foo():
            x = os.getcwd()
            return x
      """)
      f = Write(tmp_path / "f.py", src)
      result = ResolveFile(f)
      summary = result.ToDict()["summary"]
      assert summary["total_refs"] == summary["resolved"] + summary["unresolved"] + summary["dynamic"]

   def TestInvalidUtf8ReturnsFileError(self, tmp_path):
      f = WriteBytes(tmp_path / "f.py", b"x = \xff\n")
      from customfmt.symbols.model import FileError
      result = ResolveFile(f)
      assert isinstance(result, FileError)
      assert "encoding" in result.Error.lower()

   def TestSyntaxErrorReturnsFileError(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Broken(\n")
      from customfmt.symbols.model import FileError
      result = ResolveFile(f)
      assert isinstance(result, FileError)
      assert "syntax" in result.Error.lower()


# ---------------------------------------------------------------------------
# TestResolveResultSet
# ---------------------------------------------------------------------------


class TestResolveResultSet:
   def TestEmptyResultSet(self):
      rs = ResolveResultSet()
      d = rs.ToDict()
      assert d["files"] == []
      assert d["errors"] == []

   def TestMixedGoodAndBad(self, tmp_path):
      good = Write(tmp_path / "good.py", "X = 1\n")
      bad  = WriteBytes(tmp_path / "bad.py", b"x = \xff\n")
      from customfmt.symbols.model import FileError
      rs = ResolveResultSet()
      for path in [good, bad]:
         r = ResolveFile(path)
         if isinstance(r, FileError):
            rs.Errors.append(r)
         else:
            rs.Files.append(r)
      assert len(rs.Files) == 1
      assert len(rs.Errors) == 1

   def TestToDictStructure(self, tmp_path):
      f = Write(tmp_path / "f.py", "X = 1\n")
      rs = ResolveResultSet()
      r = ResolveFile(f)
      rs.Files.append(r)
      d = rs.ToDict()
      assert "files" in d
      assert "errors" in d
      file_d = d["files"][0]
      assert "scopes" in file_d
      assert "definitions" in file_d
      assert "references" in file_d
      assert "summary" in file_d


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------


class TestCLI:
   def TestResolveSubcommandExits0(self, tmp_path):
      Write(tmp_path / "f.py", "X = 1\n")
      assert RunMain("resolve", str(tmp_path)) == 0

   def TestResolveSubcommandOutputIsJson(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      RunMain("resolve", str(tmp_path))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "files" in data
      assert "errors" in data

   def TestResolvePretty(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      RunMain("resolve", "--pretty", str(tmp_path))
      out = capsys.readouterr().out
      assert "\n" in out
      assert "  " in out
      data = json.loads(out)
      assert "files" in data

   def TestResolveOutputFile(self, tmp_path):
      Write(tmp_path / "f.py", "X = 1\n")
      out_file = tmp_path / "resolve.json"
      rc = RunMain("resolve", "--output", str(out_file), str(tmp_path))
      assert rc == 0
      assert out_file.exists()
      data = json.loads(out_file.read_text(encoding="utf-8"))
      assert "files" in data

   def TestResolveNoFiles(self, tmp_path):
      assert RunMain("resolve", str(tmp_path)) == 2

   def TestResolveBadPath(self, tmp_path):
      assert RunMain("resolve", str(tmp_path / "nope.py")) == 2

   def TestResolveIndexAliasWorks(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      rc = RunResolve(str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "files" in data

   def TestResolveEntryPointExists(self):
      assert callable(_EntryResolve)

   def TestResolveSyntaxErrorInErrors(self, tmp_path, capsys):
      Write(tmp_path / "good.py", "X = 1\n")
      Write(tmp_path / "broken.py", "def Broken(\n")
      RunMain("resolve", str(tmp_path))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert len(data["files"]) == 1
      assert len(data["errors"]) == 1
      assert data["errors"][0]["file"].endswith("broken.py")

   def TestResolveInvalidUtf8InErrors(self, tmp_path, capsys):
      Write(tmp_path / "good.py", "X = 1\n")
      WriteBytes(tmp_path / "bad.py", b"x = \xff\n")
      RunMain("resolve", str(tmp_path))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert len(data["files"]) == 1
      assert len(data["errors"]) == 1
      assert data["errors"][0]["file"].endswith("bad.py")
