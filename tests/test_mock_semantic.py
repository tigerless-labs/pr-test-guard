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


def test_patch_object_import_alias_resolves_changed_method(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "src/payment/service.py",
        "class PaymentService:\n    def charge(self, amount):\n        return amount > 0\n",
    )
    write(repo / "tests/test_payment.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "src/payment/service.py",
        "class PaymentService:\n    def charge(self, amount):\n        return amount >= 0\n",
    )
    write(
        repo / "tests/test_payment.py",
        "from unittest.mock import patch\n"
        "from payment.service import PaymentService as Service\n\n"
        "@patch.object(Service, 'charge')\n"
        "def test_charge(mock_charge):\n    assert mock_charge is not None\n",
    )
    commit_all(repo, "change")

    findings = ptg005(analyze_repository(repo, base="HEAD~1"))
    assert len(findings) == 1
    assert "resolved=payment.service.PaymentService.charge" in (findings[0].evidence or "")
    assert "match=alias_resolved" in (findings[0].evidence or "")


def test_same_method_name_on_different_class_is_not_matched(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "services.py",
        "class PaymentService:\n    def run(self):\n        return 'pay'\n\n"
        "class EmailService:\n    def run(self):\n        return 'mail'\n",
    )
    write(repo / "tests/test_services.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "services.py",
        "class PaymentService:\n    def run(self):\n        return 'paid'\n\n"
        "class EmailService:\n    def run(self):\n        return 'mail'\n",
    )
    write(
        repo / "tests/test_services.py",
        "from unittest.mock import patch\nfrom services import EmailService\n\n"
        "@patch.object(EmailService, 'run')\n"
        "def test_email(mock_run):\n    assert mock_run is not None\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))


def test_same_function_name_in_different_module_is_not_matched(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "payment.py", "def send():\n    return 'pay'\n")
    write(repo / "email.py", "def send():\n    return 'mail'\n")
    write(repo / "tests/test_send.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(repo / "payment.py", "def send():\n    return 'paid'\n")
    write(
        repo / "tests/test_send.py",
        "from unittest.mock import patch\n\n"
        "@patch('email.send')\n"
        "def test_email(mock_send):\n    assert mock_send is not None\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))


def test_src_layout_uses_importable_module_name(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "src/foo/service.py", "def charge(amount):\n    return amount > 0\n")
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(repo / "src/foo/service.py", "def charge(amount):\n    return amount >= 0\n")
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "@patch('foo.service.charge')\n"
        "def test_charge(mock_charge):\n    assert mock_charge is not None\n",
    )
    commit_all(repo, "change")

    findings = ptg005(analyze_repository(repo, base="HEAD~1"))
    assert len(findings) == 1
    assert "changed symbol(s)=foo.service.charge" in (findings[0].evidence or "")


def test_module_alias_resolves_patch_object_owner(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "src/foo/service.py",
        "class PaymentService:\n    def charge(self):\n        return False\n",
    )
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "src/foo/service.py",
        "class PaymentService:\n    def charge(self):\n        return True\n",
    )
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\nimport foo.service as service_module\n\n"
        "@patch.object(service_module.PaymentService, 'charge')\n"
        "def test_charge(mock_charge):\n    assert mock_charge is not None\n",
    )
    commit_all(repo, "change")

    assert len(ptg005(analyze_repository(repo, base="HEAD~1"))) == 1


def test_relative_import_alias_resolves_patch_object_owner(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "foo/__init__.py", "")
    write(repo / "foo/tests/__init__.py", "")
    write(
        repo / "foo/service.py",
        "class PaymentService:\n    def charge(self):\n        return False\n",
    )
    write(repo / "foo/tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(
        repo / "foo/service.py",
        "class PaymentService:\n    def charge(self):\n        return True\n",
    )
    write(
        repo / "foo/tests/test_service.py",
        "from unittest.mock import patch\nfrom ..service import PaymentService\n\n"
        "@patch.object(PaymentService, 'charge')\n"
        "def test_charge(mock_charge):\n    assert mock_charge is not None\n",
    )
    commit_all(repo, "change")

    findings = ptg005(analyze_repository(repo, base="HEAD~1"))
    assert len(findings) == 1
    assert "resolved=foo.service.PaymentService.charge" in (findings[0].evidence or "")


def test_dynamic_patch_object_owner_is_left_unresolved(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write(repo / "service.py", "class Service:\n    def run(self):\n        return False\n")
    write(repo / "tests/test_service.py", "def test_placeholder():\n    assert True\n")
    commit_all(repo, "base")

    write(repo / "service.py", "class Service:\n    def run(self):\n        return True\n")
    write(
        repo / "tests/test_service.py",
        "from unittest.mock import patch\n\n"
        "def get_service():\n    return object()\n\n"
        "@patch.object(get_service(), 'run')\n"
        "def test_run(mock_run):\n    assert mock_run is not None\n",
    )
    commit_all(repo, "change")

    assert not ptg005(analyze_repository(repo, base="HEAD~1"))
