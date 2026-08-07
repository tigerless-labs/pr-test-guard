# Annotation Guidelines

This document defines the initial human-labeling rules for Claim Harness curated cases.

The goal is to keep expected findings independent from the implementation. A case should be labeled from the issue, claim, patch, tests, and controlled case construction before Claim Harness output is considered.

## Annotation Unit

The primary annotation unit is a **claim-evidence relationship**, not a whole pull request.

Each claim should be reviewed against:

- the behavior requested by the issue or task;
- the code changed to implement that behavior;
- the tests intended to support the claim;
- the assertions those tests make;
- whether mocks or patches replace the behavior under review;
- optional execution evidence such as coverage, CI results, or counterfactual probes.

## Labeling Principles

1. Label the evidence, not the overall quality of the PR.
2. Do not infer correctness from passing CI alone.
3. Do not infer adequacy from changed-line coverage alone.
4. Treat mocks as neutral until their relationship to the claim is established.
5. Prefer observable or reproducible evidence over reviewer intuition.
6. Mark ambiguous cases for adjudication instead of forcing a confident label.
7. Do not use Claim Harness output when creating the ground-truth label.

## Finding Rules

### `Missing Test Evidence`

Label `Missing Test Evidence` when all of the following hold:

1. A concrete change claim can be identified.
2. The patch changes behavior relevant to that claim.
3. No added, modified, or existing test can be identified as meaningful evidence for the claimed behavior.

A test for a nearby but materially different behavior does not remove this finding.

### `Uncovered Changed Lines`

Label `Uncovered Changed Lines` when:

1. executable changed lines or branches are relevant to a claim; and
2. execution evidence shows those lines or branches were not run by the relevant tests.

This label requires runtime coverage evidence and is not expected in curated cases that do not yet include generated coverage data.

### `Weak Assertion`

Label `Weak Assertion` when:

1. a claim has a plausible related test;
2. the relevant changed behavior is exercised or intentionally represented by the test setup; and
3. the assertions do not constrain the key outcome named by the claim.

Examples include checking only that a response is non-null when the claim requires a specific HTTP status, exception, state transition, or side effect.

A surviving counterfactual probe can strengthen this label but is not required for the initial curated cases.

### `Issue-Test Mismatch`

Label `Issue-Test Mismatch` when:

1. the issue or structured claim requires behavior A; and
2. the available test evidence primarily validates behavior B; and
3. B can pass without establishing A.

Typical examples include a failure-path claim paired only with a normal-path test, or a retry-limit claim paired only with a success-path test.

### `Suspicious Fix Without Test`

Label `Suspicious Fix Without Test` when a patch introduces or changes behavior and the submitted evidence surface contains no corresponding test change or identifiable existing test link.

Use this as a review-risk label. It does not assert that the implementation is wrong.

### `Mocked Core Path`

Label `Mocked Core Path` when:

1. the claim's core behavior can be localized to a function, method, component, or behavior path;
2. the relevant test uses a mock, stub, patch, monkeypatch, or equivalent substitution; and
3. that substitution replaces the behavior that the claim itself requires the test to validate.

Do **not** label a mock merely because it appears in the test. Mocking an external dependency can be appropriate when the behavior under review is the caller's policy or orchestration.

Example of acceptable isolation:

```python
gateway.charge = Mock(side_effect=TimeoutError)
assert retry_manager.attempt_count == 3
```

if the claim is about retry behavior.

Example of a mocked core path:

```python
retry_manager.retry = Mock(return_value=False)
```

if the claim is specifically that `retry_manager.retry` stops after three attempts.

### `CI Scope Weakening`

Label `CI Scope Weakening` when submitted CI or test configuration is changed in a way that excludes or skips validation relevant to the claim.

Examples include:

- adding a skip marker to the relevant test;
- narrowing a test command so the affected package no longer runs;
- excluding the changed path from coverage;
- changing filters so the relevant job no longer executes.

This label requires CI or configuration evidence.

### `Counterfactual Survivor`

Label `Counterfactual Survivor` only when a controlled probe has actually been executed.

The label applies when:

1. the probe removes, weakens, or reverses the behavior named in the claim;
2. the mapped supporting tests are rerun; and
3. those tests still pass.

A reviewer prediction that a mutation "would probably survive" is not sufficient.

### `Evidence Complete`

Label `Evidence Complete` conservatively when the available evidence is relatively complete for the stated claim and none of the benchmark's targeted inadequacy findings apply.

For the initial curated cases, this means the case intentionally includes a test whose setup and assertions directly constrain the claim and does not replace the core behavior with a mock.

`Evidence Complete` does not mean the PR is correct, secure, performant, complete, or ready to merge.

## Ambiguity and Adjudication

For future real-world PRs:

1. At least two reviewers should independently label each claim.
2. Reviewers should not see Claim Harness output before labeling.
3. Disagreements should be resolved by a third reviewer or explicit adjudication.
4. Cases with unresolved ambiguity should be excluded from the primary benchmark score or reported separately.
5. Inter-annotator agreement should be reported once the real-world set is large enough.

The first curated cases are intentionally synthetic so the targeted evidence defect is controlled by construction.
