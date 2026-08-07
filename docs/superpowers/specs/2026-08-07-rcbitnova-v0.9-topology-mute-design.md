# RCBitNova V0.9 — Topology transitions via a deferred, honest mute

**Date:** 2026-08-07
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V0.9` (copy of V0.8). `rcbitnova-v0.8` remains the fallback tag;
V0.8 and earlier are frozen.
**Starting point:** V0.8 design §9 (why a 20 ms dip cannot work) and §12 (the asymmetric shape).
Both analyses are taken as given and are NOT re-derived here.

---

## 1. Goal

Make the three *topology* switches — **HP/LP Placement** (in `Phase=Linear`), **Phase**, and
**HP/LP Resolution** — produce **silence instead of garbage**, by deferring the topology change
until the plugin output is already at zero and holding the mute for the real warm-up of the new
topology.

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
- The mute already covers `lat`, and the *engine's own* FDL needs the same `lat` samples to warm
  up regardless — so the fix would not shorten the mute by a single sample.
- It costs two memory writes per sample in `Both`, the most common configuration.

`dryB` therefore stays allocated and unused. If a future version makes Placement genuinely
seamless, this fix becomes required again — that is the only context in which it pays.

Also out of scope: the per-band placement (unchanged), the min-phase HP/LP path (unchanged),
bypass semantics (unchanged), the V0.8 kernel crossfade (a different event class — Freq/Slope/
Resonance — which already works), and the FIR Brick Gibbs bump (V0.8 §11, still deferred).

## 4. Architecture — `selected → pending → active`

The plugin learns about a switch only *after* the first affected sample would already be in
flight. So the topology change must be **deferred**, never applied inside the `@slider` pass
that observes it.

### 4.1 State

New instance variables (no new buffers):

| Name | Meaning |
|---|---|
| `act_phase`, `act_hp_pl`, `act_lp_pl` | ACTIVE topology actually used by `@sample` |
| `mt_state` | 0 idle, 1 fading out, 2 holding (warm-up), 3 fading in |
| `mt_pos` | sample counter within the current state |
| `mt_fo`, `mt_fi` | fade-out / fade-in lengths, `floor(srate * 0.005)` (5 ms, time-defined) |
| `mt_hold` | required hold length in samples, computed at trigger time |
| `mt_pend` | 1 = a topology commit is owed |
| `mt_g` | current envelope value (only read while `mt_state != 0`) |

`lp_geo` already carries the ACTIVE geometry (BD, KMAX, lat, dryN) per engine — the selected
resolution stays in the sliders, exactly as in V0.7/V0.8. This spec adds the same
selected-vs-active split for Phase and Placement.

### 4.2 `@slider` — detect, arm, do not apply

`@slider` compares the selected topology against the active one:

```
topo_changed =
     (slider140          != act_phase)
  || (slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4]))
  || (slider140 == 1 && (slider134 != act_hp_pl || slider138 != act_lp_pl));
```

Note the `slider140 == 1` guards: while `Phase=Min` neither Resolution nor Placement is a
topology event (the engines do not run), which preserves V0.8 behaviour exactly — including
"selecting High while in Min costs nothing".

On `topo_changed`, `@slider` **only** sets `mt_pend = 1`, computes `mt_hold` (§4.4), and starts
the fade-out (`mt_state = 1`, `mt_pos = 0`) unless a fade-out is already running. It does **not**
call `lp_relayout`, does not change `pdc_delay`, and does not touch `act_*`. Audio keeps flowing
through the old, correct topology while it fades.

Everything else in `@slider` (band setup, coefficient rebuilds, `Lk`, `out_gain`, the rebuild
signatures) is unchanged.

### 4.3 `@block` — commit at exact zero

```
mt_pend && (play_state == 0 || (mt_state == 2 && mt_g == 0)) ? topo_commit();
```

`topo_commit()` performs, in this order:

1. `slider140 == 1 && geometry differs` → `lp_relayout(sel_bd0, sel_bd1)`, `lp_win_build(0/1)`,
   `lp_rt_reset(0/1)` (which also resets the V0.8 fade state), force `hp_dirty = lp_dirty = 1`
   and `lp_fs[3] = lp_fs[7] = 0` so both kernels are rebuilt with a **snap**, not a crossfade.
   This is exactly the V0.8 `@slider` relayout block, relocated.
2. `act_phase = slider140; act_hp_pl = slider134; act_lp_pl = slider138;`
3. Recompute `lin_lat`, `pdc_delay`, `ext_tail_size` from the now-ACTIVE topology.
4. `mt_pend = 0` and restart the hold counter (`mt_pos = 0`; the state is already 2, so the hold
   begins now rather than at the moment the fade-out ended) — or, when committed at
   `play_state == 0`, go straight to `mt_state = 0` with `mt_g = 1` (nothing is audible; no mute).

**Transport-stopped fast path.** `play_state == 0` commits immediately and never engages the
envelope at all. Since the owner configures the plugin with the transport stopped, in normal use
the mute is never heard — and, per §7, never even executed.

Because `pdc_delay` is now written from `topo_commit()` rather than from `@slider`, the PDC
computation moves into a small helper called from both places (`@slider` still owns the
`Lk`/bypass part, which is not a topology event).

### 4.4 Hold length, from the geometry

All lengths in samples; `P = lpP = 2048` (one hop); `lat_e = lp_geo[e*4+2] = BD_e/2 + P`.

| Event | Hold |
|---|---|
| Placement (engine `e`, `Phase=Linear`) | `lat_e + P` |
| Resolution (relayout clears both engines) | `lat0_new + lat1_new + P` |
| Phase `Min → Linear` | `lat0 + lat1 + P` |
| Phase `Linear → Min` | `P` |

`Linear → Min` needs no warm-up (the min-phase cascade is instantaneous); the single hop covers
the host adopting the new `pdc_delay`. When several events coincide in one `@slider` pass,
`mt_hold = max(...)` of the applicable rows.

Worst case, `High+High @48k`: `18432 + 18432 + 2048 = 38912` samples = **810 ms**.
`Normal+Normal @48k`: `6144 + 6144 + 2048 = 14336` = **299 ms**.

### 4.5 `@sample` — envelope at the FINAL output

Two changes only.

**Use the active placement**, not the slider:

```
lpk_process(0, act_hp_pl);
lpk_process(1, act_lp_pl);
```

and likewise `act_phase` selects the Min vs Linear branch.

**Apply the envelope after everything**, as a tail block outside the bypass branch — the bands,
the dynamics and the Mode-B bus are stateful, so silence at the HP/LP boundary is not silence at
the plugin output (V0.8 §9):

```
mt_state ? (
  mt_state == 1 ? ( mt_g = 1 - mt_pos / mt_fo; mt_pos += 1;
                    mt_pos >= mt_fo ? ( mt_g = 0; mt_state = 2; mt_pos = 0; ); ) :
  mt_state == 2 ? ( mt_g = 0; mt_pend == 0 ? ( mt_pos += 1;
                    mt_pos >= mt_hold ? ( mt_state = 3; mt_pos = 0; ); ); ) :
                  ( mt_g = mt_pos / mt_fi; mt_pos += 1;
                    mt_pos >= mt_fi ? ( mt_g = 1; mt_state = 0; ); );
  slider1 != 1 ? ( spl0 *= mt_g; spl1 *= mt_g; );
);
```

The counter runs even under bypass so a state cannot get stuck; the multiply does not, so bypass
stays a clean pass-through. In state 2 the hold counter only advances **after** the commit
(`mt_pend == 0`), so a commit deferred by a slow `@block` extends the silence rather than
truncating the warm-up.

**Re-trigger while a transition is in flight** (coalescing and reversal):

- A new event during **fade-out** (state 1) or **hold** (state 2, still pending): update
  `mt_hold = max(mt_hold, new)` and keep going — one commit, applied once, at the end.
- A new event during **hold after commit** or **fade-in**: restart at state 1 from the current
  `mt_g` (`mt_pos = (1 - mt_g) * mt_fo`), so the envelope never jumps.
- **Reversal before commit** — the selected topology returns to the active one while still
  pending: cancel (`mt_pend = 0`), set `mt_state = 3` and `mt_pos = mt_g * mt_fi`, i.e. fade back
  in from wherever the envelope currently is. No relayout happens, nothing is reset, and the only
  audible effect is a short dip.

## 5. Interaction with the V0.8 kernel crossfade

The V0.8 per-sample crossfade covers Freq / Slope / Resonance — a *magnitude* change with the
geometry unchanged. It stays exactly as shipped. Two contact points:

- `topo_commit()` calls `lp_rt_reset()`, which already calls `lp_fs_reset()`. A fade in progress
  can therefore never survive into a relayout and point at moved memory.
- After a commit, both kernels are rebuilt with a **snap** (`lp_fs[3]/[7] = 0`), matching V0.8's
  "snap on first build and after relayout" rule. Snapping is inaudible here by construction: the
  output is muted.

## 6. PDC and the host

`pdc_delay` still follows policy (c) from V0.6 — Min is zero-latency, Linear is the sum of the
two engine latencies, Mode-B adds `Lk`. V0.9 changes only *when* the new value is published: at
commit, i.e. while the output is at zero, instead of in the `@slider` pass that observed the
switch. REAPER still adopts it at block granularity; the hold (which always includes one hop)
covers that adoption. The plugin does not and cannot guarantee sample-accurate host re-sync — the
mute is what makes that irrelevant.

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
2. `mt_hold` matches the §4.4 table for every combination (Placement / Phase / Resolution ×
   Normal / High), including the `max` when events coincide.
3. Steady-state bit-exactness (gate 2 of §7).
4. Coalescing: a second event during fade-out produces one commit with the longer hold.
5. Reversal before commit: no relayout, no reset, envelope returns without a commit.
6. Phase and Resolution changed in the same `@slider` pass.
7. An event during an active V0.8 kernel crossfade: the fade state is reset, no stale pointer.
8. `play_state == 0`: immediate commit, envelope never engaged.
9. Bounded discontinuity: `|y[n] - y[n-1]|` stays below a fixed bound across the whole
   transition — the machine-checked replacement for "sounds like it doesn't click".
10. After the hold, the output matches a clean run in the new topology (no residual warm-up).
11. Bypass during a transition stays a clean pass-through while the counter still advances.

**Live verification with the owner in REAPER:**

- Each of the three switches flipped **under playback**: silence, then correct audio — no burst,
  no click, no missing Side content.
- PDC readings before/after (12288 Normal+Normal, 24576 High+Normal, 36864 High+High).
- The V0.8 null test (§7 gate 1).
- Switching with the transport stopped: no mute at all, correct audio on the next play.
- CPU unchanged from V0.8 (the lane-B skip is untouched: Normal Mid 0.80 %, High Mid 1.2 %).

## 9. Invariants preserved

- Steady-state path **byte-identical to V0.8**; bit-accuracy INTACT.
- Min path unchanged; per-band placement unchanged; bypass unchanged.
- Instance-local memory only; **no new buffers** — the state machine is a handful of scalars.
- V0.8 and earlier stay frozen; new file `JSFX/RCBitNova V0.9`.
- The Python DSP mirror remains THE ORACLE; live REAPER confirms the transcription.

## 10. Method

Unchanged from V0.4–V0.8: verify in Python first → TDD the oracle → transcribe Python → JSFX
line by line → live-verify with the owner → Fable final review → tag `rcbitnova-v0.9`.

**EEL2 reminder from V0.8, which cost a whole live session:** never write an assignment inside a
nested ternary. The state machine in §4.5 is exactly the kind of nested-conditional code where
that bug hides — and neither the oracle nor a careful review caught it last time. Every
assignment inside a conditional chain gets its own statement.
