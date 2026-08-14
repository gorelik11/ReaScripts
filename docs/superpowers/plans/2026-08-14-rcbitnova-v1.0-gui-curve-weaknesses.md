# RCBitNova V1.0 GUI Curve Plan: Weakness Review

**Reviewed plan:** `2026-08-14-rcbitnova-v1.0-gui-curve.md`
**Design baseline:** `2026-08-14-rcbitnova-v1.0-gui-curve-design.md`, rev 5
**Review posture:** executable-plan completeness, DSP-display correctness, EEL2 state ownership, and verification quality

## Overall Assessment

The plan incorporates the important architectural corrections from the earlier design review: phase-dependent Brick precedence, native FFT instead of direct DTFT, reserved memory below `lp_base`, double buffering, target-display semantics, signed Micro, and placement-family marking.

It is not ready for agentic execution yet. The remaining problems are implementation-level, not editorial: the shared double buffer can publish mismatched HP/LP grids, generation slots are confused, required JSFX functions are absent, and the transcription gate reads a cache that the plan never fills.

## Findings

### P0. A one-engine rebuild publishes a stale grid for the other engine

`gc_lin` has one shared `active_idx` for both engines. `gc_build_grid(eng)` writes only that engine into the inactive buffer, then `gc_publish()` flips the whole buffer pair.

Example:

1. Active buffer 0 contains HP=A and LP=B.
2. Only HP rebuilds. The plan writes HP=A2 into buffer 1 and flips to buffer 1.
3. LP now comes from buffer 1 too, but nothing copied B there; it is an old or zero-initialized value.
4. A later LP-only rebuild writes B2 into buffer 0 and flips back, resurrecting old HP=A.

The Python `CurveCache` model has the same defect. Its test reads only engine 0, so it proves that one buffer is not half-written but never proves that the two-engine snapshot is coherent.

**Required correction:** either give each engine its own active index and generation, or copy the complete active pair into the inactive pair before replacing one engine and publishing. Add alternating HP-only and LP-only rebuild tests that assert the untouched engine remains byte-for-byte unchanged.

### P0. `gen_active` and `gen_target` are assigned conflicting `gc_meta` slots

Task 5 defines:

```text
gc_meta[0] = gen_active
gc_meta[1] = active_idx
gc_meta[2] = gen_target
```

`gc_publish()` correctly bumps `[0]`, but Task 6 tells `topo_commit` to bump `[2]` while commenting that it is bumping `gen_active`. That actually advances `gen_target` and leaves the active-topology generation unchanged.

The wider invalidation path is also missing from the shipping code steps: `gc_snap` is reserved, and Python has `watched_fields()`, but no task transcribes the per-field snapshot comparison into `@slider` or bumps `gen_target` there.

**Required correction:** define named offsets/constants instead of numeric indices, implement the `@slider` snapshot path, and test every commit source separately: target slider edit, `topo_commit`, initial active adoption, and successful realized-grid publication.

### P0. The reader half of the publication protocol is absent

Rev 5 requires `@gfx` to snapshot `(generation, index)` once at frame start and retain the previous frame if publication changes during the read. Task 7 does neither. It calls `gc_domain_mag()` point by point without showing where the active index is captured or rechecked.

Even after fixing the two-engine writer, a publication in the middle of a 512-point trace can make one frame combine two buffers. The Python model also never simulates a generation change during a read.

**Required correction:** add concrete `@gfx` code for frame-start snapshot, immutable-buffer addressing, end-of-frame validation, and fallback to the last completed `gc_trace` frame. Add the continuous-rebuild rendering stress test required by the design.

### P0. Core JSFX functions and most interaction logic are placeholders

Task 5 promises `gc_hplp_mag`, `gc_domain_mag`, and Task 7 relies on `gc_dom_used`, but the plan supplies code only for `gc_svf_mag` and `gc_band_mag`. The missing functions contain the difficult policy: Min versus Linear source selection, separate HP/LP realized caches, phase-conditional placement, interpolation, Off/Brick identity, and per-domain composition.

Task 8 similarly gives only node drawing and `gc_write_gain`. Hit-testing, capture, overlapping-node cycling, axis lock, wheel handling, fine mode, Esc restore, readout layout, and numeric entry are prose instructions. Task 9's debug exporter is prose as well.

This contradicts the self-review claim that every code step carries real code. An implementation worker would have to redesign substantial behavior while supposedly executing a pinned plan.

**Required correction:** add executable EEL2 pseudocode or split these into explicit TDD-sized subtasks with named state variables, event transitions, and verification after each one. At minimum, fully specify the three missing magnitude/domain functions before Task 6 and the input state machine before Task 8.

### P0. The linear oracle cannot represent separate HP and LP realized responses

Python `domain_mag()` accepts one `realized` callable and passes it to every Linear HP/LP block. RCBitNova has two independently configured engines, so HP and LP require separate realized samplers. A shared callable can only make both filters use the same response.

Task 9 then calls:

```python
curve.domain_mag(BANDS_FIXTURE, FILTERS_FIXTURE, "both", f, 48000, 1)
```

without any realized sampler. If `FILTERS_FIXTURE` contains the promised Linear/Brick cases, `hplp_mag()` raises `ValueError`; if it does not, the gate does not cover the risky implementation.

**Required correction:** pass realized responses by engine/filter identity, for example `{ "hp": hp_grid, "lp": lp_grid }`, and add a serial HP+LP test with deliberately different cutoffs and resolutions.

### P0. The transcription gate dumps an unpopulated cache and can pass by skipping

The plan reserves `gc_trace[2][5][512]`, but Task 7 computes and draws each point directly; no task ever fills or publishes `gc_trace`. Task 9 nevertheless exports “`gc_trace`'s first buffer,” which will contain initialization residue or zeros rather than the displayed response.

The proposed pytest also calls `pytest.skip()` when the dump is absent. Therefore the advertised transcription gate can be reported green without ever exercising the EEL2 implementation. Its two-column format has no sample-rate, domain, fixture, engine, or case identifier, yet the prose promises a matrix at 48 and 96 kHz with shelves, proportional-Q, Brick, and both resolutions. The comparison hard-codes 48 kHz and the Both domain.

**Required correction:** either make `gc_trace` the actual completed-frame cache and export its published buffer, or export the exact values consumed by drawing. Use a self-describing case format. Make the release-gate command fail when the required dump is absent; optional CI may keep a separately named skipped test.

### P1. Realized-grid interpolation is implemented in magnitude, not bits

The rev-5 contract says interpolation is linear in log frequency on values already converted to bits. The plan instead stores linear magnitudes and interpolates them directly in both Python and EEL2. Its test explicitly expects `0.75` halfway between magnitudes `1.0` and `0.5`; bit-linear interpolation would produce `sqrt(0.5)`, approximately `0.7071`.

This matters most on steep skirts, exactly where the realized-kernel path is intended to be trustworthy.

**Required correction:** store `log2(max(magnitude, floor))` in `gc_lin`, interpolate those bit values in log frequency, and sum bits when composing serial magnitudes. Change the midpoint test accordingly.

### P1. The plan reintroduces a sparse 256-point grid after claiming dense FFT accuracy

The native FFT produces `BD/2 + 1` dense bins, but `gc_build_grid()` immediately resamples them to only 256 log-spaced values. Drawing later interpolates those 256 values to 512 pixels. The design's statement that a narrow Brick knee cannot fall between points is therefore not proven by the implementation.

The direct-DTFT comparison samples only several low-frequency points below an 8 kHz Brick cutoff, with a loose 5% relative tolerance. It does not test the knee or deep stopband.

**Required correction:** either retain enough FFT-bin data for the drawable frequency range, or establish an error bound for the 256-point reduction against dense FFT bins. Include worst-position cutoffs halfway between stored log points and maximum resonance.

### P1. The Macro/Micro edge path can emit an out-of-range Macro

`gc_write_gain()` clamps to `[-16.999999, 16.999999]`, then snaps to a 0.05-bit grid. Values near either edge snap to exactly `-17` or `+17`; truncation then produces Macro `-17` or `+17`, outside the declared `[-16, 16]` slider range.

The Python split does not reproduce this exact clamp-then-snap sequence, and its tests stop at `+/-16.95` even though rev 5 asks for `+/-17` edge coverage.

There is a second contract violation in the same helper: it always writes and automates both sliders, even when the snapped pair is unchanged, despite the global rule that automation fires only when the value changed.

**Required correction:** pin an exactly representable closed range and clamp after snapping, or explicitly encode endpoints as Macro `+/-16`, Micro `+/-100`. Test every half-step near both edges. Skip each slider assignment and `slider_automate()` call independently when that field is unchanged.

### P1. Python and EEL2 use different tie-breaking for 0.05-bit snapping

Python `round()` uses ties-to-even; EEL2 uses `floor(x / step + 0.5)`, which rounds half ties toward positive infinity. They differ for values such as `-0.075`. None of the tests includes exact positive and negative half-step ties.

**Required correction:** define one tie policy and implement it identically in both languages. Add a table-driven test around `+/-0.025`, `+/-0.075`, integer boundaries, and the representable edges.

### P1. Off filters can create traces and false mixed-placement warnings

Python `active_domains()` treats filters as enabled because they have no `enable` key and `.get("enable", 1)` defaults to true. Thus HP/LP slope Off still activates its placement domain. Min + Brick is also identity and should not make a domain visible or cause M/S plus L/R traces to become dashed.

`gc_dom_used()` is only described in prose, so the same mistake is likely to be transcribed.

**Required correction:** define “audibly active” per block: enabled band; HP/LP ordinary slope not Off; Linear Brick active; Min Brick inactive. Test Off and Min+Brick placements against trace visibility and mixed-family marking.

### P1. The GUI steps do not implement the rev-5 layout contract

Task 7 computes a scale factor but still stretches the plot to the full `gfx_w` and `gfx_h`; it does not establish a single centered 900x500 logical transform. It does not use `gfx_ext_retina`, implement the 480x280 minimum behavior, or drop the readout below minimum size.

Task 8 prints each overrange label beside its node without the required collision ordering, selected-node priority, in-plot constraint, or identical-position handling. No code draws the F/G/Q readout fields that numeric entry is supposed to focus.

**Required correction:** add one explicit logical-to-device transform used by every rectangle, text position, node, and hit test. Implement the minimum-size branch and the pinned edge-label layout before adding interaction.

### P1. The oracle covers Brick but not ordinary Linear kernels

Task 3 lists `impulse_fft_kernel` as a dependency, yet every realized-grid test builds `fir_brick_kernel`. A transcription that works for Brick but samples or associates an ordinary windowed kernel incorrectly would pass all Python tests.

**Required correction:** add ordinary HP and LP cases at multiple slopes, resonance values, resolutions, and sample rates. Compare the FFT-derived grid against direct DTFT at passband, cutoff, resonant maximum, transition, and stopband points.

### P1. CPU and real-time gates still have no pass/fail threshold

“CPU close to V0.9” and “no dropouts” are observations, not release criteria. Task 9 omits the spec's optional 192 kHz case and does not pin a maximum peak-block regression, acceptable xrun count, measurement duration, sweep rate, or audio-buffer sizes.

**Required correction:** record the test machine and audio device, name exact buffer sizes and duration, require zero xruns, and set a maximum peak-block-time ratio or absolute deadline margin. Include 192 kHz when the configured device supports it.

### P1. Rev 5's verification list still contains stale contradictory rules

Although the plan's global constraints correctly use signed Micro and Min+Brick identity, the referenced rev-5 verification section still asks for floor-based Micro in `[0,100)` and says a Brick slope must never draw as no filter. A worker following the acceptance section can undo the corrected behavior.

**Required correction:** repair the rev-5 verification items before execution and make the plan cite the corrected test names rather than the stale prose.

### P2. Every intermediate expected test count is off by one

The current baseline is verified at 183 collected tests. The plan adds:

- Task 1: 10 tests, so 193, not 194.
- Task 2: 8 tests, so 201, not 202.
- Task 3: 6 tests, so 207, not 208.
- Task 4: 4 tests, so 211, not 212.

Task 9's transcription test would then bring the file to 212 if it is collected. The repeated one-test discrepancy suggests a planned test was omitted.

**Required correction:** either add the missing test and identify it, or correct the totals. Prefer verifying named new tests plus the baseline instead of treating a total alone as proof.

### P2. The source-diff gate does not prove bit accuracy

The `awk | diff | grep` command only searches added pre-`@gfx` lines for `log`, `pow(10)`, or `dB`. It does not detect changes to signal assignments, coefficient code, routing, memory aliases, or existing expressions. Its “expected no output” pipeline also returns a nonzero status when grep finds nothing, which can be mistaken for command failure.

**Required correction:** retain this as a narrow forbidden-token check, but add an explicit reviewed diff against V0.9 and a source-level guard for untouched audio functions. The null test remains the behavioral authority.

## Recommended Plan Repair Order

1. Redesign cache ownership: independent engine publication or whole-pair copy, named metadata slots, and a concrete reader protocol.
2. Complete the Python model for separate HP/LP grids and bit-domain interpolation.
3. Fill in the missing JSFX magnitude, invalidation, trace-cache, interaction, and export code.
4. Fix Macro/Micro endpoints, snapping parity, and change-only automation.
5. Expand oracle coverage and make the transcription/CPU gates mandatory and measurable.
6. Correct the stale rev-5 acceptance items and test counts, then hand the plan to implementation workers.
