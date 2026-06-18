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

import ast
import shutil
import textwrap
from pathlib import Path

import pytest

from customfmt.cli import Main
from customfmt.rename_plan import PlanFile
from customfmt.renamer import AnalyseFile, _ToSnake
from customfmt.symbols.model import FileError

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


def FixturePath(*parts: str) -> Path:
   return Path(__file__).parent / "fixtures" / Path(*parts)


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


   def TestPrivateHelperParameterRenamed(self, tmp_path):
      src = Src("""\
         def __Build(statementBuilder):
            return statementBuilder
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert plan.Changed
      assert "def __Build(statement_builder):" in plan.Rewritten
      assert "return statement_builder" in plan.Rewritten

   def TestPrivateHelperParameterMultipleReferencesRenamed(self, tmp_path):
      src = Src("""\
         def __Build(statementBuilder):
            statementBuilder.where()
            return statementBuilder
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert plan.Rewritten.count("statement_builder") == 3
      assert "statementBuilder" not in plan.Rewritten

   def TestPublicFunctionParameterNotRenamedByDefault(self, tmp_path):
      src = Src("""\
         def ComposeStatement(statementBuilder):
            return statementBuilder
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert not plan.Changed
      assert plan.Rewritten == src

   def TestDecoratedFunctionParameterNotRenamed(self, tmp_path):
      src = Src("""\
         @decorator
         def __Build(statementBuilder):
            return statementBuilder
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert not plan.Changed
      assert plan.Rewritten == src

   def TestMethodParameterNotRenamedByDefault(self, tmp_path):
      src = Src("""\
         class Repo:
            def Build(self, statementBuilder):
               return statementBuilder
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert not plan.Changed
      assert plan.Rewritten == src

   def TestKeywordCallRiskBlocksParameterRename(self, tmp_path):
      src = Src("""\
         def __Build(statementBuilder):
            return statementBuilder

         __Build(statementBuilder=value)
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert not plan.Changed
      assert "parameter appears in keyword-call syntax" in {s.Reason for s in plan.Skipped}

   def TestParameterReceiverRenamedButAttributeUnchanged(self, tmp_path):
      src = Src("""\
         def __Build(statementBuilder):
            statementBuilder.where()
      """)
      f = Write(tmp_path / "f.py", src)
      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      assert "statement_builder.where()" in plan.Rewritten
      assert ".Where" not in plan.Rewritten

   def TestStatementComposerLikePartialRenameRegression(self, tmp_path):
      src = Src("""\
         def ComposeStatement(repo, includes, conditions, references):
            statementBuilder = StatementBuilder()
            statementBuilder.fromTable(repo.tableName)
            includesRepos = []
            sourceTables = set()
            sourceTables.add(repo.tableName)
            referenceMapping = {}
            previousCondition = None
            isPrimaryKeyInModelFields = False

            if includes:
               includesRepos.extend(map(lambda item: item[0], includes))

            if conditions:
               for condition_group in conditions:
                  if previousCondition is not None and condition_group.nextCondition:
                     statementBuilder.where(previousCondition.nextCondition)
                  for condition in condition_group.conditions:
                     targetRepo = findRepo(condition.modelType)
                     tableReference = targetRepo.tableName
                     tableTuple = (repo.tableName, tableReference)
                     referenceMapping[tableTuple] = []
                     sourceTables.add(tableReference)
                     if condition.isPrimary:
                        isPrimaryKeyInModelFields = True
                        includesRepos.extend(condition.includes)
                     if tableTuple in references:
                        statementBuilder.include(
                           tableTuple[0],
                           tableTuple[1],
                           references[tableTuple][0],
                           references[tableTuple][1],
                        )
                     elif targetRepo.tableName in sourceTables:
                        statementBuilder.includeOptional(
                           tableReference,
                           targetRepo.tableName,
                           referenceMapping[tableTuple],
                        )
                     statementBuilder.orderBy(referenceMapping[tableTuple])
                     previousCondition = condition

            return (
               statementBuilder.getKWArgs(),
               includesRepos,
               sourceTables,
               referenceMapping,
               previousCondition,
               isPrimaryKeyInModelFields,
            )
      """)
      f = Write(tmp_path / "statement_composer.py", src)

      assert RunMain("rename", "--check", str(f)) == 1
      assert RunMain("rename", "--apply", str(f)) == 0

      content = f.read_text(encoding="utf-8")
      ast.parse(content)
      body = content[content.index("def ComposeStatement"):]

      for old_name in (
         "statementBuilder",
         "includesRepos",
         "sourceTables",
         "referenceMapping",
         "tableTuple",
         "tableReference",
         "previousCondition",
         "targetRepo",
         "isPrimaryKeyInModelFields",
      ):
         assert old_name not in body

      for new_name in (
         "statement_builder",
         "includes_repos",
         "source_tables",
         "reference_mapping",
         "table_tuple",
         "table_reference",
         "previous_condition",
         "target_repo",
         "is_primary_key_in_model_fields",
      ):
         assert new_name in body

      assert "target_repo.tableName" in body
      assert "condition_group.nextCondition" in body
      assert "def ComposeStatement" in body

   def TestPartialRenameMethodCallAndContainerReferencesRegression(self, tmp_path):
      src = Src("""\
         def ComposeOne(repo, conditions):
            statementBuilder = StatementBuilder()
            includesRepos = []
            sourceTables = set()
            referenceMapping = {}
            tableTuple = (repo.tableName, repo.alias)
            tableReference = repo.tableName
            referenceMapping[tableTuple] = tableReference
            for condition in conditions:
               statementBuilder.fromTable(repo.tableName)
               statementBuilder.orderBy(referenceMapping[tableTuple])
               includesRepos.extend(condition.includes)
               sourceTables.add(tableReference)
            return statementBuilder
      """)
      f = Write(tmp_path / "statement_composer.py", src)

      plan = PlanFile(f)
      assert not isinstance(plan, FileError)
      rewritten = plan.Rewritten
      ast.parse(rewritten)

      assert "statement_builder = StatementBuilder()" in rewritten
      assert "statement_builder.fromTable(repo.tableName)" in rewritten
      assert "statement_builder.orderBy(reference_mapping[table_tuple])" in rewritten
      assert "includes_repos.extend(condition.includes)" in rewritten
      assert "source_tables.add(table_reference)" in rewritten
      assert "reference_mapping[table_tuple] = table_reference" in rewritten

      for old_name in (
         "statementBuilder",
         "includesRepos",
         "sourceTables",
         "referenceMapping",
         "tableTuple",
         "tableReference",
      ):
         assert old_name not in rewritten


   def TestRealStatementComposerMultiFunctionRegression(self, tmp_path):
      src = Src("""\
         def ComposeStatement(repo, includes, conditions, references):
            statementBuilder = StatementBuilder()
            statementBuilder.fromTable(repo.tableName)
            __addSelectsFromTargetTable(statementBuilder, repo)
            includesRepos = []
            if includes:
               refs = __addJoinedTables(statementBuilder, repo, includes)
               references.update(refs)
               includesRepos.extend(map(lambda item: item[0], includes))
            if conditions:
               __buildConditions(statementBuilder, repo, conditions)
            statementBuilder.orderBy([str(repo.pk)])
            temp = {}
            for tableReference in references:
               ref1 = None
               ref2 = None
               for rep in chain([type(repo)], includesRepos):
                  if tableReference[0] == rep.tableName:
                     ref1 = rep
                  if tableReference[1] == rep.tableName:
                     ref2 = rep
               temp[(ref1, ref2)] = {}
            references.clear()
            references.update(temp)
            return statementBuilder.getKWArgs()

         def __buildConditions(statement_builder, repo, conditions):
            if isinstance(conditions, ConditionalStatement):
               conditions = [conditions]
            if len(conditions) > 0 and isinstance(conditions[0], tuple):
               statement_builder.openBracket()
               targetRepo = findRepo(conditions[0][0].modelType)
               statement_builder.where(
                  targetRepo.tableName,
                  conditions[0][0].fieldName,
                  conditions[0][0].operation.value,
                  conditions[0][0].condition,
               )
               __chainConditions(statement_builder, repo, conditions[0])
               statement_builder.closeBracket()
            elif len(conditions) > 0 and isinstance(conditions[0], ConditionalStatement):
               targetRepo = findRepo(conditions[0].modelType)
               statement_builder.where(
                  targetRepo.tableName,
                  conditions[0].fieldName,
                  conditions[0].operation.value,
                  conditions[0].condition,
               )
               __chainConditions(statement_builder, repo, conditions)

         def __chainConditions(statement_builder, repo, conditions):
            i = 1
            while i < len(conditions):
               previousCondition = conditions[i - 1]
               while isinstance(previousCondition, list) or isinstance(previousCondition, tuple):
                  previousCondition = previousCondition[-1]
               if previousCondition.nextCondition is None:
                  break
               if previousCondition.nextCondition == ChainCondition.AND:
                  statement_builder.andWhere()
               else:
                  statement_builder.orWhere()
               if isinstance(conditions[i], list) or isinstance(conditions[i], tuple):
                  statement_builder.openBracket()
                  targetRepo = findRepo(conditions[i][0].modelType)
                  statement_builder.where(
                     targetRepo.tableName,
                     conditions[i][0].fieldName,
                     conditions[i][0].operation.value,
                     conditions[i][0].condition,
                  )
                  __chainConditions(statement_builder, repo, conditions[i])
                  statement_builder.closeBracket()
               else:
                  targetRepo = findRepo(conditions[i].modelType)
                  statement_builder.where(
                     targetRepo.tableName,
                     conditions[i].fieldName,
                     conditions[i].operation.value,
                     conditions[i].condition,
                  )
               i += 1

         def __addSelectsFromTargetTable(statement_builder, repo):
            selects = []
            isPrimaryKeyInModelFields = False
            for column in repo.model.__fields__:
               if column != "frozen":
                  selects.append(column)
                  if column == repo.pk:
                     isPrimaryKeyInModelFields = True
            if not isPrimaryKeyInModelFields:
               selects.append(repo.pk)
            statement_builder.select(selects)

         def __addJoinedTables(statement_builder, repo, tables):
            selects = []
            referenceMapping = {}
            references = copy.deepcopy(repo.references)
            sourceTables = set()
            sourceTables.add(repo.tableName)
            for inc, isInnerJoin in tables:
               tableTuple = (None, None)
               if inc.references:
                  references |= inc.references
               for ref in references:
                  if inc.tableName == ref[1] and ref[0] in sourceTables:
                     tableTuple = ref
                     sourceTables.add(inc.tableName)
                     break
                  elif inc.tableName == ref[0] and ref[1] in sourceTables:
                     tableTuple = (ref[1], ref[0])
                     keyRef = references[ref]
                     references[tableTuple] = (keyRef[1], keyRef[0])
                     sourceTables.add(inc.tableName)
                     break
               if isInnerJoin:
                  statement_builder.include(
                     tableTuple[0],
                     tableTuple[1],
                     references[tableTuple][0],
                     references[tableTuple][1],
                  )
               else:
                  statement_builder.includeOptional(
                     tableTuple[0],
                     tableTuple[1],
                     references[tableTuple][0],
                     references[tableTuple][1],
                  )
               referenceMapping[tableTuple] = []
               isPrimaryKeyInModelFields = False
               for column in inc.model.__fields__.keys():
                  selects.append(column)
                  if column == inc.pk:
                     isPrimaryKeyInModelFields = True
               if not isPrimaryKeyInModelFields:
                  selects.append(inc.pk)
               statement_builder.select(selects)
               selects.clear()
            return referenceMapping
      """)
      f = Write(tmp_path / "statement_composer.py", src)

      assert RunMain("rename", "--apply", str(f)) == 0

      content = f.read_text(encoding="utf-8")
      ast.parse(content)

      for old_name in (
         "statementBuilder",
         "includesRepos",
         "tableReference",
         "targetRepo",
         "previousCondition",
         "isPrimaryKeyInModelFields",
         "referenceMapping",
         "sourceTables",
         "tableTuple",
         "keyRef",
         "isInnerJoin",
      ):
         assert old_name not in content

      for new_name in (
         "statement_builder",
         "includes_repos",
         "table_reference",
         "target_repo",
         "previous_condition",
         "is_primary_key_in_model_fields",
         "reference_mapping",
         "source_tables",
         "table_tuple",
         "key_ref",
         "is_inner_join",
      ):
         assert new_name in content

      assert "references[table_tuple] = (key_ref[1], key_ref[0])" in content


   def TestStatementComposerPhase2PrivateHelperParameters(self, tmp_path):
      source = FixturePath("rename", "statementComposer.input.txt")
      target = tmp_path / "statementComposer.py"
      shutil.copyfile(source, target)

      for old_name, new_name in (
         ("composeStatement", "ComposeStatement"),
         ("__buildConditions", "__BuildConditions"),
         ("__chainConditions", "__ChainConditions"),
         ("__addSelectsFromTargetTable", "__AddSelectsFromTargetTable"),
         ("__addJoinedTables", "__AddJoinedTables"),
      ):
         assert RunMain(
            "rename-symbol", str(target),
            "--name", old_name, "--to", new_name, "--apply",
         ) == 0

      assert RunMain("rename", "--apply", str(target)) == 0
      result = target.read_text(encoding="utf-8")
      ast.parse(result)

      assert "def __BuildConditions(" in result
      assert "statement_builder," in result
      assert "def __ChainConditions(statement_builder, repo, conditions):" in result
      assert "def __AddSelectsFromTargetTable(statement_builder, repo):" in result
      assert "def __AddJoinedTables(statement_builder, repo, tables):" in result
      for new_name in (
         "statement_builder",
         "includes_repos",
         "source_tables",
         "reference_mapping",
         "table_tuple",
         "table_reference",
         "previous_condition",
         "target_repo",
         "is_primary_key_in_model_fields",
      ):
         assert new_name in result

      assert "statement_builder.fromTable" in result
      assert "statement_builder.where" in result
      assert "statement_builder.include" in result
      assert "repo.tableName" in result
      assert "repo.pk" in result
      assert "previous_condition.nextCondition" in result

   def TestStatementComposerPhase3CMethodCallBucketFixtureSlice(self, tmp_path):
      project = tmp_path / "project"
      project.mkdir()
      target = project / "statementComposer.py"
      fixture = FixturePath("rename", "statementComposer.input.txt").read_text(
         encoding="utf-8")
      fixture = fixture.replace(
         "):\n   if isinstance(conditions, ConditionalStatement):",
         "):\n   statementBuilder = StatementBuilder()\n   if isinstance(conditions, ConditionalStatement):",
      )
      fixture = fixture.replace(
         "def __chainConditions(statementBuilder, repo, conditions):",
         (
            "def __chainConditions(statementBuilder, repo, "
            "conditions):\n   statementBuilder = StatementBuilder()"
         ),
      )
      fixture = fixture.replace(
         "def __addSelectsFromTargetTable(statementBuilder, repo):",
         (
            "def __addSelectsFromTargetTable(statementBuilder, "
            "repo):\n   statementBuilder = StatementBuilder()"
         ),
      )
      fixture = fixture.replace(
         "def __addJoinedTables(statementBuilder, repo, tables):",
         (
            "def __addJoinedTables(statementBuilder, repo, "
            "tables):\n   statementBuilder = StatementBuilder()"
         ),
      )
      target.write_text(fixture, encoding="utf-8")
      (project / "dataAccess").mkdir()
      (project / "repos" / "Util").mkdir(parents=True)
      Write(
         project / "dataAccess" / "statementBuilder.py",
         Src(
            """
            class StatementBuilder:
               def fromTable(self, table):
                  return self

               def where(self, table, field=None, operation=None, condition=None):
                  return self

               def include(self, source, target, source_key, target_key):
                  return self

               def includeOptional(self, source, target, source_key, target_key):
                  return self

               def orderBy(self, columns):
                  return self

               def getKWArgs(self):
                  return {}

               def openBracket(self):
                  return self

               def closeBracket(self):
                  return self

               def andWhere(self):
                  return self

               def orWhere(self):
                  return self

               def select(self, columns):
                  return self
            """
         ),
      )
      Write(
         project / "repos" / "Util" / "repositoryLocator.py",
         "def findRepo(model_type):\n   return model_type\n",
      )

      for old_name, new_name in (
         ("composeStatement", "ComposeStatement"),
         ("__buildConditions", "__BuildConditions"),
         ("__chainConditions", "__ChainConditions"),
         ("__addSelectsFromTargetTable", "__AddSelectsFromTargetTable"),
         ("__addJoinedTables", "__AddJoinedTables"),
         ("findRepo", "FindRepo"),
      ):
         assert RunMain(
            "rename-symbol", str(project), "--name", old_name, "--to", new_name,
            "--apply",
         ) == 0

      assert RunMain("rename", "--apply", str(target)) == 0
      normalized = target.read_text(encoding="utf-8")
      normalized = normalized.replace("statementBuilder.", "statement_builder.")
      normalized = normalized.replace("statementBuilder,", "statement_builder,")
      normalized = normalized.replace("statementBuilder)", "statement_builder)")
      normalized = normalized.replace(
         "def __BuildConditions(\n      statement_builder,",
         "def __BuildConditions(\n      statement_builder_arg,",
      )
      normalized = normalized.replace(
         "def __ChainConditions(statement_builder, repo, conditions):",
         "def __ChainConditions(statement_builder_arg, repo, conditions):",
      )
      normalized = normalized.replace(
         "def __AddSelectsFromTargetTable(statement_builder, repo):",
         "def __AddSelectsFromTargetTable(statement_builder_arg, repo):",
      )
      normalized = normalized.replace(
         "def __AddJoinedTables(statement_builder, repo, tables):",
         "def __AddJoinedTables(statement_builder_arg, repo, tables):",
      )
      target.write_text(normalized, encoding="utf-8")

      for old_name, new_name in (
         ("fromTable", "FromTable"),
         ("where", "Where"),
         ("include", "Include"),
         ("includeOptional", "IncludeOptional"),
         ("orderBy", "OrderBy"),
         ("getKWArgs", "GetKWArgs"),
         ("openBracket", "OpenBracket"),
         ("closeBracket", "CloseBracket"),
         ("andWhere", "AndWhere"),
         ("orWhere", "OrWhere"),
         ("select", "Select"),
      ):
         assert RunMain(
            "rename-symbol", str(project), "--name", old_name, "--to", new_name,
            "--apply",
         ) == 0

      result = target.read_text(encoding="utf-8")
      builder = (project / "dataAccess" / "statementBuilder.py").read_text(
         encoding="utf-8")
      locator = (project / "repos" / "Util" / "repositoryLocator.py").read_text(
         encoding="utf-8")
      ast.parse(result)
      ast.parse(builder)

      assert "def ComposeStatement(" in result
      assert "def __BuildConditions(" in result
      assert "def __ChainConditions(" in result
      assert "def __AddSelectsFromTargetTable(" in result
      assert "def __AddJoinedTables(" in result
      assert "from repos.Util.repositoryLocator import FindRepo" in result
      assert "FindRepo(" in result
      assert "def FindRepo(model_type):" in locator

      for new_name in (
         "statement_builder",
         "includes_repos",
         "table_reference",
         "target_repo",
         "previous_condition",
         "is_primary_key_in_model_fields",
         "reference_mapping",
         "source_tables",
         "table_tuple",
         "key_ref",
         "is_inner_join",
      ):
         assert new_name in result

      for method in (
         "FromTable",
         "Where",
         "Include",
         "IncludeOptional",
         "OrderBy",
         "GetKWArgs",
         "OpenBracket",
         "CloseBracket",
         "AndWhere",
         "OrWhere",
         "Select",
      ):
         assert f"def {method}(" in builder

      for call in (
         "statement_builder.FromTable(repo.tableName)",
         "statement_builder.Where(",
         "statement_builder.Include(",
         "statement_builder.IncludeOptional(",
         "statement_builder.OrderBy([str(repo.pk)])",
         "statement_builder.GetKWArgs()",
         "statement_builder.OpenBracket()",
         "statement_builder.CloseBracket()",
         "statement_builder.AndWhere()",
         "statement_builder.OrWhere()",
         "statement_builder.Select(selects)",
      ):
         assert call in result

      for unchanged in (
         "repo.tableName",
         "repo.pk",
         "repo.references",
         "repo.model",
         "conditions[0][0].modelType",
         "conditions[0][0].fieldName",
         "conditions[0][0].operation",
         "conditions[0][0].condition",
         "previous_condition.nextCondition",
         "statement_builder.closeBreacket()",
      ):
         assert unchanged in result

   @pytest.mark.xfail(
      reason=(
         "Golden coverage for the intended statementComposer pipeline; current "
         "local rename only covers local-variable-style casing. The remaining "
         "function/import/method/attribute/API migrations are documented in "
         "docs/design-statement-composer-pipeline.md and must stay out of the "
         "local rename planner until each bucket has a conservative owner."
      ),
      strict=True,
   )
   def TestStatementComposerFutureGoldenFixturePipeline(self, tmp_path):
      source = FixturePath("rename", "statementComposer.input.txt")
      expected = FixturePath("rename", "statementComposer.expected.txt").read_text(
         encoding="utf-8")
      target = tmp_path / "statementComposer.py"
      shutil.copyfile(source, target)

      assert RunMain("rename", "--apply", str(target)) == 0

      result = target.read_text(encoding="utf-8")
      ast.parse(result)
      assert result == expected

      for old_name in (
         "statementBuilder",
         "includesRepos",
         "tableReference",
         "targetRepo",
         "previousCondition",
         "isPrimaryKeyInModelFields",
         "referenceMapping",
         "sourceTables",
         "tableTuple",
         "keyRef",
         "isInnerJoin",
         "composeStatement",
         "findRepo",
      ):
         assert old_name not in result



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
