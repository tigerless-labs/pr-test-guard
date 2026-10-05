from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pr_test_guard.check import CheckError, analyze_repository
from pr_test_guard.cli import build_parser
from pr_test_guard.per_test_coverage import (
    canonical_test_id,
    parse_coverage_contexts,
    parse_pytest_context,
)
from pr_test_guard.reporters import github_summary, render_json, render_text


def run(*args: str, cwd: Path) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.name", "Test User", cwd=repo)
    run("git", "config", "user.email", "test@example.com", cwd=repo)
    write(
        repo / "pricing.py",
        "def calculate(kind):\n"
        "    if kind == 'vip':\n"
        "        return 80\n"
        "    return 100\n",
    )
    write(
        repo / "tests/test_pricing.py",
        "from pricing import calculate\n\n"
        "def test_normal_price():\n"
        "    assert calculate('normal') == 100\n\n"
        "def test_vip_price():\n"
        "    assert calculate('vip') == 80\n",
    )
    run("git", "add", "-A", cwd=repo)
    run("git", "commit", "-m", "base", cwd=repo)
    write(
        repo / "pricing.py",
        "def calculate(kind):\n"
        "    if kind == 'vip':\n"
        "        return 75\n"
        "    return 100\n",
    )
    run("git", "add", "-A", cwd=repo)
    run("git", "commit", "-m", "change vip price", cwd=repo)
    return repo


def context_payload(
    *,
    line_contexts: dict[str, list[str]],
    file_name: str = "pricing.py",
) -> dict[str, object]:
    executed = sorted(int(line) for line in line_contexts)
    return {
        "meta": {"format": 3, "version": "7.10.0", "show_contexts": True},
        "files": {
            file_name: {
                "executed_lines": executed,
                "missing_lines": sorted({1, 2, 3, 4} - set(executed)),
                "excluded_lines": [],
                "contexts": line_contexts,
            }
        },
    }


def rule_ids(result) -> list[str]:
    return [item.rule_id for item in result.findings]


def test_parser_preserves_parameter_ids_and_execution_phases(tmp_path: Path) -> None:
    artifact = tmp_path / "coverage-contexts.json"
    write_json(
        artifact,
        context_payload(
            file_name=r"C:\work\repo\src\pricing.py",
            line_contexts={
                "3": [
                    r"tests\test_pricing.py::test_discount[vip]|setup",
                    r"tests\test_pricing.py::test_discount[vip]|run",
                    r"tests\test_pricing.py::test_discount[vip]|teardown",
                    r"tests\test_pricing.py::test_discount[normal]|run",
                ]
            },
        ),
    )

    report = parse_coverage_contexts(artifact)
    mapped, issue = report.matching_file("src/pricing.py")

    assert issue is None
    assert mapped is not None
    assert mapped.file == "C:/work/repo/src/pricing.py"
    assert {item.test_id for item in report.executions} == {
        "tests/test_pricing.py::test_discount[vip]",
        "tests/test_pricing.py::test_discount[normal]",
    }
    assert {item.phase for item in report.executions} == {"setup", "run", "teardown"}
    assert canonical_test_id("tests/test_pricing.py::test_discount[vip]") == (
        "tests/test_pricing.py::test_discount"
    )
    dynamic = report.evidence_for(
        repo_file="src/pricing.py",
        changed_lines=(3,),
        related_test_ids=("tests/test_pricing.py::test_discount",),
    )
    assert dynamic.status == "observed"
    assert dynamic.observed_related_tests == (
        "tests/test_pricing.py::test_discount[normal]",
        "tests/test_pricing.py::test_discount[vip]",
    )
    assert dynamic.execution_phases == ("run", "setup", "teardown")


@pytest.mark.parametrize(
    "file_name",
    [
        "pricing.py",
        "./src/pricing.py",
        "/work/repo/pricing.py",
        r"C:\work\repo\pricing.py",
    ],
)
def test_context_path_normalization_maps_supported_shapes(
    tmp_path: Path, file_name: str
) -> None:
    artifact = tmp_path / "contexts.json"
    write_json(artifact, context_payload(file_name=file_name, line_contexts={"3": []}))
    mapped, issue = parse_coverage_contexts(artifact).matching_file("pricing.py")
    assert mapped is not None
    assert issue is None


def test_unknown_context_is_recorded_not_interpreted_as_pytest() -> None:
    assert parse_pytest_context("worker-17") is None
    assert parse_pytest_context("tests/test_x.py::test_x|unknown") is None


def test_positive_mapping_adds_structured_dynamic_evidence(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_json(
        repo / "contexts.json",
        context_payload(
            line_contexts={
                "2": [
                    "tests/test_pricing.py::test_normal_price|run",
                    "tests/test_pricing.py::test_vip_price|run",
                ],
                "3": ["tests/test_pricing.py::test_vip_price|run"],
                "4": ["tests/test_pricing.py::test_normal_price|run"],
            }
        ),
    )

    result = analyze_repository(
        repo, base="HEAD~1", coverage_contexts_path="contexts.json"
    )
    dynamic = result.change_units[0].dynamic_test_evidence

    assert dynamic is not None
    assert dynamic.status == "observed"
    assert dynamic.executed_changed_lines == (3,)
    assert dynamic.unexecuted_changed_lines == ()
    assert dynamic.executing_tests[0].test_id.endswith("::test_vip_price")
    assert "PTG010" not in rule_ids(result)
    payload = json.loads(render_json(result))
    structured = payload["change_units"][0]["dynamic_test_evidence"]
    assert structured["executing_tests"][0]["phase"] == "run"
    assert payload["change_units"][0]["evidence_labels"]["dynamic"] == [
        "tests/test_pricing.py::test_vip_price"
    ]
    assert "Observed runtime executor" in render_text(result)
    summary = github_summary(result)
    assert "Per-Test Dynamic Evidence" in summary
    assert "| Test | Changed target(s) | Reason(s) |" in summary
    assert summary.index("### Related Test Candidates") < summary.index(
        "### Per-Test Dynamic Evidence"
    )


def test_related_test_that_misses_changed_lines_emits_ptg010(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_json(
        repo / "contexts.json",
        context_payload(
            line_contexts={
                "2": ["tests/test_pricing.py::test_normal_price|run"],
                "4": ["tests/test_pricing.py::test_normal_price|run"],
            }
        ),
    )

    result = analyze_repository(
        repo, base="HEAD~1", coverage_contexts_path="contexts.json"
    )
    findings = [item for item in result.findings if item.rule_id == "PTG010"]

    # test_vip_price is also a deterministic source-level caller but was not
    # run, so this artifact cannot establish that all related tests missed the
    # change. The rule must stay inconclusive.
    assert findings == []
    assert result.change_units[0].dynamic_test_evidence is not None
    assert result.change_units[0].dynamic_test_evidence.status == "inconclusive"


def test_all_observed_related_tests_miss_changed_lines_emits_ptg010(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_json(
        repo / "contexts.json",
        context_payload(
            line_contexts={
                "2": [
                    "tests/test_pricing.py::test_normal_price|run",
                    "tests/test_pricing.py::test_vip_price|run",
                ],
                "4": [
                    "tests/test_pricing.py::test_normal_price|run",
                    "tests/test_pricing.py::test_vip_price|run",
                ],
            }
        ),
    )

    result = analyze_repository(
        repo, base="HEAD~1", coverage_contexts_path="contexts.json"
    )

    assert rule_ids(result).count("PTG010") == 1
    assert "PTG008" not in rule_ids(result)
    finding = next(item for item in result.findings if item.rule_id == "PTG010")
    assert finding.severity == "warning"
    assert "overlap=none" in (finding.evidence or "")


def test_one_of_several_related_tests_executes_changed_line(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_json(
        repo / "contexts.json",
        context_payload(
            line_contexts={
                "2": [
                    "tests/test_pricing.py::test_normal_price|run",
                    "tests/test_pricing.py::test_vip_price|run",
                ],
                "3": ["tests/test_pricing.py::test_vip_price|run"],
                "4": ["tests/test_pricing.py::test_normal_price|run"],
            }
        ),
    )

    result = analyze_repository(
        repo, base="HEAD~1", coverage_contexts_path="contexts.json"
    )

    assert "PTG010" not in rule_ids(result)
    dynamic = result.change_units[0].dynamic_test_evidence
    assert dynamic is not None
    assert dynamic.nonexecuting_related_tests == (
        "tests/test_pricing.py::test_normal_price",
    )


def test_no_contexts_preserves_existing_rule_behavior(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = analyze_repository(repo, base="HEAD~1")
    assert "PTG010" not in rule_ids(result)
    assert result.change_units[0].dynamic_test_evidence is None
    assert result.coverage_contexts_summary["status"] == "not_provided"


def test_unresolved_context_makes_ptg010_inconclusive(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    payload = context_payload(
        line_contexts={
            "2": [
                "tests/test_pricing.py::test_normal_price|run",
                "tests/test_pricing.py::test_vip_price|run",
                "not-a-pytest-context",
            ],
            "4": [
                "tests/test_pricing.py::test_normal_price|run",
                "tests/test_pricing.py::test_vip_price|run",
            ],
        }
    )
    write_json(repo / "contexts.json", payload)

    result = analyze_repository(
        repo, base="HEAD~1", coverage_contexts_path="contexts.json"
    )

    assert "PTG010" not in rule_ids(result)
    assert result.coverage_contexts_summary["status"] == "inconclusive"
    assert result.coverage_contexts_summary["unresolved_contexts"] == [
        "not-a-pytest-context"
    ]


def test_incomplete_context_artifact_cannot_emit_ptg010(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    payload = context_payload(
        line_contexts={
            "2": [
                "tests/test_pricing.py::test_normal_price|run",
                "tests/test_pricing.py::test_vip_price|run",
            ],
            "4": [
                "tests/test_pricing.py::test_normal_price|run",
                "tests/test_pricing.py::test_vip_price|run",
            ],
        }
    )
    meta = payload["meta"]
    assert isinstance(meta, dict)
    meta["show_contexts"] = False
    write_json(repo / "contexts.json", payload)

    result = analyze_repository(
        repo, base="HEAD~1", coverage_contexts_path="contexts.json"
    )

    assert "PTG010" not in rule_ids(result)
    assert result.coverage_contexts_summary["status"] == "inconclusive"
    assert result.coverage_contexts_summary["issues"] == [
        "meta.show_contexts_is_not_true"
    ]


def test_malformed_json_is_an_operational_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "contexts.json", "{not-json")
    with pytest.raises(CheckError, match="coverage contexts JSON is malformed"):
        analyze_repository(
            repo, base="HEAD~1", coverage_contexts_path="contexts.json"
        )


def test_cli_exposes_opt_in_coverage_context_input() -> None:
    parsed = build_parser().parse_args(
        ["check", "--coverage", "coverage.xml", "--coverage-contexts", "contexts.json"]
    )
    assert parsed.coverage == "coverage.xml"
    assert parsed.coverage_contexts == "contexts.json"
