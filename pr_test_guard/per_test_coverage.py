"""Normalized per-test coverage.py context evidence.

The parser owns the coverage JSON format so rules consume stable models rather
than reaching into a coverage.py artifact directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


PYTEST_CONTEXT = re.compile(
    r"^(?P<path>.+\.py)::(?P<node>.+)\|(?P<phase>setup|run|teardown)$"
)


class CoverageContextError(ValueError):
    """Raised when a context artifact cannot be read as coverage JSON."""


def normalize_coverage_path(value: str) -> str:
    """Normalize separators and harmless prefixes without guessing a root."""

    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def canonical_test_id(test_id: str) -> str:
    """Return the pytest collection node while retaining the original ID elsewhere."""

    path, separator, node = test_id.partition("::")
    if not separator:
        return test_id
    parts = node.split("::")
    # Parameter ids belong to a runtime context, but static analysis identifies
    # the source-level test node. Only the final pytest node is canonicalized.
    parts[-1] = re.sub(r"\[.*\]$", "", parts[-1])
    return f"{normalize_coverage_path(path)}::{'::'.join(parts)}"


@dataclass(frozen=True, slots=True)
class ParsedPytestContext:
    test_id: str
    canonical_test_id: str
    phase: str
    raw_context: str

    def to_dict(self) -> dict[str, str]:
        return {
            "test_id": self.test_id,
            "canonical_test_id": self.canonical_test_id,
            "phase": self.phase,
            "raw_context": self.raw_context,
        }


def parse_pytest_context(value: str) -> ParsedPytestContext | None:
    match = PYTEST_CONTEXT.fullmatch(value.strip())
    if not match:
        return None
    test_id = (
        f"{normalize_coverage_path(match.group('path'))}::"
        f"{match.group('node')}"
    )
    return ParsedPytestContext(
        test_id=test_id,
        canonical_test_id=canonical_test_id(test_id),
        phase=match.group("phase"),
        raw_context=value,
    )


@dataclass(frozen=True, slots=True)
class PerTestCoverage:
    file: str
    line: int
    contexts: tuple[ParsedPytestContext, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "contexts": [context.to_dict() for context in self.contexts],
        }


@dataclass(frozen=True, slots=True)
class TestExecutionEvidence:
    test_id: str
    canonical_test_id: str
    phase: str
    file: str
    lines: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "canonical_test_id": self.canonical_test_id,
            "phase": self.phase,
            "file": self.file,
            "lines": list(self.lines),
            "executed_changed_lines": list(self.lines),
        }


@dataclass(frozen=True, slots=True)
class CoverageFile:
    file: str
    executable_lines: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DynamicTestEvidence:
    """Per-change-unit dynamic evidence derived from a normalized report."""

    status: str
    reason: str | None
    coverage_file: str | None
    changed_executable_lines: tuple[int, ...]
    executing_tests: tuple[TestExecutionEvidence, ...]
    executed_changed_lines: tuple[int, ...]
    unexecuted_changed_lines: tuple[int, ...]
    execution_phases: tuple[str, ...]
    observed_related_tests: tuple[str, ...]
    nonexecuting_related_tests: tuple[str, ...]
    unobserved_related_tests: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "coverage_file": self.coverage_file,
            "changed_executable_lines": list(self.changed_executable_lines),
            "executing_tests": [item.to_dict() for item in self.executing_tests],
            "executed_changed_lines": list(self.executed_changed_lines),
            "unexecuted_changed_lines": list(self.unexecuted_changed_lines),
            "execution_phases": list(self.execution_phases),
            "observed_related_tests": list(self.observed_related_tests),
            "nonexecuting_related_tests": list(self.nonexecuting_related_tests),
            "unobserved_related_tests": list(self.unobserved_related_tests),
        }


@dataclass(frozen=True, slots=True)
class PerTestCoverageReport:
    files: tuple[CoverageFile, ...]
    lines: tuple[PerTestCoverage, ...]
    executions: tuple[TestExecutionEvidence, ...]
    unresolved_contexts: tuple[str, ...]
    issues: tuple[str, ...]

    def matching_file(self, repo_file: str) -> tuple[CoverageFile | None, str | None]:
        target = normalize_coverage_path(repo_file)
        exact = [
            item for item in self.files if normalize_coverage_path(item.file) == target
        ]
        if len(exact) == 1:
            return exact[0], None

        suffix = [
            item
            for item in self.files
            if normalize_coverage_path(item.file).endswith(f"/{target}")
            or target.endswith(f"/{normalize_coverage_path(item.file)}")
        ]
        if len(suffix) == 1:
            return suffix[0], None
        if len(exact) > 1 or len(suffix) > 1:
            return None, "coverage_path_is_ambiguous"
        return None, "coverage_path_not_mapped"

    def evidence_for(
        self,
        *,
        repo_file: str,
        changed_lines: tuple[int, ...],
        related_test_ids: tuple[str, ...],
    ) -> DynamicTestEvidence:
        coverage_file, mapping_issue = self.matching_file(repo_file)
        if coverage_file is None:
            return _inconclusive(mapping_issue or "coverage_path_not_mapped")

        executable = tuple(
            sorted(set(changed_lines).intersection(coverage_file.executable_lines))
        )
        if not executable:
            return _inconclusive(
                "changed_lines_not_mapped_to_executable_coverage_lines",
                coverage_file=coverage_file.file,
            )

        file_executions = [
            item for item in self.executions if item.file == coverage_file.file
        ]
        executing: list[TestExecutionEvidence] = []
        for item in file_executions:
            overlap = tuple(sorted(set(item.lines).intersection(executable)))
            if overlap:
                executing.append(
                    TestExecutionEvidence(
                        test_id=item.test_id,
                        canonical_test_id=item.canonical_test_id,
                        phase=item.phase,
                        file=item.file,
                        lines=overlap,
                    )
                )

        normalized_related = tuple(canonical_test_id(item) for item in related_test_ids)
        observed: set[str] = set()
        nonexecuting: set[str] = set()
        unobserved: set[str] = set()
        all_executions_by_canonical: dict[str, set[str]] = {}
        for item in self.executions:
            all_executions_by_canonical.setdefault(item.canonical_test_id, set()).add(
                item.test_id
            )
        executing_ids = {item.test_id for item in executing}
        for original, canonical in zip(related_test_ids, normalized_related, strict=True):
            runtime_ids = all_executions_by_canonical.get(canonical, set())
            if not runtime_ids:
                unobserved.add(original)
                continue
            observed.update(runtime_ids)
            nonexecuting.update(runtime_ids - executing_ids)

        executed_lines = tuple(sorted({line for item in executing for line in item.lines}))
        status = "observed"
        reason: str | None = None
        if self.issues:
            status = "inconclusive"
            reason = "coverage_context_artifact_has_invalid_entries"
        elif self.unresolved_contexts:
            status = "inconclusive"
            reason = "coverage_context_format_unresolved"
        elif unobserved:
            status = "inconclusive"
            reason = "related_test_not_observed_in_coverage_contexts"

        return DynamicTestEvidence(
            status=status,
            reason=reason,
            coverage_file=coverage_file.file,
            changed_executable_lines=executable,
            executing_tests=tuple(
                sorted(executing, key=lambda item: (item.test_id, item.phase, item.file))
            ),
            executed_changed_lines=executed_lines,
            unexecuted_changed_lines=tuple(sorted(set(executable) - set(executed_lines))),
            execution_phases=tuple(sorted({item.phase for item in executing})),
            observed_related_tests=tuple(sorted(observed)),
            nonexecuting_related_tests=tuple(sorted(nonexecuting)),
            unobserved_related_tests=tuple(sorted(unobserved)),
        )


def _inconclusive(
    reason: str,
    *,
    coverage_file: str | None = None,
) -> DynamicTestEvidence:
    return DynamicTestEvidence(
        status="inconclusive",
        reason=reason,
        coverage_file=coverage_file,
        changed_executable_lines=(),
        executing_tests=(),
        executed_changed_lines=(),
        unexecuted_changed_lines=(),
        execution_phases=(),
        observed_related_tests=(),
        nonexecuting_related_tests=(),
        unobserved_related_tests=(),
    )


def parse_coverage_contexts(path: Path) -> PerTestCoverageReport:
    """Parse ``coverage json --show-contexts`` output into normalized evidence."""

    if not path.is_file():
        raise CoverageContextError(f"coverage contexts file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageContextError(
            f"coverage contexts JSON is malformed: {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise CoverageContextError(
            f"coverage contexts JSON must contain a 'files' object: {path}"
        )

    issues: list[str] = []
    meta = payload.get("meta")
    if not isinstance(meta, dict) or meta.get("show_contexts") is not True:
        issues.append("meta.show_contexts_is_not_true")

    files: list[CoverageFile] = []
    coverage_lines: list[PerTestCoverage] = []
    unresolved: set[str] = set()
    grouped: dict[tuple[str, str, str, str], set[int]] = {}

    for raw_file, raw_data in payload["files"].items():
        if not isinstance(raw_file, str) or not isinstance(raw_data, dict):
            issues.append("invalid_file_entry")
            continue
        file_name = normalize_coverage_path(raw_file)
        executed = _integer_lines(raw_data.get("executed_lines"), issues, file_name)
        missing = _integer_lines(raw_data.get("missing_lines"), issues, file_name)
        files.append(
            CoverageFile(
                file=file_name,
                executable_lines=tuple(sorted(executed | missing)),
            )
        )
        raw_contexts = raw_data.get("contexts")
        if not isinstance(raw_contexts, dict):
            issues.append(f"{file_name}:missing_or_invalid_contexts")
            continue
        for raw_line, raw_values in raw_contexts.items():
            try:
                line = int(raw_line)
            except (TypeError, ValueError):
                issues.append(f"{file_name}:invalid_context_line")
                continue
            if not isinstance(raw_values, list) or not all(
                isinstance(value, str) for value in raw_values
            ):
                issues.append(f"{file_name}:{line}:invalid_context_list")
                continue
            parsed_contexts: list[ParsedPytestContext] = []
            for raw_context in raw_values:
                # coverage.py uses the empty context for import/module work
                # outside a pytest test phase. It is a known non-test context,
                # not an unresolved pytest identifier.
                if not raw_context:
                    continue
                parsed = parse_pytest_context(raw_context)
                if parsed is None:
                    unresolved.add(raw_context)
                    continue
                parsed_contexts.append(parsed)
                key = (
                    parsed.test_id,
                    parsed.canonical_test_id,
                    parsed.phase,
                    file_name,
                )
                grouped.setdefault(key, set()).add(line)
            coverage_lines.append(
                PerTestCoverage(
                    file=file_name,
                    line=line,
                    contexts=tuple(parsed_contexts),
                )
            )

    executions = tuple(
        TestExecutionEvidence(
            test_id=key[0],
            canonical_test_id=key[1],
            phase=key[2],
            file=key[3],
            lines=tuple(sorted(lines)),
        )
        for key, lines in sorted(grouped.items())
    )
    return PerTestCoverageReport(
        files=tuple(sorted(files, key=lambda item: item.file)),
        lines=tuple(sorted(coverage_lines, key=lambda item: (item.file, item.line))),
        executions=executions,
        unresolved_contexts=tuple(sorted(unresolved)),
        issues=tuple(sorted(set(issues))),
    )


def _integer_lines(value: Any, issues: list[str], file_name: str) -> set[int]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        issues.append(f"{file_name}:invalid_executable_line_data")
        return set()
    return set(value)
