# Integrating Kyno with LangGraph

[Adapter overview](adapters.md) · [CrewAI guide](crewai.md)

Kyno puts direction in graph state. Your model-calling node puts that
direction into the model's input.

For a complete run with an operator changing direction between model calls,
see the [customer-support example](../examples/customer_support/README.md).
It includes optional recording; that recording code is not required by the adapter.

## Install and connect

```bash
pip install "kyno[langgraph]"
```

```python
import kyno

connection = kyno.connect()
binder = connection.binder()
```

This uses your default remote profile. See [connection configuration](adapters.md#the-integration)
for named profiles and explicit credentials. Keep the connection open
while the graph runs, then call `connection.close()`.

## Required integration

Kyno supplies `KynoState`, `direction_node`, and `pull_before`. You supply
the graph and the node that calls your model.

1. Inherit `KynoState` in your graph's state schema. LangGraph only carries
   keys declared by that schema.
2. Wrap your model-calling node with `pull_before`, or place a
   `direction_node` before it in the graph. Choose one boundary; using both
   there would pull twice.
3. Include `state["kyno_direction"]` in the model's input. The adapter
   populates graph state; it does not modify your model's messages for you.

With a binder from `connection.binder()` and your configured chat model,
the node can look like this:

```python
from kyno.adapters.langgraph import KynoState, pull_before


class State(KynoState, total=False):
    messages: list[dict]
    output: str


@pull_before(binder, constitution="customer-support")
def answer(state):
    messages = [
        {"role": "system", "content": state["kyno_direction"]},
        *state["messages"],
    ]
    return {"output": model.invoke(messages).content}
```

`answer` is an example name for your own graph node, not a Kyno function
to implement or override. Decorate your existing node and register it in
your graph as usual. `model` is your application's model client.

The decorator pulls once before the node runs, applies the binder's
failure policy, and supplies direction and delivery metadata in state.
You do not need to implement those steps yourself. You also do not need
receipt storage, run IDs, or step IDs for this integration to work.

## What Kyno provides

Before your work node runs, `direction_node` or `pull_before` supplies the
direction and sets `state["kyno_delivery_status"]` automatically. Your application
does not need to set or convert this value. It is one of three named values
from `DeliveryStatus`, imported from `kyno.sdk`:

- `DeliveryStatus.CURRENT`: the read succeeded at this step's direction boundary.
- `DeliveryStatus.CACHED`: the read failed, so Kyno supplied previously read direction.
- `DeliveryStatus.EMPTY`: the read failed and no cached direction was available.

The status describes how this step received its direction, not whether the
model followed it. See the [shared status reference](adapters.md#inspecting-delivery-status).

### Optional: saving and resuming graph state

A checkpoint is a saved snapshot of graph state. If you configure a
LangGraph checkpointer, the direction keys are saved with the graph's
other state. LangGraph's default serializer restores the `DeliveryStatus`
enum when you load that checkpoint; no manual conversion is needed.
Kyno does not configure checkpoint storage for you. You do not need
checkpointing just to give your agents direction.

A direction node before a fan-out supplies the same snapshot to its branches.
Later pulls do not change earlier receipts. Resuming a checkpoint without
another pull preserves the original delivery status; it does not establish
that the saved version is still current. Work nodes should leave the
`kyno_` direction keys unchanged so the checkpoint describes their input.

### Only if you write your own JSON import

Exporting state with `json.dumps` writes the status as `"current"`, `"cached"`,
or `"empty"`. Reading that JSON with `json.loads` returns a plain string,
not a `DeliveryStatus` enum. This is separate from normal LangGraph checkpointing.

If your application rebuilds direction state from that JSON, pass the saved
status to `direction_update(direction, status=saved_status)`. This converts it
back to the enum and rejects unrecognized values. Here, `direction` is the
`Direction` you reconstructed and `saved_status` is the JSON's
`kyno_delivery_status` value.

A missing status or `None` means unknown, not a successful read. Calling
`direction_update(direction)` without a status writes `None`, clearing any
status left from an earlier binding. You do not need this manual helper when
using `direction_node` or `pull_before` normally.

## Failure behavior

By default, a failed pull uses cached direction, or empty version-0
direction if no value was cached. The status in state identifies the
fallback. To stop before the wrapped work node runs instead:

```python
from kyno.sdk import PullPolicy

binder = connection.binder(policy=PullPolicy(fail_closed=True))
```

Create this binder before wiring your direction boundary.
See the [shared failure and status reference](adapters.md#inspecting-delivery-status).

## Optional recording

Only add this if your application needs a separate record of the direction
supplied to each model call. It is not required by the adapter.

Record the state received by the work node, not the binder's latest cached
value. Use `kyno_direction` directly: it contains the exact rendered block,
including any change notes and delta. Rebuilding it with
`direction_from_state()` loses that change context.

For example, insert this inside your node after constructing the model's
messages and before calling the model:

```python
record_receipt(
    run_id=state["run_id"],
    step_id=state["step_id"],
    constitution=state["kyno_constitution"],
    version=state["kyno_version"],
    status=state["kyno_delivery_status"],
    context=state["kyno_context"],
    direction=state["kyno_direction"],
)
```

`record_receipt` is an application-defined function, not a Kyno API.
If you choose this extension, provide that function, declare `run_id` and
`step_id` in your state schema, and assign a unique step ID within each
run. Store receipts only where you intend to retain potentially
sensitive direction. A receipt records supplied context, not a completed
model call or evidence that the model followed it.


## Optional verification

Kyno does not judge model output. If you supply an external judge, add a
gate node after your work node:

```python
from kyno.adapters.langgraph import gate_node
from kyno.sdk import RealignmentGate

review = gate_node(RealignmentGate(source=your_judge, can_pause=True))
```

Here `your_judge` implements `VerdictSource`; `review` is the node you add
to your graph. A pause decision uses LangGraph's interrupt mechanism.
Your application configures checkpointing and handles resume. Other halt
decisions are returned in `kyno_blocked`; route on that value if downstream
work must stop. A gate node does not choose your graph's next edge.

See [the shared gate reference](adapters.md#the-realignment-gate) for
verdict and failure policies. Neither a gate nor a judge is required to
consume direction.
