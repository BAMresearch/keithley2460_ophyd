# Changelog

<!-- version list -->

## v0.2.0 (2026-11-23)

### Bug Fixes

- **sequencer**: One current measure range for all CV holds; refuse limits it would move
  ([`d3fe445`](https://github.com/BAMresearch/keithley2460_ophyd/commit/d3fe445129a2ec78caeed45df02c76f67bcdce94))

- **transport**: Try a VISA open that timed out again; name the cause
  ([`7f1caba`](https://github.com/BAMresearch/keithley2460_ophyd/commit/7f1caba597cf85570e749f451a7c79d0f4182aba))

### Continuous Integration

- Start CI on the release branch for the release PR
  ([`996f914`](https://github.com/BAMresearch/keithley2460_ophyd/commit/996f9147832aa1c3843f40c0c508569a7ec9c91c))

### Features

- **steps**: A CV hold can take its own current limit
  ([`4c7f4be`](https://github.com/BAMresearch/keithley2460_ophyd/commit/4c7f4be39344cb6fdc08836340e3beb8cdf7f57f))


## v0.1.0 (2026-11-16)

- Initial Release

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
