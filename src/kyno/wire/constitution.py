# SPDX-License-Identifier: MIT
import re

_KEY_FORMAT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def is_constitution_key(value: str) -> bool:
    """Return whether text uses lowercase letters, digits, and single hyphens."""
    return _KEY_FORMAT.fullmatch(value) is not None


def suggest_constitution_key(value: str) -> str:
    """Return a key suggestion for an error message, without changing stored identity."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
