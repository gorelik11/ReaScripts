# RCBitNova V1.1 Eight Bands Implementation Plan: Weakness Review

**Reviewed:** `2026-08-19-rcbitnova-v1.1-eight-bands.md`
**Design baseline:** `2026-08-19-rcbitnova-v1.1-eight-bands-design.md`, revision 4
**Review posture:** executable task order, JSFX transcription correctness, GUI event flow, migration safety, and release-gate reproducibility

## Overall Assessment

The plan incorporates most of the design reviews well. It correctly keeps `bp` dynamic, expands `gc_kc`, creates a structural B5-B8 sample loop, adds the missing band controls, separates CPU regression from feature cost, and gives the 28 `N_BANDS` sites far more attention than the earlier design revisions did.

It is not safe to execute task-by-task yet. Task 3 deliberately creates, loads, and commits a memory-corrupting intermediate plugin before Tasks 4 and 5 remove the out-of-range dynamic accesses. Several GUI read sites are omitted from the slider-base conversion, and the migration script copies REAPER's special tail parameters into the new B5-B8 slider range, moves the FX to the end of the chain, and deletes the source without transactional verification.

## Findings

### P0. Task 3 creates and live-loads a knowingly invalid intermediate plugin

Task 3 changes `N_BANDS` from 4 to 8, then asks the implementer to load the plugin and commit it. At that point:

- the `@slider` loop still runs both `setup_band` and `setup_band_dyn` over `N_BANDS`, so B5-B8 write beyond `det`, `dp`, `dm`, and `bp`;
- the first `@sample` pass still runs over `N_BANDS` and reads `dp`/`dm` beyond their four-band allocations;
- the Mode-B pass still runs over `N_BANDS` and reads every dynamic array beyond its allocation.

Those fixes are deferred to Tasks 4 and 5. Disabled B5-B8 do not make the `@slider` setup writes safe, so Task 3 Step 7's claim that the plugin should already behave like V1.0 is false. The Task 3 commit also leaves a broken revision in history, contrary to the plan's own "all tests green at every commit" rule.

**Required resolution:** make the count change, both `@sample` splits, the `@slider` split, and the Mode-B bounds one atomic task completed before the first load or commit. Alternatively introduce `N_DYN` and convert all dynamic sites while `N_BANDS` remains 4, then raise `N_BANDS` only after every path is safe.

### P0. The slider-base transcription omits the interactive B5-B8 read sites

Task 3 Step 6 replaces open-coded arithmetic only in `band_qeff`, `setup_band`, `gc_band_setup`, `gc_band_bits`, `gc_domain_bits`, and `gc_dom_used`. V1.0 also open-codes `10 * (b + 1)` or its equivalent in:

- node hit-testing;
- click-to-enable;
- drag-start value capture;
- active drag reads;
- wheel-Q handling;
- node drawing;
- selected-band readout setup;
- the original B1-B4 sample and Mode-B loops.

The first seven execute for all eight GUI bands after their loop bounds grow. Without conversion, B5-B8 read sliders 51-89, which are dynamics controls, instead of 151-189. Their nodes, hover targets, drag origins, enable state, and readout will all disagree with their actual parameters.

**Required resolution:** enumerate every band-slider read site in the plan and convert all GUI-wide sites to `band_slider_base`. Add a source test that rejects `10 * (b + 1)`, `10*(b+1)`, and `10 * (gc_b + 1)` outside the helper and explicitly exempt only loops proven to stay below `N_DYN`.

### P0. Task 7 depends on a migration script that Task 8 has not created yet

The exact-null gate in Task 7 says to transfer state with the Task 8 script. Under the prescribed execution order, that file does not exist. This makes the release-gate task impossible to complete when reached and breaks the task-by-task workflow promised at the top of the plan.

**Required resolution:** move migration implementation and tests before the gates, or split the null-fixture state copier from the user-facing migration and implement the fixture helper earlier. Task 7 must depend only on artifacts produced by Tasks 1-6 and the preceding migration task.

### P0. Migration by `range(src.n_params)` corrupts the new-band defaults

V1.0 has 95 declared JSFX sliders followed by REAPER-owned special parameters such as Bypass/Wet/Delta. V1.1 inserts 36 new declared sliders before that host-owned tail. Therefore the complete V1.0 host list is not a strict prefix of the complete V1.1 list: only the 95 declared-slider prefix is stable.

The proposed migration reads all `src.n_params` and writes each value to the same numeric index in V1.1. Once it reaches the V1.0 special tail, those values land in V1.1's first new-band parameters instead of V1.1's corresponding host-special parameters. The stated expectation of 97 values is itself unverified and omits at least one special identifier on REAPER builds that expose Bypass, Wet, and Delta.

The parameter-manifest gate has the same mistake: `b[:len(a)] == a` includes the old special tail and should fail once new declared sliders are inserted before V1.1's new tail.

**Required resolution:** copy exactly the 95 declared JSFX parameters by index. Discover and copy host-special parameters separately through their stable identifiers (`:bypass`, `:wet`, `:delta`) where supported. Compare manifests as `old_declared == new_declared[:95]`, then verify the 36 new declarations, and verify host-special parameters separately rather than treating them as part of the prefix.

### P0. The migration changes FX-chain topology and is not transactional

`tr.add_fx("JS: RCBitNova V1.1")` appends the destination to the track, while `src.delete()` removes the original from wherever it was. If V1.0 was not the final FX, V1.1 moves to the end of the chain and changes the sound even when every parameter value is correct.

The script also does not preserve enabled/offline state, wet/dry/delta/bypass state by stable identifier, pin mappings, parameter modulation, aliases, or oversampling metadata. It deletes the source immediately after assignments without first reading the destination back, checking defaults for B5-B8, or wrapping the operation in an undo block. A partial failure can leave two FX; a false-success path can delete the only known-good instance.

**Required resolution:** define the migration's supported state surface, insert or move V1.1 to the exact source index, copy stable host properties explicitly, verify all copied values and all 36 defaults before deleting V1.0, and wrap the replacement in one undo transaction. On any mismatch, delete the destination and leave the source untouched.

### P1. The context-menu snippet has unresolved string and event-order dependencies

`gfx_showmenu` receives one menu string. The proposed snippet places a ternary string expression directly beside several more string literals without constructing a single `#string` buffer or showing a supported concatenation operation. The plan contains no compile test for this code.

It also uses `gc_rclick`, which V1.0 currently computes later in the HP/LP section. The plan does not pin the insertion point or instruct the implementer to move right-click edge detection before both band and HP/LP consumers. Inserted near the band nodes, the menu reads the previous frame's value; inserted later, it must still ensure the current `gc_hover` and click routing remain coherent.

**Required resolution:** provide one compilable menu-string construction, compute `gc_rclick` once beside `gc_click`, and route the event to exactly one context-menu owner before either menu executes. Add a live compile/load check immediately after the menu is introduced.

### P1. Coincident-node cycling is an unfinished algorithm, not an implementation step

Task 6 only updates `gc_cyc_n`, `gc_cyc_x/y`, and a timestamp. It never:

- builds the hit set;
- counts its members;
- wraps `gc_cyc_n` modulo that count;
- selects the nth matching band;
- places this selection before click-to-enable and drag start;
- resets on pointer movement without a click as required by the spec.

The prose "`gc_hover` then selects" leaves the most failure-prone part to the implementer, while the self-review claims every code step carries real code. After enough repeated clicks, the shown counter can simply exceed the hit-set size and select nothing.

**Required resolution:** include the complete hit-set and selection code, its exact position in `@gfx`, initialization, modulo behavior, and interaction with enabling/dragging. Add deterministic tests or a scripted live matrix for one, two, and three coincident nodes, including disabled nodes and timeout/movement resets.

### P1. The Q Character menu loses the slider's declared resolution

The slider supports `0..1` in `0.001` steps, but the context menu exposes only 0, 0.25, 0.5, 0.75, and 1. Existing values such as 0.333 can be displayed by the audio engine but cannot be reproduced or edited accurately from the custom GUI. This is weaker than the stated nine-parameter reachability contract.

**Required resolution:** add a numeric Q Character field or a fine adjustment gesture that reaches the declared 0.001 grid. If the five presets are an intentional product simplification, say so explicitly and narrow the reachability claim from the full parameter contract to those five values.

### P1. The shadow layout never performs bounds testing

`shadow_layout()` only rebases arrays with gaps, and its test only proves those gaps exist. No model writes coefficients or state through translated addresses, no guard values are initialized, and no post-processing assertion checks them. It therefore cannot detect any overrun from the actual setup or sample algorithms.

**Required resolution:** add an instrumented memory object with guarded slices and run modeled setup/static/dynamic accesses through it, or narrow the claim to "layout spacing model." A test that merely allocates room for guards is not the bounds/overrun detection promised by the design.

### P1. The `N_BANDS` occurrence-count gate is brittle and likely has the wrong expectation

`grep -c "N_BANDS"` counts lines, including comments, rather than semantic sites. After the planned transformation, the executable occurrences are the declaration, static-state clear, two curve helpers, static setup loop, static-only sample loop, and three GUI loops: nine code lines. Added comments can change the count without changing behavior, while two occurrences on one line count once.

The plan expects 11 based on "declaration + 8 static + 2 split," which does not match the final source shape where split sites become separate `N_BANDS` and `N_DYN` lines.

**Required resolution:** replace the raw count with explicit source assertions for every expected site and explicit rejection of `N_BANDS` at every dynamic site. The 28-site table is already available; encode that table rather than reducing it to a comment-sensitive count.

### P1. The audio-address manifest is still a visual grep review

Task 7 prints address expressions from both files and asks a human to decide that they are equivalent except for `N_BANDS` becoming `N_DYN`. It neither evaluates the expressions nor compares them against fixed expected word indices. A typo that preserves plausible-looking text can pass the process.

The new Python layout model covers only the low arrays through `eg`, not the large Mode-B rings and the downstream audio bases that motivated the 28-site audit.

**Required resolution:** extend the machine-readable layout through `lp_base`, calculate the V1.0 and V1.1 addresses, and assert exact expected word indices. Keep the grep as diagnostic output, not the release gate.

### P1. The parameter-manifest gate tests names only

The design requires index, name, min, max, step, default, and round-trip value. Task 7 records only `(index, name)`, then deletes the temporary effects. It cannot detect a changed range, step, default, enum shape, raw-vs-normalized mismatch, or a new parameter initialized incorrectly.

**Required resolution:** produce a self-describing manifest for the 95 declared parameters and 36 additions, including ranges, step sizes, defaults, and set/get round trips at representative values. Handle host-special parameters separately as described above.

### P1. Null and CPU gates still have no executable tooling

The fixture conditions are much better than earlier revisions, but Task 7 provides no command or file that creates deterministic material, renders both variants, checks length/latency, compares samples at zero tolerance, measures block time, or counts xruns. The migration snippet itself defaults to dry-run and cannot perform the null transfer at this point in the task order.

These steps remain manual prose in an otherwise executable plan, so two workers can implement materially different gates and both mark the checkboxes complete.

**Required resolution:** add dedicated scripts or ReaScripts with exact invocation commands and machine-readable pass/fail output. Store the null comparator and benchmark harness in the repository, and make Task 7 fail nonzero on a sample mismatch, missing case, xrun, or CPU regression.

## Strengths To Preserve

- The plan correctly accepts all four rev-2 P0 findings instead of papering over them.
- The dedicated static-only loop is structurally safer than a large conditional inside the dynamic loop.
- `gc_kc` growth, the 13670-word clear, and the full audio-base inventory now match the rev-4 design.
- Explicit named writers and guarded `setup_band_dyn` calls reflect live JSFX behavior rather than assumed computed writes.
- The context menu and selector strip address genuine reachability gaps in V1.0.
- Separating null regression, feature CPU cost, migration, and final live review is the right release shape once their tooling is executable.

## Recommended Gate Before Execution

Fix the five P0 issues first: make the count/split changes atomic, complete every slider-base read conversion, move migration before the gates, separate declared parameters from REAPER's special tail, and make FX replacement positional and transactional. Then provide complete event-flow code for the menu/cycler and turn the layout, manifest, null, and CPU checks into machine-executed gates rather than grep output or manual observations.
