# Rule Fixtures

The fixtures under `cases/python/` are controlled regression examples for PR Test Guard.

They are not a public human-labeled benchmark. Their purpose is to make rule behavior reproducible while the implementation changes.

## Fixture Unit

Each fixture represents one small PR-like scenario and can include:

- `issue.md`: short change intent;
- `claim.json`: structured intent used by the current prototype;
- `repo/`: executable base fixture;
- `pr.patch`: PR-like change;
- `metadata.json`: fixture metadata;
- `expected_findings.json`: expected rule output for regression checking.

The `claim.json` shape is retained from the original prototype because current rule logic still uses it. A future PR-facing CLI may infer simpler context directly from the diff, repository configuration, and optional PR text.

## Fixture Principles

1. Keep fixtures small enough to understand without external context.
2. Change one primary failure mode at a time when possible.
3. Add negative controls for rules that are likely to be noisy.
4. Keep expected findings tied to concrete evidence references.
5. Treat expected findings as regression expectations, not proof of general accuracy.
6. Do not add a fixture merely to improve a score; add it to define intended behavior.

## Current Fixtures

- `weak_assertion_001`: exercises an obviously weak assertion pattern.
- `issue_test_mismatch_001`: exercises a test that covers a different behavior path.
- `mocked_core_path_001`: exercises an explicit mock that replaces changed behavior.
- `legitimate_helper_mock_001`: negative control for a dependency mock with an interaction-contract assertion.
- `unconstrained_helper_mock_001`: positive control for a changed test that mocks an internal helper called from a changed owner line but only checks a weak owner result.
- `evidence_complete_001`: positive control where the targeted behavior is directly asserted.

## Positive and Negative Controls

Future rule work should prioritize pairs of examples:

```text
signal should fire
vs.
nearby legitimate pattern where it should not fire
```

Examples worth adding include:

- behavior change with existing-test coverage vs. truly missing tests;
- legitimate dependency mock vs. mocked core behavior;
- weak non-null assertion vs. a non-null assertion that is actually the intended contract;
- targeted probe survivor vs. a nearby test that kills the same probe;
- intentional test deletion vs. suspicious coverage reduction.

These controls are more useful for product quality than a large synthetic leaderboard.

## Dogfood-Derived Controls

Real pull requests can motivate a fixture, but the committed fixture should be a
distilled control rather than a raw or lightly renamed copy. Preserve only the
rule-relevant shape:

- which rule fired;
- whether reviewer feedback was useful, false positive, unclear, or needed more context;
- the coarse path/symbol/dependency kinds;
- the relationship shape that the rule must preserve or suppress.

Then rewrite the scenario with fictional module names, paths, symbols,
dependencies, and tests. The public fixture should stand alone as a minimal
rule-boundary example; the private PR remains only local validation evidence.

For PTG005, `legitimate_helper_mock_001` and
`unconstrained_helper_mock_001` are a paired control:

```text
constrained helper mock with owner behavior evidence -> suppress PTG005
unconstrained helper mock with weak owner evidence -> emit PTG005
```

## Updating Expected Findings

When a rule intentionally changes:

1. update the implementation;
2. update or add the smallest relevant fixture;
3. inspect the generated evidence;
4. update `expected_findings.json` only when the new behavior is deliberate;
5. explain the behavior change in the PR.

The expected output should never be changed only to make CI green.
