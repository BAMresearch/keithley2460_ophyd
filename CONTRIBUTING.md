# Contributing

- Keep the package instrument-only: it must not import application, data-file,
  plotting or QueueServer packages (`tests/test_import_boundary.py` checks this).
- Timing, cutoffs and output control run on the instrument. The host never
  paces samples, never retries a command whose delivery is uncertain, and never
  reports an aborted run as completed.
- Only the packaged runtime may be uploaded. A change to `tsp/sequencer.tsp`
  bumps `SEQUENCER_BUILD`, updates the pinned digest in the tests, and is
  reviewed and checked on a dummy load before it is used with a cell.
- Encode measured instrument behaviour in the Lua mock
  (`keithley2460_ophyd.testing`) together with a test. Do not change what the
  documentation claims about hardware on the basis of simulation alone.
- Use the official Keithley 2460 Reference Manual for commands and limits, and
  mark anything unverified as such.
- Run the tests, ruff and mypy before opening a pull request (see README).
  Commits follow Conventional Commits; do not bump versions by hand.
