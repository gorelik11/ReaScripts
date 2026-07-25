# RCBitNova V0.7 Hi-Resolution Linear-Phase Design Review

**Date:** 2026-07-25  
**Reviewed spec:** `docs/superpowers/specs/2026-07-25-rcbitnova-v0.7-hires-linear-phase-design.md`  
**Reviewed base:** `JSFX/RCBitNova V0.6` at tag `rcbitnova-v0.6`  
**Review type:** DSP, runtime, memory, PDC, render-tail, and verification audit  
**Production files changed:** none

## Verdict

The per-filter Normal/High direction is sound, and the verify-first gate for a
page-aligned 32768 FFT is correct. The spec is not ready for literal
implementation yet: it contains one blocking delayed-dry error, uses the
non-production oracle for its headline attenuation values, and understates
memory, CPU, and render-tail requirements.

## Findings

### P0 - High resolution exceeds the placement dry-ring capacity

The High engine latency is:

```text
BD/2 + P = 32768/2 + 2048 = 18432 samples
```

V0.6 uses a fixed 16384-word complementary dry ring in `lpk_process()`:

```eel
drd = dwp - lp_lat;
drd < 0 ? drd += 16384;
dwp += 1;
dwp >= 16384 ? dwp = 0;
```

For `lp_lat = 18432`, adding 16384 once can leave `drd` negative. Even with
correct modulo, a 16384-sample ring cannot represent an 18432-sample delay.

This affects `Mid`, `Side`, `Left`, and `Right`, where the filtered component is
recombined with delayed dry. `Both` does not use this ring and can appear to
work, which makes the defect easy to miss in an initial smoke test.

**Required change:** make dry-ring capacity per-engine and at least 32768 for
High. Reset its write pointer on geometry changes and use the engine's ring size
for wrapping. The proposed 655360-word slot has enough spare address space to
enlarge the dry buffers.

### P1 - Headline attenuation values use the wrong kernel builder

The spec's table reports the output of analytical `build_lp_kernel()`. Shipping
V0.6 builds its magnitude through `impulse_fft_kernel()`:

1. run an impulse through the actual min-phase cascade;
2. FFT the finite impulse response;
3. take its magnitude;
4. construct the linear-phase FIR from that magnitude.

At 96 kHz, resonance 0, 20 Hz HP, 96 dB/oct, the current Python oracle produces:

| Probe | BD | Analytical builder | Production impulse-FFT |
|---|---:|---:|---:|
| 10 Hz | 8192 | -10.28 dB | -10.35 dB |
| 10 Hz | 32768 | -43.87 dB | **-37.44 dB** |
| 5 Hz | 8192 | -13.10 dB | -12.19 dB |
| 5 Hz | 32768 | -85.74 dB | **-46.53 dB** |

The 40 Hz HP / 48 dB/oct result at 20 Hz does agree:

```text
Production BD=32768: -42.16 dB
Ideal digital IIR:    -48.16 dB
```

High still improves the 20 Hz case, but the claimed -86 dB at 5 Hz overstates
production rejection by about 39 dB.

**Decision required:**

- keep the production impulse-FFT builder and replace the table and acceptance
  values with its real output; or
- use an analytical digital-magnitude builder for High if the deeper stopband is
  a product requirement.

All low-frequency acceptance tests must explicitly exercise
`impulse_fft_kernel()` unless the production builder is deliberately changed.

### P1 - Fixed worst-case slots violate the zero-memory-cost criterion

The oracle layout sizes are:

| Resolution | Per-engine used span |
|---|---:|
| Normal, BD 8192 | 229376 words |
| Fallback, BD 16384 | 360448 words |
| High, BD 32768 | 622592 words |

V0.6 places two Normal engines contiguously and touches 458752 words, which is
approximately 3.5 MiB at eight bytes per word.

The proposed fixed layout places engine 1 at `lp_base + 655360`. With both
engines in Normal, the highest touched address becomes:

```text
655360 + 229376 = 884736 words = approximately 6.75 MiB
```

Not touching the unused part of engine 0's slot does not keep the memory top at
the V0.6 value, because Normal engine 1 is already above that gap.

**Required change:** choose one of:

1. dynamically pack engine 1 immediately after engine 0 and rebuild both layouts
   when either geometry changes;
2. keep both compact Normal layouts below the current memory top and use separate
   alternate High layouts only when High is active;
3. accept and document the approximately doubled Normal footprint, removing the
   zero-cost claim.

Call `freembuf(highest_active_address + 1)` after topology changes if layouts can
shrink. The REAPER documentation describes `freembuf()` as a hint and recommends
using the lowest possible indices.

### P1 - High runtime convolution cost is undercounted by two

The spec says one High engine produces 16 `convolve_c` calls per hop. V0.6
processes two lanes:

```text
lane A: KMAX calls
lane B: KMAX calls
```

Therefore:

| Configuration | `convolve_c` calls per hop |
|---|---:|
| One Normal engine | 8 |
| One High engine | 32 |
| Normal + High | 40 |
| High + High | 64 |

Selective placement currently calls `lpk_run(eng, act, 0)` but still computes
lane B, so it does not reduce this count.

At 96 kHz and `P=2048`, there are about 46.9 hops per second. High + High
therefore performs roughly 3000 size-4096 complex convolution calls per second,
in addition to FFT/IFFT and accumulation work.

**Required change:** correct the cost model and live test both High engines at
44.1, 48, 96, and 192 kHz with small audio-device blocks. A one-lane selective
placement optimization may be considered later but is not required for
correctness.

### P1 - `ext_tail_size = 65536` can truncate High + High renders

For two serial partitioned FIR engines, the last potentially nonzero output
sample after the final input is approximately:

```text
2*P + BD_hp + BD_lp - 2 + Mode-B lookahead
```

For High + High:

```text
without Mode B: 4096 + 32768 + 32768 - 2 = 69630
maximum Mode B: 69630 + 2047 = 71677
```

The proposed fixed `ext_tail_size = 65536` is therefore short by 4094 samples
without Mode B and by up to 6141 samples with maximum lookahead.

**Required change:** derive `ext_tail_size` from the active geometry and
lookahead, or use a safe fixed maximum of at least 71677 samples. Set a smaller
value in Min and bypass if the zero-cost policy also applies to render-tail
processing.

### P2 - Verification proves kernel delay, not runtime/PDC correctness

`kernel_group_delay(32768) == 16384` only verifies a helper and the centered FIR
contract. It does not verify:

- the additional `P` samples introduced by partitioned runtime;
- delayed-dry alignment;
- mixed Normal/High serial latency;
- High + High PDC;
- placement nulls;
- output-ring and FDL wrapping;
- the complete render tail.

**Required oracle/live tests:**

1. single Normal engine impulse peak at 6144;
2. single High engine impulse peak at 18432;
3. Normal + High peak at 24576;
4. High + High peak at 36864;
5. all five placements with delayed-dry null tests;
6. Mode B adds `Lk` exactly once;
7. rendered impulse contains the final FIR tail and matches the reported PDC.

### P2 - Resolution lifecycle while Phase is Min is ambiguous

The controls are described as ignored in Min, while resolution changes are
handled in `@slider`.

Two implementations are possible, with different behavior:

- configure High immediately while Min is active, violating the zero-cost
  requirement; or
- defer configuration, in which case entering Linear must force both engines to
  reconcile their active geometry with the current slider values.

**Required change:** distinguish selected resolution from active geometry. While
Min is active, store only the slider choice. On the Min-to-Linear transition,
configure, clear, build, and reset both engines before processing Linear audio.

### P2 - The benefit is not sample-rate invariant

The design evidence covers only 96 kHz. The production impulse-FFT oracle for a
20 Hz HP / 96 dB/oct at 192 kHz gives:

| Probe | Normal BD 8192 | High BD 32768 |
|---|---:|---:|
| 10 Hz | -7.95 dB | -18.34 dB |
| 5 Hz | -8.42 dB | -27.48 dB |

High still improves rejection, but it is not a deep low-cut at 192 kHz.

**Required change:** either state that the headline deep-cut target is scoped to
96 kHz and below, or add explicit 192 kHz acceptance criteria and revise the
design if those criteria are not met.

## What is already correct

- Per-filter resolution is preferable to a global setting for the stated use.
- Keeping `P=2048` makes mixed geometries and PDC arithmetic understandable.
- `pdc_delay = lat_hp + lat_lp + Lk` is the correct series-chain model, provided
  runtime impulse tests confirm each measured latency.
- The page-aware layout is necessary.
- A 32768 complex FFT occupies exactly 65536 JSFX words and must begin on a page
  boundary.
- The verify-first 32768 smoke test is the right implementation gate.
- The documented 16384 fallback is sensible if the live 32768 gate fails.
- Freezing V0.6 and creating a separate V0.7 file is the correct release policy.

## Required spec edits before implementation

1. Enlarge and parameterize the placement dry ring.
2. Replace the low-frequency table with production-builder measurements, or
   explicitly change the production builder.
3. Redesign Normal/High memory placement or withdraw the zero-memory-cost claim.
4. Correct the runtime CPU count from 16 to 32 calls per High engine per hop.
5. Correct `ext_tail_size`.
6. Add measured runtime latency, placement-null, mixed-resolution, and tail tests.
7. Define Min-to-Linear resolution activation.
8. Add sample-rate scope and tests.

## Verification performed during this review

- Existing DSP suite: **113 tests passed**.
- Page-layout calculations:
  - Normal: 229376 words;
  - fallback: 360448 words;
  - High: 622592 words;
  - all current oracle layouts page-safe.
- Fresh analytical and production impulse-FFT comparisons at 96 and 192 kHz.
- Static trace of both convolution lanes, delayed-dry ring arithmetic, serial
  PDC, and V0.6 render-tail handling.

The existing 113 tests validate V0.6. They do not cover the V0.7 defects listed
above.
