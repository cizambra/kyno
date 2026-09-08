import subprocess
import sys
import textwrap


def test_given_the_package_when_importing_core_then_it_imports():
    import kyno.sdk as core

    assert core.__doc__


def test_given_the_core_when_inspecting_imports_then_no_framework_is_there():
    # A subprocess, not sys.modules surgery: another test may already have
    # imported crewai, and "the core is framework-free" is only true if it
    # holds in a fresh interpreter.
    code = textwrap.dedent(
        """
        import sys
        import kyno.sdk  # noqa: F401
        leaked = [m for m in sys.modules if m.split(".")[0] in ("crewai", "langgraph")]
        assert not leaked, leaked
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)
