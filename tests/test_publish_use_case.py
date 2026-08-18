"""The whole path an operator actually walks: set a direction, publish it,
have an anonymous visitor read the page, take it down again -- driven through
the real CLI and the real HTTP app against one database.
"""

from typer.testing import CliRunner

from kyno.cli import app as cli
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.transports import build_http_app

runner = CliRunner()

MISSION = "Ship a lending product people trust with their worst month"
PRINCIPLE = "Say the hard number before the soft story"
PRIVATE_NOTE = "dropped a principle because the enterprise deal needed it"


def test_an_organization_publishes_one_constitution_and_keeps_the_other_private(
    tmp_path, monkeypatch
):
    from starlette.testclient import TestClient

    db = tmp_path / "kyno.sqlite3"
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{db}")
    assert runner.invoke(cli, ["init-db"]).exit_code == 0

    runner.invoke(cli, ["set", "--mission", MISSION, "--principle", PRINCIPLE, "--note", "initial"])
    runner.invoke(cli, ["set", "--mission", f"{MISSION}, everywhere", "--note", PRIVATE_NOTE])
    runner.invoke(
        cli,
        [
            "set",
            "--constitution",
            "acme-internal",
            "--mission",
            "How we really decide",
            "--note",
            "init",
        ],
    )

    plane = ControlPlane(SqlConstitutionStore(url=f"sqlite:///{db}"))
    with TestClient(build_http_app(plane, token="secret")) as visitor:
        assert visitor.get("/constitutions/default").status_code == 404

        assert runner.invoke(cli, ["publish"]).exit_code == 0

        page = visitor.get("/constitutions/default")
        assert page.status_code == 200
        assert f"{MISSION}, everywhere" in page.text
        assert PRINCIPLE in page.text
        assert "v2" in page.text
        assert PRIVATE_NOTE not in page.text

        payload = visitor.get("/constitutions/default.json").json()
        assert payload["version"] == 2 and "history" not in payload

        index = visitor.get("/constitutions/").text
        assert "default" in index
        assert "acme-internal" not in index
        assert "How we really decide" not in index
        assert visitor.get("/constitutions/acme-internal").status_code == 404

        assert runner.invoke(cli, ["unpublish"]).exit_code == 0
        assert visitor.get("/constitutions/default").status_code == 404
        assert visitor.get("/constitutions/default.json").status_code == 404
        assert "default" not in visitor.get("/constitutions/").text


def test_opening_history_exposes_the_change_notes_and_closing_it_hides_them_again(
    tmp_path, monkeypatch
):
    from starlette.testclient import TestClient

    db = tmp_path / "kyno.sqlite3"
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{db}")
    runner.invoke(cli, ["init-db"])
    runner.invoke(cli, ["set", "--mission", MISSION, "--note", "initial"])
    runner.invoke(cli, ["set", "--mission", f"{MISSION}, everywhere", "--note", PRIVATE_NOTE])

    plane = ControlPlane(SqlConstitutionStore(url=f"sqlite:///{db}"))
    with TestClient(build_http_app(plane, token="secret")) as visitor:
        runner.invoke(cli, ["publish"])
        assert PRIVATE_NOTE not in visitor.get("/constitutions/default").text

        runner.invoke(cli, ["publish", "--with-history"])
        assert PRIVATE_NOTE in visitor.get("/constitutions/default").text

        runner.invoke(cli, ["publish"])
        assert PRIVATE_NOTE not in visitor.get("/constitutions/default").text
