# RCBitNova Phase 2b — Soft Dynamics (Mode A) + Stereo Linking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-band Soft dynamic EQ (Mode A) on top of the Phase-2a placement engine: a normalised bandpass detector drives a smoothly-enveloped, modulated bell-cut toward a bit-denominated ceiling, with the FabFilter-like Dyn Stereo Mode (Linked / Dual L/R / Dual M/S) for `Both` placement.

**Architecture:** Per band, after the static SVF (running L/R, Phase 2a), if dynamics is on, a detector (bandpass SVF at the band's freq/Q, normalised to unity at fc, `level = |k·v1|`) measures the post-static level of each working channel; a gain envelope (instant-ish attack / smooth release) follows `ceiling/level`; a per-sample modulated TPT-SVF bell applies that gain as a dynamic cut. For `Both` placement the working domain is L/R (Linked / Dual L/R) or M/S (Dual M/S); Linked shares one envelope from `max(chA,chB)` so width does not pump, Dual modes run independent envelopes per channel. All math is mirrored in the pytest-verified Python reference (prototype already confirmed convergence to ceiling and stability).

**Tech Stack:** Python 3.11 stdlib (`math`). JSFX (EEL2). pytest. Git.

## Global Constraints

- License **GPL**; preserve upstream headers.
- Dynamics = **limiter, not compressor** (no ratio; depth = excess over ceiling). Mode A = **bell-cut modulation, smooth float, NO absolute-ceiling guarantee** (Soft may slightly exceed ~5–9%, verified in prototype).
- `ceiling_lin = 2^(-(CeilMacro + CeilMicro/100))`.
- Detector: bandpass SVF at band freq/Q, **post-static**, **normalised to unity at fc** (mix `m1=k`, `k=1/Q`; `level = |k·v1|`), **peak**.
- Envelope (one-pole): `atk=exp(-1/(atk_ms*0.001*sr))`, `rel=exp(-1/(rel_ms*0.001*sr))`; step `coef = atk if gr<env else rel; env = gr + (env-gr)*coef`; `gr = ceiling/level if level>ceiling else 1`.
- Modulated cut bell (TPT-SVF, gain `env`): `A=sqrt(env)`, `ck=1/(Q*A)`, `cg=tan(pi*fc/sr)` (precomputed, gain-independent), `ca1=1/(1+cg*(cg+ck))`, `ca2=cg*ca1`, `ca3=cg*ca2`, `cm1=ck*(A*A-1)`; per sample `cv3=x-ic2; cv1=ca1*ic1+ca2*cv3; cv2=ic2+ca2*ic1+ca3*cv3; ic1=2cv1-ic1; ic2=2cv2-ic2; out=x+cm1*cv1`.
- **Dyn Stereo Mode** (only when Placement=`Both`): `0 Linked | 1 Dual L/R | 2 Dual M/S`.
  - Linked → working domain L/R; detector on both; `level=max`; one shared envelope; cut both with it.
  - Dual L/R → working domain L/R; independent envelope per channel.
  - Dual M/S → working domain **M/S**; independent envelope per channel (M and S).
- Single-target placements (Mid/Side/Left/Right) → one channel, one envelope; Dyn Stereo Mode ignored.
- HP/LP never dynamic; this phase wires dynamics for **Bell** only (shelf dynamics are a later phase). When a non-Bell band has dynamics on, treat as Bell-shaped detector/cut at its freq/Q (acceptable v1) OR ignore dynamics — **ignore dynamics for non-Bell types** this phase.
- **No `gmem`**; new state instance-local. Anti-denormal `±1e-30` toggle on the L/R bus (resolves the deferred Phase-1 hardening item).
- Builds on Phase 2a (running-L/R placement engine). Phase-1/2a static sliders unchanged.
- Python pure stdlib. Tests from repo root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`.
- JSFX path `JSFX/RCBitNova V0.1`; live testing copies it to `~/Library/Application Support/REAPER/Effects/`.

---

### Task 1: Ceiling + bandpass detector + envelope — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `ceiling_lin(ceil_macro, ceil_micro)`; `svf_make` gains a `"bandpass"` branch (mix `m0=0,m1=k,m2=0`, `k=1/q`); `env_coeffs(atk_ms, rel_ms, sr) -> (atk, rel)`; `gain_env_step(env_gain, gr, atk, rel) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def test_ceiling_lin_bits_below_zero():
    assert dsp.ceiling_lin(0, 0) == 1.0
    assert dsp.ceiling_lin(1, 0) == 0.5
    assert dsp.ceiling_lin(2, 0) == 0.25
    assert dsp.ceiling_lin(1, 50) == pytest.approx(2 ** -1.5)

def test_bandpass_detector_unity_at_center_low_off_band():
    c = dsp.svf_make("bandpass", 1000.0, 2.0, 1.0, SR)
    assert dsp.svf_magnitude(c, 1000.0, SR) == pytest.approx(1.0, abs=0.02)
    assert dsp.svf_magnitude(c, 250.0, SR) < 0.3
    assert dsp.svf_magnitude(c, 4000.0, SR) < 0.3

def test_env_coeffs_ordering():
    atk, rel = dsp.env_coeffs(1.0, 80.0, SR)
    assert 0.0 < atk < rel < 1.0

def test_gain_env_converges_and_instant():
    atk, rel = dsp.env_coeffs(1.0, 80.0, SR)
    env = 1.0
    for _ in range(20000):
        env = dsp.gain_env_step(env, 0.5, atk, rel)
    assert env == pytest.approx(0.5, abs=1e-3)
    assert dsp.gain_env_step(1.0, 0.3, 0.0, 0.9) == pytest.approx(0.3)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "ceiling or bandpass or env or gain_env" -q`
Expected: FAIL — missing attributes / unknown ftype.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def ceiling_lin(ceil_macro, ceil_micro):
    return 2.0 ** (-(ceil_macro + ceil_micro / 100.0))

def env_coeffs(atk_ms, rel_ms, sr):
    return math.exp(-1.0 / (atk_ms * 0.001 * sr)), math.exp(-1.0 / (rel_ms * 0.001 * sr))

def gain_env_step(env_gain, gr, atk, rel):
    coef = atk if gr < env_gain else rel
    return gr + (env_gain - gr) * coef
```

In `svf_make`, add a branch:

```python
    elif ftype == "bandpass":
        g = math.tan(math.pi * fc / sr); k = 1.0 / q
        m0, m1, m2 = 0.0, k, 0.0
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "ceiling or bandpass or env or gain_env" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): ceiling_lin + bandpass detector + gain envelope"
```

---

### Task 2: Single-channel Mode-A Soft reference — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `modea_process(signal, fc, q, sr, ceiling, atk_ms, rel_ms) -> list` — detector → envelope → modulated bell-cut, one channel. The oracle for the JSFX per-channel dynamic path.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def _band_peak(samples, tail=2000):
    return max(abs(v) for v in samples[-tail:])

def test_modea_pulls_band_to_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modea_process(sig, 1000.0, 2.0, SR, 0.2, 1.0, 80.0)
    assert 0.18 <= _band_peak(out) <= 0.24

def test_modea_transparent_below_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modea_process(sig, 1000.0, 2.0, SR, 2.0, 1.0, 80.0)
    assert _band_peak(out) == pytest.approx(0.8, abs=0.02)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k modea -q`
Expected: FAIL — `AttributeError: ... 'modea_process'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def modea_process(signal, fc, q, sr, ceiling, atk_ms, rel_ms):
    """Single-channel Mode-A Soft: detector -> envelope -> modulated bell-cut."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    cg = math.tan(math.pi * fc / sr)
    dic1 = dic2 = cic1 = cic2 = 0.0
    env = 1.0
    out = []
    for x in signal:
        v3 = x - dic2
        v1 = da1 * dic1 + da2 * v3
        v2 = dic2 + da2 * dic1 + da3 * v3
        dic1 = 2.0 * v1 - dic1
        dic2 = 2.0 * v2 - dic2
        level = abs(dk * v1)
        gr = ceiling / level if level > ceiling else 1.0
        env = gain_env_step(env, gr, atk, rel)
        A = math.sqrt(env)
        ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck))
        ca2 = cg * ca1
        ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = x - cic2
        cv1 = ca1 * cic1 + ca2 * cv3
        cv2 = cic2 + ca2 * cic1 + ca3 * cv3
        cic1 = 2.0 * cv1 - cic1
        cic2 = 2.0 * cv2 - cic2
        out.append(x + cm1 * cv1)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k modea -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): single-channel Mode-A Soft reference + convergence tests"
```

---

### Task 3: Stereo Mode-A linking reference — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: Task 2, `modea_process`.
- Produces: `modea_stereo(Lin, Rin, fc, q, sr, ceiling, atk_ms, rel_ms, dyn_mode) -> (Lout, Rout)`
  for `dyn_mode in {"linked","dual_lr","dual_ms"}` (Both placement). Oracle for the JSFX linking branches.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def test_modea_dual_lr_equals_independent_channels():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.modea_stereo(L, R, 700.0, 2.0, SR, 0.2, 1.0, 80.0, "dual_lr")
    assert Lo == dsp.modea_process(L, 700.0, 2.0, SR, 0.2, 1.0, 80.0)
    assert Ro == dsp.modea_process(R, 700.0, 2.0, SR, 0.2, 1.0, 80.0)

def test_modea_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modea_process(M, 700.0, 2.0, SR, 0.2, 1.0, 80.0)
    So = dsp.modea_process(S, 700.0, 2.0, SR, 0.2, 1.0, 80.0)
    Lo, Ro = dsp.modea_stereo(L, R, 700.0, 2.0, SR, 0.2, 1.0, 80.0, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)

def test_modea_linked_applies_equal_gain_no_width_shift():
    # Identical L and R (pure mid) stay identical after linked dynamics.
    w = 2 * math.pi * 700.0 / SR
    mono = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    Lo, Ro = dsp.modea_stereo(mono, list(mono), 700.0, 2.0, SR, 0.2, 1.0, 80.0, "linked")
    assert Lo == pytest.approx(Ro, abs=1e-12)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "modea_dual or modea_linked" -q`
Expected: FAIL — `AttributeError: ... 'modea_stereo'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def _modea_two_channels(chA, chB, fc, q, sr, ceiling, atk_ms, rel_ms, linked):
    """Process two channels with independent cut SVFs. If linked, one shared
    envelope from max(levelA, levelB); else independent envelopes."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    cg = math.tan(math.pi * fc / sr)
    dA1 = dA2 = dB1 = dB2 = 0.0          # detector states A,B
    cA1 = cA2 = cB1 = cB2 = 0.0          # cut states A,B
    envA = envB = 1.0
    outA = []
    outB = []
    for xa, xb in zip(chA, chB):
        # detectors
        v3 = xa - dA2; v1a = da1 * dA1 + da2 * v3; v2 = dA2 + da2 * dA1 + da3 * v3
        dA1 = 2.0 * v1a - dA1; dA2 = 2.0 * v2 - dA2
        v3 = xb - dB2; v1b = da1 * dB1 + da2 * v3; v2 = dB2 + da2 * dB1 + da3 * v3
        dB1 = 2.0 * v1b - dB1; dB2 = 2.0 * v2 - dB2
        levelA = abs(dk * v1a); levelB = abs(dk * v1b)
        if linked:
            lev = levelA if levelA > levelB else levelB
            gr = ceiling / lev if lev > ceiling else 1.0
            envA = gain_env_step(envA, gr, atk, rel); envB = envA
        else:
            grA = ceiling / levelA if levelA > ceiling else 1.0
            grB = ceiling / levelB if levelB > ceiling else 1.0
            envA = gain_env_step(envA, grA, atk, rel)
            envB = gain_env_step(envB, grB, atk, rel)
        # cut A
        A = math.sqrt(envA); ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = xa - cA2; cv1 = ca1 * cA1 + ca2 * cv3; cv2 = cA2 + ca2 * cA1 + ca3 * cv3
        cA1 = 2.0 * cv1 - cA1; cA2 = 2.0 * cv2 - cA2
        outA.append(xa + cm1 * cv1)
        # cut B
        A = math.sqrt(envB); ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = xb - cB2; cv1 = ca1 * cB1 + ca2 * cv3; cv2 = cB2 + ca2 * cB1 + ca3 * cv3
        cB1 = 2.0 * cv1 - cB1; cB2 = 2.0 * cv2 - cB2
        outB.append(xb + cm1 * cv1)
    return outA, outB


def modea_stereo(Lin, Rin, fc, q, sr, ceiling, atk_ms, rel_ms, dyn_mode):
    """Both-placement Mode-A with stereo linking."""
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modea_two_channels(M, S, fc, q, sr, ceiling, atk_ms, rel_ms, False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _modea_two_channels(Lin, Rin, fc, q, sr, ceiling, atk_ms, rel_ms, linked)
```

- [ ] **Step 4: Run to verify pass; then full suite**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): stereo Mode-A linking reference (linked/dual-lr/dual-ms) + tests"
```

---

### Task 4: JSFX — dynamics sliders + memory + @slider setup (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Phase-2a engine.
- Produces: dyn sliders (51–86), instance-local arrays `det`(4/band@96), `dst`(4/band@128), `cst`(4/band@160), `dp`(ceil_lin,atk,rel,dynOn @192, 4/band), `dm`(dynMode @208,1/band), `bp`(fc,q,cg @216,3/band), `eg`(envA,envB @256,2/band), `anti`. Consumed by Task 5.

- [ ] **Step 1: Add dynamics sliders (per band b: base 50+10b)**

After the Phase-2a band sliders, add for B1–B4 (shown for B1; repeat at 61–66, 71–76, 81–86):

```
slider51:0<0,1,1{Off,On}>B1 Dyn
slider52:0<0,2,1{Linked,Dual L/R,Dual M/S}>B1 Dyn Stereo (Both only)
slider53:1<0,16,1>B1 Ceiling Macro (bits below 0)
slider54:0<-100,100,0.1>B1 Ceiling Micro (% bit)
slider55:1<0.05,50,0.01>B1 Attack (ms)
slider56:80<1,500,1>B1 Release (ms)
```

- [ ] **Step 2: Extend `@init` memory + `setup_band_dyn`**

In `@init`, after the existing `memset(st, 0, N_BANDS * 4);`:

```eel2
det = 96; dst = 128; cst = 160; dp = 192; dm = 208; bp = 216; eg = 256;
memset(dst, 0, N_BANDS * 4);
memset(cst, 0, N_BANDS * 4);
i = 0; loop(N_BANDS * 2, eg[i] = 1; i += 1;);
anti = pow(2, -100);   // ~8e-31 anti-denormal; EEL2 rejects the 1e-30 literal
```

After the existing `setup_band` function, add:

```eel2
function setup_band_dyn(b)
  local(s, ds, fc, q, g, k, a1, a2, a3)
(
  s = 10 * (b + 1); ds = 50 + 10 * b;
  fc = slider(s + 3); q = slider(s + 4);
  g = tan($pi * fc / srate); k = 1 / q;            // detector bandpass, unity at fc
  a1 = 1 / (1 + g * (g + k)); a2 = g * a1; a3 = g * a2;
  det[b*4] = a1; det[b*4+1] = a2; det[b*4+2] = a3; det[b*4+3] = k;
  dp[b*4]   = pow(2, -(slider(ds+3) + slider(ds+4) * 0.01));   // ceil_lin
  dp[b*4+1] = exp(-1 / (slider(ds+5) * 0.001 * srate));        // atk
  dp[b*4+2] = exp(-1 / (slider(ds+6) * 0.001 * srate));        // rel
  dp[b*4+3] = slider(ds+1);                                    // dynOn
  dm[b]     = slider(ds+2);                                    // 0 Linked,1 DualLR,2 DualMS
  bp[b*3] = fc; bp[b*3+1] = q; bp[b*3+2] = tan($pi * fc / srate);
);
```

In `@slider`, extend the loop:

```eel2
b = 0;
loop(N_BANDS, setup_band(b); setup_band_dyn(b); b += 1;);
```

- [ ] **Step 3: Deploy and verify it still loads (no behaviour change)**

Run:
```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```
In REAPER: loads with no error; new Dyn sliders appear; audio identical to Phase 2a (dynamic path not wired yet). Phase 2a placement checks still pass.

- [ ] **Step 4: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX dynamics sliders + detector/env @slider setup"
```

---

### Task 5: JSFX — @sample Mode-A dynamic path with linking (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Task 4 arrays; the Phase-2a band loop.
- Produces: working Soft Mode-A dynamics with placement-coupled domain and Dyn Stereo Mode. Mirrors `modea_stereo` / `modea_process`.

- [ ] **Step 1: Anti-denormal on the bus**

In `@sample`, right after `slider1 != 1 ? (`, add:

```eel2
  anti = -anti; spl0 += anti; spl1 += anti;
```

- [ ] **Step 2: Couple Both-domain to Dyn Stereo Mode + add the dynamic path**

This task EXTENDS the Phase-2a band body. The reference `modea_two_channels` /
`modea_process` define the per-channel math exactly; transcribe it. Two changes:

(a) In the `Both` branch of placement, choose the working domain by dyn mode — L/R
unless dynamics is on AND Dyn Stereo = Dual M/S, in which case use M/S. Replace the
Phase-2a `pl == 0 ? ( chA = spl0; chB = spl1; do_b = 1; )` line with:

```eel2
      pl == 0 ? (                             // Both
        (dp[b*4+3] == 1 && dm[b] == 2) ? (    // dyn on + Dual M/S -> work in M/S
          mid = (spl0 + spl1) * 0.5; sid = (spl0 - spl1) * 0.5;
          chA = mid; chB = sid; both_ms = 1;
        ) : (
          chA = spl0; chB = spl1; both_ms = 0;
        );
        do_b = 1;
      ) : (
```

…and adjust the Both write-back (end of band body) to recombine when `both_ms`:

```eel2
      pl == 0 ? ( both_ms ? ( spl0 = chA + chB; spl1 = chA - chB; ) : ( spl0 = chA; spl1 = chB; ) ) :
```

(b) After the static filtering of chA (and chB if `do_b`), BEFORE the write-back,
insert the dynamic path (Bell types only — `slider(10*(b+1)+2) == 0`):

```eel2
      (dp[b*4+3] == 1 && slider(10*(b+1)+2) == 0) ? (   // dyn on + Bell type
        fcb = bp[b*3]; qb = bp[b*3+1]; cg = bp[b*3+2];
        da1 = det[b*4]; da2 = det[b*4+1]; da3 = det[b*4+2]; dk = det[b*4+3];
        ceil = dp[b*4]; atk = dp[b*4+1]; rel = dp[b*4+2];
        linked = (pl == 0) && (dm[b] == 0);            // linked only for Both+Linked

        // detector on chA (slot A: dst[sb],dst[sb+1])
        ic1 = dst[sb]; ic2 = dst[sb+1];
        v3 = chA - ic2; v1 = da1*ic1 + da2*v3; v2 = ic2 + da2*ic1 + da3*v3;
        dst[sb] = 2*v1 - ic1; dst[sb+1] = 2*v2 - ic2;
        levA = abs(dk * v1);
        levB = 0;
        do_b ? (                                       // detector on chB
          ic1 = dst[sb+2]; ic2 = dst[sb+3];
          v3 = chB - ic2; v1 = da1*ic1 + da2*v3; v2 = ic2 + da2*ic1 + da3*v3;
          dst[sb+2] = 2*v1 - ic1; dst[sb+3] = 2*v2 - ic2;
          levB = abs(dk * v1);
        );

        linked ? (                                     // one shared envelope
          lev = max(levA, levB);
          gr = lev > ceil ? ceil / lev : 1;
          ea = eg[b*2]; coef = gr < ea ? atk : rel; ea = gr + (ea - gr) * coef;
          eg[b*2] = ea; eg[b*2+1] = ea;
        ) : (                                          // independent envelopes
          gr = levA > ceil ? ceil / levA : 1;
          ea = eg[b*2]; coef = gr < ea ? atk : rel; ea = gr + (ea - gr) * coef; eg[b*2] = ea;
          do_b ? (
            gr = levB > ceil ? ceil / levB : 1;
            eb = eg[b*2+1]; coef = gr < eb ? atk : rel; eb = gr + (eb - gr) * coef; eg[b*2+1] = eb;
          );
        );

        // cut chA with eg[b*2]
        A = sqrt(eg[b*2]); ck = 1 / (qb * A);
        ca1 = 1 / (1 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2; cm1 = ck * (A*A - 1);
        ic1 = cst[sb]; ic2 = cst[sb+1];
        v3 = chA - ic2; v1 = ca1*ic1 + ca2*v3; v2 = ic2 + ca2*ic1 + ca3*v3;
        cst[sb] = 2*v1 - ic1; cst[sb+1] = 2*v2 - ic2;
        chA = chA + cm1 * v1;

        do_b ? (                                       // cut chB with eg[b*2+1]
          A = sqrt(eg[b*2+1]); ck = 1 / (qb * A);
          ca1 = 1 / (1 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2; cm1 = ck * (A*A - 1);
          ic1 = cst[sb+2]; ic2 = cst[sb+3];
          v3 = chB - ic2; v1 = ca1*ic1 + ca2*v3; v2 = ic2 + ca2*ic1 + ca3*v3;
          cst[sb+2] = 2*v1 - ic1; cst[sb+3] = 2*v2 - ic2;
          chB = chB + cm1 * v1;
        );
      );
```

(Note: for single-target placements `do_b==0`, so only chA path runs — one detector,
one envelope `eg[b*2]`, one cut. `linked` is false there, using the per-channel branch
on chA only. This matches `modea_process`.)

- [ ] **Step 3: Deploy**

```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```

- [ ] **Step 4: Live verification in REAPER**

1. **Dynamic cut (Bell):** loud 1 kHz / pink noise. B1 Bell 1 kHz Q2 Macro 0, Placement Both, Dyn On, Ceiling Macro 2, Atk 1, Rel 80 → 1 kHz pulled toward ceiling when it exceeds, recovers on quiet. Lower Ceiling Macro → more cut.
2. **Static + dynamic independence:** B1 Macro +2 (boost) AND dyn on → boosted band still has peaks caught.
3. **Linked (Both):** wide stereo source, Dyn Stereo = Linked → cut engages without stereo-width wobble.
4. **Dual L/R:** transient louder in one channel → only that channel ducks (other steady).
5. **Dual M/S:** signal with a loud SIDE band (e.g. wide reverb spike) → Dual M/S limits it in Side only; Mid (center) untouched (phase de-toxified). Switch to Linked → Mid now also ducks.
6. **Single targets:** Placement Side + Dyn → limits side only; Placement Left + Dyn → left only.
7. **Dyn off / non-Bell:** Dyn Off = Phase 2a. A High-Shelf band with Dyn On has NO dynamics (Bell-only this phase) — static only.
8. **Silence clean:** dyn on + silent input → no denormal CPU spike, no DC/drift.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX Mode-A Soft dynamic path + Linked/Dual-LR/Dual-MS"
```

---

## Self-Review

**Spec coverage (§4.1/§4.2 Soft, §3.1 linking, §8.2b):**
- Detector normalised bandpass, post-static, peak → Tasks 1, 4, 5. ✓
- Ceiling bits→linear → Tasks 1, 4. ✓
- Gain envelope (atk/rel) → Tasks 1, 4, 5. ✓
- Mode-A Soft bell-cut, may slightly exceed → Tasks 2, 5 (+ prototype). ✓
- Dyn Stereo Mode Linked / Dual L/R / Dual M/S (Both) → Tasks 3, 5. ✓
- Single-target placements use one envelope → Tasks 2, 5. ✓
- Static/dynamic independence → Task 5 step 4.2. ✓
- Bell-only dynamics this phase; HP/LP never dynamic → Task 5 gate `slider(...+2)==0`. ✓
- No gmem; instance-local; anti-denormal → Tasks 4, 5. ✓

Deferred to later (out of scope): Hard cascade, shared lookahead + PDC, shelf dynamics, Mode B.

**Placeholder scan:** none — all code complete.

**Type consistency:** detector mix (`m1=k`,`k=1/q`,`level=|k*v1|`), envelope step (`coef=gr<env?atk:rel`), cut bell (`cm1=ck*(A²−1)`,`ck=1/(q*A)`,`A=sqrt(env)`) identical across `modea_process`, `_modea_two_channels`, and JSFX `@sample`. `dm`/`dp`/`eg` offsets consistent between Tasks 4 and 5. Dyn Stereo ints (0 Linked,1 DualLR,2 DualMS) match `modea_stereo` strings.

---

## Next phase (separate plan)
- Phase 2c: Hard cascade ("last policeman"), shared lookahead delay + PDC, shelf dynamics.
- Phase 3: Mode B band-split RCBit limiter (bit-exact per-band clamp).
