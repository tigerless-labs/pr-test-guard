# Validation Strategy

PR Test Guard is a lightweight developer tool, so validation should focus on rule usefulness and operational safety rather than building a custom benchmark.

## What to Validate

For each rule, track three practical properties:

- **Signal quality:** does it point to a real review concern often enough to be useful?
- **Explainability:** can the reviewer see the file, line, test, or artifact that caused it?
- **Cost:** can it run quickly enough in local development and CI?

## Layer 1: Regression Fixtures

Use the controlled fixtures in `cases/python/` to ensure known rule behavior does not change accidentally.

CI should check:

- fixture structure;
- patch application;
- pytest execution;
- generated evidence artifacts;
- expected finding comparison;
- CLI entrypoints.

This is regression testing for the tool itself, not benchmark scoring.

## Layer 2: Negative Controls

Heuristic rules need nearby examples where they should stay quiet. Prioritize negative controls for:

- weak assertions;
- mock boundaries;
- missing-test heuristics;
- test deletion/skip signals;
- coverage gaps.

The goal is to reduce noisy warnings before rules are exposed broadly in CI.

## Layer 3: Real Pull Requests

Once a direct PR-check command exists, dogfood it on real repositories.

For each signal, record simple reviewer feedback such as:

```text
useful
false positive
unclear
needs more context
```

This is enough to guide early releases. Formal precision/recall studies can be added later if the project develops a research need, but they are not required for the product roadmap.

For public project materials, record shareable summaries rather than raw PR
exports. Use stable aliases and coarse evidence shapes, and keep repository-
specific notes outside this repository. See [Dogfooding](dogfooding.md).

## Layer 4: CI Behavior

Validate that CI integration is safe and unsurprising:

- default findings are advisory;
- the checker itself failing to run is distinguishable from a PR quality warning;
- repository owners can opt into stricter enforcement later;
- untrusted PR code is not given unnecessary secrets or privileged tokens;
- output remains readable in logs and GitHub job summaries.

## Related-Work Awareness

PR Test Guard should remain aware of existing categories such as patch coverage, mutation testing, linters, and automated code review. Those tools inform rule design and prevent duplicated claims.

The project should not require a public baseline leaderboard to prove that awareness. The README and rule documentation should state clearly which signals are established techniques and where PR Test Guard adds a lightweight PR-centered combination or review workflow.

## Release Readiness

For early releases, a rule is ready when:

1. its behavior is documented;
2. at least one controlled positive example exists;
3. likely false-positive patterns have been considered;
4. the output includes actionable evidence;
5. the rule does not overstate what it knows;
6. the default behavior is appropriate for advisory CI use.
