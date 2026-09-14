import json

import pytest

from kyno.delivery_context import MAX_CORRELATION_CHARS, MAX_METADATA_BYTES, delivery_context


def test_given_no_context_when_validating_then_defaults_are_returned():
    assert delivery_context({"other": "ignored"}) == {"correlation_id": None, "metadata": {}}


@pytest.mark.parametrize("correlation_id", [None, "", "session-1", "é" * 255])
def test_given_valid_correlation_id_when_validating_then_it_is_preserved(correlation_id):
    assert MAX_CORRELATION_CHARS == 255
    assert delivery_context({"correlation_id": correlation_id})["correlation_id"] == correlation_id


@pytest.mark.parametrize("correlation_id", [True, 123, [], {}, "a" * 256])
def test_given_invalid_correlation_id_when_validating_then_it_is_rejected(correlation_id):
    with pytest.raises(
        ValueError, match="correlation_id must be a string of at most 255 characters"
    ):
        delivery_context({"correlation_id": correlation_id})


def test_given_json_metadata_when_validating_then_all_json_types_are_preserved():
    metadata = {"nested": [None, True, False, 12, 1.5, "é", {"key": []}]}
    assert delivery_context({"metadata": metadata})["metadata"] == metadata


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        [],
        "text",
        1,
        True,
        {1: "value"},
        {"nested": {1: "value"}},
        {"tuple": (1, 2)},
        {"set": {1}},
        {"bytes": b"text"},
        {"object": object()},
        {"number": float("nan")},
        {"nested": [float("inf")]},
        {"number": -float("inf")},
    ],
)
def test_given_non_json_metadata_when_validating_then_it_is_rejected(metadata):
    with pytest.raises(ValueError, match="metadata must be a JSON object with finite numbers"):
        delivery_context({"metadata": metadata})


@pytest.mark.parametrize("character, encoded_width", [("a", 1), ("é", 6), ("😀", 12)])
def test_given_metadata_at_encoded_limit_when_validating_then_it_is_accepted(
    character, encoded_width
):
    assert MAX_METADATA_BYTES == 16_384
    available_bytes = MAX_METADATA_BYTES - len(json.dumps({"value": ""}).encode("utf-8"))
    repetitions, padding = divmod(available_bytes, encoded_width)
    metadata = {"value": character * repetitions + "a" * padding}
    assert len(json.dumps(metadata).encode("utf-8")) == MAX_METADATA_BYTES
    assert delivery_context({"metadata": metadata})["metadata"] == metadata


@pytest.mark.parametrize("character, encoded_width", [("a", 1), ("é", 6), ("😀", 12)])
def test_given_metadata_over_encoded_limit_when_validating_then_it_is_rejected(
    character, encoded_width
):
    available_bytes = MAX_METADATA_BYTES - len(json.dumps({"value": ""}).encode("utf-8"))
    repetitions, padding = divmod(available_bytes, encoded_width)
    metadata = {"value": character * repetitions + "a" * (padding + 1)}
    assert len(json.dumps(metadata).encode("utf-8")) == MAX_METADATA_BYTES + 1
    with pytest.raises(ValueError, match="metadata exceeds 16384 encoded bytes"):
        delivery_context({"metadata": metadata})


def test_given_nested_metadata_when_input_mutates_then_validated_context_is_unchanged():
    metadata = {"nested": [{"values": [1]}]}
    context = delivery_context({"metadata": metadata})
    metadata["nested"][0]["values"].append(2)
    assert context["metadata"] == {"nested": [{"values": [1]}]}


def test_given_nested_metadata_when_context_mutates_then_input_is_unchanged():
    metadata = {"nested": [{"values": [1]}]}
    context = delivery_context({"metadata": metadata})
    context["metadata"]["nested"][0]["values"].append(2)
    assert metadata == {"nested": [{"values": [1]}]}


@pytest.mark.parametrize("container", [{}, []])
def test_given_cyclic_metadata_when_validating_then_it_is_rejected(container):
    if isinstance(container, dict):
        container["self"] = container
    else:
        container.append(container)
    with pytest.raises(ValueError, match="metadata must be a JSON object with finite numbers"):
        delivery_context({"metadata": {"cycle": container}})


def test_given_excessively_nested_metadata_when_validating_then_it_is_rejected():
    metadata = {}
    for _depth in range(1000):
        metadata = {"nested": metadata}
    with pytest.raises(ValueError, match="metadata must be a JSON object with finite numbers"):
        delivery_context({"metadata": metadata})
