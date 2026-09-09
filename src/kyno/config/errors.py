"""Errors raised while resolving client-owned configuration."""

from kyno.wire.errors import CoherenceError


class ConfigError(CoherenceError):
    """A client configuration value is missing or malformed."""


class ProfileError(ConfigError):
    """A remote profile is missing, ambiguous, or does not resolve."""
