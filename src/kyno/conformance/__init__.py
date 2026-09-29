# SPDX-License-Identifier: MIT
"""Checks the log an adapter writes while it runs.

An adapter under test appends every block it injects to a log file, followed
by a line containing only ``---end---``. `check_log` reads that file back and
verifies the parts a correct adapter cannot get wrong: every block starts
with the marker line, version-0 blocks have the exact empty-state text, and
the version number never goes backwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MARKER = re.compile(r"^\[kyno:direction(?: constitution_key=(\S+))? version=(\d+)\]$")
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
        lines = block.split("\n")
        m = MARKER.match(lines[0])
        if not m:
            report.problems.append(
                f"block {i}: the first line must be the marker "
                f"[kyno:direction constitution_key=... version=...], got: {lines[0]!r}"
            )
            continue
        version = int(m.group(2))
        report.versions.append(version)
        if version != 0 and m.group(1) is None:
            report.problems.append(f"block {i}: written direction requires a constitution key")
        if version == 0:
            empty_state = (
                EMPTY_STATE_LINE
                if m.group(1) is not None
                else "No direction has been received yet."
            )
            if lines[1:] != [empty_state]:
                report.problems.append(
                    f"block {i}: a version-0 block must be the marker plus "
                    f"exactly one line: {empty_state!r}"
                )
        elif not any(line.startswith("Mission: ") for line in lines[1:]):
            report.problems.append(f"block {i}: no 'Mission: ' line — the block body is missing")

    for i in range(1, len(report.versions)):
        if report.versions[i] < report.versions[i - 1]:
            report.problems.append(
                f"block {i + 1}: version went backwards "
                f"({report.versions[i - 1]} then {report.versions[i]}) — an "
                f"adapter must never replace a newer direction with an older one"
            )
    return report
