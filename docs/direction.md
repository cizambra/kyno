# Direction at runtime

Direction describes what an organization is trying to accomplish and the
principles its agents use to judge tradeoffs. Kyno gives that direction an
identity, a current version, immutable history, and an interface for reading
it while a system runs. That is what we mean by a runtime primitive: the
application can name, retrieve, and record direction independently of any
one task or prompt.

Humans define the mission and principles. Agents apply them when choosing
how to carry out their work. A named constitution is the document that holds
this direction; applying an edit creates a new version.

## Instructions, policies, and direction

These concerns answer different questions in an agent system:

| Concern | Question | Example |
| --- | --- | --- |
| Task instruction | What should this step do? | Draft a reply to this customer's cancellation request. |
| Policy or permission | What actions are allowed? | Refunds above $100 require human approval. |
| Direction | What outcome matters, and how should tradeoffs be judged? | Preserve customer trust; respect a customer's decision to leave. |

The orchestrator owns task execution. Permissions and approval mechanisms
limit available actions. Direction guides judgment within those boundaries.
The application owns verification and decides what to do with its results.

## One task, updated direction

The task can stay the same while the organization changes its priorities.
For example, an application might keep asking an agent to draft a response
to a cancellation request while changing its mission from increasing
renewals to making cancellation straightforward.

This runnable local example requires `pip install kyno`. It uses an in-memory
store and no model or network connection:

```python
from kyno.sdk import DirectionBinder, LocalDirectionSource
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

store = SqlConstitutionStore(url="sqlite:///:memory:")
store.create_all()
core = ControlPlane(store)
task = "Draft a reply to this customer's cancellation request."

try:
    core.apply_direction(
        constitution_key="support",
        mission="Help customers find reasons to renew",
        principles=["Explain available options clearly"],
        change_note="Initial support direction",
    )
    binder = DirectionBinder(LocalDirectionSource(core), "support")
    first = binder.bind()

    core.apply_direction(
        constitution_key="support",
        mission="Make cancellation straightforward",
        principles=["Respect the customer's decision to leave"],
        change_note="Prioritize a clear cancellation process",
    )
    second = binder.bind()

    print(task)
    print(first.version, first.mission)
    print(second.version, second.mission)
finally:
    store.engine.dispose()
```

Expected output:

```text
Draft a reply to this customer's cancellation request.
1 Help customers find reasons to renew
2 Make cancellation straightforward
```

Both reads belong to the `support` constitution. The task string is unchanged;
Kyno has supplied two versions of the direction available to the application.
A model's response still depends on how the application supplies that direction
and how the model interprets it.

## How direction reaches an agent

Models receive direction through their input context. An adapter retrieves it
before a step and supplies the rendered block alongside task instructions.
The block carries the constitution key and version, so the application can
record which direction it supplied. A prompt is one place to carry that copy;
the version and history remain available through Kyno.

Use a shipped [CrewAI](crewai.md) or [LangGraph](langgraph.md) adapter, or follow
the [adapter guide](integrating.md) to connect another runtime. Successful
pulls return the current direction at the time of the read. Failed pulls follow
the binder's [failure policy](adapters.md#inspecting-binding-status).

`Direction` contains the selected version's mission, principles, declaration,
key, and detail level. `DirectionBinding` adds information about a particular
read: its status, recording receipt, change notes, and delta. Two consumers
reading the same constitution version and detail receive equal Directions,
even when their last-seen versions differ. Their binding metadata can differ.

## Agentic self-governance

Shared direction lets agents make local decisions with a common mission and
principles. This supports bottom-up agency: humans set direction and boundaries,
and agents choose how to carry out their tasks within them. Applications can
verify the resulting work and choose whether to continue, retry, or request
human review. Kyno supplies the direction and records delivery when configured;
it does not observe or certify the agent's reasoning or actions.

Start with [writing constitutions](constitutions.md) to define direction,
then use the [adapter guide](adapters.md) to supply it at execution boundaries.
