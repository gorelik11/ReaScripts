# RCBitNova V1.6 — Spectrum analyser, and the lookahead scan replaced

**Date:** 2026-09-24
**Branch:** `rcbitnova`
**Base:** V1.5 (HP/LP range). **V1.5's live matrix has NOT been run and V1.5 is NOT tagged.**
**Scope:** one display feature and one CPU fix. Neither changes a single audio sample.

---

## 1. Why, and the measurement that started it

Two things were on the table: an analyser, so the plugin stops being checked with someone
else's SPAN, and a Light/HQ quality switch of the kind `RCBitBrickwall V4.0` has. Measuring
first turned both questions into different ones.

Live on a 96 kHz project, RCBitNova alone in the chain, 8 bands in Mode B Split:

| Lookahead | `Lk` (samples @96k) | PDC | FX CPU |
|---|---|---|---|
| 0.1 ms | 10 | 10 | 1.6 % |
| 2 ms | 192 | 192 | 5.0 % |
| 10 ms | 960 | 960 | **22 %** |

The fit is `CPU ≈ 1.4 % + 0.0215 % × Lk`. Everything else in the plugin — eight bands, the
static engine, Mode A, the GUI, the detectors — is the 1.4 % constant. The rest is one loop:

```
worstA = 0; i = 0;
loop(Lk + 1, p = mb_peak[baseA + ((wp - i + MAX_LOOK) % MAX_LOOK)]; p > worstA ? worstA = p; i += 1;);
```

A full rescan of the lookahead window, **per sample, per lane, per band**, with a modulo in the
inner loop. At 2 ms it is 72 % of the plugin; at 10 ms it is 94 %.

That loop is precisely `RCBitBrickwall V4.0`'s **HQ** mode ("full lookahead scan: finds worst peak
in the entire window"). Nova has no Light option — the HQ path is the only path, and it is always
on. So the Light/HQ question is not "should Nova get a Light mode" but "why is HQ O(Lk)". It does
not have to be: a sliding-window maximum returns **the same** worst peak in amortised O(1).

**Therefore: no quality switch in V1.6.** Degrading the detector to save CPU makes no sense once
HQ is cheaper than Light would have been. What Nova genuinely lacks — oversampled peak detection,
and oversampling of Mode A's gain-modulation path (measured 2026-08-14: aliasing −56…−71 dB,
two-tone IMD −43.7 dB) — is a quality upgrade and belongs to a later version, not a CPU trade.

## 2. Prior art, and what it settles

Four references were examined on this machine.

- **ReEQ** and **ReSpectrum** (ReJJ) import the same `spectrum.jsfx-inc` (964 lines, LGPL,
  © 2018 Justin Johnson); Tukan's S2GFX imports it too.
- **SaikeMultiSpectralAnalyzer MK2** (LGPL, Joep Vanlier + Cockos) — a standalone instrument,
  FFT up to 32768, 16 channels, sonogram. Too large to embed.
- **EQall** (mrelwood) contains no analyser at all — its `import()` is preset loading.
- **artur_linear_faze_eq** is not an analyser but a linear-phase kernel builder (IIR impulse →
  FFT → magnitude → IFFT → Kaiser), the same construction Nova has had since V0.6.
- **`Fable Eq Mix`** — the owner's own line (`Artur Mix bit eq` → `Fable Eq Mix`). It already
  contains **both** features this version is about, working.

All of them share one structural decision, and it is the important one:

```
@sample:  ring write only           — a handful of stores per sample
@gfx:     window + FFT + binning + smoothing + drawing
```

**The whole FFT lives in the GUI thread.** The audio thread pays a ring write. This removes the
only real risk in the feature and it is confirmed by four independent plugins.

`Fable Eq Mix` is the source we port from, so `spectrum.jsfx-inc` is not used at all and its LGPL
never enters the question. (Nova is GPL, so LGPL would have been compatible anyway — the reason
to prefer the owner's own code is that it shares Nova's conventions and its bit-based aesthetic.)

One thing from it must NOT be carried over: the comment `FFT_N=8192 // limit EEL2: >8192 = cisza`
is a misdiagnosis. Nova proved in V0.7 that `fft(32768)` works when the buffer is aligned to a
65536-word page — and `an_sc=65536` in that file is itself such an aligned address, which is why
8192 worked there. The real rule is alignment, not size.

## 3. Decisions taken

| Question | Decision |
|---|---|
| Role | **Working display**, not a measuring instrument. No freeze, no deep vertical range. |
| Taps | **IN and OUT both**, as in `Fable Eq Mix` — grey IN behind, green OUT in front. |
| Domain | **A switch: Mid / Side / L+R.** Nova has eight bands with independent placement, so there is no single processed domain to follow. |
| Source | Port from `Fable Eq Mix`. Nothing from `spectrum.jsfx-inc`. |
| Quality switch | **Not in this version.** See §1. |

## 4. Architecture

A self-contained `an_*` section that never writes to the signal.

```
@sample, first line:   iL = spl0; iR = spl1;          // the input, before anything
@sample, last line:    an_on ? (                       // after out_gain and the V0.9 mute
  an_in [an_pos] = <iL,iR      in the selected domain>;
  an_out[an_pos] = <spl0,spl1  in the same domain>;
  an_pos += 1; an_pos >= FFT_N ? an_pos = 0;
);
```

Both rings are written in one place, at the end, so a single index advances both and the two
streams can never drift by a sample. The input is merely *captured* at the top into `iL`/`iR`.

Under bypass (`slider1 == 1`) both taps keep feeding, so the two curves coincide — which is the
honest picture rather than a frozen one.

`FFT_N = 8192`, Hann window built in `@init`. At 96 kHz that is 11.7 Hz per bin.

**Read `an_on` and the domain INLINE.** State that lives only in `@slider` or `@block` is dead
while the transport is stopped; three separate bugs of exactly that shape were fixed in V1.1–V1.4,
and every one of them was reported as "works only after reloading the plugin".

### Drawing

Two independent vertical scales share the existing plot rectangle — the arrangement
`Fable Eq Mix` uses, and it works because the two marks are different shapes, not because the
axes agree:

- **EQ curve** — a line about the centre, ±4 bits. Unchanged; `gc_y_of_bits` already exists.
- **Spectrum** — a fill from the bottom on its own scale, **−20…+2 bits** (−120.4…+12.0 dB)
  across the full height.

(Nova's ±4 bits is ±24.08 dB, which is exactly `Fable Eq Mix`'s `eq_scale = 24`. The two plugins
independently chose the same curve axis.)

Draw order: spectrum → grid → EQ curve → band nodes. The spectrum is always behind, or eight
nodes drown in it.

Ported numerics, with attribution in the header: magnitude scale `4/FFT_N`; ballistics
`mag = max(new, mag * 0.86)` per frame; per-pixel binning — interpolation between bins where they
are denser than pixels, **maximum** across bins where they are not (a mean loses peaks); tilt
referenced to 1 kHz; a 3-tap smoothing pass run twice in pixel space; persistent peak hold.

### Controls — four new parameters

The highest existing slider is **246** (`Panel: open dynamics card`), not 142. REAPER orders
parameters by slider NUMBER, not by position in the file, so a new parameter numbered below an
existing one silently shifts every higher parameter in every saved project.

| # | Parameter | Values |
|---|---|---|
| 247 | Analyzer | Off / On |
| 248 | Analyzer Domain | Mid / Side / L+R |
| 249 | Analyzer Tilt | 0 / 3 / 4.5 dB per octave |
| 250 | Analyzer Peak Hold | Off / On (right-click clears) |

Buttons live in the top bar beside `HP res` / `LP res`, in the same style. **A domain change
clears both rings and both peak arrays** — without it the display mixes two streams for ~85 ms,
a defect the reference plugin hit on 2026-07-25.

## 5. Memory

`lp_base` is 131072 today and the `gc_*` block ends at 84765, leaving 46307 free words — less
than needed.

| Block | Words |
|---|---|
| Hann window `an_w` | 8192 |
| rings `an_in` + `an_out` | 16384 |
| magnitudes `an_mi` + `an_mo` | 8192 |
| peaks `an_pkI` + `an_pkO` | 4096 |
| pixel scratch `an_db` | 2048 |
| *(the three pixel-indexed arrays are sized 2048 = max plot width in PHYSICAL pixels; on a retina display `gfx_w` is already doubled, so the draw loop clamps its pixel count to that bound)* | |
| FFT scratch `an_sc` | 16384 |
| **analyser** | **55296** |
| wedge queues: 16 × 2048 × (value + position) | 65536 |
| **new total** | **120832** (≈ 944 KB) |

The new block starts at the 131072 page boundary and `lp_base` moves two pages up, to 262144.
Every engine address therefore changes. `tools/rcbitnova_layout.py` stays the single source of
truth and the source gate compares the file against it.

Two hard invariants: **`an_sc` (16384 words) must not cross a 65536-word page**, and the engine
block stays page-aligned. A misaligned FFT in this plugin corrupts **silently** — that is the
V0.7 lesson and it is not worth learning twice.

## 6. The lookahead scan, replaced

Ported from `Fable Mix Limiter 2` (in `Fable Eq Mix`, lines 383–402): `dq_push(v, p)` and
`dq_evict(lp)`, a monotonic queue whose values decrease from head to tail, so the head is the
window maximum. Exactly one position leaves the window per sample, so one eviction test suffices.

Two differences from the reference, both material:

1. **One queue there, sixteen here.** Its linked stereo collapses to a single channel; Nova has
   8 bands × 2 lanes, and even in the `linked` branch each lane's maximum is computed separately
   before they are combined. So the queue state becomes arrays indexed by (band, lane) and the
   functions take a queue index. `DQ_CAP = 2048 = MAX_LOOK`; the window can never hold more.
2. **A change of `Lk` REBUILDS the queue from the ring's existing history — it does not clear
   it.** Clearing would run a shortened window for several hundred samples after the knob moves,
   and the null test would stop being an exact zero. This is the one place in the change where
   bit-exactness is easy to lose.

Code form follows the reference's `while(run)` loop rather than a compact ternary. An assignment
inside a nested ternary has already cost this project one silent defect that neither the oracle
nor a review caught — only the live CPU meter did.

## 7. Acceptance

**The headline acceptance is an exact zero, not a tolerance.** Both changes must leave the audio
untouched, and that is directly testable.

1. **Null V1.6 against V1.5**, four runs: analyser Off and On × lookahead 2 ms and 10 ms. All four
   bit-identical. An analyser that nulls proves the tap only reads; a wedge that nulls proves it
   computes the same maximum.
2. **Python oracle for the queue** — sliding maximum against brute force on random signals, and
   specifically **across an `Lk` change mid-stream**, which is the risk identified in §6.
3. **Python oracle for the spectrum** — window, `4/FFT_N` scale, binning, tilt and smoothing
   reimplemented; on a known tone the peak must land on the expected pixel with the expected value
   in bits.
4. **Source gate** — addresses and sizes match the layout tool; no FFT buffer crosses a page; the
   new sliders are ≥ 247 and above every existing number.
5. **Seeded defects** — as in V1.5, each rejected by its own assertion.
6. **CPU table reproduced live**: at 10 ms lookahead ≈ 1.4 %, not 22 %.

**Live matrix** (what no test in this repository can reach):

- The analyser **with the transport stopped**. Three bugs of this project lived exactly there.
- A domain change: buffers must clear, with no ~85 ms of mixed streams.
- Peak-hold reset, by right-click.
- The lookahead knob moved **under playback**: no click.

## 8. Known risks and what is deliberately left out

- **V1.5 is unverified and untagged.** V1.6 builds on it. The live matrix
  (`docs/superpowers/V15-LIVE-MATRIX.md`) should be run and V1.5 tagged before this work starts,
  or a later defect cannot be attributed to a version.
- **Skipping a linear engine whose slope is `Off` is NOT in this version.** In `Phase: Linear`
  both convolution engines run unconditionally and convolve an identity kernel at full cost — but
  measurement put that below 1 %, and it cannot null bit-exactly (the identity kernel carries the
  Kaiser centre gain, ≈ 1 − ε). One change per version; the wedge is worth twenty times more and
  nulls to zero.
- **No oversampling in V1.6.** Mode A's measured aliasing is real and belongs in the next version,
  scoped to the gain-modulation path, together with an inter-sample peak detector for Mode B.
- **FFT stays at 8192.** Higher is legal given the alignment rule, but 11.7 Hz bins at 96 kHz are
  adequate for a working display, and each doubling doubles the per-frame GUI cost.
