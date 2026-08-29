"""Making the public page yours: theme tokens and a template override that
can restyle the page without ever being able to un-escape what it renders.
"""

import json

import pytest
from starlette.testclient import TestClient

from kyno.public_page import PageConfig, PageTheme, render_constitution, render_index
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.transports import build_http_app

HOSTILE = "<script>alert('xss')</script>"


@pytest.fixture
def plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def direction(plane, constitution="default", mission="M1", principles=("p1", "p2"), note="init"):
    return plane.set_direction(
        mission=mission, principles=principles, change_note=note, constitution=constitution
    )


def published(plane, **kwargs):
    direction(plane, **kwargs)
    plane.publish()
    return plane.public_constitution()


# --- theme tokens ----------------------------------------------------------


def test_given_no_configuration_when_rendering_the_page_then_the_built_in_tokens_are_there(plane):
    # With no configuration, the page must carry exactly the built-in token values.
    page = render_constitution(published(plane))
    for token in (
        "--accent: #6d6d66",
        "--bg: #fbfbf9",
        "--fg: #1b1b19",
        "--muted: #6d6d66",
        "--rule: #e4e3de",
    ):
        assert token in page, token
    assert "ui-sans-serif" in page
    assert "prefers-color-scheme: dark" in page


def test_given_configured_tokens_when_rendering_then_they_reach_the_root_block(plane):
    theme = PageTheme(
        accent="#b4531f", background="#fffdf7", text="#14110c", font_family="Iowan Old Style, serif"
    )
    page = render_constitution(published(plane), PageConfig(theme=theme))
    assert "--accent: #b4531f" in page
    assert "--bg: #fffdf7" in page
    assert "--fg: #14110c" in page
    assert "Iowan Old Style, serif" in page


def test_given_your_own_colors_when_rendering_then_the_automatic_dark_swap_is_off(plane):
    # Deliberate: inverting a palette somebody chose would produce a page
    # they never approved. Picking colors means owning them.
    page = render_constitution(published(plane), PageConfig(theme=PageTheme(background="#fffdf7")))
    assert "prefers-color-scheme" not in page


def test_given_only_a_font_when_rendering_then_the_automatic_dark_swap_stays(plane):
    # A typeface is the same typeface in either scheme, so it is not a
    # reason to stop following the reader's preference.
    theme = PageTheme(font_family="Iowan Old Style, serif")
    page = render_constitution(published(plane), PageConfig(theme=theme))
    assert "prefers-color-scheme: dark" in page
    assert "Iowan Old Style, serif" in page


def test_given_a_theme_when_rendering_the_index_then_it_uses_the_same_theme(plane):
    direction(plane, "product", mission="Product mission")
    plane.publish(constitution="product")
    page = render_index(plane.published_constitutions(), PageConfig(theme=PageTheme(accent="#b45")))
    assert "--accent: #b45" in page


# --- template override -----------------------------------------------------

TEMPLATE = """<!doctype html>
<html><head><title>$name</title></head>
<body>
<h1>$mission</h1>
<ul class="ours">$principles</ul>
<p>version $version, updated $updated</p>
$history
</body></html>
"""


def test_given_a_custom_template_when_rendering_then_it_replaces_the_built_in_page(plane, tmp_path):
    path = tmp_path / "constitution.html"
    path.write_text(TEMPLATE)
    view = published(plane, mission="Ship trust")

    page = render_constitution(view, PageConfig(constitution_template=str(path)))
    assert '<ul class="ours">' in page
    assert "Ship trust" in page
    assert "version 1, updated" in page
    assert "p1" in page and "p2" in page
    # None of our own chrome survives: the operator's document is the document.
    assert "<style>" not in page
    assert "eyebrow" not in page


def test_given_a_custom_template_when_rendering_then_values_arrive_already_escaped(plane, tmp_path):
    # The whole point: an organization's own markup cannot un-escape the
    # organization's own text, so a hostile principle stays inert in it.
    path = tmp_path / "constitution.html"
    path.write_text(TEMPLATE)
    direction(plane)
    direction(
        plane,
        mission=f"Mission {HOSTILE}",
        principles=(f"Principle {HOSTILE}",),
        note=f"Note {HOSTILE}",
    )
    plane.publish(with_history=True)

    page = render_constitution(
        plane.public_constitution(), PageConfig(constitution_template=str(path))
    )
    assert "<script>alert" not in page
    escaped = "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
    assert f"Mission {escaped}" in page
    assert f"Principle {escaped}" in page
    assert f"Note {escaped}" in page


def test_given_unpublished_history_when_rendering_a_template_then_the_history_is_empty(
    plane, tmp_path
):
    path = tmp_path / "constitution.html"
    path.write_text("<html><body>[$history]</body></html>")
    view = published(plane, note="a note nobody may read")

    page = render_constitution(view, PageConfig(constitution_template=str(path)))
    assert "[]" in page
    assert "a note nobody may read" not in page


def test_given_a_template_ignoring_placeholders_when_rendering_then_that_is_fine(plane, tmp_path):
    path = tmp_path / "constitution.html"
    path.write_text("<html><body><h1>$mission</h1></body></html>")
    page = render_constitution(
        published(plane, mission="Just this"), PageConfig(constitution_template=str(path))
    )
    assert "Just this" in page


def test_given_an_unknown_placeholder_when_rendering_then_it_is_left_alone_not_exploded(
    plane, tmp_path
):
    # safe_substitute: a typo in an operator's template must not 500 the page.
    path = tmp_path / "constitution.html"
    path.write_text("<html><body>$mission $mision $$ ${nope}</body></html>")
    page = render_constitution(
        published(plane, mission="Kept"), PageConfig(constitution_template=str(path))
    )
    assert "Kept" in page
    assert "$mision" in page


def test_given_a_missing_template_when_rendering_then_the_built_in_page_serves_and_a_warning_logs(
    plane, tmp_path, caplog
):
    missing = tmp_path / "gone.html"
    with caplog.at_level("WARNING"):
        page = render_constitution(
            published(plane, mission="Still served"), PageConfig(constitution_template=str(missing))
        )
    assert "Still served" in page
    assert "<style>" in page  # the built-in page, not a blank one
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(missing) in warnings[0].getMessage()


def test_given_a_template_that_is_not_valid_text_when_rendering_then_the_built_in_page_serves(
    plane, tmp_path, caplog
):
    path = tmp_path / "binary.html"
    path.write_bytes(b"\xff\xfe not utf-8 at all")
    with caplog.at_level("WARNING"):
        page = render_constitution(
            published(plane, mission="Still served"), PageConfig(constitution_template=str(path))
        )
    assert "Still served" in page
    assert "<style>" in page
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


def test_given_a_custom_index_template_when_rendering_then_it_replaces_the_built_in_index(
    plane, tmp_path
):
    path = tmp_path / "index.html"
    path.write_text('<html><body><ul class="ours">$items</ul></body></html>')
    direction(plane, "product", mission="Product mission")
    plane.publish(constitution="product")

    page = render_index(plane.published_constitutions(), PageConfig(index_template=str(path)))
    assert '<ul class="ours">' in page
    assert "product" in page
    assert "Product mission" in page
    assert "<style>" not in page


def test_given_a_broken_index_template_when_rendering_then_the_built_in_index_serves(
    plane, tmp_path, caplog
):
    direction(plane, "product", mission="Product mission")
    plane.publish(constitution="product")
    with caplog.at_level("WARNING"):
        page = render_index(
            plane.published_constitutions(), PageConfig(index_template=str(tmp_path / "gone.html"))
        )
    assert "Product mission" in page
    assert "<style>" in page
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


# --- through the real app --------------------------------------------------


def test_given_a_template_that_disappears_when_serving_then_the_public_page_stays_up(
    plane, tmp_path
):
    # The load-bearing behavior: templates are read per request, and a broken
    # one degrades to the built-in page rather than to a 500.
    path = tmp_path / "constitution.html"
    path.write_text(TEMPLATE)
    published(plane, mission="Ship trust")
    app = build_http_app(plane, token="secret", page=PageConfig(constitution_template=str(path)))

    with TestClient(app) as client:
        assert '<ul class="ours">' in client.get("/constitutions/default").text
        path.unlink()
        recovered = client.get("/constitutions/default")
        assert recovered.status_code == 200
        assert "Ship trust" in recovered.text
        assert "<style>" in recovered.text


def test_given_a_custom_template_when_serving_then_no_route_semantics_change(plane, tmp_path):
    path = tmp_path / "constitution.html"
    path.write_text(TEMPLATE)
    direction(plane, "internal")
    app = build_http_app(plane, token="secret", page=PageConfig(constitution_template=str(path)))

    with TestClient(app) as client:
        assert client.get("/constitutions/internal").status_code == 404
        assert client.get("/constitutions/nope").status_code == 404
        payload = json.loads(client.get("/constitutions/internal.json").text)
        assert payload == {"error": "not found"}


def test_given_a_custom_template_when_reading_the_json_view_then_it_is_untouched(plane, tmp_path):
    # Templates are a presentation choice; the machine-readable view is a
    # contract and must not move with them.
    path = tmp_path / "constitution.html"
    path.write_text(TEMPLATE)
    published(plane, mission="Ship trust")
    app = build_http_app(plane, token="secret", page=PageConfig(constitution_template=str(path)))

    with TestClient(app) as client:
        payload = client.get("/constitutions/default.json").json()
    assert payload["mission"] == "Ship trust"
    assert [p["title"] for p in payload["principles"]] == ["p1", "p2"]


def test_given_the_index_template_when_rendering_then_it_can_report_how_many_are_published(
    plane, tmp_path
):
    path = tmp_path / "index.html"
    path.write_text("<html><body><p>$count published</p>$items</body></html>")
    for name in ("alpha", "beta"):
        direction(plane, name, mission=f"{name} mission")
        plane.publish(constitution=name)

    page = render_index(plane.published_constitutions(), PageConfig(index_template=str(path)))
    assert "<p>2 published</p>" in page


def test_given_the_docs_when_comparing_to_the_code_then_the_documented_placeholders_exist(
    plane, tmp_path
):
    # The publishing page is how an operator learns these names; a placeholder
    # it documents but we do not fill would render as literal text on their page.
    from pathlib import Path as _Path

    readme = (_Path(__file__).parent.parent / "docs" / "publishing.md").read_text()
    documented = [
        "$stylesheet",
        "$name",
        "$mission",
        "$declaration",
        "$principles",
        "$version",
        "$updated",
        "$history",
    ]
    for placeholder in documented:
        assert placeholder in readme, f"README does not mention {placeholder}"

    # Every documented name substitutes away; a leftover "$" means one is unfilled.
    path = tmp_path / "constitution.html"
    path.write_text(" ".join(documented))
    page = render_constitution(published(plane), PageConfig(constitution_template=str(path)))
    assert "$" not in page

    index_path = tmp_path / "index.html"
    index_path.write_text("$stylesheet $items $count")
    assert "$" not in render_index((), PageConfig(index_template=str(index_path)))


def test_given_no_accent_configured_when_rendering_then_the_muted_colour_serves_both_schemes(plane):
    # Accent defaults to the muted colour: the rules it covers would otherwise
    # read var(--muted), and an operator who sets nothing must see no
    # difference between the two tokens.
    import re

    page = render_constitution(published(plane))
    light = re.search(r":root \{(.*?)\}", page, re.S).group(1)
    dark = re.search(r"prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}", page, re.S).group(1)
    for block, label in ((light, "light"), (dark, "dark")):
        accent = re.search(r"--accent:\s*([^;]+);", block).group(1).strip()
        muted = re.search(r"--muted:\s*([^;]+);", block).group(1).strip()
        assert accent == muted, f"{label}: accent {accent} != muted {muted}"


def test_given_a_declaration_when_a_template_renders_then_it_arrives_rendered_and_escaped(
    plane, tmp_path
):
    path = tmp_path / "constitution.html"
    path.write_text("<html><body><article>$declaration</article></body></html>")
    plane.set_direction(
        mission="M",
        declaration=f"First paragraph.\n\n{HOSTILE}",
        change_note="init",
    )
    plane.publish()

    page = render_constitution(
        plane.public_constitution(), PageConfig(constitution_template=str(path))
    )
    assert "<p>First paragraph.</p>" in page
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert('xss')&lt;/script&gt;" in page


def test_given_no_declaration_when_a_template_renders_then_it_gets_an_empty_one(plane, tmp_path):
    path = tmp_path / "constitution.html"
    path.write_text("<html><body>[$declaration]</body></html>")
    page = render_constitution(published(plane), PageConfig(constitution_template=str(path)))
    assert "[]" in page


def test_given_a_markdown_declaration_when_a_template_renders_then_it_arrives_as_html(
    plane, tmp_path
):
    # An operator's template gets the document already rendered: markdown is
    # ours to interpret, and their file is markup around the result.
    path = tmp_path / "constitution.html"
    path.write_text("<html><body><article>$declaration</article></body></html>")
    plane.set_direction(mission="M", declaration="## Why\n\n- one\n", change_note="init")
    plane.publish()

    page = render_constitution(
        plane.public_constitution(), PageConfig(constitution_template=str(path))
    )
    assert "<h2>Why</h2>" in page
    assert "<li>one</li>" in page
