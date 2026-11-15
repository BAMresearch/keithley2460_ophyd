# keithley2460-ophyd

An [ophyd](https://blueskyproject.io/ophyd/) Flyer for the Keithley 2460
SourceMeter that runs finite source/measure sequences **on the instrument**.
The host compiles a validated sequence of constant-current, constant-voltage and
rest steps into a trigger model of at most 63 blocks, uploads it to a packaged,
reviewed TSP runtime, and reads the stored readings back in bounded chunks. The
2460 itself times every sample, checks the voltage limits after every reading,
drives the digital marker, READY and BUSY lines and switches the output OFF at
the end. The host never paces samples and never sends user-written TSP.

```text
Sequence + SafetyLimits ──► SequenceRequest
                                 │
SequenceFlyer (classic ophyd Flyer: stage, prepare, kickoff, complete, collect, stop)
                                 │  SequenceBackend protocol
Keithley2460SequenceBackend ─► compile_program / Replayer (pure)
                                 │  PyVISA, one owner
packaged TSP runtime on the 2460 (trigger model: timing, cutoffs, markers, output OFF)
```

This package covers the instrument only. Experiment protocols, Excel run
sheets, a QueueServer deployment, HDF5 run files and a synthetic-cell simulator
built on it are in
[electrochemistry-bluesky](https://github.com/BAMresearch/electrochemistry_bluesky).

**Status:** alpha. Supports the Keithley 2460 (firmware 1.7.16a tested) over
LAN with TSP. Not yet released on PyPI.

## Install

```sh
pip install "keithley2460-ophyd[visa]"   # once released; from a checkout: uv sync --extra visa
```

Python 3.11 or later; development and testing use 3.14.

## Use

A sequence is a tuple of `Step`s with an optional repeat block, validated
against explicit `SafetyLimits` before anything reaches the instrument:

```python
from bluesky import RunEngine
from bluesky import plan_stubs as bps

from keithley2460_ophyd import (
    SafetyLimits,
    Sampling,
    Sequence,
    SequenceFlyer,
    SequenceRequest,
    cc_step,
    k2460_sequence_backend,
    rest_step,
)

limits = SafetyLimits(
    v_min_abs=0.0, v_max_abs=2.0, i_max_abs=0.01, max_duration_s=600, max_records=100_000
)
sequence = Sequence(
    (
        rest_step(10, Sampling(0.1)),
        cc_step(0.001, target_v=1.5, max_duration_s=60, sampling=Sampling(0.1)),
        rest_step(10, Sampling(0.1)),
    )
)
request = SequenceRequest("demo-001", sequence, limits)

backend = k2460_sequence_backend(
    "TCPIP0::<instrument-ip>::5025::SOCKET",
    terminals="front",
    expected_serial_number="<serial>",  # connect refuses any other instrument
)
flyer = SequenceFlyer(backend, name="k2460")


def plan():
    yield from bps.stage(flyer)
    yield from bps.prepare(flyer, request, wait=True)
    yield from bps.open_run()
    yield from bps.kickoff(flyer, wait=True)
    yield from bps.collect_while_completing([flyer], [flyer], flush_period=1.0)
    yield from bps.close_run()
    yield from bps.unstage(flyer)


RunEngine()(plan())
```

Nothing is sent to the instrument on import or construction; `stage` connects.
A production plan should also stop and drain the Flyer on interruption (see
`run_sequence` in electrochemistry-bluesky).

`k2460-diagnose --resource '<VISA resource>' --backend '@py'` checks the
connection read-only: identity, command language and output state.

## Safety model

- Every request is finite and validated against `SafetyLimits` before arming;
  the runtime checks every uploaded value again.
- In current and rest steps the absolute voltage window is a STOP branch after
  every reading, evaluated by the 2460; compliance sits 0.1 V outside it.
- Output-off mode is **HIGH-Z** for both source functions, set and read back
  at every prepare, so an idle output does not drive a connected cell.
- Output OFF is confirmed by read-back at every terminal state. An aborted run
  is never reported as completed. Uncertain commands are never retried.
- `prepare` refuses while unread records of an earlier run remain on the
  instrument; `archive_retained` saves them first.
- Only the exact packaged runtime (`tsp/sequencer.tsp`, ABI `oe-k2460-seq-v1`)
  can be uploaded; its build and SHA-256 are checked after installation.

The instrument does not watch the voltage between readings, and it cannot
protect a cell before a session has set HIGH-Z: after power-on the 2460's
output-off mode is NORMAL. Call `backend.secure_off_mode(limits)` (connect,
set HIGH-Z with read-back, disconnect) before connecting a cell, and disconnect
the cell before switching the 2460 off. Do not claim timing beyond what the reading timestamps show.

## Documentation

- [Sequencer runtime design](docs/sequencer.md): block layout, timing, cutoffs,
  time base, runtime API and the measured instrument facts it rests on.
- `keithley2460_ophyd.testing`: the packaged runtime in a Lua mock of the 2460
  (needs the `testing` extra), for offline tests of code that uses the backend.

## Development

```sh
uv sync --locked --group dev --extra visa
uv run --locked pytest            # no test touches an instrument
uv run --locked ruff check . && uv run --locked ruff format --check .
uv run --locked mypy src
```

Any change to `tsp/sequencer.tsp` bumps `SEQUENCER_BUILD` (a test pins the
build to the source digest) and needs a review and a dummy-load check on the
instrument before it is used with a cell.

## Acknowledgments

Parts of the code were implemented with the assistance of OpenAI Codex and
Anthropic Claude, and were reviewed and tested by the authors. We are aware
that tools of this kind are built on knowledge and code contributed by people
who were never asked, and who cannot be credited individually here. We thank
them nonetheless.

## License

[BSD 3-Clause](LICENSE.md). No Keithley manuals or example code are
redistributed.
