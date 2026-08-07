# RCBitNova V0.9 Topology Mute - Weakness Review

**Date:** 2026-08-07
**Reviewed spec:** `2026-08-07-rcbitnova-v0.9-topology-mute-design.md`
**Reviewed base:** `JSFX/RCBitNova V0.8` at tag `rcbitnova-v0.8`
**Review type:** transition timing, FIR state, transport, bypass, PDC, and verification audit

## Verdict

The deferred-mute direction is substantially safer than V0.8 rev 2's short dip.
The spec now has active topology, commit-at-zero, final-output muting, event
coalescing, and an integrated oracle contract.

It is not implementation-ready yet. The hold table uses group delay where
Placement needs the complete stale FIR tail, and it ignores downstream LP latency
for an HP Placement change. Bypass advances the hold while bypassing the very
engines that are supposed to warm up. The stopped fast path similarly performs no
warm-up and may not execute at all until playback supplies the next `@block`.

## Findings

### P0 - Placement hold uses group delay, not the stale FIR tail

The Placement row specifies:

```text
hold = lat_e + P
lat_e = BD_e/2 + P
```

That is enough to pass the kernel's group-delay region, but Placement does not
reset the engine. At commit, its FDL and output ring still contain input from the
old domain. The last pre-commit sample can continue through a length-`BD` FIR for
approximately `BD + P` samples, not `BD/2 + 2P`.

V0.8 already uses the corresponding full-support tail contract for two serial
engines:

```text
2*P + BD_hp + BD_lp - 2
```

The mismatch is large in High mode. One High engine has:

```text
specified Placement hold:  lat + P = 18432 + 2048 = 20480 samples
single-engine FIR tail:     approximately 32768 + 2048 = 34816 samples
```

Fading in at sample 20480 can therefore reveal old-placement energy that remains
in the FDL. Verification item 10, "no residual warm-up," is not implied by the
current table.

**Required change:** choose one explicit Placement policy:

- Preserve state and hold through the complete old-domain FIR support; or
- Reset the affected engine at commit, force valid snap kernels, and define the
  resulting cold-start hold separately.

The oracle must seed every FDL partition and output-ring phase with nonzero,
stereo-asymmetric history. An impulse near commit is the decisive tail test;
sustained audio alone can hide stale contributions under new steady output.

### P0 - HP Placement must also flush through the downstream LP engine

The two linear engines are serial. A wrong-domain sample emitted by the HP engine
after an HP Placement change is then convolved by the LP engine before it reaches
the final mute. The table uses only `lat_hp + P`, so it can fade in while old HP
history is still travelling through LP.

For High+High, the existing full serial tail bound is about 69630 samples, while
the proposed HP Placement hold is only 20480 samples. Even a group-delay-only
model would need to include both engine latencies for HP, not only the changed
engine's latency.

LP Placement has no downstream linear engine, but it still has the single-engine
full-tail problem above.

**Required change:** make hold calculation depend on graph position, not merely
engine identity. For a state-preserving transition, HP Placement must include the
remaining support of HP and every downstream FIR stage. Test HP and LP Placement
separately; one generic `Placement(engine e)` case is insufficient.

### P0 - Bypass expires the hold without warming the new topology

The spec intentionally runs the mute counter under bypass but skips the multiply:

```text
counter advances
slider1 == 1 -> DSP branch and mute multiply are skipped
```

In V0.8, bypass skips the entire HP/LP engine path. Consequently, during bypass:

- the FDLs receive no new input;
- output rings do not advance;
- lane zero counters do not advance;
- a new or reset geometry does not warm up.

Nevertheless `mt_pos` reaches `mt_hold`, the state returns to idle, and unbypass
exposes a cold or stale topology with no protection. Verification item 11 currently
checks only that bypass stays clean while the counter advances; it encodes the bug
rather than proving warm-up.

**Required change:** either process the active HP/LP topology internally while
returning dry bypass output, freeze the hold until the topology has processed the
required number of samples, or re-arm the complete hold/fade sequence on unbypass.
Add a test that changes topology while bypassed, waits longer than `mt_hold`, then
unbypasses into a nonzero stereo signal.

### P0 - The stopped fast path neither guarantees commit nor warm-up

The fast path is implemented by a condition in `@block`:

```text
mt_pend && play_state == 0 -> topo_commit()
```

When transport is stopped and the track is not otherwise processing, REAPER is not
obliged to call `@block` merely because a slider changed. The promised "immediate"
commit can therefore remain pending until the first playback block.

Even if an idle block does run, the fast path sets `mt_state = 0` immediately. No
samples pass through a relaid-out Linear pipeline while stopped, so there is no
warm-up. On the next Play, the new engine starts cold. A Placement change can also
resume old FDL/output-ring history from the previous transport run.

The statement "nothing is audible" is true at commit time but does not establish
"correct audio on the next play."

**Required change:** separate an inaudible stopped commit from readiness for the
next audible sample. Possible contracts are:

- Commit in `@slider` only for operations legal there, but arm a startup hold that
  is consumed by actual processed samples on Play;
- Keep `mt_pend`/a `needs_warmup` flag until processing resumes;
- Explicitly rely on and live-prove a REAPER pre-roll behavior at starts, seeks,
  and cursor positions.

Test with no idle `@block` calls between the stopped slider change and the first
playback block. Also cover stop, pause, seek, loop wrap, and playback from project
time zero.

### P1 - Phase changes leave the newly active branch's runtime state stale

`topo_commit()` resets the linear engines only when geometry differs. Therefore:

- Min->Linear with unchanged Resolution resumes the FDL and output rings left by
  the previous Linear session;
- Linear->Min resumes `hplp_state`, which has not been processed while Linear was
  active.

"Min phase is instantaneous" means zero algorithmic latency. It does not mean its
IIR state requires no lifecycle policy. Stale integrator/filter state can emit an
unrelated transient, and resetting it creates its own settling interval, especially
for low-frequency, high-order filters.

**Required change:** pin the state action for every Phase edge. At minimum,
Min->Linear must reset both linear runtime pipelines even when geometry is unchanged,
and Linear->Min must deliberately preserve, reset, or continuously warm the
min-phase state. Derive each hold from that choice and test repeated
Min->Linear->Min cycles after unrelated audio history.

### P1 - One convolution hop is not one host PDC block

Section 6 says the hold always includes one `P=2048` hop and therefore covers
REAPER adopting the new `pdc_delay` at block granularity. The convolution hop and
the host audio block are independent sizes.

If `samplesblock > 2048`, a Linear->Min commit at the start of a block can finish
its `P`-sample hold and begin fading in within that same host block. There has not
yet been another `@block` boundary at which the host can observe or apply the new
PDC. Offline and anticipative processing can use block sizes unlike the live device
block used during manual testing.

**Required change:** gate PDC readiness on an explicit subsequent `@block` epoch,
not a fixed convolution-hop sample count. Record the block number at publication
and prohibit fade-in until at least the required host boundary has occurred. Test
`samplesblock` below, equal to, and above `P`, plus offline render blocks. If actual
REAPER behavior needs more than one boundary, the live gate must determine and pin
that count.

### P1 - Commit and kernel-build ordering inside `@block` is not pinned

A Resolution commit performs relayout, resets validity, and marks both kernels
dirty. The existing V0.8 rebuild code also runs in `@block`. Correct warm-up timing
depends on whether `topo_commit()` executes before those rebuild branches:

- Commit first: both snap kernels can be built before the following samples warm
  the new runtime.
- Rebuild first: the new dirty flags wait for the next block, while the hold counter
  has already started and the new engine may process with cleared/invalid `Hspec`.

The text says commit begins the hold but does not give a complete `@block` order.

**Required change:** pin `@block` as detect commit -> relayout/reset -> forced snap
builds -> publish PDC/mark committed -> process samples. If either build is deferred,
keep `mt_pend` or a separate `kernels_ready` gate set so hold time cannot be consumed
before both active kernels are valid.

### P1 - Fade endpoint code skips the penultimate gain step

The pseudocode overwrites the current sample's calculated gain when the incremented
counter reaches the length. For fade-out, the final iteration computes `1/mt_fo`
and then replaces it with `0`; for fade-in it computes `(mt_fi-1)/mt_fi` and then
replaces it with `1`.

The effective last gain increment is therefore `2/N`, not `1/N`. At 48 kHz and a
5 ms fade, that is about `0.0083` of full scale, roughly -41.6 dB before accounting
for signal phase. It is small, but it is the largest discontinuity in a feature
whose acceptance test is explicitly sample-to-sample bounded.

**Required change:** define an endpoint-inclusive integer ramp and machine-check
every emitted gain, not only the final state. Test very short lengths as well as
220/240/480/960 samples, and pin the zero-length fallback for unsupported or unusual
sample rates.

### P1 - The hold contract confuses latency with a fully primed response

For relayout and Min->Linear, the state is cleared rather than contaminated by old
topology, so the full stale-tail argument does not apply. But the spec still needs
to define what "warm" means:

- first nonzero output exists;
- group-delay center has arrived;
- output equals a zero-state reference fed since commit;
- output equals a continuously running new topology with pre-commit history.

These are different acceptance criteria. A hold based on `lat0 + lat1 + P` can
satisfy a group-delay criterion but cannot recreate pre-commit input history that
was never processed by the new topology. Verification item 10 says the output
matches a "clean run" without defining that run's initial history.

**Required change:** define the reference precisely. The feasible bit-exact claim
is equality to a new topology reset at commit and fed the same post-commit samples.
If the product claim is settled continuous-program response at fade-in, measure a
longer fill requirement and accept that arbitrary pre-commit history cannot be
reconstructed without parallel processing.

### P2 - Paused and non-playing transport states are omitted

The fast path recognizes only `play_state == 0`. REAPER distinguishes stopped,
playing, paused, recording, and record-paused states. If no samples advance while
paused, a transition armed there can remain in fade-out until playback resumes,
creating a mute the user expected to have completed while inaudible.

**Required change:** define behavior by "audio is processing" rather than only one
numeric state, and pin every relevant `play_state` value. Include paused, record
paused, live input monitoring while stopped, offline render, and anticipative FX.

### P2 - The bounded-discontinuity acceptance criterion has no bound

Verification requires `|y[n]-y[n-1]|` below a fixed bound, but the bound, signal
normalization, test material, and comparison window are absent. A loose bound can
pass the endpoint jump above or even ordinary full-scale programme transients; a
tight absolute bound can fail clean audio unrelated to the topology event.

**Required change:** measure transition error against uninterrupted old/new
references, normalize it to signal peak, and pin a dB threshold. Include sustained
sines at multiple phases, asymmetric stereo, impulse/noise, and silence with
stateful dynamics. Report the worst error across the entire mute, stale-tail
interval, PDC adoption, and fade-in.

## What Is Already Strong

- The topology change is deferred until final output is exactly zero.
- Active Phase and Linear Placement are separated from selected sliders.
- The envelope is outside downstream stateful bands and skipped entirely when idle.
- Commit coalescing, pre-commit reversal, and post-commit retrigger are considered.
- Geometry changes force snap rebuilds while muted.
- The oracle is event-driven and includes bit-exact steady-state gates.
- The design explicitly chooses an honest mute instead of claiming seamlessness.

## Required Spec Edits Before Implementation

1. Replace Placement group-delay holds with full stale-tail bounds, including all
   downstream FIR stages for HP.
2. Prevent bypass from consuming warm-up time while the engines are not running.
3. Replace the stopped fast path with a commit-plus-startup-readiness contract.
4. Reset or deliberately warm the newly active runtime on every Phase edge.
5. Gate PDC readiness on host `@block` epochs rather than one convolution hop.
6. Pin commit/rebuild ordering and require valid kernels before hold consumption.
7. Correct the endpoint-inclusive fade counter law.
8. Define "warm," paused/record transport behavior, and a numerical transition-error threshold.
