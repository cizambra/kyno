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

Only add this if your application needs a separate record of the direction
supplied to each model call. It is not required by the adapter.

Record the state received by the work node, not the binder's latest cached
value. Use `kyno_direction` directly: it contains the exact rendered block,
including any change notes and delta. Use `direction_from_state()` when you
need the structured `Direction` fields rather than the rendered text.

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

You can use Kyno without checking the model's answer. If you want to add a
review, put it in a node owned by your application, after the node that
generates the answer. That review can call a verifier such as Canon. Your
application decides what to do with the result; Kyno does not call the
verifier or choose the graph's next step.

To extend the support-answer example, replace its `State` and `answer`
definitions with these. Keep the same binder, `SCENARIO`, and model.
The `answer` node now saves three things together in `answer_record`:
the `Direction` it read, the direction text it sent to the model, and the
answer returned by that call. The next node can review that answer
without guessing which direction accompanied it.

`AnswerRecord` describes this application-defined record. It is not a
Kyno storage service, and the adapter does not create it automatically.
The `review_answer` function below is also application code, not a Kyno hook:

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

`review_answer` reads the record written by `answer`. It sets `needs_review`
to `True` if the answer contains "refund has been issued", ignoring capitalization.
This is a Python string check; it does not call a model or an external verifier.
It does not understand the sentence: "No refund has been issued" would also match.
The example shows where your application can check an answer, not how to assess
whether it follows the direction. Use checks appropriate to your application.
A verifier called from this node can use `record["direction"]`,
`record["supplied_message"]`, and `record["output"]` to review that same call.

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
automatically pause, retry, or block anything. Your application must
decide how to handle it, such as asking a person before sending the answer.
The string check calls no service, but generating the answer still calls
your configured model and may incur provider charges. Keep the connection
open during execution and close it afterward, as in the required integration.

For example, an answer might receive version 1, then a later node might
pull version 2 before review. The graph's current `kyno_` fields would
describe version 2, but `answer_record` still holds the version 1 input
and its answer. Use that record when reviewing what the original call
received; do not replace it with the latest direction.

This example keeps one answer record and runs its nodes in sequence.
If your graph generates several answers in parallel, give each call its
own record and ID. Use a LangGraph reducer, a function that combines
updates from different branches, to collect those records rather than
having every branch overwrite the same `answer_record` field.
