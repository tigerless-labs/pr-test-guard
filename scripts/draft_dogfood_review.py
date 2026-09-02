#!/usr/bin/env python3
"""Create a local dogfood review draft from a PR Test Guard JSON report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


VALID_TEST_FRAMEWORKS = {"pytest", "unittest", "mixed", "unknown"}
VALID_COMMAND_SHAPES = {"pytest", "unittest", "custom", "none", "unknown"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def draft_review(
    report: dict[str, Any],
    *,
    review_id: str,
    repo_alias: str,
    pr_alias: str,
    test_framework: str,
    test_command_shape: str,
) -> dict[str, Any]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    notes = report.get("notes") if isinstance(report.get("notes"), list) else []
    probes = report.get("probes") if isinstance(report.get("probes"), dict) else {}

    return {
        "schema_version": "1",
        "review_id": _alias(review_id, "review_001", r"[a-z0-9][a-z0-9_-]*"),
        "source": {
            "visibility": "sanitized_private_review",
            "repo_alias": _alias(repo_alias, "repo_001", r"repo_[0-9]{3,}"),
            "pr_alias": _alias(pr_alias, "pr_001", r"pr_[0-9]{3,}"),
        },
        "environment": {
            "language": "python" if _looks_like_python_report(report) else "unknown",
            "test_framework": test_framework if test_framework in VALID_TEST_FRAMEWORKS else "unknown",
            "coverage_supplied": _coverage_supplied(notes),
            "deep_enabled": bool(probes.get("enabled")) if isinstance(probes.get("enabled"), bool) else False,
            "test_command_shape": test_command_shape if test_command_shape in VALID_COMMAND_SHAPES else "unknown",
        },
        "report": {
            "base": report.get("base"),
            "head": report.get("head"),
            "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
        },
        "findings": [_draft_finding(item) for item in findings if isinstance(item, dict)],
    }


def _draft_finding(finding: dict[str, Any]) -> dict[str, Any]:
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), str) else ""
    message = finding.get("message") if isinstance(finding.get("message"), str) else ""
    return {
        "rule_id": finding.get("rule_id"),
        "review_label": "needs_more_context",
        "category": "uncategorized",
        "path_kind": _path_kind(finding.get("file")),
        "symbol_kind": _symbol_kind(evidence, message),
        "dependency_kind": _dependency_kind(evidence),
        "evidence_shape": _evidence_shape(finding, evidence),
        "action": "no_change",
        "file": finding.get("file"),
        "line": finding.get("line"),
        "severity": finding.get("severity"),
        "message": message,
        "evidence": evidence,
    }


def _alias(value: str, fallback: str, pattern: str) -> str:
    return value if re.fullmatch(pattern, value) else fallback


def _looks_like_python_report(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if summary.get("production_files") or summary.get("test_files"):
        return True
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    return any(isinstance(item, dict) and _path_kind(item.get("file")) in {"production", "test"} for item in findings)


def _coverage_supplied(notes: list[Any]) -> bool:
    rendered_notes = "\n".join(item for item in notes if isinstance(item, str))
    return "PTG002 skipped: no coverage XML was provided." not in rendered_notes


def _path_kind(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if "/tests/" in f"/{normalized}" or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if normalized.endswith(".md") or normalized.startswith("docs/"):
        return "docs"
    if name in {"pyproject.toml", "setup.py", "tox.ini"} or normalized.startswith(".github/"):
        return "config"
    if normalized.endswith(".py"):
        return "production"
    return "unknown"


def _symbol_kind(evidence: str, message: str) -> str:
    text = f"{evidence} {message}".lower()
    if "method" in text or re.search(r"\bclass\.[a-z_]", text):
        return "method"
    if "class" in text:
        return "class"
    if "module" in text:
        return "module"
    if "symbol" in text or "function" in text or "(" in evidence:
        return "function"
    return "unknown"


def _dependency_kind(evidence: str) -> str:
    text = evidence.lower()
    if "dependency_kind=external" in text or "external" in text:
        return "external"
    if "dependency_kind=internal" in text or "internal" in text or "dependency" in text:
        return "internal"
    if "mock" in text:
        return "unknown"
    return "none"


def _evidence_shape(finding: dict[str, Any], evidence: str) -> str:
    rule_id = finding.get("rule_id")
    lowered = evidence.lower()
    if rule_id == "PTG001":
        return "production changed without test file change"
    if rule_id == "PTG002":
        return "changed line uncovered by supplied coverage"
    if rule_id == "PTG003":
        return "weak assertion added in changed test"
    if rule_id == "PTG004":
        return "test validation scope weakened"
    if rule_id == "PTG005":
        if "direct_changed_symbol_mock" in lowered:
            return "changed test mocks changed symbol directly"
        if "owner" in lowered or "dependency" in lowered or "changed call" in lowered:
            return "changed test mocks dependency called from changed line"
        return "mock boundary relationship signal"
    if rule_id == "PTG006":
        if "kind=comparison" in lowered or "comparison" in lowered:
            return "comparison boundary probe survived configured tests"
        return "targeted probe survived configured tests"
    return "rule finding signal"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="JSON report written by pr-test-guard check --json-output")
    parser.add_argument("-o", "--output", type=Path, help="path for the local raw review draft; stdout when omitted")
    parser.add_argument("--review-id", default="review_001", help="sanitized-safe review id")
    parser.add_argument("--repo-alias", default="repo_001", help="sanitized-safe repository alias, for example repo_001")
    parser.add_argument("--pr-alias", default="pr_001", help="sanitized-safe pull request alias, for example pr_001")
    parser.add_argument(
        "--test-framework",
        default="unknown",
        choices=sorted(VALID_TEST_FRAMEWORKS),
        help="coarse test framework label for the review environment",
    )
    parser.add_argument(
        "--test-command-shape",
        default="unknown",
        choices=sorted(VALID_COMMAND_SHAPES),
        help="coarse test command shape; do not include the raw command",
    )
    args = parser.parse_args()

    try:
        draft = draft_review(
            load_json(args.report),
            review_id=args.review_id,
            repo_alias=args.repo_alias,
            pr_alias=args.pr_alias,
            test_framework=args.test_framework,
            test_command_shape=args.test_command_shape,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output:
        write_json(args.output, draft)
    else:
        print(json.dumps(draft, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
