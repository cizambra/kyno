"""Errors that cross the Core/SDK contract boundary."""


class CoherenceError(Exception):
    """Base class for errors represented by the Kyno contract."""


class UnknownPrincipleError(CoherenceError):
    """No principle in the current version carries that title."""


class MalformedPrincipleError(CoherenceError):
    """A principle was neither a title nor a title-and-description."""
