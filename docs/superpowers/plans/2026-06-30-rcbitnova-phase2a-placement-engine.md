# RCBitNova Phase 2a — Stereo Placement Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize RCBitNova's static engine from a global-M/S encode to a running-L/R signal with per-band placement (Both / Mid / Side / Left / Right), so any band can act on L, R, M, or S — the foundation for FabFilter-like per-band dynamics (Phase 2b).

**Architecture:** The running signal stays L/R (`spl0`/`spl1`). Each band, by its placement, locally derives its working channel(s) — Both → L&R, Mid/Side → `M=(L+R)/2`,`S=(L−R)/2`, Left/Right → that one channel — applies the band SVF, and writes back to L/R. No global encode/decode. Statically, `Both` is basis-invariant (filtering L&R equally = M&S equally), so this only generalizes routing, not the filter math. Verified against a pure-Python stereo routing reference.

**Tech Stack:** Python 3.11 stdlib (`math`). JSFX (EEL2). pytest. Git.

## Global Constraints

- License **GPL**; preserve upstream headers.
- Running representation is **L/R**; per-band local domain transform (`M=(L+R)/2`, `S=(L−R)/2`; `L=M+S`, `R=M−S`).
- Per-band **Placement**: `0 Both | 1 Mid | 2 Side | 3 Left | 4 Right`.
- Filter topology unchanged: **TPT-SVF (Simper)**, coeffs from existing `svf_make`/`svf_set`.
- **No `gmem`**; instance-local state only. Each band keeps two channel state slots (A/B); single-target placements use slot A.
- This phase is **static only** (no dynamics), **zero-latency**, **4 bands**. Dynamics + Dyn Stereo Mode (Linked/Dual-LR/Dual-MS) are Phase 2b.
- This **replaces** the Phase-1 global-M/S `@sample` and the per-band `{Stereo,Mid,Side}` slider with `{Both,Mid,Side,Left,Right}`. Phase-1 static slider numbers (11–48) otherwise unchanged.
- Python pure stdlib. Tests from repo root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`.
- JSFX path `JSFX/RCBitNova V0.1`; live testing copies it to `~/Library/Application Support/REAPER/Effects/`.

---

### Task 1: Stereo placement routing reference — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `svf_make`, `svf_process` (Phase 1).
- Produces: `process_band_stereo(ftype, placement, fc, q, gain_lin, sr, Lin, Rin) -> tuple[list, list]`
  where `placement in {"both","mid","side","left","right"}`; returns `(Lout, Rout)`.
  This is the routing oracle the JSFX `@sample` mirrors. `svf_process` is stateless
  per call, so each channel gets independent filter state automatically.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_rcbitnova_dsp.py
def _stereo_sigs(n=4096):
    wl = 2 * math.pi * 700.0 / SR
    wr = 2 * math.pi * 1500.0 / SR
    L = [0.5 * math.sin(wl * i) for i in range(n)]
    R = [0.4 * math.sin(wr * i) for i in range(n)]
    return L, R

def test_placement_left_leaves_right_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "left", 700.0, 2.0,
                                         dsp.bit_gain(1, 0, 1), SR, L, R)
    assert Rout == R
    assert Lout == dsp.svf_process(dsp.svf_make("bell", 700.0, 2.0,
                                   dsp.bit_gain(1, 0, 1), SR), L)

def test_placement_right_leaves_left_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "right", 1500.0, 2.0,
                                         dsp.bit_gain(1, 0, 1), SR, L, R)
    assert Lout == L

def test_placement_mid_leaves_side_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "mid", 700.0, 2.0,
                                         dsp.bit_gain(2, 0, 1), SR, L, R)
    side_in = [(l - r) * 0.5 for l, r in zip(L, R)]
    side_out = [(l - r) * 0.5 for l, r in zip(Lout, Rout)]
    assert side_out == pytest.approx(side_in, abs=1e-12)

def test_placement_side_leaves_mid_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "side", 700.0, 2.0,
                                         dsp.bit_gain(2, 0, 1), SR, L, R)
    mid_in = [(l + r) * 0.5 for l, r in zip(L, R)]
    mid_out = [(l + r) * 0.5 for l, r in zip(Lout, Rout)]
    assert mid_out == pytest.approx(mid_in, abs=1e-12)

def test_placement_both_filters_each_channel():
    L, R = _stereo_sigs()
    g = dsp.bit_gain(1, 0, 1)
    Lout, Rout = dsp.process_band_stereo("bell", "both", 700.0, 2.0, g, SR, L, R)
    assert Lout == dsp.svf_process(dsp.svf_make("bell", 700.0, 2.0, g, SR), L)
    assert Rout == dsp.svf_process(dsp.svf_make("bell", 700.0, 2.0, g, SR), R)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k placement -q`
Expected: FAIL — `AttributeError: ... 'process_band_stereo'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to tools/rcbitnova_dsp.py
def process_band_stereo(ftype, placement, fc, q, gain_lin, sr, Lin, Rin):
    """Apply one band to a stereo L/R pair per placement. Running domain is L/R;
    mid/side placements transform locally and recombine."""
    c = svf_make(ftype, fc, q, gain_lin, sr)
    if placement == "both":
        return svf_process(c, Lin), svf_process(c, Rin)
    if placement == "left":
        return svf_process(c, Lin), list(Rin)
    if placement == "right":
        return list(Lin), svf_process(c, Rin)
    # mid / side
    M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
    S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
    if placement == "mid":
        M = svf_process(c, M)
    elif placement == "side":
        S = svf_process(c, S)
    else:
        raise ValueError(f"unknown placement {placement!r}")
    return ([m + s for m, s in zip(M, S)], [m - s for m, s in zip(M, S)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k placement -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Run full suite and commit**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (all Phase 1 + this).

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): stereo placement routing reference + tests"
```

---

### Task 2: JSFX — placement slider + running-L/R @sample refactor (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Phase-1 `cf` (static coeffs), `out_gain`, `setup_band`.
- Produces: per-band placement routing in L/R. Reuses `st` (4/band) as channel A/B
  state. Replaces the global-M/S `@sample`. Verified live; mirrors `process_band_stereo`.

- [ ] **Step 1: Change the per-band placement sliders**

Replace each `B# M/S` slider (`slider18`, `slider28`, `slider38`, `slider48`) so the
enum is the 5-value placement. Example for B1 (apply the same to 28/38/48):

```
slider18:0<0,4,1{Both,Mid,Side,Left,Right}>B1 Placement
```

(So: `slider28:0<0,4,1{Both,Mid,Side,Left,Right}>B2 Placement`, etc.)

- [ ] **Step 2: Replace the `@sample` block with the running-L/R placement engine**

Replace the entire `@sample` block with:

```eel2
@sample
// Running signal stays L/R. Bypass leaves spl0/spl1 untouched.
slider1 != 1 ? (
  b = 0;
  loop(N_BANDS,
    slider(10 * (b + 1) + 1) == 1 ? (          // enable
      base = b * 8; sb = b * 4;
      a1 = cf[base]; a2 = cf[base+1]; a3 = cf[base+2];
      m0 = cf[base+4]; m1 = cf[base+5]; m2 = cf[base+6];
      pl = slider(10 * (b + 1) + 8);           // 0 Both,1 Mid,2 Side,3 Left,4 Right

      // Determine the two working channels (chA, chB) and whether M/S recombine needed.
      pl == 0 ? (                              // Both -> L,R
        chA = spl0; chB = spl1; ms = 0; do_b = 1;
      ) : pl == 3 ? (                          // Left -> L only
        chA = spl0; ms = 0; do_b = 0;
      ) : pl == 4 ? (                          // Right -> R only
        chA = spl1; ms = 0; do_b = 0;
      ) : (                                    // Mid/Side -> M/S
        mid = (spl0 + spl1) * 0.5; sid = (spl0 - spl1) * 0.5;
        ms = 1;
        pl == 1 ? ( chA = mid; do_b = 0; ) : ( chA = sid; do_b = 0; );
      );

      // Filter channel A (slot A state: st[sb], st[sb+1])
      ic1 = st[sb]; ic2 = st[sb+1];
      v3 = chA - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
      st[sb] = 2*v1 - ic1; st[sb+1] = 2*v2 - ic2;
      chA = m0*chA + m1*v1 + m2*v2;

      // Filter channel B if needed (Both; slot B state: st[sb+2], st[sb+3])
      do_b ? (
        ic1 = st[sb+2]; ic2 = st[sb+3];
        v3 = chB - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
        st[sb+2] = 2*v1 - ic1; st[sb+3] = 2*v2 - ic2;
        chB = m0*chB + m1*v1 + m2*v2;
      );

      // Write working channels back to L/R
      pl == 0 ? ( spl0 = chA; spl1 = chB; ) :
      pl == 3 ? ( spl0 = chA; ) :
      pl == 4 ? ( spl1 = chA; ) :
      pl == 1 ? ( spl0 = chA + sid; spl1 = chA - sid; ) :   // Mid filtered, side intact
               ( spl0 = mid + chA; spl1 = mid - chA; );      // Side filtered, mid intact
    );
    b += 1;
  );

  spl0 *= out_gain;
  spl1 *= out_gain;
);
```

(Note: `out_gain` is applied once at the end. `st` slot A is reused for the single
working channel in Mid/Side/Left/Right; slot B only for Both. This mirrors
`process_band_stereo`.)

- [ ] **Step 3: Deploy**

Run:
```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```

- [ ] **Step 4: Live verification in REAPER**

On a stereo source (different content L vs R, or a stereo mix):
1. **Both:** B1 Bell, 1 kHz, Q2, Macro +1, Placement Both → ~+6 dB bump on both channels (as Phase 1). dB still exact.
2. **Left:** Placement Left → only the left channel is EQ'd; right unchanged (check with a stereo analyzer / pan-mono).
3. **Right:** Placement Right → only right EQ'd.
4. **Mid:** Placement Mid → boost on mono/center content; side (stereo-difference) unchanged.
5. **Side:** Placement Side → boost on side content; mid unchanged.
6. **Bypass = null** (bit-identical) and **two-instance independence** (gmem fix) still hold.
7. **Multi-band mixed placements:** B1 Left bell, B2 Side high-shelf, B3 Mid HP — confirm each acts only on its placement and they compose correctly.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): running-L/R placement engine (Both/Mid/Side/Left/Right)"
```

---

## Self-Review

**Spec coverage (§3.1 placement engine, static):**
- Running L/R, per-band local domain transform → Tasks 1, 2. ✓
- Placement Both/Mid/Side/Left/Right → Tasks 1 (reference + tests), 2 (slider + routing). ✓
- Static `Both` basis-invariance (filter L&R) → Task 1 `both` branch, Task 2 `pl==0`. ✓
- Two channel state slots/band, slot A for single targets → Task 2 `st` reuse. ✓
- No gmem → Task 2 (instance-local `st`/`cf`). ✓
- Static-only, zero-latency, 4 bands → whole plan. ✓

Out of scope here (Phase 2b): dynamics, Dyn Stereo Mode (Linked/Dual-LR/Dual-MS),
detector, envelope, ceiling.

**Placeholder scan:** none — all code complete.

**Type consistency:** `process_band_stereo` placement strings (`both/mid/side/left/right`)
map to JSFX `pl` ints `0/1/2/3/4` consistently; recombine math (`L=M+S, R=M−S`) matches
between Python and JSFX; SVF coeff layout `cf[base+0..6]` and recurrence identical to
Phase 1.

---

## Next
- Phase 2b: Soft Mode A dynamics on this placement engine — normalised detector,
  gain envelope, modulated bell-cut, with Dyn Stereo Mode (Linked / Dual L/R / Dual M/S).
  The Soft DSP math is already prototyped/verified (detector ×k normalization,
  envelope, modulated bell-cut converging to ceiling).
