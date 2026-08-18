import subprocess
import sys
import textwrap


def test_core_is_importable():
    import kyno.adapters.core as core

    assert core.__doc__


def test_core_never_imports_a_framework():
    # A subprocess, not sys.modules surgery: another test may already have
    # imported crewai, and "the core is framework-free" is only true if it
    # holds in a fresh interpreter.
    code = textwrap.dedent(
        """
        import sys
        import kyno.adapters.core  # noqa: F401
        leaked = [m for m in sys.modules if m.split(".")[0] in ("crewai", "langgraph")]
        assert not leaked, leaked
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)
