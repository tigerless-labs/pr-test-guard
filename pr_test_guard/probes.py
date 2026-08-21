"""AST-scoped targeted probe generation for PTG006."""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STATUS_CODE_REPLACEMENTS: dict[int, tuple[int, str]] = {
    400: (200, "weaken HTTP 400 return to success"),
    401: (200, "weaken HTTP 401 return to success"),
    403: (200, "weaken HTTP 403 return to success"),
    404: (200, "weaken HTTP 404 return to success"),
    409: (200, "weaken HTTP 409 return to success"),
    422: (200, "weaken HTTP 422 return to success"),
    500: (200, "weaken HTTP 500 return to success"),
}

COMPARE_OPERATOR_REPLACEMENTS: dict[type[ast.cmpop], tuple[str, str]] = {
    ast.LtE: ("<", "weaken inclusive upper-bound comparison"),
    ast.GtE: (">", "weaken inclusive lower-bound comparison"),
    ast.Eq: ("!=", "flip equality comparison"),
    ast.NotEq: ("==", "flip inequality comparison"),
}


@dataclass(frozen=True, slots=True)
class ProbeCandidate:
    id: str
    file: str
    line: int
    original: str
    replacement: str
    rationale: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "line": self.line,
            "original": self.original,
            "replacement": self.replacement,
            "rationale": self.rationale,
            "kind": self.kind,
        }


def _source_for_node(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


def _node_span(node: ast.AST) -> tuple[int, int] | None:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", start)
    if start is None or end is None:
        return None
    return int(start), int(end)


def _intersects_changed_lines(node: ast.AST, changed_lines: set[int]) -> bool:
    span = _node_span(node)
    if span is None:
        return False
    start, end = span
    return any(start <= line <= end for line in changed_lines)


def _single_line(segment: str) -> bool:
    return bool(segment) and "\n" not in segment and "\r" not in segment


def _replace_single_line_segment(segment: str, old: str, new: str) -> str | None:
    if not _single_line(segment) or old not in segment:
        return None
    return segment.replace(old, new, 1)


def _replace_first_operator(segment: str, operator: str, replacement: str) -> str | None:
    if not _single_line(segment):
        return None
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(segment).readline))
    except tokenize.TokenError:
        return None
    for token in tokens:
        if token.type != tokenize.OP or token.string != operator:
            continue
        start_col = token.start[1]
        end_col = token.end[1]
        return f"{segment[:start_col]}{replacement}{segment[end_col:]}"
    return None


class _ProbeCollector(ast.NodeVisitor):
    def __init__(self, source: str, rel_path: str, changed_lines: set[int]) -> None:
        self.source = source
        self.rel_path = rel_path
        self.changed_lines = changed_lines
        self.candidates: list[ProbeCandidate] = []

    def _add(self, *, line: int, original: str, replacement: str, rationale: str, kind: str) -> None:
        if original == replacement:
            return
        self.candidates.append(
            ProbeCandidate(
                id=f"P{len(self.candidates) + 1}",
                file=self.rel_path,
                line=line,
                original=original,
                replacement=replacement,
                rationale=rationale,
                kind=kind,
            )
        )

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        if not _intersects_changed_lines(node, self.changed_lines) or node.value is None:
            return

        original = _source_for_node(self.source, node)
        if not _single_line(original):
            return

        value = node.value
        value_source = _source_for_node(self.source, value)
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            replacement_value = "False" if value.value is True else "True"
            replacement = _replace_single_line_segment(original, value_source, replacement_value)
            if replacement:
                rationale = "flip true return" if value.value is True else "flip false return"
                self._add(
                    line=node.lineno,
                    original=original,
                    replacement=replacement,
                    rationale=rationale,
                    kind="boolean_return",
                )
            return

        if isinstance(value, ast.Constant) and isinstance(value.value, int) and value.value in STATUS_CODE_REPLACEMENTS:
            replacement_value, rationale = STATUS_CODE_REPLACEMENTS[value.value]
            replacement = _replace_single_line_segment(original, value_source, str(replacement_value))
            if replacement:
                self._add(
                    line=node.lineno,
                    original=original,
                    replacement=replacement,
                    rationale=rationale,
                    kind="return_status_code",
                )
            return

        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        if not _intersects_changed_lines(node, self.changed_lines):
            return
        original = _source_for_node(self.source, node)
        if not _single_line(original):
            return

        for operator_node in node.ops:
            operator_type = type(operator_node)
            if operator_type not in COMPARE_OPERATOR_REPLACEMENTS:
                continue
            replacement_operator, rationale = COMPARE_OPERATOR_REPLACEMENTS[operator_type]
            original_operator = _operator_text(operator_node)
            replacement = _replace_first_operator(original, original_operator, replacement_operator)
            if not replacement:
                continue
            self._add(
                line=node.lineno,
                original=original,
                replacement=replacement,
                rationale=rationale,
                kind="comparison_boundary",
            )
            break

        self.generic_visit(node)


def _operator_text(operator: ast.cmpop) -> str:
    if isinstance(operator, ast.LtE):
        return "<="
    if isinstance(operator, ast.GtE):
        return ">="
    if isinstance(operator, ast.Eq):
        return "=="
    if isinstance(operator, ast.NotEq):
        return "!="
    return ""


def generate_probes(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
    *,
    max_probes: int,
) -> list[dict[str, Any]]:
    probes: list[ProbeCandidate] = []
    for rel_path, lines in changed.items():
        path = repo_root / rel_path
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        changed_lines = {int(item["line"]) for item in lines}
        collector = _ProbeCollector(source, rel_path, changed_lines)
        collector.visit(tree)
        for candidate in collector.candidates:
            probes.append(
                ProbeCandidate(
                    id=f"P{len(probes) + 1}",
                    file=candidate.file,
                    line=candidate.line,
                    original=candidate.original,
                    replacement=candidate.replacement,
                    rationale=candidate.rationale,
                    kind=candidate.kind,
                )
            )
            if len(probes) >= max_probes:
                return [item.to_dict() for item in probes]
    return [item.to_dict() for item in probes]
