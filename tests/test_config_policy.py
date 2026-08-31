from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from pr_test_guard.cli import main


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
    assert "::error file=tests/test_payment.py,line=4::[PTG005]" in output
    rendered_summary = summary.read_text(encoding="utf-8")
    assert "### PTG003 (1 warning)" in rendered_summary
    assert "### PTG005 (1 error)" in rendered_summary
    assert "### Related Test Candidates" in rendered_summary
    assert "Configured policy failed" in rendered_summary


def test_paths_ignore_suppresses_matching_findings(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = make_weak_mock_repo(tmp_path)
    write(repo / ".pr-test-guard.yml", "paths:\n  ignore:\n    - tests/**\n")
    monkeypatch.chdir(repo)

    code = main(["check", "--base", "HEAD~1", "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"] == []
    assert any("matching paths.ignore" in note for note in payload["notes"])


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
    steps = action["runs"]["steps"]
    assert any(step.get("uses") == "actions/upload-artifact@v4" for step in steps)
    assert steps[-1]["name"] == "Complete PR Test Guard"
