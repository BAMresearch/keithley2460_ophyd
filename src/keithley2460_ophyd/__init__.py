"""Ophyd Flyer and finite-sequence backend for the Keithley 2460 SourceMeter.

Importing this package never opens an instrument connection. The 2460 backend
(``k2460_sequence_backend``) needs the ``visa`` extra and an explicit VISA
resource and expected serial number.
"""

from .backend import READOUT_FIELDS, SequenceBackend, SequenceEvent, SequencePoll, SequenceRequest
from .exceptions import (
    AmbiguousTransportError,
    ElectrochemistryError,
    IncompatibleInstrumentError,
    RetainedDataError,
    ShutdownUnconfirmed,
    TransportError,
    UnsupportedCapabilityError,
    ValidationError,
)
from .flyer import SequenceFlyer, archive_retained
from .models import (
    CutoffAction,
    RepeatBlock,
    SafetyLimits,
    Sampling,
    Sequence,
    Step,
    StepMode,
    expanded,
    expected_records,
    limits_from_dict,
    nominal_duration_s,
    sample_schedule,
    sequence_from_dict,
    step_records,
    to_dict,
    validate,
)
from .runtime_artifact import RuntimeArtifact
from .sequence_backend import Keithley2460SequenceBackend, k2460_sequence_backend
from .sequencer import Replayer, SequencerProfile, SequencerProgram, compile_program
from .sequencer_runtime import SEQUENCER_ABI, SEQUENCER_BUILD, sequencer_packaged_runtime
from .state import DeviceState
from .steps import DEFAULT_FAST_INTERVAL_S, cc_step, cv_step, rest_step, two_phase_sampling

__version__ = "0.1.0.dev0"

__all__ = [
    "DEFAULT_FAST_INTERVAL_S",
    "READOUT_FIELDS",
    "SEQUENCER_ABI",
    "SEQUENCER_BUILD",
    "AmbiguousTransportError",
    "CutoffAction",
    "DeviceState",
    "ElectrochemistryError",
    "IncompatibleInstrumentError",
    "Keithley2460SequenceBackend",
    "RepeatBlock",
    "Replayer",
    "RetainedDataError",
    "RuntimeArtifact",
    "SafetyLimits",
    "Sampling",
    "Sequence",
    "SequenceBackend",
    "SequenceEvent",
    "SequenceFlyer",
    "SequencePoll",
    "SequenceRequest",
    "SequencerProfile",
    "SequencerProgram",
    "ShutdownUnconfirmed",
    "Step",
    "StepMode",
    "TransportError",
    "UnsupportedCapabilityError",
    "ValidationError",
    "__version__",
    "archive_retained",
    "cc_step",
    "compile_program",
    "cv_step",
    "expanded",
    "expected_records",
    "k2460_sequence_backend",
    "limits_from_dict",
    "nominal_duration_s",
    "rest_step",
    "sample_schedule",
    "sequence_from_dict",
    "sequencer_packaged_runtime",
    "step_records",
    "to_dict",
    "two_phase_sampling",
    "validate",
]
