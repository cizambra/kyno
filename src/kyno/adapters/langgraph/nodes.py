# SPDX-License-Identifier: MIT
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypedDict

from kyno.sdk.binder import DirectionBinder
from kyno.sdk.binding import BindingStatus
from kyno.sdk.cell import Direction
from kyno.sdk.recording import RecordingReceipt
from kyno.wire.models import DetailLevel


class KynoState(TypedDict, total=False):
    """Inherit this in your graph's state schema. LangGraph only carries the
    keys a schema declares. Without it, the direction a node pulls never
    reaches downstream work nodes.
    """

    kyno_constitution_key: str
    kyno_version: int
    kyno_mission: str
    kyno_declaration: str
    kyno_change_notes: list[str]
    kyno_delta: list[str]
    kyno_principles: list[dict]
    kyno_detail: DetailLevel
    kyno_direction: str
    kyno_binding_status: BindingStatus | None
    kyno_recording: dict[str, str | None] | None


def direction_update(
    direction: Direction,
    *,
    status: BindingStatus | str | None = None,
    recording: RecordingReceipt | None = None,
) -> dict:
    """Direction travels in graph state so a persisted checkpoint says which
    constitution and version a step served, without any other context.
    Status is unknown when no binding metadata is supplied.
    """
    return {
        "kyno_constitution_key": direction.constitution_key,
        "kyno_version": direction.version,
        "kyno_mission": direction.mission,
        "kyno_declaration": direction.declaration,
        "kyno_change_notes": list(direction.change_notes),
        "kyno_delta": list(direction.delta),
        "kyno_principles": [p.to_dict() for p in direction.principles],
        "kyno_direction": direction.render(),
        "kyno_detail": direction.detail,
        "kyno_binding_status": BindingStatus(status) if status is not None else None,
        "kyno_recording": (
            {"status": recording.status.value, "record_id": recording.record_id}
            if recording is not None
            else None
        ),
    }


def direction_from_state(state: dict) -> Direction:
    return Direction(
        constitution_key=state.get("kyno_constitution_key", "default"),
        version=state.get("kyno_version", 0),
        mission=state.get("kyno_mission", ""),
        declaration=state.get("kyno_declaration", ""),
        change_notes=tuple(state.get("kyno_change_notes", ())),
        delta=tuple(state.get("kyno_delta", ())),
        principles=state.get("kyno_principles", ()),
        detail=state.get("kyno_detail", DetailLevel.COMPACT),
    )


def direction_node(binder: DirectionBinder) -> Callable:
    """A sentinel node, and the `pre_model_hook` for prebuilt ReAct agents:
    one refresh ahead of a fan-out serves every node downstream."""

    def node(state: dict) -> dict:
        binding = binder.bind_with_status()
        return direction_update(
            binding.direction, status=binding.status, recording=binding.recording
        )

    return node


def pull_before(binder: DirectionBinder) -> Callable:
    def decorator(node: Callable) -> Callable:
        @functools.wraps(node)
        def wrapped(state: dict, *args: Any, **kwargs: Any) -> dict:
            binding = binder.bind_with_status()
            update = direction_update(
                binding.direction, status=binding.status, recording=binding.recording
            )
            result = node({**state, **update}, *args, **kwargs) or {}
            return {**update, **result}

        return wrapped

    return decorator
