# claim-harness PR #5 Bundle

This is a dogfood real PR input bundle for Claim Harness PR #5:

`runner: emit evidence artifacts for curated cases`

The bundle is an ingestion smoke sample. It shows how a real PR's metadata, diff, CI summary, missing artifacts, and claim candidates can be organized for later evidence-chain analysis.

It is not benchmark ground truth and does not make an adequacy finding.

## Included

- `bundle.json`: bundle identity and artifact manifest.
- `pr.json`: PR metadata from GitHub.
- `pr.diff`: PR diff from GitHub.
- `ci-summary.md`: observed PR check summary.
- `claim_candidates.json`: reviewable candidate change claims.
- `missing_artifacts.json`: unavailable artifacts and their expected impact.

## Notes

This PR did not publish a coverage artifact, so `coverage.xml` and `lcov.info` are intentionally absent and recorded in `missing_artifacts.json`.
