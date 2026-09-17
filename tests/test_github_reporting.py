from __future__ import annotations

from pathlib import Path

from pr_test_guard.check import AnalysisResult
from pr_test_guard.finding import Finding
from pr_test_guard.reporters import emit_github, github_summary, render_json


def make_result(
    tmp_path: Path,
    findings: list[Finding],
    *,
    max_total: int = 50,
    max_per_rule: int = 10,
) -> AnalysisResult:
    return AnalysisResult(
        repo_root=tmp_path,
        base="origin/main",
        head="abc123",
        files=[],
        findings=findings,
        notes=[],
        probe_summary={},
        related_tests=[],
        policy={
            "source": None,
            "policy": {"fail_on": []},
            "github": {
                "annotations": {
                    "max_total": max_total,
                    "max_per_rule": max_per_rule,
                }
            },
        },
    )


def finding(
    rule_id: str,
    *,
    severity: str = "warning",
    file: str = "tests/test_app.py",
    line: int = 1,
    message: str = "review this signal",
    evidence: str | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        file=file,
        line=line,
        message=message,
        evidence=evidence,
    )


def test_github_annotation_has_stable_title_and_property_escaping(tmp_path: Path) -> None:
    result = make_result(
        tmp_path,
        [
            finding(
                "PTG003",
                file="tests/a,b:c%.py",
                line=7,
                message="value %, needs review\nnext line",
            )
        ],
    )

    output = emit_github(result)

    assert output.splitlines()[0] == (
        "::warning title=PR Test Guard / PTG003,"
        "file=tests/a%2Cb%3Ac%25.py,line=7::"
        "[PTG003] value %25, needs review%0Anext line"
    )


def test_github_annotation_limits_prioritize_errors_and_report_omissions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    findings = [
        finding("PTG003", line=3, message="warning three"),
        finding("PTG003", line=1, message="warning one"),
        finding("PTG003", line=2, message="warning two"),
        finding("PTG005", severity="error", line=5, message="error five"),
        finding("PTG005", severity="error", line=4, message="error four"),
    ]
    result = make_result(tmp_path, findings, max_total=2, max_per_rule=1)
    summary_path = tmp_path / "summary.md"
    output_path = tmp_path / "outputs.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    output = emit_github(result)

    annotation_lines = [line for line in output.splitlines() if line.startswith("::")]
    assert len(annotation_lines) == 2
    assert annotation_lines[0] == (
        "::error title=PR Test Guard / PTG005,file=tests/test_app.py,line=4::"
        "[PTG005] error four"
    )
    assert annotation_lines[1] == (
        "::warning title=PR Test Guard / PTG003,file=tests/test_app.py,line=1::"
        "[PTG003] warning one"
    )
    assert "2 annotation(s) emitted; 3 omitted; failed" in output

    summary = summary_path.read_text(encoding="utf-8")
    assert "**Annotations:** 2 emitted, 3 omitted by configured limits." in summary
    assert "PTG003=2, PTG005=1" in summary
    assert "The tables and JSON report retain every finding." in summary
    assert summary.count("warning ") >= 3
    assert '"findings": 5' in render_json(result)

    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "status=failed",
        "findings-count=5",
        "warning-count=3",
        "error-count=2",
    ]


def test_zero_annotation_limit_keeps_summary_and_json_findings(tmp_path: Path) -> None:
    result = make_result(
        tmp_path,
        [finding("PTG001"), finding("PTG003")],
        max_total=0,
        max_per_rule=0,
    )

    output = emit_github(result)
    summary = github_summary(result)

    assert not any(line.startswith("::") for line in output.splitlines())
    assert "0 annotation(s) emitted; 2 omitted; advisory" in output
    assert "**2 review signal(s)**" in summary
    assert "PTG001=1, PTG003=1" in summary
    assert '"findings": 2' in render_json(result)


def test_clean_github_result_exports_clean_status(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "outputs.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    output = emit_github(make_result(tmp_path, []))

    assert "0 annotation(s) emitted; 0 omitted; clean" in output
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "status=clean",
        "findings-count=0",
        "warning-count=0",
        "error-count=0",
    ]
