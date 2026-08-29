"""The adapter-building kit: the example files match the real implementation,
and the checker catches the mistakes the guide says it catches."""

import json
import pathlib

import pytest

from kyno.authoring import read_constitution_file
from kyno.conformance import SEPARATOR, check_log
from kyno.models import COMPACT, FULL
from kyno.sdk.cell import Direction
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

ROOT = pathlib.Path(__file__).parent.parent
CONFORMANCE = ROOT / "conformance"


@pytest.fixture()
def plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def expected(name: str) -> str:
    return (CONFORMANCE / "expected" / name).read_text()


def test_given_the_example_files_when_replayed_then_they_match_what_kyno_produces(plane):
    ch0 = plane.changes_since(0)
    assert json.loads(expected("response_before_any_direction.json")) == ch0.to_dict(COMPACT)
    assert expected("block_before_any_direction.txt") == (
        Direction.from_changes(ch0, "default", COMPACT).render() + "\n"
    )

    f1 = read_constitution_file(CONFORMANCE / "v1.yaml")
    plane.set_direction(
        mission=f1.mission,
        declaration=f1.declaration,
        principles=f1.principles,
        change_note="initial constitution",
    )
    ch1 = plane.changes_since(0)
    assert json.loads(expected("response_version1_compact.json")) == ch1.to_dict(COMPACT)
    assert json.loads(expected("response_version1_full.json")) == ch1.to_dict(FULL)
    assert expected("block_version1_compact.txt") == (
        Direction.from_changes(ch1, "default", COMPACT).render() + "\n"
    )
    assert expected("block_version1_full.txt") == (
        Direction.from_changes(ch1, "default", FULL).render() + "\n"
    )

    f2 = read_constitution_file(CONFORMANCE / "v2.yaml")
    plane.set_direction(
        mission=f2.mission,
        declaration=f2.declaration,
        principles=f2.principles,
        change_note="second reviewer required above $25,000",
    )
    ch2 = plane.changes_since(1)
    assert json.loads(expected("response_version2_after_knowing_1.json")) == ch2.to_dict(COMPACT)
    assert expected("block_version2_compact.txt") == (
        Direction.from_changes(ch2, "default", COMPACT).render() + "\n"
    )


def log_of(*blocks: str) -> str:
    return "".join(b + f"\n{SEPARATOR}\n" for b in blocks)


GOOD_V0 = expected("block_before_any_direction.txt").rstrip("\n")
GOOD_V1 = expected("block_version1_compact.txt").rstrip("\n")
GOOD_V2 = expected("block_version2_compact.txt").rstrip("\n")


def test_given_a_correct_log_when_checked_then_it_passes_and_reports_version_changes():
    # A full session: before any direction, a version arrives, a step where
    # nothing changed, then a change.
    report = check_log(log_of(GOOD_V0, GOOD_V1, GOOD_V1, GOOD_V2))
    assert report.ok
    assert report.versions == [0, 1, 1, 2]
    assert report.version_changes() == [(2, 0, 1), (4, 1, 2)]


def test_given_a_block_without_the_marker_when_checked_then_its_position_is_reported():
    report = check_log(log_of(GOOD_V1, "Mission: no marker here"))
    assert not report.ok
    assert "block 2" in report.problems[0]
    assert "marker" in report.problems[0]


def test_given_a_version_going_backwards_when_checked_then_it_is_reported():
    report = check_log(log_of(GOOD_V2, GOOD_V1))
    assert not report.ok
    assert "backwards" in report.problems[0]


def test_given_a_wrong_empty_state_body_when_checked_then_it_is_reported():
    bad = GOOD_V0.split("\n")[0] + "\nSomething else entirely."
    report = check_log(log_of(bad))
    assert not report.ok
    assert "version-0" in report.problems[0]


def test_given_an_empty_file_when_checked_then_it_says_how_to_write_the_log():
    report = check_log("")
    assert not report.ok
    assert SEPARATOR in report.problems[0]
