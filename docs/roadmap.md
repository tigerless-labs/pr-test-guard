# Roadmap

PR Test Guard is a lightweight PR test-quality tool: run fast checks on a pull-request diff, explain what triggered, and fit naturally into local CLI and CI workflows.

Version `0.6.0` builds on the first public-ready Python/pytest path with bounded, stably grouped GitHub annotations and reusable Action outputs. Repositories can keep workflow noise controlled without losing findings from the GitHub Summary or JSON report, and downstream steps can consume policy-filtered result counts directly.

## What Exists in 0.6.0

- `pr-test-guard` / `python -m pr_test_guard` entrypoints;
- `pr-test-guard check --base <base-ref>` for repository-native PR analysis;
- optional `coverage.py` XML input for changed-line coverage signals;
- obvious weak-assertion and test-weakening checks;
- deterministic related-test context for changed Python symbols;
- explicit Python mock-boundary candidates on changed symbols and unconstrained changed dependency mocks;
- opt-in AST-scoped bounded targeted probes in an isolated Git worktree;
- dogfood-derived sanitized review examples and public-safe distilled PTG005 controls;
- text, JSON, and GitHub Actions output;
- `.pr-test-guard.*` configuration for rule `off` / `warn` / `error`, ignored paths, related-test display limits, and one-off `--fail-on` CI policy;
- `pr-test-guard validate-config` for strict, diff-independent configuration preflight and normalized text or JSON output;
- `paths.tests.include` / `paths.tests.exclude` configuration for repository-specific test layouts;
- `related_tests.mappings` configuration for additive source-to-test path relationships;
- optional `--json-output` report writing and GitHub artifact upload;
- dogfooding helpers for drafting raw local review records from JSON reports, sanitizing them, and summarizing aggregate reviewer feedback;
- reusable root `action.yml` with advisory warnings/job summary;
- configurable total/per-rule GitHub annotation limits with error-first deterministic selection;
- stable annotation titles, workflow-command property escaping, and composite Action result outputs;
- executable Python/pytest regression fixtures;
- normalized real-PR bundle compatibility for development artifacts.

The fixture runner is development infrastructure for the tool. It is not the product's public benchmark identity.

## Current: PTG005 Semantic Lite

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

## Current: Related Test Context

The direct checker records candidate tests tied to changed symbols through exact
imports, direct calls, supported mock targets, and test-name tokens when another
deterministic relationship already exists. This gives findings and summaries a
small amount of surrounding test context without claiming that the candidate
test is sufficient.

Repositories can supplement those inferred relationships with explicit
`related_tests.mappings`. These repository-relative source and test globs cover
stable integration or routing relationships that are invisible to direct Python
syntax. Mapping candidates are merged with inferred candidates, retain their
matched source paths in JSON, and respect configured test-path exclusions.

The context is intentionally conservative: same-name symbols from different
modules stay unrelated, dynamic calls are not guessed, and business-intent
mapping remains out of scope for the default path. Configured path relationships
are treated as review context, not proof of execution or test sufficiency.

## Product Principles

### Lightweight first

Prefer deterministic PR-scoped checks that can run locally or in CI without a hosted service or API key.

### PR first

The primary user context is a pull request: what code changed, what tests changed, what ran, and what test-quality risks deserve review.

### Beyond coverage

Patch coverage remains useful, but PR Test Guard should also surface signals that coverage alone cannot answer: obviously weak assertions, mocks that overlap changed paths, and bounded probes that survive the configured tests.

### Advisory by default

Heuristic signals default to warnings. Repositories can choose which high-confidence policies deserve to block merges.

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

Real pull requests should inform this work without becoming public fixtures.
The public repository should contain sanitized summaries and fictional distilled
controls that preserve the rule shape, not raw diffs, paths, symbols, URLs, CI
logs, or agent traces from private projects.

Priority cases:

- pure refactors with no test changes;
- existing tests that already cover changed code;
- legitimate mocks around changed paths, especially external SDK/API boundaries and internal helpers;
- strong assertions that look syntactically simple;
- test deletion/skip changes with explicit intent;
- changed code with good coverage but a surviving targeted probe.

## Current: Output and Policy Controls

The CLI now separates detection from policy. Default runs remain advisory, while
repositories can configure selected rules as `off`, `warn`, or `error`.
Configured error rules exit `1` and emit GitHub error annotations after the
summary is written.

GitHub summaries group findings by rule, include evidence in tables, and show a
bounded list of related-test candidates. This makes early adoption practical
without claiming that every heuristic warning should block merges.

The workflow-command annotation stream is independently bounded by total and
per-rule limits. It uses stable `PR Test Guard / PTGxxx` titles, prioritizes
error findings, reports omissions in the summary, and leaves the complete
summary tables and JSON result intact. The Action also exposes status and
finding counts for downstream workflow steps.

The checker can also write the full JSON result to a configured path and upload
that report from the GitHub Action before returning a policy failure.

Keep policy separate from detection: the checker identifies signals; the repository decides what blocks a merge.

## Current: Configurable Test Paths

Repositories can extend the built-in Python/pytest test path conventions with
`paths.tests.include` globs and remove false test classifications with
`paths.tests.exclude`. Excludes take precedence. The resolved classification is
used consistently by PTG001, PTG003, PTG004, PTG005, related-test discovery,
and output summaries. This is analysis configuration; `paths.ignore` remains a
post-detection finding filter.

## Current: GitHub Adoption Controls

Version `0.6.0` adds stable annotation grouping, deterministic error-first
limits, and Action outputs. After dogfooding stabilizes the signals, consider:

- per-rule thresholds for high-volume findings;

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
