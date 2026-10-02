from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pr_test_guard.change_evidence import AssertionFlow, ChangeUnit
from pr_test_guard.check import AnalysisResult, FileDiff, analyze_repository
from pr_test_guard.rollback_probes import RollbackProbe


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


def findings(result, rule_id: str):
    return [item for item in result.findings if item.rule_id == rule_id]


def test_change_evidence_json_contract(tmp_path: Path) -> None:
    unit = ChangeUnit(
        id="CU1",
        file="service.py",
        symbol="service.process",
        line=1,
        changed_lines=(2,),
        behavior_kinds=("return",),
        related_tests=("tests/test_service.py::test_process",),
        directly_exercising_tests=("tests/test_service.py::test_process",),
        indirectly_exercising_tests=(),
        mock_replacement_tests=(),
        constrained_tests=("tests/test_service.py::test_process",),
        unconstrained_tests=(),
    )
    flow = AssertionFlow(
        file="tests/test_service.py",
        test_name="test_process",
        line=3,
        symbol="service.process",
        call_lines=(4,),
        assertion_lines=(5,),
        constrained=True,
        reason="changed_result_reaches_meaningful_assertion",
    )
    probe = RollbackProbe(
        id="R1",
        file="service.py",
        symbol="service.process",
        start_line=1,
        end_line=2,
        current_source="def process():\n    return 2\n",
        base_source="def process():\n    return 1\n",
        confirmed_tests=("tests/test_service.py::test_process",),
    )
    result = AnalysisResult(
        repo_root=tmp_path,
        base="main",
        head="abc123",
        files=[FileDiff(path="service.py")],
        findings=[],
        notes=[],
        probe_summary={},
        related_tests=[],
        change_units=[unit],
        assertion_flows=[flow],
        rollback_summary={"generated": 1},
    )

    assert ChangeUnit.to_dict(unit)["indirectly_exercising_tests"] == []
    assert AssertionFlow.to_dict(flow)["assertion_lines"] == [5]
    assert flow.test_ref == "tests/test_service.py::test_process"
    assert RollbackProbe.to_dict(probe)["confirmed_tests"] == [
        "tests/test_service.py::test_process"
    ]
    assert AnalysisResult.to_dict(result)["summary"]["change_units"] == 1


def test_each_changed_function_gets_its_own_test_evidence_state(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "def first(value):\n    return value > 0\n\n"
        "def second(value):\n    return value > 0\n",
    )
    write(
        repo / "tests/test_service.py",
        "from service import first\n\n"
        "def test_first():\n    assert first(1) is True\n",
    )
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "def first(value):\n    return value >= 0\n\n"
        "def second(value):\n    return value >= 0\n",
    )
    commit_all(repo, "change two behaviors")

    result = analyze_repository(repo, base="HEAD~1")

    assert [unit.symbol for unit in result.change_units] == ["service.first", "service.second"]
    first, second = result.change_units
    assert first.directly_exercising_tests == ("tests/test_service.py::test_first",)
    assert first.changed_lines == (2,)
    assert second.directly_exercising_tests == ()
    assert second.changed_lines == (5,)
    gaps = findings(result, "PTG007")
    assert len(gaps) == 1
    assert "symbol=service.second" in (gaps[0].evidence or "")


def test_class_container_change_is_not_treated_as_direct_call_behavior(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "settings.py", "class Settings:\n    timeout = 1\n")
    write(repo / "tests/test_settings.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(repo / "settings.py", "class Settings:\n    timeout = 2\n")
    commit_all(repo, "change class data")

    result = analyze_repository(repo, base="HEAD~1")

    assert result.change_units == []
    assert findings(result, "PTG007") == []


def test_direct_test_evidence_propagates_to_changed_internal_helper(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "def _normalize(value):\n    return value\n\n"
        "def process(value):\n    return _normalize(value)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from service import process\n\n"
        "def test_process():\n    assert process('x') == 'x'\n",
    )
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "def _normalize(value):\n    return value.strip()\n\n"
        "def process(value):\n    return _normalize(value)\n",
    )
    commit_all(repo, "change helper behind public path")

    result = analyze_repository(repo, base="HEAD~1")

    units = {unit.symbol: unit for unit in result.change_units}
    assert "service.process" not in units
    assert units["service._normalize"].directly_exercising_tests == ()
    assert units["service._normalize"].indirectly_exercising_tests == (
        "tests/test_service.py::test_process",
    )
    assert findings(result, "PTG007") == []


def test_assertion_flow_distinguishes_observed_and_unobserved_results(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "pricing.py", "def calculate(amount):\n    return {'amount': amount}\n")
    write(
        repo / "tests/test_pricing.py",
        "from pricing import calculate\n\n"
        "def test_placeholder():\n    assert calculate(10)['amount'] == 10\n",
    )
    commit_all(repo, "base")

    write(repo / "pricing.py", "def calculate(amount):\n    return {'amount': amount + 2}\n")
    write(
        repo / "tests/test_pricing.py",
        "from pricing import calculate\n\n"
        "def test_amount():\n"
        "    result = calculate(10)\n"
        "    amount = result['amount']\n"
        "    assert amount == 12\n\n"
        "def test_only_exists():\n"
        "    result = calculate(10)\n"
        "    assert result is not None\n",
    )
    commit_all(repo, "change price and tests")

    result = analyze_repository(repo, base="HEAD~1")

    flows = {flow.test_name: flow for flow in result.assertion_flows}
    assert flows["test_amount"].constrained is True
    assert flows["test_amount"].assertion_lines == (6,)
    assert flows["test_only_exists"].constrained is False
    assert flows["test_only_exists"].reason == "changed_result_reaches_weak_assertion"
    weak = findings(result, "PTG008")
    assert len(weak) == 1
    assert weak[0].file == "tests/test_pricing.py"
    assert "test=test_only_exists" in (weak[0].evidence or "")


def test_assertion_flow_breaks_on_reassignment_and_accepts_expected_exception(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "parser.py", "def parse(value):\n    return int(value)\n")
    write(
        repo / "tests/test_parser.py",
        "import pytest\nfrom parser import parse\n\n"
        "def test_parse():\n    assert parse('1') == 1\n",
    )
    commit_all(repo, "base")

    write(repo / "parser.py", "def parse(value):\n    return int(value.strip())\n")
    write(
        repo / "tests/test_parser.py",
        "import pytest\nfrom parser import parse\n\n"
        "def test_overwritten_result():\n"
        "    result = parse(' 1 ')\n"
        "    result = 1\n"
        "    assert result == 1\n\n"
        "def test_invalid_value():\n"
        "    with pytest.raises(ValueError):\n"
        "        parse('bad')\n",
    )
    commit_all(repo, "change parser and tests")

    result = analyze_repository(repo, base="HEAD~1")

    flows = {flow.test_name: flow for flow in result.assertion_flows}
    assert flows["test_overwritten_result"].constrained is False
    assert flows["test_overwritten_result"].reason == "changed_result_not_observed_by_assertion"
    assert flows["test_invalid_value"].constrained is True
    assert flows["test_invalid_value"].reason == "changed_call_constrained_by_expected_exception"
    weak = findings(result, "PTG008")
    assert len(weak) == 1
    assert "test=test_overwritten_result" in (weak[0].evidence or "")


def test_base_behavior_rollback_survivor_is_reported(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "limits.py", "def allowed(value):\n    return value < 10\n")
    write(
        repo / "tests/test_limits.py",
        "from limits import allowed\n\n"
        "def test_allowed():\n    assert allowed(5) is True\n",
    )
    commit_all(repo, "base")

    write(repo / "limits.py", "def allowed(value):\n    return value <= 10\n")
    commit_all(repo, "include boundary")

    result = analyze_repository(
        repo,
        base="HEAD~1",
        deep=True,
        test_command=f"{sys.executable} -m pytest -q",
        max_probes=1,
    )

    rollback = findings(result, "PTG009")
    assert len(rollback) == 1
    assert "symbol=limits.allowed" in (rollback[0].evidence or "")
    assert result.rollback_summary["baseline_passed"] is True
    assert result.rollback_summary["survived"] == 1
    assert result.rollback_summary["killed"] == 0


def test_base_behavior_rollback_is_killed_by_boundary_assertion(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "limits.py", "def allowed(value):\n    return value < 10\n")
    write(
        repo / "tests/test_limits.py",
        "from limits import allowed\n\n"
        "def test_allowed():\n    assert allowed(5) is True\n",
    )
    commit_all(repo, "base")

    write(repo / "limits.py", "def allowed(value):\n    return value <= 10\n")
    write(
        repo / "tests/test_limits.py",
        "from limits import allowed\n\n"
        "def test_boundary():\n    assert allowed(10) is True\n",
    )
    commit_all(repo, "include and test boundary")

    result = analyze_repository(
        repo,
        base="HEAD~1",
        deep=True,
        test_command=f"{sys.executable} -m pytest -q",
        max_probes=1,
    )

    assert findings(result, "PTG009") == []
    assert result.rollback_summary["baseline_passed"] is True
    assert result.rollback_summary["survived"] == 0
    assert result.rollback_summary["killed"] == 1
