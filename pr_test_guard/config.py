"""Configuration loading for PR Test Guard."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .check import CheckError


RULE_IDS = ("PTG001", "PTG002", "PTG003", "PTG004", "PTG005", "PTG006")
RULE_ACTIONS = ("off", "warn", "error")
DEFAULT_CONFIG_NAMES = (
    ".pr-test-guard.yml",
    ".pr-test-guard.yaml",
    ".pr-test-guard.json",
    ".pr-test-guard.toml",
)


@dataclass(frozen=True, slots=True)
class GuardConfig:
    source: str | None = None
    rule_actions: dict[str, str] = field(default_factory=dict)
    fail_on: tuple[str, ...] = ()
    ignore_paths: tuple[str, ...] = ()
    related_test_max_candidates: int = 5

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
            "paths": {"ignore": list(self.ignore_paths)},
            "related_tests": {"max_candidates": self.related_test_max_candidates},
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
        related_test_max_candidates=config.related_test_max_candidates,
    )


def parse_config(raw: Any, *, source: str | None = None) -> GuardConfig:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise CheckError(f"config {source or '<memory>'} must contain a mapping")

    rules = raw.get("rules", {})
    if rules is None:
        rules = {}
    if not isinstance(rules, dict):
        raise CheckError("config field 'rules' must be a mapping")

    rule_actions: dict[str, str] = {}
    for rule_id, value in rules.items():
        normalized_rule = _normalize_rule_id(str(rule_id), field_name="rules")
        action = _normalize_rule_action(value, field_name=f"rules.{normalized_rule}")
        rule_actions[normalized_rule] = action

    policy = raw.get("policy", {})
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise CheckError("config field 'policy' must be a mapping")
    fail_on = _parse_rule_list(policy.get("fail_on", ()), field_name="policy.fail_on")

    paths = raw.get("paths", {})
    if paths is None:
        paths = {}
    if not isinstance(paths, dict):
        raise CheckError("config field 'paths' must be a mapping")
    ignore_paths = _parse_string_list(paths.get("ignore", ()), field_name="paths.ignore")

    related_tests = raw.get("related_tests", {})
    if related_tests is None:
        related_tests = {}
    if not isinstance(related_tests, dict):
        raise CheckError("config field 'related_tests' must be a mapping")
    max_candidates = related_tests.get("max_candidates", 5)
    if not isinstance(max_candidates, int) or max_candidates < 0:
        raise CheckError("config field 'related_tests.max_candidates' must be a non-negative integer")

    return GuardConfig(
        source=source,
        rule_actions=rule_actions,
        fail_on=tuple(sorted(set(fail_on))),
        ignore_paths=tuple(ignore_paths),
        related_test_max_candidates=max_candidates,
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
        value = value.get("level", value.get("action"))
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
    return tuple(item for item in values if item)
