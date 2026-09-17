from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from pr_test_guard.cli import main
from pr_test_guard.check import CheckError
from pr_test_guard.config import load_config, parse_config


def run(*args: str, cwd: Path) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.name", "Test User", cwd=repo)
    run("git", "config", "user.email", "test@example.com", cwd=repo)
    return repo


def commit_all(repo: Path, message: str) -> None:
    run("git", "add", "-A", cwd=repo)
    run("git", "commit", "-m", message, cwd=repo)


def make_weak_mock_repo(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path)
    write(repo / "payment.py", "def charge(amount):\n    return amount > 0\n")
    write(repo / "tests/test_payment.py", "from payment import charge\n\ndef test_charge():\n    assert charge(1) is True\n")
    commit_all(repo, "base")

    write(repo / "payment.py", "def charge(amount):\n    return amount >= 0\n")
    write(
        repo / "tests/test_payment.py",
        "from unittest.mock import patch\nfrom payment import charge\n\n"
        "@patch('payment.charge')\n"
        "def test_charge(mock_charge):\n"
        "    mock_charge.return_value = True\n"
        "    result = charge(0)\n"
        "    assert result is not None\n",
    )
    commit_all(repo, "change behavior and test")
    return repo


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"rulse": {}}, "unknown config field 'config.rulse'; did you mean 'rules'?"),
        ({"policy": {"fail": []}}, "unknown config field 'policy.fail'; did you mean 'fail_on'?"),
        ({"paths": {"test": {}}}, "unknown config field 'paths.test'; did you mean 'tests'?"),
        (
            {"paths": {"tests": {"includes": ["spec/**"]}}},
            "unknown config field 'paths.tests.includes'; did you mean 'include'?",
        ),
        (
            {"related_tests": {"max_candidate": 3}},
            "unknown config field 'related_tests.max_candidate'; did you mean 'max_candidates'?",
        ),
        (
            {
                "related_tests": {
                    "mappings": [
                        {"source": "src/**", "tests": ["tests/**"], "test": ["spec/**"]}
                    ]
                }
            },
            "unknown config field 'related_tests.mappings[0].test'; did you mean 'tests'?",
        ),
        (
            {"rules": {"PTG001": {"level": "warn", "enabled": True}}},
            "unknown config field 'rules.PTG001.enabled'",
        ),
        (
            {"github": {"annotations": {"max": 5}}},
            "unknown config field 'github.annotations.max'",
        ),
    ],
)
def test_config_rejects_unknown_fields_with_actionable_errors(raw, expected: str) -> None:
    with pytest.raises(CheckError) as raised:
        parse_config(raw)

    assert str(raised.value) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"related_tests": {"max_candidates": True}},
            "related_tests.max_candidates' must be a non-negative integer",
        ),
        (
            {"paths": {"ignore": [""]}},
            "paths.ignore' must not contain empty strings",
        ),
        (
            {"paths": {"tests": {"include": ["  "]}}},
            "paths.tests.include' must not contain empty strings",
        ),
        (
            {"rules": {"PTG001": {"level": "warn", "action": "error"}}},
            "rules.PTG001' must contain exactly one of: level, action",
        ),
        (
            {"rules": {"PTG001": {}}},
            "rules.PTG001' must contain exactly one of: level, action",
        ),
        (
            {"rules": {"PTG001": "warn", "ptg001": "error"}},
            "duplicate rule id after normalization: PTG001",
        ),
        (
            {"github": {"annotations": {"max_total": True}}},
            "github.annotations.max_total' must be a non-negative integer",
        ),
        (
            {"github": {"annotations": {"max_per_rule": -1}}},
            "github.annotations.max_per_rule' must be a non-negative integer",
        ),
    ],
)
def test_config_rejects_ambiguous_or_silent_noop_values(raw, expected: str) -> None:
    with pytest.raises(CheckError) as raised:
        parse_config(raw)

    assert expected in str(raised.value)


def test_validate_config_prints_normalized_json(tmp_path: Path, monkeypatch, capsys) -> None:
    write(
        tmp_path / "guard.yml",
        "rules:\n  ptg001:\n    level: error\nrelated_tests:\n  max_candidates: 2\n",
    )
    monkeypatch.chdir(tmp_path)

    code = main(["validate-config", "--config", "guard.yml", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rules"]["PTG001"] == "error"
    assert payload["rules"]["PTG006"] == "warn"
    assert payload["related_tests"]["max_candidates"] == 2
    assert payload["github"]["annotations"] == {"max_per_rule": 10, "max_total": 50}
    assert payload["source"] == str(tmp_path / "guard.yml")


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("guard.yml", "github:\n  annotations:\n    max_total: 12\n    max_per_rule: 3\n"),
        ("guard.json", '{"github":{"annotations":{"max_total":12,"max_per_rule":3}}}'),
        ("guard.toml", "[github.annotations]\nmax_total = 12\nmax_per_rule = 3\n"),
    ],
)
def test_github_annotation_limits_support_all_config_formats(
    tmp_path: Path,
    name: str,
    content: str,
) -> None:
    write(tmp_path / name, content)

    config = load_config(tmp_path, name)

    assert config.github_annotation_max_total == 12
    assert config.github_annotation_max_per_rule == 3
    assert config.to_dict()["github"]["annotations"] == {
        "max_total": 12,
        "max_per_rule": 3,
    }


def test_validate_config_reports_discovery_and_typos(tmp_path: Path, monkeypatch, capsys) -> None:
    write(tmp_path / ".pr-test-guard.yml", "related_tests:\n  max_candidate: 2\n")
    monkeypatch.chdir(tmp_path)

    code = main(["validate-config"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "did you mean 'max_candidates'?" in captured.err


def test_validate_config_accepts_built_in_defaults(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    code = main(["validate-config"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Configuration valid: built-in defaults (no config file found)" in captured.out
    assert '"source": null' in captured.out


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("guard.json", '{"paths":{"tests":{"include":["spec/**"],"exclude":["spec/helpers/**"]}}}'),
        ("guard.toml", '[paths.tests]\ninclude = ["spec/**"]\nexclude = ["spec/helpers/**"]\n'),
    ],
)
def test_test_path_config_is_supported_by_structured_config_formats(
    tmp_path: Path,
    name: str,
    content: str,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / name, content)

    config = load_config(repo, name)

    assert config.test_path_include == ("spec/**",)
    assert config.test_path_exclude == ("spec/helpers/**",)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (
            "guard.json",
            '{"related_tests":{"mappings":[{"source":"src/payments/**","tests":["spec/payments/**"]}]}}',
        ),
        (
            "guard.toml",
            '[[related_tests.mappings]]\nsource = "src/payments/**"\ntests = ["spec/payments/**"]\n',
        ),
    ],
)
def test_related_test_mappings_are_supported_by_structured_config_formats(
    tmp_path: Path,
    name: str,
    content: str,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / name, content)

    config = load_config(repo, name)

    assert len(config.related_test_mappings) == 1
    assert config.related_test_mappings[0].source == "src/payments/**"
    assert config.related_test_mappings[0].tests == ("spec/payments/**",)


def test_config_can_disable_rules_and_promote_error_policy(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_weak_mock_repo(tmp_path)
    write(
        repo / ".pr-test-guard.yml",
        "rules:\n"
        "  PTG003: off\n"
        "  PTG005: error\n"
        "related_tests:\n"
        "  max_candidates: 1\n",
    )
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert [item["rule_id"] for item in payload["findings"]] == ["PTG005"]
    assert payload["findings"][0]["severity"] == "error"
    assert payload["policy"]["rules"]["PTG003"] == "off"
    assert payload["policy"]["rules"]["PTG005"] == "error"
    assert any("suppressed 1 PTG003" in note for note in payload["notes"])
    assert any("error rule(s) triggered: PTG005" in note for note in payload["notes"])


def test_no_config_keeps_default_advisory_behavior(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/test_app.py", "from app import value\n\ndef test_value():\n    assert value() == 1\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def value():\n    return 2\n")
    commit_all(repo, "change production only")
    write(repo / ".pr-test-guard.yml", "rules:\n  PTG001: error\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json", "--no-config"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["rule_id"] == "PTG001"
    assert payload["findings"][0]["severity"] == "warning"
    assert payload["policy"]["source"] is None


def test_github_output_uses_error_annotations_and_grouped_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_weak_mock_repo(tmp_path)
    summary = tmp_path / "summary.md"
    write(repo / ".pr-test-guard.yml", "policy:\n  fail_on: [PTG005]\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    code = main(["check", "--base", "HEAD~1", "--format", "github"])

    assert code == 1
    output = capsys.readouterr().out
    assert (
        "::error title=PR Test Guard / PTG005,file=tests/test_payment.py,line=4::[PTG005]"
        in output
    )
    rendered_summary = summary.read_text(encoding="utf-8")
    assert "### PTG003 (1 warning)" in rendered_summary
    assert "### PTG005 (1 error)" in rendered_summary
    assert "### Related Test Candidates" in rendered_summary
    assert "Configured policy failed" in rendered_summary


def test_github_annotation_limits_flow_from_config_without_truncating_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_weak_mock_repo(tmp_path)
    summary = tmp_path / "summary.md"
    outputs = tmp_path / "outputs.txt"
    report = tmp_path / "report.json"
    write(
        repo / ".pr-test-guard.yml",
        "policy:\n"
        "  fail_on: [PTG005]\n"
        "github:\n"
        "  annotations:\n"
        "    max_total: 1\n"
        "    max_per_rule: 1\n",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    code = main(
        [
            "check",
            "--base",
            "HEAD~1",
            "--format",
            "github",
            "--json-output",
            str(report),
        ]
    )

    assert code == 1
    output = capsys.readouterr().out
    annotation_lines = [line for line in output.splitlines() if line.startswith("::")]
    assert len(annotation_lines) == 1
    assert "::error title=PR Test Guard / PTG005" in annotation_lines[0]
    assert "1 annotation(s) emitted; 1 omitted; failed" in output

    summary_text = summary.read_text(encoding="utf-8")
    assert "PTG003=1" in summary_text
    assert "### PTG003 (1 warning)" in summary_text
    assert "### PTG005 (1 error)" in summary_text

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert {item["rule_id"] for item in payload["findings"]} == {"PTG003", "PTG005"}
    assert payload["policy"]["github"]["annotations"] == {
        "max_total": 1,
        "max_per_rule": 1,
    }
    assert outputs.read_text(encoding="utf-8").splitlines() == [
        "status=failed",
        "findings-count=2",
        "warning-count=1",
        "error-count=1",
    ]


def test_paths_ignore_suppresses_matching_findings(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_weak_mock_repo(tmp_path)
    write(repo / ".pr-test-guard.yml", "paths:\n  ignore:\n    - tests/**\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"] == []
    assert any("matching paths.ignore" in note for note in payload["notes"])


def test_custom_test_paths_drive_rules_related_context_and_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "payment.py", "def charge(amount):\n    return amount > 0\n")
    write(
        repo / "spec/payment_spec.py",
        "from payment import charge\n\ndef test_charge():\n    assert charge(1) is True\n",
    )
    commit_all(repo, "base")

    write(repo / "payment.py", "def charge(amount):\n    return amount >= 0\n")
    write(
        repo / "spec/payment_spec.py",
        "from unittest.mock import patch\nfrom payment import charge\n\n"
        "@patch('payment.charge')\n"
        "def test_charge(mock_charge):\n"
        "    mock_charge.return_value = True\n"
        "    result = charge(0)\n"
        "    assert result is not None\n",
    )
    write(
        repo / ".pr-test-guard.yml",
        "paths:\n"
        "  tests:\n"
        "    include:\n"
        "      - spec/**\n",
    )
    commit_all(repo, "change behavior and custom-layout test")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {item["rule_id"] for item in payload["findings"]} == {"PTG003", "PTG005"}
    assert payload["summary"]["production_files"] == 1
    assert payload["summary"]["test_files"] == 1
    assert payload["summary"]["related_tests"] == 1
    assert payload["related_tests"][0]["file"] == "spec/payment_spec.py"
    assert payload["policy"]["paths"]["tests"] == {
        "include": ["spec/**"],
        "exclude": [],
    }


def test_custom_test_path_excludes_override_built_in_detection(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "test_support.py", "def helper():\n    return 1\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def value():\n    return 2\n")
    write(repo / "test_support.py", "def helper():\n    return 2\n")
    write(
        repo / ".pr-test-guard.yml",
        "paths:\n"
        "  tests:\n"
        "    include: ['test_*.py']\n"
        "    exclude: ['test_support.py']\n",
    )
    commit_all(repo, "change production helpers")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "PTG001" in {item["rule_id"] for item in payload["findings"]}
    assert payload["summary"]["production_files"] == 2
    assert payload["summary"]["test_files"] == 0


def test_configured_source_test_mapping_adds_indirect_related_test_context(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src/payments/service.py", "def charge(amount):\n    return amount > 0\n")
    write(
        repo / "tests/integration/test_checkout.py",
        "def test_checkout_decline():\n    assert checkout_status() == 'declined'\n",
    )
    commit_all(repo, "base")

    write(repo / "src/payments/service.py", "def charge(amount):\n    return amount >= 0\n")
    write(
        repo / ".pr-test-guard.yml",
        "related_tests:\n"
        "  mappings:\n"
        "    - source: src/payments/**\n"
        "      tests:\n"
        "        - tests/integration/test_checkout.py\n",
    )
    commit_all(repo, "change payment boundary")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["related_tests"] == 1
    assert payload["related_tests"][0] == {
        "file": "tests/integration/test_checkout.py",
        "line": 1,
        "matched_sources": ["src/payments/service.py"],
        "matched_symbols": ["payments.service.charge"],
        "reasons": ["configured_path_mapping"],
        "test_name": "test_checkout_decline",
    }
    assert payload["policy"]["related_tests"]["mappings"] == [
        {
            "source": "src/payments/**",
            "tests": ["tests/integration/test_checkout.py"],
        }
    ]
    ptg001 = next(item for item in payload["findings"] if item["rule_id"] == "PTG001")
    assert "related_source(s)=src/payments/service.py" in ptg001["evidence"]


def test_related_test_mapping_merges_with_automatic_relationships(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "payment.py", "def charge(amount):\n    return amount > 0\n")
    write(
        repo / "tests/test_payment.py",
        "from payment import charge\n\ndef test_charge():\n    assert charge(1) is True\n",
    )
    commit_all(repo, "base")

    write(repo / "payment.py", "def charge(amount):\n    return amount >= 0\n")
    write(
        repo / ".pr-test-guard.yml",
        "related_tests:\n"
        "  mappings:\n"
        "    - source: payment.py\n"
        "      tests: tests/test_payment.py\n",
    )
    commit_all(repo, "change charge boundary")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["related_tests"] == 1
    candidate = payload["related_tests"][0]
    assert candidate["matched_sources"] == ["payment.py"]
    assert candidate["matched_symbols"] == ["payment.charge"]
    assert candidate["reasons"] == [
        "configured_path_mapping",
        "direct_call_changed_symbol",
        "imports_changed_symbol",
        "test_name_token",
    ]


def test_related_test_mapping_handles_changed_source_without_python_symbol(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "settings.py", "PAYMENT_TIMEOUT = 10\n")
    write(repo / "tests/test_settings.py", "def test_timeout_policy():\n    assert configured_timeout() == 10\n")
    commit_all(repo, "base")

    write(repo / "settings.py", "PAYMENT_TIMEOUT = 20\n")
    write(
        repo / ".pr-test-guard.yml",
        "related_tests:\n"
        "  mappings:\n"
        "    - source: settings.py\n"
        "      tests: [tests/test_settings.py]\n",
    )
    commit_all(repo, "change timeout")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    candidate = payload["related_tests"][0]
    assert candidate["matched_symbols"] == []
    assert candidate["matched_sources"] == ["settings.py"]
    assert candidate["reasons"] == ["configured_path_mapping"]


def test_related_test_mapping_respects_test_path_excludes(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/helpers/test_factory.py", "def test_factory():\n    assert True\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def value():\n    return 2\n")
    write(
        repo / ".pr-test-guard.yml",
        "paths:\n"
        "  tests:\n"
        "    exclude: [tests/helpers/**]\n"
        "related_tests:\n"
        "  mappings:\n"
        "    - source: app.py\n"
        "      tests: [tests/helpers/**]\n",
    )
    commit_all(repo, "change value")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["related_tests"] == []


@pytest.mark.parametrize(
    ("mapping_yaml", "expected"),
    [
        ("mappings: invalid", "must be a list"),
        ("mappings: [invalid]", "must be a mapping"),
        ("mappings: [{tests: [tests/**]}]", "source' must be a non-empty string"),
        ("mappings: [{source: '../src/**', tests: [tests/**]}]", "must not contain parent-directory"),
        ("mappings: [{source: 'src/**', tests: []}]", "must contain at least one path pattern"),
    ],
)
def test_invalid_related_test_mapping_returns_operational_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
    mapping_yaml: str,
    expected: str,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    commit_all(repo, "base")
    write(repo / ".pr-test-guard.yml", f"related_tests:\n  {mapping_yaml}\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD"])

    captured = capsys.readouterr()
    assert code == 2
    assert expected in captured.err


def test_no_config_ignores_custom_test_path_classification(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "spec/app_spec.py", "from app import value\n\ndef test_value():\n    assert value() == 1\n")
    commit_all(repo, "base")
    write(repo / "app.py", "def value():\n    return 2\n")
    write(repo / "spec/app_spec.py", "from app import value\n\ndef test_value():\n    assert value() == 2\n")
    commit_all(repo, "change")
    write(repo / ".pr-test-guard.yml", "paths:\n  tests:\n    include: [spec/**]\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json", "--no-config"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "PTG001" in {item["rule_id"] for item in payload["findings"]}
    assert payload["summary"]["test_files"] == 0


def test_invalid_custom_test_path_config_returns_operational_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    commit_all(repo, "base")
    write(repo / ".pr-test-guard.yml", "paths:\n  tests:\n    include: [../private/**]\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD"])

    captured = capsys.readouterr()
    assert code == 2
    assert "must not contain parent-directory segments" in captured.err


def test_invalid_config_returns_operational_error(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    commit_all(repo, "base")
    write(repo / "app.py", "def value():\n    return 2\n")
    commit_all(repo, "change")
    write(repo / ".pr-test-guard.yml", "rules:\n  PTG999: warn\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1"])

    captured = capsys.readouterr()
    assert code == 2
    assert "unknown rule id" in captured.err


def test_config_and_no_config_are_mutually_exclusive(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    commit_all(repo, "base")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD", "--config", ".pr-test-guard.yml", "--no-config"])

    captured = capsys.readouterr()
    assert code == 2
    assert "--config and --no-config" in captured.err


def test_check_can_write_json_output_alongside_text_report(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/test_app.py", "from app import value\n\ndef test_value():\n    assert value() == 1\n")
    commit_all(repo, "base")
    write(repo / "app.py", "def value():\n    return 2\n")
    commit_all(repo, "change production only")
    monkeypatch.chdir(repo)

    report_path = repo / "artifacts" / "pr-test-guard-report.json"
    code = main(["check", "--base", "HEAD~1", "--json-output", str(report_path)])

    assert code == 0
    assert "PR Test Guard" in capsys.readouterr().out
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["findings"] == 1
    assert payload["findings"][0]["rule_id"] == "PTG001"


def test_json_output_matches_policy_filtered_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_weak_mock_repo(tmp_path)
    write(repo / ".pr-test-guard.yml", "rules:\n  PTG003: off\npolicy:\n  fail_on: [PTG005]\n")
    monkeypatch.chdir(repo)

    report_path = repo / "report.json"
    code = main(["check", "--base", "HEAD~1", "--format", "json", "--json-output", str(report_path)])

    assert code == 1
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert file_payload == stdout_payload
    assert [item["rule_id"] for item in file_payload["findings"]] == ["PTG005"]
    assert file_payload["findings"][0]["severity"] == "error"


def test_github_format_can_also_write_json_output(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_weak_mock_repo(tmp_path)
    summary = tmp_path / "summary.md"
    report_path = repo / "ptg" / "report.json"
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    code = main(["check", "--base", "HEAD~1", "--format", "github", "--json-output", str(report_path)])

    assert code == 0
    assert "PR Test Guard:" in capsys.readouterr().out
    assert "## PR Test Guard" in summary.read_text(encoding="utf-8")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert {item["rule_id"] for item in payload["findings"]} == {"PTG003", "PTG005"}


def test_invalid_json_output_path_returns_operational_error(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    commit_all(repo, "base")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD", "--json-output", str(repo)])

    captured = capsys.readouterr()
    assert code == 2
    assert "unable to write JSON output" in captured.err


def test_action_supports_json_artifact_upload() -> None:
    action = yaml.safe_load(Path("action.yml").read_text(encoding="utf-8"))

    assert action["inputs"]["json-output"]["default"] == "pr-test-guard-report.json"
    assert action["inputs"]["upload-artifact"]["default"] == "false"
    assert action["inputs"]["artifact-name"]["default"] == "pr-test-guard-report"
    assert set(action["outputs"]) == {
        "status",
        "findings-count",
        "warning-count",
        "error-count",
        "report-path",
    }
    assert action["outputs"]["status"]["value"] == "${{ steps.check.outputs.status }}"
    assert action["outputs"]["report-path"]["value"] == "${{ steps.check.outputs.report-path }}"
    steps = action["runs"]["steps"]
    assert any(step.get("uses") == "actions/upload-artifact@v4" for step in steps)
    check_step = next(step for step in steps if step.get("id") == "check")
    assert 'echo "report-path=$INPUT_JSON_OUTPUT" >> "$GITHUB_OUTPUT"' in check_step["run"]
    assert 'echo "status=operational-error" >> "$GITHUB_OUTPUT"' in check_step["run"]
    assert 'echo "exit-code=2" >> "$GITHUB_OUTPUT"' in check_step["run"]
    assert steps[-1]["name"] == "Complete PR Test Guard"
