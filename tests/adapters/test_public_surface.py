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
    "BackgroundSubscriber",
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


def test_the_core_exports_one_documented_surface():
    assert set(core.__all__) >= EXPECTED
    for name in core.__all__:
        assert hasattr(core, name), name


def test_nothing_public_leaks_in_beside_the_documented_surface():
    """__all__ is the public contract; anything else public is an accident."""
    modules = {"binder", "cell", "client", "gate", "policy", "subscriber", "trace"}
    public = {name for name in vars(core) if not name.startswith("_")} - modules

    assert public == set(core.__all__)
    assert len(core.__all__) == len(set(core.__all__))


def test_no_adapter_can_write_direction():
    """Adapters pull and subscribe. Editing the rulebook is an operator act,
    so the write path simply does not exist in this package."""
    offenders = [
        path.relative_to(ADAPTERS).as_posix()
        for path in ADAPTERS.rglob("*.py")
        if "set_direction" in path.read_text()
    ]
    assert offenders == []


def test_the_core_stays_importable_with_no_orchestrator():
    """The whole core surface, in a process that must not touch a framework."""
    code = (
        "import sys, kyno.sdk as core;"
        "assert core.__all__;"
        "loaded = {m.split('.')[0] for m in sys.modules};"
        "assert not loaded & {'crewai', 'langgraph', 'langchain_core', 'openai'}, loaded"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
