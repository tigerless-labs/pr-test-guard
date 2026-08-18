# Evaluation Design

PR Test Guard needs validation, but it does not need to become a benchmark project.

The purpose of validation is practical: keep rule behavior stable, understand false positives, and verify that the tool surfaces useful PR test-quality signals without overclaiming correctness.

## Validation Questions

For each rule, ask:

1. Does the rule fire on the controlled failure mode it is meant to detect?
2. Does it stay quiet on a nearby negative-control example?
3. Is the finding tied to inspectable evidence?
4. Is the message phrased as a signal rather than an unsupported verdict?
5. Is the rule cheap and deterministic enough for normal CLI/CI use?

## Regression Fixtures

The current `cases/python/` directory contains small executable PR-like fixtures. They are maintained to catch implementation regressions, not to act as a public leaderboard dataset.

Each fixture can include:

- an issue or change-intent description;
- structured change context used by the current prototype;
- a small executable repository;
- a PR-like patch;
- expected rule output.

The expected output is an internal regression oracle. It should be updated only when the intended rule behavior changes deliberately.

## Current Rule Families

The existing prototype exercises:

- missing test evidence;
- uncovered changed lines;
- weak assertions;
- issue/test mismatch;
- suspicious fixes without test evidence;
- mocked core paths;
- CI scope weakening;
- limited counterfactual survivors;
- a no-targeted-gap positive-control state currently named `Evidence Complete`.

Not every rule is equally suitable for hard enforcement. Heuristic signals should remain warnings until real usage shows that they are reliable enough for stricter policy.

## Runtime Evidence

When available, validation should preserve the evidence that produced a finding:

- test execution result;
- coverage result and changed-line mapping;
- test diff summary;
- assertion summary;
- mock-boundary summary;
- counterfactual result;
- file/line or test references.

This keeps failures debuggable and prevents a rule score from becoming an opaque verdict.

## Real-World Validation

After a direct PR-facing CLI exists, validate it by dogfooding on real pull requests and recording:

- which signals reviewers found useful;
- which signals were obvious false positives;
- which rules were too noisy to enable by default;
- runtime cost and setup friction;
- missing artifact patterns, especially coverage and CI data.

A small set of reviewed examples is enough to guide product iteration. A custom human-labeled benchmark and baseline leaderboard are not prerequisites for release.

## Advisory vs Enforcement

The validation target is not "does every signal deserve to fail CI?"

The safer default is:

```text
heuristic signal -> warning / summary -> reviewer decision
```

Later, repositories may choose explicit enforcement for high-confidence rules such as project-defined coverage thresholds or protected-test policies. The repository policy, not the checker alone, should decide what blocks a merge.

## Reproducibility

Changes to rule behavior should include or update a regression fixture. CI should run the fixture validator, execute patched fixtures, generate artifacts, and verify the public CLI entrypoint.

That provides enough reproducibility for a lightweight tool without turning release readiness into a benchmark research program.
