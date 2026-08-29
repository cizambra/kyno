from hypothesis import given, settings
from hypothesis import strategies as st

from kyno.models import normalize_principles
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

# A title must survive being stripped; the shapes are mixed on purpose, so
# the change-detection property covers described and title-only principles
# in the same sequence.
title = st.text(min_size=1, max_size=6).filter(lambda s: s.strip())
principle = st.one_of(
    title,
    st.fixed_dictionaries({"title": title, "description": st.text(max_size=8)}),
)
op = st.tuples(
    st.one_of(st.none(), st.text(min_size=1, max_size=12)),
    st.one_of(st.none(), st.lists(principle, max_size=4)),
).filter(lambda t: t[0] is not None or t[1] is not None)


@settings(max_examples=100, deadline=None)
@given(ops=st.lists(op, min_size=1, max_size=25))
def test_given_any_edit_history_when_asking_changes_since_then_current_and_changed_reconstruct(ops):
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)

    prev_mission, prev_principles = None, None
    applied = []  # (version, changed_mission, changed_principles)
    for mission, principles in ops:
        want_mission = mission if mission is not None else prev_mission
        want_principles = normalize_principles(principles)
        if want_principles is None:
            want_principles = prev_principles
        if applied:
            cm = want_mission != prev_mission
            cp_changed = want_principles != prev_principles
            if not (cm or cp_changed):
                continue  # no-op would raise; skip to mirror engine semantics
        v = cp.set_direction(
            mission=mission,
            principles=principles,
            change_note="n",
        )
        applied.append((v.version, v.changed_mission, v.changed_principles))
        prev_mission, prev_principles = v.mission, v.principles

    if not applied:
        return
    head = cp.current()
    c = cp.changes_since(0)
    assert c.current_version == head.version
    assert c.mission == head.mission and c.principles == head.principles
    assert c.changed_mission == any(a[1] for a in applied)
    assert c.changed_principles == any(a[2] for a in applied)
    if len(applied) >= 2:
        k = applied[len(applied) // 2 - 1][0]
        tail = [a for a in applied if a[0] > k]
        ct = cp.changes_since(k)
        assert ct.changed_mission == any(a[1] for a in tail)
        assert ct.changed_principles == any(a[2] for a in tail)
        assert len(ct.change_notes) == len(tail)
