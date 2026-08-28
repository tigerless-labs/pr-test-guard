"""Policy application for PR Test Guard findings."""

from __future__ import annotations

from dataclasses import replace
from fnmatch import fnmatch

from .check import AnalysisResult
from .config import GuardConfig
from .finding import Finding


def apply_config(result: AnalysisResult, config: GuardConfig) -> AnalysisResult:
    findings: list[Finding] = []
    suppressed_off: dict[str, int] = {}
    suppressed_paths = 0

    for finding in result.findings:
        if _ignored_path(finding.file, config.ignore_paths):
            suppressed_paths += 1
            continue

        action = config.action_for(finding.rule_id)
        if action == "off":
            suppressed_off[finding.rule_id] = suppressed_off.get(finding.rule_id, 0) + 1
            continue

        severity = "error" if action == "error" else "warning"
        findings.append(replace(finding, severity=severity))

    notes = list(result.notes)
    if suppressed_paths:
        notes.append(f"Policy: suppressed {suppressed_paths} finding(s) matching paths.ignore.")
    for rule_id, count in sorted(suppressed_off.items()):
        notes.append(f"Policy: suppressed {count} {rule_id} finding(s) because the rule is off.")

    error_rules = sorted({item.rule_id for item in findings if item.severity == "error"})
    if error_rules:
        notes.append(f"Policy: error rule(s) triggered: {', '.join(error_rules)}.")

    return replace(
        result,
        findings=findings,
        notes=notes,
        policy=config.to_dict(),
    )


def exit_code_for(result: AnalysisResult) -> int:
    return 1 if any(item.severity == "error" for item in result.findings) else 0


def _ignored_path(path: str | None, patterns: tuple[str, ...]) -> bool:
    if not path:
        return False
    normalized = path.replace("\\", "/")
    return any(fnmatch(normalized, pattern) for pattern in patterns)
