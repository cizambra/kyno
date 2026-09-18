# Customer support with CrewAI

This example uses real CrewAI agents, tasks, and crews for the same complaint
and direction files as the [LangGraph walkthrough](README.md). The application
keeps a plan and completed draft, pauses for the operator, then checks whether
new direction requires revising the remaining plan. Kyno supplies direction;
the application owns the pause, version comparison, and decision to replan.

The cycle is:

1. Pull direction through `CrewAiKyno` before a CrewAI task creates the plan.
2. Pull again before a second task drafts a reply using that plan.
3. Pause while the operator applies the revised YAML in another terminal.
4. Read direction through the SDK binder and compare its version with the
   version used for planning.
5. If newer, run a task that revises only the remaining plan, with fresh
   direction, the previous plan, and the completed draft.
6. Run the final task with fresh direction, the current plan, and the draft.

Every stage is a one-task crew with no tools, delegation, memory, or agent
retries. The draft remains in application state and is never run again.
With changed direction there are four model calls; unchanged direction uses
three. Nothing sends a message or issues a refund.

## Run it

From the repository checkout, install the CrewAI extra:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[crewai]" "python-dotenv>=1.2"
```

Follow steps 1 and 2 of the [shared walkthrough](README.md#1-server-terminal)
to create an isolated server, separate read/write tokens, and apply
`direction-v1.yaml`. Keep the write token only in the operator terminal.
In the agent terminal, from the repository root:

```bash
unset KYNO_WRITE_TOKEN
read -rsp 'Agent read token: ' KYNO_READ_TOKEN; echo
export KYNO_READ_TOKEN
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
export OPENAI_API_KEY
read -rp 'OpenAI model ID: ' MODEL
export CREWAI_TELEMETRY_DISABLED=true CREWAI_TRACING_ENABLED=false
python examples/customer_support/crewai_run.py --url http://127.0.0.1:2256 --model "$MODEL" --allow-model-calls
```

The operator chooses a model available in their account. Explicit
`--allow-model-calls` consent is required; calls can incur charges and send
the sample direction and complaint to OpenAI. The example sets
`PYTHON_DOTENV_DISABLED=1` before importing CrewAI because CrewAI otherwise
loads `.env` files implicitly. This requires the python-dotenv version above.
CrewAI tracing is disabled on each crew; the environment variables above
also disable CrewAI telemetry. Provider retention settings still apply.

After the plan and draft print, apply `direction-v2.yaml` in the operator
terminal using [step 4](README.md#4-apply-the-revision-and-continue), then press
Enter in the agent terminal. To exercise the unchanged path, press Enter
without applying an update. The version numbers printed are the actual
constitution versions, which may differ from 1 and 2 on a reused server.

## Where to read the code

`crewai_run.py` owns the cycle and state. `run_stage()` constructs a real
CrewAI `Agent`, `Task`, and `Crew`. Its before-call hook invokes
`CrewAiKyno.before_llm_call()` on CrewAI's real context and records the
direction injected into the model messages. `support.py` holds the scenario,
task prompts, command validation, and output formatting shared with LangGraph;
it imports neither framework.

The example checks direction at one explicit review boundary. Pulls are
separate reads, not a locked snapshot: an operator can update direction
between the review and the next call. Every call still gets fresh direction.
The plan's version belongs to the application and is captured from the
planning call's binding, without an extra planning read.

CrewAI may swallow ordinary hook exceptions. This example therefore records
the error and explicitly returns `False` from its before-call hook to block
inference, then raises the original error to stop the cycle. Failed output
recording stops before the next stage. Hooks are removed on success or
failure and filter by the example's agent. The example is intended for one
sequential run in its own process.

## Optional recording

No file is written unless you add `--record /private/new-recording.jsonl`.
Use `umask 077`; existing files are refused before model construction.
Each call creates a `direction_supplied` event and, after the call returns,
a separate `model_output` event with matching run, step, call, and model IDs.

The supplied event includes direction, constitution, version, binding status,
detail level, scenario, task, and the actual CrewAI message list after
injection. The output event preserves the response string exposed by CrewAI's
after-call hook, before CrewAI parses the final answer. Provider-specific
response metadata is not exposed by that hook. Application state uses the
parsed task output. A receipt alone does not prove that a call completed.

Current, written direction is required at every boundary. Empty direction,
cached fallback, failed pulls, and failed recording stop this evidence
example. These strict rules belong to the example, not Kyno's default policy.
Recordings contain prompts and responses; review them before sharing.

## Verify without a model provider

```bash
pip install -e ".[dev,crewai]" "python-dotenv>=1.2"
CREWAI_TELEMETRY_DISABLED=true CREWAI_TRACING_ENABLED=false python -m pytest -q tests/surface/e2e/test_crewai_support_example.py tests/surface/integration/test_crewai_support_recording.py
```

Tests use real CrewAI execution and authenticated Kyno HTTP with a deterministic
`BaseLLM` substitute. They verify direction delivery, plan propagation,
completed-draft retention, unchanged routing, failure stops, consent, and
record correlation. They make no paid model calls and do not measure whether
a model follows the direction or writes a better response.
