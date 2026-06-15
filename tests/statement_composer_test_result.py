import copy
import typing
from datetime import datetime
from decimal import Decimal
from enum import Enum
from itertools import chain
from typing import Sequence

from dataAccess.statementBuilder import StatementBuilder
from repos.baseRepo import BaseRepo
from repos.Util.ConditionalStatement import ChainCondition, ConditionalStatement
from repos.Util.repositoryLocator import FindRepo


def ComposeStatement(
      repo: BaseRepo,
      includes: list[tuple[BaseRepo, bool]] | None,
      conditions: Sequence[ConditionalStatement | list | tuple]
                  | ConditionalStatement
                  | None,
      references: dict,
):
   statement_builder = StatementBuilder()

   statement_builder.FromTable(repo.TableName)

   __AddSelectsFromTargetTable(statement_builder, repo)
   includes_repos = []

   if includes:
      refs = __AddJoinedTables(statement_builder, repo, includes)
      references.update(refs)
      includes_repos.extend(map(lambda x: x[0], includes))

   if conditions:
      __BuildConditions(statement_builder, repo, conditions)

   statement_builder.OrderBy([str(repo.Pk)])

   temp = {}
   for table_reference in references:
      ref1 = None
      ref2 = None
      for rep in chain([type(repo)], includes_repos):
         if table_reference[0] == rep.TableName:
            ref1 = rep
         if table_reference[1] == rep.TableName:
            ref2 = rep
      temp[(ref1, ref2)] = {}
   references.clear()
   references.update(temp)
   return statement_builder.GetKWArgs()


def __BuildConditions(
      statement_builder,
      repo,
      conditions: Sequence[ConditionalStatement | list | tuple] | ConditionalStatement,
):
   if isinstance(conditions, ConditionalStatement):
      conditions = [conditions]
   if (
         (isinstance(conditions[0], type(list)) or isinstance(conditions[0], tuple))
         and len(conditions) > 0
         and len(conditions[0])  # NOQA Doesnt recognize nested list
   ):
      statement_builder.OpenBracket()
      target_repo = FindRepo(conditions[0][0].ModelType)  # NOQA
      statement_builder.Where(
         target_repo.TableName,
         conditions[0][0].FieldName,  # NOQA
         conditions[0][0].Operation.value,  # NOQA
         conditions[0][0].Condition,  # NOQA
      )
      __ChainConditions(statement_builder, repo, conditions[0])  # NOQA
      statement_builder.CloseBracket()
   elif len(conditions) > 0 and isinstance(conditions[0], ConditionalStatement):
      target_repo = FindRepo(conditions[0].ModelType)
      statement_builder.Where(
         target_repo.TableName,
         conditions[0].FieldName,
         conditions[0].Operation.value,
         conditions[0].Condition,
      )
      __ChainConditions(statement_builder, repo, conditions)


def __ChainConditions(statement_builder, repo, conditions):
   i = 1
   while i < len(conditions):
      previous_condition = conditions[i - 1]
      while isinstance(previous_condition, list) or isinstance(previous_condition, tuple):
         previous_condition = previous_condition[-1]
      if previous_condition.NextCondition is None:
         break
      if previous_condition.NextCondition == ChainCondition.AND:
         statement_builder.AndWhere()
      else:
         statement_builder.OrWhere()
      if isinstance(conditions[i], list) or isinstance(conditions[i], tuple):
         statement_builder.OpenBracket()
         target_repo = FindRepo(conditions[i][0].ModelType)
         statement_builder.Where(
            target_repo.TableName,
            conditions[i][0].FieldName,
            conditions[i][0].Operation.value,
            conditions[i][0].Condition,
         )
         __ChainConditions(statement_builder, repo, conditions[i])
         statement_builder.CloseBracket()
      else:
         target_repo = FindRepo(conditions[i].ModelType)
         statement_builder.Where(
            target_repo.TableName,
            conditions[i].FieldName,
            conditions[i].Operation.value,
            conditions[i].Condition,
         )
      i += 1


def __AddSelectsFromTargetTable(statement_builder, repo):
   selects = []
   is_primary_key_in_model_fields = False
   for column in repo.Model.__fields__:
      if column != "frozen" and (
            repo.Model.__fields__[column].annotation.__args__[0]
            in (int, bytes, datetime, str, float, bool, Decimal, Enum)
            or (
                  typing.get_origin(
                     repo.Model.__fields__[column].annotation.__args__[0])
                  is not typing.Union
                  and isinstance(repo.Model.__fields__[column].annotation.__args__[0],
                                 type)
                  and issubclass(repo.Model.__fields__[column].annotation.__args__[0],
                                 Enum)
            )
      ):
         selects.append(f"{column} AS '{repo.TableName}.{column}'")
         if column == repo.Pk:
            is_primary_key_in_model_fields = True
   if not is_primary_key_in_model_fields:
      selects.append(f"{repo.Pk} AS '{repo.TableName}.{repo.Pk}'")
   statement_builder.Select(selects)


def __AddJoinedTables(statement_builder, repo, tables):
   selects = []
   reference_mapping = {}
   references = copy.deepcopy(repo.References)
   source_tables = set()
   source_tables.add(repo.TableName)
   for inc, is_inner_join in tables:
      table_tuple = (None, None)
      if inc.References:
         references |= inc.References
      for ref in references:
         if inc.TableName == ref[1] and ref[0] in source_tables:
            table_tuple = ref
            source_tables.add(inc.TableName)
            break
         elif inc.TableName == ref[0] and ref[1] in source_tables:
            table_tuple = (ref[1], ref[0])
            key_ref = references[ref]
            references[table_tuple] = (key_ref[1], key_ref[0])
            source_tables.add(inc.TableName)
            break
      if is_inner_join:
         statement_builder.Include(
            table_tuple[0],
            table_tuple[1],
            references[table_tuple][0],
            references[table_tuple][1],
         )
      else:
         statement_builder.IncludeOptional(
            table_tuple[0],
            table_tuple[1],
            references[table_tuple][0],
            references[table_tuple][1],
         )
      reference_mapping[table_tuple] = []
      is_primary_key_in_model_fields = False
      for column in inc.Model.__fields__.keys():
         if (
               typing.get_origin(inc.Model.__fields__[column].annotation.__args__[0])
               is typing.Union
         ):
            continue
         if not column.startswith("_") and (
               inc.Model.__fields__[column].annotation.__args__[0]
               in (int, datetime, str, float, bool, Decimal)
               or (isinstance(inc.Model.__fields__[column].annotation.__args__[0], type)
                   and issubclass(inc.Model.__fields__[column].annotation.__args__[0],
                                  Enum))
         ):
            selects.append(f"{column} AS '{inc.TableName}.{column}'")
            if column == inc.Pk:
               is_primary_key_in_model_fields = True
      if not is_primary_key_in_model_fields:
         selects.append(f"{inc.Pk} AS '{inc.TableName}.{inc.Pk}'")
      statement_builder.Select(selects)
      selects.clear()
   return reference_mapping
