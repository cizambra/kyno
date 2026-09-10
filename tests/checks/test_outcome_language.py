from pathlib import Path


def test_given_launch_copy_when_describing_direction_delivery_then_it_does_not_claim_alignment():
    root = Path(__file__).parents[2]
    public_copy = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [root / "README.md", *(root / "docs").glob("*.md"), *(root / "site").glob("*")]
        if path.is_file()
    )

    assert "every agent acts on the direction" not in public_copy
    assert "System aligned" not in public_copy
    assert "The system is aligned" not in public_copy
    assert "Current version delivered" in public_copy
