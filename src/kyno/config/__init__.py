# SPDX-License-Identifier: MIT
"""Portable profile and credential resolution shared by Core and the SDK."""

from kyno.config.errors import ConfigError, ProfileError
from kyno.config.profiles import (
    CREDENTIALS_FILE,
    DEFAULT_PROFILE,
    REMOTES_FILE,
    Credential,
    Remote,
    Resolved,
    add_credentials,
    add_remote,
    config_dir,
    credentials,
    credentials_path,
    inspect,
    normalize_endpoint,
    remotes,
    remotes_path,
    resolve,
)

__all__ = [
    "CREDENTIALS_FILE",
    "DEFAULT_PROFILE",
    "REMOTES_FILE",
    "ConfigError",
    "Credential",
    "ProfileError",
    "Remote",
    "Resolved",
    "add_credentials",
    "add_remote",
    "config_dir",
    "credentials",
    "credentials_path",
    "inspect",
    "normalize_endpoint",
    "remotes",
    "remotes_path",
    "resolve",
]
