"""Offline contracts for finite step sequences and battery protocol builders."""

import json
import math
from dataclasses import replace

import pytest

from keithley2460_ophyd import (
    RepeatBlock,
    SafetyLimits,
    Sampling,
    Sequence,
    Step,
    StepMode,
    cv_step,
    expanded,
    expected_records,
    limits_from_dict,
    nominal_duration_s,
    rest_step,
    sample_schedule,
    sequence_from_dict,
    step_records,
    to_dict,
    two_phase_sampling,
    validate,
)
from keithley2460_ophyd.exceptions import ValidationError


def current_step(**changes):
    return Step(
        **(dict(mode=StepMode.CURRENT, level=0.01, duration_s=1, sampling=Sampling(0.1)) | changes)
    )


def limits(**changes):
    return SafetyLimits(
        **(
            dict(v_min_abs=0, v_max_abs=4, i_max_abs=0.1, max_duration_s=1e6, max_records=1_000_000)
            | changes
        )
    )


BAD_NUMBERS = [True, False, "1", None, 1j, math.nan, math.inf, -math.inf, 10**1000]


@pytest.mark.parametrize("value", BAD_NUMBERS)
@pytest.mark.parametrize("field", ["interval_s", "fast_interval_s", "fast_window_s"])
def test_sampling_numeric_types_and_finiteness(field, value):
    if field == "fast_interval_s" and value is None:
        assert Sampling(0.1, None) == Sampling(0.1)
        return
    with pytest.raises(ValidationError, match=field):
        Sampling(
            **(dict(interval_s=0.1, fast_interval_s=0.005, fast_window_s=0.5) | {field: value})
        )


@pytest.mark.parametrize(
    "args,field",
    [
        ((0,), "interval_s"),
        ((-1,), "interval_s"),
        ((1, 0, 1), "fast_interval_s"),
        ((1, -1, 1), "fast_interval_s"),
        ((1, None, -1), "fast_window_s"),
        ((1, None, 1), "fast_window_s"),
        ((1, 0.1, 0), "fast_interval_s"),
        ((1, 1, 1), "fast_interval_s"),
        ((1, 2, 1), "fast_interval_s"),
    ],
)
def test_sampling_signs_and_paired_fast_phase(args, field):
    with pytest.raises(ValidationError, match=field):
        Sampling(*args)


@pytest.mark.parametrize("field", ["level", "duration_s", "v_min", "v_max", "i_abs_min"])
@pytest.mark.parametrize("value", BAD_NUMBERS)
def test_step_numeric_types_and_finiteness(field, value):
    if field in ("v_min", "v_max", "i_abs_min") and value is None:
        assert getattr(current_step(), field) is None
        return
    with pytest.raises(ValidationError, match=field):
        current_step(**{field: value})


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"mode": "current"}, "mode"),
        ({"mode": 0}, "mode"),
        ({"duration_s": 0}, "duration_s"),
        ({"duration_s": -1}, "duration_s"),
        ({"sampling": {"interval_s": 0.1}}, "sampling"),
        ({"on_cutoff": "next"}, "on_cutoff"),
        ({"label": None}, "label"),
        ({"mode": StepMode.REST}, "level"),
        ({"mode": StepMode.VOLTAGE, "v_min": 0}, "v_min"),
        ({"mode": StepMode.VOLTAGE, "v_max": 4}, "v_max"),
        ({"i_abs_min": 0.001}, "i_abs_min"),
        ({"mode": StepMode.REST, "level": 0, "i_abs_min": 0.001}, "i_abs_min"),
        ({"mode": StepMode.VOLTAGE, "i_abs_min": -0.1}, "i_abs_min"),
        ({"i_limit": 0.001}, "i_limit"),
        ({"mode": StepMode.REST, "level": 0, "i_limit": 0.001}, "i_limit"),
        ({"mode": StepMode.VOLTAGE, "i_limit": 0}, "i_limit"),
        ({"mode": StepMode.VOLTAGE, "i_limit": math.nan}, "i_limit"),
    ],
)
def test_step_structure_signs_and_mode_specific_fields(changes, field):
    with pytest.raises(ValidationError, match=field):
        current_step(**changes)


@pytest.mark.parametrize("field", ["first", "last", "count"])
@pytest.mark.parametrize("value", [True, "1", 1.0, None, -1, math.inf, math.nan])
def test_repeat_requires_integer_indices_and_count(field, value):
    with pytest.raises(ValidationError, match=field):
        RepeatBlock(**(dict(first=0, last=1, count=2) | {field: value}))


def test_repeat_order_and_zero_count():
    with pytest.raises(ValidationError, match="last"):
        RepeatBlock(1, 0, 1)
    with pytest.raises(ValidationError, match="count"):
        RepeatBlock(0, 0, 0)
    assert RepeatBlock(0, 0, 1).count == 1


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"steps": ()}, "steps"),
        ({"steps": [current_step()]}, "steps"),
        ({"steps": (current_step(),) * 31}, "steps"),
        ({"steps": (current_step(), None)}, "step 1"),
        ({"repeat": (0, 0, 2)}, "repeat"),
        ({"name": None}, "name"),
    ],
)
def test_sequence_shape(changes, field):
    with pytest.raises(ValidationError, match=field):
        Sequence(**(dict(steps=(current_step(),)) | changes))
    assert len(Sequence((current_step(),) * 30).steps) == 30


@pytest.mark.parametrize(
    "field", ["v_min_abs", "v_max_abs", "i_max_abs", "max_duration_s", "min_interval_s"]
)
@pytest.mark.parametrize("value", BAD_NUMBERS)
def test_limits_numeric_types_and_finiteness(field, value):
    with pytest.raises(ValidationError, match=field):
        limits(**{field: value})


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"v_min_abs": 4}, "v_min_abs"),
        ({"v_max_abs": -1}, "v_min_abs"),
        ({"i_max_abs": 0}, "i_max_abs"),
        ({"i_max_abs": -1}, "i_max_abs"),
        ({"max_duration_s": 0}, "max_duration_s"),
        ({"max_duration_s": -1}, "max_duration_s"),
        ({"min_interval_s": 0}, "min_interval_s"),
        ({"min_interval_s": -1}, "min_interval_s"),
        ({"max_records": 0}, "max_records"),
        ({"max_records": -1}, "max_records"),
        ({"max_records": True}, "max_records"),
        ({"max_records": 1.5}, "max_records"),
        ({"max_records": "10"}, "max_records"),
    ],
)
def test_limits_signs_window_and_integer_record_budget(changes, field):
    with pytest.raises(ValidationError, match=field):
        limits(**changes)
    assert limits(v_min_abs=-2, v_max_abs=-1).v_min_abs == -2


@pytest.mark.parametrize(
    "step,field",
    [
        (current_step(level=0.10001), "level"),
        (current_step(level=-0.10001), "level"),
        (current_step(mode=StepMode.VOLTAGE, level=4.01), "level"),
        (current_step(mode=StepMode.VOLTAGE, level=-0.01), "level"),
        (current_step(v_min=-0.01), "v_min"),
        (current_step(v_min=4.01), "v_min"),
        (current_step(v_max=-0.01), "v_max"),
        (current_step(v_max=4.01), "v_max"),
        (current_step(v_min=2, v_max=2), "v_min"),
        (current_step(v_min=3, v_max=2), "v_min"),
        (current_step(sampling=Sampling(0.004)), "sampling.interval_s"),
        (current_step(sampling=Sampling(0.1, 0.004, 0.5)), "sampling.fast_interval_s"),
        (current_step(mode=StepMode.REST, level=0, v_min=-1), "v_min"),
    ],
)
def test_cross_validation_identifies_step_and_field(step, field):
    with pytest.raises(ValidationError, match=f"step 1:.*{field}"):
        validate(Sequence((current_step(), step)), limits())


@pytest.mark.parametrize("index", [1, 2])
def test_repeat_indices_checked_before_execution_or_budgeting(index):
    sequence = Sequence((current_step(),), RepeatBlock(index, index, 2))
    for operation in (expanded, nominal_duration_s, expected_records):
        with pytest.raises(ValidationError, match=f"step {index}: repeat.first"):
            operation(sequence)
    with pytest.raises(ValidationError, match="repeat.first"):
        validate(sequence, limits())
    with pytest.raises(ValidationError, match="repeat.last"):
        validate(replace(sequence, repeat=RepeatBlock(0, index, 2)), limits())


def test_safety_boundaries_are_inclusive_and_signed():
    sequence = Sequence(
        (
            current_step(level=-0.1, v_min=0, v_max=4),
            cv_step(4, 0, 1, Sampling(0.005)),
            cv_step(0, 0.001, 1, Sampling(0.1)),
        )
    )
    validate(sequence, limits(max_duration_s=3, max_records=220))
    assert expected_records(sequence) == 220
    assert nominal_duration_s(sequence) == 3


@pytest.mark.parametrize(
    "changes,field",
    [({"max_duration_s": 1.9}, "max_duration_s"), ({"max_records": 19}, "max_records")],
)
def test_repeated_block_counts_against_safety_budgets(changes, field):
    sequence = Sequence((current_step(),), RepeatBlock(0, 0, 2))
    with pytest.raises(ValidationError, match=field):
        validate(sequence, limits(**changes))


def test_budget_checks_do_not_expand_huge_repeats():
    sequence = Sequence((current_step(),), RepeatBlock(0, 0, 10**20))
    assert expected_records(sequence) == 10**21
    with pytest.raises(ValidationError, match="max_duration_s"):
        validate(sequence, limits())
    with pytest.raises(ValidationError, match="nominal_duration_s"):
        nominal_duration_s(replace(sequence, repeat=RepeatBlock(0, 0, 10**1000)))
    with pytest.raises(ValidationError, match="nominal_duration_s"):
        nominal_duration_s(Sequence((current_step(duration_s=1e308),) * 2))
    huge_step = current_step(duration_s=1e308, sampling=Sampling(1e-308))
    with pytest.raises(ValidationError, match="record count"):
        step_records(huge_step)
    with pytest.raises(ValidationError, match="step 0:.*record count"):
        expected_records(Sequence((huge_step,)))


def test_execution_order_preserves_prefix_suffix_and_repeat_indices():
    steps = tuple(current_step(label=str(i), duration_s=i + 1) for i in range(4))
    sequence = Sequence(steps, RepeatBlock(1, 2, 3))
    result = expanded(sequence)
    assert [(index, repeat) for index, repeat, _ in result] == [
        (0, 0),
        (1, 1),
        (2, 1),
        (1, 2),
        (2, 2),
        (1, 3),
        (2, 3),
        (3, 0),
    ]
    assert all(step is steps[index] for index, _, step in result)
    assert nominal_duration_s(sequence) == 20
    assert expected_records(sequence) == 200
    assert expanded(Sequence(steps)) == [(i, 0, step) for i, step in enumerate(steps)]
    assert [(i, r) for i, r, _ in expanded(Sequence(steps, RepeatBlock(0, 3, 1)))] == [
        (i, 1) for i in range(4)
    ]


@pytest.mark.parametrize(
    "duration,sampling,count",
    [
        (1, Sampling(0.1), 10),
        (0.21, Sampling(0.1), 3),
        (1, Sampling(0.1, 0.005, 0.5), 105),
        (0.1, Sampling(0.1, 0.005, 0.5), 20),
        (0.5, Sampling(0.1, 0.005, 0.5), 100),
        (0.03, Sampling(0.1, 0.02, 0.5), 2),
        (0.76, Sampling(0.1, 0.02, 0.5), 28),
        (0.63, Sampling(0.1, 0.005, 0.5), 102),
        (1.6, Sampling(0.1, 0.005, 0.5), 111),
    ],
)
def test_record_formula_with_partial_fast_and_slow_intervals(duration, sampling, count):
    assert step_records(current_step(duration_s=duration, sampling=sampling)) == count


def test_two_phase_sampling_short_steps_are_all_fast():
    for duration in (0.1, 0.5):
        sampling = two_phase_sampling(duration)
        assert sampling == Sampling(0.006)
        assert step_records(current_step(duration_s=duration, sampling=sampling)) == math.ceil(
            duration / 0.006
        )
    assert two_phase_sampling(1) == Sampling(0.1, 0.006, 0.5)


def test_limits_round_trip_and_decoder_defaults():
    original = limits(v_min_abs=-1)
    assert limits_from_dict(json.loads(json.dumps(to_dict(original)))) == original
    data = to_dict(original)
    del data["min_interval_s"]
    assert limits_from_dict(data).min_interval_s == 0.005
    sequence = sequence_from_dict(
        {"steps": [{"mode": "rest", "level": 0, "duration_s": 1, "sampling": {"interval_s": 0.1}}]}
    )
    assert sequence == Sequence((rest_step(1, Sampling(0.1)),))


@pytest.mark.parametrize(
    "decoder,data",
    [
        (sequence_from_dict, None),
        (sequence_from_dict, {}),
        (sequence_from_dict, {"steps": ()}),
        (sequence_from_dict, {"steps": [], "unknown": 1}),
        (sequence_from_dict, {"steps": [None]}),
        (sequence_from_dict, {"steps": [{"extra": True}]}),
        (limits_from_dict, []),
        (limits_from_dict, {}),
        (limits_from_dict, to_dict(limits()) | {"unknown": 0}),
        (limits_from_dict, to_dict(limits()) | {"max_records": True}),
    ],
)
def test_malformed_metadata_is_rejected(decoder, data):
    with pytest.raises(ValidationError):
        decoder(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "power"},
        {"mode": []},
        {"on_cutoff": "ignore"},
        {"duration_s": "1"},
        {"duration_s": math.inf},
        {"level": math.nan},
        {"level": True},
        {"sampling": None},
        {"sampling": {"interval_s": True}},
        {"sampling": {}},
        {"sampling": {"interval_s": 1, "extra": 1}},
        {"label": 0},
    ],
)
def test_invalid_step_metadata_names_step(changes):
    data = to_dict(Sequence((current_step(),)))
    data["steps"][0].update(changes)
    with pytest.raises(ValidationError, match="step 0"):
        sequence_from_dict(data)


@pytest.mark.parametrize("repeat", [[], {}, {"first": 0, "last": 0, "count": False}])
def test_invalid_repeat_metadata(repeat):
    data = to_dict(Sequence((current_step(),))) | {"repeat": repeat}
    with pytest.raises(ValidationError):
        sequence_from_dict(data)


def test_public_operations_reject_wrong_model_types():
    for operation in (expanded, nominal_duration_s, expected_records, step_records, to_dict):
        with pytest.raises(ValidationError):
            operation(None)
    with pytest.raises(ValidationError, match="sequence"):
        validate(None, limits())
    with pytest.raises(ValidationError, match="limits"):
        validate(Sequence((current_step(),)), None)


def test_sample_schedule_shortens_partial_slow_interval():
    step = current_step(duration_s=0.63, sampling=Sampling(0.1, 0.005, 0.5))
    (n_fast, dt_fast), (n_slow, dt_slow) = sample_schedule(step)
    assert (n_fast, n_slow) == (100, 2)
    assert math.isclose(dt_fast, 0.005) and math.isclose(dt_slow, 0.065)


def test_validate_rejects_effective_interval_below_instrument_minimum():
    limits = SafetyLimits(0.0, 3.0, 0.01, 1e6, 10**7, min_interval_s=0.005)
    step = current_step(duration_s=0.101, sampling=Sampling(0.005))
    with pytest.raises(ValidationError, match="effective interval"):
        validate(Sequence((step,)), limits)


def test_cv_current_limit_is_checked_against_the_session_and_round_trips():
    limits = SafetyLimits(0, 2, 0.01, 100, 1000)
    held = cv_step(1.0, 1e-4, 10, Sampling(1), i_limit=2e-4)
    assert held.i_limit == 2e-4
    validate(Sequence((held,)), limits)
    with pytest.raises(ValidationError, match="i_limit exceeds i_max_abs"):
        validate(Sequence((held,)), replace(limits, i_max_abs=1e-4))
    sequence = Sequence((held,))
    assert sequence_from_dict(json.loads(json.dumps(to_dict(sequence)))) == sequence
    # Without a limit the encoding is as before, so older metadata still decodes.
    plain = to_dict(Sequence((cv_step(1.0, 1e-4, 10, Sampling(1)),)))
    assert "i_limit" not in plain["steps"][0]
    assert to_dict(held)["i_limit"] == 2e-4
