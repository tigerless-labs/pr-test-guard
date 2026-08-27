from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pr_test_guard.check import analyze_repository
from pr_test_guard.reporters import render_json, render_text


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


def rule_ids(result) -> set[str]:
    return {item.rule_id for item in result.findings}


def test_missing_test_change_is_advisory_signal(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/test_app.py", "from app import value\n\ndef test_value():\n    assert value() == 1\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def value():\n    return 2\n")
    commit_all(repo, "change production only")

    result = analyze_repository(repo, base="HEAD~1")
    assert "PTG001" in rule_ids(result)
    finding = next(item for item in result.findings if item.rule_id == "PTG001")
    assert "related_test_candidates=1" in (finding.evidence or "")
    assert result.related_tests[0].matched_symbols == ("app.value",)
    assert set(result.related_tests[0].reasons) == {
        "direct_call_changed_symbol",
        "imports_changed_symbol",
        "test_name_token",
    }
    assert "Related test candidates: 1" in render_text(result)
    assert '"related_tests"' in render_json(result)


def test_related_context_tracks_module_import_without_direct_call(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "service.py", "def charge(amount):\n    return amount > 0\n")
    write(repo / "tests/test_service.py", "import service\n\n\ndef test_service_imports():\n    assert service is not None\n")
    commit_all(repo, "base")

    write(repo / "service.py", "def charge(amount):\n    return amount >= 0\n")
    commit_all(repo, "change production only")

    result = analyze_repository(repo, base="HEAD~1")

    assert len(result.related_tests) == 1
    related = result.related_tests[0]
    assert related.test_name == "test_service_imports"
    assert related.matched_symbols == ("service.charge",)
    assert related.reasons == ("imports_changed_module", "test_name_token")


def test_related_context_ignores_same_token_from_different_module(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "payment.py", "def charge(amount):\n    return amount > 0\n")
    write(repo / "email.py", "def charge(message):\n    return True\n")
    write(repo / "tests/test_email.py", "from email import charge\n\n\ndef test_charge():\n    assert charge('hello') is True\n")
    commit_all(repo, "base")

    write(repo / "payment.py", "def charge(amount):\n    return amount >= 0\n")
    commit_all(repo, "change payment")

    result = analyze_repository(repo, base="HEAD~1")

    assert result.related_tests == []
    finding = next(item for item in result.findings if item.rule_id == "PTG001")
    assert "related_test_candidates=0" in (finding.evidence or "")


def test_weak_assertion_and_mock_boundary_are_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "payment.py", "def charge(amount):\n    return amount > 0\n")
    write(
        repo / "tests/test_payment.py",
        "from payment import charge\n\ndef test_charge():\n    assert charge(1) is True\n",
    )
    commit_all(repo, "base")

    write(repo / "payment.py", "def charge(amount):\n    return amount >= 0\n")
    write(
        repo / "tests/test_payment.py",
        "from unittest.mock import patch\nfrom payment import charge\n\n"
        "@patch('payment.charge')\ndef test_charge(mock_charge):\n    mock_charge.return_value = True\n    result = charge(0)\n    assert result is not None\n",
    )
    commit_all(repo, "change behavior and test")

    result = analyze_repository(repo, base="HEAD~1")
    ids = rule_ids(result)
    assert "PTG003" in ids
    assert "PTG005" in ids
    weak = next(item for item in result.findings if item.rule_id == "PTG003")
    assert "related_symbol(s)=payment.charge" in (weak.evidence or "")


def test_test_skip_is_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/test_app.py", "from app import value\n\ndef test_value():\n    assert value() == 1\n")
    commit_all(repo, "base")

    write(
        repo / "tests/test_app.py",
        "import pytest\nfrom app import value\n\n@pytest.mark.skip(reason='later')\ndef test_value():\n    assert value() == 1\n",
    )
    commit_all(repo, "skip test")

    result = analyze_repository(repo, base="HEAD~1")
    assert "PTG004" in rule_ids(result)


def test_uncovered_changed_line_uses_supplied_coverage(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/test_app.py", "from app import value\n\ndef test_value():\n    assert value() == 1\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def value():\n    if True:\n        return 2\n")
    write(repo / "tests/test_app.py", "from app import value\n\ndef test_value():\n    assert value() == 2\n")
    commit_all(repo, "change")

    coverage = repo / "coverage.xml"
    coverage.write_text(
        "<?xml version='1.0' ?><coverage><packages><package><classes>"
        "<class filename='app.py'><lines>"
        "<line number='1' hits='1'/><line number='2' hits='0'/><line number='3' hits='0'/>"
        "</lines></class></classes></package></packages></coverage>",
        encoding="utf-8",
    )

    result = analyze_repository(repo, base="HEAD~1", coverage_path="coverage.xml")
    assert "PTG002" in rule_ids(result)


def test_targeted_probe_survivor_runs_in_isolated_worktree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def status(ok):\n    return 400\n")
    write(repo / "tests/test_app.py", "from app import status\n\ndef test_status():\n    assert status(False) is not None\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def status(ok):\n    if not ok:\n        return 400\n    return 200\n")
    write(repo / "tests/test_app.py", "from app import status\n\ndef test_status():\n    assert status(False) is not None\n")
    commit_all(repo, "add branch")

    result = analyze_repository(
        repo,
        base="HEAD~1",
        deep=True,
        test_command=f"{sys.executable} -m pytest -q",
        max_probes=1,
    )
    assert "PTG006" in rule_ids(result)
    assert result.probe_summary["baseline_passed"] is True
    assert result.probe_summary["survived"] == 1
    findings = [item for item in result.findings if item.rule_id == "PTG006"]
    assert len(findings) == 1
    evidence = findings[0].evidence or ""
    assert "baseline_passed=true" in evidence
    assert "probe_id=P1" in evidence
    assert "kind=return_status_code" in evidence
    assert "mutation=return 400 -> return 200" in evidence
    assert "related_test_candidates=1" in evidence
    assert run_worktree_list(repo) == 1


def test_strong_status_assertion_kills_targeted_probe(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def status(ok):\n    return 400\n")
    write(repo / "tests/test_app.py", "from app import status\n\ndef test_status():\n    assert status(False) == 400\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def status(ok):\n    if not ok:\n        return 400\n    return 200\n")
    write(
        repo / "tests/test_app.py",
        "from app import status\n\n"
        "def test_status():\n    assert status(False) == 400\n\n"
        "def test_success_status():\n    assert status(True) == 200\n",
    )
    commit_all(repo, "add branch")

    result = analyze_repository(
        repo,
        base="HEAD~1",
        deep=True,
        test_command=f"{sys.executable} -m pytest -q",
        max_probes=1,
    )
    assert "PTG006" not in rule_ids(result)
    assert result.probe_summary["baseline_passed"] is True
    assert result.probe_summary["generated"] == 1
    assert result.probe_summary["applied"] == 1
    assert result.probe_summary["survived"] == 0
    assert run_worktree_list(repo) == 1


def test_targeted_probe_skips_when_baseline_command_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def status():\n    return 200\n")
    write(repo / "tests/test_app.py", "from app import status\n\ndef test_status():\n    assert status() == 200\n")
    commit_all(repo, "base")

    write(repo / "app.py", "def status():\n    return 404\n")
    write(repo / "tests/test_app.py", "from app import status\n\ndef test_status():\n    assert status() == 200\n")
    commit_all(repo, "break status")

    result = analyze_repository(
        repo,
        base="HEAD~1",
        deep=True,
        test_command=f"{sys.executable} -m pytest -q",
        max_probes=1,
    )
    assert "PTG006" not in rule_ids(result)
    assert result.probe_summary["baseline_passed"] is False
    assert result.probe_summary["generated"] == 1
    assert result.probe_summary["applied"] == 0
    assert result.probe_summary["survived"] == 0
    assert "PTG006 skipped: the configured test command fails on the unmodified PR checkout." in result.notes
    assert run_worktree_list(repo) == 1


def test_targeted_probe_respects_max_probes_limit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def missing():\n    return 404\n\ndef forbidden():\n    return 403\n")
    write(
        repo / "tests/test_app.py",
        "from app import forbidden, missing\n\n"
        "def test_statuses():\n    assert missing() is not None\n    assert forbidden() is not None\n",
    )
    commit_all(repo, "base")

    write(repo / "app.py", "def missing():\n    return 404\n\ndef forbidden():\n    return 403\n\ndef changed():\n    return True\n")
    write(
        repo / "tests/test_app.py",
        "from app import changed, forbidden, missing\n\n"
        "def test_statuses():\n    assert missing() is not None\n    assert forbidden() is not None\n    assert changed() is not None\n",
    )
    commit_all(repo, "add changed probes")

    result = analyze_repository(
        repo,
        base="HEAD~1",
        deep=True,
        test_command=f"{sys.executable} -m pytest -q",
        max_probes=1,
    )
    assert result.probe_summary["generated"] == 1
    assert result.probe_summary["applied"] == 1
    assert result.probe_summary["survived"] == 1
    assert len([item for item in result.findings if item.rule_id == "PTG006"]) == 1
    assert run_worktree_list(repo) == 1


def run_worktree_list(repo: Path) -> int:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return sum(1 for line in result.stdout.splitlines() if line.startswith("worktree "))


def test_skip_text_inside_fixture_string_is_not_a_real_skip(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "app.py", "def value():\n    return 1\n")
    write(repo / "tests/test_meta.py", "def test_meta():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "tests/test_meta.py",
        "def test_meta():\n"
        "    sample = \"@pytest.mark.skip(reason='example only')\"\n"
        "    assert sample\n",
    )
    commit_all(repo, "fixture string")

    result = analyze_repository(repo, base="HEAD~1")
    assert "PTG004" not in rule_ids(result)
