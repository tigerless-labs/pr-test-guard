# Roadmap

PR Test Guard is a lightweight PR test-quality tool: run fast checks on a pull-request diff, explain what triggered, and fit naturally into local CLI and CI workflows.

Version `0.2.2` keeps the first public-ready shape from `0.1.0`, adds AST-scoped targeted probe generation for the optional deep path, reduces PTG005 false positives for constrained dependency mocks, and fixes PTG006 rerun correctness around stale Python bytecode.

## What Exists in 0.2.2

- `pr-test-guard` / `python -m pr_test_guard` entrypoints;
- `pr-test-guard check --base <base-ref>` for repository-native PR analysis;
- optional `coverage.py` XML input for changed-line coverage signals;
- obvious weak-assertion and test-weakening checks;
- explicit Python mock-boundary candidates on changed symbols and unconstrained changed dependency mocks;
- opt-in AST-scoped bounded targeted probes in an isolated Git worktree;
- text, JSON, and GitHub Actions output;
- reusable root `action.yml` with advisory warnings/job summary;
- executable Python/pytest regression fixtures;
- normalized real-PR bundle compatibility for development artifacts.

The fixture runner is development infrastructure for the tool. It is not the product's public benchmark identity.

## Current Main: PTG005 Semantic Lite

The PTG005 precision work remains deterministic and offline, with three bounded layers.

**Identity resolution**:

- preserve class/method qualified names instead of matching only bare method names;
- resolve common `import` / `from ... import ... as ...` aliases used by `patch.object`;
- resolve standard relative imports;
- normalize common `src/` package layouts;
- suppress resolved same-name symbols when their canonical identities differ;
- keep dynamic/unresolved targets conservative rather than guessing;
- avoid treating a class container as changed merely because one of its methods changed.

**Changed-call relationships**:

- keep direct changed-symbol mocks as the highest-confidence PTG005 candidate;
- inspect only direct calls whose call sites are on lines changed by the PR;
- only expand indirect PTG005 warnings to tests that are also changed by the PR;
- recognize direct internal dependencies and report that relationship explicitly;
- recognize explicitly imported external dependencies and suppress those external-boundary candidates;
- keep unchanged call sites, untouched tests, deep instance-attribute chains, and other unresolved relationships out of the warning path.

**Constrained dependency mocks**:

- keep direct changed-symbol mocks as warnings even when the test asserts mock interaction;
- suppress internal dependency mock candidates when changed tests constrain the owner behavior through mock interaction assertions, owner result assertions, or owner exception assertions;
- keep weak existence assertions, unconstrained mock return values, and ambiguous owner behavior in the warning path.

This layer improves **structural and test-semantics precision**, not business-intent understanding. It still does not decide whether a mock is appropriate, build a repository-wide call graph, or infer dynamic Python types. PTG005 remains advisory. Real-PR dogfooding should measure whether the relationship layer removes low-value warnings while retaining direct changed-symbol and unconstrained changed-internal-dependency cases.

## Product Principles

### Lightweight first

Prefer deterministic PR-scoped checks that can run locally or in CI without a hosted service or API key.

### PR first

The primary user context is a pull request: what code changed, what tests changed, what ran, and what test-quality risks deserve review.

### Beyond coverage

Patch coverage remains useful, but PR Test Guard should also surface signals that coverage alone cannot answer: obviously weak assertions, mocks that overlap changed paths, and bounded probes that survive the configured tests.

### Advisory by default

Heuristic signals default to warnings. Repositories can choose later which high-confidence policies deserve to block merges.

### CLI core, integrations on top

The analysis logic lives behind the reusable CLI/core. GitHub Actions wraps that core rather than creating a separate implementation.

## Next: Real-PR Dogfooding

Run the public rule set on varied real PRs across multiple Python/pytest repositories and record simple reviewer feedback:

```text
useful
false positive
unclear
needs more context
```

Use recurring false-positive patterns to add regression fixtures and tighten rules before expanding the rule family.

Priority cases:

- pure refactors with no test changes;
- existing tests that already cover changed code;
- legitimate mocks around changed paths, especially external SDK/API boundaries and internal helpers;
- strong assertions that look syntactically simple;
- test deletion/skip changes with explicit intent;
- changed code with good coverage but a surviving targeted probe.

## Next: Output and Policy Controls

After dogfooding stabilizes the signals, consider:

- configurable rule enable/disable settings;
- optional fail-on selected rules or severity;
- richer GitHub annotations;
- JSON artifact upload examples;
- repository path/test mapping configuration.

Keep policy separate from detection: the checker identifies signals; the repository decides what blocks a merge.

## Later: Broader Coverage and Language Support

After the GitHub/Python path is stable, consider:

- per-test coverage mapping;
- JavaScript/TypeScript test patterns;
- additional coverage formats;
- GitLab or other CI wrappers;
- broader but still conservative mock/assertion analysis.

## Optional Deeper Semantic Assistance

Only after deterministic symbol resolution and bounded rule logic are useful on their own, consider optional semantic assistance for ambiguous business-intent mappings.

It should remain:

- opt-in;
- explainable;
- non-authoritative;
- separate from default merge policy.

## Explicit Non-Goals for the Near Term

- building a custom leaderboard benchmark;
- maintaining a large human-labeled dataset;
- proving overall PR correctness;
- replacing existing test runners or coverage tools;
- becoming a general-purpose AI code-review agent;
- running a hosted service when a local/CI workflow is sufficient;
- running an unbounded mutation-testing campaign on every PR.
