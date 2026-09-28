import re
from datetime import UTC, datetime

import pytest

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


@pytest.mark.parametrize("placeholder", ["$constitution_key", "${constitution_key}"])
def test_given_key_placeholder_when_render_constitution_runs_then_escaped_key_is_inserted(
    tmp_path,
    placeholder,
):
    template = tmp_path / "constitution.html"
    template.write_text(f"<h1>{placeholder}</h1>")

    body = render_constitution(view("a<b>"), PageConfig(constitution_template=str(template)))

    assert body == "<h1>a&lt;b&gt;</h1>"
