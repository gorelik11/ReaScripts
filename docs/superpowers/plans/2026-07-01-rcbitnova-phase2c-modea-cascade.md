# RCBitNova Phase 2c — Mode A Soft+Hard Cascade (bell-cut) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Mode A (Dynamic EQ / bell-cut) the same independent Soft+Hard cascade as Mode B: Soft rides the bell down toward a Soft Ceiling with the user Attack (lets fast transients through); Hard is an instant-attack bell-cut toward a higher Hard Ceiling that catches those transients. No clamp (gain modulation), zero-latency.

**Architecture:** Reuses the shared cascade controls (Soft on/off, Hard on/off, Soft/Hard Ceilings) already added in Phase 3c. Per active channel, on the instantaneous post-static band level `level = |k·v1|`: `gSoft = env(atk/rel → ceil_soft)` (=1 if off), `gHard = env(instant attack, rel → ceil_hard)` computed on `level·gSoft` (=1 if off); bell gain = `gSoft·gHard`, applied via the modulated TPT-SVF bell. Verified by the equivalence `soft-only ≡ Phase-2b modea_process`.

**Tech Stack:** Python 3.11 stdlib (`math`). JSFX (EEL2). pytest. Git.

## Global Constraints

- License **GPL**; preserve headers.
- Mode A cascade (per channel), instantaneous level (no lookahead, zero-latency):
  - `gSoft`: if Soft on, `tS = ceil_soft/level if level>ceil_soft else 1`; `envS = gain_env_step(envS, tS, atk, rel)`; `gS=envS`. Else `gS=1`.
  - `gHard`: if Hard on, `ps = level·gS`; `tH = ceil_hard/ps if ps>ceil_hard else 1`; `envH = gain_env_step(envH, tH, 0.0, rel)` (instant attack). Else `gH=1`.
  - bell gain `g = gS·gH`; applied as the modulated bell-cut (`A=sqrt(g)`, `ck=1/(q·A)`, `cm1=ck·(A²−1)`, `out = x + cm1·cv1`). **No clamp** (bell-gain modulation, no absolute guarantee — this is Mode A).
- Uses the shared controls: `ceil_soft = dp[b*4]` (Soft Ceiling), `ceil_hard = hc[b]` (Hard Ceiling), Soft = `slider(50+10b+8)`, Hard = `slider(90+10b+1)`, Attack/Release = existing per-band.
- Equivalence oracle: Soft-only == Phase-2b `modea_process` (same ceiling, atk, rel).
- Bell + Shelf detectors: Mode A is Bell-only this phase (matches current gate); shelf dynamics later.
- Stereo linking unchanged (Linked → level = `max(levA, levB)`, shared gain).
- **No `gmem`**; add per-(band,channel) `egh` (Mode-A hard env) instance-local, init 1. (Mode-A soft env reuses existing `eg`.)
- Python pure stdlib. Tests: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. JSFX at `JSFX/RCBitNova V0.1`.

---

### Task 1: Mode-A cascade reference (single + stereo) — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `svf_make` (bandpass), `env_coeffs`, `gain_env_step`, Phase-2b `modea_process` (oracle).
- Produces:
  - `modea_cascade(signal, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms, soft_on, hard_on) -> list`
  - `modea_cascade_stereo(Lin, Rin, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms, soft_on, hard_on, dyn_mode) -> (Lout, Rout)`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def test_modea_cascade_soft_only_equals_modea_process():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    a = dsp.modea_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 0)
    b = dsp.modea_process(sig, 1000.0, 2.0, SR, 0.2, 5.0, 80.0)
    assert a == pytest.approx(b, abs=1e-12)


def test_modea_cascade_both_sustained_near_soft_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modea_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 1.0, 80.0, 1, 1)
    pk = max(abs(v) for v in out[-2000:])
    assert 0.18 <= pk <= 0.26      # bell-cut pulls band toward soft ceiling


def test_modea_cascade_stereo_dual_ms_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modea_cascade(M, 700.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 1)
    So = dsp.modea_cascade(S, 700.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 1)
    Lo, Ro = dsp.modea_cascade_stereo(L, R, 700.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 1, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k modea_cascade -q`
Expected: FAIL — `AttributeError: ... 'modea_cascade'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def _modea_cascade_ch(chA, chB, two, fc, q, sr, cS, cH, atk_ms, rel_ms,
                      soft_on, hard_on, linked):
    det = svf_make("bandpass", fc, q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    cg = math.tan(math.pi * fc / sr)
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

    def _cut(x, g, c1, c2):
        A = math.sqrt(g); ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = x - c2; cv1 = ca1 * c1 + ca2 * cv3; cv2 = c2 + ca2 * c1 + ca3 * cv3
        return x + cm1 * cv1, 2.0 * cv1 - c1, 2.0 * cv2 - c2

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - dA2; v1a = da1 * dA1 + da2 * v3; v2 = dA2 + da2 * dA1 + da3 * v3
        dA1 = 2.0 * v1a - dA1; dA2 = 2.0 * v2 - dA2
        lvA = abs(dk * v1a)
        lvB = 0.0
        if two:
            v3 = xb - dB2; v1b = da1 * dB1 + da2 * v3; v2 = dB2 + da2 * dB1 + da3 * v3
            dB1 = 2.0 * v1b - dB1; dB2 = 2.0 * v2 - dB2
            lvB = abs(dk * v1b)
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


def modea_cascade(signal, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms, soft_on, hard_on):
    out, _ = _modea_cascade_ch(signal, signal, False, fc, q, sr, ceil_soft, ceil_hard,
                               atk_ms, rel_ms, soft_on, hard_on, False)
    return out


def modea_cascade_stereo(Lin, Rin, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms,
                         soft_on, hard_on, dyn_mode):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modea_cascade_ch(M, S, True, fc, q, sr, ceil_soft, ceil_hard,
                                   atk_ms, rel_ms, soft_on, hard_on, False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    A, B = _modea_cascade_ch(Lin, Rin, True, fc, q, sr, ceil_soft, ceil_hard,
                             atk_ms, rel_ms, soft_on, hard_on, linked)
    return A, B
```

- [ ] **Step 4: Run to verify pass; then full suite**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Mode-A Soft+Hard cascade reference + equivalence tests"
```

---

### Task 2: JSFX — Mode-A cascade in @sample (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: shared cascade controls (3c) + Mode-A block (2b).
- Produces: `egh` (Mode-A hard env, 2/band); Mode-A dynamic block computes `gS·gH` and applies the bell-cut.

- [ ] **Step 1: `@init` — add `egh`**

After the `hc = ...` / `mbeh` init block, add:

```eel2
egh = hc + N_BANDS;   // Mode-A hard env per (band,channel): 2/band
i = 0; loop(N_BANDS * 2, egh[i] = 1; i += 1;);
```

- [ ] **Step 2: `@sample` — replace the Mode-A envelope + cut with the cascade**

In the Mode-A block (gated `dp[b*4+3]==1 && Bell && mbmode[b]==0`), after the detector
computes `levA`/`levB`, replace the existing `linked ? (...) : (...)` envelope block AND
the two `cut chA`/`cut chB` blocks with the cascade. Insert cascade controls at the top of
the block (right after `linked = (pl==0)&&(dm[b]==0);` line, replacing the old
`ceil = dp[b*4]; atk = ...; rel = ...;`):

```eel2
        cS = dp[b*4]; cH = hc[b]; atk = dp[b*4+1]; rel = dp[b*4+2];
        soft_on = slider(50 + 10*b + 8); hard_on = slider(90 + 10*b + 1);
```

Then, after the detector `levA`/`levB` computation, replace the envelope+cut with:

```eel2
        linked ? ( levA = max(levA, levB); );

        // channel A cascade gain
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

        A = sqrt(gA); ck = 1 / (qb * A);
        ca1 = 1 / (1 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2; cm1 = ck * (A*A - 1);
        ic1 = cst[sb]; ic2 = cst[sb+1];
        v3 = chA - ic2; v1 = ca1*ic1 + ca2*v3; v2 = ic2 + ca2*ic1 + ca3*v3;
        cst[sb] = 2*v1 - ic1; cst[sb+1] = 2*v2 - ic2;
        chA = chA + cm1 * v1;

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
          A = sqrt(gB); ck = 1 / (qb * A);
          ca1 = 1 / (1 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2; cm1 = ck * (A*A - 1);
          ic1 = cst[sb+2]; ic2 = cst[sb+3];
          v3 = chB - ic2; v1 = ca1*ic1 + ca2*v3; v2 = ic2 + ca2*ic1 + ca3*v3;
          cst[sb+2] = 2*v1 - ic1; cst[sb+3] = 2*v2 - ic2;
          chB = chB + cm1 * v1;
        );
```

(Note: `qb` and `cg` are already set in the Mode-A block from `bp[b*3+1]`/`bp[b*3+2]`.
`eg` = Mode-A soft env, `egh` = Mode-A hard env. Detector state `dst`, cut state `cst`
unchanged.)

- [ ] **Step 3: Deploy**

```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```

- [ ] **Step 4: Live verification in REAPER**

1. **Soft only** (Mode A, Soft On, Hard Off): identical to Phase-2b Mode A (smooth bell-cut to Soft Ceiling with Attack/Release).
2. **Hard only** (Soft Off, Hard On): instant-attack bell-cut to Hard Ceiling (snappier).
3. **Cascade (both on):** Soft Ceiling lower, Hard Ceiling higher, Attack slow (e.g. 10 ms). Sustained band rides to Soft Ceiling; fast transients the slow Soft attack lets through get caught by the instant Hard at the Hard Ceiling. No clamp (phase-clean bell modulation) — softer than Mode B, still catches transients.
4. **Linking:** Both+Linked/DualLR/DualMS behave with the cascade (no width pump on Linked).
5. **Placement single-target:** Mode A cascade on Placement=Side limits only side, etc.
6. **Regression:** Mode B (3a/b/c) still works; Bypass null; A/B mixed bands coherent.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): Mode-A Soft+Hard cascade (bell-cut, slow soft + instant hard)"
```

---

## Self-Review

**Spec coverage (§4.2 / §4.6b cascade, Mode A):**
- Independent Soft + Hard bell-cut, two ceilings → Tasks 1, 2. ✓
- gSoft (atk/rel) × gHard (instant), no clamp → Tasks 1, 2. ✓
- Soft-only ≡ Phase-2b modea_process → Task 1 equivalence test. ✓
- Linking / placement unchanged → Task 2. ✓
- No gmem; `egh` instance-local → Task 2. ✓

Deferred: shelf dynamics; bell characters; GUI.

**Placeholder scan:** clean — all code final.

**Type consistency:** cascade gain `gS·gH` identical between `_modea_cascade_ch` and JSFX;
soft env reuses `eg`, hard env `egh` (offset `hc + N_BANDS`, past `hc`'s N_BANDS region).
Shared controls (`dp[b*4]` soft ceiling, `hc[b]` hard ceiling, Soft `ds+8`, Hard `90+10b+1`)
match Phase 3c. `gain_env_step(_, _, 0.0, rel)` = instant attack.

---

## Next
- Shelf dynamics (dynamic low/high shelf — dynamic de-esser).
- Phase 4: bell characters (GML/Butterworth/house).
- Phase 6: GUI (node + analyzer + @serialize + 8 bands).
