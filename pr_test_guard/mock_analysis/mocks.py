"""Extract and resolve explicit Python mock targets."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from .symbols import module_name_from_path


class ResolutionKind(str, Enum):
    LITERAL = "literal"
    ALIAS = "alias_resolved"
    QUALIFIED = "qualified"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class MockTarget:
    raw_target: str
    style: str
    line: int
    resolved_target: str | None
    resolution: ResolutionKind


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def call_name(node: ast.AST) -> str | None:
    return dotted_name(node.func) if isinstance(node, ast.Call) else None


def source_for_node(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


def _package_for_module(rel_path: str, module: str) -> str:
    if PurePosixPath(rel_path.replace("\\", "/")).name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _resolve_from_module(current_package: str, module: str | None, level: int) -> str:
    if level <= 0:
        return module or ""
    package_parts = [part for part in current_package.split(".") if part]
    drop = max(0, level - 1)
    if drop > len(package_parts):
        return ""
    base_parts = package_parts[: len(package_parts) - drop] if drop else package_parts
    if module:
        base_parts.extend(module.split("."))
    return ".".join(base_parts)


def build_import_table(tree: ast.AST, rel_path: str) -> dict[str, str]:
    """Map local import names to deterministic qualified names."""

    current_module = module_name_from_path(rel_path)
    current_package = _package_for_module(rel_path, current_module)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                aliases[local] = target
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_module(current_package, node.module, node.level)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                target = f"{base}.{alias.name}" if base else alias.name
                aliases[local] = target
    return aliases


def resolve_dotted_target(raw_target: str, imports: dict[str, str]) -> tuple[str | None, ResolutionKind]:
    raw = raw_target.strip().strip("'\"")
    if not raw or "(" in raw or ")" in raw or "[" in raw or "]" in raw:
        return None, ResolutionKind.UNRESOLVED
    parts = raw.split(".")
    first = parts[0]
    if first in imports:
        resolved = ".".join([imports[first], *parts[1:]])
        return resolved, ResolutionKind.ALIAS
    if len(parts) >= 2:
        return raw, ResolutionKind.QUALIFIED
    return None, ResolutionKind.UNRESOLVED


def _resolved_call_name(node: ast.Call, imports: dict[str, str]) -> str | None:
    raw = call_name(node)
    if not raw:
        return None
    resolved, _ = resolve_dotted_target(raw, imports)
    return resolved or raw


def extract_mock_targets(source: str, tree: ast.AST, rel_path: str) -> list[MockTarget]:
    """Extract supported mock/patch calls and resolve common aliases."""

    imports = build_import_table(tree, rel_path)
    targets: list[MockTarget] = []
    for node in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
        raw_call = call_name(node)
        resolved_call = _resolved_call_name(node, imports)
        if not raw_call or not resolved_call:
            continue

        style: str | None = None
        raw_target: str | None = None
        resolved_target: str | None = None
        resolution = ResolutionKind.UNRESOLVED

        is_patch_object = raw_call.endswith("patch.object") or resolved_call.endswith("unittest.mock.patch.object")
        is_patch = (
            raw_call == "patch"
            or raw_call.endswith(".patch")
            or resolved_call == "unittest.mock.patch"
            or resolved_call.endswith(".mocker.patch")
        )
        is_setattr = raw_call.endswith(".setattr")

        if is_patch_object and len(node.args) >= 2:
            attr = node.args[1]
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                owner = dotted_name(node.args[0])
                if owner:
                    raw_target = f"{owner}.{attr.value}"
                    resolved_target, resolution = resolve_dotted_target(raw_target, imports)
                else:
                    raw_target = f"{source_for_node(source, node.args[0])}.{attr.value}"
                style = "patch.object"
        elif is_patch and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            raw_target = node.args[0].value
            resolved_target = raw_target.strip().strip("'\"")
            resolution = ResolutionKind.LITERAL
            style = "patch"
        elif is_setattr and len(node.args) >= 2:
            first, second = node.args[0], node.args[1]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                raw_target = first.value
                resolved_target = raw_target.strip().strip("'\"")
                resolution = ResolutionKind.LITERAL
                style = "setattr"
            elif isinstance(second, ast.Constant) and isinstance(second.value, str):
                owner = dotted_name(first)
                if owner:
                    raw_target = f"{owner}.{second.value}"
                    resolved_target, resolution = resolve_dotted_target(raw_target, imports)
                else:
                    raw_target = f"{source_for_node(source, first)}.{second.value}"
                style = "setattr"

        if raw_target and style:
            targets.append(
                MockTarget(
                    raw_target=raw_target,
                    style=style,
                    line=node.lineno,
                    resolved_target=resolved_target,
                    resolution=resolution,
                )
            )
    return targets
