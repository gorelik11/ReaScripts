# RCBitNova V0.7 — High-Resolution Linear-Phase HP/LP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-filter Resolution selector (`Normal` BD=8192 / `High` BD=32768) to RCBitNova's linear-phase HP/LP engines so linear phase can perform a deep low-cut, at zero cost when unused.

**Architecture:** Verify the `fft(32768)` gate live FIRST (Task 1) — everything else depends on it. Then extend the Python oracle (Tasks 2–4) for the per-BD dry ring, packed two-engine layout, hi-res benefit, and measured runtime latency. Then a **behaviour-neutral JSFX refactor** (Task 5: per-engine geometry/offset tables replacing V0.6's hardcoded BD=8192 constants, both engines pinned to Normal → V0.7 must equal V0.6), and only then **turn High on** (Task 6: reconcile procedure, PDC, derived tail, rebuild coalescing). Task 7 = Fable review + tag.

**Tech Stack:** Python 3.11 stdlib only (`math`, `cmath` — NO numpy/scipy); JSFX/EEL2 (REAPER); pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-25-rcbitnova-v0.7-hires-linear-phase-design.md` (**rev 3**). Reviews: `…-v0.7-hires-linear-phase-review.md` (Codex), `…-v0.7-hires-weaknesses-fable.md` (Fable).
- **Bit-accuracy INTACT:** HP/LP are pure filters with no gain stage. NO `log`/`dB`/`pow(10)` in any DSP path. The only scalars are the mandatory `1/BD` (kernel ifft) and `1/B` (runtime ifft) normalisations, each applied exactly once.
- **V0.6 and earlier are FROZEN** (tags `rcbitnova-v0.1` … `rcbitnova-v0.6`). Work in a NEW file `JSFX/RCBitNova V0.7` (copy of V0.6). Never edit V0.1–V0.6 files.
- **Python stdlib only** — no numpy/scipy. Python: `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`.
- **Oracle is append-only:** add new functions at the end of `tools/rcbitnova_dsp.py`, new tests at the end of `tests/test_rcbitnova_dsp.py`. The ONE exception is `lp_engine_buffers`, whose `dryA`/`dryB` sizes must become per-BD (Task 2) — an intentional in-place edit.
- **Engine constants (unchanged):** `P = 2048`, `B = 4096`, `PB2 = 8192`. Kaiser `beta = 14` fixed.
- **Geometry:** Normal `BD=8192, KMAX=4, lat=6144, dry=16384`; High `BD=32768, KMAX=16, lat=18432, dry=32768`. Fallback High `BD=16384, KMAX=8, lat=10240, dry=16384`.
- **Used spans:** Normal `229376`; fallback-16384 `360448`; High `655360`. **Packed tops:** Normal+Normal `458752` (= V0.6 exactly), High+Normal `884736`, Normal+High `917504`, High+High `1310720`.
- **Production kernel builder is impulse-FFT** (`impulse_fft_kernel`), NOT the analytic `build_lp_kernel`. Every low-frequency acceptance test must use the production builder (spec §6).
- **Page-safety:** every `fft`/`ifft`/`fft_permute`/`convolve_c` span must lie inside one 65536-word page. A High `desbuf` spans exactly one page ⇒ must start exactly page-aligned.
- **EEL2 gotchas:** no empty ternary branch; **no scientific literals at all** (`1e-30`, `1e9` → use `pow(2,-100)`, `1000000000`); banked slider numbering; instance-local memory only (never `gmem`); functions must be defined textually before use.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **JSFX cannot be unit-tested.** The Python oracle is the automated guard; each JSFX task ends with a live REAPER check with the owner (Dima).

---

## File Structure

- **Create (scratch, NOT committed):** `<scratchpad>/fft32768_gate.jsfx` — Task 1's throwaway gate test.
- **Modify** `tools/rcbitnova_dsp.py` — in-place: per-BD dry size in `lp_engine_buffers`. Appended: `lp_packed_layouts`.
- **Modify** `tests/test_rcbitnova_dsp.py` — appended: dry-ring/span/packed-layout tests (Task 2), hi-res benefit + sample-rate scope + BD=32768 contract tests (Task 3), measured runtime-latency tests (Task 4).
- **Create** `JSFX/RCBitNova V0.7` — copy of `JSFX/RCBitNova V0.6`; Task 5 refactors it to per-engine geometry (behaviour-neutral), Task 6 enables High.

---

## Task 1: LIVE GATE — does JSFX `fft()` work at 32768?

**Files:**
- Create (scratch, not committed): `<scratchpad>/fft32768_gate.jsfx`
- Deploy to: `~/Library/Application Support/REAPER/Effects/fft32768_gate`

**Interfaces:**
- Produces: a **decision** recorded in the plan/ledger — `BD_HIGH = 32768` (gate passed) or `BD_HIGH = 16384` (fallback). Tasks 2–6 read this constant from the ledger note.

**Why first:** the owner's experience is that 32768 has never worked in JSFX. Everything downstream is wasted if it cannot work. The spec's §8 hypothesis is that the real requirement is *exact page alignment* (a 32768-point complex FFT spans 65536 words = one full page), which naive code violates silently.

- [ ] **Step 1: Write the gate test JSFX**

Write to the scratchpad (a REAPER Effects deploy target, never committed). Note: no scientific literals anywhere.

```eel
desc: fft32768 gate test (V0.7) - delta -> fft -> ifft round trip at 32768

@init

// buf starts at 0 => page-aligned by construction (a 32768-pt complex FFT spans
// 65536 words = exactly one 65536 page, so it MUST start on a page boundary).
buf = 0;
N = 32768;

// unit delta
i = 0; loop(N, buf[i*2] = i == 0 ? 1 : 0; buf[i*2+1] = 0; i += 1;);

// forward FFT: |spectrum| of a unit delta must be 1.0 in EVERY bin
fft(buf, N); fft_permute(buf, N);
mn = 1000000000; mx = -1000000000;
i = 0;
loop(N,
  m = sqrt(buf[i*2]*buf[i*2] + buf[i*2+1]*buf[i*2+1]);
  m < mn ? mn = m; m > mx ? mx = m;
  i += 1;
);

// round trip: ifft is unnormalised, so divide by N to recover the delta
fft_ipermute(buf, N); ifft(buf, N);
rterr = 0;
i = 0;
loop(N,
  e = abs(buf[i*2] / N - (i == 0 ? 1 : 0));
  e > rterr ? rterr = e;
  i += 1;
);

// second probe: a DELIBERATELY misaligned base (32768 = half a page) to see whether
// misalignment is what breaks 32768 (diagnostic only; informative either way).
buf2 = 32768;
i = 0; loop(N, buf2[i*2] = i == 0 ? 1 : 0; buf2[i*2+1] = 0; i += 1;);
fft(buf2, N); fft_permute(buf2, N);
mn2 = 1000000000; mx2 = -1000000000;
i = 0;
loop(N,
  m = sqrt(buf2[i*2]*buf2[i*2] + buf2[i*2+1]*buf2[i*2+1]);
  m < mn2 ? mn2 = m; m > mx2 ? mx2 = m;
  i += 1;
);

@gfx 560 200

gfx_setfont(1, "Arial", 15);
gfx_set(1, 1, 1, 1);
gfx_x = 10; gfx_y = 10;  gfx_drawstr("fft(32768) GATE - aligned base (offset 0)");
gfx_x = 10; gfx_y = 34;  gfx_drawstr("|X[k]| min = "); gfx_drawnumber(mn, 9);
gfx_x = 10; gfx_y = 54;  gfx_drawstr("|X[k]| max = "); gfx_drawnumber(mx, 9);
gfx_x = 10; gfx_y = 74;  gfx_drawstr("round-trip max err = "); gfx_drawnumber(rterr, 12);
gfx_x = 10; gfx_y = 98;  gfx_drawstr("PASS if min=max=1.000000000 and err ~ 0");
gfx_set(0.7, 0.8, 1, 1);
gfx_x = 10; gfx_y = 130; gfx_drawstr("diagnostic - MISALIGNED base (offset 32768)");
gfx_x = 10; gfx_y = 150; gfx_drawstr("|X[k]| min = "); gfx_drawnumber(mn2, 9);
gfx_x = 10; gfx_y = 170; gfx_drawstr("|X[k]| max = "); gfx_drawnumber(mx2, 9);
```

- [ ] **Step 2: Deploy it**

```bash
cp "<scratchpad>/fft32768_gate.jsfx" "$HOME/Library/Application Support/REAPER/Effects/fft32768_gate"
```

- [ ] **Step 3: Run it live with the owner and read the numbers**

Ask the owner to add **fft32768_gate** to any track and open its UI. Record what it shows:
- **PASS** = aligned probe shows `|X[k]| min = max = 1.000000000` and `round-trip max err` ≈ 0 (below ~0.000001).
- **FAIL** = min/max differ from 1, or the round-trip error is large, or REAPER reports a compile/runtime error.
- Also record the misaligned diagnostic (mn2/mx2): if aligned passes and misaligned fails, the spec §8 hypothesis is confirmed.

- [ ] **Step 4: Record the decision**

Append to `.superpowers/sdd/progress.md` (create the V0.7 phase header if absent) one line stating the gate result and the resulting constant:
- gate PASS → `BD_HIGH = 32768`
- gate FAIL → `BD_HIGH = 16384` (fallback; geometry `KMAX=8, lat=10240, dry=16384`, used span `360448`; all later tasks substitute these numbers, and the packed tops become Normal+High `589824`, High+High `720896`)

Then remove the deployed gate test:

```bash
rm "$HOME/Library/Application Support/REAPER/Effects/fft32768_gate"
```

- [ ] **Step 5: No commit** (the gate test is scratch, deliberately not committed — only its result is recorded)

---

## Task 2: Oracle — per-BD dry ring + packed two-engine layout

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (in-place edit of `lp_engine_buffers`; append `lp_packed_layouts`)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: existing `page_layout(base, BD, P) -> dict`, `page_layout_ok(layout, BD, P) -> bool`, `lp_engine_buffers(BD, P) -> list[(name, size, fft_touched)]`.
- Produces:
  - `lp_engine_buffers(BD, P)` — unchanged signature; `dryA`/`dryB` now `32768` when `BD >= 32768`, else `16384`.
  - `lp_packed_layouts(base, BD0, BD1, P) -> (layout0, layout1)` — engine 1 packed immediately after engine 0's used span; each layout is a `page_layout` dict (so `layout1["__top"]` is the overall top).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_dsp.py (append)

def test_dry_ring_size_scales_with_BD():
    lo = dict((n, s) for n, s, _ in dsp.lp_engine_buffers(8192, 2048))
    hi = dict((n, s) for n, s, _ in dsp.lp_engine_buffers(32768, 2048))
    assert lo["dryA"] == 16384 and lo["dryB"] == 16384
    assert hi["dryA"] == 32768 and hi["dryB"] == 32768


def test_dry_ring_covers_engine_latency_at_every_resolution():
    # the complementary-dry delay equals the engine latency BD/2 + P; the ring must exceed it
    for BD in (8192, 16384, 32768):
        lat = BD // 2 + 2048
        bufs = dict((n, s) for n, s, _ in dsp.lp_engine_buffers(BD, 2048))
        assert bufs["dryA"] > lat, f"BD={BD}: ring {bufs['dryA']} cannot hold delay {lat}"


def test_used_span_per_resolution():
    span = lambda BD: sum(s for _, s, _ in dsp.lp_engine_buffers(BD, 2048))
    assert span(8192) == 229376
    assert span(16384) == 360448
    assert span(32768) == 655360


def test_packed_normal_pair_matches_v06_footprint():
    l0, l1 = dsp.lp_packed_layouts(0, 8192, 8192, 2048)
    assert l1["__top"] == 458752          # byte-identical to V0.6
    assert dsp.page_layout_ok(l0, 8192, 2048)
    assert dsp.page_layout_ok(l1, 8192, 2048)


def test_packed_layouts_all_four_combinations():
    expect = {(8192, 8192): 458752, (32768, 8192): 884736,
              (8192, 32768): 917504, (32768, 32768): 1310720}
    for (b0, b1), top in expect.items():
        l0, l1 = dsp.lp_packed_layouts(0, b0, b1, 2048)
        assert l1["__top"] == top, f"({b0},{b1}) top {l1['__top']} != {top}"
        assert dsp.page_layout_ok(l0, b0, 2048)
        assert dsp.page_layout_ok(l1, b1, 2048)


def test_hires_desbuf_page_aligned_even_when_engine_base_is_not():
    # engine 1 packed after a Normal engine 0 starts at 229376 (not page-aligned);
    # a High desbuf spans one full page so the layout must push it to 262144.
    l0, l1 = dsp.lp_packed_layouts(0, 8192, 32768, 2048)
    assert l1["desbuf"] % 65536 == 0
    assert l1["desbuf"] == 262144
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "dry_ring or used_span or packed or hires_desbuf" -q`
Expected: FAIL — `dryA` is still 16384 at BD=32768 (`test_dry_ring_size_scales_with_BD`), and `AttributeError: … has no attribute 'lp_packed_layouts'`.

- [ ] **Step 3: Edit `lp_engine_buffers` for the per-BD dry ring**

In `tools/rcbitnova_dsp.py`, inside `lp_engine_buffers`, add the `dry` computation and use it for both dry buffers (replace the two hardcoded `16384` entries for `dryA`/`dryB` **only** — `outA`/`outB` stay 16384, they are unrelated to latency):

```python
def lp_engine_buffers(BD, P):
    """One engine's buffers as (name, size_words, fft_touched). Sizes per spec §11/§5.5.
    Complex buffers count 2 words/item. B=2P, KMAX=BD//P, PB2=B*2. The complementary-dry
    ring must exceed the engine latency BD/2+P, so it scales with BD (16384 is enough for
    BD<=16384; BD=32768 needs 32768 because its latency is 18432)."""
    B = 2 * P; KMAX = BD // P; PB2 = B * 2
    dry = 32768 if BD >= 32768 else 16384
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
        ("outA",   16384, False),          # output FIFO: only needs to exceed the hop P
        ("outB",   16384, False),
        ("dryA",   dry, False),            # complementary-dry ring: must exceed BD/2+P
        ("dryB",   dry, False),
    ]
```

- [ ] **Step 4: Append `lp_packed_layouts`**

```python
def lp_packed_layouts(base, BD0, BD1, P):
    """Both linear engines' layouts with engine 1 packed immediately after engine 0's used
    span (spec §4). Packing is what makes a Normal+Normal pair occupy exactly the V0.6
    footprint, so selecting High costs nothing until it is actually active. page_layout
    aligns each FFT-touched buffer inside a layout, so an engine base that is not itself
    page-aligned is still safe (a High desbuf gets pushed to the next page boundary).
    Returns (layout0, layout1); layout1["__top"] is the overall high-water mark."""
    l0 = page_layout(base, BD0, P)
    l1 = page_layout(l0["__top"], BD1, P)
    return l0, l1
```

- [ ] **Step 5: Run the new tests, then the full suite**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "dry_ring or used_span or packed or hires_desbuf" -q`
Expected: PASS (6 passed).

Run: `python3 -m pytest tests/ -q`
Expected: all previously-green tests still pass (the dry-size change only affects BD≥32768, and every pre-existing test uses BD=8192).

- [ ] **Step 6: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.7 oracle - per-BD dry ring + packed two-engine layout

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Oracle — hi-res benefit via the production builder, sample-rate scope, BD=32768 contracts

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `impulse_fft_kernel(BD, ftype, freq, resonance, nsec, beta, sr)` (the PRODUCTION builder), `build_lp_kernel(...)` (analytic, for contract comparison), `hplp_digital_mag(ftype, freq, resonance, nsec, f, sr)`, `kernel_group_delay(BD)`, and the existing `_kmag(k, f, sr)` DTFT test helper.
- Produces: `_hires_kernel(builder_name, *args)` — a module-level memo so each expensive BD=32768 kernel is built once per test session.

**Note on runtime:** BD=32768 kernels are expensive in pure Python (~2–4 s each). The memo keeps the suite to a handful of builds; expect the suite to grow from ~5 s to roughly 20–40 s. That is an accepted cost for guarding a feature whose failure mode is silent corruption.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_dsp.py (append)

_HIRES_CACHE = {}


def _hires_kernel(builder_name, *args):
    """Memoised kernel build - BD=32768 kernels are expensive in pure Python."""
    key = (builder_name, args)
    if key not in _HIRES_CACHE:
        _HIRES_CACHE[key] = getattr(dsp, builder_name)(*args)
    return _HIRES_CACHE[key]


def test_hires_deepens_the_lowcut_with_the_production_builder():
    # PRODUCTION path is impulse_fft_kernel (spec §6), not build_lp_kernel.
    sr = 96000.0
    k8 = _hires_kernel("impulse_fft_kernel", 8192, "hp", 20.0, 0.0, 8, 14.0, sr)
    k32 = _hires_kernel("impulse_fft_kernel", 32768, "hp", 20.0, 0.0, 8, 14.0, sr)
    d8 = 20 * math.log10(_kmag(k8, 10.0, sr) + 1e-30)
    d32 = 20 * math.log10(_kmag(k32, 10.0, sr) + 1e-30)
    assert d8 - d32 >= 20.0        # measured ~27 dB deeper at 10 Hz


def test_hires_40hz_lowcut_approaches_the_ideal_iir():
    sr = 96000.0
    k32 = _hires_kernel("impulse_fft_kernel", 32768, "hp", 40.0, 0.0, 4, 14.0, sr)
    got = 20 * math.log10(_kmag(k32, 20.0, sr) + 1e-30)
    ideal = 20 * math.log10(dsp.hplp_digital_mag("hp", 40.0, 0.0, 4, 20.0, sr))
    assert got - ideal < 8.0       # measured 6.0 dB from ideal


def test_hires_benefit_is_smaller_at_192k_scope_documented():
    # The deep-cut claim is scoped to <=96 kHz: the benefit scales with BD/srate.
    sr = 192000.0
    k8 = _hires_kernel("impulse_fft_kernel", 8192, "hp", 20.0, 0.0, 8, 14.0, sr)
    k32 = _hires_kernel("impulse_fft_kernel", 32768, "hp", 20.0, 0.0, 8, 14.0, sr)
    d8 = 20 * math.log10(_kmag(k8, 10.0, sr) + 1e-30)
    d32 = 20 * math.log10(_kmag(k32, 10.0, sr) + 1e-30)
    assert d8 - d32 >= 5.0         # still improves (measured ~10 dB)
    assert d32 > -40.0             # but NOT a deep cut at 192k - this is the scope, not a bug


def test_kernel_contracts_hold_at_BD_32768():
    sr = 96000.0; BD = 32768; half = BD // 2
    k = _hires_kernel("build_lp_kernel", BD, "hp", 120.0, 0.6, 4, 14.0, sr)
    kmax = max(abs(v) for v in k)
    asym = max(abs(k[half + d] - k[half - d]) for d in range(1, half)) / kmax
    assert asym < 1e-6                          # symmetric about BD/2
    assert dsp.kernel_group_delay(BD) == 16384   # integer group delay
    for f in [300, 1000, 12000]:                 # passband parity vs analytic magnitude
        got = 20 * math.log10(_kmag(k, f, sr) + 1e-30)
        ana = 20 * math.log10(dsp.hplp_digital_mag("hp", 120.0, 0.6, 4, f, sr))
        assert abs(got - ana) < 0.3


def test_impulse_fft_equals_analytic_at_BD_32768_in_passband():
    sr = 96000.0
    ki = _hires_kernel("impulse_fft_kernel", 32768, "hp", 240.0, 0.6, 2, 14.0, sr)
    ka = _hires_kernel("build_lp_kernel", 32768, "hp", 240.0, 0.6, 2, 14.0, sr)
    for f in [500, 1000, 4000, 12000]:
        gi = 20 * math.log10(_kmag(ki, f, sr) + 1e-30)
        ga = 20 * math.log10(_kmag(ka, f, sr) + 1e-30)
        assert abs(gi - ga) < 0.1
```

- [ ] **Step 2: Run them**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "hires or BD_32768" -q`
Expected: PASS (5 passed). These exercise only existing oracle functions, so there is no RED phase — if any FAILS, the measured premise is wrong: STOP and report the numbers rather than relaxing a threshold.

- [ ] **Step 3: Run the full suite and note the runtime**

Run: `python3 -m pytest tests/ -q`
Expected: all pass. Record the wall-clock time in the report (expected ~20–40 s).

- [ ] **Step 4: Commit**

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.7 oracle - hi-res low-cut benefit (production builder) + 32768 contracts

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Oracle — measured runtime latency per configuration

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `partitioned_convolve(sig, ker, P)` (output lags direct convolution by exactly `P`), `build_lp_kernel(...)`, `_hires_kernel` memo from Task 3.

**Why:** `kernel_group_delay` only checks a helper. This task measures the **actual** impulse-peak position for each configuration, which is what PDC must report: single Normal `6144`, single High `18432`, Normal→High series `24576`, High→High series `36864` (Codex P2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_dsp.py (append)

def _impulse_peak(kernels, P, BDs, pos=100):
    """Feed a unit impulse at `pos` through the given kernels in series via
    partitioned_convolve and return the output index of the peak."""
    need = pos + sum(BD // 2 + P for BD in BDs) + 4 * P
    sig = [0.0] * need
    sig[pos] = 1.0
    out = sig
    for ker in kernels:
        out = dsp.partitioned_convolve(out, ker, P)
    return max(range(len(out)), key=lambda i: abs(out[i]))


def test_runtime_latency_formula_on_a_small_geometry():
    # Cheap structural check of "kernel BD/2 + hop P" with a scaled-down geometry.
    BD, P = 512, 128
    ker = dsp.build_lp_kernel(BD, "hp", 4000.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([ker], P, [BD]) == 100 + BD // 2 + P     # 100 + 384


def test_runtime_latency_single_normal_engine_is_6144():
    ker = _hires_kernel("build_lp_kernel", 8192, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([ker], 2048, [8192]) == 100 + 6144


def test_runtime_latency_single_high_engine_is_18432():
    ker = _hires_kernel("build_lp_kernel", 32768, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([ker], 2048, [32768]) == 100 + 18432


def test_runtime_latency_series_normal_then_high_is_24576():
    k_n = _hires_kernel("build_lp_kernel", 8192, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    k_h = _hires_kernel("build_lp_kernel", 32768, "lp", 8000.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([k_n, k_h], 2048, [8192, 32768]) == 100 + 24576


def test_runtime_latency_series_high_then_high_is_36864():
    k_a = _hires_kernel("build_lp_kernel", 32768, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    k_b = _hires_kernel("build_lp_kernel", 32768, "lp", 8000.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([k_a, k_b], 2048, [32768, 32768]) == 100 + 36864
```

- [ ] **Step 2: Run them**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "runtime_latency" -q`
Expected: PASS (5 passed). No RED phase (existing functions). If a measured peak differs from the asserted value, **STOP and report the actual index** — that means the latency model (and therefore the planned PDC) is wrong, which must be fixed before any JSFX work.

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.7 oracle - measured runtime latency per configuration

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: JSFX — copy V0.6 → V0.7 and refactor to per-engine geometry (behaviour-neutral)

**Files:**
- Create: `JSFX/RCBitNova V0.7` (copy of `JSFX/RCBitNova V0.6`)

**Interfaces:**
- Produces (all in `JSFX/RCBitNova V0.7`): `slider141`/`slider142`; globals `lp_geo`, `lp_off`, `lp_top`; functions `lp_align(p, u)`, `lp_layout(eng, base, BD) -> top`, `lp_relayout(bd0, bd1)`, `lp_win_build(eng)`, `lp_rt_reset(eng)`; `lpk_build`/`lpk_run`/`lpk_process` reading geometry and offsets from those tables.
- **This task must NOT change audio behaviour.** Both engines stay pinned to Normal (BD=8192); the new sliders are declared but not yet wired to geometry (Task 6 does that). Success = V0.7 sounds and measures exactly like V0.6.

**Reference — what V0.6 hardcodes and must become table-driven** (line numbers in `JSFX/RCBitNova V0.6`):
- `298`, `348`, `402`: `eb = lp_base + eng * 229376` (engine stride)
- `299`: `desbuf = eb + 0; ktime = eb + 16384; hspec = eb + 32768; fftw = eb + 131072;`
- `349`–`351`: `hspec/fdlA/fdlB/fftw/yacc/tmpc/inA/inB/outA/outB` offsets
- `402`: `dryA = eb + 196608`
- `409`, `411`: dry-ring wraps at `16384` ← must become the engine's `dryN`
- `356`, `372`, `386`, `387`: **out**-ring wraps at `16384` ← stay 16384 (unrelated to latency)
- `284`: `lpBD = 8192; lpKMAX = 4;` globals ← become per-engine
- `426`, `333`: shared `lp_win` ← becomes per-engine `win_k`
- `433`: `lp_lat` global ← becomes per-engine `lp_geo[eng*4+2]`
- `425`: `memset(lp_base, 0, 458752)` ← becomes a clear of the packed span

- [ ] **Step 1: Copy V0.6 to V0.7 and update the desc line**

```bash
cp "JSFX/RCBitNova V0.6" "JSFX/RCBitNova V0.7"
```

Change the first line to:

```eel
desc: RCBitNova V0.7 - Bit-Accurate M/S Dynamic EQ (static + Mode A + Mode B Soft/Hard cascade + shelf dynamics A+B + proportional-Q bells + min-phase HP/LP + linear-phase HP/LP + FIR Brick + per-filter hi-res linear phase)
```

- [ ] **Step 2: Add the two Resolution sliders**

After `slider140:0<0,1,1{Min,Linear}>Phase` add:

```eel
slider141:0<0,1,1{Normal,High}>HP Resolution (Linear only)
slider142:0<0,1,1{Normal,High}>LP Resolution (Linear only)
```

- [ ] **Step 3: Add the geometry/layout helper functions**

Insert these **before** `lpk_build` (functions must be defined textually before use). Keep `lpP/lpB/lpBD/lpKMAX/lpPB2` line as-is for now; `lpBD`/`lpKMAX` stop being read after Step 4.

```eel
// ---- V0.7: per-engine geometry + page-safe layout tables ----
// lp_geo + eng*4:  0 BD, 1 KMAX, 2 lat (BD/2+P), 3 dryN
// lp_off + eng*16: absolute addresses, inventory order:
//   0 desbuf, 1 ktime, 2 win_k, 3 Hspec, 4 fdlA, 5 fdlB, 6 fftw, 7 yacc, 8 tmpc,
//   9 inA, 10 inB, 11 outA, 12 outB, 13 dryA, 14 dryB
// Mirrors tools/rcbitnova_dsp.py page_layout(): every FFT-touched buffer is aligned to
// min(its span, 65536) so no fft/ifft/convolve_c span ever crosses a 65536-word page.
function lp_align(p, u) local(uu) ( uu = min(u, 65536); ceil(p / uu) * uu; );

function lp_layout(eng, base, BD) local(ob, gb, KM, dry, p) (
  ob = lp_off + eng*16; gb = lp_geo + eng*4;
  KM = BD / lpP; dry = BD >= 32768 ? 32768 : 16384;
  p = base;
  p = lp_align(p, BD*2);   ob[0]  = p; p += BD*2;        // desbuf (FFT, span BD*2)
                           ob[1]  = p; p += BD;          // ktime
                           ob[2]  = p; p += BD;          // win_k
  p = lp_align(p, lpPB2);  ob[3]  = p; p += KM*lpPB2;    // Hspec (per-partition PB2)
  p = lp_align(p, lpPB2);  ob[4]  = p; p += KM*lpPB2;    // fdlA
  p = lp_align(p, lpPB2);  ob[5]  = p; p += KM*lpPB2;    // fdlB
  p = lp_align(p, lpPB2);  ob[6]  = p; p += lpPB2;       // fftw
  p = lp_align(p, lpPB2);  ob[7]  = p; p += lpPB2;       // yacc
  p = lp_align(p, lpPB2);  ob[8]  = p; p += lpPB2;       // tmpc
                           ob[9]  = p; p += lpB;         // inA
                           ob[10] = p; p += lpB;         // inB
                           ob[11] = p; p += 16384;       // outA (FIFO, only needs > P)
                           ob[12] = p; p += 16384;       // outB
                           ob[13] = p; p += dry;         // dryA (must exceed lat)
                           ob[14] = p; p += dry;         // dryB
  gb[0] = BD; gb[1] = KM; gb[2] = BD/2 + lpP; gb[3] = dry;
  p;
);

// Lay out BOTH engines with engine 1 packed right after engine 0, then clear exactly the
// used span (never touch hi-res address space while Normal is active) and hint the top.
function lp_relayout(bd0, bd1) local(t0, t1) (
  t0 = lp_layout(0, lp_base, bd0);
  t1 = lp_layout(1, t0, bd1);
  memset(lp_base, 0, t1 - lp_base);
  lp_top = t1;
  freembuf(lp_top + 1);
);

// Per-engine Kaiser window (beta 14) at that engine's own BD, into its win_k slot.
function lp_win_build(eng) local(ob, BD, wk, iv, nf, i, a) (
  ob = lp_off + eng*16; BD = lp_geo[eng*4]; wk = ob[2];
  iv = 1.0 / lp_i0(14); nf = BD - 1;
  i = 0;
  loop(BD,
    a = 2.0 * i / nf - 1.0; a = max(1.0 - a * a, 0);
    wk[i] = lp_i0(14 * sqrt(a)) * iv;
    i += 1;
  );
);

function lp_rt_reset(eng) local(rt) (
  rt = lp_rt + eng*8;
  rt[0] = 0; rt[1] = 0; rt[2] = 0; rt[3] = lpP; rt[4] = 0; rt[5] = 0;
);
```

- [ ] **Step 4: Make `lpk_build` read geometry + offsets from the tables**

Replace `lpk_build`'s header and buffer-address block. Old (V0.6):

```eel
function lpk_build(eng, ftype, freq, res, nsec, brick)
  local(eb, desbuf, ktime, hspec, fftw, fe, i, kk, n, s, st, c, a1, a2, a3, m0, m1, m2,
        ic1, ic2, v1, v2, v3, f, m, re, im, src, half, inv, k, base) (
  eb = lp_base + eng * 229376;
  desbuf = eb + 0; ktime = eb + 16384; hspec = eb + 32768; fftw = eb + 131072;
```

New:

```eel
function lpk_build(eng, ftype, freq, res, nsec, brick)
  local(ob, BD, KM, wink, desbuf, ktime, hspec, fftw, fe, i, kk, n, s, st, c,
        a1, a2, a3, m0, m1, m2, ic1, ic2, v1, v2, v3, f, m, re, im, src, half, inv, k, base) (
  ob = lp_off + eng*16; BD = lp_geo[eng*4]; KM = lp_geo[eng*4+1];
  desbuf = ob[0]; ktime = ob[1]; wink = ob[2]; hspec = ob[3]; fftw = ob[6];
```

Then, inside the same function body, replace every `lpBD` with `BD`, every `lpKMAX` with `KM`, and the shared window with this engine's:
- `loop(lpBD,` → `loop(BD,` (each occurrence: the brick-magnitude loop, the identity loop, the impulse loop, the magnitude loop, the fftshift loop)
- `kk = i <= lpBD * 0.5 ? i : lpBD - i; f = max(kk * srate / lpBD, 0.001);` → `kk = i <= BD * 0.5 ? i : BD - i; f = max(kk * srate / BD, 0.001);`
- `fft(desbuf, lpBD); fft_permute(desbuf, lpBD);` → `fft(desbuf, BD); fft_permute(desbuf, BD);`
- `fft_ipermute(desbuf, lpBD); ifft(desbuf, lpBD);` → `fft_ipermute(desbuf, BD); ifft(desbuf, BD);`
- `inv = 1.0 / lpBD; half = lpBD * 0.5;` → `inv = 1.0 / BD; half = BD * 0.5;`
- `src = i + half; src >= lpBD ? src -= lpBD;` → `src = i + half; src >= BD ? src -= BD;`
- `ktime[i] = desbuf[src*2] * inv * lp_win[i];` → `ktime[i] = desbuf[src*2] * inv * wink[i];`
- `k = 0; loop(lpKMAX,` → `k = 0; loop(KM,`

- [ ] **Step 5: Make `lpk_run` table-driven**

Replace its header/address block. Old (V0.6):

```eel
function lpk_run(eng, iA, iB)
  local(eb, hspec, fdlA, fdlB, fftw, yacc, tmpc, inA, inB, outA, outB, rt,
        ir, cnt, out_rd, out_wr, fdl_wr, i, si, k, idx, ow, sc) (
  eb = lp_base + eng * 229376;
  hspec = eb + 32768; fdlA = eb + 65536; fdlB = eb + 98304;
  fftw = eb + 131072; yacc = eb + 139264; tmpc = eb + 147456;
  inA = eb + 155648; inB = eb + 159744; outA = eb + 163840; outB = eb + 180224;
  rt = lp_rt + eng * 8;
```

New:

```eel
function lpk_run(eng, iA, iB)
  local(ob, KM, hspec, fdlA, fdlB, fftw, yacc, tmpc, inA, inB, outA, outB, rt,
        ir, cnt, out_rd, out_wr, fdl_wr, i, si, k, idx, ow, sc) (
  ob = lp_off + eng*16; KM = lp_geo[eng*4+1];
  hspec = ob[3]; fdlA = ob[4]; fdlB = ob[5];
  fftw = ob[6]; yacc = ob[7]; tmpc = ob[8];
  inA = ob[9]; inB = ob[10]; outA = ob[11]; outB = ob[12];
  rt = lp_rt + eng * 8;
```

Then inside its body replace `lpKMAX` with `KM` in all four places (`loop(lpKMAX,` twice; `idx < 0 ? idx += lpKMAX;` twice; `fdl_wr >= lpKMAX ? fdl_wr = 0;`). **Leave the four out-ring `16384` wraps unchanged** (lines 356, 372, 386, 387 in V0.6) — the out FIFO only needs to exceed the hop.

- [ ] **Step 6: Make `lpk_process` use the per-engine dry ring and latency (fixes the Codex/Fable P0 for later)**

Replace its address/dry block. Old (V0.6):

```eel
    eb = lp_base + eng * 229376; dryA = eb + 196608; rt = lp_rt + eng * 8;
```
… and …
```eel
    dwp = rt[5]; dryA[dwp] = comp;
    drd = dwp - lp_lat; drd < 0 ? drd += 16384;
    cd = dryA[drd];
    dwp += 1; dwp >= 16384 ? dwp = 0; rt[5] = dwp;
```

New (also add `dryN`, `lat` to the `local(...)` list):

```eel
    dryA = lp_off[eng*16 + 13]; rt = lp_rt + eng * 8;
    lat = lp_geo[eng*4+2]; dryN = lp_geo[eng*4+3];
```
… and …
```eel
    dwp = rt[5]; dryA[dwp] = comp;
    drd = dwp - lat; drd < 0 ? drd += dryN;
    cd = dryA[drd];
    dwp += 1; dwp >= dryN ? dwp = 0; rt[5] = dwp;
```

The full `local(...)` line becomes:

```eel
  local(l, r, mid, sid, act, comp, dryA, rt, dwp, drd, cd, lat, dryN) (
```

- [ ] **Step 7: Replace the `@init` memory setup**

Replace V0.6's setup block (its `lp_rt`/`lp_kc`/`lp_ks`/`lp_base`/`memset`/`lp_win`/window-loop/`lp_lat`/`lp_rt[...]` lines) with:

```eel
// --- V0.7 linear-engine memory: scratch below lp_base, two packed engine layouts above ---
lp_rt  = hplp_cf + 126;   // 16 words runtime state (2 engines * 8): ir,cnt,out_rd,out_wr,fdl_wr,dry_wp
lp_kc  = lp_rt + 16;      // 63 words kernel coeff scratch (<=9 sections * 7)
lp_ks  = lp_kc + 63;      // 18 words kernel state scratch
lp_geo = lp_ks + 18;      // 8 words  (2 engines * 4: BD, KMAX, lat, dryN)
lp_off = lp_geo + 8;      // 32 words (2 engines * 16 buffer addresses)
lp_base = ceil((lp_off + 32) / 65536) * 65536;   // page-align the engine block start
lp_relayout(8192, 8192);                          // V0.7 Task 5: both engines Normal (= V0.6)
lp_win_build(0); lp_win_build(1);
lp_rt_reset(0);  lp_rt_reset(1);
hp_sig_prev = -1; lp_sig_prev = -1; lp_outA = 0; lp_outB = 0;
// FIR ring-out so offline renders keep the linear-phase tail (Task 6 derives this from geometry)
ext_tail_size = 2 * 8192;
```

- [ ] **Step 8: Point the `@slider` PDC at the per-engine latencies**

Replace V0.6's `lin_lat = slider140 == 1 ? 2 * (lpBD / 2 + lpP) : 0;` with:

```eel
lin_lat = slider140 == 1 ? (lp_geo[2] + lp_geo[6]) : 0;   // engine0 lat + engine1 lat
```

(`lp_geo[0*4+2]` = engine 0 latency, `lp_geo[1*4+2]` = engine 1 latency. With both Normal this is `6144+6144 = 12288` — exactly V0.6's value.)

- [ ] **Step 9: Static checks, then deploy**

```bash
python3 -c "
s = open('JSFX/RCBitNova V0.7').read()
assert s.count('(') == s.count(')'), 'paren mismatch'
assert s.count('[') == s.count(']'), 'bracket mismatch'
assert 'lp_win[' not in s, 'shared lp_win still referenced'
assert 'eng * 229376' not in s, 'hardcoded engine stride still present'
# lpBD/lpKMAX must survive ONLY on the constants line (now unused), never inside a function
body = s.split('function lpk_build')[1]
assert 'lpBD' not in body and 'lpKMAX' not in body, 'lpBD/lpKMAX still read inside a function'
assert 'lp_lat' not in body, 'global lp_lat still read inside a function'
print('static checks OK')
"
grep -n "lpBD\|lpKMAX\|lp_lat\b" "JSFX/RCBitNova V0.7"
```
Expected: the paren/bracket/`lp_win`/stride assertions pass. The `grep` should show `lpBD`/`lpKMAX` **only** on the constants line (they are now unused) and no remaining `lp_lat` global reads.

```bash
cp "JSFX/RCBitNova V0.7" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.7"
```

- [ ] **Step 10: Live-verify with the owner that V0.7 == V0.6 (regression gate)**

Ask the owner to check, with both Resolution sliders left at **Normal**:
- V0.7 loads with no compile error.
- `Phase = Min`: HP/LP at 12/24/48/96 behave as in V0.6; FIR Brick in Min is Off.
- `Phase = Linear`, Placement **Both**: same curve as V0.6 (A/B them on the analyzer).
- `Phase = Linear`, Placement **Mid** and **Side**: still clean, no comb (this is the refactored dry-ring path).
- Reported latency in Linear is unchanged from V0.6 (12288 samples + any Mode-B lookahead).
- CPU comparable to V0.6; no crash, no artefacts on silence.

- [ ] **Step 11: Commit**

```bash
git add "JSFX/RCBitNova V0.7"
git commit -m "refactor(rcbitnova): V0.7 JSFX - per-engine geometry/offset tables (behaviour-neutral)

Copy of V0.6 with the linear engines made table-driven: lp_geo (BD/KMAX/lat/dryN) and
lp_off (15 buffer addresses) per engine, lp_layout/lp_relayout mirroring the oracle's
page_layout, per-engine Kaiser window, per-engine dry ring and latency in lpk_process.
Both engines pinned to Normal so behaviour is identical to V0.6. Resolution sliders
141/142 declared but not yet wired (Task 6). Out-ring wraps stay 16384 by design.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: JSFX — enable High (reconcile, PDC, derived tail, rebuild coalescing)

**Files:**
- Modify: `JSFX/RCBitNova V0.7`

**Interfaces:**
- Consumes: everything from Task 5 (`lp_geo`, `lp_off`, `lp_relayout`, `lp_win_build`, `lp_rt_reset`, table-driven `lpk_build`/`lpk_run`/`lpk_process`).
- Produces: `BD_HIGH` constant; selected-vs-active geometry reconciliation; per-engine dirty/rate-limited rebuilds; geometry-derived `pdc_delay` and `ext_tail_size`.

**Use the Task 1 gate result:** `BD_HIGH = 32768` if the gate passed, else `BD_HIGH = 16384`.

- [ ] **Step 1: Add the `BD_HIGH` constant and rebuild-coalescing state to `@init`**

Add next to the other linear-engine `@init` lines (after `lp_rt_reset(1);`):

```eel
// Hi-res geometry. 32768 requires an exactly page-aligned desbuf (lp_layout guarantees it);
// set to 16384 instead if the fft(32768) live gate failed.
BD_HIGH = 32768;
// rebuild coalescing: a BD=32768 rebuild is ~4x a BD=8192 one, so rate-limit to <=1 per
// 100 ms per engine. Dirty state persists, so the final knob position always gets built.
hp_dirty = 1; lp_dirty = 1; hp_built = 0; lp_built = 0; hp_tbuild = 0; lp_tbuild = 0;
```

- [ ] **Step 2: Replace the `@slider` kernel-rebuild signature block with dirty flags + geometry reconcile**

V0.6/Task-5 code to replace (the `hp_sig`/`lp_sig` block that calls `lpk_build` directly in `@block`, plus its `@slider` signature lines). New `@slider` block — put it where the V0.6 `hp_sig`/`lp_sig` lines were:

```eel
// ===== V0.7 linear engines: selected geometry, reconcile, and rebuild signatures =====
// Selected resolution -> BD. While Phase=Min nothing is configured or touched, so choosing
// High in Min costs nothing; the Min->Linear transition is handled by the geometry compare.
sel_bd0 = slider141 == 1 ? BD_HIGH : 8192;
sel_bd1 = slider142 == 1 ? BD_HIGH : 8192;
(slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4])) ? (
  lp_relayout(sel_bd0, sel_bd1);      // re-lays out BOTH engines (engine 1 is packed after 0)
  lp_win_build(0); lp_win_build(1);
  lp_rt_reset(0);  lp_rt_reset(1);
  hp_dirty = 1; lp_dirty = 1; hp_built = 0; lp_built = 0;
);

// Rebuild signature per engine: slope, freq, resonance (placement is routing, not magnitude).
hp_sig = slider131 + slider132 * 100003 + slider133 * 1009;
hp_sig != hp_sig_prev ? ( hp_sig_prev = hp_sig; hp_dirty = 1; );
lp_sig = slider135 + slider136 * 100003 + slider137 * 1009;
lp_sig != lp_sig_prev ? ( lp_sig_prev = lp_sig; lp_dirty = 1; );

// Latency: per-engine BD/2+P, summed over the series chain, only in Linear.
lin_lat = slider140 == 1 ? (lp_geo[2] + lp_geo[6]) : 0;
pdc_delay = slider1 != 1 ? (lin_lat + (any_b ? Lk : 0)) : 0;   // 0 when bypassed
pdc_bot_ch = 0; pdc_top_ch = 2;

// FIR ring-out: last possibly-nonzero output after the final input is
// 2*P + BD_hp + BD_lp - 2 + Lk; add margin. Small value when Linear is off.
ext_tail_size = slider140 == 1 ? (2*lpP + lp_geo[0] + lp_geo[4] + Lk + 64) : 1024;
```

Delete the now-superseded `pdc_delay`/`pdc_bot_ch`/`pdc_top_ch` and `lin_lat` lines from their old position, and the old `ext_tail_size = 2 * 8192;` from `@init`, so each is assigned exactly once.

- [ ] **Step 3: Replace the `@block` rebuild calls with rate-limited ones**

V0.6/Task-5 `@block` had the two direct `lpk_build` calls guarded by `hp_need_rebuild`-style flags. Use:

```eel
@block

// Coalesced, rate-limited kernel rebuilds (a BD=32768 build is heavy; never per sample).
hp_dirty ? (
  (hp_built == 0 || (time_precise() - hp_tbuild) >= 0.1) ? (
    lpk_build(0, 3, slider132, slider133,
      (slider131 == 6 ? 0 : slider131 == 5 ? 8 : slider131), slider131 == 6);
    hp_dirty = 0; hp_built = 1; hp_tbuild = time_precise();
  );
);
lp_dirty ? (
  (lp_built == 0 || (time_precise() - lp_tbuild) >= 0.1) ? (
    lpk_build(1, 4, slider136, slider137,
      (slider135 == 6 ? 0 : slider135 == 5 ? 8 : slider135), slider135 == 6);
    lp_dirty = 0; lp_built = 1; lp_tbuild = time_precise();
  );
);
```

(If V0.6 has no `@block` section, add one immediately before `@sample`.)

- [ ] **Step 4: Static checks, then deploy**

```bash
python3 -c "
s = open('JSFX/RCBitNova V0.7').read()
assert s.count('(') == s.count(')'), 'paren mismatch'
assert s.count('[') == s.count(']'), 'bracket mismatch'
assert s.count('ext_tail_size') == 1, 'ext_tail_size must be assigned exactly once'
assert s.count('pdc_delay =') == 1, 'pdc_delay must be assigned exactly once'
print('static checks OK')
"
grep -n "BD_HIGH\|sel_bd0\|hp_dirty\|time_precise" "JSFX/RCBitNova V0.7" | head -20
cp "JSFX/RCBitNova V0.7" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.7"
```

- [ ] **Step 5: Live-verify hi-res with the owner**

In order (stop at the first failure and report it):
1. **Regression:** both Resolutions = Normal → identical to V0.6/Task 5 (nothing changed).
2. **HP = High, Placement = Both**, HP 20–40 Hz, 48 or 96 dB/oct: the sub-bass is now clearly more attenuated than at Normal; compare against `Phase = Min` (should approach it).
3. **HP = High with Placement = Mid, then Side** — the dry-ring path that a Both-only test cannot exercise. No comb filtering, untouched component still nulls.
4. **Mixed resolutions:** HP = High + LP = Normal, both active in series — no artefacts; reported latency = 18432 + 6144 (+ Mode-B lookahead) = 24576 (+Lk).
5. **CPU:** Normal unchanged; one engine at High acceptable; **High + High** at 44.1 / 48 / 96 / 192 kHz with a small device block — no dropouts.
6. **Rebuild coalescing:** sweep HP Freq and Resonance while playing at High — no dropouts (clicks on the sweep are expected and accepted; the crossfade is deferred).
7. **Memory:** compare REAPER's reported memory for Min, Linear+Normal/Normal, Linear+High/High — Normal/Normal must not be measurably worse than V0.6.
8. **Switching:** Resolution and Phase changes do not crash; PDC updates; **offline render** with High + High keeps the full tail.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V0.7"
git commit -m "feat(rcbitnova): V0.7 JSFX - per-filter hi-res linear phase (High = BD 32768)

Resolution sliders wired to per-engine geometry: selected-vs-active reconcile (nothing
configured or touched while Phase=Min, so High costs nothing until used), packed relayout
of both engines, per-engine window/dry-ring/latency, geometry-derived pdc_delay and
ext_tail_size (High+High needs ~71.7k, not 65536), and coalesced rate-limited kernel
rebuilds (<=1 per 100 ms per engine) since a BD=32768 build is ~4x heavier.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Final review, docs, tag

**Files:**
- Modify: `docs/superpowers/specs/2026-07-25-rcbitnova-v0.7-hires-linear-phase-design.md` (append an as-shipped section)
- Modify: `.superpowers/sdd/progress.md`; memory files `rcbitnova-state.md` + `MEMORY.md`

- [ ] **Step 1: Full oracle regression**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (V0.6's 113 + the V0.7 additions).

- [ ] **Step 2: Dispatch Fable for the final whole-branch code review**

Range `rcbitnova-v0.6..HEAD`. Fable's remit is **error-finding and bit-accuracy verification only** (not coding — the owner's standing decision). Ask it to check: bit-accuracy INTACT (no `log`/`dB`/`pow(10)` in the DSP path; the linear engine has no gain stage); the Min path still byte-identical; page-safety of the table-driven layout at both resolutions and both packing orders; the dry-ring fix actually applied everywhere (the four `16384` sites split correctly into out-ring vs dry-ring); `ext_tail_size`/`pdc_delay` assigned once and correct; reconcile leaves no stale state; EEL2 hazards (no scientific literals, no empty ternary branches).

- [ ] **Step 3: Fix any P0/P1 Fable finds, then re-run the suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Append the as-shipped section to the spec**

Record: the Task 1 gate result and the `BD_HIGH` actually shipped; measured live behaviour; the final memory tops; anything deferred to V0.8 (kernel-rebuild crossfade; lane-B skip optimisation for selective placement; deeper-than-32768 resolution).

- [ ] **Step 5: Tag and push**

```bash
git tag -a rcbitnova-v0.7 -m "V0.7 per-filter hi-res linear-phase HP/LP (High = BD 32768, deep low-cut)"
git push origin rcbitnova rcbitnova-v0.7
```

- [ ] **Step 6: Update the ledger and memory files**

Append the V0.7 outcome to `.superpowers/sdd/progress.md`, and update `rcbitnova-state.md` + its `MEMORY.md` index line (V0.7 shipped, `BD_HIGH` value, deferrals).

---

## Self-Review (spec coverage)

- Spec §1 (goal, measured benefit, ≤96k scope) → Task 3 tests (production builder, 192k scope test).
- Spec §2 (scope; deferred crossfade / lane-B skip / no third menu entry) → Task 6 (no crossfade), Task 7 Step 4 (deferrals recorded).
- Spec §3 (sliders 141/142, defaults, geometry table) → Task 5 Step 2, Task 6 Steps 1–2.
- Spec §3.1 (selected vs active geometry, Min→Linear) → Task 6 Step 2 (geometry compare gated on `slider140 == 1`).
- Spec §4 (CPU model; packed memory; active-span rule) → Task 2 (`lp_packed_layouts` + tests), Task 5 Step 7 (`lp_relayout` clears exactly the used span), Task 6 Step 5.5/5.7 (live CPU + memory).
- Spec §5.1–5.3 (offset table, per-engine geometry, per-engine window) → Task 5 Steps 3–6.
- Spec §5.4 (reconcile procedure) → Task 6 Step 2.
- Spec §5.5 (per-engine dry ring; the four `16384` sites) → Task 2 (oracle sizes) + Task 5 Step 6 (dry) with out-ring left alone (Step 5).
- Spec §5.6 (derived `ext_tail_size`) → Task 6 Step 2.
- Spec §5.7 (rebuild cost, coalescing) → Task 6 Steps 1 and 3.
- Spec §6 (keep the impulse-FFT builder; tests must use it) → Task 3 (all low-frequency tests call `impulse_fft_kernel`).
- Spec §7 (oracle + live verification lists) → Tasks 2–4 (oracle), Task 5 Step 10 and Task 6 Step 5 (live, including the Mid/Side dry-ring path, memory check, and rebuild sweep).
- Spec §8 (fft(32768) gate + fallback) → Task 1, with `BD_HIGH` threaded into Task 6 Step 1.
- Spec §9 (invariants: frozen files, bit-accuracy, oracle) → Global Constraints + Task 7 Step 2.
