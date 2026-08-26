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

Mocks are neutral. The current structural detector raises a candidate when an explicit patch target overlaps changed code that appears central to the tested path, or when a changed test mocks an internal dependency called on a changed production line without a clear interaction or owner-outcome assertion.

A mock candidate should tell a reviewer where to look; it should not automatically fail a PR. A dependency mock that constrains the changed owner's interaction contract, return value, or exception behavior is treated differently from a mock that simply replaces behavior and then makes a weak existence assertion.

The constrained dependency check is deliberately narrow. It looks for inspectable test evidence such as `assert_called_once_with`, `assert_called_with`, `call_args` / `call_count` assertions, non-weak assertions over the changed owner result, or `pytest.raises` around the owner call. It does not infer full business intent or decide that a mock is inherently appropriate.

### Counterfactual evidence

The direct checker can execute a small set of deterministic behavior weakenings against changed Python lines. This path is opt-in through `--deep`, requires an explicit test command, and runs in an isolated Git worktree. Surviving probes can strengthen a test-quality warning.

This is a bounded PR-scoped signal, not a full mutation-testing campaign or repository-wide mutation score. A generated probe is only a candidate. If the baseline test command fails, PTG006 is skipped. If the configured tests kill the probe, no warning is emitted. Unsupported shapes such as response constructors, symbolic HTTP status constants, and unstable multi-line rewrites remain quiet by design.

## Finding Model

The direct checker uses six stable rule ids for the current Python/pytest scope:

- `PTG001` — production code changed with no test-file change;
- `PTG002` — changed Python line uncovered in a supplied coverage XML;
- `PTG003` — possible weak assertion added in a changed test;
- `PTG004` — suspicious test deletion, skip/xfail, or assertion removal;
- `PTG005` — a mock directly replaces a changed Python symbol, or a changed test mocks an unconstrained internal dependency called on a changed production line;
- `PTG006` — bounded targeted probe survives the configured tests.

Each result includes a rule id, advisory severity, file/line where available, a short message, and evidence text. The older fixture runner retains its research-prototype labels only so existing regression fixtures remain stable during the transition.

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

Version `0.2.2` provides a repository-native `check` command, a reusable GitHub Action, AST-scoped targeted probes, and PTG005 constrained dependency-mock suppression for the current Python/pytest scope. The checker is intentionally conservative: it does not infer full PR correctness, automatically discover every project's test command, or treat heuristic signals as merge-blocking failures.

The immediate engineering goal is real-PR dogfooding and false-positive reduction. Controlled fixtures remain regression tests for the tool rather than a public benchmark.
