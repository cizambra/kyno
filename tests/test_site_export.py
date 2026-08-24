"""The committed site is a genuine export: its constitution page must match
constitution.yaml, and the landing page must load nothing from the network."""

import html
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).parent.parent
SITE = ROOT / "site"

pytestmark = pytest.mark.skipif(not SITE.exists(), reason="site/ not present")


def test_the_exported_page_carries_the_committed_constitution():
    from kyno.authoring import read_constitution_file

    source = read_constitution_file(ROOT / "constitution.yaml")
    exported = (SITE / "constitution" / "index.html").read_text()
    assert html.escape(source.mission) in exported
    for principle in source.principles:
        assert html.escape(principle.title) in exported


def test_the_landing_page_requests_nothing_external():
    html = (SITE / "index.html").read_text()
    # Anchors may leave the site; assets (scripts, styles, images) may not,
    # with one deliberate exception: the cookieless Umami analytics script.
    # A data: URI is inline content, not a request, wherever it points inside.
    allowed = {"https://cloud.umami.is/script.js"}
    for tag in re.findall(r"<(?:script|link|img)\b[^>]*>", html):
        for url in re.findall(r"(?:src|href)=\"([^\"]*)\"", tag):
            if url in allowed:
                continue
            assert not url.startswith(("http://", "https://", "//")), tag


def test_the_landing_page_installs_from_pypi_not_a_clone():
    html = (SITE / "index.html").read_text()
    assert "pip install kyno" in html
    assert "pip install ." not in html
