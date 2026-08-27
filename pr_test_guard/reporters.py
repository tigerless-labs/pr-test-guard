"""Human, JSON, and GitHub Actions output for PR Test Guard."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .check import AnalysisResult
from .finding import Finding


def _location(item: Finding) -> str:
    if item.file and item.line:
        return f"{item.file}:{item.line}"
    if item.file:
        return item.file
    return "repository"


def render_text(result: AnalysisResult) -> str:
    production = sum(1 for item in result.files if item.path.endswith(".py") and not _is_test_path_for_report(item.path))
    tests = sum(1 for item in result.files if _is_test_path_for_report(item.path))
    lines = [
        "PR Test Guard",
        "─────────────",
        f"Base: {result.base}",
        f"Changed files: {len(result.files)} ({production} Python production, {tests} test)",
        f"Related test candidates: {len(result.related_tests)}",
        "",
    ]
    if result.findings:
        lines.append(f"{len(result.findings)} review signal(s)")
        lines.append("")
        for item in result.findings:
            lines.append(f"⚠ {item.rule_id} {_location(item)}")
            lines.append(f"  {item.message}")
            if item.evidence:
                lines.append(f"  Evidence: {item.evidence}")
            lines.append("")
    else:
        lines.extend(["No review signals found by the enabled rules.", ""])

    if result.notes:
        lines.append("Notes")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("Result: advisory — findings do not block merge by default.")
    return "\n".join(lines).rstrip() + "\n"


def render_json(result: AnalysisResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def _escape_workflow_value(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _annotation(item: Finding) -> str:
    attrs = []
    if item.file:
        attrs.append(f"file={_escape_workflow_value(item.file)}")
    if item.line:
        attrs.append(f"line={item.line}")
    metadata = f" {','.join(attrs)}" if attrs else ""
    message = f"[{item.rule_id}] {item.message}"
    if item.evidence:
        message += f" Evidence: {item.evidence}"
    return f"::warning{metadata}::{_escape_workflow_value(message)}"


def github_summary(result: AnalysisResult) -> str:
    lines = [
        "## PR Test Guard",
        "",
        f"**{len(result.findings)} review signal(s)** found between `{result.base}` and `HEAD`.",
        f"**{len(result.related_tests)} related test candidate(s)** identified from deterministic import/call/name context.",
        "",
    ]
    if result.findings:
        lines.extend(["| Rule | Location | Signal |", "| --- | --- | --- |"])
        for item in result.findings:
            lines.append(f"| `{item.rule_id}` | `{_location(item)}` | {item.message} |")
        lines.append("")
    else:
        lines.extend(["No review signals found by the enabled rules.", ""])
    if result.notes:
        lines.append("### Notes")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append("_Advisory by default: findings do not fail the job unless a repository adds its own enforcement policy._")
    return "\n".join(lines) + "\n"


def emit_github(result: AnalysisResult) -> str:
    output_lines = [_annotation(item) for item in result.findings]
    output_lines.append(f"PR Test Guard: {len(result.findings)} review signal(s); advisory result.")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).open("a", encoding="utf-8").write(github_summary(result))
    return "\n".join(output_lines) + "\n"


def _is_test_path_for_report(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    filename = parts[-1]
    return "tests" in parts or "test" in parts[:-1] or filename.startswith("test_") or filename.endswith("_test.py")
