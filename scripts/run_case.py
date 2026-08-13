#!/usr/bin/env python3
"""Run curated Claim Harness cases and emit raw evidence artifacts.

This is intentionally a small artifact runner, not the full Claim Harness
evaluation engine. It applies each case patch, runs the patched pytest fixture,
and writes reviewable JSON/Markdown outputs for later evidence-chain work.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from validate_cases import validate_case


RUNNER_VERSION = "0.2"


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


def parse_changed_code_lines(patch_text: str) -> dict[str, list[dict[str, Any]]]:
    changed: dict[str, list[dict[str, Any]]] = {}
    current_file: str | None = None
    new_line: int | None = None

    for raw_line in patch_text.splitlines():
        match = re.match(r"^diff --git a/(.*?) b/(.*?)$", raw_line)
        if match:
            current_file = match.group(2)
            new_line = None
            if current_file and not is_test_path(current_file):
                changed.setdefault(current_file, [])
            continue

        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
        if hunk:
            new_line = int(hunk.group(1))
            continue

        if current_file is None or new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            if not is_test_path(current_file) and raw_line[1:].strip():
                changed.setdefault(current_file, []).append(
                    {"line": new_line, "content": raw_line[1:]}
                )
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            new_line += 1

    return {path: lines for path, lines in changed.items() if lines}


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


def coverage_command(repo_copy: Path, coverage_xml_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    test_result = run_command([sys.executable, "-m", "coverage", "run", "--branch", "-m", "pytest", "-q"], repo_copy)
    if not test_result["passed"]:
        return test_result, None

    xml_result = run_command(
        [sys.executable, "-m", "coverage", "xml", "-o", str(coverage_xml_path)],
        repo_copy,
    )
    return test_result, xml_result


def parse_coverage_xml(path: Path) -> dict[str, dict[int, int]]:
    if not path.is_file():
        return {}

    root = ET.parse(path).getroot()
    covered: dict[str, dict[int, int]] = {}
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        lines: dict[int, int] = {}
        for line_node in class_node.findall("./lines/line"):
            number = line_node.attrib.get("number")
            hits = line_node.attrib.get("hits", "0")
            if number:
                lines[int(number)] = int(hits)
        covered[filename] = lines
    return covered


def find_coverage_hits(coverage: dict[str, dict[int, int]], file_path: str, line_number: int) -> int | None:
    candidates = [file_path, f"./{file_path}"]
    for candidate in candidates:
        if candidate in coverage:
            return coverage[candidate].get(line_number, 0)

    for filename, lines in coverage.items():
        if filename.endswith(file_path):
            return lines.get(line_number, 0)

    return None


def build_coverage_map(
    case_id: str,
    changed_code_lines: dict[str, list[dict[str, Any]]],
    coverage_xml_path: Path,
) -> dict[str, Any]:
    coverage = parse_coverage_xml(coverage_xml_path)
    files = []
    total_lines = 0
    covered_lines = 0

    for file_path, lines in changed_code_lines.items():
        mapped_lines = []
        for item in lines:
            total_lines += 1
            hits = find_coverage_hits(coverage, file_path, item["line"])
            covered = bool(hits and hits > 0)
            if covered:
                covered_lines += 1
            mapped_lines.append(
                {
                    "line": item["line"],
                    "content": item["content"],
                    "hits": hits,
                    "covered": covered,
                }
            )
        files.append({"path": file_path, "changed_lines": mapped_lines})

    return {
        "case_id": case_id,
        "runner_version": RUNNER_VERSION,
        "coverage_artifact": "coverage.xml",
        "summary": {
            "changed_code_lines": total_lines,
            "covered_changed_code_lines": covered_lines,
            "uncovered_changed_code_lines": total_lines - covered_lines,
        },
        "files": files,
    }


def source_for_node(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


def summarize_assertions(repo_copy: Path, test_files: list[str]) -> dict[str, Any]:
    files = []
    total_assertions = 0

    for rel_path in test_files:
        path = repo_copy / rel_path
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assertions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                total_assertions += 1
                assertions.append(
                    {
                        "line": node.lineno,
                        "source": source_for_node(source, node),
                        "shape": classify_assertion(node),
                    }
                )
        files.append({"path": rel_path, "assertions": sorted(assertions, key=lambda item: item["line"])})

    return {
        "runner_version": RUNNER_VERSION,
        "summary": {"assertion_count": total_assertions},
        "files": files,
    }


def classify_assertion(node: ast.Assert) -> str:
    test = node.test
    if isinstance(test, ast.Compare):
        ops = [type(op).__name__ for op in test.ops]
        if any(op in {"IsNot", "Is"} for op in ops) and any(
            isinstance(comp, ast.Constant) and comp.value is None for comp in test.comparators
        ):
            return "existence_or_none_check"
        return "comparison"
    if isinstance(test, ast.Name):
        return "truthiness_check"
    if isinstance(test, ast.Call):
        return "call_truthiness_check"
    return type(test).__name__


def summarize_tests(repo_copy: Path, test_files: list[str]) -> dict[str, Any]:
    files = []
    total_tests = 0

    for rel_path in test_files:
        path = repo_copy / rel_path
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        tests = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                total_tests += 1
                tests.append({"name": node.name, "line": node.lineno})
        files.append({"path": rel_path, "tests": sorted(tests, key=lambda item: item["line"])})

    return {
        "runner_version": RUNNER_VERSION,
        "summary": {"test_count": total_tests},
        "files": files,
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
    changed_code_lines = parse_changed_code_lines(patch_text)

    with tempfile.TemporaryDirectory(prefix=f"{case_dir.name}-") as temp:
        temp_dir = Path(temp)
        repo_copy = temp_dir / "repo"
        shutil.copytree(case_dir / "repo", repo_copy)

        apply_result = run_command(
            ["git", "apply", "--whitespace=nowarn", str((case_dir / "pr.patch").resolve())],
            repo_copy,
        )
        test_result = None
        coverage_xml_path = case_output / "coverage.xml"
        coverage_xml_result = None
        test_summary = {"runner_version": RUNNER_VERSION, "summary": {"test_count": 0}, "files": []}
        assertion_summary = {"runner_version": RUNNER_VERSION, "summary": {"assertion_count": 0}, "files": []}
        if apply_result["passed"]:
            test_result, coverage_xml_result = coverage_command(repo_copy, coverage_xml_path)
            test_summary = summarize_tests(repo_copy, test_files)
            assertion_summary = summarize_assertions(repo_copy, test_files)

    write_json(case_output / "test_result.json", test_result or apply_result)
    if coverage_xml_result is not None:
        write_json(case_output / "coverage_result.json", coverage_xml_result)
    write_json(case_output / "expected_findings.json", expected_findings)
    write_json(case_output / "test_diff_summary.json", test_summary)
    write_json(case_output / "assertion_summary.json", assertion_summary)

    coverage_map = build_coverage_map(case_dir.name, changed_code_lines, case_output / "coverage.xml")
    write_json(case_output / "coverage_map.json", coverage_map)

    claim_rows = []
    for claim in claim_doc.get("claims", []):
        claim_rows.append(
            {
                "claim_id": claim.get("id"),
                "claim_text": claim.get("text"),
                "source": claim.get("source"),
                "changed_code_files": changed_code_files,
                "changed_code_lines": changed_code_lines,
                "test_files": test_files,
                "test_result": "test_result.json",
                "coverage_evidence": "coverage_map.json",
                "ci_evidence": "test_result.json",
                "adequacy_finding": None,
            }
        )

    write_json(
        case_output / "evidence_chain.json",
        {
            "case_id": case_dir.name,
            "runner_version": RUNNER_VERSION,
            "status": "evidence_collected",
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
            "changed_code_line_count": coverage_map["summary"]["changed_code_lines"],
            "test_files": test_files,
            "patched_tests_passed": passed,
            "artifacts": [
                "case_summary.json",
                "test_result.json",
                "coverage_result.json",
                "coverage.xml",
                "coverage_map.json",
                "test_diff_summary.json",
                "assertion_summary.json",
                "evidence_chain.json",
                "expected_findings.json",
                "claim_harness_report.md",
            ],
        },
    )
    write_report(
        case_output / "claim_harness_report.md",
        case_dir.name,
        claim_doc,
        passed,
        coverage_map,
        test_summary,
        assertion_summary,
    )
    return passed


def write_report(
    path: Path,
    case_id: str,
    claim_doc: dict[str, Any],
    passed: bool,
    coverage_map: dict[str, Any],
    test_summary: dict[str, Any],
    assertion_summary: dict[str, Any],
) -> None:
    lines = [
        f"# Claim Harness Case Report: {case_id}",
        "",
        "This report is generated by the raw artifact runner. It does not make automated adequacy findings yet.",
        "",
        "## Test Result",
        "",
        f"- Patched fixture tests passed: `{str(passed).lower()}`",
        "",
        "## Coverage",
        "",
        f"- Changed code lines: `{coverage_map['summary']['changed_code_lines']}`",
        f"- Covered changed code lines: `{coverage_map['summary']['covered_changed_code_lines']}`",
        f"- Uncovered changed code lines: `{coverage_map['summary']['uncovered_changed_code_lines']}`",
        "",
        "## Test Evidence",
        "",
        f"- Test functions discovered: `{test_summary['summary']['test_count']}`",
        f"- Assertions discovered: `{assertion_summary['summary']['assertion_count']}`",
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
            "- `coverage.xml`",
            "- `coverage_map.json`",
            "- `test_diff_summary.json`",
            "- `assertion_summary.json`",
            "- `evidence_chain.json`",
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
