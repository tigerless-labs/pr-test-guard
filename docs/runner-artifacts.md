# Runner Artifacts

This document describes the current regression-fixture runner for PR Test Guard.

The runner predates the direct PR-facing CLI and is retained because it already exercises useful rule logic end to end: apply a PR-like patch, run tests, collect coverage and static evidence, emit findings, and compare them with fixture expectations.

## Run It

```bash
python3 -m pr_test_guard run-cases
```

Run one fixture:

```bash
python3 -m pr_test_guard run-cases --case weak_assertion_001
```

Choose an output directory:

```bash
python3 -m pr_test_guard run-cases --output-dir /tmp/pr-test-guard-artifacts
```

## Artifact Layout

```text
artifacts/<case_id>/
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
  pr_test_guard_report.md
```

## Core Artifacts

### `test_result.json`

Records whether the patched fixture tests passed and preserves stdout/stderr needed for review.

### `coverage_result.json` and `coverage.xml`

Preserve suite-level coverage execution. Coverage is evidence, not a test-quality verdict.

### `coverage_map.json`

Maps changed executable lines to coverage evidence where available.

### `test_diff_summary.json`

Summarizes changed test files and test functions found in the PR-like patch.

### `assertion_summary.json`

Captures assertion structure used by the current deterministic weak-assertion rules.

### `mock_boundary_summary.json`

Records explicit Python mock targets and whether they overlap changed functions/classes. Matches are candidate signals, not proof that mocking is inappropriate.

### `counterfactual_results.json`

Records limited deterministic probes that were actually applied and rerun. These are advanced signals retained from the original prototype.

### `evidence_chain.json`

Keeps current internal links between change intent, changed code, tests, runtime evidence, and findings. The public product no longer depends on calling this structure a harness; it remains useful implementation data while the direct PR-facing rule engine is extracted.

### `findings.json`

Contains normalized rule findings and evidence references.

### `comparison_summary.json`

Compares generated findings with the fixture's expected output. This is an internal regression check, not a public benchmark score.

### `expected_findings.json`

Copies the controlled fixture expectation into the artifact directory so rule changes remain auditable.

### `pr_test_guard_report.md`

Human-readable report for the fixture. Findings are review signals and do not certify PR correctness.

## Stability

Version `0.2.3` remains early. Artifact fields may evolve as the older fixture runner continues to follow the direct PR-facing CLI.

Changes should preserve two properties:

1. findings remain tied to inspectable evidence;
2. existing fixtures continue to catch unintended rule regressions.
