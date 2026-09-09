import subprocess
import sys

import kyno.sdk as core
import kyno.sdk.client as client
import kyno.sdk.trace as trace
from tests.paths import REPO_ROOT

EXPECTED = {
    "Direction",
    "DirectionCell",
    "DIRECTION_MARKER",
    "DirectionSource",
    "LocalDirectionSource",
    "DirectionBinder",
    "Verdict",
    "VerdictSource",
    "Action",
    "GateDecision",
    "RealignmentGate",
    "GatePolicy",
    "PullPolicy",
    "TelemetryEvent",
    "TelemetrySink",
    "LogSink",
    "RecordingSink",
}

ADAPTERS = REPO_ROOT / "src" / "kyno" / "adapters"


def test_given_the_core_when_reading_its_exports_then_one_documented_surface_shows():
    assert set(core.__all__) >= EXPECTED
    for name in core.__all__:
        assert hasattr(core, name), name


def test_given_the_exports_when_comparing_to_the_docs_then_nothing_extra_leaks():
    """__all__ is the public contract; anything else public is an accident."""
    modules = {
        "binder",
        "cell",
        "client",
        "errors",
        "gate",
        "plan",
        "policy",
        "subscriber",
        "trace",
    }
    public = {name for name in vars(core) if not name.startswith("_")} - modules

    assert public == set(core.__all__)
    assert len(core.__all__) == len(set(core.__all__))


def test_given_trace_types_when_importing_the_sdk_then_they_only_live_in_the_trace_module():
    names = {"RunTrace", "StepRecord", "DecompositionEdge"}

    assert names.isdisjoint(core.__all__)
    assert names.isdisjoint(vars(core))
    assert all(hasattr(trace, name) for name in names)


def test_given_connection_plumbing_when_importing_the_sdk_then_it_only_lives_in_the_client_module():
    names = {
        "KynoBinding",
        "McpDirectionSource",
        "RESOURCE_URI",
        "SessionRunner",
        "http_session",
    }

    assert names.isdisjoint(core.__all__)
    assert names.isdisjoint(vars(core))
    assert all(hasattr(client, name) for name in names)


def test_given_any_adapter_when_looking_for_writes_then_none_can_write_direction():
    """Adapters only pull. Editing the rulebook is an operator act, so the
    write path simply does not exist in this package."""
    offenders = [
        path.relative_to(ADAPTERS).as_posix()
        for path in ADAPTERS.rglob("*.py")
        if "set_direction" in path.read_text()
    ]
    assert offenders == []


def test_given_no_orchestrator_installed_when_importing_the_core_then_it_still_imports():
    """The whole core surface, in a process that must not touch a framework."""
    code = (
        "import sys, kyno.sdk as core;"
        "assert core.__all__;"
        "loaded = {m.split('.')[0] for m in sys.modules};"
        "assert not loaded & {'crewai', 'langgraph', 'langchain_core', 'openai'}, loaded"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
