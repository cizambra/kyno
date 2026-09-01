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
from tests.workspaces import cli_workspace

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
    cli_workspace(monkeypatch, tmp_path, path)
    assert runner.invoke(app, ["init-db"]).exit_code == 0
    return path


def plane(db):
    return ControlPlane(SqlConstitutionStore(url=f"sqlite:///{db}"))


def write(tmp_path, text, name="constitution.yaml"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# --- reading the file ------------------------------------------------------


def test_given_a_full_file_when_reading_then_every_field_a_constitution_has_is_carried(tmp_path):
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


def test_given_a_block_of_prose_when_reading_then_its_paragraphs_are_kept(tmp_path):
    # The reason the file exists: this is unwritable as a flag.
    declaration = read_constitution_file(write(tmp_path, FULL_FILE)).declaration
    assert declaration.startswith("# What we are for")
    assert "\n\n" in declaration
    assert declaration.endswith("we cannot keep.")


def test_given_an_omitted_field_when_reading_then_it_reads_as_carry_it_forward(tmp_path):
    read = read_constitution_file(write(tmp_path, "mission: M\n"))
    assert read.declaration is None and read.principles is None
    assert read.constitution is None


def test_given_unknown_keys_when_reading_a_file_then_they_are_the_operators_own(tmp_path):
    # One file can serve other tools too; note and by look like kyno
    # metadata but are not kyno fields, so they read as custom keys.
    body = "mission: M\nnote: n\nby: camilo\nteam: lending\n"
    read = read_constitution_file(write(tmp_path, body))
    assert read.mission == "M"


def test_given_an_empty_declaration_when_reading_then_it_is_a_present_value_that_clears(tmp_path):
    read = read_constitution_file(write(tmp_path, 'mission: M\ndeclaration: ""\n'))
    assert read.declaration == ""


def test_given_a_key_with_no_value_when_reading_then_it_reads_as_omitted_not_empty(tmp_path):
    # Deliberate: "declaration:" with nothing after it is far more often a
    # half-written file than a deletion, and clearing is spelled "".
    read = read_constitution_file(write(tmp_path, "mission: M\ndeclaration:\n"))
    assert read.declaration is None


def test_given_a_json_file_when_reading_then_it_is_read_as_valid_yaml(tmp_path):
    body = json.dumps({"mission": "M", "principles": ["p1"]})
    read = read_constitution_file(write(tmp_path, body, "constitution.json"))
    assert read.mission == "M" and read.principles == (Principle("p1"),)


def test_given_a_misspelled_field_when_reading_a_file_then_it_counts_as_custom(tmp_path):
    # "principals" is not refused; `kyno check` is where a typo shows up,
    # reported as a custom field beside the kyno fields the file misses.
    read = read_constitution_file(write(tmp_path, "mission: M\nprincipals:\n  - p1\n"))
    assert read.principles is None


def test_given_a_mixed_file_when_checking_then_fields_sort_into_kyno_and_custom(tmp_path):
    from kyno.authoring import check_constitution_file

    report = check_constitution_file(write(tmp_path, "mission: M\nprincipals:\n  - p1\nnote: n\n"))
    assert report.present == ("mission",)
    assert report.missing == ("constitution", "declaration", "principles")
    assert report.custom == ("note", "principals")


def test_given_a_file_that_is_not_a_mapping_when_reading_then_it_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="mapping"):
        read_constitution_file(write(tmp_path, "- just\n- a list\n"))


def test_given_a_file_that_does_not_parse_when_reading_then_it_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="could not be read"):
        read_constitution_file(write(tmp_path, "mission: [unclosed\n"))


def test_given_a_file_that_is_not_there_when_reading_then_it_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="could not be read"):
        read_constitution_file(str(tmp_path / "nowhere.yaml"))


def test_given_a_non_text_value_in_a_text_field_when_reading_then_it_is_refused(tmp_path):
    with pytest.raises(AuthoringError, match="mission"):
        read_constitution_file(write(tmp_path, "mission:\n  a: map\n"))


def test_given_principles_that_are_not_a_list_when_reading_then_they_are_refused(tmp_path):
    with pytest.raises(AuthoringError, match="principles"):
        read_constitution_file(write(tmp_path, "principles: just one\n"))


# --- through the CLI -------------------------------------------------------


def test_given_a_full_file_when_running_set_then_the_store_carries_its_content(db, tmp_path):
    result = runner.invoke(
        app,
        [
            "set",
            write(tmp_path, FULL_FILE),
            "--note",
            "the constitution as written",
            "--by",
            "camilo",
        ],
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


def test_given_a_named_file_when_applying_then_the_name_in_the_file_routes_it(db, tmp_path):
    path = write(tmp_path, FULL_FILE)
    result = runner.invoke(app, ["set", path, "--note", "the acme edit", "--by", "ops"])
    assert result.exit_code == 0, result.output

    head = plane(db).current("acme")
    assert head.change_note == "the acme edit" and head.created_by == "ops"
    assert plane(db).current("default").version == 0


@pytest.mark.parametrize("flag", ["--mission", "--declaration", "--principle", "--constitution"])
def test_given_a_content_or_name_flag_when_running_set_then_it_is_rejected_as_unknown(
    db, tmp_path, flag
):
    # The file is the only source of content, the name included. These flags
    # deliberately don't exist, and the CLI reports them as unknown.
    result = runner.invoke(app, ["set", write(tmp_path, FULL_FILE), flag, "X"])
    assert result.exit_code != 0
    assert "no such option" in plain(result).lower()


def test_given_no_note_when_running_set_then_it_is_refused(db, tmp_path):
    path = write(tmp_path, "mission: M\n")
    result = runner.invoke(app, ["set", path])
    assert result.exit_code != 0
    assert "note" in plain(result).lower()


def test_given_a_missing_file_when_running_set_then_the_error_is_clean(db, tmp_path):
    result = runner.invoke(app, ["set", str(tmp_path / "nowhere.yaml"), "--note", "n"])
    assert result.exit_code == 1
    assert "error:" in plain(result).lower()
    assert "Traceback" not in result.output


def test_given_a_second_file_when_applying_then_a_version_appends_and_omissions_carry(db, tmp_path):
    runner.invoke(app, ["set", write(tmp_path, FULL_FILE), "--note", "init"])
    second = write(tmp_path, "constitution: acme\nmission: A sharper mission\n", "2.yaml")

    assert runner.invoke(app, ["set", second, "--note", "sharpen"]).exit_code == 0

    head = plane(db).current("acme")
    assert head.version == 2
    assert head.mission == "A sharper mission"
    assert head.declaration.startswith("# What we are for")
    assert len(head.principles) == 2


def test_given_a_clearing_file_when_applying_then_the_declaration_clears(db, tmp_path):
    runner.invoke(app, ["set", write(tmp_path, FULL_FILE), "--note", "init"])
    clearing = write(tmp_path, 'constitution: acme\ndeclaration: ""\n', "3.yaml")

    assert runner.invoke(app, ["set", clearing, "--note", "retract"]).exit_code == 0
    assert plane(db).current("acme").declaration == ""


def test_given_no_file_argument_when_running_set_then_it_is_refused(db):
    """The file is the only source of content and it's a required
    argument, so `kyno set` with no file doesn't parse."""
    result = runner.invoke(app, ["set", "--note", "init"])
    assert result.exit_code != 0
    assert "file" in plain(result).lower()


def test_given_prose_content_when_rendered_to_yaml_then_reading_it_back_round_trips(tmp_path):
    from datetime import UTC, datetime

    from kyno.authoring import render_constitution_yaml
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
    text = render_constitution_yaml(version, "default")
    path.write_text(text, encoding="utf-8")
    assert "declaration: |" in text
    # A pulled file is content only; the edit metadata stays in the store.
    assert "note:" not in text and "by:" not in text

    got = read_constitution_file(str(path))
    assert got.constitution == "default"
    assert got.mission == version.mission
    assert got.declaration == version.declaration
    assert got.principles == version.principles
