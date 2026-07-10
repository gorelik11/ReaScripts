# RCBitNova V0.4 Minimum-phase HP/LP Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated minimum-phase HP/LP filter section to RCBitNova — two independent filters (HP, LP), each with slope 12/24/36/48/96 dB/oct, resonance Q, and full Placement — as cascaded 2nd-order SVF, zero-latency.

**Architecture:** Python DSP mirror first (TDD), then a JSFX edit into a new `JSFX/RCBitNova V0.4` (copied from V0.3). Each filter is a series cascade of N 2nd-order SVF sections (first section = user Q, rest Butterworth 0.7071); Placement reuses V0.3's per-band running-L/R local-M/S pattern (but Both = plain L/R, no dynamics). The section runs first in `@sample`, before the 4 EQ bands, inside the existing master-bypass short-circuit, and is zero-latency so PDC is unchanged.

**Tech Stack:** Python 3.11 stdlib (pytest), EEL2/JSFX, REAPER for live verification.

**Design numerically pre-validated before this plan** (session prototype `hplp_full_proto.py`, 2026-07-11 — full mirror, promoted to permanent tests here): enum->sections {0:0,1:1,2:2,3:3,4:4,5:8}; far-stopband slopes 12.0/24.1/36.1/48.1/96.2 dB/oct; |H(fc)| = -3xN (-3.01/-6.02/-9.03/-12.04/-24.08); droop -2.11 dB at 2xfc for 8 sec; Q=2 resonance peak +1.44 dB vs -1.61 for Q=0.7071 (4 sec); Q=10 all-slopes hp+lp on a sweep stays finite/bounded; Off == input exactly; HP Placement=Side leaves a mono signal and the Mid content unchanged; a 1-section cascade equals the existing `svf_make("hp")` bit-exactly.

## Global Constraints

- Work in `~/projects/reascripts/.claude/worktrees/rcbitnova` (branch `rcbitnova`). All paths relative to it.
- V0.4 is a **new file `JSFX/RCBitNova V0.4`, copied from V0.3**. NEVER modify frozen `JSFX/RCBitNova V0.1`, `V0.2`, `V0.2 SA`, `V0.3` (tags `rcbitnova-v0.1..v0.3`).
- Python: 3.11, **stdlib only**. Oracle: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` — **71 tests green at plan start**; each task only adds green tests.
- **BIT-ACCURACY:** an HP/LP filter has NO gain — the section is a pure SVF cascade, adds NO `log`/`dB`/`pow(10)`/`20*` to any gain path, touches no gain/ceiling. Zero latency. (`svf_response`/`log2` in TEST helpers is instrumentation only.)
- **Slope enum -> section count (the trap):** UI enum `0..5` = `{Off,12,24,36,48,96}`; `nsec = (enum==5) ? 8 : enum` -> `Off=0,12=1,24=2,36=3,48=4,96=8`. Never treat the enum value as the section count directly.
- **Q convention:** first cascade section uses the user Q; sections 1.. use Butterworth `0.7071`. HP mix `m0=1,m1=-k,m2=-1`; LP mix `m0=0,m1=0,m2=1`; `k=1/q`. Documented accepted behavior: |H(fc)| = -3xN dB at Q=0.7071; Q>0.7071 adds a resonant bump.
- **State reset:** zero a filter's cascade state ONLY on a change of its Slope or Placement (@slider-time). Freq/Q changes update coefficients only; state PERSISTS (continuous automatable — zeroing per block would buzz). Off runs no processing and advances no state.
- **Placement (per filter):** Both = plain L/R (two channels, NO M/S path, NO `both_ms`); Mid/Side = local encode `M=(L+R)/2,S=(L-R)/2`, filter the one target, exact recombine `L=M+S,R=M-S`; Left/Right = that one channel only.
- **Signal order (V0.3 real structure):** `bypass (slider1==1) -> passthrough. else: anti-denormal -> HP/LP SECTION -> 4 bands + Mode A -> Mode B bus -> out_gain`. HP/LP output feeds the band loop and the Mode B `bus_dry` (limits the filtered signal). Zero-latency -> `pdc_delay` unchanged.
- **Sliders (pinned, appended):** `slider131` HP Slope `0<0,5,1{Off,12,24,36,48,96}>`, `132` HP Freq `20<20,20000,1>`, `133` HP Q `0.707<0.1,10,0.001>`, `134` HP Placement `0<0,4,1{Both,Mid,Side,Left,Right}>`, `135` LP Slope (default 0), `136` LP Freq `20000<20,20000,1>`, `137` LP Q `0.707<0.1,10,0.001>`, `138` LP Placement (default 0). V0.3 max slider = 123; existing sliders never renumber.
- EEL2: no empty ternary branch; no `1e-` scientific literals; pure ASCII.
- Commit trailer: the running model's, e.g. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

### Task 1: Python — HP/LP cascade + placement mirror + all permanent tests

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append after `process_band_stereo`)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: `svf_make`, `svf_process`, `svf_response` (existing).
- Produces:
  - `hplp_sections(enum) -> int` — enum `0..5` -> `0/1/2/3/4/8`.
  - `hplp_cascade(x, ftype, fc, q, sr, nsec) -> list` — one channel through nsec cascaded SVF sections (section 0 user Q, rest 0.7071); `nsec==0` returns `list(x)`. `ftype` in `{"hp","lp"}`.
  - `process_hplp_stereo(Lin, Rin, ftype, fc, q, sr, nsec, placement) -> (list,list)` — placement in `{"both","mid","side","left","right"}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
# ---- Phase V0.4: minimum-phase HP/LP cascade section ----

def _hplp_cmag(f, ftype, fc, q, nsec):
    m = dsp.svf_response(dsp.svf_make(ftype, fc, q, 1.0, SR), f, SR)
    m *= dsp.svf_response(dsp.svf_make(ftype, fc, 0.7071, 1.0, SR), f, SR) ** (nsec - 1)
    return m


def test_hplp_enum_to_sections():
    assert [dsp.hplp_sections(e) for e in range(6)] == [0, 1, 2, 3, 4, 8]


def test_hplp_slope_db_per_oct():
    fc = 100.0
    for nsec in (1, 2, 3, 4, 8):
        s = abs(20*math.log10(_hplp_cmag(fc/4, "hp", fc, 0.7071, nsec))
                - 20*math.log10(_hplp_cmag(fc/8, "hp", fc, 0.7071, nsec)))
        assert abs(s - nsec*12) < 0.5, (nsec, s)


def test_hplp_fc_level_is_minus_3N():
    fc = 100.0
    for nsec in (1, 2, 3, 4, 8):
        assert abs(20*math.log10(_hplp_cmag(fc, "hp", fc, 0.7071, nsec)) - (-3.0103*nsec)) < 0.1


def test_hplp_passband_droop_high_slope():
    fc = 100.0
    assert -2.3 < 20*math.log10(_hplp_cmag(fc*2, "hp", fc, 0.7071, 8)) < -1.9


def test_hplp_resonance_bump():
    fc = 100.0
    def peak(q):
        return max(20*math.log10(_hplp_cmag(fc*(1+i*0.01), "hp", fc, q, 4)) for i in range(80))
    assert peak(2.0) > peak(0.7071) + 2.0


def test_hplp_q10_stability():
    sweep = [math.sin(2*math.pi*(50 + i*0.5)*i/SR) for i in range(20000)]
    for ftype, fc in (("hp", 200.0), ("lp", 8000.0)):
        for nsec in (1, 2, 3, 4, 8):
            out = dsp.hplp_cascade(sweep, ftype, fc, 10.0, SR, nsec)
            assert all(math.isfinite(v) for v in out) and max(abs(v) for v in out) < 100.0


def test_hplp_off_is_identity():
    x = [0.5*math.sin(0.3*i) for i in range(500)]
    assert dsp.hplp_cascade(x, "hp", 100.0, 0.7071, SR, 0) == x
    Lo, Ro = dsp.process_hplp_stereo(x, list(x), "hp", 100.0, 0.7071, SR, 0, "both")
    assert Lo == x and Ro == x


def test_hplp_placement_side_leaves_mono_and_mid():
    mono = [0.5*math.sin(0.25*i) for i in range(400)]
    Lo, Ro = dsp.process_hplp_stereo(mono, mono, "hp", 200.0, 0.7071, SR, 4, "side")
    assert all(abs(a-b) < 1e-12 for a, b in zip(Lo, mono))
    assert all(abs(a-b) < 1e-12 for a, b in zip(Ro, mono))
    L = [0.4*math.sin(0.2*i)+0.1 for i in range(400)]
    R = [0.4*math.sin(0.2*i)-0.1 for i in range(400)]
    Lo, Ro = dsp.process_hplp_stereo(L, R, "hp", 200.0, 0.7071, SR, 4, "side")
    mid_in = [(l+r)*0.5 for l, r in zip(L, R)]
    mid_out = [(a+b)*0.5 for a, b in zip(Lo, Ro)]
    assert all(abs(a-b) < 1e-12 for a, b in zip(mid_out, mid_in))


def test_hplp_12db_equals_existing_single_svf():
    x = [0.5*math.sin(0.3*i) for i in range(500)]
    one = dsp.hplp_cascade(x, "hp", 300.0, 2.0, SR, 1)
    ref = dsp.svf_process(dsp.svf_make("hp", 300.0, 2.0, 1.0, SR), x)
    assert one == ref
    # placement routing continuity: 1-section Both == filter each channel independently
    Lo, Ro = dsp.process_hplp_stereo(x, list(x), "hp", 300.0, 2.0, SR, 1, "both")
    assert Lo == ref and Ro == ref


def test_hplp_cascade_per_section_q_is_locked():
    # Locks "section 0 = user Q, sections 1.. = Butterworth 0.7071" in the time domain
    # (nsec>=2, non-default Q). A bug applying user Q to every section, or Butterworth to
    # all, would otherwise pass every other test.
    x = [0.5*math.sin(0.3*i) for i in range(500)]
    got = dsp.hplp_cascade(x, "hp", 300.0, 2.0, SR, 2)          # sec0 Q=2, sec1 Butterworth
    mid = dsp.svf_process(dsp.svf_make("hp", 300.0, 2.0, 1.0, SR), x)
    ref = dsp.svf_process(dsp.svf_make("hp", 300.0, 0.7071, 1.0, SR), mid)
    assert got == ref
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k hplp`
Expected: the 6 tests that call `hplp_sections`/`hplp_cascade`/`process_hplp_stereo` FAIL with `AttributeError: module 'rcbitnova_dsp' has no attribute 'hplp_sections'`; the 4 purely-analytic tests (`_slope_db_per_oct`, `_fc_level_is_minus_3N`, `_passband_droop_high_slope`, `_resonance_bump`, which use only the existing `svf_response`/`svf_make`) are already GREEN — that is expected, not a problem.

- [ ] **Step 3: Implement** — append to `tools/rcbitnova_dsp.py` (after `process_band_stereo`):

```python
_HPLP_SECTIONS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 8}   # slope enum -> # of 2nd-order sections


def hplp_sections(enum):
    """Slope enum (0..5 = Off/12/24/36/48/96 dB/oct) -> cascade section count."""
    return _HPLP_SECTIONS[enum]


def _hplp_cascade_ch(x, state, ftype, fc, q, sr, nsec):
    """One channel through nsec cascaded 2nd-order SVF sections. Section 0 uses the
    user Q; sections 1.. use Butterworth 0.7071. state = list of [ic1, ic2] per
    section (len nsec), mutated in place. ftype in {'hp','lp'}."""
    c0 = svf_make(ftype, fc, q, 1.0, sr)
    cR = svf_make(ftype, fc, 0.7071, 1.0, sr)
    out = []
    for v0 in x:
        s = v0
        for k in range(nsec):
            c = c0 if k == 0 else cR
            ic1, ic2 = state[k]
            v3 = s - ic2
            v1 = c["a1"]*ic1 + c["a2"]*v3
            v2 = ic2 + c["a2"]*ic1 + c["a3"]*v3
            state[k][0] = 2.0*v1 - ic1
            state[k][1] = 2.0*v2 - ic2
            s = c["m0"]*s + c["m1"]*v1 + c["m2"]*v2
        out.append(s)
    return out


def hplp_cascade(x, ftype, fc, q, sr, nsec):
    """Stateless convenience: fresh state, one channel through nsec sections.
    nsec == 0 (Off) returns a copy of the input unchanged."""
    if nsec == 0:
        return list(x)
    return _hplp_cascade_ch(x, [[0.0, 0.0] for _ in range(nsec)], ftype, fc, q, sr, nsec)


def process_hplp_stereo(Lin, Rin, ftype, fc, q, sr, nsec, placement):
    """One HP or LP filter (nsec-section cascade) applied per placement.
    placement in {'both','mid','side','left','right'}."""
    if nsec == 0:
        return list(Lin), list(Rin)
    def run(ch):
        return hplp_cascade(ch, ftype, fc, q, sr, nsec)
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
Expected: 81 passed (71 + 10).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.4 Python - HP/LP cascade + placement mirror

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: JSFX — create `RCBitNova V0.4`, add HP/LP section (sliders, memory, coeffs, reset, @sample)

**Files:**
- Create: `JSFX/RCBitNova V0.4` (copy of V0.3, then edited)
- Test: `tests/test_rcbitnova_dsp.py` (append V0.4 source guards)

**Interfaces:**
- Consumes: the verified Python `hplp_cascade` / `process_hplp_stereo` (Task 1) as the transcription reference; V0.3's `svf_set` conventions and band-placement pattern (`@sample` ~lines 256-296 and writeback ~444-448).
- Produces: `JSFX/RCBitNova V0.4` with the HP/LP section.

CRITICAL — locate every edit by surrounding code, not by cited line numbers. If an anchor does not match, STOP and report BLOCKED (a wrong JSFX edit crashes REAPER live).

- [ ] **Step 1: Create the file and add the source-guard tests**

```bash
cp "JSFX/RCBitNova V0.3" "JSFX/RCBitNova V0.4"
```

Append to `tests/test_rcbitnova_dsp.py`:

```python
def _jsfx_v04_text():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.4").read_bytes()


def test_jsfx_v04_is_pure_ascii():
    data = _jsfx_v04_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at {bad[:5]} in RCBitNova V0.4"


def test_jsfx_v04_hplp_sliders_and_wiring():
    text = _jsfx_v04_text().decode("ascii")
    for n, frag in ((131, "HP Slope"), (132, "HP Freq"), (133, "HP Q"), (134, "HP Placement"),
                    (135, "LP Slope"), (136, "LP Freq"), (137, "LP Q"), (138, "LP Placement")):
        assert f"slider{n}:" in text and frag in text, f"slider{n} {frag} missing"
    # section helpers and the @sample calls exist
    assert "function hplp_coef(" in text
    assert "function hplp_run(" in text
    assert "hplp_run(0," in text and "hplp_run(1," in text     # HP and LP invoked
    # enum->sections mapping present (the 96 -> 8 trap)
    assert "== 5 ? 8" in text
    # existing V0.3 slider numbers unchanged (spot-check)
    for n in (14, 19, 48, 91, 123):
        assert f"slider{n}:" in text
    import pathlib, re
    v3 = (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.3").read_text()
    assert len(re.findall(r"^slider\d+:", text, re.M)) == len(re.findall(r"^slider\d+:", v3, re.M)) + 8
```

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v04`
Expected: `test_jsfx_v04_is_pure_ascii` PASSES; `test_jsfx_v04_hplp_sliders_and_wiring` FAILS (nothing added yet). Record this RED.

- [ ] **Step 2: Add the eight sliders** — in `JSFX/RCBitNova V0.4`, find the last slider declaration (the V0.3 Hard bank; the highest is `slider123:`). After the last `slider12x:` line, add:

```
slider131:0<0,5,1{Off,12,24,36,48,96}>HP Slope (dB/oct)
slider132:20<20,20000,1>HP Freq (Hz)
slider133:0.707<0.1,10,0.001>HP Q
slider134:0<0,4,1{Both,Mid,Side,Left,Right}>HP Placement
slider135:0<0,5,1{Off,12,24,36,48,96}>LP Slope (dB/oct)
slider136:20000<20,20000,1>LP Freq (Hz)
slider137:0.707<0.1,10,0.001>LP Q
slider138:0<0,4,1{Both,Mid,Side,Left,Right}>LP Placement
```

- [ ] **Step 3: Add the HP/LP memory + helper functions** — in `@init`, immediately AFTER the last memory block (`egh = hc + N_BANDS;` followed by `i = 0; loop(N_BANDS * 2, egh[i] = 1; i += 1;);` — note the array is `N_BANDS*2` slots even though the offset is `hc + N_BANDS`) and BEFORE `function svf_set(...)`, insert:

```
// ===== V0.4 HP/LP section memory + coeffs =====
// hplp_state: 2 filters * 8 sections * 2 channels * 2 integrators = 64 slots.
//   per filter base = fi*32; per section k, chA = base+k*4 (+0 ic1,+1 ic2),
//   chB = base+k*4+2 (+0 ic1,+1 ic2).
// hplp_cf: 2 filters * 2 coeff-sets(first/rest) * 7 = 28 slots.
//   per filter base = fi*14; set0 (user Q) = base+0..6; set1 (Butterworth) = base+7..13.
hplp_state = egh + N_BANDS * 2;
memset(hplp_state, 0, 64);
hplp_cf = hplp_state + 64;
prev_hp_slope = -1; prev_hp_pl = -1;
prev_lp_slope = -1; prev_lp_pl = -1;
hp_nsec = 0; lp_nsec = 0;
```

Then, immediately AFTER `function svf_set(...)` closes (its final `);`), add these two functions:

```
// V0.4: write HP/LP section coeffs (no gain). ftype 3=HP, 4=LP. dst[0..6].
function hplp_coef(dst, ftype, fc, q) local(g, k, a1, a2, a3) (
  g = tan($pi * fc / srate); k = 1 / q;
  a1 = 1 / (1 + g * (g + k)); a2 = g * a1; a3 = g * a2;
  dst[0] = a1; dst[1] = a2; dst[2] = a3; dst[3] = k;
  ftype == 3 ? ( dst[4] = 1; dst[5] = -k; dst[6] = -1; )
             : ( dst[4] = 0; dst[5] = 0;  dst[6] = 1;  );
);

// V0.4: run one HP/LP filter (fi 0=HP,1=LP) over spl0/spl1 with placement + cascade.
function hplp_run(fi, nsec, pl)
  local(cfb, stb, chA, chB, mid, sid, do_b, s, kk, cs, ic1, ic2, v1, v2, v3, a1, a2, a3, m0, m1, m2) (
  cfb = hplp_cf + fi*14; stb = hplp_state + fi*32;
  pl == 0 ? ( chA = spl0; chB = spl1; do_b = 1; ) :
  pl == 3 ? ( chA = spl0; do_b = 0; ) :
  pl == 4 ? ( chA = spl1; do_b = 0; ) : (
    mid = (spl0 + spl1) * 0.5; sid = (spl0 - spl1) * 0.5;
    pl == 1 ? ( chA = mid; ) : ( chA = sid; );
    do_b = 0;
  );
  s = chA; kk = 0;
  loop(nsec,
    cs = cfb + (kk == 0 ? 0 : 7);
    a1 = cs[0]; a2 = cs[1]; a3 = cs[2]; m0 = cs[4]; m1 = cs[5]; m2 = cs[6];
    ic1 = stb[kk*4]; ic2 = stb[kk*4+1];
    v3 = s - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
    stb[kk*4] = 2*v1 - ic1; stb[kk*4+1] = 2*v2 - ic2;
    s = m0*s + m1*v1 + m2*v2;
    kk += 1;
  );
  chA = s;
  do_b ? (
    s = chB; kk = 0;
    loop(nsec,
      cs = cfb + (kk == 0 ? 0 : 7);
      a1 = cs[0]; a2 = cs[1]; a3 = cs[2]; m0 = cs[4]; m1 = cs[5]; m2 = cs[6];
      ic1 = stb[kk*4+2]; ic2 = stb[kk*4+3];
      v3 = s - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
      stb[kk*4+2] = 2*v1 - ic1; stb[kk*4+3] = 2*v2 - ic2;
      s = m0*s + m1*v1 + m2*v2;
      kk += 1;
    );
    chB = s;
  );
  pl == 0 ? ( spl0 = chA; spl1 = chB; ) :
  pl == 3 ? ( spl0 = chA; ) :
  pl == 4 ? ( spl1 = chA; ) :
  pl == 1 ? ( spl0 = chA + sid; spl1 = chA - sid; ) :
            ( spl0 = mid + chA; spl1 = mid - chA; );
);
```

- [ ] **Step 4: Compute coeffs + reset state in `@slider`** — at the END of the `@slider` section (after the existing band/Mode-B setup, before `@sample`), add:

```
// ===== V0.4 HP/LP section: coeffs + state reset (Slope/Placement change only) =====
hp_nsec = slider131 == 5 ? 8 : slider131;
hp_nsec > 0 ? (
  hplp_coef(hplp_cf + 0, 3, slider132, slider133);       // HP set0 (user Q)
  hplp_coef(hplp_cf + 7, 3, slider132, 0.7071);          // HP set1 (Butterworth)
);
(slider131 != prev_hp_slope || slider134 != prev_hp_pl) ? (
  memset(hplp_state + 0, 0, 32); prev_hp_slope = slider131; prev_hp_pl = slider134;
);

lp_nsec = slider135 == 5 ? 8 : slider135;
lp_nsec > 0 ? (
  hplp_coef(hplp_cf + 14, 4, slider136, slider137);      // LP set0 (user Q)
  hplp_coef(hplp_cf + 21, 4, slider136, 0.7071);         // LP set1 (Butterworth)
);
(slider135 != prev_lp_slope || slider138 != prev_lp_pl) ? (
  memset(hplp_state + 32, 0, 32); prev_lp_slope = slider135; prev_lp_pl = slider138;
);
```

- [ ] **Step 5: Invoke the section in `@sample`** — find the anti-denormal line inside the `slider1 != 1 ? (` block: `anti = -anti; spl0 += anti; spl1 += anti;` (followed by `b = 0; loop(N_BANDS, ...`). Immediately AFTER the anti-denormal line and BEFORE `b = 0;`, insert:

```
  // ===== DEDICATED HP/LP FILTER SECTION (min-phase cascade, before bands) =====
  hp_nsec > 0 ? hplp_run(0, hp_nsec, slider134);
  lp_nsec > 0 ? hplp_run(1, lp_nsec, slider138);
```

- [ ] **Step 6: Bump the desc line + add header manual text** — replace line 1:

```
desc: RCBitNova V0.4 - Bit-Accurate M/S Dynamic EQ (static + Mode A + Mode B Soft/Hard cascade + shelf dynamics A+B + proportional-Q bells + min-phase HP/LP slope section)
```

and add to the header comment block (pure ASCII, near the other notes):

```
// HP/LP section: minimum-phase SVF cascade (12/24/36/48/96 dB/oct). Q is on the first
// section (resonance); above 12 dB/oct, Freq is the cascade cutoff parameter, not the
// final -3 dB point (level at Freq is -3 dB per active section at Q=0.7071). Per-filter
// Placement Both/Mid/Side/Left/Right. Zero latency; runs before the EQ bands.
```

- [ ] **Step 7: Self-review (against Task 1's Python + constraints)** — verify before committing:

1. `hplp_run` placement encode/writeback mirrors V0.3's band pattern EXACTLY except: Both = plain L/R (no `both_ms`/dynamics). Mid/Side/Left/Right identical to bands.
2. Cascade: section 0 uses `cfb+0` (user Q set), sections 1.. use `cfb+7` (Butterworth) — matches Python `c0 if k==0 else cR`. HP `m=(1,-k,-1)`, LP `m=(0,0,1)` in `hplp_coef`.
3. State slots: chA `stb[kk*4 +0/+1]`, chB `stb[kk*4+2/+3]`; HP base 0, LP base 32; 8 sections x 4 = 32 per filter; no overlap with V0.3 (`hplp_state = egh + N_BANDS*2`, after the last V0.3 block).
4. Enum->sections: `slider131==5 ? 8 : slider131` (and LP) — 96 -> 8, not 5.
5. State reset fires ONLY on Slope or Placement change (`prev_*` compare), NOT on Freq/Q. `Off` (nsec 0) -> `hplp_run` not called -> no processing, no state advance.
6. Section runs after anti-denormal, before the band loop, INSIDE `slider1 != 1 ?` (bypass short-circuit); zero-latency so `pdc_delay` untouched.
7. No empty ternary branch; no `1e-` literals; only sliders 131-138 added; no existing slider renumbered.
8. `hplp_coef`/`hplp_run` defined in `@init` (after `svf_set`) before their `@slider`/`@sample` use. File byte-pure ASCII.

- [ ] **Step 8: Run the full oracle**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 83 passed (81 + 2 V0.4 guards). Confirm both `test_jsfx_v04_*` green.

- [ ] **Step 8b: Focused diff review**

```bash
git diff --no-index "JSFX/RCBitNova V0.3" "JSFX/RCBitNova V0.4"
```
Confirm ONLY: the 8 slider lines, the `@init` memory block + `hplp_coef`/`hplp_run` functions, the `@slider` coeff/reset block, the two `@sample` `hplp_run` calls, and the desc/header. The existing bands / Mode A / Mode B / shelf / proportional-Q logic is otherwise byte-identical to V0.3.

- [ ] **Step 9: Commit**

```bash
git add "JSFX/RCBitNova V0.4" tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.4 JSFX - min-phase HP/LP slope section (cascade + placement)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Deploy + live verification with Dima + push + tag V0.4

**Files:**
- Deploy copy only (no repo changes except the memory-file note in Step 5).

- [ ] **Step 1: Deploy to REAPER**

```bash
cp "JSFX/RCBitNova V0.4" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.4"
```

(Frozen V0.1/V0.2/V0.2 SA/V0.3 are NOT overwritten. After ANY JSFX hotfix, re-run `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v04` before redeploying.)

- [ ] **Step 2: Live checklist (Dima drives)**

1. Load `RCBitNova V0.4` fresh — no EEL2 syntax error.
2. **Off == V0.3:** both HP and LP Slope = Off -> V0.4 renders identical to V0.3 (null).
3. **Slopes:** HP 12/24/36/48/96 each visibly steeper on an analyzer; the high-slope `Freq`-is-not-(-3 dB) shift is visible at 48/96 (level at Freq = -3 dB per section).
4. **Resonance:** HP Q > 0.707 shows the resonant bump at cutoff; Q = 0.707 clean.
5. **Placement:** HP Side on a stereo mix leaves the Mid (mono) content untouched (mono-the-lows); HP Both filters both; Mid/Left/Right behave; LP independently (HP-Side + LP-Both valid).
6. **Automation:** Off->96, 96->Off, 12<->96, Both->Side->Mid, and a Q sweep at 96 near cutoff — no click/zipper beyond the accepted control-rate warm-up, no burst.
7. **Coexistence:** HP/LP active with Mode B active -> `pdc_delay` unchanged, no double-filter of the delayed bus; master bypass stays zero-latency / bit-perfect.
8. **Stability:** HP 96 + Q 10 near cutoff on loud material -> no NaN/blow-up.
9. **CPU:** record the delta vs V0.3 with HP 96 Both + LP 96 Both (worst case); confirm acceptable.

- [ ] **Step 3: On any failure** — do NOT hunt by ear. Reload V0.3, reproduce in the Python mirror first (`hplp_cascade`/`process_hplp_stereo`), fix in Python if behavioral or JSFX if a transcription slip; re-run the full oracle; redeploy; re-check.

- [ ] **Step 4: After Dima confirms — push + tag**

```bash
git push origin rcbitnova
git tag -a rcbitnova-v0.4 -m "RCBitNova V0.4 - min-phase HP/LP slope section, live-verified"
git push origin rcbitnova-v0.4
```

- [ ] **Step 5: Update the auto-memory file** `~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`: record V0.4 live status, the new tag, and the next roadmap item (the LINEAR-phase HP/LP with Brickwall — the deferred FFT engine).

---

## Plan self-review (done at write time)

- **Spec coverage:** section 2 structure/order -> Task 2 Steps 3-5 + Global Constraints; controls/sliders -> Task 2 Step 2 + guard test. section 3 slope/enum-mapping/memory/coeff-storage/state-reset -> Task 2 Steps 2-4 + Task 1 `hplp_sections`. section 4 Q convention + header text -> Task 2 Steps 3/6 + Task 1 tests 3/5; Q=10 -> Task 1 `test_hplp_q10_stability`. section 5 placement -> Task 1 `process_hplp_stereo` + Task 2 `hplp_run`. section 6 bit-accuracy -> Global Constraints (no gain). section 7 tests: 1 enum, 2 slope, 3 fc, 4 droop, 5 resonance, 6 Q10, 7 Off, 8 placement, 9 12dB -> Task 1 tests one-to-one; new scaffolding (`hplp_cascade`/`process_hplp_stereo`) -> Task 1; live checks -> Task 3. section 8 out-of-scope respected (no Brick, no linear-phase, no saturation; new file only).
- **Placeholders:** none; every step has complete code or an exact command with expected output.
- **Type consistency:** `hplp_sections`/`hplp_cascade(x,ftype,fc,q,sr,nsec)`/`process_hplp_stereo(...,placement)` used with those exact signatures in the tests; the JSFX `hplp_coef`/`hplp_run` mirror the Python cascade + placement term-for-term (first/rest coeff sets, HP/LP m-vectors, per-section state slots, Both=plain-L/R).
- **Numerically pre-validated:** every test constant (slopes, -3N fc, -2.11 droop, resonance, Q10 stability, Off identity, Side routing, 12dB==existing) measured in `hplp_full_proto.py`, not guessed.
