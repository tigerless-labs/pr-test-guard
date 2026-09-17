# Real PR Input

PR Test Guard now supports repository-native pull-request analysis. The normal user path is the current Git checkout plus a base ref; the older normalized bundle remains only as a development/compatibility prototype.

## Direct Repository Input

Run inside the PR branch:

```bash
pr-test-guard check --base origin/main
```

The checker derives the diff from Git and analyzes the current `HEAD` against the merge-base with the supplied base ref.

Optional inputs add more signals:

```bash
pr-test-guard check --base origin/main --coverage coverage.xml
```

```bash
pr-test-guard check \
  --base origin/main \
  --deep \
  --test-command "pytest -q" \
  --max-probes 3
```

`--json-output` writes the complete structured result in addition to the selected
stdout format. Parent directories are created automatically:

```bash
pr-test-guard check \
  --base origin/main \
  --format github \
  --json-output artifacts/pr-test-guard-report.json
```

The default path does not require a PR body, issue text, LLM output, or a custom JSON bundle.

## Configuration

`pr-test-guard check` automatically reads the first config file found at the repository root:

```text
.pr-test-guard.yml
.pr-test-guard.yaml
.pr-test-guard.json
.pr-test-guard.toml
```

A minimal YAML config can tune rollout without changing rule detection:

```yaml
rules:
  PTG001: warn
  PTG003: off
  PTG005: warn
  PTG006: error

policy:
  fail_on: [PTG006]

paths:
  ignore:
    - "docs/**"
  tests:
    include:
      - "spec/**"
      - "**/*_spec.py"
    exclude:
      - "src/test_support/**"

related_tests:
  max_candidates: 5
  mappings:
    - source: "src/payments/**"
      tests:
        - "tests/integration/payments/**"
```

Use `--config path/to/config.yml` to pass an explicit file, `--no-config` to run with the default advisory policy, and `--fail-on PTG006,PTG005` for a one-off CI override.

Validate and inspect the normalized effective configuration without analyzing a
PR diff:

```bash
pr-test-guard validate-config
pr-test-guard validate-config --config path/to/config.yml --format json
```

The validator can run outside a Git repository. With no explicit path it uses
the same `.pr-test-guard.*` discovery order as `check`; if no file is found, it
reports the built-in defaults. Invalid configuration exits `2`. Unknown fields,
ambiguous rule objects, empty path patterns, and booleans supplied where an
integer is required are rejected with a field-specific error. Nearby supported
field names are suggested when possible.

Rule actions, `policy.fail_on`, and `paths.ignore` are applied after detection:
they control which findings are shown and whether the command exits `1` without
making heuristic rules more certain. Test path configuration participates in
detection because it determines which changed and tracked files are treated as
tests. `paths.tests.include` extends the built-in Python/pytest conventions;
`paths.tests.exclude` takes precedence over configured includes and built-in
matches. Both accept repository-relative globs. `paths.ignore` only suppresses
findings and does not change file classification.

`related_tests.mappings` handles stable repository relationships that cannot be
recovered from direct Python imports or calls. Each entry has one repository-
relative `source` glob and a `tests` string or list of globs. A mapping is
additive: matching candidates are merged with automatically inferred candidates
and tagged with `configured_path_mapping`. It does not prove test execution or
change PTG001's definition of a test-file change. Test excludes still take
precedence over mapping matches.

## What the Direct Checker Reads

The current Python/pytest path uses:

- `git diff <base>...HEAD`;
- changed production and test files;
- changed Python lines;
- changed test assertions and skip/xfail markers;
- related-test candidates from deterministic imports, direct calls, test names, mock targets, and optional configured path mappings;
- tracked Python tests for symbol-resolved mock targets and bounded changed-call relationships;
- optional `coverage.py` XML;
- optional explicit test command for bounded targeted probes.
- optional `.pr-test-guard.*` test-path, related-test mapping, and policy configuration.
- optional JSON report output path for CI artifacts or follow-up analysis.

Missing optional artifacts are reported as skipped checks, not silently converted into negative evidence.

Related-test candidates are included to make output easier to inspect. They do
not prove that a test validates the changed behavior, and they are not used as a
merge-blocking policy.

## GitHub Action

The root `action.yml` wraps the same CLI/core. A consumer repository checks out the PR with enough history to resolve the base and then invokes PR Test Guard:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- uses: tigerless-labs/pr-test-guard@v0.5.1
  with:
    base: origin/${{ github.base_ref }}
```

The Action emits GitHub warning annotations and appends a job summary. Findings are advisory by default and do not make the Action fail.

To use repository policy:

```yaml
- uses: tigerless-labs/pr-test-guard@v0.5.1
  with:
    base: origin/${{ github.base_ref }}
    config: .pr-test-guard.yml
```

To enforce a high-confidence rule without a config file:

```yaml
- uses: tigerless-labs/pr-test-guard@v0.5.1
  with:
    base: origin/${{ github.base_ref }}
    fail-on: PTG006
```

Rules configured as `error` emit GitHub error annotations and make the Action fail after the summary is written. Warning rules remain advisory.

The Action also supports JSON report artifacts:

```yaml
- uses: tigerless-labs/pr-test-guard@v0.5.1
  with:
    base: origin/${{ github.base_ref }}
    json-output: pr-test-guard-report.json
    upload-artifact: "true"
    artifact-name: pr-test-guard-report
```

The Action records the checker exit code, writes the JSON report, uploads it when
requested, and only then fails the job for configured error-level findings.

## Deep Probe Boundary

`--deep` is opt-in because it executes the repository's configured test command. PR Test Guard first creates an isolated Git worktree at `HEAD`, verifies that the unmodified test command passes, and only then applies a bounded number of supported probes.

This is intentionally different from a full mutation-testing campaign: the probe set is small, scoped to changed Python lines, and used as reviewer evidence rather than as a repository-wide mutation score. Killed probes are treated as useful test sensitivity and do not produce PTG006 warnings. Unsupported probe shapes are skipped rather than guessed.

## Normalized Bundle Compatibility

The prototype bundle under `examples/real-pr-bundles/` can still include:

- `bundle.json`;
- `pr.json`;
- `pr.diff`;
- CI/test artifacts;
- coverage;
- optional change-intent context;
- explicit missing-artifact records.

Validate it with:

```bash
python3 -m pr_test_guard validate-real-pr-bundles
```

This bundle is no longer required for normal real-PR use.

## Security Boundary

The static/default checker only reads repository content, Git history, and an optional repository-local config file. Coverage is consumed only when explicitly supplied. JSON report output writes only the analysis result that the CLI can already print.

Deep probes execute a test command chosen by the repository/user. In GitHub Actions, that execution therefore follows the trust boundary of the workflow that opted into it. PR Test Guard does not request repository write permission or secrets for its default advisory path.
