"""Authoring a constitution from a file: the path that exists because long
prose through command-line flags is misery."""

import json
import re

import pytest
from typer.testing import CliRunner

from kyno.authoring import read_constitution_file
from kyno.cli import app
from kyno.errors import AuthoringError
from kyno.models import Principle
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

runner = CliRunner()


def plain(result):
    """The output as a person reads it — styling stripped, wrapping unwrapped.

    Assertions pin Kyno's message, not the CLI library's rendering; rich may
    split a flag name across style spans or wrap it across box lines.
    """
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    return " ".join(line.strip("│╭╰─╮╯ ") for line in text.splitlines())


FULL_FILE = """
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
"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "kyno.sqlite3"
    monkeypatch.setenv("KYNO_DATABASE_URL", f"sqlite:///{path}")
    assert runner.invoke(app, ["init-db"]).exit_code == 0
    return path


def plane(db):
    return ControlPlane(SqlConstitutionStore(url=f"sqlite:///{db}"))


def write(tmp_path, text, name="constitution.yaml"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# --- reading the file ------------------------------------------------------


def test_a_file_carries_every_field_a_constitution_has(tmp_path):
    read = read_constitution_file(write(tmp_path, FULL_FILE))

    assert read.constitution == "acme"
    assert read.mission == "Ship a lending product people trust with their worst month"
    assert read.principles == (
        Principle("Say the hard number first"),
        Principle(
            "Refuse quietly",
            "A refusal is a sentence, not a maze. If we cannot lend, say so on the\n"
            "first screen and say why.",
        ),
    )


def test_a_block_of_prose_keeps_its_paragraphs(tmp_path):
    # The reason the file exists: this is unwritable as a flag.
    declaration = read_constitution_file(write(tmp_path, FULL_FILE)).declaration
    assert declaration.startswith("# What we are for")
    assert "\n\n" in declaration
    assert declaration.endswith("we cannot keep.")


def test_an_omitted_field_reads_as_carry_it_forward(tmp_path):
    read = read_constitution_file(write(tmp_path, "mission: M\n"))
    assert read.declaration is None and read.principles is None
    assert read.constitution is None


def test_note_and_by_in_a_file_are_refused_and_the_flags_named(tmp_path):
    # The file is the constitution; who changed it and why belong to the
    # edit, so they travel as --note and --by.
    with pytest.raises(AuthoringError, match="--note, --by"):
        read_constitution_file(write(tmp_path, "mission: M\nnote: n\nby: camilo\n"))


def test_an_empty_declaration_is_a_present_value_that_clears_it(tmp_path):
    read = read_constitution_file(write(tmp_path, 'mission: M\ndeclaration: ""\n'))
    assert read.declaration == ""


def test_a_key_with_no_value_reads_as_omitted_rather_than_empty(tmp_path):
    # Deliberate: "declaration:" with nothing after it is far more often a
    # half-written file than a deletion, and clearing is spelled "".
    read = read_constitution_file(write(tmp_path, "mission: M\ndeclaration:\n"))
    assert read.declaration is None


def test_json_is_read_too_since_it_is_valid_yaml(tmp_path):
    body = json.dumps({"mission": "M", "principles": ["p1"]})
    read = read_constitution_file(write(tmp_path, body, "constitution.json"))
    assert read.mission == "M" and read.principles == (Principle("p1"),)


def test_a_misspelled_key_is_refused_and_named(tmp_path):
    # Silently ignoring "principals" would publish a constitution missing
    # everything the operator thought they had written.
    with pytest.raises(AuthoringError, match="principals"):
        read_constitution_file(write(tmp_path, "mission: M\nprincipals:\n  - p1\n"))


def test_a_file_that_is_not_a_mapping_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="mapping"):
        read_constitution_file(write(tmp_path, "- just\n- a list\n"))


def test_a_file_that_does_not_parse_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="could not be read"):
        read_constitution_file(write(tmp_path, "mission: [unclosed\n"))


def test_a_file_that_is_not_there_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="could not be read"):
        read_constitution_file(str(tmp_path / "nowhere.yaml"))


def test_a_field_that_should_be_text_is_refused_when_it_is_not(tmp_path):
    with pytest.raises(AuthoringError, match="mission"):
        read_constitution_file(write(tmp_path, "mission:\n  a: map\n"))


def test_principles_that_are_not_a_list_are_refused(tmp_path):
    with pytest.raises(AuthoringError, match="principles"):
        read_constitution_file(write(tmp_path, "principles: just one\n"))


# --- through the CLI -------------------------------------------------------


def test_setting_a_constitution_from_a_file(db, tmp_path):
    result = runner.invoke(
        app,
        ["set", "--file", write(tmp_path, FULL_FILE), "--note", "the constitution as written", "--by", "camilo"],
    )
    assert result.exit_code == 0, result.output

    head = plane(db).current("acme")
    assert head.version == 1
    assert head.mission.startswith("Ship a lending product")
    assert head.declaration.startswith("# What we are for")
    assert [p.title for p in head.principles] == ["Say the hard number first", "Refuse quietly"]
    assert head.principles[1].description.startswith("A refusal is a sentence")
    assert head.change_note == "the constitution as written"
    assert head.created_by == "camilo"


def test_the_edit_flags_route_and_describe_a_file_edit(db, tmp_path):
    path = write(tmp_path, FULL_FILE)
    result = runner.invoke(
        app,
        ["set", "--file", path, "--constitution", "eu", "--note", "the EU edit", "--by", "ops"],
    )
    assert result.exit_code == 0, result.output

    head = plane(db).current("eu")
    assert head.change_note == "the EU edit" and head.created_by == "ops"
    assert plane(db).current("acme").version == 0


@pytest.mark.parametrize(
    "flags",
    [
        ["--mission", "M"],
        ["--declaration", "D"],
        ["--principle", "p1"],
    ],
)
def test_a_file_and_a_field_flag_together_are_refused(db, tmp_path, flags):
    # Two sources for one field is a question nobody should have to answer.
    result = runner.invoke(app, ["set", "--file", write(tmp_path, FULL_FILE), *flags])
    assert result.exit_code != 0
    assert "--file" in plain(result)


def test_a_file_with_no_note_and_no_flag_is_refused(db, tmp_path):
    path = write(tmp_path, "mission: M\n")
    result = runner.invoke(app, ["set", "--file", path])
    assert result.exit_code != 0
    assert "note" in plain(result).lower()


def test_a_missing_file_reports_a_clean_error(db, tmp_path):
    result = runner.invoke(app, ["set", "--file", str(tmp_path / "nowhere.yaml")])
    assert result.exit_code == 1
    assert "error:" in plain(result).lower()
    assert "Traceback" not in result.output


def test_a_second_file_appends_a_version_and_carries_what_it_omits(db, tmp_path):
    runner.invoke(app, ["set", "--file", write(tmp_path, FULL_FILE), "--note", "init"])
    second = write(tmp_path, "constitution: acme\nmission: A sharper mission\n", "2.yaml")

    assert runner.invoke(app, ["set", "--file", second, "--note", "sharpen"]).exit_code == 0

    head = plane(db).current("acme")
    assert head.version == 2
    assert head.mission == "A sharper mission"
    assert head.declaration.startswith("# What we are for")
    assert len(head.principles) == 2


def test_a_file_can_clear_the_declaration(db, tmp_path):
    runner.invoke(app, ["set", "--file", write(tmp_path, FULL_FILE), "--note", "init"])
    clearing = write(tmp_path, 'constitution: acme\ndeclaration: ""\n', "3.yaml")

    assert runner.invoke(app, ["set", "--file", clearing, "--note", "retract"]).exit_code == 0
    assert plane(db).current("acme").declaration == ""


def test_the_flags_still_work_on_their_own(db):
    result = runner.invoke(
        app,
        ["set", "--mission", "M1", "--declaration", "D1", "--principle", "p1", "--note", "init"],
    )
    assert result.exit_code == 0, result.output
    head = plane(db).current()
    assert head.mission == "M1" and head.declaration == "D1"
    assert [p.title for p in head.principles] == ["p1"]


def test_an_empty_field_flag_still_conflicts_with_a_file(db, tmp_path):
    # `--mission ""` is a real instruction (clear it), not an absent flag.
    result = runner.invoke(app, ["set", "--file", write(tmp_path, FULL_FILE), "--mission", ""])
    assert result.exit_code != 0
    assert "--mission" in plain(result)


def test_write_constitution_file_round_trips_prose(tmp_path):
    from datetime import UTC, datetime

    from kyno.authoring import write_constitution_file
    from kyno.models import ConstitutionVersion

    version = ConstitutionVersion(
        version=3,
        mission="Ship a lending product people trust",
        declaration="## What we are for\n\nLending is a promise.",
        principles=(
            Principle(title="Refuse clearly", description="We say no early.\nAnd in plain words."),
            Principle(title="Say the hard number first"),
        ),
        change_note="the reviewed edit",
        changed_mission=True,
        changed_principles=True,
        created_at=datetime.now(UTC),
        created_by=None,
    )
    path = tmp_path / "c.yaml"
    write_constitution_file(str(path), version, "default")
    text = path.read_text(encoding="utf-8")
    assert "declaration: |" in text
    # A pulled file is content only; the edit metadata stays in the store.
    assert "note:" not in text and "by:" not in text

    got = read_constitution_file(str(path))
    assert got.constitution == "default"
    assert got.mission == version.mission
    assert got.declaration == version.declaration
    assert got.principles == version.principles
