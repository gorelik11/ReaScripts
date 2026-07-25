# RCBitNova V0.7 — High-Resolution Linear-Phase HP/LP — Design Spec

**Date:** 2026-07-25 (**rev 3** — rev 2 folded the Codex weakness review
`…-v0.7-hires-linear-phase-review.md`; rev 3 folds the Fable review
`…-v0.7-hires-weaknesses-fable.md`: corrected High span 655360, memory claim restated without
an undocumented mechanism, rebuild-cost budget, active-span rule covers all write loops)
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.6 (frozen, tag `rcbitnova-v0.6`, commit `ceda9bd`) — new file `JSFX/RCBitNova V0.7`
**Predecessor spec:** `2026-07-21-rcbitnova-v0.6-linear-phase-hplp-design.md` (its §15 records
the as-shipped V0.6 state and the deferral list this spec draws from)

---

## 1. Goal

Add a **per-filter Resolution selector** (`Normal` = BD 8192 / `High` = BD 32768) to the
linear-phase HP/LP section, so linear phase can perform a **deep low-cut** — the one case
V0.6 cannot serve. Everything else about V0.6 stays as shipped.

**Why:** V0.6's fixed BD=8192 kernel resolves ~11.7 Hz/bin @96k, so below ~50 Hz it cannot
represent a steep sub-cutoff transition and the deep stopband stays shallow (documented V0.6
limitation). BD=32768 quadruples resolution to ~2.93 Hz/bin.

**Measured with the PRODUCTION builder** (`impulse_fft_kernel` — the method the shipping JSFX
uses; see §6 for why this, not the analytic builder), 96 kHz, resonance 0:

| Case | probe | ideal IIR | BD=8192 | BD=32768 | gain |
|---|---|---|---|---|---|
| 20 Hz HP, 96 dB/oct | 10 Hz | −96 dB | −10.4 dB | **−37.4 dB** | +27 dB |
| 20 Hz HP, 96 dB/oct | 5 Hz | −193 dB | −12.2 dB | **−46.5 dB** | +34 dB |
| 30 Hz HP, 96 dB/oct | 15 Hz | −96 dB | −13.7 dB | **−55.3 dB** | +42 dB |
| 40 Hz HP, 48 dB/oct | 20 Hz | −48 dB | −17.8 dB | **−42.2 dB** | +24 dB (≈ideal) |

High-frequency cuts need none of this — V0.6's FIR Brick already reaches −150 dB within
~600 Hz near Nyquist. Hence **per-filter**, not global.

**Sample-rate scope (honest):** the headline figures are for **≤96 kHz**. The benefit scales
with `BD/srate`, so at 192 kHz the same BD=32768 gives only ≈−18 dB at 10 Hz (20 Hz HP,
96 dB/oct) — still better than BD=8192's ≈−8 dB, but not a deep cut. **The deep-low-cut claim
is scoped to ≤96 kHz**; 192 kHz gets a documented, weaker improvement (§7 tests both).

## 2. Scope

**In:** per-filter Resolution (Normal/High); per-engine buffer layout, geometry (`BD`/`KMAX`),
Kaiser window, and dry-ring size; latency/PDC accounting; memory placement that keeps the
Normal footprint identical to V0.6; oracle tests; live verification.

**Out (YAGNI / deferred):**
- Click-safe dual-kernel **crossfade** on Freq/Resonance/Slope sweep in Linear — stays
  deferred (V0.6 §15). Resolution changes are topology changes and are not click-safe either.
- A user-facing intermediate 16384 option — 16384 exists only as the **fallback** if 32768
  proves unusable (§8), not as a third menu entry.
- **Lane-B skip optimisation.** In selective placement (Mid/Side/Left/Right) V0.6 still runs
  lane B with a zero input, so half the convolution work is wasted. Skipping it would halve
  the cost of those placements (attractive at High), but it changes the V0.6 runtime and is
  not needed for correctness — deferred, recorded here so it is not forgotten.
- Linear phase / hi-res for bells, shelves, or dynamics (impossible or out of scope — V0.6
  spec §2 DSP verdict: a bit-exact limiter can never be linear-phase).
- Seamless (crossfaded) Resolution or Phase switching during playback — not required (owner).

## 3. Controls & behaviour

- **New sliders** (fresh bank past the V0.6 Phase slider 140):
  - `slider141:0<0,1,1{Normal,High}>HP Resolution`
  - `slider142:0<0,1,1{Normal,High}>LP Resolution`
- Active **only when `Phase = Linear`** (same convention as FIR Brick, which is Linear-only).
- Default `Normal` (0) for both → a freshly loaded V0.7 behaves exactly like V0.6.
- Typical use: **HP = High** (deep sub-bass low-cut) + **LP = Normal** (high-cut brickwall
  needs no extra resolution) — hi-res cost paid on one engine only.

**Per-engine geometry.** The runtime hop is deliberately identical for both settings
(`P = 2048`, `B = 4096`, `PB2 = 8192`) — chosen over a larger hop for lower latency and a
minimal diff:

| Resolution | `BD` | `KMAX = BD/P` | latency `BD/2 + P` | ≈ @96k | bin width @96k | dry ring |
|---|---|---|---|---|---|---|
| Normal | 8192 | 4 | 6144 | 64 ms | 11.7 Hz | 16384 |
| High | 32768 | 16 | 18432 | 192 ms | 2.93 Hz | **32768** |

### 3.1 Selected vs active geometry (resolves Codex P2)

The slider value is the **selected** resolution; each engine also has an **active geometry**
(`BD`, `KMAX`, offsets, window, dry-ring size). They are reconciled **only when needed**, so
selecting High while `Phase = Min` costs nothing:

- While `Phase = Min`: store the selection; do **not** configure or touch hi-res memory.
- On the **Min → Linear** transition, or when a selected resolution changes while already in
  Linear: reconcile **both** engines (§5.4) before any Linear audio is processed.
- Configuration is idempotent: reconciling when nothing changed is a no-op.

## 4. Cost when hi-res is OFF (the owner's decision criterion)

- **CPU:** in `Phase = Min` the convolution engines do not run at all. In `Linear + Normal`
  the work is exactly V0.6's. The extra cost is incurred **only on an engine actually set to
  High**.
- **Corrected cost model (Codex P1).** `lpk_run` processes **two lanes** (A and B), so the
  per-hop `convolve_c` count is `2 × KMAX`, not `KMAX`:

  | Configuration | `convolve_c` per hop | hops/s @96k |
  |---|---|---|
  | one Normal engine | 8 | ~46.9 |
  | one High engine | **32** | ~46.9 |
  | Normal + High | 40 | ~46.9 |
  | High + High | 64 | ~46.9 |

  So High + High ≈ 3000 size-4096 complex convolutions per second plus FFT/IFFT and
  accumulation. Must be live-tested at small device block sizes (§7).
- **Memory (corrected — Codex P1, Fable P0-2).** rev 1 proposed fixed worst-case slots with
  engine 1 at `lp_base + 655360`, and justified "free when off" by asserting that JSFX commits
  memory lazily per page. Both were wrong: two **Normal** engines would reach a top of
  `655360 + 229376 = 884736` words (~6.75 MB) instead of V0.6's 458752 (~3.5 MB), and the
  lazy-page-commit mechanism is **not documented** (Fable searched the SDK docs) — so the claim
  rested on an unverified assumption. **V0.7 does not need that assumption.** It packs engine 1
  immediately after engine 0, which makes the Normal footprint *identical to V0.6 by
  construction*:
  - `e0_base = lp_base` (page-aligned); `e1_base = lp_base + e0_used_span`.
  - `page_layout` aligns each FFT-touched buffer **within** a layout, so an arbitrary
    `e1_base` is safe: a High engine's `desbuf` (span 65536 = one full page) is pushed up to
    the next page boundary automatically. Oracle-verified for all four combinations:

    | e0 | e1 | `e1_base` | top | page-safe |
    |---|---|---|---|---|
    | Normal | Normal | 229376 | **458752 (= V0.6 exactly)** | ✓ |
    | High | Normal | 655360 | 884736 (6.75 MB) | ✓ |
    | Normal | High | 229376 (`desbuf`→262144) | 917504 (7.00 MB) | ✓ |
    | High | High | 655360 | 1310720 (10.00 MB) | ✓ |

  - Used spans (with the §5.5 per-BD dry ring): Normal **229376**, fallback-16384 **360448**,
    High **655360** (exactly 10 pages). rev 1's "622592" was computed with the old 16384 dry
    ring and is superseded.
  - **The zero-cost claim now rests only on "footprint tracks the highest touched address"** —
    the same premise V0.6 already lives under, and which V0.6's measured ~3.5 MB confirms
    empirically. With packing, Normal + Normal touches exactly the addresses V0.6 touched, so
    its footprint cannot be worse than V0.6's regardless of how JSFX pages memory. The top
    rises only while an engine is actually at High. §7 adds an **empirical footprint check**
    rather than trusting any mechanism.
  - Because `e1_base` depends on `e0`'s span, a geometry change on **either** engine
    re-lays-out **both** (§5.4).
  - Call `freembuf(top + 1)` after a topology change so the hint can shrink again (REAPER
    documents `freembuf` as a hint; keep indices as low as possible).
- **Active-span rule (Fable P1).** "Touch nothing beyond the active span" governs **every**
  write loop, not just `memset`: the Kaiser-window build (`BD` words into `win_k`), the
  impulse-response build (`BD` complex into `desbuf`), the partition loop, and the runtime
  rings. All are inside the engine's own current-geometry layout by construction; the rule
  exists so a future edit cannot silently reach into hi-res address space while Normal is
  active.

## 5. Engine changes

1. **Per-engine offset table instead of hardcoded constants.** V0.6 hardcodes
   `hspec = eb + 32768` etc., valid only for BD=8192. V0.7 stores each engine's 15 buffer
   offsets (absolute addresses) in memory (`lp_off + eng*16`); `lpk_build` / `lpk_run` /
   `lpk_process` read them from there. A new `lp_layout(eng, base, BD)` helper mirrors the
   oracle's `page_layout`, including the rule that every FFT-touched buffer's span never
   crosses a 65536-word page. `lpk_run` loads the offsets once per call into locals (its
   existing pattern), so the hot path cost is unchanged.
2. **Per-engine geometry** (`lp_geo + eng*4`: `BD`, `KMAX`, `lat`, `dryN`) replaces the
   globals. `P`, `B`, `PB2` stay global constants.
3. **Per-engine Kaiser window** built in that engine's own `win_k` slot at its own length
   (beta stays fixed at 14), rebuilt when that engine's geometry changes. A 32768-length I0
   series build runs at reconcile time (`@slider`/`@block`), never per sample.
4. **Reconcile procedure** (per engine, on geometry change or Min→Linear): compute layout →
   clear **only that engine's used span** → rebuild its Kaiser window → reset its runtime
   state (`ir, cnt, out_rd, out_wr = P, fdl_wr, dry_wp`) → force a kernel rebuild → update
   `lat`/`dryN` → recompute PDC and `ext_tail_size` → `freembuf(top + 1)`. Resolution joins
   `slope/freq/resonance` in the rebuild signature.
5. **Per-engine dry ring, enlarged (resolves Codex P0 — a real defect).** V0.6's
   `lpk_process` uses a fixed 16384-word complementary-dry ring with a single
   `drd < 0 ? drd += 16384` wrap. A High engine's latency is **18432 > 16384**, so the ring
   cannot represent the delay and `drd` can stay negative — corrupting Mid/Side/Left/Right
   (Both is unaffected, which is exactly why a naive smoke test would miss it). V0.7 makes the
   dry-ring size **per-engine** (`dryN`: 16384 for Normal, **32768** for High), wraps with
   that size, and resets `dry_wp` on geometry change. Normal keeps 16384 so its footprint
   stays identical to V0.6 (§4). The literal `16384` appears in **four** places in V0.6's
   `lpk_run`/`lpk_process` (out-ring and dry-ring wraps) — the out-ring uses are unrelated to
   latency and stay 16384 (the out ring only needs to exceed the hop `P`); only the **dry**
   uses become `dryN`. The oracle's `lp_engine_buffers` must gain the same per-BD dry size,
   which is what raises the High span to 655360 (§4).
6. **`ext_tail_size` derived from geometry (resolves Codex P1).** A fixed 65536 truncates
   High + High: the last possibly-nonzero output after the final input is
   `2·P + BD_hp + BD_lp − 2 + Lk` = `4096 + 32768 + 32768 − 2 + 2047 = 71677`. V0.7 sets
   `ext_tail_size = 2·P + BD_hp + BD_lp + Lk + 64` (worst case 71743) at reconcile time, and a
   small value in Min/bypass.
7. **Kernel-rebuild cost is ~4× at BD=32768 — budget and coalesce it (Fable P1).** A rebuild
   runs a `BD`-sample impulse through the cascade, a `BD`-point FFT and IFFT, a `BD`-length
   Kaiser window, and `KMAX` partition FFTs — all inside one `@block`. At BD=32768 that is
   roughly 4× V0.6's already-heavy rebuild, so a Freq/Resonance knob sweep at High can spike
   the audio thread (V0.6's deferred click issue becomes a possible dropout). Since the
   crossfade stays out of scope (§2), V0.7 **coalesces and rate-limits** rebuilds instead:
   a changed signature marks the engine dirty, and at most one rebuild is performed per
   ~100 ms per engine (dirty state persists, so the final knob position always gets built).
   This bounds the worst case without introducing crossfade machinery. §7 live-tests a sweep
   at High for dropouts.
8. Everything else — the overlap-save runtime, placement routing, FIR Brick, Mode-B
   integration — carries over unchanged in structure, with `lp_lat` now per-engine.

## 6. Kernel builder: keep the production impulse-FFT (resolves Codex P1)

Codex correctly observed that rev 1's headline numbers came from the oracle's **analytic**
`build_lp_kernel`, while the shipping JSFX builds the magnitude via **impulse-FFT**
(`impulse_fft_kernel`: impulse → actual min-phase cascade → FFT → magnitude → zero-phase
kernel), and that the two diverge at BD=32768.

**Decision: keep the production impulse-FFT builder; correct the numbers instead.** Measured
comparison (96 kHz, resonance 0) shows the divergence is confined to the far subsonic floor,
while the musically relevant region near the knee is **identical**:

| Case | probe | production | analytic | verdict |
|---|---|---|---|---|
| 20 Hz HP 96 dB | 15 Hz | −17.2 dB | −17.5 dB | identical (resolution-limited, not builder-limited) |
| 20 Hz HP 96 dB | 10 Hz | −37.4 dB | −43.9 dB | +6 dB, already deep |
| 20 Hz HP 96 dB | 5 Hz | −46.5 dB | −85.7 dB | +39 dB, but subsonic and already −46 dB |
| 30 Hz HP 96 dB | 22 Hz | −24.1 dB | −24.0 dB | identical |
| 40 Hz HP 48 dB | all probes | −104.9 / −78.8 / −42.2 / −17.5 | same | identical everywhere |

Near and just below cutoff both builders are limited by **resolution**, not by the builder, so
switching to analytic would not make the practical low-cut steeper — it would only lower an
already-inaudible subsonic floor, at the cost of new hand-written complex-arithmetic EEL2
(per-bin state-space transfer evaluation) on a feature that already carries the §8 risk.
V0.6's impulse-FFT method is live-proven and oracle-tested (`impulse_fft_kernel` ==
`build_lp_kernel` in passband/transition).

**Binding consequence:** every low-frequency acceptance test in §7 must exercise
`impulse_fft_kernel` (the production path), never `build_lp_kernel`. If absolute subsonic
depth is ever wanted, the tool is **Min phase** (exact IIR) — already documented in §9.

## 7. Verification

**Oracle (Python, stdlib only).** The V0.6 oracle is parameterised by `BD`, so mainly tests
are needed; `lp_engine_buffers` gains a per-BD dry-ring size (16384 / 32768) to match §5.5.

1. **Low-frequency gain is real, via the production builder** (§6): at 96 kHz, 20 Hz HP /
   96 dB/oct, `impulse_fft_kernel` at BD=32768 rejects at 10 Hz **≥20 dB** more than BD=8192
   (measured 27 dB); 40 Hz HP / 48 dB/oct at 20 Hz lands **within 8 dB** of the ideal IIR
   (measured 6.0 dB). Assert with margin, never exact measured values.
2. **Sample-rate scope:** the same 20 Hz HP case at 192 kHz still improves at 10 Hz
   (≥5 dB better than BD=8192) but is **not** asserted to be deep — encodes §1's honest scope.
3. **Page-safety at BD=32768:** `page_layout_ok` holds for both engines under the packed
   placement of §4, and a High `desbuf` (span 65536 = exactly one page) starts page-aligned —
   the §8 condition, asserted explicitly, including a packed `e1_base` that is not itself
   page-aligned.
4. **Memory placement:** under the packed placement, `top` == 458752 for Normal + Normal
   (V0.6 parity), 884736 for High + Normal, 917504 for Normal + High, 1310720 for High + High;
   the fallback-16384 span is 360448. Page-safety asserted for all four combinations.
5. **Contracts still hold at BD=32768:** kernel symmetric about `BD/2` (tol 1e-6),
   `kernel_group_delay(32768) == 16384`, passband parity within 0.3 dB, and
   `impulse_fft_kernel` == `build_lp_kernel` in passband/transition (<0.1 dB).
6. **Runtime latency, not just kernel delay (resolves Codex P2).** Using
   `partitioned_convolve`, assert the measured impulse-peak position for each configuration:
   Normal 6144; High 18432; Normal+High 24576; High+High 36864.
7. **Dry-ring capacity:** a High engine's delay (18432) is representable in its ring
   (32768) — a direct regression test for the §5.5 defect.

**Live (REAPER, with the owner), in order:**
0. **The §8 smoke test** — a 32768 kernel builds and sounds correct. Gate for everything else.
1. Regression: `Phase = Min` unchanged; `Linear` with both Resolutions = Normal identical to V0.6.
2. **HP = High with Placement = Mid and = Side** (the §5.5 defect path, not just Both): no comb
   filtering, untouched component still nulls.
3. HP = High: a 20–40 Hz linear-phase low-cut audibly/measurably removes sub-bass; compare to
   Min (approaches it) and to Normal (clearly deeper).
4. Mixed resolutions (HP High + LP Normal) in series: alignment holds, no artefacts.
5. CPU: Normal unchanged from V0.6; one engine at High acceptable; **High + High** tested at
   44.1 / 48 / 96 / 192 kHz with small device blocks — no dropouts.
6. Resolution switching does not crash; PDC updates; **offline render keeps the full tail**
   (High + High, per §5.6).
7. **Empirical memory footprint (replaces the withdrawn lazy-commit assumption, §4).** Read
   REAPER's reported plugin/instance memory in three states — Min, Linear + Normal/Normal,
   Linear + High/High — and confirm Normal/Normal is not measurably worse than V0.6's.
8. **Rebuild cost at High (§5.7):** sweep HP Freq and Resonance while playing with HP = High
   and confirm the coalescing keeps it dropout-free (clicks on the sweep remain expected and
   accepted — the crossfade is deferred, §2).

## 8. Primary risk: does JSFX `fft()` actually work at 32768?

The documented JSFX ceiling for `fft`/`ifft` is 32768 — exactly the size we need — but the
owner's experience is that **32768 in JSFX has never worked** in past attempts (older
AI-written code), and Arthur's reference file comments treat 8192 as the practical `fft()`
ceiling. Treat this as unverified.

**Likely explanation, and why we may succeed where naive attempts failed:** at BD=32768 the
complex kernel buffer spans `65536` **words** = exactly one full JSFX memory page. An FFT
buffer must not cross a 65536 boundary, so a 32768-point FFT is only legal if its buffer
starts **exactly on a page boundary**. Any casually chosen offset ("after my other buffers")
violates it, and the failure is **silent** — no compile error, just corrupted or silent output.
V0.6's page-aware layout already aligns `desbuf` to a page boundary automatically, which is
precisely the condition earlier attempts would have missed.

**Confidence raised by review:** Fable checked this against the actual SDK docs
(`advfunc.php` / `js.php`) and confirmed (a) **32768 is an enumerated legal FFT size**, and
(b) the no-crossing rule is stated in **item** units, with no items-vs-words ambiguity that
would change our arithmetic — a 32768-point complex FFT is 32768 items / 65536 words, and our
layout aligns to the stricter interpretation either way. So the hypothesis stands: the size is
legal, and alignment is the thing that must be right. It remains **unverified in practice**
until the smoke test passes.

**Mitigation — verify FIRST.** The plan's first task is a minimal REAPER smoke test: build one
32768 kernel on a page-aligned buffer and confirm the output is correct (not silent, not
corrupted), including `fft_permute`/`fft_ipermute` at that size. Only then proceed.

**Fallback if 32768 is genuinely unusable:** `High` = **BD 16384** (KMAX 8, latency 10240,
≈107 ms @96k, ~5.9 Hz/bin, used span 360448, dry ring 16384 suffices since 10240 < 16384).
Still a 2× resolution gain, and its `desbuf` span (32768 words = half a page) sidesteps the
exact-page-alignment requirement entirely. The architecture of §3–§6 is unchanged; only the
constant differs. This fallback decision is explicit, not implicit.

## 9. Invariants preserved

- **Bit-accuracy INTACT:** HP/LP remain pure filters with no gain stage; resolution changes
  only FFT sizes. No `log`/`dB`/`pow(10)` in the DSP path. The only scalars stay the mandatory
  `1/BD` (kernel ifft) and `1/B` (runtime ifft) normalisations, each applied exactly once.
- **V0.6 and earlier files stay frozen.** New file `JSFX/RCBitNova V0.7` (copy of V0.6);
  `rcbitnova-v0.6` remains the fallback tag.
- Min path stays byte-identical to V0.5/V0.6 behaviour (zero added latency).
- Instance-local memory only (never `gmem`).
- The Python DSP mirror remains THE ORACLE; live REAPER confirms transcription.
- **Known limitation carried forward:** even at BD=32768 a 20 Hz HP does not match the ideal
  IIR in the deepest stopband (−37 dB vs −96 dB at 10 Hz with the production builder). **Min
  phase remains the tool for absolute sub-bass surgery**; hi-res narrows the gap substantially
  rather than closing it. At 192 kHz the gap is wider still (§1).
