# Conservative method-call and object-attribute rename design

## Status and scope

This document designs conservative rename buckets for method-call and
object-attribute casing support. Phase 3A implements read-only simple receiver
method resolution, Phase 3B covers guarded apply for simple proven method calls,
Phase 3C adds focused statementComposer-style smoke coverage for the
method-call bucket, Phase 3D adds read-only helper-parameter receiver
inference, Phase 4A adds read-only discovery for simple project-owned
object-attribute references, and Phase 4B documents the future guarded
object-attribute apply boundary. Apply behavior and object-attribute rename
remain future work.

The goal is to make future casing migrations possible only when the tool can
prove the owner of an attribute access. The tool must not make arbitrary textual
replacements, must not guess from receiver names, and must not treat every
`obj.name` token as the same symbol.

## Non-goals for this PR

* Simple proven method-call apply is covered by guarded method apply only for
  proven project-owned receiver types.
* No object-attribute apply or rename behavior.
* No test xfail removal.
* No broadening of `customfmt rename`.
* No arbitrary search-and-replace for attribute text.

## Safety principles

* Attribute access in Python is dynamic and must remain blocked unless ownership
  is proven.
* Any future edit must be planned from resolved declarations and token positions,
  not from textual matches.
* A safe plan must include the declaration and every safe reference that belongs
  to that declaration.
* Dynamic, unresolved, external, or ambiguous references must block apply mode by
  default.
* The resolver and project graph remain read-only discovery layers; rewrite
  logic belongs in a guarded rename planner.

## Track A: Method-call rename support

### Phase 3A implemented read-only target pattern

`customfmt refs` can now classify simple instance method-call references as
resolved when all of these facts are proven without writing files:

1. The receiver variable has exactly one obvious type source in the local scope.
2. The type source is a direct constructor assignment, a bare annotation, or an
   annotated assignment.
3. The receiver class resolves to a project-owned class, including supported
   project imports.
4. The method is declared directly on that class.

Examples now supported read-only, and supported by guarded `rename-symbol
--diff` / `--apply` when the complete method reference set is proven:

```python
class Builder:
   def Where(self):
      ...

def Run():
   builder = Builder()
   builder.where()
```

```python
from pkg.builder import Builder

def Run():
   builder: Builder
   builder.where()
```

Reassigned receivers, unknown receivers, inherited methods, external classes,
`getattr(obj, "where")`, strings, and unproven dynamic calls remain dynamic or
unresolved. The method-call bucket is intentionally limited to project-owned
receiver classes whose constructor or annotation can be proven by the project
reference graph.

### Phase 3D implemented read-only helper-parameter receiver inference

`customfmt refs` can now prove a helper parameter's receiver type when a
project-owned helper is called with a locally proven receiver. This is a
read-only project-graph fact first: it classifies references such as
`statement_builder.where(...)` inside helpers, but it does not add
object-attribute rename support and does not broaden arbitrary attribute edits.

Supported proof shape:

```python
class StatementBuilder:
   def where(self, condition):
      ...

def ComposeStatement(repo, conditions):
   statement_builder = StatementBuilder()
   __BuildConditions(statement_builder, repo, conditions)

def __BuildConditions(statement_builder, repo, conditions):
   statement_builder.where(conditions[0])
```

The helper-parameter proof is accepted only when the callee resolves directly to
a project-owned function, the positional argument has a proven project-owned
receiver type, the parameter position is unambiguous, every observed call agrees
on the same receiver type, no `*args` / `**kwargs` / keyword-call ambiguity is
present, and the target method is declared directly on the inferred class.

Conflicting calls, unknown arguments, dynamic callees, inherited methods,
external classes, and unproven model or condition fields remain dynamic,
unresolved, or future work. Simple object attributes are handled only by the
read-only Phase 4A discovery described below when ownership is proven.

### Supported future method-rename target pattern

A future method-call rename may be considered only when all of these facts are
proven:

1. The receiver type is proven at the call site.
2. The target method declaration is known on a specific project class.
3. The declaration and all complete resolved method references are included in a
   project-wide token edit plan.
4. No dynamic receiver ambiguity exists for any planned reference.
5. The target is a project-owned API, not an external or library API.
6. The planner can validate the whole affected file set before writing any file.

Example future-safe shape:

```python
class StatementBuilder:
   def Where(self, condition):
      ...

statement_builder: StatementBuilder = StatementBuilder()
statement_builder.where(condition)
```

Even in this shape, a future implementation would need to prove that
`statement_builder` is a `StatementBuilder`, that `where` maps to the known
method declaration being renamed, and that every relevant call is accounted for.

### Blocked patterns

The following patterns must remain blocked unless a later design explicitly
proves them safe:

* Arbitrary `obj.method()` calls.
* Unknown receiver type.
* Duck-typed receivers.
* Inherited or overridden methods unless method-resolution-order handling is
  designed.
* `getattr(obj, "method")`.
* String references.
* Monkey-patched attributes.
* External or library APIs.
* Calls behind dynamic factories, plugins, descriptors, or reflection.
* Calls where only some project references are resolved.

### Likely owner

Method-call rename support likely belongs in `customfmt rename-symbol`, not in
local `customfmt rename`. Method calls are project API references, so they need a
project-wide owner that can consume read-only reference discovery, produce a
complete token plan, render a diff, and apply only after validation.

`customfmt rename` should continue to own only local-scope rewrites such as local
variables and the already-designed conservative private-helper parameter casing
bucket.

## Track B: Phase 4 object-attribute rename support

### Phase 4A implemented read-only simple class-attribute discovery

`customfmt refs` can now classify simple object-attribute reads and writes as
resolved when all of these facts are proven without writing files:

1. The receiver variable has exactly one direct constructor assignment or bare
   annotation in the local scope.
2. The receiver class resolves to a project-owned class, including supported
   project imports.
3. The attribute is declared directly in that class body.
4. The reference is a simple `receiver.attribute` read or assignment target.

Examples now supported read-only:

```python
class Repo:
   tableName = "x"

def Run():
   repo = Repo()
   return repo.tableName
```

```python
from pkg.repos import Repo

def Run():
   repo: Repo
   repo.tableName = "x"
```

Unknown receivers, external classes, inherited attributes, `getattr`, `setattr`,
`hasattr`, `__dict__` access, dataclass/Pydantic/ORM/model fields, string
references, and statementComposer-style `repo.tableName` without a proven
declaration remain dynamic, unresolved, blocked, or future work. Phase 4A is
read-only discovery only; it does not add `rename-attribute`, does not broaden
`customfmt rename`, and does not enable apply behavior for object attributes.


### Phase 4B guarded apply boundary design

Phase 4B is a design-and-test-plan boundary only. It does not implement
object-attribute apply behavior, does not add `rename-attribute`, does not add
`--attribute`, does not broaden local `customfmt rename`, and does not remove
the statementComposer golden xfail. The purpose is to define the contract that
a later implementation must satisfy before any object-attribute write is
allowed.

#### CLI ownership

The preferred future command shape is a dedicated project-wide command:

```bash
customfmt rename-attribute <root> --class Repo --name tableName --to TableName
```

An acceptable explicit alternative is a project-wide symbol mode that makes the
attribute boundary visible at the CLI:

```bash
customfmt rename-symbol <root> --attribute --class Repo --name tableName --to TableName
```

The local command is explicitly rejected for this bucket:

```bash
customfmt rename <root> --name tableName --to TableName
```

`customfmt rename` owns local lexical bindings only. Object attributes are
project/API references whose ownership may span files, imports, receivers,
frameworks, and serialization boundaries. Any implementation must therefore use
a project-wide planner that consumes read-only discovery and emits guarded token
edits; it must not route object-attribute apply through the local rename
planner.

#### Required complete plan

A future object-attribute apply is allowed only when the planner builds one
complete plan containing all of these token edits:

1. The attribute declaration token on the proven owner class.
2. Every safe read resolved to that declaration.
3. Every safe write resolved to that declaration.
4. Every affected file rendered and parsed successfully before any write.
5. No unresolved, dynamic, skipped, external, partial, or ambiguous reference in
   the discovered project reference set.

The declaration and all safe references must be validated as one unit. A diff
mode may render the same token plan read-only, but apply mode must reject any
plan that cannot prove completeness.

#### Apply blockers

Apply mode must fail with exit code 2 and write nothing when any of these facts
are present in the target project or plan:

* Unknown receiver type.
* External owner class or library API.
* Inherited attribute without an explicit, tested attribute-resolution design.
* Dataclass, Pydantic, SQLModel, ORM, or model-like owner.
* `getattr`, `setattr`, or `hasattr` involving the owner, receiver, or spelling.
* `__dict__` access or mutation involving the owner or receiver.
* String references in configs, SQL, JSON, templates, migrations, or other
  non-token locations.
* Partial plans, including skipped, unresolved, dynamic, or external
  references.
* Multiple candidate owners.
* Missing declaration on the specified owner class.
* New-name collision on the owner class.
* References to both the old and new spelling unless a later design explicitly
  defines and tests mixed-spelling handling.

#### Rollback and write safety

Apply mode must stage all file edits in memory first. The implementation must
render every edited file, parse every edited file, validate UTF-8 LF output, and
only then write files. If any validation fails, no file may be written. If a
write failure occurs after validation, the implementation must either roll back
all written files to their original bytes or otherwise leave originals
unchanged through an atomic-write strategy. Partial writes are not acceptable.

#### Phase 4B test plan

A future implementation must add focused tests for the guarded apply boundary
before enabling object-attribute writes:

| Case | Expected result |
| --- | --- |
| Safe same-file declaration/read/write diff | complete diff from one token plan |
| Safe same-file declaration/read/write apply | declaration, read, and write are updated after all-files validation |
| Imported class attribute diff/apply | resolved project import produces complete diff and guarded apply |
| Unknown receiver | apply blocked with exit 2 and no writes |
| Inherited attribute | apply blocked with exit 2 and no writes |
| Future-mode owner, including dataclass/Pydantic/SQLModel/ORM/model-like classes | apply blocked with exit 2 and no writes |
| Dynamic `getattr`, `setattr`, or `hasattr` | apply blocked with exit 2 and no writes |
| `__dict__` access or mutation | apply blocked with exit 2 and no writes |
| Declaration collision on owner class | apply blocked with exit 2 and no writes |
| Partial unresolved plan | apply blocked with exit 2 and no writes |
| statementComposer repo/model/condition fields | remain future/manual and the strict golden xfail remains |

### Supported future object-attribute target pattern

A future object-attribute rename may be considered only when all of these facts
are proven:

1. A project-owned class declaration is proven as the owner of the receiver.
2. The attribute declaration is proven on that project-owned class.
3. Every read and write for the attribute is resolved to that same declaration.
4. No dynamic `getattr`, `setattr`, or `hasattr` use can affect the attribute.
5. No `__dict__` access or mutation can affect the attribute.
6. No generated, reflected, serialized, or public API field ambiguity exists.
7. No external class owns or participates in the planned attribute references.
8. No inherited attribute is included unless explicit method-resolution-order and
   attribute-resolution support is designed and tested.
9. The planner can build one complete project-wide token plan and validate the
   whole affected file set before writing any file.

Example future-safe shape:

```python
class BaseRepo:
   TableName = "example"

repo: BaseRepo = BaseRepo()
print(repo.tableName)
```

This still requires proof that `repo` is a `BaseRepo` or explicitly supported
subclass, that `TableName` is the declaration being migrated, and that every
read and write of the old spelling is included in one guarded plan. A receiver
name such as `repo` is never proof by itself.

The motivating repository metadata migrations are examples of this future
bucket only after ownership is proven:

* `repo.tableName` -> `repo.TableName`
* `repo.pk` -> `repo.Pk`
* `repo.references` -> `repo.References`
* `repo.model` -> `repo.Model`

### Blocked patterns

The following patterns must remain blocked unless a later design explicitly
proves them safe:

* Arbitrary `repo.tableName` where `repo` type is unknown.
* Dataclass, Pydantic, ORM, or other model fields unless serialization and
  schema implications are explicit.
* Dynamic `setattr`, `getattr`, or `hasattr` usage.
* `__dict__` access or mutation.
* String references in configs, SQL, JSON, templates, migrations, comments, or
  other non-token locations.
* Framework magic, descriptors, generated fields, reflected fields, plugin
  hooks, monkey-patching, or dynamically attached attributes.
* External object attributes or library APIs.
* Inherited attributes unless MRO and attribute shadowing are explicitly
  supported.
* Model or condition fields from the statementComposer fixture unless their
  declarations are proven.
* Partial plans where some reads or writes are unresolved, dynamic, skipped, or
  external.

### Proposed CLI ownership

Object-attribute rename support preferably belongs in a future dedicated command:

```bash
customfmt rename-attribute <root> --class Repo --name tableName --to TableName
```

An alternative is an explicit project-wide mode on the existing symbol command:

```bash
customfmt rename-symbol <root> --attribute --class BaseRepo --name tableName --to TableName
```

It must not belong to local `customfmt rename`. Object attributes are
project/API references, not local bindings, and require project-wide ownership
proof, complete reference discovery, guarded token rendering, diff support, and
all-files validation before apply.

### Phase 4 test matrix

A future implementation should add targeted tests before any statementComposer
golden xfail is removed:

| Case | Expected result |
| --- | --- |
| Safe same-file class attribute declaration, read, and write | complete plan / diff / apply succeeds |
| Safe imported class attribute declaration with resolved project import | complete plan / diff / apply succeeds |
| Assignment, read, and write coverage for one proven owner | every token included in one plan |
| Unknown receiver such as arbitrary `repo.tableName` | blocked |
| Dynamic `getattr`, `setattr`, or `hasattr` involving the name or receiver | blocked |
| `__dict__` access involving the receiver or owner | blocked |
| Inherited attribute without explicit MRO support | blocked |
| Dataclass, Pydantic, ORM, generated, reflected, or serialized fields | blocked unless an explicit future mode defines schema/API handling |
| External class attributes | blocked |
| StatementComposer repository/model/condition fields | remain future/manual unless declarations are proven |

### StatementComposer Phase 4 notes

The statementComposer fixture remains a planning fixture, not authorization for
attribute text replacement. Repository metadata such as `repo.tableName`,
`repo.pk`, `repo.references`, and `repo.model` requires proven `BaseRepo` or
subclass ownership before a future attribute planner may consider edits. The
planner must prove the repository declaration, the receiver type, and every
read/write reference.

Condition and model fields such as `conditions[*].modelType`,
`conditions[*].fieldName`, `conditions[*].operation`,
`conditions[*].condition`, and `previous_condition.nextCondition` are
model/property migrations. They remain manual unless declarations are proven and
serialization or framework implications are explicitly handled.

The `closeBreacket` typo/API correction remains manual. It is not an object
attribute rename, and it must not be inferred from casing rules.
