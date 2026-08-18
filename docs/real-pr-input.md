# Real PR Input

This document defines the current bridge from controlled fixtures to real pull requests.

PR Test Guard should keep its core analysis independent from one coding agent or one hosting provider. The long-term product shape is a CLI that can analyze local PR context, with GitHub Actions as the first automated integration.

## Why Normalize PR Artifacts

A pull request may expose useful context through different places:

- PR title and body;
- linked issue or task;
- git diff;
- test diff;
- CI summary or logs;
- coverage reports;
- optional change-intent text.

The checker should use what is available and record what is missing instead of inventing evidence.

## Current Bundle Shape

The prototype bundle under `examples/real-pr-bundles/` can include:

- `bundle.json`
- `pr.json`
- `pr.diff`
- `ci-summary.md`
- `claim_candidates.json`
- `missing_artifacts.json`
- optional issue/task text
- optional coverage or test results

The current `claim_candidates.json` is a prototype context artifact, not a requirement for every future rule. Straightforward diff- and coverage-based checks should not need an LLM-generated claim layer.

## Validation

Validate the example bundle with:

```bash
python3 -m pr_test_guard validate-real-pr-bundles
```

The validator checks structure and cross-file consistency. It does not claim that the example represents a real repository or a scored dataset.

## CLI Direction

The target CLI should eventually accept repository-native context directly, for example:

```text
pr-test-guard check --base <base-ref>
```

A direct check command should derive the PR diff from git, discover relevant test changes, optionally consume an existing coverage artifact, and emit normalized findings.

That command does not exist in `0.1.0`; the current bundle is preparation for that transition.

## GitHub Actions Direction

GitHub Actions should wrap the same CLI/core rather than becoming a separate analysis engine.

The intended flow is:

```text
pull_request event
  -> checkout
  -> existing project test/coverage job
  -> PR Test Guard CLI
  -> annotations / job summary
```

The default integration should be advisory. A warning such as a possible weak assertion should not automatically block a merge. Repositories may later configure selected high-confidence rules or thresholds as enforcement policy.

## Missing Evidence

Missing evidence is itself useful context, but it must be reported precisely.

For example, if no coverage artifact is available, the tool may say that changed-line coverage was not evaluated. It should not infer that changed code is uncovered.

This distinction is important for a lightweight tool that must work across repositories with different CI setups.

## Security Boundary

A GitHub Action should request the minimum permissions needed for analysis. The checker should not need write access or repository secrets for its default rule path.

If a future mode executes untrusted PR code, that execution must follow the repository's existing CI trust model rather than silently escalating privileges.
