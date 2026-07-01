# RCBitNova Phase 3b — Mode B Soft (Band-Split, RCBitLimiter) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-band Mode B "Soft" — a band-split limiter with `RCBitLimiter` behaviour (PurestGain-smoothed gain, NO hard clamp; may slightly exceed the ceiling), as the softer sibling of Mode B Brick, selectable via a per-band Dyn Character (Soft/Hard) switch.

**Architecture:** Reuses the Phase-3a band-split + global-lookahead infrastructure. A per-band **Dyn Character** switch selects Soft or Hard within Mode B (and later within Mode A). Mode B **Hard** = the Phase-3a bit-exact clamp path. Mode B **Soft** = same band extraction + lookahead worst-peak envelope (instant attack, smooth release), then a **PurestGain** one-pole smoothing on the gain and **no clamp** (`out = dry_delayed − band_delayed + band_delayed·gain_smoothed`). Prototype-verified: limits the band toward the ceiling, stable, transparent below.

**Tech Stack:** Python 3.11 stdlib (`math`). JSFX (EEL2). pytest. Git.

## Global Constraints

- License **GPL**; preserve upstream headers.
- Per band **Dyn Character**: `0 Soft | 1 Hard`. In Mode B: Soft = RCBitLimiter (smoothed, no clamp), Hard = RCBitBrickwall (bit-exact clamp, Phase 3a). (In Mode A, Hard is Phase 2c — not this phase; a Mode-A band ignores Character=Hard until 2c, behaving as its current Soft.)
- Mode B Soft: worst-peak lookahead envelope `tgt = ceiling/worst if worst>ceiling else 1`; `env = tgt if tgt<env else tgt+(env-tgt)*rel`; **PurestGain gain smoothing** `gcur = (gcur*GSMOOTH + env)/(GSMOOTH+1)` with `GSMOOTH = 400`; recombine `out = dry_delayed − band_delayed + band_delayed·gcur`. **No clamp** (may slightly exceed).
- Bell type only; HP/LP never dynamic. Global lookahead + PDC unchanged from 3a.
- Stereo linking (Linked/Dual-LR/Dual-MS) identical framework to 3a.
- **No `gmem`**; new per-(band,channel) `mbgc` (PurestGain state) instance-local, init 1.
- Builds on Phase 3a. Python pure stdlib. Tests: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`.
- JSFX path `JSFX/RCBitNova V0.1`; deploy to `~/Library/Application Support/REAPER/Effects/`.

---

### Task 1: Mode-B Soft reference (single + stereo) — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `svf_make` (bandpass).
- Produces: `modeb_soft(signal, fc, q, sr, ceiling, look_ms, rel_ms, gsmooth=400.0) -> list`
  and `modeb_soft_stereo(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, dyn_mode, gsmooth=400.0) -> (Lout, Rout)`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def test_modeb_soft_limits_toward_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_soft(sig, 1000.0, 2.0, SR, 0.2, 2.0, 80.0)
    pk = _band_contrib_peak(out, 1000.0, 2.0, SR)
    assert 0.18 <= pk <= 0.24        # near ceiling (soft; steady-state ~= ceiling)

def test_modeb_soft_transparent_below_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.1 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_soft(sig, 1000.0, 2.0, SR, 0.5, 2.0, 80.0)
    assert _band_contrib_peak(out, 1000.0, 2.0, SR) == pytest.approx(0.1, abs=0.01)

def test_modeb_soft_dual_lr_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.modeb_soft_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_lr")
    assert Lo == dsp.modeb_soft(L, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    assert Ro == dsp.modeb_soft(R, 700.0, 2.0, SR, 0.2, 2.0, 80.0)

def test_modeb_soft_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modeb_soft(M, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    So = dsp.modeb_soft(S, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    Lo, Ro = dsp.modeb_soft_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k modeb_soft -q`
Expected: FAIL — `AttributeError: ... 'modeb_soft'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def modeb_soft(signal, fc, q, sr, ceiling, look_ms, rel_ms, gsmooth=400.0):
    """Single-channel Mode-B Soft: band-split + lookahead worst-peak + PurestGain
    gain smoothing (no clamp). May slightly exceed the ceiling on transients."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    br = [0.0] * size; pr = [0.0] * size; dr = [0.0] * size
    wpos = 0; ic1 = ic2 = 0.0; env = 1.0; gcur = 1.0
    out = []
    for x in signal:
        v3 = x - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        b = k * v1
        br[wpos] = b; pr[wpos] = abs(b); dr[wpos] = x
        worst = 0.0
        for i in range(size):
            p = pr[(wpos - i) % size]
            if p > worst:
                worst = p
        tgt = ceiling / worst if worst > ceiling else 1.0
        if tgt < env:
            env = tgt
        else:
            env = tgt + (env - tgt) * rel
            if env > 1.0:
                env = 1.0
        gcur = (gcur * gsmooth + env) * inv_g
        rpos = (wpos - L) % size
        bd = br[rpos]
        out.append(dr[rpos] - bd + bd * gcur)
        wpos = (wpos + 1) % size
    return out


def _modeb_soft_two(chA, chB, fc, q, sr, ceiling, look_ms, rel_ms, linked, gsmooth):
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    bA = [0.0]*size; pA = [0.0]*size; dA = [0.0]*size
    bB = [0.0]*size; pB = [0.0]*size; dB = [0.0]*size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envA = envB = gcA = gcB = 1.0
    outA, outB = [], []

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    for xa, xb in zip(chA, chB):
        v3 = xa - iA2; v1a = a1*iA1 + a2*v3; v2 = iA2 + a2*iA1 + a3*v3
        iA1 = 2.0*v1a - iA1; iA2 = 2.0*v2 - iA2
        v3 = xb - iB2; v1b = a1*iB1 + a2*v3; v2 = iB2 + a2*iB1 + a3*v3
        iB1 = 2.0*v1b - iB1; iB2 = 2.0*v2 - iB2
        ba = k*v1a; bb = k*v1b
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA); wb = _worst(pB)
        if linked:
            w = wa if wa > wb else wb
            tgt = ceiling / w if w > ceiling else 1.0
            if tgt < envA: envA = tgt
            else:
                envA = tgt + (envA - tgt) * rel
                if envA > 1.0: envA = 1.0
            envB = envA
        else:
            tgt = ceiling / wa if wa > ceiling else 1.0
            if tgt < envA: envA = tgt
            else:
                envA = tgt + (envA - tgt) * rel
                if envA > 1.0: envA = 1.0
            tgt = ceiling / wb if wb > ceiling else 1.0
            if tgt < envB: envB = tgt
            else:
                envB = tgt + (envB - tgt) * rel
                if envB > 1.0: envB = 1.0
        gcA = (gcA * gsmooth + envA) * inv_g
        gcB = (gcB * gsmooth + envB) * inv_g
        rpos = (wpos - L) % size
        bda = bA[rpos]; outA.append(dA[rpos] - bda + bda * gcA)
        bdb = bB[rpos]; outB.append(dB[rpos] - bdb + bdb * gcB)
        wpos = (wpos + 1) % size
    return outA, outB


def modeb_soft_stereo(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, dyn_mode, gsmooth=400.0):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modeb_soft_two(M, S, fc, q, sr, ceiling, look_ms, rel_ms, False, gsmooth)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _modeb_soft_two(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, linked, gsmooth)
```

- [ ] **Step 4: Run; then full suite**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Mode-B Soft reference (band-split RCBitLimiter) + tests"
```

---

### Task 2: JSFX — Dyn Character slider + Mode-B Soft path (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Phase-3a Mode-B pass + memory.
- Produces: per-band Dyn Character slider (dyn base `ds+8`: B1=58, B2=68, B3=78, B4=88); `mbgc` PurestGain state (2/band); Mode-B pass branches Soft vs Hard.

- [ ] **Step 1: Add per-band Dyn Character sliders**

After each band's Dyn Mode slider (57/67/77/87) add:

```
slider58:0<0,1,1{Soft,Hard}>B1 Dyn Char
slider68:0<0,1,1{Soft,Hard}>B2 Dyn Char
slider78:0<0,1,1{Soft,Hard}>B3 Dyn Char
slider88:0<0,1,1{Soft,Hard}>B4 Dyn Char
```

- [ ] **Step 2: `@init` — GSMOOTH + `mbgc`**

In `@init`, after the Mode-B memory block (`memset(mbwpos, 0, N_BANDS);`), add:

```eel2
GSMOOTH = 400; inv_gsmooth = 1 / (GSMOOTH + 1);   // PurestGain (Mode-B Soft)
mbgc = bus_dry + MAX_LOOK * 2;                     // PurestGain gain state: 2/band
i = 0; loop(N_BANDS * 2, mbgc[i] = 1; i += 1;);
```

- [ ] **Step 3: `@sample` — branch Mode-B Soft vs Hard**

In the Mode-B pass, replace the clamp+correction block (the lines computing `limA/dcA`
and `limB/dcB`) with a Soft/Hard branch keyed on the Dyn Character slider `slider(50+10*b+8)`:

```eel2
        rpos = (wp - Lk + MAX_LOOK) % MAX_LOOK;
        hard = slider(50 + 10*b + 8);          // 0 Soft, 1 Hard
        bdA = mb_band[baseA + rpos];
        hard ? (
          limA = bdA * mbenv[csA]; abs(limA) > ceil ? (limA = limA > 0 ? ceil : -ceil);
        ) : (
          mbgc[csA] = (mbgc[csA] * GSMOOTH + mbenv[csA]) * inv_gsmooth;
          limA = bdA * mbgc[csA];
        );
        dcA = limA - bdA;
        two ? (
          bdB = mb_band[baseB + rpos];
          hard ? (
            limB = bdB * mbenv[csB]; abs(limB) > ceil ? (limB = limB > 0 ? ceil : -ceil);
          ) : (
            mbgc[csB] = (mbgc[csB] * GSMOOTH + mbenv[csB]) * inv_gsmooth;
            limB = bdB * mbgc[csB];
          );
          dcB = limB - bdB;
        );
```

(Everything else in the Mode-B pass — detector, worst-peak, envelope, domain mapping,
`bus_dry` recombine — is unchanged from Phase 3a.)

- [ ] **Step 4: Deploy**

```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```

- [ ] **Step 5: Live verification in REAPER**

1. **Soft vs Hard:** B1 Bell, Placement Both, Dyn On, **Dyn Mode = B**, Ceiling Macro 2, Lookahead 2 ms. Toggle **Dyn Char Soft ↔ Hard** on a transient-rich band: Hard clamps the band contribution exactly (bit-exact, may sound harder); Soft rides it smoothly toward the ceiling (rounder, may slightly exceed on transients). Steady tones: both sit ~at the ceiling.
2. **Below ceiling / transparent:** Soft passes through cleanly below ceiling.
3. **Linking (Soft):** Both+Linked (no width pump), Dual L/R, Dual M/S — all behave as in Brick, just softer.
4. **PDC unchanged:** Soft still uses the global lookahead (delay reported); toggling Soft/Hard does not change latency.
5. **Regression:** Dyn Mode A (2b) and Mode B Hard (3a) still work; Bypass null; multi-instance independent.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX Dyn Character (Soft/Hard) + Mode-B Soft band-split"
```

---

## Self-Review

**Spec coverage (§4.3 Mode B Soft):**
- Band-split RCBitLimiter (PurestGain smoothing, no clamp) → Tasks 1, 2 (+ prototype). ✓
- Per-band Dyn Character Soft/Hard switch → Task 2. ✓
- Reuses 3a lookahead/PDC/linking → Task 2. ✓
- Bell-only; global lookahead unchanged → Task 2. ✓
- No gmem; `mbgc` instance-local → Task 2. ✓

Deferred: Mode-A Hard (Phase 2c) — a Mode-A band ignores Character=Hard until then.

**Placeholder scan:** clean — all code final.

**Type consistency:** `modeb_soft` mirrors JSFX Soft branch (`gcur=(gcur*GSMOOTH+env)*inv_g`,
`out = dry − band + band*gcur`); Hard branch identical to Phase 3a clamp. `mbgc` offset
(`bus_dry + MAX_LOOK*2`) is past `bus_dry`'s 2*MAX_LOOK region — non-overlapping. Dyn
Character slider `ds+8` doesn't collide (dyn bank uses ds+1..ds+8; next band ds+10).

---

## Next
- Phase 2c: Mode-A Hard cascade + shelf dynamics.
- Phase 4: bell characters (GML/Butterworth/house) — Hermes-delegation candidate.
- Phase 6: GUI (node + analyzer + @serialize + 8 bands).
