from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class RecordingPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


@dataclass(frozen=True)
class DeliverySettings:
    recording_policy: RecordingPolicy = RecordingPolicy.NEVER
    recording_timeout_seconds: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "recording_policy", RecordingPolicy(self.recording_policy))
        timeout = self.recording_timeout_seconds
        if type(timeout) not in (int, float) or not isfinite(timeout) or timeout <= 0:
            raise ValueError("recording_timeout_seconds must be a positive finite number")
