"""The planning example pulls direction over HTTP before planning and checking for changes."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

EXAMPLE = Path(__file__).resolve().parents[3] / "examples/planning/run.py"


def run_script(url, token):
    return subprocess.run(
        [sys.executable, str(EXAMPLE), "--url", url],
        input="\n",
        capture_output=True,
        text=True,
        env={**os.environ, "KYNO_READ_TOKEN": token},
        timeout=15,
    )


@pytest.mark.e2e
@pytest.mark.parametrize("update", [False, True], ids=["unchanged", "revised"])
def test_given_operator_direction_when_planning_script_resumes_then_only_changes_rebuild_the_plan(
    live_server, update, monkeypatch
):
    control_plane, url, token = live_server
    initial = yaml.safe_load(EXAMPLE.with_name("direction-v1.yaml").read_text())
    revised = yaml.safe_load(EXAMPLE.with_name("direction-v2.yaml").read_text())
    control_plane.set_direction(**initial, change_note="initial")
    reads = []
    original_read = control_plane.changes_since

    def read(*args, **kwargs):
        reads.append(args)
        if update and len(reads) == 2:
            control_plane.set_direction(**revised, change_note="priority changed")
        return original_read(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", read)
    result = run_script(url, token)
    transcript = result.stdout
    assert result.returncode == 0, result.stderr
    assert "Plan from planning-support v1" in transcript
    assert "Simulated completion: Check the delivery facts" in transcript
    assert ("Application rebuilds unfinished work" in transcript) is update
    assert ("Direction unchanged; application keeps its plan" in transcript) is not update
    assert ("Plan from planning-support v2" in transcript) is update
    assert "Remaining: Explain the next step" in transcript
    assert transcript.count("Simulated completion:") == 1
    assert "Remaining: Check the delivery facts" not in transcript
    assert [arguments[0] for arguments in reads] == ([0, 1, 2] if update else [0, 1])
    if update:
        assert "Remaining: Review urgent complaints first" in transcript
        assert "Remaining: Review complaints in arrival order" not in transcript


@pytest.mark.e2e
@pytest.mark.parametrize("written", [False, True], ids=["unwritten", "no-principles"])
def test_given_no_review_tasks_when_planning_script_starts_then_it_exits_without_a_plan(
    live_server, written
):
    control_plane, url, token = live_server
    if written:
        control_plane.set_direction(
            mission="Review complaints", constitution="planning-support", change_note="initial"
        )
    result = run_script(url, token)
    assert result.returncode == 1
    expected = "needs at least one principle" if written else "Apply direction before planning"
    assert expected in result.stderr
    assert "Simulated completion:" not in result.stdout


@pytest.mark.e2e
@pytest.mark.parametrize("failed_read", [1, 2, 3], ids=["initial", "check", "replan"])
def test_given_failed_pull_when_planning_script_reads_direction_then_it_stops_without_a_new_plan(
    live_server, monkeypatch, failed_read
):
    control_plane, url, token = live_server
    initial = yaml.safe_load(EXAMPLE.with_name("direction-v1.yaml").read_text())
    revised = yaml.safe_load(EXAMPLE.with_name("direction-v2.yaml").read_text())
    control_plane.set_direction(**initial, change_note="initial")
    original_read = control_plane.changes_since
    reads = []

    def read(*args, **kwargs):
        reads.append(args)
        if len(reads) == failed_read:
            raise OSError("direction unavailable")
        if len(reads) == 2:
            control_plane.set_direction(**revised, change_note="priority changed")
        return original_read(*args, **kwargs)

    monkeypatch.setattr(control_plane, "changes_since", read)
    result = run_script(url, token)

    assert result.returncode == 1
    assert "Planning stopped:" in result.stderr
    assert "cannot reach kyno for 'planning-support'" in result.stderr
    assert "Remaining:" not in result.stdout
    assert "Direction unchanged" not in result.stdout
    assert len(reads) == failed_read
