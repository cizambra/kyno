# SPDX-License-Identifier: MIT
from kyno.sdk.binder import DirectionBinder
from kyno.sdk.cell import Direction


class PlanTracker:
    """Remembers which version a plan was made under and says when it went
    stale.

    Kyno's part ends at the signal and the fresh direction: rewriting the
    remaining work takes the orchestrator's own model, so `changed()` hands
    back what to replan against and nothing more. Replanning is a new plan
    pull — call `direction()` again and the plan is current from there.
    """

    def __init__(self, binder: DirectionBinder, constitution: str = "default") -> None:
        self._binder = binder
        self._constitution = constitution
        self._planned_version: int | None = None

    def direction(self) -> Direction:
        """The direction to plan against. Pulls, and marks the plan as made
        under the version that came back."""
        direction = self._binder.bind(self._constitution)
        self._planned_version = direction.version
        return direction

    def changed(self) -> Direction | None:
        """The fresh direction when a newer version exists than the plan was
        made under; None while the plan is still current. A failed pull
        degrades to the last-known direction, so an unreachable control
        plane reports no change rather than a false one."""
        if self._planned_version is None:
            return None
        direction = self._binder.bind(self._constitution)
        if direction.version > self._planned_version:
            return direction
        return None
