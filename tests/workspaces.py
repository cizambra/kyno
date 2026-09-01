"""One helper: a workspace for CLI tests to stand in."""

from kyno.workspace import create_workspace


def cli_workspace(monkeypatch, tmp_path, db=None, root=None):
    """Create a workspace and chdir into it, so CLI commands resolve their
    store there. With `db`, the store goes to that exact file instead of
    the workspace's own db/kyno.sqlite3."""
    root = root or tmp_path / "instance"
    if not (root / "config" / "server").is_file():
        create_workspace(root)
    if db is not None:
        (root / "config" / "server").write_text(
            f"[database]\nadapter = sqlite3\ndatabase = {db}\n", encoding="utf-8"
        )
    monkeypatch.chdir(root)
    return root
