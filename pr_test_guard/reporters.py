"""Human, JSON, and GitHub Actions output for PR Test Guard."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .check import AnalysisResult
from .config import (
    DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE,
    DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL,
)
from .finding import Finding


def _location(item: Finding) -> str:
    if item.file and item.line:
        return f"{item.file}:{item.line}"
    if item.file:
        return item.file
    return "repository"


def render_text(result: AnalysisResult) -> str:
    production = sum(
        1 for item in result.files if item.path.endswith(".py") and not result.test_paths.is_test(item.path)
    )
    tests = sum(1 for item in result.files if result.test_paths.is_test(item.path))
    lines = [
        "PR Test Guard",
        "─────────────",
        f"Base: {result.base}",
        f"Changed files: {len(result.files)} ({production} Python production, {tests} test)",
        f"Related test candidates: {len(result.related_tests)}",
        f"Policy: {_policy_label(result)}",
        "",
    ]
    if result.findings:
        lines.append(f"{len(result.findings)} review signal(s)")
        lines.append("")
        for rule_id, items in _findings_by_rule(result.findings):
            lines.append(f"{rule_id} ({_severity_counts(items)})")
            for item in items:
                marker = "ERROR" if item.severity == "error" else "WARN"
                lines.append(f"  [{marker}] {_location(item)}")
                lines.append(f"  {item.message}")
                if item.evidence:
                    lines.append(f"  Evidence: {item.evidence}")
            lines.append("")
    else:
        lines.extend(["No review signals found by the enabled rules.", ""])

    related_limit = _related_test_limit(result)
    if result.related_tests and related_limit:
        lines.append("Related Tests")
        for item in result.related_tests[:related_limit]:
            targets = ", ".join((*item.matched_symbols, *item.matched_sources)[:3])
            reasons = ", ".join(item.reasons)
            lines.append(f"- {item.file}:{item.line} {item.test_name} ({targets}; {reasons})")
        hidden = len(result.related_tests) - related_limit
        if hidden > 0:
            lines.append(f"- ... {hidden} more related test candidate(s) hidden by related_tests.max_candidates")
        lines.append("")

    if result.notes:
        lines.append("Notes")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("Result: advisory — findings do not block merge by default.")
    return "\n".join(lines).rstrip() + "\n"


def render_json(result: AnalysisResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def _escape_workflow_message(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_workflow_property(value: str) -> str:
    return _escape_workflow_message(value).replace(":", "%3A").replace(",", "%2C")


def _annotation(item: Finding) -> str:
    attrs = [f"title={_escape_workflow_property(f'PR Test Guard / {item.rule_id}')}"]
    if item.file:
        attrs.append(f"file={_escape_workflow_property(item.file)}")
    if item.file and item.line:
        attrs.append(f"line={item.line}")
    metadata = f" {','.join(attrs)}"
    message = f"[{item.rule_id}] {item.message}"
    if item.evidence:
        message += f" Evidence: {item.evidence}"
    command = "error" if item.severity == "error" else "warning"
    return f"::{command}{metadata}::{_escape_workflow_message(message)}"


def github_summary(result: AnalysisResult) -> str:
    selected_annotations, omitted_annotations = _select_github_annotations(result)
    omitted_total = sum(omitted_annotations.values())
    lines = [
        "## PR Test Guard",
        "",
        f"**{len(result.findings)} review signal(s)** found between `{result.base}` and `HEAD`.",
        f"**{len(result.related_tests)} related test candidate(s)** identified from deterministic or configured path context.",
        f"**Policy:** {_policy_label(result)}.",
        (
            f"**Annotations:** {len(selected_annotations)} emitted, "
            f"{omitted_total} omitted by configured limits."
        ),
        "",
    ]
    if omitted_annotations:
        omitted_by_rule = ", ".join(
            f"{rule_id}={count}" for rule_id, count in sorted(omitted_annotations.items())
        )
        lines.extend(
            [
                f"> Annotation stream limited; omitted findings by rule: {omitted_by_rule}. "
                "The tables and JSON report retain every finding.",
                "",
            ]
        )
    if result.findings:
        for rule_id, items in _findings_by_rule(result.findings):
            lines.append(f"### {rule_id} ({_severity_counts(items)})")
            lines.append("")
            lines.extend(["| Severity | Location | Signal | Evidence |", "| --- | --- | --- | --- |"])
            for item in items:
                lines.append(
                    "| "
                    f"{_markdown_cell(item.severity)} | "
                    f"`{_location(item)}` | "
                    f"{_markdown_cell(item.message)} | "
                    f"{_markdown_cell(item.evidence or '')} |"
                )
            lines.append("")
    else:
        lines.extend(["No review signals found by the enabled rules.", ""])
    related_limit = _related_test_limit(result)
    if result.related_tests and related_limit:
        lines.append("### Related Test Candidates")
        lines.append("")
        lines.extend(["| Test | Changed target(s) | Reason(s) |", "| --- | --- | --- |"])
        for item in result.related_tests[:related_limit]:
            targets = ", ".join((*item.matched_symbols, *item.matched_sources))
            lines.append(
                "| "
                f"`{item.file}:{item.line} {item.test_name}` | "
                f"{_markdown_cell(targets)} | "
                f"{_markdown_cell(', '.join(item.reasons))} |"
            )
        hidden = len(result.related_tests) - related_limit
        if hidden > 0:
            lines.append(f"| _{hidden} more hidden by `related_tests.max_candidates`_ |  |  |")
        lines.append("")
    if result.notes:
        lines.append("### Notes")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")
    if any(item.severity == "error" for item in result.findings):
        lines.append("_Configured policy failed because at least one error-level rule triggered._")
    else:
        lines.append("_No error-level policy triggered. Warning findings remain advisory._")
    return "\n".join(lines) + "\n"


def emit_github(result: AnalysisResult) -> str:
    selected, omitted = _select_github_annotations(result)
    output_lines = [_annotation(item) for item in selected]
    status = _github_status(result)
    omitted_total = sum(omitted.values())
    output_lines.append(
        f"PR Test Guard: {len(result.findings)} review signal(s); "
        f"{len(selected)} annotation(s) emitted; {omitted_total} omitted; {status}."
    )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).open("a", encoding="utf-8").write(github_summary(result))
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        errors = sum(1 for item in result.findings if item.severity == "error")
        warnings = len(result.findings) - errors
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"status={status}\n")
            handle.write(f"findings-count={len(result.findings)}\n")
            handle.write(f"warning-count={warnings}\n")
            handle.write(f"error-count={errors}\n")
    return "\n".join(output_lines) + "\n"


def _github_status(result: AnalysisResult) -> str:
    if any(item.severity == "error" for item in result.findings):
        return "failed"
    if result.findings:
        return "advisory"
    return "clean"


def _select_github_annotations(
    result: AnalysisResult,
) -> tuple[list[Finding], dict[str, int]]:
    max_total, max_per_rule = _github_annotation_limits(result)
    ordered = sorted(
        enumerate(result.findings),
        key=lambda entry: (
            0 if entry[1].severity == "error" else 1,
            entry[1].rule_id,
            entry[1].file or "",
            entry[1].line if entry[1].line is not None else -1,
            entry[0],
        ),
    )
    selected: list[Finding] = []
    selected_by_rule: dict[str, int] = {}
    omitted_by_rule: dict[str, int] = {}
    for _, finding in ordered:
        rule_count = selected_by_rule.get(finding.rule_id, 0)
        if len(selected) >= max_total or rule_count >= max_per_rule:
            omitted_by_rule[finding.rule_id] = omitted_by_rule.get(finding.rule_id, 0) + 1
            continue
        selected.append(finding)
        selected_by_rule[finding.rule_id] = rule_count + 1
    return selected, omitted_by_rule


def _github_annotation_limits(result: AnalysisResult) -> tuple[int, int]:
    if not result.policy:
        return DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL, DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE
    github = result.policy.get("github")
    if not isinstance(github, dict):
        return DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL, DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE
    annotations = github.get("annotations")
    if not isinstance(annotations, dict):
        return DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL, DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE
    max_total = annotations.get("max_total", DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL)
    max_per_rule = annotations.get("max_per_rule", DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE)
    if isinstance(max_total, bool) or not isinstance(max_total, int) or max_total < 0:
        max_total = DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL
    if isinstance(max_per_rule, bool) or not isinstance(max_per_rule, int) or max_per_rule < 0:
        max_per_rule = DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE
    return max_total, max_per_rule


def _findings_by_rule(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    grouped: dict[str, list[Finding]] = {}
    for item in findings:
        grouped.setdefault(item.rule_id, []).append(item)
    return [(rule_id, grouped[rule_id]) for rule_id in sorted(grouped)]


def _severity_counts(findings: list[Finding]) -> str:
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = len(findings) - errors
    parts = []
    if errors:
        parts.append(f"{errors} error")
    if warnings:
        parts.append(f"{warnings} warning")
    return ", ".join(parts) if parts else "0 findings"


def _policy_label(result: AnalysisResult) -> str:
    if not result.policy or not result.policy.get("source"):
        fail_on = result.policy.get("policy", {}).get("fail_on", []) if result.policy else []
        if fail_on:
            return "command-line override"
        return "default advisory"
    return f"loaded from {result.policy['source']}"


def _related_test_limit(result: AnalysisResult) -> int:
    if not result.policy:
        return 5
    related_tests = result.policy.get("related_tests")
    if not isinstance(related_tests, dict):
        return 5
    value = related_tests.get("max_candidates", 5)
    return value if isinstance(value, int) and value >= 0 else 5


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")
