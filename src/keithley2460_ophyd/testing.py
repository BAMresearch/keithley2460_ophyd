"""Test support: the packaged sequencer runtime in a Lua mock of the 2460.

``FakeInstrument`` is a ``SequenceTransport`` that executes every line the
backend sends in a Lua mock of the 2460's TSP API (``MOCK`` plus ``EXTRA``: an
event log, a reading buffer and a Python stand-in for the trigger model), so a
``Keithley2460SequenceBackend`` can run end to end without hardware. The mock
reproduces behaviour measured on the instrument: off mode is stored per source
function, a source-function change forces the output off, and
``smu.source.output`` can stay ON after an OFF command until such a change.

Needs the ``testing`` extra (``lupa``). Not used by the library itself.
"""

import math
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .exceptions import TransportProtocolError, TransportTimeoutError
from .models import SafetyLimits, Sequence, StepMode, expanded, sample_schedule, validate
from .sequencer_runtime import sequencer_packaged_runtime
from .transport import InstrumentIdentity

CLOCK_OFFSET = 4167.75  # instrument minus host UTC
T0 = 1_793_715_558.25  # instrument time of the OE_T0 event
SERIAL = "04567"  # synthetic serial number of the mocked instrument

MOCK = r"""
outputs = {}
print = function(...)
    local parts = {}
    for i = 1, select('#', ...) do parts[i] = tostring(select(i, ...)) end
    table.insert(outputs, table.concat(parts, "\t"))
end
log = {}
local function rec(...) table.insert(log, {...}) end

smu = {
    ON = "smu.ON", OFF = "smu.OFF",
    FUNC_DC_CURRENT = "smu.FUNC_DC_CURRENT", FUNC_DC_VOLTAGE = "smu.FUNC_DC_VOLTAGE",
    OFFMODE_HIGHZ = "smu.OFFMODE_HIGHZ", OFFMODE_NORMAL = "smu.OFFMODE_NORMAL",
    SENSE_2WIRE = "smu.SENSE_2WIRE", SENSE_4WIRE = "smu.SENSE_4WIRE",
    TERMINALS_FRONT = "smu.TERMINALS_FRONT", TERMINALS_REAR = "smu.TERMINALS_REAR",
    terminals = "smu.TERMINALS_FRONT",
}
src = { func = "smu.FUNC_DC_VOLTAGE", output = "smu.OFF", level = 0 }
offmodes = { ["smu.FUNC_DC_CURRENT"] = "smu.OFFMODE_NORMAL",
             ["smu.FUNC_DC_VOLTAGE"] = "smu.OFFMODE_NORMAL" }
stale_on = false
meas = { func = "smu.FUNC_DC_VOLTAGE" }
src_store, meas_store = {}, {}
smu.source = setmetatable({ vlimit = { level = 0 }, ilimit = { level = 0 }, configlist = {
    create = function(name) rec("src_create", name) end,
    delete = function(name) rec("src_delete", name) end,
    store = function(name)
        table.insert(src_store, { func = src.func, meas = meas.func, level = src.level,
            readback = src.readback, range = src.range,
            vlimit = smu.source.vlimit.level, ilimit = smu.source.ilimit.level })
    end,
} }, {
    __index = function(t, k)
        if k == "offmode" then return offmodes[src.func] end
        return src[k]
    end,
    __newindex = function(t, k, v)
        if k == "offmode" then offmodes[src.func] = v
        elseif k == "func" then
            if v ~= src.func then src.output = "smu.OFF"; stale_on = false end
            src.func = v
        elseif k == "output" then
            if not (v == "smu.OFF" and stale_on) then src.output = v end
        else src[k] = v end
    end,
})
smu.measure = setmetatable({ autozero = {}, configlist = {
    create = function(name) rec("meas_create", name) end,
    delete = function(name) rec("meas_delete", name) end,
    store = function(name)
        table.insert(meas_store, { func = meas.func, src = src.func, range = meas.range,
            nplc = meas.nplc, sense = meas.sense, autozero = smu.measure.autozero.enable })
    end,
} }, { __index = meas, __newindex = meas })

model_state = "trigger.STATE_EMPTY"
blocks = {}
trigger = {
    STATE_RUNNING = "trigger.STATE_RUNNING", STATE_WAITING = "trigger.STATE_WAITING",
    STATE_IDLE = "trigger.STATE_IDLE", STATE_EMPTY = "trigger.STATE_EMPTY",
    BLOCK_CONFIG_RECALL = "RECALL", BLOCK_SOURCE_OUTPUT = "OUTPUT",
    BLOCK_DIGITAL_IO = "DIGIO", BLOCK_DELAY_CONSTANT = "DELAY",
    BLOCK_MEASURE_DIGITIZE = "MEASURE", BLOCK_BRANCH_LIMIT_CONSTANT = "LIMIT",
    BLOCK_BRANCH_COUNTER = "COUNTER", BLOCK_RESET_BRANCH_COUNT = "RESET",
    BLOCK_WAIT = "WAIT", BLOCK_LOG_EVENT = "LOG", BLOCK_BRANCH_ALWAYS = "ALWAYS",
    LIMIT_OUTSIDE = "OUTSIDE", LIMIT_INSIDE = "INSIDE", CLEAR_ENTER = "CLEAR_ENTER",
    EDGE_RISING = "RISING", EDGE_FALLING = "FALLING",
    LOG_INFO1 = "INFO1", LOG_INFO2 = "INFO2", LOG_INFO3 = "INFO3", LOG_INFO4 = "INFO4",
    EVENT_DIGIO1 = "DIGIO1", EVENT_DIGIO2 = "DIGIO2", EVENT_DIGIO3 = "DIGIO3",
    EVENT_DIGIO4 = "DIGIO4", EVENT_DIGIO5 = "DIGIO5", EVENT_DIGIO6 = "DIGIO6",
    digin = {},
    model = {
        state = function() return model_state, model_state, 0 end,
        load = function(name) rec("load", name); blocks = {} end,
        setblock = function(i, ...) blocks[i] = {...} end,
        initiate = function() rec("initiate"); model_state = "trigger.STATE_RUNNING" end,
        abort = function() rec("abort"); model_state = "trigger.STATE_IDLE" end,
    },
}
for i = 1, 6 do
    trigger.digin[i] = { clear = function() rec("digin_clear", i) end }
end
digio = { MODE_DIGITAL_OUT = "OUT", MODE_TRIGGER_IN = "TRIGIN",
          STATE_LOW = "LOW", STATE_HIGH = "HIGH", line = {} }
for i = 1, 6 do digio.line[i] = {} end
buffers = {}
buffer = {
    STYLE_STANDARD = "STD",
    make = function(capacity, style)
        local b = { n = 0, capacity = capacity, seconds = "S", fractionalseconds = "F",
            readings = "R", sourcevalues = "V", statuses = "ST", sourcestatuses = "SS" }
        table.insert(buffers, b)
        return b
    end,
    delete = function(b) rec("buffer_delete"); b.deleted = true end,
}
eventlog = { SEV_INFO = "INFO", post = function(m, s) rec("post", m, s) end }
format = { asciiprecision = 0 }
printbuffer = function(...) rec("printbuffer", ...) end
"""

EXTRA = r"""
localnode = { linefreq = 50 }
clock_s = 0
events = {}
function push_event(number, message, severity, t)
    local s = math.floor(t)
    table.insert(events, { number, message, severity, 2, s, math.floor((t - s) * 1e9 + 0.5) })
end
eventlog.SEV_ALL = "ALL"
eventlog.getcount = function(sev) return #events end
eventlog.next = function(sev)
    local e = table.remove(events, 1)
    return e[1], e[2], e[3], e[4], e[5], e[6]
end
eventlog.post = function(m, s) push_event(1003, "User: " .. m, 4, clock_s) end
trigger.STATE_ABORTED = "trigger.STATE_ABORTED"
trigger.STATE_FAILED = "trigger.STATE_FAILED"
model_block = 0
trigger.model.state = function() return model_state, model_state, model_block end
trigger.model.abort = function()
    table.insert(log, { "abort" })
    if model_state == "trigger.STATE_RUNNING" or model_state == "trigger.STATE_WAITING" then
        model_state = "trigger.STATE_ABORTED"
    end
end
trigger.model.initiate = function()
    table.insert(log, { "initiate" })
    model_state = "trigger.STATE_RUNNING"
    on_initiate()
end
printbuffer = function(first, last, ...) print(py_printbuffer(first, last)) end
"""


class FakeClock:
    def __init__(self):
        self.now = 1_793_711_390.0

    def __call__(self):
        self.now += 0.001
        return self.now


class FakeInstrument:
    """Transport whose instrument is the packaged runtime in a mocked 2460."""

    def __init__(
        self, clock: Callable[[], float], *, firmware: str = "1.7.16a", language: str = "TSP"
    ) -> None:
        self.clock = clock
        import lupa.lua51 as lupa

        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK)
        self.g = self.lua.globals()
        self.g.py_printbuffer = self._printbuffer
        self.g.on_initiate = self._on_initiate
        self.lua.execute(EXTRA)
        self.identity = InstrumentIdentity(
            "KEITHLEY INSTRUMENTS",
            "2460",
            SERIAL,
            firmware,
            f"KEITHLEY INSTRUMENTS,MODEL 2460,{SERIAL},{firmware}",
        )
        self.command_language = language
        self.connected = False
        self.records: list[tuple[float, ...]] = []
        self.sent: list[str] = []
        self.instant = None  # (records, logged) produced as soon as the model starts
        self.fail_on: str | None = None

    # Transport

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def query(self, command):
        if not self.connected:
            raise TransportTimeoutError("not connected")
        if self.fail_on is not None and self.fail_on in command:
            self.connected = False
            raise TransportTimeoutError(f"timed out during {command!r}; session invalidated")
        self.sent.append(command)
        self.g.clock_s = self.clock() + CLOCK_OFFSET
        self.g.outputs = self.lua.table()
        self.lua.execute(command)
        lines = list(self.g.outputs.values())
        if not lines:
            self.connected = False
            raise TransportTimeoutError(f"no reply to {command!r}; session invalidated")
        if len(lines) > 1:
            raise TransportProtocolError(f"{len(lines)} reply lines to {command!r}")
        return lines[0]

    def load_runtime(self, source, *, abi, sha256):
        artifact = sequencer_packaged_runtime()
        assert (source, abi, sha256) == (artifact.source, artifact.abi, artifact.sha256)
        assert self.g.src.output == "smu.OFF"
        if self.g.oe_seq_runtime_abi is None:
            self.lua.execute(source)
        self.g.oe_seq_initialize()

    # Instrument side

    def _printbuffer(self, first, last):
        rows = self.records[int(first) - 1 : int(last)]
        return ", ".join(repr(float(v)) for row in rows for v in row)

    def _on_initiate(self):
        if self.instant is not None:
            records, logged = self.instant
            self.start()
            self.add(records)
            self.finish(logged)

    def log(self, name, t, block=3):
        self.g.push_event(2734, f"TM path #1 block #{block} logged: {name}", 4, t)

    def start(self, t0=T0):
        self.log("OE_T0", t0, 1)
        self.g.src.output = "smu.ON"

    def add(self, rows):
        self.records.extend(rows)
        self.g.oe_seq_buf.n = len(self.records)

    def finish(self, logged="end", t=None):
        t = (self.records[-1][0] + self.records[-1][1] if self.records else T0) if t is None else t
        self.log("OE_END" if logged == "end" else "OE_STOP", t + 0.001)
        self.log("OE_DONE", t + 0.001)
        self.g.model_state = "trigger.STATE_IDLE"
        self.g.src.output = "smu.OFF"


def resistor_records(
    sequence: Sequence,
    limits: SafetyLimits,
    *,
    resistance_ohm: float = 100.0,
    offset_v: float = 0.5,
    t0: float = T0,
) -> tuple[dict[str, NDArray[Any]], list[tuple[Any, ...]]]:
    """Expected readout and buffer rows of a voltage source behind a resistor.

    Rows are ``(seconds, fraction, reading, source value, measure status, source
    status)`` as the runtime stores them, sampled on the step's own schedule.
    The model has no cutoffs: choose sequences whose readings stay inside every
    step and absolute limit, so the run completes.
    """
    validate(sequence, limits)
    names = ("t_s", "voltage_v", "current_a", "step_index", "repeat_index")
    columns: dict[str, list[float]] = {name: [] for name in names}
    rows: list[tuple[Any, ...]] = []
    time_s = 0.0
    for step_index, repeat_index, step in expanded(sequence):
        phase_start = 0.0
        for count, interval in sample_schedule(step):
            for k in range(1, count + 1):
                if step.mode == StepMode.VOLTAGE:
                    voltage, current = step.level, (step.level - offset_v) / resistance_ohm
                    reading, source = current, voltage
                else:
                    current = step.level
                    voltage = offset_v + current * resistance_ohm
                    reading, source = voltage, current
                t_s = time_s + phase_start + k * interval
                for name, value in zip(
                    names, (t_s, voltage, current, step_index, repeat_index), strict=True
                ):
                    columns[name].append(value)
                t = t0 + t_s
                rows.append((math.floor(t), t - math.floor(t), reading, source, 0, 0))
            phase_start += count * interval
        time_s += step.duration_s
    readout = {
        name: np.asarray(values, dtype="f8" if i < 3 else "i4")
        for i, (name, values) in enumerate(columns.items())
    }
    size = len(rows)
    readout["source_status"] = np.zeros(size, dtype="i4")
    readout["measure_status"] = np.zeros(size, dtype="i4")
    return readout, rows
