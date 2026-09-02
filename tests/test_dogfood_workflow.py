from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sanitize_module = load_script("sanitize_dogfood_review.py")
summary_module = load_script("summarize_dogfood_reviews.py")
draft_module = load_script("draft_dogfood_review.py")


def test_draft_review_from_check_report_preserves_local_review_context() -> None:
    report = {
        "base": "HEAD~1",
        "head": "abc123",
        "summary": {"changed_files": 2, "production_files": 1, "test_files": 1, "findings": 2},
        "notes": ["PTG002 skipped: no coverage XML was provided."],
        "probes": {"enabled": True, "generated": 1, "applied": 1, "survived": 1, "baseline_passed": True},
        "findings": [
            {
                "rule_id": "PTG005",
                "severity": "warning",
                "file": "tests/payments/test_private_gateway.py",
                "line": 12,
                "message": "Mock overlaps changed code.",
                "evidence": "relationship_type=internal_dependency_mock; changed owner symbol=PrivatePaymentService.charge",
            },
            {
                "rule_id": "PTG006",
                "severity": "warning",
                "file": "payments/service.py",
                "line": 9,
                "message": "A bounded targeted probe survived.",
                "evidence": "baseline_passed=true; kind=comparison_boundary; mutation=>= -> >",
            },
        ],
    }

    draft = draft_module.draft_review(
        report,
        review_id="review_123",
        repo_alias="repo_123",
        pr_alias="pr_456",
        test_framework="pytest",
        test_command_shape="pytest",
    )

    assert draft["source"]["repo_alias"] == "repo_123"
    assert draft["environment"] == {
        "language": "python",
        "test_framework": "pytest",
        "coverage_supplied": False,
        "deep_enabled": True,
        "test_command_shape": "pytest",
    }
    assert draft["findings"][0]["review_label"] == "needs_more_context"
    assert draft["findings"][0]["path_kind"] == "test"
    assert draft["findings"][0]["dependency_kind"] == "internal"
    assert draft["findings"][0]["evidence_shape"] == "changed test mocks dependency called from changed line"
    assert draft["findings"][1]["path_kind"] == "production"
    assert draft["findings"][1]["evidence_shape"] == "comparison boundary probe survived configured tests"

    sanitized = sanitize_module.sanitize_review(draft)
    rendered = json.dumps(sanitized)
    assert "PrivatePaymentService" not in rendered
    assert "test_private_gateway.py" not in rendered


def test_sanitize_review_drops_repository_specific_details() -> None:
    raw = {
        "review_id": "real_review_001",
        "repo_url": "https://github.com/example/private-repo",
        "pr_url": "https://github.com/example/private-repo/pull/123",
        "repo_alias": "repo_123",
        "pr_alias": "pr_456",
        "test_command": "pytest tests/private_payment_flow.py -q",
        "environment": {
            "language": "python",
            "test_framework": "pytest",
            "coverage_supplied": True,
            "deep_enabled": True,
        },
        "findings": [
            {
                "rule_id": "PTG005",
                "label": "false_positive",
                "category": "Legitimate Internal Helper Mock",
                "file": "tests/payments/test_private_gateway.py",
                "symbol": "PrivatePaymentService.charge",
                "dependency": "private_gateway.client.create",
                "evidence": "changed symbol=private.payment.PrivatePaymentService.charge",
                "evidence_shape": "changed test mocks dependency called from changed line",
                "action": "add_fixture",
            }
        ],
    }

    sanitized = sanitize_module.sanitize_review(raw)
    rendered = json.dumps(sanitized)

    assert sanitized["source"] == {
        "visibility": "sanitized_private_review",
        "repo_alias": "repo_123",
        "pr_alias": "pr_456",
    }
    assert sanitized["environment"]["test_command_shape"] == "pytest"
    assert sanitized["findings"][0]["path_kind"] == "test"
    assert sanitized["findings"][0]["category"] == "legitimate_internal_helper_mock"
    assert "private-repo" not in rendered
    assert "test_private_gateway.py" not in rendered
    assert "PrivatePaymentService" not in rendered
    assert "private_gateway" not in rendered
    assert "pytest tests/private_payment_flow.py -q" not in rendered


def test_summarize_records_counts_labels_and_categories() -> None:
    records = [
        {
            "schema_version": "1",
            "review_id": "review_001",
            "source": {"visibility": "sanitized_private_review", "repo_alias": "repo_001", "pr_alias": "pr_001"},
            "environment": {"language": "python", "test_framework": "pytest", "coverage_supplied": True, "deep_enabled": False},
            "findings": [
                {
                    "rule_id": "PTG005",
                    "review_label": "false_positive",
                    "category": "legitimate_internal_helper_mock",
                    "path_kind": "test",
                    "evidence_shape": "changed test mocks dependency called from changed line",
                    "action": "add_fixture",
                },
                {
                    "rule_id": "PTG006",
                    "review_label": "useful",
                    "category": "surviving_comparison_boundary_probe",
                    "path_kind": "production",
                    "evidence_shape": "comparison boundary probe survived configured tests",
                    "action": "no_change",
                },
            ],
        },
        {
            "schema_version": "1",
            "review_id": "review_002",
            "source": {"visibility": "sanitized_private_review", "repo_alias": "repo_002", "pr_alias": "pr_001"},
            "environment": {"language": "python", "test_framework": "pytest", "coverage_supplied": False, "deep_enabled": True},
            "findings": [
                {
                    "rule_id": "PTG005",
                    "review_label": "unclear",
                    "category": "legitimate_internal_helper_mock",
                    "path_kind": "test",
                    "evidence_shape": "changed test mocks dependency called from changed line",
                    "action": "improve_evidence",
                }
            ],
        },
    ]

    summary = summary_module.summarize_records(records)

    assert summary["record_count"] == 2
    assert summary["finding_count"] == 3
    assert summary["rules"]["PTG005"]["labels"]["false_positive"] == 1
    assert summary["rules"]["PTG005"]["labels"]["unclear"] == 1
    assert summary["rules"]["PTG005"]["label_rates"]["false_positive"] == 0.5
    assert summary["rules"]["PTG005"]["top_categories"] == [
        {"category": "legitimate_internal_helper_mock", "count": 2}
    ]
    assert summary["rules"]["PTG005"]["top_evidence_shapes"] == [
        {"evidence_shape": "changed test mocks dependency called from changed line", "count": 2}
    ]
    assert summary["rules"]["PTG005"]["actions"] == {
        "add_fixture": 1,
        "improve_evidence": 1,
    }
    assert "add_negative_control_fixture" in summary["rules"]["PTG005"]["recommended_next_actions"]
    assert summary["rules"]["PTG006"]["recommended_next_actions"] == ["keep_rule_behavior"]


def test_load_records_skips_schema_documents() -> None:
    records = summary_module.load_records(ROOT / "examples" / "dogfood-reviews")

    assert [record["review_id"] for record in records] == [
        "ptg005_distilled_controls_001",
        "sample_001",
    ]


def test_sanitize_preserves_existing_command_shape() -> None:
    raw = {
        "review_id": "review_001",
        "environment": {"test_command_shape": "pytest"},
        "findings": [],
    }

    sanitized = sanitize_module.sanitize_review(raw)

    assert sanitized["environment"]["test_command_shape"] == "pytest"
