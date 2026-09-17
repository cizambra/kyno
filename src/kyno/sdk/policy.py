# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PullPolicy:
    fail_closed: bool = False
