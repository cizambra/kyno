# Direction changes during a customer-support run

Run one LangGraph workflow with two model calls. After the first answer,
the graph waits while you change direction in Kyno. The second call pulls
again without restarting the workflow.

Both calls receive the same customer complaint and the same permitted
actions. Only the supplied direction changes. The model may choose a
different answer; this example does not assert that it follows the principles
or that its second answer is better. It drafts responses and executes no
refunds, messages, or other actions.

```mermaid
sequenceDiagram
    participant Operator
    participant Kyno
    participant Graph
    participant Model
    Operator->>Kyno: Apply direction v1
    Graph->>Kyno: Pull before first answer
    Kyno-->>Graph: v1 and delivery status
    Graph->>Graph: Record supplied direction
    Graph->>Model: Direction and customer complaint
    Model-->>Graph: First answer
    Graph->>Graph: Wait for operator input
    Operator->>Kyno: Apply direction v2
    Operator->>Graph: Press Enter to continue
    Graph->>Kyno: Pull before second answer
    Kyno-->>Graph: v2 and change context
    Graph->>Model: New direction and the same complaint
    Model-->>Graph: Second answer
```

## Install

The example files live in the repository, not in the installed package.
From a checkout of this revision, create a virtual environment and install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[langgraph]" langchain-openai
```

The script uses [LangChain's OpenAI integration](https://docs.langchain.com/oss/python/integrations/chat/openai).
Choose an available model in your account; there is no default model. Real
calls require `--allow-model-calls`, can incur charges, and send the sample
direction and complaint to the provider. No `.env` file is loaded.

## 1. Server terminal

Use an isolated workspace for this example. Activate the same environment
in each terminal. These commands use Bash syntax.

```bash
kyno new /tmp/kyno-support-instance
cd /tmp/kyno-support-instance
kyno db init
kyno token add support-agent --scope read
kyno token add support-operator --scope write
kyno serve --transport http
```

Keep the two printed token values separate. Give the read token to the agent
terminal and the write token only to the operator terminal. Do not paste
either into direction files or model messages. Use your server's actual URL
below if it differs from `http://127.0.0.1:2256`.

## 2. Operator terminal

From the repository root:

```bash
read -rsp 'Operator write token: ' KYNO_WRITE_TOKEN; echo
export KYNO_WRITE_TOKEN
kyno remote add --profile support-operator --url http://127.0.0.1:2256 --token-env KYNO_WRITE_TOKEN
kyno apply examples/customer_support/direction-v1.yaml --remote --profile support-operator --note "Initial support direction"
```

Review and confirm the apply. Keep this terminal open for step 4. Use a fresh
constitution for a literal v1 → v2 run; rerunning against existing history
can produce different version numbers. The script reports the actual ones.

## 3. Agent terminal

From the repository root, with no operator credential in this environment:

```bash
unset KYNO_WRITE_TOKEN
read -rsp 'Agent read token: ' KYNO_READ_TOKEN; echo
export KYNO_READ_TOKEN
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
export OPENAI_API_KEY
read -rp 'OpenAI model ID: ' MODEL
python examples/customer_support/run.py --url http://127.0.0.1:2256 --model "$MODEL" --allow-model-calls
```

The first step prints the run ID, step ID, constitution, version, delivery
status, and model answer. It then waits for your input. This is an ordinary
input pause inside the same graph invocation, not checkpoint persistence or
a Kyno orchestration feature. Do not press Enter until the next apply succeeds.

## 4. Apply the revision and continue

In the **operator terminal**:

```bash
kyno apply examples/customer_support/direction-v2.yaml --remote --profile support-operator --note "Explain remedies and preserve customer choice"
```

Return to the agent terminal and press Enter. The second step pulls the
latest direction and prints another answer. If no change was applied, both
receipts name the same version. Kyno does not invent a change for the example.

## Optional recording

No JSONL file is written by default. To retain a run, add
`--record /path/to/new-recording.jsonl` to the agent command. Use `umask 077`
before running and choose a private location. Existing files are refused.
Disable any separately configured LangSmith tracing if you do not intend to
send prompts or responses there. Your model provider's retention settings
still apply.

Each call produces two separate events:

- `direction_supplied`: run/call/step IDs, model ID, constitution, version,
  delivery status, context level, exact rendered direction, fixed scenario,
  and the time immediately before the model call.
- `model_output`: the same call identity, capture time, and the full serialized
  LangChain response message, including its content and response metadata.

The response is not rewritten or replaced with an expected answer. A receipt
without an output event means no completed response was recorded; the model
call or recording may have failed. The script stops on errors and does not
retry model calls. A failed pull or unwritten constitution stops before
inference rather than using cached or empty direction. That strict choice
belongs to this evidence example, not the adapter's default failure policy.

Recordings can contain sensitive direction and model output. Review them
before sharing. This is not the public replay demo: any later replay must
be labeled as recorded and use the matching scenario, direction, and responses.

## Test without a model provider

```bash
pip install -e ".[dev,langgraph]"
python -m pytest -q tests/surface/e2e/test_customer_support_example.py tests/surface/integration/test_customer_support_recording.py
```

These tests use a deterministic model substitute, real LangGraph execution,
and an authenticated Kyno HTTP server. They test direction delivery and
record correlation, not model obedience. No provider API key is required.
