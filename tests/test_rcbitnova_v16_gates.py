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
