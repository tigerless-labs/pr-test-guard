# Dogfooding Review Workflow

PR Test Guard should be validated on real pull requests, but this public
repository should only contain shareable summaries. Keep repository-specific
notes outside this repository and convert them into stable aliases before using
them for public examples, aggregate counts, or rule-planning discussions.

## Workflow

1. Run `pr-test-guard check` on a real PR checkout.
2. Draft a local review record from the JSON report.
3. Review each finding as a reviewer would.
4. Keep any raw notes in a local or private location.
5. Convert the review into a sanitized record.
6. Aggregate sanitized records to choose the next fixture or rule change.

The sanitized record should preserve the evidence shape that matters for rule
work while avoiding repository-specific details.

## Reviewer Labels

Use one label for each finding:

- `useful`: the signal points to a concrete review concern.
- `false_positive`: the signal is explainable but should not have warned.
- `unclear`: the signal might matter, but the output lacks enough context.
- `needs_more_context`: the rule needs another artifact, mapping, or policy input.

## Shareable Fields

Use aliases and coarse classifications:

- `repo_alias`: stable value such as `repo_001`.
- `pr_alias`: stable value such as `pr_001`.
- `path_kind`: `production`, `test`, `docs`, `config`, or `unknown`.
- `symbol_kind`: `function`, `method`, `class`, `module`, or `unknown`.
- `dependency_kind`: `internal`, `external`, `unknown`, or `none`.
- `evidence_shape`: a short reusable phrase such as
  `changed test mocks dependency called from changed line`.

Do not include repository URLs, PR URLs, branch names, real file paths, real
symbols, dependency names, command strings, code snippets, CI logs, or raw
finding evidence in records committed to this repository.

## Local Layout

A practical local layout is:

```text
~/private/pr-test-guard-dogfood/
  raw/
    repo-001-pr-001.json
  sanitized/
    repo-001-pr-001.json
```

Draft the local raw record from a checker JSON report:

```bash
pr-test-guard check --base origin/main --json-output /tmp/pr-test-guard-report.json
python3 scripts/draft_dogfood_review.py \
  /tmp/pr-test-guard-report.json \
  --review-id review_001 \
  --repo-alias repo_001 \
  --pr-alias pr_001 \
  --test-framework pytest \
  --test-command-shape pytest \
  -o ~/private/pr-test-guard-dogfood/raw/repo-001-pr-001.json
```

The draft keeps local-only fields such as file, line, message, and evidence so
the reviewer can label the finding. Before publishing or committing anything,
convert the raw record into the shareable schema:

```bash
python3 scripts/sanitize_dogfood_review.py \
  ~/private/pr-test-guard-dogfood/raw/repo-001-pr-001.json \
  -o ~/private/pr-test-guard-dogfood/sanitized/repo-001-pr-001.json
```

The public repository can include sanitized examples under
`examples/dogfood-reviews/` and scripts that operate on sanitized records. Raw
notes should stay local or in a private workspace.

## Aggregation

Run:

```bash
python3 scripts/summarize_dogfood_reviews.py ~/private/pr-test-guard-dogfood/sanitized
```

The summary reports label counts, label rates, top categories, top evidence
shapes, action counts, and recommended next actions per rule.

Use the aggregate output to decide whether the next PR should add a regression
fixture, tighten a rule, improve finding evidence, or only update documentation.

## From Summary to Fixture

When the same sanitized category appears repeatedly as a `false_positive` or
`unclear` signal, add the smallest public-safe fixture that captures the rule
boundary. The fixture should use fictional code and stable names, and its
expected output should define the intended behavior without copying details from
the original PR.

For rule PRs, the public artifact should be one of these forms:

- a direct-check unit test that builds a tiny temporary Git repository;
- an executable micro-PR fixture under `cases/python/`;
- a sanitized aggregate/example record under `examples/dogfood-reviews/`;
- documentation that explains the boundary without naming the original project.

Do not commit a real external or private PR merely to justify a rule change. A
distilled fixture is the normative artifact when it preserves the rule-relevant
shape and removes project-specific details.
