"""Direction responses identify the constitution Core actually selected."""

import json

import pytest

from kyno.service import ControlPlane
from kyno.wire import RESOURCE_URI


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_empty_store_when_current_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):

    result = cp.current(**selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_empty_store_when_get_constitution_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):

    result = cp.get_constitution(version=0, **selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_empty_store_when_changes_since_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):

    result = cp.changes_since(last_seen_version=0, **selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_empty_store_when_publication_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):

    result = cp.publication(**selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_stored_direction_when_current_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    result = cp.current(**selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_stored_direction_when_get_constitution_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    result = cp.get_constitution(version=1, **selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_newer_direction_when_changes_since_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    result = cp.changes_since(last_seen_version=0, **selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_current_version_when_changes_since_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    result = cp.changes_since(last_seen_version=1, **selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_private_direction_when_publish_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    result = cp.publish(**selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_private_direction_when_publication_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    result = cp.publication(**selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_public_direction_when_unpublish_runs_then_result_identifies_selected_key(
    cp, selector, expected_key
):
    cp.apply_direction(mission="Help customers", change_note="Initial direction", **selector)
    cp.publish(**selector)

    result = cp.unpublish(**selector)

    assert result.constitution_key == expected_key


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_current_direction_when_call_tool_get_constitution_then_response_identifies_key(
    mcp_runner, initialized, selector, expected_key
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    reply = runner.call(lambda session: session.call_tool("get_constitution", {**selector}))

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected_key


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_version_zero_when_call_tool_get_constitution_then_response_identifies_key(
    mcp_runner, initialized, selector, expected_key
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    reply = runner.call(
        lambda session: session.call_tool("get_constitution", {**selector, "version": 0})
    )

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected_key


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_changes_when_call_tool_get_changes_since_then_response_identifies_key(
    mcp_runner, initialized, selector, expected_key
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    reply = runner.call(
        lambda session: session.call_tool("get_changes_since", {**selector, "last_seen_version": 0})
    )

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected_key


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_mission_when_call_tool_get_mission_then_response_identifies_key(
    mcp_runner, initialized, selector, expected_key
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    reply = runner.call(lambda session: session.call_tool("get_mission", {**selector}))

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected_key


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_declaration_when_call_tool_get_declaration_then_response_identifies_key(
    mcp_runner, initialized, selector, expected_key
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    reply = runner.call(lambda session: session.call_tool("get_declaration", {**selector}))

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected_key


@pytest.mark.parametrize("initialized", [False, True], ids=["empty", "written"])
@pytest.mark.parametrize(
    "selector, expected_key",
    [
        pytest.param({}, "default", id="omitted"),
        pytest.param({"constitution_key": None}, "default", id="null"),
        pytest.param({"constitution_key": " eu-west "}, "eu-west", id="padded-named-key"),
    ],
)
def test_given_principles_when_call_tool_get_principles_then_response_identifies_key(
    mcp_runner, initialized, selector, expected_key
):
    runner, plane = mcp_runner
    if initialized:
        plane.apply_direction(mission="Help customers", change_note="Initial direction", **selector)

    reply = runner.call(lambda session: session.call_tool("get_principles", {**selector}))

    assert not reply.isError
    assert json.loads(reply.content[0].text)["constitution_key"] == expected_key


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
def test_given_empty_store_when_call_tool_apply_direction_then_created_version_identifies_key(
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
def test_given_two_histories_when_store_head_runs_then_selected_key_returns(store, key):
    plane = ControlPlane(store)
    plane.apply_direction(mission="Default mission", change_note="Initial direction")
    plane.apply_direction(
        mission="Support mission", change_note="Initial direction", constitution_key="support"
    )

    version = store.head(key)

    assert version.constitution_key == key


@pytest.mark.parametrize("key", ["default", "support"])
def test_given_two_histories_when_store_get_runs_then_selected_key_returns(store, key):
    plane = ControlPlane(store)
    plane.apply_direction(mission="Default mission", change_note="Initial direction")
    plane.apply_direction(
        mission="Support mission", change_note="Initial direction", constitution_key="support"
    )

    version = store.get(key, 1)

    assert version.constitution_key == key


@pytest.mark.parametrize("key", ["default", "support"])
def test_given_two_histories_when_store_versions_after_runs_then_selected_key_returns(store, key):
    plane = ControlPlane(store)
    plane.apply_direction(mission="Default mission", change_note="Initial direction")
    plane.apply_direction(
        mission="Support mission", change_note="Initial direction", constitution_key="support"
    )

    versions = store.versions_after(key, 0)

    assert [version.constitution_key for version in versions] == [key]


@pytest.mark.parametrize("key", ["default", "support"])
def test_given_two_histories_when_store_export_versions_runs_then_selected_key_returns(store, key):
    plane = ControlPlane(store)
    plane.apply_direction(mission="Default mission", change_note="Initial direction")
    plane.apply_direction(
        mission="Support mission", change_note="Initial direction", constitution_key="support"
    )

    versions = store.export_versions(key)

    assert [version["constitution_key"] for version in versions] == [key]


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


def test_given_two_keys_when_head_and_delta_runs_then_head_identifies_selected_key(cp):
    cp.apply_direction(mission="Default mission", change_note="Initial direction")
    cp.apply_direction(
        mission="Support mission", change_note="Initial direction", constitution_key="support"
    )

    head, _ = cp.head_and_delta(mission="Resolve customer issues", constitution_key=" support ")

    assert head.constitution_key == "support"
    assert head.mission == "Support mission"
