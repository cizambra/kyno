"""The default pages are template files the operator can copy and edit, and
the built-in rendering path goes through the same substitution an operator's
template does. One mechanism, so the defaults cannot drift from what a copy
of them can express."""

import pytest

from kyno.public_page import (
    PACKAGED_TEMPLATES,
    PageConfig,
    PageTheme,
    packaged_template,
    render_constitution,
    render_index,
)
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.fixture
def plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def published(plane, **kwargs):
    plane.set_direction(change_note="init", **kwargs)
    plane.publish()
    return plane.public_constitution()


RICH = dict(
    mission="Ship lending people trust",
    declaration="## Why\n\nBecause it is somebody's worst month.",
    principles=({"title": "Say the hard number first", "description": "Before the story."},),
)


# --- the defaults are files ------------------------------------------------


def test_the_default_pages_ship_as_templates_beside_the_stylesheet():
    assert PACKAGED_TEMPLATES == ("constitution.html", "index.html", "page.css")
    for name in PACKAGED_TEMPLATES:
        assert packaged_template(name).strip(), name


def test_the_packaged_constitution_template_uses_the_placeholders_it_documents():
    text = packaged_template("constitution.html")
    for placeholder in ("$stylesheet", "$name", "$mission", "$declaration", "$principles"):
        assert placeholder in text, placeholder


def test_a_packaged_template_that_is_missing_is_a_broken_install_and_raises():
    # Unlike an operator's template, which degrades to the built-in page:
    # there is nothing left to degrade to, and silence would hide the break.
    with pytest.raises(FileNotFoundError):
        packaged_template("no-such-page.html")


def test_the_built_in_page_is_exactly_what_the_packaged_template_renders(plane, tmp_path):
    # The dogfooding proof: point the operator-template path at a copy of the
    # packaged file and the output is byte-for-byte the built-in page.
    view = published(plane, **RICH)
    copy = tmp_path / "constitution.html"
    copy.write_text(packaged_template("constitution.html"), encoding="utf-8")

    assert render_constitution(view, PageConfig(constitution_template=str(copy))) == (
        render_constitution(view)
    )


def test_the_built_in_index_is_exactly_what_the_packaged_template_renders(plane, tmp_path):
    plane.set_direction(mission="Product mission", change_note="init", constitution="product")
    plane.publish(constitution="product")
    views = plane.published_constitutions()
    copy = tmp_path / "index.html"
    copy.write_text(packaged_template("index.html"), encoding="utf-8")

    assert render_index(views, PageConfig(index_template=str(copy))) == render_index(views)


def test_a_copied_template_still_follows_the_theme_it_is_rendered_with(plane, tmp_path):
    copy = tmp_path / "constitution.html"
    copy.write_text(packaged_template("constitution.html"), encoding="utf-8")
    config = PageConfig(theme=PageTheme(accent="#b4531f"), constitution_template=str(copy))

    assert "--accent: #b4531f" in render_constitution(published(plane, **RICH), config)


# --- $stylesheet -----------------------------------------------------------


def test_a_custom_template_can_inherit_the_house_stylesheet(plane, tmp_path):
    path = tmp_path / "mine.html"
    path.write_text("<html><head>$stylesheet</head><body>$mission</body></html>")

    page = render_constitution(
        published(plane, **RICH), PageConfig(constitution_template=str(path))
    )

    assert "<style>" in page and "</style>" in page
    assert "--accent: #6d6d66" in page  # the theme tokens
    assert ".claims li" in page  # the packaged rules
    assert "prefers-color-scheme: dark" in page


def test_a_custom_template_may_bring_its_own_styles_instead(plane, tmp_path):
    path = tmp_path / "mine.html"
    path.write_text("<html><head><style>body{color:red}</style></head><body>$mission</body></html>")

    page = render_constitution(
        published(plane, **RICH), PageConfig(constitution_template=str(path))
    )

    assert "body{color:red}" in page
    assert ".claims li" not in page


# --- placeholders are whole blocks, so substitution alone can omit them ----


def test_the_declaration_placeholder_is_the_whole_block_or_nothing(plane, tmp_path):
    path = tmp_path / "t.html"
    path.write_text("[$declaration]")

    with_one = render_constitution(
        published(plane, **RICH), PageConfig(constitution_template=str(path))
    )
    assert '[<div class="declaration">' in with_one

    bare = SqlConstitutionStore(url="sqlite://")
    bare.create_all()
    other = ControlPlane(bare)
    assert (
        render_constitution(
            published(other, mission="M"), PageConfig(constitution_template=str(path))
        )
        == "[]"
    )


def test_the_principles_placeholder_carries_its_own_heading_or_nothing(plane, tmp_path):
    path = tmp_path / "t.html"
    path.write_text("[$principles]")

    with_some = render_constitution(
        published(plane, **RICH), PageConfig(constitution_template=str(path))
    )
    assert "Operating principles" in with_some
    assert '<ol class="claims">' in with_some

    bare = SqlConstitutionStore(url="sqlite://")
    bare.create_all()
    other = ControlPlane(bare)
    assert (
        render_constitution(
            published(other, mission="M"), PageConfig(constitution_template=str(path))
        )
        == "[]"
    )


def test_the_index_items_placeholder_carries_the_empty_state_itself(plane, tmp_path):
    # A pure substitution cannot branch, so "nothing is published" has to be
    # part of the value rather than a conditional in the renderer.
    path = tmp_path / "t.html"
    path.write_text("[$items]")

    assert "Nothing is published here yet" in render_index((), PageConfig(index_template=str(path)))
