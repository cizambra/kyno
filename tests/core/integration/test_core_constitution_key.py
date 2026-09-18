"""Embedded control-plane operations select constitution keys independently."""

from kyno.service import ControlPlane


def test_given_named_direction_when_selecting_key_then_embedded_operations_share_it(memory_store):
    plane = ControlPlane(memory_store)
    plane.apply_direction(mission="EU mission", change_note="init", constitution_key=" eu-west ")
    assert plane.current(constitution_key="eu-west").mission == "EU mission"
    assert plane.get_constitution(constitution_key="eu-west", version=1).mission == "EU mission"
    assert plane.changes_since(0, constitution_key="eu-west").current_version == 1
    assert plane.export_versions(constitution_key="eu-west")[0]["version"] == 1
    assert plane.preview_edit(mission="Next mission", constitution_key="eu-west")
    assert plane.head_and_delta(mission="Next mission", constitution_key="eu-west")[0].version == 1
    assert plane.publish(constitution_key="eu-west").published
    assert plane.publication(constitution_key="eu-west").published
    assert plane.public_constitution(constitution_key="eu-west").name == "eu-west"
    assert not plane.unpublish(constitution_key="eu-west").published
    assert plane.current().version == 0
