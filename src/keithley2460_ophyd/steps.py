"""Generic step constructors for finite sequences; no instrument I/O."""

from .exceptions import ValidationError
from .models import CutoffAction, Sampling, Step, StepMode
from .validation import number, positive

# 6 ms at 0.1 NPLC on the 2460 (5 ms needs 0.05 NPLC).
DEFAULT_FAST_INTERVAL_S = 0.006


def two_phase_sampling(
    duration_s: float,
    fast_interval_s: float = DEFAULT_FAST_INTERVAL_S,
    fast_window_s: float = 0.5,
    interval_s: float = 0.1,
) -> Sampling:
    """Use only the fast interval when the entire step fits in the fast window."""
    positive(duration_s, "duration_s")
    sampling = Sampling(interval_s, fast_interval_s, fast_window_s)
    if duration_s <= fast_window_s:
        return Sampling(fast_interval_s)
    return sampling


def cc_step(
    current_a: float,
    target_v: float,
    max_duration_s: float,
    sampling: Sampling,
    on_cutoff: CutoffAction = CutoffAction.NEXT,
) -> Step:
    """CC toward a voltage target; the caller supplies the current direction."""
    # Validate before using the sign to select the voltage cutoff.
    number(current_a, "current_a")
    number(target_v, "target_v")
    if current_a == 0:
        raise ValidationError("current_a must be nonzero; use rest_step for 0 A")
    return Step(
        StepMode.CURRENT,
        current_a,
        max_duration_s,
        sampling,
        v_max=target_v if current_a > 0 else None,
        v_min=target_v if current_a <= 0 else None,
        on_cutoff=on_cutoff,
    )


def rest_step(duration_s: float, sampling: Sampling) -> Step:
    """Zero-current rest with output on, measuring open-circuit voltage."""
    return Step(StepMode.REST, 0.0, duration_s, sampling)


def cv_step(voltage_v: float, i_abs_min: float, max_duration_s: float, sampling: Sampling) -> Step:
    number(voltage_v, "voltage_v")
    positive(i_abs_min, "i_abs_min", zero=True)
    return Step(StepMode.VOLTAGE, voltage_v, max_duration_s, sampling, i_abs_min=i_abs_min)
