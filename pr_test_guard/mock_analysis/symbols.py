"""Lightweight Python symbol resolution for mock-boundary analysis."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class PythonSymbol:
    """A Python symbol changed by the current PR."""

    file: str
    module: str
    qualname: str
    name: str
    line: int

    @property
    def canonical_name(self) -> str:
        return f"{self.module}.{self.qualname}" if self.module else self.qualname


def module_name_from_path(rel_path: str) -> str:
    """Convert a repository-relative Python path to its common import name.

    The resolver intentionally handles only deterministic layout conventions.
    In particular, ``src/foo/bar.py`` maps to ``foo.bar`` rather than
    ``src.foo.bar``.  Projects with custom import hooks remain unresolved
    rather than being guessed.
    """

    path = PurePosixPath(rel_path.replace("\\", "/"))
    parts = list(path.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if not parts or not parts[-1].endswith(".py"):
        return ""
    stem = parts[-1][:-3]
    parts[-1] = stem
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(part for part in parts if part)


class _ChangedSymbolCollector(ast.NodeVisitor):
    def __init__(self, module: str, rel_path: str, changed_lines: set[int]) -> None:
        self.module = module
        self.rel_path = rel_path
        self.changed_lines = changed_lines
        self.scope: list[str] = []
        self.symbols: list[PythonSymbol] = []

    @staticmethod
    def _nested_symbol_spans(node: ast.AST) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []

        def walk(current: ast.AST) -> None:
            for child in ast.iter_child_nodes(current):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = getattr(child, "lineno", None)
                    end = getattr(child, "end_lineno", start)
                    if start is not None and end is not None:
                        spans.append((int(start), int(end)))
                    # The whole nested definition belongs to the nested symbol,
                    # so there is no need to collect deeper spans here.
                    continue
                walk(child)

        walk(node)
        return spans

    def _visit_symbol(self, node: ast.AST, name: str) -> None:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        changed_here = False
        if start is not None and end is not None:
            nested_spans = self._nested_symbol_spans(node)
            for line in self.changed_lines:
                if not (start <= line <= end):
                    continue
                if any(nested_start <= line <= nested_end for nested_start, nested_end in nested_spans):
                    continue
                changed_here = True
                break
        if changed_here:
            qualname = ".".join([*self.scope, name])
            self.symbols.append(
                PythonSymbol(
                    file=self.rel_path,
                    module=self.module,
                    qualname=qualname,
                    name=name,
                    line=start,
                )
            )
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast visitor API
        self._visit_symbol(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast visitor API
        self._visit_symbol(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802 - ast visitor API
        self._visit_symbol(node, node.name)


def collect_changed_symbols(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
) -> list[PythonSymbol]:
    """Collect changed classes/functions with lexical qualified names."""

    symbols: list[PythonSymbol] = []
    for rel_path, line_items in changed.items():
        path = repo_root / rel_path
        if not path.is_file() or path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        changed_lines = {int(item["line"]) for item in line_items}
        collector = _ChangedSymbolCollector(module_name_from_path(rel_path), rel_path, changed_lines)
        collector.visit(tree)
        symbols.extend(collector.symbols)
    return symbols
