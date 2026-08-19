"""Bounded changed-call relationship analysis for PTG005.

The module intentionally stops at direct call sites that are themselves changed by
this PR.  It does not try to build a whole-repository call graph or infer dynamic
Python types.  The goal is to add a small amount of relationship evidence without
turning PTG005 into a general static-analysis engine.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .mocks import MockTarget, build_import_table, dotted_name, resolve_dotted_target
from .symbols import PythonSymbol, module_name_from_path


class OwnershipKind(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class MockRelation(str, Enum):
    DIRECT_CHANGED_SYMBOL = "direct_changed_symbol"
    DIRECT_INTERNAL_DEPENDENCY = "direct_internal_dependency"
    EXTERNAL_BOUNDARY = "external_boundary"
    UNRELATED = "unrelated"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DependencyCall:
    """One direct call on a line added by the current PR."""

    owner: PythonSymbol
    raw_target: str
    line: int
    candidate_targets: tuple[str, ...]
    ownership: OwnershipKind


@dataclass(frozen=True, slots=True)
class RelationshipMatch:
    relation: MockRelation
    target: MockTarget
    changed_symbol: PythonSymbol | None = None
    dependency: DependencyCall | None = None


@dataclass(frozen=True, slots=True)
class RepoModuleIndex:
    modules: frozenset[str]

    @classmethod
    def from_paths(cls, paths: Iterable[str]) -> "RepoModuleIndex":
        modules = {
            module_name_from_path(path)
            for path in paths
            if path.endswith(".py") and module_name_from_path(path)
        }
        return cls(frozenset(modules))

    def owns_target(self, target: str) -> bool:
        normalized = _canonical(target)
        if not normalized:
            return False
        # A canonical symbol can continue below the module path with class and
        # member names, so match the longest tracked module prefix.
        return any(normalized == module or normalized.startswith(f"{module}.") for module in self.modules)


def _canonical(value: str) -> str:
    return value.strip().strip("'\"").strip(".")


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


def _top_level_definitions(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _owner_class_qualname(symbol: PythonSymbol) -> str | None:
    if "." not in symbol.qualname:
        return None
    return symbol.qualname.rsplit(".", 1)[0]


def _resolve_call_candidates(
    raw_target: str,
    *,
    module: str,
    owner: PythonSymbol,
    imports: dict[str, str],
    local_definitions: set[str],
) -> tuple[str, ...]:
    """Resolve a call conservatively to lookup and definition identities.

    For imported names, Python mocks are commonly applied where a name is
    looked up (for example ``service.calculate_retry``) rather than only where
    it was originally defined (``retry.calculate_retry``).  Keep both forms so
    relationship matching follows real-world patching practice.
    """

    raw = _canonical(raw_target)
    if not raw or "(" in raw or ")" in raw or "[" in raw or "]" in raw:
        return ()

    parts = raw.split(".")
    first = parts[0]
    candidates: list[str] = []

    if first in {"self", "cls"}:
        class_qualname = _owner_class_qualname(owner)
        # ``self.method()`` is deterministic enough for a lexical class-method
        # relationship.  Deeper chains such as ``self.gateway.send()`` require
        # instance-attribute type inference and intentionally remain unresolved.
        if not class_qualname or len(parts) != 2:
            return ()
        candidates.append(".".join([module, class_qualname, parts[1]]).strip("."))
        return tuple(dict.fromkeys(item for item in candidates if item))

    if first in imports:
        resolved, _ = resolve_dotted_target(raw, imports)
        if resolved:
            candidates.append(resolved)
        # Preserve the module-local lookup identity as well.  This catches the
        # canonical "patch where looked up" form for imported functions/modules.
        if module:
            candidates.append(f"{module}.{raw}")
        return tuple(dict.fromkeys(_canonical(item) for item in candidates if item))

    if first in local_definitions:
        candidates.append(f"{module}.{raw}" if module else raw)
        return tuple(dict.fromkeys(_canonical(item) for item in candidates if item))

    # A bare unresolved name may be a builtin, closure, dynamically assigned
    # callable, or global.  A dotted name whose root is not an import/local
    # definition may be an instance attribute.  Do not guess either case.
    return ()


class _ChangedCallCollector(ast.NodeVisitor):
    """Collect calls while refusing to descend into nested definitions."""

    def __init__(
        self,
        *,
        owner: PythonSymbol,
        module: str,
        imports: dict[str, str],
        local_definitions: set[str],
        changed_lines: set[int],
        module_index: RepoModuleIndex,
    ) -> None:
        self.owner = owner
        self.module = module
        self.imports = imports
        self.local_definitions = local_definitions
        self.changed_lines = changed_lines
        self.module_index = module_index
        self.calls: list[DependencyCall] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if _intersects_changed_lines(node, self.changed_lines):
            raw = dotted_name(node.func)
            if raw:
                candidates = _resolve_call_candidates(
                    raw,
                    module=self.module,
                    owner=self.owner,
                    imports=self.imports,
                    local_definitions=self.local_definitions,
                )
                if candidates:
                    first = raw.split(".")[0]
                    if first in {"self", "cls"} or first in self.local_definitions:
                        ownership = OwnershipKind.INTERNAL
                    elif first in self.imports:
                        resolved, _ = resolve_dotted_target(raw, self.imports)
                        ownership = (
                            OwnershipKind.INTERNAL
                            if resolved and self.module_index.owns_target(resolved)
                            else OwnershipKind.EXTERNAL
                        )
                    else:
                        ownership = OwnershipKind.UNKNOWN
                    self.calls.append(
                        DependencyCall(
                            owner=self.owner,
                            raw_target=raw,
                            line=node.lineno,
                            candidate_targets=candidates,
                            ownership=ownership,
                        )
                    )
        self.generic_visit(node)


def _walk_symbol_nodes(tree: ast.Module) -> dict[str, ast.AST]:
    """Index function/method definitions by lexical qualname."""

    nodes: dict[str, ast.AST] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qualname = ".".join([*self.scope, node.name])
            nodes[qualname] = node
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

    Visitor().visit(tree)
    return nodes


def collect_changed_dependency_calls(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
    symbols: list[PythonSymbol],
    *,
    tracked_python_paths: Iterable[str],
) -> list[DependencyCall]:
    """Collect direct dependencies on changed call sites inside changed functions.

    Only call expressions that overlap added PR lines are considered.  Calls in
    unchanged parts of a changed function are intentionally ignored because
    relating those mocks to the current PR is more ambiguous and noisier.
    """

    by_file: dict[str, list[PythonSymbol]] = {}
    for symbol in symbols:
        by_file.setdefault(symbol.file, []).append(symbol)

    module_index = RepoModuleIndex.from_paths(tracked_python_paths)
    dependencies: list[DependencyCall] = []

    for rel_path, line_items in changed.items():
        file_symbols = by_file.get(rel_path, [])
        if not file_symbols:
            continue
        path = repo_root / rel_path
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        module = module_name_from_path(rel_path)
        imports = build_import_table(tree, rel_path)
        local_definitions = _top_level_definitions(tree)
        changed_lines = {int(item["line"]) for item in line_items}
        symbol_nodes = _walk_symbol_nodes(tree)

        for symbol in file_symbols:
            node = symbol_nodes.get(symbol.qualname)
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            collector = _ChangedCallCollector(
                owner=symbol,
                module=module,
                imports=imports,
                local_definitions=local_definitions,
                changed_lines=changed_lines,
                module_index=module_index,
            )
            for statement in node.body:
                collector.visit(statement)
            dependencies.extend(collector.calls)

    # Preserve stable output while removing duplicate calls that can arise from
    # overlapping changed-line spans in a multi-line call expression.
    unique: dict[tuple[str, str, int, tuple[str, ...]], DependencyCall] = {}
    for item in dependencies:
        key = (item.owner.canonical_name, item.raw_target, item.line, item.candidate_targets)
        unique[key] = item
    return list(unique.values())


def _target_candidates(target: MockTarget) -> tuple[str, ...]:
    values = []
    if target.resolved_target:
        values.append(_canonical(target.resolved_target))
    raw = _canonical(target.raw_target)
    if raw and raw not in values:
        values.append(raw)
    return tuple(values)


def classify_dependency_relation(
    target: MockTarget,
    dependencies: Iterable[DependencyCall],
) -> RelationshipMatch:
    candidates = set(_target_candidates(target))
    if not candidates:
        return RelationshipMatch(MockRelation.UNKNOWN, target)

    matches = [
        dependency
        for dependency in dependencies
        if candidates.intersection(dependency.candidate_targets)
    ]
    if not matches:
        return RelationshipMatch(MockRelation.UNRELATED, target)

    internal = [item for item in matches if item.ownership == OwnershipKind.INTERNAL]
    if internal:
        return RelationshipMatch(
            MockRelation.DIRECT_INTERNAL_DEPENDENCY,
            target,
            changed_symbol=internal[0].owner,
            dependency=internal[0],
        )

    external = [item for item in matches if item.ownership == OwnershipKind.EXTERNAL]
    if external:
        return RelationshipMatch(
            MockRelation.EXTERNAL_BOUNDARY,
            target,
            changed_symbol=external[0].owner,
            dependency=external[0],
        )

    return RelationshipMatch(
        MockRelation.UNKNOWN,
        target,
        changed_symbol=matches[0].owner,
        dependency=matches[0],
    )
