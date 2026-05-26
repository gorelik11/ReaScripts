# Multi-Mic Drift Analyzer — Design

**Date:** 2026-05-27
**Status:** Approved for planning
**Language:** Python (core CLI) + thin Lua/Python ReaScript wrapper
**Phase:** 1 of 2 — *measurement only*. Correction (Phase 2) is a separate spec,
written after we see a real `delay(t)` curve from this tool.

## Problem

Two recordings of the **same acoustic source**, captured by **two different
microphones/positions** through **two different audio devices with independent
clocks**. Because the clocks differ, the time offset between the two recordings
is **not constant** — it drifts over the length of the recording, and (per the
user) the drift is **not smooth**: there are likely dropouts / buffer jumps /
unstable-clock steps on long takes.

End goal (set by user): **blend the two as a multi-mic pair** — phase-coherent
summing of two different timbres. That goal demands sample-accurate alignment
across the *entire* length, with no glitches at correction boundaries. A single
static delay (à la Sound Radix Auto-Align) cannot hold alignment as the offset
creeps; hard-cut block re-alignment would glitch when summed.

This is a **different problem** from the existing `Align Track to Reference`
family, which matches *transient onsets between different instruments*. Here the
signal is the same source, so the right primitive is **cross-correlation**, not
onset matching. A separate tool avoids overloading the onset-based UI/logic.

## Why measure first

The user has not yet measured the drift. The correction strategy hinges on its
character:

- mostly **linear** → one smooth variable-rate warp (Approach A);
- **jumpy / discontinuous** → piecewise re-sync with crossfades (Approach B).

So Phase 1 is a **non-destructive analyzer**: it only reads both items and
reports how they diverge. It reads nothing into the project, moves nothing,
resamples nothing. Its output decides A vs B for Phase 2.

## User Decisions (captured)

- **Use case:** multi-mic blend (phase-coherent summing).
- **Source:** different microphones / positions (not a single split mic) → there
  is a real acoustic time-of-flight offset *plus* clock drift; perfect null is
  not expected, but coherent blend is the target.
- **Drift behavior:** long recordings, drift expected to *jump* (dropouts /
  buffer steps / unstable clock) — not assumed linear.
- **Strategy:** measure first, then choose correction approach.
- **Selection unit:** by **track**, not item. Top selected track = reference,
  bottom = target. Rationale: in Phase 2 the audio gets split (15 s blocks in the
  block mode), after which item-level selection is unreadable — so the whole
  workflow keys off tracks.
- **Material:** stereo, full-range field recordings (two Zoom-style recorders at
  a concert from different positions) — effectively finished stereo, not mono
  stems. This shapes the Phase 2 choices (see Phase 2 Preview).
- **Phase 2 modes:** build **both** correction modes (varispeed resample *and*
  the user's 15 s block approach), user-selectable, so they can be A/B'd by ear.
- **Report location:** `<project_dir>/drift_reports/` next to the `.rpp`.

## Architecture

Two layers, so the algorithm is testable independent of REAPER:

1. **Core CLI** (`drift_analyzer.py`): inputs are two WAV paths + parameters;
   outputs PNG + JSON + CSV. No REAPER dependency. This is what synthetic tests
   drive directly.
2. **ReaScript wrapper**: reads the two **selected tracks** — topmost selected
   track = reference (master), the other = target (slave) — resolves the source
   file path(s), take start-offset and length of the recording item(s) on each
   track, then invokes the core CLI via subprocess (the established tempo-script
   pattern: ReaScript → external Python → JSON back). It passes the geometry so
   the core analyzes only the overlapping region. (Assumes one long recording
   item per track, the common Zoom-dump case; if a track holds several items,
   analyze the common time span across whatever items cover it.)

## Input & Parameters

- **Reference / target:** topmost selected **track** = reference, the other
  = target. Mirrors the user's "верхний задающий, нижний принимающий" mental
  model and survives the Phase 2 splitting.
- **Reading audio:** read the source WAVs of each track's recording item
  directly — **incrementally, window by window** (`soundfile` seek), applying
  take start-offset and length to locate the relevant span. Direct file reads
  avoid REAPER round-trip and keep sample accuracy; windowed reads keep memory
  flat regardless of recording length.
- **Parameters (defaults):**
  - `window` = 10 s analysis window, `overlap` = 50 % hop.
  - `band` = 80–5000 Hz correlation band (robustness across different-timbre
    mics; below/above this, mic responses diverge most).
  - `max_delay` = ±200 ms initial search range, **adaptively widened** if the
    correlation peak lands at the search-range edge.
  - **stereo handled natively** (files are stereo). Delay is estimated **per
    channel** (L↔L, R↔R) and combined by confidence — *not* via an L+R mono
    downmix, which can comb-filter/cancel and corrupt the correlation. >2
    channels: estimate per channel, combine the same way.
  - common analysis SR: if the two devices used different nominal sample rates
    (e.g. 44.1 vs 48 kHz), resample both to a common SR *before* measuring, so
    the reported drift is the residual clock drift, not the nominal-SR gap.

## Algorithm

1. Read both signals (all channels) at the common analysis SR; restrict to the
   overlapping span.
2. For each window `t_i`:
   - compute **GCC-PHAT** (generalized cross-correlation with phase transform)
     **per channel** (reference-L↔target-L, reference-R↔target-R, …);
   - each correlation peak gives a delay; refine to **sub-sample** via parabolic
     interpolation around the peak, and record peak sharpness / prominence as a
     per-channel **confidence**;
   - combine the per-channel estimates into one `d_i` (confidence-weighted),
     since the clock drift is identical across channels; keep the combined
     confidence `c_i`.
3. Assemble the curve `(t_i, d_i, c_i)`.
4. Post-process:
   - drop low-confidence windows (silence / low SNR / transient-dominated);
   - fit overall drift **slope** → report ppm and samples/min;
   - report **linearity** (R² of the linear fit) and **total accumulated drift**;
   - detect **discontinuities** (jumps/dropouts) where the curve breaks beyond a
     residual threshold → list each as `(time, jump size)`.

GCC-PHAT is the crux: phase-whitening makes the delay estimate robust when the
two mics have different timbre, where plain cross-correlation smears.

## Output (to `<project_dir>/drift_reports/`)

- **PNG plot** of `delay(t)`: the curve, confidence shading, detected jumps
  marked — so the user *sees* the drift character at a glance.
- **JSON / printed summary:** initial offset (ms + samples), drift rate (ppm +
  samples/min), total drift over the take, linear-fit R², list of detected jumps
  `(time, size)`, confidence statistics.
- **Verdict line:** a plain-language recommendation, e.g. *"drift ≈ X ppm,
  mostly linear, 2 jumps at mm:ss → Approach A"* or *"drift ragged → Approach B"*.
- **CSV** `(t, d, c)` for Phase 2 to consume directly.

File naming is timestamped/derived from the reference source name so repeated
runs do not clobber each other.

## Error Handling & Edge Cases

- **Different nominal SR** → resample to a common SR before measuring.
- **Silence / low SNR window** → confidence threshold; window dropped, not forced.
- **Stereo / multi-channel** → handled natively (per-channel delay, combined by
  confidence); never collapsed to mono for measurement.
- **Different lengths / partial overlap** → analyze only the common span; warn.
- **Peak at search-range edge** → widen `max_delay` adaptively and re-search.
- **Not exactly 2 selected tracks**, or a track with no audio item → clear
  message, abort (wrapper-level validation).

## Test Plan (TDD anchor — synthetic ground truth)

Generate a known-truth pair from one real WAV:

1. Make a "second mic" copy: resample by a **known ppm**, add a **known start
   offset**, insert a **known jump** at a known time, apply a **different EQ**
   (simulate a second mic), add noise.
2. Run the analyzer; assert it recovers slope (ppm), initial offset, and jump
   location/size within tolerance.
3. Edge tests: zero drift; pure linear drift (no jump); a silent passage in the
   middle (confidence drops, curve interpolates/flags rather than spiking);
   different nominal SR inputs.

This validates the measurement objectively before any real material is used.

## Dependencies & Performance

Phase 1 core needs only **`numpy`** (FFT), **`soundfile`** (WAV I/O),
**`matplotlib`** (PNG). **No `madmom`, no neural nets, no `librosa`** —
GCC-PHAT is plain FFT (forward FFT, conjugate-multiply, magnitude-normalize,
inverse FFT). `scipy` is optional convenience, not required for Phase 1.

Performance is not a concern even for a 1-hour concert:

- The analyzer never loads the whole file — it reads 10 s windows incrementally,
  so memory stays flat (~tens of MB) regardless of length.
- A 1-hour stereo take @ 48 kHz ≈ 720 windows; each window FFT is milliseconds →
  total analysis is a few seconds.

Planning step: confirm `numpy`/`soundfile`/`matplotlib` availability in
`python3.11` (`/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`)
or the madmom venv (used only because those libs already live there), and pick
the interpreter the wrapper calls.

## Out of Scope (YAGNI — Phase 1)

- **Any correction** (resampling, time-warping, moving/splitting items). Phase 2.
- Choosing/automating Approach A vs B — Phase 1 only *recommends*.
- Driving any GUI phase-alignment plugin headlessly — not needed; we compute the
  delay ourselves.
- Polarity/all-pass phase rotation between mics — Phase 2 consideration at most.
- A parameter dialog beyond sensible defaults + a small param file if needed.

## Phase 2 Preview (not committed here)

Phase 2 will implement **both** correction modes, user-selectable, so they can be
compared by ear:

- **A — varispeed resample.** Fit the drift curve and resample the target by the
  (time-varying) ratio, crossfading only at genuine jumps. Crucial distinction:
  this is **varispeed resampling, not pitch-preserving time-stretch** — no
  élastique/phase-vocoder "stretch-marker" smearing. Clock drift *is* a
  sample-rate error, so the fix is the exact inverse resample; the pitch change
  at ppm-level drift is sub-thousandth of a cent (inaudible). A high-quality
  sinc/soxr resampler is transparent on full-range stereo.
- **B — block re-sync (user's idea).** Overlapping ~15 s blocks, each shifted by
  its measured delay, crossfaded at the overlaps. Simpler, robust to ragged
  drift; small phase wobble within/between blocks. For two decorrelated room
  perspectives (different Zoom positions) this wobble is often inaudible, which
  is why both modes are worth having.

Both consume Phase 1's per-window delay CSV. Correction is applied **identically
to all channels** (one clock relationship), so the output is a single corrected
**stereo** WAV aligned to the reference, imported as a new take/track (original
untouched), consistent with the `Align Track to Reference` output convention.
Spec'd separately once the drift character is known.
