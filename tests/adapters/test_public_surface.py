import subprocess
import sys
from pathlib import Path

import kyno.sdk as core

EXPECTED = {
    "Direction",
    "DirectionCell",
    "DIRECTION_MARKER",
    "KynoBinding",
    "DirectionSource",
    "LocalDirectionSource",
    "McpDirectionSource",
    "SessionRunner",
    "http_session",
    "DirectionBinder",
    "RESOURCE_URI",
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
    "StepRecord",
    "DecompositionEdge",
    "RunTrace",
}

ADAPTERS = Path(__file__).resolve().parents[2] / "src" / "kyno" / "adapters"


def test_given_the_core_when_reading_its_exports_then_one_documented_surface_shows():
    assert set(core.__all__) >= EXPECTED
    for name in core.__all__:
        assert hasattr(core, name), name


def test_given_the_exports_when_comparing_to_the_docs_then_nothing_extra_leaks():
    """__all__ is the public contract; anything else public is an accident."""
    modules = {"binder", "cell", "client", "gate", "plan", "policy", "subscriber", "trace"}
    public = {name for name in vars(core) if not name.startswith("_")} - modules

    assert public == set(core.__all__)
    assert len(core.__all__) == len(set(core.__all__))


def test_given_any_adapter_when_looking_for_writes_then_none_can_write_direction():
    """Adapters pull and subscribe. Editing the rulebook is an operator act,
    so the write path simply does not exist in this package."""
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
