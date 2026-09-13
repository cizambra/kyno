"""Validation of application-supplied session labels and delivery metadata."""

import json

from pydantic import JsonValue, TypeAdapter, ValidationError

MAX_METADATA_BYTES = 16_384
MAX_SESSION_CHARS = 255
_metadata_adapter = TypeAdapter(dict[str, JsonValue])


def delivery_context(arguments: dict) -> dict:
    """Return a detached session ID and metadata object, or raise ValueError.

    Missing fields default to None and an empty object. Metadata must contain
    finite JSON values and fit the byte limit using Python's default JSON encoding.
    """
    session_id = arguments.get("session_id")
    if session_id is not None and (
        not isinstance(session_id, str) or len(session_id) > MAX_SESSION_CHARS
    ):
        raise ValueError(f"session_id must be a string of at most {MAX_SESSION_CHARS} characters")
    try:
        metadata = _metadata_adapter.validate_python(arguments.get("metadata", {}), strict=True)
        encoded = json.dumps(metadata, allow_nan=False)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise ValueError("metadata must be a JSON object with finite numbers") from None
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} encoded bytes")
    return {"session_id": session_id, "metadata": json.loads(encoded)}
