#!/usr/bin/env python3
"""Run curated Claim Harness cases and emit raw evidence artifacts.

This is intentionally a small artifact runner, not the full Claim Harness
evaluation engine. It applies each case patch, runs the patched pytest fixture,
and writes reviewable JSON/Markdown outputs for later evidence-chain work.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from validate_cases import validate_case


RUNNER_VERSION = "0.1"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_patch_files(patch_text: str) -> tuple[list[str], list[str], list[str]]:
    patch_files: list[str] = []
    changed_code_files: list[str] = []
    test_files: list[str] = []

    for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", patch_text, re.MULTILINE):
        path = match.group(2)
        if path not in patch_files:
            patch_files.append(path)
        if is_test_path(path):
            if path not in test_files:
                test_files.append(path)
        elif path not in changed_code_files:
            changed_code_files.append(path)

    return patch_files, changed_code_files, test_files


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    filename = parts[-1]
    return "tests" in parts or filename.startswith("test_") or filename.endswith("_test.py")


def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run_case(case_dir: Path, output_root: Path) -> bool:
    errors = validate_case(case_dir)
    case_output = output_root / case_dir.name
    if case_output.exists():
        shutil.rmtree(case_output)
    case_output.mkdir(parents=True, exist_ok=True)

    if errors:
        write_json(
            case_output / "case_summary.json",
            {
                "case_id": case_dir.name,
                "runner_version": RUNNER_VERSION,
                "valid": False,
                "validation_errors": errors,
            },
        )
        return False

    metadata = load_json(case_dir / "metadata.json")
    claim_doc = load_json(case_dir / "claim.json")
    expected_findings = load_json(case_dir / "expected_findings.json")
    patch_text = (case_dir / "pr.patch").read_text(encoding="utf-8")
    patch_files, changed_code_files, test_files = parse_patch_files(patch_text)

    with tempfile.TemporaryDirectory(prefix=f"{case_dir.name}-") as temp:
        temp_dir = Path(temp)
        repo_copy = temp_dir / "repo"
        shutil.copytree(case_dir / "repo", repo_copy)

        apply_result = run_command(
            ["git", "apply", "--whitespace=nowarn", str((case_dir / "pr.patch").resolve())],
            repo_copy,
        )
        test_result = None
        if apply_result["passed"]:
            test_result = run_command([sys.executable, "-m", "pytest", "-q"], repo_copy)

    write_json(case_output / "test_result.json", test_result or apply_result)
    write_json(case_output / "expected_findings.json", expected_findings)

    claim_rows = []
    for claim in claim_doc.get("claims", []):
        claim_rows.append(
            {
                "claim_id": claim.get("id"),
                "claim_text": claim.get("text"),
                "source": claim.get("source"),
                "changed_code_files": changed_code_files,
                "test_files": test_files,
                "coverage_evidence": None,
                "ci_evidence": "test_result.json",
                "adequacy_finding": None,
            }
        )

    write_json(
        case_output / "evidence_chain_stub.json",
        {
            "case_id": case_dir.name,
            "runner_version": RUNNER_VERSION,
            "status": "stub",
            "claims": claim_rows,
        },
    )

    passed = bool((test_result or apply_result)["passed"])
    write_json(
        case_output / "case_summary.json",
        {
            "case_id": case_dir.name,
            "runner_version": RUNNER_VERSION,
            "valid": True,
            "metadata": metadata,
            "claims_count": len(claim_doc.get("claims", [])),
            "patch_files": patch_files,
            "changed_code_files": changed_code_files,
            "test_files": test_files,
            "patched_tests_passed": passed,
            "artifacts": [
                "case_summary.json",
                "test_result.json",
                "evidence_chain_stub.json",
                "expected_findings.json",
                "claim_harness_report.md",
            ],
        },
    )
    write_report(case_output / "claim_harness_report.md", case_dir.name, claim_doc, passed)
    return passed


def write_report(path: Path, case_id: str, claim_doc: dict[str, Any], passed: bool) -> None:
    lines = [
        f"# Claim Harness Case Report: {case_id}",
        "",
        "This report is generated by the raw artifact runner. It does not make automated adequacy findings yet.",
        "",
        "## Test Result",
        "",
        f"- Patched fixture tests passed: `{str(passed).lower()}`",
        "",
        "## Claims",
        "",
    ]

    for claim in claim_doc.get("claims", []):
        lines.append(f"- `{claim.get('id')}`: {claim.get('text')}")

    lines.extend(
        [
            "",
            "## Artifact References",
            "",
            "- `case_summary.json`",
            "- `test_result.json`",
            "- `evidence_chain_stub.json`",
            "- `expected_findings.json`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def discover_cases(cases_root: Path, selected: list[str]) -> list[Path]:
    if selected:
        case_dirs = [cases_root / case_id for case_id in selected]
    else:
        case_dirs = sorted(path for path in cases_root.iterdir() if path.is_dir())

    missing = [path for path in case_dirs if not path.is_dir()]
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise ValueError(f"case not found: {names}")

    return case_dirs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases-root",
        default="cases/python",
        help="directory containing curated cases (default: cases/python)",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="case id to run; may be provided multiple times",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts",
        help="directory for generated artifacts (default: artifacts)",
    )
    args = parser.parse_args()

    cases_root = Path(args.cases_root)
    output_root = Path(args.output_dir)
    if not cases_root.is_dir():
        print(f"ERROR: cases root not found: {cases_root}", file=sys.stderr)
        return 1

    try:
        case_dirs = discover_cases(cases_root, args.case)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_root.mkdir(parents=True, exist_ok=True)
    failed = False
    for case_dir in case_dirs:
        ok = run_case(case_dir, output_root)
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {case_dir.name} -> {output_root / case_dir.name}")
        failed = failed or not ok

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
