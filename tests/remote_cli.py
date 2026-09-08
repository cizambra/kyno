"""Shared helpers for the remote CLI test lanes."""

import pathlib
import re

from typer.testing import CliRunner

runner = CliRunner()


def plain(output):
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).split())


def write_file(dirpath, mission="M1", name="c.yaml", constitution="default"):
    path = pathlib.Path(dirpath) / name
    path.write_text(f"constitution: {constitution}\nmission: {mission}\n", encoding="utf-8")
    return str(path)
