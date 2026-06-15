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
from repos.Util.repositoryLocator import findRepo


def composeStatement(
      repo: BaseRepo,
      includes: list[tuple[BaseRepo, bool]] | None,
      conditions: Sequence[ConditionalStatement | list | tuple]
                  | ConditionalStatement
                  | None,
      references: dict,
):
   statementBuilder = StatementBuilder()

   statementBuilder.fromTable(repo.tableName)

   __addSelectsFromTargetTable(statementBuilder, repo)
   includesRepos = []

   if includes:
      refs = __addJoinedTables(statementBuilder, repo, includes)
      references.update(refs)
      includesRepos.extend(map(lambda x: x[0], includes))

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


def __buildConditions(
      statementBuilder,
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
      statementBuilder.openBracket()
      targetRepo = findRepo(conditions[0][0].modelType)  # NOQA
      statementBuilder.where(
         targetRepo.tableName,
         conditions[0][0].fieldName,  # NOQA
         conditions[0][0].operation.value,  # NOQA
         conditions[0][0].condition,  # NOQA
      )
      __chainConditions(statementBuilder, repo, conditions[0])  # NOQA
      statementBuilder.closeBreacket()
   elif len(conditions) > 0 and isinstance(conditions[0], ConditionalStatement):
      targetRepo = findRepo(conditions[0].modelType)
      statementBuilder.where(
         targetRepo.tableName,
         conditions[0].fieldName,
         conditions[0].operation.value,
         conditions[0].condition,
      )
      __chainConditions(statementBuilder, repo, conditions)


def __chainConditions(statementBuilder, repo, conditions):
   i = 1
   while i < len(conditions):
      previousCondition = conditions[i - 1]
      while isinstance(previousCondition, list) or isinstance(previousCondition, tuple):
         previousCondition = previousCondition[-1]
      if previousCondition.nextCondition is None:
         break
      if previousCondition.nextCondition == ChainCondition.AND:
         statementBuilder.andWhere()
      else:
         statementBuilder.orWhere()
      if isinstance(conditions[i], list) or isinstance(conditions[i], tuple):
         statementBuilder.openBracket()
         targetRepo = findRepo(conditions[i][0].modelType)
         statementBuilder.where(
            targetRepo.tableName,
            conditions[i][0].fieldName,
            conditions[i][0].operation.value,
            conditions[i][0].condition,
         )
         __chainConditions(statementBuilder, repo, conditions[i])
         statementBuilder.closeBracket()
      else:
         targetRepo = findRepo(conditions[i].modelType)
         statementBuilder.where(
            targetRepo.tableName,
            conditions[i].fieldName,
            conditions[i].operation.value,
            conditions[i].condition,
         )
      i += 1


def __addSelectsFromTargetTable(statementBuilder, repo):
   selects = []
   isPrimaryKeyInModelFields = False
   for column in repo.model.__fields__:
      if column != "frozen" and (
            repo.model.__fields__[column].annotation.__args__[0]
            in (int, bytes, datetime, str, float, bool, Decimal, Enum)
            or (
                  typing.get_origin(
                     repo.model.__fields__[column].annotation.__args__[0])
                  is not typing.Union
                  and isinstance(repo.model.__fields__[column].annotation.__args__[0],
                                 type)
                  and issubclass(repo.model.__fields__[column].annotation.__args__[0],
                                 Enum)
            )
      ):
         selects.append(f"{column} AS '{repo.tableName}.{column}'")
         if column == repo.pk:
            isPrimaryKeyInModelFields = True
   if not isPrimaryKeyInModelFields:
      selects.append(f"{repo.pk} AS '{repo.tableName}.{repo.pk}'")
   statementBuilder.select(selects)


def __addJoinedTables(statementBuilder, repo, tables):
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
         statementBuilder.include(
            tableTuple[0],
            tableTuple[1],
            references[tableTuple][0],
            references[tableTuple][1],
         )
      else:
         statementBuilder.includeOptional(
            tableTuple[0],
            tableTuple[1],
            references[tableTuple][0],
            references[tableTuple][1],
         )
      referenceMapping[tableTuple] = []
      isPrimaryKeyInModelFields = False
      for column in inc.model.__fields__.keys():
         if (
               typing.get_origin(inc.model.__fields__[column].annotation.__args__[0])
               is typing.Union
         ):
            continue
         if not column.startswith("_") and (
               inc.model.__fields__[column].annotation.__args__[0]
               in (int, datetime, str, float, bool, Decimal)
               or (isinstance(inc.model.__fields__[column].annotation.__args__[0], type)
                   and issubclass(inc.model.__fields__[column].annotation.__args__[0],
                                  Enum))
         ):
            selects.append(f"{column} AS '{inc.tableName}.{column}'")
            if column == inc.pk:
               isPrimaryKeyInModelFields = True
      if not isPrimaryKeyInModelFields:
         selects.append(f"{inc.pk} AS '{inc.tableName}.{inc.pk}'")
      statementBuilder.select(selects)
      selects.clear()
   return referenceMapping
