# Roadmap and MVP Scope

Claim Harness started as a documentation and methodology seed. The repository now adds a small executable benchmark foundation so later implementation can be evaluated against fixed cases and ground truth.

The first implementation should stay narrow: enough structure to evaluate a few pull-request evidence patterns reproducibly, without turning into a general agent benchmark or a broad test-generation system.

## Current Scope

This repository now contains:

- Project positioning and workflow in `README.md`.
- Evaluation methodology in `docs/methodology.md`.
- Evaluation design in `docs/evaluation-design.md`.
- Human-labeling rules in `docs/annotation-guidelines.md`.
- Baseline comparison rules in `docs/benchmark-protocol.md`.
- Four executable Python/pytest micro-PR cases under `cases/python/`.
- A lightweight structural and executability validator in `scripts/validate_cases.py`.

There is still no Claim Harness runner, automated semantic layer, per-test coverage mapping, automated mock analysis, counterfactual generator, or end-to-end baseline implementation.

## Ecosystem Position

Claim Harness is adjacent to several existing categories, but it asks a different question.

| Category | Typical question | Claim Harness question |
| --- | --- | --- |
| SWE-bench-style issue benchmarks | Can the agent solve the issue? | After the agent submits a PR, do the tests support the PR's claims? |
| Patch coverage tools | Did tests execute changed lines? | Did executed tests assert the claimed behavior? |
| Test generation benchmarks | Can tests be generated for code? | Are the tests attached to this PR adequate evidence? |
| Agentic PR empirical studies | What patterns appear across generated PRs? | Can a reviewer inspect evidence adequacy for one PR reproducibly? |

The project should use restrained claims about novelty. The useful distinction is lifecycle and evidence focus, not a claim that related work is irrelevant.

## MVP Boundary

The practical MVP should aim for a small, inspectable workflow:

1. Curated Python/pytest cases with known weak and adequate evidence patterns.
2. A minimal claim and finding format.
3. A runner that can execute tests and collect coverage.
4. Manual or semi-structured claim extraction before full automation.
5. Baseline comparison against simple coverage-only and heuristic rules.
6. A semantic layer only where natural-language alignment is required.
7. Controlled mock-boundary and counterfactual analysis after the evidence chain is stable.

The MVP should avoid:

- Generating tests automatically.
- Running arbitrary untrusted repositories without isolation design.
- Scoring PR correctness.
- Treating an LLM judgment as the only evidence source.
- Expanding into many languages before the evaluation shape is stable.
- Emitting pseudo-precise confidence percentages before calibration data exists.

## Staged Evolution

### Stage 1: Curated Benchmark Foundation

**Status: initial version added.**

Maintain a small set of executable Python/pytest examples. Each case includes:

- an issue;
- manually structured claims;
- a base repository fixture;
- a PR-like patch;
- expected findings;
- metadata.

The first cases cover `Weak Assertion`, `Issue-Test Mismatch`, `Mocked Core Path`, and a positive `Evidence Complete` control.

The stage also defines annotation and benchmark protocols so ground truth is fixed before the main implementation is evaluated.

### Stage 2: Runner Skeleton

Add a lightweight runner that can:

- materialize or copy a case fixture;
- apply its PR patch;
- execute pytest;
- collect raw test results;
- collect line and branch coverage;
- preserve raw artifacts rather than immediately compressing them into a score.

### Stage 3: Per-Test Evidence Mapping

Connect:

```text
changed lines/functions -> exact pytest tests -> execution evidence
```

For the Python MVP, this stage can use diff parsing, Python AST information, pytest test IDs, and per-test coverage context.

Emit the first machine-readable `evidence_chain.json`.

### Stage 4: Initial Automated Findings

Implement the first deterministic or mostly deterministic findings:

- `Missing Test Evidence`;
- `Uncovered Changed Lines`;
- basic assertion extraction;
- obvious weak-assertion patterns.

Keep the rules auditable and report evidence references instead of a single opaque score.

### Stage 5: Semantic Alignment

Introduce an LLM-assisted semantic layer for tasks that genuinely require natural-language understanding:

- issue or PR text to structured claims;
- claim-to-code mapping where structural mapping is insufficient;
- claim-to-assertion semantic alignment;
- distinction between nearby but materially different test behavior.

The LLM should propose or interpret semantics; structural and runtime artifacts remain the primary evidence.

### Stage 6: Mock Boundary Analysis

Start with explicit Python mock patterns:

- `unittest.mock.patch`;
- `pytest` monkeypatch;
- common `mocker.patch` forms.

First detect mock targets structurally. Then determine whether the mock merely isolates a dependency or replaces the behavior named by the claim.

### Stage 7: Controlled Counterfactual Probes

Introduce reproducible claim-guided probes.

Progress from:

1. manually authored counterfactual patches in curated cases;
2. simple rule/AST-based mutations;
3. optional LLM-guided mutation proposals validated and executed by the harness.

A `Counterfactual Survivor` requires an actual rerun result, not an LLM prediction.

### Stage 8: Baseline Benchmark

Run the same labeled case suite through:

- coverage only;
- deterministic heuristic baseline;
- LLM prompt-only baseline;
- LLM all-evidence baseline;
- Claim Harness.

Report precision, recall, F1, and per-finding results. Add stability, cost, and evidence-localization metrics as the implementations mature.

### Stage 9: Real-World Agentic PR Validation

Expand beyond synthetic cases only after the evaluation contract is stable.

Use:

- real agent-generated PRs;
- blind human labeling;
- adjudication;
- inter-annotator agreement;
- a clearly separated real-world benchmark split.

## Design Principles

- Evidence should be auditable by humans.
- Ground truth should be independent from Claim Harness output.
- Findings should explain why evidence is adequate or inadequate.
- Coverage should remain an input, not the final answer.
- LLM reasoning should handle semantics, not replace runtime evidence.
- Mocks should be evaluated relative to the claim, not treated as inherently suspicious.
- Counterfactual findings should be backed by executed probes.
- Benchmarks should prefer small, clear cases before scale.
- The harness should help reviewers find risk, not certify correctness.
