# Roadmap

PR Test Guard is moving from an evidence-research prototype into a lightweight PR test-quality tool.

The product direction is intentionally narrow:

> run fast, explain what triggered, surface review signals, and fit naturally into local CLI and CI workflows.

Version `0.1.0` remains pre-release while the public naming and product boundary are stabilized.

## What Exists in 0.1.0

- `pr-test-guard` / `python -m pr_test_guard` entrypoints;
- executable Python/pytest regression fixtures;
- changed-line coverage evidence;
- test-diff and assertion summaries;
- explicit Python mock-boundary candidates;
- limited deterministic counterfactual probes;
- normalized real-PR input bundle validation;
- JSON and Markdown artifacts for debugging rule behavior.

The fixture runner is development infrastructure for the tool. It is not the product's public benchmark identity.

## Product Principles

### Lightweight first

Prefer deterministic checks that can run locally or in CI without a hosted service, API key, or large setup burden.

### PR first

The primary user context is a pull request: what code changed, what tests changed, what ran, and what obvious test-quality risks deserve review.

### Advisory by default

Heuristic signals such as weak assertions or suspicious mocks should default to warnings. Repositories can choose later which high-confidence policies deserve to block merges.

### CLI core, integrations on top

The analysis logic should live behind a reusable CLI/core. GitHub Actions should wrap that core rather than creating a separate implementation.

## Stage 1: Rename and Reposition

- rename the public project to PR Test Guard;
- rename package and CLI surfaces;
- remove benchmark/harness language from the main product story;
- retain useful existing rule logic and regression fixtures;
- make README and docs describe the same lightweight PR-checking direction.

## Stage 2: Direct PR Check Command

Add a first repository-native command, for example:

```text
pr-test-guard check --base <base-ref>
```

It should initially focus on low-cost inputs:

- git diff;
- production/test file changes;
- assertion/test changes;
- optional existing coverage report.

Avoid requiring a normalized bundle for normal local use.

## Stage 3: Small Rule Set

Turn the most useful existing logic into explicit, individually configurable rules.

Initial candidates:

1. changed production code with no obvious test change;
2. uncovered changed executable lines when coverage exists;
3. obvious weak assertion patterns;
4. suspicious test deletion, skip, xfail, or assertion weakening;
5. explicit mock candidates on changed behavior paths as warning-only evidence.

Each rule should emit:

```text
rule id
severity
file / line when available
short message
evidence reference
```

## Stage 4: GitHub Action

Publish a reusable GitHub Action that invokes the same core CLI on `pull_request` workflows.

First output targets:

- normal workflow logs;
- GitHub job summary;
- file/line warnings where supported.

Do not require a backend service.

## Stage 5: Advisory and Enforcement Policy

Add a small configuration surface such as:

```text
advisory by default
optional fail-on selected rules or severity
```

Keep policy separate from detection. The checker identifies signals; the repository decides what blocks a merge.

## Stage 6: False-Positive Reduction

Expand regression fixtures with negative controls and dogfood the rules on real PRs.

Prioritize noisy areas:

- weak assertions;
- mock boundaries;
- existing-test coverage when no test file changed;
- refactors and non-behavioral changes;
- test deletion/skip intent.

## Stage 7: Broader CI and Language Support

After the GitHub/Python path is stable, consider:

- GitLab or other CI wrappers;
- JavaScript/TypeScript test patterns;
- other coverage formats;
- repository configuration for path/test mapping.

## Stage 8: Optional Semantic Assistance

Only after deterministic rules are useful on their own, consider optional semantic assistance for ambiguous mappings.

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
- running a hosted service when a local/CI workflow is sufficient.
