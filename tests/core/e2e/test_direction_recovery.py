"""The documented recovery recipe reapplies historical content without replacing version history."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kyno.cli import app
from tests.workspaces import cli_workspace

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "recovery.md"
runner = CliRunner()


def extract(history, version, constitution, output):
    code = GUIDE.read_text(encoding="utf-8").split("```python\n", 1)[1].split("```", 1)[0]
    return subprocess.run(
        [sys.executable, "-c", code, str(history), str(version), constitution, str(output)],
        capture_output=True,
        text=True,
        timeout=10,
    )


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
    history = tmp_path / "history.json"
    history.write_text(exported.stdout, encoding="utf-8")
    recovery = tmp_path / "recovery.json"

    extracted = extract(history, 1, constitution, recovery)

    assert extracted.returncode == 0, extracted.stderr
    assert json.loads(recovery.read_text()) == good
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


def test_given_a_missing_version_when_extracting_then_no_recovery_file_is_created(tmp_path):
    history = tmp_path / "history.json"
    history.write_text("[]", encoding="utf-8")
    output = tmp_path / "recovery.json"

    result = extract(history, 8, "support", output)

    assert result.returncode != 0
    assert "Expected exactly one version 8" in result.stderr
    assert not output.exists()


def test_given_an_existing_recovery_file_when_extracting_then_it_is_not_overwritten(tmp_path):
    history = tmp_path / "history.json"
    history.write_text(
        json.dumps([{"version": 1, "mission": "Help", "declaration": "", "principles": []}]),
        encoding="utf-8",
    )
    output = tmp_path / "recovery.json"
    output.write_text("reviewed file", encoding="utf-8")

    result = extract(history, 1, "support", output)

    assert result.returncode != 0
    assert output.read_text() == "reviewed file"
