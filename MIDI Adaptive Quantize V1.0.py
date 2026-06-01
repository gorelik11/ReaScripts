#!/usr/bin/env python3
"""MIDI Adaptive Quantize V1.0 — quantize only off-grid MIDI note starts."""

from __future__ import annotations

import math


def run_quantize(config=None):
    config = config or {}
    if config.get("headless"):
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}
    return _run_in_reaper(config)


def _run_in_reaper(config):
    raise NotImplementedError("REAPER path added in Task 7")


def main():
    # A REAPER ReaScript runs in an embedded interpreter; NEVER raise SystemExit
    # / sys.exit() / exit() — it routes to Py_Exit and kills the whole REAPER
    # process. Just call run_quantize and return normally.
    run_quantize()


if __name__ == "__main__":
    main()
