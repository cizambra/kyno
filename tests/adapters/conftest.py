import pytest

from kyno.models import COMPACT, ChangesSince
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def control_plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


class ScriptedDirectionSource:
    """A fake Kyno: every reply is scripted, so adapter tests never depend
    on a store, a socket, or a model."""

    def __init__(self, replies: dict[str, ChangesSince] | None = None):
        self.replies = replies or {}
        self.failure: Exception | None = None
        self.calls: list[tuple[int, str]] = []
        self.details: list[str] = []

    def set(self, constitution: str, version: int, mission: str, *principles: str) -> None:
        self.replies[constitution] = ChangesSince(
            current_version=version,
            changed=True,
            mission=mission,
            principles=tuple(principles),
            changed_mission=True,
            changed_principles=bool(principles),
            change_notes=(f"v{version}",),
        )

    def changes_since(
        self, known_version: int, constitution: str, detail: str = COMPACT
    ) -> ChangesSince:
        self.calls.append((known_version, constitution))
        self.details.append(detail)
        if self.failure is not None:
            raise self.failure
        return self.replies[constitution]


@pytest.fixture
def scripted_source():
    return ScriptedDirectionSource()
