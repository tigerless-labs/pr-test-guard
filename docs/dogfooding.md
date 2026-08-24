# Dogfooding Review Workflow

PR Test Guard should be validated on real pull requests, but this public
repository should only contain shareable summaries. Keep repository-specific
notes outside this repository and convert them into stable aliases before using
them for public examples, aggregate counts, or rule-planning discussions.

## Workflow

1. Run `pr-test-guard check` on a real PR checkout.
2. Review each finding as a reviewer would.
3. Keep any raw notes in a local or private location.
4. Convert the review into a sanitized record.
5. Aggregate sanitized records to choose the next fixture or rule change.

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

The public repository can include sanitized examples under
`examples/dogfood-reviews/` and scripts that operate on sanitized records. Raw
notes should stay local or in a private workspace.

## Aggregation

Run:

```bash
python3 scripts/summarize_dogfood_reviews.py ~/private/pr-test-guard-dogfood/sanitized
```

Use the aggregate output to decide whether the next PR should add a regression
fixture, tighten a rule, improve finding evidence, or only update documentation.
