"""The MIT integration surface must not depend on Elastic/Core modules."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.paths import REPO_ROOT

SRC = REPO_ROOT / "src" / "kyno"
MIT_SUBTREES = {"sdk", "adapters", "conformance", "wire", "config"}
MIT_MODULES = MIT_SUBTREES | {"client_errors"}


def _kyno_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return [name for name in imports if name == "kyno" or name.startswith("kyno.")]


def test_given_mit_subtrees_when_scanning_imports_then_they_only_depend_on_mit_subtrees():
    offenders = []
    for subtree in MIT_SUBTREES:
        for path in sorted((SRC / subtree).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for imported in _kyno_imports(path):
                parts = imported.split(".")
                if len(parts) == 1 or parts[1] not in MIT_MODULES:
                    offenders.append(f"{path.relative_to(SRC.parent.parent)} imports {imported}")
    assert not offenders, "\n" + "\n".join(offenders)


def test_given_the_mit_config_when_imported_then_it_does_not_load_core_modules():
    code = (
        "import sys, kyno.config; "
        "assert not {'kyno.errors', 'kyno.models', 'kyno.service'} & set(sys.modules), sys.modules"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
