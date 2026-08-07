# Benchmark Protocol

This document defines the first comparison protocol for Claim Harness and simpler baselines.

The benchmark is intended to answer a narrow question:

> Given the same agentic-PR evidence surface, how accurately can a method identify whether test evidence supports each change claim?

The benchmark does not score overall PR correctness.

## Evaluation Unit

The primary unit is one labeled claim inside one case.

A case contains:

- an issue or task;
- one or more structured claims;
- a small executable repository fixture;
- a PR-like patch;
- human-authored expected findings;
- optional runtime artifacts added by later runner stages.

## Ground Truth

Ground truth must be defined independently from Claim Harness output.

For synthetic curated cases, the target defect is controlled by construction and documented in `expected_findings.json`.

For future real-world PRs, labels should follow `docs/annotation-guidelines.md`, use blind independent reviewers, and resolve disagreements through adjudication.

## Baselines

The initial benchmark should compare at least these perspectives.

### Coverage Only

Inputs:

- changed lines or branches;
- coverage evidence.

This baseline can identify uncovered changed code but should not infer semantic adequacy.

### Test-Diff Heuristic

Inputs:

- PR diff;
- test diff.

Possible signals include:

- whether tests changed;
- assertion shape;
- skips;
- mock additions;
- fallback or exception-handling changes.

The baseline should remain deterministic and intentionally simple.

### LLM Prompt Only

Inputs:

- issue or task;
- PR diff;
- test diff.

The model is prompted to identify evidence-adequacy findings without structured runtime evidence.

### LLM All Evidence

Once runtime artifacts exist, provide the LLM with the same available evidence surface used by Claim Harness:

- issue and claims;
- PR and test diffs;
- coverage;
- CI results;
- mock summary;
- counterfactual results when available.

This baseline helps separate the value of **more evidence** from the value of Claim Harness's structured evidence chain.

### Claim Harness

Uses the structured claim-evidence workflow defined by the project methodology.

## Output Contract for Comparison

Each evaluated method should normalize its output to:

```json
{
  "case_id": "weak_assertion_001",
  "claim_id": "C1",
  "findings": [
    {
      "type": "Weak Assertion",
      "evidence_refs": []
    }
  ]
}
```

Free-form explanations can be retained separately, but benchmark scoring should operate on normalized finding labels.

## Primary Metrics

Report:

- precision;
- recall;
- F1;
- per-finding precision, recall, and F1.

Do not rely only on a single aggregate score.

A method can be strong at `Uncovered Changed Lines` and weak at `Issue-Test Mismatch`; the benchmark should preserve that distinction.

## Secondary Metrics

Add these once implementations exist:

- run-to-run consistency;
- evidence-localization accuracy;
- latency;
- LLM token or API cost;
- number of findings requiring human correction.

## Ablations

Once Claim Harness has multiple evidence layers, compare:

- full Claim Harness;
- without semantic reasoning;
- without per-test coverage;
- without mock-boundary analysis;
- without counterfactual probes.

The goal is to show which components materially improve which finding families.

## Reporting Rules

Benchmark reports should:

1. distinguish synthetic and real-world results;
2. report case counts by finding family;
3. include confidence intervals when the sample size supports them;
4. disclose model and prompt versions for LLM baselines;
5. avoid claiming that benchmark success proves PR correctness;
6. retain enough evidence references to audit false positives and false negatives.
