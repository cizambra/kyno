"""Coercions that name their key.

A config value arrives as text; these turn it into the type the key
wants, and when they can't, the refusal says which key went wrong
instead of a bare ValueError.
"""

from __future__ import annotations

import configparser

from kyno.errors import ConfigError


def to_int(value: str, *, owner: str) -> int:
    # int() alone raises without saying which key went wrong.
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{owner} must be an integer, got '{value}'") from None


def to_bool(value: str, *, owner: str) -> bool:
    # configparser's own truth table (true/false, 1/0, yes/no, on/off);
    # only the refusal is ours, so it names the key.
    try:
        return configparser.ConfigParser.BOOLEAN_STATES[value.lower()]
    except KeyError:
        raise ConfigError(f"{owner} must be true or false, got '{value}'") from None
