"""The execution request, poll result and backend protocol shared by every backend."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from numpy.typing import NDArray

from .exceptions import ValidationError
from .models import SafetyLimits, Sequence, validate
from .state import DeviceState
from .validation import text

# Kept independent of run_file so importing a Flyer needs no optional HDF5 package.
READOUT_FIELDS = (
    "t_s",
    "voltage_v",
    "current_a",
    "step_index",
    "repeat_index",
    "source_status",
    "measure_status",
)
SequenceEvent = tuple[float, int, int, str, str]


@dataclass(frozen=True)
class SequenceRequest:
    """What a backend executes: one finite, validated sequence under explicit limits.

    Experiment provenance (sample, notes, run-sheet row) belongs to the
    application; it may subclass this request to carry it.
    """

    measurement_id: str
    sequence: Sequence
    limits: SafetyLimits
    start_mode: Literal["immediate", "external"] = "immediate"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "measurement_id", text(self.measurement_id, "measurement_id").strip()
        )
        if self.start_mode not in ("immediate", "external"):
            raise ValidationError("start_mode must be immediate or external")
        validate(self.sequence, self.limits)


@dataclass(frozen=True)
class SequencePoll:
    readout: dict[str, NDArray[Any]]
    events: list[SequenceEvent]
    outcome: str | None
    detail: str = ""


class SequenceBackend(Protocol):
    """One owner; bounded polls are the only readout path."""

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def inspect(self) -> tuple[DeviceState, bool | None]: ...
    def equipment(self) -> dict[str, str | int | float | bool]: ...
    def prepare(self, request: SequenceRequest) -> None: ...  # also from PREPARED
    def kickoff(self) -> None: ...
    def time_origin_epoch_s(self) -> float | None: ...
    def poll(self, max_records: int) -> SequencePoll: ...
    def abort(self, reason: str) -> None: ...
    def recover(self) -> None: ...
