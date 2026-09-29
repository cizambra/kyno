import json
import subprocess
import textwrap
import tomllib
import venv

import build

import kyno
from tests.paths import REPO_ROOT


def test_given_project_version_when_importing_kyno_then_package_version_matches():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    declared_version = project["version"]

    exposed_version = kyno.__version__

    assert exposed_version == declared_version


def test_given_built_wheel_when_installing_then_distribution_and_import_versions_match_project(
    tmp_path,
):
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    declared_version = project["version"]
    wheel = build.ProjectBuilder(str(REPO_ROOT)).build("wheel", str(tmp_path / "dist"))
    environment = tmp_path / "installed"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", wheel],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    code = textwrap.dedent(
        """
        import json
        import sys
        from importlib.metadata import version
        from pathlib import Path

        import kyno

        assert Path(kyno.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        print(json.dumps({"distribution": version("kyno"), "import": kyno.__version__}))
        """
    )

    result = subprocess.run(
        [str(python), "-I", "-c", code],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert json.loads(result.stdout) == {
        "distribution": declared_version,
        "import": declared_version,
    }
