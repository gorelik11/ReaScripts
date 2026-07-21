# RCBitNova V0.6 — Linear-Phase HP/LP + FIR Brick — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a linear-phase mode (min↔linear switch) to RCBitNova's dedicated HP/LP section, plus a FIR-Brick slope, via two independent partitioned-convolution engines — matching the min-phase V0.5 magnitude and leaving all dynamics untouched.

**Architecture:** Python oracle FIRST (verified numerically — see the validated prototype math below), then line-by-line transcription into `JSFX/RCBitNova V0.6` (copy of frozen V0.5), then live-verify in REAPER. Linear path = two serial Arthur-style partitioned-convolution engines (P=2048, B=4096, BD=8192, KMAX=4), each building its kernel from the EXACT digital V0.5 SVF magnitude (Butterworth cascade × resonance bell) or a magnitude step (FIR Brick). Min path (`hplp_run`) is unchanged. Constant MAXLAT PDC + warm engines make all transitions click-safe via output crossfade.

**Tech Stack:** Python 3.11 stdlib only (`math`, `cmath` — NO numpy/scipy); JSFX/EEL2 (REAPER); pytest.

## Global Constraints

- **Bit-accuracy is untouched:** HP/LP are pure filters (no gain stage). Linearizing their phase does not touch the bit claim (gains/ceilings on the `2^n` grid). NO `log`/`dB`/`pow(10)` in any DSP path.
- **Python stdlib only** — no numpy/scipy on this machine. FFT is hand-written radix-2 (`cmath`).
- **V0.5 is FROZEN** (tag `rcbitnova-v0.5`). Work in a NEW file `JSFX/RCBitNova V0.6` (copy of V0.5). Never edit V0.1–V0.5 files.
- **The Python DSP mirror `tools/rcbitnova_dsp.py` is THE ORACLE.** JSFX is a faithful transcription; live REAPER confirms transcription + integration.
- **EEL2 gotchas:** no empty ternary branch; no `1e-30` literal (use `pow(2,-100)`); banked slider numbering; instance-local memory only (never `gmem`); functions defined in `@init`.
- **Engine constants:** `P=2048, B=4096, BD=8192, KMAX=BD/P=4`. Per-engine group delay `= BD/2 = 4096`; per-engine reported latency `= BD/2 + P = 6144` samples. Kaiser `beta = 14` (fixed, no slider).
- **Symmetry tolerance:** kernel is symmetric about integer index `BD/2` to within ~`1e-6` (Kaiser window centered at `(BD-1)/2` vs impulse at `BD/2` — inherent half-sample, matches Arthur). Tests use `1e-6`, NOT exact.
- **Spec:** `docs/superpowers/specs/2026-07-21-rcbitnova-v0.6-linear-phase-hplp-design.md` (rev 3). Reviews: `…-weaknesses.md` (Codex), `…-weaknesses-fable.md` (Fable).
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- **Modify** `tools/rcbitnova_dsp.py` — append (never edit frozen functions) a linear-phase block: `lp_fft`/`lp_ifft`, `kaiser_window`, `hplp_digital_mag`, `build_lp_kernel`, `fir_brick_kernel`, `kernel_group_delay`, `partitioned_convolve`, `page_layout_ok`.
- **Modify** `tests/test_rcbitnova_dsp.py` — append linear-phase tests (fast analytic + a few golden `BD=8192` acceptance cases).
- **Create** `JSFX/RCBitNova V0.6` — copy of `JSFX/RCBitNova V0.5`; add Phase slider, FIR-Brick enum + Min-mode mapping fix, two convolution engines, page-safe memory, placement routing, constant-PDC + crossfade, Mode-B integration.

---

## Task 1: Hand-written FFT/IFFT + Kaiser window (oracle)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append at end)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces: `lp_fft(a: list[complex], inverse=False) -> list[complex]`, `lp_ifft(a) -> list[complex]`, `kaiser_window(N: int, beta: float) -> list[float]`. All pure stdlib.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rcbitnova_dsp.py (append)
import cmath

def test_lp_fft_ifft_roundtrip():
    x = [complex(math.sin(i), 0.3 * math.cos(2 * i)) for i in range(64)]
    rt = dsp.lp_ifft(dsp.lp_fft(x))
    assert max(abs(a - b) for a, b in zip(x, rt)) < 1e-12

def test_lp_fft_matches_naive_dft_small():
    x = [complex(i % 3 - 1, 0) for i in range(8)]
    got = dsp.lp_fft(x)
    for k in range(8):
        ref = sum(x[n] * cmath.exp(-2j * math.pi * k * n / 8) for n in range(8))
        assert abs(got[k] - ref) < 1e-12

def test_kaiser_window_symmetric_and_peaks_center():
    w = dsp.kaiser_window(256, 14.0)
    assert w[0] < 1e-3 and w[-1] < 1e-3
    assert w[128] == pytest.approx(1.0, abs=1e-6)
    assert all(abs(w[i] - w[255 - i]) < 1e-12 for i in range(256))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "lp_fft or kaiser" -q`
Expected: FAIL — `AttributeError: module 'rcbitnova_dsp' has no attribute 'lp_fft'`.

- [ ] **Step 3: Write minimal implementation** (validated prototype math)

```python
# tools/rcbitnova_dsp.py (append)

# ===================== V0.6: linear-phase HP/LP kernel engine =====================
# Pure stdlib. Hand-written radix-2 FFT (no numpy). All math verified numerically
# against the digital V0.5 magnitude before this file was written.

def lp_fft(a, inverse=False):
    """In-place iterative radix-2 FFT. Natural order in and out. len must be 2^k.
    Unnormalized forward; inverse divides by n (so ifft(fft(x)) == x)."""
    n = len(a)
    assert n & (n - 1) == 0, "length must be a power of two"
    a = list(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit; bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        ang = (2j if inverse else -2j) * math.pi / length
        wlen = cmath.exp(ang)
        for i in range(0, n, length):
            w = 1 + 0j; half = length >> 1
            for k in range(half):
                u = a[i + k]; v = a[i + k + half] * w
                a[i + k] = u + v
                a[i + k + half] = u - v
                w *= wlen
        length <<= 1
    if inverse:
        a = [x / n for x in a]
    return a


def lp_ifft(a):
    return lp_fft(a, inverse=True)


def _kaiser_i0(x):
    """Modified Bessel I0 via series (matches Arthur's kaiser_i0, 40 terms)."""
    s = 1.0; t = 1.0; k = 1; xh = x * 0.5
    while k < 40:
        t *= (xh / k) * (xh / k); s += t; k += 1
    return s


def kaiser_window(N, beta):
    """Length-N Kaiser window, symmetric about (N-1)/2 (same as Arthur's win_k)."""
    iv = 1.0 / _kaiser_i0(beta); nf = N - 1
    return [_kaiser_i0(beta * math.sqrt(max(1.0 - (2.0 * i / nf - 1.0) ** 2, 0.0))) * iv
            for i in range(N)]
```

Add `import cmath` at the top of the module if not already present (it is — line 8).

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "lp_fft or kaiser" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.6 oracle - radix-2 FFT/IFFT + Kaiser window

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Kernel construction + symmetry/delay contract (oracle)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `lp_fft`, `lp_ifft`, `kaiser_window`, existing `svf_make`, `svf_response`, `butter_q`, `res_glin`, `fc_eff`.
- Produces:
  - `hplp_digital_mag(ftype: str, freq: float, resonance: float, nsec: int, f: float, sr: float) -> float` — exact realized |H| of the V0.5 min-phase HP/LP filter at frequency `f`. `ftype` in `{"hp","lp"}`. `nsec==0` → 1.0.
  - `build_lp_kernel(BD: int, ftype: str, freq: float, resonance: float, nsec: int, beta: float, sr: float) -> list[float]` — length-BD linear-phase FIR, symmetric about `BD/2`.
  - `kernel_group_delay(BD: int) -> int` — returns `BD // 2`.

- [ ] **Step 1: Write the failing test**

```python
def test_hplp_digital_mag_matches_v05_min_phase():
    # digital_mag must equal the realized magnitude of the actual V0.5 cascade+bell
    sr = 48000.0
    for f in [80, 250, 1000, 8000, 18000]:
        # reconstruct the V0.5 realized magnitude independently
        fe = dsp.fc_eff(120.0, sr); m = 1.0
        for k in range(4):
            m *= dsp.svf_response(dsp.svf_make("hp", fe, dsp.butter_q(k, 4), 1.0, sr), f, sr)
        m *= dsp.svf_response(dsp.svf_make("bell", fe, 2.0, dsp.res_glin(0.6), sr), f, sr)
        assert dsp.hplp_digital_mag("hp", 120.0, 0.6, 4, f, sr) == pytest.approx(m, rel=1e-12)

def test_identity_kernel_is_delta_at_BD_over_2():
    BD = 8192
    k = dsp.build_lp_kernel(BD, "hp", 100.0, 0.0, 0, 14.0, 48000.0)  # nsec=0 -> mag==1
    peak = max(range(BD), key=lambda i: abs(k[i]))
    other = max(abs(k[i]) for i in range(BD) if abs(i - BD // 2) > 4)
    assert peak == BD // 2
    assert other < 1e-9

def test_kernel_symmetric_about_BD_over_2():
    BD = 8192; half = BD // 2
    k = dsp.build_lp_kernel(BD, "hp", 120.0, 0.6, 4, 14.0, 48000.0)
    kmax = max(abs(v) for v in k)
    asym = max(abs(k[half + d] - k[half - d]) for d in range(1, half)) / kmax
    assert asym < 1e-6           # window-centering half-sample; NOT exact
    assert dsp.kernel_group_delay(BD) == 4096
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "digital_mag or identity_kernel or symmetric_about" -q`
Expected: FAIL — no attribute `hplp_digital_mag`.

- [ ] **Step 3: Write minimal implementation**

```python
def hplp_digital_mag(ftype, freq, resonance, nsec, f, sr):
    """Exact realized |H| of the V0.5 min-phase HP/LP filter (nsec staggered-Butterworth
    2nd-order sections + one always-tick resonance bell, Q=2 -> effective 2*sqrt(glin))
    at frequency f. nsec==0 -> 1.0 (Off/identity). Same coefficients as JSFX hplp_coef/
    hplp_bell, so kernel magnitude == min-phase magnitude by construction."""
    if nsec == 0:
        return 1.0
    fe = fc_eff(freq, sr)
    m = 1.0
    for k in range(nsec):
        m *= svf_response(svf_make(ftype, fe, butter_q(k, nsec), 1.0, sr), f, sr)
    m *= svf_response(svf_make("bell", fe, 2.0, res_glin(resonance), sr), f, sr)
    return m


def kernel_group_delay(BD):
    return BD // 2


def build_lp_kernel(BD, ftype, freq, resonance, nsec, beta, sr):
    """Arthur-style linear-phase FIR: sample the desired magnitude over BD bins (natural
    order, mirrored above Nyquist) as a real zero-phase spectrum -> ifft -> fftshift by
    BD/2 -> Kaiser(beta) window. Result is symmetric about index BD/2 (integer group
    delay BD/2) to within ~1e-6 (window centering)."""
    spec = [0j] * BD
    for i in range(BD):
        kk = i if i <= BD // 2 else BD - i          # mirror above Nyquist
        f = max(kk * sr / BD, 0.001)
        spec[i] = complex(hplp_digital_mag(ftype, freq, resonance, nsec, f, sr), 0.0)
    t = lp_ifft(spec)                               # real, circularly even about 0
    half = BD // 2
    win = kaiser_window(BD, beta)
    return [t[(i + half) % BD].real * win[i] for i in range(BD)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "digital_mag or identity_kernel or symmetric_about" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.6 oracle - digital-magnitude kernel + BD/2 symmetry contract

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Magnitude-parity acceptance tests (passband dB + stopband floor)

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `build_lp_kernel`, `hplp_digital_mag`. Adds a local DTFT helper in the test.

- [ ] **Step 1: Write the failing test** (also encodes the parity tolerances from spec §6)

```python
def _kmag(k, f, sr):
    """|DTFT(kernel)| at frequency f."""
    w = 2.0 * math.pi * f / sr
    return abs(sum(kn * cmath.exp(-1j * w * n) for n, kn in enumerate(k) if kn != 0.0))

def test_linear_passband_matches_v05_within_0p3_dB():
    sr = 48000.0; BD = 8192
    k = dsp.build_lp_kernel(BD, "hp", 120.0, 0.6, 4, 14.0, sr)      # 48 dB/oct + res
    for f in [300, 500, 1000, 4000, 12000, 20000]:                  # passband (>= 2*fc)
        got = 20 * math.log10(_kmag(k, f, sr) + 1e-30)
        ana = 20 * math.log10(dsp.hplp_digital_mag("hp", 120.0, 0.6, 4, f, sr))
        assert abs(got - ana) < 0.3

def test_linear_stopband_is_attenuated():
    sr = 48000.0; BD = 8192
    k = dsp.build_lp_kernel(BD, "hp", 120.0, 0.6, 4, 14.0, sr)
    for f in [20, 30, 40, 55]:                                      # >= ~1 octave below fc
        assert 20 * math.log10(_kmag(k, f, sr) + 1e-30) < -40.0

def test_lp_kernel_passband_matches_v05():
    sr = 48000.0; BD = 8192
    k = dsp.build_lp_kernel(BD, "lp", 8000.0, 0.0, 4, 14.0, sr)     # LP, no resonance
    for f in [100, 500, 2000, 5000]:                               # passband (<= fc/2 region)
        got = 20 * math.log10(_kmag(k, f, sr) + 1e-30)
        ana = 20 * math.log10(dsp.hplp_digital_mag("lp", 8000.0, 0.0, 4, f, sr))
        assert abs(got - ana) < 0.3
```

- [ ] **Step 2: Run to verify it fails, then passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "passband or stopband" -q`
Expected: PASS immediately (functions already exist from Task 2 — this task is pure verification of parity tolerances). If any FAIL, the kernel build is wrong — STOP and debug before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.6 oracle - min/linear magnitude parity tolerances

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: FIR Brick kernel + tolerances (oracle)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces: `fir_brick_kernel(BD, ftype, freq, beta, sr) -> list[float]` — linear-phase FIR from a magnitude step (HP `f>=fc?1:0`, LP `f<=fc?1:0`), no resonance, symmetric about `BD/2`.

- [ ] **Step 1: Write the failing test**

```python
def test_fir_brick_symmetric_and_steep():
    sr = 48000.0; BD = 8192; half = BD // 2
    k = dsp.fir_brick_kernel(BD, "hp", 500.0, 14.0, sr)
    kmax = max(abs(v) for v in k)
    assert max(abs(k[half + d] - k[half - d]) for d in range(1, half)) / kmax < 1e-6
    # passband well above fc ~ unity, deep stopband an octave below
    assert 20 * math.log10(_kmag(k, 4000.0, sr) + 1e-30) > -0.5
    assert 20 * math.log10(_kmag(k, 125.0, sr) + 1e-30) < -60.0   # 2 octaves below, beta=14

def test_fir_brick_lp_passes_lows():
    sr = 48000.0; BD = 8192
    k = dsp.fir_brick_kernel(BD, "lp", 2000.0, 14.0, sr)
    assert 20 * math.log10(_kmag(k, 200.0, sr) + 1e-30) > -0.5
    assert 20 * math.log10(_kmag(k, 8000.0, sr) + 1e-30) < -60.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "fir_brick" -q`
Expected: FAIL — no attribute `fir_brick_kernel`.

- [ ] **Step 3: Write minimal implementation**

```python
def fir_brick_kernel(BD, ftype, freq, beta, sr):
    """Linear-phase FIR Brick: magnitude step at fc (no resonance). HP: f>=fc -> 1 else 0;
    LP: f<=fc -> 1 else 0. Finite windowed FIR -> finite transition/ringing (NOT infinite
    slope); the 'FIR Brick' label is deliberately distinct from Mode-B 'Brick' (hard bit
    ceiling)."""
    fe = fc_eff(freq, sr)
    spec = [0j] * BD
    for i in range(BD):
        kk = i if i <= BD // 2 else BD - i
        f = max(kk * sr / BD, 0.001)
        m = (1.0 if f >= fe else 0.0) if ftype == "hp" else (1.0 if f <= fe else 0.0)
        spec[i] = complex(m, 0.0)
    t = lp_ifft(spec)
    half = BD // 2
    win = kaiser_window(BD, beta)
    return [t[(i + half) % BD].real * win[i] for i in range(BD)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "fir_brick" -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.6 oracle - FIR Brick kernel (magnitude step)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Partitioned overlap-save reference + equivalence (oracle)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces: `partitioned_convolve(sig: list[float], ker: list[float], P: int) -> list[float]` — uniform-partitioned overlap-save (B=2P, KMAX=len(ker)/P), matching Arthur's runtime engine bookkeeping. Output lags direct linear convolution by exactly `P` samples (the runtime hop; the kernel's own `BD/2` delay is already baked into a linear-phase kernel).

- [ ] **Step 1: Write the failing test** (equivalence, verified at err ~1e-16 in prototype)

```python
def _direct_conv(sig, ker):
    return [sum(sig[n - m] * ker[m] for m in range(len(ker)) if 0 <= n - m < len(sig))
            for n in range(len(sig))]

def test_partitioned_identity_latency_is_P():
    sig = [float(i) for i in range(80)]
    ker = [0.0] * 16; ker[0] = 1.0
    out = dsp.partitioned_convolve(sig, ker, 16)
    assert all(out[16 + i] == pytest.approx(sig[i], abs=1e-12) for i in range(32))

def test_partitioned_equals_direct():
    sig = [math.sin(0.3 * i) + 0.5 * math.sin(0.02 * i) for i in range(240)]
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]   # 4 partitions of P=16
    ref = _direct_conv(sig, ker)
    out = dsp.partitioned_convolve(sig, ker, 16)
    P = 16   # partitioned lags direct by the hop P
    err = max(abs(out[n + P] - ref[n]) for n in range(64, 160))
    assert err < 1e-12
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "partitioned" -q`
Expected: FAIL — no attribute `partitioned_convolve`.

- [ ] **Step 3: Write minimal implementation** (validated prototype)

```python
def partitioned_convolve(sig, ker, P):
    """Uniform-partitioned overlap-save FFT convolution (Arthur's runtime scheme):
    B=2P, KMAX=len(ker)//P; each partition is P taps zero-padded to B; a frequency-domain
    delay line (FDL) accumulates delayed partitions. Output lags a direct linear
    convolution by exactly P samples. len(ker) must be a multiple of P and P a power of 2."""
    B = 2 * P
    KMAX = len(ker) // P
    Hspec = [lp_fft([complex(ker[kp * P + i], 0) if i < P else 0j for i in range(B)])
             for kp in range(KMAX)]
    fdl = [[0j] * B for _ in range(KMAX)]
    fdl_wr = 0
    hist = [0.0] * B; hp = 0; cnt = 0
    out = []; pend = []
    for n in range(len(sig)):
        hist[hp] = sig[n]; hp = (hp + 1) % B; cnt += 1
        out.append(pend.pop(0) if pend else 0.0)
        if cnt >= P:
            cnt = 0
            blk = [complex(hist[(hp + i) % B], 0) for i in range(B)]   # oldest..newest
            X = lp_fft(blk); fdl[fdl_wr] = X
            yacc = [0j] * B
            for kp in range(KMAX):
                Fd = fdl[(fdl_wr - kp) % KMAX]; H = Hspec[kp]
                for i in range(B):
                    yacc[i] += Fd[i] * H[i]
            y = lp_ifft(yacc)
            for i in range(P):
                pend.append(y[P + i].real)          # valid overlap-save region = last P
            fdl_wr = (fdl_wr + 1) % KMAX
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "partitioned" -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.6 oracle - partitioned overlap-save == direct

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Page-safe memory layout helper (oracle-side guard for the JSFX map)

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces:
  - `lp_engine_buffers(BD, P) -> list[tuple[str, int, bool]]` — ordered `(name, size_words, fft_touched)` for one engine (sizes from spec §11). `fft_touched=True` buffers must not cross a 65536 page.
  - `page_layout(base, BD, P) -> dict[str, int]` — assigns page-aligned base offsets for all FFT-touched buffers of ONE engine starting at `base`, packing ring buffers into gaps; returns `{name: start_offset}` and `{"__top": high_water}`.
  - `page_layout_ok(layout, BD, P) -> bool` — asserts every FFT-touched span `[start, start+size)` lies within a single 65536 page.

- [ ] **Step 1: Write the failing test**

```python
PAGE = 65536

def test_lp_engine_buffer_inventory():
    bufs = dsp.lp_engine_buffers(8192, 2048)
    names = {n for n, _, _ in bufs}
    assert {"desbuf", "Hspec", "fdlA", "fdlB", "fftw", "yacc", "tmpc"} <= names
    # FFT-touched buffers are flagged
    touched = {n for n, _, t in bufs if t}
    assert {"desbuf", "Hspec", "fftw", "yacc", "tmpc"} <= touched

def test_page_layout_keeps_every_fft_span_in_one_page():
    for base in [0, 12345, 200000, 458752]:      # incl. the tight ~7-page start
        layout = dsp.page_layout(base, 8192, 2048)
        assert dsp.page_layout_ok(layout, 8192, 2048)

def test_two_engines_layouts_are_disjoint_and_page_safe():
    l1 = dsp.page_layout(0, 8192, 2048)
    l2 = dsp.page_layout(l1["__top"], 8192, 2048)
    assert dsp.page_layout_ok(l1, 8192, 2048)
    assert dsp.page_layout_ok(l2, 8192, 2048)
    assert l2["__top"] > l1["__top"]             # second engine strictly above the first
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "engine_buffer or page_layout or two_engines" -q`
Expected: FAIL — no attribute `lp_engine_buffers`.

- [ ] **Step 3: Write minimal implementation**

```python
_LP_PAGE = 65536

def lp_engine_buffers(BD, P):
    """One engine's buffers as (name, size_words, fft_touched). Sizes per spec §11.
    Complex buffers count 2 words/item. B=2P, KMAX=BD//P, PB2=B*2."""
    B = 2 * P; KMAX = BD // P; PB2 = B * 2
    return [
        ("desbuf", BD * 2, True),          # complex kernel spectrum, FFT'd
        ("ktime",  BD,     False),         # real kernel (scratch)
        ("win_k",  BD,     False),
        ("Hspec",  KMAX * PB2, True),      # partitions, each span PB2 convolve_c'd
        ("fdlA",   KMAX * PB2, True),
        ("fdlB",   KMAX * PB2, True),
        ("fftw",   PB2, True),
        ("yacc",   PB2, True),
        ("tmpc",   PB2, True),
        ("inA",    B,   False),
        ("inB",    B,   False),
        ("outA",   16384, False),
        ("outB",   16384, False),
        ("dryA",   16384, False),
        ("dryB",   16384, False),
    ]

def _round_up(x, m):
    return ((x + m - 1) // m) * m

def page_layout(base, BD, P):
    """Assign offsets so every FFT-touched buffer's whole span lies in one 65536 page.
    Strategy: place each FFT-touched block on a boundary that is a multiple of its own
    span (span <= 16384 <= page, so alignment guarantees no page crossing); pack non-FFT
    ring buffers afterwards. Partitioned buffers (Hspec/fdlA/fdlB) are page-safe per
    PARTITION: each partition span is PB2; align the block base to PB2 and PB2 divides the
    page, so every partition stays in-page."""
    B = 2 * P; PB2 = B * 2
    layout = {}
    ptr = base
    for name, size, touched in lp_engine_buffers(BD, P):
        if touched:
            unit = PB2 if name in ("Hspec", "fdlA", "fdlB") else size
            # align so the (sub)block never straddles a page; unit divides the page
            ptr = _round_up(ptr, min(unit, _LP_PAGE))
        layout[name] = ptr
        ptr += size
    layout["__top"] = ptr
    return layout

def page_layout_ok(layout, BD, P):
    B = 2 * P; PB2 = B * 2; KMAX = BD // P
    for name, size, touched in lp_engine_buffers(BD, P):
        if not touched:
            continue
        start = layout[name]
        if name in ("Hspec", "fdlA", "fdlB"):
            spans = [(start + kp * PB2, PB2) for kp in range(KMAX)]   # per-partition
        else:
            spans = [(start, size)]
        for s, sz in spans:
            if s // _LP_PAGE != (s + sz - 1) // _LP_PAGE:
                return False
    return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "engine_buffer or page_layout or two_engines" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the FULL oracle to confirm no regression**

Run: `python3 -m pytest tests/ -q`
Expected: PASS (95 prior + new tests all green).

- [ ] **Step 6: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.6 oracle - page-safe layout guard for FFT buffers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: JSFX — copy V0.5 → V0.6, Phase slider, FIR-Brick enum + Min-mode mapping fix

**Files:**
- Create: `JSFX/RCBitNova V0.6` (copy of `JSFX/RCBitNova V0.5`)

**Interfaces:**
- Consumes: the frozen V0.5 source.
- Produces: `slider140` (Phase Min/Linear); HP/LP slope enums extended to index 6 (FIR Brick); `hp_nsec`/`lp_nsec` remap so index 6 → Off in Min mode.

> **JSFX cannot be unit-tested.** These tasks are transcription + deploy + live-verify. The Python oracle (Tasks 1–6) is the correctness guard. After each JSFX task, deploy and confirm the specific live behavior listed.

- [ ] **Step 1: Copy the frozen V0.5 to V0.6**

```bash
cp "JSFX/RCBitNova V0.5" "JSFX/RCBitNova V0.6"
```

- [ ] **Step 2: Update the desc line and add the Phase slider**

Change the top `desc:` to `RCBitNova V0.6` and add, in a fresh bank past the HP/LP block (131–138, leaving 139 as a gap):

```eel
slider140:0<0,1,1{Min,Linear}>Phase
```

- [ ] **Step 3: Extend the HP/LP slope enums to index 6 (FIR Brick)**

Change (slider lines 123 and 127 in V0.5):

```eel
slider131:0<0,5,1{Off,12,24,36,48,96}>HP Slope (dB/oct)
slider135:0<0,5,1{Off,12,24,36,48,96}>LP Slope (dB/oct)
```

to:

```eel
slider131:0<0,6,1{Off,12,24,36,48,96,FIR Brick}>HP Slope (dB/oct)
slider135:0<0,6,1{Off,12,24,36,48,96,FIR Brick}>LP Slope (dB/oct)
```

- [ ] **Step 4: Fix the Min-mode section-count mapping (MANDATORY — else index 6 runs 72 dB/oct)**

In `@slider`, change:

```eel
hp_nsec = slider131 == 5 ? 8 : slider131;
```
to:
```eel
hp_nsec = slider131 == 6 ? 0 : slider131 == 5 ? 8 : slider131;   // FIR Brick (6) -> Off in Min path
```

and the LP analogue:

```eel
lp_nsec = slider135 == 6 ? 0 : slider135 == 5 ? 8 : slider135;
```

(This governs ONLY the min-phase `hplp_run` path. The Linear path reads slope index 6 directly to select the FIR Brick kernel — Task 8.)

- [ ] **Step 5: Deploy and live-verify Min-mode parity (no linear code yet)**

```bash
cp "JSFX/RCBitNova V0.6" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.6"
```

Live check with Dima (Phase defaults to Min; V0.6 must behave EXACTLY like V0.5):
- Load V0.6; Phase=Min. HP/LP at 12/24/48/96 sound identical to V0.5.
- Set HP Slope = FIR Brick with Phase=Min → filter is OFF (bypassed), NOT 72 dB/oct.
- No crash, no CPU change vs V0.5.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V0.6"
git commit -m "feat(rcbitnova): V0.6 JSFX - copy V0.5 + Phase slider + FIR Brick enum + Min mapping fix

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: JSFX — two partitioned-convolution engines + page-safe memory + kernel build

**Files:**
- Modify: `JSFX/RCBitNova V0.6`

**Interfaces:**
- Consumes: `slider140`, extended slope enums, page layout from `page_layout` (Task 6) as the offset table.
- Produces: `@init` memory for two engines (HP=engine 0, LP=engine 1) placed page-safe after `hplp_cf`; helpers `lpk_build(eng, ftype, freq, res, nsec, brick)` (kernel build in `@block`), `lpk_run_lane(eng, ...)` (runtime overlap-save); rebuild signature per engine.

- [ ] **Step 1: Add the page-safe engine memory in `@init`**

Transcribe the offset table from the oracle. Run the oracle once to print the concrete offsets:

```bash
python3 -c "import sys; sys.path.insert(0,'tools'); import rcbitnova_dsp as d; \
l1=d.page_layout(0,8192,2048); l2=d.page_layout(l1['__top'],8192,2048); \
print('E0',{k:v for k,v in l1.items()}); print('E1',{k:v for k,v in l2.items()})"
```

In `@init`, after `hplp_cf = hplp_state + 72;` and its `memset`, add (base = first free word after V0.5's `hplp_cf` block of 126 words, page-aligned):

```eel
// V0.6 linear-phase engines. Two engines (0=HP, 1=LP), each Arthur's partitioned
// convolution (P=2048,B=4096,BD=8192,KMAX=4). Page-safe per spec 11: every FFT/convolve
// span within one 65536 page. Offsets from tools page_layout (transcribe printed table).
lpP = 2048; lpB = 4096; lpBD = 8192; lpKMAX = 4; lpPB2 = lpB * 2;
lp_base = (hplp_cf + 126 + 65535) & ~65535;     // page-align the whole block
// engine stride = one engine's __top; place engine 1 right after engine 0 (also aligned)
// --- transcribe per-buffer offsets for E0 and E1 from the oracle print above ---
// e.g. e0_desbuf = lp_base + <off>; ... e1_desbuf = lp_base + <E1 off>; ...
// (Use the exact printed integers; do NOT hand-arithmetic in EEL — pin them.)
memset(lp_base, 0, <E1.__top - lp_base>);        // clear both engines' span
```

Pin every `e{0,1}_{desbuf,ktime,win_k,Hspec,fdlA,fdlB,fftw,yacc,tmpc,inA,inB,outA,outB,dryA,dryB}` as `lp_base + <printed offset>`. Keep a comment asserting each FFT-touched base is a multiple of its span.

- [ ] **Step 2: Add the Kaiser window + kernel-build helpers in `@init`** (transcribe from oracle)

```eel
function lp_i0(x) local(s,t,k,xh) ( s=1;t=1;k=1;xh=x*0.5;
  while(k<40)(t*=(xh/k)*(xh/k); s+=t; k+=1;); s; );

// build engine eng's kernel into its Hspec, from the digital V0.5 magnitude (or brick).
// ftype 3=HP,4=LP; nsec sections (0=Off/identity); brick=1 -> magnitude step.
function lpk_build(eng, ftype, freq, res, nsec, brick)
  local(dbuf,ktim,wk,hsp,i,kk,f,m,fe,glin,A,src,half,inv,kp,base,jj,q,cc) (
  // ... transcribe build_lp_kernel: fill desbuf with digital_mag over BD bins (mirror
  //     above Nyquist), fft_ipermute+ifft, fftshift by BD/2, Kaiser(beta=14) window,
  //     then partition into Hspec (each P samples -> zero-pad B -> fft+permute).
  // magnitude uses the SAME svf coeffs as hplp_coef/hplp_bell (build coeffs inline,
  //   evaluate |H(e^jw)| via the state-space form used by svf_response).
);
```

The magnitude per bin must be computed from the exact digital SVF transfer (same `a1,a2,a3,m0,m1,m2` as `hplp_coef`/`hplp_bell`), evaluated at `z=exp(j*2pi*f/srate)` using the `svf_response` state-space formula — NOT Arthur's analog `r=f/fc`. Beta is the literal `14`.

- [ ] **Step 3: Add the runtime overlap-save per lane** (transcribe Arthur's `@sample` inner loop, per engine, two lanes A/B)

```eel
// lpk_run_lane advances one engine lane by one sample; every P samples it does the
// FFT block, FDL accumulate over KMAX partitions, ifft, and writes P outputs to outX.
// Mirror Arthur exactly (fft/fft_permute on input block; convolve_c(tmpc, Hspec+kp*PB2, B);
// fft_ipermute+ifft(yacc); outX[ow]=yacc[(P+i)*2]*(1/B)). Zero added latency beyond BD/2+P.
```

- [ ] **Step 4: Rebuild signature per engine in `@slider`/`@block`**

```eel
// compare slope,freq,resonance,placement PER ENGINE individually (never a floating hash).
hp_lin_sig = slider131 + slider132*100003 + slider133*1009 + slider134*7;
hp_lin_sig != hp_lin_sig_prev ? ( hp_need_rebuild = 1; hp_lin_sig_prev = hp_lin_sig; );
// LP analogue with slider135/136/137/138.
// in @block: hp_need_rebuild ? ( lpk_build(0, 3, slider132, slider133,
//   (slider131==6?0:slider131==5?8:slider131), slider131==6); hp_need_rebuild=0; );
```

- [ ] **Step 5: Deploy and live-verify kernel build (Linear, single filter, Both placement)**

Deploy; with Dima:
- Phase=Linear, HP 12 dB/oct @ 500 Hz, Both, Resonance 0 → sounds like the Min HP but with linear phase (no phase smear); A/B against Phase=Min shows same magnitude.
- FIR Brick @ 1 kHz → very steep, clean.
- No crash, CPU sane, no NaN/denormal blowups on silence.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V0.6"
git commit -m "feat(rcbitnova): V0.6 JSFX - two partitioned-conv engines + page-safe memory + kernel build

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: JSFX — placement routing with delayed-dry, serial HP→LP chaining

**Files:**
- Modify: `JSFX/RCBitNova V0.6`

**Interfaces:**
- Consumes: the two engines from Task 8.
- Produces: in the Linear branch of `@sample`, encode each engine's Placement (Both/Mid/Side/Left/Right), filter the active component(s), delay the complementary component by the engine latency, decode, and feed engine 0's output into engine 1 (series) with matched time origin.

- [ ] **Step 1: Implement the five-placement encode/filter/delayed-dry/decode per engine** (per spec §7)

```eel
// For engine with placement pl on input (l,r):
// pl==0 Both  : lane A=l, lane B=r; both filtered; out l'=A_f, r'=B_f
// pl==1 Mid   : M=(l+r)*0.5 filtered -> Mf; S=(l-r)*0.5 delayed by engine latency -> Sd;
//               l'=Mf+Sd, r'=Mf-Sd
// pl==2 Side  : S filtered, M delayed; l'=Md+Sf, r'=Md-Sf
// pl==3 Left  : l filtered, r delayed; l'=l_f, r'=r_delayed
// pl==4 Right : r filtered, l delayed; r'=r_f, l'=l_delayed
// The delayed-dry lane uses a per-engine ring of length >= engine latency (BD/2+P).
```

- [ ] **Step 2: Chain HP (engine 0) → LP (engine 1) in series with matched origin**

Engine 1 consumes engine 0's `(l',r')` output; engine 1's own delayed-dry lane must delay engine-0 output by engine-1 latency so its untouched component still nulls.

- [ ] **Step 3: Deploy and live-verify routing null**

With Dima:
- Phase=Linear, HP Mid @ 200 Hz: pan a mono source hard — the Side (untouched) content passes clean; sum/null test shows no Mid leakage into Side.
- HP=Mid, LP=Side simultaneously (different domains): both act independently, no cross-domain artifacts.
- Left/Right placements affect only the intended channel.

- [ ] **Step 4: Commit**

```bash
git add "JSFX/RCBitNova V0.6"
git commit -m "feat(rcbitnova): V0.6 JSFX - placement routing + delayed-dry + serial chaining

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: JSFX — constant MAXLAT PDC, warm engines, crossfades, Mode-B integration, tail

**Files:**
- Modify: `JSFX/RCBitNova V0.6`

**Interfaces:**
- Produces: constant `pdc_delay = MAXLAT`; warm engines (always collecting history while loaded); Phase-toggle and rebuild output crossfades; Mode-B sample-index integration (`Lk` only, `Dlin` once); `ext_tail_size = MAXLAT`.

- [ ] **Step 1: Define MAXLAT and constant PDC**

```eel
// MAXLAT = worst-case linear (two engines) + Mode-B lookahead allowance, FIXED for the
// whole loaded lifetime (seamless switching over low latency — Dima's decision, spec 9).
LP_LAT = lpBD/2 + lpP;                 // 6144 per engine
MAXLAT = 2*LP_LAT + MAX_LOOK;          // MAX_LOOK = existing Mode-B worst-case lookahead ring
pdc_bot_ch = 0; pdc_top_ch = 2; pdc_delay = MAXLAT;   // constant; NOT gated on bypass anymore
```

Delay the Min path, Off filters, and every dry/complementary lane to `MAXLAT` so all paths share one time origin.

- [ ] **Step 2: Keep engines warm + Phase/rebuild crossfade**

```eel
// Both engines always run (collect input history) while loaded, so Off->On and Phase
// Min<->Linear wake seamlessly. On a Phase change or kernel rebuild, crossfade outputs
// over ~one partition P (both buffers are MAXLAT-aligned, so the fade is sample-accurate).
```

- [ ] **Step 3: Mode-B sample-index integration** (spec §7.1)

Apply the sample-index contract: linear latency `Dlin` is applied once by the engines; Mode-B delays its own bus by `Lk` only (never re-adds `Dlin`); detectors read the current post-HP/LP sample; reported PDC stays `MAXLAT`.

- [ ] **Step 4: Kernel tail / transport**

```eel
ext_tail_size = MAXLAT;    // two serial FIR tails + lookahead; offline renders keep the ring-out
```

- [ ] **Step 5: Deploy and live-verify transitions + integration**

With Dima (play + stopped, and offline render):
- Toggle Phase Min↔Linear while playing → NO timeline jump, NO click (crossfade).
- Toggle master bypass while playing → no jump (constant PDC, dry delayed).
- Sweep HP Freq / Resonance in Linear while playing → click-safe (coalesced rebuild crossfade).
- Mode-B band active + Linear HP/LP → limiter still guarantees its ceiling; no double-delay (transient lands where expected); PDC reads constant.
- Offline render of an item ending in a transient → full linear-phase tail present.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V0.6"
git commit -m "feat(rcbitnova): V0.6 JSFX - constant MAXLAT PDC + warm engines + crossfades + Mode-B integration

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Full regression, adversarial re-review of risky DSP, tag

**Files:**
- All above.

- [ ] **Step 1: Full oracle regression**

Run: `python3 -m pytest tests/ -q`
Expected: all green (95 prior + V0.6 additions).

- [ ] **Step 2: Adversarial review of the risky integration** (per method — dispatch a reviewer for P0/P1 on the JSFX transcription: page-safety offsets, serial-latency origin, Mode-B double-delay, crossfade correctness). Fix any P0/P1 before tagging.

- [ ] **Step 3: Final bit-accuracy audit** (Fable): grep the DSP path for `log`/`dB`/`pow(10)` — must be clean (filters carry no gain stage). Confirm Min path byte-identical to V0.5 except the intentional constant-latency deviation.

- [ ] **Step 4: Live sign-off with Dima** — the full §5/§8/§9/§10 live checks pass in one session.

- [ ] **Step 5: Tag + backup**

```bash
git tag -a rcbitnova-v0.6 -m "V0.6 linear-phase HP/LP + FIR Brick (two serial engines, fixed beta=14, constant MAXLAT)"
git push origin rcbitnova rcbitnova-v0.6
cp "JSFX/RCBitNova V0.6" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.6"
```

- [ ] **Step 6: Update the state memory** (`rcbitnova-state.md`) and handoff doc with V0.6 status.

---

## Self-Review (spec coverage)

- Spec §2 (scope/DSP verdict) → documented in plan header + Global Constraints (no linear dynamics).
- Spec §3 (Phase switch, FIR-Brick enum, two serial engines) → Tasks 7, 8, 9.
- Spec §4 (engine constants) → Global Constraints + Task 8.
- Spec §5 (symmetry/delay `BD/2`) → Task 2 (proven), Global Constraints tolerance.
- Spec §6 (exact digital magnitude, tolerances, FIR Brick) → Tasks 2, 3, 4.
- Spec §7 + §7.1 (placement + Mode-B sample-index) → Tasks 9, 10.
- Spec §8 (rebuild/warm-Off/crossfade) → Tasks 8 (signature), 10 (crossfade/warm).
- Spec §9 (constant MAXLAT, ext_tail_size, bypass) → Task 10.
- Spec §10 (verification suite) → Tasks 1–6 (all TDD, prototype-validated).
- Spec §11 (page-safe layout) → Task 6 (oracle guard) + Task 8 (JSFX transcription).
- Spec §12 (Phase slider140, FIR Brick, beta=14, Freq/Res continuous) → Tasks 7, 8.
- Spec §14 (V0.5 frozen, new file, oracle) → Global Constraints + Task 7.
