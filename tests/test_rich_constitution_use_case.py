"""The whole path a rich constitution walks: an operator writes it in a
file, publishes it, an anonymous visitor reads the document -- and the crew
bound to it keeps being sent a small block, unless it asks for more.
"""

from starlette.testclient import TestClient
from typer.testing import CliRunner

from kyno.adapters.core.binder import DirectionBinder
from kyno.adapters.core.client import LocalDirectionSource
from kyno.cli import app as cli
from kyno.models import FULL
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.transports import build_http_app

runner = CliRunner()

CONSTITUTION = """
constitution: acme
mission: Ship a lending product people trust with their worst month
declaration: |
  # What we are for

  Lending is a promise about somebody's worst month.

  We would rather lose the deal than make a promise we cannot keep.
principles:
  - Say the hard number first
  - title: Refuse quietly
    description: |
      A refusal is a sentence, not a maze. If we cannot lend, say so on the
      first screen and say why.
note: the constitution as written
by: camilo
"""

HEADLINE = "Ship a lending product people trust with their worst month"
PARAGRAPH = "Lending is a promise about somebody's worst month."
DESCRIPTION = "A refusal is a sentence, not a maze."


def test_an_organization_writes_a_rich_constitution_publishes_it_and_binds_a_crew_to_it(
    tmp_path, monkeypatch
):
    db = tmp_path / "kyno.sqlite3"
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{db}")
    path = tmp_path / "constitution.yaml"
    path.write_text(CONSTITUTION)

    assert runner.invoke(cli, ["init-db"]).exit_code == 0
    assert runner.invoke(cli, ["set", "--file", str(path)]).exit_code == 0
    assert runner.invoke(cli, ["publish", "--constitution", "acme"]).exit_code == 0

    plane = ControlPlane(SqlConstitutionStore(url=f"sqlite:///{db}"))

    # The published page is the document, not a summary of it.
    with TestClient(build_http_app(plane, token="secret")) as visitor:
        page = visitor.get("/constitutions/acme")
        assert page.status_code == 200
        assert HEADLINE in page.text
        assert "<h1>What we are for</h1>" in page.text
        assert f"<p>{PARAGRAPH}</p>" in page.text
        assert "Say the hard number first" in page.text
        assert DESCRIPTION in page.text
        assert page.text.index(PARAGRAPH) < page.text.index("Say the hard number first")

        payload = visitor.get("/constitutions/acme.json").json()

    assert payload["declaration"].startswith("# What we are for")
    assert payload["principles"] == [
        {"title": "Say the hard number first", "description": ""},
        {
            "title": "Refuse quietly",
            "description": (
                "A refusal is a sentence, not a maze. If we cannot lend, say so on the\n"
                "first screen and say why."
            ),
        },
    ]

    # The crew bound to that same record is sent the handles, not the document.
    source = LocalDirectionSource(plane)
    compact = DirectionBinder(source).bind("acme").render()
    assert HEADLINE in compact
    assert "Say the hard number first" in compact and "Refuse quietly" in compact
    assert PARAGRAPH not in compact
    assert DESCRIPTION not in compact

    # Unless this binding would rather spend the tokens.
    full = DirectionBinder(source, context=FULL).bind("acme").render()
    assert PARAGRAPH in full and DESCRIPTION in full
