"""The MIT integration surface must not depend on Elastic/Core modules."""

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from tests.paths import REPO_ROOT

SRC = REPO_ROOT / "src" / "kyno"
MIT_SUBTREES = {"sdk", "adapters", "conformance", "wire", "config"}
MIT_MODULES = MIT_SUBTREES


def _module_name(path: Path, source_root: Path) -> str:
    parts = list(path.relative_to(source_root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _kyno_imports(path: Path, source_root: Path = SRC) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports = []
    module = _module_name(path, source_root)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                imports.append(importlib.util.resolve_name("." * node.level + node.module, package))
            elif node.level:
                imports.extend(
                    importlib.util.resolve_name("." * node.level + alias.name, package)
                    for alias in node.names
                )
            elif node.module:
                imports.append(node.module)
    return [name for name in imports if name == "kyno" or name.startswith("kyno.")]


@pytest.mark.parametrize(
    "statement",
    ["from ..service import ControlPlane\n", "from .. import service\n"],
)
def test_given_a_relative_core_import_when_scanning_mit_code_then_kyno_service_is_returned(
    statement, tmp_path
):
    source_root = tmp_path / "src" / "kyno"
    path = source_root / "sdk" / "probe.py"
    path.parent.mkdir(parents=True)
    path.write_text(statement)

    assert _kyno_imports(path, source_root) == ["kyno.service"]


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


@pytest.mark.parametrize("package", sorted(f"kyno.{name}" for name in MIT_SUBTREES))
def test_given_an_mit_package_when_imported_then_it_does_not_load_core_modules(package):
    allowed = tuple(f"kyno.{name}" for name in MIT_SUBTREES)
    code = (
        f"import sys, {package}; "
        "loaded = {name for name in sys.modules if name.startswith('kyno.')}; "
        f"allowed = {allowed!r}; "
        "offenders = {name for name in loaded "
        "if not any(name == root or name.startswith(root + '.') for root in allowed)}; "
        "assert not offenders, offenders"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_given_sdk_transport_errors_when_importing_them_then_the_sdk_owns_the_module():
    errors = importlib.import_module("kyno.sdk.errors")

    assert errors.KynoUnavailableError.__module__ == "kyno.sdk.errors"
    assert errors.KynoRefusedError.__module__ == "kyno.sdk.errors"


def test_given_the_core_mcp_server_when_importing_the_resource_uri_then_wire_owns_it():
    imports = _kyno_imports(SRC / "mcp_server.py")

    assert "kyno.wire" in imports
    assert "kyno.sdk.client" not in imports
