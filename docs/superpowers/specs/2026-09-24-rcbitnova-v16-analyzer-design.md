# RCBitNova V1.6 — Spectrum analyser, and the lookahead scan replaced

**Date:** 2026-09-24 · **Revision 2** (answers every finding in
`2026-09-24-rcbitnova-v16-analyzer-weaknesses.md`)
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

Two things from it must NOT be carried over:

1. The comment `FFT_N=8192 // limit EEL2: >8192 = cisza` is a misdiagnosis. Nova proved in V0.7
   that `fft(32768)` works when the buffer is aligned to a 65536-word page — and `an_sc=65536`
   in that file is itself such an aligned address, which is why 8192 worked there. The real rule
   is alignment, not size.
2. **No absolute address.** Its `PK_KEEP=160000` would land inside this design's `an_mo` span.
   Every address comes from `tools/rcbitnova_layout.py`.

## 3. Decisions taken

| Question | Decision |
|---|---|
| Role | **Working display**, not a measuring instrument. No freeze, no deep vertical range. |
| Taps | **IN and OUT both**, as in `Fable Eq Mix` — grey IN behind, green OUT in front. |
| Domain | **Mid / Side / Left / Right / M/S** — five scalar modes (see §4.2). |
| Source | Port from `Fable Eq Mix`. Nothing from `spectrum.jsfx-inc`, and no address from either. |
| Quality switch | **Not in this version.** See §1. |

## 4. The analyser

### 4.1 Sections, ownership, and generations

`@sample` and `@gfx` run on different threads and Nova already documents that they can touch
memory at the same time. Ownership is therefore explicit and one-directional:

| Owned by `@sample` | Owned by `@gfx` |
|---|---|
| `an_in`, `an_out` (rings) | `an_mi`, `an_mo` (magnitudes) |
| `an_pos` (single write cursor for both rings) | `an_db` (pixel scratch), `an_pk*` (peaks) |
| `an_gen_seen` (generation it has acted on) | `an_gen` (generation it requests) |

Neither section writes into the other's column. **`@gfx` never clears a ring and `@sample` never
clears a peak array** — the literal Fable port does both and would race.

The protocol has exactly three steps:

1. The GUI writes a control (domain, Analyzer Off→On, sample-rate or `FFT_N` change) and
   **bumps `an_gen`**, then immediately clears its own display state: `an_mi`, `an_mo`, both peak
   arrays, and a `frame_valid` flag.
2. `@sample` compares `an_gen` with `an_gen_seen` inline. On a difference it zeroes both rings,
   sets `an_pos = 0`, starts a `fill_count`, and copies the generation. It does this **from the
   audio thread only**.
3. `@gfx` draws nothing until `fill_count >= FFT_N` — no partial frame is ever displayed. It
   latches `an_pos` and `an_gen_seen` **once** at the top of a frame and uses those two values for
   both transforms; if `an_gen_seen` changed between latch and end of copy, the frame is discarded
   rather than drawn.

A torn read inside one copy remains possible in principle — the writer can lap the reader — and is
accepted: the worst case is one frame containing a splice, replaced 30 ms later. It is a display,
and no acceptance test depends on frame content being sample-exact.

**Transport stopped:** no `@sample` runs, so a domain change publishes a generation, the display
clears and stays empty until audio flows. That is correct and must be stated in the live matrix so
it is not reported as a bug. `an_on` and the domain are read **inline**, never cached in `@slider`
or `@block` — three bugs of exactly that shape were fixed in V1.1–V1.4.

### 4.2 Taps and domains

```
@sample, first line:  iL = spl0; iR = spl1;         // the input, before anything
@sample, last line:   an_on ? (                      // after out_gain and the V0.9 mute
  an_in [an_pos] = D(iL, iR);
  an_out[an_pos] = D(spl0, spl1);
  an_pos += 1; an_pos >= FFT_N ? an_pos = 0;
);
```

One cursor advances both rings, so IN and OUT can never drift by a sample. The input is only
*captured* at the top.

Every mode is **scalar**, which is what keeps the design at one FFT pair:

| Domain | `an_in` gets | `an_out` gets |
|---|---|---|
| Mid | `(iL + iR) * 0.5` | `(spl0 + spl1) * 0.5` |
| Side | `(iL - iR) * 0.5` | `(spl0 - spl1) * 0.5` |
| Left | `iL` | `spl0` |
| Right | `iR` | `spl1` |
| **M/S** | `(spl0 + spl1) * 0.5` — Mid of the **output** | `(spl0 - spl1) * 0.5` — Side of the output |

The fifth mode reuses the same two rings for a different comparison: instead of input against
output it shows **Mid against Side of the output**, which costs no extra memory and no extra
transform. What is traded is the before/after view while it is selected — an acceptable trade,
because this mode answers a different question and is looked at deliberately. See §4.4 for the
red rule it exists for.

`L+R` from revision 1 is deleted. With a single scalar ring it is Mid with a +1 bit offset — a
third name for a second thing. Left and Right replace it: unambiguous, no extra memory, and they
cover the case Mid hides (anti-phase material). A true stereo magnitude would need both channels
carried through the transform and is out of scope.

Under bypass (`slider1 == 1`) both taps keep feeding, so the two curves coincide — the honest
picture rather than a frozen one.

`FFT_N = 8192`, Hann window built in `@init`. At 96 kHz that is 11.7 Hz per bin.

### 4.3 From bins to pixels

`an_px_n` is **one bounded integer**, computed once per frame as `min(gc_pw_physical, 2048)`, and
used by binning, both smoothing passes, the peak update, the peak draw, the fill and the contour.
Those `an_px_n` columns are mapped across the **entire** plot width, never its left prefix: a
window wider than 2048 physical pixels draws a slightly coarser curve, not a blank right side.
V1.5's `gc_pw` is unbounded and Retina doubles it, so this bound is reached in ordinary use.

For a column spanning bins `b0..b1`, the reference's two cases, stated as inequalities so the
prose cannot invert them again:

- **`b1 - b0 <= 1`** (a column covers at most one bin — pixels are denser than bins):
  **interpolate** linearly between the two adjacent bins.
- **`b1 - b0 > 1`** (several bins fall inside one column): take the **maximum** over them, so a
  narrow peak survives. A mean here smooths real peaks away, which is exactly the failure a
  believable-looking display hides.

(Revision 1 stated these the wrong way round.)

Edges:

- **Below bin 1.** Clamp the bin *index* before computing the interpolation fraction, never after.
  At 192 kHz, 20 Hz is bin 0.853, and fraction-then-clamp interpolates the wrong pair.
- **At or above Nyquist.** The axis reaches 24 kHz while Nyquist is 22.05 kHz at 44.1 kHz. Those
  columns render as **floor / no data**. Repeating the last real bin — Fable's terminal clamp —
  would draw content in a region where none can exist, in the very octave this plugin's FIR Brick
  is judged by.

Units. The vertical axis is bits, so the internal path converts once, at the source:

```
mag_bits  = log(mag) / log(2)
tilt_bits = tilt_db / 6.020599913 * (log(f / 1000) / log(2))
```

Ballistics `mag = max(new, mag * 0.86)` per frame; a 3-tap smoothing pass run twice in pixel
space; magnitude scale `4 / FFT_N` — all as in the reference.

### 4.4 Drawing

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

### 4.4.1 The red rule (M/S mode only)

In `M/S` the second curve is Side, and **every column where Side exceeds Mid is drawn red** — a
mono-compatibility warning read straight off the spectrum, at the frequencies where it happens
rather than as one summary number.

| Condition (per column, in bits) | Colour |
|---|---|
| `side <= mid` | normal (green) |
| `side > mid` | warm red |
| `side > mid + 1` | bright red |

Tilt cancels out of the comparison — both curves carry the same tilt — so the rule is tilt-
independent by construction. Two guards keep it from lying:

- **Floor gate.** A column is only eligible when `max(mid, side) >= -16 bits`. Near the display
  floor at −20 bits the two values differ by arithmetic noise, and without this the top of the
  graph flickers red over silence.
- **Hysteresis, per column.** A column turns red at `side > mid + 0.1 bit` and turns back at
  `side < mid - 0.1 bit`. Exact equality is a coin flip at 30 frames per second; this costs one
  `an_ms_state` byte-per-column array and removes the shimmer at the boundary.

The rule is evaluated after both smoothing passes, on the same values that are drawn — never on
raw bins, or the colour and the curve would disagree on screen.

### 4.5 Controls

The highest existing slider is **246** (`Panel: open dynamics card`), not 142. REAPER orders
parameters by slider NUMBER, not by position in the file, so a new parameter numbered below an
existing one silently shifts every higher parameter in every saved project.

| # | Parameter | Values | Default |
|---|---|---|---|
| 247 | Analyzer | Off / On | **Off** |
| 248 | Analyzer Domain | Mid / Side / Left / Right / M/S | **Mid** |
| 249 | Analyzer Tilt | 0 / 3 / 4.5 dB per octave | **4.5** |
| 250 | Analyzer Peak Hold | Off / On | **Off** |

`Off` by default: a new parameter must not change how an existing project looks or performs on
load. Off→On follows §4.1 — generation bump, rings refill, nothing drawn until a full frame.

**Geometry is specified before implementation, not during it.** The top bar already holds five
110-unit slots (two frequency fields, Phase, HP res, LP res) and at the 900×500 reference size
four more of that width do not fit. The four analyser controls therefore occupy a **second row**,
which reduces the plot height by one row unit; `gc_panel_on` / `gc_small` thresholds are
recomputed from that, and in small mode the second row is hidden and the analyser is forced off
on screen (the parameter is untouched). Rectangles, segmented widths and the right-click target
for the peak reset are all pinned in the plan.

**Pointer ownership.** V1.5 computes the top bar's hit owner *before* node hit collection, at
`JSFX/RCBitNova V1.5:2358-2373`, because a top-bar click used to also enable and arm a band node.
The union of every new rectangle joins that early calculation. A control drawn without extending
`gc_topbar_hot` reopens a defect that changes audio from a click on a label.

## 5. Memory

`lp_base` is 131072 today and the `gc_*` block ends at 84765, leaving 46307 free words — less
than needed.

| Block | Words |
|---|---|
| Hann window `an_w` | 8192 |
| rings `an_in` + `an_out` | 16384 |
| magnitudes `an_mi` + `an_mo` | 8192 |
| peaks `an_pkI` + `an_pkO` (2048 columns each) | 4096 |
| pixel scratch `an_db` (stream being drawn) | 2048 |
| pixel scratch `an_db2` (the stream drawn before it, for the red rule) | 2048 |
| red-rule hysteresis state `an_ms_state` (one per column) | 2048 |
| FFT scratch `an_sc` | 16384 |
| analyser metadata: `an_pos`, `an_gen`, `an_gen_seen`, `fill_count`, `frame_valid`, first-load marker | 16 |
| **analyser** | **59408** |
| wedge queues: 16 × `DQ_CAP` 2049 × (value + position) | 65568 |
| queue metadata: 16 × (head, tail, count, lane-valid, pending-`Lk`, last-cursor) | 96 |
| **new total** | **125072** (≈ 977 KB) |

The new block starts at the 131072 page boundary and `lp_base` moves two pages up, to 262144.
Every engine address therefore changes. `tools/rcbitnova_layout.py` stays the single source of
truth; **every span above, metadata included, is declared there** — the gate cannot protect an
object it does not know exists.

Gated invariants: all spans pairwise disjoint; **`an_sc` (16384 words) does not cross a
65536-word page**; the whole new block lies below `lp_base`; the engine block begins at exactly
262144 and stays page-aligned; every clear operation covers exactly its declared span. A
misaligned FFT in this plugin corrupts **silently** — the V0.7 lesson, not worth learning twice.

## 6. The lookahead scan, replaced

Ported from `Fable Mix Limiter 2` (in `Fable Eq Mix`, lines 383–402 and 911–925): `dq_push(v, p)`
and `dq_evict(lp)`, a monotonic queue whose values decrease from head to tail, so the head is the
window maximum.

**The acceptance is bug-for-bug equality with V1.5, not mathematical correctness.** That
distinction decides the whole design, because of what V1.5 actually does:

`mbwpos[b] = (wp + 1) % MAX_LOOK` at `JSFX/RCBitNova V1.5:2230` sits **outside** the `two ?`
block, while lane B's `mb_peak[baseB + wp]` is written only **inside** it (lines 2175-2182). In
Mid, Side, Left or Right the band's cursor keeps advancing while lane B is never written. When the
band returns to `Both`, V1.5's rescan therefore reads **stale values left in the ring from an
earlier rotation** and limits on them. The queue must reproduce that, stale reads included.

(That is a latent defect in V1.5 — a band returning to `Both` can briefly limit against a peak up
to `MAX_LOOK` samples old. It is recorded here and **must not be fixed in V1.6**, because fixing
it breaks the null that proves everything else. It belongs to its own version, with its own
before/after listening test.)

Four contracts follow.

**6.1 Validity is per `(band, lane)`, never global.** Each of the sixteen queues carries its own
valid flag and its own pending-`Lk` flag. A lane that resumes after its cursor advanced without
queue maintenance is invalid and must rebuild.

**6.2 The rebuild replays the exact positions V1.5 would scan,** oldest to newest, using Fable's
form at lines 911-920:

```
head = tail = cnt = 0;
r = Lk; while (r >= 1) ( p = (wp - r + MAX_LOOK) % MAX_LOOK; dq_push(peak[base + p], p); r -= 1; );
```

then the current sample is pushed at `wp` exactly once. Reading `mb_peak` at those positions —
rather than recomputing anything — is what reproduces the stale lane-B values.

**6.3 Eviction order and capacity.** The reference pushes before evicting, so occupancy is
transiently `Lk + 2`. V1.5's window holds `Lk + 1` values, and at the clamp `Lk = MAX_LOOK - 1 =
2047` that transient is **2049** — one past a 2048-slot buffer, which would overwrite its own head
and corrupt the position test. Reached only at 352.8/384 kHz, so every proposed live null could
pass while the defect sat there.

**Decision: keep the reference's push→evict order and set `DQ_CAP = MAX_LOOK + 1 = 2049.`** The
wrap is a comparison (`t >= DQ_CAP ? t = 0`), not a mask, so a non-power-of-two capacity costs
nothing. Every operation asserts `cnt <= DQ_CAP`.

**6.4 A pending `Lk` change stays pending per lane** until that lane next processes a sample.
Consuming it globally would mark a lane clean that never rebuilt. The same applies across band
disable/enable, Mode A↔B, and bypass: where V1.5 freezes and retains ring history, the queue
freezes and retains too; where V1.5 rescans, the queue rebuilds.

Code form follows the reference's `while(run)` loop rather than a compact ternary. An assignment
inside a nested ternary has already cost this project one silent defect that neither the oracle
nor a review caught — only the live CPU meter did.

## 7. Acceptance

**The headline acceptance is an exact zero, not a tolerance**, and the comparator is 64-bit float
with zero tolerance, as in the V1.5 harness.

### 7.1 Steady-state nulls (necessary, not sufficient)

V1.6 against V1.5: analyser Off and On × lookahead 2 ms and 10 ms — four runs, bit-identical.

### 7.2 Transition nulls — the ones that matter

Revision 1 tested only steady states, which is exactly where the §6 risks are invisible. Each of
these is a JSFX-against-JSFX null, run in REAPER, not a Python comparison:

1. Lookahead **automated mid-stream** (2 ms → 10 ms → 2 ms under playback).
2. `Both → Mid → Both` on a band in Mode B, with material in both lanes.
3. A lookahead change **while lane B is inactive**, then a return to `Both`.
4. Mode B off → on; a band disabled → re-enabled.
5. Analyzer On with the **FX window closed** during a render, then open — the closed case never
   runs `@gfx` and is the one a careless harness skips.
6. Maximum capacity: `Lk = 2047` at 384 kHz with strictly decreasing data, equal runs, random
   data, and several ring wraps.

**One seeded defect per transition**, so a test that never reaches its transition cannot pass
decoratively.

### 7.3 Oracles and gates

- **Queue oracle** (Python): sliding maximum against brute force on random signals, equal runs,
  and across an `Lk` change mid-stream — plus the skipped-lane sequence from §6, asserting the
  stale maximum V1.5 produces, not the mathematically clean one.
- **Spectrum oracle** (Python): window, `4/FFT_N`, both binning branches, bit conversion, tilt and
  both smoothing passes. Tones placed **between** sampled pixel positions; assert peak value as
  well as peak column. Sample rates 44.1 / 48 / 96 / 192 / 384 kHz, plus a Retina-wide window, to
  cover the Nyquist and sub-bin-1 edges.
- **Layout gate**: every span in §5 present and disjoint, `an_sc` page-safe, engines at 262144.
- **Manifest gate**: the full expected **176-record V1.5 manifest as an exact prefix**, then
  exactly four records 176..179 with pinned names, defaults, ranges, steps and enum labels. The
  live build reports 180 declared plus the three host parameters at 180..182. "All new sliders are
  above 246" is not sufficient — it passes while an old declaration is edited or dropped. No
  migrator is needed, and the spec says why: the audio-bearing prefix is unchanged and all four
  appended parameters are display-only.
- **Round-trips**: save/reload and automation write/read for all four controls.

### 7.4 CPU acceptance

Pinned conditions: 96 kHz, 512-sample block, 8 bands in Mode B Split, `Phase: Min`, Analyzer On,
peak hold on, FX window **closed** for the audio-thread figure and **open** for the GUI figure,
REAPER Performance Meter FX CPU column, 60 s average.

The invariant being accepted is **the disappearance of the linear `Lk` term**, not one number:
measured at 0.1 / 2 / 10 ms, the three readings must agree within ±0.3 % of each other. The 1.4 %
of §1 is a fit intercept, not a threshold, and machine scheduling moves it.

### 7.5 Live matrix

What no test in this repository can reach:

- The analyser **with the transport stopped** — including a domain change there, which by §4.1
  clears and then waits. It must be documented as expected, not reported as a hang.
- **M/S mode and the red rule**: anti-phase material must turn the affected columns red, and a
  mono source must never show red anywhere, at any level including near-silence.
- Domain switching under playback: no mixed-stream smear.
- Peak-hold reset by right-click; peak behaviour across transport start, sample-rate change and
  Analyzer Off→On (the reset matrix of §8).
- The lookahead knob moved **under playback**: no click.
- Top-bar clicks at 900×500, default, and Retina sizes: no band is enabled or armed by a click on
  an analyser control.

## 8. Lifecycle details

**Peak-hold reset matrix.** Peaks clear on: domain change, right-click, Analyzer Off→On,
sample-rate change, and plot-width change (`an_px_n` changes meaning). Peaks **survive** an
ordinary `@init` caused by transport start, which requires the first-load marker of §5 — REAPER
re-runs `@init` at transport start and resets variables while memory survives. All active peak
columns initialise to an explicit floor, never zero.

**Magnitudes reset together with peaks.** `an_mi`/`an_mo` decay by 0.86 per frame, so clearing
peaks alone lets the previous domain repopulate the display within two frames.

## 9. Known risks and what is deliberately left out

- **V1.5 is unverified and untagged.** V1.6 builds on it. The live matrix
  (`docs/superpowers/V15-LIVE-MATRIX.md`) should be run and V1.5 tagged before this work starts,
  or a later defect cannot be attributed to a version.
- **V1.5's stale lane-B peak is preserved, not fixed** (§6). Recorded as a known latent defect.
- **Skipping a linear engine whose slope is `Off` is NOT in this version.** In `Phase: Linear`
  both convolution engines run unconditionally and convolve an identity kernel at full cost — but
  measurement put that below 1 %, and it cannot null bit-exactly (the identity kernel carries the
  Kaiser centre gain, ≈ 1 − ε). One change per version; the wedge is worth twenty times more and
  nulls to zero.
- **No oversampling in V1.6.** Mode A's measured aliasing is real and belongs in the next version,
  scoped to the gain-modulation path, together with an inter-sample peak detector for Mode B.
- **FFT stays at 8192.** Higher is legal given the alignment rule, but 11.7 Hz bins at 96 kHz are
  adequate for a working display, and each doubling doubles the per-frame GUI cost.
- **A torn frame is accepted** (§4.1). The display may show one spliced frame under a lapping
  writer; no acceptance test depends on frame content.
