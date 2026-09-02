#!/usr/bin/env python3
"""Summarize sanitized dogfood review records."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


LABELS = ("useful", "false_positive", "unclear", "needs_more_context")


def load_records(root: Path) -> list[dict[str, Any]]:
    if root.is_file():
        paths = [root]
    else:
        paths = sorted(root.glob("*.json"))
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected a JSON object")
        if value.get("schema_version") != "1" or not isinstance(value.get("findings"), list):
            continue
        records.append(value)
    return records


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_rule: dict[str, dict[str, Any]] = {}
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    evidence_shape_counts: dict[str, Counter[str]] = defaultdict(Counter)
    action_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for record in records:
        findings = record.get("findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            rule_id = finding.get("rule_id")
            label = finding.get("review_label")
            category = finding.get("category")
            evidence_shape = finding.get("evidence_shape")
            action = finding.get("action")
            if not isinstance(rule_id, str) or label not in LABELS:
                continue
            bucket = by_rule.setdefault(
                rule_id,
                {
                    "total": 0,
                    "labels": {item: 0 for item in LABELS},
                    "label_rates": {item: 0.0 for item in LABELS},
                    "top_categories": [],
                    "top_evidence_shapes": [],
                    "actions": {},
                    "recommended_next_actions": [],
                },
            )
            bucket["total"] += 1
            bucket["labels"][label] += 1
            if isinstance(category, str) and category:
                category_counts[rule_id][category] += 1
            if isinstance(evidence_shape, str) and evidence_shape:
                evidence_shape_counts[rule_id][evidence_shape] += 1
            if isinstance(action, str) and action:
                action_counts[rule_id][action] += 1

    for rule_id, bucket in by_rule.items():
        total = bucket["total"]
        bucket["label_rates"] = {
            label: round(count / total, 3) if total else 0.0
            for label, count in bucket["labels"].items()
        }
        bucket["top_categories"] = [
            {"category": category, "count": count}
            for category, count in category_counts[rule_id].most_common(5)
        ]
        bucket["top_evidence_shapes"] = [
            {"evidence_shape": shape, "count": count}
            for shape, count in evidence_shape_counts[rule_id].most_common(5)
        ]
        bucket["actions"] = dict(sorted(action_counts[rule_id].items()))
        bucket["recommended_next_actions"] = _recommended_actions(bucket)

    return {
        "record_count": len(records),
        "finding_count": sum(item["total"] for item in by_rule.values()),
        "rules": dict(sorted(by_rule.items())),
    }


def _recommended_actions(bucket: dict[str, Any]) -> list[str]:
    labels = bucket["labels"]
    actions: list[str] = []
    if labels["false_positive"]:
        actions.append("add_negative_control_fixture")
        actions.append("tighten_rule_or_evidence")
    if labels["unclear"] or labels["needs_more_context"]:
        actions.append("improve_finding_context")
    if labels["useful"] and not actions:
        actions.append("keep_rule_behavior")
    return actions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="sanitized record file or directory")
    args = parser.parse_args()

    try:
        summary = summarize_records(load_records(args.path))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
