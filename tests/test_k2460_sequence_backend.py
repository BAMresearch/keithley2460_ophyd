"""Hardware sequence backend against the real packaged runtime under Lua.

``keithley2460_ophyd.testing.FakeInstrument`` executes every line the backend
sends in a Lua mock of the 2460; readings come from a resistive dummy load.
"""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

lupa = pytest.importorskip("lupa.lua51")

from bluesky import RunEngine  # noqa: E402
from bluesky import plan_stubs as bps  # noqa: E402
from sequence_fixtures import sequence_fixture  # noqa: E402

from keithley2460_ophyd import SequenceFlyer, SequenceRequest  # noqa: E402
from keithley2460_ophyd.backend import READOUT_FIELDS  # noqa: E402
from keithley2460_ophyd.exceptions import (  # noqa: E402
    ElectrochemistryError,
    IncompatibleInstrumentError,
    RetainedDataError,
    ShutdownUnconfirmed,
    TransportProtocolError,
    TransportTimeoutError,
    ValidationError,
)
from keithley2460_ophyd.models import (  # noqa: E402
    SafetyLimits,
    expanded,
)
from keithley2460_ophyd.sequence_backend import (  # noqa: E402
    Keithley2460SequenceBackend,
    guarded,
    k2460_sequence_backend,
    parse_event,
    parse_status,
)
from keithley2460_ophyd.sequencer import compile_program  # noqa: E402
from keithley2460_ophyd.sequencer_runtime import sequencer_packaged_runtime  # noqa: E402
from keithley2460_ophyd.state import DeviceState  # noqa: E402
from keithley2460_ophyd.testing import (  # noqa: E402
    CLOCK_OFFSET,
    SERIAL,
    T0,
    FakeClock,
    FakeInstrument,
    resistor_records,
)


def instrument_records(sequence, limits, *, t0=T0):
    """Resistor-load readings as stored by the instrument, and the expected run."""
    readout, rows = resistor_records(sequence, limits, t0=t0)
    events, time_s = [], 0.0
    for step_index, repeat_index, step in expanded(sequence):
        events.append((time_s, step_index, repeat_index, "step_start", step.label))
        time_s += step.duration_s
    return SimpleNamespace(readout=readout, events=events), rows


@pytest.fixture
def limits():
    return SafetyLimits(0, 4, 0.01, 10000, 100000)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def instrument(clock):
    return FakeInstrument(clock)


def make_backend(instrument, clock, **kwargs):
    kwargs.setdefault("expected_serial_number", SERIAL)
    return Keithley2460SequenceBackend(instrument, terminals="front", wall_clock=clock, **kwargs)


@pytest.fixture
def backend(instrument, clock):
    b = make_backend(instrument, clock)
    b.connect()
    return b


def pulse_request(limits, **kwargs):
    sequence = sequence_fixture("k2460_sequence_backend-07")  # 59 of 63 blocks
    return SequenceRequest("pulse 001", sequence, limits, **kwargs)


def drain(backend, max_records=100):
    readouts, events, outcome, detail = [], [], None, ""
    for _ in range(1000):
        poll = backend.poll(max_records)
        readouts.append(poll.readout)
        events.extend(poll.events)
        if poll.outcome is not None and len(poll.readout["t_s"]) < max_records:
            outcome, detail = poll.outcome, poll.detail
            break
    readout = {k: np.concatenate([r[k] for r in readouts]) for k in READOUT_FIELDS}
    return readout, events, outcome, detail


# Helpers


def test_guarded_wraps_numeric_calls_only():
    assert guarded("oe_seq_ack(5)") == (
        'local ok, e = pcall(oe_seq_ack, 5) if not ok then print("ERR " .. tostring(e)) end'
    )
    assert guarded("oe_seq_initialize()", prints=False).endswith(
        'if ok then print("OK") else print("ERR " .. tostring(e)) end'
    )
    for bad in (
        'oe_seq_ack("x")',
        "os.exit()",
        "oe_seq_ack(1) print(2)",
        "oe_seq_ack(" + "1" * 900 + ")",
    ):
        with pytest.raises(ValidationError):
            guarded(bad)


def test_parsers_reject_malformed_replies():
    assert parse_status("armed\ttrigger.STATE_RUNNING\t9\tsmu.ON\t12\t0").active
    assert parse_event(
        "2734\tTM path #1 block #1 logged: OE_T0\t4\t2\t1793715558\t381898180"
    ).time == (pytest.approx(1793715558.381898180))
    for reply in (
        "armed\tx",
        "armed\ttrigger.STATE_IDLE\t1.5\tsmu.OFF\t0\t0",
        "a\tb\t1\tsmu.MAYBE\t0\t0",
    ):
        with pytest.raises(TransportProtocolError):
            parse_status(reply)
    with pytest.raises(TransportProtocolError):
        parse_event("1003\tUser: OE_PING")


# Connection


def test_connect_installs_runtime_and_verifies_identity(instrument, clock):
    backend = make_backend(instrument, clock)
    backend.connect()
    assert instrument.g.oe_seq_runtime_build == "seq-v2"
    assert backend.inspect() == (DeviceState.IDLE, False)
    assert backend.equipment()["firmware"] == "1.7.16a"


@pytest.mark.parametrize(
    "change",
    [
        lambda i: setattr(i, "identity", replace(i.identity, firmware_version="1.7.12b")),
        lambda i: setattr(i, "command_language", "SCPI"),
        lambda i: setattr(i.g.localnode, "linefreq", 60),
        lambda i: setattr(i, "identity", replace(i.identity, serial_number="09999")),
    ],
)
def test_connect_refuses_unreviewed_instrument(instrument, clock, change):
    change(instrument)
    backend = make_backend(instrument, clock)
    with pytest.raises(IncompatibleInstrumentError):
        backend.connect()
    assert not instrument.connected


@pytest.mark.parametrize("serial", [None, "", "  "])
def test_the_expected_serial_number_is_required(instrument, clock, serial):
    with pytest.raises(ValidationError, match="expected_serial_number"):
        make_backend(instrument, clock, expected_serial_number=serial)
    with pytest.raises(ValidationError, match="expected_serial_number"):
        k2460_sequence_backend(
            "TCPIP0::192.0.2.1::5025::SOCKET", terminals="front", expected_serial_number=serial
        )


def test_connect_never_installs_under_a_running_model(instrument, clock):
    instrument.g.model_state = "trigger.STATE_RUNNING"
    with pytest.raises(IncompatibleInstrumentError, match="runtime build"):
        make_backend(instrument, clock).connect()
    assert instrument.g.oe_seq_runtime_abi is None


# Prepare


def test_prepare_uploads_program_and_maps_clock(backend, instrument, limits):
    request = pulse_request(limits)
    backend.prepare(request)
    g = instrument.g
    assert backend.inspect() == (DeviceState.PREPARED, False)
    assert g.oe_seq_state == "ready"
    assert (g.oe_seq_cfg.ready, g.oe_seq_cfg.busy, g.oe_seq_cfg.marker, g.oe_seq_cfg.start) == (
        1,
        2,
        4,
        6,
    )
    assert g.oe_seq_cfg.vlimit_max == pytest.approx(4.1)
    assert (
        g.offmodes["smu.FUNC_DC_CURRENT"]
        == g.offmodes["smu.FUNC_DC_VOLTAGE"]
        == "smu.OFFMODE_HIGHZ"
    )
    program = compile_program(request.sequence, limits)
    assert len(list(g.blocks.keys())) == len(program.blocks)
    equipment = backend.equipment()
    assert equipment["clock_offset_s"] == pytest.approx(CLOCK_OFFSET, abs=1e-3)
    assert 0 < equipment["clock_uncertainty_s"] <= 0.001
    assert equipment["block_count"] == len(program.blocks)
    assert equipment["marker_line"] == 4
    # Every line sent was a fixed query or a guarded packaged call.
    assert all(
        line.startswith(("print(", "local ok, e = pcall(oe_seq_")) for line in instrument.sent
    )


def test_runtime_refusal_reports_the_message_and_leaves_output_off(backend, instrument, limits):
    instrument.lua.execute('oe_seq_measure = function() error("boom") end')
    with pytest.raises(ElectrochemistryError, match="oe_seq_measure.*boom"):
        backend.prepare(pulse_request(limits))
    assert backend.inspect() == (DeviceState.IDLE, False)


def test_upload_warnings_fail_prepare(backend, instrument, limits):
    instrument.lua.execute(
        "local commit = oe_seq_commit "
        "oe_seq_commit = function() "
        'push_event(5076, "Source Limit changed to 0.21 V due to new measure Range", 2, 0) '
        "commit() end"
    )
    with pytest.raises(ElectrochemistryError, match="5076"):
        backend.prepare(pulse_request(limits))


def test_earlier_instrument_events_are_recorded_not_fatal(backend, instrument, limits):
    instrument.g.push_event(-363, "Input buffer overrun", 1, 0)
    backend.prepare(pulse_request(limits))
    assert backend.equipment()["pre_run_instrument_events"] == "-363 Input buffer overrun"


# Runs


def test_completed_run_matches_the_resistor_model(backend, instrument, limits, clock):
    request = pulse_request(limits)
    sim, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    assert backend.inspect() == (DeviceState.RUNNING, False)
    assert backend.time_origin_epoch_s() is None
    instrument.start()
    instrument.add(rows[:150])
    first = backend.poll(100)
    assert len(first.readout["t_s"]) == 100 and first.outcome is None
    assert backend.inspect() == (DeviceState.RUNNING, True)
    instrument.add(rows[150:])
    instrument.finish("end")
    readout, events, outcome, detail = drain(backend)
    readout = {k: np.concatenate([first.readout[k], readout[k]]) for k in READOUT_FIELDS}
    assert (outcome, detail) == ("completed", "")
    for key in ("step_index", "repeat_index", "measure_status", "source_status"):
        np.testing.assert_array_equal(readout[key], sim.readout[key])
    np.testing.assert_allclose(readout["t_s"], sim.readout["t_s"], atol=1e-6)
    np.testing.assert_allclose(readout["voltage_v"], sim.readout["voltage_v"])
    events = first.events + events
    assert [e[1:] for e in events] == [e[1:] for e in sim.events]
    assert backend.inspect() == (DeviceState.COMPLETE, False)
    assert backend.time_origin_epoch_s() == pytest.approx(T0 - CLOCK_OFFSET, abs=1e-3)


def test_reads_are_chunked_at_250_records(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.sent.clear()
    poll = backend.poll(600)
    assert len(poll.readout["t_s"]) == min(600, len(rows))
    reads = [line for line in instrument.sent if "oe_seq_read" in line]
    assert [r.split("pcall(oe_seq_read, ")[1].split(")")[0] for r in reads] == [
        "1, 250",
        "251, 250",
        "501, 100",
    ]


def test_logged_end_disagreeing_with_replay_is_an_error(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows[:-5])
    instrument.finish("end")
    *_, outcome, detail = drain(backend)
    assert outcome == "error"
    assert "predicted running, logged end" in detail


def test_instrument_error_during_run_fails_outcome(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.g.push_event(5077, "Cannot change source Limit", 1, T0 + 0.05)
    instrument.finish("end")
    _, events, outcome, detail = drain(backend)
    assert outcome == "error"
    assert "instrument 5077: Cannot change source Limit" in detail
    errors = [e for e in events if e[3] == "error"]
    assert errors and errors[0][0] == pytest.approx(0.05, abs=1e-6)


def test_stale_on_after_model_end_is_forced_off_and_fails(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.finish("end")
    instrument.g.src.output = "smu.ON"
    instrument.g.stale_on = True
    *_, outcome, detail = drain(backend)
    assert outcome == "error" and "forced OFF" in detail
    assert backend.inspect() == (DeviceState.COMPLETE, False)


def test_external_start_waits_then_runs(backend, instrument, limits):
    backend.prepare(pulse_request(limits, start_mode="external"))
    backend.kickoff()
    instrument.g.model_state = "trigger.STATE_WAITING"
    instrument.g.model_block = 2
    assert backend.inspect() == (DeviceState.WAITING_START, False)
    poll = backend.poll(100)
    assert len(poll.readout["t_s"]) == 0 and poll.outcome is None
    assert backend.time_origin_epoch_s() is None
    instrument.g.model_block = 9  # a later WAITING (not the START wait) is running
    assert backend.inspect()[0] == DeviceState.RUNNING


def test_abort_mid_run_drains_and_recovers(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows[:40])
    backend.poll(10)
    backend.abort("user")
    assert backend.inspect() == (DeviceState.ABORTED, False)
    assert instrument.g.digio.line[4].state == "LOW"
    readout, events, outcome, detail = drain(backend)
    assert (outcome, detail) == ("aborted", "user")
    assert len(readout["t_s"]) == 30
    assert events[-1][3:] == ("abort", "user")
    backend.recover()
    assert backend.inspect() == (DeviceState.IDLE, False)
    backend.prepare(request)  # all 40 records were read: acknowledged, not refused
    assert backend.inspect() == (DeviceState.PREPARED, False)


def test_abort_while_waiting_for_start(backend, instrument, limits):
    backend.prepare(pulse_request(limits, start_mode="external"))
    backend.kickoff()
    instrument.g.model_state = "trigger.STATE_WAITING"
    backend.abort("start timeout")
    _, events, outcome, _ = drain(backend)
    assert outcome == "aborted" and events == [(0.0, 0, 0, "abort", "start timeout")]


def test_abort_refuses_unconfirmed_off(backend, instrument, limits):
    backend.prepare(pulse_request(limits))
    backend.kickoff()
    instrument.g.src.output = "smu.ON"
    instrument.lua.execute('oe_seq_off = function() print("ON") end')
    with pytest.raises(ShutdownUnconfirmed):
        backend.abort("user")


def test_transport_timeout_needs_recover(backend, instrument, limits):
    backend.prepare(pulse_request(limits))
    backend.kickoff()
    instrument.fail_on = "oe_seq_status"
    with pytest.raises(TransportTimeoutError):
        backend.poll(10)
    assert backend.inspect() == (DeviceState.ERROR, None)
    with pytest.raises(ElectrochemistryError, match="recover"):
        backend.poll(10)
    instrument.fail_on = None
    backend.recover()
    assert backend.inspect() == (DeviceState.IDLE, False)
    assert instrument.g.model_state == "trigger.STATE_ABORTED"


@pytest.mark.parametrize(
    "change",
    [
        lambda i: setattr(i, "identity", replace(i.identity, serial_number="09999")),
        lambda i: setattr(i, "identity", replace(i.identity, firmware_version="1.7.12b")),
        lambda i: setattr(i, "command_language", "SCPI"),
    ],
)
def test_recover_refuses_another_instrument_after_a_broken_session(
    backend, instrument, limits, change
):
    backend.prepare(pulse_request(limits))
    backend.kickoff()
    instrument.fail_on = "oe_seq_status"
    with pytest.raises(TransportTimeoutError):
        backend.poll(10)
    instrument.fail_on = None
    change(instrument)  # the reconnect reaches a different or reconfigured instrument
    instrument.sent.clear()
    with pytest.raises(IncompatibleInstrumentError):
        backend.recover()
    assert instrument.sent == []  # nothing, in particular no OFF, was sent
    assert not instrument.connected
    assert backend.inspect() == (DeviceState.ERROR, None)


# Retained data


def test_unread_records_of_another_session_must_be_archived(instrument, clock, limits, tmp_path):
    first = make_backend(instrument, clock)
    first.connect()
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    first.prepare(request)
    first.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.finish("end")
    # The host process dies here; a new one connects to the same instrument.
    second = make_backend(instrument, clock)
    second.connect()
    assert second.inspect() == (DeviceState.IDLE, False)
    with pytest.raises(RetainedDataError, match=f"{len(rows)} unread records"):
        second.prepare(request)
    path = second.archive_retained(tmp_path / "retained.npz")
    with np.load(path) as saved:
        np.testing.assert_allclose(saved["reading"], [r[2] for r in rows])
        assert '"first_record": 1' in str(saved["metadata"])
    with pytest.raises(FileExistsError):
        second.archive_retained(path)
    second.prepare(request)
    assert second.inspect() == (DeviceState.PREPARED, False)


def test_consecutive_runs_acknowledge_read_records(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    for _ in range(2):
        instrument.records = []
        backend.prepare(request)
        backend.kickoff()
        instrument.start()
        instrument.add(rows)
        instrument.finish("end")
        assert drain(backend)[2] == "completed"
    assert instrument.g.oe_seq_acked == 0  # the second run's records are not yet acknowledged


# Through the Flyer and the RunEngine


def test_flyer_runs_under_a_plain_run_engine(backend, instrument, limits):
    """A test-local plan: the device needs no application plan or run file."""
    request = pulse_request(limits)
    expected, rows = instrument_records(request.sequence, limits)
    instrument.instant = (rows, "end")
    flyer = SequenceFlyer(backend, name="k2460", poll_period_s=0.01, chunk_records=97)
    re = RunEngine({}, call_returns_result=True)
    docs = []
    re.subscribe(lambda name, doc: docs.append((name, doc)))

    def plan():
        yield from bps.stage(flyer)
        yield from bps.prepare(flyer, request, wait=True)
        yield from bps.open_run(md={"equipment": flyer.equipment})
        yield from bps.kickoff(flyer, wait=True)
        yield from bps.collect_while_completing([flyer], [flyer], flush_period=0.05)
        yield from bps.close_run()
        yield from bps.unstage(flyer)
        return flyer.outcome

    assert re(plan()).plan_result == "completed"
    descriptor = next(d["uid"] for n, d in docs if n == "descriptor" and d["name"] == "readout")
    pages = [d for n, d in docs if n == "event_page" and d["descriptor"] == descriptor]
    np.testing.assert_array_equal(
        np.concatenate([p["data"]["step_index"] for p in pages]), expected.readout["step_index"]
    )
    start = next(d for n, d in docs if n == "start")
    assert start["equipment"]["backend"] == "k2460-sequencer"
    assert start["equipment"]["marker_line"] == 4
    # Unstaging closed the session with the output OFF.
    assert not instrument.connected and instrument.g.src.output == "smu.OFF"


def configured(instrument):
    return [c for c in instrument.sent if "oe_seq_configure" in c]


def test_secure_off_mode_sets_high_z_and_disconnects(instrument, clock, limits):
    assert instrument.g.offmodes["smu.FUNC_DC_VOLTAGE"] == "smu.OFFMODE_NORMAL"
    make_backend(instrument, clock).secure_off_mode(limits)
    g = instrument.g
    assert g.offmodes["smu.FUNC_DC_CURRENT"] == "smu.OFFMODE_HIGHZ"
    assert g.offmodes["smu.FUNC_DC_VOLTAGE"] == "smu.OFFMODE_HIGHZ"
    assert not instrument.connected


def test_secure_off_mode_fails_with_the_output_on(instrument, clock, limits):
    first = make_backend(instrument, clock)
    first.connect()
    first.close()
    instrument.g.src.output = "smu.ON"
    with pytest.raises(ElectrochemistryError, match="output is not OFF"):
        make_backend(instrument, clock, install_runtime=False).secure_off_mode(limits)
    assert not instrument.connected


def test_secure_off_mode_leaves_a_running_model_alone(instrument, clock, limits):
    first = make_backend(instrument, clock)
    first.connect()
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    first.prepare(request)
    first.kickoff()
    instrument.start()
    instrument.add(rows[:5])
    instrument.sent.clear()
    # A new host process opens the environment while the 2460 still runs.
    make_backend(instrument, clock).secure_off_mode(limits)
    assert not configured(instrument)
    assert instrument.g.src.output == "smu.ON"


def test_secure_off_mode_leaves_unread_records_alone(instrument, clock, limits, tmp_path):
    first = make_backend(instrument, clock)
    first.connect()
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    first.prepare(request)
    first.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.finish("end")
    instrument.sent.clear()
    make_backend(instrument, clock).secure_off_mode(limits)
    assert not configured(instrument)
    second = make_backend(instrument, clock)
    second.connect()
    with np.load(second.archive_retained(tmp_path / "retained.npz")) as saved:
        assert len(saved["reading"]) == len(rows)


def test_new_session_after_a_closed_run_prepares_without_archive(instrument, clock, limits):
    # The notebook builds a new backend per run: closing (unstage) acknowledges.
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    first = make_backend(instrument, clock)
    first.connect()
    first.prepare(request)
    first.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.finish("end")
    assert drain(first)[2] == "completed"
    first.close()
    assert instrument.g.oe_seq_acked == len(rows)
    second = make_backend(instrument, clock)
    second.connect()
    second.prepare(request)
    assert second.inspect() == (DeviceState.PREPARED, False)


def test_close_does_not_acknowledge_an_unfinished_read(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.finish("end")
    backend.poll(10)
    backend.close()
    assert instrument.g.oe_seq_acked == 0
    backend.connect()
    with pytest.raises(RetainedDataError):
        backend.prepare(request)


def test_recover_reconnects_after_the_flyer_closed_the_session(backend, instrument, limits):
    request = pulse_request(limits)
    _, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    backend.kickoff()
    instrument.start()
    instrument.add(rows[:20])
    backend.abort("user")
    drain(backend)
    backend.close()  # Flyer unstage after the abort
    assert not instrument.connected
    backend.recover()
    assert backend.inspect() == (DeviceState.IDLE, False)


def test_backend_refuses_programs_above_the_firmware_block_limit(instrument, clock, limits):
    from keithley2460_ophyd.sequencer import SequencerProfile

    with pytest.raises(ValidationError, match="exceeds the 2460's 63 trigger blocks"):
        make_backend(instrument, clock, profile=SequencerProfile(max_blocks=255))
    b = make_backend(instrument, clock)
    b.connect()
    request = SequenceRequest("too big", sequence_fixture("k2460_sequence_backend-08"), limits)
    with pytest.raises(ValidationError, match="83 trigger blocks exceed 63"):
        b.prepare(request)


def test_prepare_rechecks_the_block_count_before_upload(backend, instrument, limits, monkeypatch):
    from keithley2460_ophyd import sequence_backend
    from keithley2460_ophyd.sequencer import SequencerProfile

    def oversize(sequence, limits, profile, **kwargs):
        return compile_program(sequence, limits, SequencerProfile(max_blocks=255), **kwargs)

    monkeypatch.setattr(sequence_backend, "compile_program", oversize)
    sent = len(instrument.sent)
    request = SequenceRequest("too big", sequence_fixture("k2460_sequence_backend-08"), limits)
    with pytest.raises(ValidationError, match="83 trigger blocks exceed 63"):
        backend.prepare(request)
    assert not any("oe_seq_begin" in c for c in instrument.sent[sent:])
    assert backend.inspect() == (DeviceState.IDLE, False)


def test_an_older_runtime_build_on_the_instrument_is_refused(instrument, clock):
    instrument.lua.execute(sequencer_packaged_runtime().source)
    instrument.g.oe_seq_runtime_build = "seq-v1"  # what a runtime from before 264c63c reports
    with pytest.raises(IncompatibleInstrumentError, match="'seq-v1' is not 'seq-v2'"):
        make_backend(instrument, clock, install_runtime=False).connect()
    instrument.g.model_state = "trigger.STATE_RUNNING"  # observed, never reinstalled under
    with pytest.raises(IncompatibleInstrumentError, match="'seq-v1' is not 'seq-v2'"):
        make_backend(instrument, clock).connect()


def test_a_run_starting_on_the_lowest_range_uploads_and_completes(instrument, clock, limits):
    from keithley2460_ophyd.sequencer import SequencerProfile

    backend = make_backend(instrument, clock, profile=SequencerProfile(start_on_lowest_range=True))
    backend.connect()
    request = pulse_request(limits)
    sim, rows = instrument_records(request.sequence, limits)
    backend.prepare(request)
    equipment = backend.equipment()
    assert (equipment["source_1_range"], equipment["source_2_range"]) == (1e-6, 0.001)
    backend.kickoff()
    instrument.start()
    instrument.add(rows)
    instrument.finish("end")
    readout, _, outcome, detail = drain(backend)
    assert (outcome, detail) == ("completed", "")
    assert len(readout["t_s"]) == len(sim.readout["t_s"])
