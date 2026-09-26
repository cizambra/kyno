"""Direction responses identify the constitution Core actually selected."""

import json

import pytest

from kyno.wire import RESOURCE_URI


@pytest.mark.parametrize("key, expected", [(None, "default"), (" eu-west ", "eu-west")])
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 0}),
        ("changes_since", {"last_seen_version": 0}),
        ("publication", {}),
    ],
)
def test_given_empty_direction_when_core_operation_runs_then_resolved_key_returns(
    cp, key, expected, operation, arguments
):
    result = getattr(cp, operation)(constitution_key=key, **arguments)

    assert result.constitution_key == expected


@pytest.mark.parametrize("key, expected", [(None, "default"), (" eu-west ", "eu-west")])
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 1}),
        ("changes_since", {"last_seen_version": 0}),
        ("changes_since", {"last_seen_version": 1}),
        ("publish", {}),
        ("publication", {}),
        ("unpublish", {}),
    ],
)
def test_given_written_direction_when_core_operation_runs_then_selected_key_returns(
    cp, key, expected, operation, arguments
):
    written = cp.apply_direction(mission="Help", change_note="Initial", constitution_key=key)
    assert written.constitution_key == expected

    result = getattr(cp, operation)(constitution_key=key, **arguments)

    assert result.constitution_key == expected


@pytest.mark.parametrize("initialized", [False, True])
@pytest.mark.parametrize("key, expected", [(None, "default"), (" eu-west ", "eu-west")])
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("get_constitution", {}),
        ("get_constitution", {"version": 0}),
        ("get_changes_since", {"last_seen_version": 0}),
        ("get_mission", {}),
        ("get_declaration", {}),
        ("get_principles", {}),
    ],
)
def test_given_selected_key_when_call_tool_then_response_identifies_selected_key(
    mcp_runner, initialized, key, expected, operation, arguments
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help", change_note="init", constitution_key=key)
    reply = runner.call(
        lambda session: session.call_tool(operation, {**arguments, "constitution_key": key})
    )
    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected


@pytest.mark.parametrize("initialized", [False, True])
def test_given_default_direction_when_read_resource_then_resolved_key_returns(
    mcp_runner,
    initialized,
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help", change_note="init")
    reply = runner.call(lambda session: session.read_resource(RESOURCE_URI))
    assert json.loads(reply.contents[0].text)["constitution_key"] == "default"


@pytest.mark.parametrize("key, expected", [(None, "default"), (" eu-west ", "eu-west")])
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("get_constitution", {"version": 1}),
        ("get_principle", {"title": "Be clear"}),
        ("export_versions", {}),
    ],
)
def test_given_history_when_call_tool_reads_direction_then_results_identify_selected_key(
    mcp_runner, key, expected, operation, arguments
):
    runner, plane = mcp_runner
    plane.apply_direction(
        mission="First", principles=("Be clear",), change_note="init", constitution_key=key
    )
    plane.apply_direction(mission="Second", change_note="next", constitution_key=key)
    reply = runner.call(
        lambda session: session.call_tool(operation, {**arguments, "constitution_key": key})
    )
    assert not reply.isError
    result = json.loads(reply.content[0].text)
    rows = result if operation == "export_versions" else [result]
    assert all(row["constitution_key"] == expected for row in rows)
    if operation == "get_constitution":
        assert result["version"] == 1
        assert result["mission"] == "First"
    elif operation == "export_versions":
        assert [row["version"] for row in rows] == [1, 2]


@pytest.mark.parametrize("key, expected", [(None, "default"), (" eu-west ", "eu-west")])
def test_given_write_selection_when_call_tool_applies_direction_then_result_identifies_key(
    mcp_runner, key, expected
):
    runner, _ = mcp_runner
    reply = runner.call(
        lambda session: session.call_tool(
            "apply_direction", {"constitution_key": key, "mission": "Help", "change_note": "init"}
        )
    )
    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected
