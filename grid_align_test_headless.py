#!/usr/bin/env python3
"""Headless harness for Grid Align Transients task checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("Grid Align Transients V1.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("grid_align_v1", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entrypoint_presence() -> None:
    module = load_module(SCRIPT_PATH)
    assert hasattr(module, "run_grid_align"), "Missing run_grid_align(config=None) entrypoint"


def main() -> int:
    test_entrypoint_presence()
    print("PASS: run_grid_align entrypoint present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
