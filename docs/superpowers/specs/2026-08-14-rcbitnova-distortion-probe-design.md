# RCBitNova — Distortion & Aliasing Probe

**Date:** 2026-08-14
**Branch:** `rcbitnova`
**New file:** `tools/rcbitnova_probe.py` (the oracle `tools/rcbitnova_dsp.py` is NOT modified)
**Purpose:** answer two questions with numbers instead of listening: *is the plugin clean where
it must be*, and *does it need oversampling*.

---

## 1. Why

RCBitNova has **no oversampling**, and Mode B clips. Harmonics generated above Nyquist therefore
fold back as inharmonic components. Whether that matters at the settings the owner actually uses
has never been measured — the roadmap item "Eco/HQ oversampling" has been an assumption, not a
finding. Meanwhile the parts that are supposed to be linear (SVF bands, HP/LP, the FIR engines,
the power-of-two bit gain) should produce **no** harmonics at all, and nothing currently checks
that.

Doing this in REAPER means hundreds of manual renders. In the Python mirror one configuration
costs **0.02 s** (measured), so a full sweep is seconds.

## 2. Scope

**In:** single-tone THD, aliasing (inharmonic products), two-tone IMD, noise floor — measured
against the oracle's DSP for the static bands, HP/LP (min-phase, linear-phase, FIR Brick),
Mode A, Mode B (soft/hard cascade) and shelf dynamics.

**Out:** comparing against third-party plugins (the oracle cannot model foreign code; that needs
REAPER renders and is a separate exercise); anything about the GUI; changing any DSP. This probe
only *measures*. If it finds a problem, fixing it is a separate spec.

## 3. Method

### 3.1 Tone generation

Frequencies are chosen **inharmonic with respect to the analysis length**: `f = (k + 0.5) * sr/N`
with `k` prime-ish, so a genuine harmonic lands on `k×f` while spectral leakage and folded
products do not coincide with it. This is what makes "everything not on `k×f`" a sound definition
of an aliasing product rather than a guess.

Amplitude is specified in the project's own terms — exact powers of two (e.g. 0.5, 0.25) — so the
input itself introduces no rounding.

### 3.2 Analysis

`lp_fft` from the oracle (no new dependency; the oracle is deliberately pure-stdlib), a
Blackman-Harris window, and peak picking with parabolic interpolation. Transients are excluded by
discarding the first `N` samples so only steady state is analysed — otherwise the attack of a
dynamics stage would be scored as distortion.

### 3.3 Metrics, all in dB relative to the fundamental

| Metric | Definition |
|---|---|
| `thd` | RMS sum of harmonics 2…10 |
| `alias_peak` | largest component that is neither the fundamental nor a harmonic |
| `imd` | for the two-tone case, largest difference/sum product absent from the input |
| `noise_floor` | median of the remaining bins |

## 4. Application (a): hygiene tests, permanent in the suite

Blocks that must be linear are asserted to be at the float64 floor. Thresholds are set from
measurement, not guessed — the first run pins them, and they go into `tests/test_rcbitnova_dsp.py`
so a future change that adds distortion fails the suite.

| Block | Expectation |
|---|---|
| SVF bands (Bell / Low Shelf / High Shelf), static | `thd` below −250 dBFS |
| HP/LP min-phase cascade | below −250 dBFS |
| HP/LP linear-phase, incl. FIR Brick | below −250 dBFS |
| Bit gain (powers of two) | exactly zero — bit-identical, not a threshold |
| Mode A / Mode B with the signal **below threshold** | exactly zero: a silent dynamics stage must be bit-transparent |

The last row is the most valuable: it catches "the dynamics section leaks something even when it
is not working", which no listening test would reliably reveal.

## 5. Application (b): the aliasing sweep

Axes:

- **Tone frequency:** 1 kHz → 0.45·Nyquist, log-spaced.
- **Drive:** from just touching the threshold to ~12 dB of gain reduction.
- **Attack / release:** fast (0 ms / 70 ms — the owner's mastering default) through slow.
- **Sample rate:** 48 kHz and 96 kHz. (96 kHz halves the folding problem by itself; if aliasing
  is only a 48 kHz issue, that is a legitimate answer and cheaper than building oversampling.)
- **Mode:** A and B, soft and hard ceilings.

The owner's mastering defaults (−0.5 dB ceiling, 0 ms attack, 70 ms release, 5 ms window) get
their own labelled row, so the conclusion is about his actual work rather than about the
parameter space in general.

**Output:** `docs/superpowers/reviews/2026-08-14-rcbitnova-distortion-probe.md` — a table plus a
verdict in one sentence: below −100 dB is irrelevant, above −60 dB justifies oversampling, and
the region between is a judgement call to put to the owner with the numbers visible.

## 6. Honest limitation

The oracle mirrors the DSP; it is not the JSFX. Arithmetic agrees (176 tests enforce that), but a
transcription slip in EEL2 would be invisible here — exactly the failure mode of V0.8, whose one
real defect was caught only by the live CPU meter. So the workflow is hybrid: hundreds of runs in
Python, then the two or three worst configurations rendered in REAPER and compared. The probe
proposes where to look; REAPER confirms.

## 7. Success criteria

1. The hygiene tests pass and are in the suite, with thresholds derived from measurement.
2. The sweep produces a report with a defensible one-sentence answer on oversampling.
3. No change to `tools/rcbitnova_dsp.py` and no change to any JSFX file — this spec adds
   measurement only.
