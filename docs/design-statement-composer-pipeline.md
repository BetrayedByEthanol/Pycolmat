# StatementComposer rename pipeline design

## Status and scope

PR #48 added `tests/fixtures/rename/statementComposer.input.txt`,
`tests/fixtures/rename/statementComposer.expected.txt`, and the strict xfail test
`TestStatementComposerFutureGoldenFixturePipeline`. The fixture is a planning
fixture for the final migration shape, not a request to broaden the existing
local rename pass until the golden output passes.

This document analyzes the full delta and assigns ownership for each kind of
change. It intentionally proposes no formatter or resolver behavior changes.

Phase 3 method-call and object-attribute casing is designed separately in
[`docs/design-method-attribute-rename.md`](design-method-attribute-rename.md).

## Safety principles

* The existing local rename tool, `customfmt rename`, must remain a conservative
  token-position local planner.
* The existing local rename must not rename arbitrary attributes such as
  `repo.tableName`, `repo.pk`, `repo.model`, or `repo.references`.
* The existing local rename must not rename arbitrary method calls such as
  `statement_builder.where`, `statement_builder.select`, or
  `statement_builder.orderBy`.
* Project-wide symbol rename must be used for real function and imported symbol
  changes, including definitions, imports, and safely resolved references. This
  function/import-symbol bucket is implemented for Phase 1.
* Attribute/API casing requires a separate conservative design because attribute
  access is dynamic in Python and may refer to object state, properties,
  descriptors, external APIs, generated model fields, or duck-typed objects.

## Desired pipeline overview

The fixture should eventually be reached by composing multiple guarded tools and
manual API decisions, not by one broad local pass:

1. Run `customfmt rename` for local variables and the implemented Phase 2
   private-helper parameter casing inside safe function scopes.
2. Run `customfmt rename-symbol` for project symbols that have definitions and
   safely resolved imports/references, such as `composeStatement` to
   `ComposeStatement`, private helper functions, and `findRepo` to `FindRepo`.
   This Phase 1 bucket is implemented; method, attribute, and API casing buckets
   remain future/manual work.
3. Use future method/attribute rename support only for proven API owners where
   receiver types and declarations can be resolved conservatively.
4. Use manual/API migration for model fields, third-party or framework-reflected
   properties, and typo/API corrections that cannot be proven from the local
   file alone.

## Delta classification and ownership

| Transformation | Examples in fixture | Bucket | Owning tool/process |
| --- | --- | --- | --- |
| `statementBuilder` -> `statement_builder` | local assignment, argument passed to helpers, all reads in helper scopes | local variable rename / parameter rename | `customfmt rename` for the local variable and Phase 2 private-helper parameter support |
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
| `statement_builder.fromTable` -> `FromTable` | statement-builder fluent API calls | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.orderBy` -> `OrderBy` | statement-builder fluent API calls | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.getKWArgs` -> `GetKWArgs` | statement-builder result extraction | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.openBracket` -> `OpenBracket` | statement-builder grouping API | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.where` -> `Where` | statement-builder predicate API | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.andWhere` -> `AndWhere` and `orWhere` -> `OrWhere` | condition chain API | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.closeBracket` -> `CloseBracket` | statement-builder grouping API | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder`; does not cover `closeBreacket` |
| `statement_builder.select` -> `Select` | select-list API | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
| `statement_builder.include` -> `Include` and `includeOptional` -> `IncludeOptional` | join API calls | method call rename | `customfmt rename-symbol` only when the receiver is proven to be a project-owned `StatementBuilder` |
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

### Phase 1 command sequence

Run the Phase 1 function/import-symbol bucket against a fixture copy with this
exact sequence:

```bash
customfmt rename-symbol <fixture-copy-root> --name composeStatement --to ComposeStatement --apply
customfmt rename-symbol <fixture-copy-root> --name __buildConditions --to __BuildConditions --apply
customfmt rename-symbol <fixture-copy-root> --name __chainConditions --to __ChainConditions --apply
customfmt rename-symbol <fixture-copy-root> --name __addSelectsFromTargetTable --to __AddSelectsFromTargetTable --apply
customfmt rename-symbol <fixture-copy-root> --name __addJoinedTables --to __AddJoinedTables --apply
customfmt rename-symbol <fixture-copy-root> --name findRepo --to FindRepo --apply
```

This sequence is intentionally limited to function definitions, private helper
definitions and direct helper calls, plus the safely resolved `FindRepo` import
binding and direct calls. It must leave local variables, method calls, and
attributes unchanged, including `statementBuilder`,
`statementBuilder.fromTable`, `statementBuilder.where`,
`statementBuilder.include`, `repo.tableName`, `repo.pk`, and
`previousCondition.nextCondition`.

### `customfmt rename`

`customfmt rename` owns local casing fixes for variables and local bindings in a
single function or method scope. In this fixture that includes local assignments,
loop targets, and local reads such as `tableTuple`, `keyRef`, and
`isPrimaryKeyInModelFields`.

Phase 2 implements a narrow parameter-casing extension for private helper
functions only. `customfmt rename` may rename direct parameters such as
`statementBuilder` to `statement_builder` only when the owning function name is
private/internal (`_` or `__` prefix), is not a method, has no decorators, uses
only ordinary parameters, and the old name does not appear in keyword-call
syntax in the analyzed file. The edit remains local-scope token rewriting: it
updates the parameter token and resolved local reads/writes in that function,
including receiver-name uses such as `statement_builder.where`, but it does not
rename the called attribute `where`. Public parameter rename, method parameter
rename, method-call casing, attribute casing, model/property casing, and typo/API
correction remain future/manual work.

### `customfmt rename-symbol`

`customfmt rename-symbol` owns real project symbols: top-level function
renames, private helper function renames, and imported symbol renames where
project refs can prove the target and references. Phase 1 implements this bucket
for `composeStatement`, private helper definition/call changes, and the
`findRepo` import/call migration through guarded token plans. It still does not
own method-call casing, arbitrary object attribute casing, model/property field
casing, or typo/API migrations.

### Phase 3C proven method-call smoke coverage

Method-call casing for the statement-builder bucket is supported only through
`customfmt rename-symbol` when the receiver type is proven and project-owned.
The Phase 3C smoke test uses an artificial statementComposer-style source file
with a project-local `StatementBuilder` stub so calls such as
`statement_builder.Where(...)`, `statement_builder.Include(...)`, and
`statement_builder.OrderBy(...)` can be planned from the method declarations and
validated call sites without hand-editing the target between rename phases. This
support must still reject dynamic receivers, external owners, inherited methods,
and incomplete method plans.

Phase 3C does not claim that the real statementComposer fixture helper-parameter
pipeline is complete. Inference for typed or call-threaded helper parameters,
such as proving every private-helper `statementBuilder` parameter is the same
project-owned builder created by `ComposeStatement`, remains a separate Phase 3D
design topic.

Object/model attributes remain outside this bucket. `repo.tableName`, `repo.pk`,
`repo.references`, `repo.model`, `conditions[*].modelType`,
`conditions[*].fieldName`, `conditions[*].operation`,
`conditions[*].condition`, and `previous_condition.nextCondition` must not be
changed by the method-call pipeline. They must not be smuggled into
`customfmt rename` by matching attribute text.

### Manual/API migration only

Some changes represent product API decisions rather than mechanically safe
renames. The `closeBreacket` to `CloseBracket` change is both a casing change
and a spelling correction, so it requires an explicit API migration decision
unless the fixture actually declares a `closeBracket` method and the call is an
exact proven reference to that declared method. Model and condition properties
may also require manual migration when they are framework-reflected, generated,
serialized, or used dynamically.

## Test notes

`TestStatementComposerFutureGoldenFixturePipeline` must remain `xfail(strict=True)`
while the pipeline is incomplete. The current `customfmt rename --apply` result
is expected to cover only local-variable-style casing plus Phase 2 private-helper
parameter casing and therefore should not match the golden fixture. Phase 3C adds
a targeted artificial method-call smoke test for proven project-owned
`StatementBuilder` receivers, but the full golden still includes object attribute
casing, model/property casing, and the `closeBreacket` typo/API correction.

Keeping the xfail strict is useful: it preserves the desired end-to-end target
while preventing accidental unsafe broadening of the local rename planner. The
xfail should be removed only after each bucket above is implemented by its
correct owner with targeted tests and safety guards.
