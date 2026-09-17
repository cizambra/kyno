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
from kyno.sdk import DetailLevel, PullPolicy

connection = kyno.connect()
binder = connection.binder(
    context=DetailLevel.FULL,
    policy=PullPolicy(fail_closed=True),
)
```

This uses your default remote profile. See [connection configuration](adapters.md#the-integration)
for named profiles and explicit credentials. Keep the connection open
while the graph runs, then call `connection.close()`.

This guide requests full direction and stops if a read fails.
These are example settings, not the SDK defaults.

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

This node drafts a response to a delivery complaint using the binder above
and your configured chat model:

```python
from kyno.adapters.langgraph import KynoState, pull_before
from kyno.sdk import DeliveryStatus

SCENARIO = (
    "A customer paid $40 for express delivery. The package arrived two days late. "
    "They ask for the delivery fee back and an explanation. Tracking confirms the delay. "
    "You may draft a reply, propose a refund of up to $40, or propose escalation to a person. "
    "Do not execute any action or claim a refund has already been issued. "
    "Choose a response and explain the tradeoff using the supplied mission and principles."
)


class State(KynoState, total=False):
    output: str


@pull_before(binder, constitution="customer-support")
def answer(state):
    if state["kyno_version"] == 0 or state["kyno_delivery_status"] != DeliveryStatus.CURRENT:
        raise ValueError("A current, written constitution is required before calling the model")
    messages = [
        {"role": "system", "content": state["kyno_direction"]},
        {"role": "user", "content": SCENARIO},
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

### Optional: LangGraph checkpoints

A checkpoint is a saved snapshot of a workflow's state that LangGraph can use to resume
the workflow later. A checkpointer is the component that saves and loads
those snapshots. See [LangGraph's persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence).

Kyno adds direction and delivery status to graph state. If your graph uses
a LangGraph checkpointer, it saves those fields alongside the rest of the
workflow's state. LangGraph's default serializer restores the `DeliveryStatus`
enum when you load that checkpoint; no manual conversion is needed.
Kyno does not configure checkpoint storage for you. You do not need
checkpointing just to give your agents direction.

Continue the [support-answer example](#required-integration) by adding this
code after the `answer` function. It uses the `State` class and decorated
`answer` node already defined there, with the same open connection, binder,
and model. You do not need another direction node: `answer` already pulls
through `@pull_before`.

This builds a one-node graph and adds checkpoint storage. Running it calls
your configured model once and may incur provider charges:

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

graph = (
    StateGraph(State)
    .add_node("answer", answer)
    .add_edge(START, "answer")
    .add_edge("answer", END)
    .compile(checkpointer=InMemorySaver())
)
config = {"configurable": {"thread_id": "support-example"}}
graph.invoke({}, config)

checkpoint = graph.get_state(config)
saved = checkpoint.values
print("Saved direction version:", saved["kyno_version"])
print("Delivery status at that step:", saved["kyno_delivery_status"].value)
print("Saved answer:", saved["output"])
```

`graph.invoke` runs `answer`: its decorator pulls direction, then the node
sends that direction and the complaint to your model. LangGraph saves the state
under the `support-example` thread ID. `graph.get_state(config)` retrieves
that thread's latest checkpoint; `checkpoint.values` is the dictionary of
saved state fields.

The first printed line identifies the direction version supplied to that
step. The second says how it was obtained: for example, `current` means the
read succeeded at that step. `.value` gets this text from the saved
`DeliveryStatus` enum. Reading the checkpoint does not contact Kyno, so it
cannot tell you whether a newer direction version has since been applied.

`InMemorySaver` keeps checkpoints only in this Python process. To retain
them after a restart, configure persistent storage through LangGraph. The
runnable customer-support script does not enable checkpointing; its optional
JSONL recording is a separate feature.

A direction node before a fan-out supplies the same snapshot to its branches.
Later pulls do not change earlier receipts. Resuming a checkpoint without
another pull preserves the original delivery status; it does not establish
that the saved version is still current. Work nodes should leave the
`kyno_` direction keys unchanged so the checkpoint describes their input.

## Failure behavior

The SDK's default policy uses cached direction after a failed read, or empty
version-0 direction if no value was cached. The binder in this guide instead
uses `PullPolicy(fail_closed=True)`:
a failed read stops the graph before the model call. The `answer` node also
rejects version 0, because a successful read can return an unwritten constitution.

Configure this policy when creating the binder, before decorating `answer`
or building the graph:

```python
from kyno.sdk import DetailLevel, PullPolicy

binder = connection.binder(
    context=DetailLevel.FULL,
    policy=PullPolicy(fail_closed=True),
)
```

This is the same binder configuration used in the setup section; you do not need
to create it a second time.
See the [shared failure and status reference](adapters.md#inspecting-delivery-status).

## Optional recording

`state["kyno_recording"]` carries the server's recording receipt as a plain
dictionary, or `None` when the source supplied no receipt. It travels with
the direction through graph state and checkpoints; it is not added to the
model's direction text. A `recorded` receipt contains a `record_id` that
identifies a stored Kyno delivery record. A `disabled` or `failed` receipt
has no record ID. These recording statuses are separate from
`kyno_delivery_status`, which describes whether direction was read or cached.

Recording is disabled by default. When recording succeeds, the record
describes Core's direction response before your graph uses it. That record
does not establish that the graph inserted direction into a model
request, that the model completed, or that its answer followed direction.
If a pull fails and the binder supplies cached direction, the receipt still
describes the original response's recording outcome; the failed pull creates no new ID.

To associate an answer with its delivery record, capture the receipt inside
the model-calling node and store its ID alongside the output in your own
storage. In the `answer` function above, replace its final return with:

```python
recording = state["kyno_recording"]
output = model.invoke(messages).content
save_answer(
    output=output,
    record_id=recording.get("record_id") if recording is not None else None,
    supplied_message=state["kyno_direction"],
)
return {"output": output}
```

`save_answer` is an application-defined storage function that you must
provide. Kyno stores direction delivery history, not model output. Keep
your outputs and supplied messages in storage appropriate for their
sensitivity. Capture the state received by this node, rather than reading
the binder's cache after the model call: another pull may have replaced it.
Use `direction_from_state()` when you also need structured direction fields.
For later inspection, you can use the saved delivery ID to
[retrieve the served direction version](integrating.md#current-and-historical-direction).

You can group delivery reads with an application-chosen
[correlation ID](integrating.md#associating-delivery-history-with-application-work).
For example, replace the binder setup above with:

```python
binder = connection.binder(
    context=DetailLevel.FULL,
    policy=PullPolicy(fail_closed=True),
    correlation_id="support-run-123",
)
```

Every pull through this binder carries the same correlation ID. It groups
recorded reads; it does not identify a model call or its output. Each recorded
read has its own `record_id`, while cached uses can share the original ID.


## Optional verification

Verification belongs to your application. You choose whether to verify, which
direction version to assess against, when to run the check, and what to do with
its result. Kyno supplies direction and delivery history; it does not call a
verifier or choose the graph's next step.

The example below illustrates one approach: keep an answer with the direction
supplied to that call, then check it in another node. To try it, replace the
support-answer example's `State` and `answer` definitions with these.
Keep the same binder, `SCENARIO`, and model.
The `answer` node now saves three things together in `answer_record`:
the `Direction` it read, the direction text it sent to the model, and the
answer returned by that call. The next node can review that answer
without guessing which direction accompanied it.

`AnswerRecord` is an illustrative application type, not a Kyno API or a required
storage format. `review_answer` is also application code:

```python
from typing import TypedDict

from kyno.adapters.langgraph import direction_from_state
from kyno.sdk import Direction


class AnswerRecord(TypedDict):
    direction: Direction
    supplied_message: str
    output: str


class State(KynoState, total=False):
    output: str
    answer_record: AnswerRecord
    needs_review: bool


@pull_before(binder, constitution="customer-support")
def answer(state):
    if state["kyno_version"] == 0 or state["kyno_delivery_status"] != DeliveryStatus.CURRENT:
        raise ValueError("A current, written constitution is required before calling the model")
    direction = direction_from_state(state)
    supplied_message = state["kyno_direction"]
    messages = [
        {"role": "system", "content": supplied_message},
        {"role": "user", "content": SCENARIO},
    ]
    output = model.invoke(messages).content
    return {
        "output": output,
        "answer_record": {
            "direction": direction,
            "supplied_message": supplied_message,
            "output": output,
        },
    }


def review_answer(state):
    record = state["answer_record"]
    needs_review = "refund has been issued" in record["output"].lower()
    return {"needs_review": needs_review}
```

The phrase check is only an illustration, not an alignment assessment.
Your own check can use the saved direction, supplied message, and output.

Build the graph after defining those nodes. The edge from `answer` to
`review_answer` tells LangGraph to run the review after the answer is ready;
you do not need to call `review_answer` yourself:

```python
from langgraph.graph import END, START, StateGraph

graph = (
    StateGraph(State)
    .add_node("answer", answer)
    .add_node("review_answer", review_answer)
    .add_edge(START, "answer")
    .add_edge("answer", "review_answer")
    .add_edge("review_answer", END)
    .compile()
)
result = graph.invoke({})
```

`graph.invoke({})` runs the sequence: pull direction, generate the answer,
review it, then finish. Read `result["output"]` for the answer and
`result["needs_review"]` for the check's result. A `True` result does not
automatically pause, retry, or block anything. Your application decides
whether any action follows.
The string check calls no service, but generating the answer still calls
your configured model and may incur provider charges. Keep the connection
open during execution and close it afterward, as in the required integration.

For example, an answer might receive version 1, then a later node might
pull version 2 before review. The graph's current `kyno_` fields would
describe version 2, but `answer_record` still holds the version 1 input
and its answer. Use that record when reviewing what the original call
received; do not replace it with the latest direction.

This illustrative graph keeps one answer record and runs sequentially.
For parallel work, your application owns the association between each output
and its input. A shared `answer_record` field cannot keep separate answers
from multiple branches.
