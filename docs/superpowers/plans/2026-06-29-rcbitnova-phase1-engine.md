# RCBitNova Phase 1 — Static Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working static mid-side bit-EQ JSFX (5 filter types, per-band M/S, RCBit Macro/Micro/BitRatio gain, low-cramping TPT-SVF, instance-local memory) plus a pytest-verified pure-Python DSP mirror.

**Architecture:** A pure-Python reference module (`tools/rcbitnova_dsp.py`) holds the exact DSP math and is unit-tested with pytest. The JSFX (`JSFX/RCBitNova V0.1`) is a line-by-line transcription of that verified math, so numeric correctness is guarded offline and the live REAPER check confirms transcription + integration. All filters use Andy Simper's TPT state-variable form (exact gain at cutoff → no cramping). All state lives in instance-local JSFX memory — never `gmem`.

**Tech Stack:** Python 3.11 stdlib only (no numpy/scipy — magnitude via steady-state sine). JSFX (EEL2). pytest. Git.

## Global Constraints

- License: **GPL**; preserve upstream copyright headers on any reused code.
- Bit logic: 1 bit = 6.0206 dB. `gain_lin = 2^((Macro + Micro/100) * BitRatio)`.
- Bit-accurate gain stages use exact `pow(2, ...)`; filtering is float DSP.
- Filter topology: **TPT-SVF (Simper)** for all types; gain convention `A = sqrt(gain_lin)`.
- **No `gmem`** anywhere — all filter state/buffers in instance-local memory (this is the core bug fix vs Artur's EQ).
- Phase 1 is **zero-latency, slider-driven, 4 bands**; no dynamics, no GUI, no linear phase (later phases).
- Python module is **pure stdlib** (`math` only). Run tests from repo root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`.
- JSFX file path: `JSFX/RCBitNova V0.1` (no extension, matches repo convention). Live testing copies it to `~/Library/Application Support/REAPER/Effects/`.

---

### Task 1: Bit-gain core (Python)

**Files:**
- Create: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `bit_gain(macro: float, micro: float, bit_ratio: float) -> float`,
  `bit_gain_db(macro, micro, bit_ratio) -> float`, constant `ONE_BIT_DB = 6.0206`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rcbitnova_dsp.py
import math
import pytest
from tools import rcbitnova_dsp as dsp


def test_bit_gain_integer_macro_is_exact_power_of_two():
    assert dsp.bit_gain(1, 0, 1) == 2.0
    assert dsp.bit_gain(2, 0, 1) == 4.0
    assert dsp.bit_gain(-1, 0, 1) == 0.5
    assert dsp.bit_gain(0, 0, 1) == 1.0


def test_bit_gain_micro_is_fraction_of_a_bit():
    assert dsp.bit_gain(0, 100, 1) == pytest.approx(2.0)
    assert dsp.bit_gain(0, -100, 1) == pytest.approx(0.5)


def test_bit_gain_bit_ratio_scales_bits():
    assert dsp.bit_gain(1, 0, 0.5) == pytest.approx(2 ** 0.5)
    assert dsp.bit_gain(2, 0, 0.25) == pytest.approx(2 ** 0.5)


def test_bit_gain_db():
    assert dsp.bit_gain_db(1, 0, 1) == pytest.approx(6.0206)
    assert dsp.bit_gain_db(0, 0, 1) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.rcbitnova_dsp'` (or AttributeError).

- [ ] **Step 3: Write minimal implementation**

```python
# tools/rcbitnova_dsp.py
"""Pure-Python DSP mirror for RCBitNova (no numpy/scipy).

Mirrors the exact math transcribed into JSFX, so numeric correctness is
verified by pytest offline. Filters use Andy Simper's TPT state-variable form.
"""
from __future__ import annotations

import math

ONE_BIT_DB = 6.0206


def bit_gain(macro: float, micro: float, bit_ratio: float) -> float:
    """Linear gain: 2 ^ ((macro + micro/100) * bit_ratio)."""
    return 2.0 ** ((macro + micro / 100.0) * bit_ratio)


def bit_gain_db(macro: float, micro: float, bit_ratio: float) -> float:
    """Display dB for a bit gain."""
    return (macro + micro / 100.0) * bit_ratio * ONE_BIT_DB
```

Also create `tools/__init__.py` if it does not exist (empty file) so `from tools import ...` works.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): bit-gain core + tests"
```

---

### Task 2: M/S codec (Python)

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `encode_ms(l, r) -> tuple[float, float]` returning `(mid, side)`;
  `decode_ms(m, s) -> tuple[float, float]` returning `(left, right)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_rcbitnova_dsp.py
def test_ms_encode():
    assert dsp.encode_ms(1.0, 0.0) == (0.5, 0.5)
    assert dsp.encode_ms(1.0, 1.0) == (1.0, 0.0)


def test_ms_roundtrip():
    for l, r in [(0.3, -0.7), (1.0, 0.0), (-0.2, 0.9)]:
        m, s = dsp.encode_ms(l, r)
        l2, r2 = dsp.decode_ms(m, s)
        assert l2 == pytest.approx(l)
        assert r2 == pytest.approx(r)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'encode_ms'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to tools/rcbitnova_dsp.py
def encode_ms(l: float, r: float) -> tuple[float, float]:
    return (l + r) * 0.5, (l - r) * 0.5


def decode_ms(m: float, s: float) -> tuple[float, float]:
    return m + s, m - s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): M/S codec + tests"
```

---

### Task 3: TPT-SVF engine + magnitude helper — Lowpass (Python)

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces:
  - `svf_make(ftype: str, fc: float, q: float, gain_lin: float, sr: float) -> dict`
    where `ftype in {"bell","lowshelf","highshelf","hp","lp"}` and the dict has keys
    `a1,a2,a3,k,m0,m1,m2`.
  - `svf_process(coeffs: dict, samples: list[float]) -> list[float]`.
  - `svf_magnitude(coeffs: dict, freq: float, sr: float, n: int = 1<<15) -> float`
    (steady-state sine magnitude ratio).
- Later tasks (4–6) extend `svf_make` with more `ftype` branches.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_rcbitnova_dsp.py
SR = 48000


def test_lowpass_passes_dc_blocks_highs():
    c = dsp.svf_make("lp", 1000.0, 0.707, 1.0, SR)
    assert dsp.svf_magnitude(c, 20.0, SR) == pytest.approx(1.0, abs=0.01)
    assert dsp.svf_magnitude(c, 18000.0, SR) < 0.02
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py::test_lowpass_passes_dc_blocks_highs -q`
Expected: FAIL — `AttributeError: ... 'svf_make'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to tools/rcbitnova_dsp.py
def svf_make(ftype: str, fc: float, q: float, gain_lin: float, sr: float) -> dict:
    """Andy Simper TPT-SVF coefficients. A = sqrt(gain_lin)."""
    A = math.sqrt(gain_lin)
    if ftype == "lp":
        g = math.tan(math.pi * fc / sr); k = 1.0 / q
        m0, m1, m2 = 0.0, 0.0, 1.0
    else:
        raise ValueError(f"unknown ftype {ftype!r}")
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    return {"a1": a1, "a2": a2, "a3": a3, "k": k, "m0": m0, "m1": m1, "m2": m2}


def svf_process(coeffs: dict, samples) -> list:
    a1, a2, a3 = coeffs["a1"], coeffs["a2"], coeffs["a3"]
    m0, m1, m2 = coeffs["m0"], coeffs["m1"], coeffs["m2"]
    ic1 = ic2 = 0.0
    out = []
    for v0 in samples:
        v3 = v0 - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out.append(m0 * v0 + m1 * v1 + m2 * v2)
    return out


def svf_magnitude(coeffs: dict, freq: float, sr: float, n: int = 1 << 15) -> float:
    """Steady-state magnitude: RMS(out_tail) / RMS(in_tail) for a unit sine."""
    w = 2.0 * math.pi * freq / sr
    samples = [math.sin(w * i) for i in range(n)]
    out = svf_process(coeffs, samples)
    half = n // 2
    acc_o = sum(out[i] * out[i] for i in range(half, n))
    acc_i = sum(samples[i] * samples[i] for i in range(half, n))
    return math.sqrt(acc_o / acc_i)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py::test_lowpass_passes_dc_blocks_highs -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): TPT-SVF engine + magnitude helper (lowpass)"
```

---

### Task 4: Highpass (Python)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (extend `svf_make`)
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `svf_make`, `svf_magnitude` from Task 3.
- Produces: `ftype == "hp"` branch in `svf_make`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_rcbitnova_dsp.py
def test_highpass_blocks_dc_passes_highs():
    c = dsp.svf_make("hp", 1000.0, 0.707, 1.0, SR)
    assert dsp.svf_magnitude(c, 20.0, SR) < 0.02
    assert dsp.svf_magnitude(c, 18000.0, SR) == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py::test_highpass_blocks_dc_passes_highs -q`
Expected: FAIL — `ValueError: unknown ftype 'hp'`.

- [ ] **Step 3: Write minimal implementation**

In `svf_make`, add before the `else: raise` branch:

```python
    elif ftype == "hp":
        g = math.tan(math.pi * fc / sr); k = 1.0 / q
        m0, m1, m2 = 1.0, -k, -1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py::test_highpass_blocks_dc_passes_highs -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): SVF highpass + test"
```

---

### Task 5: Bell + cramping acceptance (Python)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (extend `svf_make`)
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `ftype == "bell"` branch in `svf_make`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_rcbitnova_dsp.py
def test_bell_exact_gain_at_center_and_unity_far_away():
    for bits, expect in [(1, 2.0), (2, 4.0), (-1, 0.5)]:
        c = dsp.svf_make("bell", 1000.0, 2.0, dsp.bit_gain(bits, 0, 1), SR)
        assert dsp.svf_magnitude(c, 1000.0, SR) == pytest.approx(expect, rel=0.01)
        assert dsp.svf_magnitude(c, 60.0, SR) == pytest.approx(1.0, abs=0.01)


def test_bell_no_cramping_at_top_octave():
    # A high bell at 18 kHz @ 48k must still reach its exact center gain.
    c = dsp.svf_make("bell", 18000.0, 2.0, dsp.bit_gain(2, 0, 1), SR)
    assert dsp.svf_magnitude(c, 18000.0, SR) == pytest.approx(4.0, rel=0.02)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k bell -q`
Expected: FAIL — `ValueError: unknown ftype 'bell'`.

- [ ] **Step 3: Write minimal implementation**

In `svf_make`, add a branch:

```python
    elif ftype == "bell":
        g = math.tan(math.pi * fc / sr); k = 1.0 / (q * A)
        m0, m1, m2 = 1.0, k * (A * A - 1.0), 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k bell -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): SVF bell + cramping acceptance test"
```

---

### Task 6: Low-shelf + High-shelf (Python)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (extend `svf_make`)
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `ftype in {"lowshelf","highshelf"}` branches in `svf_make`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_rcbitnova_dsp.py
def test_lowshelf_boosts_dc_unity_highs():
    c = dsp.svf_make("lowshelf", 300.0, 0.707, dsp.bit_gain(1, 0, 1), SR)
    assert dsp.svf_magnitude(c, 20.0, SR) == pytest.approx(2.0, rel=0.02)
    assert dsp.svf_magnitude(c, 18000.0, SR) == pytest.approx(1.0, abs=0.02)


def test_highshelf_boosts_highs_unity_dc():
    c = dsp.svf_make("highshelf", 4000.0, 0.707, dsp.bit_gain(1, 0, 1), SR)
    assert dsp.svf_magnitude(c, 20000.0, SR) == pytest.approx(2.0, rel=0.02)
    assert dsp.svf_magnitude(c, 20.0, SR) == pytest.approx(1.0, abs=0.02)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k shelf -q`
Expected: FAIL — `ValueError: unknown ftype 'lowshelf'`.

- [ ] **Step 3: Write minimal implementation**

In `svf_make`, add branches:

```python
    elif ftype == "lowshelf":
        g = math.tan(math.pi * fc / sr) / math.sqrt(A); k = 1.0 / q
        m0, m1, m2 = 1.0, k * (A - 1.0), (A * A - 1.0)
    elif ftype == "highshelf":
        g = math.tan(math.pi * fc / sr) * math.sqrt(A); k = 1.0 / q
        m0, m1, m2 = A * A, k * (1.0 - A) * A, (1.0 - A * A)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k shelf -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): SVF low/high shelf + tests"
```

---

### Task 7: JSFX skeleton — memory, sliders, pass-through (live)

**Files:**
- Create: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Produces: a loadable JSFX with global sliders 1–3 and per-band sliders for 4 bands
  (band b∈0..3 uses base `10*(b+1)`: enable, type, freq, Q, macro, micro, bitratio,
  mstarget), instance-local arrays `cf` (8/band) and `st` (4/band). Consumed by Tasks 8–9.

- [ ] **Step 1: Write the JSFX skeleton (audio pass-through)**

```eel2
// JSFX/RCBitNova V0.1
desc: RCBitNova V0.1 - Bit-Accurate M/S EQ (Phase 1: static engine)

// License: GPL - http://www.gnu.org/licenses/gpl.html
// Bit logic: 1 bit = 6.0206 dB; gain_lin = 2^((macro + micro/100) * bitratio).
// Filters: TPT state-variable (Andy Simper / Cytomic). All state instance-local.

in_pin:Left
in_pin:Right
out_pin:Left
out_pin:Right

slider1:0<0,1,1{Off,On}>-Bypass
slider2:0<-16,16,1>-Output Macro (bits)
slider3:0<-100,100,0.1>-Output Micro (% bit)

slider11:1<0,1,1{Off,On}>B1 Enable
slider12:0<0,4,1{Bell,Low Shelf,High Shelf,High Pass,Low Pass}>B1 Type
slider13:100<20,20000,1>B1 Freq
slider14:0.707<0.1,10,0.001>B1 Q
slider15:0<-16,16,1>B1 Macro (bits)
slider16:0<-100,100,0.1>B1 Micro (% bit)
slider17:1<0,3,0.05>B1 Bit Ratio
slider18:0<0,2,1{Stereo,Mid,Side}>B1 M/S

slider21:0<0,1,1{Off,On}>B2 Enable
slider22:0<0,4,1{Bell,Low Shelf,High Shelf,High Pass,Low Pass}>B2 Type
slider23:1000<20,20000,1>B2 Freq
slider24:0.707<0.1,10,0.001>B2 Q
slider25:0<-16,16,1>B2 Macro (bits)
slider26:0<-100,100,0.1>B2 Micro (% bit)
slider27:1<0,3,0.05>B2 Bit Ratio
slider28:0<0,2,1{Stereo,Mid,Side}>B2 M/S

slider31:0<0,1,1{Off,On}>B3 Enable
slider32:0<0,4,1{Bell,Low Shelf,High Shelf,High Pass,Low Pass}>B3 Type
slider33:3000<20,20000,1>B3 Freq
slider34:0.707<0.1,10,0.001>B3 Q
slider35:0<-16,16,1>B3 Macro (bits)
slider36:0<-100,100,0.1>B3 Micro (% bit)
slider37:1<0,3,0.05>B3 Bit Ratio
slider38:0<0,2,1{Stereo,Mid,Side}>B3 M/S

slider41:0<0,1,1{Off,On}>B4 Enable
slider42:0<0,4,1{Bell,Low Shelf,High Shelf,High Pass,Low Pass}>B4 Type
slider43:10000<20,20000,1>B4 Freq
slider44:0.707<0.1,10,0.001>B4 Q
slider45:0<-16,16,1>B4 Macro (bits)
slider46:0<-100,100,0.1>B4 Micro (% bit)
slider47:1<0,3,0.05>B4 Bit Ratio
slider48:0<0,2,1{Stereo,Mid,Side}>B4 M/S

@init
N_BANDS = 4;
cf = 0;     // coeffs: 8 slots per band (instance-local memory, NOT gmem)
st = 64;    // state: 4 slots per band (M ic1,ic2; S ic1,ic2)
memset(st, 0, N_BANDS * 4);

@sample
spl0 = spl0;
spl1 = spl1;
```

- [ ] **Step 2: Deploy and load in REAPER**

Run:
```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```
In REAPER: add FX → JSFX → "RCBitNova V0.1" on a track.
Expected: loads with no red error text; all 4 band slider groups visible; audio passes
through unchanged (bit-identical) since `@sample` is pass-through.

- [ ] **Step 3: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX skeleton - sliders, instance-local memory, pass-through"
```

---

### Task 8: JSFX @slider — coefficient computation (live, mirrors Python)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: slider bank + `cf`/`st` from Task 7.
- Produces: per-band coeffs written to `cf[b*8 + 0..6]` =
  `a1,a2,a3,k,m0,m1,m2`, computed identically to Python `svf_make` (Tasks 3–6).

- [ ] **Step 1: Add the EEL coefficient functions and `@slider` block**

Insert after the `@init` block (before `@sample`):

```eel2
function svf_set(base, ftype, fc, q, glin)
  local(A, g, k, m0, m1, m2, a1, a2, a3)
(
  A = sqrt(glin);
  ftype == 0 ? (                 // Bell
    g = tan($pi * fc / srate); k = 1 / (q * A);
    m0 = 1; m1 = k * (A * A - 1); m2 = 0;
  ) : ftype == 1 ? (             // Low Shelf
    g = tan($pi * fc / srate) / sqrt(A); k = 1 / q;
    m0 = 1; m1 = k * (A - 1); m2 = A * A - 1;
  ) : ftype == 2 ? (             // High Shelf
    g = tan($pi * fc / srate) * sqrt(A); k = 1 / q;
    m0 = A * A; m1 = k * (1 - A) * A; m2 = 1 - A * A;
  ) : ftype == 3 ? (             // High Pass
    g = tan($pi * fc / srate); k = 1 / q;
    m0 = 1; m1 = -k; m2 = -1;
  ) : (                          // Low Pass
    g = tan($pi * fc / srate); k = 1 / q;
    m0 = 0; m1 = 0; m2 = 1;
  );
  a1 = 1 / (1 + g * (g + k)); a2 = g * a1; a3 = g * a2;
  cf[base]   = a1; cf[base+1] = a2; cf[base+2] = a3; cf[base+3] = k;
  cf[base+4] = m0; cf[base+5] = m1; cf[base+6] = m2;
);

function setup_band(b)
  local(s, glin)
(
  s = 10 * (b + 1);                                  // slider base: 10,20,30,40
  glin = pow(2, (slider(s+5) + slider(s+6) * 0.01) * slider(s+7));
  svf_set(b * 8, slider(s+2), slider(s+3), slider(s+4), glin);
);

@slider
out_gain = pow(2, slider2 + slider3 * 0.01);
b = 0;
loop(N_BANDS, setup_band(b); b += 1;);
```

(Note: slider indices used by `setup_band(b)` for band b are base `s=10*(b+1)`:
`s+2`=type, `s+3`=freq, `s+4`=Q, `s+5`=macro, `s+6`=micro, `s+7`=bitratio. Enable is
`s+1` and M/S is `s+8`, read in Task 9.)

- [ ] **Step 2: Reload in REAPER and verify no errors**

Run:
```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```
In REAPER, the FX still loads with no error. (No audible change yet — `@sample` is still
pass-through; coeffs are computed but unused.) Confirm no "srate" / divide errors appear.

- [ ] **Step 3: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX @slider SVF coefficient computation"
```

---

### Task 9: JSFX @sample — M/S engine + per-band SVF + output trim (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: `cf`/`st`, `out_gain`, per-band enable/M-S sliders.
- Produces: the working static EQ. Verified live against Python `svf_magnitude` values
  and against "Artur Mix bit eq".

- [ ] **Step 1: Replace the `@sample` block**

Replace the existing `@sample` block with:

```eel2
@sample
slider1 == 1 ? (
  // Bypass: pass through untouched
) : (
  m = (spl0 + spl1) * 0.5;
  s = (spl0 - spl1) * 0.5;

  b = 0;
  loop(N_BANDS,
    slider(10 * (b + 1) + 1) == 1 ? (       // enable
      base = b * 8; sb = b * 4;
      a1 = cf[base]; a2 = cf[base+1]; a3 = cf[base+2];
      m0 = cf[base+4]; m1 = cf[base+5]; m2 = cf[base+6];
      tgt = slider(10 * (b + 1) + 8);        // 0 Stereo, 1 Mid, 2 Side

      tgt != 2 ? (                            // process M (Stereo or Mid)
        ic1 = st[sb]; ic2 = st[sb+1];
        v3 = m - ic2;
        v1 = a1 * ic1 + a2 * v3;
        v2 = ic2 + a2 * ic1 + a3 * v3;
        st[sb]   = 2 * v1 - ic1;
        st[sb+1] = 2 * v2 - ic2;
        m = m0 * m + m1 * v1 + m2 * v2;
      );
      tgt != 1 ? (                            // process S (Stereo or Side)
        ic1 = st[sb+2]; ic2 = st[sb+3];
        v3 = s - ic2;
        v1 = a1 * ic1 + a2 * v3;
        v2 = ic2 + a2 * ic1 + a3 * v3;
        st[sb+2] = 2 * v1 - ic1;
        st[sb+3] = 2 * v2 - ic2;
        s = m0 * s + m1 * v1 + m2 * v2;
      );
    );
    b += 1;
  );

  spl0 = (m + s) * out_gain;
  spl1 = (m - s) * out_gain;
);
```

- [ ] **Step 2: Deploy and verify tonal correctness live**

Run:
```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```
In REAPER:
1. On a track with pink noise / music, add RCBitNova V0.1.
2. B1: Enable On, Type Bell, Freq 1000, Q 2, Macro +1, M/S Stereo. Confirm a clear
   +1-bit (~6 dB) bump at 1 kHz on a spectrum analyzer (gain ×2 at center — matches
   `test_bell_exact_gain_at_center_and_unity_far_away`).
3. Set B1 M/S = Mid, then Side: confirm the boost applies only to the mid (mono) or
   side (stereo-difference) content respectively.
4. Set B1 Type High Shelf, Freq 4000, Macro +1: confirm highs lift, DC unaffected.
5. Bypass On: confirm bit-identical pass-through (null test against a dry copy).

- [ ] **Step 3: Verify the gmem bug is fixed (multi-instance)**

In REAPER: put RCBitNova V0.1 on **two** different tracks with **different** band
settings (e.g. track A: bell +2 @ 200 Hz; track B: high-shelf −2 @ 8 kHz). Play both.
Expected: each track shows ONLY its own EQ curve; settings on one do not alter the
other (this is what Artur's `gmem`-based EQ got wrong). Confirms instance-local state.

- [ ] **Step 4: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX @sample M/S engine + per-band SVF + output trim"
```

---

## Self-Review

**Spec coverage (Phase 1 scope, §8.1):**
- M/S codec → Tasks 2, 9. ✓
- Static bands Bell + Shelf + HP/LP → Tasks 3–6 (Python), 8–9 (JSFX). ✓
- Bit-gain Macro/Micro/BitRatio → Tasks 1, 8. ✓
- Matched/low-cramping (TPT-SVF) → Tasks 3–6 + cramping test (Task 5); JSFX 8. ✓
- Instance-local memory (gmem fix) → Task 7 (`cf`/`st`, no gmem), verified Task 9 step 3. ✓
- Zero-latency, slider-driven, 4 bands → Tasks 7–9. ✓
- Per-band M/S Stereo/Mid/Side incl. stereo handling → Task 9. ✓

Out of Phase-1 scope (correctly deferred): dynamics, bell characters, linear phase,
HQ oversampling, GUI/analyzer, @serialize, 8 bands.

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `svf_make`/`svf_process`/`svf_magnitude` signatures consistent
across Tasks 3–6; JSFX `svf_set`/`setup_band` use the same coeff layout `cf[base+0..6]`
in Tasks 8 and 9; slider index scheme `10*(b+1)+offset` identical in Tasks 8 and 9.

---

## Next phases (separate plans, after Phase 1 ships)
- Phase 2: Dynamics Mode A (detector, Soft/Hard bell·shelf-cut, Stereo-linked, shared delay).
- Phase 3: Dynamics Mode B (band-split RCBit Soft/Brick + bit-exact clamp).
- Phase 4: Bell characters (GML / Butterworth / house).
- Phase 5: Phase + Quality modes (Linear-Phase FIR, Eco/HQ oversampling).
- Phase 6: GUI (FFT analyzer, draggable nodes, panel, @serialize); expand to 8 bands.
