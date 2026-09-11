from __future__ import annotations

from pr_test_guard.paths import TestPathMatcher as PathMatcher
from pr_test_guard.paths import normalize_repo_path


def test_default_test_path_conventions_remain_supported() -> None:
    matcher = PathMatcher()

    assert matcher.is_test("tests/test_service.py") is True
    assert matcher.is_test("package/test/service.py") is True
    assert matcher.is_test("test_service.py") is True
    assert matcher.is_test("service_test.py") is True
    assert not matcher.is_test("src/test_support/service.py")
    assert not matcher.is_test("src/service.py")


def test_configured_includes_extend_defaults_and_excludes_take_precedence() -> None:
    matcher = PathMatcher(
        include=("spec/**", "**/*_spec.py"),
        exclude=("spec/helpers/**", "tests/integration/**"),
    )

    assert matcher.is_test("spec/payment_spec.py") is True
    assert matcher.is_test("features/account_spec.py") is True
    assert not matcher.is_test("spec/helpers/factories.py")
    assert not matcher.is_test("tests/integration/test_payment.py")


def test_repository_paths_are_normalized_without_losing_dotfile_prefixes() -> None:
    matcher = PathMatcher(include=(".checks/**", "spec/**"))

    assert normalize_repo_path(r".\spec\payment_spec.py") == "spec/payment_spec.py"
    assert normalize_repo_path(".checks/test_policy.py") == ".checks/test_policy.py"
    assert matcher.is_test(r".\spec\payment_spec.py") is True
    assert matcher.is_test(".checks/policy.py") is True
