"""Task 4 of docs/superpowers/plans/2026-09-24-rcbitnova-v16-analyzer.md.

These tests prove the ALGORITHM, in Python. They do not prove its EEL2 transcription or its
connection to mbwpos, placement, slider timing and the retained rings - that is what the
transition nulls in Task 7 are for. Keeping the two apart is deliberate: a green oracle here and
a red null there localises the bug to the transcription in one step.
"""
import random

import pytest

from tools.rcbitnova_wedge import Wedge, brute_max, run_reference, run_wedge

MAX_LOOK = 2048
ALWAYS = (lambda n: True)


def test_matches_brute_force_on_random_data():
    random.seed(7)
    sig = [random.random() for _ in range(5000)]
    assert run_wedge(sig, lambda n: 192, ALWAYS) == run_reference(sig, lambda n: 192, ALWAYS)


def test_matches_across_an_lk_change_midstream():
    # the principal risk in the change: a shortened window after the knob moves would make the
    # null stop being an exact zero
    random.seed(8)
    sig = [random.random() for _ in range(5000)]
    lk = lambda n: 192 if n < 2500 else 960            # noqa: E731
    assert run_wedge(sig, lk, ALWAYS) == run_reference(sig, lk, ALWAYS)


def test_matches_when_lk_shrinks_as_well_as_grows():
    random.seed(9)
    sig = [random.random() for _ in range(4000)]
    lk = lambda n: 960 if n < 2000 else 100            # noqa: E731
    assert run_wedge(sig, lk, ALWAYS) == run_reference(sig, lk, ALWAYS)


def test_equal_runs_do_not_diverge():
    # ties are where a `<` / `<=` slip shows: the queue drops equals, the rescan keeps them,
    # and both must still report the same maximum
    sig = [0.5] * 3000
    assert run_wedge(sig, lambda n: 100, ALWAYS) == run_reference(sig, lambda n: 100, ALWAYS)


def test_a_single_spike_leaves_the_window_at_the_right_sample():
    sig = [0.0] * 500
    sig[10] = 1.0
    lk = 64
    ref = run_reference(sig, lambda n: lk, ALWAYS)
    assert run_wedge(sig, lambda n: lk, ALWAYS) == ref
    assert ref[10 + lk] == 1.0 and ref[10 + lk + 1] == 0.0


def test_strictly_decreasing_at_max_capacity_never_overflows():
    lk = MAX_LOOK - 1
    w = Wedge(cap=MAX_LOOK + 1)
    for n in range(lk + 50):
        w.push(1.0 - n * 1e-6, n % MAX_LOOK)
        if n >= lk + 1:
            w.evict((n - lk - 1) % MAX_LOOK)
        assert w.count() <= w.cap


def test_a_2048_slot_buffer_would_overflow_at_the_clamp():
    # the reason DQ_CAP is MAX_LOOK + 1 and not MAX_LOOK: push-before-evict makes occupancy
    # transiently Lk + 2. Reachable only at 352.8/384 kHz, so every 96 kHz null would pass.
    lk = MAX_LOOK - 1
    w = Wedge(cap=MAX_LOOK)
    with pytest.raises(AssertionError):
        for n in range(lk + 50):
            w.push(1.0 - n * 1e-6, n % MAX_LOOK)
            if n >= lk + 1:
                w.evict((n - lk - 1) % MAX_LOOK)


# The minimal skipped-lane case, found by exhaustive search rather than by hand. A ring of 8 and
# Lk = 3 so positions genuinely ROTATE: with the production MAX_LOOK of 2048 a short signal never
# wraps, the "stale" cells are simply zeros, and a hand-written eight-sample case passes whether
# the queue rebuilds or not. That version of this test was decorative and was replaced.
STALE_SIG = [4.0, 9.0, 4.0, 1.0, 9.0, 4.0, 4.0, 1.0, 1.0, 4.0]
STALE_SKIP = {8}
STALE_ML, STALE_LK = 8, 3


def _stale_active(n):
    return n not in STALE_SKIP


def test_skipped_lane_reproduces_the_stale_maximum():
    # V1.5 writes lane B only while the band is in Both, but the band's cursor advances anyway
    # (V1.5:2230 sits outside the `two ?` block at 2175-2182). After Both -> Mid -> Both the
    # rescan reads STALE ring values and limits on them. The queue must agree, defect included.
    assert run_wedge(STALE_SIG, lambda n: STALE_LK, _stale_active, STALE_ML) == \
           run_reference(STALE_SIG, lambda n: STALE_LK, _stale_active, STALE_ML)


def test_the_stale_case_would_catch_a_queue_that_never_rebuilt():
    # This is the guard that makes the test above worth having: a queue that pushes and evicts
    # without ever rebuilding reports 9.0 at index 9 where the rescan reports 4.0 - the exact
    # divergence the design review predicted. If this ever stops failing, the case has gone
    # vacuous and must be re-derived.
    peaks = [0.0] * STALE_ML
    w = Wedge(STALE_ML + 1)
    wp, out, started = 0, [], False
    for n, s in enumerate(STALE_SIG):
        if _stale_active(n):
            peaks[wp] = abs(s)
            if not started:
                w.rebuild(peaks, wp, STALE_LK, STALE_ML)
                started = True
            w.push(peaks[wp], wp)
            w.evict((wp - STALE_LK - 1 + STALE_ML) % STALE_ML)
            out.append(w.top())
        else:
            out.append(None)
        wp = (wp + 1) % STALE_ML
    ref = run_reference(STALE_SIG, lambda n: STALE_LK, _stale_active, STALE_ML)
    assert out != ref
    assert (ref[9], out[9]) == (4.0, 9.0)


def test_a_long_inactive_stretch_still_agrees():
    random.seed(11)
    sig = [random.random() for _ in range(3000)]
    active = (lambda n: not (700 <= n < 1500))
    assert run_wedge(sig, lambda n: 192, active) == run_reference(sig, lambda n: 192, active)


def test_an_lk_change_that_happens_while_the_lane_is_inactive():
    # the pending change must survive until the lane next processes, or a lane is marked clean
    # that never rebuilt
    random.seed(12)
    sig = [random.random() for _ in range(3000)]
    active = (lambda n: not (1000 <= n < 1400))
    lk = lambda n: 192 if n < 1200 else 500            # noqa: E731
    assert run_wedge(sig, lk, active) == run_reference(sig, lk, active)


def test_brute_max_is_the_window_and_nothing_else():
    peaks = [0.0] * MAX_LOOK
    peaks[0], peaks[1], peaks[5] = 3.0, 2.0, 9.0
    assert brute_max(peaks, 1, 1) == 3.0               # positions 1 and 0
    assert brute_max(peaks, 1, 0) == 2.0               # position 1 only
