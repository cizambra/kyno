"""Files under the MIT subtrees carry their license with them, because they
are the files meant to be copied out of the repository. A contributor who
forgets the header gets told here, with the exact line to paste. Files
outside these subtrees need no header: the root LICENSE says everything
unlabeled is under the Elastic License 2.0."""

import pathlib

SRC = pathlib.Path(__file__).parent.parent / "src" / "kyno"
MIT_DIRS = ("sdk", "adapters", "conformance")
HEADER = "# SPDX-License-Identifier: MIT"


def test_given_the_mit_subtrees_when_scanning_headers_then_every_file_starts_with_mit():
    missing = []
    for mit_dir in MIT_DIRS:
        for path in sorted((SRC / mit_dir).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path.read_text().split("\n", 1)[0] != HEADER:
                name = path.relative_to(SRC.parent.parent)
                missing.append(f"{name}: add this first line -> {HEADER}")
    assert not missing, "\n" + "\n".join(missing)


def test_given_files_outside_the_mit_subtrees_when_scanning_headers_then_none_claims_mit():
    wrong = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts or path.relative_to(SRC).parts[0] in MIT_DIRS:
            continue
        if path.read_text().split("\n", 1)[0] == HEADER:
            wrong.append(str(path.relative_to(SRC.parent.parent)))
    assert not wrong, f"these files are not under an MIT subtree: {wrong}"
