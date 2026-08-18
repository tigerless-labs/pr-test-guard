"""Finding model shared by CLI and CI reporters."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """One advisory PR test-quality signal."""

    rule_id: str
    severity: str
    file: str | None
    line: int | None
    message: str
    evidence: str | None = None

    def to_dict(self) -> dict[str, object | None]:
        return asdict(self)
