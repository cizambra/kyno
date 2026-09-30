# The agency model

Kyno supplies shared, versioned mission and principles for agents to use in
judgment. The integrating application decides which choices to delegate and
evaluates the result. Bottom-up agency comes from agents using that direction
to choose how to pursue the intended outcome.

Kyno works with or without AI governance tools or a formal top-down governance
system. Governance answers “What am I allowed to do?” Direction answers “What
outcome am I working toward, and what principles should guide my choices?”
Where the application has policies, permissions, or approval requirements,
agent judgment operates within them. The application and its governance tools
are responsible for enforcing those boundaries.

Runtime direction has an authoritative source. That alone does not establish
agency: if an integration prescribes every decision, it is using Kyno to
distribute versioned direction without delegating meaningful judgment.

This page describes the integration responsibilities. Kyno does not provide
a delegation engine, a principle-conflict resolver, a proposal review workflow,
or a detector of rationalization or behavioral drift.

## Which decisions are delegated?

Your application must define the choices an agent may make and the decisions
that remain with people or other systems. A constitution supplies direction;
it does not grant authority or select tools the agent may call.

For a support workflow, the division could be:

| Decision | Who decides? | Boundary |
| --- | --- | --- |
| How to explain a cancellation or refund | Agent | Use accurate information and respect the customer's choice. |
| Which permitted remedy to recommend | Agent | Stay within the remedies the application makes available. |
| Whether to issue a refund above $100 | Authorized reviewer | The refund tool requires approval before execution. |
| Whether to change the organization's mission | Authorized operator or review process | The agent may submit a proposal if the application provides that route. |

This is an illustrative delegation model, not a policy Kyno installs.
Put hard limits in tool permissions, approval mechanisms, and application
controls. Your orchestrator continues to own task execution.

## Which principles guide judgment?

Principles express how to judge choices and tradeoffs: “preserve customer
trust” or “make cancellation straightforward,” for example. They leave room
for different appropriate decisions in different situations.

A hard boundary such as “refunds above $100 require approval” can also appear
in explanatory direction, but its enforcement belongs to the surrounding
system. Putting that sentence in a constitution does not restrict a refund
tool. A principle cannot grant permission to cross an enforced boundary.

## How should agents handle conflicting principles?

Kyno preserves principle order and delivers their content. It does not
calculate which principle wins. The mission provides the overarching purpose
for judging tradeoffs; using it as a tie-breaker is guidance for the agent,
not an algorithm Core executes.

Define a conflict procedure in your integration. A useful starting procedure is:

1. Check the action against any applicable permissions and approval requirements.
2. Identify the relevant principles and the evidence available for the decision.
3. Use the mission and any authored precedence guidance to compare available
   choices. Principle descriptions can explain when a principle applies and
   what costs the organization accepts.
4. If the conflict remains unresolved or exceeds the delegated authority,
   follow the application's review or stop path. Do not invent an exception.

For example, “resolve requests quickly” and “explain options fully” can conflict.
Under “make cancellation straightforward,” an agent may give a brief explanation
of relevant options and the requested cancellation steps, rather than delay the
request with an exhaustive sales pitch. The application can evaluate factual
completeness and whether cancellation was obstructed.

If the procedure depends on descriptions or the declaration, supply full
direction. The default compact read includes the mission and principle titles.
With an open SDK connection, include the longer guidance:

```python
binder = connection.binder("customer-support", detail="full")
```

The application must also define what happens when a direction read fails.
See [binding status and failure policies](adapters.md#inspecting-binding-status).

## May agents propose constitutional changes?

Yes, if the application provides a proposal channel. An agent can identify a
recurring conflict or an unhelpful principle and submit a suggested change
through an application-owned issue, review queue, or draft pull request.

Keep proposal authority separate from write authority. Shipped adapters only
read direction. Kyno has no proposal endpoint or pending-proposal state.
A proposal does not change the constitution served to other agents.

Keep write credentials with an authorized operator or trusted deployment job.
HTTP read-only tokens enforce that distinction at the MCP endpoint; local,
stdio, and embedded setups depend on host-process access. See
[who should hold write access](operating.md#who-should-hold-write-access).

## How are bottom-up proposals evaluated, adopted, and versioned?

The review process belongs to your organization. A practical process using
the existing authoring workflow is:

1. Record the proposed edit, the constitution version it addresses, the
   observed problem, supporting examples, and expected consequences.
2. Have an authorized reviewer evaluate the edit against the mission and
   any applicable governance boundaries. Rehearse it against representative
   cases, including cases where the changed principle could lead to a worse
   decision.
3. If accepted, apply the reviewed content through the operator or deployment
   workflow, with a change note linking to the review.
4. Check the resulting version and observe subsequent work. A later successful
   pull can supply the accepted direction to an agent's next step.

Kyno appends an immutable version when the applied content changes; identical
content is a no-op. Rejected or pending proposals remain in the external review
system. Kyno's version history records the adopted content, not the deliberation
or evidence that review occurred. See [version-controlled review](best-practices.md#keep-the-constitution-in-version-control)
and [rehearsal before applying](best-practices.md#rehearse-before-you-apply).

## How is legitimate judgment distinguished from rationalization or drift?

Kyno does not make that distinction. Receiving the correct direction or citing
a principle does not establish that a decision was justified. A plausible
explanation alone is insufficient evidence.

Your application can capture the output or action with the exact supplied
constitution key, version, and direction, plus the relevant inputs and a
concise decision summary. Check observable behavior against the delegated
authority, the evidence, and independently defined evaluation criteria.
Use task-specific checks, independent review, or human assessment where the
decision warrants it. Compare repeated outcomes to identify possible drift.

When a delivery receipt is available, its record ID can link the application
record to the direction response. That receipt establishes delivery, not
compliance or the quality of judgment. The application decides whether to
continue, retry, restrict the action, or ask for human review. See
[application-owned verification](adapters.md#application-owned-verification).

These checks can reveal failures; they do not guarantee that every instance
of rationalization or drift will be detected.
