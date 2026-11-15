"""The packaged TSP runtime as the host checks and installs it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeArtifact:
    """Exact packaged source plus the globals the installer verifies after upload."""

    abi: str
    build: str
    source: str
    sha256: str
    script_name: str
    abi_variable: str
    build_variable: str
    initializer: str
