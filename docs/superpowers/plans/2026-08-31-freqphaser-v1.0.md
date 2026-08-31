# Freqphaser 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a five-band mastering JSFX that phase-rotates Side bands and adds or moves them into Mid so stereo-only material survives mono playback.

**Architecture:** A page-safe 32768-sample kernel builder creates combined injection and removal FIR responses from five complementary masks. One partitioned overlap-save Side analysis feeds the required convolution outputs; latency-matched dry Mid/Side are recombined after processing.

**Tech Stack:** JSFX/EEL2, REAPER FFT primitives, stdlib-only Python 3.12 oracle, pytest, REAPER live verification.

---

## File map

- Create `JSFX/Freqphaser 1.0`: parameters, DSP, PDC, transitions, monitoring, and GUI.
- Create `tools/freqphaser_dsp.py`: pure-Python mathematical and convolution oracle.
- Create `tools/freqphaser_gates.py`: source, parameter ABI, and memory-layout checks.
- Create `tests/test_freqphaser_dsp.py`: offline regression suite.
- Create `docs/superpowers/specs/fixtures/freqphaser-v1.0-live-checklist.md`: REAPER acceptance matrix.
- Modify `JSFX/README.md`: user documentation.

### Task 1: Transfer-math oracle

**Files:**
- Create: `tools/freqphaser_dsp.py`
- Create: `tests/test_freqphaser_dsp.py`

- [ ] **Step 1: Write the failing math tests**

```python
import math
from tools import freqphaser_dsp as dsp

def test_amount_curve():
    assert dsp.amount_from_bits(0.0) == 0.0
    assert dsp.amount_from_bits(1.0) == 1.0
    assert math.isclose(dsp.amount_from_bits(0.05), 2.0**0.05 - 1.0)

def test_masks_are_complementary():
    cuts = (200.0, 1500.0, 7000.0, 10000.0)
    for slope in (12, 24, 48, 96):
        for k in range(16385):
            weights = dsp.band_weights(24000.0*k/16384.0, cuts, slope)
            assert min(weights) >= -1e-15
            assert math.isclose(sum(weights), 1.0, abs_tol=2e-15)

def test_all_move_at_one_removes_side():
    settings = [dsp.BandSetting(1.0, p, True) for p in (-30, 0, 45, 90, 180)]
    _, removal = dsp.transfer_at(8000.0, (200, 1500, 7000, 10000), 24, settings)
    assert math.isclose(removal, 1.0, abs_tol=2e-15)
```

- [ ] **Step 2: Run the test and verify it fails on the missing module**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Expected: FAIL because `tools.freqphaser_dsp` does not exist.

- [ ] **Step 3: Implement the public math functions**

```python
from dataclasses import dataclass
import cmath
import math

ONE_BIT_DB = 6.020599913279624

@dataclass(frozen=True)
class BandSetting:
    bits: float
    phase_deg: float
    move: bool

def amount_from_bits(bits):
    return 2.0**bits - 1.0

def phase_factor(degrees):
    return cmath.exp(1j * math.radians(degrees))

def high_fraction(freq, cutoff, slope):
    if freq <= 0.0:
        return 0.0
    z = slope / ONE_BIT_DB * math.log2(freq / cutoff)
    return 1.0 if z >= 60 else 0.0 if z <= -60 else 1.0 / (1.0 + 2.0**(-z))

def band_weights(freq, cuts, slope):
    c1, c2, c3, c4 = (high_fraction(freq, cut, slope) for cut in cuts)
    return 1-c1, c1-c2, c2-c3, c3-c4, c4

def transfer_at(freq, cuts, slope, settings):
    injection = 0j
    removal = 0.0
    for weight, setting in zip(band_weights(freq, cuts, slope), settings, strict=True):
        amount = amount_from_bits(setting.bits)
        injection += weight * amount * phase_factor(setting.phase_deg)
        removal += weight * amount if setting.move else 0.0
    return injection, removal
```

- [ ] **Step 4: Run the tests and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Expected: PASS.

Commit: `git add tools/freqphaser_dsp.py tests/test_freqphaser_dsp.py`, then
`git commit -m "test: define Freqphaser transfer math"`.

### Task 2: FFT, layout, and convolution oracle

**Files:**
- Modify: `tools/freqphaser_dsp.py`
- Modify: `tests/test_freqphaser_dsp.py`

- [ ] **Step 1: Add failing tests for conjugate symmetry, page safety, and latency**

```python
def test_response_symmetry_and_layout():
    settings = [dsp.BandSetting(0.5, p, False) for p in (0, 30, -90, 150, 180)]
    injection, removal = dsp.build_transfer_spectra(32768, 48000, (200,1500,7000,10000), 24, settings)
    for k in (1, 17, 1000, 12000):
        assert injection[-k] == injection[k].conjugate()
        assert removal[-k] == removal[k].conjugate()
    layout = dsp.page_layout(32768, 2048, outputs=2, targets=True)
    assert layout.latency == 18432
    assert all(a//65536 == (a+n-1)//65536 for a, n in layout.fft_spans)
```

- [x] **Step 2: Port the proven reference primitives**

Port `lp_fft`, `lp_ifft`, `partitioned_convolve`, Kaiser helpers, and `engine_layout` from
`/Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova/tools/rcbitnova_dsp.py`. Preserve
normalisation and hop ordering. Add `build_transfer_spectra` that fills positive bins from
`transfer_at`, mirrors their conjugates, and keeps DC/Nyquist real.

- [x] **Step 3: Test a centred identity kernel**

Use a 32768-tap impulse at index 16384 and assert the partitioned engine's peak is sample 18432.
Also realize the requested response through IFFT, BD/2 shift, Kaiser beta 14, and FFT so tests cover
the FIR that the plugin actually builds rather than only the ideal spectrum.

- [ ] **Step 4: Run all tests and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Commit the two files as `test: model Freqphaser convolution engine`.

### Task 3: Parameter ABI and source gates

**Files:**
- Create: `JSFX/Freqphaser 1.0`
- Create: `tools/freqphaser_gates.py`
- Modify: `tests/test_freqphaser_dsp.py`

- [ ] **Step 1: Write failing manifest and memory-gate tests**

Read the plugin source and call `assert_slider_manifest`, `assert_page_safe_layout`, and
`assert_no_nested_ternary_compound_assignments`.

- [ ] **Step 2: Declare the exact controls**

Use sliders 1–6 for crossovers 200/1500/7000/10000, Slope 12/24/48/96, and Mono Check. Use four
controls at bases 10/20/30/40/50 for each band's Amount `<0,1,0.05>`, Phase `<-180,180,1>`,
Add/Move, and Listen. Do not declare Output Trim.

- [ ] **Step 3: Implement literal gates**

The manifest compares slider number, default, range, step, enum, and label. The memory gate compares
every FFT span with the oracle. The syntax gate rejects compound assignment in the known dangerous
nested-ternary shape.

- [ ] **Step 4: Run tests and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Commit the plugin, gates, and tests as `feat: define Freqphaser parameter ABI`.

### Task 4: Kernel builder and audio runtime

**Files:**
- Modify: `JSFX/Freqphaser 1.0`
- Modify: `tools/freqphaser_gates.py`
- Modify: `tests/test_freqphaser_dsp.py`

- [ ] **Step 1: Add failing gates for required DSP functions**

Require `fp_layout`, `fp_build_kernels`, `fp_run_hop`, `fp_process`, and `fp_publish_pdc`, exact
`pow(2,bits)-1`, one shared Side FDL, and active/target injection/removal kernels.

- [ ] **Step 2: Port the page-safe RCBitNova engine**

Port the 32768/2048/4096 convolution geometry, Kaiser beta 14, buffer alignment, FFT partitioning,
FDL, output rings, dry rings, and PDC from `JSFX/RCBitNova V1.1`. Remove HP/LP and EQ-specific code.

- [ ] **Step 3: Build combined kernels**

For each positive bin, compute four stable logistic crossover fractions, five telescoping masks,
`amount=pow(2,bits)-1`, and `cos/sin` phase factors. Build conjugate-symmetric injection and real
removal spectra, inverse-transform, shift by 16384, window, and partition.

Sanitize NaN/Inf and enforce ordered crossover values at this kernel boundary. The minimum spacing
is slope-dependent: 2/4/8/16 resolvable bins for 12/24/48/96 dB/oct respectively. GUI clamping is
not a substitute because host automation and presets can bypass it.

- [ ] **Step 4: Process M/S**

```eel
mid = (spl0 + spl1) * 0.5;
side = (spl0 - spl1) * 0.5;
fp_process(side);
mout = delayed_mid + fp_inject;
sout = delayed_side - fp_remove;
spl0 = mout + sout;
spl1 = mout - sout;
```

When every Amount is zero and Listen is off, emit delayed dry L/R exactly while keeping Side
history warm. Report `pdc_delay=18432` from geometry and derive `ext_tail_size`.

- [ ] **Step 5: Run tests and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Commit the engine and tests as `feat: implement Freqphaser audio engine`.

### Task 5: Transitions and monitoring

**Files:**
- Modify: `JSFX/Freqphaser 1.0`
- Modify: `tools/freqphaser_dsp.py`
- Modify: `tests/test_freqphaser_dsp.py`

- [ ] **Step 1: Add failing tests for 50 ms endpoints and monitoring priority**

Cover all four sample rates, queued target replacement, lowest-band Listen under conflicting host
automation, Listen over Mono, and unrotated Move removal.

- [ ] **Step 2: Port RCBitNova's dual-kernel transition discipline**

Build only target banks; queue the newest dirty state during an active fade; use one sample-indexed
alpha for both outputs; copy target to active exactly at completion; skip blending at steady state.

- [ ] **Step 3: Implement Listen and Mono Check**

Listen builds the selected unity rotated band into the injection kernel, skips removal, and outputs
dual mono. Normal mode applies Add/Move; Mono Check outputs final Mid dual mono. Route switches use
the same click-safe final-output transition.

- [ ] **Step 4: Run tests and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Commit the monitoring path as `feat: add click-safe Freqphaser monitoring`.

### Task 6: Custom GUI

**Files:**
- Modify: `JSFX/Freqphaser 1.0`
- Modify: `tools/freqphaser_gates.py`
- Modify: `tests/test_freqphaser_dsp.py`

- [ ] **Step 1: Add failing GUI source gates**

Require logarithmic frequency mapping, four crossover targets, five Amount and Phase knobs, exact
named slider writers, `slider_automate`, Retina scaling, numeric entry, double-click reset, and
0.05-bit/1-degree quantisation.

- [ ] **Step 2: Implement the mastering interface**

Draw a five-region logarithmic band strip with four handles and five band columns. Each column has
a centred PHA-style Phase knob, Amount knob plus percentage, Add/Move, and Listen. Put Slope and
Mono Check outside the columns.

- [ ] **Step 3: Implement exact gestures**

Wheel/drag use declared steps, double-click resets Amount/Phase, right-click accepts numeric entry,
and activating Listen writes the other four Listen sliders off. Every edit calls the explicit
named slider and `slider_automate`.

- [ ] **Step 4: Run tests and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Commit the GUI and gates as `feat: add Freqphaser mastering GUI`.

### Task 7: Documentation, live test, and final audit

**Files:**
- Create: `docs/superpowers/specs/fixtures/freqphaser-v1.0-live-checklist.md`
- Modify: `JSFX/README.md`

- [ ] **Step 1: Document and run the offline contract**

Document controls, amount formula, latency, absence of Output Trim, and the exact live matrix.

Run: `/opt/homebrew/bin/python3.12 -m pytest tests/test_freqphaser_dsp.py -q`

Run: `git diff --check`

Expected: all tests pass and the whitespace check prints nothing.

- [ ] **Step 2: Install a non-overwriting development copy**

Check that `Freqphaser 1.0 Codex Test 1` does not exist in REAPER Effects, then copy to that new
filename. Never replace the user's production file without confirmation.

- [ ] **Step 3: Run live REAPER checks**

Verify compile/load, PDC 18432, delayed null, each band Add/Move at 0/0.5/1 bit, phase
0/±90/±180, all slopes, crossover sweeps, Listen/Mono priority, automation, preset reload,
44.1/48/96/192 kHz, offline tail, CPU, and the harmonica excerpt in stereo and mono.
Use an instrumented copy, never the production artifact, to dump the realized JSFX kernels and
compare them bin-for-bin with `tools/freqphaser_dsp.py`.

- [ ] **Step 4: Commit documentation and regression-tested fixes**

Commit `JSFX/README.md` and the checklist as `docs: verify Freqphaser 1.0`. Any DSP correction must
first receive a failing regression test and use a separate focused commit.

- [ ] **Step 5: Confirm isolation and artifact path**

Run `git status --short`; require no unrelated changes. Report the exact tested plugin path and any
live checks that still require the owner's harmonica source.
