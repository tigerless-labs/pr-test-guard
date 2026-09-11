"""Repository-relative path classification for PR analysis."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase


def normalize_repo_path(value: str) -> str:
    """Normalize a Git-style repository path before matching configured globs."""

    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def _matches_default_test_shape(path: str) -> bool:
    parts = path.split("/")
    filename = parts[-1]
    return (
        "tests" in parts
        or "test" in parts[:-1]
        or filename.startswith("test_")
        or filename.endswith("_test.py")
    )


@dataclass(frozen=True, slots=True)
class TestPathMatcher:
    """Classify test paths with compatible defaults and repository overrides.

    Configured include patterns extend the built-in Python/pytest conventions.
    Exclude patterns take precedence over both configured includes and defaults.
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def is_test(self, path: str) -> bool:
        normalized = normalize_repo_path(path)
        if _matches(normalized, self.exclude):
            return False
        return _matches_default_test_shape(normalized) or _matches(normalized, self.include)


DEFAULT_TEST_PATH_MATCHER = TestPathMatcher()
