"""V1.6 gates. Task 1 of docs/superpowers/plans/2026-09-24-rcbitnova-v16-analyzer.md.

A record is [index, name, lo, hi, step, default] - the shape _declared_records writes, NOT a
dict. The plan's first draft asserted dict keys; the fixture is the authority, not the plan.
"""
from tools.rcbitnova_gates import load_declared_v15


def test_v15_manifest_has_176_records():
    recs = load_declared_v15()
    assert len(recs) == 176


def test_v15_manifest_is_indexed_in_order():
    recs = load_declared_v15()
    assert [r[0] for r in recs] == list(range(176))


def test_v15_manifest_pins_the_hp_lp_range_change():
    recs = load_declared_v15()
    assert recs[84][1] == "HP Slope (dB/oct)"
    assert recs[85][1] == "HP Freq (Hz)"
    assert (recs[85][2], recs[85][3]) == (20.0, 24000.0)
    assert recs[89][1] == "LP Freq (Hz)"
    assert (recs[89][2], recs[89][3]) == (20.0, 24000.0)
    assert recs[92][1] == "Phase"


def test_v15_manifest_keeps_v14_defaults_where_the_range_did_not_change():
    from tools.rcbitnova_gates import load_declared_v14
    v14, v15 = load_declared_v14(), load_declared_v15()
    assert len(v14) == len(v15) == 176
    differing = [i for i, (a, b) in enumerate(zip(v14, v15)) if a != b]
    assert differing == [85, 89], f"unexpected records changed between V1.4 and V1.5: {differing}"


def test_the_last_record_is_the_panel_card_state():
    recs = load_declared_v15()
    assert recs[175][1].startswith("Panel: open dynamics card")


# ---- Task 2: V1.6 exists as an exact copy, and every consumer points at it ----

def test_v16_names_itself_in_desc():
    # REAPER identifies a JSFX by its desc line, not its filename. A copy left with the old desc
    # is INVISIBLE: the browser shows nothing new and add_fx fuzzy-matches the previous version,
    # reporting the right parameter count and no error.
    line = open("JSFX/RCBitNova V1.6").read().split("\n")[1]
    assert line.startswith("desc: RCBitNova V1.6 - ")


# The "V1.6 differs from V1.5 in exactly one line" test lived here for Task 2 only. It did its
# job in commit 2992338 - it proved the copy was exact BEFORE anything was built on it - and it
# was required to go red at the first real change, which is Task 3 below. git holds the proof.


def test_the_source_gate_targets_v16():
    from tools.rcbitnova_gates import V16, check_source
    import inspect
    assert V16 == "JSFX/RCBitNova V1.6"
    assert inspect.signature(check_source).parameters["path"].default == V16


def test_the_null_harness_compares_v16_against_v15():
    from tools import rcbitnova_nulltest as nt
    assert (nt.BASE, nt.UNDER_TEST) == ("RCBitNova V1.5", "RCBitNova V1.6")


def test_the_v14_migrator_still_names_v15():
    # it migrates V1.4 -> V1.5 and must not be dragged forward with the working file
    src = open("tools/migrate_v14_to_v15.py").read()
    assert 'add_fx("RCBitNova V1.5")' in src


# ---- Task 3: a Phase switch made under playback must commit ----

from tools.rcbitnova_gates import _function_body


def _code(text, name):
    """The function's body with // comments stripped - an assertion about ORDER must not be
    satisfied, or defeated, by prose. check_forbidden strips the same way."""
    return "\n".join(l.split("//")[0] for l in _function_body(text, name).splitlines())


def test_gc_w_topo_arms_regardless_of_the_transport():
    # V1.4 gated this whole writer on a stopped transport, so a click made under playback set
    # nothing - and @block's commit is itself gated on mt_pend, which only this writer and
    # @slider set, while @slider is not guaranteed to run after slider_automate. The switch then
    # waited for a plugin reload. Found live 2026-09-24: FIR Brick would not engage.
    body = _code(open("JSFX/RCBitNova V1.6").read(), "gc_w_topo")
    assert "mt_pend = 1" in body
    assert body.index("mt_pend = 1") < body.index("play_state == 0"), \
        "the arm sits behind the play_state gate: a switch under playback would never commit"


def test_gc_w_topo_also_arms_the_fade_out():
    # arming mt_pend alone is not enough: @block commits at (mt_state == 2 && mt_g == 0), which
    # is only ever reached if the fade-out was started.
    body = _code(open("JSFX/RCBitNova V1.6").read(), "gc_w_topo")
    assert "mt_state = 1" in body and "mt_ready = 0" in body


def test_gc_w_topo_still_commits_immediately_when_stopped():
    body = _code(open("JSFX/RCBitNova V1.6").read(), "gc_w_topo")
    assert "play_state == 0" in body and "topo_commit_state()" in body


# ---- Task 5 (+ the memory half of Task 9): the V1.6 block in the layout source of truth ----

from tools import rcbitnova_layout as L


def test_the_constants_match_the_design():
    assert (L.DQ_CAP, L.N_QUEUES, L.FFT_N, L.AN_PX) == (2049, 16, 8192, 2048)
    assert L.DQ_CAP == L.MAX_LOOK + 1, (
        "push-before-evict makes occupancy transiently Lk + 2; at the clamp Lk = 2047 a "
        "2048-slot buffer overwrites its own head")


def test_every_span_is_declared_with_the_size_the_design_gives():
    want = {"an_sc": 16384, "an_w": 8192, "an_in": 8192, "an_out": 8192,
            "an_mi": 4096, "an_mo": 4096, "an_pkI": 2048, "an_pkO": 2048,
            "an_db": 2048, "an_ms_state": 2048, "an_meta": 16,
            "dq_v": 16 * 2049, "dq_p": 16 * 2049, "dq_meta": 16 * 5}
    spans = L.v16_new_spans()
    assert set(spans) == set(want)
    for name, words in want.items():
        assert spans[name][1] - spans[name][0] == words, name


def test_the_spans_are_pairwise_disjoint():
    flat = sorted(L.v16_new_spans().values())
    for (a0, a1), (b0, b1) in zip(flat, flat[1:]):
        assert a1 <= b0, f"{(a0, a1)} overlaps {(b0, b1)}"


def test_the_fft_scratch_does_not_cross_a_page():
    # V0.7: a misaligned fft() corrupts SILENTLY - no error, no noise, just wrong numbers
    lo, hi = L.v16_new_spans()["an_sc"]
    assert lo // 65536 == (hi - 1) // 65536


def test_the_block_starts_on_a_page_and_the_engines_move_up_two():
    assert L.v16_block_base() == 131072
    assert L.v16_lp_base() == 262144
    assert max(e for _, e in L.v16_new_spans().values()) <= L.v16_lp_base()


def test_the_block_is_the_size_the_design_states():
    spans = L.v16_new_spans()
    assert max(e for _, e in spans.values()) - L.v16_block_base() == 123008


def test_a_small_shift_does_not_cross_a_page_and_that_is_the_point():
    # 16384 words sit inside a 65536-word page with room to spare, so nudging an_sc by a few
    # words proves nothing. Writing the negative test the obvious way produced a check that
    # passed while asserting nothing - recorded here so it is not rewritten that way.
    saved = L.V16_BLOCK[:]
    try:
        L.V16_BLOCK.insert(0, ("an_spacer", lambda: 16))
        L.v16_check()                      # still legal: an_sc has not left its page
    finally:
        L.V16_BLOCK[:] = saved


def test_v16_check_rejects_an_fft_scratch_that_straddles_a_page():
    # push an_sc so it ENDS one word past 196608 - the only shift that can actually break it
    saved = L.V16_BLOCK[:]
    spacer = (196608 - 2 * L.FFT_N + 16) - L.v16_block_base()
    try:
        L.V16_BLOCK.insert(0, ("an_spacer", lambda: spacer))
        import pytest as _p
        with _p.raises(AssertionError, match="crosses a 65536-word page"):
            L.v16_check()
    finally:
        L.V16_BLOCK[:] = saved
    L.v16_check()          # and the real map is still valid afterwards
