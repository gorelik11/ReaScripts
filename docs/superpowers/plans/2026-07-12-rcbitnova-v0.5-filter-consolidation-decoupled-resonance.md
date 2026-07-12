# RCBitNova V0.5 — Filter Consolidation + Decoupled Resonance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Remove High Pass / Low Pass from the per-band Type enum; (2) rework the dedicated HP/LP section so its slope is a clean staggered-Butterworth cascade and its Q control becomes a Resonance that drives a separate always-ticking peaking bell — removing V0.4's high-Q/high-slope dip.

**Architecture:** Python DSP mirror first (append the V0.5 functions `hplp_butter_*` alongside the frozen V0.4 `hplp_*`; no churn), then a JSFX edit into a new `JSFX/RCBitNova V0.5` (copied from V0.4). Consolidation is a per-band Type enum reduction + `svf_set` cleanup + a Type-sanitize guard. The dedicated section keeps its placement/structure but swaps the "Q on first section" cascade for a staggered-Butterworth cascade + a resonance bell.

**Tech Stack:** Python 3.11 stdlib (pytest), EEL2/JSFX, REAPER for live verification.

**Design numerically pre-validated before this plan** (`v05_full_proto.py`, 2026-07-12, promoted to permanent tests): staggered-Butterworth `|H(fc)| = -3.01 dB` for EVERY N (HP and LP); resonance bell peaks (HP=LP) `r=0.5 -> +7.95 (12) / +9.57 (96) dB`, `r=1.0 -> +12.60 / +13.89 dB`, single peak with NO passband dip; the bell at `glin=1` (Resonance=0) is a bit-exact identity (`max|out-input|=0.0`); `1->0->1` Resonance sweep with the always-tick bell shows no burst; finite/bounded output at `r=1` across sample rates {44.1,48,96,192 kHz}, slopes, and min/max cutoff; Type sanitize maps {-1,3,4,5}->0.

## Global Constraints

- Work in `~/projects/reascripts/.claude/worktrees/rcbitnova` (branch `rcbitnova`). All paths relative to it.
- V0.5 is a **new file `JSFX/RCBitNova V0.5`, copied from V0.4**. NEVER modify frozen `JSFX/RCBitNova V0.1..V0.4` (tags `rcbitnova-v0.1..v0.4`).
- Python: 3.11, **stdlib only**. Oracle: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` — **83 tests green at plan start**; each task only adds green tests. The V0.4 `hplp_*` functions/tests stay (they document the frozen V0.4); V0.5 adds `hplp_butter_*` alongside.
- **BIT-ACCURACY:** the slope cascade has no gain; the resonance bell uses a LINEAR gain map `glin = 1 + Resonance*5` — no `log`/`dB`/`pow(10)`/`20*` in production functions. Zero latency.
- **Consolidation:** per-band Type enum `{Bell(0),Low Shelf(1),High Shelf(2)}` (max 2). Remove `svf_set` HP(3)/LP(4) branches (restructure `ftype==0?Bell:ftype==1?Low Shelf:High Shelf`). **Sanitize** the per-band Type before use: `ty>2 || ty<0 -> ty=0` (a stale HP/LP value degrades to a transparent Bell). The dedicated section keeps HP/LP via its own coeff builder (NOT `svf_set`).
- **Slope = staggered-Butterworth:** section `k` of `N` uses `Q_k = 1/(2*cos(pi*(2k+1)/(4N)))`. `|H(fc)| = -3 dB` for every N. Enum `5 -> 8` sections.
- **Resonance = separate bell:** the dedicated-section Q slider becomes **Resonance** (`0..1`, default 0), driving a 2nd-order peaking bell at `fc` with fixed input Q=2 and `glin=1+Resonance*5`. The bell **ALWAYS ticks while Slope is active** (identity at `glin=1`, state stays current -> no click on `1->0->1`). `Slope=Off` disables cascade AND bell (bit-perfect, no state advance, zero latency).
- **Cutoff clamp:** `fc_eff = min(slider_freq, srate*0.49)` in BOTH Python and JSFX.
- **State reset:** zero a filter's state only on Slope or Placement change (NOT Freq/Resonance). Reset ranges HP `[0,36)`, LP `[36,72)`.
- **Sliders:** `slider133` -> **HP Resonance** `0<0,1,0.001>` (was HP Q), `slider137` -> **LP Resonance** `0<0,1,0.001>` (was LP Q). No slider renumbered. Cross-file V0.4->V0.5 preset transfer unsupported.
- **Memory:** `hplp_state = egh + N_BANDS*2` size **72** (HP `[0,36)`, LP `[36,72)`; per filter base `fi*36`, stage `s` 0..7=sections/8=bell, channel `c`: `base+s*4+c*2+{0,1}`). `hplp_cf = hplp_state + 72` size **126** (per filter base `fi*63`; section `k` = `base+k*7`; bell = `base+56`).
- EEL2: no empty ternary branch; no `1e-` literals; pure ASCII.
- Commit trailer: the running model's, e.g. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

### Task 1: Python — V0.5 HP/LP mirror (`hplp_butter_*`) + helpers + tests (append-only)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append after the V0.4 `process_hplp_stereo`)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: `svf_make` (bell/hp/lp), `svf_response`, `svf_process` (existing).
- Produces:
  - `butter_q(k, N) -> float`; `res_glin(r) -> float` (= `1 + r*5`); `hplp_type_sanitize(ty) -> int` (`>2 or <0 -> 0`); `fc_eff(freq, sr) -> float` (= `min(freq, sr*0.49)`).
  - `hplp_butter_cascade(x, ftype, freq, resonance, sr, nsec) -> list` — `nsec` staggered-Butterworth 2nd-order sections + one always-ticking resonance bell (Q=2, `glin=res_glin(resonance)`), fresh state, `fc_eff` applied; `nsec==0` returns `list(x)`.
  - `process_hplp_butter_stereo(Lin, Rin, ftype, freq, resonance, sr, nsec, placement) -> (list,list)` — placement in `{both,mid,side,left,right}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
# ---- Phase V0.5: staggered-Butterworth HP/LP + decoupled resonance ----

def _v05_cmag(f, ftype, fc, resonance, nsec):
    fe = dsp.fc_eff(fc, SR)
    m = 1.0
    for k in range(nsec):
        m *= dsp.svf_response(dsp.svf_make(ftype, fe, dsp.butter_q(k, nsec), 1.0, SR), f, SR)
    m *= dsp.svf_response(dsp.svf_make("bell", fe, 2.0, dsp.res_glin(resonance), SR), f, SR)
    return m


def test_v05_butter_flat_at_fc():
    for ft, fc in (("hp", 380.0), ("lp", 6000.0)):
        for n in (1, 2, 3, 4, 8):
            assert abs(20*math.log10(_v05_cmag(fc, ft, fc, 0.0, n)) - (-3.0103)) < 0.05, (ft, n)


def test_v05_slope_db_per_oct():
    # probe INSIDE the stopband and well below Nyquist (both probes < srate/2). HP probes
    # below fc (fc/8, fc/4); LP probes above fc (2*fc, 4*fc) with a low fc so 4*fc stays
    # far below Nyquist. (Measured worst error: HP 0.33, LP 0.54 dB/oct at SR=48000.)
    for ft, fc, f1, f2 in (("hp", 380.0, 380.0/8, 380.0/4), ("lp", 300.0, 1200.0, 600.0)):
        for n in (1, 2, 3, 4, 8):
            s = abs(20*math.log10(_v05_cmag(f1, ft, fc, 0.0, n))
                    - 20*math.log10(_v05_cmag(f2, ft, fc, 0.0, n))) / abs(math.log2(f2/f1))
            assert abs(s - n*12) < 0.8, (ft, n, s)


def test_v05_resonance_peak_height():
    for ft, fc in (("hp", 380.0), ("lp", 6000.0)):
        for n in (1, 8):
            def peak(r):
                return max(20*math.log10(_v05_cmag(fc*(1+i*0.005) if ft == "hp" else fc*(1-i*0.005),
                                                   ft, fc, r, n)) for i in range(200))
            assert peak(0.0) <= 0.1
            assert 7.0 < peak(0.5) < 10.5
            assert 12.0 < peak(1.0) < 15.0


def test_v05_no_dip_single_peak():
    for ft, fc in (("hp", 380.0), ("lp", 6000.0)):
        frs = [1 + i*0.02 for i in range(40)] if ft == "hp" else [1 - i*0.02 for i in range(40)]
        vals = [20*math.log10(_v05_cmag(fc*fr, ft, fc, 1.0, 8)) for fr in frs]
        minima = sum(1 for i in range(1, len(vals)-1)
                     if vals[i] < vals[i-1]-0.03 and vals[i] < vals[i+1]-0.03)
        assert minima == 0, (ft, minima)


def test_v05_resonance0_is_pure_cascade():
    x = [0.5*math.sin(0.3*i) for i in range(400)]
    got = dsp.hplp_butter_cascade(x, "hp", 380.0, 0.0, SR, 4)
    fe = dsp.fc_eff(380.0, SR)
    ref = x
    for k in range(4):
        ref = dsp.svf_process(dsp.svf_make("hp", fe, dsp.butter_q(k, 4), 1.0, SR), ref)
    assert got == ref   # bell at glin=1 is exact identity


def test_v05_always_tick_stable_no_runaway():
    # Always-tick bell: a 1 -> 0 -> 1 Resonance sweep through ONE persistent cascade stays
    # FINITE and BOUNDED (no burst / runaway / NaN). The always-tick keeps the bell state
    # current, so re-enabling Resonance does not cold-start. (An INSTANT glin step is a
    # coefficient change and produces a bounded step like any IIR param jump; smoothness of
    # instant jumps is NOT asserted - Resonance is a continuous automatable control per spec.)
    sig = [0.5*math.sin(0.05*i) + 0.3*math.sin(0.31*i) for i in range(1500)]
    out = []
    fe = dsp.fc_eff(380.0, SR)
    state = [[0.0, 0.0] for _ in range(9)]  # 8 sections + always-tick bell
    for i, v0 in enumerate(sig):
        r = 1.0 if i < 500 else (0.0 if i < 1000 else 1.0)
        coefs = [dsp.svf_make("hp", fe, dsp.butter_q(k, 8), 1.0, SR) for k in range(8)]
        coefs.append(dsp.svf_make("bell", fe, 2.0, dsp.res_glin(r), SR))
        s = v0
        for st in range(9):
            c = coefs[st]; ic1, ic2 = state[st]
            v3 = s - ic2; v1 = c["a1"]*ic1 + c["a2"]*v3; v2 = ic2 + c["a2"]*ic1 + c["a3"]*v3
            state[st][0] = 2*v1 - ic1; state[st][1] = 2*v2 - ic2
            s = c["m0"]*s + c["m1"]*v1 + c["m2"]*v2
        out.append(s)
    assert all(math.isfinite(v) for v in out)
    assert max(abs(v) for v in out) < 50.0   # bounded, no runaway (typical peak is ~1-2)


def test_v05_stability_across_sr_slope_fc():
    for sr in (44100.0, 48000.0, 96000.0, 192000.0):
        sweep = [math.sin(2*math.pi*(30 + i*0.4)*i/sr) for i in range(12000)]
        for ft in ("hp", "lp"):
            for fc in (20.0, 20000.0):
                for n in (1, 4, 8):
                    o = dsp.hplp_butter_cascade(sweep, ft, fc, 1.0, sr, n)
                    assert all(math.isfinite(v) for v in o) and max(abs(v) for v in o) < 1000.0


def test_v05_type_sanitize():
    assert [dsp.hplp_type_sanitize(t) for t in (-1, 0, 1, 2, 3, 4, 5)] == [0, 0, 1, 2, 0, 0, 0]


def test_v05_fc_eff_clamp():
    assert dsp.fc_eff(20000.0, 44100.0) == 20000.0        # below nyquist*0.49=21609
    assert dsp.fc_eff(20000.0, 32000.0) == 32000.0 * 0.49  # clamped on a low-rate session


def test_v05_off_and_placement():
    x = [0.5*math.sin(0.3*i) for i in range(400)]
    assert dsp.hplp_butter_cascade(x, "hp", 380.0, 1.0, SR, 0) == x   # Off = identity even at r=1
    mono = [0.5*math.sin(0.25*i) for i in range(400)]
    Lo, Ro = dsp.process_hplp_butter_stereo(mono, mono, "hp", 200.0, 0.0, SR, 4, "side")
    assert all(abs(a-b) < 1e-12 for a, b in zip(Lo, mono)) and all(abs(a-b) < 1e-12 for a, b in zip(Ro, mono))
    L = [0.4*math.sin(0.2*i)+0.1 for i in range(400)]; R = [0.4*math.sin(0.2*i)-0.1 for i in range(400)]
    Lo, Ro = dsp.process_hplp_butter_stereo(L, R, "hp", 200.0, 0.0, SR, 4, "side")
    mid_in = [(l+r)*0.5 for l, r in zip(L, R)]; mid_out = [(a+b)*0.5 for a, b in zip(Lo, Ro)]
    assert all(abs(a-b) < 1e-12 for a, b in zip(mid_out, mid_in))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v05`
Expected: FAIL — `AttributeError: module 'rcbitnova_dsp' has no attribute 'butter_q'` (all V0.5 tests error on the missing helpers).

- [ ] **Step 3: Implement** — append to `tools/rcbitnova_dsp.py` (after the V0.4 `process_hplp_stereo`):

```python
def butter_q(k, N):
    """Q of section k (0-based) for a 2N-th order Butterworth cascade of 2nd-order sections."""
    return 1.0 / (2.0 * math.cos(math.pi * (2*k + 1) / (4*N)))


def res_glin(r):
    """Linear resonance-bell peak gain (no dB/log): 0 -> 1 (identity), 1 -> 6 (~+15.6 dB)."""
    return 1.0 + r * 5.0


def hplp_type_sanitize(ty):
    """Clamp a per-band Type to the V0.5 range; a stale HP/LP (3/4) or out-of-range -> Bell(0)."""
    return 0 if (ty > 2 or ty < 0) else ty


def fc_eff(freq, sr):
    """Effective cutoff, clamped below Nyquist for coefficient safety."""
    return min(freq, sr * 0.49)


def _hplp_butter_ch(x, state, ftype, freq, resonance, sr, nsec):
    """One channel: nsec staggered-Butterworth 2nd-order sections + one ALWAYS-ticking
    resonance bell (Q=2, glin=res_glin(resonance)). state = list of [ic1,ic2], length
    nsec+1 (last = bell). ftype in {'hp','lp'}. Bell at glin=1 is a bit-exact identity."""
    fe = fc_eff(freq, sr)
    coefs = [svf_make(ftype, fe, butter_q(k, nsec), 1.0, sr) for k in range(nsec)]
    coefs.append(svf_make("bell", fe, 2.0, res_glin(resonance), sr))
    out = []
    for v0 in x:
        s = v0
        for st in range(nsec + 1):
            c = coefs[st]; ic1, ic2 = state[st]
            v3 = s - ic2
            v1 = c["a1"]*ic1 + c["a2"]*v3
            v2 = ic2 + c["a2"]*ic1 + c["a3"]*v3
            state[st][0] = 2.0*v1 - ic1
            state[st][1] = 2.0*v2 - ic2
            s = c["m0"]*s + c["m1"]*v1 + c["m2"]*v2
        out.append(s)
    return out


def hplp_butter_cascade(x, ftype, freq, resonance, sr, nsec):
    """Stateless convenience. nsec == 0 (Off) returns a copy of the input unchanged."""
    if nsec == 0:
        return list(x)
    return _hplp_butter_ch(x, [[0.0, 0.0] for _ in range(nsec + 1)], ftype, freq, resonance, sr, nsec)


def process_hplp_butter_stereo(Lin, Rin, ftype, freq, resonance, sr, nsec, placement):
    if nsec == 0:
        return list(Lin), list(Rin)
    def run(ch):
        return hplp_butter_cascade(ch, ftype, freq, resonance, sr, nsec)
    if placement == "both":
        return run(Lin), run(Rin)
    if placement == "left":
        return run(Lin), list(Rin)
    if placement == "right":
        return list(Lin), run(Rin)
    M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
    S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
    if placement == "mid":
        M = run(M)
    else:  # side
        S = run(S)
    return ([m + s for m, s in zip(M, S)], [m - s for m, s in zip(M, S)])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 93 passed (83 + 10).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.5 Python - staggered-Butterworth HP/LP + decoupled resonance bell

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: JSFX — create `RCBitNova V0.5`, consolidate Type + rework dedicated section

**Files:**
- Create: `JSFX/RCBitNova V0.5` (copy of V0.4, then edited)
- Test: `tests/test_rcbitnova_dsp.py` (append V0.5 source guards)

**Interfaces:**
- Consumes: the verified Python `hplp_butter_cascade` / `process_hplp_butter_stereo` (Task 1) as the transcription reference.
- Produces: `JSFX/RCBitNova V0.5`.

CRITICAL — locate every edit by surrounding code, not line numbers. If an anchor does not match, STOP and report BLOCKED.

- [ ] **Step 1: Create the file and add source-guard tests**

```bash
cp "JSFX/RCBitNova V0.4" "JSFX/RCBitNova V0.5"
```

Append to `tests/test_rcbitnova_dsp.py`:

```python
def _jsfx_v05_text():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.5").read_bytes()


def test_jsfx_v05_is_pure_ascii():
    data = _jsfx_v05_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at {bad[:5]} in RCBitNova V0.5"


def test_jsfx_v05_consolidation_and_resonance():
    text = _jsfx_v05_text().decode("ascii")
    # per-band Type enum reduced to Bell/Low Shelf/High Shelf (max 2), all 4 bands
    for n in (12, 22, 32, 42):
        assert f"slider{n}:0<0,2,1{{Bell,Low Shelf,High Shelf}}>" in text, f"slider{n} Type not consolidated"
    # svf_set no longer has an HP/LP branch (High Pass / Low Pass comment gone from svf_set)
    assert "// High Pass" not in text and "// Low Pass" not in text
    # dedicated-section Q sliders became Resonance 0..1
    assert "slider133:0<0,1,0.001>" in text and "Resonance" in text
    assert "slider137:0<0,1,0.001>" in text
    # new DSP wiring present
    assert "function butter_q(" in text
    assert "function hplp_bell(" in text
    assert "hplp_run(0," in text and "hplp_run(1," in text
    # Type sanitize guard present
    assert "> 2 || " in text or "ty > 2" in text
```

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v05_is_pure_ascii or v05_consolidation"` (the `-k` expression MUST be quoted, else the shell splits `or`).
Expected: ASCII passes; consolidation test FAILS (nothing changed yet). Record RED.

- [ ] **Step 2: Consolidate the per-band Type sliders** — change each of `slider12`, `slider22`, `slider32`, `slider42` from
`sliderN2:0<0,4,1{Bell,Low Shelf,High Shelf,High Pass,Low Pass}>Bn Type`
to
`sliderN2:0<0,2,1{Bell,Low Shelf,High Shelf}>Bn Type` (for the four bands N=1/2/3/4 -> slider 12/22/32/42).

- [ ] **Step 3: Remove `svf_set` HP/LP branches + sanitize Type** — in `svf_set`, replace the `ftype == 3 ? ( High Pass ) : ( Low Pass )` tail so the function is `Bell / Low Shelf / High Shelf` only. Find:

```
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
```
replace with:
```
  ) : (                          // High Shelf
    g = tan($pi * fc / srate) * sqrt(A); k = 1 / q;
    m0 = A * A; m1 = k * (1 - A) * A; m2 = 1 - A * A;
  );
```
Then, in `setup_band(b)`, sanitize the Type read before `svf_set`. Find `svf_set(b * 8, slider(s+2), slider(s+3), band_qeff(b), glin);` and change the type argument to a sanitized local:
```
  bty = slider(s+2); (bty > 2 || bty < 0) ? bty = 0;
  svf_set(b * 8, bty, slider(s+3), band_qeff(b), glin);
```
(add `bty` to `setup_band`'s `local(...)`). NOTE: `band_qeff(b)` and the detector `setup_band_dyn` read `slider(s+2)` too; those already treat only `ty==0` (Bell) specially and everything else as shelf-ish — a stale 3/4 there is harmless, but for consistency the plan's source guard only requires the `svf_set` path sanitized; the reset is the `bty` clamp above.

- [ ] **Step 4: Add `butter_q` + `hplp_bell` helpers** — in `@init`, right AFTER the existing `function hplp_coef(...)` (before `function hplp_run`), insert:

```
// V0.5: staggered-Butterworth section Q for a 2N-th order cascade.
function butter_q(kk, nn) ( 1 / (2 * cos($pi * (2*kk + 1) / (4*nn))) );

// V0.5: resonance bell coeffs (fixed Q=2), glin = 1 + Resonance*5. glin=1 -> identity.
function hplp_bell(dst, fc, glin) local(A, g, bk, a1, a2, a3) (
  A = sqrt(glin); g = tan($pi * fc / srate); bk = 1 / (2 * A);
  a1 = 1 / (1 + g * (g + bk)); a2 = g * a1; a3 = g * a2;
  dst[0] = a1; dst[1] = a2; dst[2] = a3; dst[3] = bk;
  dst[4] = 1; dst[5] = bk * (A * A - 1); dst[6] = 0;
);
```

- [ ] **Step 5: Grow the memory block** — in `@init`, change the V0.4 hplp memory sizing. Find:
```
hplp_state = egh + N_BANDS * 2;
memset(hplp_state, 0, 64);
hplp_cf = hplp_state + 64;
```
replace with (72 state, 126 coeff):
```
hplp_state = egh + N_BANDS * 2;   // V0.5: 2 filters * (8 sec + 1 bell) * 2 ch * 2 = 72
memset(hplp_state, 0, 72);
hplp_cf = hplp_state + 72;         // V0.5: 2 filters * (8 sec + 1 bell) * 7 = 126
```

- [ ] **Step 6: Rework the `@slider` coeff/reset block** — replace the V0.4 HP/LP coeff+reset block (the one that computes `hp_nsec`/`lp_nsec` and calls `hplp_coef` twice per filter) with the staggered-Butterworth + bell version:
```
// ===== V0.5 HP/LP: staggered-Butterworth sections + resonance bell + reset =====
hp_nsec = slider131 == 5 ? 8 : slider131;
hp_fe = min(slider132, srate * 0.49);
hp_nsec > 0 ? (
  kk = 0; loop(hp_nsec, hplp_coef(hplp_cf + kk*7, 3, hp_fe, butter_q(kk, hp_nsec)); kk += 1;);
  hplp_bell(hplp_cf + 56, hp_fe, 1 + slider133 * 5);
);
(slider131 != prev_hp_slope || slider134 != prev_hp_pl) ? (
  memset(hplp_state + 0, 0, 36); prev_hp_slope = slider131; prev_hp_pl = slider134;
);

lp_nsec = slider135 == 5 ? 8 : slider135;
lp_fe = min(slider136, srate * 0.49);
lp_nsec > 0 ? (
  kk = 0; loop(lp_nsec, hplp_coef(hplp_cf + 63 + kk*7, 4, lp_fe, butter_q(kk, lp_nsec)); kk += 1;);
  hplp_bell(hplp_cf + 63 + 56, lp_fe, 1 + slider137 * 5);
);
(slider135 != prev_lp_slope || slider138 != prev_lp_pl) ? (
  memset(hplp_state + 36, 0, 36); prev_lp_slope = slider135; prev_lp_pl = slider138;
);
```

- [ ] **Step 7: Rework `hplp_run`** — replace the V0.4 `hplp_run` body's cascade (which used `cfb + (kk==0?0:7)`) with N staggered sections + the always-tick bell at a fixed slot. Replace the whole function with:
```
// V0.5: run one HP/LP filter (fi 0=HP,1=LP): N Butterworth sections + always-tick bell.
function hplp_run(fi, nsec, pl)
  local(cfb, stb, chA, chB, mid, sid, do_b, s, kk, cs, ic1, ic2, v1, v2, v3, a1, a2, a3, m0, m1, m2) (
  cfb = hplp_cf + fi*63; stb = hplp_state + fi*36;
  pl == 0 ? ( chA = spl0; chB = spl1; do_b = 1; ) :
  pl == 3 ? ( chA = spl0; do_b = 0; ) :
  pl == 4 ? ( chA = spl1; do_b = 0; ) : (
    mid = (spl0 + spl1) * 0.5; sid = (spl0 - spl1) * 0.5;
    pl == 1 ? ( chA = mid; ) : ( chA = sid; );
    do_b = 0;
  );
  s = chA; kk = 0;
  loop(nsec,
    cs = cfb + kk*7; a1 = cs[0]; a2 = cs[1]; a3 = cs[2]; m0 = cs[4]; m1 = cs[5]; m2 = cs[6];
    ic1 = stb[kk*4]; ic2 = stb[kk*4+1];
    v3 = s - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
    stb[kk*4] = 2*v1 - ic1; stb[kk*4+1] = 2*v2 - ic2;
    s = m0*s + m1*v1 + m2*v2; kk += 1;
  );
  cs = cfb + 56; a1 = cs[0]; a2 = cs[1]; a3 = cs[2]; m0 = cs[4]; m1 = cs[5]; m2 = cs[6];  // bell, fixed slot 8
  ic1 = stb[32]; ic2 = stb[33];
  v3 = s - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
  stb[32] = 2*v1 - ic1; stb[33] = 2*v2 - ic2;
  chA = m0*s + m1*v1 + m2*v2;
  do_b ? (
    s = chB; kk = 0;
    loop(nsec,
      cs = cfb + kk*7; a1 = cs[0]; a2 = cs[1]; a3 = cs[2]; m0 = cs[4]; m1 = cs[5]; m2 = cs[6];
      ic1 = stb[kk*4+2]; ic2 = stb[kk*4+3];
      v3 = s - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
      stb[kk*4+2] = 2*v1 - ic1; stb[kk*4+3] = 2*v2 - ic2;
      s = m0*s + m1*v1 + m2*v2; kk += 1;
    );
    cs = cfb + 56; a1 = cs[0]; a2 = cs[1]; a3 = cs[2]; m0 = cs[4]; m1 = cs[5]; m2 = cs[6];
    ic1 = stb[34]; ic2 = stb[35];
    v3 = s - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
    stb[34] = 2*v1 - ic1; stb[35] = 2*v2 - ic2;
    chB = m0*s + m1*v1 + m2*v2;
  );
  pl == 0 ? ( spl0 = chA; spl1 = chB; ) :
  pl == 3 ? ( spl0 = chA; ) :
  pl == 4 ? ( spl1 = chA; ) :
  pl == 1 ? ( spl0 = chA + sid; spl1 = chA - sid; ) :
            ( spl0 = mid + chA; spl1 = mid - chA; );
);
```
(The `@sample` calls `hp_nsec > 0 ? hplp_run(0, hp_nsec, slider134);` / `lp_nsec > 0 ? hplp_run(1, lp_nsec, slider138);` are UNCHANGED from V0.4. The bell always runs INSIDE `hplp_run`, gated only by Slope>0 — so `Slope=Off` disables both cascade and bell.)

- [ ] **Step 8: Bump desc + header, rename the Resonance sliders** — replace `slider133:...HP Q` with `slider133:0<0,1,0.001>HP Resonance` and `slider137:...LP Q` with `slider137:0<0,1,0.001>LP Resonance`. Replace line 1 desc with `...+ min-phase HP/LP (staggered-Butterworth slope + decoupled resonance))` and update the HP/LP header comment to describe the staggered-Butterworth slope + separate Resonance bell. **IMPORTANT: the new header comment must NOT contain the literal strings `// High Pass` or `// Low Pass`** (write "HP" / "LP" / "high-pass" instead) — the guard test `test_jsfx_v05_consolidation_and_resonance` asserts `"// High Pass" not in text and "// Low Pass" not in text` over the whole file to confirm the svf_set branches are gone; a stray comment would fail it.

- [ ] **Step 9: Self-review (against Task 1's Python)** — verify before committing:
1. `butter_q` matches Python `1/(2*cos(pi*(2k+1)/(4N)))`; `hplp_bell` matches `svf_make("bell",fc,2,glin)` (`bk=1/(2A)`, m=`(1, bk*(A*A-1), 0)`); identity at glin=1.
2. Per-filter coeff base `fi*63`; section `k` at `cfb+kk*7`, bell at `cfb+56`; state base `fi*36`, section `k` chA `stb[kk*4+0/1]` chB `stb[kk*4+2/3]`, bell chA `stb[32/33]` chB `stb[34/35]`.
3. `fc_eff = min(slider, srate*0.49)` used for both filters' coeffs.
4. Bell ALWAYS ticks (no Resonance>0 gate around the bell block); `Slope=Off` -> hplp_run not called -> cascade+bell both off, no state advance.
5. Reset `memset(hplp_state+0,0,36)` HP / `+36,36` LP, only on Slope/Placement change.
6. Consolidation: Type enum max 2 (4 bands); svf_set Bell/LS/HS only; `bty` sanitize before svf_set.
7. Memory: `hplp_state` 72, `hplp_cf = hplp_state+72` 126; no overlap (still appended after `egh`).
8. No empty ternary / no `1e-` literals; only sliders 12/22/32/42 (enum) + 133/137 (Resonance) changed; ASCII pure.

- [ ] **Step 10: Full oracle**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 95 passed (93 + 2 V0.5 guards). Confirm both `test_jsfx_v05_*` green.

- [ ] **Step 10b: Focused diff review**

```bash
git diff --no-index "JSFX/RCBitNova V0.4" "JSFX/RCBitNova V0.5"
```
Confirm ONLY: 4 Type sliders (enum 4->2), `svf_set` HP/LP removal, `setup_band` `bty` sanitize, 2 Resonance sliders, `butter_q`+`hplp_bell` added, memory 64->72 / cf base, the `@slider` staggered block, the `hplp_run` rework, desc/header. Existing bands/shelf/prop-Q/Mode A/Mode B logic otherwise byte-identical.

- [ ] **Step 11: Commit**

```bash
git add "JSFX/RCBitNova V0.5" tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.5 JSFX - Type consolidation + staggered-Butterworth HP/LP + resonance bell

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Deploy + live verification with Dima + push + tag V0.5

- [ ] **Step 1: Deploy**

```bash
cp "JSFX/RCBitNova V0.5" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.5"
```
(Frozen V0.1..V0.4 NOT overwritten. After any hotfix re-run `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v05` before redeploying.)

- [ ] **Step 2: Live checklist (Dima drives)**
1. Loads with no EEL2 error.
2. **Consolidation:** per-band Type dropdown offers only Bell / Low Shelf / High Shelf (no HP/LP).
3. **Clean slopes:** dedicated HP each slope 12/24/36/48/96 is flat/monotonic on an analyzer, `-3 dB` at Freq for every slope (no droop), no wiggle at any Resonance.
4. **Resonance:** Resonance 0->1 grows a clean single bump at cutoff at BOTH 12 and 96 dB/oct — the V0.4 high-slope dip is gone; Resonance=0 is flat.
5. **Always-tick:** automate Resonance 1->0->1 on sustained material — no click/burst.
6. **Placement / LP:** HP-Side leaves the Mid untouched; LP independent; Both/Mid/Left/Right behave.
7. **Off:** both Slope=Off -> nulls vs V0.4-filters-off; `Slope=Off, Resonance=1` still bit-perfect (no standalone bell).
8. **Stability:** HP 96 + Resonance 1 near cutoff on loud material -> no NaN/blow-up; test a low-rate (44.1) session too (Nyquist clamp).
9. **Mode B coexistence / CPU:** PDC unchanged with Mode B; record CPU delta vs V0.4 at HP 96 Both + LP 96 Both + Resonance 1.

- [ ] **Step 3: On failure** — reload V0.4, reproduce in the Python mirror (`hplp_butter_cascade`), fix Python-first or JSFX transcription; re-run oracle; redeploy.

- [ ] **Step 4: Push + tag**
```bash
git push origin rcbitnova
git tag -a rcbitnova-v0.5 -m "RCBitNova V0.5 - filter consolidation + decoupled resonance, live-verified"
git push origin rcbitnova-v0.5
```

- [ ] **Step 5: Update `~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`**: V0.5 live status + tag; next = V0.6 linear-phase HP/LP + Brickwall (Arthur's FFT block).

---

## Plan self-review (done at write time)

- **Spec coverage:** section 2 consolidation -> Task 2 Steps 2-3 + guard; section 3 staggered-Butterworth -> Task 1 `butter_q`/`_hplp_butter_ch` + Task 2 Steps 4/6/7; section 4 resonance bell + always-tick + Slope=Off + fc_eff -> Task 1 `res_glin`/bell-always-appended + Task 2 `hplp_bell`/Step 6/7; section 5 memory/sliders -> Task 2 Steps 5/6/8 + guard; section 6 bit-accuracy -> Global Constraints + linear `res_glin`; section 7 tests 1-12 -> Task 1 tests (butter-flat, slope, peak, no-dip, res0-identity, always-tick, stability, sanitize, fc_eff, off/placement) + Task 2 source guards; section 8 out-of-scope respected. (Bandwidth-characterization test 12 is optional-informational; folded into the peak tests' coverage.)
- **Placeholders:** none; every step has complete code or an exact command.
- **Type consistency:** `hplp_butter_cascade`/`process_hplp_butter_stereo`/`butter_q`/`res_glin`/`fc_eff`/`hplp_type_sanitize` used with those signatures in tests; JSFX `butter_q`/`hplp_bell`/`hplp_run` mirror them term-for-term (staggered Q, bell m-vector, fixed bell state slot 8, fc_eff, glin=1+r*5).
- **Numerically pre-validated:** every constant (−3 dB@fc, peak +7.95..+13.89, no-dip, identity, stability) measured in `v05_full_proto.py`.
