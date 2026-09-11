"""Release validation requires both framework integrations before publication."""

import pytest
import yaml

from tests.paths import REPO_ROOT


@pytest.fixture
def release_commands():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/release.yml").read_text())
    return [step["run"] for step in workflow["jobs"]["build"]["steps"] if "run" in step]


def test_given_release_build_when_installing_dependencies_then_both_framework_extras_are_required(
    release_commands,
):
    assert 'python -m pip install -e ".[dev,crewai,langgraph]"' in release_commands


def test_given_release_validation_when_framework_imports_fail_then_tests_cannot_silently_skip_them(
    release_commands,
):
    guard = 'python -c "import crewai.hooks; import langgraph.graph"'
    assert guard in release_commands
    test_index = next(
        index for index, command in enumerate(release_commands) if "python -m pytest" in command
    )
    assert release_commands.index(guard) < test_index
