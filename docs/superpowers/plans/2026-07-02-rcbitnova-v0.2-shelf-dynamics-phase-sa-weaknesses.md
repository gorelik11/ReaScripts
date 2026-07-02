# RCBitNova V0.2 Phase S-A Plan - Weakness Review

**Date:** 2026-07-02  
**Reviewed plan:** `2026-07-02-rcbitnova-v0.2-shelf-dynamics-phase-sa.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

This review lists the weak points to tighten before handing the Phase S-A plan to an
implementation agent. The plan is generally strong: it keeps Mode B deliberately out
of S-A, moves scratchpad claims into permanent tests, adds ASCII coverage, documents
DC sensitivity, and gives concrete Python-to-JSFX transcription code. The remaining
risks are mostly around state reuse, brittle test thresholds, and deployment/live
verification details.

## P1 - Worktree Path Ambiguity Still Exists

The user-facing path `docs/superpowers/plans/2026-07-02-rcbitnova-v0.2-shelf-dynamics-phase-sa.md`
does not exist in the main worktree. The actual plan is in:

`/Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova/docs/superpowers/plans/2026-07-02-rcbitnova-v0.2-shelf-dynamics-phase-sa.md`

The plan correctly says to work in the `rcbitnova` worktree, but if a worker starts
from the main repo path and blindly follows the relative path, it will fail.

**Recommendation:** in the handoff message or task title, name the full worktree path.

## P1 - Shared State Reuse Has No Reset Policy

The plan intentionally adds no new memory blocks and reuses `dst`, `cst`, `eg`, and
`egh` for Bell and shelf dynamics (global constraints lines 17 and JSFX task lines
459-462 / 561). This is efficient and probably acceptable because band types are
exclusive.

The missing piece is state transition behavior. If a user switches a band from Bell
to High Shelf, Low Shelf to Bell, changes Dyn Mode, or sweeps frequency/Q while the
detector/cut integrators contain old state, the first samples after the change can
inherit stale SVF state and envelope values from a different topology.

**Recommendation:** add an explicit policy:

- Accept transient state carryover as a known behavior, or
- Reset `dst/cst/eg/egh` when `type` or `mode` changes, or
- Smooth/reset only when type class changes between Bell and Shelf.

If no reset is implemented in S-A, add it to the live checklist: switch Bell <-> High
Shelf while audio runs and listen for clicks or wild gain movement.

## P1 - S-A Defers Mode B Correctly, But Does Not Test The Deferral In Code

The plan carefully says Mode B gates stay Bell-only in S-A (global constraint line
19, self-review line 620). That is the right scope decision. However, it is only
covered by live checklist item 7, not by an automated guard.

A worker could accidentally change one of the Mode B gates while implementing the
new type checks and still pass the Python DSP tests, because those tests do not parse
the JSFX source.

**Recommendation:** add a small source-level regression test next to the ASCII guard:

- Read `JSFX/RCBitNova V0.2`.
- Assert the Mode B `any_b` gate still contains `slider(10*(b+1)+2) == 0`.
- Assert the Mode B sample gate still contains `slider(10*(b+1)+2) == 0`.

This is not elegant DSP testing, but it catches the exact S-A/S-B scope leak the plan
warns about.

## P1 - De-Esser Test Threshold Is Brittle

The high-shelf de-esser test says the measured reduction is `-6.272 dB`, with only
about `0.27 dB` of margin against `assert red_db < -6.0` (lines 197-200). The comment
acknowledges not to tighten the bound, but the bound is already tight for a test that
may shift when detector Q, envelope math, or window boundaries change.

This can produce false failures during legitimate refactoring or slight DSP changes.

**Recommendation:** either:

- Use a wider behavior range, for example `-9.0 < red_db < -4.5`, plus tone/release
  invariants, or
- Assert against the intended measured value with a documented tolerance, for example
  `pytest.approx(-6.27, abs=0.75)`.

The goal is to catch "not de-essing" and "over-killing", not to lock one exact release
trajectory forever.

## P1 - JSFX Transcription Is Large Enough To Deserve A Source Diff Checklist

Task 4 inserts a substantial JSFX block, but the automated oracle cannot execute
JSFX. The plan has a good manual self-review checklist, yet it does not require a
focused diff review after patching.

**Recommendation:** add a required command before commit:

`git diff -- JSFX/RCBitNova\ V0.2 tests/test_rcbitnova_dsp.py tools/rcbitnova_dsp.py`

Then explicitly inspect:

- The Bell block is unchanged.
- Shelf block is inserted before writeback.
- Mode B gates are unchanged.
- Desc/header additions are ASCII-only.
- No unrelated slider or memory map churn.

This keeps the "additive sibling block" promise honest.

## P2 - Test Count Expectations Are Fragile

The plan states exact expected totals: 46, 49, 51, 52 passed. This is useful for
orientation, but stale counts are a common source of confusion if another worker has
already added tests on the branch.

**Recommendation:** keep the totals, but phrase them as approximate baselines:

`Expected at current plan baseline: 52 passed. If the total differs, verify that all
new Phase S-A tests are present and passing.`

## P2 - Deployment And Memory Update Need Permission Awareness

Task 5 deploys to:

`$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.2`

and asks to update:

`~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`

Both are outside the repo. In a sandboxed Codex session, these writes may require
approval. The plan is written for local agentic execution, but a worker following it
inside this environment may hit a permission wall.

**Recommendation:** add a note:

`In Codex sandboxed runs, deployment to REAPER Effects and edits under ~/.claude may
require approval/escalation. Do not bypass; request approval or ask Dima to deploy.`

## P2 - The ASCII Guard Only Covers JSFX After Task 4

The plan adds `test_jsfx_v02_is_pure_ascii`, which is good. But the plan itself also
instructs exact commit messages and comments. A worker can still paste non-ASCII into
the JSFX between running `-k ascii` and the full oracle, or into a later manual hotfix
before deploy.

**Recommendation:** make the ASCII guard part of every post-JSFX-edit verification:

- Run `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k ascii` immediately after
  editing JSFX.
- Run the full oracle after that.
- Re-run `-k ascii` after any last-minute JSFX hotfix.

## P2 - Live Checklist Should Include Type-Switch And Silence Tail Cases

The live checklist covers de-essing, hard stage, low shelf, placement, Mode B static
behavior, and CPU. It does not explicitly test:

- Switching a dynamic band between Bell, Low Shelf, and High Shelf while audio runs.
- Silence after a strong shelf reduction, to catch denormal tails or stuck envelope.
- Very low-frequency/DC-ish low-shelf behavior on real material.

These are exactly the risky edges introduced by shared state and DC-sensitive LP
detection.

**Recommendation:** add three live checks:

1. While audio plays, switch B1 type Bell -> High Shelf -> Low Shelf and confirm no
   explosive transient or stuck reduction.
2. After a strong sibilant/boom burst, stop audio or play silence and confirm CPU and
   output settle normally.
3. Test a low-shelf band on material with rumble/offset-like low energy and confirm
   the documented DC sensitivity feels acceptable.

## Suggested Plan Edits Before Execution

1. Add a state reset/carryover decision for shared `dst/cst/eg/egh`.
2. Add source-level tests that Mode B shelf gates remain Bell-only during S-A.
3. Widen or reframe the de-esser dB assertion.
4. Add a required `git diff` self-review before the JSFX commit.
5. Add permission notes for REAPER deploy and `~/.claude` memory updates.
6. Expand live verification with type-switch, silence-tail, and low-frequency edge
   cases.
