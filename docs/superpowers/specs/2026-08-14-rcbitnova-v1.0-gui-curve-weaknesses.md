# RCBitNova V1.0 GUI Curve Design Rev 3: Weakness Review

**Reviewed:** `2026-08-14-rcbitnova-v1.0-gui-curve-design.md`, revision 3
**Review posture:** adversarial architecture, DSP-display correctness, real-time safety, and acceptance-test completeness
**Overall assessment:** Rev 3 closes most of the mathematical and product-semantics gaps from the earlier review. The remaining blockers are concentrated in the linear-phase display path: one contradictory Brick rule, an unbounded audio-thread workload, and incomplete synchronization between `@block` and `@gfx`.

## Findings

### P0. The Brick verification rule contradicts the actual Min-phase topology

The response table distinguishes Min and Linear modes, but then adds an unconditional row:

> HP/LP Slope = FIR Brick -> actual `fir_brick_kernel` at the active BD

The verification section is stronger still:

> Brick slope must never draw as no filter

That is false when `Phase = Min`. In the current engine, FIR Brick maps to Off in Min phase: the active minimum-phase section count is zero and the audible response is identity. A test enforcing the current sentence would make the graph show a cutoff that is not being heard.

**Required resolution:** define precedence explicitly:

- `act_phase = Min` and active slope `FIR Brick`: identity response, exactly like Off.
- `act_phase = Linear` and active slope `FIR Brick`: magnitude of the realized `fir_brick_kernel` at the active BD.
- Add both combinations to the oracle and live GUI matrix. Rename the verification requirement to “Linear + FIR Brick must use the realized Brick kernel.”

### P0. Direct DTFT in `@block` is an unbounded real-time regression

At High resolution, 100 query frequencies over a 32768-tap kernel are about 3.3 million tap operations per engine per rebuild. Two engines rebuilding together are about 6.6 million operations. At the proposed 100 ms rebuild cadence, a continuous edit can demand roughly 66 million interpreted EEL operations per second before counting kernel construction, trigonometry or recurrence setup, partition FFTs, and the existing audio work.

The important failure mode is peak block time, not average CPU. Putting the calculation in `@block` can make one audio block miss its deadline even when the later average looks acceptable. It also runs while the GUI is closed, so V1.0 can regress the audio-only case.

“Benchmark High + High” is not a sufficient contract because no pass/fail limit is pinned and implementation is allowed before the result is known.

**Required resolution:** remove the direct per-frequency DTFT from the audio thread. The natural implementation is one native FFT of the already-windowed `ktime` in reusable build scratch, followed by permutation/magnitude extraction and interpolation to display frequencies. If direct DTFT remains, make the benchmark a pre-implementation gate and specify hard limits for:

- worst and percentile audio-block duration versus the device deadline;
- added CPU versus V0.9 with the GUI closed;
- xruns during simultaneous HP and LP sweeps at High + High;
- 44.1, 48, 96, and 192 kHz at small and normal audio buffers;
- open and closed GUI states.

### P0. The curve cache has no safe publication protocol

Moving visualization storage below `lp_base` protects it from `memset` and `freembuf`, but it does not make an array update atomic. `@block` can be writing a new coarse linear response while `@gfx` is reading it. A frame may therefore combine old and new bins and briefly draw spikes, discontinuities, or a response belonging to neither kernel.

`curve_gen` is described as an invalidation counter, not as a completed-publication marker. Incrementing it before or during a write does not solve the torn-read problem.

**Required resolution:** use a two-buffer publication scheme:

1. `@block` fills an inactive cache completely.
2. It publishes the completed generation and active cache index only after the final value is written.
3. `@gfx` snapshots generation/index, reads that immutable buffer, and retains the previous frame if publication changes during the read.

Add a stress test that continuously rebuilds both kernels while rendering and checks for non-finite values and one-frame discontinuities beyond a pinned bound.

### P0. Invalidation is tied to `@slider`, but active topology changes in `@block`

The specification correctly says the graph must use active values such as `act_phase`, active placement, and active resolution. However, the proposed invalidation check runs in `@slider`, while those active values are changed later by `topo_commit` in `@block`. There is no guarantee that `@slider` runs again after the commit.

The result can be a graph that continues to display the old active topology, or publishes a new realized kernel without causing `@gfx` to consume it.

**Required resolution:** bump a completed curve generation from the same places that commit audible state:

- `topo_commit` for phase, placement, and resolution changes;
- successful realized-kernel cache publication;
- any immediate active-state path that does not pass through `topo_commit`.

Keep target-slider invalidation separate from active-state publication so the UI cannot accidentally present requested topology as committed topology.

### P1. “Actual realized curve” is underspecified during rebuild and kernel crossfade

For an ordinary linear parameter change, V0.9 can keep the old kernel audible, build a new kernel, and then run a 50 ms dual-kernel crossfade. Rev 3 proposes publishing the magnitude of the newly built `ktime` immediately. During that interval the graph is neither the old audible response nor the time-varying crossfade response; it is the target response.

The same ambiguity exists during the 100 ms rebuild coalescing window. Static band changes can be reflected immediately while the linear HP/LP response still belongs to the previous build.

**Required resolution:** choose and name one contract:

- **Target display:** publish the new curve only as a target and explicitly accept that it leads the sound during rebuild/crossfade.
- **Audible display:** retain old and new caches and blend their complex responses or documented magnitude approximation with the engine's crossfade progress.

The current wording alternates between “what is actually heard” and target-kernel behavior, so either implementation could pass an informal review while violating the other interpretation.

### P1. The 50-100 point realized grid has no accuracy bound

Across roughly three decades, 50-100 log-spaced points are about 6-15% apart in frequency. A narrow Brick transition or resonant/high-Q cutoff can sit between points. Interpolating sparse magnitudes can miss the knee, attenuate a local maximum, or place the apparent cutoff incorrectly even though every sampled point is mathematically correct.

The design does not pin:

- whether interpolation is linear in Hz or log frequency;
- whether it interpolates linear magnitude, dB, or bits;
- the maximum permitted error between samples;
- adaptive samples around HP/LP cutoff and resonant extrema.

**Required resolution:** prefer a full native FFT grid and interpolate in log frequency from complex-bin magnitudes. Otherwise define an adaptive grid and a numerical error budget against dense direct evaluation. Test Brick and maximum-resonance cases with cutoffs deliberately placed halfway between coarse query points, at every supported block duration.

### P1. The canonical Macro/Micro split loses part of the current negative range

The proposed canonical form is:

```text
Macro = floor(base_bits)
Micro = (base_bits - Macro) * 100
Micro in [0, 100)
```

But Macro is limited to `[-16, +16]`. A value such as `-16.5` is currently representable as Macro `-16`, Micro `-50`; the canonical formula requires Macro `-17`, which is outside the slider range. Conversely, positive values can approach `+17` using Macro `+16` and positive Micro. The canonical range is therefore approximately `[-16, +17)`, not the full physical range implied by the two sliders.

“Clamp to the representable slider range” does not resolve which range is intended, and the proposed tests stop at +/-16 instead of covering the actual edges.

**Required resolution:** pin one of these choices:

- deliberately adopt the asymmetric canonical range `[-16, +17)` and document it;
- retain a signed remainder using truncation toward zero, preserving approximately `(-17, +17)`;
- special-case the lower edge with a different canonical representation.

Add round-trip tests around `-17`, `-16`, `0`, `+16`, and `+17`, including values one Micro step to either side.

### P1. Two slider assignments are not specified as one observable transaction

“Write Macro first, then Micro, then automate both” controls automation notification order, but it does not establish that `@slider` or the audio path cannot observe the pair between assignments. At a canonical boundary, the intermediate value can be large: changing `0.95` to `1.00` and writing Macro first temporarily forms `1.95` with the old Micro.

JSFX may in practice coalesce both assignments before the next `@slider` execution, but the design currently relies on that unstated host/runtime behavior.

**Required resolution:** document and verify the event-order guarantee being relied on, or route GUI edits through one pending combined value that the control path decomposes and publishes coherently. Include fast drags and automation recording across positive and negative integer boundaries in live tests; assert that DSP never observes an outlier combined value.

### P1. The fixed cache has no exact memory inventory

“About 1000 cached y-values” and “placed below `lp_base`” are not enough to verify memory safety. Rev 3 now needs at least realized coarse grids, per-domain traces, snapshots, generation metadata, and, if publication is fixed, double buffers. Growing the static region can cross the next 65536-word boundary and move `lp_base`, changing total allocation even if all offsets remain technically below it.

**Required resolution:** add an explicit word-level layout with named start/end offsets, buffer counts, maximum point counts, and alignment padding. Pin `lp_base` before and after the change and calculate worst-case `freembuf` size for High + High. The memory test should assert exact non-overlap and maximum allocation, not only “no crash.”

### P1. Mixed M/S and L/R traces are knowingly non-physical but have no visible state

Rev 3 honestly states that simultaneous M/S and L/R placement cannot be represented exactly and that the colored traces are group displays. That limitation remains invisible in the proposed GUI. A user can still read the curves as channel responses, especially because the design motivation says the graph shows what is heard.

**Required resolution:** when incompatible placement families coexist, visually mark the affected traces as group/approximate views, for example with a distinct dashed style and a compact legend state. Add a GUI test for Both + Mid + Left/Right showing that the limitation is visible without consulting the design document.

### P2. Edge-label behavior is accepted as a requirement but not designed

The document says overrange nodes clamp to the edge and that overlap handling must be deterministic, but it never defines the algorithm. Multiple bands at the same frequency and beyond the same Y edge can produce coincident nodes and unreadable labels. “Clipped to plot bounds” can also hide the very numeric value meant to preserve information outside +/-4 bits.

**Required resolution:** specify ordering, offsets, collision resolution, selected-node priority, and whether labels remain fully inside the plot. Include identical-frequency/identical-value and opposite-overrange cases at minimum width and Retina scale.

### P2. “GUI open versus closed” is not the most important CPU comparison

Because the realized grid is intentionally computed with the GUI closed, comparing V1.0 open versus V1.0 closed mostly measures drawing. It does not expose the new unconditional audio-thread cost.

**Required resolution:** make V0.9 closed versus V1.0 closed the primary regression benchmark, with peak block time and xruns as well as average CPU. Keep open versus closed as a secondary measurement of `@gfx` cost.

## Strengths Preserved in Rev 3

These parts are now strong enough to implement as written and should not be reopened without new evidence:

- Per-placement-domain traces include Both-domain processing and explicitly reject a false scalar-combined response.
- Bell and shelf overlays use the exact TPT/SVF closed form, including effective `band_qeff`.
- Ordinary Linear HP/LP and Linear Brick are intended to display realized windowed kernels rather than ideal analog substitutes.
- Active topology, logarithmic magnitude floor, effective-Y inversion, ratio-zero lock, drag clamp, and base snapping are all explicit.
- The slider count is corrected to 95.
- Numeric-entry field mapping, minimum drawable size, Retina coordinate policy, and Python-to-JSFX transcription gate are substantially better specified than in rev 1.

## Recommended Gate Before the Implementation Plan

Do not start the GUI implementation plan until the four P0 items have explicit dispositions in the design. In particular, run a small JSFX benchmark/prototype comparing native FFT extraction against direct DTFT at BD 32768, and choose the cache publication protocol before assigning memory offsets. Those two decisions determine the CPU budget, buffer count, invalidation flow, and a meaningful acceptance matrix.
