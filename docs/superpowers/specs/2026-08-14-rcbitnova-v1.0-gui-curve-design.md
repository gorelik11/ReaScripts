# RCBitNova V1.0 — GUI: EQ curve with draggable nodes

**Date:** 2026-08-14 (**rev 5**. Reviews folded in: weakness review of rev 1 (§10), Fable on
rev 2 (§11), weakness review of rev 3 (§12), Fable on rev 4 (§13).)
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V1.0` (copy of V0.9). `rcbitnova-v0.9` remains the fallback tag;
V0.9 and earlier are frozen.
**Scope:** the first GUI stage — a graph of the static response with draggable band nodes.
Spectrum analyser and dynamics display are later stages (§7).

---

## 1. Why

The plugin has **95 sliders** and four bands. Reaching a parameter means hunting through a long
list, which is the "slider-reachability pain" the roadmap has recorded since V0.3. A curve with
draggable nodes fixes the common gestures — set a frequency, set a gain, widen a bell — and shows
what the filters are actually doing.

The owner's priority, asked directly: the curve with draggable nodes first; the analyser can
wait.

## 2. Non-negotiable constraints

- **The GUI cannot change the sound.** `@gfx` never touches the signal path; it reads parameters
  and writes sliders. Bit-accuracy and every live result from V0.9 therefore hold by
  construction. Gate: a null test V0.9 vs V1.0, mouse untouched, must be digital silence.
- **Sliders stay fully usable.** No parameter becomes reachable *only* through the graph. This
  keeps automation working exactly as before and leaves a fallback if the GUI has a bug.
- **`slider_automate()` after every write.** Without it REAPER neither records the change into
  automation nor updates its own display — the classic defect of hand-written JSFX interfaces.
- V0.9 and earlier stay frozen; work happens in a new file.

## 3. The curve — one trace per placement domain

**A single combined trace is mathematically wrong here** (review P0-1). Each block can sit in
Both, Mid, Side, Left or Right, and a selective block is a stereo 2x2 matrix, not a scalar.
Serial blocks in different domains would have to be multiplied as ordered complex matrices;
multiplying their scalar magnitudes applies every filter to every domain and draws boost or cut
that neither output channel has.

**Solution, following ReEQ** (`ReJJ-1.0.11/ReEQ.jsfx`, `draw_filter_response(group, r,g,b)`):
draw **one trace per domain**, each in its own colour, and only when that domain has an enabled
block. Within one domain, multiplying magnitudes is exactly correct.

| Domain | Colour (from ReEQ, kept for familiarity) |
|---|---|
| Both / stereo | white |
| Mid | green 92,190,98 |
| Side | cyan 91,236,252 |
| Left | yellow 240,201,27 |
| Right | red 213,65,66 |

A domain trace includes the **Both** blocks as well as its own, because a Both block genuinely
processes that domain too - so the Mid trace is "what actually happens to a mid signal", not
"what the mid-placed bands do". The white trace is drawn whenever any Both block is enabled.

*Why this is legitimate and not a coincidence:* a Both-placed block applies the **same**
coefficients to L and R. Since M = (L+R)/2 and S = (L-R)/2 are linear combinations, applying an
identical LTI filter to L and R is mathematically identical to applying it to M and S. So a Both
block's scalar magnitude multiplies correctly into every domain trace. Verified against
`@sample` and `lpk_process` in V0.9. (Recorded so a future editor does not "fix" what looks like
an unexplained shortcut.)

**Stated limitation:** when M/S-placed and L/R-placed blocks are used *at the same time*, no set
of per-domain scalar traces describes the true channel response - the stages do not factor. The
traces then read as "what each group does", exactly as ReEQ's do.

**And it must be visible in the GUI, not only in this document** (rev-3 review P1-5). While
incompatible placement families coexist, the affected traces switch to a **dashed** style and the
legend shows a compact "group view" state. Without that, a user reasonably reads the curves as
channel responses — the more so because the whole point of the graph is to show what is heard. A
GUI test covers Both + Mid + Left simultaneously.

### 3.1 Magnitude per block, honestly per mode

Review P0-2 is right that "Linear draws the same as Min" is false in general: the min-phase
magnitude is the kernel's *target*, and the finite Kaiser window changes what is realized -
which is the very reason Resolution exists.

**FIR Brick precedence, pinned by phase** (rev-3 review P0-1). rev 3 said "a Brick slope must
never draw as no filter" — that is wrong under `Phase = Min`, where Brick maps to `nsec = 0` and
the audible response really *is* identity. Enforcing the rev-3 sentence would draw a cutoff that
is not being heard, which is precisely the class of error this spec exists to avoid:

- `act_phase = Min` + Brick → identity, exactly like Off.
- `act_phase = Linear` + Brick → realized `fir_brick_kernel` magnitude.

Both combinations go into the oracle matrix and the live checklist.

| Block / mode | Magnitude source |
|---|---|
| Bands (Bell / Low Shelf / High Shelf) | TPT/ZDF SVF magnitude from `svf_make` coefficients |
| HP/LP, Phase = Min | `hplp_digital_mag` |
| HP/LP, Phase = Linear, ordinary slopes | magnitude of the **actual windowed kernel** at the ACTIVE `BD` (Normal 8192 / High 32768) |
| HP/LP, **Min** + Slope = FIR Brick | **identity** — see below |
| HP/LP, **Linear** + Slope = FIR Brick | magnitude of the realized `fir_brick_kernel` at the active BD |

- **Band gain** is `bit_gain(Macro, Micro, BitRatio)` - the same expression as the audio path.
- **Proportional-Q:** drawn width uses `band_qeff(b)`, the effective Q, not the knob Q.

**This is new computation, not reuse** (Fable P0-2). rev 2 claimed the work "is already
happening" in `lpk_build`; it is not. `lpk_build` computes the magnitude of the min-phase
**target** and then windows in the *time* domain (`ktime[i] = desbuf[...] * inv * wink[i]`); it
never evaluates the frequency response of the windowed kernel.

**Method: one native `fft()` of the windowed kernel — NOT a per-point DTFT** (rev-3 review P0-2).
rev 3 proposed summing a DTFT at 50–100 query points: ~3.3 M interpreted multiply-adds per engine
per rebuild, ~6.6 M for both. The danger there is not average CPU but **peak block time** — one
`@block` can miss its deadline while the average still looks fine — and it runs with the GUI
closed, so V1.0 would regress the audio-only case.

Instead: copy `ktime` into the existing `desbuf` scratch as a complex array, run the **native
`fft(BD)`** already proven at 32768 in V0.7 (same page-alignment rules), take bin magnitudes, and
resample to the display grid. Four details are pinned here rather than left as "obvious", because
this project's failures have all been plausible-looking transcriptions:

- **`fft_permute` is mandatory.** EEL2's `fft()` returns bit-reversed order, and all four
  existing `fft()` calls in V0.9 (lines 446, 459, 496, 533) are immediately followed by
  `fft_permute()`. Omitting it yields a scrambled frequency mapping that still draws a smooth,
  believable curve.
- **Zero the imaginary lane explicitly** for all `BD` entries when copying `ktime` in. The prior
  `ifft` leaves rounding residue there, not exact zeros.
- **Use bins `0..BD/2` only.** `ktime` is real, so `X[BD-k] = conj(X[k])`; the upper half carries
  no independent information.
- **The `fftshift` needs no correction.** `ktime[i] = desbuf[(i + BD/2) mod BD] * inv * wink[i]`
  is a circular shift applied before windowing; a half-period circular shift multiplies the
  spectrum by `(-1)^k`, which `|X[k]|` removes entirely. Stated as a closed argument so a future
  editor does not "fix" a phase artefact that does not exist.

**Buffer lifecycle, verified:** `desbuf` (`ob[0]`, span `BD*2`) is last written by the `ifft` at
line 451 and only read afterwards; `lpk_run` never touches it. It is free once `lpk_build`
finishes, is exactly the right size, and at BD = 32768 is the same page-aligned span V0.7 already
proved safe — this reuses the identical allocation rather than adding one. This is O(N log N) in native code rather than millions of
interpreted operations, and it reuses a buffer that is already there. It also removes the sparse-
grid accuracy problem (rev-3 review P1-2): the FFT grid is dense (BD/2 bins), so a narrow Brick
transition or a resonant knee cannot fall between query points.

**Interpolation, pinned:** linear in **log frequency**, on **magnitudes in bits** (i.e. after the
log), which keeps a steep skirt straight on the drawn axes.

**Where it runs and where it lands** (Fable P0-3). `@gfx` must **never** read `ktime`, `Hspec`,
`fdlA` or `fdlB`: they live above `lp_base`, `@block` rewrites them mid-rebuild, and
`lp_relayout()` clears and `freembuf`s that whole region on any Resolution change — exactly the
hazard §3.3 exists to prevent. Instead **`@block` computes the coarse grid in the same
audio-thread pass, immediately after `lpk_build`/`lpk_commit`, and copies the results into the
protected below-`lp_base` cache.** `@gfx` only reads that cache. This is the one place where the
DSP thread, not `@gfx`, writes curve data — §2's "the GUI only reads parameters and writes
sliders" is scoped to `@gfx` itself and does not cover this transfer.

**Closed form for the bands** (Fable P0-4). The oracle has two magnitude functions and only one
is usable: `svf_magnitude()` brute-forces 32768 IIR samples and measures RMS — infeasible per
frame and too noisy for a numeric gate — while **`svf_response()` evaluates the exact 2x2 complex
state-space at `z = e^{jw}`** and is cheap. `svf_response` is the explicit porting target for the
JSFX. EEL2 has no complex type, so this is a hand-rolled ~15-20 line function, not a one-liner;
ReEQ's `zdf_magnitude` (`ReJJ-1.0.11/svf_filter.jsfx-inc`) confirms the approach is standard in
this plugin family, but its topology differs and does not supply RCBitNova's `m0/m1/m2` mixing —
that algebra must be derived and oracle-tested first.

**Which topology to read — phase-conditional, NOT uniformly `act_*`** (Fable rev-2 P1-1, then
corrected by Fable rev-4 P0).

In **Linear**, a Placement/Phase/Resolution change is deferred: armed at `@slider`, committed at
`@block`, and the hold can run for a second at BD = 32768. Reading the sliders there would draw a
topology that is not playing. So Linear evaluation uses `act_phase`, `act_hp_pl`, `act_lp_pl`,
`lp_geo`.

In **Min**, the opposite is true, and rev 4's blanket rule would have been wrong. Verified in
V0.9: `topo_changed` only fires for a placement change when `slider140 == 1` (line 757), so while
the user stays in Min and moves HP/LP Placement, `act_hp_pl`/`act_lp_pl` are **never updated
after boot** — they are a fossil of whatever existed then. Meanwhile `@sample`'s Min branch calls
`hplp_run(0, hp_nsec, slider134)` with the **raw slider** (line 874), and the state reset at
lines 715–717 is ungated, so Min-phase placement is live and immediate.

Pinned rule:

| `act_phase` | HP/LP placement source for the curve |
|---|---|
| Min (0) | `slider134` / `slider138` — live, never deferred |
| Linear (1) | `act_hp_pl` / `act_lp_pl` |

Live test: with Phase held at Min, flip HP Placement repeatedly and confirm the trace follows
immediately.

### 3.2 Log floor

The curve must become bits: `bits = log(mag)/log(2)`. FIR Brick's target contains **exact
zeros**, and serial cuts underflow, so `log(0)` would produce non-finite coordinates and corrupt
a whole line strip before any clamp (review P1-5). Magnitudes are floored at `1e-7` (-140 dB, far
below the +-4-bit viewport) before the log, and the resulting bit value is clamped before pixel
conversion.

**Scope note:** the project invariant "no `log` in the DSP path" applies to `@sample`. `log` in
`@gfx` is not an audio-path regression, and the bit-accuracy grep gate must be scoped to the DSP
sections so this is not mistaken for one.

### 3.3 Cache, publication and invalidation

**Memory (rev-1 review P1-2).** The cache lives in a **fixed region reserved before `lp_base` is
aligned**, beside `lp_rt`/`lp_geo`/`lp_off`. It must never live relative to `lp_top`:
`lp_relayout()` clears that region and calls `freembuf(lp_top + 1)`, which would free or
overwrite a cache above it — while `@gfx` runs on another thread. `@gfx` never allocates and
never relocates audio memory. Confirmed by Fable against the real layout: a region before
`lp_base` is untouched by the `memset`/`freembuf`, and V0.7's page alignment is unaffected
because `lp_align` re-derives everything from `lp_base` itself.

**Exact inventory** (rev-3 review P1-4) — word counts, not "about 1000":

| Region | Words | Purpose |
|---|---|---|
| `gc_trace[2][5][CURVE_N]` | 2 × 5 × 512 = 5120 | display traces, **double-buffered**, 5 domains |
| `gc_lin[2][2][LIN_N]` | 2 × 2 × 256 = 1024 | realized Linear/Brick magnitudes, per engine, double-buffered |
| `gc_snap[SNAP_N]` | 128 | per-field snapshot for invalidation |
| `gc_meta` | 8 | generation counters, active buffer index, publication flags |
| **Total** | **6280** | |

**It fits, with the numbers rather than a promise** (Fable rev-4 P2-7). Tracing the static chain
from `cf = 0`: `hplp_state = 37932`, `hplp_cf = 38004`, `lp_rt = 38130`, `lp_kc = 38146`,
`lp_ks = 38209`, `lp_geo = 38227`, `lp_off = 38235`, `lp_fs = 38267`, end of region **38275**.
`lp_base = ceil(38275 / 65536) * 65536 = 65536`, leaving **27261 words of padding**. Adding the
6280-word `gc_*` block ends the region at **44555** — still ~21000 words short of the boundary.
**`lp_base` does not move and page alignment is untouched.**

The memory tests still pin `lp_base` before and after, and assert the worst-case `freembuf` size
at High+High exactly — but as a regression guard, not as an open question.

**Publication protocol** (rev-3 review P0-3). Reserving memory does not make an array update
atomic: `@block` can be writing while `@gfx` reads, producing a frame that mixes old and new
bins and draws spikes belonging to neither kernel. So:

1. `@block` fills the **inactive** buffer completely.
2. Only after the final word is written does it publish — write the new generation and flip the
   active index.
3. `@gfx` snapshots (generation, index) **once** at frame start, reads only that buffer, and if
   the publication changed mid-read, keeps the previous frame rather than drawing a mixture.

A stress test rebuilds both kernels continuously while rendering and asserts no non-finite values
and no single-frame discontinuity beyond a pinned bound.

**What this protocol does and does not guarantee** (Fable rev-4 P1-5). It is a seqlock, and it
does catch a second rebuild completing mid-read. It does **not** prevent store-store reordering:
on ARM — which is what this M4 actually is — the generation flip could in principle become
visible before the buffer words, and EEL2 has no memory-barrier primitive to prevent that. This
spec does not know what synchronisation REAPER guarantees between `@gfx` and `@block`, and does
not claim the scheme is sufficient by construction. It is accepted because the **worst case is
scoped**: a one-frame visual glitch in `@gfx`, self-correcting on the next frame, never signal
corruption — `@gfx` writes nothing the audio path reads. Recorded as an accepted unknown rather
than presented as solved.

**Invalidation is two separate things** (rev-3 review P0-4). rev 3 bumped one counter from
`@slider` — but `act_phase`/`act_hp_pl`/`act_lp_pl` change later, in `topo_commit` inside
`@block`, and `@slider` is not guaranteed to run again afterwards. The graph could keep showing
the superseded topology indefinitely. Therefore:

- **`gen_target`** — bumped from `@slider` when any *requested* value changes (per-field
  snapshot comparison, never a weighted arithmetic signature, which can collide and leave a
  stale but plausible curve).
- **`gen_active`** — bumped from wherever *audible* state actually commits: `topo_commit`, a
  successful realized-kernel publication, and any immediate active-state path that bypasses
  `topo_commit`.

Keeping them separate is what stops the GUI presenting a *requested* topology as if it were
committed.

Watched fields for `gen_target`: per band Enable, Type, Freq, Q, Macro, Micro, Bit Ratio,
Placement, Q Character; HP/LP Slope, Freq, Resonance, Placement; **Phase (`slider140`) and both
Resolutions (`slider141`, `slider142`)** — omitted in rev 4 (Fable rev-4 P1-6), although Phase
selects which of §3.1's three magnitude sources applies and Resolution selects which BD grid is
read; and `srate`.

`gen_target` gates recomputation of the cheap analytic curves (bands, Min-phase HP/LP).
`gen_active` gates what the realized Linear/Brick trace is allowed to show.

### 3.4 What the curve represents during a rebuild

rev 3 alternated between "what is heard" and the freshly built target (rev-3 review P1-1). Pinned
choice: **the curve is a TARGET display.** When a Linear kernel is rebuilt, the new magnitude is
published as soon as it exists, so during V0.8's 50 ms crossfade — and inside the 100 ms rebuild
coalescing window — the graph leads the sound.

Why target rather than audible: blending two complex responses by the engine's crossfade progress
would double the cache and the publication logic to chase a 50 ms visual discrepancy that no one
can perceive. The cost is named here rather than left for someone to discover and call a bug.

## 4. Axes

- **X:** logarithmic, 20 Hz – 20 kHz, gridlines at 100 / 1k / 10k with labels.
- **Y:** **in bits**, gridlines on whole bits, range **±4 bits** (= ±24 dB). Macro allows ±16
  bits, but a node parked at 16 bits would make the graph unreadable; values beyond the scale
  are clamped to the edge and labelled with their number so nothing is hidden.

Bits — not dB — because every gain parameter in this plugin is already in bits; the axis is a
direct view of the parameter rather than a conversion.

## 5. Nodes and interaction

One node per band, drawn at (frequency, gain).

| Gesture | Effect |
|---|---|
| Drag horizontally | Frequency |
| Drag vertically | Gain, in **0.05-bit steps** (= 5 % of Micro) |
| Shift + drag | Fine step |
| Mouse wheel on a node | Q |
| Hover + type a digit | Numeric entry: Enter commits, Esc cancels, Backspace deletes |
| Click | Select (the selected node's readouts are shown) |

**Slider map per band `b` (0-based), base `10*(b+1)`** — verified against the file, not assumed:

| Offset | Parameter | Range / step |
|---|---|---|
| +1 | Enable | 0/1 |
| +2 | Type | Bell / Low Shelf / High Shelf |
| +3 | Freq | 20–20000, step 1 |
| +4 | Q | 0.1–10, step 0.001 |
| +5 | Macro (bits) | −16…16, step 1 |
| +6 | Micro (% bit) | −100…100, step 0.1 |
| +7 | Bit Ratio | 0–3, step 0.1 |
| +8 | Placement | Both / Mid / Side / Left / Right |
| +9 | Q Character | 0–1 |

**Y is EFFECTIVE gain, and drag inverts Bit Ratio** (review P0-3, owner's choice). The node is
drawn at `bit_gain(Macro, Micro, BitRatio)`, so for the node to follow the pointer the drag must
solve backwards:

```
base_target = effective_target / BitRatio      (BitRatio != 0)
```

- `BitRatio == 0` has **no inverse**: every Macro/Micro setting sounds at 0 bits. The node is
  pinned at the zero line, drawn in a distinct "locked" style, and vertical drag does nothing.
  A readout says why. Silently resetting Bit Ratio would destroy a setting the owner chose
  deliberately.
- If the inverse exceeds the representable base range, the value **clamps** and the node stops
  following the pointer rather than jumping.
- Division by e.g. 0.3 will not land on the Micro grid; the result is snapped after inversion,
  so the audible step stays a clean multiple of 0.05 bit **of effective gain** only when
  `BitRatio` is 1. Otherwise the snap applies to the base value and the readout shows the true
  effective figure.

**Canonical Macro/Micro split.** Many pairs encode the same gain (`+0.95` bits is
`Macro 0, Micro 95` or `Macro 1, Micro -5`), so one rule is pinned: **truncation toward zero** —
`Macro = int(base)`, `Micro = (base - Macro) * 100`, with Micro **signed**, in `(-100, +100)`.

rev 3 specified `floor` with Micro in `[0,100)`; that silently lost part of the negative range
(rev-3 review P1-3): `-16.5` would need `Macro = -17`, outside the slider's `[-16, +16]`, making
the canonical range an asymmetric `[-16, +17)`. Truncation toward zero keeps the representable
span symmetric at approximately `(-17, +17)` and treats positive and negative identically. The
combined base is clamped to that span **before** splitting.

Round-trip tests cover `-17`, `-16`, `0`, `+16`, `+17` and one Micro step either side of each.

Two slider writes are not atomic (rev-3 review P1-3b). Writing Macro first at a boundary — say
`0.95 → 1.00` — momentarily pairs the new Macro with the old Micro, i.e. `1.95` bits. Whether the
DSP can ever observe that depends on JSFX coalescing both assignments before the next `@slider`,
which is **host behaviour this spec would otherwise be relying on silently**.

rev 4 pinned "Micro first" and claimed the transient is bounded by one bit. **That holds only for
a single Macro-step crossing** (Fable rev-4 P1-3). Measured counter-example: `16.95 → -16.95`
bits, a legitimate numeric entry or fast drag —

| Transition | Micro first | Macro first |
|---|---|---|
| `0.95 → 1.00` (one boundary) | **0.00 bits** | +1.95 bits |
| `16.95 → -16.95` (large jump) | **+15.05 bits** (x33923) | -15.05 bits (x0.000029) |

Neither fixed order is safe in general: Micro-first is perfect for smooth dragging and produces a
34000x bang on a jump; Macro-first is the reverse, erring toward silence.

**Pinned: choose the order per write.** Compute both candidate intermediates —
`bit_gain(old_macro, new_micro)` and `bit_gain(new_macro, old_micro)` — and write the field that
yields the **smaller absolute intermediate gain** first. Two comparisons, no cost, and it always
errs toward silence rather than toward a bang. This is the same failure class as V0.8's
full-amplitude step, which is why it is worth two lines of arithmetic.

**`slider_automate` fires only when the snapped pair actually changed**, so a stationary drag does
not flood automation with identical points.

**Load-bearing and still unverified** (Fable rev-4 P1-4): whether the DSP can observe the
intermediate pair at all depends on JSFX coalescing both writes before the next `@slider`. rev 4
called this "live-tested"; no live test has run yet. It stays on the live checklist as a gate,
not as a formality — with large numeric-entry jumps and fast multi-integer drags, both polarities,
automation recording on.

**Numeric entry targets a named field, not "the node"** (review P1-7). One node carries Freq,
Gain and Q, so "hover and type" is ambiguous. The readout strip at the bottom has three fields —
**F / G / Q** — and clicking one gives it keyboard focus (highlighted border). Typing then edits
that field: digits, minus and dot accumulate, Enter commits, Esc cancels, Backspace deletes.
Units are shown in the field label: Hz, bits, Q. The `gfx_getchar` loop is adapted from
`Fable Eq Dynamic.jsfx` (~lines 2160–2190).

**Drag semantics, pinned:**

| | Behaviour |
|---|---|
| Drag capture | The node grabbed on mouse-down keeps capture until release, even outside the graph |
| Axis lock | None by default; Shift held **at mouse-down** locks to the dominant axis |
| Shift after start | Changes sensitivity to fine (0.01 bit / 1 Hz), does not re-lock the axis |
| Wheel | Up = higher Q (narrower), one step per notch; Ctrl+wheel = fine |
| Overlapping nodes | The topmost by band index wins; a second click within 300 ms cycles through them |
| Release outside window | Treated as a normal release, value kept |
| Esc during drag | Cancels, restoring the value from mouse-down |

**Node colour encodes placement** (Both / Mid / Side / Left / Right). Without it the graph would
imply a band acts on the whole signal when it acts only on the side.

**Disabled bands** draw as dimmed outlines — visible, so a forgotten band is not invisible, but
clearly not contributing.

## 6. Layout and coordinates

Size is declared on the section line — **`@gfx 900 500`** — which is the JSFX contract.
(`gfx_init()` named in rev 1 is the ReaScript gfx API, not JSFX; review P1-8.)

- **Base coordinate space** 900x500 logical units; everything is drawn through one scale factor
  derived from the actual `gfx_w`/`gfx_h`, and **hit-testing uses the same transform** as
  drawing. On Retina, `gfx_ext_retina` must be applied to both or nodes render in one place and
  respond in another.
- **Rectangles:** graph occupies the top area with 40 units of left margin (bit labels) and 24
  bottom (frequency labels); the readout strip is the bottom 60 units.
- **Minimum usable size** 480x280; below it the readout strip is dropped before the graph.
- **Node hit radius** scales with the transform, minimum 8 logical units.
- **Over-range label algorithm** (rev-3 review P2), pinned rather than left to taste: nodes
  clamped to the same edge are ordered by band index; each subsequent label is offset downward
  (top edge) or upward (bottom edge) by one text height; the **selected** node's label always
  draws last, on top, and is never displaced. Labels stay fully inside the plot rectangle —
  clipping them would hide the very number that keeps an out-of-range value visible. Tested with
  identical frequency and identical value, with opposite-edge over-ranges, at minimum width and
  at Retina scale.

Whether REAPER shows its generic slider list below the custom graph or behind a UI toggle is
confirmed **live**, not assumed.

## 7. Explicitly out of scope

Deferred so the first stage stays finishable:

- **Spectrum analyser** → V1.1. Heaviest part in both CPU and code.
- **Live dynamics curve** (Mode A/B action) → V1.2. Needs detector state passed from `@sample`
  to `@gfx`.
  *Forward note for that spec (Fable P2):* a Both-placed band whose dynamics run in Dual M/S
  (`dp[b*4+3] == 1 && dm[b] == 2`) routes even its **static** SVF through M/S rather than L/R.
  The static magnitude is domain-invariant so V1.0 is unaffected, but the *dynamic gain* is not —
  V1.2 must handle this rather than rediscovering it live.
- **Eight bands** — a DSP and memory change, not a GUI one; its own cycle and spec.
- **Dragging HP/LP on the graph** — they are drawn in V1.0 but adjusted by their sliders.
- **`@serialize`** — unnecessary: REAPER already persists slider values and the GUI holds no
  state of its own.
- Themes and skins.

## 8. Verification

**Oracle (Python):** the magnitude functions are testable without a GUI, and that is where the
value is — a wrong curve is a silent, plausible-looking bug.

1. **Bell** magnitude at `fc` equals the full applied bit gain (exactly: +2.0000000000 bits for
   a +2-bit bell). **Shelves do NOT**: the shipping TPT shelf uses `A = sqrt(gain_lin)`, so at
   `fc` a shelf sits at **exactly half** the gain in logarithmic terms — `svf_response` gives
   precisely `bits/2` for every `fc` (20 Hz–19.9 kHz) and `Q` (0.1–10) swept.
   **All pinned numbers come from `svf_response`, the exact closed form** — never from
   `svf_magnitude` (a finite-window RMS estimator) and never from an FFT bin. rev 2 quoted
   "+-0.9966 at fc" as verified; that figure was an artefact of reading FFT bin 171 (1002 Hz)
   instead of exactly 1000 Hz, which is also why it was asymmetric between low and high shelf
   (0.9966 vs 1.0034). A correct implementation would have failed a test pinned to it
   (Fable P0-1).
   *Node convention, pinned:* a shelf node is a **handle** drawn at `(fc, full gain)`, so it does
   not sit on its own curve. Stated here so it is not later diagnosed as a rendering defect.
2. Band magnitude far from the centre tends to unity.
3. HP/LP magnitude matches `hplp_digital_mag`, and is **-3 dB at cutoff only for non-Brick
   slopes at Resonance 0** (review P1-1): the resonance bell multiplies the cutoff magnitude, and
   FIR Brick follows the sampled/windowed step contract instead. Separate tests cover
   Resonance 0..1 and realized Brick behaviour.
4. **Per-domain traces:** each domain's trace equals the product of the magnitudes of the Both
   blocks and that domain's blocks — and a mixed-placement configuration is included, with the
   expected values computed independently rather than by calling the same helper the
   implementation uses (otherwise the test only proves the code agrees with itself).
5. Proportional-Q: with Q Character above zero, the drawn width follows `band_qeff`, not the
   knob Q.
6. Bit-to-pixel mapping round-trips; the 0.05-bit snap always lands on a multiple.
7. Clamping beyond +-4 bits does not wrap or invert — for individual nodes **and for the total
   curve**, which can exceed the viewport while every node is inside it (review P2-1).
8. **Canonical split:** for a swept target, `floor`-based Macro plus Micro in `[0,100)`
   reproduces the value exactly at every integer boundary, at +-0.05, at +-16, and for negative
   values.
9. **Bit Ratio inversion:** for every Ratio step 0..3, the node follows the cursor within a
   stated tolerance or reports a constrained state; `Ratio = 0` is locked, not silently reset.
10. **Realized Linear/Brick magnitude:** the drawn curve for Linear at Normal vs High differs in
    the steep low-frequency case that motivated V0.7, and the Brick trace comes from
    `fir_brick_kernel` — a Brick slope must never draw as "no filter".
11. **Log floor:** exact zeros, subnormals and a serial HP+LP with no passband all produce finite
    coordinates.
12. **Curve-generation counter:** every watched field, changed alone, invalidates the cache; a
    deliberately-constructed pair of configurations that an arithmetic signature would collide on
    must NOT reuse the cache.

**Transcription gate (review P1-4).** Python tests prove the Python maths; the shipping graph is
a separate EEL implementation and a sign error there can still draw a smooth, believable curve.
So: a debug path dumps the JSFX curve cache at a pinned parameter matrix, and the values are
compared numerically against the oracle. Screenshots are not a numeric oracle. Coverage: shelf
plateaus on both sides, `fc`, near-Nyquist warping, proportional-Q, Brick, and both sample rates.

**Live in REAPER, with the owner:**

- Drag each node: frequency, gain and Q change, and the graph matches what is heard.
- The written values appear in the slider list, and **automation records them** (the
  `slider_automate` gate).
- Numeric entry: type, Enter, Esc, Backspace.
- **Null test V0.9 vs V1.0** with the mouse untouched → digital silence.
- **Primary CPU gate: V0.9 with GUI closed vs V1.0 with GUI closed** (rev-3 review P2). The
  realized-magnitude FFT runs in `@block` whether or not the window is open, so "GUI closed ==
  V0.9" is *not* exactly true, and comparing V1.0-open against V1.0-closed would mostly measure
  drawing. Measure **peak block time and xruns**, not only average CPU — a deadline miss is the
  failure mode, and an average hides it.
- Worst case to test: **High + High**, both engines sweeping simultaneously, at 44.1 / 48 / 96
  and, if available, 192 kHz, at small and normal audio buffers.
- **GUI open vs closed** stays as a secondary measurement, of `@gfx` drawing cost.
- Gating the FFT on `gfx_w > 0` was considered and rejected: reading `@gfx`-owned state from
  `@block` is the same unsynchronised cross-thread hazard as the cache publication problem.
- Placement colours match the actual placement of each band.

## 9. Method

Unchanged: verify the magnitude maths in Python first → TDD the oracle → transcribe to JSFX →
live-verify with the owner → Fable final review → tag `rcbitnova-v1.0`.

**EEL2 reminder:** V0.8's defect was a compound assignment under a conditional that read
correctly and never executed. Its exact parsing cause remains unproven, so new code avoids both
compound assignment under `?` and unparenthesized conditional branches. GUI code is dense with
conditionals and is exactly where this hides again.

## 10. Weakness-review disposition (rev 1 → rev 2)

Every finding accepted; two were verified numerically before accepting.

| Finding | Disposition |
|---|---|
| **P0** Mixed Placement has no single scalar response | **Accepted** — one trace per domain, ReEQ's model and colours (§3). The owner rejected picking a single domain: he uses all of them. The M/S-plus-L/R limitation is documented, not hidden |
| **P0** Linear/FIR Brick are not the min-phase curve | **Accepted** — three separate magnitude sources (§3.1). Confirmed in the code: a Brick slope maps to `nsec = 0` in the min path, so rev 1 would have drawn "no filter" for it |
| **P0** Vertical drag inconsistent with Bit Ratio | **Accepted** — Y is effective gain, drag inverts the Ratio; `Ratio = 0` locks the node instead of silently resetting a deliberate setting (§5) |
| **P0** Shelf centre-gain assertion is false | **Accepted, measured**: +-2 bits plateau vs **+-0.9966 at `fc`**. Tests split by type; the shelf node is pinned as a handle (§8.1) |
| **P1** -3 dB cutoff test needs scope | **Accepted** — asserted only for non-Brick at Resonance 0 (§8.3) |
| **P1** Curve cache has no memory ownership | **Accepted** — fixed region below `lp_base`; never relative to `lp_top`, which `lp_relayout` frees (§3.3) |
| **P1** Arithmetic signature can collide | **Accepted** — per-field snapshot and a `curve_gen` counter; a collision test is required (§3.3, §8.12) |
| **P1** Python tests do not verify the EEL transcription | **Accepted** — numeric dump-and-compare gate (§8) |
| **P1** Product-then-log needs a zero contract | **Accepted** — 1e-7 floor, clamp before pixels, and the "no log" invariant scoped to `@sample` (§3.2) |
| **P1** Macro/Micro split non-canonical | **Accepted** — `floor` + remainder in `[0,100)`, clamp before split, `slider_automate` only on real change (§5) |
| **P1** Numeric entry does not identify the parameter | **Accepted** — focusable F / G / Q fields with units; full drag/wheel semantics pinned (§5) |
| **P1** Resize and Retina asserted, not designed | **Accepted** — `@gfx 900 500`, one shared transform for drawing and hit-testing, minimum size, scaled hit radius (§6). rev 1's `gfx_init` was the ReaScript API, not JSFX |
| **P2** Over-range covers nodes but not the curve | **Accepted** — clipping indicators and deterministic edge-label handling (§8.7) |
| **P2** Slider count off by one | **Accepted, verified**: 95 declarations, not 96 (§1) |

## 11. Fable review disposition (rev 2 → rev 3)

Fable reviewed rev 2 against the V0.9 source and the oracle, and returned "needs edits".

| Finding | Disposition |
|---|---|
| **P0-1** the pinned "+-0.9966 bits at fc" is measurement noise, not the true value | **Accepted, re-verified.** `svf_response` gives exactly `bits/2` for every `fc` and `Q`. My figure came from an FFT bin at 1002 Hz, not 1000 Hz — the low/high asymmetry (0.9966 vs 1.0034) was the tell. All pinned numbers now come from the closed form (§8.1). This is the fourth time on this project a "verified" number was an artefact of how it was measured |
| **P0-2** "that work is already happening" in `lpk_build` is false | **Accepted** — `lpk_build` windows in the time domain and never evaluates the windowed kernel's response. The DTFT cost is now stated explicitly (§3.1) |
| **P0-3** the coarse-grid data has no safe home; `@gfx` reading `ktime` reopens the very hazard §3.3 closes | **Accepted** — `@block` computes the grid in the same pass as the rebuild and copies it into the protected cache; `@gfx` never touches engine buffers (§3.1) |
| **P0-4** no closed form given, and the tempting oracle function is the wrong one | **Accepted** — `svf_response` named as the porting target, `svf_magnitude` explicitly excluded, EEL2's lack of a complex type noted (§3.1) |
| **P1-1** the magnitude table omits "active" topology | **Accepted** — all evaluation reads `act_*`/`lp_geo`, never the sliders, because a pending topology change can hold for a second (§3.1) |
| **P1-2** the coarse-grid cost is unconditional, undermining the GUI-open-vs-closed gate | **Accepted** — stated as unconditional; the `gfx_w > 0` gate rejected as its own cross-thread hazard (§8) |
| **P2** dynamics in Dual M/S route a Both band's static SVF through M/S | **Accepted** — forward note added to §7 for the V1.2 spec |

**Confirmed correct by Fable, no change needed:** the per-domain trace model and its stated
M/S-plus-L/R limitation (verified against `@sample` and `lpk_process`; the linearity argument is
now written into §3); Brick mapping to `nsec = 0` in the min path; 95 slider declarations; the
below-`lp_base` cache being untouched by `lp_relayout`'s `memset`/`freembuf` and not disturbing
V0.7's page alignment; and `Fable Eq Dynamic`'s numeric-entry pattern already using per-field
identity, matching §5's design.

## 12. Rev-3 weakness review disposition (rev 3 → rev 4)

All findings accepted. One of them replaced my method with a better one.

| Finding | Disposition |
|---|---|
| **P0** the Brick rule contradicts Min-phase topology | **Accepted** — precedence pinned by phase: Min + Brick draws **identity** (it really is Off, `nsec = 0`), Linear + Brick draws the realized kernel. rev 3's "must never draw as no filter" would have drawn a cutoff nobody hears (§3.1) |
| **P0** per-point DTFT in `@block` is an unbounded real-time regression | **Accepted, and the method changed**: a single native `fft(BD)` of the windowed kernel — already proven at 32768 in V0.7 — replaces ~3.3 M interpreted operations per engine. The danger correctly identified is peak block time, not average CPU (§3.1) |
| **P0** the cache has no safe publication protocol | **Accepted** — double buffering with publish-after-complete and a frame-start snapshot in `@gfx`; a torn read now cannot draw a mixture of two kernels (§3.3) |
| **P0** invalidation runs in `@slider` but active topology commits in `@block` | **Accepted** — split into `gen_target` (requested, from `@slider`) and `gen_active` (audible, from `topo_commit` and cache publication). This is what stops the GUI showing a requested topology as committed (§3.3) |
| **P1** "realized curve" undefined during rebuild and crossfade | **Accepted** — pinned as a **target display**, with the 50 ms lead stated openly rather than left to be found and called a bug (§3.4) |
| **P1** the sparse 50–100 point grid has no accuracy bound | **Dissolved by the FFT change** — the grid is now BD/2 bins, so a narrow Brick knee cannot fall between points. Interpolation pinned: linear in log frequency, on values already in bits (§3.1) |
| **P1** the canonical split loses part of the negative range | **Accepted** — truncation toward zero with a signed Micro, keeping the span symmetric at ≈`(-17, +17)`; `floor` would have made it `[-16, +17)` (§5) |
| **P1** two slider writes are not one observable transaction | **Accepted** — write **Micro first**, so any transient is bounded by one bit instead of a full Macro step; the host-coalescing assumption is now stated and live-tested rather than relied on silently (§5) |
| **P1** the cache has no exact memory inventory | **Accepted** — word-level table totalling 6280 words, with `lp_base` pinned before and after and the worst-case `freembuf` asserted exactly (§3.3) |
| **P1** the mixed M/S + L/R limitation is invisible in the GUI | **Accepted** — affected traces go dashed with a legend state, plus a GUI test (§3) |
| **P2** edge-label behaviour required but not designed | **Accepted** — ordering, offsets, selected-node priority and in-plot constraint pinned (§6) |
| **P2** "GUI open vs closed" is not the important comparison | **Accepted** — primary gate is now V0.9-closed vs V1.0-closed, with peak block time and xruns (§8) |

## 13. Fable review disposition (rev 4 → rev 5)

| Finding | Disposition |
|---|---|
| **P0** "always read `act_*`" is wrong in Min phase | **Accepted, verified in code.** `topo_changed` only fires for placement when `slider140 == 1`, so in Min the `act_*` pair goes permanently stale while `@sample` uses the raw slider — the curve would have shown a domain abandoned minutes earlier. Rule is now phase-conditional (§3.1) |
| **P1** `fft_permute`, Hermitian symmetry, imaginary-lane residue missing from the write-up | **Accepted** — all three pinned in §3.1. Omitting the permute would have produced a scrambled but entirely believable curve |
| **P1** fftshift concern | **Closed as a non-issue**, with the shift-theorem argument recorded so nobody "fixes" it later |
| **P1** Micro-first does not bound the transient in general | **Accepted, measured.** `16.95 → -16.95` gives **+15.05 bits (x33923)** with Micro first. Replaced by choosing the order per write, always erring toward silence (§5) |
| **P1** the host-coalescing assumption is restated, not resolved | **Accepted** — explicitly marked load-bearing and unverified, kept as a live gate (§5) |
| **P1** the double-buffer scheme has no memory barrier on ARM | **Accepted as a scoped unknown** — worst case is a one-frame `@gfx` glitch, never signal corruption; recorded honestly instead of claiming sufficiency (§3.3) |
| **P1** `gen_target` omits Phase and Resolution | **Accepted** — both added, and what each generation counter gates is now stated (§3.3) |
| **P2** memory arithmetic left as a future test | **Accepted** — computed and written into the spec: 27261 words of padding today, 21000 remaining after the 6280-word block; `lp_base` does not move (§3.3) |
| **P2** imaginary lane must be zeroed explicitly | **Accepted** — folded into the §3.1 FFT details |

**Confirmed correct by Fable, no change needed:** the `desbuf` reuse is safe in lifecycle, size
and page alignment (it is literally the same allocation); the below-`lp_base` cache is untouched
by `lp_relayout`; 95 slider declarations; and the peak-block-time reasoning behind choosing a
native FFT over a per-point DTFT.
