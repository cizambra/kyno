# SPDX-License-Identifier: Elastic-2.0
"""Reading a constitution out of a file an operator wrote.

A declaration is paragraphs and a description is a paragraph; both are
miserable to type as command-line flags and worse to re-type on the next
edit. A file is where a rich constitution actually gets written, and it is
YAML because a block scalar is the readable way to hold prose (JSON parses
too -- it is valid YAML).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kyno.errors import AuthoringError, CoherenceError
from kyno.models import Principle, normalize_principles

# Every key a file may carry. An unknown one is refused rather than ignored:
# a constitution missing the half somebody thought they wrote is worse than
# a file that will not load.
FIELDS = ("constitution", "mission", "declaration", "principles", "note", "by")


@dataclass(frozen=True)
class ConstitutionFile:
    """What the file said. None means the key was absent, which set_direction
    reads as "carry this one forward" -- clearing a field is spelled ""."""

    constitution: str | None = None
    mission: str | None = None
    declaration: str | None = None
    principles: tuple[Principle, ...] | None = None
    note: str | None = None
    created_by: str | None = None


def read_constitution_file(path: str) -> ConstitutionFile:
    document = _load(path)
    if not isinstance(document, Mapping):
        raise AuthoringError(f"{path}: a constitution file must be a mapping of fields")
    unknown = sorted(set(document) - set(FIELDS))
    if unknown:
        raise AuthoringError(
            f"{path}: unknown field(s) {', '.join(unknown)} "
            f"(a constitution file takes {', '.join(FIELDS)})"
        )
    return ConstitutionFile(
        constitution=_text(document, "constitution", path),
        mission=_text(document, "mission", path),
        declaration=_text(document, "declaration", path),
        principles=_principles(document, path),
        note=_text(document, "note", path),
        created_by=_text(document, "by", path),
    )


def _load(path: str):
    import yaml

    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise AuthoringError(f"{path} could not be read: {exc}") from None


def _text(document: Mapping, field: str, path: str) -> str | None:
    # A key with nothing after it is far more often a half-written file than
    # a deletion, so it reads as absent; clearing a field is spelled "".
    value = document.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AuthoringError(f"{path}: {field} must be text, got {type(value).__name__}")
    return value.strip()


def _principles(document: Mapping, path: str) -> tuple[Principle, ...] | None:
    value = document.get("principles")
    if value is None:
        return None
    try:
        return normalize_principles(value)
    except CoherenceError as exc:
        raise AuthoringError(f"{path}: principles: {exc}") from None
