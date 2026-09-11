"""The documented recovery recipe reapplies historical content without replacing version history."""

import json

import pytest
import yaml
from typer.testing import CliRunner

from kyno.cli import app
from tests.workspaces import cli_workspace

runner = CliRunner()


@pytest.mark.parametrize("constitution", ["default", "support"])
@pytest.mark.parametrize("empty_fields", ["none", "details", "mission"])
def test_given_an_earlier_version_when_reapplied_then_its_full_content_returns_as_a_new_version(
    tmp_path, monkeypatch, constitution, empty_fields
):
    cli_workspace(monkeypatch, tmp_path)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    good = {
        "constitution": constitution,
        "mission": "" if empty_fields == "mission" else "Help customers",
        "declaration": "" if empty_fields == "details" else "Explain the complete resolution.",
        "principles": (
            [] if empty_fields == "details" else [{"title": "Trust", "description": "Be honest."}]
        ),
    }
    authored = tmp_path / "direction.json"
    authored.write_text(json.dumps(good), encoding="utf-8")
    first = runner.invoke(app, ["apply", str(authored), "--note", "reviewed direction"])
    assert first.exit_code == 0, first.output
    authored.write_text(
        json.dumps(
            {
                "constitution": constitution,
                "mission": "Unreviewed objective",
                "declaration": "Unwanted declaration",
                "principles": ["Unwanted principle"],
            }
        ),
        encoding="utf-8",
    )
    second = runner.invoke(app, ["apply", str(authored), "--note", "incorrect change"])
    assert second.exit_code == 0, second.output
    exported = runner.invoke(app, ["export", "--constitution", constitution])
    assert exported.exit_code == 0, exported.output
    recovery = tmp_path / "recovery.yaml"

    historical = runner.invoke(app, ["get-version", "1", "--constitution", constitution, "--yaml"])

    assert historical.exit_code == 0, historical.output
    assert yaml.safe_load(historical.stdout) == good
    recovery.write_text(historical.stdout, encoding="utf-8")
    preview = runner.invoke(app, ["apply", str(recovery), "--dry-run"])
    assert preview.exit_code == 0, preview.output
    unchanged = runner.invoke(app, ["export", "--constitution", constitution])
    assert json.loads(unchanged.stdout) == json.loads(exported.stdout)
    applied = runner.invoke(app, ["apply", str(recovery), "--note", "restore reviewed v1"])
    assert applied.exit_code == 0, applied.output
    after = runner.invoke(app, ["export", "--constitution", constitution])
    assert after.exit_code == 0, after.output
    rows = json.loads(after.stdout)
    assert rows[:2] == json.loads(exported.stdout)
    assert [row["version"] for row in rows] == [1, 2, 3]
    assert rows[-1]["change_note"] == "restore reviewed v1"
    for field in ("mission", "declaration", "principles"):
        assert rows[-1][field] == good[field]
    current = runner.invoke(app, ["current", "--constitution", constitution])
    assert current.exit_code == 0, current.output
    assert json.loads(current.stdout)["version"] == 3
    if constitution != "default":
        other = runner.invoke(app, ["export", "--constitution", "default"])
        assert other.exit_code == 1
        assert "'default' has no versions" in other.output
