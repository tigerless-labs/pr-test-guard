# Claim Harness

**Evaluate whether agentic PRs have enough test evidence to support their change claims - not just covered lines or passing CI.**

Claim Harness is a documentation-first project seed for evaluating the test evidence behind AI-generated pull requests. It focuses on the review question that normal CI and coverage reports often leave unanswered: did the tests actually support the behavior the PR claims to change?

## Why This Exists

AI coding agents can now turn an issue, task description, or PR comment into a complete pull request. Reviewers often start with familiar signals: CI passed, tests ran, and changed lines were covered. Those signals are useful, but they do not prove that the intended behavior was tested.

The risky case is a PR that looks tested while its evidence is thin:

- The changed code executed, but no meaningful assertion constrained the behavior.
- Tests exercised a fallback path but never checked the failure mode.
- Mocks replaced the core path the PR claims to fix.
- The issue asked for one behavior, while the test targets a nearby but different one.
- CI passed because the relevant test scope was narrowed.

Claim Harness treats coverage as one piece of an evidence chain, not as the final answer.

## What It Evaluates

Claim Harness is centered on this evaluation frame:

```text
change claim -> evidence chain -> counterfactual probe -> mock boundary -> adequacy findings
```

It aims to connect:

- **Change claims:** what the PR says it changed, from the issue, PR text, commits, and diff.
- **Evidence chains:** which tests, assertions, coverage spans, and CI runs support each claim.
- **Counterfactual probes:** whether tests would fail if the claimed behavior were removed or weakened.
- **Mock boundaries:** whether tests replace the behavior they are supposed to validate.
- **Adequacy findings:** reviewable conclusions about missing, weak, mismatched, or complete evidence.

Initial finding concepts include:

| Finding | Meaning |
| --- | --- |
| `Missing Test Evidence` | A claim has no clear test evidence attached. |
| `Uncovered Changed Lines` | Changed behavior is not executed by the relevant tests. |
| `Weak Assertion` | Code is executed, but assertions do not constrain the claimed behavior. |
| `Issue-Test Mismatch` | Tests target a different behavior than the issue or claim describes. |
| `Suspicious Fix Without Test` | A behavioral fix appears in the diff without a corresponding test change or existing test link. |
| `Mocked Core Path` | The test mocks or stubs the path that should provide evidence. |
| `CI Scope Weakening` | The tested CI scope appears narrower than the PR's affected behavior. |
| `Counterfactual Survivor` | A weakened or removed behavior still passes the attached tests. |
| `Evidence Complete` | The current evidence chain is relatively complete; this does not mean the PR is correct. |

## What It Is Not

- Not a generic coverage reporter.
- Not a SWE-bench clone.
- Not a test generation agent.
- Not a pure LLM judge.
- Not a replacement for human review.

SWE-bench-style evaluations ask whether an agent can solve an issue. Patch coverage tools ask whether changed lines were executed. Test generation benchmarks ask whether tests can be produced. Claim Harness starts later in the lifecycle: an agent has already submitted a PR, and a reviewer needs to understand whether the PR's tests support its claims.

## Core Workflow

1. **Extract claims** from the issue, task text, PR description, commits, and diff.
2. **Map evidence** from test diffs, existing tests, coverage output, and CI logs.
3. **Check alignment** between each claim and the tests that allegedly support it.
4. **Probe counterfactuals** by weakening or removing claimed behavior and observing whether tests fail.
5. **Inspect mock boundaries** to identify tests that skip the core behavior.
6. **Report findings** in a form a human reviewer can audit and challenge.

## Curated Benchmark Foundation

The repository now includes the first executable Python/pytest micro-PR cases under `cases/python/`.

The initial cases intentionally isolate four evidence patterns:

- `weak_assertion_001`
- `issue_test_mismatch_001`
- `mocked_core_path_001`
- `evidence_complete_001`

Each case includes an issue, structured claim, executable repository fixture, PR-like patch, metadata, and expected findings defined independently from Claim Harness output.

The benchmark foundation is intentionally small. Its purpose is to stabilize the case contract and ground-truth rules before implementing the full runner or automated semantic analysis.

Validate the case structure:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/validate_cases.py
```

Apply each patch in a temporary copy and run the patched pytest fixture:

```bash
python3 scripts/validate_cases.py --run
```

The `--run` mode requires `git` and `pytest` in the local environment.

Generate evidence artifacts and v0 adequacy findings for the curated cases:

```bash
python3 scripts/run_case.py
```

The runner writes per-case artifacts under `artifacts/`, including test results, coverage evidence, test/assertion summaries, mock-boundary summaries, limited counterfactual probe results, an evidence chain, generated findings, expected-finding comparison, and a short Markdown report.

Validate real PR input bundles:

```bash
python3 scripts/validate_real_pr_bundles.py
```

Optionally extract LLM-assisted claim candidates for a real PR bundle:

```bash
OPENAI_API_KEY=... OPENAI_MODEL=... python3 scripts/extract_claim_candidates.py \
  examples/real-pr-bundles/claim-harness-pr-5
```

This optional script requires `requirements-llm.txt`. It emits candidate claims only, not adequacy findings.

## Project Documents

- [Methodology](docs/methodology.md): how claims, evidence chains, probes, and mock-boundary checks fit together.
- [Evaluation Design](docs/evaluation-design.md): how cases, baselines, findings, and expected outputs are organized.
- [Real PR Input Bundles](docs/real-pr-input.md): how real PR artifacts and LLM-assisted claim candidates should be organized.
- [Annotation Guidelines](docs/annotation-guidelines.md): how human ground truth should be created without using Claim Harness output.
- [Benchmark Protocol](docs/benchmark-protocol.md): how coverage, heuristic, LLM, and Claim Harness methods should be compared.
- [Runner Artifacts](docs/runner-artifacts.md): what the curated-case runner emits for evidence, findings, mock boundaries, and probes.
- [Roadmap](docs/roadmap.md): the MVP boundary and staged evolution.

## Current Scope

This repository now contains documentation plus the first executable benchmark fixtures, a lightweight case validator, a curated-case evidence runner with v0 deterministic findings, and a dogfood real PR input bundle.

It still does **not** include:

- a full general-purpose Claim Harness adequacy runner for arbitrary repositories;
- default automated claim extraction;
- automated real PR ingestion;
- per-test coverage mapping;
- automated LLM semantic reasoning;
- broad mock-boundary classification beyond explicit Python mock patterns;
- broad counterfactual generation beyond limited deterministic probe templates;
- a reusable GitHub Action for external PR review.

The next implementation stage is to make the runner callable from other projects with a stable artifact contract and clearer packaging boundaries.

## Later Direction

Future work can add stable finding schemas, baseline implementations, per-test coverage, semantic claim alignment, broader mock-boundary analysis, broader controlled counterfactual probes, and real-world agentic PR evaluation.

The goal is to make evidence-adequacy review repeatable without pretending that any automated harness can prove a PR correct.
