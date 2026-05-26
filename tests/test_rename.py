"""
Tests for customfmt.renamer and ``customfmt rename``.

TestToSnake
   TestPascalToSnake
   TestCamelToSnake
   TestAlreadySnake
   TestAcronym

TestAnalyseFile – core rename logic
   TestSimpleAssignmentRename
   TestMultipleReferencesRenamed
   TestForLoopTargetRenamed
   TestWithAsTargetRenamed
   TestExceptAsTargetRenamed
   TestAlreadySnakeCaseUnchanged
   TestUnderscorePrefixSkipped
   TestCommentUnchanged
   TestStringUnchanged
   TestCollisionWithExistingLocalSkipped
   TestCollisionWithParamSkipped
   TestCollisionWithBuiltinSkipped
   TestCollisionWithImportSkipped
   TestTwoBadNamesSameTargetSkipped
   TestGlobalDeclarationSkipsFunction
   TestNonlocalDeclarationSkipsFunction
   TestEvalCallSkipsFunction
   TestExecCallSkipsFunction
   TestLocalsCallSkipsFunction
   TestGlobalsCallSkipsFunction
   TestVarsCallSkipsFunction
   TestNestedFunctionScopeNotRewritten
   TestMethodCallOnLocalsAttrNotMistaken

TestCLIRename – CLI exit codes and output
   TestCheckExits1WhenCandidates
   TestCheckExits0WhenClean
   TestDiffExits0WhenCandidates
   TestDiffExits0WhenClean
   TestApplyExits0AndWritesFile
   TestApplyExits0WhenNoCandidates
   TestCheckDoesNotModifyFile
   TestDiffDoesNotModifyFile
   TestCheckOutputContainsRename
   TestDiffOutputContainsDiff
   TestNoPathExits2
   TestBadPathExits2

TestCLIFixAndCheckCrlf – Fix 4: CRLF tests for fix/check
   TestTryAutoFormatCheckReportsCrlfAsWouldChange
   TestTryAutoFormatFixesCrlfToLf
   TestCheckFormatReportsCf011ForCrlf
   TestCheckFormatNoCf009NoiseFromCrlf
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from customfmt.cli import Main
from customfmt.renamer import AnalyseFile, _ToSnake

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


# ---------------------------------------------------------------------------
# _ToSnake unit tests
# ---------------------------------------------------------------------------


class TestToSnake:
   def TestPascalToSnake(self):
      assert _ToSnake("TotalCount") == "total_count"
      assert _ToSnake("UserName") == "user_name"
      assert _ToSnake("MyVariable") == "my_variable"

   def TestCamelToSnake(self):
      assert _ToSnake("totalCount") == "total_count"
      assert _ToSnake("myVar") == "my_var"

   def TestAlreadySnake(self):
      assert _ToSnake("total_count") == "total_count"
      assert _ToSnake("x") == "x"

   def TestAcronym(self):
      assert _ToSnake("HTMLParser") == "html_parser"
      assert _ToSnake("parseHTML") == "parse_html"


# ---------------------------------------------------------------------------
# AnalyseFile – core rename logic
# ---------------------------------------------------------------------------


class TestAnalyseFile:
   def TestSimpleAssignmentRename(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      assert "total_count" in result.rewritten
      assert "TotalCount" not in result.rewritten

   def TestMultipleReferencesRenamed(self, tmp_path):
      src = Src("""\
         def Foo():
            MyVar = 1
            MyVar = MyVar + 1
            return MyVar
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      assert result.rewritten.count("my_var") == 4
      assert "MyVar" not in result.rewritten

   def TestForLoopTargetRenamed(self, tmp_path):
      src = Src("""\
         def Foo():
            for ItemName in []:
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      assert "item_name" in result.rewritten

   def TestWithAsTargetRenamed(self, tmp_path):
      src = Src("""\
         def Foo():
            with open("f") as FileHandle:
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      assert "file_handle" in result.rewritten

   def TestExceptAsTargetRenamed(self, tmp_path):
      src = Src("""\
         def Foo():
            try:
               pass
            except Exception as MyError:
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      assert "my_error" in result.rewritten

   def TestAlreadySnakeCaseUnchanged(self, tmp_path):
      src = Src("""\
         def Foo():
            total_count = 0
            return total_count
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestUnderscorePrefixSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            _TmpVal = 1
            return _TmpVal
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestCommentUnchanged(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0  # TotalCount is important
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      # Comment must be verbatim-preserved
      assert "# TotalCount is important" in result.rewritten

   def TestStringUnchanged(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            label = "TotalCount"
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert result.Changed
      # String content must be verbatim-preserved
      assert '"TotalCount"' in result.rewritten

   def TestCollisionWithExistingLocalSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            total_count = 2
            return TotalCount + total_count
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # Renaming TotalCount -> total_count would collide; must be skipped.
      assert not result.Changed

   def TestCollisionWithParamSkipped(self, tmp_path):
      src = Src("""\
         def Foo(total_count):
            TotalCount = 1
            return TotalCount + total_count
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestCollisionWithBuiltinSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            List = [1, 2, 3]
            return List
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # list is a builtin — renaming List -> list would shadow it.
      assert not result.Changed

   def TestCollisionWithImportSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            import os
            OsPath = os.path
            return OsPath
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # os_path does not conflict, but os is imported — check renaming is safe
      assert result.Changed
      assert "os_path" in result.rewritten

   def TestTwoBadNamesSameTargetSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            Total_Count = 2
            return TotalCount + Total_Count
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # Both map to total_count — both must be skipped.
      assert not result.Changed

   def TestGlobalDeclarationSkipsFunction(self, tmp_path):
      src = Src("""\
         def Foo():
            global x
            TotalCount = 1
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestNonlocalDeclarationSkipsFunction(self, tmp_path):
      src = Src("""\
         def Outer():
            def Foo():
               nonlocal y
               TotalCount = 1
               return TotalCount
            y = 0
            Foo()
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # Inner Foo has nonlocal -> skipped. Outer Foo has no bad names.
      assert not result.Changed

   def TestEvalCallSkipsFunction(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            eval("TotalCount")
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestExecCallSkipsFunction(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            exec("TotalCount = 2")
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestLocalsCallSkipsFunction(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            d = locals()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestGlobalsCallSkipsFunction(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            d = globals()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestVarsCallSkipsFunction(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            d = vars()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      assert not result.Changed

   def TestNestedFunctionScopeNotRewritten(self, tmp_path):
      src = Src("""\
         def Outer():
            OuterVar = 1
            def Inner():
               InnerVar = 2
               return InnerVar
            return OuterVar
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # OuterVar in Outer IS renamed.
      assert "outer_var" in result.rewritten
      # InnerVar in Inner: processed independently, also renamed.
      assert "inner_var" in result.rewritten

   def TestMethodCallOnLocalsAttrNotMistaken(self, tmp_path):
      # obj.locals() should not trigger the unsafe-call guard.
      src = Src("""\
         def Foo(obj):
            TotalCount = obj.locals()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      result = AnalyseFile(f)
      # obj.locals() is an attribute call, not a bare locals() call.
      # The unsafe-call guard checks ast.Name(id="locals"), not attr access.
      # So rename should proceed.
      assert result.Changed
      assert "total_count" in result.rewritten


# ---------------------------------------------------------------------------
# CLI rename tests
# ---------------------------------------------------------------------------


class TestCLIRename:
   def TestCheckExits1WhenCandidates(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      assert RunMain("rename", "--check", str(f)) == 1

   def TestCheckExits0WhenClean(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            total_count = 0
            return total_count
      """))
      assert RunMain("rename", "--check", str(f)) == 0

   def TestDiffExits0WhenCandidates(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      assert RunMain("rename", "--diff", str(f)) == 0

   def TestDiffExits0WhenClean(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            total_count = 0
            return total_count
      """))
      assert RunMain("rename", "--diff", str(f)) == 0

   def TestApplyExits0AndWritesFile(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      rc = RunMain("rename", "--apply", str(f))
      assert rc == 0
      content = f.read_text(encoding="utf-8")
      assert "total_count" in content
      assert "TotalCount" not in content

   def TestApplyExits0WhenNoCandidates(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            total_count = 0
            return total_count
      """))
      assert RunMain("rename", "--apply", str(f)) == 0

   def TestCheckDoesNotModifyFile(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      RunMain("rename", "--check", str(f))
      assert f.read_text(encoding="utf-8") == src

   def TestDiffDoesNotModifyFile(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      RunMain("rename", "--diff", str(f))
      assert f.read_text(encoding="utf-8") == src

   def TestCheckOutputContainsRename(self, tmp_path, capsys):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      RunMain("rename", "--check", str(f))
      out = capsys.readouterr().out
      assert "RENAME" in out
      assert "TotalCount" in out
      assert "total_count" in out

   def TestDiffOutputContainsDiff(self, tmp_path, capsys):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      RunMain("rename", "--diff", str(f))
      out = capsys.readouterr().out
      assert "---" in out
      assert "+++" in out

   def TestNoPathExits2(self, tmp_path):
      assert RunMain("rename", "--check", str(tmp_path)) == 2

   def TestBadPathExits2(self, tmp_path):
      assert RunMain("rename", "--check", str(tmp_path / "nope.py")) == 2


# ---------------------------------------------------------------------------
# Fix 4: CRLF tests wired through fix/check commands
# ---------------------------------------------------------------------------


class TestCLIFixAndCheckCrlf:
   def TestTryAutoFormatCheckReportsCrlfAsWouldChange(self, tmp_path):
      """try-auto-format --check exits 1 (would-change) for a CRLF file."""
      f = WriteBytes(tmp_path / "f.py", b"x = 1\r\ny = 2\r\n")
      rc = RunMain("fix", "--check", str(f))
      assert rc == 1

   def TestTryAutoFormatFixesCrlfToLf(self, tmp_path):
      """try-auto-format converts CRLF to LF and exits 0."""
      f = WriteBytes(tmp_path / "f.py", b"x = 1\r\ny = 2\r\n")
      rc = RunMain("fix", str(f))
      assert rc == 0
      assert b"\r" not in f.read_bytes()

   def TestCheckFormatReportsCf011ForCrlf(self, tmp_path):
      """check-format reports CF011 for a CRLF file."""
      f = WriteBytes(tmp_path / "my_module.py", b"X = 1\r\n")
      rc = RunMain("check", str(f))
      assert rc == 1

   def TestCheckFormatNoCf009NoiseFromCrlf(self, tmp_path):
      """
      A file with CRLF endings and an already-aligned self-assignment block
      must not produce CF009 violations purely because of CRLF.
      """
      # Build a CRLF file whose self-assignment block IS aligned after LF
      # normalisation. If the checker runs CF009 on raw CRLF lines,
      # the trailing \r on each line would make alignment calculations wrong
      # and produce false CF009 violations.
      lines = [
         "class A:\r\n",
         "   def __init__(self):\r\n",
         "      self.Name            = ''\r\n",
         "      self.Descr           = None\r\n",
         "      self.ShowInDatasheet = True\r\n",
      ]
      f = WriteBytes(tmp_path / "my_module.py",
                     b"".join(line.encode() for line in lines))
      RunMain("check", str(f))
      # CF011 fires (CRLF) but CF009 must NOT fire (block is aligned).
      from customfmt.checker import CheckFile
      viols = CheckFile(f)
      codes = {v.code for v in viols}
      assert "CF011" in codes
      assert "CF009" not in codes
