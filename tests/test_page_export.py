"""`kyno page export` — the copy-and-edit workflow: take the real default
pages, edit them, point Kyno at your copies."""

from pathlib import Path

from typer.testing import CliRunner

from kyno.cli import app
from kyno.public_page import PACKAGED_TEMPLATES, PageConfig, packaged_template
from kyno.public_page import render_constitution as render
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore

runner = CliRunner()


def test_given_a_target_directory_when_exporting_then_the_pages_and_stylesheet_are_written(
    tmp_path,
):
    result = runner.invoke(app, ["page", "export", str(tmp_path / "pages")])

    assert result.exit_code == 0, result.output
    written = tmp_path / "pages"
    for name in PACKAGED_TEMPLATES:
        assert (written / name).read_text(encoding="utf-8") == packaged_template(name)


def test_given_a_missing_directory_when_exporting_then_it_is_created(tmp_path):
    target = tmp_path / "a" / "b" / "pages"
    assert runner.invoke(app, ["page", "export", str(target)]).exit_code == 0
    assert (target / "constitution.html").exists()


def test_given_an_export_when_reading_its_output_then_it_names_the_page_keys_to_set(tmp_path):
    # The copy is useless until the workspace points at it, so the
    # command says how rather than leaving it to the README.
    target = tmp_path / "pages"
    result = runner.invoke(app, ["page", "export", str(target)])

    assert "constitution_template =" in result.output
    assert "index_template =" in result.output
    assert str((target / "constitution.html").resolve()) in result.output
    assert str((target / "index.html").resolve()) in result.output


def test_given_an_export_when_reading_its_output_then_it_says_what_the_stylesheet_is_for(tmp_path):
    # page.css is a starting point for the operator's own template; the
    # built-in $stylesheet keeps serving the packaged copy either way.
    result = runner.invoke(app, ["page", "export", str(tmp_path / "pages")])
    assert "page.css" in result.output
    assert "$stylesheet" in result.output


def test_given_existing_files_when_exporting_then_it_refuses_to_overwrite_and_writes_nothing(
    tmp_path,
):
    target = tmp_path / "pages"
    target.mkdir()
    mine = target / "index.html"
    mine.write_text("mine, hand-edited")

    result = runner.invoke(app, ["page", "export", str(target)])

    assert result.exit_code == 1
    assert "index.html" in result.output
    assert mine.read_text() == "mine, hand-edited"
    # All or nothing: a half-written export would leave the operator guessing
    # which files are theirs.
    assert not (target / "constitution.html").exists()
    assert not (target / "page.css").exists()


def test_given_a_dangling_symlink_when_exporting_then_it_is_refused_not_written_through(tmp_path):
    # A link to a missing file passes an exists() check, but writing through
    # it would plant the export wherever the link points.
    target = tmp_path / "pages"
    target.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (target / "index.html").symlink_to(tmp_path / "elsewhere" / "planted.html")

    result = runner.invoke(app, ["page", "export", str(target)])

    assert result.exit_code == 1
    assert "index.html" in result.output
    assert not (tmp_path / "elsewhere" / "planted.html").exists()


def test_given_a_file_appearing_mid_write_when_exporting_then_it_stops_and_removes_nothing(
    tmp_path,
):
    # The dangling symlink is exactly the shape of the check-then-write race:
    # nothing there at the check, refused at the write. Files exported before
    # the refusal stay put -- deleting them could delete an operator's work.
    target = tmp_path / "pages"
    target.mkdir()
    (target / "index.html").symlink_to(tmp_path / "nowhere")

    result = runner.invoke(app, ["page", "export", str(target)])

    assert result.exit_code == 1
    written = target / "constitution.html"
    assert written.read_text(encoding="utf-8") == packaged_template("constitution.html")
    assert not (target / "page.css").exists()


def test_given_an_exported_template_when_rendering_then_it_matches_the_page_it_was_copied_from(
    tmp_path,
):
    # The whole point of the workflow: what you export is what is running.
    target = tmp_path / "pages"
    assert runner.invoke(app, ["page", "export", str(target)]).exit_code == 0

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    plane = ControlPlane(store)
    plane.set_direction(mission="Ship trust", declaration="## Why\n\nBecause.", change_note="init")
    plane.publish()
    view = plane.public_constitution()

    exported = render(view, PageConfig(constitution_template=str(target / "constitution.html")))
    assert exported == render(view)


def test_given_an_edited_export_when_serving_then_the_edit_is_what_gets_served(tmp_path):
    target = tmp_path / "pages"
    runner.invoke(app, ["page", "export", str(target)])
    page = target / "constitution.html"
    page.write_text(page.read_text().replace("<main>", '<main class="ours">'))

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    plane = ControlPlane(store)
    plane.set_direction(mission="Ship trust", change_note="init")
    plane.publish()

    served = render(plane.public_constitution(), PageConfig(constitution_template=str(page)))
    assert '<main class="ours">' in served
    assert "Ship trust" in served


def test_given_the_built_wheel_when_inspecting_then_it_ships_the_templates_and_the_stylesheet(
    tmp_path,
):
    # importlib.resources reads them from the source tree in a dev checkout,
    # so only a real build proves an installed copy has them too.
    import zipfile

    build = __import__("pytest").importorskip("build")
    __import__("pytest").importorskip("hatchling")

    root = Path(__file__).parent.parent
    builder = build.ProjectBuilder(str(root))
    wheel = builder.build("wheel", str(tmp_path), {})

    members = set(zipfile.ZipFile(wheel).namelist())
    for name in PACKAGED_TEMPLATES:
        assert f"kyno/templates/{name}" in members, name

    # The migration scripts ship the same way: `kyno upgrade-db` must work
    # from an installed wheel, with no repo checkout around.
    assert "kyno/migrations/env.py" in members
    assert "kyno/migrations/script.py.mako" in members
    versions = {
        m
        for m in members
        if m.startswith("kyno/migrations/versions/")
        and m.endswith(".py")
        and not m.endswith("__init__.py")
    }
    assert len(versions) >= 3, versions
