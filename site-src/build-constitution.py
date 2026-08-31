"""Render Kyno's own constitution page.

Reads constitution.yaml at the repo root and writes
site/constitution/index.html through the same renderer and template
substitution any operator's page goes through -- the template just lives
here (site-src/constitution.html) instead of shipping inside kyno.

Usage:
    python site-src/build-constitution.py --version 6 --updated 2026-08-24

Version and date come from the store's ledger (kyno log), not from this
script: the page states them, it does not decide them.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from kyno.authoring import read_constitution_file
from kyno.models import PublicConstitution, normalize_principles
from kyno.public_page import PageConfig, render_constitution

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--updated", required=True, help="YYYY-MM-DD, from kyno log")
    args = parser.parse_args()

    fields = read_constitution_file(str(ROOT / "constitution.yaml"))
    view = PublicConstitution(
        name=fields.constitution or "default",
        mission=fields.mission or "",
        principles=normalize_principles(fields.principles) or (),
        version=args.version,
        last_changed_at=datetime.strptime(args.updated, "%Y-%m-%d").replace(tzinfo=UTC),
        history=None,
        declaration=fields.declaration or "",
    )
    config = PageConfig(constitution_template=str(ROOT / "site-src" / "constitution.html"))
    html = _to_template_markup(render_constitution(view, config))
    target = ROOT / "site" / "constitution" / "index.html"
    target.write_text(html, encoding="utf-8")
    print(f"wrote {target}")

    # The JSON export beside the page, from the same view, so the two can
    # never disagree. History stays absent: this site doesn't publish it.
    data = ROOT / "site" / "constitution" / "constitution.json"
    data.write_text(json.dumps(view.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {data}")


# The template's own markup for this constitution: labeled sections and
# numbered clauses. The values inside still come from kyno's renderer.
_SECTIONS = (
    ("what", "01 / DECLARATION"),
    ("why", "02 / WHY THIS PROJECT EXISTS"),
    ("accountability", "03 / ACCOUNTABILITY"),
)


def _to_template_markup(html: str) -> str:
    import re

    m = re.search(r'<div class="declaration">\n(.*?)\n</div>', html, re.S)
    if m:
        parts = [part for part in re.split(r"(?=<h2>)", m.group(1)) if part.strip()]
        sections = []
        for i, part in enumerate(parts):
            sid, label = _SECTIONS[i] if i < len(_SECTIONS) else (f"s-{i + 1}", f"0{i + 1} / SECTION")
            sections.append(
                f'<section id="{sid}">\n<div class="section-rule">{label}</div>\n{part.strip()}\n</section>'
            )
        html = html.replace(m.group(0), "\n".join(sections))

    html = html.replace(
        '<h2>Operating principles</h2>',
        '<section id="principles">\n<div class="principles-title">\n'
        '<h2>Operating principles</h2>\n<p>ORDER IS A PRIORITY HINT</p>\n</div>',
    )
    counter = 0

    def clause(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        title, note = match.group(1), match.group(2)
        body = f"<h3>{title}</h3>"
        if note is not None:
            body += f"\n    <p>{note}</p>"
        return (
            f'<li>\n  <span class="clause-no">{counter:02d}</span>\n'
            f'  <div class="clause-body">\n    {body}\n  </div>\n</li>'
        )

    html = re.sub(
        r'<li><div class="claim"><p class="claim-title">(.*?)</p>(?:\n<p class="claim-note">(.*?)</p>)?</div></li>',
        clause,
        html,
        flags=re.S,
    )
    html = html.replace('<ol class="claims">', '<ol class="clauses">')
    html = html.replace("</ol>", "</ol>\n</section>", 1) if 'id="principles"' in html else html
    return html



if __name__ == "__main__":
    main()
