# SPDX-License-Identifier: MIT
"""Constitution identity shared by Core and SDK operation boundaries."""

from kyno.wire.errors import InvalidConstitutionNameError

MAX_CONSTITUTION_NAME_CHARS = 200


def check_constitution(constitution: str | None = None) -> str:
    """Return default for None or the exact supplied name; reject invalid names."""
    if constitution is None:
        return "default"
    if not isinstance(constitution, str) or not constitution.strip():
        raise InvalidConstitutionNameError("constitution name must be a non-blank string")
    if len(constitution) > MAX_CONSTITUTION_NAME_CHARS:
        raise InvalidConstitutionNameError(
            f"constitution name is {len(constitution)} characters, "
            f"over the cap of {MAX_CONSTITUTION_NAME_CHARS}"
        )
    return constitution
