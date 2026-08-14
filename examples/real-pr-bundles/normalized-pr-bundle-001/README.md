# Normalized PR Bundle 001

This is a synthetic normalized PR bundle that demonstrates the real-PR input shape.
It does not represent a real repository, a real pull request, or benchmark ground truth.

The bundle shows how PR metadata, a diff, CI summary, claim candidates, and missing
artifact records can be organized before evidence-chain evaluation.

## Included

- `bundle.json`: bundle identity and artifact manifest.
- `pr.json`: synthetic PR metadata.
- `pr.diff`: synthetic PR diff in unified git format.
- `ci-summary.md`: synthetic CI check summary.
- `claim_candidates.json`: reviewable candidate change claims.
- `missing_artifacts.json`: unavailable artifacts and expected impact.

## Notes

This bundle is intentionally small. It validates the normalized input contract
without implying that Claim Harness can ingest every hosting provider or evaluate
arbitrary repositories end to end.
