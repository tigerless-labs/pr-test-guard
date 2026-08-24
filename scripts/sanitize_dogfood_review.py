#!/usr/bin/env python3
"""Convert local dogfood notes into a shareable review summary."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


VALID_LABELS = {"useful", "false_positive", "unclear", "needs_more_context"}
VALID_ACTIONS = {"add_fixture", "tighten_rule", "improve_evidence", "docs_only", "no_change"}


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


def _alias(value: Any, fallback: str, pattern: str) -> str:
    if isinstance(value, str) and re.fullmatch(pattern, value):
        return value
    return fallback


def _bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False


def _test_command_shape(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "none"
    lowered = value.lower()
    if "pytest" in lowered:
        return "pytest"
    if "unittest" in lowered:
        return "unittest"
    return "custom"


def _environment_command_shape(environment: dict[str, Any], raw: dict[str, Any]) -> str:
    explicit = environment.get("test_command_shape")
    if explicit in {"pytest", "unittest", "custom", "none", "unknown"}:
        return explicit
    return _test_command_shape(environment.get("test_command") or raw.get("test_command"))


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


def _safe_token(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    token = re.sub(r"[^a-z0-9_:]+", "", token)
    return token or fallback


def _symbol_kind(value: Any) -> str:
    token = _safe_token(value, "unknown")
    return token if token in {"function", "method", "class", "module", "unknown", "none"} else "unknown"


def _dependency_kind(value: Any) -> str:
    token = _safe_token(value, "unknown")
    return token if token in {"internal", "external", "unknown", "none"} else "unknown"


def _review_label(value: Any) -> str:
    token = _safe_token(value, "needs_more_context")
    if token == "false_positive":
        return token
    return token if token in VALID_LABELS else "needs_more_context"


def _action(value: Any) -> str:
    token = _safe_token(value, "no_change")
    return token if token in VALID_ACTIONS else "no_change"


def _evidence_shape(finding: dict[str, Any]) -> str:
    explicit = finding.get("evidence_shape")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    rule_id = finding.get("rule_id")
    if rule_id == "PTG005":
        return "mock boundary relationship signal"
    if rule_id == "PTG006":
        return "targeted probe survivor signal"
    return "rule finding signal"


def sanitize_review(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    environment = raw.get("environment") if isinstance(raw.get("environment"), dict) else {}
    raw_findings = raw.get("findings") if isinstance(raw.get("findings"), list) else []

    sanitized_findings: list[dict[str, Any]] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("rule_id")
        if not isinstance(rule_id, str) or not re.fullmatch(r"PTG[0-9]{3}", rule_id):
            continue
        sanitized_findings.append(
            {
                "rule_id": rule_id,
                "review_label": _review_label(item.get("review_label") or item.get("label")),
                "category": _safe_token(item.get("category"), "uncategorized"),
                "path_kind": item.get("path_kind") if item.get("path_kind") in {"production", "test", "docs", "config", "unknown"} else _path_kind(item.get("file") or item.get("path")),
                "symbol_kind": _symbol_kind(item.get("symbol_kind")),
                "dependency_kind": _dependency_kind(item.get("dependency_kind")),
                "evidence_shape": _evidence_shape(item),
                "action": _action(item.get("action")),
            }
        )

    return {
        "schema_version": "1",
        "review_id": _alias(raw.get("review_id"), "review_001", r"[a-z0-9][a-z0-9_-]*"),
        "source": {
            "visibility": "sanitized_private_review",
            "repo_alias": _alias(source.get("repo_alias") or raw.get("repo_alias"), "repo_001", r"repo_[0-9]{3,}"),
            "pr_alias": _alias(source.get("pr_alias") or raw.get("pr_alias"), "pr_001", r"pr_[0-9]{3,}"),
        },
        "environment": {
            "language": "python" if environment.get("language") == "python" else "unknown",
            "test_framework": environment.get("test_framework") if environment.get("test_framework") in {"pytest", "unittest", "mixed", "unknown"} else "unknown",
            "coverage_supplied": _bool(environment.get("coverage_supplied")),
            "deep_enabled": _bool(environment.get("deep_enabled")),
            "test_command_shape": _environment_command_shape(environment, raw),
        },
        "findings": sanitized_findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="local dogfood review JSON")
    parser.add_argument("-o", "--output", type=Path, help="path for sanitized JSON; stdout when omitted")
    args = parser.parse_args()

    try:
        sanitized = sanitize_review(load_json(args.input))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output:
        write_json(args.output, sanitized)
    else:
        print(json.dumps(sanitized, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
