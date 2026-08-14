# RCBitNova — Distortion & Aliasing Measurements

**Date:** 2026-08-14
**Tool:** `tools/rcbitnova_probe.py` (spec: `docs/superpowers/specs/2026-08-14-rcbitnova-distortion-probe-design.md`)
**Method:** coherent sampling (tone at exactly `k·sr/N`, odd `k`), rectangular window, steady
state only. Measurement floor ≈ −285 dB, i.e. float64 arithmetic itself.
**Levels:** dB relative to the fundamental. `−400` means "nothing measurable at all".

---

## Verdict in one sentence

**Mode B needs no oversampling (aliasing −124…−138 dB); Mode A does (aliasing −56…−71 dB and
two-tone IMD −44 dB), and until it exists the practical mitigation is a slower attack** — going
from 0.05 ms to 5 ms buys 9 dB, and to 50 ms buys 21 dB.

This inverts the expectation the roadmap was built on. Mode B *clips*, so it looked like the
oversampling candidate; Mode A is "just an EQ". In fact Mode B's band-split with perfect
reconstruction and window-smoothed gain is almost perfectly clean, while Mode A's fast gain
modulation of a bell is what generates both sidebands and folded products.

## 1. Blocks that must be linear — all clean

Single tone, amplitude 0.5, 48 kHz.

| Block | THD | Aliasing | Sidebands |
|---|---|---|---|
| Bell, unity gain | −284.7 | none | −271.2 |
| Bell, boost ×2 | −286.2 | none | — |
| Low shelf ×0.5 | −283.8 | none | — |
| High shelf ×2 | −283.8 | none | — |
| HP min-phase 100 Hz, 24 dB/oct | −285.0 | none | — |
| LP min-phase 8 kHz, 48 dB/oct | −286.0 | none | — |
| HP linear-phase 100 Hz | −282.3 | none | — |
| FIR Brick LP 15 kHz | −282.1 | none | −274.4 |
| Bit gain, macro −1 | −285.0 | none | — |

Everything sits at the arithmetic floor. No linear block distorts, and the bit gain is exactly a
power of two as designed.

## 2. Dynamics below threshold — bit-transparent

Tone at 0.5 against a ceiling of 0.9, so neither stage should act:

| | THD |
|---|---|
| Mode A | −285.0 |
| Mode B | −285.2 |

A silent dynamics section adds nothing. This is the row most worth keeping as a permanent test:
it would catch "the detector leaks something even when it is not working", which no listening
test reliably reveals.

## 3. Dynamics engaged — where the difference appears

48 kHz, tone amplitude 0.5, attack 0.05 ms, release 70 ms. Band frequency tracks the tone.

| Tone | Mode | Ceiling | THD | **Aliasing** | Sidebands |
|---|---|---|---|---|---|
| 1 kHz | A | 0.250 | −54.3 | none | −67.1 |
| 1 kHz | A | 0.125 | −44.8 | none | −70.4 |
| 1 kHz | B | 0.250 | −132.4 | none | −91.6 |
| 5 kHz | A | 0.125 | −58.9 | **−55.9** | −71.7 |
| 5 kHz | B | 0.125 | −141.5 | −129.6 | −87.0 |
| 11 kHz | A | 0.125 | −133.7 | **−61.2** | −71.2 |
| 11 kHz | B | 0.125 | −144.7 | −125.8 | −87.2 |
| 15 kHz | A | 0.125 | — | **−61.3** | −48.2 |
| 15 kHz | B | 0.125 | — | −133.5 | −87.0 |
| 19 kHz | A | 0.125 | — | **−55.9** | −71.7 |
| 19 kHz | B | 0.125 | — | −124.5 | −87.0 |

Mode A's aliasing is 60–70 dB worse than Mode B's throughout. Deeper action makes it worse:
every doubling of gain reduction costs roughly 6 dB.

## 4. Two-tone intermodulation, 19 + 20 kHz

The harshest ordinary test, and the clearest result:

| | IMD |
|---|---|
| Mode A, ceiling 0.125 | **−43.7 dB** |
| Mode B, ceiling 0.125 | −56.7 dB |
| Bell, unity gain (control) | −234.0 dB |

−43.7 dB is not subtle. Two loud high tones put an intermodulation product 44 dB below them into
the signal — and high-frequency Mode A action is exactly the de-esser use the mode was built for.

## 5. What actually helps

**Attack time** (Mode A, 19 kHz, ceiling 0.125, 48 kHz):

| Attack | Aliasing |
|---|---|
| 0.05 ms | −55.9 |
| 0.2 ms | −59.4 |
| 1 ms | −60.9 |
| 5 ms | −64.7 |
| 20 ms | −71.1 |
| 50 ms | −77.1 |

**Sample rate** (Mode A, ceiling 0.125, attack 0.05 ms):

| Tone | 48 kHz | 96 kHz | Gain |
|---|---|---|---|
| 5 kHz | −55.9 | −71.3 | 15 dB |
| 11 kHz | −61.2 | −64.0 | 3 dB |
| 19 kHz | −55.9 | −60.3 | 4 dB |

Working at 96 kHz helps a lot at mid frequencies and only a little near the top — the products
that fold from a 19 kHz fundamental are still folding at 96 kHz. So a high project rate is not a
substitute for oversampling the detector path.

## 6. Recommendation

1. **Oversampling belongs in Mode A, not Mode B** — the opposite of the roadmap's assumption.
   Scope it to the gain-modulation path rather than the whole plugin.
2. **Until then:** for high-frequency Mode A work (de-essing), an attack of 5 ms or slower keeps
   aliasing below −65 dB. Worth stating in the plugin's own documentation.
3. **Mode B needs nothing.** Its numbers are already at −124 dB and below; oversampling it would
   cost CPU for no audible return.

## 7. Caveats

These are measurements of the **Python mirror**, not of the JSFX. The arithmetic is the same
(176 tests enforce equivalence), but a transcription slip in EEL2 would be invisible here —
precisely the failure mode of V0.8, whose one real defect was caught only by a live CPU meter.
Before acting on point 1, render the Mode A 19 kHz / ceiling 0.125 case in REAPER and confirm the
aliasing figure matches.

Two corrections were made to the probe itself during this run, both recorded because they are the
kind of error that silently produces plausible numbers:

- The first version used a Blackman-Harris window on a deliberately inharmonic tone and reported
  −131 dB THD for a *linear* filter — that was the window's sidelobe floor, not the plugin.
  Coherent sampling with a rectangular window moved the floor to −285 dB.
- The second version lumped folded harmonics together with modulation sidebands, and reported
  identical figures for 5 kHz and 19 kHz — impossible for real aliasing, and the giveaway.
  Harmonics below Nyquist, folded harmonics above it, and near-carrier modulation are now three
  separate metrics.
