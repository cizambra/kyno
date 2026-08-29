"""Reading a constitution out of a file an operator wrote, and writing
the store's current version back into one.

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
from kyno.models import ConstitutionVersion, Principle, normalize_principles

# The keys kyno reads. Every other key in the file is the operator's own
# and is ignored, so one file can serve other tools too.
FIELDS = ("constitution", "mission", "declaration", "principles")


@dataclass(frozen=True)
class ConstitutionFile:
    """What the file said. None means the key was absent, which set_direction
    reads as "carry this one forward" -- clearing a field is spelled ""."""

    constitution: str | None = None
    mission: str | None = None
    declaration: str | None = None
    principles: tuple[Principle, ...] | None = None


def read_constitution_file(path: str) -> ConstitutionFile:
    document = _load(path)
    if not isinstance(document, Mapping):
        raise AuthoringError(f"{path}: a constitution file must be a mapping of fields")
    return ConstitutionFile(
        constitution=_text(document, "constitution", path),
        mission=_text(document, "mission", path),
        declaration=_text(document, "declaration", path),
        principles=_principles(document, path),
    )


@dataclass(frozen=True)
class FileReport:
    """What `kyno check` reports: the kyno fields a file sets, the ones it
    leaves to carry forward, and the keys that belong to the operator."""

    present: tuple[str, ...]
    missing: tuple[str, ...]
    custom: tuple[str, ...]


def check_constitution_file(path: str) -> FileReport:
    """Validate a file the way an apply would, and sort its keys."""
    read_constitution_file(path)
    document = _load(path)
    return FileReport(
        present=tuple(f for f in FIELDS if document.get(f) is not None),
        missing=tuple(f for f in FIELDS if document.get(f) is None),
        custom=tuple(sorted(set(document) - set(FIELDS))),
    )


def render_constitution_yaml(version: ConstitutionVersion, constitution: str) -> str:
    """The current version in the file format `kyno set --file` reads back.
    Applying it unchanged is a no-op edit."""
    document: dict = {"constitution": constitution}
    if version.mission:
        document["mission"] = version.mission
    if version.declaration:
        document["declaration"] = version.declaration
    if version.principles:
        document["principles"] = [
            p.title if not p.description else {"title": p.title, "description": p.description}
            for p in version.principles
        ]
    return _dump(document)


def _dump(document: dict) -> str:
    import yaml

    class _Dumper(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False):
            # Never indentless: list items sit indented under their key,
            # the way the docs and people write the file by hand.
            return super().increase_indent(flow, False)

    def _scalar(dumper, text):
        # Prose keeps its line breaks readable as a block scalar; a
        # single-line value stays a plain one.
        style = "|" if "\n" in text else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)

    _Dumper.add_representer(str, _scalar)
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True)


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
