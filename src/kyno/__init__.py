__version__ = "0.1.0"


def __getattr__(name: str):
    # `import kyno` stays cheap for the CLI and the server; the SDK loads on
    # first use of kyno.connect.
    if name == "connect":
        from kyno.sdk import connect

        return connect
    raise AttributeError(f"module 'kyno' has no attribute {name!r}")
