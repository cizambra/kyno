"""Generate and hash token values, parse --ttl strings, and format
last-used times for `kyno token list`."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

# The prefix that makes a leaked value recognizable, by people and by
# secret scanners.
VALUE_PREFIX = "kyno_"


def generate_value() -> str:
    """A fresh token value. Shown once at minting; only its hash is stored."""
    return VALUE_PREFIX + secrets.token_urlsafe(32)


def hash_value(value: str) -> str:
    """What the database stores instead of the value. If the database
    leaks, the thief holds hashes: a hash does not work as a token, and
    it cannot be turned back into one."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_TTL_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_ttl(text: str) -> timedelta:
    """'30m', '2h' or '7d' as the timedelta it means. Anything else is
    refused naming the input, so the error reads back what was typed."""
    number, unit = text[:-1], text[-1:]
    if unit in _TTL_UNITS and number.isdigit() and int(number) > 0:
        return timedelta(**{_TTL_UNITS[unit]: int(number)})
    raise ValueError(f"a ttl is a number and a unit (30m, 2h, 7d); got '{text}'")


def age(then: datetime | None, now: datetime) -> str:
    """How long ago, in the largest unit that fits: '2m ago', '3h ago'.
    'never' is a token that was minted and not used yet."""
    if then is None:
        return "never"
    seconds = int((now - then).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"
