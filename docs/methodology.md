# Methodology

PR Test Guard is a lightweight PR test-quality checker. It looks for review signals that are easy to miss when a pull request has passing tests or acceptable line coverage but the tests may still be incomplete, weak, mismatched, or over-isolated.

The project does **not** try to prove that a PR is correct. Its job is to make test-related review risk easier to inspect.

## Review Unit

The practical unit is a **PR change and the test evidence around it**.

For a changed behavior, PR Test Guard may inspect:

- changed production files and lines;
- added, modified, removed, skipped, or weakened tests;
- assertion shapes;
- changed-line coverage when available;
- explicit mock or patch boundaries;
- CI/test-run evidence;
- optional change-intent text from an issue, PR body, task, or structured fixture.

Change intent can improve mapping, but it is context rather than a requirement for every lightweight rule.

## Rule Philosophy

Rules should prefer signals that are:

1. **Local** — tied to a concrete PR diff, test, assertion, line, or CI artifact.
2. **Inspectable** — a reviewer can see why the signal fired.
3. **Deterministic by default** — the default path should not require an LLM.
4. **Cheap enough for CI** — lightweight checks should not require an expensive benchmark or hosted service.
5. **Advisory when uncertain** — heuristics should surface risk without pretending to know the final merge decision.

## Evidence Layers

### Test-diff evidence

The cheapest checks compare production-code changes with test changes. Useful signals include:

- production code changed but no test file changed;
- tests were deleted, skipped, or narrowed;
- assertions became visibly weaker;
- a behavioral fix has no obvious nearby test update.

These are review signals, not proof that testing is missing. Existing tests may already cover a change.

### Coverage evidence

Changed-line coverage answers whether changed executable code ran. It is valuable, but it should remain one input rather than the final verdict.

A covered branch can still be backed by a weak assertion. A passing test can still exercise the wrong behavior.

### Assertion evidence

The current Python prototype extracts assertion structure and can flag obvious weak patterns. This is intentionally conservative. An assertion that looks weak syntactically can still be meaningful in a richer test context, so this class of signal should be advisory by default.

### Mock-boundary evidence

Mocks are neutral. The current structural detector only raises a candidate when an explicit patch target overlaps changed code that appears central to the tested path.

A mock candidate should tell a reviewer where to look; it should not automatically fail a PR.

### Counterfactual evidence

The existing prototype can execute a small set of deterministic behavior weakenings and rerun pytest. Surviving probes can strengthen a test-quality warning.

This mechanism is retained as an advanced signal, not as a requirement for the lightweight product direction.

## Finding Model

The current prototype retains these finding families:

- `Missing Test Evidence`
- `Uncovered Changed Lines`
- `Weak Assertion`
- `Issue-Test Mismatch`
- `Suspicious Fix Without Test`
- `Mocked Core Path`
- `CI Scope Weakening`
- `Counterfactual Survivor`
- `Evidence Complete`

The public interpretation should be conservative. A finding is a **review signal**. `Evidence Complete` only means that the current fixture did not trigger the targeted evidence-gap rules; it is not a correctness certificate.

## CLI and CI Boundary

The core product should remain callable from a CLI. GitHub Actions is the first automated integration target, not the only runtime.

The intended shape is:

```text
PR Test Guard core
    -> local CLI / arbitrary CI
    -> GitHub Action wrapper
```

CI integration should be advisory by default. Repositories may later opt into stricter enforcement for specific high-confidence rules or project-defined thresholds.

## Current Limits

Version `0.1.0` still uses controlled Python/pytest fixtures to exercise the rule logic. It does not yet provide a general `check` command for arbitrary repositories or a reusable GitHub Action.

The immediate engineering goal is therefore not to add more research machinery. It is to extract the useful rule logic into a direct PR-facing workflow while keeping the current fixtures as regression tests.
