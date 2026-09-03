"""The unauthenticated /constitutions pages: what they show, what they must
never show, and how they answer for something that is not published."""

from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.transports import build_http_app


@pytest.fixture
def store():
    s = SqlConstitutionStore(url="sqlite://")
    s.create_all()
    return s


@pytest.fixture
def plane(store):
    return ControlPlane(store)


@pytest.fixture
def client(plane, store):
    """A client with no Authorization header at all: the public pages must
    work for anonymous visitors, with no token involved."""
    with TestClient(build_http_app(plane, store=store)) as c:
        yield c


def direction(plane, constitution="default", mission="M1", principles=("p1", "p2"), note="init"):
    return plane.set_direction(
        mission=mission, principles=principles, change_note=note, constitution=constitution
    )


def test_given_a_published_constitution_when_rendering_then_mission_principles_and_stamp_show(
    plane, client
):
    direction(plane, mission="Ship lending people trust", principles=("Be plain", "Be fast"))
    plane.publish()

    r = client.get("/constitutions/default")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "Ship lending people trust" in body
    assert "Be plain" in body and "Be fast" in body
    assert "v1" in body
    assert plane.current().created_at.strftime("%Y-%m-%d") in body


def test_given_an_unpublished_constitution_when_requesting_its_page_then_it_is_404_not_401(
    plane, client
):
    # 401 would confirm the name exists. Whether a private constitution is
    # there at all is exactly what it is private about.
    direction(plane)
    r = client.get("/constitutions/default")
    assert r.status_code == 404


def test_given_an_unknown_name_when_requesting_its_page_then_it_answers_like_unpublished(
    plane, client
):
    direction(plane, "internal")
    unpublished = client.get("/constitutions/internal")
    unknown = client.get("/constitutions/no-such-thing")
    assert unpublished.status_code == unknown.status_code == 404
    assert unpublished.text == unknown.text


def test_given_no_token_when_requesting_the_public_page_then_it_serves_while_mcp_refuses(
    plane, client
):
    direction(plane)
    plane.publish()
    assert client.get("/constitutions/default").status_code == 200
    mcp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert mcp.status_code == 401


def test_given_a_default_publish_when_rendering_then_history_and_change_notes_stay_off(
    plane, client
):
    direction(plane, note="initial constitution")
    direction(plane, mission="M2", note="dropped a principle for the enterprise deal")
    plane.publish()

    body = client.get("/constitutions/default").text
    assert "enterprise deal" not in body
    assert "initial constitution" not in body
    assert "M2" in body


def test_given_published_history_when_rendering_then_it_appears_newest_first(plane, client):
    direction(plane, note="first note")
    direction(plane, mission="M2", note="second note")
    direction(plane, mission="M3", note="third note")
    plane.publish(with_history=True)

    body = client.get("/constitutions/default").text
    assert body.index("third note") < body.index("second note") < body.index("first note")


def test_given_organization_authored_text_when_rendering_then_it_is_escaped_not_injected(
    plane, client
):
    hostile = "<script>alert('xss')</script>"
    direction(plane)
    direction(
        plane,
        mission=f"Mission {hostile}",
        principles=(f"Principle {hostile}",),
        note=f"Note {hostile}",
    )
    plane.publish(with_history=True)

    body = client.get("/constitutions/default").text
    assert "<script>alert" not in body
    escaped = "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
    assert f"Mission {escaped}" in body
    assert f"Principle {escaped}" in body
    assert f"Note {escaped}" in body


def test_given_the_page_when_inspecting_then_it_is_self_contained_with_no_external_assets(
    plane, client
):
    direction(plane)
    plane.publish(with_history=True)
    body = client.get("/constitutions/default").text
    assert "<script" not in body
    assert "http://" not in body and "https://" not in body
    assert "<style>" in body
    assert "prefers-color-scheme" in body


def test_given_no_principles_when_rendering_then_the_principles_list_is_omitted(plane, client):
    plane.set_direction(mission="Mission only", principles=(), change_note="init")
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "Mission only" in body
    assert "Principles" not in body


def test_given_no_mission_when_rendering_then_the_name_is_the_headline(plane, client):
    # Reachable: `kyno set --principle p --note init` sets no mission. A
    # blank headline would read as a broken page rather than a sparse one.
    plane.set_direction(principles=("p1",), change_note="init", constitution="rules")
    plane.publish(constitution="rules")
    body = client.get("/constitutions/rules").text
    assert "<h1" in body
    assert "rules" in body


def test_given_the_json_route_when_requesting_then_the_machine_readable_view_returns(plane, client):
    direction(plane, mission="Ship trust")
    plane.publish()

    r = client.get("/constitutions/default.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    payload = r.json()
    assert payload["constitution"] == "default"
    assert payload["mission"] == "Ship trust"
    assert payload["principles"] == [
        {"title": "p1", "description": ""},
        {"title": "p2", "description": ""},
    ]
    assert payload["version"] == 1
    assert "history" not in payload


def test_given_a_json_request_when_routing_then_it_matches_before_the_html_route(plane, client):
    # /constitutions/{name} would otherwise swallow "default.json" as a name.
    direction(plane)
    plane.publish()
    assert client.get("/constitutions/default.json").json()["constitution"] == "default"


def test_given_an_unpublished_name_when_requesting_its_json_then_it_is_404(plane, client):
    direction(plane)
    r = client.get("/constitutions/default.json")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_given_the_json_route_when_requesting_then_history_comes_only_if_published(plane, client):
    direction(plane, note="first note")
    direction(plane, mission="M2", note="second note")
    plane.publish(with_history=True)
    payload = client.get("/constitutions/default.json").json()
    assert [h["version"] for h in payload["history"]] == [2, 1]
    assert payload["history"][0]["change_note"] == "second note"


def test_given_published_constitutions_when_rendering_the_index_then_they_list_with_links(
    plane, client
):
    direction(plane, "product", mission="Product mission")
    plane.publish(constitution="product")

    r = client.get("/constitutions/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "product" in r.text
    assert "Product mission" in r.text
    assert 'href="/constitutions/product"' in r.text


def test_given_an_unpublished_constitution_when_rendering_the_index_then_it_never_shows(
    plane, client
):
    direction(plane, "acme-internal", mission="Internal mission nobody may see")
    direction(plane, "product", mission="Product mission")
    plane.publish(constitution="product")

    body = client.get("/constitutions/").text
    assert "acme-internal" not in body
    assert "Internal mission nobody may see" not in body
    assert "product" in body

    payload = client.get("/constitutions.json").json()
    assert [c["constitution"] for c in payload["constitutions"]] == ["product"]


def test_given_nothing_published_when_rendering_the_index_then_the_empty_page_is_honest(
    plane, client
):
    direction(plane, "internal")
    r = client.get("/constitutions/")
    assert r.status_code == 200
    assert "internal" not in r.text
    assert client.get("/constitutions.json").json()["constitutions"] == []


def test_given_a_multi_line_mission_when_rendering_the_index_then_only_the_first_line_shows(
    plane, client
):
    direction(plane, "product", mission="Headline claim\nA long second paragraph nobody needs here")
    plane.publish(constitution="product")
    body = client.get("/constitutions/").text
    assert "Headline claim" in body
    assert "A long second paragraph" not in body


def _publish_bypassing_the_name_rule(plane, name):
    """A row from before published names had to be slugs. The page renderer's
    escaping and URL-encoding are what keep such a page safe, so the tests
    using this helper exercise them against a name today's `publish` would
    refuse."""
    plane._store.set_publication(
        name, published_at=datetime(2026, 1, 1, tzinfo=UTC), history_public=False
    )


def test_given_a_hostile_name_when_rendering_the_index_then_it_is_escaped_and_url_encoded(
    plane, client
):
    direction(plane, "a<b> c", mission="Odd name")
    _publish_bypassing_the_name_rule(plane, "a<b> c")
    body = client.get("/constitutions/").text
    assert "<b>" not in body
    assert "&lt;b&gt;" in body
    assert "a%3Cb%3E%20c" in body


def test_given_a_constitution_named_index_when_routing_then_the_index_route_does_not_shadow_it(
    plane, client
):
    # The index lives at /constitutions.json rather than
    # /constitutions/index.json precisely so this name stays usable.
    direction(plane, "index", mission="A constitution actually named index")
    plane.publish(constitution="index")
    assert client.get("/constitutions/index").status_code == 200
    assert client.get("/constitutions/index.json").json()["constitution"] == "index"


def test_given_no_trailing_slash_when_requesting_the_index_then_it_is_reachable(plane, client):
    direction(plane, "product")
    plane.publish(constitution="product")
    assert client.get("/constitutions").status_code == 200


def _unbalanced_tags(markup: str) -> list[str]:
    """Tags left open (or closed twice) in a document, ignoring void elements."""
    from html.parser import HTMLParser

    void = {"meta", "br", "hr", "img", "input", "link"}

    class Balance(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.problems = []

        def handle_starttag(self, tag, attrs):
            if tag not in void:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack[-1] != tag:
                self.problems.append(f"</{tag}> closes {self.stack[-1:] or ['nothing']}")
            else:
                self.stack.pop()

    parser = Balance()
    parser.feed(markup)
    return parser.problems + [f"<{t}> never closed" for t in parser.stack]


@pytest.mark.parametrize("path", ["/constitutions/default", "/constitutions/", "/constitutions/x"])
def test_given_hostile_content_when_rendering_any_page_then_the_markup_stays_well_formed(
    plane, client, path
):
    # The pages are built by string concatenation, so tag balance is a real
    # property to hold rather than an assumption.
    hostile = "</ol></main><script>alert(1)</script>"
    direction(plane, mission=hostile, principles=(hostile,), note=hostile)
    direction(plane, mission=f"{hostile} two", note=hostile)
    plane.publish(with_history=True)

    assert _unbalanced_tags(client.get(path).text) == []


def test_given_the_public_endpoints_when_inspecting_then_they_are_sync_off_the_event_loop(
    plane, store
):
    # Deliberate: these handlers read the store, which is blocking. Starlette
    # runs a plain `def` endpoint in a threadpool and an `async def` one
    # directly on the event loop, where a slow query would stall every other
    # request in flight.
    import inspect

    app = build_http_app(plane, store=store)
    public = [r for r in app.routes if getattr(r, "path", "").startswith("/constitutions")]
    assert len(public) == 4
    for route in public:
        assert not inspect.iscoroutinefunction(route.endpoint), route.path


def test_given_hostile_content_when_rendering_the_title_element_then_it_is_escaped_too(
    plane, client
):
    # The title is a second HTML context fed from the same mission, and a
    # regression there would not show up in any body assertion.
    import re

    direction(plane, mission="Mission <script>alert(1)</script>")
    plane.publish()
    title = re.search(r"<title>(.*?)</title>", client.get("/constitutions/default").text).group(1)
    assert title == "Mission &lt;script&gt;alert(1)&lt;/script&gt;"


def test_given_no_mission_when_rendering_the_title_then_the_escaped_name_is_the_fallback(
    plane, client
):
    import re

    plane.set_direction(principles=("p1",), change_note="init", constitution="a<b>")
    _publish_bypassing_the_name_rule(plane, "a<b>")
    page = client.get("/constitutions/a%3Cb%3E")
    assert page.status_code == 200
    title = re.search(r"<title>(.*?)</title>", page.text).group(1)
    assert title == "a&lt;b&gt;"


# --- principles render as titled sections ----------------------------------


def test_given_a_described_principle_when_rendering_then_its_title_and_paragraph_show(
    plane, client
):
    plane.set_direction(
        mission="Ship lending people trust",
        principles=(
            {"title": "Say the hard number first", "description": "Before any softening story."},
        ),
        change_note="init",
    )
    plane.publish()

    body = client.get("/constitutions/default").text
    title_at = body.index("Say the hard number first")
    assert title_at < body.index("Before any softening story.")


def test_given_a_title_only_principle_when_rendering_then_no_empty_paragraph_shows(plane, client):
    direction(plane, principles=("p1",))
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "p1" in body
    assert "<p></p>" not in body


def test_given_a_hostile_description_when_rendering_then_it_is_escaped_like_everything(
    plane, client
):
    hostile = "<script>alert('xss')</script>"
    plane.set_direction(
        principles=({"title": "t", "description": f"Because {hostile}"},), change_note="init"
    )
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "<script>alert" not in body
    assert "Because &lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in body


def test_given_the_json_view_when_reading_then_principles_come_as_titles_and_descriptions(
    plane, client
):
    plane.set_direction(
        principles=("plain", {"title": "described", "description": "why"}), change_note="init"
    )
    plane.publish()
    payload = client.get("/constitutions/default.json").json()
    assert payload["principles"] == [
        {"title": "plain", "description": ""},
        {"title": "described", "description": "why"},
    ]


# --- the declaration renders as the document body --------------------------


def test_given_a_declaration_when_rendering_then_it_sits_between_mission_and_principles(
    plane, client
):
    plane.set_direction(
        mission="Ship lending people trust",
        declaration="The long form of what that means.",
        principles=("Say the hard number first",),
        change_note="init",
    )
    plane.publish()

    body = client.get("/constitutions/default").text
    assert body.index("Ship lending people trust") < body.index("The long form of what that means.")
    assert body.index("The long form of what that means.") < body.index("Say the hard number first")


def test_given_a_blank_line_in_the_declaration_when_rendering_then_a_new_paragraph_starts(
    plane, client
):
    plane.set_direction(
        mission="M", declaration="First paragraph.\n\nSecond paragraph.", change_note="init"
    )
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "<p>First paragraph.</p>" in body
    assert "<p>Second paragraph.</p>" in body


def test_given_a_wrapped_line_in_the_declaration_when_rendering_then_it_stays_one_paragraph(
    plane, client
):
    # CommonMark: a single newline is a soft break. Somebody wrapping a
    # paragraph in their editor must not get it broken across lines.
    plane.set_direction(mission="M", declaration="One line.\nNext line.", change_note="init")
    plane.publish()
    assert "<p>One line.\nNext line.</p>" in client.get("/constitutions/default").text


def test_given_a_markdown_declaration_when_rendering_the_page_then_the_markdown_renders(
    plane, client
):
    plane.set_direction(
        mission="M",
        declaration=(
            "# What we are for\n\n"
            "Lending is a *promise*.\n\n"
            "- Say the hard number\n"
            "- Refuse quietly\n\n"
            "> We would rather lose the deal.\n"
        ),
        change_note="init",
    )
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "<h1>What we are for</h1>" in body
    assert "<em>promise</em>" in body
    assert "<ul>" in body and "<li>Say the hard number</li>" in body
    assert "<blockquote>" in body
    assert "# What we are for" not in body


def test_given_markup_in_a_declaration_when_rendering_then_it_is_escaped_not_passed_through(
    plane, client
):
    # The load-bearing one: this page serves anonymous visitors, so an
    # organization's own text must never become markup that runs.
    plane.set_direction(
        mission="M",
        declaration="Before\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>",
        change_note="init",
    )
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "<script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<img" not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_given_a_javascript_link_in_a_declaration_when_rendering_then_it_is_refused(plane, client):
    plane.set_direction(
        mission="M",
        declaration="[click](javascript:alert(1)) and [ok](https://example.com/policy)",
        change_note="init",
    )
    plane.publish()
    body = client.get("/constitutions/default").text
    # It never becomes a link at all: markdown-it leaves the source as inert
    # literal text, which is safe -- what must never appear is the href.
    assert 'href="javascript:' not in body
    assert '<a href="https://example.com/policy">ok</a>' in body


def test_given_an_image_in_a_declaration_when_rendering_then_no_external_asset_appears(
    plane, client
):
    # Deliberate: the page is self-contained -- one response that
    # renders on a locked-down network and survives being saved to a file.
    plane.set_direction(
        mission="M", declaration="![tracker](https://evil.example/x.png)", change_note="init"
    )
    plane.publish()
    assert "<img" not in client.get("/constitutions/default").text


def test_given_a_rendered_declaration_when_inspecting_the_page_then_it_stays_well_formed(
    plane, client
):
    hostile = "</div></main># heading\n\n- <script>alert(1)</script>\n"
    plane.set_direction(mission="M", declaration=hostile, change_note="init")
    plane.publish()
    assert _unbalanced_tags(client.get("/constitutions/default").text) == []


def test_given_the_json_view_when_reading_the_declaration_then_it_is_raw_markdown(plane, client):
    # Data is markdown; rendering is the HTML page's business alone.
    source = "# What we are for\n\n- one\n"
    plane.set_direction(mission="M", declaration=source, change_note="init")
    plane.publish()
    assert client.get("/constitutions/default.json").json()["declaration"] == source


def test_given_no_declaration_when_rendering_then_no_empty_block_appears(plane, client):
    direction(plane)
    plane.publish()
    body = client.get("/constitutions/default").text
    assert '<div class="declaration">' not in body
    assert "<p></p>" not in body


def test_given_the_json_view_when_reading_then_the_declaration_is_exposed(plane, client):
    plane.set_direction(mission="M", declaration="The long form.", change_note="init")
    plane.publish()
    assert client.get("/constitutions/default.json").json()["declaration"] == "The long form."


def test_given_markdown_in_mission_and_principles_when_rendering_then_they_stay_plain_text(
    plane, client
):
    # Markdown is the declaration's privilege: it is the long-form document.
    # The rest are one-liners, where the literal text is the honest rendering.
    plane.set_direction(
        mission="# Not a heading",
        principles=({"title": "*not emphasis*", "description": "- not a list"},),
        change_note="init",
    )
    plane.publish()
    body = client.get("/constitutions/default").text
    assert "# Not a heading" in body
    assert "*not emphasis*" in body
    assert "- not a list" in body
    assert "<em>" not in body


SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@pytest.mark.parametrize(
    "path",
    [
        "/constitutions/",
        "/constitutions.json",
        "/constitutions/default",
        "/constitutions/default.json",
        "/constitutions/never-published",
        "/constitutions/never-published.json",
    ],
)
def test_given_any_public_response_when_inspecting_headers_then_the_security_set_is_there(
    plane, client, path
):
    # The last two paths answer 404: an error page is served to the same
    # anonymous visitors and carries the same headers.
    direction(plane)
    plane.publish()

    response = client.get(path)

    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, (path, name)


def _many_versions(plane, count):
    for i in range(1, count + 1):
        direction(plane, mission=f"M{i}", note=f"note {i}")


def test_given_a_long_history_when_serving_the_public_view_then_it_stops_at_a_hundred(
    plane, client
):
    from kyno.service import PUBLIC_HISTORY_LIMIT

    _many_versions(plane, PUBLIC_HISTORY_LIMIT + 5)
    plane.publish(with_history=True)

    versions = [h["version"] for h in client.get("/constitutions/default.json").json()["history"]]
    assert len(versions) == PUBLIC_HISTORY_LIMIT
    assert versions[0] == PUBLIC_HISTORY_LIMIT + 5
    assert versions[-1] == 6


def test_given_the_bounded_history_when_comparing_page_and_json_then_they_serve_the_same(
    plane, client
):
    from kyno.service import PUBLIC_HISTORY_LIMIT

    _many_versions(plane, PUBLIC_HISTORY_LIMIT + 2)
    plane.publish(with_history=True)

    body = client.get("/constitutions/default").text
    assert f"note {PUBLIC_HISTORY_LIMIT + 2}" in body
    assert "note 3" in body
    assert "note 2</p>" not in body


def test_given_a_history_at_the_bound_when_serving_then_it_comes_whole(plane, client):
    from kyno.service import PUBLIC_HISTORY_LIMIT

    _many_versions(plane, PUBLIC_HISTORY_LIMIT)
    plane.publish(with_history=True)

    history = client.get("/constitutions/default.json").json()["history"]
    assert [h["version"] for h in history] == list(range(PUBLIC_HISTORY_LIMIT, 0, -1))


def test_given_the_bound_when_reading_authenticated_then_the_full_history_is_still_there(plane):
    from kyno.service import PUBLIC_HISTORY_LIMIT

    _many_versions(plane, PUBLIC_HISTORY_LIMIT + 5)

    assert len(plane.changes_since(0).change_notes) == PUBLIC_HISTORY_LIMIT + 5


def test_given_repeat_visits_when_rendering_a_declaration_then_it_renders_once_per_text(
    plane, client
):
    from kyno.public_page import _declaration_html

    _declaration_html.cache_clear()
    plane.set_direction(mission="M", declaration="## Long\n\ntext", change_note="init")
    plane.publish()

    first = client.get("/constitutions/default").text
    second = client.get("/constitutions/default").text

    assert first == second
    info = _declaration_html.cache_info()
    assert info.misses == 1 and info.hits >= 1


def test_given_the_render_cache_when_inspecting_its_key_then_it_is_the_declaration_text(
    plane, client
):
    # Two constitutions sharing one declaration share one render: versions
    # are immutable, so the text is the whole identity of the output.
    from kyno.public_page import _declaration_html

    _declaration_html.cache_clear()
    text = "## Shared\n\nsame text"
    for name in ("alpha", "beta"):
        plane.set_direction(mission="M", declaration=text, change_note="init", constitution=name)
        plane.publish(name)

    client.get("/constitutions/alpha")
    client.get("/constitutions/beta")

    info = _declaration_html.cache_info()
    assert info.misses == 1 and info.hits == 1
    assert info.maxsize == 64
