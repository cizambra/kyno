# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from kyno.sdk.binder import DirectionBinder
from kyno.sdk.binding import DirectionBinding
from kyno.sdk.cell import refresh

_log = logging.getLogger(__name__)


class CrewAiKyno:
    """Supply direction before CrewAI model calls and optionally observe its delivery."""

    def __init__(
        self,
        binder: DirectionBinder,
        *,
        constitution: str = "default",
        on_direction: Callable[[DirectionBinding], None] | None = None,
    ) -> None:
        self._binder = binder
        self.constitution = constitution
        self.on_direction = on_direction

    def before_llm_call(self, ctx: Any) -> None:
        """Inject direction, then notify the optional observer; observer failures are logged."""
        binding = self._binder.bind_with_status(self.constitution)
        messages = getattr(ctx, "messages", None)
        if messages is None:
            messages = ctx.messages = []
        # CrewAI's executor keeps a reference to this list, so rebinding it
        # would silently detach the hook from the call it is editing.
        messages[:] = refresh(
            messages,
            binding.direction.render(),
            text_of=_system_content,
            make=lambda block: {"role": "system", "content": block},
        )
        if self.on_direction is not None:
            try:
                self.on_direction(binding)
            except Exception:
                _log.exception(
                    "direction observer failed constitution=%s version=%s",
                    binding.direction.constitution,
                    binding.direction.version,
                )

    def register(self) -> None:
        """Register direction injection in CrewAI's global before-call hook registry."""
        from crewai.hooks import register_before_llm_call_hook

        register_before_llm_call_hook(self.before_llm_call)

    def unregister(self) -> bool:
        from crewai.hooks import unregister_before_llm_call_hook

        return unregister_before_llm_call_hook(self.before_llm_call)


def _system_content(message: Any) -> str:
    # Only a system message can be the block this adapter injected. Marker text on any other
    # role is data (a tool result echoed into the transcript, or a paste from the user) and the
    # adapter must not delete it.
    if not isinstance(message, dict) or message.get("role") != "system":
        return ""
    content = message.get("content", "")
    return content if isinstance(content, str) else ""
