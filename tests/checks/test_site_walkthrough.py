"""The published replay keeps recorded inputs intact and remains readable without scripts."""

import html
import json
import re
import shutil
import subprocess

import pytest

from tests.paths import REPO_ROOT

WALKTHROUGH = REPO_ROOT / "site" / "demo"


def _run_script(scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the website script check")
    return subprocess.run(
        [
            node,
            str(REPO_ROOT / "tests" / "checks" / "walkthrough_navigation.cjs"),
            str(REPO_ROOT),
            scenario,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_given_the_recording_when_reading_the_page_then_all_call_inputs_and_outputs_are_preserved():
    recording = json.loads((WALKTHROUGH / "recording.json").read_text())
    page = (WALKTHROUGH / "index.html").read_text()

    assert [call["version"] for call in recording["calls"]] == [1, 1, 2, 2]
    assert [call["step_id"] for call in recording["calls"]] == [
        "plan",
        "first_answer",
        "replan",
        "second_answer",
    ]
    for call in recording["calls"]:
        assert html.escape(call["output"]) in page
        for message in call["messages"]:
            assert html.escape(message["content"]) in page


def test_given_no_javascript_when_reading_the_page_then_all_eight_events_are_visible():
    page = (WALKTHROUGH / "index.html").read_text()

    screens = re.findall(r"<section\b[^>]*data-walkthrough-screen[^>]*>", page)
    assert len(screens) == 8
    assert all("hidden" not in screen for screen in screens)
    assert [re.search(r'data-walkthrough-screen="(\d+)"', screen)[1] for screen in screens] == [
        str(index) for index in range(8)
    ]


@pytest.mark.parametrize("scenario", ["sequence", "previous", "picker", "step-button", "restart"])
def test_given_a_walkthrough_when_using_step_controls_then_one_current_event_is_visible(scenario):
    result = _run_script(scenario)

    assert result.returncode == 0, result.stderr


def test_given_an_invalid_step_when_the_picker_changes_then_the_current_event_is_retained():
    result = _run_script("invalid-step")

    assert result.returncode == 0, result.stderr


def test_given_a_walkthrough_when_the_script_initializes_then_controls_enable_at_the_first_event():
    result = _run_script("initialization")

    assert result.returncode == 0, result.stderr


def test_given_no_walkthrough_when_the_script_initializes_then_it_returns_without_error():
    result = _run_script("missing-page")

    assert result.returncode == 0, result.stderr
