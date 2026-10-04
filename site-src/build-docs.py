"""Render maintained documentation into the public website."""

import html
import re
from pathlib import Path
from posixpath import normpath
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "README": (
        "",
        "Kyno documentation — AI agent setup and integrations",
        "Set up Kyno and integrate shared, versioned mission and principles "
        "with Python, CrewAI and LangGraph.",
    ),
    "quick-start": (
        "quick-start/",
        "Kyno quick start — versioned direction through MCP",
        "Install Kyno, publish your first mission and principles, and read versioned direction "
        "through the Python SDK over MCP.",
    ),
    "crewai": (
        "crewai/",
        "Kyno + CrewAI — shared mission and principles for AI agents",
        "Integrate Kyno with CrewAI to refresh versioned mission and principles "
        "before model calls. "
        "Includes setup, failure policies and optional recording.",
    ),
    "langgraph": (
        "langgraph/",
        "Kyno + LangGraph — versioned direction in agent workflows",
        "Integrate Kyno with LangGraph using KynoState, pull_before and direction_node. "
        "Supply current mission and principles at graph decision boundaries.",
    ),
}


def source_for(name):
    if name != "quick-start":
        return (ROOT / "docs" / f"{name}.md").read_text()
    readme = (ROOT / "README.md").read_text()
    start = readme.split("## Quick start\n", 1)[1].split("## Use it from an agent framework", 1)[0]
    limits = readme.split("## Limits\n", 1)[1].split("## Self-hosting", 1)[0]
    return (
        "# Kyno quick start\n\nPython 3.11 or later is required. These commands create a "
        "local Kyno workspace and an HTTP server backed by SQLite.\n\n"
        + start
        + "\n## Failure behavior and limits\n"
        + limits
        + "\n## Connect your agents\n\n"
        "Continue with the [CrewAI guide](crewai.md) or [LangGraph guide](langgraph.md). "
        "[View the recorded demo](https://cizambra.github.io/kyno/demo/) to see "
        "direction change during a workflow.\n"
    )


def render(name):
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(source_for(name))
    headings = set()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            label = tokens[index + 1].content
            slug = re.sub(r"[^\w\s-]", "", label.lower())
            slug = re.sub(r"\s+", "-", slug)
            candidate = slug
            suffix = 1
            while candidate in headings:
                candidate = f"{slug}-{suffix}"
                suffix += 1
            headings.add(candidate)
            token.attrSet("id", candidate)
        for child in token.children or []:
            if child.type != "link_open":
                continue
            href = child.attrGet("href")
            parsed = urlsplit(href)
            if parsed.scheme or href.startswith("#"):
                continue
            stem = Path(parsed.path).stem
            # Unpublished guides retain their original GitHub paths and anchors.
            if stem in PAGES and not parsed.fragment and not parsed.path.startswith("../"):
                child.attrSet("href", "/kyno/docs/" + PAGES[stem][0])
            else:
                relative = (Path("docs") / parsed.path).as_posix()
                # Resolve repository-relative links without depending on local existence.
                child.attrSet(
                    "href",
                    "https://github.com/cizambra/kyno/blob/main/"
                    + normpath(relative)
                    + ("#" + parsed.fragment if parsed.fragment else ""),
                )
    return md.renderer.render(tokens, md.options, {})


def main():
    template = (ROOT / "site-src" / "docs.html").read_text()
    for name, (slug, title, description) in PAGES.items():
        page = template.replace("{{TITLE}}", html.escape(title))
        page = page.replace("{{DESCRIPTION}}", html.escape(description, quote=True))
        page = page.replace("{{CANONICAL}}", "https://cizambra.github.io/kyno/docs/" + slug)
        page = page.replace("{{CONTENT}}", render(name))
        page = page.replace(
            "{{SOURCE}}", "README.md" if name == "quick-start" else f"docs/{name}.md"
        )
        target = ROOT / "site" / "docs" / slug / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page)


if __name__ == "__main__":
    main()
