import pytest

from kyno.delivery import MAX_METADATA_BYTES, delivery_context


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        [],
        {1: "bad key"},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": object()},
        {"x": {1, 2}},
    ],
)
def test_given_invalid_metadata_when_building_context_then_it_is_rejected(metadata):
    with pytest.raises(ValueError, match="metadata"):
        delivery_context({"metadata": metadata})


@pytest.mark.parametrize("session_id", [42, [], "x" * 256])
def test_given_an_invalid_session_label_when_building_context_then_it_is_rejected(session_id):
    with pytest.raises(ValueError, match="session_id"):
        delivery_context({"session_id": session_id})


def test_given_nested_metadata_when_the_caller_mutates_it_then_the_context_is_unchanged():
    metadata = {"app": {"ids": [1, 2]}}
    context = delivery_context({"metadata": metadata})
    metadata["app"]["ids"].append(3)
    assert context["metadata"] == {"app": {"ids": [1, 2]}}


def test_given_oversized_metadata_when_building_context_then_it_is_rejected():
    with pytest.raises(ValueError, match="exceeds"):
        delivery_context({"metadata": {"data": "x" * MAX_METADATA_BYTES}})


def test_given_no_caller_context_when_building_context_then_session_is_absent_and_metadata_empty():
    assert delivery_context({}) == {"session_id": None, "metadata": {}}
