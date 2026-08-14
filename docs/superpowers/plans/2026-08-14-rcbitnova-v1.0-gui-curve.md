# RCBitNova V1.0 — GUI Curve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RCBitNova a `@gfx` EQ graph — one response trace per placement domain, with draggable band nodes that write Macro/Micro — so the common gestures stop requiring a hunt through 95 sliders.

**Architecture:** All curve mathematics is proven in the Python oracle first, then transcribed to EEL2. Analytic magnitudes (bands, min-phase HP/LP) are computed in `@gfx` from a port of `svf_response`; realized linear-phase and FIR Brick magnitudes are computed in `@block` by one native `fft()` of the already-windowed kernel and published to `@gfx` through a double-buffered cache in reserved memory. `@gfx` never touches engine buffers and never allocates.

**Tech Stack:** JSFX (EEL2) `@gfx`; Python 3.11 stdlib-only mirror (`tools/rcbitnova_dsp.py`) as THE ORACLE plus a new `tools/rcbitnova_curve.py`; `pytest`; live REAPER.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-14-rcbitnova-v1.0-gui-curve-design.md` (**rev 5**). Section numbers below are that document's.
- **New file `JSFX/RCBitNova V1.0`, an exact copy of `JSFX/RCBitNova V0.9`.** V0.9 and earlier are frozen and tagged; `rcbitnova-v0.9` is the fallback.
- **The GUI must not change the sound.** `@gfx` reads parameters and writes sliders; it touches no signal path. Gate: null test V0.9 vs V1.0 with the mouse untouched → digital silence.
- **`slider_automate()` after every slider write**, and only when the snapped value actually changed.
- **Write order for the Macro/Micro pair is chosen per write** — compute both candidate intermediates and write the field giving the smaller absolute intermediate gain first. A fixed order is unsafe: `16.95 → −16.95` with Micro first yields **+15.05 bits (×33923)**.
- **Placement source is phase-conditional:** `act_phase == 0` (Min) → read `slider134`/`slider138` live; `act_phase == 1` (Linear) → read `act_hp_pl`/`act_lp_pl`. In Min the `act_*` pair goes permanently stale, because `topo_changed` only fires for placement when `slider140 == 1`.
- **FIR Brick precedence:** Min + Brick = **identity** (it maps to `nsec = 0`); Linear + Brick = realized `fir_brick_kernel` magnitude.
- **Every `fft()` is followed by `fft_permute()`** — EEL2 returns bit-reversed order. All four existing calls in V0.9 do this.
- **All pinned numbers come from `svf_response`** (exact closed form) — never from `svf_magnitude` (finite-window RMS estimator) and never from an FFT bin. This project has been burned four times by numbers that were artefacts of how they were measured.
- **EEL2 gotcha:** avoid compound assignment under a conditional and unparenthesized conditional branches. V0.8's only real defect was of that shape, read correctly, and never executed.
- **Python:** `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`; oracle is pure stdlib.
- **Run from the worktree root:** `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. All 183 existing tests stay green at every commit.
- **Never claim a task is done without running its test and reading the output.**

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/rcbitnova_curve.py` | NEW. Everything the graph needs as pure functions: per-domain composition, realized-kernel magnitude, axis mapping, Macro/Micro split, Bit Ratio inversion, write-order choice. Kept out of the oracle so `rcbitnova_dsp.py` stays the DSP mirror. | Create |
| `tools/rcbitnova_dsp.py` | THE ORACLE. Already has `svf_response`, `hplp_digital_mag`, `fir_brick_kernel`, `q_eff`, `bit_gain`. | **Unchanged** |
| `tests/test_rcbitnova_dsp.py` | All tests, V1.0 block appended. | Modify |
| `JSFX/RCBitNova V1.0` | The plugin. | Create (copy of V0.9), then modified in Tasks 5–8 |

Tasks 1–4 are pure Python and test-driven. Tasks 5–8 are the EEL2 transcription, each live-verifiable. Tasks 9–10 are the gates and shipping.

---

### Task 1: Per-block magnitude and per-domain composition

**Files:**
- Create: `tools/rcbitnova_curve.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `dsp.svf_make`, `dsp.svf_response`, `dsp.hplp_digital_mag`, `dsp.bit_gain`, `dsp.q_eff`.
- Produces:
  - `band_mag(band: dict, f: float, sr: float) -> float` — linear magnitude of one band at `f`. `band` keys: `enable, type, freq, q, macro, micro, ratio, placement, qchar`.
  - `hplp_mag(hp: dict, f: float, sr: float, act_phase: int) -> float` — `hp` keys: `slope, freq, res, placement, ftype`.
  - `domain_mag(bands: list, filters: list, domain: str, f: float, sr: float, act_phase: int) -> float` — product over blocks whose placement is `"both"` or `domain`.
  - `DOMAINS = ("both", "mid", "side", "left", "right")`

- [ ] **Step 1: Write the failing tests**

```python
from tools import rcbitnova_curve as curve   # noqa: E402


def _band(**kw):
    b = dict(enable=1, type="bell", freq=1000.0, q=0.707, macro=0, micro=0.0,
             ratio=1.0, placement="both", qchar=0.0)
    b.update(kw)
    return b


def _hp(**kw):
    h = dict(ftype="hp", slope=4, freq=100.0, res=0.0, placement="both")
    h.update(kw)
    return h


def test_v10_bell_at_fc_is_the_full_bit_gain():
    import math
    for bits in (2.0, -2.0, 0.5):
        b = _band(macro=int(bits), micro=(bits - int(bits)) * 100)
        m = curve.band_mag(b, 1000.0, 48000)
        assert abs(math.log2(m) - bits) < 1e-9, (bits, math.log2(m))


def test_v10_shelf_at_fc_is_exactly_half_the_gain():
    """The shipping TPT shelf uses A = sqrt(gain_lin). Measured with svf_response, this is
    EXACTLY bits/2 at fc for every fc and Q - not 0.9966, which was an FFT-bin artefact."""
    import math
    for ftype in ("lowshelf", "highshelf"):
        for bits in (2.0, -2.0):
            for fc in (100.0, 1000.0, 8000.0):
                for q in (0.4, 0.707, 3.0):
                    b = _band(type=ftype, freq=fc, q=q, macro=int(bits))
                    m = curve.band_mag(b, fc, 48000)
                    assert abs(math.log2(m) - bits / 2) < 1e-9, (ftype, bits, fc, q)


def test_v10_disabled_band_is_transparent():
    assert curve.band_mag(_band(enable=0, macro=4), 1000.0, 48000) == 1.0


def test_v10_band_far_from_centre_tends_to_unity():
    m = curve.band_mag(_band(macro=4, q=4.0), 20.0, 48000)
    assert abs(m - 1.0) < 1e-3


def test_v10_band_width_follows_q_eff_not_the_knob():
    """Q Character > 0 narrows a boosted bell. The drawn width must follow q_eff."""
    wide = _band(macro=4, q=1.0, qchar=0.0)
    narrow = _band(macro=4, q=1.0, qchar=1.0)
    off = 1000.0 * 2 ** (1 / 6)          # a third of an octave above fc
    assert curve.band_mag(narrow, off, 48000) < curve.band_mag(wide, off, 48000)


def test_v10_min_phase_brick_is_identity():
    """Brick maps to nsec = 0 in the min path, so the audible response IS identity."""
    for f in (20.0, 100.0, 1000.0, 15000.0):
        assert curve.hplp_mag(_hp(slope=6), f, 48000, act_phase=0) == 1.0


def test_v10_min_phase_hplp_matches_the_oracle():
    for slope in (1, 2, 4, 8):
        for f in (50.0, 100.0, 400.0):
            got = curve.hplp_mag(_hp(slope=slope), f, 48000, act_phase=0)
            want = dsp.hplp_digital_mag("hp", 100.0, 0.0, slope, f, 48000)
            assert abs(got - want) < 1e-12, (slope, f)


def test_v10_hplp_is_minus_3db_at_cutoff_only_without_resonance():
    import math
    m = curve.hplp_mag(_hp(slope=4, res=0.0), 100.0, 48000, act_phase=0)
    assert abs(20 * math.log10(m) + 3.0) < 0.2
    m_res = curve.hplp_mag(_hp(slope=4, res=1.0), 100.0, 48000, act_phase=0)
    assert m_res > m, "resonance must lift the cutoff magnitude"


def test_v10_domain_trace_includes_both_blocks():
    """A Both block applies identical coefficients to L and R, which by linearity is identical
    to applying them to M and S - so it multiplies into EVERY domain trace."""
    bands = [_band(macro=2, placement="both"), _band(freq=4000.0, macro=2, placement="mid")]
    f = 1000.0
    mid = curve.domain_mag(bands, [], "mid", f, 48000, 1)
    side = curve.domain_mag(bands, [], "side", f, 48000, 1)
    both_only = curve.band_mag(bands[0], f, 48000)
    assert abs(mid - both_only * curve.band_mag(bands[1], f, 48000)) < 1e-12
    assert abs(side - both_only) < 1e-12, "side trace must not include the mid-placed band"


def test_v10_domain_trace_is_not_a_product_of_all_blocks():
    """Guards against the rev-1 mistake: multiplying every block into one scalar curve."""
    bands = [_band(macro=3, placement="left"), _band(macro=3, placement="right")]
    f = 1000.0
    left = curve.domain_mag(bands, [], "left", f, 48000, 1)
    naive = curve.band_mag(bands[0], f, 48000) * curve.band_mag(bands[1], f, 48000)
    assert abs(left - naive) > 1e-6, "left trace wrongly includes the right-placed band"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v10`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.rcbitnova_curve'`.

- [ ] **Step 3: Implement `tools/rcbitnova_curve.py`**

```python
"""Curve mathematics for the RCBitNova V1.0 GUI.

Pure functions, no drawing. Everything the @gfx graph needs, proven here before it is
transcribed to EEL2. Reads the oracle; never modifies it.

Design: docs/superpowers/specs/2026-08-14-rcbitnova-v1.0-gui-curve-design.md (rev 5)
"""

import math

try:
    from tools import rcbitnova_dsp as dsp
except ImportError:
    import rcbitnova_dsp as dsp

DOMAINS = ("both", "mid", "side", "left", "right")

BRICK_SLOPE = 6                      # slider enum index for FIR Brick
_SLOPE_SECTIONS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 8, 6: 0}   # 5 = 96 dB/oct, 6 = Brick -> Off


def band_gain_bits(band):
    """Effective gain in bits, including Bit Ratio - the same expression the audio path uses."""
    return (band["macro"] + band["micro"] * 0.01) * band["ratio"]


def band_mag(band, f, sr):
    """Linear magnitude of one band at frequency f. Disabled bands are transparent."""
    if not band["enable"]:
        return 1.0
    gain_lin = dsp.bit_gain(band["macro"], band["micro"], band["ratio"])
    qe = dsp.q_eff(band["type"], band["q"], band["qchar"], band_gain_bits(band))
    c = dsp.svf_make(band["type"], dsp.fc_eff(band["freq"], sr), qe, gain_lin, sr)
    return abs(dsp.svf_response(c, f, sr))


def hplp_mag(hp, f, sr, act_phase, realized=None):
    """Magnitude of one HP/LP block.

    Min phase: the digital cascade, and Brick is IDENTITY there (it maps to nsec = 0, so the
    audible response really is no filter - drawing a cutoff would show something unheard).
    Linear phase: the caller supplies `realized`, a function f -> magnitude sampled from the
    actual windowed kernel; there is no analytic shortcut, because windowing changes the
    response and that is the whole reason Resolution exists.
    """
    nsec = _SLOPE_SECTIONS[hp["slope"]]
    if act_phase == 0:
        if hp["slope"] == BRICK_SLOPE or nsec == 0:
            return 1.0
        return dsp.hplp_digital_mag(hp["ftype"], hp["freq"], hp["res"], nsec, f, sr)
    if realized is None:
        raise ValueError("Linear phase needs a realized-kernel sampler")
    return realized(f)


def _applies(placement, domain):
    return placement == "both" or placement == domain


def domain_mag(bands, filters, domain, f, sr, act_phase, realized=None):
    """Product of the magnitudes of every block that acts on `domain`.

    Multiplying magnitudes is valid WITHIN one domain. It is not valid across domains - a
    selective block is a stereo matrix - which is why there is one trace per domain.
    """
    m = 1.0
    for hp in filters:
        if _applies(hp["placement"], domain):
            m *= hplp_mag(hp, f, sr, act_phase, realized)
    for b in bands:
        if _applies(b["placement"], domain):
            m *= band_mag(b, f, sr)
    return m


def active_domains(bands, filters):
    """Domains that have at least one enabled block, so only those traces are drawn."""
    out = set()
    for blk in list(bands) + list(filters):
        if blk.get("enable", 1):
            out.add(blk["placement"])
    return tuple(d for d in DOMAINS if d in out)


def mixed_placement_families(bands, filters):
    """True when M/S-placed and L/R-placed blocks coexist, in which case per-domain scalar
    traces cannot describe the true channel response and must be drawn dashed."""
    doms = active_domains(bands, filters)
    return any(d in doms for d in ("mid", "side")) and any(d in doms for d in ("left", "right"))
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 194 passed (183 + 11).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_curve.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.0 curve maths - per-block magnitude and per-domain composition"
```

---

### Task 2: Axis mapping, Macro/Micro split, Bit Ratio inversion, write order

**Files:**
- Modify: `tools/rcbitnova_curve.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: Task 1's module.
- Produces:
  - `f_to_x(f, x0, w, fmin=20.0, fmax=20000.0) -> float` and `x_to_f(x, x0, w, ...) -> float`
  - `bits_to_y(bits, y0, h, span=4.0) -> float` and `y_to_bits(y, y0, h, span=4.0) -> float`
  - `snap_bits(bits, step=0.05) -> float`
  - `split_macro_micro(base_bits) -> (int, float)` — truncation toward zero, signed Micro
  - `invert_ratio(effective_bits, ratio) -> float | None` — `None` when `ratio == 0`
  - `write_order(old_macro, old_micro, new_macro, new_micro, ratio) -> str` — `"macro"` or `"micro"`, whichever field to write FIRST

- [ ] **Step 1: Write the failing tests**

```python
def test_v10_frequency_axis_round_trips():
    for f in (20.0, 100.0, 1000.0, 12345.0, 20000.0):
        x = curve.f_to_x(f, 40, 800)
        assert abs(curve.x_to_f(x, 40, 800) - f) < 1e-6, f


def test_v10_bits_axis_round_trips_and_clamps():
    for b in (-4.0, -1.5, 0.0, 2.25, 4.0):
        y = curve.bits_to_y(b, 10, 400)
        assert abs(curve.y_to_bits(y, 10, 400) - b) < 1e-9, b
    top = curve.bits_to_y(99.0, 10, 400)
    bot = curve.bits_to_y(-99.0, 10, 400)
    assert top == curve.bits_to_y(4.0, 10, 400), "over-range must clamp, not wrap"
    assert bot == curve.bits_to_y(-4.0, 10, 400)


def test_v10_snap_lands_on_multiples_of_five_hundredths():
    for v in (0.0, 0.024, 0.026, -0.049, 1.234, -16.97):
        s = curve.snap_bits(v)
        assert abs(round(s / 0.05) - s / 0.05) < 1e-9, (v, s)


def test_v10_split_truncates_toward_zero_and_round_trips():
    """floor() would lose part of the negative range: -16.5 needs Macro -17, outside [-16,16]."""
    for base in (0.0, 0.05, 0.95, 1.0, -0.05, -0.95, -1.0, 16.0, -16.0, 16.95, -16.95):
        macro, micro = curve.split_macro_micro(base)
        assert -16 <= macro <= 16, (base, macro)
        assert -100.0 < micro < 100.0, (base, micro)
        assert abs((macro + micro * 0.01) - base) < 1e-9, (base, macro, micro)


def test_v10_split_is_symmetric_between_signs():
    for base in (0.35, 1.6, 12.4):
        pm, pu = curve.split_macro_micro(base)
        nm, nu = curve.split_macro_micro(-base)
        assert nm == -pm and abs(nu + pu) < 1e-9, base


def test_v10_ratio_inversion_and_the_zero_case():
    assert abs(curve.invert_ratio(2.0, 1.0) - 2.0) < 1e-12
    assert abs(curve.invert_ratio(2.0, 2.0) - 1.0) < 1e-12
    assert abs(curve.invert_ratio(-3.0, 0.5) + 6.0) < 1e-12
    assert curve.invert_ratio(2.0, 0.0) is None, "Ratio 0 has no inverse - the node must lock"


def test_v10_write_order_always_errs_toward_silence():
    """Neither fixed order is safe. Measured: 16.95 -> -16.95 with Micro first gives +15.05
    bits (x33923); Macro first on a single-boundary move gives +1.95. Pick per write."""
    assert curve.write_order(16, 95.0, -16, -95.0, 1.0) == "macro"
    assert curve.write_order(0, 95.0, 1, 0.0, 1.0) == "micro"


def test_v10_write_order_intermediate_is_never_the_larger_one():
    import itertools
    for om, ou, nm, nu in itertools.product((-16, -1, 0, 1, 16), (-95.0, 0.0, 95.0),
                                            (-16, -1, 0, 1, 16), (-95.0, 0.0, 95.0)):
        first = curve.write_order(om, ou, nm, nu, 1.0)
        inter_micro_first = abs(dsp.bit_gain(om, nu, 1.0))
        inter_macro_first = abs(dsp.bit_gain(nm, ou, 1.0))
        chosen = inter_micro_first if first == "micro" else inter_macro_first
        assert chosen <= max(inter_micro_first, inter_macro_first) + 1e-12
        assert chosen == min(inter_micro_first, inter_macro_first)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v10_frequency or v10_bits or v10_snap or v10_split or v10_ratio or v10_write"`
Expected: FAIL — `AttributeError: module 'tools.rcbitnova_curve' has no attribute 'f_to_x'`.

- [ ] **Step 3: Append to `tools/rcbitnova_curve.py`**

```python
# --------------------------------------------------------------------- axis mapping

FMIN, FMAX = 20.0, 20000.0
BITS_SPAN = 4.0                      # +-4 bits = +-24 dB viewport


def f_to_x(f, x0, w, fmin=FMIN, fmax=FMAX):
    f = min(max(f, fmin), fmax)
    return x0 + w * (math.log(f / fmin) / math.log(fmax / fmin))


def x_to_f(x, x0, w, fmin=FMIN, fmax=FMAX):
    t = min(max((x - x0) / w, 0.0), 1.0)
    return fmin * (fmax / fmin) ** t


def bits_to_y(bits, y0, h, span=BITS_SPAN):
    """Positive bits go UP, so y decreases. Over-range clamps to the edge; the caller draws the
    numeric label so the value is never hidden."""
    b = min(max(bits, -span), span)
    return y0 + h * (0.5 - b / (2.0 * span))


def y_to_bits(y, y0, h, span=BITS_SPAN):
    t = (y - y0) / h
    return (0.5 - t) * 2.0 * span


# --------------------------------------------------------------------- parameter mapping

def snap_bits(bits, step=0.05):
    return round(bits / step) * step


def split_macro_micro(base_bits, macro_min=-16, macro_max=16):
    """Canonical split: TRUNCATION TOWARD ZERO with a signed Micro in (-100, 100).

    floor() with Micro in [0,100) was rejected: -16.5 would need Macro -17, outside the slider
    range, making the canonical span an asymmetric [-16, +17). Truncation keeps it symmetric.
    """
    lo = macro_min - 0.999999
    hi = macro_max + 0.999999
    base = min(max(base_bits, lo), hi)
    macro = int(base)                       # int() truncates toward zero for both signs
    micro = (base - macro) * 100.0
    return macro, micro


def invert_ratio(effective_bits, ratio):
    """Base value that yields `effective_bits` after Bit Ratio scaling.

    Returns None when ratio == 0: every Macro/Micro pair then sounds at 0 bits, so there is no
    inverse and the node must lock rather than silently resetting a deliberate setting.
    """
    if ratio == 0.0:
        return None
    return effective_bits / ratio


def write_order(old_macro, old_micro, new_macro, new_micro, ratio):
    """Which of the two sliders to write FIRST, so the transient errs toward silence.

    The two writes are not atomic. A fixed order is unsafe in general: Micro-first is perfect
    for a single-boundary drag (0.95 -> 1.00 gives 0.00 bits) and catastrophic on a jump
    (16.95 -> -16.95 gives +15.05 bits, a 33923x bang - the same failure class as V0.8's
    full-amplitude step). So evaluate both candidate intermediates and pick the quieter.
    """
    micro_first = abs(dsp.bit_gain(old_macro, new_micro, ratio))
    macro_first = abs(dsp.bit_gain(new_macro, old_micro, ratio))
    return "micro" if micro_first <= macro_first else "macro"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 202 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_curve.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.0 axis mapping, canonical split, ratio inversion, safe write order"
```

---

### Task 3: Realized linear-phase / Brick magnitude via FFT of the windowed kernel

**Files:**
- Modify: `tools/rcbitnova_curve.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `dsp.fir_brick_kernel`, `dsp.impulse_fft_kernel`, `dsp.lp_fft`, Task 1's module.
- Produces:
  - `realized_mag_grid(kernel: list, sr: float, n_out: int = 256) -> list[tuple[float, float]]` — `(freq, magnitude)` pairs on a log grid, derived from **one FFT** of the kernel, using bins `0..N/2` only.
  - `sample_grid(grid, f) -> float` — linear interpolation **in log frequency**, on values already in bits.

- [ ] **Step 1: Write the failing tests**

```python
def test_v10_realized_grid_matches_a_direct_dtft():
    """The FFT route must agree with a slow but obviously-correct DTFT at sampled points."""
    import math
    BD, sr = 1024, 48000
    ker = dsp.fir_brick_kernel(BD, "lp", 8000.0, 14.0, sr)
    grid = curve.realized_mag_grid(ker, sr, n_out=64)
    for f, m in grid[8:56:8]:
        w = 2 * math.pi * f / sr
        re = sum(h * math.cos(-w * n) for n, h in enumerate(ker))
        im = sum(h * math.sin(-w * n) for n, h in enumerate(ker))
        want = math.hypot(re, im)
        assert abs(m - want) / max(want, 1e-12) < 0.05, (f, m, want)


def test_v10_realized_brick_is_not_identity():
    """A Brick slope in Linear must draw an actual cutoff - the failure it must never have is
    drawing 'no filter', which is what the min-phase helper would give."""
    import math
    BD, sr = 2048, 48000
    ker = dsp.fir_brick_kernel(BD, "lp", 5000.0, 14.0, sr)
    grid = curve.realized_mag_grid(ker, sr, n_out=128)
    pass_m = curve.sample_grid(grid, 1000.0)
    stop_m = curve.sample_grid(grid, 12000.0)
    assert abs(20 * math.log10(pass_m)) < 0.5, "passband should be flat"
    assert 20 * math.log10(max(stop_m, 1e-12)) < -60.0, "stopband should be deep"


def test_v10_realized_grid_uses_only_the_lower_half_spectrum():
    """ktime is real, so X[N-k] = conj(X[k]); the grid must never run past Nyquist."""
    ker = dsp.fir_brick_kernel(1024, "hp", 500.0, 14.0, 48000)
    grid = curve.realized_mag_grid(ker, 48000, n_out=64)
    assert max(f for f, _ in grid) <= 48000 / 2 + 1e-9


def test_v10_sample_grid_interpolates_in_log_frequency():
    grid = [(100.0, 1.0), (1000.0, 0.5)]
    mid = curve.sample_grid(grid, math.sqrt(100.0 * 1000.0))   # geometric midpoint
    assert abs(mid - 0.75) < 1e-9, "interpolation must be linear in LOG frequency"


def test_v10_high_resolution_differs_from_normal_on_a_steep_low_cut():
    """The case that motivated V0.7: BD=32768 resolves a deep low cut that BD=8192 cannot.
    If the drawn curve did not differ here, it would not be showing the realized kernel."""
    import math
    sr = 96000
    lo = dsp.fir_brick_kernel(8192, "hp", 40.0, 14.0, sr)
    hi = dsp.fir_brick_kernel(32768, "hp", 40.0, 14.0, sr)
    g_lo = curve.realized_mag_grid(lo, sr, n_out=256)
    g_hi = curve.realized_mag_grid(hi, sr, n_out=256)
    at20_lo = 20 * math.log10(max(curve.sample_grid(g_lo, 20.0), 1e-12))
    at20_hi = 20 * math.log10(max(curve.sample_grid(g_hi, 20.0), 1e-12))
    assert at20_hi < at20_lo - 20.0, (at20_lo, at20_hi)


def test_v10_log_floor_keeps_everything_finite():
    """FIR Brick's target contains exact zeros; log(0) would corrupt a whole line strip."""
    import math
    ker = dsp.fir_brick_kernel(1024, "lp", 2000.0, 14.0, 48000)
    grid = curve.realized_mag_grid(ker, 48000, n_out=128)
    for f, m in grid:
        b = curve.mag_to_bits(m)
        assert math.isfinite(b), (f, m, b)
        assert b >= curve.BITS_FLOOR
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v10_realized or v10_sample_grid or v10_high_resolution or v10_log_floor"`
Expected: FAIL — `AttributeError: ... has no attribute 'realized_mag_grid'`.

- [ ] **Step 3: Append to `tools/rcbitnova_curve.py`**

```python
# --------------------------------------------------------------------- realized kernels

MAG_FLOOR = 1e-7                     # -140 dB, far below the +-4-bit viewport
BITS_FLOOR = math.log2(MAG_FLOOR)


def mag_to_bits(m):
    """Magnitude -> bits, with a floor. FIR Brick's target has exact zeros and serial cuts
    underflow; log(0) would produce non-finite pixel coordinates."""
    return math.log2(max(m, MAG_FLOOR))


def realized_mag_grid(kernel, sr, n_out=256, fmin=FMIN, fmax=FMAX):
    """(freq, magnitude) pairs sampled from ONE FFT of the windowed kernel.

    This mirrors exactly what the JSFX will do in @block: copy the windowed kernel into the
    existing desbuf scratch, fft(BD) + fft_permute, take bin magnitudes of bins 0..BD/2 (the
    sequence is real, so the upper half is the conjugate mirror) and resample to a log grid.

    The kernel's fftshift needs no correction: a half-period circular shift multiplies the
    spectrum by (-1)^k, which |X[k]| removes.
    """
    N = len(kernel)
    X = dsp.lp_fft([complex(v, 0.0) for v in kernel])
    half = N // 2
    mags = [abs(X[k]) for k in range(half + 1)]
    out = []
    for i in range(n_out):
        t = i / (n_out - 1)
        f = fmin * (fmax / fmin) ** t
        if f > sr * 0.5:
            f = sr * 0.5
        b = f * N / sr
        k0 = int(b)
        if k0 >= half:
            out.append((f, mags[half]))
            continue
        frac = b - k0
        out.append((f, mags[k0] * (1.0 - frac) + mags[k0 + 1] * frac))
    return out


def sample_grid(grid, f):
    """Linear interpolation in LOG frequency, so a steep skirt stays straight on the drawn axes."""
    if f <= grid[0][0]:
        return grid[0][1]
    if f >= grid[-1][0]:
        return grid[-1][1]
    lo = 0
    hi = len(grid) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if grid[mid][0] <= f:
            lo = mid
        else:
            hi = mid
    f0, m0 = grid[lo]
    f1, m1 = grid[hi]
    t = math.log(f / f0) / math.log(f1 / f0)
    return m0 + (m1 - m0) * t
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 208 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_curve.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.0 realized linear/Brick magnitude from one FFT of the kernel"
```

---

### Task 4: Publication protocol and generation counters

**Files:**
- Modify: `tools/rcbitnova_curve.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `class CurveCache` with `write_inactive(engine, grid)`, `publish()`, `snapshot()` returning `(gen, index)`, `read(gen_index)`, and attributes `gen_target`, `gen_active`; plus `watched_fields(bands, filters, phase, res0, res1, srate) -> tuple` for snapshot comparison.

- [ ] **Step 1: Write the failing tests**

```python
def test_v10_reader_never_sees_a_half_written_buffer():
    """The whole point of double buffering: a frame must show one kernel or the other, never
    a mixture. Reserving memory does not make an array update atomic."""
    c = curve.CurveCache(n_out=8)
    c.write_inactive(0, [(100.0, 1.0)] * 8)
    c.publish()
    snap = c.snapshot()
    before = list(c.read(snap)[0])
    c.write_inactive(0, [(100.0, 0.0)] * 8)     # a new build lands, NOT yet published
    assert list(c.read(snap)[0]) == before, "reader saw an unpublished write"
    c.publish()
    assert list(c.read(c.snapshot())[0]) != before


def test_v10_generation_changes_only_on_publish():
    c = curve.CurveCache(n_out=4)
    g0 = c.snapshot()[0]
    c.write_inactive(0, [(100.0, 1.0)] * 4)
    assert c.snapshot()[0] == g0, "generation must not move before publication"
    c.publish()
    assert c.snapshot()[0] != g0


def test_v10_watched_fields_notice_every_single_field():
    base = dict(bands=[_band()], filters=[_hp()], phase=0, res0=0, res1=0, srate=48000)
    ref = curve.watched_fields(**base)
    variations = [
        dict(base, bands=[_band(enable=0)]),
        dict(base, bands=[_band(type="lowshelf")]),
        dict(base, bands=[_band(freq=1001.0)]),
        dict(base, bands=[_band(q=0.708)]),
        dict(base, bands=[_band(macro=1)]),
        dict(base, bands=[_band(micro=0.1)]),
        dict(base, bands=[_band(ratio=1.1)]),
        dict(base, bands=[_band(placement="mid")]),
        dict(base, bands=[_band(qchar=0.5)]),
        dict(base, filters=[_hp(slope=2)]),
        dict(base, filters=[_hp(freq=101.0)]),
        dict(base, filters=[_hp(res=0.5)]),
        dict(base, filters=[_hp(placement="side")]),
        dict(base, phase=1),
        dict(base, res0=1),
        dict(base, res1=1),
        dict(base, srate=96000),
    ]
    for v in variations:
        assert curve.watched_fields(**v) != ref, v


def test_v10_watched_fields_have_no_arithmetic_collision():
    """A weighted sum like hp_sig can collide and leave a stale but plausible curve. A tuple
    snapshot cannot - this test constructs a pair that a naive sum would merge."""
    a = curve.watched_fields(bands=[_band(macro=1, micro=0.0)], filters=[], phase=0,
                             res0=0, res1=0, srate=48000)
    b = curve.watched_fields(bands=[_band(macro=0, micro=100.0)], filters=[], phase=0,
                             res0=0, res1=0, srate=48000)
    assert a != b, "two configurations with the same gain sum must still differ"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v10_reader or v10_generation or v10_watched"`
Expected: FAIL — `AttributeError: ... has no attribute 'CurveCache'`.

- [ ] **Step 3: Append to `tools/rcbitnova_curve.py`**

```python
# --------------------------------------------------------------------- publication

class CurveCache:
    """Double-buffered publication of realized-kernel grids, mirroring the JSFX design.

    @block fills the INACTIVE buffer completely, then publishes by flipping the index and
    bumping the generation. @gfx snapshots (gen, index) once per frame and reads only that
    buffer. This is a seqlock; on ARM it has no memory barrier (EEL2 has no primitive), so it
    is accepted with a scoped worst case: a one-frame visual glitch, never signal corruption.
    """

    def __init__(self, n_out=256, engines=2):
        self.n_out = n_out
        self.buffers = [[[(0.0, 1.0)] * n_out for _ in range(engines)] for _ in range(2)]
        self.active = 0
        self.gen_active = 0
        self.gen_target = 0

    def write_inactive(self, engine, grid):
        self.buffers[1 - self.active][engine] = list(grid)

    def publish(self):
        self.active = 1 - self.active
        self.gen_active += 1

    def snapshot(self):
        return (self.gen_active, self.active)

    def read(self, snap):
        return self.buffers[snap[1]]


def watched_fields(bands, filters, phase, res0, res1, srate):
    """Exact snapshot of everything the curve depends on.

    A tuple comparison, never a weighted arithmetic signature: a signature can collide, and a
    collision leaves a stale but entirely plausible curve on screen. Phase and both Resolutions
    are included because Phase selects which magnitude source applies and Resolution selects
    which BD grid is read.
    """
    bt = tuple((b["enable"], b["type"], b["freq"], b["q"], b["macro"], b["micro"],
                b["ratio"], b["placement"], b["qchar"]) for b in bands)
    ft = tuple((h["ftype"], h["slope"], h["freq"], h["res"], h["placement"]) for h in filters)
    return (bt, ft, phase, res0, res1, srate)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 212 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_curve.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.0 double-buffered publication and collision-free invalidation"
```

---

### Task 5: `JSFX/RCBitNova V1.0` — new file, reserved memory, magnitude helpers

**Files:**
- Create: `JSFX/RCBitNova V1.0` (byte copy of `JSFX/RCBitNova V0.9`)
- Modify: `JSFX/RCBitNova V1.0` only

**Interfaces:**
- Produces (used by Tasks 6–8): memory symbols `gc_trace`, `gc_lin`, `gc_snap`, `gc_meta`; functions `gc_svf_mag(cdst, f)`, `gc_band_mag(b, f)`, `gc_hplp_mag(eng, f)`, `gc_domain_mag(dom, f)`.

- [ ] **Step 1: Create the file and update `desc`**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
cp "JSFX/RCBitNova V0.9" "JSFX/RCBitNova V1.0"
```

Change the `desc:` line to read `V1.0` instead of `V0.9`, and append ` + EQ curve GUI` to it.

- [ ] **Step 2: Reserve the GUI memory before `lp_base`**

Find the static memory chain (`lp_rt = hplp_cf + 126;` … `lp_fs = lp_off + 32;`) and insert **before** the `lp_base` line:

```eel2
// ---- V1.0 GUI curve memory. MUST sit before lp_base: lp_relayout() memsets [lp_base, lp_top]
// and calls freembuf(lp_top + 1), so anything above lp_base can be freed or overwritten while
// @gfx is reading it on another thread. Verified fit: the static chain ends at 38275 words and
// lp_base = 65536, leaving 27261 words of padding; this block ends the region at 44555, still
// ~21000 short of the boundary, so lp_base does NOT move and page alignment is untouched.
GC_N     = 512;                       // display points per trace
GC_LIN_N = 256;                       // realized-kernel grid points per engine
gc_trace = lp_fs + 8;                 // [2 buffers][5 domains][GC_N]
gc_lin   = gc_trace + 2*5*GC_N;       // [2 buffers][2 engines][GC_LIN_N]
gc_snap  = gc_lin + 2*2*GC_LIN_N;     // 128 words: per-field snapshot
gc_meta  = gc_snap + 128;             // 8 words: 0 gen_active, 1 active_idx, 2 gen_target
```

Then change the `lp_base` line to start from `gc_meta + 8` instead of `lp_fs + 8`:

```eel2
lp_base = ceil((gc_meta + 8) / 65536) * 65536;     // page-align the engine block start
```

- [ ] **Step 3: Add the magnitude helpers next to `band_qeff`**

```eel2
// ---- V1.0: exact |H(e^jw)| of the TPT-SVF, ported from the oracle's svf_response.
// EEL2 has no complex type, so the 2x2 solve is written out. Do NOT substitute a brute-force
// RMS measurement (the oracle's svf_magnitude): it is far too slow per frame and its own noise
// floor would make the transcription gate meaningless.
function gc_svf_mag(cdst, f)
  local(a1, a2, a3, m0, m1, m2, A11, A12, A21, A22, B1, B2, C1, C2, D,
        w, zr, zi, M11r, M11i, M12r, M22r, M22i, M21r, dr, di,
        n1r, n1i, n2r, n2i, xr, xi, yr, yi, hr, hi, den)
(
  a1 = cdst[0]; a2 = cdst[1]; a3 = cdst[2];
  m0 = cdst[4]; m1 = cdst[5]; m2 = cdst[6];
  A11 = 2*a1 - 1; A12 = -2*a2;
  A21 = 2*a2;     A22 = 1 - 2*a3;
  B1 = 2*a2; B2 = 2*a3;
  C1 = m1*a1 + m2*a2;
  C2 = -m1*a2 + m2*(1 - a3);
  D  = m0 + m1*a2 + m2*a3;
  w = 2 * $pi * f / srate;
  zr = cos(w); zi = sin(w);
  M11r = zr - A11; M11i = zi;
  M12r = -A12;
  M21r = -A21;
  M22r = zr - A22; M22i = zi;
  // det = M11*M22 - M12*M21   (M12, M21 are real)
  dr = M11r*M22r - M11i*M22i - M12r*M21r;
  di = M11r*M22i + M11i*M22r;
  den = dr*dr + di*di;
  // (M^-1 B) via Cramer: x = (B1*M22 - M12*B2)/det, y = (M11*B2 - B1*M21)/det
  n1r = B1*M22r - M12r*B2; n1i = B1*M22i;
  n2r = M11r*B2 - B1*M21r; n2i = M11i*B2;
  xr = (n1r*dr + n1i*di) / den; xi = (n1i*dr - n1r*di) / den;
  yr = (n2r*dr + n2i*di) / den; yi = (n2i*dr - n2r*di) / den;
  hr = C1*xr + C2*yr + D;
  hi = C1*xi + C2*yi;
  sqrt(hr*hr + hi*hi);
);

// Magnitude of band b at frequency f.
//
// It READS the coefficients the audio path is already using - `setup_band` calls
// `svf_set(b * 8, ...)` in @slider for every band, writing a1,a2,a3,k,m0,m1,m2 to cf[b*8+0..6].
// So the graph cannot drift from the sound: it is literally the same numbers, including
// band_qeff's effective Q and the bit_gain expression that produced them.
//
// It must NOT call svf_set itself: that function writes into the GLOBAL cf array, so calling it
// from @gfx would overwrite the live audio coefficients from another thread.
function gc_band_mag(b, f) (
  slider(10 * (b + 1) + 1) == 0 ? ( 1; ) : ( gc_svf_mag(cf + b * 8, f); );
);
```

- [ ] **Step 4: Verify the file still loads in REAPER**

Load `JS: RCBitNova V1.0` on a track. No `@gfx` yet, so it must behave exactly like V0.9: filters
work, no error dialog, no silence. If REAPER reports a memory error, the reservation is wrong —
check that `lp_base` still evaluates to 65536.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.0"
git commit -m "feat(rcbitnova): V1.0 - new file, reserved GUI memory, exact SVF magnitude helper"
```

---

### Task 6: Realized-kernel grid in `@block`, published to the cache

**Files:**
- Modify: `JSFX/RCBitNova V1.0` (`lpk_build`, `@block`)

**Interfaces:**
- Consumes: Task 5's `gc_lin`, `gc_meta`.
- Produces: a published realized grid per engine; `gc_publish()`.

- [ ] **Step 1: Add the grid builder after `lpk_build`**

```eel2
// V1.0: sample the REALIZED windowed kernel's magnitude with ONE native FFT.
// Not a per-point DTFT: 100 points over BD=32768 is ~3.3M interpreted operations per engine,
// and the danger is peak block time - one @block missing its deadline - not average CPU.
// desbuf (ob[0], span BD*2) is free once lpk_build has finished: it is last written by the
// ifft and only read by the ktime loop, and lpk_run never touches it. Same page-aligned span
// V0.7 already proved safe at 32768.
function gc_build_grid(eng) local(ob, BD, desbuf, ktime, half, i, k, b, frac, dst, f, t, m) (
  ob = lp_off + eng*16; BD = lp_geo[eng*4];
  desbuf = ob[0]; ktime = ob[1];
  // real -> complex, zeroing the imaginary lane EXPLICITLY (the prior ifft left rounding
  // residue there, not exact zeros)
  i = 0; loop(BD, desbuf[i*2] = ktime[i]; desbuf[i*2+1] = 0; i += 1;);
  fft(desbuf, BD); fft_permute(desbuf, BD);   // permute is MANDATORY: fft() returns bit-reversed
  half = BD * 0.5;
  dst = gc_lin + (1 - gc_meta[1]) * (2*GC_LIN_N) + eng * GC_LIN_N;   // INACTIVE buffer
  i = 0;
  loop(GC_LIN_N,
    t = i / (GC_LIN_N - 1);
    f = 20 * pow(1000, t);                     // 20 Hz .. 20 kHz, log spaced
    f = min(f, srate * 0.5);
    b = f * BD / srate;
    k = floor(b); frac = b - k;
    k >= half ? ( k = half - 1; frac = 1; );
    // |X[k]| for a REAL sequence: bins 0..BD/2 carry all the information
    m = sqrt(desbuf[k*2]*desbuf[k*2] + desbuf[k*2+1]*desbuf[k*2+1]) * (1 - frac)
      + sqrt(desbuf[(k+1)*2]*desbuf[(k+1)*2] + desbuf[(k+1)*2+1]*desbuf[(k+1)*2+1]) * frac;
    dst[i] = m;
    i += 1;
  );
);

// Publish: flip the active index, then bump the generation. Both happen only AFTER every word
// of the inactive buffer is written, so @gfx can never draw a mixture of two kernels.
function gc_publish() (
  gc_meta[1] = 1 - gc_meta[1];
  gc_meta[0] = gc_meta[0] + 1;
);
```

- [ ] **Step 2: Call it from the rebuild branches in `@block`**

In the `hp_dirty` branch, immediately after `hp_dirty = 0; lp_fs[3] = 1; hp_tbuild = time_precise();` add:

```eel2
    act_phase == 1 ? ( gc_build_grid(0); gc_dirty = 1; );
```

and the same in the `lp_dirty` branch with `gc_build_grid(1)`.

Then, at the very end of `@block`, after the `mt_state == 2` block:

```eel2
// One publication per block, after any grids built this pass are complete.
gc_dirty ? ( gc_publish(); gc_dirty = 0; );
```

- [ ] **Step 3: Bump `gen_active` where audible state commits**

Inside `topo_commit` (right after `mt_state = 2;`), add:

```eel2
  gc_meta[2] = gc_meta[2] + 1;   // gen_active: the graph must follow COMMITTED topology
```

This is required because `act_phase`/`act_hp_pl`/`act_lp_pl` change here, in `@block`, and
`@slider` is not guaranteed to run again afterwards — without it the graph could keep drawing a
superseded topology indefinitely.

- [ ] **Step 4: Live check that nothing regressed**

Load V1.0, play audio, sweep HP Freq in Linear at Normal and at High. Expected: no clicks, no
dropouts, CPU close to V0.9. If CPU jumps or the audio stutters at High, the FFT is running more
often than once per rebuild — check the `gc_dirty` gating.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.0"
git commit -m "feat(rcbitnova): V1.0 - realized kernel grid via one FFT, double-buffered publish"
```

---

### Task 7: `@gfx` — axes, traces, domains

**Files:**
- Modify: `JSFX/RCBitNova V1.0` (new `@gfx` section at end of file)

**Interfaces:**
- Consumes: Tasks 5–6.
- Produces: a drawn graph; `gc_x_of_f(f)`, `gc_f_of_x(x)`, `gc_y_of_bits(bits)`, `gc_bits_of_y(y)`.

- [ ] **Step 1: Add the section header and coordinate helpers**

At the very end of the file:

```eel2
@gfx 900 500

// One transform for BOTH drawing and hit-testing. On Retina these must agree or nodes render
// in one place and respond in another.
gc_sc = min(gfx_w / 900, gfx_h / 500);
gc_px = 40 * gc_sc; gc_py = 10 * gc_sc;
gc_pw = gfx_w - gc_px - 10 * gc_sc;
gc_ph = gfx_h - gc_py - 84 * gc_sc;        // leave 60 units of readout + 24 of labels

function gc_x_of_f(f) ( gc_px + gc_pw * (log(min(max(f,20),20000) / 20) / log(1000)); );
function gc_f_of_x(x) ( 20 * pow(1000, min(max((x - gc_px) / gc_pw, 0), 1)); );
function gc_y_of_bits(bits) ( gc_py + gc_ph * (0.5 - min(max(bits,-4),4) / 8); );
function gc_bits_of_y(y) ( (0.5 - (y - gc_py) / gc_ph) * 8; );
function gc_mag_to_bits(m) ( log(max(m, 0.0000001)) / log(2); );   // 1e-7 floor: Brick has exact zeros
```

- [ ] **Step 2: Draw the grid**

```eel2
gfx_set(0.09, 0.09, 0.10, 1); gfx_rect(0, 0, gfx_w, gfx_h);
gfx_set(0.25, 0.25, 0.27, 1);
gc_i = 0;
loop(3,
  gc_f = 100 * pow(10, gc_i);
  gc_gx = gc_x_of_f(gc_f);
  gfx_line(gc_gx, gc_py, gc_gx, gc_py + gc_ph);
  gfx_x = gc_gx + 3 * gc_sc; gfx_y = gc_py + gc_ph - 14 * gc_sc;
  gfx_drawnumber(gc_f, 0);
  gc_i += 1;
);
gc_b = -4;
loop(9,
  gc_gy = gc_y_of_bits(gc_b);
  gfx_set(0.25, 0.25, 0.27, gc_b == 0 ? 1 : 0.5);
  gfx_line(gc_px, gc_gy, gc_px + gc_pw, gc_gy);
  gfx_x = 4 * gc_sc; gfx_y = gc_gy - 6 * gc_sc;
  gfx_set(0.5, 0.5, 0.52, 1); gfx_drawnumber(gc_b, 0);
  gc_b += 1;
);
```

- [ ] **Step 3: Draw one trace per active domain**

```eel2
// Domain order and colours follow ReEQ so the plugin reads familiarly next to it.
// A Both-placed block multiplies into EVERY domain trace: it applies identical coefficients to
// L and R, which by linearity is identical to applying them to M and S.
function gc_draw_domain(dom, r, g, b, dashed)
  local(i, x, f, m, bits, y, py, first) (
  gfx_set(r, g, b, 1);
  first = 1; i = 0;
  loop(GC_N,
    x = gc_px + gc_pw * i / (GC_N - 1);
    f = gc_f_of_x(x);
    m = gc_domain_mag(dom, f);
    bits = gc_mag_to_bits(m);
    y = gc_y_of_bits(bits);
    (!first && !(dashed && (i % 8) < 4)) ? gfx_line(x - gc_pw / (GC_N - 1), py, x, y);
    py = y; first = 0;
    i += 1;
  );
);

// Dashed when M/S-placed and L/R-placed blocks coexist: no set of per-domain scalar traces
// describes the true channel response then, and the user must be able to see that without
// reading the design document.
gc_mixed = (gc_dom_used(1) || gc_dom_used(2)) && (gc_dom_used(3) || gc_dom_used(4));
gc_dom_used(1) ? gc_draw_domain(1, 0.36, 0.75, 0.38, gc_mixed);   // Mid   green
gc_dom_used(2) ? gc_draw_domain(2, 0.36, 0.93, 0.99, gc_mixed);   // Side  cyan
gc_dom_used(3) ? gc_draw_domain(3, 0.94, 0.79, 0.11, gc_mixed);   // Left  yellow
gc_dom_used(4) ? gc_draw_domain(4, 0.84, 0.25, 0.26, gc_mixed);   // Right red
gc_dom_used(0) ? gc_draw_domain(0, 1.0, 1.0, 1.0, 0);             // Both  white
```

`gc_dom_used(d)` returns 1 when any enabled band or filter has placement `d`; `gc_domain_mag(dom, f)`
multiplies `gc_band_mag`/`gc_hplp_mag` over the blocks whose placement is Both or `dom`, reading
`slider134`/`slider138` when `act_phase == 0` and `act_hp_pl`/`act_lp_pl` when `act_phase == 1`.

- [ ] **Step 4: Live verification**

Open the GUI. Expected: dark graph, grid, a white curve that changes as you move band Freq/Gain
sliders. Set one band to Mid — a green trace appears. Add a Left-placed band — both traces go
dashed. Switch Phase to Min with a Brick slope — the HP/LP contribution must **disappear** (Brick
is Off in Min), which is the one case a wrong implementation would draw as a steep cutoff.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.0"
git commit -m "feat(rcbitnova): V1.0 - @gfx axes and per-domain response traces"
```

---

### Task 8: Nodes, dragging, wheel, numeric entry

**Files:**
- Modify: `JSFX/RCBitNova V1.0` (`@gfx`)

- [ ] **Step 1: Draw the nodes**

```eel2
// Node position uses the FULL effective gain including Bit Ratio, so it sits where the audio
// actually is. A shelf node is a HANDLE at (fc, full gain) and deliberately does not lie on its
// own curve, which reaches only half the gain at fc.
gc_b = 0;
loop(N_BANDS,
  gc_s = 10 * (gc_b + 1);
  gc_en = slider(gc_s + 1);
  gc_bits = (slider(gc_s + 5) + slider(gc_s + 6) * 0.01) * slider(gc_s + 7);
  gc_nx = gc_x_of_f(slider(gc_s + 3));
  gc_ny = gc_y_of_bits(gc_bits);
  gc_pl = slider(gc_s + 8);
  gc_pl == 0 ? gfx_set(1,1,1, gc_en ? 1 : 0.3) :
  gc_pl == 1 ? gfx_set(0.36,0.75,0.38, gc_en ? 1 : 0.3) :
  gc_pl == 2 ? gfx_set(0.36,0.93,0.99, gc_en ? 1 : 0.3) :
  gc_pl == 3 ? gfx_set(0.94,0.79,0.11, gc_en ? 1 : 0.3) :
               gfx_set(0.84,0.25,0.26, gc_en ? 1 : 0.3);
  gc_en ? gfx_circle(gc_nx, gc_ny, 6 * gc_sc, 1, 1) : gfx_circle(gc_nx, gc_ny, 6 * gc_sc, 0, 1);
  // over-range: clamp to the edge and print the number so the value is never hidden
  abs(gc_bits) > 4 ? (
    gfx_x = gc_nx + 8 * gc_sc; gfx_y = gc_ny - 6 * gc_sc;
    gfx_drawnumber(gc_bits, 2);
  );
  gc_b += 1;
);
```

- [ ] **Step 2: Add drag with the safe write order**

```eel2
// Writing Macro and Micro is NOT atomic. Choose the order per write: compute both candidate
// intermediates and write the one giving the smaller absolute gain first, so a transient always
// errs toward silence. A fixed order is unsafe - 16.95 -> -16.95 with Micro first is +15.05
// bits, a 33923x bang, the same failure class as V0.8's full-amplitude step.
function gc_write_gain(b, eff_bits)
  local(s, ratio, base, macro, micro, om, ou, im, ia) (
  s = 10 * (b + 1);
  ratio = slider(s + 7);
  ratio == 0 ? ( 0; ) : (          // Ratio 0 has no inverse: the node is locked, not reset
    base = eff_bits / ratio;
    base = min(max(base, -16.999999), 16.999999);
    base = floor(base / 0.05 + 0.5) * 0.05;
    macro = base < 0 ? ceil(base) : floor(base);     // truncation toward zero
    micro = (base - macro) * 100;
    om = slider(s + 5); ou = slider(s + 6);
    im = abs(pow(2, (om + micro * 0.01) * ratio));   // micro written first
    ia = abs(pow(2, (macro + ou * 0.01) * ratio));   // macro written first
    im <= ia ? (
      slider(s + 6) = micro; slider_automate(slider(s + 6));
      slider(s + 5) = macro; slider_automate(slider(s + 5));
    ) : (
      slider(s + 5) = macro; slider_automate(slider(s + 5));
      slider(s + 6) = micro; slider_automate(slider(s + 6));
    );
  );
);
```

Hit-testing, capture and the wheel follow the pinned semantics in spec §5: capture is held by the
node grabbed at mouse-down until release even outside the graph; Shift held **at mouse-down**
locks to the dominant axis; Shift pressed later switches to fine steps (0.01 bit / 1 Hz); wheel up
raises Q; `Esc` during a drag restores the value from mouse-down.

- [ ] **Step 3: Numeric entry into the F / G / Q fields**

Adapt the `gfx_getchar` loop from `Fable Eq Dynamic.jsfx` (~lines 2160–2190): clicking a readout
field gives it focus; digits, `-` and `.` accumulate into a buffer; Enter parses and commits via
`gc_write_gain` (for G) or a direct `slider_automate` write (F, Q); Esc cancels; Backspace deletes.
The field label shows the unit — Hz, bits, Q — so the number's meaning is never ambiguous.

- [ ] **Step 4: Live verification**

Drag each node: frequency, gain and Q change; the values appear in the slider list; automation
records them. Set Bit Ratio to 2 and drag — the node must follow the cursor. Set Bit Ratio to 0 —
the node locks at zero and says so. Type a number into each field. Drag fast across several
integer boundaries with automation recording on and confirm no burst.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.0"
git commit -m "feat(rcbitnova): V1.0 - draggable nodes, safe Macro/Micro writes, numeric entry"
```

---

### Task 9: Transcription gate, bit-accuracy gates, CPU

**Files:**
- Modify: `JSFX/RCBitNova V1.0` (temporary debug dump), `tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Add a temporary curve dump to the JSFX**

Behind a slider or a key press, write `gc_trace`'s first buffer to a file via `file_open`/
`file_var`, for a pinned parameter matrix: shelf plateaus on both sides, `fc`, near-Nyquist,
proportional-Q, Brick at both resolutions, at 48 kHz and 96 kHz.

- [ ] **Step 2: Compare the dump against the oracle**

```python
def test_v10_jsfx_dump_matches_the_oracle(dump_path="/tmp/rcbitnova_curve_dump.txt"):
    """The transcription gate. Python tests prove the Python maths; the shipping graph is a
    SEPARATE EEL2 implementation, and a sign error there still draws a smooth, believable
    curve. Screenshots are not a numeric oracle."""
    import os
    import pytest
    if not os.path.exists(dump_path):
        pytest.skip("no dump present - run the JSFX debug export first")
    rows = [line.split() for line in open(dump_path) if line.strip()]
    worst = 0.0
    for f_s, m_s in rows:
        f = float(f_s); got = float(m_s)
        want = curve.domain_mag(BANDS_FIXTURE, FILTERS_FIXTURE, "both", f, 48000, 1)
        worst = max(worst, abs(curve.mag_to_bits(got) - curve.mag_to_bits(want)))
    assert worst < 0.01, f"JSFX curve deviates from the oracle by {worst} bits"
```

`BANDS_FIXTURE` / `FILTERS_FIXTURE` are module-level dicts matching the pinned matrix exactly.

- [ ] **Step 3: Bit-accuracy gates**

```bash
# no log/dB/pow(10) added to the DSP sections - @gfx is exempt, it is not the audio path
awk '/^@gfx/{exit} {print}' "JSFX/RCBitNova V1.0" > /tmp/v10_dsp_only.txt
diff <(awk '/^@gfx/{exit} {print}' "JSFX/RCBitNova V0.9") /tmp/v10_dsp_only.txt \
  | grep '^>' | grep -vE "^> *//" | grep -E "log|pow *\( *10|[^a-zA-Z]dB[^a-zA-Z]"
# expected: no output
python3 -m pytest tests/test_rcbitnova_dsp.py -q     # expected: all green
```

- [ ] **Step 4: Live gates**

- **Null test V0.9 vs V1.0**, mouse untouched, polarity inverted → digital silence.
- **Primary CPU gate: V0.9 GUI-closed vs V1.0 GUI-closed**, measuring **peak block time and
  xruns**, not only average — the realized-grid FFT runs whether the window is open or not.
  Worst case: High+High, both engines sweeping, at 44.1 / 48 / 96 kHz, small and normal buffers.
- **GUI open vs closed** as a secondary measure of drawing cost.
- Project reload with the GUI open; sample-rate change with the GUI open.

- [ ] **Step 5: Remove the debug dump and commit**

```bash
git add "JSFX/RCBitNova V1.0" tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.0 transcription gate and bit-accuracy gates"
```

---

### Task 10: Fable final review, as-shipped, tag

- [ ] **Step 1: Fable final review**

Dispatch with `model: fable` over `JSFX/RCBitNova V1.0` in full, the diff against V0.9, and spec
rev 5. Ask specifically for: bit-accuracy verdict; whether the DSP path is byte-identical to V0.9
when the GUI is idle; EEL2 parsing traps in the new `@gfx` code; whether `gc_build_grid` can ever
read `desbuf` while `lpk_build` is mid-flight; and whether any drag path can write a slider pair
whose intermediate exceeds both endpoints.

- [ ] **Step 2: Address every P0/P1, then re-run Steps 3–4 of Task 9**

- [ ] **Step 3: Append "As-shipped" to the spec**

Record every live measurement (CPU with and without GUI, peak block time, null-test result), every
deviation from the design and why, every defect found live and how, and what is deferred to V1.1.
Follow V0.9 §13 as the model.

- [ ] **Step 4: Update the memory file and tag**

```bash
git add -A
git commit -m "docs(rcbitnova): V1.0 as-shipped"
git tag rcbitnova-v1.0
git push origin rcbitnova --tags
git ls-remote --tags origin | grep rcbitnova-v1.0     # confirm it landed
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3 per-domain traces, linearity argument, dashed mixed-family marking | 1 (maths), 7 (drawing) |
| §3.1 magnitude sources, Brick precedence by phase, FFT details, active-vs-slider rule | 1, 3, 5, 6, 7 |
| §3.2 log floor | 3 (`mag_to_bits`), 7 (`gc_mag_to_bits`) |
| §3.3 memory inventory, publication protocol, gen_target/gen_active | 4 (model), 5 (reservation), 6 (publish + gen_active) |
| §3.4 target-display contract | 6 (publish at build time) |
| §4 axes in bits, ±4 clamp | 2, 7 |
| §5 nodes, drag, wheel, ratio inversion, canonical split, write order, numeric entry | 2 (maths), 8 (GUI) |
| §6 layout, one transform, Retina, minimum size, edge labels | 7, 8 |
| §7 out of scope | — (nothing to implement) |
| §8 verification, transcription gate, CPU gates | 1–4 (oracle), 9 (gates) |

**Placeholder scan:** every code step carries real code. Task 8 Step 3 and Task 9 Step 1 describe
adapting an existing, cited implementation (`Fable Eq Dynamic.jsfx` lines 2160–2190) and a
throwaway debug export — both are pointed at a concrete source rather than left open.

**Type consistency:** `band` and `hp` dict keys are identical across Tasks 1–4;
`realized_mag_grid`/`sample_grid`/`mag_to_bits`/`CurveCache`/`watched_fields` are spelled the same
everywhere; JSFX symbols `gc_trace`, `gc_lin`, `gc_snap`, `gc_meta`, `gc_svf_mag`, `gc_band_mag`,
`gc_domain_mag`, `gc_dom_used`, `gc_build_grid`, `gc_publish`, `gc_write_gain` are consistent
between Tasks 5–8.

**Dependency checked before writing the plan:** V0.9 already has `svf_set(base, ftype, fc, q, glin)`
as a separate function — but it writes into the **global** `cf` array (`cf[base]…cf[base+6]`), the
live audio coefficients. So the graph must never call it; it reads `cf + b*8` instead, which
`setup_band` has already filled in `@slider`. That is strictly better than recomputing: the drawn
curve uses the identical numbers the audio path uses, so the two cannot drift apart, and no
cross-thread write can occur.
