# SPDX-License-Identifier: Elastic-2.0
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from kyno.models import ConstitutionVersion, Principle, Publication


@runtime_checkable
class ConstitutionStore(Protocol):
    def head(self, constitution: str) -> ConstitutionVersion | None: ...

    def get(self, constitution: str, version: int) -> ConstitutionVersion | None: ...

    def versions_after(
        self, constitution: str, known_version: int
    ) -> list[ConstitutionVersion]: ...

    def publication(self, constitution: str) -> Publication: ...

    def published_names(self) -> list[str]: ...

    def set_publication(
        self, constitution: str, *, published_at: datetime | None, history_public: bool
    ) -> bool: ...

    def append(
        self,
        constitution: str,
        version: int,
        *,
        mission: str,
        principles: tuple[Principle | str, ...],
        change_note: str,
        declaration: str = "",
        changed_mission: bool,
        changed_principles: bool,
        created_by: str | None,
    ) -> ConstitutionVersion: ...
