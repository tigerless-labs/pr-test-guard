"""Stable source-tree CLI for PR Test Guard."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from .version import __version__


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def invoke_script(module_name: str, args: list[str]) -> int:
    """Run an existing script module while preserving its command contract."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))

    module = importlib.import_module(module_name)
    original_argv = sys.argv[:]
    try:
        sys.argv = [module_name, *args]
        return int(module.main())
    finally:
        sys.argv = original_argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-test-guard",
        description=(
            "Run PR Test Guard regression fixtures and real-PR input checks. "
            "Findings are review signals, not merge verdicts."
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the PR Test Guard version and exit",
    )

    subcommands = parser.add_subparsers(dest="command")

    validate_cases = subcommands.add_parser(
        "validate-cases",
        help="validate regression fixture structure and optionally run patched fixtures",
    )
    validate_cases.add_argument(
        "--cases-root",
        default="cases/python",
        help="directory containing regression fixtures",
    )
    validate_cases.add_argument(
        "--run",
        action="store_true",
        help="apply each PR patch in a temp copy and run pytest",
    )

    run_cases = subcommands.add_parser(
        "run-cases",
        help="run regression fixtures and emit test-quality evidence and findings",
    )
    run_cases.add_argument(
        "--cases-root",
        default="cases/python",
        help="directory containing regression fixtures",
    )
    run_cases.add_argument(
        "--case",
        action="append",
        default=[],
        help="fixture id to run; may be provided multiple times",
    )
    run_cases.add_argument(
        "--output-dir",
        default="artifacts",
        help="directory for generated artifacts",
    )

    validate_bundles = subcommands.add_parser(
        "validate-real-pr-bundles",
        help="validate normalized real PR input bundle structure",
    )
    validate_bundles.add_argument(
        "--bundles-root",
        default="examples/real-pr-bundles",
        help="directory containing real PR bundles",
    )

    subcommands.add_parser("version", help="print the PR Test Guard version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    parsed = parser.parse_args(args_list)

    if parsed.version or parsed.command == "version":
        print(__version__)
        return 0

    if parsed.command == "validate-cases":
        script_args = ["--cases-root", parsed.cases_root]
        if parsed.run:
            script_args.append("--run")
        return invoke_script("validate_cases", script_args)

    if parsed.command == "run-cases":
        script_args = ["--cases-root", parsed.cases_root, "--output-dir", parsed.output_dir]
        for case_id in parsed.case:
            script_args.extend(["--case", case_id])
        return invoke_script("run_case", script_args)

    if parsed.command == "validate-real-pr-bundles":
        return invoke_script(
            "validate_real_pr_bundles",
            ["--bundles-root", parsed.bundles_root],
        )

    parser.print_help()
    return 0
