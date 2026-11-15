"""The device package imports no application, data-file or QueueServer code."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "keithley2460_ophyd"
FORBIDDEN = (
    "electrochemistry_bluesky",
    "ophyd_electrochemistry",
    "bluesky_queueserver",
    "h5py",
    "pandas",
    "openpyxl",
    "plotly",
    "nbformat",
)
MODULES = sorted(
    f"keithley2460_ophyd.{p.stem}" for p in PACKAGE.glob("*.py") if p.stem != "__init__"
)


def test_no_module_imports_a_forbidden_package():
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in FORBIDDEN, f"{path.name} imports {name}"


@pytest.mark.parametrize("module", ["keithley2460_ophyd", *MODULES])
def test_importing_loads_no_forbidden_package(module):
    # A fresh interpreter, so modules loaded by other tests do not count.
    code = (
        "import sys, importlib; importlib.import_module(sys.argv[1]); "
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {FORBIDDEN!r}); "
        "print(','.join(bad))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, module], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_packaged_runtime_is_readable_from_the_installed_package():
    from keithley2460_ophyd import sequencer_packaged_runtime

    assert sequencer_packaged_runtime().source.startswith("--")
