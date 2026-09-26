from dataclasses import replace
from unittest.mock import Mock

import pytest

pytest.importorskip("crewai")

from kyno.adapters.crewai.hooks import CrewAiKyno  # noqa: E402
from kyno.sdk.binder import DirectionBinder  # noqa: E402
from kyno.sdk.binding import BindingStatus  # noqa: E402
from kyno.sdk.cell import DIRECTION_MARKER  # noqa: E402
from kyno.sdk.errors import KynoUnavailableError  # noqa: E402
from kyno.sdk.policy import PullPolicy  # noqa: E402
from kyno.wire.models import DetailLevel  # noqa: E402


class FakeCtx:
    """A stand-in for LLMCallHookContext: before_llm_call only touches
    messages, so this carries nothing task-shaped."""

    def __init__(self, messages=None, agent="researcher", task="Find lenders"):
        self.messages = messages if messages is not None else []
        self.agent = agent
        self.task = task


@pytest.fixture
def unit_kyno(scripted_source):
    scripted_source.set("default", 1, "M1", "Be honest")
    binder = DirectionBinder(scripted_source)
    binder.bind()
    adapter = CrewAiKyno(binder)
    return adapter, scripted_source


def test_given_second_positional_argument_when_CrewAiKyno_is_created_then_TypeError_is_raised(
    scripted_source,
):
    with pytest.raises(TypeError, match="positional"):
        CrewAiKyno(DirectionBinder(scripted_source), object())


def test_given_adapter_when_register_and_clear_all_hooks_run_then_neither_raises(unit_kyno):
    from crewai.hooks import clear_all_hooks

    adapter, _cp = unit_kyno
    try:
        adapter.register()
    finally:
        clear_all_hooks()


def test_given_registered_adapter_when_unregister_runs_then_before_llm_call_is_removed(unit_kyno):
    from crewai.hooks import clear_all_hooks, get_before_llm_call_hooks

    adapter, _cp = unit_kyno
    try:
        adapter.register()
        assert adapter.before_llm_call in get_before_llm_call_hooks()
        assert adapter.unregister() is True
        assert adapter.before_llm_call not in get_before_llm_call_hooks()
    finally:
        clear_all_hooks()


def test_given_message_list_when_before_llm_call_runs_then_direction_is_inserted_in_place(
    unit_kyno,
):
    """CrewAI's executor holds this list; rebinding it drops the injection."""
    adapter, _cp = unit_kyno
    messages = [{"role": "user", "content": "go"}]
    ctx = FakeCtx(messages=messages)

    adapter.before_llm_call(ctx)

    assert ctx.messages is messages
    assert messages[0]["content"].startswith(DIRECTION_MARKER)


def test_given_markers_in_user_or_tool_messages_when_before_llm_call_runs_then_messages_are_kept(
    unit_kyno,
):
    """The adapter replaces only the block it injected, which is a system
    message. Marker text arriving any other way (a tool result echoed into
    the transcript, or a paste from the user) is data, not something to
    delete."""
    adapter, _cp = unit_kyno
    echoed = {"role": "tool", "content": f"{DIRECTION_MARKER} constitution_key=x version=9]"}
    pasted = {"role": "user", "content": f"{DIRECTION_MARKER} quoted by a person"}
    ctx = FakeCtx(messages=[echoed, pasted])

    adapter.before_llm_call(ctx)

    assert echoed in ctx.messages
    assert pasted in ctx.messages
    assert ctx.messages[0]["role"] == "system"
    blocks = [m for m in ctx.messages if m["role"] == "system"]
    assert len(blocks) == 1


def test_given_non_dict_message_when_before_llm_call_runs_then_message_is_kept(
    unit_kyno,
):
    """CrewAI may hand over message objects, not dicts; never drop them."""
    adapter, _cp = unit_kyno
    other = object()
    ctx = FakeCtx(messages=[other, {"role": "user", "content": "go"}])

    adapter.before_llm_call(ctx)

    assert ctx.messages[1] is other
    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)


@pytest.mark.parametrize("status", list(BindingStatus))
@pytest.mark.parametrize("detail", list(DetailLevel))
def test_given_observer_when_before_llm_call_runs_then_binding_is_reported_after_injection(
    scripted_source, status, detail
):
    scripted_source.set("support", 2, "Help customers", "Be honest")
    scripted_source.replies["support"] = replace(
        scripted_source.replies["support"],
        declaration="Explain the complete resolution.",
        delta=("Mission changed.",),
    )
    binder = DirectionBinder(scripted_source, "support", detail=detail)
    if status is BindingStatus.CACHED:
        binder.bind()
    if status is not BindingStatus.PULLED:
        scripted_source.failure = OSError("offline")
    scripted_source.calls.clear()
    messages = [{"role": "user", "content": "Help"}]
    ctx = FakeCtx(messages=messages)
    observed = []

    def observe(binding):
        observed.append((binding, [message.copy() for message in ctx.messages]))

    adapter = CrewAiKyno(binder, on_direction=observe)
    adapter.before_llm_call(ctx)

    assert len(observed) == 1
    binding, captured_messages = observed[0]
    assert binding.status is status
    assert binding.direction.constitution_key == "support"
    assert binding.direction.detail is detail
    assert binding.direction.version == (0 if status is BindingStatus.EMPTY else 2)
    assert captured_messages == messages
    assert messages[0]["content"] == binding.direction.render()
    assert ctx.messages is messages
    assert len(scripted_source.calls) == 1


def test_given_observer_returning_false_when_before_llm_call_runs_then_hook_returns_none(
    scripted_source,
):
    scripted_source.set("default", 1, "Help")
    observer = Mock(return_value=False)
    adapter = CrewAiKyno(DirectionBinder(scripted_source), on_direction=observer)
    ctx = FakeCtx()

    assert adapter.before_llm_call(ctx) is None

    observer.assert_called_once()
    assert "Mission: Help" in ctx.messages[0]["content"]


def test_given_new_direction_when_before_llm_call_runs_again_then_prior_binding_keeps_its_version(
    scripted_source,
):
    scripted_source.set("support", 1, "M1")
    observed = []
    adapter = CrewAiKyno(DirectionBinder(scripted_source, "support"), on_direction=observed.append)
    ctx = FakeCtx()
    adapter.before_llm_call(ctx)
    first_block = ctx.messages[0]["content"]
    scripted_source.set("support", 2, "M2")
    adapter.before_llm_call(ctx)

    first, second = observed
    assert first.direction.version == 1
    assert first.direction.render() == first_block
    assert second.direction.version == 2
    assert second.direction.render() == ctx.messages[0]["content"]
    assert first.status is second.status is BindingStatus.PULLED
    assert len(ctx.messages) == 1


def test_given_observer_error_when_before_llm_call_runs_then_error_is_logged_without_raising(
    scripted_source, caplog
):
    scripted_source.set("support", 3, "Help")
    observer = Mock(side_effect=RuntimeError("recording failed"))
    adapter = CrewAiKyno(DirectionBinder(scripted_source, "support"), on_direction=observer)
    ctx = FakeCtx()

    assert adapter.before_llm_call(ctx) is None

    observer.assert_called_once()
    assert "Mission: Help" in ctx.messages[0]["content"]
    assert "direction observer failed constitution_key=support version=3" in caplog.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("cached", [False, True])
def test_given_fail_closed_pull_error_when_before_llm_call_runs_then_no_injection_or_notification(
    scripted_source, cached
):
    scripted_source.set("default", 1, "M1")
    binder = DirectionBinder(scripted_source, policy=PullPolicy(fail_closed=True))
    if cached:
        binder.bind()
    scripted_source.failure = OSError("offline")
    observer = Mock()
    adapter = CrewAiKyno(binder, on_direction=observer)
    ctx = FakeCtx(messages=[{"role": "user", "content": "Help"}])

    with pytest.raises(KynoUnavailableError):
        adapter.before_llm_call(ctx)

    observer.assert_not_called()
    assert ctx.messages == [{"role": "user", "content": "Help"}]


def test_given_injection_error_when_before_llm_call_runs_then_observer_is_not_called(
    scripted_source,
):
    class UnwritableMessages(list):
        def __setitem__(self, key, value):
            raise RuntimeError("cannot inject")

    scripted_source.set("default", 1, "M1")
    observer = Mock()
    adapter = CrewAiKyno(DirectionBinder(scripted_source), on_direction=observer)

    with pytest.raises(RuntimeError, match="cannot inject"):
        adapter.before_llm_call(FakeCtx(messages=UnwritableMessages()))

    observer.assert_not_called()


def test_given_same_version_when_before_llm_call_runs_twice_then_observer_is_notified_twice(
    scripted_source,
):
    scripted_source.set("default", 2, "Help")
    observed = []
    ctx = FakeCtx()
    adapter = CrewAiKyno(DirectionBinder(scripted_source), on_direction=observed.append)
    adapter.before_llm_call(ctx)
    first_block = ctx.messages[0]["content"]
    scripted_source.replies["default"] = replace(
        scripted_source.replies["default"],
        changed=False,
        changed_mission=False,
        changed_principles=False,
        change_notes=(),
        delta=(),
    )

    adapter.before_llm_call(ctx)

    first, second = observed
    assert first.direction.version == second.direction.version == 2
    assert first.status is second.status is BindingStatus.PULLED
    assert first.direction.render() == first_block
    assert second.direction.render() == ctx.messages[0]["content"]
    assert second.direction.change_notes == ()
    assert scripted_source.calls == [(0, None), (2, "default")]


def test_given_prior_observer_error_when_before_llm_call_runs_again_then_observer_is_called(
    scripted_source, caplog
):
    scripted_source.set("default", 1, "M1")
    observer = Mock(side_effect=[RuntimeError("recording failed"), None])
    adapter = CrewAiKyno(DirectionBinder(scripted_source), on_direction=observer)
    ctx = FakeCtx()
    adapter.before_llm_call(ctx)
    scripted_source.set("default", 2, "M2")

    adapter.before_llm_call(ctx)

    assert observer.call_count == 2
    first, second = [call.args[0] for call in observer.call_args_list]
    assert (first.direction.version, second.direction.version) == (1, 2)
    assert second.direction.render() == ctx.messages[0]["content"]
    assert second.status is BindingStatus.PULLED
    assert sum("direction observer failed" in record.message for record in caplog.records) == 1


def test_given_user_message_when_before_llm_call_runs_then_direction_is_injected_and_none_returns(
    unit_kyno,
):
    adapter, _source = unit_kyno
    ctx = FakeCtx(messages=[{"role": "user", "content": "go"}])

    assert adapter.before_llm_call(ctx) is None

    assert ctx.messages[0]["content"].startswith(DIRECTION_MARKER)
    assert ctx.messages[-1] == {"role": "user", "content": "go"}
