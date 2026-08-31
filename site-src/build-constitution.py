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
    target = ROOT / "site" / "constitution" / "index.html"
    target.write_text(render_constitution(view, config), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
