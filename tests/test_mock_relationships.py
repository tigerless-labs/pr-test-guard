from __future__ import annotations

import subprocess
from pathlib import Path

from pr_test_guard.check import analyze_repository


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


def ptg005(result):
    return [item for item in result.findings if item.rule_id == "PTG005"]


def test_changed_test_mocking_changed_internal_callsite_is_reported(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "def calculate_retry(value):\n    return value + 1\n\n"
        "def charge(value):\n    return value\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "def calculate_retry(value):\n    return value + 1\n\n"
        "def charge(value):\n    return calculate_retry(value)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('service.calculate_retry')\n"
        "def test_charge(mock_retry):\n    mock_retry.return_value = 3\n    assert charge_result(mock_retry) is not None\n\n"
        "def charge_result(mock_retry):\n    return mock_retry.return_value\n",
    )
    commit_all(repo, "change")

    findings = ptg005(analyze_repository(repo, base="HEAD~1"))
    assert len(findings) == 1
    assert "relation=direct_internal_dependency" in (findings[0].evidence or "")
    assert "changed symbol=service.charge" in (findings[0].evidence or "")
    assert "dependency target(s)=service.calculate_retry" in (findings[0].evidence or "")


def test_patch_where_looked_up_matches_internal_imported_dependency(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src/payment/__init__.py", "")
    write(repo / "src/payment/retry.py", "def calculate_retry(value):\n    return value + 1\n")
    write(
        repo / "src/payment/service.py",
        "from .retry import calculate_retry\n\n"
        "def charge(value):\n    return value\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "src/payment/service.py",
        "from .retry import calculate_retry\n\n"
        "def charge(value):\n    return calculate_retry(value)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('payment.service.calculate_retry')\n"
        "def test_charge(mock_retry):\n    assert mock_retry is not None\n",
    )
    commit_all(repo, "change")

    findings = ptg005(analyze_repository(repo, base="HEAD~1"))
    assert len(findings) == 1
    evidence = findings[0].evidence or ""
    assert "relation=direct_internal_dependency" in evidence
    assert "payment.retry.calculate_retry" in evidence
    assert "payment.service.calculate_retry" in evidence


def test_external_import_mock_on_changed_callsite_is_suppressed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "import stripe\n\n"
        "def charge(amount):\n    return None\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "import stripe\n\n"
        "def charge(amount):\n    return stripe.PaymentIntent.create(amount=amount)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('service.stripe.PaymentIntent.create')\n"
        "def test_charge(mock_create):\n    assert mock_create is not None\n",
    )
    commit_all(repo, "change")

    result = analyze_repository(repo, base="HEAD~1")
    assert not ptg005(result)
    external_notes = [note for note in result.notes if note.startswith("PTG005:")]
    assert external_notes == ["PTG005: suppressed 1 external-boundary mock candidate(s) on changed call sites."]


def test_external_definition_target_mock_is_also_suppressed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "import stripe\n\n"
        "def charge(amount):\n    return None\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "import stripe\n\n"
        "def charge(amount):\n    return stripe.PaymentIntent.create(amount=amount)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('stripe.PaymentIntent.create')\n"
        "def test_charge(mock_create):\n    assert mock_create is not None\n",
    )
    commit_all(repo, "change")

    result = analyze_repository(repo, base="HEAD~1")
    assert not ptg005(result)
    external_notes = [note for note in result.notes if note.startswith("PTG005:")]
    assert external_notes == ["PTG005: suppressed 1 external-boundary mock candidate(s) on changed call sites."]


def test_unchanged_test_does_not_gain_indirect_dependency_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "def calculate_retry(value):\n    return value + 1\n\n"
        "def charge(value):\n    return calculate_retry(value)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('service.calculate_retry')\n"
        "def test_charge(mock_retry):\n    assert mock_retry is not None\n",
    )
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "def calculate_retry(value):\n    return value + 1\n\n"
        "def charge(value):\n    return calculate_retry(value + 1)\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))


def test_mock_of_unchanged_callsite_is_not_related_to_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "def calculate_retry(value):\n    return value + 1\n\n"
        "def charge(value):\n    value = calculate_retry(value)\n    return value\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "def calculate_retry(value):\n    return value + 1\n\n"
        "def charge(value):\n    value = calculate_retry(value)\n    return value + 1\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('service.calculate_retry')\n"
        "def test_charge(mock_retry):\n    assert mock_retry is not None\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))


def test_method_body_change_does_not_mark_class_container_as_changed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "class PaymentService:\n"
        "    def charge(self):\n"
        "        return False\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "class PaymentService:\n"
        "    def charge(self):\n"
        "        return True\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('service.PaymentService')\n"
        "def test_charge(mock_service):\n    assert mock_service is not None\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))


def test_self_method_call_on_changed_line_is_internal_dependency(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "class PaymentService:\n"
        "    def normalize(self, value):\n        return value\n\n"
        "    def charge(self, value):\n        return value\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "class PaymentService:\n"
        "    def normalize(self, value):\n        return value\n\n"
        "    def charge(self, value):\n        return self.normalize(value)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\nfrom service import PaymentService\n\n"
        "@patch.object(PaymentService, 'normalize')\n"
        "def test_charge(mock_normalize):\n    assert mock_normalize is not None\n",
    )
    commit_all(repo, "change")

    findings = ptg005(analyze_repository(repo, base="HEAD~1"))
    assert len(findings) == 1
    assert "relation=direct_internal_dependency" in (findings[0].evidence or "")
    assert "service.PaymentService.normalize" in (findings[0].evidence or "")


def test_deep_self_attribute_chain_stays_unresolved(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "service.py",
        "class PaymentService:\n"
        "    def charge(self, value):\n        return value\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "service.py",
        "class PaymentService:\n"
        "    def charge(self, value):\n        return self.gateway.send(value)\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('service.gateway.send')\n"
        "def test_charge(mock_send):\n    assert mock_send is not None\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))
