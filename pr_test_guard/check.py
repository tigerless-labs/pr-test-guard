"""Repository-native pull-request analysis for PR Test Guard."""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .finding import Finding
from .mock_analysis import (
    MockRelation,
    classify_dependency_relation,
    collect_changed_dependency_calls,
    collect_changed_symbols,
    extract_mock_targets,
    match_mock_target,
)


PROBE_REPLACEMENTS: tuple[tuple[str, str, str], ...] = (
    ("return 400", "return 200", "weaken HTTP 400 return to success"),
    ("return 401", "return 200", "weaken HTTP 401 return to success"),
    ("return 403", "return 200", "weaken HTTP 403 return to success"),
    ("return 404", "return 200", "weaken HTTP 404 return to success"),
    ("return 409", "return 200", "weaken HTTP 409 return to success"),
    ("return 422", "return 200", "weaken HTTP 422 return to success"),
    ("return 500", "return 200", "weaken HTTP 500 return to success"),
    ("return False", "return True", "flip false return"),
    ("return True", "return False", "flip true return"),
    (" <= ", " < ", "weaken inclusive upper-bound comparison"),
    (" >= ", " > ", "weaken inclusive lower-bound comparison"),
    (" == ", " != ", "flip equality comparison"),
)


class CheckError(RuntimeError):
    """Raised when a repository cannot be analyzed safely or consistently."""


@dataclass(slots=True)
class FileDiff:
    path: str
    status: str = "M"
    added: list[tuple[int, str]] | None = None
    removed: list[tuple[int, str]] | None = None

    def __post_init__(self) -> None:
        if self.added is None:
            self.added = []
        if self.removed is None:
            self.removed = []


@dataclass(slots=True)
class AnalysisResult:
    repo_root: Path
    base: str
    head: str
    files: list[FileDiff]
    findings: list[Finding]
    notes: list[str]
    probe_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "head": self.head,
            "summary": {
                "changed_files": len(self.files),
                "production_files": sum(1 for item in self.files if is_python_path(item.path) and not is_test_path(item.path)),
                "test_files": sum(1 for item in self.files if is_test_path(item.path)),
                "findings": len(self.findings),
                "notes": len(self.notes),
            },
            "findings": [item.to_dict() for item in self.findings],
            "notes": self.notes,
            "probes": self.probe_summary,
        }


def run_command(
    command: list[str],
    cwd: Path,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        rendered = " ".join(shlex.quote(part) for part in command)
        detail = (result.stderr or result.stdout).strip()
        raise CheckError(f"command failed ({rendered}): {detail}")
    return result


def repository_root(cwd: Path) -> Path:
    result = run_command(["git", "rev-parse", "--show-toplevel"], cwd)
    if result.returncode != 0:
        raise CheckError("current directory is not inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def resolve_commit(repo_root: Path, ref: str) -> str:
    result = run_command(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], repo_root)
    if result.returncode != 0:
        raise CheckError(f"base ref does not resolve to a commit: {ref}")
    return result.stdout.strip()


def is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    filename = parts[-1]
    return (
        "tests" in parts
        or "test" in parts[:-1]
        or filename.startswith("test_")
        or filename.endswith("_test.py")
    )


def is_python_path(path: str) -> bool:
    return path.endswith(".py")


def parse_name_status(repo_root: Path, base: str) -> dict[str, str]:
    result = run_command(
        ["git", "diff", "--name-status", "-M", f"{base}...HEAD", "--"],
        repo_root,
        check=True,
    )
    statuses: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        code = parts[0]
        if code.startswith("R") and len(parts) >= 3:
            statuses[parts[2]] = code
        elif len(parts) >= 2:
            statuses[parts[1]] = code
    return statuses


def parse_diff(repo_root: Path, base: str) -> list[FileDiff]:
    result = run_command(
        ["git", "diff", "--unified=0", "--no-ext-diff", "--find-renames", f"{base}...HEAD", "--"],
        repo_root,
        check=True,
    )
    statuses = parse_name_status(repo_root, base)
    files: dict[str, FileDiff] = {}
    current: FileDiff | None = None
    old_line: int | None = None
    new_line: int | None = None

    for raw_line in result.stdout.splitlines():
        match = re.match(r"^diff --git a/(.*?) b/(.*?)$", raw_line)
        if match:
            path = match.group(2)
            current = files.setdefault(path, FileDiff(path=path, status=statuses.get(path, "M")))
            old_line = None
            new_line = None
            continue

        hunk = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
        if hunk:
            old_line = int(hunk.group(1))
            new_line = int(hunk.group(2))
            continue

        if current is None or old_line is None or new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current.added.append((new_line, raw_line[1:]))
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            current.removed.append((old_line, raw_line[1:]))
            old_line += 1
        else:
            old_line += 1
            new_line += 1

    for path, status in statuses.items():
        files.setdefault(path, FileDiff(path=path, status=status))

    return sorted(files.values(), key=lambda item: item.path)


def changed_code_lines(files: list[FileDiff]) -> dict[str, list[dict[str, Any]]]:
    changed: dict[str, list[dict[str, Any]]] = {}
    for item in files:
        if is_test_path(item.path) or not is_python_path(item.path):
            continue
        lines = []
        for line, content in item.added:
            stripped = content.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append({"line": line, "content": content})
        if lines:
            changed[item.path] = lines
    return changed


def source_for_node(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


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
    if isinstance(test, ast.Attribute):
        return "truthiness_check"
    return type(test).__name__


def weak_assertion_findings(repo_root: Path, files: list[FileDiff]) -> list[Finding]:
    findings: list[Finding] = []
    for diff in files:
        if not is_test_path(diff.path) or not diff.path.endswith(".py"):
            continue
        path = repo_root / diff.path
        if not path.is_file():
            continue
        added_lines = {line for line, _ in diff.added}
        if not added_lines:
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert) or node.lineno not in added_lines:
                continue
            shape = classify_assertion(node)
            if shape not in {"existence_or_none_check", "truthiness_check", "call_truthiness_check"}:
                continue
            evidence = source_for_node(source, node)
            findings.append(
                Finding(
                    rule_id="PTG003",
                    severity="warning",
                    file=diff.path,
                    line=node.lineno,
                    message="Possible weak assertion; review whether it constrains the behavior changed by this PR.",
                    evidence=evidence,
                )
            )
    return findings


def missing_test_change_findings(files: list[FileDiff]) -> list[Finding]:
    production = [item for item in files if not is_test_path(item.path) and is_python_path(item.path)]
    test_changes = [item for item in files if is_test_path(item.path)]
    if not production or test_changes:
        return []
    first = production[0]
    return [
        Finding(
            rule_id="PTG001",
            severity="warning",
            file=first.path,
            line=first.added[0][0] if first.added else None,
            message="Production code changed, but this PR contains no test-file change. Existing tests may still cover it; review whether extra test evidence is needed.",
            evidence=f"{len(production)} production file(s) changed; 0 test files changed",
        )
    ]


def test_weakening_findings(repo_root: Path, files: list[FileDiff]) -> list[Finding]:
    findings: list[Finding] = []
    skip_names = {
        "pytest.mark.skip",
        "pytest.mark.skipif",
        "pytest.mark.xfail",
        "pytest.skip",
        "unittest.skip",
        "unittest.expectedFailure",
    }
    for diff in files:
        if not is_test_path(diff.path):
            continue
        if diff.status.startswith("D"):
            findings.append(
                Finding(
                    rule_id="PTG004",
                    severity="warning",
                    file=diff.path,
                    line=None,
                    message="A test file was deleted in this PR; review whether validation scope was intentionally reduced.",
                    evidence="deleted test file",
                )
            )
            continue

        path = repo_root / diff.path
        added_lines = {line for line, _ in diff.added}
        if path.is_file() and path.suffix == ".py" and added_lines:
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError):
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and node.lineno in added_lines:
                        name = call_name(node)
                        if name in skip_names:
                            findings.append(
                                Finding(
                                    rule_id="PTG004",
                                    severity="warning",
                                    file=diff.path,
                                    line=node.lineno,
                                    message="Test skip/xfail behavior was added; review whether the PR weakens validation scope.",
                                    evidence=source_for_node(source, node),
                                )
                            )
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for decorator in node.decorator_list:
                            name = call_name(decorator) if isinstance(decorator, ast.Call) else dotted_name(decorator)
                            line = getattr(decorator, "lineno", None)
                            if line in added_lines and name in skip_names:
                                findings.append(
                                    Finding(
                                        rule_id="PTG004",
                                        severity="warning",
                                        file=diff.path,
                                        line=line,
                                        message="Test skip/xfail behavior was added; review whether the PR weakens validation scope.",
                                        evidence=source_for_node(source, decorator),
                                    )
                                )

        removed_asserts = [content.strip() for _, content in diff.removed if content.strip().startswith("assert ")]
        added_asserts = [content.strip() for _, content in diff.added if content.strip().startswith("assert ")]
        if len(removed_asserts) > len(added_asserts):
            findings.append(
                Finding(
                    rule_id="PTG004",
                    severity="warning",
                    file=diff.path,
                    line=diff.added[0][0] if diff.added else None,
                    message="Assertions were removed without an equal number of replacement assertions; review whether the test became weaker.",
                    evidence=f"removed assertions={len(removed_asserts)}, added assertions={len(added_asserts)}",
                )
            )
    return findings


def parse_coverage_xml(path: Path) -> dict[str, dict[int, int]]:
    if not path.is_file():
        raise CheckError(f"coverage file not found: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise CheckError(f"coverage XML is malformed: {path}: {exc}") from exc
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


def coverage_hits(coverage: dict[str, dict[int, int]], file_path: str, line: int) -> int | None:
    for candidate in (file_path, f"./{file_path}"):
        if candidate in coverage:
            return coverage[candidate].get(line)
    for filename, lines in coverage.items():
        if filename.endswith(file_path):
            return lines.get(line)
    return None


def uncovered_line_findings(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
    coverage_path: str | None,
    notes: list[str],
) -> list[Finding]:
    if not coverage_path:
        notes.append("PTG002 skipped: no coverage XML was provided.")
        return []
    path = Path(coverage_path)
    if not path.is_absolute():
        path = repo_root / path
    coverage = parse_coverage_xml(path)
    findings: list[Finding] = []
    for file_path, lines in changed.items():
        for item in lines:
            hits = coverage_hits(coverage, file_path, item["line"])
            if hits is None:
                continue
            if hits == 0:
                findings.append(
                    Finding(
                        rule_id="PTG002",
                        severity="warning",
                        file=file_path,
                        line=item["line"],
                        message="Changed executable line is not covered by the supplied coverage report.",
                        evidence=item["content"].strip(),
                    )
                )
    return findings


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def call_name(node: ast.AST) -> str | None:
    return dotted_name(node.func) if isinstance(node, ast.Call) else None


def tracked_python_files(repo_root: Path) -> list[str]:
    result = run_command(["git", "ls-files", "*.py"], repo_root, check=True)
    return [line for line in result.stdout.splitlines() if line]


def tracked_test_files(repo_root: Path) -> list[str]:
    return [line for line in tracked_python_files(repo_root) if is_test_path(line)]


def mock_boundary_findings(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
    files: list[FileDiff],
    notes: list[str],
) -> list[Finding]:
    symbols = collect_changed_symbols(repo_root, changed)
    if not symbols:
        return []

    python_files = tracked_python_files(repo_root)
    production_python_files = [path for path in python_files if not is_test_path(path)]
    dependencies = collect_changed_dependency_calls(
        repo_root,
        changed,
        symbols,
        tracked_python_paths=production_python_files,
    )
    changed_test_files = {item.path for item in files if is_test_path(item.path) and item.status != "D"}

    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    suppressed_external = 0

    for rel_path in (line for line in python_files if is_test_path(line)):
        path = repo_root / rel_path
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for target in extract_mock_targets(source, tree, rel_path):
            key = (rel_path, target.line, target.raw_target)
            if key in seen:
                continue

            direct_matches = match_mock_target(target, symbols)
            if direct_matches:
                seen.add(key)
                changed_names = ", ".join(sorted({item.symbol.canonical_name for item in direct_matches}))
                match_kinds = ", ".join(sorted({item.kind.value for item in direct_matches}))
                resolved = target.resolved_target or "unresolved"
                findings.append(
                    Finding(
                        rule_id="PTG005",
                        severity="warning",
                        file=rel_path,
                        line=target.line,
                        message=(
                            "A mock directly replaces a Python symbol changed by this PR; "
                            "review whether the real changed behavior is still exercised."
                        ),
                        evidence=(
                            f"relation={MockRelation.DIRECT_CHANGED_SYMBOL.value}; "
                            f"{target.style} target={target.raw_target}; resolved={resolved}; "
                            f"match={match_kinds}; changed symbol(s)={changed_names}"
                        ),
                    )
                )
                continue

            # Relationship expansion is deliberately narrower than direct symbol
            # matching: only mocks in tests changed by this PR are considered,
            # and only dependencies called on changed production lines qualify.
            # This prevents v2 from surfacing a backlog of old mocks in untouched
            # tests just because a production function changed.
            if rel_path not in changed_test_files:
                continue

            relationship = classify_dependency_relation(target, dependencies)
            if relationship.relation == MockRelation.EXTERNAL_BOUNDARY:
                suppressed_external += 1
                seen.add(key)
                continue
            if relationship.relation != MockRelation.DIRECT_INTERNAL_DEPENDENCY:
                continue

            dependency = relationship.dependency
            owner = relationship.changed_symbol
            if dependency is None or owner is None:
                continue
            seen.add(key)
            resolved = target.resolved_target or "unresolved"
            dependency_targets = ", ".join(dependency.candidate_targets)
            findings.append(
                Finding(
                    rule_id="PTG005",
                    severity="warning",
                    file=rel_path,
                    line=target.line,
                    message=(
                        "A changed test mocks an internal dependency called on a line changed by this PR; "
                        "review whether the changed behavior is still exercised."
                    ),
                    evidence=(
                        f"relation={MockRelation.DIRECT_INTERNAL_DEPENDENCY.value}; "
                        f"{target.style} target={target.raw_target}; resolved={resolved}; "
                        f"changed symbol={owner.canonical_name}; changed call line={dependency.line}; "
                        f"dependency target(s)={dependency_targets}"
                    ),
                )
            )

    if suppressed_external:
        notes.append(
            "PTG005: suppressed "
            f"{suppressed_external} external-boundary mock candidate(s) on changed call sites."
        )
    return findings

def generate_probes(
    changed: dict[str, list[dict[str, Any]]],
    max_probes: int,
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for rel_path, lines in changed.items():
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


def run_shell(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True)


def targeted_probe_findings(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
    *,
    deep: bool,
    test_command: str | None,
    max_probes: int,
    notes: list[str],
) -> tuple[list[Finding], dict[str, Any]]:
    empty_summary = {"enabled": deep, "generated": 0, "applied": 0, "survived": 0, "baseline_passed": None}
    if not deep:
        notes.append("PTG006 skipped: deep targeted probes are opt-in (--deep).")
        return [], empty_summary
    if not test_command:
        raise CheckError("--deep requires --test-command so PR Test Guard knows how to rerun the repository tests")

    probes = generate_probes(changed, max_probes=max(1, max_probes))
    summary = {**empty_summary, "generated": len(probes)}
    if not probes:
        notes.append("PTG006: no supported targeted probe candidate was found in the changed Python lines.")
        return [], summary

    findings: list[Finding] = []
    with tempfile.TemporaryDirectory(prefix="pr-test-guard-worktree-") as temp_dir:
        worktree = Path(temp_dir)
        add_result = run_command(["git", "worktree", "add", "--detach", str(worktree), "HEAD"], repo_root)
        if add_result.returncode != 0:
            detail = (add_result.stderr or add_result.stdout).strip()
            raise CheckError(f"failed to create isolated probe worktree: {detail}")
        try:
            baseline = run_shell(test_command, worktree)
            summary["baseline_passed"] = baseline.returncode == 0
            if baseline.returncode != 0:
                notes.append("PTG006 skipped: the configured test command fails on the unmodified PR checkout.")
                return [], summary

            for probe in probes:
                path = worktree / probe["file"]
                if not path.is_file():
                    continue
                original_text = path.read_text(encoding="utf-8")
                lines = original_text.splitlines(keepends=True)
                index = probe["line"] - 1
                if index < 0 or index >= len(lines) or probe["original"] not in lines[index]:
                    continue
                lines[index] = lines[index].replace(probe["original"], probe["replacement"], 1)
                path.write_text("".join(lines), encoding="utf-8")
                summary["applied"] += 1
                result = run_shell(test_command, worktree)
                path.write_text(original_text, encoding="utf-8")
                if result.returncode == 0:
                    summary["survived"] += 1
                    findings.append(
                        Finding(
                            rule_id="PTG006",
                            severity="warning",
                            file=probe["file"],
                            line=probe["line"],
                            message="A bounded targeted probe survived the configured tests; the tests may be insensitive to this changed behavior.",
                            evidence=f"{probe['original'].strip()} -> {probe['replacement'].strip()} ({probe['rationale']})",
                        )
                    )
        finally:
            run_command(["git", "worktree", "remove", "--force", str(worktree)], repo_root)
            run_command(["git", "worktree", "prune"], repo_root)

    return findings, summary


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str | None, int | None, str]] = set()
    unique: list[Finding] = []
    for item in findings:
        key = (item.rule_id, item.file, item.line, item.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return sorted(unique, key=lambda item: (item.rule_id, item.file or "", item.line or 0, item.message))


def analyze_repository(
    cwd: Path,
    *,
    base: str,
    coverage_path: str | None = None,
    deep: bool = False,
    test_command: str | None = None,
    max_probes: int = 3,
) -> AnalysisResult:
    repo_root = repository_root(cwd)
    resolve_commit(repo_root, base)
    head = resolve_commit(repo_root, "HEAD")
    files = parse_diff(repo_root, base)
    changed = changed_code_lines(files)
    notes: list[str] = []

    findings: list[Finding] = []
    findings.extend(missing_test_change_findings(files))
    findings.extend(uncovered_line_findings(repo_root, changed, coverage_path, notes))
    findings.extend(weak_assertion_findings(repo_root, files))
    findings.extend(test_weakening_findings(repo_root, files))
    findings.extend(mock_boundary_findings(repo_root, changed, files, notes))
    probe_findings, probe_summary = targeted_probe_findings(
        repo_root,
        changed,
        deep=deep,
        test_command=test_command,
        max_probes=max_probes,
        notes=notes,
    )
    findings.extend(probe_findings)

    if not files:
        notes.append(f"No changes found between {base} and HEAD.")
    elif not changed:
        notes.append("No changed Python production lines were found; Python-specific coverage/mock/probe rules may be quiet.")

    return AnalysisResult(
        repo_root=repo_root,
        base=base,
        head=head,
        files=files,
        findings=dedupe_findings(findings),
        notes=notes,
        probe_summary=probe_summary,
    )


def default_base() -> str:
    github_base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base:
        return f"origin/{github_base}"
    return "origin/main"
