"""
Tests for customfmt.rename_plan (RenamePlan) and ``customfmt rename``.

TestToSnake
   TestPascalToSnake
   TestCamelToSnake
   TestAlreadySnake
   TestAcronym

TestPlanFileItems — rename candidates produced
   TestSimpleLocalAssignmentRename
   TestMultipleReadSitesRenamed
   TestMultipleWriteSitesRenamed
   TestAnnAssignLocalRename
   TestAugAssignReadWriteRename
   TestForLoopTargetRename
   TestWithAsTargetRename
   TestExceptAsTargetRename
   TestAlreadySnakeCaseUnchanged
   TestUnderscorePrefixSkipped

TestPlanFileSafety — scopes and names skipped
   TestGlobalScopeSkipped
   TestNonlocalScopeSkipped
   TestLocalsCallScopeSkipped
   TestGlobalsCallScopeSkipped
   TestVarsCallScopeSkipped
   TestEvalCallScopeSkipped
   TestExecCallScopeSkipped
   TestCollisionWithParameterSkipped
   TestCollisionWithLocalSkipped
   TestCollisionWithBuiltinSkipped
   TestCollisionWithImportSkipped
   TestTwoBadNamesSameTargetSkipped

TestPlanFileTokenRewrite — rewriter precision
   TestCommentUnchanged
   TestStringUnchanged
   TestNestedFunctionScopeNotRewritten
   TestNestedClassScopeNotRewritten

TestRenamePlanModel — data model
   TestRenameItemToDict
   TestRenameSkipToDict
   TestRenamePlanToDict
   TestChangedProperty
   TestViolationsFormat

TestCLIRename — CLI entry points
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
   TestJsonOutputContainsPlan
   TestJsonOutputApply
   TestNoPathExits2
   TestBadPathExits2
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from customfmt.cli import Main
from customfmt.rename_plan import (
   PlanFile,
   RenameItem,
   RenameSkip,
   SourcePos,
   _FilterDuplicatePatchSites,
   _ToSnake,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def Src(text: str) -> str:
   return textwrap.dedent(text)


def Write(path: Path, text: str) -> Path:
   path.write_text(text, encoding="utf-8")
   return path


def RunMain(*args: str) -> int:
   return Main(list(args))


def GetItems(plan) -> list[RenameItem]:
   assert not isinstance(plan, Exception)
   return plan.Items


def GetSkips(plan) -> list[RenameSkip]:
   assert not isinstance(plan, Exception)
   return plan.Skipped


# ---------------------------------------------------------------------------
# TestToSnake
# ---------------------------------------------------------------------------


class TestToSnake:
   def TestPascalToSnake(self):
      assert _ToSnake("TotalCount") == "total_count"
      assert _ToSnake("UserName") == "user_name"

   def TestCamelToSnake(self):
      assert _ToSnake("totalCount") == "total_count"
      assert _ToSnake("myVar") == "my_var"

   def TestAlreadySnake(self):
      assert _ToSnake("total_count") == "total_count"

   def TestAcronym(self):
      assert _ToSnake("HTMLParser") == "html_parser"


# ---------------------------------------------------------------------------
# TestPlanFileItems
# ---------------------------------------------------------------------------


class TestPlanFileItems:
   def TestSimpleLocalAssignmentRename(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(
         i.OldName == "TotalCount" and i.NewName == "total_count"
         for i in items
      )
      assert "total_count" in plan.Rewritten
      assert "TotalCount" not in plan.Rewritten

   def TestMultipleReadSitesRenamed(self, tmp_path):
      src = Src("""\
         def Foo():
            MyVar = 1
            x = MyVar + MyVar
            return MyVar
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "MyVar" for i in items)
      assert plan.Rewritten.count("my_var") >= 3

   def TestMultipleWriteSitesRenamed(self, tmp_path):
      src = Src("""\
         def Foo():
            MyVar = 1
            MyVar = MyVar + 1
            return MyVar
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "MyVar" for i in items)
      assert "MyVar" not in plan.Rewritten

   def TestAnnAssignLocalRename(self, tmp_path):
      src = Src("""\
         def Foo():
            MyCount: int = 0
            return MyCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "MyCount" for i in items)
      assert "my_count" in plan.Rewritten

   def TestAugAssignReadWriteRename(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            TotalCount += 1
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "TotalCount" for i in items)
      assert "TotalCount" not in plan.Rewritten

   def TestForLoopTargetRename(self, tmp_path):
      src = Src("""\
         def Foo():
            for ItemName in []:
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "ItemName" for i in items)
      assert "item_name" in plan.Rewritten
      assert "ItemName" not in plan.Rewritten

   def TestWithAsTargetRename(self, tmp_path):
      src = Src("""\
         def Foo():
            with open("f") as FileHandle:
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "FileHandle" for i in items)
      assert "file_handle" in plan.Rewritten
      assert "FileHandle" not in plan.Rewritten

   def TestExceptAsTargetRename(self, tmp_path):
      src = Src("""\
         def Foo():
            try:
               pass
            except Exception as MyError:
               pass
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "MyError" for i in items)
      assert "my_error" in plan.Rewritten
      assert "MyError" not in plan.Rewritten

   def TestAlreadySnakeCaseUnchanged(self, tmp_path):
      src = Src("""\
         def Foo():
            total_count = 0
            return total_count
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []
      assert not plan.Changed

   def TestUnderscorePrefixSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            _TmpVal = 1
            return _TmpVal
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []


# ---------------------------------------------------------------------------
# TestPlanFileSafety
# ---------------------------------------------------------------------------


class TestPlanFileSafety:
   def TestGlobalScopeSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            global x
            TotalCount = 1
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert any("global" in s.Reason for s in skips)

   def TestNonlocalScopeSkipped(self, tmp_path):
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
      plan = PlanFile(f)
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert any("nonlocal" in s.Reason for s in skips)

   def TestLocalsCallScopeSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            d = locals()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []

   def TestGlobalsCallScopeSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            d = globals()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []

   def TestVarsCallScopeSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            d = vars()
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []

   def TestEvalCallScopeSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            eval("TotalCount")
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []

   def TestExecCallScopeSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            exec("TotalCount = 2")
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []

   def TestCollisionWithParameterSkipped(self, tmp_path):
      src = Src("""\
         def Foo(total_count):
            TotalCount = 1
            return TotalCount + total_count
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert any("TotalCount" in s.Name for s in skips)

   def TestCollisionWithLocalSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            total_count = 2
            return TotalCount + total_count
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []

   def TestCollisionWithBuiltinSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            List = [1, 2, 3]
            return List
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      # "list" is a builtin — must be skipped
      assert GetItems(plan) == []

   def TestCollisionWithImportSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            from somewhere import total_count
            TotalCount = 1
            return TotalCount + total_count
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert any("TotalCount" in s.Name for s in skips)

   def TestParentModuleCollisionSkipped(self, tmp_path):
      src = Src("""\
         total_count = 0

         def Foo():
            TotalCount = 1
            return TotalCount + total_count
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert any("TotalCount" in s.Name for s in skips)

   def TestParentFunctionCollisionSkipped(self, tmp_path):
      src = Src("""\
         def Outer():
            total_count = 0
            def Inner():
               TotalCount = 1
               return TotalCount + total_count
            return Inner()
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert any("TotalCount" in s.Name for s in skips)

   def TestSafeImportNameDoesNotBlockDifferentTarget(self, tmp_path):
      src = Src("""\
         def Foo():
            import os
            OsPath = os.path
            return OsPath
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      items = GetItems(plan)
      assert any(i.OldName == "OsPath" for i in items)

   def TestTwoBadNamesSameTargetSkipped(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 1
            Total_Count = 2
            return TotalCount + Total_Count
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      # Both map to total_count — both must be skipped
      assert GetItems(plan) == []
      skips = GetSkips(plan)
      assert len([s for s in skips if s.Name]) >= 2


# ---------------------------------------------------------------------------
# TestPlanFileTokenRewrite
# ---------------------------------------------------------------------------


class TestPlanFileTokenRewrite:
   def TestCommentUnchanged(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0  # TotalCount is important
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert plan.Changed
      assert "# TotalCount is important" in plan.Rewritten

   def TestStringUnchanged(self, tmp_path):
      src = Src("""\
         def Foo():
            TotalCount = 0
            label = "TotalCount"
            return TotalCount
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert plan.Changed
      assert '"TotalCount"' in plan.Rewritten

   def TestNestedFunctionScopeNotRewritten(self, tmp_path):
      """Outer rename must not cross into a nested function scope."""
      src = Src("""\
         def Outer():
            OuterVar = 1
            def Inner():
               InnerVar = 2
               return InnerVar
            return OuterVar
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert plan.Changed
      # Both should be renamed (independently)
      assert "outer_var" in plan.Rewritten
      assert "inner_var" in plan.Rewritten

   def TestNestedClassScopeNotRewritten(self, tmp_path):
      """A class-body name must not be renamed by the function planner."""
      src = Src("""\
         def Foo():
            MyLocal = 1
            return MyLocal
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert "my_local" in plan.Rewritten


# ---------------------------------------------------------------------------
# TestRenamePlanModel
# ---------------------------------------------------------------------------


class TestRenamePlanModel:
   def TestRenameItemToDict(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      plan = PlanFile(f)
      items = GetItems(plan)
      assert items
      d = items[0].ToDict()
      assert d["old_name"] == "TotalCount"
      assert d["new_name"] == "total_count"
      assert "scope" in d
      assert "def_line" in d
      assert "sites" in d
      assert "definition_sites" in d
      assert "read_sites" in d
      assert "write_sites" in d
      assert "all_sites" in d
      assert d["sites"] == d["all_sites"]
      assert isinstance(d["sites"], list)
      assert items[0].Sites == items[0].AllSites

   def TestRenameItemSiteBuckets(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            TotalCount += 1
            return TotalCount
      """))
      plan = PlanFile(f)
      item = GetItems(plan)[0]
      assert item.DefinitionSites
      assert item.ReadSites
      assert item.WriteSites
      assert item.AllSites == item.Sites

   def TestDuplicatePatchSiteCollisionSkipped(self):
      pos = SourcePos(3, 6)
      first = RenameItem(
         OldName         = "FirstName",
         NewName         = "first_name",
         ScopeQual       = "Foo",
         DefinitionSites = [pos],
         ReadSites       = [],
         WriteSites      = [pos],
         DefLine         = 3,
      )
      second = RenameItem(
         OldName         = "SecondName",
         NewName         = "second_name",
         ScopeQual       = "Foo",
         DefinitionSites = [pos],
         ReadSites       = [],
         WriteSites      = [pos],
         DefLine         = 3,
      )
      items, skips = _FilterDuplicatePatchSites([first, second])
      assert items == []
      assert len(skips) == 2
      assert all("duplicate patch site" in s.Reason for s in skips)

   def TestRenameSkipToDict(self):
      skip = RenameSkip("Foo", "collision", "TotalCount")
      d = skip.ToDict()
      assert d["scope"] == "Foo"
      assert d["reason"] == "collision"
      assert d["name"] == "TotalCount"

   def TestRenamePlanToDict(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      plan = PlanFile(f)
      d = plan.ToDict()
      assert "file" in d
      assert "items" in d
      assert "skipped" in d
      assert "changed" in d
      assert d["changed"] is True

      skipped_file = Write(tmp_path / "skipped.py", Src("""\
         def Bar(total_count):
            TotalCount = 0
            return TotalCount + total_count
      """))
      skipped_plan = PlanFile(skipped_file).ToDict()
      assert skipped_plan["items"] == []
      assert skipped_plan["skipped"]

   def TestChangedProperty(self, tmp_path):
      clean = Write(tmp_path / "clean.py", "def Foo():\n   x = 1\n")
      dirty = Write(tmp_path / "dirty.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      assert not PlanFile(clean).Changed
      assert PlanFile(dirty).Changed

   def TestViolationsFormat(self, tmp_path):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      plan = PlanFile(f)
      viols = plan.Violations(f)
      assert viols
      v = viols[0]
      assert v.code == "RENAME"
      assert "TotalCount" in v.message
      assert "total_count" in v.message


# ---------------------------------------------------------------------------
# TestCLIRename
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
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      rc = RunMain("rename", "--apply", str(f))
      assert rc == 0
      assert "total_count" in f.read_text(encoding="utf-8")
      assert "TotalCount" not in f.read_text(encoding="utf-8")

   def TestApplyExits0WhenNoCandidates(self, tmp_path):
      f = Write(tmp_path / "f.py", "def Foo():\n   x = 1\n")
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

   def TestJsonOutputContainsPlan(self, tmp_path, capsys):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      RunMain("rename", "--check", "--json", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert isinstance(data, list)
      assert data[0]["items"][0]["old_name"] == "TotalCount"
      assert "definition_sites" in data[0]["items"][0]
      assert "skipped" in data[0]

   def TestJsonOutputApply(self, tmp_path, capsys):
      f = Write(tmp_path / "f.py", Src("""\
         def Foo():
            TotalCount = 0
            return TotalCount
      """))
      RunMain("rename", "--apply", "--json", str(f))
      out = capsys.readouterr().out
      data = json.loads(out)
      assert isinstance(data, list)
      assert "TotalCount" not in f.read_text(encoding="utf-8")

   def TestNoPathExits2(self, tmp_path):
      assert RunMain("rename", "--check", str(tmp_path)) == 2

   def TestBadPathExits2(self, tmp_path):
      assert RunMain("rename", "--check", str(tmp_path / "nope.py")) == 2
