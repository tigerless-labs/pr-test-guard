from __future__ import annotations

import pr_test_guard


def test_package_version_is_current() -> None:
    assert pr_test_guard.__version__ == "0.2.5"
