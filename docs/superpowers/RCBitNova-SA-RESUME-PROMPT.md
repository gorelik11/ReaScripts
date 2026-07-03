# RCBitNova Phase S-A — Resume Prompt (for a fresh Opus/Claude session)

**Paste-able task:** continue executing Phase S-A (Mode A shelf dynamics) of RCBitNova
V0.2 via **superpowers:subagent-driven-development**, from the exact state below.
Previous session (Fable 5) ran out of session limits mid-execution; all state is
committed and ledgered — nothing is lost, do not redo completed work.

## Where

- Worktree (ALL work happens here): `~/projects/reascripts/.claude/worktrees/rcbitnova/`
  (branch `rcbitnova`). Relative paths below are from this root.
- Oracle: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` (Python 3.11, stdlib only).

## Read in this order (before doing anything)

1. This file.
2. Ledger (source of truth for progress): `.superpowers/sdd/progress.md` — Phase S-A
   section at the bottom.
3. The plan being executed (has complete code for every step):
   `docs/superpowers/plans/2026-07-02-rcbitnova-v0.2-shelf-dynamics-phase-sa.md`
4. Spec (approved + twice-reviewed): `docs/superpowers/specs/2026-07-02-rcbitnova-v0.2-shelf-dynamics-design.md`
5. Project handoff (method, invariants, EEL2 gotchas): `docs/superpowers/RCBitNova-DEV-HANDOFF.md`
6. Task briefs/reports so far: `.superpowers/sdd/task-{1,2}-brief.md`, `task-{1,2}-report.md`.

## Exact state at handoff (2026-07-03)

| Plan task | Status |
|---|---|
| Task 1 (Python primitives: `DET_Q`, `shelf_cut_coeffs` + 4 tests) | ✅ complete, commit `fc98b4a`, 46/46, **review clean** |
| Task 2 (Python `_shelf_cascade_ch`/`shelf_cascade`/`shelf_cascade_stereo` + 3 tests) | ✅ implemented+committed `30b380e`, 49/49 green, report written — **REVIEW PENDING** |
| Task 3 (behavioral tests: low-shelf mirror + DC) | ⬜ not started |
| Task 4 (JSFX transcription + ASCII/gate guards) | ⬜ not started |
| Task 5 (deploy + live verification with Dima + push) | ⬜ not started (needs Dima in REAPER) |

Baseline commit for Phase S-A: `954bac8`. Plan went through TWO pre-execution reviews
(internal adversarial: EXECUTE AS-IS; Codex weaknesses: all 6 items adopted, commit
`954bac8`). Do not re-review the plan — execute it.

## First actions of the fresh session

1. Verify state: `git log --oneline -3` (expect `30b380e`, `fc98b4a`, `954bac8`) and run
   the oracle (expect **49 passed**).
2. **Review Task 2** (it is implemented but unreviewed): generate the diff package
   with the SDD skill script
   (`~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/subagent-driven-development/scripts/review-package fc98b4a 30b380e`),
   dispatch a task-reviewer subagent (sonnet) with: the package path,
   `.superpowers/sdd/task-2-brief.md`, `.superpowers/sdd/task-2-report.md`, and the
   plan's Global Constraints. Loop fixes until clean; ledger the result.
3. Continue the SDD loop for Tasks 3 → 4 → 5 exactly per the skill: `task-brief` script
   to extract each brief, fresh implementer per task, reviewer after each, ledger line
   after each clean review.

## Execution notes that saved time / prevented bugs so far

- **Model selection:** the plan contains COMPLETE code — implementers for Tasks 3 are
  transcription+testing (cheapest tier worked: haiku). Task 4 (JSFX insert into a
  446-line EEL2 file, collision-sensitive) → use a mid/high tier (sonnet minimum) and
  its Step 5 self-review checklist + Step 6b focused diff review are MANDATORY.
  Reviewers: sonnet.
- **Commit trailer:** every commit ends with the CURRENT model's trailer, e.g.
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` (update name to whatever
  model actually runs).
- **Task 5 is not subagent-able:** deploy = `cp "JSFX/RCBitNova V0.2"
  "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.2"`, then Dima drives
  the 11-item live checklist in the plan (items 9-11 are the state-transition/silence/
  rumble edges). After his confirmation: `git push origin rcbitnova`, NO tag (tag only
  when all of V0.2 incl. S-B is done), update the auto-memory file
  `~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`.
- **Hard invariants:** never touch `JSFX/RCBitNova V0.1` (frozen, tag `rcbitnova-v0.1`);
  JSFX stays pure ASCII (guard test exists after Task 4); both Mode B gates stay
  Bell-only in S-A (gate-guard test enforces exactly 2 occurrences); no new JSFX memory
  blocks (reuse `dst`/`cst`/`eg`/`egh`).
- After ANY JSFX edit (incl. live-test hotfixes) re-run
  `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "ascii or gates"` before
  redeploying.

## After S-A is live-verified

Phase S-B (Mode B shelf split) has NO plan yet: run superpowers:writing-plans against
the same spec (§4). Carry the HARD requirement from the adversarial review: S-B must
flip BOTH Mode B gates (`@slider` ~line 213 `any_b`, `@sample` ~line 346) **and** update
`test_jsfx_v02_modeb_gates_stay_bell_only_in_sa` in the SAME commit. S-B plan must get
the same adversarial review before execution. Spec's permanent-test items 2 and 4
(split identity, Mode B off == identity) belong to S-B.

## Session hygiene for the main agent (why this file exists)

Fable 5 burned session limits fast because the main loop did design + plan + reviews +
orchestration in one session. Keep the main loop thin: dispatch subagents per the SDD
skill, keep briefs/reports/packages as FILES (never paste them into prompts), and
ledger after every task so any future session can resume from `progress.md` alone.
