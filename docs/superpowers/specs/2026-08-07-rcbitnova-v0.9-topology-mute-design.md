# RCBitNova V0.9 — Topology transitions via a deferred, honest mute

**Date:** 2026-08-07 (**rev 3**, after the weakness review
`2026-08-07-rcbitnova-v0.9-topology-mute-weaknesses.md` and Fable's review of rev 2 — see §12)
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V0.9` (copy of V0.8). `rcbitnova-v0.8` remains the fallback tag;
V0.8 and earlier are frozen.
**Starting point:** V0.8 design §9 (why a 20 ms dip cannot work) and §12 (the asymmetric shape).
Both analyses are taken as given and are NOT re-derived here.

---

## 1. Goal

Make the three *topology* switches — **HP/LP Placement** (in `Phase=Linear`), **Phase**, and
**HP/LP Resolution** — produce **silence instead of garbage**, by deferring the topology change
until the plugin output is already at zero and holding the mute until the new topology is
provably warm.

Non-goal: a seamless (audible-through) Placement transition. See §3.

## 2. Why this shape, and not the one V0.8 §12 proposed

V0.8 §12 proposed an asymmetric V0.9: seamless Placement (ramped lane inputs + recombination
weights) plus a mute for Phase/Resolution. Two things overturned it during brainstorming.

**A latency detail §12 missed.** A ramp applied to the *lane inputs* only reaches the output
`lat` samples later (6144–18432 samples = 64–192 ms per engine), while a ramp applied to the
*recombination weights* acts immediately. Keeping them coherent requires running the output
alpha delayed by `lat` behind the input alpha — and even then the crossfade is only approximate,
because multiplying by a time-varying weight does not commute with a linear-phase convolution.
An exact transition needs either both lanes running the old and new routings in parallel
(giving up V0.8's lane-B skip: High Mid 1.2 % → 1.6 %, i.e. −25 % of the whole-plugin CPU win)
or a hybrid state machine that switches between the two — the most complex machinery in the
project so far.

**The owner does not make the gesture.** Asked directly, the owner stated that Placement is a
set-up decision, not a performance move: an EQ set to Mid does not become Side mid-track. Paying
CPU or accepting complexity for a transition that is never performed is a bad trade.

**Therefore V0.9 is symmetric:** all three switches use one mechanism. The steady-state path is
byte-identical to V0.8, and no transition is claimed to be seamless — the transition is honestly
silent.

## 3. Explicitly rejected: the `dryA`/`dryB` fix

V0.8 §12 identified that `lpk_process` writes the complementary dry ring only in the selective
branch, that `dryB` (`ob[14]`) is allocated but never used, and that always writing `l`/`r`
would give the complementary component zero warm-up on a Placement switch.

**This is rejected for V0.9**, deliberately, and the reason is recorded so it is not
re-discovered as a bug:

- Its only benefit is removing the complementary channel's `lat`-sample warm-up.
- The mute already covers it, and under rev 2 the engines are reset at commit anyway, so the
  fix would not shorten the mute by a single sample.
- It costs two memory writes per sample in `Both`, the most common configuration.

`dryB` therefore stays allocated and unused. If a future version makes Placement genuinely
seamless, this fix becomes required again — that is the only context in which it pays.

Also out of scope: the per-band placement (unchanged), bypass semantics (unchanged), the V0.8
kernel crossfade (a different event class — Freq/Slope/Resonance — which already works), and the
FIR Brick Gibbs bump (V0.8 §11, still deferred).

## 4. Architecture — `selected → pending → active`

The plugin learns about a switch only *after* the first affected sample would already be in
flight. So the topology change must be **deferred**, never applied inside the `@slider` pass
that observes it.

### 4.1 The rev-2 simplification: every topology event is a full reset

The weakness review established (P0-1, P0-2) that a Placement change leaves stale old-domain
history in the engine: a linear-phase kernel has support `BD`, not `BD/2`, so the last
pre-commit sample keeps emitting for about `BD + P` samples — 34816 samples (725 ms @48k) for
one High engine — and for an **HP** Placement change that stale output then still has to travel
through the downstream **LP** engine. Holding through that full serial tail would mean up to
69630 samples (1.45 s).

**Instead, every topology commit clears both linear engines and the min-phase state.** Then no
stale tail can exist, the hold reduces to a cold-start warm-up, and one formula covers every
event. It also closes P1-1 (stale runtime on a Phase edge) by construction.

**rev 3 correction — the hold is `BD`, not `BD/2 + P` (Fable P0-1).** rev 2 set the hold to the
engine's reported latency `lat = BD/2 + P`. That is a *phase-alignment* constant — where the
linear-phase kernel's centre sits — and it is the moment output first *appears*, not the moment
output is *right*. A cleared engine convolves a signal whose pre-commit past has been zeroed;
since the kernel has finite support `BD`, that zeroed past stops influencing the output only
after `BD` samples. Fade in at `lat` and the first `BD/2` samples still carry the filter's
switch-on transient. Fade in at `BD` and the output depends solely on post-commit samples — and
is therefore **bit-identical to an engine that had been running continuously**, which is the
strongest claim physically available and, unlike rev 2's, a claim that actually constrains the
hold length.

(One detail of Fable's argument does not hold and is recorded so it is not re-litigated: an
unpopulated FDL partition contains zeros, and its contribution is exactly the correct
contribution of a zero-valued past — the engine is never computing a "truncated filter". The
conclusion about the required length is nevertheless correct, for the reason above.)

The clearing is explicit — resetting indices is not enough, because the FDL and rings still hold
old samples that `convolve_c` would fold back in. A new helper `lp_engine_clear(eng)` zeroes
`fdlA`, `fdlB`, `inA`, `inB`, `outA`, `outB`, `dryA`, `dryB` for that engine and then calls
`lp_rt_reset(eng)` (which also resets the V0.8 fade state). `lp_relayout` already `memset`s the
whole span, so a Resolution commit gets this for free; Placement and Phase commits call it
explicitly.

### 4.2 State

New instance variables (no new buffers):

| Name | Meaning |
|---|---|
| `act_phase`, `act_hp_pl`, `act_lp_pl` | ACTIVE topology actually used by `@sample` |
| `mt_state` | 0 idle, 1 fading out, 2 holding (warm-up), 3 fading in |
| `mt_pos` | sample counter within the current state |
| `mt_fo`, `mt_fi` | fade-out / fade-in lengths, `floor(srate * 0.005)` (5 ms, time-defined) |
| `mt_hold` | required hold in **processed** samples, computed at commit from the new geometry |
| `mt_blocks` | remaining `@block` epochs that must pass before fade-in (PDC gate, §6) |
| `mt_pend` | 1 = a topology commit is owed |
| `mt_ready` | 1 = commit done AND both active kernels valid; gates hold consumption |
| `mt_g` | current envelope value (only read while `mt_state != 0`) |
| `topo_boot` | 1 until the first `@slider` pass has adopted the loaded slider state (§4.3a) |

`lp_geo` already carries the ACTIVE geometry (BD, KMAX, lat, dryN) per engine — the selected
resolution stays in the sliders, exactly as in V0.7/V0.8. This spec adds the same
selected-vs-active split for Phase and Placement.

### 4.3 `@slider` — detect, arm, do not apply

```
topo_changed =
     (slider140          != act_phase)
  || (slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4]))
  || (slider140 == 1 && (slider134 != act_hp_pl || slider138 != act_lp_pl));
```

The `slider140 == 1` guards mean that while `Phase=Min` neither Resolution nor Placement is a
topology event (the engines do not run) — preserving V0.8 behaviour exactly, including
"selecting High while in Min costs nothing".

On `topo_changed`, `@slider` **only** sets `mt_pend = 1`, clears `mt_ready`, and starts the
fade-out (`mt_state = 1`, `mt_pos = 0`) unless a fade-out is already running. It does **not**
call `lp_relayout`, does not change `pdc_delay`, and does not touch `act_*`. Audio keeps flowing
through the old, correct topology while it fades. `mt_hold` is computed at commit, not here,
because it depends on the geometry that only exists after the relayout.

Everything else in `@slider` (band setup, coefficient rebuilds, `Lk`, `out_gain`, the rebuild
signatures) is unchanged.

### 4.3a Boot: loading a project is not a topology event (Fable P0-2, P1-4)

`@init` in V0.8 hardcodes `lp_relayout(8192, 8192)` and never consults the sliders. Under rev 2
as written, a project saved with `Phase=Linear, Resolution=High, Placement=Mid` would reload
with `act_*` at their EEL2 defaults of 0, so the **first** `@slider` pass — which JSFX runs
during instantiation, before audio — would see a topology change, arm the mute, and play through
the *wrong* topology (a stale Min-phase cascade) until the hold expired. On every reload. REAPER
also re-runs `@init` on a **sample-rate change**, which would reproduce it mid-project.

rev 3 therefore treats cold init as *already committed to the loaded state*:

- `@init` sets `act_phase = slider140; act_hp_pl = slider134; act_lp_pl = slider138;`, sets
  `mt_state = 0; mt_g = 1; mt_pend = 0; mt_ready = 1;` and sets `topo_boot = 1`.
- The first `@slider` pass with `topo_boot == 1` **applies** the selected geometry immediately —
  the V0.8 path: `lp_relayout(sel_bd0, sel_bd1)`, window builds, resets, forced snap rebuilds —
  then adopts `act_*`, publishes PDC, and clears `topo_boot`. No mute, no deferral.
- Every subsequent pass uses the deferred path of §4.3.

Doing the geometry work in the first `@slider` rather than in `@init` avoids depending on
whether slider values are already loaded when `@init` runs, which JSFX does not guarantee across
all hosts and load paths.

### 4.4 `@block` — pinned order

The review (P1-3) is right that the order matters: if the V0.8 rebuild branches ran before the
commit, the new engine could process samples against a cleared, invalid `Hspec` while the hold
was already being consumed. `@block` therefore runs in this exact order:

1. **Detect and commit.** `mt_pend && (play_state == 0 || (mt_state == 2 && mt_g == 0))` →
   `topo_commit()`.
2. **Relayout / clear.** Inside `topo_commit()`: if the geometry differs,
   `lp_relayout(sel_bd0, sel_bd1)` + `lp_win_build(0/1)`; otherwise `lp_engine_clear(0/1)`.
   On any Phase edge also `memset(hplp_state, 0, 72)` — the min-phase cascade must not resume
   integrator state left over from a previous Min session (P1-1). Force `hp_dirty = lp_dirty = 1`
   and `lp_fs[3] = lp_fs[7] = 0` so both kernels are rebuilt with a **snap**, never a crossfade.
3. **Adopt.** `act_phase = slider140; act_hp_pl = slider134; act_lp_pl = slider138;` then
   recompute `lin_lat`, `pdc_delay`, `ext_tail_size` from the now-ACTIVE topology. Set
   `mt_hold` (§4.5), `mt_blocks = 2` (§6), `mt_pos = 0`, `mt_pend = 0`.
4. **Forced snap builds.** The V0.8 rebuild branches run, unconditionally for this pass (the
   100 ms rate limiter is bypassed when `lp_fs[3]/[7] == 0`, which is already V0.8 behaviour).
5. **`mt_ready = 1`** only once both active kernels are valid (`lp_fs[3] && lp_fs[7]`, or
   `act_phase == 0` where no kernel is needed). If a build was deferred, `mt_ready` stays 0 and
   the hold does not start counting.

Because `pdc_delay` is now written from `topo_commit()` rather than from `@slider`, the PDC
computation moves into a small helper called from both places — `@slider` still owns the
`Lk`/bypass part, which is not a topology event.

6. **Decrement `mt_blocks`** — as an explicit final step, and **not on the commit block itself**
   (Fable P1-2). The commit block is the one that *publishes* the new `pdc_delay`; the two
   epochs counted are the blocks that follow it. Implementation: the decrement is guarded by
   `mt_state == 2 && mt_pend == 0`, and the commit sets `mt_pend = 0` and `mt_blocks = 2` in the
   same pass, so the guard must additionally skip the pass in which the commit happened. The
   guarantee is therefore exactly "the publishing block, plus two full blocks after it".

**Transport-stopped commit (P0-4).** `play_state == 0` allows an *early* commit — it does not
skip the warm-up and does not clear the machine. This matters because REAPER is not obliged to
call `@block` at all while stopped: if it never does, the commit simply happens on the first
playback block instead, via the ordinary path, and everything still works. Either way `mt_hold`
is consumed by **actually processed samples** (§4.6), so the new topology is never exposed cold.
The practical effect of a stopped configuration change is a short silence at the start of the
next playback — which is exactly the interval during which a freshly cleared linear engine has
nothing to output anyway.

### 4.5 Hold length — one formula

All lengths in **processed samples**; `P = lpP = 2048`; `BD_e = lp_geo[e*4]` from the **new**
geometry. Note this is `BD`, the kernel's full support — **not** the reported latency `lat_e`
(§4.1).

```
mt_hold = act_phase == 1 ? (BD0 + BD1 + 2*P) : 0
```

| Resulting case | Hold |
|---|---|
| Placement, Phase `Min→Linear`, or Resolution, at Normal+Normal | 20480 samples = 427 ms @48k |
| …at High+Normal | 45056 = 939 ms |
| …at High+High | 69632 = 1.45 s |
| Phase `Linear→Min` | 0 samples — only the `mt_blocks` PDC gate (§6) |

The serial composition is `BD0 + BD1 + 2P`: engine 0's output is free of pre-commit influence
after `BD0` samples plus its own hop of block latency, and engine 1 then needs `BD1` samples of
that clean input plus its own hop. **Measured in the oracle** (`test_v09_serial_pair_needs_...`):
at `BD0+BD1+P` the residual against a continuous reference is still −219 dBFS; at `BD0+BD1+2P`
it is −282 dBFS, i.e. float64 noise. The High+High figure of 69632 is, satisfyingly, the same
number the weakness review derived as the full serial FIR tail (69630).

**The measurement also settles how much this mattered.** Against a continuously running
reference, rev 2's group-delay length leaves an error of **−43 dBFS** — plainly audible, not the
"gentle ramp-in" it was assumed to be — while the full-support length leaves −282 dBFS. The
owner chose the honest length with the cost table in front of him; the measurement confirms it
was not a cosmetic choice.

`Linear→Min` needs no sample hold: the min-phase cascade is IIR with no finite support, and it
was just zeroed, so it is correct from its first sample for a signal with a zero past. It still
waits out the block gate so the host has adopted `pdc_delay = 0`. Its own ring-up (a
staggered-Butterworth cascade plus the always-on resonance bell, which can run at high Q) is
asserted to be inaudible rather than measured — §8.12 puts a high-Resonance `Linear→Min` case in
the test matrix so the assertion is checked rather than assumed (Fable P1-1).

Since every event resets everything, coincident events need no `max()` — the formula already
covers them.

### 4.6 `@sample` — envelope at the FINAL output

Two changes only.

**Use the active topology**, not the sliders: `act_phase` selects the Min vs Linear branch, and
`lpk_process(0, act_hp_pl)` / `lpk_process(1, act_lp_pl)` replace the direct slider reads.

**Apply the envelope after everything**, as a tail block **inside** the `slider1 != 1` branch —
the bands, the dynamics and the Mode-B bus are stateful, so silence at the HP/LP boundary is not
silence at the plugin output (V0.8 §9):

```
mt_state ? (
  mt_state == 1 ? (
      mt_pos += 1; mt_g = (mt_fo - mt_pos) / mt_fo;
      mt_pos >= mt_fo ? ( mt_g = 0; mt_state = 2; mt_pos = 0; );
  ) : mt_state == 2 ? (
      mt_g = 0;
      (mt_ready && mt_blocks <= 0) ? (
        mt_pos += 1;
        mt_pos >= mt_hold ? ( mt_state = 3; mt_pos = 0; );
      );
  ) : (
      mt_pos += 1; mt_g = mt_pos / mt_fi;
      mt_pos >= mt_fi ? ( mt_g = 1; mt_state = 0; );
  );
  spl0 *= mt_g; spl1 *= mt_g;
);
```

**Endpoint-inclusive ramp (P1-4).** rev 1 computed the gain *before* incrementing and then
overwrote the last value, making the final step `2/N` instead of `1/N` (≈ −41.6 dB at 5 ms /
48 kHz — the largest discontinuity in a feature whose acceptance test is a sample-to-sample
bound). rev 2 increments first, so the emitted sequence for `N = 4` is `0.75, 0.5, 0.25, 0` —
every step exactly `1/N`. `mt_fo`/`mt_fi` are clamped to a minimum of 1 so an unusual sample rate
cannot produce a division by zero.

**Bypass (P0-3).** The whole block lives inside `slider1 != 1`, so under bypass **nothing
advances** — not the envelope, not the hold. rev 1 let the counter run while the engines were
not being fed, which would have expired the warm-up and exposed a cold topology on unbypass.
Frozen state resumes correctly when bypass is released: the fade-out finishes, the commit
happens, and the hold is consumed by real samples.

**Re-trigger while a transition is in flight:**

- New event during **fade-out** (state 1) or during **hold before commit**: keep going — one
  commit, applied once, with the hold computed from the final selected geometry.
- New event **after commit** (state 2 with `mt_ready`, or state 3): restart at state 1 from the
  current `mt_g` (`mt_pos = (1 - mt_g) * mt_fo`), so the envelope never jumps.
- **Reversal before commit** — the selected topology returns to the active one while still
  pending: cancel (`mt_pend = 0`), set `mt_state = 3` and `mt_pos = mt_g * mt_fi`, i.e. fade back
  in from wherever the envelope is. No relayout, no reset; the only audible effect is a short dip.

**What "warm" means (P1-5, corrected in rev 3 per Fable P0-3).** rev 2 defined it as "equals the
new topology reset at commit and fed the same post-commit samples". Fable is right that this is
**vacuous**: a cleared engine satisfies it at every hold length, including zero, because it is
simply a restatement of what a cleared engine computes. It constrained nothing.

rev 3's definition constrains the hold: after the hold, the output **matches the same topology
running continuously**, i.e. an instance that had processed the full pre-commit history. With
`mt_hold = BD0 + BD1 + 2P` this is achievable, because both kernels have finite support: every
sample the output depends on lies after the commit, so the two instances can differ only by
float64 rounding (they sum different FFT blocks). Measured: **−282 dBFS**. At any shorter hold it
is false — at rev 2's length, −43 dBFS — which is exactly what makes the test meaningful (§8.4).

Note the wording: *matches*, not *is bit-identical*. The FFT path makes literal bit-equality
unavailable here, and claiming it would be false.

## 5. Interaction with the V0.8 kernel crossfade

The V0.8 per-sample crossfade covers Freq / Slope / Resonance — a *magnitude* change with the
geometry unchanged. It stays exactly as shipped. Two contact points:

- `lp_engine_clear()` calls `lp_rt_reset()`, which calls `lp_fs_reset()`, so a fade in progress
  can never survive a commit and point at cleared or moved memory.
- After a commit both kernels are rebuilt with a **snap**, matching V0.8's "snap on first build
  and after relayout" rule. Snapping is inaudible here by construction: the output is muted.

## 6. PDC and the host — a block gate, not a hop count

`pdc_delay` still follows policy (c) from V0.6 — Min zero-latency, Linear the sum of the two
engine latencies, Mode-B adds `Lk`. V0.9 changes only *when* the new value is published: at
commit, while the output is at zero.

rev 1 argued that the one-hop term in the hold covered the host adopting the new latency. The
review (P1-2) is right that this is unfounded: `P = 2048` and `samplesblock` are independent, so
with a 4096-sample block a `Linear→Min` commit could finish its hold and start fading in inside
the same host block — before any boundary at which REAPER could act on the new PDC. rev 2
therefore gates fade-in on **`mt_blocks` `@block` epochs** (pinned at 2 full blocks after the
publishing block, §4.4 step 6) in addition to the sample hold.

**A prior question the plugin cannot answer (Fable P1-3), and the first experiment to run.**
V0.6–V0.8 never moved `pdc_delay` while the transport was running — PDC changed only at load or
on a slider pass before playback. V0.9 is the first version to change host-visible latency
*during playback*, and there is no evidence anywhere in this project's history about how REAPER
behaves when a plugin does that: if the host re-buffers or flushes its routing around a live PDC
change, the resulting artefact happens **outside** this instance and no amount of internal muting
can suppress it. The fallback the owner rejected in V0.6 — constant maximum PDC — exists exactly
for this failure mode.

Therefore the very first work item (plan Task 0) was a standalone live experiment: change
`pdc_delay` under playback in a trivial test JSFX — an honest pure delay matching exactly what it
reports, so anything heard beyond the latency change is the host's doing — and listen for
host-side disruption.

**Result, 2026-08-09 (owner, live): clean.** Flipping the reported latency between 0 and 12288
samples under playback produced no click, dropout or stall. REAPER adopts a mid-playback PDC
change without host-side artefacts, so V0.9's architecture stands as designed: the internal mute
is sufficient, and the constant-max-PDC fallback the owner rejected in V0.6 is not needed. (The
owner reported the outcome as a whole rather than per buffer size; no disruption was observed.)
If a later session finds REAPER needs more than two block boundaries after all, `mt_blocks` is
the single constant to raise.

## 7. Bit-accuracy — four machine-checked gates

The steady-state guarantee is structural: when `mt_state == 0` the entire envelope block is
**skipped by the condition**, so not one arithmetic operation is added to `spl0`/`spl1`. It is
not "multiplied by 1.0".

Required before tagging:

1. **Null test V0.8 ↔ V0.9** in REAPER: identical settings, one instance polarity-inverted,
   summed → silence.
2. **Oracle test**: with no topology event, V0.9's output is bit-identical to the V0.8 model.
   The test must fail if the envelope block is executed as a no-op.
3. **Grep gate**: no `log`, `dB`, `pow(10)` introduced anywhere in the new code.
4. **Fable final review** on bit-accuracy, as in every previous version.

The envelope itself is ordinary float, exactly like the V0.8 kernel crossfade weights, which
Fable passed as "bit-accuracy INTACT" on the same argument: outside the transition it is not in
the path, and inside the transition the signal is deliberately being taken to zero.

## 8. Verification

**Oracle** (`tools/rcbitnova_dsp.py` + `tests/`) gains a topology state machine driven by an
**event log** — V0.8 §9 asked for exactly this instead of a subjective listen.

1. The commit happens **exactly** when the envelope reaches zero — not one sample earlier.
2. `mt_hold` matches §4.5 for every event × geometry combination, including `Linear→Min` = 0.
3. Steady-state bit-exactness (gate 2 of §7).
4. **Hold sufficiency, against a CONTINUOUS reference.** After the hold, the output must be
   bit-equal to the same topology **running continuously since before the commit** (§4.6) — not
   to a cleared-at-commit reference, which rev 2 used and which is satisfied at every hold
   length including zero (Fable P0-3). The companion test asserts the negative: at
   `lat0 + lat1 + P` (rev 2's length) the two references differ by −43 dBFS, so the test fails if
   someone shortens the hold back. Every FDL partition, input ring and output ring is seeded
   with nonzero, **stereo-asymmetric** history, and an impulse is placed just before the commit —
   sustained audio can hide a partially-formed response under new steady output. Run separately
   for **HP** Placement and **LP** Placement, since only HP has a downstream FIR stage.
5. **Bypass warm-up.** Change topology while bypassed, wait longer than `mt_hold`, then unbypass
   into a nonzero stereo signal: the machine must still be frozen and must then run the full
   fade-out → commit → hold → fade-in. (rev 1's test would have passed the bug.)
6. **No idle `@block`.** Change topology with `play_state == 0` and deliver **no** `@block` until
   playback starts: the commit must happen on the first playback block and the hold must be
   consumed by processed samples. Also cover paused, record, record-paused, seek, loop wrap and
   playback from time zero — the contract is "samples are being processed", not one numeric
   `play_state` (P2-1).
7. **Block gate.** `samplesblock` below, equal to and above `P`, plus offline-render block sizes:
   fade-in must never begin before `mt_blocks` epochs have elapsed.
8. **Commit/build ordering.** A commit whose kernel build is deferred must not consume hold time
   (`mt_ready == 0`), and no sample may ever be processed against an invalid `Hspec`.
9. **Endpoint ramp.** Every emitted gain is checked, not just the final state: all steps equal
   `1/N` for `N` = 2, 3, 240, 480, 960, and the clamp holds for degenerate rates.
10. Coalescing, pre-commit reversal, post-commit re-trigger; Phase and Resolution changed in the
    same `@slider` pass; an event during an active V0.8 kernel crossfade.
11. **Transition error, with a number (P2-2).** Compare against **uninterrupted** old and new
    references — an instance that never stopped running, explicitly NOT a cleared-at-commit one
    (Fable P0-3) — normalize to signal peak, and require the worst error outside the intended
    mute to be **≤ −80 dBFS**, measured across the whole transition (fade-out, hold, PDC
    adoption, fade-in). The bound replaces rev 1's unquantified `|y[n] − y[n−1]|` criterion.
12. **Test matrix for items 4 and 11**, chosen to expose a partially-formed response rather than
    hide it: Slope 96 dB/oct and FIR Brick; High Resolution on both engines; Resonance near
    maximum; sustained sines at several phases; asymmetric stereo; impulse; noise; silence with
    the dynamics active; and a high-Resonance `Linear→Min` edge (the one case whose zero hold
    rests on an assertion rather than a measurement — Fable P1-1).

**Live verification with the owner in REAPER:**

- Each of the three switches flipped **under playback**: silence, then correct audio — no burst,
  no click, no missing Side content.
- PDC readings before/after (12288 Normal+Normal, 24576 High+Normal, 36864 High+High).
- The V0.8 null test (§7 gate 1).
- Switching with the transport stopped, then playing: correct audio, short leading silence only.
- Switching while bypassed, then unbypassing.
- **Save a project with `Phase=Linear, Resolution=High, Placement=Mid`, reopen it, and play
  immediately**: correct audio from the first sample, no mute, no interval of wrong-topology
  sound (§4.3a). Repeat after a **sample-rate change** in the audio device settings.
- **The Task 0 PDC experiment** (§6) repeated on the finished plugin: change Phase under
  playback and confirm the host itself introduces no artefact around the latency change.
- CPU unchanged from V0.8 (the lane-B skip is untouched: Normal Mid 0.80 %, High Mid 1.2 %).

## 8a. Accepted risks

- **Automating a topology slider mutes indefinitely.** If Phase, Resolution or Placement is
  automated (or thrashed by a control surface) faster than `mt_hold`, the machine re-arms before
  it can reach fade-in and the output stays silent for as long as that continues. This is
  accepted, not fixed: these are set-up controls, not performance controls (§2), and silence is
  a better failure than a burst of garbage per event. It is stated here so it is a known mode
  rather than a surprise.
- **Anticipative FX / offline render.** The design is driven by processed-sample counts and
  `@block` epochs, never by wall-clock time, so pre-processing ahead of the transport behaves
  like ordinary processing. `play_state` is used only to permit an *early* commit, never to skip
  warm-up, so an ambiguous value cannot shorten a mute. Considered, no change required; §8.6 and
  §8.7 cover it in tests.

## 9. Invariants preserved

- Steady-state path **byte-identical to V0.8**; bit-accuracy INTACT.
- Min path unchanged apart from its state being zeroed on a Phase edge; per-band placement
  unchanged; bypass stays a clean pass-through.
- Instance-local memory only; **no new buffers** — the state machine is a handful of scalars.
- V0.8 and earlier stay frozen; new file `JSFX/RCBitNova V0.9`.
- The Python DSP mirror remains THE ORACLE; live REAPER confirms the transcription.

## 10. Method

Unchanged from V0.4–V0.8: verify in Python first → TDD the oracle → transcribe Python → JSFX
line by line → live-verify with the owner → Fable final review → tag `rcbitnova-v0.9`.

**EEL2 reminder from V0.8, which cost a whole live session:** never write an assignment inside a
nested ternary. The state machine in §4.6 is exactly the kind of nested-conditional code where
that bug hides — and neither the oracle nor a careful review caught it last time. Every
assignment inside a conditional chain gets its own statement.

## 11. Weakness-review disposition (rev 1 → rev 2)

| Finding | Disposition |
|---|---|
| P0 Placement hold uses group delay, not the stale FIR tail | **Accepted**, resolved by clearing the engines at commit (§4.1) rather than by holding through the tail — shorter mute, and the acceptance test becomes bit-exact |
| P0 HP Placement must flush through the downstream LP engine | **Accepted**; the same clear-everything policy covers it, so no graph-position-dependent hold formula is needed |
| P0 Bypass expires the hold without warming | **Accepted** — the machine is frozen under bypass (§4.6) |
| P0 Stopped fast path guarantees neither commit nor warm-up | **Accepted** — the stopped path is now only an *early commit*; the hold is always consumed by processed samples (§4.4) |
| P1 Phase edges leave stale runtime state | **Accepted** — both linear engines and `hplp_state` are cleared on any Phase edge |
| P1 One hop is not one host block | **Accepted** — `mt_blocks` epoch gate replaces the hop argument (§6) |
| P1 Commit/build ordering not pinned | **Accepted** — `@block` order pinned, `mt_ready` gates hold consumption (§4.4) |
| P1 Fade endpoint skips a step | **Accepted** — increment-first ramp, every step `1/N` (§4.6) |
| P1 "Warm" is undefined | **Accepted** — defined as bit-equality with a cleared-at-commit reference; the stronger claim is explicitly not made (§4.6) |
| P2 Paused/record transport states omitted | **Accepted** — contract is "samples are being processed"; covered by the frozen-machine design and tested in §8.6 |
| P2 Bounded-discontinuity criterion has no bound | **Accepted** — ≤ −80 dBFS relative to peak, with pinned material (§8.11) |

## 12. Fable review disposition (rev 2 → rev 3)

Fable reviewed rev 2 against the V0.8 source and returned "needs edits — not ready to plan".

| Finding | Disposition |
|---|---|
| **P0-1** hold conflates group delay with settling; `lat0+lat1+P` is undersized | **Accepted**, hold is now `BD0+BD1+P` (§4.1, §4.5). One supporting argument of the finding is wrong — unpopulated FDL partitions hold zeros and contribute correctly, so the engine is never a "truncated filter" — but the conclusion stands: finite support `BD` is when the zeroed past stops mattering. The owner chose the longer hold with the cost table in front of him |
| **P0-2** `act_*` and geometry never synced to loaded sliders; every project reload mutes and plays the wrong topology | **Accepted** — §4.3a treats cold init as already committed, and does the geometry work in the first `@slider` rather than `@init` so it does not depend on when slider values become available |
| **P0-3** the stale-tail test cannot fail; the −80 dB gate inherits the same vacuity | **Accepted** — "warm" is redefined against a **continuous** reference (§4.6), the test asserts the negative at rev 2's length, and §8.12 pins a matrix that exposes a partially-formed response |
| **P1-1** `Linear→Min` hold 0 asserted, not measured | **Accepted** — high-Resonance `Linear→Min` added to the §8.12 matrix; the assertion stays but is now checked |
| **P1-2** when `mt_blocks` decrements is unpinned | **Accepted** — explicit step 6 in §4.4; not on the commit block |
| **P1-3** live PDC change mid-playback is untested territory and could force a different architecture | **Accepted and promoted** — it is now plan **Task 0**, run before any implementation (§6) |
| **P1-4** sample-rate change re-runs `@init` and reproduces P0-2 | **Accepted** — same fix, stated explicitly, with a live test |
| **P2** automation thrashing → indefinite silence | **Accepted as a documented risk** (§8a) |
| **P2** anticipative FX / offline `play_state` semantics | **Addressed in §8a**: the design is sample-count driven and `play_state` can only permit an early commit, never shorten a mute |
