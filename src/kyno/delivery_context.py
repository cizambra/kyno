"""Validation of application-supplied correlation labels and delivery metadata."""

import json

from pydantic import JsonValue, TypeAdapter, ValidationError

MAX_METADATA_BYTES = 16_384
MAX_CORRELATION_CHARS = 255
_metadata_adapter = TypeAdapter(dict[str, JsonValue])


def delivery_context(arguments: dict) -> dict:
    """Return a detached correlation ID and metadata object, or raise ValueError.

    Missing fields default to None and an empty object. Metadata must contain
    finite JSON values and fit the byte limit using Python's default JSON encoding.
    """
    correlation_id = arguments.get("correlation_id")
    if correlation_id is not None and (
        not isinstance(correlation_id, str) or len(correlation_id) > MAX_CORRELATION_CHARS
    ):
        raise ValueError(
            f"correlation_id must be a string of at most {MAX_CORRELATION_CHARS} characters"
        )
    try:
        metadata = _metadata_adapter.validate_python(arguments.get("metadata", {}), strict=True)
        encoded = json.dumps(metadata, allow_nan=False)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise ValueError("metadata must be a JSON object with finite numbers") from None
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} encoded bytes")
    return {"correlation_id": correlation_id, "metadata": json.loads(encoded)}
