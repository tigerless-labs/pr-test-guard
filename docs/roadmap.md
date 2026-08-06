# Roadmap and MVP Scope

Claim Harness starts as a documentation and methodology seed. The first implementation should stay narrow: enough structure to evaluate a few real pull requests reproducibly, without turning into a general agent benchmark or a broad test-generation system.

## Current Scope

This repository currently contains the initial documentation only:

- Project positioning and workflow in `README.md`.
- Evaluation methodology in `docs/methodology.md`.
- Evaluation design for future cases, baselines, findings, and outputs in `docs/evaluation-design.md`.
- MVP boundary and staged roadmap in this document.

There is no runner, CLI, benchmark case set, baseline comparison, or finding schema implementation yet.

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

The first practical MVP should aim for a small, inspectable workflow:

1. Curated Python/pytest cases with known weak and adequate evidence patterns.
2. A minimal claim and finding format.
3. A runner skeleton that can collect test output and coverage.
4. Manual or semi-structured claim extraction before full automation.
5. Baseline comparison against simple coverage-only rules.

The MVP should avoid:

- Generating tests automatically.
- Running arbitrary untrusted repositories without isolation design.
- Scoring PR correctness.
- Treating an LLM judgment as the only evidence source.
- Expanding into many languages before the evaluation shape is stable.

## Staged Evolution

### Stage 1: Curated Cases

Add a small set of intentionally simple Python/pytest examples. Each case should follow the evaluation design in `docs/evaluation-design.md` and include a PR-like diff, an issue claim, test evidence, and expected findings such as `Weak Assertion`, `Mocked Core Path`, or `Evidence Complete`.

### Stage 2: Runner Skeleton

Add a lightweight runner that can execute tests, collect coverage, and emit raw artifacts. The runner should preserve evidence rather than immediately compressing it into a single score.

### Stage 3: Findings Format

Define a stable report shape that links each finding to claims, tests, coverage spans, probes, and CI evidence. The format should be easy to review in a PR comment or local artifact.

### Stage 4: Counterfactual Probes

Introduce controlled probes for selected cases. Early probes can be simple mutations that remove or weaken the claimed behavior, with clear limits and reproducibility notes.

### Stage 5: Mock Boundary Analysis

Add heuristics and language-specific analysis for identifying when mocks replace the core path under review. This should start with explicit patterns in curated cases before expanding.

## Design Principles

- Evidence should be auditable by humans.
- Findings should explain why evidence is adequate or inadequate.
- Coverage should remain an input, not the final answer.
- Benchmarks should prefer small, clear cases before scale.
- The harness should help reviewers find risk, not certify correctness.
