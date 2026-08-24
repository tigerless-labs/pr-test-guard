"""Bounded test-semantics helpers for PTG005 dependency mocks."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .mocks import MockTarget, dotted_name
from .symbols import PythonSymbol


INTERACTION_ASSERTIONS = {
    "assert_any_call",
    "assert_called",
    "assert_called_once",
    "assert_called_once_with",
    "assert_called_with",
    "assert_has_calls",
    "assert_not_called",
}


@dataclass(frozen=True, slots=True)
class BoundaryConstraint:
    constrained: bool
    reason: str


def dependency_mock_is_constrained(
    tree: ast.AST,
    *,
    target: MockTarget,
    owner: PythonSymbol,
    added_lines: set[int],
) -> BoundaryConstraint:
    """Detect whether a dependency mock is used as a constrained boundary.

    This is intentionally narrower than business-intent understanding.  It
    looks for deterministic test evidence that the changed owner behavior is
    still constrained through either interaction assertions on the mock or a
    non-weak assertion over the owner call result.
    """

    test_node = _enclosing_test_function(tree, target.line)
    if test_node is None:
        return BoundaryConstraint(False, "no_enclosing_test_function")

    mock_names = _mock_names_for_target(test_node, target)
    if mock_names and _has_added_interaction_assertion(test_node, mock_names, added_lines):
        return BoundaryConstraint(True, "interaction_assertion")

    owner_result_names = _owner_result_names(test_node, owner)
    if _has_added_owner_outcome_assertion(test_node, owner, owner_result_names, added_lines):
        return BoundaryConstraint(True, "owner_outcome_assertion")

    if _has_added_pytest_raises_for_owner(test_node, owner, added_lines):
        return BoundaryConstraint(True, "owner_exception_assertion")

    return BoundaryConstraint(False, "no_interaction_or_outcome_constraint")


def _enclosing_test_function(tree: ast.AST, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start is not None and end is not None and int(start) <= line <= int(end):
            matches.append(node)
            continue
        for decorator in node.decorator_list:
            deco_start = getattr(decorator, "lineno", None)
            deco_end = getattr(decorator, "end_lineno", deco_start)
            if deco_start is not None and deco_end is not None and int(deco_start) <= line <= int(deco_end):
                matches.append(node)
                break
    if not matches:
        return None
    return max(matches, key=lambda item: int(getattr(item, "lineno", 0)))


def _mock_names_for_target(test_node: ast.FunctionDef | ast.AsyncFunctionDef, target: MockTarget) -> set[str]:
    names: set[str] = set()
    target_leaf = target.raw_target.strip().strip("'\"").rsplit(".", 1)[-1].lower()

    for arg in [*test_node.args.posonlyargs, *test_node.args.args, *test_node.args.kwonlyargs]:
        if arg.arg.startswith("mock") or target_leaf in arg.arg.lower():
            names.add(arg.arg)

    for node in ast.walk(test_node):
        if isinstance(node, ast.With):
            for item in node.items:
                line = getattr(item.context_expr, "lineno", None)
                if line == target.line and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
        elif isinstance(node, ast.Assign):
            line = getattr(node.value, "lineno", None)
            if line == target.line:
                names.update(_assigned_names(node.targets))
        elif isinstance(node, ast.AnnAssign):
            line = getattr(node.value, "lineno", None) if node.value is not None else None
            if line == target.line:
                names.update(_assigned_names([node.target]))

    return names


def _assigned_names(targets: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.update(_assigned_names([item for item in target.elts if isinstance(item, ast.expr)]))
    return names


def _root_name(name: str) -> str:
    return name.split(".", 1)[0]


def _is_added(node: ast.AST, added_lines: set[int]) -> bool:
    line = getattr(node, "lineno", None)
    return line in added_lines if line is not None else False


def _has_added_interaction_assertion(
    test_node: ast.FunctionDef | ast.AsyncFunctionDef,
    mock_names: set[str],
    added_lines: set[int],
) -> bool:
    for node in ast.walk(test_node):
        if isinstance(node, ast.Call) and _is_added(node, added_lines):
            name = dotted_name(node.func)
            if not name:
                continue
            parts = name.split(".")
            if parts[-1] in INTERACTION_ASSERTIONS and _root_name(name) in mock_names:
                return True
        if isinstance(node, ast.Assert) and _is_added(node, added_lines):
            for child in ast.walk(node.test):
                if isinstance(child, ast.Attribute):
                    name = dotted_name(child)
                    if not name:
                        continue
                    if _root_name(name) in mock_names and name.split(".")[-1] in {"call_args", "call_count"}:
                        return True
    return False


def _owner_result_names(test_node: ast.FunctionDef | ast.AsyncFunctionDef, owner: PythonSymbol) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(test_node):
        if isinstance(node, ast.Assign) and _contains_owner_call(node.value, owner):
            names.update(_assigned_names(node.targets))
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _contains_owner_call(node.value, owner):
            names.update(_assigned_names([node.target]))
    return names


def _has_added_owner_outcome_assertion(
    test_node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: PythonSymbol,
    owner_result_names: set[str],
    added_lines: set[int],
) -> bool:
    for node in ast.walk(test_node):
        if not isinstance(node, ast.Assert) or not _is_added(node, added_lines):
            continue
        if not _is_strong_assertion(node.test):
            continue
        if _contains_owner_call(node.test, owner) or _contains_owner_result_name(node.test, owner_result_names):
            return True
    return False


def _has_added_pytest_raises_for_owner(
    test_node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: PythonSymbol,
    added_lines: set[int],
) -> bool:
    for node in ast.walk(test_node):
        if not isinstance(node, ast.With) or not _is_added(node, added_lines):
            continue
        has_raises = any(dotted_name(item.context_expr.func) == "pytest.raises" for item in node.items if isinstance(item.context_expr, ast.Call))
        if has_raises and any(isinstance(child, ast.Call) and _is_owner_call(child, owner) for child in ast.walk(node)):
            return True
    return False


def _contains_owner_call(node: ast.AST, owner: PythonSymbol) -> bool:
    return any(isinstance(child, ast.Call) and _is_owner_call(child, owner) for child in ast.walk(node))


def _is_owner_call(node: ast.Call, owner: PythonSymbol) -> bool:
    name = dotted_name(node.func)
    if not name:
        return False
    owner_leaf = owner.name
    owner_qualname = owner.qualname
    return name == owner_leaf or name.endswith(f".{owner_leaf}") or name.endswith(f".{owner_qualname}")


def _contains_owner_result_name(node: ast.AST, owner_result_names: set[str]) -> bool:
    return bool(owner_result_names) and any(
        isinstance(child, ast.Name) and child.id in owner_result_names for child in ast.walk(node)
    )


def _is_strong_assertion(test: ast.AST) -> bool:
    if isinstance(test, ast.Compare):
        if any(isinstance(comparator, ast.Constant) and comparator.value is None for comparator in test.comparators):
            return False
        if any(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops):
            return False
        return True
    if isinstance(test, ast.Call):
        return False
    if isinstance(test, (ast.Name, ast.Attribute)):
        return False
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return False
    return False
