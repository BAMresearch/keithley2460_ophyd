"""Realistic protocol sequences, frozen as data for the compiler and backend tests.

``fixtures/sequences.json`` holds each sequence's ``to_dict`` form and the
protocol-builder call (in ``electrochemistry-bluesky``) that produced it. The
device tests need representative sequences, not the builders themselves.
"""

import json
from functools import cache
from pathlib import Path

from keithley2460_ophyd.models import Sequence, sequence_from_dict


@cache
def _fixtures() -> dict[str, dict]:
    path = Path(__file__).with_name("fixtures") / "sequences.json"
    return json.loads(path.read_text(encoding="utf-8"))


def sequence_fixture(name: str) -> Sequence:
    return sequence_from_dict(_fixtures()[name]["sequence"])
