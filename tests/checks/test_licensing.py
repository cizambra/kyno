"""Licensing follows package boundaries, not individual source files."""

from tests.paths import REPO_ROOT

SRC = REPO_ROOT / "src" / "kyno"
MIT_DIRS = ("sdk", "adapters", "conformance", "wire", "config")
HEADER = "# SPDX-License-Identifier: MIT"


def test_given_the_mit_subtrees_when_reading_their_licenses_then_each_is_mit():
    missing = []
    for mit_dir in MIT_DIRS:
        path = SRC / mit_dir / "LICENSE"
        if not path.exists() or not path.read_text().startswith("MIT License"):
            missing.append(str(path.relative_to(REPO_ROOT)))
    assert not missing, "\n" + "\n".join(missing)


def test_given_python_files_when_scanning_headers_then_none_claims_its_own_license():
    headers = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.read_text().split("\n", 1)[0] == HEADER:
            headers.append(str(path.relative_to(REPO_ROOT)))
    assert not headers, f"licenses belong at package boundaries, not source files: {headers}"
