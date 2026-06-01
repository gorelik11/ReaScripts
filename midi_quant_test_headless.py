#!/usr/bin/env python3
"""Headless harness for MIDI Adaptive Quantize checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("MIDI Adaptive Quantize V1.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("midi_quant_v1", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entrypoint_presence() -> None:
    module = load_module(SCRIPT_PATH)
    assert hasattr(module, "run_quantize"), "Missing run_quantize(config=None)"


TESTS = [test_entrypoint_presence]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
