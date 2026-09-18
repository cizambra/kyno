# SPDX-License-Identifier: MIT
"""Checks the log an adapter writes while it runs.

An adapter under test appends every block it injects to a log file, followed
by a line containing only ``---end---``. `check_log` reads that file back and
verifies the parts a correct adapter cannot get wrong: every block starts
with the marker, version-0 blocks have the exact empty-state text, and
the version number never goes backwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kyno.wire.constitution import check_constitution
from kyno.wire.errors import InvalidConstitutionNameError

MARKER = re.compile(r"^\[kyno:direction constitution=(.+?) version=(\d+)\](?:\n|$)", re.DOTALL)
SEPARATOR = "---end---"
EMPTY_STATE_LINE = "No direction has been set yet."


@dataclass
class Report:
    versions: list[int] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def version_changes(self) -> list[tuple[int, int, int]]:
        """(step number, old version, new version) for every step where the
        version moved. Step numbers start at 1."""
        changes = []
        for i in range(1, len(self.versions)):
            if self.versions[i] != self.versions[i - 1]:
                changes.append((i + 1, self.versions[i - 1], self.versions[i]))
        return changes


def check_log(text: str) -> Report:
    report = Report()
    blocks = [b.strip("\n") for b in text.split(f"\n{SEPARATOR}\n")]
    blocks = [b for b in blocks if b.strip() and b.strip() != SEPARATOR]
    if not blocks:
        report.problems.append(
            f"no blocks found — append each injected block followed by a line "
            f"containing only {SEPARATOR}"
        )
        return report

    for i, block in enumerate(blocks, start=1):
        m = MARKER.match(block)
        if not m:
            report.problems.append(
                f"block {i}: the block must start with the marker "
                f"[kyno:direction constitution=... version=...], got: {block.splitlines()[0]!r}"
            )
            continue
        try:
            check_constitution(m.group(1))
        except InvalidConstitutionNameError as exc:
            report.problems.append(f"block {i}: {exc}")
            continue
        lines = block[m.end() :].split("\n")
        version = int(m.group(2))
        report.versions.append(version)
        if version == 0:
            if lines != [EMPTY_STATE_LINE]:
                report.problems.append(
                    f"block {i}: a version-0 block must be the marker plus "
                    f"exactly one line: {EMPTY_STATE_LINE!r}"
                )
        elif not any(line.startswith("Mission: ") for line in lines):
            report.problems.append(f"block {i}: no 'Mission: ' line — the block body is missing")

    for i in range(1, len(report.versions)):
        if report.versions[i] < report.versions[i - 1]:
            report.problems.append(
                f"block {i + 1}: version went backwards "
                f"({report.versions[i - 1]} then {report.versions[i]}) — an "
                f"adapter must never replace a newer direction with an older one"
            )
    return report
