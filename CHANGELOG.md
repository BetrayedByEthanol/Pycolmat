# Changelog

## Unreleased

- Added namespace package support for project refs in conservatively resolved, unambiguous scanned roots.
- Added namespace package support for `rename-symbol` diff/apply when scanned roots make the import target unambiguous.
- Added the public `InspectProjectModules` module inspection API.
- Added `customfmt doctor` diagnostics for namespace package ambiguity.

## v0.1.0 - 2026-06-05

- custom formatter/checker
- indexer
- resolver
- refs
- local rename
- project-wide rename-symbol plan/diff/apply
- guardrails
- relative import resolution for project refs and rename-symbol
- GitHub Actions CI with lint/test/smoke jobs

### Release checklist

```bash
ruff check customfmt/ tests/
try-auto-format --check customfmt/ tests/
check-format customfmt/ tests/
pytest
create-index customfmt/ --pretty
resolve-index customfmt/ --pretty
customfmt refs customfmt/ --name ResolveFile --pretty
customfmt rename-symbol customfmt/ --name ResolveFile --to ResolvePath --diff
```
