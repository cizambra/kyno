import tomllib

import kyno
from tests.paths import REPO_ROOT


def test_given_project_version_when_importing_kyno_then_package_version_matches():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    declared_version = project["version"]

    exposed_version = kyno.__version__

    assert exposed_version == declared_version
