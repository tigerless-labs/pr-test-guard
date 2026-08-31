"""CLI entrypoint for PR Test Guard."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from .check import CheckError, analyze_repository, default_base
from .config import GuardConfig, config_from_overrides, load_config
from .policy import apply_config, exit_code_for
from .reporters import emit_github, render_json, render_text
from .version import __version__


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def invoke_script(module_name: str, args: list[str]) -> int:
    """Run an existing development script while preserving its command contract."""
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
            "Lightweight PR test-quality checks. Findings are advisory review signals, "
            "not merge verdicts."
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the PR Test Guard version and exit",
    )

    subcommands = parser.add_subparsers(dest="command")

    check = subcommands.add_parser(
        "check",
        help="analyze the current repository diff against a base ref",
    )
    check.add_argument(
        "--base",
        default=None,
        help="base ref for the PR diff (default: origin/$GITHUB_BASE_REF in CI, otherwise origin/main)",
    )
    check.add_argument(
        "--coverage",
        default=None,
        help="optional coverage.py XML report used for changed-line coverage checks",
    )
    check.add_argument(
        "--config",
        default=None,
        help="optional path to .pr-test-guard.yml, .json, or .toml config",
    )
    check.add_argument(
        "--no-config",
        action="store_true",
        help="disable automatic .pr-test-guard.* config discovery",
    )
    check.add_argument(
        "--fail-on",
        default=None,
        help="comma-separated rule ids that should fail the command when triggered",
    )
    check.add_argument(
        "--deep",
        action="store_true",
        help="enable bounded targeted probes in an isolated git worktree",
    )
    check.add_argument(
        "--test-command",
        default=None,
        help="test command used by --deep, for example 'pytest -q'",
    )
    check.add_argument(
        "--max-probes",
        type=int,
        default=3,
        help="maximum targeted probes to run in deep mode (default: 3)",
    )
    check.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
        help="output format (default: text)",
    )
    check.add_argument(
        "--json-output",
        default=None,
        help="optional path to also write the full JSON analysis result",
    )

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


def run_check(parsed: argparse.Namespace) -> int:
    base = parsed.base or default_base()
    try:
        if parsed.no_config and parsed.config:
            raise CheckError("--config and --no-config cannot be used together")
        config = GuardConfig() if parsed.no_config else load_config(Path.cwd(), explicit_path=parsed.config)
        config = config_from_overrides(config, fail_on=parsed.fail_on)
        result = analyze_repository(
            Path.cwd(),
            base=base,
            coverage_path=parsed.coverage,
            deep=parsed.deep,
            test_command=parsed.test_command,
            max_probes=parsed.max_probes,
        )
        result = apply_config(result, config)
        if parsed.json_output:
            write_json_output(Path(parsed.json_output), render_json(result))
    except CheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if parsed.format == "json":
        sys.stdout.write(render_json(result))
    elif parsed.format == "github":
        sys.stdout.write(emit_github(result))
    else:
        sys.stdout.write(render_text(result))

    return exit_code_for(result)


def write_json_output(path: Path, content: str) -> None:
    try:
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise CheckError(f"unable to write JSON output {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    parsed = parser.parse_args(args_list)

    if parsed.version or parsed.command == "version":
        print(__version__)
        return 0

    if parsed.command == "check":
        return run_check(parsed)

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
