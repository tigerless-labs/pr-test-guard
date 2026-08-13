#!/usr/bin/env python3
"""Extract LLM-assisted claim candidates for a real PR bundle.

The script is optional. It requires the `openai` package, OPENAI_API_KEY, and a
model supplied through --model or OPENAI_MODEL. It emits candidate claims only;
it does not create adequacy findings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims", "limits"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "text",
                    "source_refs",
                    "expected_evidence",
                    "candidate_confidence",
                    "notes",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                    "expected_evidence": {"type": "array", "items": {"type": "string"}},
                    "candidate_confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "notes": {"type": "string"},
                },
            },
        },
        "limits": {"type": "array", "items": {"type": "string"}},
    },
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]\n"


def build_prompt(bundle_dir: Path, max_diff_chars: int) -> str:
    pr = load_json(bundle_dir / "pr.json")
    diff = truncate((bundle_dir / "pr.diff").read_text(encoding="utf-8"), max_diff_chars)

    optional_parts = []
    for name in ("issue.md", "task.md", "ci-summary.md"):
        path = bundle_dir / name
        if path.is_file():
            optional_parts.append(f"## {name}\n{path.read_text(encoding='utf-8')}")

    return "\n\n".join(
        [
            "Extract candidate change claims from this PR evidence bundle.",
            "Return only claims that can be tied to the PR title, body, issue/task text, or diff.",
            "Do not decide whether evidence is adequate.",
            "Do not create findings.",
            "Do not mark Evidence Complete.",
            "Each claim should be specific enough to later map to changed code and tests.",
            f"## PR metadata\n{json.dumps(pr, indent=2, sort_keys=True)}",
            *optional_parts,
            f"## pr.diff\n{diff}",
        ]
    )


def extract_with_openai(bundle_dir: Path, model: str, max_diff_chars: int) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The optional openai package is not installed. Install it with "
            "`python -m pip install -r requirements-llm.txt`."
        ) from exc

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for LLM claim extraction.")

    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "You extract reviewable change-claim candidates for Claim Harness. "
                    "You are not an adequacy judge."
                ),
            },
            {"role": "user", "content": build_prompt(bundle_dir, max_diff_chars)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "claim_candidates",
                "strict": True,
                "schema": CLAIM_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)


def wrap_output(bundle_id: str, claims: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "bundle_id": bundle_id,
        "candidate_version": "0.2",
        "producer": {
            "mode": "llm_assisted_extraction",
            "model": model,
            "review_status": "human_review_required",
            "notes": "Candidate claims only; this file is not an adequacy finding.",
        },
        "source_artifacts": ["pr.json", "pr.diff"],
        "claims": claims["claims"],
        "limits": [
            *claims.get("limits", []),
            "Claims are candidates only.",
            "No claim should be converted to Evidence Complete without mapped evidence.",
            "This file does not replace human review.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", help="real PR bundle directory")
    parser.add_argument(
        "--output",
        help="output path (default: <bundle>/claim_candidates.json)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help="OpenAI model to use; may also be set with OPENAI_MODEL",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=30000,
        help="maximum pr.diff characters to send (default: 30000)",
    )
    args = parser.parse_args()

    bundle_dir = Path(args.bundle)
    if not bundle_dir.is_dir():
        print(f"ERROR: bundle not found: {bundle_dir}", file=sys.stderr)
        return 1

    if not args.model:
        print("ERROR: --model or OPENAI_MODEL is required", file=sys.stderr)
        return 1

    try:
        claims = extract_with_openai(bundle_dir, args.model, args.max_diff_chars)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else bundle_dir / "claim_candidates.json"
    write_json(output_path, wrap_output(bundle_dir.name, claims, args.model))
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
