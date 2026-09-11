"""Run two support answers with a Kyno pull before each model call."""

import argparse
import json
import os
import sys
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from langgraph.graph import END, START, StateGraph

import kyno
from kyno.adapters.langgraph import KynoState, pull_before
from kyno.sdk import DeliveryStatus, DetailLevel, PullPolicy

SCENARIO = (
    "A customer paid $40 for express delivery. The package arrived two days late. "
    "They ask for the delivery fee back and an explanation. Tracking confirms the delay. "
    "You may draft a reply, propose a refund of up to $40, or propose escalation to a person. "
    "Do not execute any action or claim a refund has already been issued. "
    "Choose a response and explain the tradeoff using the supplied mission and principles."
)


class State(KynoState):
    run_id: str


def run_example(model, binder, *, constitution, model_name, wait_for_operator, emit):
    """Run one graph with two calls, waiting for the operator between them.
    Emit supplied-direction events before inference and response events only after success."""

    def answer(step_id):
        @pull_before(binder, constitution=constitution)
        def node(state):
            if (
                state["kyno_version"] == 0
                or state["kyno_delivery_status"] != DeliveryStatus.CURRENT
            ):
                raise ValueError(
                    "A current, written constitution is required before calling the model"
                )
            messages = [
                {"role": "system", "content": state["kyno_direction"]},
                {"role": "user", "content": SCENARIO},
            ]
            identity = {
                "run_id": state["run_id"],
                "step_id": step_id,
                "call_id": f"{state['run_id']}:{step_id}",
                "model": model_name,
            }
            emit(
                {
                    **identity,
                    "event": "direction_supplied",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "boundary": "before_model_call",
                    "constitution": state["kyno_constitution"],
                    "version": state["kyno_version"],
                    "status": state["kyno_delivery_status"],
                    "context": state["kyno_context"],
                    "direction": messages[0]["content"],
                    "scenario": SCENARIO,
                }
            )
            response = model.invoke(messages)
            emit(
                {
                    **identity,
                    "event": "model_output",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "response": response.model_dump(mode="json"),
                }
            )
            return {}

        return node

    def operator_pause(state):
        wait_for_operator()
        return {}

    graph = StateGraph(State)
    graph.add_node("first_answer", answer("first_answer"))
    graph.add_node("operator_pause", operator_pause)
    graph.add_node("second_answer", answer("second_answer"))
    graph.add_edge(START, "first_answer")
    graph.add_edge("first_answer", "operator_pause")
    graph.add_edge("operator_pause", "second_answer")
    graph.add_edge("second_answer", END)
    return graph.compile().invoke({"run_id": str(uuid.uuid4())})


def report(event, recording=None):
    """Print each boundary or response; optionally flush the full event to JSONL."""
    if recording is not None:
        recording.write(json.dumps(event, ensure_ascii=False) + "\n")
        recording.flush()
    if event["event"] == "direction_supplied":
        print(
            f"run={event['run_id']} step={event['step_id']} "
            f"constitution={event['constitution']} version={event['version']} "
            f"status={event['status']}",
            flush=True,
        )
    else:
        print(json.dumps(event["response"]["content"], ensure_ascii=False, indent=2), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Kyno HTTP URL.")
    parser.add_argument(
        "--token-env", default="KYNO_READ_TOKEN", help="Variable holding a read-only token."
    )
    parser.add_argument("--constitution", default="customer-support")
    parser.add_argument("--model", required=True, help="OpenAI model ID selected by the operator.")
    parser.add_argument(
        "--allow-model-calls", action="store_true", help="Consent to two billable model calls."
    )
    parser.add_argument(
        "--record", type=Path, help="New JSONL file for sensitive receipts and responses."
    )
    args = parser.parse_args(argv)
    if not args.allow_model_calls:
        parser.error("add --allow-model-calls to consent to real model usage")
    token = os.environ.get(args.token_env)
    if not token or not token.strip():
        parser.error(f"set {args.token_env} to a read-only Kyno token")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("set OPENAI_API_KEY in the agent terminal")
    if not args.model.strip():
        parser.error("--model must name a model")

    try:
        from langchain_openai import ChatOpenAI

        with ExitStack() as stack:
            recording = (
                stack.enter_context(args.record.open("x", encoding="utf-8"))
                if args.record
                else None
            )
            model = ChatOpenAI(model=args.model, max_retries=0, timeout=60)
            connection = stack.enter_context(kyno.connect(url=args.url, token=token))
            binder = connection.binder(
                context=DetailLevel.FULL, policy=PullPolicy(fail_closed=True)
            )

            def wait_for_operator():
                input(
                    "Apply the revised direction in the operator terminal, then press Enter here: "
                )

            run_example(
                model,
                binder,
                constitution=args.constitution,
                model_name=args.model,
                wait_for_operator=wait_for_operator,
                emit=lambda event: report(event, recording),
            )
    except ImportError:
        print(
            'Install the example dependencies: pip install "kyno[langgraph]" langchain-openai',
            file=sys.stderr,
        )
        return 1
    except FileExistsError:
        print(
            "Recording file already exists; choose a new path. Nothing was overwritten.",
            file=sys.stderr,
        )
        return 1
    except (Exception, KeyboardInterrupt):
        print(
            "Run stopped. A supplied-direction receipt does not imply a completed model call. "
            "Check Kyno connectivity, direction, model configuration, and recording permissions.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
