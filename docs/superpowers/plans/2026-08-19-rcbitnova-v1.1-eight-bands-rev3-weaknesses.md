# RCBitNova V1.1 Eight Bands Plan Rev 3 - Weakness Review

**Reviewed:** `docs/superpowers/plans/2026-08-19-rcbitnova-v1.1-eight-bands.md`, Revision 3 at
commit `6dda781`, against spec rev 4, the shipped `JSFX/RCBitNova V1.0`, the two earlier weakness
reviews, and the public REAPER ReaScript API.

**Scope:** this review does not repeat closed rev-1/rev-2 findings. It tests whether rev 3's
dispositions are executable and whether the new gates would reject the defects they claim to cover.

## Coverage verdict

The implementation tasks still account for all 28 authoritative sites on paper, and no additional
four-band production array was found in V1.0. The new Task 6 gate does **not** encode that same
inventory, however: its list has 28 entries only because it includes non-authoritative additions
while omitting five authoritative runtime sites. The plan's manual coverage and its claimed machine
coverage therefore have different answers.

## Findings

### P0-1 - The pre-flip source gate is required to fail

Task 6 runs while `N_BANDS` is deliberately still 4, but its first site assertion requires 8.
Task 6 Step 5 acknowledges that failure while still invoking the same `--source-only` command that
is documented to exit nonzero on any failure. There is no `--preflip` mode, expected-failure wrapper,
or temporary eight-band projection.

The address assertions are phase-inconsistent too. Before the flip, V1.1's
`gc_fc - v10.gc_fc` is 0, but the gate unconditionally requires 32. Thus the command cannot pass
"everything except the N_BANDS row" as claimed. If these failures are tolerated, the same command
in Task 7 no longer proves that the flip is safe.

**Required:** define two explicit contracts. `--preflip` must require `N_BANDS == 4`, unchanged
`gc_fc`, and every preparatory conversion; `--source-only` after the flip must require 8 and the
32-word GUI shift. Better still, have pre-flip validation create an in-memory source projection
with only `N_BANDS` changed to 8 and run the full post-flip contract against that projection.

### P0-2 - `eval_init` computes `ceil()` incorrectly

The evaluator implements `_ceil` as `lambda x: -(-int(x) // 1)`. Converting to `int` happens before
the ceiling, so every positive fractional value is truncated: the real `ceil(51913 / 65536)` is 1,
but this function returns 0. It therefore evaluates V1.0's `lp_base` as 0 instead of 65536 and fails
its own exact-address assertion in both phases.

**Required:** use `math.ceil` after validating the AST. Add direct evaluator tests for values below,
at, and above a page boundary, including the shipped `lp_base` expression.

### P0-3 - The "complete 28-site table" omits the dangerous runtime sites

The 28 entries shown in Task 6 are not the 28 sites from spec section 3.2. The table adds
`N_DYN`, `gc_kc`, and `gc_fc`, and represents the setup split as two rows, but omits:

- the first `@sample` loop bounded by `N_DYN`;
- the Mode-B `@sample` pass bounded by `N_DYN`;
- all three `@gfx` loops: coefficient setup, hit-test, and node drawing.

Leaving the Mode-B pass on `N_BANDS` reads and writes four-band dynamic arrays after the flip, yet
the advertised 28-site gate can pass. The Mode-B scan row is also unmatchable as written: its regex
expects the first line after `loop(N_DYN,` to be `slider(50 + 10*b + 1)`, while the actual loop starts
with `mbmode[b] = slider(50 + 10 * b + 7)`.

**Required:** derive a one-to-one manifest from the authoritative spec rows and give split sites
named sub-assertions without using the displayed list length as proof. Seed one defect in every
runtime loop, not just `@init`, and require rejection.

### P0-4 - Migration can fail before entering its rollback block

Task 9 begins the undo block, calls `tr.add_fx`, and dereferences `dst.index` to obtain `dst_guid`
before entering `try`. If `add_fx` returns `None` or raises, exactly the failure Step 4 intends to
exercise, no exception handler runs: the undo block remains open and the script can leave an orphan
or partially created destination.

**Required:** put every operation after `Undo_BeginBlock2`, including `add_fx` and GUID acquisition,
inside `try/finally`. Initialize `dst_guid = None`, close the undo block exactly once on every path,
and test both an exception and a `None` return from `add_fx`.

### P0-5 - The CPU gate is built on ReaScript metrics that do not exist

Task 10 says peak block time and an audio-underrun counter come from `GetSetProjectInfo`. The public
API's documented project-info keys contain render/project settings, not Performance Meter values.
The public xrun function is `GetUnderrunTime`, which returns the timestamps of the last audio/media
xruns rather than a counter. `GetAudioDeviceInfo` exposes only mode, device identifiers, block size,
sample rate, and bit depth. See the
[official REAPER ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html).

Consequently `tools/rcbitnova_cpu.py` cannot implement the pinned table as written, and an absolute
release gate has no data source.

**Required:** first prove a real API for peak/longest block time on this REAPER build, or reclassify
CPU measurement as a controlled manual Performance Meter protocol. Use `GetUnderrunTime` with
timestamp windows for xruns, and test that the chosen signal changes when an xrun is deliberately
induced.

### P1-1 - The address gate still does not compare the complete GUI map

Task 6 computes `model_gui` but never uses it. Source values are checked only for ordering, the
`gc_fc` delta, exact `lp_base`, and `end < lp_base`. A wrong `gc_snap`, `gc_meta`, `gc_ebuf`, or
`gc_hits` base can remain ordered and below the page boundary and still pass. The production
`memset(gc_trace, 0, gc_hits + 8 - gc_trace)` expression is not asserted at all.

`GUI_ORDER`, `check_source`, the site matcher, CLI handling and `SEEDED_DEFECTS` are also referenced
but not implemented in the plan snippets, despite Task 6 being presented as a transcription-ready
gate.

**Required:** compare every source GUI base exactly to `model_gui`, assert the clear expression or
its evaluated end, and provide the complete runnable `check_source` path. Seed defects in every GUI
base and in the clear span.

### P1-2 - The parameter "full record" omits both step and default

Task 10 says each record contains index, name, min, max, step, default, and round trips. The shown
`record()` returns index, name, range, `p.formatted`, and round trips. It never reads step or default;
`p.formatted` is the current value's display string, not either one. Two incompatible slider
declarations can therefore compare equal if their current formatted values happen to match.

**Required:** obtain min/max/mid and step/toggle/enumeration data from the relevant parameter APIs;
capture defaults from independently fresh instances before any probes; then restore and verify the
original normalized value after every record.

### P1-3 - The automated writer gate has no way to invoke a GUI writer

The live gate says it will "drive" each of nine internal EEL2 `gc_w_*` functions from the GUI and
observe the manifest through reapy. Reapy can set host parameters, but it cannot call an internal
JSFX function; setting the parameter externally bypasses the writer being tested. No GUI automation,
coordinates, menu navigation, or test-only JSFX hook is specified.

**Required:** either make writer correctness a complete source-level structural gate and keep the
existing reachability matrix manual, or specify a real GUI-driving harness that invokes every
gesture/menu/numeric path and proves which parameter changed.

### P1-4 - The null gate can quantise away a nonzero residual

The render format, bit depth, dither, normalization, render source/bounds, track selection, and
state restoration are not pinned. `wave` + `array` reads PCM, so choosing an integer PCM format can
turn a small real difference into identical quantised samples. Conversely, Python 3.11's `wave`
module does not provide a general IEEE-float WAV reader, so merely selecting float render does not
complete the proposed implementation.

The deterministic 30-second fixture is said to be committed, but it is absent from the file list
and no task creates it. `Main_OnCommand(41824, 0)` uses global render settings; "one track per
version" does not state how the other track is excluded from each render or how completion is
awaited.

**Required:** add the fixture as a named artifact; save, set and restore every render property;
render one selected-track stem at a time with dither/normalization disabled; use 64-bit float and a
tested float-WAV reader (or direct sample capture); and prove the comparator fails on a seeded
sub-PCM-level difference.

### P1-5 - Destructive migration has no offline REAPER tests

The migration task goes directly from a code block to live dry-run and destructive tests. Local
REAPER protocol requires the Python/ReaScript wrapper to be tested against an in-memory fake before
any live mutation. This is especially important here because correctness depends on index shifts,
GUID identity, undo closure, insertion failure, and preserving unrelated FX.

**Required:** add a focused fake for track FX enumeration, add/move/delete, GUIDs, parameters,
named config, enabled/offline state and undo calls. Assert the entire chain and undo balance after
every success/failure branch before running it in REAPER.

### P1-6 - Detectable host state is still silently discarded

The plan says pin mappings and per-FX oversampling are "not detected" and suggests adding checks if
REAPER exposes them. It does: `TrackFX_GetPinMappings` reads effective pin mappings, and
`TrackFX_GetNamedConfigParm(..., "instance_oversample_shift")` reads instance oversampling. The same
named-config API also exposes related chain settings.

**Required:** detect and refuse non-default pin maps and instance oversampling before mutation, or
explicitly migrate and verify them. Keep only genuinely unavailable metadata in the undetectable
warning.

### P1-7 - The selector strip shares the node click area without event ownership

V1.0 sets `gc_fy = gc_py + gc_ph + 6*gc_sc`. The proposed selector occupies
`gc_fy - 24*gc_sc .. gc_fy - 6*gc_sc`, which is the bottom 18 logical pixels of the graph. Nodes can
sit at that edge. Node click-to-enable and drag-start execute earlier than the selector code, so a
click intended to select B1-B8 can also enable or begin dragging a graph node underneath it.

**Required:** place the selector outside the plot or compute a selector-hot owner before node event
handling and suppress node click/drag/menu consumption when the selector owns the event. Add an
edge-clamped coincident-node case to the reachability matrix.

### P1-8 - The planned spec rev 5 leaves another known contradiction intact

Task 11 updates only `gc_hits` and the clear span. Spec rev 4 section 6.7 still says V1.0's full
host parameter list is a strict prefix of V1.1's, while the measured contract in the plan correctly
says only the 95 declared parameters are a prefix and the host tail moves.

**Required:** include section 6.7 in the rev-5 update: declared prefix by index, host-special tail
validated separately by position.

### P2-1 - The static-node drawing adds an outline instead of making it thinner

The spec asks for static-only bands to have a thinner node outline. Task 8 keeps the existing body
unchanged and adds a second outer ring only to static nodes. This increases their visual structure
rather than defining a thinner version of the same outline, and enabled filled nodes still have no
comparable dynamic outline weight.

**Required:** pin an actual two-style rendering rule for the same node primitive, then verify the
relative stroke at 1x and Retina scale. The textual `DYN`/`STATIC` tag remains the accessible cue.

### P2-2 - The one-node cycling expectation contradicts the algorithm

The matrix says a single node keeps the counter at 0, but every repeated click within 400 ms executes
`gc_cyc_n += 1`; only modulo one keeps the selected band unchanged. This does not break selection,
but the stated test cannot validate the implementation state it describes.

**Required:** either normalize `gc_cyc_n` by the current hit count or change the expected result to
"selection remains unchanged regardless of counter value."

## Recommended revision order

1. Repair Task 6's phase contracts, `_ceil`, and authoritative runtime-site manifest.
2. Replace the nonexistent CPU metric path and make the null render format truly bit-preserving.
3. Move all migration mutations inside rollback scope and add FakeReaper branch tests.
4. Complete exact GUI/address, parameter-record and writer-source gates.
5. Resolve selector ownership and finish the rev-5 spec corrections.

