# Runner Artifacts

This document describes the curated-case runner for Claim Harness. The runner is not a full general-purpose evidence-adequacy engine, but it now executes the first closed loop for benchmark cases: collect evidence, run limited probes, inspect explicit mock boundaries, emit v0 findings, and compare them with expected labels.

## Purpose

The curated cases already define issues, structured claims, PR-like patches, executable fixtures, metadata, and expected findings. The runner adds a reproducible evaluation layer:

```text
case fixture -> patched working copy -> pytest + coverage -> mock/probe checks -> findings
```

The runner preserves evidence instead of collapsing the case into a single score. Its findings are deterministic review-support signals for curated Python/pytest cases, not proof that a PR is correct.

## Command

Run all curated Python cases:

```bash
python3 -m pip install -e .
python3 -m claim_harness run-cases
```

Run one case:

```bash
python3 -m claim_harness run-cases --case weak_assertion_001
```

Write artifacts somewhere other than `artifacts/`:

```bash
python3 -m claim_harness run-cases --output-dir /tmp/claim-harness-artifacts
```

The legacy script entrypoint remains available as `python3 scripts/run_case.py`.

The runner requires `git` and `pytest` in the local environment.
It also requires `coverage` for coverage artifacts.

## Generated Files

For each case, the runner writes:

```text
artifacts/
  weak_assertion_001/
    case_summary.json
    test_result.json
    coverage_result.json
    coverage.xml
    coverage_map.json
    test_diff_summary.json
    assertion_summary.json
    mock_boundary_summary.json
    counterfactual_results.json
    evidence_chain.json
    findings.json
    comparison_summary.json
    expected_findings.json
    claim_harness_report.md
```

### `case_summary.json`

Summarizes the case id, runner version, metadata, claim count, patch files, changed code files, changed code line count, test files, generated artifact names, and whether the patched fixture tests passed.

### `test_result.json`

Records the command, return code, pass/fail status, stdout, and stderr for the patched fixture test run. If patch application fails, this file records the patch failure instead.

### `coverage.xml`

Cobertura-style XML emitted by `coverage xml` after running the patched fixture tests.

### `coverage_map.json`

Maps changed code lines from `pr.patch` to coverage hits from `coverage.xml`.

### `test_diff_summary.json`

Lists discovered pytest test functions in changed test files.

### `assertion_summary.json`

Lists Python `assert` statements in changed test files and records a simple assertion shape such as comparison, truthiness check, or existence check.

### `mock_boundary_summary.json`

Lists explicit Python mock targets found in changed test files. The v0 detector recognizes common `unittest.mock.patch`, `patch.object`, `monkeypatch.setattr`, and `mocker.patch`-style calls, then marks mocks whose target matches a changed function or class as core-path candidates.

Mocks are not treated as inherently bad. The suspicious case is when the mock replaces the same path the claim requires the test to validate.

This artifact should be read as a candidate boundary map, not a complete semantic judgment. Determining whether a mock isolates a dependency or replaces the claim's core behavior may require claim-relative analysis or human review.

### `counterfactual_results.json`

Records limited deterministic probes generated from changed code lines. The v0 probe templates weaken common behavior signals such as HTTP error returns, boolean returns, and simple retry limits, then rerun the patched pytest suite.

A surviving probe means the weakened behavior still passed the tests. This can support a `Counterfactual Survivor` finding.

Current templates include:

- HTTP status weakening for common failure statuses such as `400`, `401`, `403`, `404`, `422`, and `500`;
- boolean return flips;
- simple retry-limit rollback;
- basic inclusive-boundary comparison weakening.

The probe runner clears Python bytecode caches around each mutation so reruns execute the changed source, not stale `.pyc` files.

### `evidence_chain.json`

Connects each structured claim to changed code files, changed code lines, related test files, test-result evidence, coverage-map evidence, mock-boundary evidence, counterfactual evidence, and generated adequacy findings.

### `findings.json`

Contains v0 generated findings by claim. The current deterministic rules cover:

- `Evidence Complete`;
- `Missing Test Evidence`;
- `Uncovered Changed Lines`;
- `Weak Assertion`;
- `Issue-Test Mismatch`;
- `Mocked Core Path`;
- `Counterfactual Survivor`.

The runner intentionally keeps the rationale and evidence references visible so reviewers can challenge the finding.

### `comparison_summary.json`

Compares generated finding labels with `expected_findings.json` for each claim. It reports exact label matches, missing expected labels, and extra generated labels. This artifact supports benchmark iteration; it does not fail the run by itself.

### `expected_findings.json`

Copies the human-labeled expected findings into the artifact directory so later benchmark tooling can compare method output against stable ground truth.

### `claim_harness_report.md`

Provides a small human-readable report for the case. It summarizes the claims and points to the machine-readable artifacts.

## Non-goals

This runner does not:

- evaluate arbitrary external repositories safely;
- call an LLM;
- perform per-test coverage mapping;
- run broad semantic claim alignment;
- classify CI scope weakening from real CI configuration;
- score baselines end to end.

Those stages should build on these artifacts rather than replace them.

## Stability

The artifact names above are the public v0 contract for the curated-case runner. Field-level schemas may still evolve while the benchmark suite is small, but changes should preserve reviewability: every generated finding should keep evidence references and a rationale that can be inspected without trusting an opaque score.
