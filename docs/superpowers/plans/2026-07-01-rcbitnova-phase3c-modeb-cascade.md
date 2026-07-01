# RCBitNova Phase 3c — Mode B Soft+Hard Cascade (two ceilings) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Mode B's exclusive Soft/Hard switch with an independent **Soft + Hard cascade** on two ceilings: Soft rides musically toward a Soft Ceiling (PurestGain lag lets fast transients through); Hard, instant, bit-exact clamps what Soft missed at a higher Hard Ceiling ("last policeman").

**Architecture:** One lookahead per band. Soft stage = PurestGain-smoothed envelope toward `ceil_soft` → `gSoft` (=1 if off). Hard stage acts on the post-soft peak (`worst·gSoft`): instant-attack envelope toward `ceil_hard` → `gHard` (=1 if off), plus a bit-exact clamp at `ceil_hard`. Combined band gain = `gSoft·gHard`; `limited = clamp(band_delayed·gSoft·gHard, ceil_hard)` (clamp only if Hard on). Prototype-verified: sustained → soft ceiling (soft dominates, no double-reduction), each stage alone matches Phase 3a/3b exactly.

**Tech Stack:** Python 3.11 stdlib (`math`). JSFX (EEL2). pytest. Git.

## Global Constraints

- License **GPL**; preserve headers.
- Soft and Hard are **independent** (both may be on = cascade). Two ceilings, both powers of two:
  `ceil_soft = 2^(-(SoftCeilMacro+SoftCeilMicro/100))`, `ceil_hard = 2^(-(HardCeilMacro+HardCeilMicro/100))`.
  Hard Ceiling is typically *higher/louder* (fewer bits below 0) — it only catches Soft's overshoots.
- Cascade math (per channel, one lookahead worst-peak `worst`):
  - `gSoft`: if Soft on, `tgtS = ceil_soft/worst if worst>ceil_soft else 1`; env instant-attack + release (`envS`); PurestGain `gcS = (gcS*GSMOOTH+envS)*inv`, `GSMOOTH=400`. Else `gcS=1`.
  - `gHard`: if Hard on, `ps = worst*gcS`; `tgtH = ceil_hard/ps if ps>ceil_hard else 1`; env instant-attack + release (`envH`). Else `envH=1`.
  - `g = gcS*envH`; `lim = band_delayed*g`; if Hard on, bit-exact clamp `|lim|>ceil_hard -> ±ceil_hard`.
  - `out = dry_delayed - band_delayed + lim`.
- Equivalences (used as test oracles): Soft-only == Phase-3b `modeb_soft`; Hard-only == Phase-3a `modeb_brick` (with its ceiling = `ceil_hard`).
- Bell type only; global lookahead + PDC unchanged (§3a). Stereo linking unchanged (Linked shares `worst`).
- **No `gmem`**; new per-(band,channel) `mbeh` (hard env) + per-band `hc` (hard ceiling) instance-local.
- **Control-model change:** the exclusive per-band Dyn Char {Soft|Hard} (`slider ds+8`) becomes **Soft on/off**; a second slider bank adds **Hard on/off + Hard Ceiling (Macro/Micro)**. Existing per-band Ceiling (`ds+3/ds+4`) is relabelled **Soft Ceiling**.
- This phase covers **Mode B only**; Mode A cascade is Phase 2c (uses Attack-based soft vs instant hard on the bell).
- Python pure stdlib. Tests: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. JSFX at `JSFX/RCBitNova V0.1`, deploy to REAPER Effects.

---

### Task 1: Mode-B cascade reference (single + stereo) — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `svf_make` (bandpass), Phase-3a `modeb_brick`, Phase-3b `modeb_soft` (as oracles).
- Produces:
  - `modeb_cascade(signal, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms, soft_on, hard_on, gsmooth=400.0) -> list`
  - `modeb_cascade_stereo(Lin, Rin, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms, soft_on, hard_on, dyn_mode, gsmooth=400.0) -> (Lout, Rout)`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def test_cascade_soft_only_equals_modeb_soft():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    a = dsp.modeb_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 0)
    b = dsp.modeb_soft(sig, 1000.0, 2.0, SR, 0.2, 2.0, 120.0)
    assert a == pytest.approx(b, abs=1e-12)

def test_cascade_hard_only_equals_modeb_brick():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    a = dsp.modeb_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 0, 1)
    b = dsp.modeb_brick(sig, 1000.0, 2.0, SR, 0.4, 2.0, 120.0)  # hard ceiling
    assert a == pytest.approx(b, abs=1e-12)

def test_cascade_both_sustained_settles_to_soft_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    assert _band_contrib_peak(out, 1000.0, 2.0, SR) == pytest.approx(0.2, rel=0.05)

def test_cascade_stereo_dual_ms_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modeb_cascade(M, 700.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    So = dsp.modeb_cascade(S, 700.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    Lo, Ro = dsp.modeb_cascade_stereo(L, R, 700.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k cascade -q`
Expected: FAIL — `AttributeError: ... 'modeb_cascade'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def _modeb_cascade_ch(chA, chB, two, fc, q, sr, cS, cH, look_ms, rel_ms,
                      soft_on, hard_on, linked, gsmooth):
    """Core: 1 or 2 channels through the Soft+Hard cascade (one lookahead).
    Returns (outA, outB) where outB is None if not `two`."""
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
    envSA = gcA = envHA = 1.0
    envSB = gcB = envHB = 1.0
    outA, outB = [], ([] if two else None)

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    def _stage(worst, envS, gc, envH):
        if soft_on:
            tS = cS / worst if worst > cS else 1.0
            envS = tS if tS < envS else min(1.0, tS + (envS - tS) * rel)
            gc = (gc * gsmooth + envS) * inv_g
        else:
            gc = 1.0
        if hard_on:
            ps = worst * gc
            tH = cH / ps if ps > cH else 1.0
            envH = tH if tH < envH else min(1.0, tH + (envH - tH) * rel)
        else:
            envH = 1.0
        return gc * envH, envS, gc, envH

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - iA2; v1a = a1*iA1 + a2*v3; v2 = iA2 + a2*iA1 + a3*v3
        iA1 = 2.0*v1a - iA1; iA2 = 2.0*v2 - iA2
        ba = k * v1a
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        if two:
            v3 = xb - iB2; v1b = a1*iB1 + a2*v3; v2 = iB2 + a2*iB1 + a3*v3
            iB1 = 2.0*v1b - iB1; iB2 = 2.0*v2 - iB2
            bb = k * v1b
            bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA)
        wb = _worst(pB) if two else 0.0
        if linked:
            w = wa if wa > wb else wb
            gA, envSA, gcA, envHA = _stage(w, envSA, gcA, envHA)
            gB = gA
        else:
            gA, envSA, gcA, envHA = _stage(wa, envSA, gcA, envHA)
            gB = 1.0
            if two:
                gB, envSB, gcB, envHB = _stage(wb, envSB, gcB, envHB)
        rpos = (wpos - L) % size
        bda = bA[rpos]; lim = bda * gA
        if hard_on and abs(lim) > cH:
            lim = cH if lim > 0 else -cH
        outA.append(dA[rpos] - bda + lim)
        if two:
            bdb = bB[rpos]; lim = bdb * gB
            if hard_on and abs(lim) > cH:
                lim = cH if lim > 0 else -cH
            outB.append(dB[rpos] - bdb + lim)
        wpos = (wpos + 1) % size
    return outA, outB


def modeb_cascade(signal, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms,
                  soft_on, hard_on, gsmooth=400.0):
    out, _ = _modeb_cascade_ch(signal, signal, False, fc, q, sr, ceil_soft, ceil_hard,
                               look_ms, rel_ms, soft_on, hard_on, False, gsmooth)
    return out


def modeb_cascade_stereo(Lin, Rin, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms,
                         soft_on, hard_on, dyn_mode, gsmooth=400.0):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modeb_cascade_ch(M, S, True, fc, q, sr, ceil_soft, ceil_hard,
                                   look_ms, rel_ms, soft_on, hard_on, False, gsmooth)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    A, B = _modeb_cascade_ch(Lin, Rin, True, fc, q, sr, ceil_soft, ceil_hard,
                             look_ms, rel_ms, soft_on, hard_on, linked, gsmooth)
    return A, B
```

- [ ] **Step 4: Run to verify pass; then full suite**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (all — new cascade tests + the untouched primitives).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Mode-B Soft+Hard cascade reference + equivalence tests"
```

---

### Task 2: JSFX — control model (Soft/Hard toggles + two ceilings) + cascade path (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Phase-3a/3b Mode-B pass + memory.
- Produces: relabelled Soft Ceiling; per-band **Soft on/off** (repurposed `ds+8`); second bank **Hard on/off + Hard Ceiling** (base2 = 90+10b: 91-93, 101-103, 111-113, 121-123); `mbeh` (hard env, 2/band) + `hc` (hard ceiling lin, 1/band); Mode-B pass replaced by the cascade.

- [ ] **Step 1: Relabel + repurpose sliders and add the Hard bank**

Change the Ceiling labels to "Soft Ceiling" and the Dyn Char slider to "Soft" (for each band; shown for B1 — apply to 63/64→"Soft Ceiling", 73/74, 83/84, and 58/68/78/88→"Soft"):

```
slider53:1<0,16,1>B1 Soft Ceiling Macro (bits below 0)
slider54:0<-100,100,0.1>B1 Soft Ceiling Micro (% bit)
slider58:1<0,1,1{Off,On}>B1 Soft
```

(Default `slider58` = 1/On.) Then add the Hard bank at the end of the slider list:

```
slider91:0<0,1,1{Off,On}>B1 Hard
slider92:0<0,16,1>B1 Hard Ceiling Macro (bits below 0)
slider93:0<-100,100,0.1>B1 Hard Ceiling Micro (% bit)
slider101:0<0,1,1{Off,On}>B2 Hard
slider102:0<0,16,1>B2 Hard Ceiling Macro (bits below 0)
slider103:0<-100,100,0.1>B2 Hard Ceiling Micro (% bit)
slider111:0<0,1,1{Off,On}>B3 Hard
slider112:0<0,16,1>B3 Hard Ceiling Macro (bits below 0)
slider113:0<-100,100,0.1>B3 Hard Ceiling Micro (% bit)
slider121:0<0,1,1{Off,On}>B4 Hard
slider122:0<0,16,1>B4 Hard Ceiling Macro (bits below 0)
slider123:0<-100,100,0.1>B4 Hard Ceiling Micro (% bit)
```

- [ ] **Step 2: `@init` — `mbeh` + `hc`**

After the `mbgc` init block, add:

```eel2
mbeh = mbgc + N_BANDS * 2;   // Mode-B hard env per (band,channel): 2/band
hc   = mbeh + N_BANDS * 2;   // hard ceiling (linear) per band: 1/band
i = 0; loop(N_BANDS * 2, mbeh[i] = 1; i += 1;);
```

- [ ] **Step 3: `@slider` — compute hard ceiling per band**

In the band loop that calls `setup_band_dyn`, or right after it, add hard-ceiling
computation (base2 = 90 + 10*b):

```eel2
b = 0;
loop(N_BANDS,
  hc[b] = pow(2, -(slider(90 + 10*b + 2) + slider(90 + 10*b + 3) * 0.01));
  b += 1;
);
```

(`dp[b*4]` remains the Soft Ceiling. `slider(50+10*b+8)` is now Soft on/off; `slider(90+10*b+1)` is Hard on/off.)

- [ ] **Step 4: `@sample` — replace the Mode-B Soft/Hard branch with the cascade**

Replace the entire block from `rpos = (wp - Lk + MAX_LOOK) % MAX_LOOK;` through the
`dcB = limB - bdB;` (the Phase-3b Soft/Hard exclusive branch) with:

```eel2
        rpos = (wp - Lk + MAX_LOOK) % MAX_LOOK;
        soft_on = slider(50 + 10*b + 8);
        hard_on = slider(90 + 10*b + 1);
        cS = dp[b*4]; cH = hc[b];

        // ----- channel A cascade gain -----
        soft_on ? (
          tS = worstA > cS ? cS / worstA : 1;
          esa = mbenv[csA]; tS < esa ? esa = tS : ( esa = tS + (esa - tS)*rel; esa = min(esa,1); ); mbenv[csA] = esa;
          mbgc[csA] = (mbgc[csA] * GSMOOTH + esa) * inv_gsmooth;
        ) : ( mbgc[csA] = 1; );
        hard_on ? (
          ps = worstA * mbgc[csA];
          tH = ps > cH ? cH / ps : 1;
          eha = mbeh[csA]; tH < eha ? eha = tH : ( eha = tH + (eha - tH)*rel; eha = min(eha,1); ); mbeh[csA] = eha;
        ) : ( mbeh[csA] = 1; );
        gA = mbgc[csA] * mbeh[csA];
        bdA = mb_band[baseA + rpos];
        limA = bdA * gA; hard_on ? ( abs(limA) > cH ? (limA = limA > 0 ? cH : -cH); );
        dcA = limA - bdA;

        two ? (
          // ----- channel B cascade gain (linked shares A's gain) -----
          linked ? (
            gB = gA;
          ) : (
            soft_on ? (
              tS = worstB > cS ? cS / worstB : 1;
              esb = mbenv[csB]; tS < esb ? esb = tS : ( esb = tS + (esb - tS)*rel; esb = min(esb,1); ); mbenv[csB] = esb;
              mbgc[csB] = (mbgc[csB] * GSMOOTH + esb) * inv_gsmooth;
            ) : ( mbgc[csB] = 1; );
            hard_on ? (
              ps = worstB * mbgc[csB];
              tH = ps > cH ? cH / ps : 1;
              ehb = mbeh[csB]; tH < ehb ? ehb = tH : ( ehb = tH + (ehb - tH)*rel; ehb = min(ehb,1); ); mbeh[csB] = ehb;
            ) : ( mbeh[csB] = 1; );
            gB = mbgc[csB] * mbeh[csB];
          );
          bdB = mb_band[baseB + rpos];
          limB = bdB * gB; hard_on ? ( abs(limB) > cH ? (limB = limB > 0 ? cH : -cH); );
          dcB = limB - bdB;
        );
```

(For `linked`, channel B reuses `gA` — but note linked should base the gain on
`max(worstA,worstB)`. Adjust: when `linked`, compute worst = `max(worstA,worstB)` and run
the A-stage on that. Implementer: in the linked case, set `worstA = max(worstA, worstB)`
BEFORE the channel-A cascade block, so both channels share the max-based gain. Add this
one line right after `worstB` is computed and before the channel-A cascade:
`linked ? ( worstA = max(worstA, worstB); );`)

Also update the `@slider` `any_b` gate and the Mode-A gate: a Mode-B band is "active" when
`Dyn on && Dyn Mode==B && Bell` (unchanged); the cascade runs regardless of which of
Soft/Hard is on (if both off, gA=1 → transparent, which is fine).

- [ ] **Step 5: Deploy**

```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```

- [ ] **Step 6: Live verification in REAPER**

1. **Soft only** (Soft On, Hard Off): identical to Phase-3b Soft (rounded ride to Soft Ceiling).
2. **Hard only** (Soft Off, Hard On): identical to Phase-3a Brick at the Hard Ceiling.
3. **Cascade (both on):** Soft Ceiling 2 bits, Hard Ceiling 0-1 bits (higher). Sustained band → sits at Soft Ceiling; fast transients that Soft rounds past are caught hard at the Hard Ceiling (audible "policeman"). Never exceeds Hard Ceiling.
4. **Neither on** (both off, Dyn on, Mode B): transparent.
5. **Linking:** Both+Linked/DualLR/DualMS behave as before, now with the cascade.
6. **Regression:** Mode A (2b) still works; Bypass null; PDC correct; multi-instance independent.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): Mode-B Soft+Hard cascade (two ceilings, last policeman)"
```

---

## Self-Review

**Spec coverage (§4.4 / §4.6b cascade, Mode B):**
- Independent Soft + Hard, two ceilings → Tasks 1, 2. ✓
- Cascade math (gSoft smoothed, gHard instant on post-soft, clamp) → Tasks 1, 2 (+ prototype). ✓
- Soft-only ≡ 3b, Hard-only ≡ 3a (equivalence tests) → Task 1. ✓
- Linking / placement unchanged → Task 2. ✓
- No gmem; `mbeh`/`hc` instance-local → Task 2. ✓

Deferred: Mode A cascade (Phase 2c). Shelf dynamics, bell characters, GUI later.

**Placeholder scan:** clean — all code final.

**Type consistency:** cascade gain `gcS*envH` + clamp identical between `_modeb_cascade_ch`
and JSFX; `mbenv`=envS, `mbgc`=gcS, `mbeh`=envH reused consistently; hard ceiling `hc[b]`
matches `ceil_hard`. Slider map: Soft `ds+8`, Hard `90+10b+1`, Hard Ceiling `90+10b+2/3`.

---

## Next
- Phase 2c: Mode A Soft+Hard cascade on the bell (Attack-based soft vs instant hard).
- Phase 4: bell characters. Phase 6: GUI (+ 8 bands).
