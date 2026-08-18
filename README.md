<h1 align="center">PR Test Guard</h1>

<p align="center">
  <img src="https://img.shields.io/badge/release-v0.1.0-brightgreen.svg" alt="release v0.1.0" /> <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" /> <img src="https://img.shields.io/badge/output-JSON%20%7C%20Markdown-lightgrey.svg" alt="JSON and Markdown output" /> <img src="https://img.shields.io/badge/scope-Python%2Fpytest-yellow.svg" alt="Python pytest scope" /> <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license MIT" />
</p>

**Lightweight, rule-based test-quality checks for pull requests.**

PR Test Guard helps reviewers spot PRs that look tested but still carry obvious test-quality risks: missing test changes, uncovered changed code, weak assertions, mismatched tests, or mocks that may replace the behavior under review.

The project is CLI-first and designed to fit naturally into CI. Its default product direction is advisory: surface actionable signals for reviewers, and let each repository decide which rules, if any, should become merge-blocking policy. Version `0.1.0` keeps the existing executable regression-fixture runner while the direct PR-checking CLI and reusable GitHub Action are being built.

| | |
| --- | --- |
| **PR-focused** | Starts from a pull-request diff and the tests around that change instead of trying to judge an entire repository. |
| **Rule-based by default** | Uses deterministic, inspectable signals before optional semantic assistance. |
| **Coverage is one signal, not the verdict** | Changed-line coverage matters, but covered code can still be backed by weak or mismatched tests. |
| **Review signals, not correctness claims** | Findings highlight where a reviewer should look; they do not prove that a PR is correct or incorrect. |
| **CLI-first, CI-friendly** | The core is intended to run locally or in any CI environment, with GitHub Actions as the first automated integration target. |
| **No model required on the default path** | The current core runner and rule checks do not require an API key or an LLM. |

## Quick Start

Clone the repository and run the current Python/pytest regression fixtures. Version `0.1.0`
is intended for source-tree use and is not published to PyPI yet:

```bash
python3 -m pip install -e .
python3 -m pr_test_guard --version
python3 -m pr_test_guard validate-cases
python3 -m pr_test_guard validate-cases --run
python3 -m pr_test_guard run-cases --output-dir /tmp/pr-test-guard-artifacts
```

The same commands are available through the console script after editable install:

```bash
pr-test-guard validate-cases
pr-test-guard run-cases --case weak_assertion_001 --output-dir /tmp/pr-test-guard-artifacts
```

The script entrypoints remain supported:

```bash
python3 scripts/validate_cases.py
python3 scripts/validate_cases.py --run
python3 scripts/run_case.py --output-dir /tmp/pr-test-guard-artifacts
```

Validate the synthetic normalized real-PR input bundle:

```bash
python3 -m pr_test_guard validate-real-pr-bundles
```

## What It Evaluates

PR Test Guard is centered on a simple review question:

```text
PR change -> related tests -> runtime/static evidence -> test-quality signals
```

It currently models evidence that can help answer:

- **Was behavior changed without clear test evidence?**
- **Are changed executable lines actually covered?**
- **Do the relevant assertions constrain the behavior they appear to test?**
- **Do tests exercise a different path than the change they are meant to support?**
- **Do mocks or patches appear to replace the behavior under review?**
- **Can a limited counterfactual change survive the attached tests?**

Initial finding types are kept from the original research prototype because they exercise useful PR-test failure modes:

| Finding | Meaning |
| --- | --- |
| `Missing Test Evidence` | No clear test evidence is attached to a behavior-changing PR path. |
| `Uncovered Changed Lines` | Relevant changed executable code is not exercised by the available tests. |
| `Weak Assertion` | Code is exercised, but the assertion may not meaningfully constrain the expected outcome. |
| `Issue-Test Mismatch` | The available test appears to validate a materially different behavior from the change intent. |
| `Suspicious Fix Without Test` | A behavioral change appears without a corresponding test change or identifiable existing test link. |
| `Mocked Core Path` | A mock or stub appears to replace the behavior path that should provide evidence. |
| `CI Scope Weakening` | CI or test configuration appears to narrow validation around affected behavior. |
| `Counterfactual Survivor` | A limited controlled weakening still passes the attached tests. |
| `Evidence Complete` | The current fixture has no targeted evidence gap; this is not a correctness certificate. |

These are review-oriented signals. Heuristic findings such as `Weak Assertion` or `Mocked Core Path` should be advisory by default rather than automatic reasons to block a merge.

## Current Runner

The repository ships four executable Python/pytest regression fixtures under `cases/python/`:

- `weak_assertion_001`
- `issue_test_mismatch_001`
- `mocked_core_path_001`
- `evidence_complete_001`

Each fixture includes a small PR-like change, executable code, tests, change intent, and expected rule output. The expected output is used for regression testing of the tool itself; it is not presented as a public benchmark or a human-labeled comparison dataset.

For each fixture, the runner writes:

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

`comparison_summary.json` is a regression check against the fixture's expected signals. It exists to catch rule regressions while the implementation evolves, not to establish leaderboard-style benchmark performance.

## Real PR Bundles

PR Test Guard is intended to move from controlled fixtures to real pull requests without tying the core analysis to one agent or hosting workflow.

The current normalized input prototype is:

```text
PR metadata + diff + test/CI artifacts -> normalized PR bundle -> rule evidence -> findings
```

A normalized bundle can include:

- `issue.md` or `task.md`
- `pr.json`
- `pr.diff`
- `ci-summary.md`
- `test-result.json` or `ci.log`
- `coverage.xml` or `lcov.info`
- optional change-intent candidates
- `missing_artifacts.json`

Missing artifacts should be recorded explicitly instead of silently treated as evidence. See [Real PR Input](docs/real-pr-input.md).

The long-term integration is intentionally lighter than a hosted service: keep the analysis core callable from the CLI, then wrap it in a GitHub Action so pull requests can receive automatic advisory results in CI.

## Mock and Probe Boundaries

The current mock detector is structural. It recognizes explicit Python patterns such as `patch`, `patch.object`, `monkeypatch.setattr`, and `mocker.patch`, then checks whether the target matches a changed function or class. That produces a **candidate signal**; it does not prove that the mock is wrong.

The current counterfactual probe generator is also deliberately limited. It covers common status-code weakening, boolean return flips, simple retry-limit rollback, and basic inclusive-boundary comparison weakening. A `Counterfactual Survivor` requires an actual pytest rerun result.

These deeper signals are retained from the original prototype, but they are not required to define the product. The lightweight public direction is to keep deterministic rules understandable, cheap to run, and safe to treat as advisory unless a repository explicitly opts into enforcement.

## Optional LLM Claim Candidates

The default path is rule-based and does not require an LLM. The existing optional helper for extracting change-intent candidates from a normalized PR bundle is retained as an experimental aid:

```bash
python3 -m pip install -e ".[llm]"
OPENAI_API_KEY=... OPENAI_MODEL=... python3 scripts/extract_claim_candidates.py \
  examples/real-pr-bundles/normalized-pr-bundle-001
```

This helper only proposes candidate change intent. It must not turn heuristic signals into correctness judgments, decide whether a PR may merge, or replace test execution, coverage, CI evidence, or deterministic rule output.

## What It Is Not

- Not a replacement for the repository's test suite.
- Not a generic coverage reporter.
- Not a full code-review agent.
- Not a benchmark or leaderboard project.
- Not a pure LLM judge.
- Not a correctness certificate.
- Not a mandatory merge gate by default.

Patch-coverage tools answer whether changed lines were executed. PR Test Guard keeps that useful signal, then looks for additional test-quality risks around the same PR. Its goal is not to make the final merge decision; it is to give reviewers a fast, inspectable reason to look more closely where test evidence appears weak.

## Project Documents

- [Methodology](docs/methodology.md): the PR-centered evidence model and rule-design principles.
- [Evaluation Design](docs/evaluation-design.md): how rules are validated without turning the project into a benchmark effort.
- [Real PR Input](docs/real-pr-input.md): the normalized PR input shape and the path toward CLI/CI integration.
- [Rule Fixtures](docs/rule-fixtures.md): how controlled fixtures define expected rule behavior for regression testing.
- [Validation Strategy](docs/validation-strategy.md): how to validate rule usefulness, false positives, and real-world behavior.
- [Runner Artifacts](docs/runner-artifacts.md): what the current regression-fixture runner emits.
- [Roadmap](docs/roadmap.md): the lightweight CLI and GitHub Action path from the current `0.1.0` prototype.

## Current Scope

Version `0.1.0` contains the renamed CLI surface, executable Python/pytest regression fixtures, deterministic rule/evidence artifacts, and normalized real-PR input validation.

It still does **not** include:

- a direct arbitrary-repository `pr-test-guard check` command;
- a reusable GitHub Action for external repositories;
- GitHub API ingestion or PR annotations;
- configurable advisory/error severity policy;
- per-test coverage mapping;
- broad semantic assertion or mock classification;
- safe general-purpose execution of untrusted external repositories.

The next product milestone is to turn the existing rule logic into a lightweight PR-facing CLI, then expose the same core through GitHub Actions. Advisory output should remain the default; repositories can choose later which high-confidence rules deserve enforcement.

## License

[MIT](LICENSE)
