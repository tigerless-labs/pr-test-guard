#!/usr/bin/env python3
"""Run curated Claim Harness cases and emit evidence adequacy artifacts.

This is intentionally a small runner, not a general repository evaluator. It
applies each case patch, runs the patched pytest fixture, maps coverage, checks
obvious assertion and mock-boundary signals, runs limited counterfactual probes,
and writes reviewable JSON/Markdown outputs.
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


RUNNER_VERSION = "0.3"

WEAK_ASSERTION_SHAPES = {
    "existence_or_none_check",
    "truthiness_check",
    "call_truthiness_check",
}

PROBE_REPLACEMENTS = [
    ("status_code=400", "status_code=201", "weaken HTTP 400 response to success"),
    ("status_code = 400", "status_code = 201", "weaken HTTP 400 response to success"),
    ("return 400", "return 201", "weaken HTTP 400 return to success"),
    ("return 401", "return 200", "weaken HTTP 401 return to success"),
    ("status_code=401", "status_code=200", "weaken HTTP 401 response to success"),
    ("status_code = 401", "status_code = 200", "weaken HTTP 401 response to success"),
    ("return 403", "return 200", "weaken HTTP 403 return to success"),
    ("status_code=403", "status_code=200", "weaken HTTP 403 response to success"),
    ("status_code = 403", "status_code = 200", "weaken HTTP 403 response to success"),
    ("return 404", "return 200", "weaken HTTP 404 return to success"),
    ("status_code=404", "status_code=200", "weaken HTTP 404 response to success"),
    ("status_code = 404", "status_code = 200", "weaken HTTP 404 response to success"),
    ("return 422", "return 200", "weaken HTTP 422 return to success"),
    ("status_code=422", "status_code=200", "weaken HTTP 422 response to success"),
    ("status_code = 422", "status_code = 200", "weaken HTTP 422 response to success"),
    ("return 500", "return 200", "weaken HTTP 500 return to success"),
    ("status_code=500", "status_code=200", "weaken HTTP 500 response to success"),
    ("status_code = 500", "status_code = 200", "weaken HTTP 500 response to success"),
    ("return False", "return True", "flip false return"),
    ("return True", "return False", "flip true return"),
    ("max_attempts: int = 3", "max_attempts: int = 5", "weaken retry limit"),
    ("max_attempts=3", "max_attempts=5", "weaken retry limit"),
    (" <= ", " < ", "weaken inclusive upper-bound comparison"),
    (" >= ", " > ", "weaken inclusive lower-bound comparison"),
]


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


def clear_python_bytecode(root: Path) -> None:
    for cache_dir in root.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)


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


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return None


def token_set(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = value.lower().replace("_", " ")
        tokens.update(re.findall(r"[a-zA-Z0-9]+", normalized))
    return {token for token in tokens if len(token) > 1}


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


def collect_changed_symbols(
    repo_copy: Path,
    changed_code_files: list[str],
    changed_code_lines: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []

    for rel_path in changed_code_files:
        path = repo_copy / rel_path
        if not path.is_file() or path.suffix != ".py":
            continue
        changed_lines = {item["line"] for item in changed_code_lines.get(rel_path, [])}
        if not changed_lines:
            continue

        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_name = path.with_suffix("").name
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", start)
            if start is None or end is None:
                continue
            if not any(start <= line <= end for line in changed_lines):
                continue
            symbols.append(
                {
                    "file": rel_path,
                    "name": node.name,
                    "kind": type(node).__name__,
                    "line_start": start,
                    "line_end": end,
                    "candidate_targets": sorted(
                        {
                            node.name,
                            f"{module_name}.{node.name}",
                            f"{rel_path.removesuffix('.py').replace('/', '.')}.{node.name}",
                        }
                    ),
                }
            )

    return symbols


def extract_mock_target(source: str, node: ast.Call) -> tuple[str | None, str | None]:
    name = call_name(node)
    if not name:
        return None, None

    if name.endswith("patch.object") and len(node.args) >= 2:
        attr = node.args[1]
        if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
            return f"{source_for_node(source, node.args[0])}.{attr.value}", "patch.object"

    if name == "patch" or name.endswith(".patch"):
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value, "patch"

    if name.endswith(".setattr") and len(node.args) >= 2:
        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value, "setattr"
        if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            return f"{source_for_node(source, node.args[0])}.{node.args[1].value}", "setattr"

    return None, None


def mock_matches_changed_symbol(target: str, symbol: dict[str, Any]) -> bool:
    normalized = target.strip("'\"")
    for candidate in symbol["candidate_targets"]:
        if normalized == candidate or normalized.endswith(f".{candidate}") or candidate.endswith(f".{normalized}"):
            return True
    return False


def summarize_mock_boundaries(
    repo_copy: Path,
    test_files: list[str],
    changed_symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    mocks: list[dict[str, Any]] = []

    for rel_path in test_files:
        path = repo_copy / rel_path
        if not path.is_file() or path.suffix != ".py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for test_node in ast.walk(tree):
            if not isinstance(test_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not test_node.name.startswith("test_"):
                continue

            call_nodes = [
                node for node in ast.walk(test_node) if isinstance(node, ast.Call)
            ]
            call_nodes.extend(
                node for node in test_node.decorator_list if isinstance(node, ast.Call)
            )
            for call in call_nodes:
                target, style = extract_mock_target(source, call)
                if not target or not style:
                    continue
                matched_symbols = [
                    symbol
                    for symbol in changed_symbols
                    if mock_matches_changed_symbol(target, symbol)
                ]
                mocks.append(
                    {
                        "file": rel_path,
                        "line": call.lineno,
                        "test": test_node.name,
                        "style": style,
                        "target": target,
                        "source": source_for_node(source, call),
                        "is_core_path_candidate": bool(matched_symbols),
                        "matched_changed_symbols": matched_symbols,
                    }
                )

    return {
        "runner_version": RUNNER_VERSION,
        "summary": {
            "mock_count": len(mocks),
            "core_path_candidate_count": sum(
                1 for item in mocks if item["is_core_path_candidate"]
            ),
        },
        "changed_symbols": changed_symbols,
        "mocks": sorted(mocks, key=lambda item: (item["file"], item["line"], item["target"])),
    }


def generate_counterfactual_probes(
    changed_code_lines: dict[str, list[dict[str, Any]]],
    max_probes: int = 5,
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for rel_path, lines in changed_code_lines.items():
        for item in lines:
            content = item["content"]
            for original, replacement, rationale in PROBE_REPLACEMENTS:
                if original not in content:
                    continue
                probes.append(
                    {
                        "id": f"P{len(probes) + 1}",
                        "file": rel_path,
                        "line": item["line"],
                        "original": original,
                        "replacement": replacement,
                        "rationale": rationale,
                    }
                )
                break
            if len(probes) >= max_probes:
                return probes
    return probes


def run_counterfactual_probes(
    repo_copy: Path,
    changed_code_lines: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    probes = generate_counterfactual_probes(changed_code_lines)
    results: list[dict[str, Any]] = []

    for probe in probes:
        path = repo_copy / probe["file"]
        if not path.is_file():
            results.append({**probe, "applied": False, "survived": None, "error": "file not found"})
            continue

        original_text = path.read_text(encoding="utf-8")
        lines = original_text.splitlines(keepends=True)
        index = probe["line"] - 1
        if index < 0 or index >= len(lines) or probe["original"] not in lines[index]:
            results.append(
                {
                    **probe,
                    "applied": False,
                    "survived": None,
                    "error": "expected source fragment not found at changed line",
                }
            )
            continue

        lines[index] = lines[index].replace(probe["original"], probe["replacement"], 1)
        path.write_text("".join(lines), encoding="utf-8")
        clear_python_bytecode(repo_copy)
        test_result = run_command([sys.executable, "-m", "pytest", "-q"], repo_copy)
        path.write_text(original_text, encoding="utf-8")
        clear_python_bytecode(repo_copy)

        results.append(
            {
                **probe,
                "applied": True,
                "survived": bool(test_result["passed"]),
                "test_result": {
                    "command": test_result["command"],
                    "returncode": test_result["returncode"],
                    "passed": test_result["passed"],
                    "stdout": test_result["stdout"],
                    "stderr": test_result["stderr"],
                },
            }
        )

    return {
        "runner_version": RUNNER_VERSION,
        "summary": {
            "probes_generated": len(probes),
            "probes_applied": sum(1 for item in results if item["applied"]),
            "survivors": sum(1 for item in results if item.get("survived") is True),
        },
        "probes": results,
    }


def flatten_assertions(assertion_summary: dict[str, Any]) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    for file_item in assertion_summary.get("files", []):
        for assertion in file_item.get("assertions", []):
            assertions.append({**assertion, "file": file_item.get("path")})
    return assertions


def flatten_tests(test_summary: dict[str, Any]) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for file_item in test_summary.get("files", []):
        for test in file_item.get("tests", []):
            tests.append({**test, "file": file_item.get("path")})
    return tests


def claim_expected_numbers(claim: dict[str, Any]) -> set[str]:
    return set(
        re.findall(
            r"\b\d{3}\b",
            " ".join(
                str(claim.get(key, ""))
                for key in ("text", "trigger", "expected_outcome")
            ),
        )
    )


def has_issue_test_mismatch(claim: dict[str, Any], assertions: list[dict[str, Any]], tests: list[dict[str, Any]]) -> bool:
    evidence_text = " ".join(
        [item.get("source", "") for item in assertions]
        + [item.get("name", "") for item in tests]
    ).lower()
    trigger = str(claim.get("trigger", "")).lower()

    if "expired" in trigger and "expired=true" not in evidence_text.replace(" ", ""):
        return True

    expected_numbers = claim_expected_numbers(claim)
    if expected_numbers:
        assertion_text = " ".join(item.get("source", "") for item in assertions)
        has_expected_number = any(number in assertion_text for number in expected_numbers)
        trigger_tokens = token_set(claim.get("trigger")) - {"is", "the", "a", "an", "with"}
        evidence_tokens = token_set(evidence_text)
        has_trigger_overlap = bool(trigger_tokens & evidence_tokens)
        return not has_expected_number and not has_trigger_overlap

    return False


def finding(
    finding_type: str,
    evidence_refs: list[str],
    rationale: str,
) -> dict[str, Any]:
    return {
        "type": finding_type,
        "evidence_refs": sorted(set(evidence_refs)),
        "rationale": rationale,
    }


def build_findings(
    case_id: str,
    claim_doc: dict[str, Any],
    test_result: dict[str, Any],
    coverage_map: dict[str, Any],
    test_summary: dict[str, Any],
    assertion_summary: dict[str, Any],
    mock_summary: dict[str, Any],
    counterfactual_results: dict[str, Any],
) -> dict[str, Any]:
    assertions = flatten_assertions(assertion_summary)
    tests = flatten_tests(test_summary)
    test_refs = [f"repo/{item['file']}::{item['name']}" for item in tests]
    weak_assertion_refs = [
        f"repo/{item['file']}:{item['line']}"
        for item in assertions
        if item.get("shape") in WEAK_ASSERTION_SHAPES
    ]
    coverage_refs = [
        f"repo/{file_item['path']}:{line_item['line']}"
        for file_item in coverage_map.get("files", [])
        for line_item in file_item.get("changed_lines", [])
        if not line_item.get("covered")
    ]
    mock_refs = [
        f"repo/{item['file']}:{item['line']}"
        for item in mock_summary.get("mocks", [])
        if item.get("is_core_path_candidate")
    ]
    survivor_refs = [
        f"{item['id']}:{item['file']}:{item['line']}"
        for item in counterfactual_results.get("probes", [])
        if item.get("survived") is True
    ]

    claim_results = []
    for claim in claim_doc.get("claims", []):
        claim_findings: list[dict[str, Any]] = []
        mismatch = has_issue_test_mismatch(claim, assertions, tests)

        if not tests or not assertions:
            claim_findings.append(
                finding(
                    "Missing Test Evidence",
                    [],
                    "No changed test function and assertion evidence was found for this claim.",
                )
            )

        if coverage_refs:
            claim_findings.append(
                finding(
                    "Uncovered Changed Lines",
                    coverage_refs,
                    "One or more changed executable lines were not covered by the patched test run.",
                )
            )

        if mismatch:
            claim_findings.append(
                finding(
                    "Issue-Test Mismatch",
                    test_refs,
                    "The discovered tests exercise a nearby path, but they do not constrain the trigger or outcome named by the claim.",
                )
            )
            claim_findings.append(
                finding(
                    "Missing Test Evidence",
                    test_refs,
                    "The claim has tests in the PR, but no clear test evidence for the claimed behavior was found.",
                )
            )

        if weak_assertion_refs and not mismatch:
            claim_findings.append(
                finding(
                    "Weak Assertion",
                    weak_assertion_refs,
                    "At least one related test uses an assertion shape that exercises code without constraining the claimed outcome.",
                )
            )

        if mock_refs:
            claim_findings.append(
                finding(
                    "Mocked Core Path",
                    mock_refs,
                    "A test mock target matches a changed function or class, so the test may replace the path it should validate.",
                )
            )

        if survivor_refs:
            claim_findings.append(
                finding(
                    "Counterfactual Survivor",
                    survivor_refs,
                    "A generated counterfactual weakened changed behavior and the patched test suite still passed.",
                )
            )

        if not claim_findings and test_result.get("passed"):
            claim_findings.append(
                finding(
                    "Evidence Complete",
                    test_refs,
                    "The current evidence chain covers changed lines, includes constraining assertions, and has no v0 mock or probe warning. Human review is still required.",
                )
            )

        adequacy = "complete" if all(item["type"] == "Evidence Complete" for item in claim_findings) else "weak"
        claim_results.append(
            {
                "claim_id": claim.get("id"),
                "adequacy": adequacy,
                "findings": claim_findings,
            }
        )

    return {
        "case_id": case_id,
        "runner_version": RUNNER_VERSION,
        "claims": claim_results,
    }


def compare_findings(case_id: str, generated: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    expected_by_claim = {
        item.get("claim_id"): sorted({finding.get("type") for finding in item.get("findings", [])})
        for item in expected.get("claims", [])
    }
    generated_by_claim = {
        item.get("claim_id"): sorted({finding.get("type") for finding in item.get("findings", [])})
        for item in generated.get("claims", [])
    }
    claims = []
    exact_matches = 0
    for claim_id in sorted(set(expected_by_claim) | set(generated_by_claim)):
        expected_labels = expected_by_claim.get(claim_id, [])
        generated_labels = generated_by_claim.get(claim_id, [])
        missing = sorted(set(expected_labels) - set(generated_labels))
        extra = sorted(set(generated_labels) - set(expected_labels))
        exact = not missing and not extra
        exact_matches += int(exact)
        claims.append(
            {
                "claim_id": claim_id,
                "expected_labels": expected_labels,
                "generated_labels": generated_labels,
                "missing_expected_labels": missing,
                "extra_generated_labels": extra,
                "exact_label_match": exact,
            }
        )

    return {
        "case_id": case_id,
        "runner_version": RUNNER_VERSION,
        "summary": {
            "claims_compared": len(claims),
            "exact_label_matches": exact_matches,
            "exact_label_match": exact_matches == len(claims),
        },
        "claims": claims,
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
        mock_summary = {
            "runner_version": RUNNER_VERSION,
            "summary": {"mock_count": 0, "core_path_candidate_count": 0},
            "changed_symbols": [],
            "mocks": [],
        }
        counterfactual_results = {
            "runner_version": RUNNER_VERSION,
            "summary": {"probes_generated": 0, "probes_applied": 0, "survivors": 0},
            "probes": [],
        }
        if apply_result["passed"]:
            test_result, coverage_xml_result = coverage_command(repo_copy, coverage_xml_path)
            test_summary = summarize_tests(repo_copy, test_files)
            assertion_summary = summarize_assertions(repo_copy, test_files)
            changed_symbols = collect_changed_symbols(repo_copy, changed_code_files, changed_code_lines)
            mock_summary = summarize_mock_boundaries(repo_copy, test_files, changed_symbols)
            counterfactual_results = run_counterfactual_probes(repo_copy, changed_code_lines)

    write_json(case_output / "test_result.json", test_result or apply_result)
    if coverage_xml_result is not None:
        write_json(case_output / "coverage_result.json", coverage_xml_result)
    write_json(case_output / "expected_findings.json", expected_findings)
    write_json(case_output / "test_diff_summary.json", test_summary)
    write_json(case_output / "assertion_summary.json", assertion_summary)
    write_json(case_output / "mock_boundary_summary.json", mock_summary)
    write_json(case_output / "counterfactual_results.json", counterfactual_results)

    coverage_map = build_coverage_map(case_dir.name, changed_code_lines, case_output / "coverage.xml")
    write_json(case_output / "coverage_map.json", coverage_map)
    active_test_result = test_result or apply_result
    generated_findings = build_findings(
        case_dir.name,
        claim_doc,
        active_test_result,
        coverage_map,
        test_summary,
        assertion_summary,
        mock_summary,
        counterfactual_results,
    )
    write_json(case_output / "findings.json", generated_findings)
    comparison_summary = compare_findings(case_dir.name, generated_findings, expected_findings)
    write_json(case_output / "comparison_summary.json", comparison_summary)

    claim_rows = []
    findings_by_claim = {
        item.get("claim_id"): item
        for item in generated_findings.get("claims", [])
    }
    for claim in claim_doc.get("claims", []):
        claim_finding = findings_by_claim.get(claim.get("id"), {})
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
                "mock_boundary_evidence": "mock_boundary_summary.json",
                "counterfactual_evidence": "counterfactual_results.json",
                "adequacy_finding": claim_finding.get("adequacy"),
                "findings": claim_finding.get("findings", []),
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

    passed = bool(active_test_result["passed"])
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
                "mock_boundary_summary.json",
                "counterfactual_results.json",
                "evidence_chain.json",
                "findings.json",
                "comparison_summary.json",
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
        mock_summary,
        counterfactual_results,
        generated_findings,
        comparison_summary,
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
    mock_summary: dict[str, Any],
    counterfactual_results: dict[str, Any],
    generated_findings: dict[str, Any],
    comparison_summary: dict[str, Any],
) -> None:
    lines = [
        f"# Claim Harness Case Report: {case_id}",
        "",
        "This report is generated by the curated-case runner. Findings are review support signals, not proof that a PR is correct.",
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
        "## Mock Boundary",
        "",
        f"- Mock targets discovered: `{mock_summary['summary']['mock_count']}`",
        f"- Core-path mock candidates: `{mock_summary['summary']['core_path_candidate_count']}`",
        "",
        "## Counterfactual Probes",
        "",
        f"- Probes generated: `{counterfactual_results['summary']['probes_generated']}`",
        f"- Probes applied: `{counterfactual_results['summary']['probes_applied']}`",
        f"- Survivors: `{counterfactual_results['summary']['survivors']}`",
        "",
        "## Findings",
        "",
    ]

    for claim_result in generated_findings.get("claims", []):
        lines.append(f"### `{claim_result.get('claim_id')}`")
        lines.append("")
        lines.append(f"- Adequacy: `{claim_result.get('adequacy')}`")
        for item in claim_result.get("findings", []):
            refs = ", ".join(f"`{ref}`" for ref in item.get("evidence_refs", [])) or "`none`"
            lines.append(f"- `{item.get('type')}`: {item.get('rationale')} Evidence: {refs}.")
        lines.append("")

    lines.extend(
        [
            "## Expected Comparison",
            "",
            f"- Exact label match: `{str(comparison_summary['summary']['exact_label_match']).lower()}`",
            f"- Claims compared: `{comparison_summary['summary']['claims_compared']}`",
            "",
        ]
    )

    lines.extend(
        [
        "## Claims",
        "",
        ]
    )

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
            "- `mock_boundary_summary.json`",
            "- `counterfactual_results.json`",
            "- `evidence_chain.json`",
            "- `findings.json`",
            "- `comparison_summary.json`",
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
