# Integrating Kyno with CrewAI

[Adapter overview](adapters.md) · [LangGraph guide](langgraph.md)

Kyno refreshes direction in CrewAI's model messages before each model
call. You keep your existing agents, tasks, and crew.

## Install and connect

```bash
pip install "kyno[crewai]"
```

The example below uses your default remote profile. See
[connection configuration](adapters.md#the-integration) for named profiles
and explicit credentials.

## Required integration

Create a `CrewAiKyno` adapter and register its hook while your crew runs:

```python
import kyno
from kyno.adapters.crewai import CrewAiKyno

with kyno.connect() as connection:
    binder = connection.binder()
    adapter = CrewAiKyno(binder, constitution="customer-support")
    adapter.register()
    try:
        result = crew.kickoff()
    finally:
        adapter.unregister()
```

`crew` is your application's configured CrewAI crew, not an object Kyno
creates. You do not need to override a method, write a model-calling
wrapper, or manually insert direction into its messages.

Registration uses CrewAI's global before-call hook registry. Keep its
lifetime limited to the calls you intend to bind to this constitution;
it is not scoped to the `crew` variable. Unregistering removes this
adapter's hook without clearing unrelated hooks.

## What Kyno provides

Before each model call, the hook pulls direction, applies the binder's
failure policy, and replaces the previous Kyno direction block in the
messages. The block names the constitution and version and includes the
mission, principles, and change context. Other messages are preserved.

Use `connection.binder(context="full")` if the model also needs the
declaration and principle descriptions. No callback, receipt storage,
run ID, or step ID is required for direction injection.

## Failure behavior

By default, a failed pull uses cached direction, or empty version-0
direction if no value was cached. The binder reports the fallback through
telemetry. To raise instead of supplying fallback direction:

```python
from kyno.sdk import PullPolicy

binder = connection.binder(policy=PullPolicy(fail_closed=True))
```

Pass this binder to `CrewAiKyno` before registering the hook. See the
[shared failure and status reference](adapters.md#inspecting-delivery-status).

## Optional recording

Pass `on_direction` only if you want to observe the direction supplied
before each model call. The callback receives an immutable
`DirectionBinding` after the hook has inserted its rendered direction
into the messages:

```python
observed_bindings = []
adapter = CrewAiKyno(
    binder,
    constitution="customer-support",
    on_direction=observed_bindings.append,
)
```

Register and unregister this adapter around your crew's execution as in
the required integration. In this example, `observed_bindings` is an
application-owned list, not storage Kyno creates. Its `append` method
is the observer; you do not need to override an adapter method.

Each binding contains `direction` and `status`. The status is a
`DeliveryStatus` enum: `current`, `cached`, or `empty`, with the
[shared meanings](adapters.md#inspecting-delivery-status). Use
`binding.direction.render()` for the exact direction block, including
the selected compact/full context, change notes, and delta. Later pulls
do not change previously received bindings.

If you need durable per-call receipts, replace `append` with your own
synchronous recording function. Your application assigns run/call IDs,
captures the time, and chooses storage. The observer receives no task
output or framework call ID; it reports supplied context before the model
call, not completion or proof that the model followed direction. Do not
infer a task/output association from callback order in parallel work.

The observer runs once per successful injection and adds no pull. A failed
injection or a fail-closed pull emits no observer callback. If the observer
raises an ordinary exception, Kyno logs it and leaves the injected
direction in place. Its return value is ignored: it is not an approval
gate. This is best-effort observation, not mandatory durable auditing.
The callback runs synchronously, so slow recording delays the model call.

The adapter accepts an optional `trace` and provides `task_callback` and
`step_callback` methods for application-configured tracing. These read
the binder's latest cached direction when the callback runs. A task can
contain multiple model calls, so a task record is not an exact record of
the direction supplied to every call. Trace types remain outside the
stable top-level SDK API.

Neither tracing nor separate receipt storage is required to run the
adapter. Keep any retained prompts, direction, and outputs in storage
appropriate for potentially sensitive content.

## Optional verification

Kyno does not judge model output. To review finished tasks, supply an
external judge and attach the adapter's task callback when constructing
your crew:

```python
from crewai import Crew
from kyno.sdk import RealignmentGate

adapter = CrewAiKyno(
    binder,
    constitution="customer-support",
    gate=RealignmentGate(source=your_judge),
)
crew = Crew(agents=agents, tasks=tasks, task_callback=adapter.task_callback)
```

`your_judge` implements `VerdictSource`; `agents` and `tasks` are your
application's CrewAI configuration. Register and unregister this adapter
around execution as shown in the required integration. `register()` does
not attach the task callback for you. If you already use a task callback,
compose the two in your own callback.

A halt decision raises `TaskBlockedByKyno`. CrewAI cannot resume a paused
task through this adapter, so a pause decision also blocks. Review uses
the direction cached at task completion, not a reconstruction of every
model call's input. See [the shared gate reference](adapters.md#the-realignment-gate)
for verdict and failure policies. Neither a gate nor a judge is required
to consume direction.
