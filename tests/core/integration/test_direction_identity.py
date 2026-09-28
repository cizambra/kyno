"""Direction responses identify the constitution Core actually selected."""

import json

import pytest

from kyno.service import ControlPlane
from kyno.wire import RESOURCE_URI


@pytest.mark.parametrize(
    "selector, expected",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 0}),
        pytest.param("changes_since", {"last_seen_version": 0}, id="changes_since-version-zero"),
        ("publication", {}),
    ],
)
def test_given_empty_direction_when_core_operation_runs_then_resolved_key_returns(
    cp, selector, expected, operation, arguments
):
    result = getattr(cp, operation)(**selector, **arguments)

    assert result.constitution_key == expected


@pytest.mark.parametrize(
    "selector, expected",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
@pytest.mark.parametrize(
    "operation, arguments",
    [
        ("current", {}),
        ("get_constitution", {"version": 1}),
        pytest.param("changes_since", {"last_seen_version": 0}, id="changes_since-version-zero"),
        pytest.param("changes_since", {"last_seen_version": 1}, id="changes_since-current-version"),
        ("publish", {}),
        ("publication", {}),
        ("unpublish", {}),
    ],
)
def test_given_written_direction_when_core_operation_runs_then_selected_key_returns(
    cp, selector, expected, operation, arguments
):
    cp.apply_direction(mission="Help", change_note="Initial", **selector)
    if operation == "unpublish":
        cp.publish(**selector)

    result = getattr(cp, operation)(**selector, **arguments)

    assert result.constitution_key == expected


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
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
    mcp_runner, initialized, selector, expected, operation, arguments
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help", change_note="init", **selector)

    reply = runner.call(lambda session: session.call_tool(operation, {**arguments, **selector}))

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
def test_given_default_direction_when_read_resource_then_resolved_key_returns(
    mcp_runner,
    initialized,
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help", change_note="init")

    reply = runner.call(lambda session: session.read_resource(RESOURCE_URI))
    assert json.loads(reply.contents[0].text)["constitution_key"] == "default"


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_two_versions_when_call_tool_get_constitution_then_version_one_identifies_key(
    mcp_runner, selector, expected_key
):
    runner, plane = mcp_runner
    plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)
    plane.apply_direction(
        mission="Resolve customer issues", change_note="Refine mission", **selector
    )

    reply = runner.call(
        lambda session: session.call_tool("get_constitution", {**selector, "version": 1})
    )

    assert not reply.isError
    version = json.loads(reply.content[0].text)
    assert version["constitution_key"] == expected_key
    assert version["version"] == 1
    assert version["mission"] == "Help customers"


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_stored_principle_when_call_tool_get_principle_then_response_identifies_key(
    mcp_runner, selector, expected_key
):
    runner, plane = mcp_runner
    plane.apply_direction(
        mission="Help customers",
        principles=("Be clear",),
        change_note="Initial direction",
        **selector,
    )

    reply = runner.call(
        lambda session: session.call_tool("get_principle", {**selector, "title": "Be clear"})
    )

    assert not reply.isError
    principle = json.loads(reply.content[0].text)
    assert principle["constitution_key"] == expected_key
    assert principle["title"] == "Be clear"


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_two_versions_when_call_tool_export_versions_then_each_version_identifies_key(
    mcp_runner, selector, expected_key
):
    runner, plane = mcp_runner
    plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)
    plane.apply_direction(
        mission="Resolve customer issues", change_note="Refine mission", **selector
    )

    reply = runner.call(lambda session: session.call_tool("export_versions", selector))

    assert not reply.isError
    versions = json.loads(reply.content[0].text)
    assert [version["constitution_key"] for version in versions] == [expected_key, expected_key]
    assert [version["version"] for version in versions] == [1, 2]


@pytest.mark.parametrize(
    "selector, expected",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_write_selection_when_call_tool_applies_direction_then_result_identifies_key(
    mcp_runner, selector, expected
):
    runner, _ = mcp_runner

    reply = runner.call(
        lambda session: session.call_tool(
            "apply_direction", {**selector, "mission": "Help", "change_note": "init"}
        )
    )

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected


@pytest.mark.parametrize("key", ["default", "support"])
@pytest.mark.parametrize("operation", ["head", "get", "versions_after", "export_versions"])
def test_given_two_histories_when_store_read_runs_then_each_result_identifies_selected_key(
    store, key, operation
):
    cp = ControlPlane(store)
    cp.apply_direction(mission="Default mission", change_note="init")
    cp.apply_direction(mission="Support mission", change_note="init", constitution_key="support")

    if operation == "get":
        results = [store.get(key, 1)]
    elif operation == "versions_after":
        results = store.versions_after(key, 0)
    elif operation == "export_versions":
        results = store.export_versions(key)
    else:
        results = [store.head(key)]

    assert len(results) == 1
    result = results[0]
    returned_key = (
        result["constitution_key"] if operation == "export_versions" else result.constitution_key
    )
    assert returned_key == key


@pytest.mark.parametrize("detail", ["compact", "full"])
def test_given_named_direction_when_version_to_dict_runs_then_selected_key_is_serialized(
    cp, detail
):
    version = cp.apply_direction(
        mission="Help customers", change_note="init", constitution_key="support"
    )

    payload = version.to_dict(detail)

    assert payload["constitution_key"] == "support"


@pytest.mark.parametrize("detail", ["compact", "full"])
@pytest.mark.parametrize("written", [False, True], ids=["empty", "written"])
def test_given_named_direction_when_changes_to_dict_runs_then_selected_key_is_serialized(
    cp, detail, written
):
    if written:
        cp.apply_direction(mission="Help customers", change_note="init", constitution_key="support")
    changes = cp.changes_since(0, constitution_key="support")

    payload = changes.to_dict(detail)

    assert payload["constitution_key"] == "support"


@pytest.mark.parametrize("key", ["default", "support"])
def test_given_two_keys_when_apply_direction_runs_then_written_version_identifies_selected_key(
    cp, key
):
    cp.apply_direction(mission="Default mission", change_note="init")
    cp.apply_direction(mission="Support mission", change_note="init", constitution_key="support")

    result = cp.apply_direction(
        mission="Updated mission", change_note="update", constitution_key=key
    )

    assert result.constitution_key == key
