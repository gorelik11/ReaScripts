# RCBitNova V0.3 Proportional-Q Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-band Proportional-Q to RCBitNova's bell bands — the bell narrows as the band's static boost/cut grows — via one new per-band `Q Character` control, with `s = 0` bit-identical to V0.2.

**Architecture:** Python DSP mirror first (TDD), then a minimal JSFX edit into a new `JSFX/RCBitNova V0.3` (copied from V0.2). The whole feature is one bit-native law `Q_eff = clamp(Q_knob*(1 + s*|gain_bits_eff|), Q_knob, 16.0)` fed into the EXISTING bell/detector/cut/split Q inputs — no new filter, no new memory, no per-sample state. A single shared `q_eff` expression drives all three Bell Q sites so they cannot diverge.

**Tech Stack:** Python 3.11 stdlib (pytest), EEL2/JSFX, REAPER for live verification.

**Design numerically pre-validated before this plan** (scratchpad `propq_proto.py`, 2026-07-07): `s=0` → bell coefficient tuple bit-identical to raw Q across Q/gain; an analytic `|H|` from the coefficient tuple matches the sine-probe to ~1e-15 at fc; `s>0` narrows the half-gain octave width monotonically (Q_knob=1.0, s=1.0, fc=1 kHz: +0.5/+1/+2 bit → Q_eff 1.5/2.0/3.0 → **0.942 / 0.712 / 0.477 oct**; s=0 holds **1.384 oct** at all gains); worst case (gain_bits_eff=51) clamps to 16.0 and a Q_MAX bell stays stable (impulse tail → 1e-17).

## Global Constraints

- Work in `~/projects/reascripts/.claude/worktrees/rcbitnova` (branch `rcbitnova`). All paths relative to it.
- V0.3 is a **new file `JSFX/RCBitNova V0.3`, copied from V0.2**. NEVER modify frozen `JSFX/RCBitNova V0.1` (tag `rcbitnova-v0.1`), `RCBitNova V0.2` (tag `rcbitnova-v0.2`), or `RCBitNova V0.2 SA`.
- Python: 3.11, **stdlib only**. Oracle: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` — **62 tests green at plan start**; each task only adds green tests.
- **BIT-ACCURACY INVARIANT (paramount):** the law is pure arithmetic on the bit exponent — `gain_bits_eff = (Macro + Micro*0.01) * BitRatio` — with NO `log`, `log10`, `dB`, `pow(10,...)`, or `20*` conversion. `s`/`Q_eff` touch only the bell's `Q` (filter shape), never a gain or ceiling. (The `log2`/`cmath` in TEST measurement helpers is instrumentation, never the DSP path.)
- **`s = 0` MUST be bit-identical to V0.2** via the mandatory fast path `q_eff = (s==0 || type!=Bell) ? Q_knob : clamp(...)` — pass the unmodified `Q_knob` through, no `min/max` round-trip, no new arithmetic.
- **`Q_MAX = 16.0`** pinned. Clamp is applied before coefficient computation. `Q_eff` never drops below `Q_knob`.
- **One shared `q_eff` expression** drives all three Bell Q sites (static `setup_band`, detector `setup_band_dyn` `qd`, and `bp[b*3+1]`). The Mode B `qb = bp[b*3+1]` read is DEAD — do not route the split through it; the split's Q comes from `det[]` (site 2).
- **Bell only.** For Shelf/HP/LP the helper returns `Q_knob` unchanged; the shelf Mode-B split's fixed `Q = 0.7071` is untouched.
- New sliders: **`slider19`=B1, `slider29`=B2, `slider39`=B3, `slider49`=B4**, label `B<n> Q Character`, range `0–1`, default `0`, step `0.001`. Existing slider numbers 11–48 / 51–88 / 91–123 are NOT renumbered. Neutral labels only (no SSL/Neve/API/GML/Sontec).
- EEL2: no empty ternary branch; no `1e-` scientific literals; JSFX stays pure ASCII.
- `gain_bits_eff` in the mirror uses the SAME `(Macro + Micro*0.01)*BitRatio` float form as V0.2's `glin` exponent (V0.2 ~line 188), so JSFX and mirror share the exact exponent float.
- Every commit ends with the CURRENT model's trailer, e.g. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

### Task 1: Python — `q_eff` law helper + analytic `svf_response` + law tests

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append two helpers after `svf_magnitude`, i.e. near the top filter section)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: `svf_make`, `svf_magnitude` (existing).
- Produces:
  - `q_eff(ftype, q_knob, qchar, gain_bits_eff, q_max=16.0) -> float` — the proportional-Q law. Returns `q_knob` exactly when `qchar == 0.0` or `ftype != "bell"`; else `min(q_max, q_knob*(1 + qchar*abs(gain_bits_eff)))`.
  - `svf_response(coeffs, freq, sr) -> float` — exact `|H(e^jw)|` of the TPT-SVF from a coefficient dict (state-space evaluation; replaces the slow sine-probe for bandwidth search).
  These are the V0.3 law + a test utility; the existing bell/detector/cut/split functions are unchanged (V0.3 feeds them `q_eff` at the call sites, which is a JSFX-side concern — the mirror proves the law).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
# ---- Phase V0.3: Proportional-Q law ----

def _octave_bw(fc, q, glin, sr, level_db):
    """Half-gain octave width: distance between the two freqs where |H|_dB == level_db,
    using the exact analytic svf_response (not a sine-probe)."""
    c = dsp.svf_make("bell", fc, q, glin, sr)
    def mdb(f):
        return 20.0 * math.log10(dsp.svf_response(c, f, sr))
    def find(lo, hi):
        for _ in range(60):
            mid = math.sqrt(lo * hi)
            if (mdb(mid) > level_db) == (mdb(lo) > level_db):
                lo = mid
            else:
                hi = mid
        return math.sqrt(lo * hi)
    return math.log2(find(fc, sr / 2.0 - 1.0) / find(1.0, fc))


def test_qeff_s0_is_bit_identical_bell_coeffs():
    # s = 0 -> q_eff == q_knob exactly -> bell coefficient tuple identical to V0.2.
    for qk in (0.5, 0.707, 2.0, 7.0):
        for bits in (-16.0, -6.0, 0.0, 3.0, 16.0):
            glin = 2.0 ** bits
            qe = dsp.q_eff("bell", qk, 0.0, bits)
            assert qe == qk
            assert dsp.svf_make("bell", 1000.0, qe, glin, SR) == \
                   dsp.svf_make("bell", 1000.0, qk, glin, SR)
            # detector (bandpass) tuple identical too (the Mode A/B bell detector site)
            assert dsp.svf_make("bandpass", 1000.0, qe, 1.0, SR) == \
                   dsp.svf_make("bandpass", 1000.0, qk, 1.0, SR)


def test_qeff_bitratio_and_symmetry():
    assert dsp.q_eff("bell", 2.0, 1.0, 0.0) == 2.0            # gain_bits_eff 0 -> no-op
    # BitRatio 0 gives gain_bits_eff 0 regardless of Macro/Micro
    assert dsp.q_eff("bell", 2.0, 1.0, (16 + 100 * 0.01) * 0.0) == 2.0
    # (Macro 2, BitRatio 0.5) == (Macro 1, BitRatio 1): both gain_bits_eff = 1.0
    assert dsp.q_eff("bell", 2.0, 0.7, 2 * 0.5) == dsp.q_eff("bell", 2.0, 0.7, 1 * 1.0)
    # symmetric in sign (boost vs cut)
    assert dsp.q_eff("bell", 2.0, 0.7, 3.0) == dsp.q_eff("bell", 2.0, 0.7, -3.0)


def test_qeff_non_bell_untouched():
    for ft in ("lowshelf", "highshelf", "hp", "lp"):
        for s in (0.0, 0.5, 1.0):
            assert dsp.q_eff(ft, 0.9, s, 12.0) == 0.9


def test_qeff_clamp_worst_case():
    # true worst case: Macro 16, Micro 100, BitRatio 3 -> gain_bits_eff 51
    gbits = (16 + 100 * 0.01) * 3
    assert dsp.q_eff("bell", 10.0, 1.0, gbits) == 16.0
    # a Q_MAX bell stays finite/bounded (no self-oscillation blow-up)
    c = dsp.svf_make("bell", 12000.0, 16.0, 2.0 ** 8, SR)
    out = dsp.svf_process(c, [1.0] + [0.0] * 20000)
    assert all(math.isfinite(v) for v in out)
    assert max(abs(v) for v in out) < 3.0


def test_qeff_proportional_narrowing_monotonic():
    # s = 0 holds constant width; s > 0 narrows monotonically as gain grows.
    fc = 1000.0
    w0 = [_octave_bw(fc, dsp.q_eff("bell", 1.0, 0.0, b), 2.0 ** b, SR, b * 6.0206 / 2.0)
          for b in (0.5, 1.0, 2.0)]
    assert abs(w0[0] - w0[1]) < 1e-9 and abs(w0[1] - w0[2]) < 1e-9   # constant
    w1 = [_octave_bw(fc, dsp.q_eff("bell", 1.0, 1.0, b), 2.0 ** b, SR, b * 6.0206 / 2.0)
          for b in (0.5, 1.0, 2.0)]
    assert w1[0] > w1[1] > w1[2]                                     # narrows
    # measured values from the prototype (loose bands, not a locked trajectory)
    assert 0.90 < w1[0] < 0.98 and 0.68 < w1[1] < 0.74 and 0.45 < w1[2] < 0.50


def test_svf_response_matches_probe():
    # the analytic magnitude equals the sine-probe (exact at fc)
    c = dsp.svf_make("bell", 1000.0, 2.0, 4.0, SR)
    assert abs(dsp.svf_response(c, 1000.0, SR) - dsp.svf_magnitude(c, 1000.0, SR)) < 1e-9
    assert abs(dsp.svf_response(c, 1000.0, SR) - 4.0) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "qeff or svf_response"`
Expected: FAIL — `AttributeError: module 'rcbitnova_dsp' has no attribute 'q_eff'`.

- [ ] **Step 3: Implement** — append to `tools/rcbitnova_dsp.py` (after `svf_magnitude`, before `process_band_stereo`):

```python
def q_eff(ftype, q_knob, qchar, gain_bits_eff, q_max=16.0):
    """Proportional-Q law (V0.3). For a bell band, Q rises with the static gain:
    Q_eff = min(q_max, q_knob*(1 + qchar*|gain_bits_eff|)). qchar in [0,1]; qchar=0 or
    a non-bell type returns q_knob exactly (bit-identical fast path). gain_bits_eff is
    the signed static gain exponent (Macro + Micro*0.01)*BitRatio."""
    if qchar == 0.0 or ftype != "bell":
        return q_knob
    qe = q_knob * (1.0 + qchar * abs(gain_bits_eff))
    return q_max if qe > q_max else qe          # qe >= q_knob always; no lower clamp


def svf_response(coeffs, freq, sr):
    """Exact |H(e^jw)| of the Simper TPT-SVF from its coefficient dict, via a
    state-space evaluation. Cheap and exact; use instead of svf_magnitude for
    bandwidth searches."""
    a1, a2, a3 = coeffs["a1"], coeffs["a2"], coeffs["a3"]
    m0, m1, m2 = coeffs["m0"], coeffs["m1"], coeffs["m2"]
    A11 = 2.0 * a1 - 1.0; A12 = -2.0 * a2
    A21 = 2.0 * a2;       A22 = 1.0 - 2.0 * a3
    B1 = 2.0 * a2; B2 = 2.0 * a3
    C1 = m1 * a1 + m2 * a2
    C2 = -m1 * a2 + m2 * (1.0 - a3)
    D = m0 + m1 * a2 + m2 * a3
    z = cmath.exp(1j * 2.0 * math.pi * freq / sr)
    M11 = z - A11; M12 = -A12
    M21 = -A21;    M22 = z - A22
    det = M11 * M22 - M12 * M21
    x1 = (M22 * B1 - M12 * B2) / det
    x2 = (-M21 * B1 + M11 * B2) / det
    return abs(C1 * x1 + C2 * x2 + D)
```

Also add `import cmath` at the top of `tools/rcbitnova_dsp.py` next to `import math` (only if not already present).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 68 passed (62 + 6).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.3 Python - proportional-Q law + analytic svf_response

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: JSFX — create `RCBitNova V0.3`, add Q Character sliders + `band_qeff` + substitute all Bell Q sites

**Files:**
- Create: `JSFX/RCBitNova V0.3` (copy of `JSFX/RCBitNova V0.2`, then edited)
- Test: `tests/test_rcbitnova_dsp.py` (append source-guard + ASCII guard for V0.3)

**Interfaces:**
- Consumes: the verified `q_eff` law (Task 1) as the transcription reference; existing V0.2 memory/sliders — NO new memory blocks.
- Produces: `JSFX/RCBitNova V0.3` with per-band proportional-Q.

CRITICAL — locate every edit by surrounding code, not by cited line numbers. If an anchor does not match, STOP and report BLOCKED.

- [ ] **Step 1: Create the V0.3 file and add the guard tests** — first copy, then append tests:

```bash
cp "JSFX/RCBitNova V0.2" "JSFX/RCBitNova V0.3"
```

Append to `tests/test_rcbitnova_dsp.py`:

```python
def _jsfx_v03_text():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.3").read_bytes()


def test_jsfx_v03_is_pure_ascii():
    data = _jsfx_v03_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at {bad[:5]} in RCBitNova V0.3"


def test_jsfx_v03_qchar_sliders_added_not_renumbered():
    text = _jsfx_v03_text().decode("ascii")
    # the four new Q Character sliders exist, default 0
    for n in (19, 29, 39, 49):
        assert f"slider{n}:0<0,1,0.001>" in text, f"slider{n} Q Character missing/wrong"
    # existing per-band static/dyn/hard slider numbers are untouched (spot-check anchors)
    for n in (11, 14, 17, 41, 48, 51, 58, 91, 121):
        assert f"slider{n}:" in text
    # exactly four new sliders were added vs the V0.2 count
    import pathlib, re
    v2 = (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.2").read_text()
    n2 = len(re.findall(r"^slider\d+:", v2, re.M))
    n3 = len(re.findall(r"^slider\d+:", text, re.M))
    assert n3 == n2 + 4
```

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v03"`
Expected: `test_jsfx_v03_is_pure_ascii` PASSES (fresh copy is ASCII), `test_jsfx_v03_qchar_sliders_added_not_renumbered` FAILS (sliders not added yet). Record this RED.

- [ ] **Step 2: Add the four Q Character sliders** — in `JSFX/RCBitNova V0.3`, find the per-band slider declarations (each band has `sliderN1..N8` for Enable/Type/Freq/Q/Macro/Micro/BitRatio/Placement; bases 10/20/30/40). After each band's `sliderN8` (Placement) line — i.e. after `slider18:...`, `slider28:...`, `slider38:...`, `slider48:...` — add the matching Q Character slider:

```
slider19:0<0,1,0.001>B1 Q Character (0 Constant .. 1 Proportional)
```
```
slider29:0<0,1,0.001>B2 Q Character (0 Constant .. 1 Proportional)
```
```
slider39:0<0,1,0.001>B3 Q Character (0 Constant .. 1 Proportional)
```
```
slider49:0<0,1,0.001>B4 Q Character (0 Constant .. 1 Proportional)
```

(Place each right after its band's Placement slider so the file stays grouped; the number, not the position, is what REAPER binds.)

- [ ] **Step 3: Add the `band_qeff` helper** — in `JSFX/RCBitNova V0.3`, immediately BEFORE `function setup_band(b)`, insert:

```
// Proportional-Q (V0.3): Bell Q_eff = clamp(Qknob*(1 + qchar*|gain_bits_eff|), Qknob, 16).
// Single shared expression for all three Bell Q sites. qchar=0 or non-Bell -> raw Q
// (bit-identical to V0.2). Non-Bell and shelf split fixed Q are untouched.
function band_qeff(b)
  local(s, ty, qk, qc, gbits, qe)
(
  s = 10 * (b + 1);
  ty = slider(s + 2); qk = slider(s + 4); qc = slider(s + 9);
  (qc == 0 || ty != 0) ? ( qe = qk; ) : (
    gbits = (slider(s+5) + slider(s+6) * 0.01) * slider(s+7);
    qe = qk * (1 + qc * abs(gbits));
    qe > 16 ? ( qe = 16; ) : ( qe = qe; );
  );
  qe;
);
```

(The `: ( qe = qe; )` else-arm keeps the ternary non-empty per the EEL2 rule.)

- [ ] **Step 4: Substitute `band_qeff(b)` at the static Bell site** — in `setup_band(b)`, change:

```
  svf_set(b * 8, slider(s+2), slider(s+3), slider(s+4), glin);
```
to:
```
  svf_set(b * 8, slider(s+2), slider(s+3), band_qeff(b), glin);
```

- [ ] **Step 5: Substitute `band_qeff(b)` at the detector and `bp[]` sites** — in `setup_band_dyn(b)`, change the detector Q and the band-Q store. Find:

```
  fc = slider(s + 3); q = slider(s + 4);
  // Bell: bandpass detector at band Q (unity at fc). Shelf: HP/LP-tap detector
  // at fixed Butterworth Q (spec: monotonic, unity passband, 0.7071 at fc).
  qd = (ty == 1 || ty == 2) ? 0.7071 : q;
```
replace with (drop the now-dead `q` read; use `band_qeff(b)` for the Bell detector):
```
  fc = slider(s + 3);
  // Bell: bandpass detector at Q_eff (proportional-Q). Shelf: HP/LP-tap detector
  // at fixed Butterworth Q (monotonic, unity passband, 0.7071 at fc).
  qd = (ty == 1 || ty == 2) ? 0.7071 : band_qeff(b);
```
and find:
```
  bp[b*3] = fc; bp[b*3+1] = q; bp[b*3+2] = tan($pi * fc / srate);
```
replace with:
```
  bp[b*3] = fc; bp[b*3+1] = band_qeff(b); bp[b*3+2] = tan($pi * fc / srate);
```
Then remove `q` from the function's `local(...)` list (it is no longer used; `band_qeff` reads the slider itself). For a Bell band `band_qeff(b)` returns `Q_eff`; for a Shelf band it returns the raw Q (so `bp[b*3+1]` is unchanged and the `qd` ternary already takes the `0.7071` branch) — Shelf/HP/LP behavior is identical to V0.2.

- [ ] **Step 6: Bump the desc line** — replace line 1 of `JSFX/RCBitNova V0.3`:

```
desc: RCBitNova V0.3 - Bit-Accurate M/S Dynamic EQ (static + Mode A + Mode B Soft/Hard cascade + shelf dynamics A+B + proportional-Q bells)
```

- [ ] **Step 7: Self-review (against Task 1's `q_eff` and the constraints)** — verify before committing:

1. `band_qeff` returns raw `qk` when `qc == 0` OR `ty != 0` (non-Bell) — the s=0 / non-Bell fast path; matches Python `q_eff`.
2. `gbits = (slider(s+5) + slider(s+6)*0.01) * slider(s+7)` — same `*0.01` and `*BitRatio` form as `glin` in `setup_band`.
3. Clamp `qe > 16 ? qe = 16` present; no lower clamp needed (`qe >= qk`).
4. `band_qeff(b)` substituted at ALL THREE Bell sites: `setup_band` svf_set, `setup_band_dyn` `qd`, `bp[b*3+1]`. The dead Mode B `qb = bp[b*3+1]` read is NOT touched (the split narrows via `det[]`).
5. No empty ternary branch (the `qe > 16 ? (...) : (qe = qe;)` and the outer ternary both have statements); no `1e-` literals.
6. Only sliders 19/29/39/49 added; no existing slider renumbered; each default `0`, step `0.001`.
7. Shelf/HP/LP paths unchanged (band_qeff returns raw Q for them; shelf split fixed 0.7071 untouched).
8. File byte-pure ASCII.

- [ ] **Step 8: Run the full oracle**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 70 passed (68 + 2 V0.3 guards). Confirm both `test_jsfx_v03_*` green.

- [ ] **Step 8b: Focused diff review**

```bash
git diff --no-index "JSFX/RCBitNova V0.2" "JSFX/RCBitNova V0.3"
```
Confirm hunk by hunk: only the four slider lines added, the `band_qeff` function added, three Bell-Q substitutions (svf_set / qd / bp), the dropped `q` read, and the desc line changed. Nothing else — the static/dynamic/Mode-A/Mode-B/shelf logic is otherwise byte-identical to V0.2.

- [ ] **Step 9: Commit**

```bash
git add "JSFX/RCBitNova V0.3" tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.3 JSFX - per-band proportional-Q bells (band_qeff at all 3 Bell Q sites)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Deploy + live verification with Dima + push + tag V0.3

**Files:**
- Deploy copy only (no repo changes except the memory-file note in Step 5).

- [ ] **Step 1: Deploy to REAPER**

```bash
cp "JSFX/RCBitNova V0.3" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.3"
```

(The frozen `RCBitNova V0.2` and `RCBitNova V0.2 SA` are NOT overwritten — they stay loadable. After ANY JSFX hotfix, re-run `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v03"` before redeploying.)

- [ ] **Step 2: Live checklist (Dima drives)** — on a Bell band with real material:

1. Load `RCBitNova V0.3` fresh — plugin loads with no EEL2 syntax error.
2. **`s = 0` == V0.2:** with all four Q Character sliders at 0, V0.3 nulls (or near-nulls) against V0.2 on a static Bell boost/cut (ideally a null render). Confirms the additive-safety guarantee live.
3. **Proportional widen/narrow:** Bell band, raise Q Character; at low static boost the bell is broad, at high boost it narrows — visibly on an analyzer and audibly.
4. **Automate `s` 0→1 while audio plays** — smooth, no zipper/click beyond normal coefficient recompute.
5. **Automate Macro/Micro gain while Q Character is high** — the bell narrows as gain rises, no explosive resonance / self-oscillation at extremes.
6. **Type switch Bell → Shelf → Bell with Q Character nonzero** — Shelf ignores it (shelf sounds exactly as V0.2), Bell resumes proportional behavior; no click.
7. **Dynamics consistency:** with a Bell in Mode A (and Mode B), a high Q Character narrows the detected/cut region too (not just the resting shape) — the dynamic action tracks the narrowed bell.
8. **Extreme stability:** max Macro + max BitRatio + Q Character 1 on a high-freq Bell → clamped, no NaN/blow-up (Q_eff pinned at 16).
9. **CPU:** no meaningful increase vs V0.2.

- [ ] **Step 3: On any failure** — do NOT hunt by ear. Reload `RCBitNova V0.2`, reproduce in the Python mirror first (the `q_eff`/coefficient path), fix in Python if behavioral or JSFX if a transcription slip; re-run the full oracle; redeploy; re-check.

- [ ] **Step 4: After Dima confirms — push + tag**

```bash
git push origin rcbitnova
git tag -a rcbitnova-v0.3 -m "RCBitNova V0.3 - per-band proportional-Q bells, live-verified"
git push origin rcbitnova-v0.3
```

- [ ] **Step 5: Update the auto-memory file** `~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`: record V0.3 live status, the new tag, and the next roadmap item (curve-shape/filter-order modeling — the V0.4 candidate from the spec).

---

## Plan self-review (done at write time)

- **Spec coverage:** §2 law → Task 1 `q_eff` + Task 2 `band_qeff`; bit-native/no-dB → Global Constraints + Task 1 (pure arithmetic). §3 all-Bell-paths from static gain → Task 2 Steps 4–5 (three sites, single shared expr, dead `qb` noted). §4 bit-accuracy → Global Constraints + Task 1 `s=0` identity test. §5 stability/clamp (Q_MAX=16, worst case 51 bits) → Task 1 `test_qeff_clamp_worst_case` + Task 2 clamp. §6 sliders 19/29/39/49, step 0.001, neutral labels, no renumber → Task 2 Steps 1–2 + guard test. §7 tests: 1 (s=0 identity static+detector) → `test_qeff_s0_is_bit_identical_bell_coeffs`; 2 (BitRatio edges) → `test_qeff_bitratio_and_symmetry`; 3 (analytic narrowing) → `test_qeff_proportional_narrowing_monotonic` + `_octave_bw`; 4 (clamp) → `test_qeff_clamp_worst_case`; 5 (non-bell) → `test_qeff_non_bell_untouched`; 6 (source guard) → `test_jsfx_v03_qchar_sliders_added_not_renumbered`. Live checks → Task 3. §8 out-of-scope respected (no shape/order, no presets, no saturation; new file only).
- **Placeholders:** none; every step has complete code or an exact command with expected output.
- **Type consistency:** `q_eff(ftype, q_knob, qchar, gain_bits_eff, q_max=16.0)` and `svf_response(coeffs, freq, sr)` are used with those exact signatures in the tests; the JSFX `band_qeff(b)` mirrors `q_eff` term-for-term (`(qc==0||ty!=0)?qk : min(16, qk*(1+qc*|gbits|))`); `gbits` uses the same `(Macro+Micro*0.01)*BitRatio` form as V0.2's `glin`.
- **Numerically pre-validated:** all test constants (bit-identity at s=0, BW 1.384 constant, 0.942/0.712/0.477 at s=1, clamp 51→16, stable tail) are measured in `propq_proto.py`, not guessed.
