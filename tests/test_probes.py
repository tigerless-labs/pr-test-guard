from __future__ import annotations

from pathlib import Path

from pr_test_guard.probes import generate_probes


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_generates_return_status_probe_from_ast(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "def status(ok):\n    if not ok:\n        return 404\n    return 200\n")

    probes = generate_probes(tmp_path, {"app.py": [{"line": 3, "content": "        return 404"}]}, max_probes=3)

    assert probes == [
        {
            "id": "P1",
            "file": "app.py",
            "line": 3,
            "original": "return 404",
            "replacement": "return 200",
            "rationale": "weaken HTTP 404 return to success",
            "kind": "return_status_code",
        }
    ]


def test_generates_comparison_probe_without_spacing_assumptions(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "def valid(amount):\n    return amount>=0\n")

    probes = generate_probes(tmp_path, {"app.py": [{"line": 2, "content": "    return amount>=0"}]}, max_probes=3)

    assert probes == [
        {
            "id": "P1",
            "file": "app.py",
            "line": 2,
            "original": "amount>=0",
            "replacement": "amount>0",
            "rationale": "weaken inclusive lower-bound comparison",
            "kind": "comparison_boundary",
        }
    ]


def test_generates_comparison_probe_inside_if_condition(tmp_path: Path) -> None:
    write(
        tmp_path / "app.py",
        "def status(amount):\n"
        "    if amount >= 0:\n"
        "        return 200\n"
        "    return 400\n",
    )

    probes = generate_probes(tmp_path, {"app.py": [{"line": 2, "content": "    if amount >= 0:"}]}, max_probes=3)

    assert probes == [
        {
            "id": "P1",
            "file": "app.py",
            "line": 2,
            "original": "amount >= 0",
            "replacement": "amount > 0",
            "rationale": "weaken inclusive lower-bound comparison",
            "kind": "comparison_boundary",
        }
    ]


def test_chained_comparison_generates_single_stable_probe(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "def valid(amount, limit):\n    return 0 <= amount <= limit\n")

    probes = generate_probes(
        tmp_path,
        {"app.py": [{"line": 2, "content": "    return 0 <= amount <= limit"}]},
        max_probes=3,
    )

    assert probes == [
        {
            "id": "P1",
            "file": "app.py",
            "line": 2,
            "original": "0 <= amount <= limit",
            "replacement": "0 < amount <= limit",
            "rationale": "weaken inclusive upper-bound comparison",
            "kind": "comparison_boundary",
        }
    ]


def test_generates_boolean_return_probe(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "def enabled():\n    return True\n")

    probes = generate_probes(tmp_path, {"app.py": [{"line": 2, "content": "    return True"}]}, max_probes=3)

    assert probes[0]["original"] == "return True"
    assert probes[0]["replacement"] == "return False"
    assert probes[0]["kind"] == "boolean_return"


def test_response_constructor_status_code_is_not_a_probe_candidate(tmp_path: Path) -> None:
    write(
        tmp_path / "app.py",
        "class Response:\n"
        "    def __init__(self, status_code):\n"
        "        self.status_code = status_code\n\n"
        "def status():\n"
        "    return Response(status_code=404)\n",
    )

    probes = generate_probes(
        tmp_path,
        {"app.py": [{"line": 6, "content": "    return Response(status_code=404)"}]},
        max_probes=3,
    )

    assert probes == []


def test_http_status_symbol_return_is_not_a_probe_candidate(tmp_path: Path) -> None:
    write(
        tmp_path / "app.py",
        "from http import HTTPStatus\n\n"
        "def status():\n"
        "    return HTTPStatus.NOT_FOUND\n",
    )

    probes = generate_probes(
        tmp_path,
        {"app.py": [{"line": 4, "content": "    return HTTPStatus.NOT_FOUND"}]},
        max_probes=3,
    )

    assert probes == []


def test_max_probes_preserves_stable_order(tmp_path: Path) -> None:
    write(
        tmp_path / "app.py",
        "def first():\n"
        "    return 404\n\n"
        "def second():\n"
        "    return False\n",
    )

    probes = generate_probes(
        tmp_path,
        {
            "app.py": [
                {"line": 2, "content": "    return 404"},
                {"line": 5, "content": "    return False"},
            ]
        },
        max_probes=1,
    )

    assert len(probes) == 1
    assert probes[0]["id"] == "P1"
    assert probes[0]["line"] == 2
    assert probes[0]["kind"] == "return_status_code"


def test_string_and_comment_text_do_not_generate_probes(tmp_path: Path) -> None:
    write(
        tmp_path / "app.py",
        "def sample():\n"
        "    text = 'return 404'\n"
        "    # return 400\n"
        "    return text\n",
    )

    probes = generate_probes(
        tmp_path,
        {
            "app.py": [
                {"line": 2, "content": "    text = 'return 404'"},
                {"line": 3, "content": "    # return 400"},
            ]
        },
        max_probes=3,
    )

    assert probes == []


def test_unchanged_comparison_line_does_not_generate_probe(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "def valid(amount):\n    checked = amount >= 0\n    return checked\n")

    probes = generate_probes(tmp_path, {"app.py": [{"line": 3, "content": "    return checked"}]}, max_probes=3)

    assert probes == []


def test_multiline_expression_is_skipped_when_replacement_is_not_stable(tmp_path: Path) -> None:
    write(tmp_path / "app.py", "def valid(amount):\n    return (\n        amount >= 0\n    )\n")

    probes = generate_probes(tmp_path, {"app.py": [{"line": 3, "content": "        amount >= 0"}]}, max_probes=3)

    assert probes == []
