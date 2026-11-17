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

## Releases

Releases come from `main` through a release pull request (python-semantic-release,
configured in `pyproject.toml`):

1. After the checks pass on `main`, CI opens or updates the PR
   `chore(release): vX.Y.Z` from the commits since the last tag: `feat` gives a
   minor version, `fix` and `perf` a patch (major versions only after 1.0).
   It sets `__version__` and adds the version's section to `CHANGELOG.md`;
   edit the notes on its branch if needed.
2. The same job starts CI on the release branch, whose checks appear on the PR
   (checks of a PR opened with the workflow token do not start by themselves).
   If they are missing, run CI on `release/next` from the Actions tab. Then
   merge it.
3. The merge tags `vX.Y.Z` and creates the GitHub release from the changelog
   section. With the repository variable `PYPI_PUBLISH` set to `true` (and a
   PyPI trusted publisher for this repository's `ci.yml`, environment `pypi`),
   the same run uploads the package to PyPI.
