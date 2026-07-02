# RCBitNova V0.2 Shelf Dynamics — Weakness Review

**Date:** 2026-07-02  
**Reviewed spec:** `2026-07-02-rcbitnova-v0.2-shelf-dynamics-design.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

This review lists the weak points to tighten before implementing shelf dynamics in
`JSFX/RCBitNova V0.2`. The design is substantially stronger than the parent spec:
it narrows the guarantee scope, keeps HP/LP static-only, and separates Mode A from
Mode B. The remaining risks are mostly specification precision and JSFX integration
details.

## P1 — Path / Worktree Ambiguity

The referenced file exists in the `rcbitnova` worktree:

`/Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova/docs/superpowers/specs/2026-07-02-rcbitnova-v0.2-shelf-dynamics-design.md`

It does not exist at the same relative path in the main worktree. This can confuse
the next agent or script that starts from `~/projects/reascripts`.

**Recommendation:** keep all RCBitNova V0.2 implementation work explicitly inside
`.claude/worktrees/rcbitnova`, or copy/sync the spec into the main tree only if that
is intended.

## P1 — Mode B Shelf Q Semantics

The detector section specifies a fixed shelf-region detector Q of `0.7071`
(spec lines 32-35). Mode B then says the shelf split also uses one SVF at `freq`,
detector Q `0.7071` (lines 59-62). Mode A, however, uses a second shelf filter with
the band's own `freq`/`Q` (lines 45-46).

That means the visible shelf `Q` control affects Mode A shelf-cut shape, but appears
not to affect Mode B split-region shape. This may be correct musically, but it needs
to be explicit because users will expect the same band controls to shape both modes.

**Recommendation:** decide one of these and document it:

- Mode B shelf region is intentionally Butterworth-wide and ignores band shelf Q.
- Mode B split uses the band's shelf Q, while only the detector uses fixed Q.
- Add a hidden/internal distinction: `detector_q = 0.7071`, `split_q = band_q`.

## P1 — Shelf Ceiling Semantics Are Still Slightly Overcompressed

The spec says the detector is unity in its passband and has "same semantics as Bell"
(lines 38-41). For shelves, this is less intuitive than for Bell:

- At cutoff the detector is around `0.7071`, not unity.
- The detector measures broad region energy, not a center frequency.
- A high shelf will respond differently to narrow sibilants, broadband hiss, and
  stacked harmonics even if they share a similar peak.

**Recommendation:** define the control text more literally:

`Shelf ceiling = peak level of the detector's shelf-region output. The transition is
-3 dB at cutoff for detector Q 0.7071; passband tends toward unity.`

This avoids implying that the ceiling corresponds to a single frequency point.

## P1 — Bell-Only Guards Need An Explicit Implementation Checklist

The spec says the dynamics gate changes from Bell-only to `{Bell, Low Shelf, High
Shelf}` (lines 72-76). In the current `JSFX/RCBitNova V0.2`, Bell-only checks appear
in multiple places:

- PDC / `any_b` activation: `slider(... type ...) == 0`
- Mode A processing gate
- Mode B processing gate

If one is missed, shelves may appear to work in one mode but fail to enable PDC,
skip processing, or silently stay static.

**Recommendation:** add an implementation checklist:

- Define a helper predicate conceptually: `dyn_type = type <= 2`.
- Update Mode A gate.
- Update Mode B gate.
- Update `any_b` / PDC gate.
- Keep HP/LP excluded: `type == 3 || type == 4` remains static-only.
- Add Python and live checks proving Low Shelf and High Shelf activate PDC in Mode B.

## P1 — State And Memory Map Are Too Vague

The spec says new detector/cut state is appended past the last V0.1 memory block
(lines 77-78), but does not specify offsets, block sizes, or reset behavior.

Shelf dynamics add at least:

- Shelf detector SVF state per band-channel.
- Shelf cut SVF state per band-channel for Mode A.
- Mode B split state if it cannot safely reuse Bell detector state.
- Potential previous type/mode tracking for state reset or smoothing.

The current handoff warns that state is instance-local and memory offsets are part
of the architecture invariants. A loose "append past the last block" invites overlap
bugs or stale integrator state when switching band type.

**Recommendation:** before code, add exact memory ranges and reset rules:

- New offsets and total `freembuf`/memory extent.
- What state resets when `type`, `mode`, `freq`, or `Q` changes.
- Whether reset is hard, smoothed, or intentionally not done.

## P2 — Scratchpad Verification Is Not Reproducible

The spec references `shelf_dyn_proto.py` and says 8/8 checks passed (lines 82-86),
but that scratchpad is not present in the worktree.

**Recommendation:** convert the scratch checks into permanent tests in
`tests/test_rcbitnova_dsp.py`, including:

- Shelf-region detector high/low magnitude shape.
- Mode A shelf dynamics off equals static shelf.
- Mode B shelf with Soft/Hard off equals identity for the split path.
- High/low shelf mirror symmetry.
- De-esser burst test.
- Low-shelf DC/subsonic behavior test.

## P2 — Mode B Signal Observation Point Needs To Be Stated

The spec says shelf detector is fed post-static-EQ in the band's placement domain
(lines 36-37). The current JSFX architecture runs global Mode B after the static and
Mode A pass, on the intermediate bus.

This distinction matters: a Mode B shelf detector may see previous bands and Mode A
cuts, not only its own static shelf output.

**Recommendation:** state the intended ordering explicitly:

`Mode B detectors observe the current post-static/post-Mode-A running bus at their
position in the global Mode B pass. The guarantee remains only for the extracted
split contribution, not for the summed output.`

If a different ordering is desired, the spec should describe how per-band Mode B is
interleaved with static bands.

## P2 — Low-Shelf Detector Can React To DC / Subsonic Energy

A low-shelf detector using the LP output with unity at DC will react to DC offset and
very low rumble. This may be desirable for a rumble tamer, but it can also cause
unexpected gain reduction from non-musical offset.

**Recommendation:** choose and test one behavior:

- Keep DC sensitivity and document it as intentional.
- Add a detector-only DC blocker / HP floor.
- Clamp the low-shelf detector's effective minimum frequency.

## Suggested Pre-Implementation Additions

Before implementing Phase S-A/S-B, update the spec or implementation plan with:

1. Mode B shelf Q decision.
2. Exact JSFX guard checklist for Bell/Low Shelf/High Shelf dynamics.
3. Exact new memory map and state reset policy.
4. Permanent Python tests replacing the scratchpad claims.
5. Live verification cases for high-shelf de-essing and low-shelf rumble/DC behavior.
