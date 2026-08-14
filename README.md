<h1 align="center">Claim Harness</h1>

<p align="center">
  <img src="https://img.shields.io/badge/release-v0.1.0-brightgreen.svg" alt="release v0.1.0" /> <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" /> <img src="https://img.shields.io/badge/output-JSON%20%7C%20Markdown-lightgrey.svg" alt="JSON and Markdown output" /> <img src="https://img.shields.io/badge/scope-curated%20Python%2Fpytest%20cases-yellow.svg" alt="curated Python pytest cases" /> <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license MIT" />
</p>

**Evaluate whether agentic PRs have enough test evidence to support their change claims - not just covered lines or passing CI.**

Claim Harness is an early evidence-adequacy runner for AI-generated pull requests. It helps reviewers inspect whether a PR's tests support the behavior the PR claims to change, especially when the PR looks tested but the evidence is weak, mismatched, over-mocked, or only superficially covered.

The current release provides a runnable curated-case loop, deterministic v0 findings, explicit Python mock-boundary candidates, limited counterfactual probes, normalized real-PR input bundles, and an optional LLM-assisted claim-candidate script. It does not prove a PR correct and does not replace human review.

| | |
| --- | --- |
| **Claim-centered evidence** | Connects structured change claims to changed code, tests, coverage, mock boundaries, probe results, and findings. |
| **Coverage as evidence, not the verdict** | Changed-line coverage is preserved and compared, but weak assertions and mismatched tests can still be reported. |
| **Executed counterfactual probes** | Limited deterministic probes weaken common behavior signals and rerun pytest before reporting survivors. |
| **Mock-boundary candidates** | Explicit Python mock targets are mapped back to changed functions/classes to surface possible core-path replacement. |
| **Agent-agnostic input shape** | Real PR artifacts are normalized into bundles so the core runner is not tied to one AI agent's PR style. |
| **Optional LLM claim extraction** | LLM use is limited to candidate claims by default, not adequacy judgment. |

## Quick Start

Clone the repository and run the curated Python/pytest cases. Version `0.1.0`
is intended for source-tree use and is not published to PyPI yet:

```bash
python3 -m pip install -e .
python3 -m claim_harness --version
python3 -m claim_harness validate-cases
python3 -m claim_harness validate-cases --run
python3 -m claim_harness run-cases --output-dir /tmp/claim-harness-artifacts
```

The same commands are available through the console script after editable install:

```bash
claim-harness validate-cases
claim-harness run-cases --case weak_assertion_001 --output-dir /tmp/claim-harness-artifacts
```

The legacy script entrypoints remain supported:

```bash
python3 scripts/validate_cases.py
python3 scripts/validate_cases.py --run
python3 scripts/run_case.py --output-dir /tmp/claim-harness-artifacts
```

Validate the synthetic normalized real-PR input bundle:

```bash
python3 -m claim_harness validate-real-pr-bundles
```

## What It Evaluates

Claim Harness is centered on this review frame:

```text
change claim -> evidence chain -> counterfactual probe -> mock boundary -> adequacy findings
```

It aims to connect:

- **Change claims:** what the PR says it changed, from the issue, task text, PR body, commit context, or diff.
- **Evidence chains:** which tests, assertions, coverage spans, and test runs support each claim.
- **Counterfactual probes:** whether tests fail when a claimed behavior is weakened by a controlled mutation.
- **Mock boundaries:** whether tests replace the behavior path they are supposed to validate.
- **Adequacy findings:** reviewable conclusions about missing, weak, mismatched, or relatively complete evidence.

Initial finding types:

| Finding | Meaning |
| --- | --- |
| `Missing Test Evidence` | A claim has no clear test evidence attached. |
| `Uncovered Changed Lines` | Changed behavior is not executed by the relevant tests. |
| `Weak Assertion` | Code is executed, but assertions do not constrain the claimed behavior. |
| `Issue-Test Mismatch` | Tests target a different behavior than the issue or claim describes. |
| `Suspicious Fix Without Test` | A behavioral fix appears in the diff without a corresponding test change or existing test link. |
| `Mocked Core Path` | A test mock or stub appears to replace the path that should provide evidence. |
| `CI Scope Weakening` | The tested CI scope appears narrower than the PR's affected behavior. |
| `Counterfactual Survivor` | A weakened or removed behavior still passes the attached tests. |
| `Evidence Complete` | The current evidence chain is relatively complete; this does not mean the PR is correct. |

## Current Runner

The repository ships four executable Python/pytest micro-PR cases under `cases/python/`:

- `weak_assertion_001`
- `issue_test_mismatch_001`
- `mocked_core_path_001`
- `evidence_complete_001`

Each case includes an issue, structured claim, executable base fixture, PR-like patch, metadata, and human-authored expected findings.

For each case, the runner writes:

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
  claim_harness_report.md
```

`comparison_summary.json` compares generated finding labels with the human-authored expected labels. It is useful for benchmark iteration, but it is not a claim that the harness has solved general PR review.

## Real PR Bundles

Agentic PRs vary by source: one agent may write a detailed PR body, another may rely on an issue, a task prompt, commits, or comments. Claim Harness keeps those differences outside the core runner.

The intended path is:

```text
agent-specific PR artifacts -> normalized real PR bundle -> claim candidates -> evidence artifacts -> findings
```

A normalized bundle can include:

- `issue.md` or `task.md`
- `pr.json`
- `pr.diff`
- `ci-summary.md`
- `test-result.json` or `ci.log`
- `coverage.xml` or `lcov.info`
- `claim_candidates.json`
- `missing_artifacts.json`

Missing artifacts should be recorded explicitly instead of silently ignored. See [Real PR Input Bundles](docs/real-pr-input.md).

## Mock and Probe Boundaries

The current mock detector is structural. It recognizes explicit Python patterns such as `patch`, `patch.object`, `monkeypatch.setattr`, and `mocker.patch`, then checks whether the target matches a changed function or class. That produces a mock-boundary candidate; it does not prove the mock is wrong.

The current probe generator is deterministic and limited. It covers common status-code weakening, boolean return flips, simple retry-limit rollback, and basic inclusive-boundary comparison weakening. A `Counterfactual Survivor` requires an actual pytest rerun result.

LLM-based semantic assessment is intentionally not on the default path. A later optional layer can help classify whether a mock isolates a dependency or replaces the claim's core behavior, but structural artifacts and executed tests should remain the primary evidence.

## Optional LLM Claim Candidates

Install the optional dependency and provide an API key only if you want LLM-assisted claim extraction:

```bash
python3 -m pip install -e ".[llm]"
OPENAI_API_KEY=... OPENAI_MODEL=... python3 scripts/extract_claim_candidates.py \
  examples/real-pr-bundles/normalized-pr-bundle-001
```

This emits candidate claims only. It must not create `Evidence Complete`, judge adequacy, or replace test execution, coverage, CI evidence, mock-boundary analysis, or counterfactual probes.

## What It Is Not

- Not a generic coverage reporter.
- Not a SWE-bench clone.
- Not a test generation agent.
- Not a pure LLM judge.
- Not a mutation-testing framework.
- Not a replacement for human review.

SWE-bench-style evaluations ask whether an agent can solve an issue. Patch coverage tools ask whether changed lines were executed. Claim Harness starts later in the lifecycle: an agent has already submitted a PR, and a reviewer needs to inspect whether the PR's tests support its claims.

## Project Documents

- [Methodology](docs/methodology.md): how claims, evidence chains, probes, and mock-boundary checks fit together.
- [Evaluation Design](docs/evaluation-design.md): how cases, baselines, findings, and expected outputs are organized.
- [Real PR Input Bundles](docs/real-pr-input.md): how real PR artifacts and LLM-assisted claim candidates should be organized.
- [Annotation Guidelines](docs/annotation-guidelines.md): how human ground truth should be created without using Claim Harness output.
- [Benchmark Protocol](docs/benchmark-protocol.md): how coverage, heuristic, LLM, and Claim Harness methods should be compared.
- [Runner Artifacts](docs/runner-artifacts.md): what the curated-case runner emits for evidence, findings, mock boundaries, and probes.
- [Roadmap](docs/roadmap.md): the MVP boundary and staged evolution.

## Current Scope

Version `0.1.0` contains a source-tree runner for curated Python/pytest cases and normalized real-PR input validation.

It still does **not** include:

- a safe general-purpose runner for arbitrary external repositories;
- default automated claim extraction;
- automated GitHub ingestion;
- per-test coverage mapping;
- default LLM semantic reasoning;
- broad mock-boundary classification beyond explicit Python mock patterns;
- broad counterfactual generation beyond limited deterministic probe templates;
- a reusable GitHub Action for external PR review.

The goal is to make evidence-adequacy review repeatable without pretending that any automated harness can prove a PR correct.

## License

[MIT](LICENSE)
