from kyno import errors
from kyno.store.base import ConstitutionStore


def test_protocol_is_runtime_checkable():
    class Dummy:
        def head(self, constitution): ...
        def get(self, constitution, version): ...
        def versions_after(self, constitution, known_version): ...
        def publication(self, constitution): ...
        def published_names(self): ...
        def set_publication(self, constitution, *, published_at, history_public): ...
        def append(
            self,
            constitution,
            version,
            *,
            mission,
            principles,
            change_note,
            changed_mission,
            changed_principles,
            created_by,
        ): ...

    assert isinstance(Dummy(), ConstitutionStore)


def test_error_hierarchy():
    for name in (
        "UnknownConstitutionError",
        "UnknownVersionError",
        "EmptyChangeError",
        "VersionConflictError",
        "CorruptStateError",
    ):
        assert issubclass(getattr(errors, name), errors.CoherenceError)
