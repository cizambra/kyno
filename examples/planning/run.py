"""An application-owned checklist plan that reads direction from Kyno."""

import argparse
import os
import sys

from kyno.sdk import DetailLevel, PullPolicy, connect
from kyno.sdk.errors import KynoUnavailableError


def build_plan(direction, completed):
    """Use principle titles as review tasks, excluding completed tasks."""
    if direction.version == 0:
        raise ValueError("Apply direction before planning; this constitution has no versions.")
    if not direction.principles:
        raise ValueError("This checklist example needs at least one principle.")
    return [
        principle.title for principle in direction.principles if principle.title not in completed
    ]


def show_plan(direction, plan):
    print(f"Plan from {direction.constitution} v{direction.version}")
    print(f"Mission: {direction.mission}")
    for task in plan:
        print(f"  Planned: {task}")


def run_example(binder):
    tracker = binder.plan()
    completed = set()
    direction = tracker.direction()
    remaining = build_plan(direction, completed)
    show_plan(direction, remaining)

    finished = remaining.pop(0)
    completed.add(finished)
    print(f"Simulated completion: {finished}")
    print("Apply revised direction in the operator terminal, then press Enter here.")
    input()

    changed = tracker.changed()
    if changed is not None:
        print(f"Direction changed to v{changed.version}. Application rebuilds unfinished work.")
        direction = tracker.direction()
        remaining = build_plan(direction, completed)
        show_plan(direction, remaining)
    else:
        print("Direction unchanged; application keeps its plan.")

    for task in remaining:
        print(f"Remaining: {task}")
    print("No actions executed; this example only prints the plan.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Kyno server URL")
    parser.add_argument("--constitution", default="planning-support", help="Constitution name")
    args = parser.parse_args(argv)
    token = os.environ.get("KYNO_READ_TOKEN")
    if not token or not token.strip():
        parser.error("set KYNO_READ_TOKEN to a read-scoped token")
    try:
        with connect(url=args.url, token=token) as connection:
            binder = connection.binder(
                args.constitution,
                context=DetailLevel.FULL,
                policy=PullPolicy(fail_closed=True),
            )
            run_example(binder)
    except (KynoUnavailableError, ValueError, EOFError) as exc:
        print(f"Planning stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
