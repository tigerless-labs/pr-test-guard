"""Generate function-scoped probes that restore behavior from the base commit."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .change_evidence import ChangeUnit


@dataclass(frozen=True, slots=True)
class RollbackProbe:
    id: str
    file: str
    symbol: str
    start_line: int
    end_line: int
    current_source: str
    base_source: str
    confirmed_tests: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "current_source": self.current_source,
            "base_source": self.base_source,
            "confirmed_tests": list(self.confirmed_tests),
        }


@dataclass(frozen=True, slots=True)
class _FunctionSource:
    qualname: str
    start_line: int
    end_line: int
    signature: str
    source: str


def _functions(source: str) -> dict[str, _FunctionSource]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines(keepends=True)
    found: dict[str, _FunctionSource] = {}
    scope: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qualname = ".".join([*scope, node.name])
            start = int(node.lineno)
            end = int(getattr(node, "end_lineno", start))
            found[qualname] = _FunctionSource(
                qualname=qualname,
                start_line=start,
                end_line=end,
                signature=ast.dump(node.args, include_attributes=False),
                source="".join(lines[start - 1 : end]),
            )
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

    Visitor().visit(tree)
    return found


def _base_source(repo_root: Path, base: str, rel_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base}:{rel_path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def generate_rollback_probes(
    repo_root: Path,
    base: str,
    change_units: list[ChangeUnit],
    *,
    max_probes: int,
) -> tuple[list[dict[str, Any]], int]:
    """Restore compatible changed functions while retaining the PR's tests.

    Functions with changed signatures are excluded because collection or call
    failures would measure interface incompatibility rather than test
    sensitivity to the changed behavior.
    """

    probes: list[RollbackProbe] = []
    skipped_unconfirmed = 0
    by_file: dict[str, list[ChangeUnit]] = {}
    for unit in change_units:
        by_file.setdefault(unit.file, []).append(unit)

    for rel_path in sorted(by_file):
        path = repo_root / rel_path
        try:
            current_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        base_text = _base_source(repo_root, base, rel_path)
        if base_text is None:
            continue
        current_functions = _functions(current_text)
        base_functions = _functions(base_text)
        for unit in sorted(by_file[rel_path], key=lambda item: (item.line, item.symbol)):
            if not unit.directly_exercising_tests:
                skipped_unconfirmed += 1
                continue
            qualname = unit.symbol.rsplit(".", 1)[-1]
            # Prefer the longest suffix so class methods retain their owner.
            matches = [name for name in current_functions if unit.symbol.endswith(name)]
            if matches:
                qualname = max(matches, key=len)
            current = current_functions.get(qualname)
            previous = base_functions.get(qualname)
            if current is None or previous is None:
                continue
            if current.signature != previous.signature or current.source == previous.source:
                continue
            probes.append(
                RollbackProbe(
                    id=f"R{len(probes) + 1}",
                    file=rel_path,
                    symbol=unit.symbol,
                    start_line=current.start_line,
                    end_line=current.end_line,
                    current_source=current.source,
                    base_source=previous.source,
                    confirmed_tests=unit.directly_exercising_tests,
                )
            )
            if len(probes) >= max(1, max_probes):
                return [probe.to_dict() for probe in probes], skipped_unconfirmed
    return [probe.to_dict() for probe in probes], skipped_unconfirmed
