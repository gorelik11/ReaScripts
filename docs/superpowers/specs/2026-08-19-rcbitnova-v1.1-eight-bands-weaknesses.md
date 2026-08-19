# RCBitNova V1.1 Eight Bands Design Rev 2: Weakness Review

**Reviewed:** `2026-08-19-rcbitnova-v1.1-eight-bands-design.md`, revision 2
**Review posture:** adversarial memory-layout review, static/dynamic ownership, GUI reachability, migration semantics, and executable release gates

## Overall Assessment

Rev 2 resolves the original review's main conceptual defects. The fixed-address boundaries are now stated correctly, the Mode-B order is normative, computed reads and named writes are separated, the host-parameter prefix is treated as an ABI, and the verification section is much closer to a release contract.

The specification is still not implementation-ready. Two memory claims now contradict the shipped V1.0 layout, one array is assigned to the wrong ownership count, and the proposed "static-only" path does not explicitly remove dynamic reads embedded in V1.0's static loop. The GUI also still cannot configure all nine parameters of a new band or turn an enabled band off, so the reachability premise is only partially true.

## Findings

### P0. Eight GUI coefficient sets cannot fit while every `gc_*` base remains unchanged

V1.0 lays out the GUI scratch contiguously:

```text
gc_meta + 16 -> gc_kc, 32 words (4 bands x 8)
gc_kc + 32   -> gc_fc
gc_fc + 126  -> gc_ebuf
```

At eight bands, `gc_kc` needs 64 words. The direct parameterized implementation `gc_kc + b * 8` therefore overwrites the first 32 words of `gc_fc` for B5-B8. Expanding `gc_kc` normally shifts `gc_fc` and `gc_ebuf` by 32 words, contradicting verification item 3's requirement that "every `gc_*` base" remain byte-equal to V1.0.

The initializer also hard-codes `memset(gc_trace, 0, 13638)`. A 32-word expansion requires recalculating that span; otherwise part of the enlarged region remains stale.

**Required resolution:** choose and document one layout:

- expand contiguous `gc_kc` to 64 words, move `gc_fc`/`gc_ebuf`, update the clear span from 13638 to 13670, and assert only the audio-critical bases plus `lp_base == 65536` remain unchanged; or
- keep the old bases and place B5-B8 coefficients in a separately named 32-word region, with a `gc_band_coef_base(b)` helper and explicit ownership of the currently reserved `gc_snap` space if it is reused.

Add non-overlap assertions for `gc_kc`, `gc_fc`, and `gc_ebuf`, plus a GUI curve test with all eight bands enabled and both HP/LP coefficient regions populated.

### P0. `bp` is dynamic state, not an eight-band static array

Rev 2 classifies `bp` under `N_BANDS` and tests `bp + N_BANDS * 3 <= eg`. In V1.0, however:

- only `setup_band_dyn(b)` writes `bp`;
- Mode A and Mode B are its only readers;
- the static SVF path never reads it.

The same revision correctly requires `setup_band_dyn(b)` to be skipped for B5-B8. Their proposed `bp` slots would therefore be uninitialized and unused. Expanding this array contradicts the core rule that everything dynamic remains at `N_DYN = 4`.

**Required resolution:** move `bp` to the `N_DYN` column, keep it at 12 words, and remove the eight-band `bp` boundary assertion. If `bp` is intentionally being promoted to shared static state, specify which static code writes and reads all three fields and why that refactor is needed.

### P0. V1.0's "static" loop reads `dp` and `dm` before entering a dynamics branch

The current first pass does not isolate static filtering from dynamics cleanly. For every enabled band with Placement Both, it evaluates:

```text
dp[b*4+3] == 1 && dm[b] == 2
```

to decide whether the static SVF should run in L/R or M/S. The later Mode-A conditions also read `dp` and `mbmode`. Merely changing the outer loop to `N_BANDS` and guarding `setup_band_dyn` is not enough: B5 immediately reads past the four-band arrays before its static filter runs.

**Required resolution:** make the two paths structural, not just conditional prose:

1. B1-B4 retain the existing domain selection and Mode-A code.
2. B5-B8 use a dedicated static-only path in which Placement Both always means L/R and no expression mentions `dp`, `dm`, `mbmode`, `bp`, `det`, `dst`, `cst`, `eg`, `egh`, or `hc`.

Add read canaries or an instrumented bounds model, not only write canaries, and exercise Placement Both on every new band. The source audit should reject dynamic-array identifiers inside the B5-B8 path.

### P0. The custom GUI still does not expose the complete new-band contract

Each new band has nine sliders, but the inherited V1.0 GUI can reach only six:

- Enable, indirectly, by clicking a disabled node;
- Frequency, Q, Macro, Micro, and Bit Ratio through gestures or fields.

There is no band control for Type, Placement, or Q Character in V1.0's custom GUI. There is also no inverse of the enable gesture: clicking a disabled node turns it on, but an enabled band cannot be turned off. The new B1-B8 selector and `DYN`/`STATIC` label do not address these missing operations.

This undercuts the stated reason that the graph removes the 131-slider reachability blocker. B5-B8 would be usable only as Bell/Both/constant-Q bands unless the user returns to REAPER's parameter machinery, and once enabled they cannot be disabled from the custom UI.

**Required resolution:** define a selected-band control surface or context menu for Enable/Disable, Type, Placement, and Q Character. All writes must use explicit named-slider branches and preserve the one-gesture-one-slider rule. Add a 9-parameter reachability matrix for B5-B8 and prove every declared value can be set and read back without opening the generic parameter list.

### P1. Runtime canaries "either side" are impossible at the two zero-slack boundaries

The corrected arithmetic proves that `cf` ends exactly where `st` starts and `st` ends exactly where `det` starts. There is no spare word in which to place a guard. A sentinel at `cf[64]` is `st[0]`, which legitimately changes during audio processing; a sentinel at `st[96]` is `det[0]`, which coefficient setup legitimately owns.

The same problem occurs at several adjacent dynamic regions. Writing production-layout canaries "either side of every expanded array" either corrupts valid state or observes expected state changes as false failures.

**Required resolution:** distinguish three tests explicitly:

- compile/source arithmetic assertions for exact production addresses;
- an instrumented shadow layout with guard words for bounds testing;
- value/invariant tests on the real compact layout without inserting sentinels into neighboring arrays.

Do not claim that physical red-zone canaries exist in a layout whose safety property is zero slack.

### P1. The downstream address manifest is incomplete and uses the wrong unit

Verification item 3 says every downstream base is preserved but omits `lp_kc`, `lp_ks`, `lp_geo`, `lp_off`, and `lp_fs`, all of which sit between `lp_rt` and the GUI block. A shift in any of them can invalidate packed-engine geometry even when the listed endpoints happen to match.

The phrase "byte-equal" is also inaccurate for EEL2 memory: these are word indices, not byte addresses.

**Required resolution:** list every base from `hplp_state` through `lp_base` in order and compare exact word indices. Exempt the GUI bases that must move under the chosen `gc_kc` solution, while requiring their ranges to remain below `lp_base` and non-overlapping.

### P1. The supported migration operation is still an unresolved alternative

The spec says state is transferred by "preset or FX-chain copy" and includes automation envelopes. Those are not one operation with equivalent semantics:

- a preset is plugin-identity-specific and normally carries parameter state, not track automation envelopes;
- copying an FX instance normally copies the original V1.0 identity rather than translating it into a V1.1 instance;
- automation envelopes live at the track/FX parameter level and need an explicit remapping procedure.

Section 4 also still says "an old project therefore opens with four inaudible extra bands," while section 6 correctly says an old project simply reopens V1.0. Both cannot be true.

**Required resolution:** choose one tested migration mechanism. If it is a ReaScript/state-chunk migration, specify how it replaces the FX identity, copies the old 95 values, appends the 36 defaults, and preserves or recreates each automation envelope by host parameter index. If no migration tool ships, narrow the compatibility claim to manual preset recreation and remove automation preservation and the "old project opens" statement.

### P1. The exact-null fixture is still missing an executable comparator contract

Rev 2 pins the broad conditions but not the actual sample rate, block size, input duration, pre-roll/state reset, output capture path, or comparison command. "Bit-identical" implies a zero-tolerance sample comparator, but the test could still be implemented as a meter observation or a floating-point threshold and be reported as passing.

**Required resolution:** name the render/capture method and exact comparator, fix the numeric fixture values, compare both channels sample-for-sample, and fail on a length or latency mismatch. Include at least one non-default state with all old bands active, both Mode A and Mode B cases, and Min plus Linear topology cases; a single default-state null does not cover the loops being edited.

### P1. The CPU ceiling lacks a stable measurement protocol

The fixture now has sample rate, block sizes, duration, configurations, zero xruns, and a +10% limit, which is a substantial improvement. It still does not say how peak block time is captured, how many repetitions run, whether the first run is warm-up, or how background scheduling noise is handled. A single 60-second maximum is dominated by one unrelated OS scheduling spike and is not a reproducible +10% metric.

Comparing V1.1 with eight enabled filters against V1.0 with only four also mixes feature cost with regression. That can be a product budget, but it should not be described as a like-for-like regression.

**Required resolution:** separate two comparisons: V1.1 with B5-B8 disabled versus V1.0 for regression, and V1.1 eight-enabled versus V1.1 four-enabled for feature cost. Pin the measurement source, warm-up, repetition count, aggregation statistic, and allowed variance; retain zero xruns as an absolute gate.

### P2. Coincident-node cycling is not operationally defined

"Selected node wins" and "repeated clicks cycle" conflict unless the cycling rule explicitly overrides selected-node priority. The spec also does not define the coincidence tolerance, whether cycling resets after pointer movement or time, or whether disabled nodes participate.

The B1-B8 selector strip provides a deterministic escape, so this is not blocking.

**Required resolution:** define the hit set, cycle order, reset condition, and precedence over selected-node priority. Test exact and near overlap with enabled and disabled mixtures at normal and Retina scale.

## Rev-1 Findings Resolved In Rev 2

The following original findings are substantively closed and should remain preserved:

- `cf` and `st` now use correct adjacency assertions rather than the unsafe `cf <= 96` bound.
- Signal order is normative: B5-B8 run before Mode B, and a discriminating test is specified.
- Computed slider reads and explicit named writes are correctly separated.
- Writers are required to guard `setup_band_dyn` for static-only bands.
- The old host-parameter prefix, enabled-band oracle coverage, overlap escape, capability label, and CPU budget are now explicit verification concerns.
- The misleading "ninth node," contiguous slider-range wording, and literal "costs nothing" audio claim were corrected.

## Strengths To Preserve

- Eight static/four dynamic remains the correct scope for the current memory budget.
- The zero-slack `cf`/`st` layout is now documented honestly, including the eight-band maximum.
- The Mode-B ordering decision is clear and testable rather than being left to implementation taste.
- Eight-way named writes respect the live V1.0 discovery that computed slider writes are not host-safe.
- Per-band enabled response oracles, a host manifest, an exact-null intent, and downstream-layout checks are the right release gates once made executable.
- A deterministic B1-B8 selector is a good fallback for overlapping nodes.

## Recommended Gate Before Planning

Resolve the four P0 items before producing an implementation plan: choose a valid eight-band GUI scratch layout, keep `bp` under `N_DYN`, define a truly dynamic-free B5-B8 sample path, and expose every new band parameter plus disable from the custom GUI. Then replace impossible production canaries with an instrumented bounds test, complete the word-address manifest, choose one real migration mechanism, and turn the null and CPU prose into named executable fixtures.
