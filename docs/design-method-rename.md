# Design: Conservative Method Rename Support

## Status

This document is a design note for conservative method rename support. Phase 1
resolver/index metadata is implemented: direct class-body method definitions are
reported as `kind: "method"` and include owning class metadata.

Phase 2 read-only method references are implemented. Project reference discovery
can resolve conservative same-class `self.Method()` / `cls.Method()` references,
same-file `ClassName.Method(instance)` references, safely resolved imported
`ClassName.Method(instance)` references, and safely resolved imported module
alias `module_alias.ClassName.Method(instance)` references. Unsupported or
ambiguous method-looking references remain read-only dynamic or unresolved
results rather than rename candidates.

`customfmt rename-symbol` still does not support method targets. The Phase 1
and Phase 2 work is read-only/planning groundwork only and does not add method
rename planning, method diff/apply support, CLI flags, or changes to the current
rename safety rules.

## Goals

Future method rename support should extend project-wide rename planning while
preserving the current conservative model:

* build a read-only plan before any write is possible;
* show the user an exact diff before apply;
* use guarded token-position edits rather than text replacement;
* block apply when the plan contains unresolved or dynamic references; and
* avoid guessing across Python's dynamic dispatch model.

The initial feature should support only method references whose owning class is
known. It should not attempt general object type inference, duck typing, or
inheritance-aware dispatch.

## Why Method Rename Is Harder Than Function Or Class Rename

Function and class renames usually target lexical names. A module-level
function call such as `BuildPlan()` can often be matched to a function
symbol in the same file or to an imported binding. A class name such as
`RenamePlan` is likewise a named symbol that can be resolved through local
scope or supported import forms.

Methods are harder because a method reference is usually an attribute access,
not a standalone lexical name. In `value.Render()`, the token `Render` does not
identify its owner by itself. The correct target depends on what `value` is at
runtime. Python also permits monkey patching, decorators, descriptors,
properties, dynamic `getattr()` / `setattr()`, and duck-typed objects with the
same method name. Renaming every `.Render` token would be unsafe because
unrelated classes can intentionally use the same method name.

A conservative method rename therefore needs two facts before planning an edit:

1. the selected target method definition belongs to a specific class symbol; and
2. each planned reference is proven to point at that same class method.

When either fact is missing, the reference must be reported as unresolved or
dynamic and must block apply by default.

## Supported Future Cases

The first implementation should support only references where the class owner is
known from syntax and resolver data.

### Same-Class Method Definition And `self.Method()`

When the selected target is a method definition inside class `ClassName`, the
planner may rename:

* the method definition token; and
* `self.Method()` references inside methods of that same class, when `self` is
  inferred to be the instance parameter for that class scope.

Example:

```python
class Worker:
   def Run(self):
      self.Build()

   def Build(self):
      return None
```

Renaming `Worker.Build` to `Create` may plan edits for `def Build` and
`self.Build()` because both references are owned by `Worker`.

### `cls.Method()`

Inside methods where `cls` is inferred to be the class parameter for the owning
class, the planner may rename `cls.Method()` when the selected target is a
method on that same class.

This should be limited to class methods or other class-scope functions where the
resolver can identify the class binding. The first version does not need to
validate decorator semantics deeply; if class binding is ambiguous, mark the
reference dynamic instead of guessing.

### Direct Class Call `ClassName.Method(instance)`

The planner may rename direct class attribute calls when `ClassName` resolves to
the selected class symbol:

```python
ClassName.Method(instance)
```

This is safer than arbitrary object calls because the attribute owner is the
class symbol itself. The planner should still validate that `ClassName` is a
resolved class target, not a local variable shadowing the class.

### Imported Class Method References When Class Is Resolved

The planner may rename imported class method references only when the imported
class resolves to the selected class symbol through supported project reference
rules.

Examples that may be supported after import resolution proves the class target:

```python
from package.module import ClassName

ClassName.Method(instance)
```

```python
import package.module as module_alias

module_alias.ClassName.Method(instance)
```

If the imported class cannot be resolved with high confidence, the method
reference must be unresolved and must not be edited.

## Unsupported Cases

The initial method rename design should explicitly reject or mark as dynamic all
cases below.

### Arbitrary `obj.Method()`

Calls through arbitrary variables are not safe without whole-program type
inference:

```python
obj.Method()
```

Even if `obj` is assigned from `ClassName()` nearby, the first version should
not rely on flow-sensitive type tracking.

### Duck Typing

Different classes may intentionally implement the same method name as a shared
protocol. A rename of `Worker.Run` must not rename `Runner.Run` or every
`.Run()` call merely because names match.

### Dynamic `getattr()` / `setattr()`

String-based method references are not token-safe method references:

```python
getattr(obj, "Method")()
setattr(ClassName, "Method", replacement)
```

These should be reported as dynamic when detected near the selected method name,
but they should not be rewritten.

### Monkey Patching

Runtime assignment can create, replace, or alias methods:

```python
ClassName.Method = Replacement
obj.Method = Replacement
```

The first version should not attempt to model these effects. Such patterns
should be dynamic or skipped and should block apply by default when relevant.

### Inheritance And MRO At First

The first version should not rename inherited overrides, base-class calls, or
subclass dispatch through the method resolution order. This includes:

* `super().Method()`;
* `SubClass.Method(instance)` when the selected method is declared on a base
  class;
* overrides with the same method name in subclasses; and
* calls that may dispatch through inheritance at runtime.

Inheritance-aware support can be designed later as a separate feature with its
own safety rules and tests.

## Required Resolver Additions

Method rename support should remain separated from rewriting. The resolver and
project reference graph should provide read-only facts; the rename planner
should consume those facts to produce guarded token edits.

### Class Scope Ownership

The resolver needs explicit ownership metadata for symbols declared inside a
class body. Each method definition should be associated with its containing class
symbol, including file path and source position, so the planner can distinguish
`A.Render` from `B.Render`.

### Method Definition Indexing

The indexer or resolver output should expose method definitions as class-owned
symbols. A method target should be selectable by a stable class-qualified form,
for example `ClassName.Method`, or by a symbol identifier that points to the
method definition token.

The method definition record should include enough information for token edits:

* file path;
* line and column span for the method name token;
* owning class symbol identifier;
* method name; and
* confidence that the definition is a regular class-body function definition.

### `self` / `cls` Binding Inference Inside Class Bodies

For functions defined directly in a class body, the resolver should infer the
instance or class parameter name conservatively:

* `self` binding is available only inside a class-owned function where the first
  parameter is named `self`;
* `cls` binding is available only inside a class-owned function where the first
  parameter is named `cls`; and
* ambiguous signatures, nested functions, lambdas, static methods, or unusual
  descriptors should not create an inferred binding unless explicitly supported.

The resolver should attach the owning class symbol to safe `self.Method` and
`cls.Method` attribute references. References outside that proof should remain
`dynamic`.

### Optional Class Symbol Target Selection

The CLI may eventually need a way to select a method by class symbol rather than
by unqualified method name. Potential forms include:

```bash
customfmt rename-symbol customfmt/ --name ClassName.Method --to NewMethod --pretty
customfmt rename-symbol customfmt/ --symbol <method-symbol-id> --to NewMethod --pretty
```

Unqualified method names are ambiguous across classes and should either be
rejected or require an exact single match. The safer default is to require a
class-qualified method target or a symbol identifier.

## Safety Model

### Read-Only Plan First

The first command mode must produce a JSON or pretty plan without changing
files. The plan should include:

* selected method target;
* owning class symbol;
* planned definition edits;
* planned reference edits;
* unresolved references;
* dynamic references;
* skipped unsupported patterns; and
* warnings that would block apply.

### Diff Before Apply

Diff rendering should use the same validated token edit plan that apply mode
would use. The diff should be read-only and should make every planned token
change visible before a user chooses apply mode.

### Apply Blocked By Unresolved Or Dynamic References

Apply mode must validate all affected files before writing any file. By default,
it must fail with exit code `2` and write nothing if the plan contains:

* unresolved method references;
* dynamic references related to the target method name;
* unsupported inheritance or MRO patterns;
* skipped monkey patching or dynamic attribute writes;
* token validation failures; or
* any warning that means the rename may be incomplete.

If an override flag is ever allowed, it should follow the existing
`--allow-incomplete` rule: apply-only, explicit, and rejected for JSON or diff
modes.

## Implementation Phases

1. Resolver metadata only (implemented)

   - direct class-body methods are exposed in indexer and resolver output as
     `kind: "method"`

   - method definitions expose owning class metadata in definition `extra`
     fields

   - `rename-symbol` method targets remain unsupported; this phase makes no
     rename behavior changes



2. Read-only method refs (Phase 2A same-class self/cls implemented;
   Phase 2B-A same-file class-owned calls implemented; Phase 2B-B imported
   class-owned calls implemented)

   - safe direct `self.Method()` and `cls.Method()` calls inside the owning
     class method resolve to `kind: "method"` targets with receiver, owner
     class, method name, and method target metadata

   - direct `ClassName.Method(instance)` references resolve when `ClassName` is
     a known local class definition and `Method` is a direct method definition
     on that class

   - imported `ClassName.Method(instance)` references resolve only when the
     class import resolves through existing safe project import resolution

   - arbitrary receivers, nested functions, lambdas, `super()`, missing
     methods, mismatched first parameters, unknown classes, inheritance/MRO,
     monkey-patching, and dynamic string references remain dynamic or
     unresolved rather than guessed

   - no rename planning or apply support



3. Rename-symbol plan/diff

   - emit guarded token edits for supported method refs

   - diff only first

   - no apply support until tests are strong



4. Apply support

   - reuse token renderer

   - block incomplete plans by default

   - require full test coverage before enabling



## Test Plan

Future implementation should add focused tests before enabling apply support.

### Resolver And Indexer Tests

* indexes class-owned method definitions with owning class metadata;
* distinguishes methods with the same name in different classes;
* records method token positions for guarded edits;
* infers `self` only from direct class-owned methods with first parameter
  `self`;
* infers `cls` only from direct class-owned methods with first parameter `cls`;
* does not leak `self` / `cls` binding into nested functions or lambdas;
* marks arbitrary `obj.Method()` as dynamic;
* marks `getattr()`, `setattr()`, `globals()`, and `importlib` patterns as
  dynamic when relevant; and
* preserves current function, class, and module-symbol reference behavior.

### Project Reference Tests

* resolves same-file `ClassName.Method` targets;
* resolves `from package.module import ClassName` before accepting
  `ClassName.Method(instance)`;
* resolves `import package.module as alias` before accepting
  `alias.ClassName.Method(instance)`;
* rejects or reports unresolved relative imports, wildcard imports, and
  unsupported import patterns;
* reports exactly one confidence value for each method reference; and
* keeps project graph behavior read-only.

### Rename Plan Tests

* plans edits for a same-class method definition and `self.Method()` references;
* plans edits for safe `cls.Method()` references;
* plans edits for direct `ClassName.Method(instance)` references when the class
  is resolved;
* plans edits for imported class method references only when the imported class
  is resolved;
* does not edit arbitrary `obj.Method()` calls;
* does not edit strings or comments containing the method name;
* blocks apply when unresolved or dynamic references exist;
* blocks apply for inheritance/MRO patterns in the first version;
* rejects `--allow-incomplete` outside apply mode;
* validates all affected files before writing any file; and
* avoids partial writes on validation failure.

### CLI And Documentation Tests

* pretty and JSON plan output include owner class, confidence, warnings, and
  skipped items;
* diff mode is read-only;
* apply mode returns exit code `2` for blocked plans;
* user-facing errors avoid internal tracebacks; and
* README documentation is updated in the implementation PR that enables the
  behavior.
