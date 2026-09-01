<h1 align="center">PR Test Guard</h1>

<p align="center">
  <img src="https://img.shields.io/badge/release-v0.2.5-brightgreen.svg" alt="release v0.2.5" /> <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" /> <img src="https://img.shields.io/badge/output-JSON%20%7C%20Markdown-lightgrey.svg" alt="JSON and Markdown output" /> <img src="https://img.shields.io/badge/scope-Python%2Fpytest-yellow.svg" alt="Python pytest scope" /> <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license MIT" />
</p>

**Lightweight, rule-based test-quality checks for pull requests.**

PR Test Guard helps reviewers spot PRs that look tested but still carry obvious test-quality risks: missing test changes, uncovered changed code, weak assertions, mismatched tests, or mocks that may replace the behavior under review.

The project is CLI-first and designed to fit naturally into CI. Its default behavior is advisory: surface actionable signals for reviewers, and let each repository decide which rules, if any, should become merge-blocking policy. Version `0.2.5` adds JSON report artifact output on top of configurable rule policy and richer GitHub output.

| | |
| --- | --- |
| **PR-focused** | Starts from a pull-request diff and the tests around that change instead of trying to judge an entire repository. |
| **Rule-based by default** | Uses deterministic, inspectable signals before optional semantic assistance. |
| **Coverage is one signal, not the verdict** | Changed-line coverage matters, but covered code can still be backed by weak or mismatched tests. |
| **Review signals, not correctness claims** | Findings highlight where a reviewer should look; they do not prove that a PR is correct or incorrect. |
| **CLI-first, CI-friendly** | The core is intended to run locally or in any CI environment, with GitHub Actions as the first automated integration target. |
| **No model required on the default path** | The current core runner and rule checks do not require an API key or an LLM. |

## Quick Start

Install from a source checkout:

```bash
python3 -m pip install -e .
```

Run the checker inside any Git repository that contains the PR branch you want to review:

```bash
cd /path/to/your-project
pr-test-guard check --base origin/main
```

If the project already produces a `coverage.py` XML report, add it as another signal:

```bash
pr-test-guard check --base origin/main --coverage coverage.xml
```

To keep a structured report for CI artifacts or later analysis, write JSON in
addition to the selected human-facing output:

```bash
pr-test-guard check \
  --base origin/main \
  --format text \
  --json-output pr-test-guard-report.json
```

For the optional deeper check, explicitly provide the project's test command. PR Test Guard creates an isolated Git worktree, runs the unmodified tests once, then applies at most a few bounded probes to changed Python lines:

```bash
pr-test-guard check \
  --base origin/main \
  --deep \
  --test-command "pytest -q" \
  --max-probes 3
```

Findings are advisory and a successful analysis exits `0` even when warnings are found. Operational errors such as an invalid base ref or malformed coverage file exit non-zero.

To tune adoption in a repository, add `.pr-test-guard.yml`:

```yaml
rules:
  PTG001: warn
  PTG003: warn
  PTG005: warn
  PTG006: error

policy:
  fail_on: []

paths:
  ignore:
    - "docs/**"
    - "scripts/generated/**"

related_tests:
  max_candidates: 5
```

Rule actions are `off`, `warn`, or `error`. `off` suppresses matching findings, `warn` keeps the default advisory behavior, and `error` makes `pr-test-guard check` exit `1` when that rule triggers. `policy.fail_on` accepts rule ids that should be treated as error-level without repeating them under `rules`.

To run the same analyzer automatically on pull requests, add a workflow such as:

```yaml
name: PR Test Guard

on:
  pull_request:

permissions:
  contents: read

jobs:
  pr-test-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: tigerless-labs/pr-test-guard@v0.2.5
        with:
          base: origin/${{ github.base_ref }}
          config: .pr-test-guard.yml
```

Coverage and deep probes are opt-in Action inputs. Deep mode assumes the workflow has already installed the target repository's own test dependencies and that the configured test command passes before PR Test Guard runs:

```yaml
      - uses: tigerless-labs/pr-test-guard@v0.2.5
        with:
          base: origin/${{ github.base_ref }}
          coverage: coverage.xml
          deep: "true"
          test-command: pytest -q
          max-probes: "3"
          fail-on: PTG006
```

The Action can also write and optionally upload a structured JSON report:

```yaml
      - uses: tigerless-labs/pr-test-guard@v0.2.5
        with:
          base: origin/${{ github.base_ref }}
          json-output: pr-test-guard-report.json
          upload-artifact: "true"
          artifact-name: pr-test-guard-report
```

The existing regression-fixture commands remain available for development of PR Test Guard itself. Install the development extras first:

```bash
python3 -m pip install -e ".[dev]"
pr-test-guard validate-cases --run
pr-test-guard run-cases --output-dir /tmp/pr-test-guard-artifacts
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
- **Which tests have deterministic relationships to changed Python symbols?**
- **Do tests exercise a different path than the change they are meant to support?**
- **Do mocks or patches appear to replace the behavior under review?**
- **Can a limited counterfactual change survive the attached tests?**

The direct `check` command currently emits six PR-scoped rule families:

| Rule | Signal |
| --- | --- |
| `PTG001` | Production Python changed but the PR contains no test-file change. |
| `PTG002` | A changed Python line is uncovered in the supplied coverage XML. |
| `PTG003` | A newly added assertion has an obviously weak existence/truthiness shape. |
| `PTG004` | A test was deleted, skipped/xfail-marked, or lost assertions. |
| `PTG005` | A mock directly replaces a changed Python symbol, or a changed test mocks an unconstrained internal dependency called on a changed production line. |
| `PTG006` | An opt-in bounded targeted probe survives the configured tests. |

These are review-oriented signals. Heuristic findings such as `PTG003` and `PTG005` are advisory by default rather than automatic reasons to block a merge. The older fixture runner retains its research-prototype labels internally so existing regression cases keep working.

## Current Runner

The repository ships executable Python/pytest regression fixtures under `cases/python/`:

- `weak_assertion_001`
- `issue_test_mismatch_001`
- `mocked_core_path_001`
- `legitimate_helper_mock_001`
- `unconstrained_helper_mock_001`
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

Normal users no longer need to prepare a normalized bundle. The primary real-PR path is repository-native:

```text
current Git repository + base ref + optional coverage/test command
  -> pr-test-guard check
  -> PR-scoped rule signals
  -> text / JSON / GitHub Actions output
  -> optional JSON report artifact
```

The older normalized bundle under `examples/real-pr-bundles/` remains as a development fixture and compatibility prototype for richer CI artifacts. It can include PR metadata, a diff, CI/test results, coverage, and optional change-intent context, but it is not required by the direct checker. See [Real PR Input](docs/real-pr-input.md).

The reusable `action.yml` calls the same CLI/core. There is no separate hosted analysis service and no API key is required for the default path. GitHub output is grouped by rule, includes related-test candidates up to the configured limit, emits error annotations for rules configured as error-level policy, and can retain the full JSON report as a workflow artifact.

## Mock and Probe Boundaries

The current mock detector uses a lightweight Python semantic layer before matching. It recognizes explicit patterns such as `patch`, `patch.object`, `monkeypatch.setattr`, and `mocker.patch`, resolves common import aliases, preserves class/method qualified names, and normalizes common `src/` layouts.

PTG005 then applies three bounded layers:

- direct changed-symbol mocks remain the highest-confidence warning;
- explicitly imported external dependencies are treated as external-boundary candidates and suppressed from warnings;
- changed tests that mock direct internal dependencies called on changed production lines are warned only when the mock is not constrained by an interaction assertion, owner return assertion, or owner exception assertion.

PTG005 evidence is emitted as stable key/value context, including the relationship type, mock style, target, resolution result, review reason, changed owner symbol, changed call line, and candidate dependency targets where available. Suppressed constrained-helper and external-boundary candidates are summarized in notes rather than hidden silently.

Unchanged call sites, untouched tests, deep instance-attribute chains, and other unresolved dynamic relationships remain conservative. A `PTG005` result is still a **candidate signal**; structural and test-semantics evidence does not prove that a mock is inappropriate.

The direct checker also reports related-test candidates using deterministic import, direct-call, mock-target, and test-name context. This makes findings easier to inspect without claiming that a related test fully validates the changed behavior.

The targeted probe generator is deliberately limited and AST-scoped. It covers a small set of status-code returns, boolean return flips, and comparison-boundary changes on lines added by the current PR while avoiding string/comment matches and unstable multi-line rewrites. A generated probe is not itself a finding: `PTG006` is emitted only when the configured tests pass at baseline and a supported probe survives an actual rerun in an isolated Git worktree.

These deeper signals are part of the product's differentiation beyond patch coverage. Mock-boundary analysis stays static and advisory. Targeted probes are bounded, PR-scoped, and opt-in through `--deep` because they rerun repository tests. The goal is not a full mutation-testing campaign; it is a small number of review-focused probes against code changed by the current PR.

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
- [Real PR Input](docs/real-pr-input.md): direct repository input, Action usage, optional coverage, and deep-probe boundaries.
- [Dogfooding](docs/dogfooding.md): how to record shareable real-PR review summaries without committing raw PR details.
- [Rule Fixtures](docs/rule-fixtures.md): how controlled fixtures define expected rule behavior for regression testing.
- [Validation Strategy](docs/validation-strategy.md): how to validate rule usefulness, false positives, and real-world behavior.
- [Runner Artifacts](docs/runner-artifacts.md): what the current regression-fixture runner emits.
- [Roadmap](docs/roadmap.md): the lightweight CLI and GitHub Action path from the current `0.2.5` release.

## Current Scope

Version `0.2.5` supports direct Python/pytest PR analysis from the current Git repository and a reusable advisory GitHub Action. The direct checker currently surfaces:

- production-code changes with no test-file change;
- uncovered changed Python lines when a coverage XML report is supplied;
- obvious weak assertions added in changed tests;
- suspicious test deletion, skip/xfail, or assertion removal;
- deterministic related-test context for changed Python symbols;
- lightweight symbol-resolved mock relationships around changed Python symbols and changed call sites, with constrained dependency mocks suppressed from PTG005 warnings;
- optional bounded targeted probes that survive an explicit test command.
- configurable rule policy through `.pr-test-guard.yml`, `--config`, `--no-config`, and `--fail-on`.
- optional JSON report output through `--json-output` and GitHub artifact upload.

It still does **not** include:

- per-test coverage mapping;
- broad business-intent assertion or mock classification;
- automatic discovery of every repository's test command;
- safe privileged execution of untrusted PR code;
- GitHub API ingestion or a hosted service.

The next milestone remains real-PR dogfooding: run the rules across varied repositories, record useful / false-positive / unclear signals, and turn recurring patterns into public-safe distilled controls rather than raw PR examples. PTG005 now combines symbol identity, bounded direct-dependency relationships, constrained dependency-mock suppression, and clearer relationship evidence; later work should focus on real-PR precision, related-test selection, and only then optional deeper semantic assistance where deterministic relationships remain ambiguous.

## License

[MIT](LICENSE)

---

Built by [Tigerless Labs](https://github.com/tigerless-labs), the AI lab of [Tigerless](https://www.tigerless.com) — also home to [tigerless.ai](https://tigerless.ai).
