import re
from datetime import UTC, datetime

from kyno.models import PublicConstitution
from kyno.public_page import render_constitution, render_index


def view(constitution_key, mission=""):
    return PublicConstitution(
        constitution_key=constitution_key,
        mission=mission,
        principles=(),
        version=1,
        last_changed_at=datetime(2026, 1, 1, tzinfo=UTC),
        history=None,
    )


def test_given_hostile_name_when_rendering_index_then_text_is_escaped_and_url_encoded():
    body = render_index([view("a<b> c", "Odd name")])
    assert "<b>" not in body
    assert "&lt;b&gt;" in body
    assert "a%3Cb%3E%20c" in body


def test_given_no_mission_when_rendering_constitution_then_escaped_name_is_title():
    body = render_constitution(view("a<b>"))
    assert re.search(r"<title>(.*?)</title>", body).group(1) == "a&lt;b&gt;"
