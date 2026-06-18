# Conservative method-call and object-attribute rename design

## Status and scope

This document designs a Phase 3 rename bucket for conservative method-call and
object-attribute casing support. Phase 3A implements read-only simple receiver
method resolution, Phase 3B covers guarded apply for simple proven method calls,
and Phase 3C adds focused statementComposer-style smoke coverage for the
method-call bucket. Object-attribute rename remains future work.

The goal is to make future casing migrations possible only when the tool can
prove the owner of an attribute access. The tool must not make arbitrary textual
replacements, must not guess from receiver names, and must not treat every
`obj.name` token as the same symbol.

## Non-goals for this PR

* Simple proven method-call apply is covered by guarded method apply only for
  proven project-owned receiver types.
* No object-attribute rename behavior.
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

## Track B: Object-attribute rename support

### Supported future object-attribute target pattern

A future object-attribute rename may be considered only when all of these facts
are proven:

1. A project-owned class, dataclass, Pydantic model, or model declaration owns the
   attribute declaration.
2. The declaration and all safe attribute reads and writes are resolved to that
   same owner.
3. The tool can build a complete project-wide plan covering every affected token.
4. Dynamic attribute mechanisms are absent or explicitly classified as blocking.
5. Serialized/public API implications are reviewed before apply mode is allowed.
6. The planner can validate the whole affected file set before writing any file.

Example future-safe shape:

```python
class BaseRepo:
   TableName = "example"

repo: BaseRepo = BaseRepo()
print(repo.tableName)
```

This still requires proof that `repo` is a `BaseRepo` or known subclass, that the
attribute belongs to that owner, and that all safe reads and writes are included
in one guarded plan.

### Blocked patterns

The following patterns must remain blocked unless a later design explicitly
proves them safe:

* Arbitrary `repo.tableName` where `repo` type is unknown.
* Generated or reflected fields.
* Serialized API fields.
* Dynamic `setattr`, `getattr`, or `hasattr` usage.
* `__dict__` access or mutation.
* Framework magic.
* External object attributes.
* Descriptor behavior that changes lookup ownership.
* Attribute names used in strings, configs, SQL, JSON, templates, or migrations.
* Partial plans where some reads or writes are unresolved.

### Likely owner

Object-attribute rename support likely belongs in a future `rename-attribute`
command or an explicitly extended `rename-symbol` mode, not in local
`customfmt rename`. The local rename planner cannot prove project-wide object
ownership and must not rewrite `obj.attr` text by pattern.

## StatementComposer implications

The `statementComposer` golden fixture includes several changes that look like
simple casing fixes but are not safe local renames:

* `statement_builder.where` to `statement_builder.Where` is safe only when the
  guarded method apply proves `statement_builder` is a `StatementBuilder` and
  that `where` is the owned method declaration being migrated.
* `repo.tableName` to `repo.TableName` is not safe until the tool proves `repo`
  is a `BaseRepo` or known subclass and owns that attribute.
* `conditions[*].modelType` to `ModelType` is a model/property migration and may
  be manual unless declarations are provable.
* `closeBreacket` to `CloseBracket` is an API typo migration and should remain
  manual. It is not a safe rename inference because it changes both spelling and
  casing.

Phase 3C covers only an artificial, proven project-owned `StatementBuilder`
method-call smoke slice with a local stub. Repository attributes, condition/model
attributes, and typo/API migrations remain future/manual work. For this reason,
the full statementComposer method/attribute bucket should remain
`xfail(strict=True)` until object-attribute rename and the remaining manual/API
migration tracks have targeted tests and safety guards.

## Proposed future test matrix

When a future implementation is started, add targeted coverage before removing
any statementComposer xfail:

| Area | Scenario | Expected result |
| --- | --- | --- |
| Method call | Safe same-file class method rename | Covered by guarded method apply when declaration and proven calls are planned together |
| Method call | Safe imported class method rename | Covered by guarded method apply when import graph proves class owner and calls |
| Method call | Dynamic receiver | Blocked |
| Method call | Inherited method | Blocked or explicitly unresolved until MRO handling is designed |
| Method call | `getattr(obj, "method")` | Blocked |
| Object attribute | Safe class attribute rename | Declaration and proven reads/writes planned together |
| Object attribute | Dataclass/Pydantic field rename | Allowed only if complete and serialization implications are safe |
| Object attribute | Dynamic `setattr`/`getattr`/`hasattr` | Blocked |
| StatementComposer | Simple proven method calls | Covered by guarded method apply smoke coverage and the Phase 3C statementComposer-style smoke test |
| StatementComposer | Object-attribute bucket | Remains future work; full golden remains xfail |

## Implementation boundaries for a future PR

A future PR should keep responsibilities separated:

* `symbols/project_graph.py` remains read-only project reference discovery.
* `symbols/resolver.py` remains read-only lexical resolution and must not write
  files.
* Any write path must use a guarded token renderer and validate every affected
  file before writing.
* Apply mode must fail by default when the plan has warnings, skipped items,
  unresolved references, or dynamic references.
* The future implementation must update README and command help if it adds new
  commands, flags, exit behavior, or output schema.
