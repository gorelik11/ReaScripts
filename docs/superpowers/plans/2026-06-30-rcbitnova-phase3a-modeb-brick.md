# RCBitNova Phase 3a — Mode B Brick (Band-Split, Bit-Exact) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-band Mode B "Brick" — a true bit-accurate band-split limiter that guarantees a band's own contribution stays at/under a power-of-two ceiling (the "alive" RCBit limiting), selectable per band as an alternative to Mode A.

**Architecture:** Per Mode-B band, the band is extracted (normalised bandpass at freq/Q) from the post-static/Mode-A signal; a lookahead worst-peak envelope (instant attack, smooth release) targets `ceiling/peak`; the delayed band is gain-applied and **bit-exact clamped** to ±ceiling; the result recombines as `out = dry_delayed − band_delayed + limited_band`. A **single global lookahead** delays the whole bus (PDC = L) so all bands stay time-aligned; Mode-B detectors run on the un-delayed signal to see ahead. Prototype-verified: band contribution held at exactly the ceiling (ratio 1.000).

**Tech Stack:** Python 3.11 stdlib (`math`). JSFX (EEL2). pytest. Git.

## Global Constraints

- License **GPL**; preserve upstream headers.
- Per band, **Dyn Mode**: `0 A (Dynamic EQ, Phase 2b)` | `1 B (Band-Split)`. This phase implements **B = Brick** (bit-exact). Mode-B Soft is Phase 3b.
- Mode B applies to **Bell** type only this phase; HP/LP never dynamic; non-Bell + Mode B → no dynamics.
- `ceiling_lin = 2^(-(CeilMacro + CeilMicro/100))` (power of two).
- Band extraction = normalised bandpass (`svf_make("bandpass")`, `level/band = k·v1`, unity at fc).
- **Bit-exact clamp:** after gain, `if |x| > ceiling: x = sign(x)*ceiling` (clamp to the exact power-of-two ceiling).
- Lookahead worst-peak envelope: `tgt = ceiling/worst if worst>ceiling else 1`; `env = tgt if tgt<env else tgt+(env-tgt)*rel` (instant attack, one-pole release `rel=exp(-1/(rel_ms*0.001*sr))`).
- Recombine: `out = dry_delayed − band_delayed + clamp(band_delayed*env, ceiling)`.
- **Single global lookahead** `L` (one plugin control, ms→samples). `pdc_delay = L` iff ≥1 Mode-B band enabled, else 0. Detectors run on un-delayed signal; corrections applied to the delayed bus.
- Stereo linking reuses Phase-2b framework: for `Both` placement, Dyn Stereo Mode `Linked` (shared worst-peak/env across the two channels) / `Dual L/R` / `Dual M/S` (independent). Single-target placements: one channel.
- **No `gmem`**; all ring/state instance-local. `MAX_LOOK = 512` samples/channel ring.
- Builds on Phase 2 (placement engine + Mode A). Static + Mode-A run on the delayed bus when Mode-B is active.
- Python pure stdlib. Tests: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`.
- JSFX path `JSFX/RCBitNova V0.1`; deploy copy to `~/Library/Application Support/REAPER/Effects/`.

---

### Task 1: Mode-B Brick single-channel reference — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `svf_make`, `svf_process` (bandpass), `ceiling_lin`.
- Produces: `modeb_brick(signal, fc, q, sr, ceiling, look_ms, rel_ms) -> list`. The oracle for the JSFX Mode-B per-channel path.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def _band_contrib_peak(out, fc, q, sr, tail=2000):
    bp = dsp.svf_process(dsp.svf_make("bandpass", fc, q, 1.0, sr), out)
    return max(abs(v) for v in bp[-tail:])

def test_modeb_brick_holds_band_at_exact_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    for ceiling in (0.25, 0.2, 0.1):
        out = dsp.modeb_brick(sig, 1000.0, 2.0, SR, ceiling, 2.0, 80.0)
        pk = _band_contrib_peak(out, 1000.0, 2.0, SR)
        assert pk <= ceiling * 1.001                 # guaranteed under ceiling
        assert pk == pytest.approx(ceiling, rel=0.01) # and pinned to it

def test_modeb_brick_transparent_below_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.1 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_brick(sig, 1000.0, 2.0, SR, 0.5, 2.0, 80.0)
    assert _band_contrib_peak(out, 1000.0, 2.0, SR) == pytest.approx(0.1, abs=0.01)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k modeb_brick -q`
Expected: FAIL — `AttributeError: ... 'modeb_brick'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def modeb_brick(signal, fc, q, sr, ceiling, look_ms, rel_ms):
    """Single-channel Mode-B Brick: band-split + lookahead worst-peak +
    bit-exact clamp + recombine. Guarantees the band contribution <= ceiling."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    size = L + 1
    band_ring = [0.0] * size
    peak_ring = [0.0] * size
    dry_ring = [0.0] * size
    wpos = 0
    ic1 = ic2 = 0.0
    env = 1.0
    out = []
    for x in signal:
        v3 = x - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        b = k * v1
        band_ring[wpos] = b
        peak_ring[wpos] = abs(b)
        dry_ring[wpos] = x
        worst = 0.0
        for i in range(size):
            p = peak_ring[(wpos - i) % size]
            if p > worst:
                worst = p
        tgt = ceiling / worst if worst > ceiling else 1.0
        if tgt < env:
            env = tgt
        else:
            env = tgt + (env - tgt) * rel
            if env > 1.0:
                env = 1.0
        rpos = (wpos - L) % size
        bd = band_ring[rpos]
        xd = dry_ring[rpos]
        lim = bd * env
        if abs(lim) > ceiling:
            lim = ceiling if lim > 0 else -ceiling
        out.append(xd - bd + lim)
        wpos = (wpos + 1) % size
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k modeb_brick -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Mode-B Brick single-channel reference (bit-exact) + tests"
```

---

### Task 2: Mode-B Brick stereo linking reference — Python

**Files:**
- Modify: `tools/rcbitnova_dsp.py`
- Test: `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `modeb_brick_stereo(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, dyn_mode) -> (Lout, Rout)`
  with `dyn_mode in {"linked","dual_lr","dual_ms"}`. Linked shares one worst-peak/env across channels.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_rcbitnova_dsp.py
def test_modeb_brick_dual_lr_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.modeb_brick_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_lr")
    assert Lo == dsp.modeb_brick(L, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    assert Ro == dsp.modeb_brick(R, 700.0, 2.0, SR, 0.2, 2.0, 80.0)

def test_modeb_brick_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modeb_brick(M, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    So = dsp.modeb_brick(S, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    Lo, Ro = dsp.modeb_brick_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)

def test_modeb_brick_linked_equal_gain():
    w = 2 * math.pi * 700.0 / SR
    mono = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    Lo, Ro = dsp.modeb_brick_stereo(mono, list(mono), 700.0, 2.0, SR, 0.2, 2.0, 80.0, "linked")
    assert Lo == pytest.approx(Ro, abs=1e-12)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "modeb_brick_dual or modeb_brick_linked" -q`
Expected: FAIL — `AttributeError: ... 'modeb_brick_stereo'`.

- [ ] **Step 3: Implement**

```python
# append to tools/rcbitnova_dsp.py
def _modeb_brick_two(chA, chB, fc, q, sr, ceiling, look_ms, rel_ms, linked):
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    size = L + 1
    bA = [0.0] * size; pA = [0.0] * size; dA = [0.0] * size
    bB = [0.0] * size; pB = [0.0] * size; dB = [0.0] * size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envA = envB = 1.0
    outA, outB = [], []

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    for xa, xb in zip(chA, chB):
        v3 = xa - iA2; v1a = a1 * iA1 + a2 * v3; v2 = iA2 + a2 * iA1 + a3 * v3
        iA1 = 2.0 * v1a - iA1; iA2 = 2.0 * v2 - iA2
        v3 = xb - iB2; v1b = a1 * iB1 + a2 * v3; v2 = iB2 + a2 * iB1 + a3 * v3
        iB1 = 2.0 * v1b - iB1; iB2 = 2.0 * v2 - iB2
        ba = k * v1a; bb = k * v1b
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
        rpos = (wpos - L) % size
        bda = bA[rpos]; lim = bda * envA
        if abs(lim) > ceiling: lim = ceiling if lim > 0 else -ceiling
        outA.append(dA[rpos] - bda + lim)
        bdb = bB[rpos]; lim = bdb * envB
        if abs(lim) > ceiling: lim = ceiling if lim > 0 else -ceiling
        outB.append(dB[rpos] - bdb + lim)
        wpos = (wpos + 1) % size
    return outA, outB


def modeb_brick_stereo(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, dyn_mode):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modeb_brick_two(M, S, fc, q, sr, ceiling, look_ms, rel_ms, False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _modeb_brick_two(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, linked)
```

- [ ] **Step 4: Run; then full suite**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Mode-B Brick stereo linking reference + tests"
```

---

### Task 3: JSFX — Dyn Mode slider, global lookahead, memory, PDC (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Phase-2b dyn arrays/sliders.
- Produces: global `slider4` Lookahead; per-band Dyn Mode slider (dyn base `ds+7`); Mode-B ring memory `MB` (band/peak/dry rings, `MAX_LOOK` each, per band×2 channels), per-band `mbmode`/`mbenv`/`mbwpos`; `Lk` samples; `pdc_delay`. Consumed by Task 4.

- [ ] **Step 1: Add global lookahead + per-band Dyn Mode sliders**

Add a global slider (after `slider3`):

```
slider4:2<0.1,10,0.1>-Lookahead (ms, Mode B)
```

Add per band a Dyn Mode slider at dyn base `ds+7` (B1=57, B2=67, B3=77, B4=87):

```
slider57:0<0,1,1{A Dynamic EQ,B Band-Split}>B1 Dyn Mode
slider67:0<0,1,1{A Dynamic EQ,B Band-Split}>B2 Dyn Mode
slider77:0<0,1,1{A Dynamic EQ,B Band-Split}>B3 Dyn Mode
slider87:0<0,1,1{A Dynamic EQ,B Band-Split}>B4 Dyn Mode
```

- [ ] **Step 2: `@init` — Mode-B memory**

In `@init`, after the Phase-2b memory block, add:

```eel2
MAX_LOOK = 2048;   // covers the 10 ms slider max up to 192 kHz (1920 samples)
// Mode-B rings: per (band, channel) -> band + peak rings of MAX_LOOK each.
// channel-slot index cs = b*2 + c  (c: 0=A,1=B). 8 slots for 4 bands.
// (No per-band dry ring: the shared stereo bus_dry below reconstructs the dry path.)
mb_band = 1024;
mb_peak = mb_band + N_BANDS * 2 * MAX_LOOK;
mb_end  = mb_peak + N_BANDS * 2 * MAX_LOOK;
memset(mb_band, 0, mb_end - mb_band);
mbenv  = mb_end;        // env per (band,channel): 2/band
mbmode = mbenv + N_BANDS * 2;   // Dyn Mode per band
mbwpos = mbmode + N_BANDS;      // write pos per band
bus_dry = mbwpos + N_BANDS;     // shared stereo dry delay (L at [0..], R at [MAX_LOOK..])
bus_wp = 0;
memset(bus_dry, 0, MAX_LOOK * 2);
i = 0; loop(N_BANDS * 2, mbenv[i] = 1; i += 1;);
memset(mbwpos, 0, N_BANDS);
```

- [ ] **Step 3: `@slider` — lookahead samples, Dyn Mode, PDC, release**

In `@slider`, after the band setup loop, add:

```eel2
Lk = floor(slider4 * 0.001 * srate + 0.5);
Lk = min(max(Lk, 1), MAX_LOOK - 1);
any_b = 0;
b = 0;
loop(N_BANDS,
  mbmode[b] = slider(50 + 10 * b + 7);                 // 0 A, 1 B
  (slider(50 + 10 * b + 1) == 1 && mbmode[b] == 1 && slider(10*(b+1)+2) == 0) ? any_b = 1;
  b += 1;
);
pdc_delay = (slider1 != 1 && any_b) ? Lk : 0;   // 0 when bypassed (passthrough is zero-latency)
pdc_bot_ch = 0; pdc_top_ch = 2;
```

**P1 (review):** the bypass gate on `pdc_delay` is required — `@sample` passes through
with zero delay when `slider1==1`, so reporting `Lk` while bypassed would shift the
bypassed signal early against PDC-compensated tracks.

(Release for Mode-B reuses the per-band Release slider `dp[b*4+2]` already computed in `setup_band_dyn`.)

- [ ] **Step 4: Deploy and verify it still loads (no behaviour change)**

```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```
In REAPER: loads with no error; new Lookahead + per-band Dyn Mode sliders appear (scroll). With all Dyn Mode = A, behaviour is identical to Phase 2b. PDC shows 0 (no Mode-B band active).

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX Dyn Mode slider + global lookahead + Mode-B memory + PDC"
```

---

### Task 4: JSFX — @sample Mode-B Brick integration (live)

**Files:**
- Modify: `JSFX/RCBitNova V0.1`

**Interfaces:**
- Consumes: Task 3 memory; the Phase-2 static + Mode-A band loop.
- Produces: working Mode-B Brick. Mirrors `modeb_brick`/`modeb_brick_stereo`. Static + Mode-A run first (producing the intermediate signal); Mode-B then applies on the globally-delayed bus.

- [ ] **Step 1: Restructure `@sample` so Mode-B runs after static+Mode-A on a delayed bus**

The current `@sample` (Phase 2b) processes static + Mode-A in place and writes `spl0/spl1`. Mode-B must run AFTER, with the global lookahead. Replace the final `spl0 *= out_gain; spl1 *= out_gain;` and the band-loop's per-band Mode-A gating so that **Mode-A only runs for Dyn Mode A bands**, and add a Mode-B pass after the band loop.

(a) Gate the Phase-2b Mode-A dynamic block so it only runs for Dyn Mode A: change its condition from
`(dp[b*4+3] == 1 && slider(10*(b+1)+2) == 0) ? (`
to
`(dp[b*4+3] == 1 && slider(10*(b+1)+2) == 0 && mbmode[b] == 0) ? (`.

(b) After the band loop (which has produced the intermediate L/R in spl0/spl1) and BEFORE `spl0 *= out_gain`, insert the Mode-B pass:

```eel2
  // ===== Mode B (Brick, band-split, bit-exact) =====
  any_b ? (
    L_in = spl0; R_in = spl1;          // intermediate (post static + Mode-A)
    corrL = 0; corrR = 0;              // sum of band corrections (lim - band_delayed)
    b = 0;
    loop(N_BANDS,
      (slider(50 + 10*b + 1) == 1 && mbmode[b] == 1 && slider(10*(b+1)+2) == 0) ? (
        pl = slider(10*(b+1)+8);
        qb = bp[b*3+1];
        da1 = det[b*4]; da2 = det[b*4+1]; da3 = det[b*4+2]; dk = det[b*4+3];
        ceil = dp[b*4]; rel = dp[b*4+2];
        linked = (pl == 0) && (dm[b] == 0);

        // working channels for this band (xa, optionally xb) + a flag if M/S domain
        ms_dom = 0; two = 0;
        pl == 0 ? (
          (dm[b] == 2) ? ( xa = (L_in + R_in)*0.5; xb = (L_in - R_in)*0.5; ms_dom = 1; ) :
                         ( xa = L_in; xb = R_in; );
          two = 1;
        ) : pl == 1 ? ( xa = (L_in + R_in)*0.5; ms_dom = 1; ) :
            pl == 2 ? ( xa = (L_in - R_in)*0.5; ms_dom = 1; ) :
            pl == 3 ? ( xa = L_in; ) : ( xa = R_in; );

        wp = mbwpos[b];
        csA = b*2; csB = b*2 + 1;
        baseA = csA*MAX_LOOK; baseB = csB*MAX_LOOK;

        // --- channel A: extract band (state in dst slot A), ring write, worst-peak, env, clamp ---
        ic1 = dst[b*4]; ic2 = dst[b*4+1];
        v3 = xa - ic2; v1 = da1*ic1 + da2*v3; v2 = ic2 + da2*ic1 + da3*v3;
        dst[b*4] = 2*v1 - ic1; dst[b*4+1] = 2*v2 - ic2;
        bA = dk * v1;
        mb_band[baseA + wp] = bA; mb_peak[baseA + wp] = abs(bA);
        worstA = 0; i = 0;
        loop(Lk + 1, p = mb_peak[baseA + ((wp - i + MAX_LOOK) % MAX_LOOK)]; p > worstA ? worstA = p; i += 1;);

        two ? (
          ic1 = dst[b*4+2]; ic2 = dst[b*4+3];
          v3 = xb - ic2; v1 = da1*ic1 + da2*v3; v2 = ic2 + da2*ic1 + da3*v3;
          dst[b*4+2] = 2*v1 - ic1; dst[b*4+3] = 2*v2 - ic2;
          bB = dk * v1;
          mb_band[baseB + wp] = bB; mb_peak[baseB + wp] = abs(bB);
          worstB = 0; i = 0;
          loop(Lk + 1, p = mb_peak[baseB + ((wp - i + MAX_LOOK) % MAX_LOOK)]; p > worstB ? worstB = p; i += 1;);
        );

        // envelopes
        linked ? (
          worst = max(worstA, worstB);
          tgt = worst > ceil ? ceil / worst : 1;
          ea = mbenv[csA]; tgt < ea ? ea = tgt : ( ea = tgt + (ea - tgt)*rel; ea = min(ea,1); );
          mbenv[csA] = ea; mbenv[csB] = ea;
        ) : (
          tgt = worstA > ceil ? ceil / worstA : 1;
          ea = mbenv[csA]; tgt < ea ? ea = tgt : ( ea = tgt + (ea - tgt)*rel; ea = min(ea,1); ); mbenv[csA] = ea;
          two ? (
            tgt = worstB > ceil ? ceil / worstB : 1;
            eb = mbenv[csB]; tgt < eb ? eb = tgt : ( eb = tgt + (eb - tgt)*rel; eb = min(eb,1); ); mbenv[csB] = eb;
          );
        );

        // read delayed, clamp, accumulate correction (lim - band_delayed) in the band's domain
        rpos = (wp - Lk + MAX_LOOK) % MAX_LOOK;
        bdA = mb_band[baseA + rpos];
        limA = bdA * mbenv[csA]; abs(limA) > ceil ? (limA = limA > 0 ? ceil : -ceil);
        dcA = limA - bdA;                 // correction for channel A
        two ? (
          bdB = mb_band[baseB + rpos];
          limB = bdB * mbenv[csB]; abs(limB) > ceil ? (limB = limB > 0 ? ceil : -ceil);
          dcB = limB - bdB;
        );

        // map the band-domain correction back to L/R and accumulate
        pl == 0 ? (
          ms_dom ? ( corrL += dcA + dcB; corrR += dcA - dcB; ) : ( corrL += dcA; corrR += dcB; );
        ) : pl == 1 ? ( corrL += dcA; corrR += dcA; ) :       // Mid correction adds to both
            pl == 2 ? ( corrL += dcA; corrR -= dcA; ) :       // Side correction +L,-R
            pl == 3 ? ( corrL += dcA; ) : ( corrR += dcA; );

        mbwpos[b] = (wp + 1) % MAX_LOOK;
      );
      b += 1;
    );

    // Delayed dry bus: use a dedicated stereo dry delay (one shared ring).
    bus_dry[bus_wp] = L_in; bus_dry[bus_wp + MAX_LOOK] = R_in;
    rp = (bus_wp - Lk + MAX_LOOK) % MAX_LOOK;
    spl0 = bus_dry[rp] + corrL;
    spl1 = bus_dry[rp + MAX_LOOK] + corrR;
    bus_wp = (bus_wp + 1) % MAX_LOOK;
  );

```

**Note on the shared dry bus:** the FINAL recombine adds the domain-mapped band
corrections (`corrL/corrR`) to the delayed *L/R intermediate*, held in a dedicated
stereo dry ring `bus_dry` (created in Step 2). The per-band `mb_dry` rings are written
for parity with the single-channel reference but are not read in the L/R recombine — the
`bus_dry` delay is what reconstructs the dry path. All Mode-B bands share `bus_dry` and
the same global `Lk`, so their contributions stay time-aligned.

- [ ] **Step 2: (bus_dry already added in Task 3 Step 2)**

`bus_dry` / `bus_wp` were declared and zeroed in Task 3 Step 2's `@init` block. No
additional `@init` change is needed here — proceed to Step 3.

- [ ] **Step 3: Deploy**

```bash
cp "JSFX/RCBitNova V0.1" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.1"
```

- [ ] **Step 4: Live verification in REAPER**

1. **Bit-exact ceiling:** loud 1 kHz. B1 Bell 1kHz Q2 Macro 0, Placement Both, Dyn On, **Dyn Mode = B Band-Split**, Ceiling Macro 2, Lookahead 2 ms, **Output trim 0 (out_gain=1)**. On a meter/analyzer the 1 kHz band contribution is pinned at the ceiling and cannot exceed it (vs Mode A which slightly exceeds). Lower Ceiling → lower hard ceiling. (With Output trim ≠ 0 the band sits at `ceiling × 2^trim` — still a power of two, since out_gain is applied after the Mode-B pass.)
2. **PDC:** REAPER reports latency = Lookahead samples when a Mode-B band is on; 0 when all bands are Mode A / off. Confirm time-alignment (null a parallel dry routing with PDC compensation).
3. **A vs B audible difference:** toggle B1 Dyn Mode A↔B on a transient-rich band — B should sound harder/"alive" (bit-exact clamp) vs A's smooth ride.
4. **Linking:** Both + Linked (no width pump), Dual L/R (independent channels), Dual M/S (limits side only). Single targets (Side/Left) act on one channel.
5. **Mixed A/B bands:** B1 Mode A, B2 Mode B → both work; overall stays time-aligned (B forces the global delay; A runs on the delayed bus).
6. **Transparent below ceiling & silence:** no artefacts; no denormal spike.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V0.1"
git commit -m "feat(rcbitnova): JSFX Mode-B Brick band-split + global lookahead + PDC"
```

---

## Self-Review

**Spec coverage (§4.3 Mode B Brick, §4.5 lookahead):**
- Band-split + bit-exact clamp + recombine → Tasks 1, 4 (+ prototype). ✓
- Per-band contribution guarantee (not master) → Task 1 tests. ✓
- Single global lookahead + PDC; detectors un-delayed, corrections on delayed bus → Tasks 3, 4. ✓
- Per-band Dyn Mode A/B switch → Tasks 3, 4. ✓
- Stereo linking (Linked/Dual-LR/Dual-MS) → Tasks 2, 4. ✓
- Bell-only; HP/LP never dynamic → Task 4 gate `slider(...+2)==0`. ✓
- No gmem; instance-local rings → Tasks 3, 4. ✓

Deferred: Mode-B Soft (RCBitLimiter band-split, no clamp) → Phase 3b. Hard cascade/shelf
dynamics → 2c. Per-band lookahead (single global used instead, §4.5) → not planned.

**Placeholder scan:** clean — all code is final; the recombine uses the `bus_dry` ring
(Step 2). No scaffolding/TODO left.

**Type consistency:** detector (`bandpass`, `level=|k*v1|`), worst-peak/env, clamp, and
recombine identical across `modeb_brick`, `_modeb_brick_two`, and JSFX. `mbmode/mbenv/
mbwpos/bus_dry` offsets consistent between Tasks 3 and 4. Dyn Stereo ints reused from 2b.

---

## Known limitations / accepted (from adversarial plan review)
- **Warm-up transient:** enabling a Mode-B band mid-playback reads `Lk` samples of stale
  ring data (the per-band ring froze while disabled). Accepted as a brief warm-up; the
  envelope/PDC settle within `Lk` samples. (Future: zero the band ring on enable-edge.)
- **Static + Mode-B interaction is offline-untested:** the Python oracle covers Macro 0
  (unity static bell). A Mode-B Bell with Macro≠0 limits the post-static band — a valid
  design, verified live (step 4.? boost + B), not by pytest. Optional future Python test.
- **Worst-peak is O(Lk) per sample × band × channel** (mirrors the oracle). Correct and
  fine for a few opt-in Mode-B bands; a monotonic-deque running max would be bit-identical
  and O(1) if CPU becomes an issue (future perf).
- **Guarantee scope:** per-band *contribution* ≤ ceiling (× out_gain), NOT the summed
  master (other bands + decode add on top). This is by design (no master brickwall).

## Next
- Phase 3b: Mode-B Soft (RCBitLimiter band-split: PurestGain-smoothed, no clamp).
- Phase 2c: Hard cascade, shelf dynamics.
- Phase 6: GUI (node + analyzer, @serialize, 8 bands) — resolves slider reachability.
