# Changelog

<!-- version list -->

Initial public release of the Keithley 2460 sequencer path, extracted from an
internal development repository:

- Finite sequence models (`Step`, `Sequence`, `Sampling`, `SafetyLimits`,
  validation) and generic step constructors.
- `SequenceRequest` / `SequencePoll` / `SequenceBackend` protocol and the
  classic-ophyd `SequenceFlyer`.
- `Keithley2460SequenceBackend`: pure compiler and replay, PyVISA transport,
  packaged TSP sequencer runtime (ABI `oe-k2460-seq-v1`, build `seq-v2`).
- `k2460-diagnose`: read-only connection check.
- `keithley2460_ophyd.testing`: the runtime in a Lua mock of the 2460.
