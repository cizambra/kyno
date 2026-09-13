from dataclasses import dataclass
from enum import StrEnum


class RecordingPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


@dataclass(frozen=True)
class RecordingsSettings:
    policy: RecordingPolicy = RecordingPolicy.NEVER

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy", RecordingPolicy(self.policy))
