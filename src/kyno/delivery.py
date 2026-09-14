from dataclasses import dataclass
from enum import StrEnum


class RecordingPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


@dataclass(frozen=True)
class DeliverySettings:
    recording_policy: RecordingPolicy = RecordingPolicy.NEVER

    def __post_init__(self) -> None:
        object.__setattr__(self, "recording_policy", RecordingPolicy(self.recording_policy))
