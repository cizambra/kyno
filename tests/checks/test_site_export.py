"""The committed site is a genuine export: its constitution page must match
constitution.yaml. Marketing pages use local assets except for Umami analytics."""

import html
import json
import re
import runpy
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

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


@pytest.mark.parametrize(
    "page", ["index.html", "how-it-works/index.html", "faq/index.html", "walkthrough/index.html"]
)
def test_given_a_marketing_page_when_scanning_requests_then_only_analytics_is_external(page):
    html = (SITE / page).read_text()
    # Anchors may leave the site; assets (scripts, styles, images) may not,
    # with one deliberate exception: the cookieless Umami analytics script.
    # A data: URI is inline content, not a request, wherever it points inside.
    allowed = {"https://cloud.umami.is/script.js"}
    for tag in re.findall(r"<(?:script|link|img)\b[^>]*>", html):
        # A canonical link identifies the page; it does not load an asset.
        if tag.startswith("<link") and re.search(r'\brel="canonical"', tag):
            continue
        for url in re.findall(r"(?:src|href)=\"([^\"]*)\"", tag):
            if url in allowed:
                continue
            assert not url.startswith(("http://", "https://", "//")), tag


class _PageLinks(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids = []
        self.links = []
        self.canonical = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        for name in ("href", "src"):
            if name in attrs:
                self.links.append(attrs[name])
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs["href"]


def test_given_public_pages_when_following_local_links_then_files_and_fragments_exist():
    origin = "https://cizambra.github.io/kyno/"
    pages = {path: _PageLinks(path.read_text()) for path in SITE.rglob("*.html")}
    for path, page in pages.items():
        assert len(page.ids) == len(set(page.ids)), path
        page_url = urljoin(origin, path.relative_to(SITE).as_posix())
        for link in page.links:
            target_url = urlsplit(urljoin(page_url, link))
            if target_url.netloc != "cizambra.github.io":
                continue
            assert target_url.path.startswith("/kyno/"), (path, link)
            target = SITE / unquote(target_url.path.removeprefix("/kyno/"))
            if target.is_dir():
                target /= "index.html"
            assert target.is_file(), (path, link)
            if target_url.fragment:
                assert unquote(target_url.fragment) in pages[target].ids, (path, link)


def test_given_the_sitemap_when_reading_public_pages_then_canonical_urls_match():
    urls = [node.text for node in ET.parse(SITE / "sitemap.xml").findall(".//{*}loc")]
    assert len(urls) == len(set(urls))
    pages = [_PageLinks(path.read_text()) for path in SITE.rglob("*.html")]
    assert set(urls) == {page.canonical for page in pages}


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
