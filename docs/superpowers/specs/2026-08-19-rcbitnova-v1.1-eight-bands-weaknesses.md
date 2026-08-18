# RCBitNova V1.1 Eight Bands Design: Weakness Review

**Reviewed:** `2026-08-19-rcbitnova-v1.1-eight-bands-design.md`
**Review posture:** adversarial memory-layout review, parameter ABI compatibility, DSP topology, GUI reachability, and acceptance-test completeness

## Overall Assessment

The central split is sound: eight static bands with dynamics limited to the original four avoids the expensive Mode-B memory re-layout and gives the GUI a useful next step. Keeping the old slider IDs and allocating new static controls above the existing range are also the right instincts.

The specification is not implementation-ready yet. One proposed memory test has the wrong boundary, the current four-band GUI writers cannot be generalized through the read helper, and the audio ordering of the new static bands relative to nonlinear Mode B is undefined. Those gaps can produce memory corruption, edits to the wrong band, or two conforming implementations that sound different.

## Findings

### P0. The `cf` memory acceptance bound is wrong and would permit an overlap

The layout table correctly says that `cf` occupies 64 words at eight bands and that `st` begins at address 64. Verification item 2 instead accepts `cf <= 96`. That test would pass an implementation in which `cf` overwrites all of `st[64..95]`.

This is the tightest boundary alongside `st`, so a loose upper bound defeats the purpose of the memory test.

**Required resolution:** assert adjacent addresses, not unrelated constants:

```text
cf + N_BANDS * 8 == st          == 64
st + N_BANDS * 4 == det         == 96
bp + N_BANDS * 3 <= eg          == 256
```

Add sentinels on both sides of every expanded static array and exercise coefficient setup plus audio processing before checking them.

### P0. The current named GUI writers map every band above B3 to B4

V1.0's `gc_w_freq`, `gc_w_macro`, `gc_w_micro`, `gc_w_ratio`, `gc_w_q`, and `gc_w_enable` each have explicit branches for B1-B3 followed by a final B4 fallback. After `N_BANDS` becomes 8, dragging B5-B8 will therefore write B4 unless every writer is expanded.

The proposed `band_slider_base` helper cannot solve this write path: V1.0 already established that computed `slider(index)` writes do not update the real parameter reliably. The helper is appropriate for reads only.

There is a second hazard in the same functions: every writer currently calls both `setup_band(b)` and `setup_band_dyn(b)`. Calling the dynamic builder for B5-B8 writes beyond `det`, `dp`, and `dm` and into neighboring arrays.

**Required resolution:** specify eight-way named writes for every editable static field, with `setup_band_dyn(b)` guarded by `b < N_DYN`. Add a gesture matrix for B1-B8 that snapshots all slider values and dynamic-memory sentinels, then proves exactly one named slider changed and no static-only edit touched dynamic memory.

### P0. The dynamic/static split has no exhaustive transcription gate

In V1.0, `N_BANDS` controls much more than the allocation declarations: initialization, `setup_band_dyn`, the `@slider` Mode-B scan, Mode-A processing, Mode-B processing, envelope resets, and several address calculations. Leaving even one of these sites at eight can reinterpret hard-ceiling sliders as B5 dynamic controls or overwrite the arrays immediately following the four-band dynamic regions.

Verification item 3 checks array sizes and `mb_end`, but it does not prove that every dynamic loop is bounded by `N_DYN` or that no B5-B8 path calls a dynamic function.

**Required resolution:** inventory every current `N_BANDS` use and classify it as static or dynamic in the design. Add source-level assertions for the expected loop bounds and runtime canaries around `det`, `dst`, `cst`, `dp`, `dm`, `eg`, `mbenv`, `mbmode`, `mbwpos`, `mbgc`, `mbeh`, `hc`, and `egh` while all four new bands are exercised.

### P0. DSP order relative to Mode B is undefined

The existing processor does not have one simple per-band cascade. Static filtering and Mode A happen in the first pass; Mode B is a later nonlinear pass. There are therefore at least two plausible placements for B5-B8:

- process their static filters in the first pass, before the B1-B4 Mode-B stage;
- process them after the Mode-B stage.

These placements are not equivalent. In the first topology, B5-B8 alter the signal seen by Mode-B detection and limiting. In the second, they do not. Both fit the phrase "bands 4-7 run static filtering only."

**Required resolution:** add a normative stage diagram and state the exact order of HP/LP, B1-B4 static/Mode A, B5-B8 static, B1-B4 Mode B, and output trim. Add an audio test in which an enabled B5 boost crosses a B1 Mode-B ceiling; the expected result must distinguish the chosen order.

### P1. The old-project compatibility test does not describe a migration

V1.1 is a new JSFX filename while V1.0 remains frozen. An existing project containing `RCBitNova V1.0` will simply reopen V1.0; that proves nothing about whether the same state loads correctly into V1.1.

**Required resolution:** define the supported migration operation: preset transfer, state-chunk substitution, or manual replacement. Test that operation with non-default and off-grid values on every old parameter, including automation envelopes. Confirm that the old 95 host parameters retain their index, name, range, and value, and that only the 36 new parameters are appended with defaults.

### P1. Preserving slider IDs alone is not a complete parameter-ABI test

The specification correctly avoids renumbering existing `sliderNN` declarations, but REAPER-facing compatibility also depends on exposed parameter order and the serialized state shape. A source-level check of IDs cannot catch an accidental declaration reorder, duplicate ID, changed range, or changed default.

**Required resolution:** capture V1.0's host parameter manifest through REAPER and compare it with the V1.1 prefix. The manifest should include host index, JSFX slider ID where recoverable, display name, minimum, maximum, step, default, and a round-trip value. Assert that the new B5-B8 parameters follow the complete V1.0 prefix rather than appearing inside it.

### P1. The null gate is under-specified and "cost nothing" is too strong

Digital zero with B5-B8 disabled is the right audio regression gate, but it does not follow merely from matching visible settings. V1.0 already exposed how sub-step parameter values, state-reset timing, and GUI-originated writes can defeat a null while the controls look identical.

Also, four extra enable checks and additional setup/GUI work are not literally zero cost. A null test proves output identity, not zero CPU cost.

**Required resolution:** define a reproducible null fixture: identical old-parameter state transferred programmatically, GUI closed, equal latency, fresh/reset instances, fixed sample rate and block size, deterministic input, no automation, and a stated residual threshold or exact-bit comparator. Reword the promise as "bit-identical audio while B5-B8 are disabled" and measure disabled CPU overhead separately.

### P1. Verification never proves that an enabled new band is mathematically correct

The oracle only checks that disabled B5-B8 contribute identity. The live test that eight nodes "change the sound" can pass with the wrong frequency, wrong placement, wrong Q Character, or B5 controlling B8.

**Required resolution:** for each of B5-B8, enable that band alone and compare JSFX output or an impulse-derived response against the existing oracle across Bell, Low Shelf, High Shelf, all placements, representative positive/negative gains, and constant/proportional Q. Include a multi-band case to verify cascade addressing and channel-domain behavior.

### P1. `mb_end` alone does not prove that the dynamic memory layout stayed flat

Even if `mb_end` remains unchanged, accidentally sizing `mbenv`, `mbmode`, `mbwpos`, `mbgc`, `mbeh`, `hc`, or `egh` by eight shifts every downstream address, including HP/LP and GUI memory. The design promises that `lp_base` and the low layout remain unchanged, but the stated test covers only the two large rings.

**Required resolution:** snapshot every V1.0 dynamic and downstream base address and require exact equality in V1.1. At minimum cover `mb_end`, `mbenv`, `mbmode`, `mbwpos`, `bus_dry`, `mbgc`, `mbeh`, `hc`, `egh`, `hplp_state`, `hplp_cf`, the GUI cache bases, and `lp_base`.

### P1. The helper is tested, but its adoption is not

Testing `band_slider_base()` outputs does not prove that all static read sites use it. V1.0 open-codes `10 * (b + 1)` in coefficient setup, curve construction, domain visibility, hit-testing, node drawing, drag initialization, wheel handling, and the readout. One missed site makes B5-B8 read nonexistent old-range sliders while other parts of the UI appear correct.

**Required resolution:** list the required call sites and add a source audit that rejects the old open-coded band-slider formulas outside the helper. Keep explicit named-slider assignments exempt because writes must not use the computed helper.

### P1. Eight nodes make overlap a reachability problem again

Spread-out defaults prevent overlap only on first load. Users can place several bands at the same frequency and gain. V1.0's loop-based hit-testing can leave only one coincident node reachable; doubling the nodes makes that substantially more likely. A thinner outline identifies capability but does not provide a way to select an occluded band.

**Required resolution:** define overlap selection behavior, such as selected-node priority plus repeated-click cycling, or add a compact B1-B8 selector tied to the readout. Test exact overlap and near-overlap at normal and Retina scale.

### P1. The CPU check has no pass/fail contract

"CPU with 8 bands vs 4" names a measurement, not a release gate. It does not fix sample rate, block size, duration, signal, enabled filter types, placement, GUI state beyond closed, acceptable regression, or xrun count.

**Required resolution:** pin the benchmark fixture and require zero xruns plus a maximum regression or minimum deadline margin. Measure at least disabled B5-B8, four new enabled Bell bands, and the stated worst case with all original Mode-B dynamics active.

### P2. Outline thickness alone is a fragile capability cue

A one-stroke thickness difference can disappear on Retina scaling, under disabled/selected styling, or for users with reduced contrast. It also has no textual confirmation in the specified readout.

**Required resolution:** retain the outline distinction but add a compact capability label in the selected-band readout, for example `DYN` for B1-B4 and `STATIC` for B5-B8. Specify logical stroke widths and verify both selected and disabled states.

### P2. A few statements overclaim or obscure the actual range

"A ninth band node" is inconsistent with an eight-band product and may be counting unrelated HP/LP nodes. Likewise, "151-189" looks contiguous even though the intended IDs are `151-159`, `161-169`, `171-179`, and `181-189`. These are minor editorial issues, but parameter-map prose should be exact.

**Required resolution:** say "each additional band node" and list the four explicit slider ranges.

## Strengths To Preserve

- Keeping dynamics at four bands avoids the large Mode-B ring expansion and protects the existing `lp_base` page.
- New static slider IDs sit above the existing map, which is the correct direction for compatibility.
- Disabled defaults make the added bands audibly inert on first instantiation.
- Separating `N_BANDS` from `N_DYN` is clearer than scattering special cases through DSP code.
- A single helper for computed reads is appropriate, provided named writes remain explicit.
- Carrying forward quantized GUI writes, inline dependency recomputation, and function-order checks directly addresses defects found live in V1.0.

## Recommended Gate Before Planning

Resolve the four P0 findings first: correct the `cf` boundary, specify named B5-B8 writers with guarded dynamic recomputation, inventory every static/dynamic loop and allocation, and pin the position of B5-B8 relative to Mode B. Then strengthen the release contract with an actual V1.0-to-V1.1 state migration fixture, a full host-parameter manifest, enabled-band audio-oracle cases, exact downstream memory addresses, and a deterministic null test.
