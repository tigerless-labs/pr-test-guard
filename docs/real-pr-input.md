# Real PR Input Bundles

This document defines the first input contract for bringing real agentic PRs into Claim Harness. Curated cases remain the benchmark foundation; real PR bundles are the bridge to reviewer-facing usage.

The goal is to preserve the evidence surface for a PR without pretending every artifact is always available.

## Bundle Goal

A real PR bundle should answer:

```text
what did the PR claim -> what changed -> what tests changed or ran -> what evidence is present -> what is missing
```

The bundle is not a finding report. It is the normalized input that later runner stages can use for coverage mapping, semantic alignment, mock-boundary analysis, counterfactual probes, and deterministic findings.

## Layout

Use one directory per PR:

```text
examples/real-pr-bundles/<bundle_id>/
  README.md
  bundle.json
  pr.json
  pr.diff
  ci-summary.md
  claim_candidates.json
  missing_artifacts.json
```

Optional artifacts can be added when available:

```text
  issue.md
  task.md
  test-result.json
  ci.log
  coverage.xml
  lcov.info
  mock-boundary.json
  counterfactual-results.json
```

## Artifact Sources

| Artifact | Source | Notes |
| --- | --- | --- |
| `issue.md` or `task.md` | Issue tracker, task brief, PR prompt, or review request | At least one source of intended behavior is preferred. If absent, record the gap. |
| `pr.json` | Hosting provider API or CLI | Should include PR number, URL, title, body, author, base/head refs, merge status, commit ids, and changed-file counts. |
| `pr.diff` | Hosting provider diff endpoint or CLI | Source of changed code units and test diff. |
| `ci-summary.md` | CI provider check summary | Should record check names, status, URLs, and relevant commands when known. |
| `test-result.json` or `ci.log` | CI logs or local runner output | Evidence that tests actually ran. |
| `coverage.xml` or `lcov.info` | CI artifact or local coverage run | Coverage is evidence, not the final adequacy answer. |
| `claim_candidates.json` | Manual or LLM-assisted extraction | Candidate claims must be reviewed and linked back to source artifacts. |
| `missing_artifacts.json` | Bundle author | Explicit record of unavailable inputs and expected impact. |

## LLM-Assisted Claim Candidates

LLM use is appropriate for candidate extraction and summarization, but not as the final judge.

The claim-candidate step may use an LLM to propose structured change claims from:

- issue or task text;
- PR title and body;
- PR diff;
- test diff summary.

The output must remain a candidate artifact:

- It should be stored as `claim_candidates.json`.
- It should include source references and confidence notes.
- It should be reviewable and editable.
- It must not create `Evidence Complete`.
- It must not replace test execution, coverage evidence, CI evidence, mock-boundary analysis, or counterfactual probes.

If an LLM is used later in automation, it should propose claims or mappings that the harness verifies with structured artifacts. A prompt-only adequacy judgment should remain a baseline, not the core method.

## Missing Artifacts

Missing evidence should be explicit. A bundle should not silently omit unavailable inputs.

Use `missing_artifacts.json` to record:

- the missing artifact name;
- whether it is required or optional for the current stage;
- why it is missing;
- the expected impact on evidence adequacy review.

Example:

```json
{
  "missing": [
    {
      "artifact": "coverage.xml",
      "required_for_stage": false,
      "reason": "No coverage artifact was published for the PR.",
      "impact": "Changed-line execution cannot be evaluated from this bundle yet."
    }
  ]
}
```

Missing artifacts should lower confidence in the evidence chain, but they should not force the harness to invent evidence.

## Relationship to Curated Cases

Curated cases define controlled ground truth. Real PR bundles define ingestion shape.

Do not use a real PR bundle as benchmark ground truth unless it has been independently labeled under `docs/annotation-guidelines.md`. A dogfood bundle can validate artifact organization without becoming a scored case.

Validate bundle structure:

```bash
python3 scripts/validate_real_pr_bundles.py
```

## Non-goals

This input contract does not:

- implement a GitHub ingestion client;
- call an LLM API;
- create automated findings;
- score real PRs;
- require coverage to exist for every PR;
- replace human review.
