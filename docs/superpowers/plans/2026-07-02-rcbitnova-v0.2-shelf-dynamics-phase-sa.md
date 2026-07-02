# RCBitNova V0.2 Phase S-A: Mode A Shelf Dynamics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend RCBitNova Mode A dynamics (currently Bell-only) to Low Shelf and High Shelf band types — a phase-clean dynamic de-esser / low-end tamer — per the approved spec `docs/superpowers/specs/2026-07-02-rcbitnova-v0.2-shelf-dynamics-design.md`.

**Architecture:** Python DSP mirror first (TDD, equivalence + behavioral tests), then line-by-line JSFX transcription into `JSFX/RCBitNova V0.2`. Detector = HP tap (high shelf) or LP tap (low shelf) of a dedicated SVF at the band's freq with fixed Q = 0.7071; cut = a second shelf filter modulated by the existing Soft+Hard cascade gain, with a tan()-free per-sample coefficient update (`g = g0 * gdyn^0.25` scaling). The live-verified Bell path is NOT touched — the shelf path is a purely additive sibling block.

**Tech Stack:** Python 3.11 stdlib (pytest for tests), EEL2/JSFX, REAPER for live verification.

## Global Constraints

- Work in `~/projects/reascripts/.claude/worktrees/rcbitnova` (branch `rcbitnova`). All paths below are relative to it.
- NEVER modify `JSFX/RCBitNova V0.1` (frozen, tag `rcbitnova-v0.1`). All JSFX edits go to `JSFX/RCBitNova V0.2`.
- Python: 3.11, **stdlib only** (no numpy/scipy). Oracle: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` — 42 tests green at plan start; each task only adds green tests.
- `JSFX/RCBitNova V0.2` must stay **pure ASCII** (non-ASCII crashed REAPER's ascii codec before). No em-dashes in JSFX comments.
- Instance-local memory only (never `gmem`). Phase S-A adds **NO new memory blocks**: shelf dynamics reuses `dst` (detector state), `cst` (cut state), `eg`/`egh` (env gains) — band type is mutually exclusive, so slots never conflict (spec §5).
- EEL2 gotchas (handoff §6): no empty ternary branch; no `1e-30`-style scientific literals; parenthesize nested-assignment clamps `a ? (x = ...);`; per-band sliders via `slider(base + offset)`.
- Mode B gates (`@slider` line ~213 `any_b`/PDC and `@sample` line ~346 Mode B pass) stay **Bell-only in S-A**. A shelf band set to Dyn Mode B is intentionally static until Phase S-B — this is documented, expected, and part of the live checklist. **HARD requirement carried to S-B (adversarial review):** S-B must flip BOTH gates (~213 and ~346) in the SAME commit — flipping only one creates PDC-without-processing or processing-without-PDC, exactly the mismatch the spec's three-gate checklist warns about.
- Every commit ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Bit conventions: `ceiling_lin = 2^(-(Macro + Micro/100))`; detector semantics per spec §2 (unity in passband, 0.7071 at cutoff).

---

### Task 1: Python primitives — `DET_Q` + `shelf_cut_coeffs` + detector-shape tests

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append new section after `modea_cascade_stereo`, line 622)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: `svf_make`, `svf_magnitude` (existing).
- Produces: `DET_Q: float = 0.7071` (module constant) and `shelf_cut_coeffs(shelf_type: str, g0: float, q: float, gdyn: float) -> tuple[float, float, float, float, float, float, float]` returning `(a1, a2, a3, k, m0, m1, m2)`; `shelf_type` is `"lowshelf"` or `"highshelf"`; `g0 = tan(pi*fc/sr)` precomputed by the caller. Task 2 consumes both.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
# ---- Phase S-A: Mode A shelf dynamics ----


def test_shelf_cut_coeffs_match_svf_make():
    # Fast per-sample update (no tan) must equal the full recompute to machine zero.
    for st in ("lowshelf", "highshelf"):
        for fc, q in ((6000.0, 0.7071), (200.0, 1.5)):
            g0 = math.tan(math.pi * fc / SR)
            for gdyn in (1.0, 0.7, 0.5, 0.25, 0.1, 2.0 ** -5):
                fast = dsp.shelf_cut_coeffs(st, g0, q, gdyn)
                full = dsp.svf_make(st, fc, q, gdyn, SR)
                ref = (full["a1"], full["a2"], full["a3"], full["k"],
                       full["m0"], full["m1"], full["m2"])
                for a, b in zip(fast, ref):
                    assert abs(a - b) < 1e-15


def test_shelf_cut_coeffs_identity_at_unity_gain():
    # gdyn == 1 must be a bit-exact pass-through filter (m0=1, m1=0, m2=0).
    for st in ("lowshelf", "highshelf"):
        a1, a2, a3, k, m0, m1, m2 = dsp.shelf_cut_coeffs(
            st, math.tan(math.pi * 3000.0 / SR), 0.7071, 1.0)
        assert m0 == 1.0 and m1 == 0.0 and m2 == 0.0


def test_shelf_detector_shape_high():
    # Spec item 1: HP detector at fixed DET_Q — unity passband, 0.7071 at fc,
    # rejects lows, monotonic (no resonant bump).
    det = dsp.svf_make("hp", 6000.0, dsp.DET_Q, 1.0, SR)
    assert dsp.svf_magnitude(det, 1000.0, SR) < 0.05
    assert abs(dsp.svf_magnitude(det, 6000.0, SR) - 0.7071) < 0.01
    assert dsp.svf_magnitude(det, 16000.0, SR) == pytest.approx(1.0, abs=0.02)
    freqs = (500, 1000, 2000, 4000, 6000, 8000, 12000, 16000, 20000)
    vals = [dsp.svf_magnitude(det, f, SR) for f in freqs]
    assert max(vals) < 1.02
    assert all(b >= a - 1e-3 for a, b in zip(vals, vals[1:]))


def test_shelf_detector_shape_low():
    # LP mirror: unity toward DC, 0.7071 at fc, rejects highs.
    det = dsp.svf_make("lp", 200.0, dsp.DET_Q, 1.0, SR)
    assert dsp.svf_magnitude(det, 20.0, SR) == pytest.approx(1.0, abs=0.02)
    assert abs(dsp.svf_magnitude(det, 200.0, SR) - 0.7071) < 0.01
    assert dsp.svf_magnitude(det, 5000.0, SR) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k shelf`
Expected: **4 failed, 2 passed** — the 4 new tests fail with `AttributeError: module 'tools.rcbitnova_dsp' has no attribute 'shelf_cut_coeffs'` (and `DET_Q`); the 2 passes are pre-existing static-shelf tests that `-k shelf` also matches.

- [ ] **Step 3: Implement** — append to `tools/rcbitnova_dsp.py` after line 622:

```python
# ---- Phase S-A: Mode A shelf dynamics (V0.2) ----

DET_Q = 0.7071  # fixed shelf-region detector Q (Butterworth: monotonic, no bump)


def shelf_cut_coeffs(shelf_type, g0, q, gdyn):
    """Per-sample shelf-cut coefficients without tan(). g0 = tan(pi*fc/sr),
    precomputed once. Matches svf_make(shelf_type, fc, q, gdyn, sr) exactly:
    the only fc-dependent term is g = g0 * gdyn**0.25 (highshelf) or
    g0 / gdyn**0.25 (lowshelf). shelf_type: 'lowshelf' | 'highshelf'."""
    A = math.sqrt(gdyn)
    rA = math.sqrt(A)
    k = 1.0 / q
    if shelf_type == "highshelf":
        g = g0 * rA
        m0, m1, m2 = A * A, k * (1.0 - A) * A, (1.0 - A * A)
    elif shelf_type == "lowshelf":
        g = g0 / rA
        m0, m1, m2 = 1.0, k * (A - 1.0), (A * A - 1.0)
    else:
        raise ValueError(f"unknown shelf_type {shelf_type!r}")
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    return a1, a2, a3, k, m0, m1, m2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 46 passed (42 old + 4 new).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Phase S-A Python - shelf detector Q + tan-free shelf-cut coeffs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Python shelf cascade — `_shelf_cascade_ch` / `shelf_cascade` / `shelf_cascade_stereo` + identity & de-esser tests

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append after `shelf_cut_coeffs`)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: `DET_Q`, `shelf_cut_coeffs` (Task 1); `svf_make`, `env_coeffs`, `gain_env_step` (existing).
- Produces:
  - `shelf_cascade(signal, shelf_type, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms, soft_on, hard_on) -> list` (single channel);
  - `shelf_cascade_stereo(Lin, Rin, shelf_type, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms, soft_on, hard_on, dyn_mode) -> tuple[list, list]` with `dyn_mode` in `("linked", "dual_lr", "dual_ms")`;
  - `_shelf_cascade_ch(...)` internal (same channel plumbing as `_modea_cascade_ch`).
  Task 3 tests consume `shelf_cascade`; the JSFX transcription (Task 4) mirrors `_shelf_cascade_ch` line-by-line.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
def _tone_amp(sig, freq, i0, i1):
    """Amplitude of the `freq` component over window [i0, i1) by correlation."""
    c = s = 0.0
    for i in range(i0, i1):
        w = 2.0 * math.pi * freq * i / SR
        c += sig[i] * math.cos(w)
        s += sig[i] * math.sin(w)
    return 2.0 * math.hypot(c, s) / (i1 - i0)


def test_shelf_cascade_both_stages_off_is_identity():
    # Spec item 3 (equivalence): dynamics fully off -> the cut stage is exact
    # identity, so band output == static shelf output (the cascade models only
    # the post-static cut stage, like modea_cascade).
    sig = [math.sin(0.31 * i) + 0.5 * math.sin(2.7 * i + 1.0) for i in range(2000)]
    for st in ("lowshelf", "highshelf"):
        out = dsp.shelf_cascade(sig, st, 3000.0, 0.7071, SR, 0.25, 0.5,
                                1.0, 80.0, False, False)
        for a, b in zip(out, sig):
            assert abs(a - b) < 1e-12


def test_highshelf_deesser_burst():
    # Spec item 7: 8 kHz burst on a 1 kHz tone; high-shelf band at 6 kHz,
    # Soft only, ceiling 0.25 (2 bits down). Burst ducks toward ceiling;
    # tone unaffected during AND after (full release).
    n = SR
    b0, b1 = int(0.3 * SR), int(0.7 * SR)
    x = []
    for i in range(n):
        v = 0.2 * math.sin(2.0 * math.pi * 1000.0 * i / SR)
        if b0 <= i < b1:
            v += 0.8 * math.sin(2.0 * math.pi * 8000.0 * i / SR)
        x.append(v)
    y = dsp.shelf_cascade(x, "highshelf", 6000.0, 0.7071, SR, 0.25, 0.5,
                          0.5, 60.0, True, False)
    w0, w1 = int(0.5 * SR), int(0.65 * SR)      # steady mid-burst
    red_db = 20.0 * math.log10(_tone_amp(y, 8000.0, w0, w1) /
                               _tone_amp(x, 8000.0, w0, w1))
    q0, q1 = int(0.05 * SR), int(0.25 * SR)     # pre-burst
    tone_db = 20.0 * math.log10(_tone_amp(y, 1000.0, q0, q1) /
                                _tone_amp(x, 1000.0, q0, q1))
    r0, r1 = int(0.9 * SR), int(0.99 * SR)      # post-burst (released)
    rel_db = 20.0 * math.log10(_tone_amp(y, 1000.0, r0, r1) /
                               _tone_amp(x, 1000.0, r0, r1))
    # Measured -6.272 dB: only ~0.27 dB of margin. Deterministic pure-Python
    # math, so it passes reliably - but do NOT tighten this bound, and expect
    # it to move if DET_Q, env coeffs, or window boundaries ever change.
    assert red_db < -6.0
    assert abs(tone_db) < 0.1
    assert abs(rel_db) < 0.1


def test_shelf_cascade_stereo_linked_identical_channels():
    # Linked Both-placement on identical channels must give identical output
    # and equal the single-channel result.
    sig = [0.6 * math.sin(2.0 * math.pi * 9000.0 * i / SR) for i in range(4800)]
    L, R = dsp.shelf_cascade_stereo(sig, sig, "highshelf", 6000.0, 0.7071, SR,
                                    0.25, 0.5, 0.5, 60.0, True, False, "linked")
    mono = dsp.shelf_cascade(sig, "highshelf", 6000.0, 0.7071, SR,
                             0.25, 0.5, 0.5, 60.0, True, False)
    for a, b, m in zip(L, R, mono):
        assert a == b
        assert abs(a - m) < 1e-12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "shelf_cascade or deesser"`
Expected: 3 FAIL — `AttributeError: ... no attribute 'shelf_cascade'`.

- [ ] **Step 3: Implement** — append to `tools/rcbitnova_dsp.py`:

```python
def _shelf_cascade_ch(chA, chB, two, shelf_type, fc, q, sr, cS, cH,
                      atk_ms, rel_ms, soft_on, hard_on, linked):
    """Mode-A shelf dynamics, one or two channels (mirror of _modea_cascade_ch).
    Detector: HP tap (highshelf) / LP tap (lowshelf) of an SVF at fc with fixed
    DET_Q. Cut: full shelf filter of the band's fc/q, gain = gSoft * gHard from
    the existing Soft+Hard cascade. q is the band's shelf Q (audio path only)."""
    high = shelf_type == "highshelf"
    det = svf_make("hp" if high else "lp", fc, DET_Q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    g0 = math.tan(math.pi * fc / sr)
    dA1 = dA2 = dB1 = dB2 = 0.0
    cA1 = cA2 = cB1 = cB2 = 0.0
    esA = ehA = esB = ehB = 1.0
    outA = []
    outB = [] if two else None

    def _gain(level, es, eh):
        if soft_on:
            tS = cS / level if level > cS else 1.0
            es = gain_env_step(es, tS, atk, rel)
            gS = es
        else:
            gS = 1.0
        if hard_on:
            ps = level * gS
            tH = cH / ps if ps > cH else 1.0
            eh = gain_env_step(eh, tH, 0.0, rel)   # instant attack
            gH = eh
        else:
            gH = 1.0
        return gS * gH, es, eh

    def _cut(x, gdyn, c1, c2):
        a1, a2, a3, k, m0, m1, m2 = shelf_cut_coeffs(shelf_type, g0, q, gdyn)
        v3 = x - c2
        v1 = a1 * c1 + a2 * v3
        v2 = c2 + a2 * c1 + a3 * v3
        return m0 * x + m1 * v1 + m2 * v2, 2.0 * v1 - c1, 2.0 * v2 - c2

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - dA2; v1 = da1 * dA1 + da2 * v3; v2 = dA2 + da2 * dA1 + da3 * v3
        dA1 = 2.0 * v1 - dA1; dA2 = 2.0 * v2 - dA2
        lvA = abs(xa - dk * v1 - v2) if high else abs(v2)
        lvB = 0.0
        if two:
            v3 = xb - dB2; v1 = da1 * dB1 + da2 * v3; v2 = dB2 + da2 * dB1 + da3 * v3
            dB1 = 2.0 * v1 - dB1; dB2 = 2.0 * v2 - dB2
            lvB = abs(xb - dk * v1 - v2) if high else abs(v2)
        if linked:
            lev = lvA if lvA > lvB else lvB
            gA, esA, ehA = _gain(lev, esA, ehA)
            gB = gA
        else:
            gA, esA, ehA = _gain(lvA, esA, ehA)
            gB = 1.0
            if two:
                gB, esB, ehB = _gain(lvB, esB, ehB)
        oa, cA1, cA2 = _cut(xa, gA, cA1, cA2)
        outA.append(oa)
        if two:
            ob, cB1, cB2 = _cut(xb, gB, cB1, cB2)
            outB.append(ob)
    return outA, outB


def shelf_cascade(signal, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                  atk_ms, rel_ms, soft_on, hard_on):
    out, _ = _shelf_cascade_ch(signal, signal, False, shelf_type, fc, q, sr,
                               ceil_soft, ceil_hard, atk_ms, rel_ms,
                               soft_on, hard_on, False)
    return out


def shelf_cascade_stereo(Lin, Rin, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                         atk_ms, rel_ms, soft_on, hard_on, dyn_mode):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _shelf_cascade_ch(M, S, True, shelf_type, fc, q, sr, ceil_soft,
                                   ceil_hard, atk_ms, rel_ms, soft_on, hard_on,
                                   False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _shelf_cascade_ch(Lin, Rin, True, shelf_type, fc, q, sr, ceil_soft,
                             ceil_hard, atk_ms, rel_ms, soft_on, hard_on, linked)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 49 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Phase S-A Python - shelf Soft+Hard cascade (de-esser core)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Python behavioral coverage — low-shelf mirror + DC sensitivity

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append at end; no production code expected)

**Interfaces:**
- Consumes: `shelf_cascade` (Task 2), `_tone_amp` (Task 2 test helper).
- Produces: nothing new — characterization tests locking spec items 6 and 8.

- [ ] **Step 1: Write the tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
def test_lowshelf_mirror_tames_low_burst():
    # Spec item 6 (mirror symmetry): 60 Hz burst on a 5 kHz tone; low-shelf
    # band at 200 Hz, Soft only, ceiling 0.25. Burst ducked, tone untouched.
    n = SR
    b0, b1 = int(0.3 * SR), int(0.7 * SR)
    x = []
    for i in range(n):
        v = 0.2 * math.sin(2.0 * math.pi * 5000.0 * i / SR)
        if b0 <= i < b1:
            v += 0.8 * math.sin(2.0 * math.pi * 60.0 * i / SR)
        x.append(v)
    y = dsp.shelf_cascade(x, "lowshelf", 200.0, 0.7071, SR, 0.25, 0.5,
                          0.5, 60.0, True, False)
    w0, w1 = int(0.5 * SR), int(0.65 * SR)
    red_db = 20.0 * math.log10(_tone_amp(y, 60.0, w0, w1) /
                               _tone_amp(x, 60.0, w0, w1))
    q0, q1 = int(0.05 * SR), int(0.25 * SR)
    tone_db = 20.0 * math.log10(_tone_amp(y, 5000.0, q0, q1) /
                                _tone_amp(x, 5000.0, q0, q1))
    r0, r1 = int(0.9 * SR), int(0.99 * SR)
    rel_db = 20.0 * math.log10(_tone_amp(y, 5000.0, r0, r1) /
                               _tone_amp(x, 5000.0, r0, r1))
    assert red_db < -6.0
    assert abs(tone_db) < 0.1
    assert abs(rel_db) < 0.1


def test_lowshelf_detector_reacts_to_dc():
    # Spec item 8: the LP detector is unity at DC by design (rumble/boom tamer);
    # a DC offset above the ceiling gets pulled toward it. Documents the kept
    # behaviour of spec section 2.
    n = SR
    x = [0.5] * n
    y = dsp.shelf_cascade(x, "lowshelf", 100.0, 0.7071, SR, 0.25, 0.125,
                          1.0, 80.0, True, False)
    tail = y[-4800:]
    m = sum(tail) / len(tail)
    assert 0.20 < m < 0.32   # 0.5 * gdyn -> ~0.25 (ceiling), not 0.5
```

- [ ] **Step 2: Run the tests**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 51 passed. These are characterization tests of Task 2's implementation — if either FAILS, that is a real bug in `_shelf_cascade_ch` (most likely the LP-tap level or the low-shelf `g0 / rA` scaling): STOP and debug before proceeding; do not weaken the assertions.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): Phase S-A - low-shelf mirror + DC-sensitivity coverage

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: JSFX transcription into `JSFX/RCBitNova V0.2` + ASCII guard

**Files:**
- Modify: `JSFX/RCBitNova V0.2` (desc line 1; `setup_band_dyn` lines 183-197; new block inserted after the Bell dyn block, i.e. after line 328's closing `);`, before the `// Write working channels back to L/R` comment at line 330)
- Test: `tests/test_rcbitnova_dsp.py` (append ASCII guard)

**Interfaces:**
- Consumes: the verified Python `_shelf_cascade_ch` (Task 2) as the transcription source; existing JSFX memory blocks `det`, `dst`, `cst`, `dp`, `dm`, `bp`, `eg`, `egh`, `hc` — NO new blocks.
- Produces: `JSFX/RCBitNova V0.2` with working Mode A shelf dynamics. Slider surface unchanged (spec §5: no new sliders).

- [ ] **Step 1: Add the ASCII guard test** — append to `tests/test_rcbitnova_dsp.py`:

```python
def test_jsfx_v02_is_pure_ascii():
    # REAPER's ascii codec crashed on an em-dash before (see reels_tempo_map);
    # keep the V0.2 source byte-pure.
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.2"
    data = p.read_bytes()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at offsets {bad[:5]} in RCBitNova V0.2"
```

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k ascii` — Expected: PASS already (V0.2 is a copy of ASCII-clean V0.1). It exists to catch what Steps 2-4 introduce.

- [ ] **Step 2: Detector Q by type in `setup_band_dyn`** — in `JSFX/RCBitNova V0.2` replace the function's opening (current lines 183-190):

```
function setup_band_dyn(b)
  local(s, ds, fc, q, g, k, a1, a2, a3)
(
  s = 10 * (b + 1); ds = 50 + 10 * b;
  fc = slider(s + 3); q = slider(s + 4);
  g = tan($pi * fc / srate); k = 1 / q;              // detector bandpass, unity at fc
  a1 = 1 / (1 + g * (g + k)); a2 = g * a1; a3 = g * a2;
  det[b*4] = a1; det[b*4+1] = a2; det[b*4+2] = a3; det[b*4+3] = k;
```

with:

```
function setup_band_dyn(b)
  local(s, ds, ty, fc, q, qd, g, k, a1, a2, a3)
(
  s = 10 * (b + 1); ds = 50 + 10 * b;
  ty = slider(s + 2);
  fc = slider(s + 3); q = slider(s + 4);
  // Bell: bandpass detector at band Q (unity at fc). Shelf: HP/LP-tap detector
  // at fixed Butterworth Q (spec: monotonic, unity passband, 0.7071 at fc).
  qd = (ty == 1 || ty == 2) ? 0.7071 : q;
  g = tan($pi * fc / srate); k = 1 / qd;
  a1 = 1 / (1 + g * (g + k)); a2 = g * a1; a3 = g * a2;
  det[b*4] = a1; det[b*4+1] = a2; det[b*4+2] = a3; det[b*4+3] = k;
```

(The rest of the function — `dp`/`dm`/`bp` writes — is unchanged. `bp[b*3+1]` keeps the band's shelf Q for the audio-path cut.)

- [ ] **Step 3: Insert the shelf Mode A block** — in `@sample`, immediately after the closing `);` of the Bell dynamics block (line 328) and before `// Write working channels back to L/R`, insert:

```
      // ----- Dynamics (Mode A shelf): Low/High Shelf, Dyn on, Dyn Mode A -----
      // Additive sibling of the Bell block above (types are mutually exclusive,
      // so dst/cst/eg/egh slots are shared safely). Transcribed line-by-line
      // from _shelf_cascade_ch in tools/rcbitnova_dsp.py.
      ty = slider(10 * (b + 1) + 2);
      (dp[b*4+3] == 1 && (ty == 1 || ty == 2) && mbmode[b] == 0) ? (
        qb = bp[b*3+1]; cg = bp[b*3+2];
        da1 = det[b*4]; da2 = det[b*4+1]; da3 = det[b*4+2]; dk = det[b*4+3];
        cS = dp[b*4]; cH = hc[b]; atk = dp[b*4+1]; rel = dp[b*4+2];
        soft_on = slider(50 + 10*b + 8); hard_on = slider(90 + 10*b + 1);
        linked = (pl == 0) && (dm[b] == 0);

        // detector on chA: HP tap (High Shelf) or LP tap (Low Shelf)
        ic1 = dst[sb]; ic2 = dst[sb+1];
        v3 = chA - ic2; v1 = da1*ic1 + da2*v3; v2 = ic2 + da2*ic1 + da3*v3;
        dst[sb] = 2*v1 - ic1; dst[sb+1] = 2*v2 - ic2;
        levA = ty == 2 ? abs(chA - dk*v1 - v2) : abs(v2);
        levB = 0;
        do_b ? (
          ic1 = dst[sb+2]; ic2 = dst[sb+3];
          v3 = chB - ic2; v1 = da1*ic1 + da2*v3; v2 = ic2 + da2*ic1 + da3*v3;
          dst[sb+2] = 2*v1 - ic1; dst[sb+3] = 2*v2 - ic2;
          levB = ty == 2 ? abs(chB - dk*v1 - v2) : abs(v2);
        );

        linked ? ( levA = max(levA, levB); );

        // channel A cascade gain (gSoft atk/rel * gHard instant) - same as Bell
        soft_on ? (
          tS = levA > cS ? cS / levA : 1;
          es = eg[b*2]; coef = tS < es ? atk : rel; es = tS + (es - tS)*coef; eg[b*2] = es; gsA = es;
        ) : ( gsA = 1; );
        hard_on ? (
          ps = levA * gsA;
          tH = ps > cH ? cH / ps : 1;
          eh = egh[b*2]; tH < eh ? eh = tH : ( eh = tH + (eh - tH)*rel; eh = min(eh,1); ); egh[b*2] = eh; ghA = eh;
        ) : ( ghA = 1; );
        gA = gsA * ghA;

        // shelf-cut coeffs without tan(): g = cg*rA (HS) or cg/rA (LS); full
        // m0/m1/m2 output (not the bell x + cm1*v1 shortcut)
        A = sqrt(gA); rA = sqrt(A); ckq = 1 / qb;
        ty == 2 ? (
          cgs = cg * rA; cm0 = A*A; cm1 = ckq*(1-A)*A; cm2 = 1 - A*A;
        ) : (
          cgs = cg / rA; cm0 = 1; cm1 = ckq*(A-1); cm2 = A*A - 1;
        );
        ca1 = 1 / (1 + cgs*(cgs + ckq)); ca2 = cgs * ca1; ca3 = cgs * ca2;
        ic1 = cst[sb]; ic2 = cst[sb+1];
        v3 = chA - ic2; v1 = ca1*ic1 + ca2*v3; v2 = ic2 + ca2*ic1 + ca3*v3;
        cst[sb] = 2*v1 - ic1; cst[sb+1] = 2*v2 - ic2;
        chA = cm0*chA + cm1*v1 + cm2*v2;

        do_b ? (
          linked ? ( gB = gA; ) : (
            soft_on ? (
              tS = levB > cS ? cS / levB : 1;
              es = eg[b*2+1]; coef = tS < es ? atk : rel; es = tS + (es - tS)*coef; eg[b*2+1] = es; gsB = es;
            ) : ( gsB = 1; );
            hard_on ? (
              ps = levB * gsB;
              tH = ps > cH ? cH / ps : 1;
              eh = egh[b*2+1]; tH < eh ? eh = tH : ( eh = tH + (eh - tH)*rel; eh = min(eh,1); ); egh[b*2+1] = eh; ghB = eh;
            ) : ( ghB = 1; );
            gB = gsB * ghB;
          );
          A = sqrt(gB); rA = sqrt(A);
          ty == 2 ? (
            cgs = cg * rA; cm0 = A*A; cm1 = ckq*(1-A)*A; cm2 = 1 - A*A;
          ) : (
            cgs = cg / rA; cm0 = 1; cm1 = ckq*(A-1); cm2 = A*A - 1;
          );
          ca1 = 1 / (1 + cgs*(cgs + ckq)); ca2 = cgs * ca1; ca3 = cgs * ca2;
          ic1 = cst[sb+2]; ic2 = cst[sb+3];
          v3 = chB - ic2; v1 = ca1*ic1 + ca2*v3; v2 = ic2 + ca2*ic1 + ca3*v3;
          cst[sb+2] = 2*v1 - ic1; cst[sb+3] = 2*v2 - ic2;
          chB = cm0*chB + cm1*v1 + cm2*v2;
        );
      );
```

- [ ] **Step 4: Bump the desc line and document the detector semantics** — replace line 1 with:

```
desc: RCBitNova V0.2 - Bit-Accurate M/S Dynamic EQ (static + Mode A + Mode B Soft/Hard cascade + shelf dynamics A)
```

and add to the header comment block (after the `// Filters: ...` lines, keeping pure ASCII) the spec's §2 control-text sentence — JSFX sliders cannot carry help text, so the header is the manual:

```
// Shelf dynamics: Shelf ceiling = peak of the shelf-region detector
// (HP tap for High Shelf, LP tap for Low Shelf, fixed Q 0.7071);
// -3 dB at cutoff, passband -> unity. The Low Shelf detector is unity
// at DC by design (rumble/boom tamer) - it reacts to DC offset.
```

- [ ] **Step 5: Transcription self-review (line-by-line, against Task 2's Python)** — verify each of these before committing; every item is a past live-crash class:

1. Detector taps: `ty == 2` (High Shelf) -> `abs(chA - dk*v1 - v2)`; `ty == 1` (Low Shelf) -> `abs(v2)`; matches `lvA = abs(xa - dk*v1 - v2) if high else abs(v2)`.
2. Cut coeffs vs `shelf_cut_coeffs`: HS `g = cg*rA`, LS `g = cg/rA`; `m` rows match the Python tuples exactly; `ckq = 1/qb` uses the BAND's Q, `qd = 0.7071` is used only inside `setup_band_dyn` for `det[]`.
3. No empty ternary branches; both branches of every `? ( ) : ( )` contain statements.
4. No scientific literals (`1e-…`) anywhere in the new code.
5. State slots: detector `dst[sb..sb+3]`, cut `cst[sb..sb+3]`, envelopes `eg[b*2..]`/`egh[b*2..]` — identical to the Bell block (shared safely; band type is exclusive).
6. New local names (`ty`, `rA`, `ckq`, `cgs`, `cm0`, `cm2`) do not collide with live variables used AFTER the block (`pl`, `mid`, `sid`, `both_ms`, `do_b`, `chA`, `chB` are the only values consumed later, and none are clobbered — `cm1` is reused from the Bell block but always dead by then since the Bell and shelf blocks are mutually exclusive by `ty`).
7. Mode B gates untouched: `@slider` `any_b` line and the `@sample` Mode B pass still say `slider(10*(b+1)+2) == 0` (Bell-only until Phase S-B).
8. File byte-pure ASCII: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k ascii` passes.

- [ ] **Step 6: Run the full oracle**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 52 passed (51 + ASCII guard). Python is the correctness proof; the JSFX has no automated harness — Step 5's review plus Task 5's live check cover the transcription.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V0.2" tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Phase S-A JSFX - Mode A shelf dynamics in V0.2 + ASCII guard

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Deploy + live verification with Dima + push

**Files:**
- Deploy copy only (no repo changes except the memory-file note below).

- [ ] **Step 1: Deploy to REAPER**

```bash
cp "JSFX/RCBitNova V0.2" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.2"
```

- [ ] **Step 2: Live checklist (Dima drives, via FX window or TCP)** — all on real program material (vocal for HS, boomy mix for LS):

1. Load `RCBitNova V0.2` fresh — plugin loads with no EEL2 syntax error (the transcription gate).
2. Sanity: bypass on/off = clean null; a static Bell band behaves exactly as in V0.1 (regression).
3. **High Shelf de-esser:** B1 Type = High Shelf, ~6 kHz, Dyn on, Mode A, Soft on (ceiling ~2 bits), Hard off — sibilants duck audibly, body untouched; release breathes naturally.
4. **Hard stage:** Soft off / Hard on (ceiling ~1 bit) — instant-attack pinning; then BOTH on (Hard ceiling higher) — cascade behaves like the Bell cascade ("last policeman").
5. **Low Shelf tamer:** Type = Low Shelf, ~150-200 Hz, Soft on — boom ducks, top end untouched.
6. **Placements:** Mid-only HS de-ess (Side untouched); Both + Dual M/S (Side-heavy sibilance ducks in Side only); Linked (no width pumping).
7. **Expected static (documented):** shelf band + Dyn Mode B = static, no PDC change — S-B is the next phase. Also HP/LP + Dyn = static (unchanged rule).
8. CPU eyeball: no meaningful increase vs V0.1 with one dynamic shelf active.

- [ ] **Step 3: On any failure** — undo nothing in REAPER; fix in Python mirror first if the failure is behavioral (then re-transcribe), or in the JSFX only if it is a pure transcription slip; re-run the full oracle; redeploy; re-check.

- [ ] **Step 4: After Dima confirms — push for backup**

```bash
git push origin rcbitnova
```

(No tag yet: `rcbitnova-v0.2` is tagged only when ALL of V0.2 — S-A and S-B — is live-verified.)

- [ ] **Step 5: Update the auto-memory file** `~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`: record S-A live status (verified or what failed), and that S-B (Mode B shelf split) is next.

---

## Plan self-review (done at write time)

- **Spec coverage:** §2 detector -> Tasks 1/4; §3 Mode A cut -> Tasks 2/4; §5 gates/state-reuse -> Task 4 (gate ~267 sibling block; ~213/~346 explicitly deferred to S-B per Global Constraints); §6 permanent tests items 1, 3, 5, 6, 7, 8 -> Tasks 1-3 (items 2, 4 are S-B: split identity + Mode B off == identity); §6 live checks -> Task 5 (PDC-for-shelf check moves to S-B with the gates).
- **Placeholders:** none; every step has complete code or an exact command.
- **Type consistency:** `shelf_cut_coeffs` 7-tuple order `(a1,a2,a3,k,m0,m1,m2)` matches `svf_make` dict order and the JSFX `cf[]` layout; `shelf_cascade*` signatures match `modea_cascade*` conventions (`dyn_mode` strings identical).
