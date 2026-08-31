# Freqphaser 1.0 — Five-Band Side-to-Mid Phase Router

**Date:** 2026-08-31

**Status:** Approved conversational design; awaiting review of this written specification

**Target:** `JSFX/Freqphaser 1.0`

**Licence:** GPL v3, matching the RCBitNova and RCBitRangeGain sources whose proven patterns are reused

## 1. Goal

Build a mastering JSFX that rescues stereo information which lives mainly in Side and therefore
becomes weak or disappears in mono. The primary use case is upper-register harmonica in a stereo
master intended for Instagram and phone playback.

Freqphaser divides Side into five user-defined frequency bands. Each band can be phase-rotated and
added to Mid, or moved from Side to Mid. The plugin must make the mono result audible without
unnecessarily collapsing the rest of the stereo image.

This is a new plugin, not a mode added to RCBitNova. It reuses RCBitNova's verified engineering
patterns where they apply: M/S conventions, bit-scale parameter discipline, page-safe JSFX FFT
memory, PDC/tail accounting, click-safe transitions, GUI/DSP memory separation, and oracle-first
verification.

## 2. User-visible controls

### 2.1 Global controls

| Control | Values | Default | Meaning |
|---|---|---:|---|
| Crossover 1 | 20 Hz…20 kHz | 200 Hz | Boundary between bands 1 and 2 |
| Crossover 2 | 20 Hz…20 kHz | 1.5 kHz | Boundary between bands 2 and 3 |
| Crossover 3 | 20 Hz…20 kHz | 7 kHz | Boundary between bands 3 and 4 |
| Crossover 4 | 20 Hz…20 kHz | 10 kHz | Boundary between bands 4 and 5 |
| Slope | 12 / 24 / 48 / 96 dB/oct | 24 dB/oct | Common spectral transition slope |
| Mono Check | Off / On | Off | Outputs the final Mid identically to L and R |

The four crossovers are freely adjustable on a logarithmic frequency scale. Their effective upper
limit is `min(20000, 0.49 * srate)`. They remain ordered and separated by at least one resolvable
FFT bin. Editing one crossover clamps that crossover to its nearest legal value; it does not move
the other three.

There is no Output Trim in version 1.0. Add mode can raise the output peak, and the user remains
responsible for headroom and any downstream limiting.

### 2.2 Per-band controls

Each of the five identical bands has:

| Control | Values | Default | Meaning |
|---|---|---:|---|
| Amount | 0.00…1.00 bit, step 0.05 | 0.00 bit | Side-to-Mid transfer amount |
| Phase | -180°…+180°, step 1° | 0° | Constant phase rotation before Mid injection |
| Mode | Add / Move | Add | Preserve Side, or remove the transferred share from Side |
| Listen | Off / On | Off | Audition this rotated Side band in centered dual mono |

All controls are declared JSFX parameters and remain available to REAPER automation.

### 2.3 Amount scale

The amount is not an ordinary gain control. It follows the zero-origin transfer curve agreed with
the owner and derived from RCBitRangeGain's `2^x - 1` fader principle:

```text
amount = 2^bits - 1
```

Therefore:

| Bits | Transfer coefficient |
|---:|---:|
| 0.00 | 0.000000 |
| 0.05 | 0.035265 |
| 0.25 | 0.189207 |
| 0.50 | 0.414214 |
| 0.75 | 0.681793 |
| 1.00 | 1.000000 |

The GUI may show the corresponding percentage as secondary information, but bits are the stored,
displayed, typed, and automated unit. Values are quantised to exactly 0.05 bit before writing a
parameter.

## 3. Signal model

### 3.1 M/S convention

Freqphaser uses the same convention as RCBitNova:

```text
M = (L + R) / 2
S = (L - R) / 2
L = M + S
R = M - S
```

The input Mid and Side are delayed by the engine's exact measured latency before recombination.

### 3.2 Complementary five-band masks

One FFT analysis of Side produces spectrum `X[k]`. Four monotonic high-side crossover functions
`C1…C4` are evaluated for every positive-frequency bin. Each is 0 below its crossover, 0.5 at the
crossover, and 1 above it. Its asymptotic amplitude slope is the selected 12/24/48/96 dB/oct.

The five non-negative masks are:

```text
w1 = 1 - C1
w2 = C1 - C2
w3 = C2 - C3
w4 = C3 - C4
w5 = C4
```

Because the crossovers are ordered and use the same curve family, `C1 >= C2 >= C3 >= C4` at every
bin. Consequently each `wb >= 0`, and the five masks telescope to exactly one before floating-point
rounding:

```text
w1 + w2 + w3 + w4 + w5 = 1
```

The crossover function is evaluated in stable log-frequency form rather than with an unbounded
power expression. The dB/oct labels describe the far-transition asymptote of these complementary
spectral crossfades; they do not claim to be analogue Butterworth or Linkwitz-Riley filters.

### 3.3 Per-band phase rotation

For each band, positive-frequency bins are multiplied by:

```text
q_b = cos(theta_b) + i * sin(theta_b)
```

Negative-frequency bins receive the conjugate multiplier, preserving a real time-domain signal.
DC and Nyquist use the real `cos(theta_b)` component, which is the real-signal Hilbert-rotation
endpoint convention. Thus 0° is unchanged, ±90° is quadrature rotation, and ±180° is inversion.

This is frequency-independent phase rotation within the active band, in the sense used by a
linear-phase phase rotator; it is not a time delay.

### 3.4 Add and Move equations

For every spectral bin, the Mid-injection spectrum is:

```text
I[k] = sum_b(amount_b * w_b[k] * q_b * X[k])
```

The Side-removal spectrum contains only bands in Move mode and is not phase-rotated:

```text
R[k] = sum_b(is_move_b * amount_b * w_b[k] * X[k])
```

After inverse transforms and latency alignment:

```text
M_out = M_delayed + I_time
S_out = S_delayed - R_time
L_out = M_out + S_out
R_out = M_out - S_out
```

Consequences:

- Add at 0 bit is neutral.
- Add at 1 bit injects a full phase-rotated copy of that weighted Side band into Mid and leaves
  Side unchanged.
- Move at 1 bit removes that weighted band share from Side and injects its phase-rotated copy into
  Mid.
- If every band is Move at 1 bit, the masks' complementary sum removes all Side and transfers it
  to Mid according to the five phase settings.

## 4. FFT engine

### 4.1 Architecture

The engine uses one Side analysis FFT, not five independent filter engines. Per frame it builds:

1. the phase-rotated Mid-injection spectrum `I`;
2. the unrotated Move-removal spectrum `R`;
3. at most one Listen spectrum when auditioning.

Only the spectra required by the current state receive inverse FFTs. A shared analysis avoids a
fivefold FFT cost and makes mask complementarity explicit.

### 4.2 Geometry

- FFT size `N = 32768`.
- Hop `H = 2048`.
- Weighted overlap-add with a matched square-root Hann analysis/synthesis window and explicit
  overlap normalisation.
- Instance-local memory only; no `gmem`.
- Every FFT/ifft buffer is allocated with RCBitNova's page-safe layout rule. A 32768-point complex
  buffer occupies one 65536-word page and must start on a page boundary. Misalignment is treated
  as a hard verification failure because RCBitNova proved that it causes silent corruption.

Latency is deliberately not constrained: this is a mastering plugin. The implementation derives
and reports `pdc_delay` from the actual engine, and an impulse test must prove that the reported
value equals the measured output delay. `ext_tail_size` is derived from the analysis window,
overlap, crossfade, and synthesis tail so an offline render cannot truncate processed audio.

### 4.3 Neutral state

When every Amount is zero and Listen is off, the audible path uses a latency-matched dry delay
rather than an FFT round trip. The input ring continues to receive samples so processing can be
enabled without an uninitialised history window. The neutral output must be sample-identical to
the delayed input.

## 5. Parameter transitions

Every audible configuration change is click-safe:

- crossover frequency;
- slope;
- phase;
- amount;
- Add/Move;
- Listen selection;
- Mono Check.

The engine uses RCBitNova's proven transition discipline: build/compute the pending state without
overwriting the active one, then crossfade the final aligned output over 50 ms. Outside a
transition, the blend is skipped and weights are exact endpoints. If another change arrives during
a fade, the newest target is queued/coalesced; the current fade is never replaced by an instant
snap. Both channels use the same sample-indexed fade coefficient.

The transition state is reset safely on sample-rate changes and fresh loads. A first build snaps
while output is not yet valid rather than fading from uninitialised memory.

## 6. Listen and mono monitoring

- Only one Listen band is active at a time.
- Activating Listen from the custom GUI writes the other four Listen parameters off.
- If host automation presents multiple active Listen parameters simultaneously, the
  lowest-numbered active band wins deterministically.
- Listen outputs the selected Side band after its Phase rotation, at unity audition level,
  identically to L and R. Listen is independent of the band's Amount and Add/Move setting.
- Mono Check outputs final `M_out` identically to L and R.
- Listen has priority when Listen and Mono Check are both active.
- Entering and leaving either monitoring mode uses the same 50 ms transition system.

## 7. Custom GUI

Freqphaser uses a compact custom `@gfx` interface while retaining all parameters in REAPER's host
parameter list.

### 7.1 Layout

- A logarithmic 20 Hz…20 kHz band strip displays five shaded frequency regions and four draggable
  crossover handles.
- Five matching band columns show the current frequency range, Amount knob, Phase knob,
  Add/Move button, and Listen button.
- The global Slope selector and Mono Check sit outside the band columns.
- Phase is a continuous rotary control visually centred at 0°, modelled on the requested PHA-style
  interaction rather than a two-position polarity switch.

### 7.2 Interaction

- Mouse wheel changes Amount by 0.05 bit and Phase by 1°.
- Dragging uses the same declared increments; no hidden continuous values are written.
- Double-click resets Amount or Phase to zero.
- Right-click permits exact numeric entry for crossovers, Amount, and Phase.
- Typed and dragged values are quantised before `slider_automate`.
- GUI writes use explicit named slider assignments; computed slider indices are read-only, matching
  the live-tested RCBitNova restriction.
- GUI scratch memory never overlaps or writes DSP state. The GUI displays committed/active state,
  not a pending state that has not reached audio yet.
- Retina scaling and reduced-window behaviour follow RCBitNova's proven `gfx_ext_retina` pattern.

## 8. Failure handling and limits

- Illegal or crossing crossover values are clamped, never allowed to produce negative band masks.
- Non-finite parameter or DSP values fall back to the last valid parameter snapshot; audio is not
  allowed to propagate NaN/Inf.
- The plugin does not hard-clip and does not promise peak containment. Add mode may exceed 0 dBFS.
- The plugin accepts ordinary stereo input. Mono input has zero Side, so Side-to-Mid processing is
  naturally silent and the delayed mono signal passes unchanged.
- Phase rotation cannot reconstruct source material that has already cancelled before reaching the
  plugin; it operates only on Side information present in its stereo input.

## 9. Verification contract

### 9.1 Offline oracle

A stdlib-only Python oracle mirrors the mask, amount, phase, Add/Move, WOLA, and latency equations.
It runs under an explicit project-safe interpreter and installs no packages into REAPER's Framework
Python.

Required tests:

1. For every slope and sample rate, each mask is non-negative and the five masks sum to one within
   tight floating-point tolerance at every bin.
2. Crossover clamping preserves strict order at the edges and under typed invalid values.
3. Amount control points match `2^bits - 1`, including exact endpoints 0 and 1.
4. Phase control points 0°, ±90°, and ±180° match an analytic/Hilbert reference and preserve real
   output symmetry.
5. Add leaves Side unchanged; Move removes the correct unrotated weighted share.
6. All bands Move at 1 bit removes Side within numerical tolerance.
7. Neutral state is sample-identical to the delayed input.
8. Reported latency equals the measured impulse position.
9. WOLA reconstruction and tail length hold at 44.1, 48, 96, and 192 kHz.
10. A transition ending at 50 ms lands exactly on the target, never snaps, and returns to the
    single steady-state path.
11. Listen exclusivity/priority and Mono Check equations are deterministic.
12. Every FFT-touched span satisfies the 65536-word page rule, especially the 32768 complex
    buffers.

### 9.2 Source gates

Static checks assert:

- no FFT buffer can cross its permitted page;
- no GUI memory range overlaps DSP memory;
- all slider writes are explicit named assignments;
- all Amount writes quantise to 0.05 bit and all Phase writes to 1°;
- `pdc_delay` and `ext_tail_size` are derived rather than unrelated literals;
- no forbidden EEL2 nested-ternary assignment pattern is introduced.

### 9.3 Live REAPER verification

After offline tests pass:

1. Load the real JSFX at 44.1, 48, 96, and 192 kHz; confirm compile, PDC, and offline tail.
2. Run a delayed null test in the all-zero state.
3. Exercise each band independently in Add and Move at 0, 0.5, and 1 bit.
4. Verify 0°, ±90°, and ±180° with stereo tones, noise, and an analyzer.
5. Sweep every crossover and Phase knob, and switch every slope and Add/Move mode during playback;
   require no clicks or zippering.
6. Verify Listen, Mono Check, their priority, automation, exact numeric entry, and preset reload.
7. Measure steady and transition CPU with the REAPER Performance Meter.
8. Test the target harmonica excerpt in stereo, REAPER mono, and a phone-style mono playback path.
   Success means the selected harmonica information remains clearly audible without an unacceptable
   change to unrelated frequency bands.

## 10. Deliverables

- `JSFX/Freqphaser 1.0`
- offline DSP oracle and unit tests
- source/memory gates
- reproducible live-REAPER checklist and recorded results
- short entry in `JSFX/README.md` describing the purpose, controls, latency, and lack of output trim

## 11. Explicitly out of scope for 1.0

- more or fewer than five bands;
- per-band slope values;
- Output Trim, limiter, or automatic gain compensation;
- automatic detection of harmonica or automatic phase selection;
- minimum-phase or low-latency monitoring mode;
- spectrum analyzer or correlation meter;
- processing Mid into Side;
- multichannel audio beyond stereo L/R.
