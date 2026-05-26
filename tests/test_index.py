"""
Tests for customfmt.symbols.* and ``customfmt index`` / ``create-index``.

TestModel
   TestSymbolEntryToDict
   TestFileIndexToDict
   TestFileErrorToDict
   TestIndexResultToDict

TestAstIndexer
   TestImportsIndexed
   TestImportFromIndexed
   TestModuleDeclAssignIndexed
   TestModuleDeclAnnAssignIndexed
   TestClassIndexed
   TestClassDeclAssignIndexed
   TestClassDeclAnnAssignIndexed
   TestFunctionIndexed
   TestMethodIndexed
   TestParametersIndexed
   TestLocalWriteSimple
   TestLocalWriteForLoop
   TestLocalWriteWithAs
   TestLocalWriteExceptAs
   TestLocalWriteTupleUnpack
   TestNameReadIndexed
   TestCallIndexed
   TestAttributeCallIndexed
   TestNestedClassInsideFunction
   TestSpecExample
   TestInvalidUtf8ReturnsFileError
   TestBomReturnsFileError
   TestSyntaxErrorReturnsFileError

TestIndexPaths
   TestIndexPathsCollectsFiles
   TestIndexPathsBadPathReturnsError
   TestIndexPathsMixedGoodAndBad

TestCLI
   TestIndexSubcommandExits0
   TestIndexSubcommandOutputIsJson
   TestIndexSubcommandPretty
   TestIndexSubcommandOutputFile
   TestIndexSubcommandNoFiles
   TestIndexSubcommandBadPath
   TestCreateIndexAliasWorks
   TestInvalidUtf8FileReportedInErrors
   TestSyntaxErrorFileReportedInErrors
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main, MainIndex
from customfmt.indexer import IndexPaths
from customfmt.io import UTF8_BOM
from customfmt.symbols.ast_indexer import IndexFile
from customfmt.symbols.model import (
   KIND_ATTR_CALL,
   KIND_CALL,
   KIND_CLASS,
   KIND_CLASS_DECL,
   KIND_FUNCTION,
   KIND_IMPORT,
   KIND_IMPORT_FROM,
   KIND_LOCAL_WRITE,
   KIND_METHOD,
   KIND_MODULE_DECL,
   KIND_NAME_READ,
   KIND_PARAMETER,
   FileError,
   FileIndex,
   IndexResult,
   SymbolEntry,
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


def Symbols(index: FileIndex, kind: str) -> list[SymbolEntry]:
   return [s for s in index.Symbols if s.Kind == kind]


def Names(index: FileIndex, kind: str) -> list[str]:
   return [s.Name for s in Symbols(index, kind)]


def Qualified(index: FileIndex, kind: str) -> list[str]:
   return [s.QualifiedName for s in Symbols(index, kind)]


def RunMain(*args: str) -> int:
   return Main(list(args))


def RunIndex(*args: str) -> int:
   return MainIndex(list(args))


# ---------------------------------------------------------------------------
# TestModel — data model serialisation
# ---------------------------------------------------------------------------


class TestModel:
   def TestSymbolEntryToDict(self):
      s = SymbolEntry(
         Kind          = KIND_FUNCTION,
         Name          = "MyFunc",
         QualifiedName = "MyFunc",
         FilePath      = "f.py",
         Line          = 1,
         Col           = 0,
         Scope         = "",
         Extra         = {},
      )
      d = s.ToDict()
      assert d["kind"] == KIND_FUNCTION
      assert d["name"] == "MyFunc"
      assert d["qualified_name"] == "MyFunc"
      assert d["file"] == "f.py"
      assert d["line"] == 1
      assert d["col"] == 0
      assert d["scope"] == ""
      assert d["extra"] == {}

   def TestFileIndexToDict(self):
      fi = FileIndex(FilePath="f.py")
      d = fi.ToDict()
      assert d["file"] == "f.py"
      assert d["symbols"] == []

   def TestFileErrorToDict(self):
      fe = FileError(FilePath="bad.py", Error="encoding error")
      d = fe.ToDict()
      assert d["file"] == "bad.py"
      assert d["error"] == "encoding error"

   def TestIndexResultToDict(self):
      ir = IndexResult()
      ir.Files.append(FileIndex(FilePath="a.py"))
      ir.Errors.append(FileError(FilePath="b.py", Error="oops"))
      d = ir.ToDict()
      assert len(d["files"]) == 1
      assert len(d["errors"]) == 1
      assert d["errors"][0]["file"] == "b.py"


# ---------------------------------------------------------------------------
# TestAstIndexer — core indexing logic
# ---------------------------------------------------------------------------


class TestAstIndexer:
   def TestImportsIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("import os\nimport sys\n"))
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)
      assert "os" in Names(idx, KIND_IMPORT)
      assert "sys" in Names(idx, KIND_IMPORT)

   def TestImportFromIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("from pathlib import Path\n"))
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)
      assert "Path" in Names(idx, KIND_IMPORT_FROM)
      imp = Symbols(idx, KIND_IMPORT_FROM)[0]
      assert imp.Extra["module"] == "pathlib"

   def TestImportFromAsIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("from pathlib import Path as P\n"))
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)
      # bound name is the alias
      assert "P" in Names(idx, KIND_IMPORT_FROM)
      imp = Symbols(idx, KIND_IMPORT_FROM)[0]
      assert imp.Extra["asname"] == "P"
      assert imp.Extra["name"] == "Path"

   def TestModuleDeclAssignIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("AppConfig = LoadConfig()\n"))
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)
      assert "AppConfig" in Names(idx, KIND_MODULE_DECL)

   def TestModuleDeclAnnAssignIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("MyCount: int = 0\n"))
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)
      assert "MyCount" in Names(idx, KIND_MODULE_DECL)

   def TestModuleDeclNotInsideFunction(self, tmp_path):
      """Assignments inside functions must NOT appear as module_declaration."""
      f = Write(tmp_path / "f.py", Src("def Foo():\n   X = 1\n"))
      idx = IndexFile(f)
      assert "X" not in Names(idx, KIND_MODULE_DECL)

   def TestClassIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("class UserRepo:\n   pass\n"))
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)
      assert "UserRepo" in Names(idx, KIND_CLASS)
      cls = Symbols(idx, KIND_CLASS)[0]
      assert cls.QualifiedName == "UserRepo"
      assert cls.Scope == ""

   def TestClassWithBasesIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("class Child(Parent):\n   pass\n"))
      idx = IndexFile(f)
      cls = Symbols(idx, KIND_CLASS)[0]
      assert "Parent" in cls.Extra["bases"]

   def TestClassDeclAssignIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src(
         "class Repo:\n   TableName = \"x\"\n   Pk = \"ID\"\n"
      ))
      idx = IndexFile(f)
      qualified = Qualified(idx, KIND_CLASS_DECL)
      assert "Repo.TableName" in qualified
      assert "Repo.Pk" in qualified

   def TestClassDeclAnnAssignIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("class A:\n   Count: int\n"))
      idx = IndexFile(f)
      assert "A.Count" in Qualified(idx, KIND_CLASS_DECL)

   def TestFunctionIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def MyFunc():\n   pass\n"))
      idx = IndexFile(f)
      assert "MyFunc" in Names(idx, KIND_FUNCTION)
      fn = Symbols(idx, KIND_FUNCTION)[0]
      assert fn.QualifiedName == "MyFunc"
      assert fn.Scope == ""

   def TestMethodIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src(
         "class Repo:\n   def GetByID(self, id: int):\n      pass\n"
      ))
      idx = IndexFile(f)
      assert "GetByID" in Names(idx, KIND_METHOD)
      m = Symbols(idx, KIND_METHOD)[0]
      assert m.QualifiedName == "Repo.GetByID"
      assert m.Scope == "Repo"

   def TestParametersIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src(
         "def Foo(user_name, count: int = 0):\n   pass\n"
      ))
      idx = IndexFile(f)
      param_names = Names(idx, KIND_PARAMETER)
      assert "user_name" in param_names
      assert "count" in param_names
      count_param = next(s for s in Symbols(idx, KIND_PARAMETER) if s.Name == "count")
      assert count_param.Extra["annotation"] == "int"

   def TestMethodParametersQualified(self, tmp_path):
      f = Write(tmp_path / "f.py", Src(
         "class A:\n   def Foo(self, val: int):\n      pass\n"
      ))
      idx = IndexFile(f)
      qualified = Qualified(idx, KIND_PARAMETER)
      assert "A.Foo.self" in qualified
      assert "A.Foo.val" in qualified

   def TestLocalWriteSimple(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def Foo():\n   result = 1\n"))
      idx = IndexFile(f)
      assert "result" in Names(idx, KIND_LOCAL_WRITE)
      lw = Symbols(idx, KIND_LOCAL_WRITE)[0]
      assert lw.QualifiedName == "Foo.result"

   def TestLocalWriteForLoop(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def Foo():\n   for item in []:\n      pass\n"))
      idx = IndexFile(f)
      assert "item" in Names(idx, KIND_LOCAL_WRITE)

   def TestLocalWriteWithAs(self, tmp_path):
      f = Write(tmp_path / "f.py", Src(
         "def Foo():\n   with open('f') as fh:\n      pass\n"
      ))
      idx = IndexFile(f)
      assert "fh" in Names(idx, KIND_LOCAL_WRITE)

   def TestLocalWriteExceptAs(self, tmp_path):
      f = Write(tmp_path / "f.py", Src(
         "def Foo():\n   try:\n      pass\n   except Exception as err:\n      pass\n"
      ))
      idx = IndexFile(f)
      assert "err" in Names(idx, KIND_LOCAL_WRITE)

   def TestLocalWriteTupleUnpack(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def Foo():\n   a, b = 1, 2\n"))
      idx = IndexFile(f)
      names = Names(idx, KIND_LOCAL_WRITE)
      assert "a" in names
      assert "b" in names

   def TestNameReadIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def Foo():\n   x = 1\n   return x\n"))
      idx = IndexFile(f)
      reads = Names(idx, KIND_NAME_READ)
      assert "x" in reads

   def TestCallIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def Foo():\n   Bar(1, 2)\n"))
      idx = IndexFile(f)
      calls = Names(idx, KIND_CALL)
      assert "Bar" in calls
      call = next(s for s in Symbols(idx, KIND_CALL) if s.Name == "Bar")
      assert call.Extra["args"] == 2

   def TestAttributeCallIndexed(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("def Foo(self):\n   self.Db.Fetch(1)\n"))
      idx = IndexFile(f)
      assert "Fetch" in Names(idx, KIND_ATTR_CALL)
      ac = next(s for s in Symbols(idx, KIND_ATTR_CALL) if s.Name == "Fetch")
      assert "Fetch" in ac.Extra["full"]

   def TestNestedClassInsideFunction(self, tmp_path):
      """A class defined inside a function is still indexed."""
      f = Write(tmp_path / "f.py", Src(
         "def Outer():\n   class Inner:\n      pass\n"
      ))
      idx = IndexFile(f)
      assert "Inner" in Names(idx, KIND_CLASS)

   def TestSpecExample(self, tmp_path):
      """The canonical spec example — verify all expected symbol kinds present."""
      src = Src("""\
         from models.UserModel import UserModel
         AppConfig = LoadConfig()
         class UserRepo:
            TableName = "User"
            def GetByID(self, ID: int):
               Result = self.Db.Fetch(ID)
               return UserModel(**Result)
      """)
      f = Write(tmp_path / "my_module.py", src)
      idx = IndexFile(f)
      assert isinstance(idx, FileIndex)

      assert "UserModel"        in Names(idx, KIND_IMPORT_FROM)
      assert "AppConfig"        in Names(idx, KIND_MODULE_DECL)
      assert "UserRepo"         in Names(idx, KIND_CLASS)
      assert "UserRepo.TableName" in Qualified(idx, KIND_CLASS_DECL)
      assert "GetByID"          in Names(idx, KIND_METHOD)
      assert "self"             in Names(idx, KIND_PARAMETER)
      assert "ID"               in Names(idx, KIND_PARAMETER)
      assert "Result"           in Names(idx, KIND_LOCAL_WRITE)
      assert "Fetch"            in Names(idx, KIND_ATTR_CALL)
      assert "UserModel"        in Names(idx, KIND_CALL)

   def TestInvalidUtf8ReturnsFileError(self, tmp_path):
      f = WriteBytes(tmp_path / "f.py", b"x = \xff\n")
      result = IndexFile(f)
      assert isinstance(result, FileError)
      assert "encoding" in result.Error.lower()

   def TestBomReturnsFileError(self, tmp_path):
      f = WriteBytes(tmp_path / "f.py", UTF8_BOM + b"x = 1\n")
      result = IndexFile(f)
      assert isinstance(result, FileError)
      assert "bom" in result.Error.lower() or "encoding" in result.Error.lower()

   def TestSyntaxErrorReturnsFileError(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Broken(\n")
      result = IndexFile(f)
      assert isinstance(result, FileError)
      assert "syntax" in result.Error.lower()


# ---------------------------------------------------------------------------
# TestIndexPaths — facade
# ---------------------------------------------------------------------------


class TestIndexPaths:
   def TestIndexPathsCollectsFiles(self, tmp_path):
      Write(tmp_path / "a.py", "X = 1\n")
      Write(tmp_path / "b.py", "Y = 2\n")
      result, errors = IndexPaths([str(tmp_path)])
      assert errors == []
      assert len(result.Files) == 2
      assert result.Errors == []

   def TestIndexPathsBadPathReturnsError(self, tmp_path):
      _, errors = IndexPaths([str(tmp_path / "nope.py")])
      assert errors  # discovery error returned

   def TestIndexPathsMixedGoodAndBad(self, tmp_path):
      Write(tmp_path / "good.py", "X = 1\n")
      WriteBytes(tmp_path / "bad.py", b"x = \xff\n")
      result, errors = IndexPaths([str(tmp_path)])
      assert errors == []
      assert len(result.Files) == 1
      assert len(result.Errors) == 1
      assert result.Files[0].FilePath.endswith("good.py")
      assert result.Errors[0].FilePath.endswith("bad.py")


# ---------------------------------------------------------------------------
# TestCLI — CLI entry points
# ---------------------------------------------------------------------------


class TestCLI:
   def TestIndexSubcommandExits0(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      rc = RunMain("index", str(tmp_path))
      assert rc == 0

   def TestIndexSubcommandOutputIsJson(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      RunMain("index", str(tmp_path))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "files" in data
      assert "errors" in data

   def TestIndexSubcommandPretty(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      RunMain("index", "--pretty", str(tmp_path))
      out = capsys.readouterr().out
      # Pretty output has newlines and indentation
      assert "\n" in out
      assert "  " in out
      data = json.loads(out)
      assert "files" in data

   def TestIndexSubcommandOutputFile(self, tmp_path):
      Write(tmp_path / "f.py", "X = 1\n")
      out_file = tmp_path / "index.json"
      rc = RunMain("index", "--output", str(out_file), str(tmp_path))
      assert rc == 0
      assert out_file.exists()
      data = json.loads(out_file.read_text(encoding="utf-8"))
      assert "files" in data

   def TestIndexSubcommandPrettyOutputFile(self, tmp_path):
      Write(tmp_path / "f.py", "X = 1\n")
      out_file = tmp_path / "index.json"
      rc = RunMain("index", "--pretty", "--output", str(out_file), str(tmp_path))
      assert rc == 0
      raw = out_file.read_text(encoding="utf-8")
      assert "\n  " in raw  # indented JSON

   def TestIndexSubcommandNoFiles(self, tmp_path):
      rc = RunMain("index", str(tmp_path))
      assert rc == 2

   def TestIndexSubcommandBadPath(self, tmp_path):
      rc = RunMain("index", str(tmp_path / "nope.py"))
      assert rc == 2

   def TestCreateIndexAliasWorks(self, tmp_path, capsys):
      Write(tmp_path / "f.py", "X = 1\n")
      rc = RunIndex(str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert "files" in data

   def TestInvalidUtf8FileReportedInErrors(self, tmp_path, capsys):
      """Invalid UTF-8 file must appear in errors, other files still indexed."""
      Write(tmp_path / "good.py", "X = 1\n")
      WriteBytes(tmp_path / "bad.py", b"x = \xff\n")
      rc = RunMain("index", str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert len(data["files"]) == 1
      assert len(data["errors"]) == 1
      assert data["errors"][0]["file"].endswith("bad.py")

   def TestSyntaxErrorFileReportedInErrors(self, tmp_path, capsys):
      """Syntax-error file must appear in errors, other files still indexed."""
      Write(tmp_path / "good.py", "X = 1\n")
      Write(tmp_path / "broken.py", "def Broken(\n")
      rc = RunMain("index", str(tmp_path))
      assert rc == 0
      out = capsys.readouterr().out
      data = json.loads(out)
      assert len(data["files"]) == 1
      assert len(data["errors"]) == 1
      assert data["errors"][0]["file"].endswith("broken.py")
