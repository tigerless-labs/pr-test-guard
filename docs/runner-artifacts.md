# Runner Artifacts

This document describes the first raw artifact runner for curated Claim Harness cases. The runner is not the full evidence-adequacy engine. It prepares the inputs that later stages can use for coverage mapping, semantic alignment, mock-boundary analysis, counterfactual probes, and baseline comparison.

## Purpose

The curated cases already define issues, structured claims, PR-like patches, executable fixtures, metadata, and expected findings. The runner adds a reproducible execution layer:

```text
case fixture -> patched working copy -> pytest result -> raw evidence artifacts
```

The first version deliberately stops before automated adequacy judgment. It should preserve evidence, not collapse the case into a single score.

## Command

Run all curated Python cases:

```bash
python3 scripts/run_case.py
```

Run one case:

```bash
python3 scripts/run_case.py --case weak_assertion_001
```

Write artifacts somewhere other than `artifacts/`:

```bash
python3 scripts/run_case.py --output-dir /tmp/claim-harness-artifacts
```

The runner requires `git` and `pytest` in the local environment.

## Generated Files

For each case, the runner writes:

```text
artifacts/
  weak_assertion_001/
    case_summary.json
    test_result.json
    evidence_chain_stub.json
    expected_findings.json
    claim_harness_report.md
```

### `case_summary.json`

Summarizes the case id, runner version, metadata, claim count, patch files, changed code files, test files, generated artifact names, and whether the patched fixture tests passed.

### `test_result.json`

Records the command, return code, pass/fail status, stdout, and stderr for the patched fixture test run. If patch application fails, this file records the patch failure instead.

### `evidence_chain_stub.json`

Connects each structured claim to the code files changed by the patch and the test files changed by the patch. Coverage evidence and automated adequacy findings are intentionally left empty in this version.

### `expected_findings.json`

Copies the human-labeled expected findings into the artifact directory so later benchmark tooling can compare method output against stable ground truth.

### `claim_harness_report.md`

Provides a small human-readable report for the case. It summarizes the claims and points to the machine-readable artifacts.

## Non-goals

This runner does not:

- collect coverage yet;
- produce `findings.json`;
- infer claim adequacy;
- call an LLM;
- classify mock boundaries;
- generate counterfactual probes;
- score baselines.

Those stages should build on the raw artifacts rather than replace them.
