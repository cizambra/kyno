"""Plan and draft support responses with Kyno direction before each model call."""

import json
import sys
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime

from langgraph.graph import END, START, StateGraph
from support import SCENARIO, parse_arguments, report, task_prompt, wait_for_operator

import kyno
from kyno.adapters.langgraph import KynoState, pull_before
from kyno.sdk import DeliveryStatus, DetailLevel, PullPolicy


class State(KynoState):
    run_id: str
    plan: str
    plan_version: int
    first_answer: str
    second_answer: str
    replan_needed: bool
    plan_change_summary: str


def require_current_direction(state):
    """Refuse empty or fallback direction before planning or inference."""
    if state["kyno_version"] == 0 or state["kyno_delivery_status"] != DeliveryStatus.CURRENT:
        raise ValueError("A current, written constitution is required before calling the model")


def prepare_messages(state, step_id):
    """Build model input from current direction and the application's plan and draft."""
    require_current_direction(state)
    return [
        {"role": "system", "content": state["kyno_direction"]},
        {"role": "user", "content": task_prompt(state, step_id)},
    ]


def supplied_direction_event(state, identity, messages):
    """Describe the direction and scenario in the prepared model input."""
    return {
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
        "task": messages[1]["content"],
    }


def model_node(model, binder, *, model_name, step_id, emit):
    """Create a model node with a fresh pull and separate supplied/output events."""

    @pull_before(binder)
    def node(state):
        messages = prepare_messages(state, step_id)
        identity = {
            "run_id": state["run_id"],
            "step_id": step_id,
            "call_id": f"{state['run_id']}:{step_id}",
            "model": model_name,
        }
        emit(supplied_direction_event(state, identity, messages))
        response = model.invoke(messages)
        emit(
            {
                **identity,
                "event": "model_output",
                "captured_at": datetime.now(UTC).isoformat(),
                "response": response.model_dump(mode="json"),
            }
        )
        content = response.content
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if step_id in ("plan", "replan"):
            return {"plan": text, "plan_version": state["kyno_version"]}
        return {step_id: text}

    return node


def run_example(model, binder, *, model_name, wait_for_operator, emit):
    """Plan, draft, check for changes, optionally replan, and finalize in one graph."""

    def operator_pause(state):
        wait_for_operator()
        return {}

    @pull_before(binder)
    def check_direction(state):
        require_current_direction(state)
        return {
            "replan_needed": state["kyno_version"] > state["plan_version"],
            "plan_change_summary": "\n".join(state["kyno_change_notes"] + state["kyno_delta"]),
        }

    graph = StateGraph(State)
    for step_id in ("plan", "first_answer", "replan", "second_answer"):
        graph.add_node(
            step_id,
            model_node(
                model,
                binder,
                model_name=model_name,
                step_id=step_id,
                emit=emit,
            ),
        )
    graph.add_node("operator_pause", operator_pause)
    graph.add_node("check_direction", check_direction)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "first_answer")
    graph.add_edge("first_answer", "operator_pause")
    graph.add_edge("operator_pause", "check_direction")
    graph.add_conditional_edges(
        "check_direction",
        lambda state: "replan" if state["replan_needed"] else "second_answer",
        {"replan": "replan", "second_answer": "second_answer"},
    )
    graph.add_edge("replan", "second_answer")
    graph.add_edge("second_answer", END)
    return graph.compile().invoke({"run_id": str(uuid.uuid4())})


def run_live(args, token):
    """Open the selected resources, run the example, and close them on success or failure."""
    from langchain_openai import ChatOpenAI

    with ExitStack() as stack:
        recording = (
            stack.enter_context(args.record.open("x", encoding="utf-8")) if args.record else None
        )
        model = ChatOpenAI(model=args.model, max_retries=0, timeout=60)
        connection = stack.enter_context(kyno.connect(url=args.url, token=token))
        binder = connection.binder(
            args.constitution, context=DetailLevel.FULL, policy=PullPolicy(fail_closed=True)
        )
        run_example(
            model,
            binder,
            model_name=args.model,
            wait_for_operator=wait_for_operator,
            emit=lambda event: report(event, recording),
        )


def main(argv=None):
    args, token = parse_arguments(argv)
    try:
        run_live(args, token)
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
