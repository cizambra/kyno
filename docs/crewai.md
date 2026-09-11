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

For output records, the application must keep the corresponding input
and output together using its own framework or model instrumentation.
The observer alone cannot identify that pair. When your application has
the correct pair, it can use `RunTrace.record_step` from `kyno.sdk.trace`
to record the output with its supplied `Direction`. Trace types remain
outside the stable top-level SDK API.

Neither tracing nor separate receipt storage is required to run the
adapter. Keep any retained prompts, direction, and outputs in storage
appropriate for potentially sensitive content.

## Optional verification

Your application calls a verifier, such as Canon, and decides whether to
accept, retry, escalate, or stop work. Kyno supplies direction; CrewAI
callbacks and execution decisions belong to your application.

To assess the final crew output against a deliberately chosen direction
snapshot, select it before the `crew.kickoff()` call in the required
integration above:

```python
assessment_direction = binder.bind("customer-support")
```

After that call returns `result` and the hook is unregistered, assess the
output against the selected snapshot:

```python
assessment = assess_output(
    output=result.raw,
    direction=assessment_direction,
)
handle_assessment(result, assessment)
```

`assess_output` and `handle_assessment` are functions your application
implements, not Kyno or Canon APIs. The first calls your chosen verifier;
the second interprets its result and chooses what happens next. Keep the
assessment direction with the output and verifier result in your own
records. Apply your required availability policy when selecting it.

This assesses the final output against the snapshot selected before the
crew ran. It does not claim that every contributing model call received
that version: direction can change during a task. To assess an individual
call against what it actually received, capture that call's injected
messages and output together under an application-owned call identity.
Parallel calls need separate records; observer order or the binder's
latest cached value cannot establish that association. Assessing against
a newer version is also an application choice and should be recorded as
such. Verification is optional and requires no Kyno wrapper.
