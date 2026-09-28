"""The committed site is a genuine export: its constitution page must match
constitution.yaml, and the landing page must load nothing from the network."""

import html
import json
import re
import runpy
import sys

import pytest

from tests.paths import REPO_ROOT

ROOT = REPO_ROOT
SITE = ROOT / "site"

pytestmark = pytest.mark.skipif(not SITE.exists(), reason="site/ not present")


def test_given_the_committed_constitution_when_exporting_the_site_then_the_page_carries_it():
    from kyno.authoring import read_constitution_file

    source = read_constitution_file(ROOT / "constitution.yaml")
    exported = (SITE / "constitution" / "index.html").read_text()
    assert html.escape(source.mission) in exported
    for principle in source.principles:
        assert html.escape(principle.title) in exported


def test_given_the_landing_page_when_scanning_its_requests_then_nothing_is_external():
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


def test_given_the_landing_page_when_reading_the_install_step_then_it_uses_pypi_not_a_clone():
    html = (SITE / "index.html").read_text()
    assert "pip install kyno" in html
    assert "pip install ." not in html


def test_given_repo_constitution_when_build_script_runs_then_html_and_json_share_its_key(
    tmp_path, monkeypatch
):
    (tmp_path / "site-src").mkdir()
    (tmp_path / "site" / "constitution").mkdir(parents=True)
    (tmp_path / "constitution.yaml").write_text((ROOT / "constitution.yaml").read_text())
    (tmp_path / "site-src" / "constitution.html").write_text(
        (ROOT / "site-src" / "constitution.html").read_text()
    )
    script = runpy.run_path(str(ROOT / "site-src" / "build-constitution.py"))
    monkeypatch.setitem(script["main"].__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["build-constitution", "--version", "6", "--updated", "2026-08-24"]
    )

    script["main"]()

    output = tmp_path / "site" / "constitution"
    payload = json.loads((output / "constitution.json").read_text())
    assert payload["constitution_key"] == "main"
    assert payload["version"] == 6
    assert html.escape(payload["mission"]) in (output / "index.html").read_text()
    assert "constitution/main" in (output / "index.html").read_text()
