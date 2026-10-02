"""Changed-symbol evidence and bounded assertion-flow analysis."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mock_analysis.matching import match_mock_target
from .mock_analysis.mocks import build_import_table, extract_mock_targets, resolve_dotted_target
from .mock_analysis.symbols import PythonSymbol, collect_changed_symbols, module_name_from_path


@dataclass(frozen=True, slots=True)
class ChangeUnit:
    """One changed Python function/method and its available test evidence."""

    id: str
    file: str
    symbol: str
    line: int
    changed_lines: tuple[int, ...]
    behavior_kinds: tuple[str, ...]
    related_tests: tuple[str, ...]
    directly_exercising_tests: tuple[str, ...]
    indirectly_exercising_tests: tuple[str, ...]
    mock_replacement_tests: tuple[str, ...]
    constrained_tests: tuple[str, ...]
    unconstrained_tests: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "symbol": self.symbol,
            "line": self.line,
            "changed_lines": list(self.changed_lines),
            "behavior_kinds": list(self.behavior_kinds),
            "related_tests": list(self.related_tests),
            "directly_exercising_tests": list(self.directly_exercising_tests),
            "indirectly_exercising_tests": list(self.indirectly_exercising_tests),
            "mock_replacement_tests": list(self.mock_replacement_tests),
            "constrained_tests": list(self.constrained_tests),
            "unconstrained_tests": list(self.unconstrained_tests),
        }


@dataclass(frozen=True, slots=True)
class AssertionFlow:
    file: str
    test_name: str
    line: int
    symbol: str
    call_lines: tuple[int, ...]
    assertion_lines: tuple[int, ...]
    constrained: bool
    reason: str

    @property
    def test_ref(self) -> str:
        return f"{self.file}::{self.test_name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "test_name": self.test_name,
            "line": self.line,
            "symbol": self.symbol,
            "call_lines": list(self.call_lines),
            "assertion_lines": list(self.assertion_lines),
            "constrained": self.constrained,
            "reason": self.reason,
        }


def _call_name(node: ast.Call) -> str | None:
    current: ast.AST = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _resolved_call_matches(node: ast.Call, imports: dict[str, str], symbol: PythonSymbol) -> bool:
    name = _call_name(node)
    if not name:
        return False
    resolved, _ = resolve_dotted_target(name, imports)
    candidates = {name, resolved or ""}
    return symbol.canonical_name in candidates


def _assigned_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for item in target.elts for name in _assigned_names(item)}
    return set()


def _names_in(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _contains_symbol_call(node: ast.AST, imports: dict[str, str], symbol: PythonSymbol) -> bool:
    return any(
        isinstance(child, ast.Call) and _resolved_call_matches(child, imports, symbol)
        for child in ast.walk(node)
    )


def _is_meaningful_assertion(node: ast.Assert) -> bool:
    test = node.test
    if isinstance(test, ast.Constant):
        return False
    if isinstance(test, ast.Compare):
        # Self-comparisons do not constrain the changed behavior.
        if len(test.comparators) == 1 and ast.dump(test.left) == ast.dump(test.comparators[0]):
            return False
        if any(
            isinstance(comparator, ast.Constant) and comparator.value is None
            for comparator in test.comparators
        ):
            return False
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    return not isinstance(test, (ast.Name, ast.Attribute, ast.Call))


def analyze_assertion_flow(
    repo_root: Path,
    test_files: list[str],
    symbols: list[PythonSymbol],
) -> list[AssertionFlow]:
    """Track direct changed-symbol results to assertions within one test function.

    The analysis is intentionally intraprocedural.  It follows assignments and
    derived attribute/subscript expressions, while leaving fixtures and helper
    calls unknown rather than guessing.
    """

    flows: list[AssertionFlow] = []
    for rel_path in test_files:
        path = repo_root / rel_path
        if not path.is_file() or path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        imports = build_import_table(tree, rel_path)
        mock_targets = extract_mock_targets(source, tree, rel_path)
        for test_node in ast.walk(tree):
            if not isinstance(test_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not test_node.name.startswith("test_"):
                continue
            for symbol in symbols:
                calls = [
                    node
                    for node in ast.walk(test_node)
                    if isinstance(node, ast.Call) and _resolved_call_matches(node, imports, symbol)
                ]
                if not calls:
                    continue

                decorator_lines = [
                    int(getattr(decorator, "lineno", test_node.lineno))
                    for decorator in test_node.decorator_list
                ]
                test_start = min([int(getattr(test_node, "lineno", 0)), *decorator_lines])
                test_end = int(getattr(test_node, "end_lineno", test_start))
                directly_mocked = any(
                    test_start <= target.line <= test_end and bool(match_mock_target(target, [symbol]))
                    for target in mock_targets
                )

                tainted: set[str] = set()
                observing: list[ast.Assert] = []
                events = [
                    node
                    for node in ast.walk(test_node)
                    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.Assert))
                ]
                events.sort(
                    key=lambda node: (
                        int(getattr(node, "lineno", 0)),
                        1 if isinstance(node, ast.Assert) else 0,
                        int(getattr(node, "col_offset", 0)),
                    )
                )
                for node in events:
                    if isinstance(node, ast.Assert):
                        if _contains_symbol_call(node.test, imports, symbol) or bool(
                            _names_in(node.test) & tainted
                        ):
                            observing.append(node)
                        continue
                    value: ast.AST | None = None
                    targets: set[str] = set()
                    if isinstance(node, ast.Assign):
                        value = node.value
                        targets = {name for target in node.targets for name in _assigned_names(target)}
                    elif isinstance(node, ast.AnnAssign) and node.value is not None:
                        value = node.value
                        targets = _assigned_names(node.target)
                    elif isinstance(node, ast.NamedExpr):
                        value = node.value
                        targets = _assigned_names(node.target)
                    if value is None or not targets:
                        continue
                    derives = _contains_symbol_call(value, imports, symbol) or bool(_names_in(value) & tainted)
                    if derives:
                        tainted.update(targets)
                    else:
                        # A later unrelated assignment breaks the local flow.
                        tainted.difference_update(targets)

                meaningful = [node for node in observing if _is_meaningful_assertion(node)]
                exception_lines = [
                    int(node.lineno)
                    for node in ast.walk(test_node)
                    if isinstance(node, ast.With)
                    and any(
                        isinstance(item.context_expr, ast.Call)
                        and _call_name(item.context_expr) == "pytest.raises"
                        for item in node.items
                    )
                    and any(_contains_symbol_call(statement, imports, symbol) for statement in node.body)
                ]
                if directly_mocked:
                    reason = "direct_changed_symbol_mock_reported_by_ptg005"
                elif exception_lines:
                    reason = "changed_call_constrained_by_expected_exception"
                elif meaningful:
                    reason = "changed_result_reaches_meaningful_assertion"
                elif observing:
                    reason = "changed_result_reaches_weak_assertion"
                else:
                    reason = "changed_result_not_observed_by_assertion"
                flows.append(
                    AssertionFlow(
                        file=rel_path,
                        test_name=test_node.name,
                        line=int(getattr(test_node, "lineno", 0)),
                        symbol=symbol.canonical_name,
                        call_lines=tuple(sorted({int(node.lineno) for node in calls})),
                        assertion_lines=tuple(
                            sorted({int(node.lineno) for node in observing} | set(exception_lines))
                        ),
                        constrained=bool(meaningful or exception_lines) and not directly_mocked,
                        reason=reason,
                    )
                )
    return sorted(flows, key=lambda item: (item.file, item.line, item.symbol))


def _symbol_node(path: Path, symbol: PythonSymbol) -> ast.AST | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    matched: ast.AST | None = None
    scope: list[str] = []

    class Finder(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            nonlocal matched
            qualname = ".".join([*scope, node.name])
            if qualname == symbol.qualname:
                matched = node
                return
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

    Finder().visit(tree)
    return matched


def _behavior_kinds(path: Path, changed_lines: set[int], symbol: PythonSymbol) -> tuple[str, ...]:
    matched = _symbol_node(path, symbol)
    if matched is None:
        return ("statement",)
    kinds: set[str] = set()
    for node in ast.walk(matched):
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start is None or end is None or not any(int(start) <= line <= int(end) for line in changed_lines):
            continue
        if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
            kinds.add("branch")
        elif isinstance(node, ast.Compare):
            kinds.add("condition")
        elif isinstance(node, ast.Return):
            kinds.add("return")
        elif isinstance(node, ast.Raise):
            kinds.add("exception")
        elif isinstance(node, ast.Call):
            kinds.add("dependency_call")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            kinds.add("state_update")
    return tuple(sorted(kinds or {"statement"}))


def _symbol_call_candidates(
    node: ast.Call,
    imports: dict[str, str],
    caller: PythonSymbol,
) -> set[str]:
    name = _call_name(node)
    if not name:
        return set()
    resolved, _ = resolve_dotted_target(name, imports)
    candidates = {item for item in (name, resolved) if item}
    if "." not in name:
        candidates.add(f"{caller.module}.{name}" if caller.module else name)
    elif name.startswith(("self.", "cls.")) and "." in caller.qualname:
        owner = caller.qualname.rsplit(".", 1)[0]
        leaf = name.split(".", 1)[1]
        candidates.add(f"{caller.module}.{owner}.{leaf}")
    return {candidate.strip(".") for candidate in candidates}


def _file_function_index(
    repo_root: Path,
    files: set[str],
) -> tuple[list[PythonSymbol], dict[str, ast.AST], dict[str, dict[str, str]]]:
    """Index module functions and class methods, excluding local definitions."""

    symbols: list[PythonSymbol] = []
    nodes: dict[str, ast.AST] = {}
    imports_by_file: dict[str, dict[str, str]] = {}
    for rel_path in sorted(files):
        path = repo_root / rel_path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        imports_by_file[rel_path] = build_import_table(tree, rel_path)
        module = module_name_from_path(rel_path)
        class_scope: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
                class_scope.append(node.name)
                for child in node.body:
                    if isinstance(child, ast.ClassDef):
                        self.visit(child)
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.visit(child)
                class_scope.pop()

            def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                qualname = ".".join([*class_scope, node.name])
                symbol = PythonSymbol(
                    file=rel_path,
                    module=module,
                    qualname=qualname,
                    name=node.name,
                    line=int(node.lineno),
                )
                symbols.append(symbol)
                nodes[symbol.canonical_name] = node
                # Local functions and classes are implementation details of
                # this evidence unit and are not separate PTG007 candidates.

            visit_FunctionDef = _visit_function
            visit_AsyncFunctionDef = _visit_function

        Visitor().visit(tree)
    return symbols, nodes, imports_by_file


def _call_edges(
    symbols: list[PythonSymbol],
    nodes: dict[str, ast.AST],
    imports_by_file: dict[str, dict[str, str]],
) -> dict[str, set[str]]:
    """Build conservative direct call edges between indexed symbols."""

    canonical = {symbol.canonical_name for symbol in symbols}
    edges: dict[str, set[str]] = {symbol.canonical_name: set() for symbol in symbols}
    for symbol in symbols:
        imports = imports_by_file.get(symbol.file, {})
        root = nodes.get(symbol.canonical_name)
        if root is None:
            continue
        calls: list[ast.Call] = []

        class CallVisitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
                calls.append(node)
                self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
                if node is root:
                    self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
                if node is root:
                    self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
                return None

        CallVisitor().visit(root)
        for call in calls:
            edges[symbol.canonical_name].update(
                _symbol_call_candidates(call, imports, symbol) & canonical
            )
    return edges


def _direct_test_calls(
    repo_root: Path,
    test_files: list[str],
    symbols: list[PythonSymbol],
) -> dict[str, set[str]]:
    canonical = {symbol.canonical_name for symbol in symbols}
    calls_by_symbol: dict[str, set[str]] = {name: set() for name in canonical}
    for rel_path in test_files:
        path = repo_root / rel_path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        imports = build_import_table(tree, rel_path)
        for test_node in ast.walk(tree):
            if not isinstance(test_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not test_node.name.startswith("test_"):
                continue
            test_ref = f"{rel_path}::{test_node.name}"
            for call in (node for node in ast.walk(test_node) if isinstance(node, ast.Call)):
                name = _call_name(call)
                if not name:
                    continue
                resolved, _ = resolve_dotted_target(name, imports)
                for candidate in {name, resolved or ""} & canonical:
                    calls_by_symbol[candidate].add(test_ref)
    return calls_by_symbol


def build_change_units(
    repo_root: Path,
    changed: dict[str, list[dict[str, Any]]],
    related_tests: list[Any],
    test_files: list[str],
) -> tuple[list[ChangeUnit], list[AssertionFlow]]:
    changed_symbols = collect_changed_symbols(repo_root, changed)
    indexed_symbols, indexed_nodes, imports_by_file = _file_function_index(
        repo_root,
        set(changed),
    )
    changed_names = {symbol.canonical_name for symbol in changed_symbols}
    symbols = [symbol for symbol in indexed_symbols if symbol.canonical_name in changed_names]
    flows = analyze_assertion_flow(repo_root, test_files, symbols)
    call_edges = _call_edges(indexed_symbols, indexed_nodes, imports_by_file)
    all_direct_tests = _direct_test_calls(repo_root, test_files, indexed_symbols)
    direct_tests_by_symbol: dict[str, set[str]] = {
        symbol.canonical_name: set(all_direct_tests[symbol.canonical_name])
        for symbol in indexed_symbols
    }
    mock_tests_by_symbol: dict[str, set[str]] = {}
    related_by_symbol: dict[str, list[Any]] = {}
    for symbol in symbols:
        related = [item for item in related_tests if symbol.canonical_name in item.matched_symbols]
        related_by_symbol[symbol.canonical_name] = related
        mock_tests_by_symbol[symbol.canonical_name] = {
            f"{item.file}::{item.test_name}"
            for item in related
            if "mocks_changed_symbol" in item.reasons
        }
        direct_tests_by_symbol[symbol.canonical_name].difference_update(
            mock_tests_by_symbol[symbol.canonical_name]
        )

    exercising_tests = {name: set(refs) for name, refs in direct_tests_by_symbol.items()}
    changed_evidence = True
    while changed_evidence:
        changed_evidence = False
        for caller, callees in call_edges.items():
            for callee in callees:
                before = len(exercising_tests[callee])
                exercising_tests[callee].update(exercising_tests[caller])
                changed_evidence = changed_evidence or len(exercising_tests[callee]) > before

    units: list[ChangeUnit] = []
    for index, symbol in enumerate(symbols, start=1):
        symbol_node = _symbol_node(repo_root / symbol.file, symbol)
        start = int(getattr(symbol_node, "lineno", symbol.line))
        end = int(getattr(symbol_node, "end_lineno", start))
        changed_lines = tuple(
            sorted(
                int(item["line"])
                for item in changed.get(symbol.file, ())
                if start <= int(item["line"]) <= end
            )
        )
        related = related_by_symbol[symbol.canonical_name]
        related_refs = tuple(sorted({f"{item.file}::{item.test_name}" for item in related}))
        direct_refs = tuple(sorted(direct_tests_by_symbol[symbol.canonical_name]))
        indirect_refs = tuple(
            sorted(exercising_tests[symbol.canonical_name] - direct_tests_by_symbol[symbol.canonical_name])
        )
        mock_refs = tuple(sorted(mock_tests_by_symbol[symbol.canonical_name]))
        symbol_flows = [flow for flow in flows if flow.symbol == symbol.canonical_name]
        constrained = tuple(sorted({flow.test_ref for flow in symbol_flows if flow.constrained}))
        unconstrained = tuple(sorted({flow.test_ref for flow in symbol_flows if not flow.constrained}))
        units.append(
            ChangeUnit(
                id=f"CU{index}",
                file=symbol.file,
                symbol=symbol.canonical_name,
                line=symbol.line,
                changed_lines=changed_lines,
                behavior_kinds=_behavior_kinds(repo_root / symbol.file, set(changed_lines), symbol),
                related_tests=related_refs,
                directly_exercising_tests=direct_refs,
                indirectly_exercising_tests=indirect_refs,
                mock_replacement_tests=mock_refs,
                constrained_tests=constrained,
                unconstrained_tests=unconstrained,
            )
        )
    return units, flows
