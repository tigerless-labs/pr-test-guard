"""Configuration loading for PR Test Guard."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .check import CheckError
from .paths import RelatedTestMapping


RULE_IDS = ("PTG001", "PTG002", "PTG003", "PTG004", "PTG005", "PTG006")
RULE_ACTIONS = ("off", "warn", "error")
DEFAULT_CONFIG_NAMES = (
    ".pr-test-guard.yml",
    ".pr-test-guard.yaml",
    ".pr-test-guard.json",
    ".pr-test-guard.toml",
)
TOP_LEVEL_FIELDS = ("rules", "policy", "paths", "related_tests", "github")
DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL = 50
DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE = 10


@dataclass(frozen=True, slots=True)
class GuardConfig:
    source: str | None = None
    rule_actions: dict[str, str] = field(default_factory=dict)
    fail_on: tuple[str, ...] = ()
    ignore_paths: tuple[str, ...] = ()
    test_path_include: tuple[str, ...] = ()
    test_path_exclude: tuple[str, ...] = ()
    related_test_max_candidates: int = 5
    related_test_mappings: tuple[RelatedTestMapping, ...] = ()
    github_annotation_max_total: int = DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL
    github_annotation_max_per_rule: int = DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE

    def action_for(self, rule_id: str) -> str:
        action = self.rule_actions.get(rule_id, "warn")
        if action != "off" and rule_id in self.fail_on:
            return "error"
        return action

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "rules": {rule_id: self.action_for(rule_id) for rule_id in RULE_IDS},
            "policy": {"fail_on": list(self.fail_on)},
            "paths": {
                "ignore": list(self.ignore_paths),
                "tests": {
                    "include": list(self.test_path_include),
                    "exclude": list(self.test_path_exclude),
                },
            },
            "related_tests": {
                "max_candidates": self.related_test_max_candidates,
                "mappings": [
                    {"source": mapping.source, "tests": list(mapping.tests)}
                    for mapping in self.related_test_mappings
                ],
            },
            "github": {
                "annotations": {
                    "max_total": self.github_annotation_max_total,
                    "max_per_rule": self.github_annotation_max_per_rule,
                },
            },
        }


def load_config(repo_root: Path, explicit_path: str | None = None) -> GuardConfig:
    path = _resolve_config_path(repo_root, explicit_path)
    if path is None:
        return GuardConfig()

    try:
        raw = _read_config_file(path)
    except OSError as exc:
        raise CheckError(f"unable to read config file {path}: {exc}") from exc
    except (ValueError, yaml.YAMLError) as exc:
        raise CheckError(f"unable to parse config file {path}: {exc}") from exc
    return parse_config(raw, source=str(path))


def config_from_overrides(config: GuardConfig, *, fail_on: str | None = None) -> GuardConfig:
    if not fail_on:
        return config
    values = _parse_rule_list(fail_on, field_name="--fail-on")
    merged = tuple(sorted(set(config.fail_on).union(values)))
    return GuardConfig(
        source=config.source,
        rule_actions=dict(config.rule_actions),
        fail_on=merged,
        ignore_paths=config.ignore_paths,
        test_path_include=config.test_path_include,
        test_path_exclude=config.test_path_exclude,
        related_test_max_candidates=config.related_test_max_candidates,
        related_test_mappings=config.related_test_mappings,
        github_annotation_max_total=config.github_annotation_max_total,
        github_annotation_max_per_rule=config.github_annotation_max_per_rule,
    )


def parse_config(raw: Any, *, source: str | None = None) -> GuardConfig:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise CheckError(f"config {source or '<memory>'} must contain a mapping")
    _reject_unknown_fields(raw, field_name="config", allowed=TOP_LEVEL_FIELDS)

    rules = raw.get("rules", {})
    if rules is None:
        rules = {}
    if not isinstance(rules, dict):
        raise CheckError("config field 'rules' must be a mapping")

    rule_actions: dict[str, str] = {}
    for rule_id, value in rules.items():
        normalized_rule = _normalize_rule_id(str(rule_id), field_name="rules")
        if normalized_rule in rule_actions:
            raise CheckError(
                f"config field 'rules' contains duplicate rule id after normalization: {normalized_rule}"
            )
        action = _normalize_rule_action(value, field_name=f"rules.{normalized_rule}")
        rule_actions[normalized_rule] = action

    policy = raw.get("policy", {})
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise CheckError("config field 'policy' must be a mapping")
    _reject_unknown_fields(policy, field_name="policy", allowed=("fail_on",))
    fail_on = _parse_rule_list(policy.get("fail_on", ()), field_name="policy.fail_on")

    paths = raw.get("paths", {})
    if paths is None:
        paths = {}
    if not isinstance(paths, dict):
        raise CheckError("config field 'paths' must be a mapping")
    _reject_unknown_fields(paths, field_name="paths", allowed=("ignore", "tests"))
    ignore_paths = _parse_path_patterns(paths.get("ignore", ()), field_name="paths.ignore")

    test_paths = paths.get("tests", {})
    if test_paths is None:
        test_paths = {}
    if not isinstance(test_paths, dict):
        raise CheckError("config field 'paths.tests' must be a mapping")
    _reject_unknown_fields(
        test_paths,
        field_name="paths.tests",
        allowed=("include", "exclude"),
    )
    test_path_include = _parse_path_patterns(
        test_paths.get("include", ()),
        field_name="paths.tests.include",
    )
    test_path_exclude = _parse_path_patterns(
        test_paths.get("exclude", ()),
        field_name="paths.tests.exclude",
    )

    related_tests = raw.get("related_tests", {})
    if related_tests is None:
        related_tests = {}
    if not isinstance(related_tests, dict):
        raise CheckError("config field 'related_tests' must be a mapping")
    _reject_unknown_fields(
        related_tests,
        field_name="related_tests",
        allowed=("max_candidates", "mappings"),
    )
    max_candidates = _parse_non_negative_integer(
        related_tests.get("max_candidates", 5),
        field_name="related_tests.max_candidates",
    )
    related_test_mappings = _parse_related_test_mappings(related_tests.get("mappings", ()))

    github = raw.get("github", {})
    if github is None:
        github = {}
    if not isinstance(github, dict):
        raise CheckError("config field 'github' must be a mapping")
    _reject_unknown_fields(github, field_name="github", allowed=("annotations",))

    annotations = github.get("annotations", {})
    if annotations is None:
        annotations = {}
    if not isinstance(annotations, dict):
        raise CheckError("config field 'github.annotations' must be a mapping")
    _reject_unknown_fields(
        annotations,
        field_name="github.annotations",
        allowed=("max_total", "max_per_rule"),
    )
    github_annotation_max_total = _parse_non_negative_integer(
        annotations.get("max_total", DEFAULT_GITHUB_ANNOTATION_MAX_TOTAL),
        field_name="github.annotations.max_total",
    )
    github_annotation_max_per_rule = _parse_non_negative_integer(
        annotations.get("max_per_rule", DEFAULT_GITHUB_ANNOTATION_MAX_PER_RULE),
        field_name="github.annotations.max_per_rule",
    )

    return GuardConfig(
        source=source,
        rule_actions=rule_actions,
        fail_on=tuple(sorted(set(fail_on))),
        ignore_paths=tuple(ignore_paths),
        test_path_include=test_path_include,
        test_path_exclude=test_path_exclude,
        related_test_max_candidates=max_candidates,
        related_test_mappings=related_test_mappings,
        github_annotation_max_total=github_annotation_max_total,
        github_annotation_max_per_rule=github_annotation_max_per_rule,
    )


def _resolve_config_path(repo_root: Path, explicit_path: str | None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.is_absolute() else repo_root / path
    for name in DEFAULT_CONFIG_NAMES:
        path = repo_root / name
        if path.is_file():
            return path
    return None


def _read_config_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in {".yml", ".yaml"}:
        return yaml.safe_load(text)
    if suffix == ".json":
        return json.loads(text)
    if suffix == ".toml":
        return tomllib.loads(text)
    raise CheckError(f"unsupported config file extension: {path.suffix}")


def _normalize_rule_id(value: str, *, field_name: str) -> str:
    rule_id = value.strip().upper()
    if rule_id not in RULE_IDS:
        raise CheckError(f"{field_name} contains unknown rule id: {value}")
    return rule_id


def _normalize_rule_action(value: Any, *, field_name: str) -> str:
    if isinstance(value, dict):
        _reject_unknown_fields(value, field_name=field_name, allowed=("level", "action"))
        configured_fields = [name for name in ("level", "action") if name in value]
        if len(configured_fields) != 1:
            raise CheckError(f"config field '{field_name}' must contain exactly one of: level, action")
        value = value[configured_fields[0]]
    if isinstance(value, bool):
        return "warn" if value else "off"
    if not isinstance(value, str):
        raise CheckError(f"{field_name} must be one of: {', '.join(RULE_ACTIONS)}")
    action = value.strip().lower()
    if action not in RULE_ACTIONS:
        raise CheckError(f"{field_name} must be one of: {', '.join(RULE_ACTIONS)}")
    return action


def _parse_rule_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        raise CheckError(f"{field_name} must be a list or comma-separated string")
    return tuple(_normalize_rule_id(str(item), field_name=field_name) for item in items)


def _parse_non_negative_integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CheckError(f"config field '{field_name}' must be a non-negative integer")
    return value


def _parse_string_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    elif isinstance(value, tuple):
        values = list(value)
    else:
        raise CheckError(f"{field_name} must be a string or list of strings")
    if not all(isinstance(item, str) for item in values):
        raise CheckError(f"{field_name} must contain only strings")
    if any(not item.strip() for item in values):
        raise CheckError(f"config field '{field_name}' must not contain empty strings")
    return tuple(values)


def _parse_path_patterns(value: Any, *, field_name: str) -> tuple[str, ...]:
    patterns = _parse_string_list(value, field_name=field_name)
    normalized: list[str] = []
    for pattern in patterns:
        candidate = pattern.replace("\\", "/")
        path = PurePosixPath(candidate)
        if path.is_absolute() or (len(candidate) >= 2 and candidate[1] == ":"):
            raise CheckError(f"config field '{field_name}' must contain repository-relative globs")
        if ".." in path.parts:
            raise CheckError(f"config field '{field_name}' must not contain parent-directory segments")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        if not candidate or candidate == ".":
            raise CheckError(f"config field '{field_name}' must not contain empty path patterns")
        normalized.append(candidate)
    return tuple(normalized)


def _parse_related_test_mappings(value: Any) -> tuple[RelatedTestMapping, ...]:
    field_name = "related_tests.mappings"
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise CheckError(f"config field '{field_name}' must be a list")

    mappings: list[RelatedTestMapping] = []
    for index, item in enumerate(value):
        item_name = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            raise CheckError(f"config field '{item_name}' must be a mapping")
        _reject_unknown_fields(item, field_name=item_name, allowed=("source", "tests"))

        source = item.get("source")
        if not isinstance(source, str) or not source:
            raise CheckError(f"config field '{item_name}.source' must be a non-empty string")
        normalized_source = _parse_path_patterns((source,), field_name=f"{item_name}.source")[0]

        tests = _parse_path_patterns(item.get("tests", ()), field_name=f"{item_name}.tests")
        if not tests:
            raise CheckError(f"config field '{item_name}.tests' must contain at least one path pattern")
        mappings.append(RelatedTestMapping(source=normalized_source, tests=tests))

    return tuple(mappings)


def _reject_unknown_fields(
    value: dict[Any, Any],
    *,
    field_name: str,
    allowed: tuple[str, ...],
) -> None:
    for key in value:
        if not isinstance(key, str):
            raise CheckError(f"config field '{field_name}' must contain only string keys")
        if key in allowed:
            continue
        qualified = f"{field_name}.{key}"
        matches = get_close_matches(key, allowed, n=1, cutoff=0.6)
        suggestion = f"; did you mean '{matches[0]}'?" if matches else ""
        raise CheckError(f"unknown config field '{qualified}'{suggestion}")
