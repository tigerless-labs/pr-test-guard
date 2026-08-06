# Evaluation Design

This document defines how Claim Harness should be evaluated and reproduced once curated cases and a runner exist. It is not an implementation design, and it does not define a full benchmark suite yet.

The goal is to keep Claim Harness centered on test evidence adequacy for agentic PRs, rather than drifting into a generic coverage wrapper.

## Evaluation Question

Given an agentic PR and its supporting artifacts, does the PR provide enough test evidence for the change claims it makes?

Claim Harness evaluates test evidence adequacy. It does not prove that a PR is correct, complete, secure, performant, or ready to merge. Its output should support human review by showing which claims are supported by evidence, which are weakly supported, and which appear unsupported or misleading.

## Input Artifacts

Future cases or runner executions should treat the PR and its review artifacts as the input surface:

- `issue.md` or task description: the source of the requested behavior or engineering change.
- PR title and description: the author's stated change claims and rationale.
- PR diff: the changed code units and affected behavior surface.
- Test diff: added or modified tests, assertions, skips, mocks, fixtures, and snapshots.
- Coverage report, such as `coverage.xml` or `lcov.info`: evidence that changed lines or branches executed.
- CI log or test result: evidence that relevant tests actually ran in the submitted validation path.
- Optional counterfactual probe results: whether tests fail when the claimed behavior is weakened or removed.
- Optional mock boundary data: information about mocks, patches, stubs, and substituted dependencies.

Coverage is one input to the evidence chain. It should not be treated as the final adequacy answer.

## Evidence Chain

Claim Harness should connect artifacts through a claim-centered chain:

```text
change claim -> changed code unit -> related tests -> coverage evidence -> CI evidence -> adequacy finding
```

Each link answers a different review question:

- **Change claim:** what behavior or engineering change the PR claims to make, sourced from the issue, task description, PR text, or commit context.
- **Changed code unit:** the file, function, branch, or behavior surface in the PR diff that appears to implement the claim.
- **Related tests:** tests from the test diff or existing test files that are plausibly intended to support the claim.
- **Coverage evidence:** whether the changed lines or branches ran under the related tests.
- **CI evidence:** whether the relevant tests ran in the submitted CI or test result, rather than only locally or in a narrowed scope.
- **Adequacy finding:** whether the chain is relatively complete, missing, weak, mismatched, or misleading.

The chain should be reviewable. A finding is more useful when a reviewer can inspect the claim, the mapped code, the tests, and the reason the evidence is considered adequate or inadequate.

## Baseline Perspectives

Claim Harness should be compared against simpler perspectives so the added value is visible and testable.

| Perspective | What it checks | Expected limitation |
| --- | --- | --- |
| Diff Coverage Only | Whether changed executable lines or branches are covered. | Can miss weak assertions, issue-test mismatch, mocked core paths, and counterfactual survivors. |
| Test Diff Heuristic | Whether tests were added or changed, whether assertions increased, and whether skips, mocks, or snapshots changed. | Can detect suspicious shape, but cannot reliably connect tests to claims or executed behavior. |
| LLM Judge Only | Uses the issue, PR diff, and test diff to prompt an LLM for test sufficiency. | Useful as a prompt-only comparison, but too opaque to be the core method. |
| Claim Harness Evidence Chain | Combines claim extraction, diff mapping, related tests, coverage, CI evidence, counterfactual probes, and mock boundary analysis. | More artifact-heavy, but produces findings tied to auditable evidence. |

Claim Harness does not reject coverage. Diff coverage should be both a baseline and an evidence source. The harness should find the review risks that coverage alone can miss, including `Weak Assertion`, `Issue-Test Mismatch`, `Mocked Core Path`, `Suspicious Fix Without Test`, and `Counterfactual Survivor`.

## Finding Taxonomy v0

The first finding taxonomy should stay small and reviewable.

### Evidence Complete

The current evidence chain is relatively complete for the stated change claim. This does not mean the PR is correct; it means the available tests, coverage, CI evidence, and optional probes support the claim well enough to reduce this specific evidence concern.

### Missing Test Evidence

A change claim has no clear related test evidence. This can include behavior-changing code without a test diff or without an existing test that maps to the claim.

### Uncovered Changed Lines

Changed executable lines or branches are not covered by the relevant tests. This is a coverage finding, but it should still be tied back to a specific claim where possible.

### Weak Assertion

The relevant code runs, but the test assertion does not constrain the claimed behavior. A test that only checks for a non-null result may cover the line while failing to validate the expected status, error, state change, or side effect.

### Issue-Test Mismatch

The test targets a different behavior than the issue or PR claim. For example, the issue asks for a failure path, but the test only covers the normal path.

### Suspicious Fix Without Test

The PR appears to add or change behavior, but there is no corresponding test change or existing evidence chain. This finding should be phrased as a review risk, not as proof that the PR is wrong.

### Mocked Core Path

The test mocks, stubs, or patches the path that should provide evidence for the claim. Mocks are acceptable when they isolate dependencies, but not when they replace the behavior under review.

### CI Scope Weakening

The submitted validation scope appears weaker than the PR's affected behavior requires. Examples include skipped tests, narrowed test commands, excluded paths, or changed CI filters that reduce relevant coverage.

### Counterfactual Survivor

A counterfactual probe weakens, removes, or reverses the claimed behavior and the related tests still pass. This suggests the tests do not actually enforce the behavior named in the claim.

## Case Design

Future benchmark-style cases should be small, explicit, and artifact-backed. A case should make it possible to reproduce the evidence chain and compare Claim Harness against simpler baselines.

Example layout:

```text
cases/
  python/
    weak_assertion_001/
      issue.md
      pr.diff
      test.diff
      coverage.xml
      ci.log
      metadata.json
      expected_findings.json
```

File roles:

- `issue.md`: source material for the change claim.
- `pr.diff`: code changes that implement or appear to implement the claim.
- `test.diff`: added or modified tests and assertion changes.
- `coverage.xml` or `lcov.info`: coverage evidence for changed code.
- `ci.log`: evidence about which tests ran and whether they passed.
- `metadata.json`: language, test framework, case family, task type, and other case-level labels.
- `expected_findings.json`: human-labeled expected adequacy findings.

The repository should not add real cases until the case format and expected finding shape are clear enough to review.

## Initial Curated Case Families

The first curated cases should cover common ways an agentic PR can look tested while evidence remains inadequate:

- `weak_assertion_001`: changed code is executed by coverage, but the test only makes a weak assertion.
- `missing_test_001`: core behavior changes without related test evidence.
- `issue_test_mismatch_001`: the issue asks for a failure path, while the test covers only a normal path.
- `mocked_core_path_001`: the test mocks out the path changed by the PR.
- `fallback_without_test_001`: the PR adds fallback behavior, exception swallowing, or a default return without failure-path tests.
- `ci_scope_weakening_001`: CI passes after the validation scope is narrowed or relevant tests are skipped.
- `counterfactual_survivor_001`: removing or reversing the key fix still leaves the tests passing.

These families should be intentionally small at first. The goal is to validate the evidence model before expanding coverage across languages, frameworks, or agent workflows.

## Expected Output

A future runner or case evaluator should emit artifacts that preserve the evidence behind each finding:

- `findings.json`: normalized adequacy findings by claim.
- `evidence_chain.json`: claim-to-code-to-test-to-evidence links.
- `coverage_map.json`: changed line and branch coverage mapped to claims and tests where possible.
- `counterfactual_results.json`: probe definitions, outcomes, and affected claims.
- `mock_boundary_summary.json`: mocks, stubs, patches, and their relationship to the claimed behavior path.
- `claim_harness_report.md`: human-readable review report summarizing claims, evidence, and findings.

This document defines the intended output shape only. It does not require an implementation in this stage.

## Non-goals for This Stage

- No runner implementation yet.
- No CLI yet.
- No real curated cases yet.
- No GitHub Action integration yet.
- No claim that Claim Harness proves PR correctness.
- No broad multi-language support yet.
