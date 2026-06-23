# StatementComposer rename pipeline design

## Status and scope

PR #48 added `tests/fixtures/rename/statementComposer.input.txt`,
`tests/fixtures/rename/statementComposer.expected.txt`, and the strict xfail test
`TestStatementComposerFutureGoldenFixturePipeline`. The fixture is a planning
fixture for the final migration shape, not a request to broaden the existing
local rename pass until the golden output passes.

This document analyzes the full delta and assigns ownership for each kind of
change. It intentionally proposes no formatter or resolver behavior changes.

Phase 3 method-call support and Phase 4 object-attribute rename design are
described separately in
[`docs/design-method-attribute-rename.md`](design-method-attribute-rename.md).
Phase 4B is design-only: it defines the future guarded object-attribute apply
boundary and test plan, but it does not implement object-attribute writes.

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
   This Phase 1 bucket is implemented; method support is covered only for
   proven project-owned receiver types, and object/model attribute or API casing
   buckets remain future/manual work.
3. Use method rename support only for proven project-owned receiver types, and
   use future object-attribute rename support only when the project-owned class
   declaration, attribute declaration, receiver type, and all reads/writes are
   proven conservatively.
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
| `repo.tableName`, `rep.tableName`, `inc.tableName`, `target_repo.tableName` -> `TableName` | repository attributes used for SQL aliases and references | object attribute rename | future `rename-attribute` or `rename-symbol --attribute` only if `BaseRepo`/subclass ownership and declarations are proven; otherwise manual/API migration |
| `repo.pk`, `inc.pk` -> `Pk` | repository primary-key metadata | object attribute rename | future `rename-attribute` or `rename-symbol --attribute` only if `BaseRepo`/subclass ownership and declarations are proven; otherwise manual/API migration |
| `repo.references`, `inc.references` -> `References` | repository relationship metadata | object attribute rename | future `rename-attribute` or `rename-symbol --attribute` only if `BaseRepo`/subclass ownership and declarations are proven; otherwise manual/API migration |
| `repo.model`, `inc.model` -> `Model` | repository model metadata | object attribute rename | future `rename-attribute` or `rename-symbol --attribute` only if `BaseRepo`/subclass ownership and declarations are proven; otherwise manual/API migration |
| `conditions[*].modelType` -> `ModelType` | conditional statement model reference | model field/property rename | manual/API migration unless a future attribute planner proves declarations, ownership, all safe references, and serialization implications |
| `conditions[*].fieldName` -> `FieldName` | conditional statement field reference | model field/property rename | manual/API migration unless declarations, ownership, all safe references, and serialization implications are proven |
| `conditions[*].operation` -> `Operation` | conditional statement operation reference | model field/property rename | manual/API migration unless declarations, ownership, all safe references, and serialization implications are proven |
| `conditions[*].condition` -> `Condition` | conditional statement value reference | model field/property rename | manual/API migration unless declarations, ownership, all safe references, and serialization implications are proven |
| `previous_condition.nextCondition` -> `NextCondition` | chain condition link property | model field/property rename | manual/API migration unless declarations, ownership, all safe references, and serialization implications are proven |
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

Phase 3D adds the read-only bridge for helper-parameter receiver inference:
when `ComposeStatement` creates a project-owned `StatementBuilder` and passes it
positionally into project-owned helpers, `customfmt refs` may prove helper calls
such as `statement_builder.where`, `statement_builder.include`,
`statement_builder.orderBy`, and `statement_builder.select` as method references.
This remains proof-first discovery; guarded method rename may use it only when
existing completeness checks prove the whole plan safe.

The full real statementComposer golden xfail remains in place. Phase 3D does
not claim the entire statementComposer migration is automatic and does not move
object/model attribute casing into the method-call bucket.

Object/model attributes remain outside this bucket. `repo.tableName`, `repo.pk`,
`repo.references`, `repo.model`, `conditions[*].modelType`,
`conditions[*].fieldName`, `conditions[*].operation`,
`conditions[*].condition`, and `previous_condition.nextCondition` must not be
changed by the method-call pipeline. They must not be smuggled into
`customfmt rename` by matching attribute text.

### Phase 4 object-attribute rename design

Phase 4A implements read-only discovery for simple project-owned class-attribute
references when the receiver type and direct class-body declaration are proven.
Phase 4B defines the future guarded apply contract and test plan. Phase 4C adds
read-only completeness diagnostics for object-attribute candidates before any
write support exists. It reports whether the declaration, resolved reads,
resolved writes, dynamic references, unresolved references, external references,
and blocked/future-mode owner status would make a future plan complete. It
always reports `apply_allowed: false` for now. These phases do not implement
apply behavior, do not add `rename-attribute`, do not add
`rename-symbol --attribute`, do not broaden local `customfmt rename`, and do not
remove the strict statementComposer golden xfail.

Phase 4E adds only the future command skeleton for diff planning:

```bash
customfmt rename-attribute <root> --class Repo --name tableName --to TableName --diff
```

The skeleton validates that `--class`, `--name`, and `--to` are explicit and
refuses apply/write behavior. A later diff implementation must prove a complete
project-wide object-attribute plan before rendering any diff: declaration found
on the explicit owner class, all reads and writes resolved, no dynamic refs, no
unresolved refs, no external refs, no future-mode owner, no inherited attrs, no
multiple candidate owners, and no collision with the new name. Diff-only support
must land before any apply mode so the project can review the exact token plan
without writing files.

A future object-attribute planner may consider repository metadata migrations
such as `repo.tableName` -> `repo.TableName`, `repo.pk` -> `repo.Pk`,
`repo.references` -> `repo.References`, and `repo.model` -> `repo.Model` only
when all of these facts are proven:

* The receiver belongs to a project-owned class declaration, such as `BaseRepo`
  or an explicitly proven subclass.
* The old and new spellings map to a proven attribute declaration on that owner.
* Every read and write for the attribute is resolved into one complete token
  plan.
* No dynamic `getattr`, `setattr`, `hasattr`, `__dict__`, framework magic,
  generated/reflected field behavior, serialized/API field ambiguity, external
  owner, or unsupported inherited attribute participates in the plan.

Unknown receiver expressions remain blocked. The spelling `repo.tableName` is
not sufficient evidence that `repo` is a repository, and text matching must not
be used to infer ownership. Dataclass, Pydantic, ORM, model, or condition fields
remain blocked unless a future explicit mode defines how schema, serialization,
and framework behavior are handled. The migration path therefore needs
read-only completeness diagnostics before write support: the tool must first
show that repository attributes have proven owner classes, direct declarations,
and complete read/write coverage, while leaving StatementComposer repository
attributes incomplete when those facts are absent.

StatementComposer `repo`, `model`, and `condition` attributes must still be
refused without proven declarations, even when the future command is invoked
with plausible names. The skeleton does not authorize `repo.tableName`,
`conditions[*].modelType`, or `previous_condition.nextCondition` edits; those
remain blocked/manual until a complete owner/declaration/reference plan exists.

The preferred owner is a future dedicated command:

```bash
customfmt rename-attribute <root> --class Repo --name tableName --to TableName
```

An acceptable explicit alternative is a project-wide symbol mode:

```bash
customfmt rename-symbol <root> --attribute --class Repo --name tableName --to TableName
```

It must not be local `customfmt rename`, because object attributes are
project/API references rather than local bindings. The future planner must own
the declaration token, every safe read, and every safe write in one complete
plan. Apply must be blocked by unknown receivers, external owners, inherited
attributes, dataclass/Pydantic/SQLModel/ORM/model-like owners, dynamic
`getattr`/`setattr`/`hasattr`, `__dict__`, string references, partial or
unresolved plans, multiple candidate owners, missing declarations, owner-class
new-name collisions, and mixed old/new spelling references unless a later design
explicitly supports them.


#### Phase 4B apply safety and tests

A future object-attribute apply must stage all edits in memory, render and parse
all edited files, validate complete UTF-8 LF output, and write files only after
the full plan succeeds. On validation failure it must write nothing. On write
failure it must roll back written files or use an atomic strategy that leaves
original bytes unchanged. Partial writes are forbidden.

The required future test plan includes safe same-file declaration/read/write
diff and apply, imported class attribute diff and apply, blockers for unknown
receivers, inherited attributes, future-mode framework/model-like owners,
dynamic `getattr`/`setattr`/`hasattr`, `__dict__`, owner declaration
collisions, and partial unresolved plans. StatementComposer `repo`, model, and
condition fields remain future/manual and the golden xfail remains strict.

For the statementComposer fixture specifically, `repo.tableName`, `repo.pk`,
`repo.references`, and `repo.model` require proven `BaseRepo` or subclass
ownership before any automated casing migration. `conditions[*].modelType`,
`conditions[*].fieldName`, `conditions[*].operation`,
`conditions[*].condition`, and `previous_condition.nextCondition` are
model/property migrations and remain manual unless declarations are proven by a
specific fixture or a future explicit mode. The `closeBreacket` typo/API
correction remains manual and outside attribute rename support.

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
