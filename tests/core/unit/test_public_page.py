import re
from datetime import UTC, datetime

from kyno.models import PublicConstitution
from kyno.public_page import PageConfig, render_constitution, render_index
from kyno.wire.models import Principle


def view(constitution_key, mission="", principles=()):
    return PublicConstitution(
        constitution_key=constitution_key,
        mission=mission,
        principles=principles,
        version=1,
        last_changed_at=datetime(2026, 1, 1, tzinfo=UTC),
        history=None,
    )


def test_given_hostile_name_when_rendering_index_then_text_is_escaped_and_url_encoded():
    body = render_index([view("a<b> c", "Odd name")])
    assert "<b>" not in body
    assert "&lt;b&gt;" in body
    assert "a%3Cb%3E%20c" in body


def test_given_principles_without_mission_when_render_constitution_runs_then_key_is_page_title():
    body = render_constitution(view("support", principles=(Principle("Help customers"),)))
    assert re.search(r"<title>(.*?)</title>", body).group(1) == "support"


def test_given_html_in_title_fallback_when_render_constitution_runs_then_markup_is_escaped():
    body = render_constitution(view("a<b>"))
    assert re.search(r"<title>(.*?)</title>", body).group(1) == "a&lt;b&gt;"


def test_given_name_and_key_placeholders_when_render_constitution_then_only_key_is_filled(
    tmp_path,
):
    template = tmp_path / "constitution.html"
    template.write_text("<h1>$constitution_key</h1><p>$name / ${name}</p>")

    body = render_constitution(view("support"), PageConfig(constitution_template=str(template)))

    assert body == "<h1>support</h1><p>$name / ${name}</p>"
