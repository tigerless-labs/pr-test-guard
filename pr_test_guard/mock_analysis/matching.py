"""Match resolved mock targets against changed Python symbols."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .mocks import MockTarget, ResolutionKind
from .symbols import PythonSymbol


class MatchKind(str, Enum):
    EXACT = "exact"
    ALIAS_RESOLVED = "alias_resolved"
    HEURISTIC = "heuristic"


@dataclass(frozen=True, slots=True)
class MockMatch:
    target: MockTarget
    symbol: PythonSymbol
    kind: MatchKind


def _canonical(value: str) -> str:
    return value.strip().strip("'\"").strip(".")


def _conservative_unresolved_match(raw_target: str, symbol: PythonSymbol) -> bool:
    """Fallback only when semantic resolution is unavailable.

    Require at least a module-qualified target plus the full symbol qualname.
    A bare method/function name is intentionally insufficient because that was
    a common source of same-name false positives in the original PTG005 rule.
    """

    raw = _canonical(raw_target)
    if raw.count(".") < 1:
        return False
    suffix = f".{symbol.qualname}"
    return raw == symbol.qualname or raw.endswith(suffix)


def match_mock_target(target: MockTarget, symbols: list[PythonSymbol]) -> list[MockMatch]:
    matches: list[MockMatch] = []
    for symbol in symbols:
        if target.resolved_target:
            if _canonical(target.resolved_target) != _canonical(symbol.canonical_name):
                continue
            kind = MatchKind.ALIAS_RESOLVED if target.resolution == ResolutionKind.ALIAS else MatchKind.EXACT
            matches.append(MockMatch(target=target, symbol=symbol, kind=kind))
            continue
        if _conservative_unresolved_match(target.raw_target, symbol):
            matches.append(MockMatch(target=target, symbol=symbol, kind=MatchKind.HEURISTIC))
    return matches
