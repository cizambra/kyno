"""Direct MCP handler and schema contracts."""

from datetime import UTC, datetime

import pytest

from kyno import mcp_server, mcp_tools
from kyno.models import Token, TokenScope


def test_given_a_typed_token_scope_when_asking_whoami_then_a_plain_string_is_returned():
    token = Token(id=7, name="deploy", scope=TokenScope.WRITE, created_at=datetime.now(UTC))

    answer = mcp_server.handle_whoami(token)

    assert answer["scope"] == "write"
    assert type(answer["scope"]) is str


def test_given_a_set_direction_when_getting_the_constitution_then_it_round_trips(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by="op"
    )
    d = mcp_server.handle_get_constitution(cp)
    assert d["version"] == 1 and d["mission"] == "M1"
    assert d["principles"] == [{"title": "p1"}]


def test_given_versions_when_calling_get_changes_since_then_the_changes_return(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )
    d = mcp_server.handle_get_changes_since(cp, 1)
    assert d["current_version"] == 2 and d["changed"] is True
    assert d["mission"] == "M2" and d["change_notes"] == ["pivot"]


def test_given_a_fresh_store_when_getting_the_constitution_then_the_empty_state_returns(cp):
    d = mcp_server.handle_get_constitution(cp)
    assert d["version"] == 0
    assert d["mission"] == ""
    assert d["principles"] == []


def test_given_a_future_version_when_calling_get_changes_since_then_valueerror_raises(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    with pytest.raises(ValueError):
        mcp_server.handle_get_changes_since(cp, 9)


def test_given_a_built_server_when_listing_registrations_then_the_expected_names_are_there(cp):
    server = mcp_server.build_server(cp)
    assert server.name == "kyno"
    assert mcp_server.RESOURCE_URI == "kyno://constitution/current"


def test_given_a_missing_known_version_when_requiring_it_then_it_raises_cleanly():
    with pytest.raises(ValueError, match="missing required argument: known_version"):
        mcp_server._require({}, "known_version")


def test_given_a_missing_change_note_when_requiring_it_then_it_raises_cleanly():
    with pytest.raises(ValueError, match="missing required argument: change_note"):
        mcp_server._require({}, "change_note")


def test_given_a_no_op_change_when_calling_set_direction_then_it_maps_to_valueerror(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    with pytest.raises(ValueError):
        mcp_server.handle_set_direction(
            cp, mission="M1", principles=["p1"], change_note="noop", created_by=None
        )


def test_given_a_blank_change_note_when_calling_set_direction_then_it_maps_to_valueerror(cp):
    # _require only checks the key is present; a blank value must still be
    # rejected downstream (EmptyChangeError -> ValueError via _guard).
    with pytest.raises(ValueError):
        mcp_server.handle_set_direction(
            cp, mission="M1", principles=["p1"], change_note="   ", created_by=None
        )


def test_given_the_module_when_looking_up_run_stdio_then_it_is_a_coroutine_function():
    import inspect

    from kyno.transports import run_stdio

    assert inspect.iscoroutinefunction(run_stdio)


def test_given_the_tool_schemas_when_inspecting_then_constitution_is_an_optional_argument():
    for tool in mcp_tools.TOOLS:
        if tool.name == "whoami":
            # whoami answers about the request's token, not a constitution.
            assert tool.inputSchema["properties"] == {}
            continue
        props = tool.inputSchema["properties"]
        assert props["constitution"]["type"] == "string"
        assert "constitution" not in tool.inputSchema.get("required", [])


def test_given_a_named_set_when_getting_that_name_then_it_round_trips(cp):
    mcp_server.handle_set_direction(
        cp, mission="EU1", principles=["p1"], change_note="init", created_by="op", constitution="eu"
    )
    d = mcp_server.handle_get_constitution(cp, constitution="eu")
    assert d["version"] == 1 and d["mission"] == "EU1"
    assert mcp_server.handle_get_constitution(cp)["version"] == 0


def test_given_a_name_when_calling_get_changes_since_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp, mission="EU1", principles=["p1"], change_note="init", created_by=None, constitution="eu"
    )
    mcp_server.handle_set_direction(
        cp, mission="EU2", principles=None, change_note="pivot", created_by=None, constitution="eu"
    )
    d = mcp_server.handle_get_changes_since(cp, 1, constitution="eu")
    assert d["current_version"] == 2 and d["mission"] == "EU2"
    assert d["change_notes"] == ["pivot"]


def test_given_an_unknown_constitution_when_reading_over_mcp_then_the_empty_state_returns(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    d = mcp_server.handle_get_constitution(cp, constitution="never-written")
    assert d["version"] == 0 and d["mission"] == "" and d["principles"] == []
    changes = mcp_server.handle_get_changes_since(cp, 4, constitution="never-written")
    assert changes["current_version"] == 0 and changes["changed"] is False


def test_given_no_detail_asked_when_getting_the_constitution_then_it_is_compact(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_constitution(cp)

    assert d["mission"] == "Ship trustworthy lending"
    # Absent, not empty: "you did not ask for it" and "there is none" are
    # different answers, and only one of them is true here.
    assert "declaration" not in d
    assert d["principles"] == [{"title": "Be honest"}]


def test_given_full_detail_when_getting_the_constitution_then_the_whole_document_comes(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_constitution(cp, detail="full")

    assert d["declaration"] == "# Our declaration\n\nThe long form of what that means."
    assert d["principles"] == [{"title": "Be honest", "description": "Say the hard number first."}]


def test_given_no_detail_asked_when_calling_get_changes_since_then_metadata_still_comes(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )

    d = mcp_server.handle_get_changes_since(cp, 1)

    assert "declaration" not in d
    assert d["principles"] == [{"title": "Be honest"}]
    assert d["changed"] is True and d["change_notes"] == ["pivot"]
    assert d["changed_mission"] is True and d["changed_principles"] is False


def test_given_full_detail_when_calling_get_changes_since_then_the_whole_document_comes(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )

    d = mcp_server.handle_get_changes_since(cp, 1, detail="full")

    assert d["declaration"] == "# Our declaration\n\nThe long form of what that means."
    assert d["principles"] == [{"title": "Be honest", "description": "Say the hard number first."}]


@pytest.mark.parametrize("tool", ["get_constitution", "get_changes_since"])
def test_given_an_unknown_detail_when_reading_then_the_error_is_clean(cp, tool):
    with pytest.raises(ValueError, match="verbose"):
        if tool == "get_constitution":
            mcp_server.handle_get_constitution(cp, detail="verbose")
        else:
            mcp_server.handle_get_changes_since(cp, 0, detail="verbose")


def test_given_the_two_read_tools_when_inspecting_schemas_then_both_advertise_detail():
    # An agent reads the schema to learn the knob exists; a tool that hides it
    # would leave the whole document unreachable in practice.
    by_name = {t.name: t for t in mcp_tools.TOOLS}
    read_tools = {n: by_name[n] for n in ("get_constitution", "get_changes_since")}
    for name, tool in read_tools.items():
        assert "detail" in tool.inputSchema["properties"], name
        assert tool.inputSchema["properties"]["detail"]["enum"] == ["compact", "full"], name
        assert "full" in tool.description, name


def test_given_a_declaration_when_calling_get_declaration_then_it_comes_with_its_version(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_declaration(cp)

    assert d["declaration"] == "# Our declaration\n\nThe long form of what that means."
    assert d["version"] == 1


def test_given_no_declaration_when_calling_get_declaration_then_it_is_not_an_error(cp):
    # Reads never fail: "there is no declaration" is an answer, not a fault.
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by=None
    )
    assert mcp_server.handle_get_declaration(cp) == {"version": 1, "declaration": ""}


def test_given_an_empty_store_when_calling_get_declaration_then_version_zero_answers(cp):
    assert mcp_server.handle_get_declaration(cp) == {"version": 0, "declaration": ""}


def test_given_a_name_when_calling_get_declaration_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        declaration="The EU long form.",
        principles=None,
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_declaration(cp, "eu")["declaration"] == "The EU long form."
    assert mcp_server.handle_get_declaration(cp)["declaration"] == ""


def test_given_a_title_when_calling_get_principle_then_one_comes_in_full_with_its_version(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)

    d = mcp_server.handle_get_principle(cp, "Be honest")

    assert d == {
        "title": "Be honest",
        "description": "Say the hard number first.",
        "version": 1,
    }


def test_given_a_title_when_calling_get_principle_then_the_match_is_exact(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    for near_miss in ("be honest", "Be honest ", "honest"):
        with pytest.raises(ValueError, match="honest"):
            mcp_server.handle_get_principle(cp, near_miss)


def test_given_a_missing_title_when_calling_get_principle_then_the_error_names_it(cp):
    # Unlike an empty store, asking about a principle that is not there is a
    # real mistake, and the message has to be enough to spot the typo.
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    with pytest.raises(ValueError, match="Be hnoest"):
        mcp_server.handle_get_principle(cp, "Be hnoest")


def test_given_a_name_when_calling_get_principle_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        principles=[{"title": "EU only", "description": "why"}],
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_principle(cp, "EU only", "eu")["description"] == "why"
    with pytest.raises(ValueError):
        mcp_server.handle_get_principle(cp, "EU only")


def test_given_two_principles_with_one_title_when_calling_get_principle_then_the_first_answers(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="M",
        principles=[
            {"title": "Be honest", "description": "first"},
            {"title": "Be honest", "description": "second"},
        ],
        change_note="init",
        created_by=None,
    )
    assert mcp_server.handle_get_principle(cp, "Be honest")["description"] == "first"


def test_given_the_targeted_reads_when_inspecting_schemas_then_argument_sources_are_stated():
    tools = {t.name: t for t in mcp_tools.TOOLS}
    assert "get_constitution" in tools["get_principle"].description
    assert "version" in tools["get_principle"].description
    assert "version" in tools["get_declaration"].description
    assert tools["get_principle"].inputSchema["required"] == ["title"]


def test_given_a_mission_when_calling_get_mission_then_the_headline_comes_with_its_version(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    assert mcp_server.handle_get_mission(cp) == {
        "version": 1,
        "mission": "Ship trustworthy lending",
    }


def test_given_an_empty_store_when_calling_get_mission_then_version_zero_answers(cp):
    assert mcp_server.handle_get_mission(cp) == {"version": 0, "mission": ""}


def test_given_a_name_when_calling_get_mission_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        principles=None,
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_mission(cp, "eu")["mission"] == "EU"
    assert mcp_server.handle_get_mission(cp)["mission"] == ""


def test_given_no_detail_asked_when_calling_get_principles_then_titles_only_come(cp):
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    assert mcp_server.handle_get_principles(cp) == {
        "version": 1,
        "principles": [{"title": "Be honest"}],
    }


def test_given_explained_detail_when_calling_get_principles_then_every_description_comes(cp):
    # The slice an agent adjudicating between principles wants: all of them,
    # explained, without the mission or the declaration around them.
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    assert mcp_server.handle_get_principles(cp, detail="full") == {
        "version": 1,
        "principles": [{"title": "Be honest", "description": "Say the hard number first."}],
    }


def test_given_no_principles_when_calling_get_principles_then_it_is_not_an_error(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by=None
    )
    assert mcp_server.handle_get_principles(cp) == {"version": 1, "principles": []}


def test_given_an_empty_store_when_calling_get_principles_then_version_zero_answers(cp):
    assert mcp_server.handle_get_principles(cp) == {"version": 0, "principles": []}


def test_given_a_detail_it_does_not_offer_when_calling_get_principles_then_it_refuses(cp):
    with pytest.raises(ValueError, match="compact"):
        mcp_server.handle_get_principles(cp, detail="compact")


def test_given_a_name_when_calling_get_principles_then_it_reads_that_constitution(cp):
    mcp_server.handle_set_direction(
        cp,
        mission="EU",
        principles=["EU only"],
        change_note="init",
        created_by=None,
        constitution="eu",
    )
    assert mcp_server.handle_get_principles(cp, "eu")["principles"] == [{"title": "EU only"}]
    assert mcp_server.handle_get_principles(cp)["principles"] == []


def test_given_the_read_family_when_answering_then_each_carries_its_source_version(cp):
    # What makes mixing reads safe: two answers with the same version
    # describe one document.
    mcp_server.handle_set_direction(cp, **RICH, change_note="init", created_by=None)
    reads = (
        mcp_server.handle_get_constitution(cp),
        mcp_server.handle_get_mission(cp),
        mcp_server.handle_get_declaration(cp),
        mcp_server.handle_get_principles(cp),
        mcp_server.handle_get_principle(cp, "Be honest"),
    )
    assert [r["version"] for r in reads] == [1, 1, 1, 1, 1]


def test_given_the_server_when_listing_tools_then_all_of_them_read_as_one_family():
    names = [t.name for t in mcp_tools.TOOLS]
    assert names == [
        "get_constitution",
        "get_changes_since",
        "get_mission",
        "get_declaration",
        "get_principles",
        "get_principle",
        "export_versions",
        "set_direction",
        "whoami",
    ]
    for tool in mcp_tools.TOOLS:
        description = tool.description
        assert description.startswith("Return ") or description.startswith("Append "), tool.name
        assert description.endswith("."), tool.name
        if tool.name.startswith("get_"):
            assert "constitution" in tool.inputSchema["properties"], tool.name


def test_given_a_markdown_declaration_when_calling_get_declaration_then_raw_markdown_serves(cp):
    # Data is markdown. Rendering it is the public HTML page's business, and
    # an agent asking for the declaration wants the source, not a document.
    source = "# What we are for\n\n- one\n- two\n"
    mcp_server.handle_set_direction(
        cp, mission="M", declaration=source, principles=None, change_note="init", created_by=None
    )
    assert mcp_server.handle_get_declaration(cp)["declaration"] == source
    assert mcp_server.handle_get_constitution(cp, detail="full")["declaration"] == source


def test_given_versions_when_calling_export_versions_then_the_whole_history_comes_ascending(cp):
    mcp_server.handle_set_direction(
        cp, mission="M1", principles=None, change_note="init", created_by="camilo"
    )
    mcp_server.handle_set_direction(
        cp, mission="M2", principles=None, change_note="pivot", created_by=None
    )
    rows = mcp_server.handle_export_versions(cp)
    assert [r["version"] for r in rows] == [1, 2]
    assert rows[0]["mission"] == "M1" and rows[0]["change_note"] == "init"
    assert rows[0]["created_by"] == "camilo" and "created_at" in rows[0]


def test_given_bounds_when_calling_export_versions_then_they_are_inclusive(cp):
    for n in (1, 2, 3):
        mcp_server.handle_set_direction(
            cp, mission=f"M{n}", principles=None, change_note=f"n{n}", created_by=None
        )
    rows = mcp_server.handle_export_versions(cp, from_version=2, to_version=3)
    assert [r["version"] for r in rows] == [2, 3]


def test_given_an_unwritten_name_when_calling_export_versions_then_the_list_is_empty(cp):
    assert mcp_server.handle_export_versions(cp, "nope") == []


def test_given_an_authorization_argument_when_setting_direction_then_it_is_recorded(cp):
    result = mcp_server.handle_set_direction(
        cp,
        mission="M1",
        principles=None,
        change_note="init",
        created_by="ci",
        authorized_by="automation",
    )
    assert result["authorized_by"] == "automation"


RICH = dict(
    mission="Ship trustworthy lending",
    declaration="# Our declaration\n\nThe long form of what that means.",
    principles=[{"title": "Be honest", "description": "Say the hard number first."}],
)
