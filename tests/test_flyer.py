"""SequenceFlyer lifecycle on a minimal SequenceBackend and a plain RunEngine.

The fake backend releases a fixed readout on poll; it models no instrument or
cell. The 2460 backend under a RunEngine is in test_k2460_sequence_backend.py.
"""

import threading

import numpy as np
import pytest
from bluesky import RunEngine
from bluesky import plan_stubs as bps
from bluesky import preprocessors as bpp

from keithley2460_ophyd import (
    READOUT_FIELDS,
    DeviceState,
    SafetyLimits,
    Sampling,
    Sequence,
    SequenceFlyer,
    SequencePoll,
    SequenceRequest,
    rest_step,
)


class ListBackend:
    """A SequenceBackend that releases ``records`` rows per poll once kicked off."""

    def __init__(self, total: int, *, records: int = 4, hold: bool = False) -> None:
        self.total, self.records, self.hold = total, records, hold
        self.state, self.sent, self.aborts = DeviceState.IDLE, 0, []
        self.lock = threading.Lock()

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def inspect(self):
        with self.lock:
            return self.state, self.state == DeviceState.RUNNING

    def equipment(self):
        return {"backend": "list"}

    def prepare(self, request: SequenceRequest) -> None:
        with self.lock:
            self.state, self.sent = DeviceState.PREPARED, 0

    def kickoff(self) -> None:
        with self.lock:
            self.state = DeviceState.RUNNING

    def time_origin_epoch_s(self):
        return 1_700_000_000.0

    def poll(self, max_records: int) -> SequencePoll:
        with self.lock:
            if self.state == DeviceState.ABORTED:
                return SequencePoll(self._rows(0), [], "aborted", self.aborts[-1])
            n = 0 if self.hold else min(self.records, max_records, self.total - self.sent)
            readout = self._rows(n)
            self.sent += n
            outcome = None
            if self.sent == self.total:
                self.state, outcome = DeviceState.COMPLETE, "completed"
            return SequencePoll(readout, [], outcome)

    def _rows(self, n: int):
        t = 0.1 * np.arange(self.sent + 1, self.sent + n + 1)
        rows = {
            name: np.zeros(n, dtype="f8" if i < 3 else "i4")
            for i, name in enumerate(READOUT_FIELDS)
        }
        rows["t_s"] = t
        return rows

    def abort(self, reason: str) -> None:
        with self.lock:
            if self.state == DeviceState.RUNNING:
                self.state = DeviceState.ABORTED
                self.aborts.append(reason)

    def recover(self) -> None:
        with self.lock:
            self.state = DeviceState.IDLE


@pytest.fixture
def request_():
    limits = SafetyLimits(0, 4, 0.01, 1000, 1000)
    return SequenceRequest("rest", Sequence((rest_step(1.0, Sampling(0.1)),)), limits)


def fly(flyer, request):
    """A test-local plan; the production plan belongs to the application."""

    def body():
        yield from bps.kickoff(flyer, wait=True)
        yield from bps.collect_while_completing([flyer], [flyer], flush_period=0.02)
        return flyer.outcome

    yield from bps.stage(flyer)
    yield from bps.prepare(flyer, request, wait=True)
    yield from bpp.run_wrapper(
        bpp.finalize_wrapper(body(), bps.stop(flyer)), md={"plan_name": "fly"}
    )
    yield from bps.unstage(flyer)
    return flyer.outcome


def readout_rows(docs):
    descriptor = next(d["uid"] for n, d in docs if n == "descriptor" and d["name"] == "readout")
    pages = [d for n, d in docs if n == "event_page" and d["descriptor"] == descriptor]
    return np.concatenate([p["data"]["t_s"] for p in pages]) if pages else np.array([])


def test_completed_run_emits_every_record(request_):
    backend = ListBackend(10)
    flyer = SequenceFlyer(backend, name="k2460", poll_period_s=0.01)
    re = RunEngine({}, call_returns_result=True)
    docs = []
    re.subscribe(lambda name, doc: docs.append((name, doc)))
    assert re(fly(flyer, request_)).plan_result == "completed"
    np.testing.assert_allclose(readout_rows(docs), 0.1 * np.arange(1, 11))
    stop = next(d for n, d in docs if n == "stop")
    assert stop["exit_status"] == "success"
    assert backend.state == DeviceState.COMPLETE and not backend.aborts


def test_abort_is_never_reported_as_success(request_):
    backend = ListBackend(10, hold=True)  # never finishes on its own
    flyer = SequenceFlyer(backend, name="k2460", poll_period_s=0.01)
    re = RunEngine({}, call_returns_result=True)
    docs = []
    re.subscribe(lambda name, doc: docs.append((name, doc)))
    threading.Timer(0.2, re.abort, kwargs={"reason": "operator"}).start()
    with pytest.raises(Exception):  # noqa: B017 - RunEngine raises its own interrupt type
        re(fly(flyer, request_))
    assert backend.aborts, "the backend was not aborted"
    assert flyer.outcome == "aborted"
    stop = next(d for n, d in docs if n == "stop")
    assert stop["exit_status"] != "success"


def test_prepare_refuses_an_unstaged_flyer(request_):
    flyer = SequenceFlyer(ListBackend(1), name="k2460")
    status = flyer.prepare(request_)
    with pytest.raises(Exception):  # noqa: B017 - the status carries the refusal
        status.wait(timeout=5)
