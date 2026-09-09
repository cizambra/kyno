# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GatePolicy:
    """Per gate, not per process: "refuse to publish unjudged" and "refuse to
    think unjudged" are different risks, and one switch for both would force
    the strictest gate's posture onto every other gate."""

    fail_closed: bool = False


@dataclass(frozen=True)
class PullPolicy:
    fail_closed: bool = False
