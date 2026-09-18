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
    binder = connection.binder("customer-support")
    adapter = CrewAiKyno(binder)
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

Use `connection.binder("customer-support", context="full")` if the model also needs the
declaration and principle descriptions. No callback, receipt storage,
run ID, or step ID is required for direction injection.

## Failure behavior

By default, a failed pull uses cached direction, or empty version-0
direction if no value was cached. The binder logs a warning through Python's
`kyno.sdk.binder` logger. To raise instead of supplying fallback direction:

```python
from kyno.sdk import PullPolicy

binder = connection.binder("customer-support", policy=PullPolicy(fail_closed=True))
```

Pass this binder to `CrewAiKyno` before registering the hook. See the
[shared failure and status reference](adapters.md#inspecting-binding-status).

## Optional recording

Pass `on_direction` only if you want to observe the direction supplied
before each model call. The callback receives an immutable
`DirectionBinding` after the hook has inserted its rendered direction
into the messages:

```python
observed_bindings = []
adapter = CrewAiKyno(
    binder,
    on_direction=observed_bindings.append,
)
```

Register and unregister this adapter around your crew's execution as in
the required integration. In this example, `observed_bindings` is an
application-owned list, not storage Kyno creates. Its `append` method
is the observer; you do not need to override an adapter method.

Each binding contains `direction`, `status`, and `recording`. The status is a
`BindingStatus` enum: `pulled`, `cached`, or `empty`, with the
[shared meanings](adapters.md#inspecting-binding-status). Use
`binding.direction.render()` for the exact direction block, including
the selected compact/full context, change notes, and delta. Later pulls
do not change previously received bindings.

`binding.recording` is the server's immutable recording receipt, or `None`
when the source supplied no receipt. Its `status` is a `RecordingStatus`:
`recorded`, `disabled`, or `failed`. A recorded receipt has a `record_id`
identifying a stored Kyno delivery record; the other statuses have no ID.
These statuses describe server recording, separately from how direction
was obtained. A failed pull using cached direction preserves the original
receipt rather than creating a new record ID.

Recording is disabled by default. When recording succeeds, the record
describes Core's direction response before the adapter injects it.
Its receipt does not prove injection, model completion, or that an answer
followed direction. The observer runs after injection, but still before
the model call.

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

To record which direction accompanied a model output, your application
must capture that call's input messages and output together. `on_direction`
cannot do this by itself: it runs before the call and receives neither
the output nor an ID identifying the call. Once your application has
matched an output to its supplied binding, store the output together with
`binding.recording.record_id` when a receipt is available. Kyno stores
direction delivery history; your application owns output storage and the
association between each call and its receipt. A record ID identifies a
server read, not a CrewAI task or model call; cached uses can share an ID.
For later inspection, you can use the saved delivery ID to
[retrieve the served direction version](integrating.md#current-and-historical-direction).

You can group delivery reads with an application-chosen
[correlation ID](integrating.md#associating-delivery-history-with-application-work).
For example, replace the binder setup in the required integration with:

```python
binder = connection.binder("customer-support", correlation_id="support-run-123")
```

Every pull through this binder carries the same correlation ID. It groups
recorded reads; it does not identify a model call or its output. The global hook
registry still requires the registration scope described above.

Separate application receipt storage is optional. Keep any retained
prompts, direction, and outputs in storage
appropriate for potentially sensitive content.

## Optional verification

Verification belongs to your application. You choose whether to verify, which
direction version to assess against, when to run the check, and what to do with
its result. Kyno supplies direction and delivery history; it does not call a
verifier or control the crew's next action.

For example, suppose you want to review the final answer against the
direction you read before starting the crew. Save that `Direction` object,
run the crew, then pass the answer and saved direction to your verifier.

This is an illustrative extension of the required integration, not a prescribed
verification workflow. As before, `crew` is your configured CrewAI crew.
Two functions below belong to your application; neither is provided by Kyno:

- `assess_output` calls your chosen verifier with the output and direction.
- `handle_assessment` reads its result and decides what to do next.

Replace these placeholders with your own functions to run this example.

```python
with kyno.connect() as connection:
    binder = connection.binder("customer-support")
    assessment_direction = binder.bind()
    adapter = CrewAiKyno(binder)
    adapter.register()
    try:
        result = crew.kickoff()
    finally:
        adapter.unregister()

    assessment = assess_output(
        output=result.raw,
        direction=assessment_direction,
    )
    handle_assessment(result, assessment)
```

`result.raw` is the final answer's text. Review runs after the crew
finishes, not after every model call. If you keep review records, save
the answer, `assessment_direction`, and the assessment together.

The saved direction does not change when the adapter pulls again. If you
save version 1 and an operator publishes version 2 while the crew runs,
later model calls can receive version 2. This example still reviews the
final answer against version 1. It does not claim every call used that
version. Your application chooses which version is relevant to its assessment.

The initial `binder.bind()` uses the same failure policy as other reads.
By default, a failed read returns cached direction, or empty version-0
direction if nothing was cached. If your review requires a successful
read, configure the binder as shown in [Failure behavior](#failure-behavior).
Also reject version 0 if your application requires a written constitution.

To review individual model calls instead, record each call's input and
output under the same ID in your application. Do not match outputs to
`on_direction` callbacks by their order: when two calls run at the same
time, the second can finish first. Reading the binder's cache afterward
does not identify a call's direction either; another call may already
have replaced it with a newer version.
