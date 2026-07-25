# RCBitNova V0.7 — High-Resolution Linear-Phase HP/LP — Design Spec

**Date:** 2026-07-25
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.6 (frozen, tag `rcbitnova-v0.6`, commit `ceda9bd`) — new file `JSFX/RCBitNova V0.7`
**Predecessor spec:** `2026-07-21-rcbitnova-v0.6-linear-phase-hplp-design.md` (see its §15 for
the as-shipped state and the deferral list this spec draws from)

---

## 1. Goal

Add a **per-filter Resolution selector** (`Normal` = BD 8192 / `High` = BD 32768) to the
linear-phase HP/LP section, so linear phase can perform a **deep low-cut** — the one case
V0.6 cannot serve. Everything else about V0.6 stays as shipped.

**Why:** V0.6's fixed BD=8192 kernel resolves ~11.7 Hz/bin @96k, so below ~50 Hz it cannot
represent a steep sub-cutoff transition and the deep stopband stays shallow (documented
V0.6 limitation). BD=32768 quadruples resolution to ~2.93 Hz/bin. Measured with the oracle
(96 kHz, resonance 0):

| Case | probe | ideal IIR | BD=8192 | BD=32768 |
|---|---|---|---|---|
| 20 Hz HP, 96 dB/oct | 10 Hz | −96 dB | −10 dB | **−44 dB** |
| 20 Hz HP, 96 dB/oct | 5 Hz | −193 dB | −13 dB | **−86 dB** |
| 40 Hz HP, 48 dB/oct | 20 Hz | −48 dB | −18 dB | **−42 dB** (≈ideal) |

High-frequency cuts need none of this — V0.6's FIR Brick already reaches −150 dB within
~600 Hz near Nyquist. Hence **per-filter**, not global.

## 2. Scope

**In:** per-filter Resolution (Normal/High) for the two linear-phase engines; per-engine
buffer layout, Kaiser window, `BD`/`KMAX`; latency/PDC accounting; on-demand memory so the
feature is free when unused; oracle tests; live verification.

**Out (YAGNI / deferred):**
- Click-safe dual-kernel **crossfade** on Freq/Resonance/Slope sweep in Linear — stays
  deferred (V0.6 §15). Resolution changes are topology changes, not click-safe either.
- A user-facing intermediate 16384 option — 16384 exists only as the **fallback** if
  32768 proves unusable (§6), not as a third menu entry.
- Linear phase / hi-res for bells, shelves, or dynamics (impossible or out of scope — see
  the V0.6 spec §2 DSP verdict; the bit-exact limiter can never be linear-phase).
- Seamless (crossfaded) Resolution switching during playback — not needed (owner).

## 3. Controls & behaviour

- **New sliders** (fresh bank past the V0.6 Phase slider 140, leaving room):
  - `slider141:0<0,1,1{Normal,High}>HP Resolution`
  - `slider142:0<0,1,1{Normal,High}>LP Resolution`
- Active **only when `Phase = Linear`**. In Min they are ignored (same convention as
  FIR Brick, which is Linear-only).
- Default `Normal` (0) for both → a freshly loaded V0.7 behaves exactly like V0.6.
- Typical use: **HP = High** (deep sub-bass low-cut) + **LP = Normal** (high-cut brickwall
  needs no extra resolution) — so hi-res cost is paid on one engine only.

**Per-engine geometry** (`P = 2048`, `B = 4096`, `PB2 = 8192` unchanged for both settings —
the runtime hop is deliberately identical, chosen over a larger hop for lower latency and a
minimal diff):

| Resolution | `BD` | `KMAX = BD/P` | latency `BD/2 + P` | ≈ @96k | bin width @96k |
|---|---|---|---|---|---|
| Normal | 8192 | 4 | 6144 | 64 ms | 11.7 Hz |
| High | 32768 | 16 | 18432 | 192 ms | 2.93 Hz |

**Latency / PDC:** `pdc_delay = (lat_hp + lat_lp) + (Mode-B lookahead if any)`, where each
`lat` is that engine's `BD/2 + P` in Linear and `0` in Min; `0` on full bypass. Constant for
a given configuration (both engines always run in Linear, so it does not vary with Slope).
Changing Resolution or Phase changes the reported latency — a deliberate topology change
(owner confirmed no seamless live switching is required). This continues V0.6's PDC
policy (c).

## 4. Cost when hi-res is OFF: zero (the owner's decision criterion)

- **CPU:** in `Phase = Min` the convolution engines do not run at all. In
  `Linear + Normal` the work is byte-for-byte what V0.6 does. The ~4× convolution cost
  (`KMAX` 4→16) is incurred **only on an engine actually set to High**.
- **Memory:** each engine gets a fixed **worst-case address-space slot** of `655360` words
  (10 pages; hi-res needs 622592), engine 0 at `lp_base`, engine 1 at `lp_base + 655360`.
  JSFX commits memory **lazily by highest-touched address**, so in Normal the hi-res part of
  a slot is never touched and never committed. Footprint stays ≈ today's (~3.5 MB).
  **This requires one rule in code:** never `memset`/touch beyond the current resolution's
  used span. V0.6's blanket `memset(lp_base, 0, 458752)` must become a **per-engine clear of
  that engine's currently-used span**. (Reserving address space is free; touching it is not.)

## 5. Engine changes (small, contained)

1. **Per-engine offset table instead of hardcoded constants.** V0.6 hardcodes
   `hspec = eb + 32768` etc., valid only for BD=8192. V0.7 stores the 15 buffer offsets per
   engine in memory (`lp_off + eng*16`, absolute addresses) and `lpk_build`/`lpk_run`/
   `lpk_process` read them from there. Offsets are computed by a new `lp_layout(eng, BD)`
   helper that mirrors the oracle's `page_layout` (§7) — including the constraint that every
   FFT-touched buffer is aligned so its span never crosses a 65536-word page.
2. **Per-engine `BD` and `KMAX`** (stored alongside, e.g. `lp_geo + eng*4`) replace the
   globals. `P`, `B`, `PB2` stay global constants.
3. **Per-engine Kaiser window.** V0.6 shares one BD=8192 window (`lp_win`); V0.7 builds each
   engine's window in its own `win_k` slot at its own length (beta stays fixed at 14).
   Rebuilt when that engine's resolution changes.
4. **Resolution-change handling** (in `@slider`, per engine, on change only): recompute the
   offset table and geometry → clear that engine's used span → reset its runtime state
   (`ir, cnt, out_rd, out_wr=P, fdl_wr, dry_wp`) → force a kernel rebuild → recompute PDC.
   Resolution joins `slope/freq/resonance` in that engine's rebuild signature.
5. Everything else — the overlap-save runtime, placement routing with delayed dry
   (`lp_lat` now per-engine), FIR Brick, Mode-B integration, `ext_tail_size`
   (now `2 * max BD` = 65536) — carries over unchanged in structure.

## 6. Primary risk: does JSFX `fft()` actually work at 32768?

The documented JSFX ceiling for `fft`/`ifft` is 32768, i.e. exactly the size we need — but
the owner's experience is that **32768 in JSFX has never worked** in past attempts (with
older AI-written code), and Arthur's reference file comments treat 8192 as the practical
`fft()` ceiling. Treat this as unverified.

**Likely explanation (and why we may succeed where naive attempts failed):** at BD=32768 the
complex kernel buffer spans `65536` words = **exactly one full JSFX memory page**. The JSFX
rule is that an FFT buffer must not cross a 65536-item boundary, so a 32768-point FFT is only
legal if its buffer starts **exactly on a page boundary**. Any casually-chosen offset
(e.g. "after my other buffers") violates it, and the failure is silent — no compile error,
just corrupted or silent output. V0.6's page-aware layout already aligns `desbuf` to a page
boundary automatically (verified with the oracle at bases 0, 65536, 655360 — all aligned,
`page_layout_ok = True`), which is precisely the condition earlier attempts would have missed.

**Mitigation — verify FIRST, before any other work.** The implementation plan's first task is
a minimal REAPER smoke test: build one 32768 kernel on a page-aligned buffer and confirm the
result is correct (not silent, not corrupted). Only then proceed.

**Fallback if 32768 is genuinely unusable:** `High` = **BD 16384** (KMAX 8, latency 10240,
≈107 ms @96k, ~5.9 Hz/bin). Still a 2× resolution gain over V0.6, and its `desbuf` span is
32768 words = half a page, which sidesteps the exact-page-alignment requirement entirely.
The architecture in §3–§5 is unchanged; only the constant differs. The fallback decision is
recorded in the plan, not left implicit.

## 7. Verification

**Oracle (Python, stdlib only).** The V0.6 oracle is already parameterised by `BD`
(`build_lp_kernel`, `impulse_fft_kernel`, `lp_engine_buffers`, `page_layout`,
`page_layout_ok`), so no new production helpers are needed — only tests:

1. **Low-frequency gain is real:** at 96 kHz, 20 Hz HP / 96 dB/oct, BD=32768 rejects at
   10 Hz by ≥25 dB more than BD=8192 (measured: 33.6 dB); 40 Hz HP / 48 dB/oct at 20 Hz
   lands within 8 dB of the ideal IIR (measured: 6.0 dB — assert 8 dB so the test is not
   brittle). Assert improvements with margin, never exact measured values.
2. **Page-safety at BD=32768:** `page_layout_ok` holds for both engine slots, and `desbuf`
   (span 65536 = exactly one page) starts page-aligned — the §6 condition, asserted explicitly.
3. **Contracts still hold at BD=32768:** kernel symmetric about `BD/2` (tolerance 1e-6),
   `kernel_group_delay(32768) == 16384`, passband parity vs the analytic magnitude within
   0.3 dB, impulse-FFT build == analytic build in passband/transition (<0.1 dB).
4. **Slot arithmetic:** a 655360-word slot holds the hi-res layout with the Normal layout
   fitting inside its low part (the property §4's lazy-commit argument depends on).

**Live (REAPER, with the owner).** In order:
0. **The §6 smoke test** — 32768 kernel builds and sounds correct (gate for everything else).
1. Regression: Phase=Min unchanged; Linear + both Resolutions=Normal identical to V0.6.
2. HP=High: a 20–40 Hz linear-phase low-cut now audibly/measurably removes sub-bass; compare
   against Min (should approach it) and against Normal (clearly deeper).
3. LP=Normal + HP=High simultaneously (mixed resolutions, different latencies, series chain)
   — no comb filtering, placement still nulls the untouched component.
4. CPU in Normal is unchanged from V0.6; CPU with one engine at High is acceptable; no
   dropouts at small block sizes (the hi-res burst is 16 `convolve_c` per hop).
5. Resolution switching does not crash; PDC updates; offline render keeps the longer tail.

## 8. Invariants preserved

- **Bit-accuracy INTACT:** HP/LP remain pure filters with no gain stage; resolution changes
  only FFT sizes. No `log`/`dB`/`pow(10)` anywhere in the DSP path. The only scalars stay the
  mandatory `1/BD` (kernel ifft) and `1/B` (runtime ifft) normalisations, each applied once.
- **V0.6 and earlier files stay frozen.** New file `JSFX/RCBitNova V0.7` (copy of V0.6);
  `rcbitnova-v0.6` remains the fallback tag.
- Min path stays byte-identical to V0.5/V0.6 behaviour (zero added latency).
- Instance-local memory only (never `gmem`).
- The Python DSP mirror remains THE ORACLE; live REAPER confirms transcription.
- **Known limitation carried forward:** even at BD=32768 a 20 Hz HP does not fully match the
  ideal IIR in the deepest stopband (−44 dB vs −96 dB at 10 Hz). Min phase remains the tool
  for absolute sub-bass surgery; hi-res narrows the gap substantially rather than closing it.
