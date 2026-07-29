# RCBitNova V0.7 — Final Whole-Branch Code Review (Fable)

**Scope:** `JSFX/RCBitNova V0.7` (967 lines) against frozen `JSFX/RCBitNova V0.6`, the oracle
`tools/rcbitnova_dsp.py` (129 tests, all passing), and design spec rev 3
(`2026-07-25-rcbitnova-v0.7-hires-linear-phase-design.md`) plus the two prior adversarial
reviews (Codex, my own rev-1/rev-2 pass). Role: error-finding and bit-accuracy verification
only — no rewriting.

## Verdict up front

**READY TO TAG.** No P0s. The three P0s raised against rev 1/rev 2 of the spec (dry-ring
overflow at High, unverified "free when off" memory claim, wrong `ext_tail_size`) are all
present and correctly fixed in the shipped V0.7 file, and I independently re-derived the
arithmetic rather than trusting the spec's prose. **Bit-accuracy: INTACT** — verified by grep
and by re-tracing every scalar in the linear-engine path.

---

## Verification performed (not just re-read)

1. **Recomputed all four packed-layout combinations independently** via
   `tools/rcbitnova_dsp.py::lp_packed_layouts` (base=0, P=2048):

   | e0 | e1 | e1 top | overall top | `page_layout_ok` |
   |---|---|---:|---:|---|
   | Normal | Normal | 229376 | **458752** | True / True |
   | High | Normal | 655360 | **884736** | True / True |
   | Normal | High | 229376→262144 (desbuf pushed to page) | **917504** | True / True |
   | High | High | 655360 | **1310720** | True / True |

   These match the spec's claimed tops exactly (458752/884736/917504/1310720), and match the
   task's expected values. `pytest tests/test_rcbitnova_dsp.py -q` → **129 passed**, including
   `test_packed_layouts_all_four_combinations`, `test_hires_desbuf_page_aligned_even_when_engine_base_is_not`,
   `test_runtime_latency_*` (6144 / 18432 / 24576 / 36864).

2. **Traced `lp_layout` (JSFX, lines 309–330) against `page_layout` (oracle, lines 1185–1204)
   term-by-term.** Buffer inventory order, per-buffer sizes, and the alignment rule (`unit =
   PB2` for Hspec/fdlA/fdlB, `unit = size` for the other FFT-touched buffers, no alignment for
   untouched buffers) match exactly. `lp_align(p,u) = ceil(p/min(u,65536))*min(u,65536)` is the
   same formula as `_round_up(ptr, min(unit, _LP_PAGE))`. `dry = BD>=32768 ? 32768 : 16384`
   (JSFX line 311) is byte-identical to the oracle's `lp_engine_buffers` dry-ring rule.

3. **`lp_base` / V0.5 boundary.** Scratch (`lp_rt`→`lp_off+32`, 137 words) sits contiguously
   right after `hplp_cf + 126` (V0.5's own end) with zero gap and zero overlap; `lp_base =
   ceil((lp_off+32)/65536)*65536` page-aligns the engine block start. No collision with V0.5
   memory, no collision between scratch and the engine block.

4. **Dry-ring defect (the real V0.6 bug) is fixed correctly and only where it should be.**
   Grepped every remaining `16384` literal in the file (lines 324/325 sizes, 423/439/453/454
   wraps) — all four are the **OUT ring** (FIFO, only needs to exceed hop `P`), left at 16384
   as required. The **DRY ring** (`ob[13]`/`ob[14]`, `lpk_process`'s `dryA`/`drd`/`dwp` wraps)
   reads `dryN = lp_geo[eng*4+3]` and wraps with it — confirmed per-engine, confirmed `dryN`
   (16384 Normal / 32768 High) always exceeds `lat` (6144 / 18432) so the single
   `drd < 0 ? drd += dryN` correction is always sufficient (no double-wrap needed).

5. **PDC / tail arithmetic re-derived independently:**
   - `lin_lat = lp_geo[2] + lp_geo[6]` — `lp_geo[eng*4+2]` is exactly where `lp_layout` writes
     `BD/2 + lpP` for that engine (`gb[2]` with `gb = lp_geo + eng*4`); for eng=0 that's index 2,
     for eng=1 index 6. Confirmed correct addressing, not an off-by-4 error.
   - `ext_tail_size = 2*lpP + lp_geo[0] + lp_geo[4] + Lk + 64`. At High+High with worst-case
     `Lk = MAX_LOOK-1 = 2047`: `4096+32768+32768+2047+64 = 71743 ≥ 71677` (the spec's own
     derived worst-case minimum). Covers it with 66 words of margin.
   - Reconcile block (sliders 604–611) executes **before** the PDC/tail computation (623–629)
     in the same `@slider` pass — confirmed by reading the file top-to-bottom, not assumed.

6. **Reconcile / stale-state check.** On a Resolution change (guarded by
   `slider140==1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4])`, i.e. only reconciles in
   Linear, exactly per spec §3.1): both engines' layouts are recomputed (engine 1 always,
   since its base depends on engine 0's span even if only engine 0 changed), the combined span
   is memset to 0, both Kaiser windows rebuilt at their own current `BD`, both runtime states
   reset via `lp_rt_reset` (`ir,cnt,out_rd,out_wr=P,fdl_wr,dry_wp` all zeroed, `out_wr=lpP`),
   both `*_dirty`/`*_built` forced so the very next `@block` rebuilds unconditionally
   (`hp_built==0` bypasses the 100 ms rate limit). While `Phase=Min`, the guard's `slider140==1`
   term is false, so Resolution changes touch nothing — confirmed by tracing the condition, not
   inferred from the comment. On Min→Linear with a stale selection, the same comparison against
   `lp_geo` (unchanged while Min) correctly detects the mismatch and reconciles before any Linear
   `@sample` code runs.

7. **Rebuild coalescing.** `time_precise()` is called only inside the `hp_dirty ?`/`lp_dirty ?`
   branches (no unconditional per-block call). `hp_built==0 || (time_precise()-hp_tbuild)>=0.1`
   guarantees the first build after any geometry/signature change is never delayed (short-circuit
   on `hp_built==0`), and `hp_dirty` is only cleared once a build actually runs, so a fast knob
   sweep cannot skip the final position — dirty persists across `@block` calls until served.

8. **EEL2 hazards, checked mechanically:**
   - `grep -n '[0-9]e[+-]\?[0-9]'` (excluding comments) → **no hits** — no scientific literals.
   - `grep -n 'gmem'` → only the two header/init **comments** documenting that gmem is
     deliberately *not* used; zero actual `gmem` accesses.
   - `grep -n 'log(\|pow(10\|20\*'` → **no hits** anywhere in the DSP path.
   - No `? ;` / `:;` empty ternary branches found.
   - All V0.7 functions (`lp_align`, `lp_layout`, `lp_relayout`, `lp_win_build`, `lp_rt_reset`,
     `lpk_build`, `lpk_run`, `lpk_process`) are defined textually (lines 307–488) **before**
     their first call from `@init` (lines 499–511) — verified by line number, not assumed.
   - `ceil`/`min` usages (`lp_align`, `lp_base`) match the established V0.6 pattern exactly.

9. **Bit-accuracy re-traced end to end for the linear engine.** The kernel-build normalization
   `inv = 1.0/BD` (line 398) is applied exactly once, in the kernel ifft
   (`ktime[i] = desbuf[src*2]*inv*wink[i]`). The runtime normalization `sc = 1.0/lpB` (line 425)
   is applied exactly once per hop, after `ifft(yacc, lpB)`, when writing to `outA`/`outB`. No
   other scalar appears anywhere in `lpk_build`/`lpk_run`/`lpk_process`/`lp_layout` — the linear
   engine remains a pure filter with **no gain stage**, exactly as V0.6. Everything downstream of
   the dedicated HP/LP section (bands, Mode A/B dynamics, output gain) is byte-identical text to
   V0.6 — confirmed by direct comparison, not a diff tool (both files were read in full).

10. **Min path and Linear-at-Normal path.** The `@sample` block's Min-phase branch
    (`hplp_run` calls, lines 658–660) and the entire post-HP/LP band/dynamics/Mode-B code
    (lines 665–967) are textually identical to V0.6's `@sample` (V0.6 lines 551–863). The
    Linear-at-Normal path is structurally identical to V0.6 (same `BD=8192`, `KM=4`, same
    algorithm) but reads offsets from `lp_off`/`lp_geo` instead of V0.6's hardcoded constants;
    the packed-layout arithmetic above confirms the addresses it resolves to reproduce V0.6's
    exact footprint (458752) and per-buffer geometry.

---

## Findings

**No P0 findings.** All three P0s from the pre-implementation reviews (dry-ring overflow,
unverified lazy-commit memory claim, truncating `ext_tail_size`) are fixed in the shipped code
and independently re-verified above (items 4, 5, 6).

### P2 — Kernel rebuilds still fire while `Phase = Min` (inherited from V0.6, not a V0.7 regression)

`hp_sig`/`lp_sig` (lines 614–617) are compared unconditionally in `@slider`, so tweaking HP/LP
Freq/Slope/Resonance while `Phase = Min` still marks the engine dirty and `@block` still runs
`lpk_build` — wasted CPU, since the kernel isn't used until Linear is selected. This was already
true in V0.6 (`lpk_build` calls were unconditional there too); V0.7 doesn't make it worse in the
common case, because while `Phase=Min` the *active* geometry (`lp_geo`) is whatever it last was
(default Normal on a fresh instance), so the wasted rebuild is cheap. It only becomes a 4×-cost
wasted rebuild if the user leaves an engine reconciled to High from a previous Linear session and
then tweaks Freq/Slope while parked in Min — a narrow, already-rare path. Not worth blocking the
tag; worth a one-line comment if V0.8 revisits rebuild cost.

### P2 — Resolution reconcile clears (and re-dirties) the *other* engine even when only one Resolution slider moved

Because `e1_base` depends on `e0`'s span, `lp_relayout` always relays out and memsets **both**
engines' full combined span, and the reconcile block always sets `hp_dirty=1; lp_dirty=1;
hp_built=0; lp_built=0;` together — even if, say, only `slider142` (LP Resolution) changed and
`slider141` (HP) did not. This means toggling LP's Resolution also wipes and forces a rebuild of
HP's kernel/runtime state, causing a brief HP glitch as a side effect of an LP-only change. This
is a direct, correct consequence of the packing design (documented in the spec, §5 item 4:
"a geometry change on either engine re-lays-out both") — not a bug, just worth naming explicitly
in case a future reader assumes only the touched engine resets.

No other findings. I did not find fabricated or inflated issues to pad this review — the
implementation matches the spec's rev-3 fixes precisely everywhere I checked the arithmetic.

---

## Explicit verdicts

- **BIT-ACCURACY: INTACT.** No `log`/`dB`/`pow(10)`/`20*` anywhere in the DSP path. The linear
  engine has no gain stage. The only two scalars (`1/BD` kernel-ifft, `1/B` runtime-ifft) are
  each applied exactly once, confirmed by direct code trace.
- **PAGE-SAFETY: VERIFIED at both resolutions and all four packing orders**, independently
  recomputed against the oracle (458752 / 884736 / 917504 / 1310720, all `page_layout_ok`).
- **DRY-RING DEFECT: FIXED**, confirmed per-engine (`dryN`) with the OUT ring correctly left at
  a fixed 16384 in exactly the four places that should stay fixed.
- **RECONCILE: LEAVES NO STALE STATE** that I could find — layout, windows, runtime state, and
  dirty flags are all updated consistently, in the right order relative to PDC.
- **EEL2 HAZARDS: NONE FOUND** (no scientific literals, no `gmem`, functions defined before use,
  no empty ternary branches).
- **V0.7 IS READY TO TAG.**
