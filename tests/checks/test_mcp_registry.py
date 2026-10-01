"""Registry metadata identifies the package that release publishing makes available."""

import json
import tomllib

import pytest
import yaml

from tests.paths import REPO_ROOT


@pytest.fixture
def manifest():
    return json.loads((REPO_ROOT / "server.json").read_text())


@pytest.mark.parametrize("scope", ["server", "package"])
def test_given_package_version_when_reading_registry_metadata_then_release_version_matches(
    manifest, scope
):
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    metadata = manifest if scope == "server" else manifest["packages"][0]

    assert metadata["version"] == project["version"]


def test_given_registry_name_when_reading_package_readme_then_ownership_marker_matches(manifest):
    readme = (REPO_ROOT / "README.md").read_text()

    assert f"<!-- mcp-name: {manifest['name']} -->" in readme


def test_given_registry_publish_job_when_releasing_then_pypi_publication_precedes_oidc_login():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/release.yml").read_text())
    job = workflow["jobs"]["publish-mcp"]
    commands = [step["run"] for step in job["steps"] if "run" in step]

    assert job["needs"] == "publish"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert "./mcp-publisher login github-oidc" in commands
