"""Every source file names its license, so a contributor who forgets gets
told here, with the exact line to paste, instead of a reviewer having to
notice."""

import pathlib

SRC = pathlib.Path(__file__).parent.parent / "src" / "kyno"
MIT_DIRS = ("sdk", "adapters", "conformance")


def expected_license(path: pathlib.Path) -> str:
    relative = path.relative_to(SRC)
    return "MIT" if relative.parts[0] in MIT_DIRS else "Elastic-2.0"


def test_every_source_file_starts_with_its_spdx_header():
    missing = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        wanted = f"# SPDX-License-Identifier: {expected_license(path)}"
        first_line = path.read_text().split("\n", 1)[0]
        if first_line != wanted:
            name = path.relative_to(SRC.parent.parent)
            missing.append(f"{name}: add this first line -> {wanted}")
    assert not missing, "\n" + "\n".join(missing)
