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


def test_scope_and_guards() -> None:
    module = load_module(SCRIPT_PATH)
    ts = module.resolve_processing_scope(
        {"time_selection": (1.0, 2.0), "selected_items": [object()], "all_items": []}
    )
    assert ts["mode"] == "time_selection"
    assert ts["range"] == (1.0, 2.0)

    sel = module.resolve_processing_scope({"selected_items": [1, 2], "all_items": [9]})
    assert sel["mode"] == "selected_items"

    full = module.resolve_processing_scope({"all_items": [9]})
    assert full["mode"] == "full_range"

    assert module.should_skip_item({"playrate": 1.25, "reversed": 0, "section": 0}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 1, "section": 0}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 0, "section": 1}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 0, "section": 0}) is False


def main() -> int:
    test_entrypoint_presence()
    test_scope_and_guards()
    print("PASS: scope + guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
