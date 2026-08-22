# RCBitNova V1.1 Eight Bands Plan Rev 2 - Weakness Review

**Reviewed:** `docs/superpowers/plans/2026-08-19-rcbitnova-v1.1-eight-bands.md`,
Revision 2 at commit `ea2d5d4`, against spec rev 4 and the shipped
`JSFX/RCBitNova V1.0` source.

**This is a fresh review.** The earlier `eight-bands-weaknesses.md` reviewed rev 1; its thirteen
findings are dispositioned at the end of the current plan and are not repeated here.

## Coverage verdict

The plan accounts for all 28 authoritative sites from spec section 3.2:

| Sites | Count | Plan disposition |
|---|---:|---|
| count declaration | 1 | Task 6 flips `N_BANDS` |
| `@init` static state plus dynamic allocations/bases | 18 | Task 3 keeps `st` on `N_BANDS` and converts the other 17 to `N_DYN` |
| GUI domain helpers | 2 | remain on `N_BANDS`, checked by Task 9 |
| `@slider` setup and Mode-B scan | 2 | Task 5 splits setup and bounds the scan by `N_DYN` |
| `@sample` first pass and Mode-B pass | 2 | Task 5 creates a structural static loop and bounds Mode B by `N_DYN` |
| `@gfx` setup, hit-test, draw | 3 | remain on `N_BANDS`, checked by Task 9 |
| **Total** | **28** | no unassigned site |

No additional four-band production array was found in V1.0. `cf` and `st` grow to their exact
zero-slack boundaries; detector, envelope and Mode-B arrays remain four-band via `N_DYN`; and
`gc_kc` is the one GUI scratch array that must grow. The main remaining risk is that the plan does
not enforce this correct inventory early or completely enough.

## Findings

### P0-1 - Task 6 depends on a gate that Task 9 has not created

Task 6 line 814 runs `tools/rcbitnova_gates.py --source-only`, explicitly annotated as "written in
Task 9". Its fallback is only the two greps from Tasks 4 and 5. Those greps check open-coded slider
arithmetic and forbidden dynamic identifiers in the new static loop; they do not verify the 17
`@init` count conversions or compute a single base address.

This is the first commit that sets `N_BANDS = 8`, so a missed address site can silently relocate the
map exactly as spec section 3.2 warns. Watching for a REAPER memory error (Task 6 line 825) is not a
valid fallback: the documented failure is silent corruption with no load error.

**Required:** create and run the complete 28-site and computed-address source gate before the Task 6
flip. Moving only `--source-only` implementation ahead of Task 6 is sufficient; REAPER-dependent
null, manifest and CPU gates can remain in Task 9.

### P0-2 - Migration copies the wrong `Bypass`

V1.0 declares `slider1` with the parameter name `Bypass`, while REAPER also appends a host-special
parameter named `Bypass` after the 95 declared parameters. `_by_name()` returns the first match, so
Task 8 line 1088 reads declared parameter 0 instead of host parameter 95. Lines 1103 and 1114 make
the same mistake on V1.1. The true host bypass is never copied or verified.

This also contaminates Task 9's null test because that test uses the migration script to establish
equal state.

**Required:** address the measured host tail positionally after validating its names, or use stable
host parameter identifiers. For V1.0 read indices `95..97`; for V1.1 locate the validated three-item
tail after its 131 declared parameters. Do not use an unqualified name search.

### P1-1 - Plan and authoritative spec disagree on the GUI memory contract

Spec rev 4 sections 2.1 and 6.1 pin the clear span to `13670`: V1.0's `13638` plus 32 words for the
larger `gc_kc`. The plan adds an eight-word `gc_hits` buffer and instead requires `13678`. Both
cannot be the acceptance contract.

Task 3 also calls its work a no-op rewrite while immediately clearing the final eight-band span even
though `N_BANDS` is still 4. That writes 32 words beyond the then-current named eight-word-hit GUI
region. Padding makes it unlikely to affect audio, but it defeats the claimed byte-identical
intermediate and leaves the clear size hand-coded.

**Required:** revise the spec to include `gc_hits` and `13678`, or redesign cycling without the new
buffer. Then derive the production clear span from `gc_hits + 8 - gc_trace` and use the count-correct
value at each intermediate task.

### P1-2 - The address model does not actually run "through lp_base"

`AUDIO_CHAIN` ends at `lp_ks`. It omits `lp_geo`, `lp_off`, `lp_fs`, and the bridge from `lp_fs` to
`gc_trace`. Task 9 compares exact values only for names returned by that incomplete model, then
checks merely that `lp_base` is divisible by 65536. A wrong but page-aligned `lp_base`, overlap in
the omitted tail, or an incorrect GUI end can pass.

The negative test for a missed dynamic site is also not a gate test: it edits only a copied
`mb_peak` value and asserts that the manually introduced difference equals 16384. It neither
recomputes downstream addresses nor proves that `eval_init()` rejects the defect.

**Required:** model and compare every audio base named by spec section 6.3 through exact
`lp_base == 65536`; model the complete GUI interval and assert ordering, non-overlap, exact clear
span and `end < lp_base`. Mutate a fixture source and assert that the real source gate fails.

### P1-3 - Task 9 is still a specification of gates, not an executable implementation plan

The central `SITES` table literally contains `# ... all 28`, and `eval_init()` is called without a
parser or evaluator design. The null-render and CPU scripts are prose only. Important mechanics are
unresolved: how fresh instances are created, how V1.0 is rendered before migration removes it, how
latency and samples are read, and how peak block time and xruns are measured repeatably.

This matters because Task 6 and the release checklist treat these files as available, deterministic
gates. The plan cannot currently be executed by transcription, and a partial implementation can
still print the expected success labels.

**Required:** include the complete 28-entry table and concrete implementations or pinned helper APIs
for `eval_init`, rendering, latency comparison, timing and xrun detection. Add self-tests that force
each gate to fail.

### P1-4 - Migration is not transactional for arbitrary existing chains

On failure, Task 8 deletes the first FX whose name contains `RCBitNova V1.1`, not the instance it
just created. A track that already contains V1.1 can lose the wrong FX. Likewise the source is found
again by a non-unique name after the move. An undo block groups operations; it does not itself roll
back an exception, so the returned claim `source untouched` is stronger than the code proves.

The prose says modulation, pin mappings, aliases and oversampling metadata require manual migration,
but the script does not detect or refuse any of them. Running it can therefore silently discard
state that the plan explicitly calls out of scope.

**Required:** retain identity/GUIDs for the exact source and destination, verify them after the move,
and restore via an actual undo on every failed post-mutation path. Implement refusal checks for the
listed unsupported state, or remove the claim that such instances are safely refused.

### P1-5 - Q Character numeric entry violates the slider's value contract

Task 7 says typed Q Character values are committed "unquantised", but the slider declares a 0.001
step. V1.0's GUI writers deliberately quantise values to declared steps to preserve host/GUI
round-trips and null behaviour. An arbitrary parsed float can therefore differ from a value set via
REAPER or the context menu.

**Required:** preserve full 0.001 resolution, but round the GUI write to `floor(v / 0.001 + 0.5) *
0.001` after clamping to `0..1`. "Full resolution" should mean no coarse 0.25-only restriction, not
no slider-step quantisation.

### P1-6 - The automated source gate does not cover writer safety

Task 5's grep expects six existing GUI writers. Task 7 later adds three writers, but Task 9 checks
only the 28 `N_BANDS` sites and open-coded slider arithmetic. It does not assert that all nine
writers have eight named branches, use the correct B5-B8 slider numbers, call `setup_band`, and
guard `setup_band_dyn` with `b < N_DYN`.

A transcription error here can write a wrong band or touch four-band dynamic memory while all 28
site assertions still pass.

**Required:** add a machine-readable nine-writer manifest, including per-band target slider IDs and
the guarded dynamic-setup requirement. Exercise every writer for B1-B8 in the live parameter gate.

### P1-7 - One normative GUI distinction has no implementation step

Spec section 5 requires static-only bands to have both a thinner node outline and a `DYN`/`STATIC`
tag. Task 7 implements the tag and selector strip but never changes V1.0's common
`gfx_circle(..., 6 * gc_sc, ...)` node drawing for B5-B8. The final reachability matrix also checks
only the tag.

**Required:** add an explicit node-rendering change and a visual/live check covering enabled and
disabled DYN and STATIC nodes at Retina scaling.

### P2-1 - `GuardedMemory` detects one-word overruns, not general out-of-bounds access

`GuardedMemory._check()` fails only when an address equals a guard word. An access that jumps over
the guard into the next array or any unowned address succeeds. The two negative tests happen to land
on first guards, so they do not prove the class's broad docstring claim.

**Required:** make accesses ownership-aware, for example `read(name, offset)` / `write(name, offset)`,
and reject every offset outside that array's span. Keep a separate absolute-address API only for
tests that intentionally model aliasing.

## Recommended revision order

1. Fix the host-tail migration bug and settle the `13670` versus `13678` spec contract.
2. Move a complete, self-tested source/address gate before Task 6.
3. Complete the address model and writer manifest.
4. Tighten migration identity/rollback and unsupported-state refusal.
5. Resolve the Q Character and thinner-outline GUI gaps.

