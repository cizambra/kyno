"""HTML for the public constitution pages.

The default pages ship as template files (`kyno/templates/`) and the
built-in rendering path fills them with the same substitution that fills a
template an operator supplies. One mechanism: the defaults cannot express
anything a copy of them could not, and `kyno page export` hands an operator
the real thing to edit.

Substitution is `string.Template` and nothing more -- placeholders, never a
language. See `_fill_template`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from importlib import resources
from pathlib import Path
from string import Template
from urllib.parse import quote

from markdown_it import MarkdownIt

from kyno.models import PublicConstitution

_log = logging.getLogger(__name__)

_DEFAULT_FONT = 'ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
_MONO_FONT = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace'

# Raw HTML off: this page serves anonymous visitors, and an organization's own
# text must never reach them as markup that runs. Images off too -- an
# external <img> would stop the page being one self-contained response.
# markdown-it refuses javascript: and friends in links itself.
_MARKDOWN = MarkdownIt("js-default", {"html": False}).disable("image")


@dataclass(frozen=True)
class PageTheme:
    """The handful of values the built-in page's look flows through."""

    accent: str = "#6d6d66"
    background: str = "#fbfbf9"
    text: str = "#1b1b19"
    muted: str = "#6d6d66"
    rule: str = "#e4e3de"
    font_family: str = _DEFAULT_FONT

    @property
    def uses_custom_colors(self) -> bool:
        default = PageTheme()
        mine = (self.accent, self.background, self.text, self.muted, self.rule)
        theirs = (default.accent, default.background, default.text, default.muted, default.rule)
        return mine != theirs


@dataclass(frozen=True)
class PageConfig:
    theme: PageTheme = field(default_factory=PageTheme)
    constitution_template: str | None = None
    index_template: str | None = None


_DEFAULT_CONFIG = PageConfig()


def _stylesheet(theme: PageTheme) -> str:
    root = (
        ":root {\n"
        f"  --accent: {theme.accent}; --bg: {theme.background}; --fg: {theme.text};\n"
        f"  --muted: {theme.muted}; --rule: {theme.rule};\n"
        f"  --font: {theme.font_family};\n"
        f"  --mono: {_MONO_FONT};\n"
        "}\n"
    )
    # Inverting a palette somebody chose would produce a page they never
    # approved, so the automatic dark swap only applies to our own colors.
    dark = (
        ""
        if theme.uses_custom_colors
        else (
            "@media (prefers-color-scheme: dark) {\n"
            "  :root { --bg: #131312; --fg: #ecebe6; --muted: #97968e;\n"
            "          --rule: #2b2b28; --accent: #97968e; }\n"
            "}\n"
        )
    )
    return root + dark + _RULES


# What ships as the default pages, and what `kyno page export` copies.
PACKAGED_TEMPLATES = ("constitution.html", "index.html", "page.css")


def packaged_template(name: str) -> str:
    """A default page as it ships. Unlike an operator's template, an
    unreadable one is a broken install rather than a bad configuration, so it
    raises: there is nothing left to fall back to, and silence would hide it."""
    return (resources.files("kyno") / "templates" / name).read_text(encoding="utf-8")


# Authored as CSS so editors treat it as CSS; still served inline, because a
# published constitution should render on a locked-down network and survive
# being archived as a single saved file.
_RULES = packaged_template("page.css")


def _style_block(theme: PageTheme) -> str:
    return f"<style>{_stylesheet(theme)}</style>"


def _date(value) -> str:
    return value.strftime("%Y-%m-%d")


def _path(name: str) -> str:
    return f"/constitutions/{quote(name, safe='')}"


def _substitute(text: str, values: dict[str, str]) -> str:
    """Every value is already escaped or already rendered, so no template --
    ours or an operator's -- can un-escape the text it displays."""
    return Template(text).safe_substitute(values)


def _fill_template(path: str, values: dict[str, str]) -> str | None:
    """Fill an operator's template. Returns None when the file cannot be used,
    so the caller falls back to the packaged page: a broken template must never
    take the public page down. Read per request, so a fix needs no restart."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        _log.warning("template %s could not be read (%s); serving the built-in page", path, exc)
        return None
    return _substitute(text, values)


def _render(packaged: str, operator: str | None, values: dict[str, str]) -> str:
    if operator:
        filled = _fill_template(operator, values)
        if filled is not None:
            return filled
    return _substitute(packaged_template(packaged), values)


def _headline(view: PublicConstitution) -> str:
    # A constitution may carry principles and no mission; a blank headline
    # would read as a broken page rather than a sparse one.
    return escape(view.mission) if view.mission.strip() else escape(view.name)


@lru_cache(maxsize=64)
def _declaration_html(text: str) -> str:
    """The declaration is the one field that is a document rather than a line,
    so it is rendered as markdown. Everything else on this page stays escaped
    plain text -- markdown is the long-form document's privilege. Cached by
    text: versions are immutable and CommonMark on an adversarial document is
    slow, so each declaration is rendered once, not once per anonymous GET."""
    return _MARKDOWN.render(text).strip() if text.strip() else ""


def _declaration_block(view: PublicConstitution) -> str:
    html = _declaration_html(view.declaration)
    return f'<div class="declaration">\n{html}\n</div>' if html else ""


def _principles_section(view: PublicConstitution) -> str:
    # A whole block, empty when there are none: substitution cannot branch, so
    # anything the built-in page omits conditionally has to omit itself.
    if not view.principles:
        return ""
    return f'<h2>Operating principles</h2>\n<ol class="claims">\n{_principle_items(view)}\n</ol>'


def _principle_items(view: PublicConstitution) -> str:
    items = []
    for principle in view.principles:
        lines = [f'<p class="claim-title">{escape(principle.title)}</p>']
        if principle.description:
            lines.append(f'<p class="claim-note">{escape(principle.description)}</p>')
        body = "\n".join(lines)
        items.append(f'<li><div class="claim">{body}</div></li>')
    return "\n".join(items)


def _history_block(view: PublicConstitution) -> str:
    if view.history is None:
        return ""
    entries = "\n".join(
        f'<li><p class="stamp">v{entry.version} &middot; {_date(entry.changed_at)}</p>'
        f"<p>{escape(entry.change_note)}</p></li>"
        for entry in view.history
    )
    return f'<h2>History</h2>\n<ol class="log">\n{entries}\n</ol>'


def _index_block(views: Sequence[PublicConstitution]) -> str:
    if not views:
        # True and unremarkable, so it is a page rather than an error -- and it
        # travels inside the value, because substitution cannot branch.
        return "<p>Nothing is published here yet.</p>"
    return f'<ul class="directory">\n{_index_items(views)}\n</ul>'


def _index_items(views: Sequence[PublicConstitution]) -> str:
    items = []
    for view in views:
        # The index is a directory, so a long mission is trimmed to the line
        # that carries the claim.
        headline = view.mission.strip().splitlines()[0] if view.mission.strip() else view.name
        items.append(
            f'<li><h2><a href="{escape(_path(view.name))}">{escape(view.name)}</a></h2>'
            f"<p>{escape(headline)}</p>"
            f'<p class="stamp">v{view.version} &middot; {_date(view.last_changed_at)}</p></li>'
        )
    return "\n".join(items)


def render_constitution(view: PublicConstitution, config: PageConfig | None = None) -> str:
    config = config or _DEFAULT_CONFIG
    values = {
        "stylesheet": _style_block(config.theme),
        "name": escape(view.name),
        "mission": _headline(view),
        "declaration": _declaration_block(view),
        "principles": _principles_section(view),
        "version": str(view.version),
        "updated": _date(view.last_changed_at),
        "history": _history_block(view),
    }
    return _render("constitution.html", config.constitution_template, values)


def render_index(views: Sequence[PublicConstitution], config: PageConfig | None = None) -> str:
    config = config or _DEFAULT_CONFIG
    values = {
        "stylesheet": _style_block(config.theme),
        "items": _index_block(views),
        "count": str(len(views)),
    }
    return _render("index.html", config.index_template, values)


def render_not_found(config: PageConfig | None = None) -> str:
    """Built here rather than from a template: it has no placeholders and no
    operator override, so a file would be a page nobody can change."""
    config = config or _DEFAULT_CONFIG
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Not found</title>\n"
        f"{_style_block(config.theme)}\n"
        "</head>\n"
        "<body>\n"
        "<main><h1>Not found</h1></main>\n"
        "</body>\n"
        "</html>\n"
    )
