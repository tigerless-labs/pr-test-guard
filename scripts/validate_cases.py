#!/usr/bin/env python3
"""Validate Claim Harness curated-case structure.

By default this script checks file presence, JSON shape, claim references, and
finding labels. With --run it also copies each fixture to a temporary directory,
applies pr.patch with `git apply`, and runs pytest.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_FILES = {
    "issue.md",
    "claim.json",
    "metadata.json",
    "expected_findings.json",
    "pr.patch",
}

ALLOWED_FINDINGS = {
    "Evidence Complete",
    "Missing Test Evidence",
    "Uncovered Changed Lines",
    "Weak Assertion",
    "Issue-Test Mismatch",
    "Suspicious Fix Without Test",
    "Mocked Core Path",
    "CI Scope Weakening",
    "Counterfactual Survivor",
}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def validate_case(case_dir: Path) -> list[str]:
    errors: list[str] = []

    missing = sorted(name for name in REQUIRED_FILES if not (case_dir / name).is_file())
    if missing:
        errors.append(f"missing required files: {', '.join(missing)}")

    repo_dir = case_dir / "repo"
    if not repo_dir.is_dir():
        errors.append("missing repo/ fixture directory")

    if errors:
        return errors

    claim_doc = load_json(case_dir / "claim.json")
    metadata = load_json(case_dir / "metadata.json")
    expected = load_json(case_dir / "expected_findings.json")

    claims = claim_doc.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("claim.json must contain a non-empty 'claims' list")
        claim_ids = set()
    else:
        claim_ids = set()
        for item in claims:
            claim_id = item.get("id") if isinstance(item, dict) else None
            if not claim_id:
                errors.append("every claim must have a non-empty 'id'")
                continue
            if claim_id in claim_ids:
                errors.append(f"duplicate claim id: {claim_id}")
            claim_ids.add(claim_id)

    if metadata.get("case_id") != case_dir.name:
        errors.append(
            f"metadata.json case_id must equal directory name {case_dir.name!r}"
        )

    expected_claims = expected.get("claims")
    if not isinstance(expected_claims, list) or not expected_claims:
        errors.append("expected_findings.json must contain a non-empty 'claims' list")
    else:
        for result in expected_claims:
            claim_id = result.get("claim_id") if isinstance(result, dict) else None
            if claim_id not in claim_ids:
                errors.append(
                    f"expected_findings.json references unknown claim_id {claim_id!r}"
                )
            findings = result.get("findings")
            if not isinstance(findings, list) or not findings:
                errors.append(
                    f"claim {claim_id!r} must contain a non-empty findings list"
                )
                continue
            for finding in findings:
                finding_type = finding.get("type") if isinstance(finding, dict) else None
                if finding_type not in ALLOWED_FINDINGS:
                    errors.append(
                        f"claim {claim_id!r} uses unknown finding type {finding_type!r}"
                    )

    return errors


def run_case(case_dir: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix=f"{case_dir.name}-") as temp:
        temp_dir = Path(temp)
        repo_copy = temp_dir / "repo"
        shutil.copytree(case_dir / "repo", repo_copy)

        patch_path = case_dir / "pr.patch"
        apply_result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch_path.resolve())],
            cwd=repo_copy,
            capture_output=True,
            text=True,
        )
        if apply_result.returncode != 0:
            return False, f"git apply failed:\n{apply_result.stderr.strip()}"

        test_result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=repo_copy,
            capture_output=True,
            text=True,
        )
        output = (test_result.stdout + "\n" + test_result.stderr).strip()
        return test_result.returncode == 0, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases-root",
        default="cases/python",
        help="directory containing curated cases (default: cases/python)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="apply each PR patch in a temp copy and run pytest",
    )
    args = parser.parse_args()

    cases_root = Path(args.cases_root)
    if not cases_root.is_dir():
        print(f"ERROR: cases root not found: {cases_root}", file=sys.stderr)
        return 1

    case_dirs = sorted(path for path in cases_root.iterdir() if path.is_dir())
    if not case_dirs:
        print(f"ERROR: no cases found under {cases_root}", file=sys.stderr)
        return 1

    failed = False
    for case_dir in case_dirs:
        errors = validate_case(case_dir)
        if errors:
            failed = True
            print(f"[FAIL] {case_dir.name}")
            for error in errors:
                print(f"  - {error}")
            continue

        print(f"[OK]   {case_dir.name}: structure")

        if args.run:
            ok, output = run_case(case_dir)
            if ok:
                print(f"[OK]   {case_dir.name}: patched fixture tests")
            else:
                failed = True
                print(f"[FAIL] {case_dir.name}: patched fixture tests")
                print(output)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
