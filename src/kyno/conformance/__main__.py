"""Command line for the adapter checker: python -m kyno.conformance check FILE"""

from __future__ import annotations

import pathlib
import sys

from kyno.conformance import check_log


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print("usage: python -m kyno.conformance check YOUR_LOG_FILE")
        return 2
    path = pathlib.Path(argv[1])
    if not path.exists():
        print(f"file not found: {path}")
        return 2

    report = check_log(path.read_text())
    print(f"blocks found: {len(report.versions)}")
    if report.versions:
        print(f"versions, step by step: {report.versions}")
    for step, old, new in report.version_changes():
        print(f"  version changed at step {step}: {old} -> {new}")
    if report.ok:
        print("all checks passed")
        return 0
    print()
    for problem in report.problems:
        print(f"PROBLEM: {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
