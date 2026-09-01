"""The whole path an operator actually walks: set a direction, publish it,
have an anonymous visitor read the page, take it down again -- driven through
the real CLI and the real HTTP app against one database.
"""

from typer.testing import CliRunner

from kyno.cli import app as cli
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.transports import build_http_app
from tests.workspaces import cli_workspace

runner = CliRunner()


def apply_yaml(
    tmp_path,
    *,
    mission,
    principles=(),
    constitution="default",
    note=None,
    by=None,
    name="applied.yaml",
):
    """Write a constitution file and apply it: the only way content lands."""
    lines = []
    if constitution is not None:
        lines.append(f"constitution: {constitution}")
    lines.append(f"mission: {mission}")
    if principles:
        lines.append("principles:")
        lines.extend(f"  - {p}" for p in principles)
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args = ["set", str(path)]
    if note is not None:
        args += ["--note", note]
    if by is not None:
        args += ["--by", by]
    return runner.invoke(cli, args)


MISSION = "Ship a lending product people trust with their worst month"
PRINCIPLE = "Say the hard number before the soft story"
PRIVATE_NOTE = "dropped a principle because the enterprise deal needed it"


def test_given_two_constitutions_when_publishing_one_then_the_other_stays_private(
    tmp_path, monkeypatch
):
    from starlette.testclient import TestClient

    db = tmp_path / "kyno.sqlite3"
    cli_workspace(monkeypatch, tmp_path, db)
    assert runner.invoke(cli, ["db", "init"]).exit_code == 0

    apply_yaml(tmp_path, mission=MISSION, principles=[PRINCIPLE], note="initial")
    apply_yaml(tmp_path, mission=f"{MISSION}, everywhere", note=PRIVATE_NOTE)
    apply_yaml(tmp_path, mission="How we really decide", constitution="acme-internal", note="init")

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


def test_given_a_published_history_when_toggled_then_change_notes_show_and_hide(
    tmp_path, monkeypatch
):
    from starlette.testclient import TestClient

    db = tmp_path / "kyno.sqlite3"
    cli_workspace(monkeypatch, tmp_path, db)
    runner.invoke(cli, ["db", "init"])
    apply_yaml(tmp_path, mission=MISSION, note="initial")
    apply_yaml(tmp_path, mission=f"{MISSION}, everywhere", note=PRIVATE_NOTE)

    plane = ControlPlane(SqlConstitutionStore(url=f"sqlite:///{db}"))
    with TestClient(build_http_app(plane, token="secret")) as visitor:
        runner.invoke(cli, ["publish"])
        assert PRIVATE_NOTE not in visitor.get("/constitutions/default").text

        runner.invoke(cli, ["publish", "--with-history"])
        assert PRIVATE_NOTE in visitor.get("/constitutions/default").text

        runner.invoke(cli, ["publish"])
        assert PRIVATE_NOTE not in visitor.get("/constitutions/default").text
