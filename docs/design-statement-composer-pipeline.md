# StatementComposer rename pipeline design

## Status and scope

PR #48 added `tests/fixtures/rename/statementComposer.input.txt`,
`tests/fixtures/rename/statementComposer.expected.txt`, and the strict xfail test
`TestStatementComposerFutureGoldenFixturePipeline`. The fixture is a planning
fixture for the final migration shape, not a request to broaden the existing
local rename pass until the golden output passes.

This document analyzes the full delta and assigns ownership for each kind of
change. It intentionally proposes no formatter or resolver behavior changes.

## Safety principles

* The existing local rename tool, `customfmt rename`, must remain a conservative
  token-position local planner.
* The existing local rename must not rename arbitrary attributes such as
  `repo.tableName`, `repo.pk`, `repo.model`, or `repo.references`.
* The existing local rename must not rename arbitrary method calls such as
  `statement_builder.where`, `statement_builder.select`, or
  `statement_builder.orderBy`.
* Project-wide symbol rename must be used for real function and imported symbol
  changes, including definitions, imports, and safely resolved references.
* Attribute/API casing requires a separate conservative design because attribute
  access is dynamic in Python and may refer to object state, properties,
  descriptors, external APIs, generated model fields, or duck-typed objects.

## Desired pipeline overview

The fixture should eventually be reached by composing multiple guarded tools and
manual API decisions, not by one broad local pass:

1. Run `customfmt rename` for local variable and, if explicitly implemented as a
   separate conservative extension, parameter casing inside function scopes.
2. Run `customfmt rename-symbol` for project symbols that have definitions and
   safely resolved imports/references, such as `composeStatement` to
   `ComposeStatement`, private helper functions, and `findRepo` to `FindRepo`.
3. Use future method/attribute rename support only for proven API owners where
   receiver types and declarations can be resolved conservatively.
4. Use manual/API migration for model fields, third-party or framework-reflected
   properties, and typo/API corrections that cannot be proven from the local
   file alone.

## Delta classification and ownership

| Transformation | Examples in fixture | Bucket | Owning tool/process |
| --- | --- | --- | --- |
| `statementBuilder` -> `statement_builder` | local assignment, argument passed to helpers, all reads in helper scopes | local variable rename / parameter rename | `customfmt rename` for the local variable; parameter support only if added as a conservative local-scope feature |
| `includesRepos` -> `includes_repos` | accumulator list in `ComposeStatement` | local variable rename | `customfmt rename` |
| `tableReference` -> `table_reference` | loop target and reads | local variable rename | `customfmt rename` |
| `targetRepo` -> `target_repo` | local results from repository lookup | local variable rename | `customfmt rename` |
| `previousCondition` -> `previous_condition` | local loop state in condition chaining | local variable rename | `customfmt rename` |
| `isPrimaryKeyInModelFields` -> `is_primary_key_in_model_fields` | local boolean in select builders | local variable rename | `customfmt rename` |
| `referenceMapping` -> `reference_mapping` | local dict returned from join builder | local variable rename | `customfmt rename` |
| `sourceTables` -> `source_tables` | local set in join builder | local variable rename | `customfmt rename` |
| `tableTuple` -> `table_tuple` | local tuple for references | local variable rename | `customfmt rename` |
| `keyRef` -> `key_ref` | local tuple value in reversed-reference branch | local variable rename | `customfmt rename` |
| `isInnerJoin` -> `is_inner_join` | `for inc, isInnerJoin in tables` binding | local variable rename / parameter-like loop binding | `customfmt rename` |
| `composeStatement` -> `ComposeStatement` | top-level function definition | function definition rename | `customfmt rename-symbol` |
| `__buildConditions` -> `__BuildConditions` | private helper definition and same-file calls | private helper function rename | `customfmt rename-symbol` |
| `__chainConditions` -> `__ChainConditions` | private helper definition and recursive/same-file calls | private helper function rename | `customfmt rename-symbol` |
| `__addSelectsFromTargetTable` -> `__AddSelectsFromTargetTable` | private helper definition and same-file call | private helper function rename | `customfmt rename-symbol` |
| `__addJoinedTables` -> `__AddJoinedTables` | private helper definition and same-file call | private helper function rename | `customfmt rename-symbol` |
| `from repos.Util.repositoryLocator import findRepo` -> `FindRepo` | import binding and call sites | imported symbol rename | `customfmt rename-symbol`, after project refs prove the imported definition and all safe references |
| `statement_builder.fromTable` -> `FromTable` | statement-builder fluent API calls | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.orderBy` -> `OrderBy` | statement-builder fluent API calls | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.getKWArgs` -> `GetKWArgs` | statement-builder result extraction | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.openBracket` -> `OpenBracket` | statement-builder grouping API | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.where` -> `Where` | statement-builder predicate API | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.andWhere` -> `AndWhere` and `orWhere` -> `OrWhere` | condition chain API | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.closeBracket` -> `CloseBracket` | statement-builder grouping API | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.select` -> `Select` | select-list API | method call rename | future method/attribute rename support, not `customfmt rename` |
| `statement_builder.include` -> `Include` and `includeOptional` -> `IncludeOptional` | join API calls | method call rename | future method/attribute rename support, not `customfmt rename` |
| `repo.tableName`, `rep.tableName`, `inc.tableName`, `target_repo.tableName` -> `TableName` | repository attributes used for SQL aliases and references | object attribute rename | future method/attribute rename support if repository declarations are proven; otherwise manual/API migration |
| `repo.pk`, `inc.pk` -> `Pk` | repository primary-key metadata | object attribute rename | future method/attribute rename support if declarations are proven; otherwise manual/API migration |
| `repo.references`, `inc.references` -> `References` | repository relationship metadata | object attribute rename | future method/attribute rename support if declarations are proven; otherwise manual/API migration |
| `repo.model`, `inc.model` -> `Model` | repository model metadata | object attribute rename | future method/attribute rename support if declarations are proven; otherwise manual/API migration |
| `conditions[*].modelType` -> `ModelType` | conditional statement model reference | model field/property rename | manual/API migration unless a future attribute planner can prove the `ConditionalStatement` field declaration and all safe references |
| `conditions[*].fieldName` -> `FieldName` | conditional statement field reference | model field/property rename | manual/API migration unless proven by future attribute support |
| `conditions[*].operation` -> `Operation` | conditional statement operation reference | model field/property rename | manual/API migration unless proven by future attribute support |
| `conditions[*].condition` -> `Condition` | conditional statement value reference | model field/property rename | manual/API migration unless proven by future attribute support |
| `previous_condition.nextCondition` -> `NextCondition` | chain condition link property | model field/property rename | manual/API migration unless proven by future attribute support |
| `statementBuilder.closeBreacket()` -> `statement_builder.CloseBracket()` | misspelled API call in input | typo/API correction | manual/API migration only; should not be inferred by rename tools |

## Bucket ownership details

### `customfmt rename`

`customfmt rename` owns local casing fixes for variables and local bindings in a
single function or method scope. In this fixture that includes local assignments,
loop targets, and local reads such as `tableTuple`, `keyRef`, and
`isPrimaryKeyInModelFields`.

Parameter casing is listed separately because parameters can be API surface. If
`statementBuilder` parameters are renamed to `statement_builder`, that should be
an explicit conservative extension with tests for call compatibility, keyword
arguments, decorators, overrides, and public API boundaries. It must still remain
local-scope token rewriting and must not become attribute or project-symbol
rewriting.

### `customfmt rename-symbol`

`customfmt rename-symbol` owns real project symbols: top-level function
renames, private helper function renames, and imported symbol renames where
project refs can prove the target and references. It should handle the
`composeStatement` and private helper definition/call changes, and the
`findRepo` import/call migration, through guarded token plans.

### Future method/attribute rename support

Method calls and object attributes need a separate conservative design. A safe
version would need to prove receiver type, declaration ownership, import graph,
subclass/override risks, dynamic reference exclusions, and complete affected
references before applying edits. It must reject or skip dynamic receivers such
as untyped `repo`, `inc`, and `target_repo` unless their concrete declarations
and all relevant references are proven.

This future support is where `statement_builder.Where`, `repo.TableName`,
`repo.Pk`, and similar API-casing changes belong. They must not be smuggled into
`customfmt rename` by matching attribute text.

### Manual/API migration only

Some changes represent product API decisions rather than mechanically safe
renames. The `closeBreacket` to `CloseBracket` change is both a casing change
and a spelling correction, so it requires an explicit API migration decision.
Model and condition properties may also require manual migration when they are
framework-reflected, generated, serialized, or used dynamically.

## Test notes

`TestStatementComposerFutureGoldenFixturePipeline` must remain `xfail(strict=True)`
while the pipeline is incomplete. The current `customfmt rename --apply` result
is expected to cover only local-variable-style casing and therefore should not
match the golden fixture, which also includes project symbol renames,
import-binding renames, method-call casing, object attribute casing,
model/property casing, and the `closeBreacket` typo/API correction.

Keeping the xfail strict is useful: it preserves the desired end-to-end target
while preventing accidental unsafe broadening of the local rename planner. The
xfail should be removed only after each bucket above is implemented by its
correct owner with targeted tests and safety guards.
