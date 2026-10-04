"""Public integration pages stay current with their maintained Markdown sources."""

import runpy

from tests.paths import REPO_ROOT


def test_given_maintained_guides_when_building_docs_then_committed_pages_match():
    script = runpy.run_path(str(REPO_ROOT / "site-src" / "build-docs.py"))
    paths = [
        REPO_ROOT / "site" / "docs" / page[0] / "index.html" for page in script["PAGES"].values()
    ]
    before = {path: path.read_bytes() for path in paths}

    script["main"]()

    for path in paths:
        assert path.read_bytes() == before[path], f"Regenerate documentation: {path}"


def test_given_published_and_repository_links_when_rendering_guides_then_targets_are_preserved():
    script = runpy.run_path(str(REPO_ROOT / "site-src" / "build-docs.py"))

    page = script["render"]("crewai")

    assert 'href="/kyno/docs/langgraph/"' in page
    assert (
        'href="https://github.com/cizambra/kyno/blob/main/docs/adapters.md#the-integration"' in page
    )
    assert 'href="#optional-recording"' in page
    assert 'id="optional-recording"' in page
