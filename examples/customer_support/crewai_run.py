"""Plan and draft support responses using CrewAI and current Kyno direction."""

import os
import sys
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime

from support import SCENARIO, parse_arguments, report, task_prompt, wait_for_operator

import kyno
from kyno.adapters.crewai import CrewAiKyno
from kyno.sdk import BindingStatus, DetailLevel, PullPolicy

os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def require_current_direction(binding):
    """Reject empty or fallback direction before inference or reviewing a plan."""
    if binding.direction.version == 0 or binding.status != BindingStatus.PULLED:
        raise ValueError("A current, written constitution is required before calling the model")


class StageBoundary:
    """Apply the example's delivery and recording policy to one CrewAI stage."""

    def __init__(self, binder, agent, prompt, identity, emit):
        self.agent = agent
        self.prompt = prompt
        self.identity = identity
        self.emit = emit
        self.bindings = []
        self.errors = []
        self.adapter = CrewAiKyno(binder, on_direction=self.bindings.append)

    def before_call(self, context):
        if context.agent is not self.agent:
            return None
        try:
            if self.bindings:
                raise RuntimeError("The stage exhausted its one-call model budget")
            self.adapter.before_llm_call(context)
            binding = self.bindings[-1]
            require_current_direction(binding)
            direction = binding.direction
            self.emit(
                {
                    **self.identity,
                    "event": "direction_supplied",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "boundary": "before_model_call",
                    "constitution": direction.constitution,
                    "version": direction.version,
                    "status": binding.status,
                    "detail": direction.detail,
                    "direction": direction.render(),
                    "scenario": SCENARIO,
                    "task": self.prompt,
                    "messages": [message.copy() for message in context.messages],
                }
            )
        except Exception as error:
            self.errors.append(error)
            return False
        return None

    def after_call(self, context):
        if context.agent is not self.agent:
            return None
        try:
            self.emit(
                {
                    **self.identity,
                    "event": "model_output",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "response": {"content": context.response},
                }
            )
        except Exception as error:
            self.errors.append(error)
        return None


def run_stage(model, binder, state, step_id, *, model_name, emit):
    """Run one CrewAI task with a fresh adapter pull and a one-call budget."""
    from crewai import Agent, Crew, Task
    from crewai.hooks import (
        register_after_llm_call_hook,
        register_before_llm_call_hook,
        unregister_after_llm_call_hook,
        unregister_before_llm_call_hook,
    )

    prompt = task_prompt(state, step_id)
    identity = {
        "run_id": state["run_id"],
        "step_id": step_id,
        "call_id": f"{state['run_id']}:{step_id}",
        "model": model_name,
    }
    agent = Agent(
        role="Support response writer",
        goal="Propose a response to the supplied complaint using the supplied direction",
        backstory="You draft proposals only; you never send messages or execute refunds.",
        llm=model,
        tools=[],
        allow_delegation=False,
        max_retry_limit=0,
        max_iter=1,
        verbose=False,
    )

    boundary = StageBoundary(binder, agent, prompt, identity, emit)

    task = Task(
        description=prompt, expected_output="The requested plan or proposed response", agent=agent
    )
    crew = Crew(agents=[agent], tasks=[task], memory=False, verbose=False, tracing=False)
    register_before_llm_call_hook(boundary.before_call)
    register_after_llm_call_hook(boundary.after_call)
    try:
        try:
            output = crew.kickoff()
        except Exception:
            if boundary.errors:
                raise boundary.errors[0] from None
            raise
        if boundary.errors:
            raise boundary.errors[0]
    finally:
        unregister_before_llm_call_hook(boundary.before_call)
        unregister_after_llm_call_hook(boundary.after_call)
    if step_id in ("plan", "replan"):
        state.update(plan=output.raw, plan_version=boundary.bindings[-1].direction.version)
    else:
        state[step_id] = output.raw


def run_example(model, binder, *, model_name, wait_for_operator, emit):
    """Plan, draft, pause, assess direction, optionally replan, then finalize."""
    state = {"run_id": str(uuid.uuid4())}
    for step_id in ("plan", "first_answer"):
        run_stage(model, binder, state, step_id, model_name=model_name, emit=emit)
    wait_for_operator()
    binding = binder.bind_with_status()
    require_current_direction(binding)
    direction = binding.direction
    state["replan_needed"] = direction.version > state["plan_version"]
    state["plan_change_summary"] = "\n".join(direction.change_notes + direction.delta)
    if state["replan_needed"]:
        run_stage(model, binder, state, "replan", model_name=model_name, emit=emit)
    run_stage(model, binder, state, "second_answer", model_name=model_name, emit=emit)
    return state


def run_live(args, token):
    """Open opt-in recording and the read connection, then run the selected model."""
    from crewai import LLM

    with ExitStack() as stack:
        recording = (
            stack.enter_context(args.record.open("x", encoding="utf-8")) if args.record else None
        )
        model = LLM(model=args.model, max_retries=0, timeout=60)
        connection = stack.enter_context(kyno.connect(url=args.url, token=token))
        run_example(
            model,
            connection.binder(
                args.constitution, detail=DetailLevel.FULL, policy=PullPolicy(fail_closed=True)
            ),
            model_name=args.model,
            wait_for_operator=wait_for_operator,
            emit=lambda event: report(event, recording),
        )


def main(argv=None):
    args, token = parse_arguments(argv)
    try:
        run_live(args, token)
    except ImportError:
        print('Install the example dependencies: pip install "kyno[crewai]"', file=sys.stderr)
        return 1
    except FileExistsError:
        print(
            "Recording file already exists; choose a new path. Nothing was overwritten.",
            file=sys.stderr,
        )
        return 1
    except (Exception, KeyboardInterrupt):
        print(
            "Run stopped. A supplied-direction receipt does not imply a completed model call.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
