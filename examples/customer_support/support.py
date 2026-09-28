"""Framework-neutral scenario, prompts, and command options for support examples."""

import argparse
import json
import os
from pathlib import Path

SCENARIO = (
    "A customer paid $40 for express delivery. The package arrived two days late. "
    "They ask for the delivery fee back and an explanation. Tracking confirms the delay. "
    "You may draft a reply, propose a refund of up to $40, or propose escalation to a person. "
    "Do not execute any action or claim a refund has already been issued. "
    "Choose a response and explain the tradeoff using the supplied mission and principles."
)


def task_prompt(state, step_id):
    """Supply the scenario, existing work, and the application's task for this call."""
    if step_id == "plan":
        return SCENARIO + (
            "\n\nCreate a short plan with two stages: draft a response, then finalize it. "
            "Use the supplied direction to explain the tradeoffs. Do not draft the response yet."
        )
    prompt = f"{SCENARIO}\n\nCurrent plan:\n{state['plan']}"
    if step_id == "first_answer":
        return prompt + "\n\nCarry out the drafting stage. Produce a draft, not a sent message."
    prompt += f"\n\nCompleted draft (not sent):\n{state['first_answer']}"
    if step_id == "replan":
        prompt += f"\n\nChanges observed:\n{state['plan_change_summary']}"
        return prompt + (
            "\n\nDirection changed. Revise only the remaining finalization plan. "
            "Use the completed draft as existing work; do not redo the drafting stage."
        )
    return prompt + "\n\nCarry out the remaining plan and produce the final proposed response."


def report(event, recording=None):
    """Print each boundary or response; optionally flush the full event to JSONL."""
    if recording is not None:
        recording.write(json.dumps(event, ensure_ascii=False) + "\n")
        recording.flush()
    if event["event"] == "direction_supplied":
        print(
            f"run={event['run_id']} step={event['step_id']} "
            f"constitution_key={event['constitution_key']} version={event['version']} "
            f"status={event['status']}",
            flush=True,
        )
    else:
        print(json.dumps(event["response"]["content"], ensure_ascii=False, indent=2), flush=True)


def parse_arguments(argv):
    """Validate command options and required credentials before opening external resources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Kyno HTTP URL.")
    parser.add_argument(
        "--token-env", default="KYNO_READ_TOKEN", help="Variable holding a read-only token."
    )
    parser.add_argument("--constitution", default="customer-support")
    parser.add_argument("--model", required=True, help="OpenAI model ID selected by the operator.")
    parser.add_argument(
        "--allow-model-calls",
        action="store_true",
        help="Consent to three or four billable model calls.",
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
    return args, token


def wait_for_operator():
    input("Apply the revised direction in the operator terminal, then press Enter here: ")
