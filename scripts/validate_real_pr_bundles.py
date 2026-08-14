#!/usr/bin/env python3
"""Validate real PR input bundle structure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FILES = {
    "README.md",
    "bundle.json",
    "pr.json",
    "pr.diff",
    "ci-summary.md",
    "claim_candidates.json",
    "missing_artifacts.json",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def validate_bundle(bundle_dir: Path) -> list[str]:
    errors: list[str] = []

    missing = sorted(name for name in REQUIRED_FILES if not (bundle_dir / name).is_file())
    if missing:
        errors.append(f"missing required files: {', '.join(missing)}")
        return errors

    bundle = load_json(bundle_dir / "bundle.json")
    pr = load_json(bundle_dir / "pr.json")
    claims = load_json(bundle_dir / "claim_candidates.json")
    missing_artifacts = load_json(bundle_dir / "missing_artifacts.json")
    diff_text = (bundle_dir / "pr.diff").read_text(encoding="utf-8")

    if bundle.get("bundle_id") != bundle_dir.name:
        errors.append("bundle.json bundle_id must equal directory name")

    if bundle.get("bundle_type") != "real_pr_ingestion_smoke":
        errors.append("bundle.json bundle_type must be 'real_pr_ingestion_smoke'")

    if not pr.get("number") or not pr.get("url") or not pr.get("title"):
        errors.append("pr.json must include number, url, and title")

    if bundle.get("pr_number") != pr.get("number"):
        errors.append("bundle.json pr_number must match pr.json number")

    if "diff --git " not in diff_text:
        errors.append("pr.diff must contain at least one git diff section")

    claim_items = claims.get("claims")
    if not isinstance(claim_items, list) or not claim_items:
        errors.append("claim_candidates.json must contain a non-empty claims list")
    else:
        claim_ids = set()
        for claim in claim_items:
            claim_id = claim.get("id") if isinstance(claim, dict) else None
            if not claim_id:
                errors.append("every claim candidate must have an id")
                continue
            if claim_id in claim_ids:
                errors.append(f"duplicate claim candidate id: {claim_id}")
            claim_ids.add(claim_id)
            if not claim.get("text"):
                errors.append(f"claim candidate {claim_id} must include text")
            if not claim.get("source_refs"):
                errors.append(f"claim candidate {claim_id} must include source_refs")

    missing_items = missing_artifacts.get("missing")
    if not isinstance(missing_items, list):
        errors.append("missing_artifacts.json must contain a missing list")
    else:
        for item in missing_items:
            artifact = item.get("artifact") if isinstance(item, dict) else None
            if not artifact:
                errors.append("every missing artifact entry must include artifact")

    ground_truth = bundle.get("ground_truth")
    if not isinstance(ground_truth, dict):
        errors.append("bundle.json must include ground_truth")
    elif ground_truth.get("is_benchmark_case") is not False:
        errors.append("example real PR bundles must not be marked as benchmark cases")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundles-root",
        default="examples/real-pr-bundles",
        help="directory containing real PR bundles (default: examples/real-pr-bundles)",
    )
    args = parser.parse_args()

    bundles_root = Path(args.bundles_root)
    if not bundles_root.is_dir():
        print(f"ERROR: bundles root not found: {bundles_root}", file=sys.stderr)
        return 1

    bundle_dirs = sorted(path for path in bundles_root.iterdir() if path.is_dir())
    if not bundle_dirs:
        print(f"ERROR: no bundles found under {bundles_root}", file=sys.stderr)
        return 1

    failed = False
    for bundle_dir in bundle_dirs:
        errors = validate_bundle(bundle_dir)
        if errors:
            failed = True
            print(f"[FAIL] {bundle_dir.name}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"[OK]   {bundle_dir.name}: structure")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
