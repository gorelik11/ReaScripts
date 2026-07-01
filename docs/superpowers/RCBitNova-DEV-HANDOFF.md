# RCBitNova — Development Handoff (for continuing with Fable)

**Purpose:** everything a fresh agent session (e.g. Fable 5, `claude-fable-5`) needs to
continue developing the RCBitNova JSFX plugin without re-deriving context. Read this
first, then the spec, then the Python DSP mirror.

**Owner:** Dima Gorelik. **Branch:** `rcbitnova` (GitHub `gorelik11/ReaScripts`).
**Worktree:** `~/projects/reascripts/.claude/worktrees/rcbitnova/`.

---

## 1. What RCBitNova is

A mid-side **dynamic** parametric EQ for REAPER (JSFX), with **bit-denominated controls
and bit-accurate gain staging** (RCBit: gains/ceilings are powers of two, 1 bit = 6.0206 dB)
rather than dB logic. Think TDR Nova / FabFilter Pro-Q, but in bit logic.

**"Bit logic" scope (do not over-claim):** it lives in the *controls and gain stages*
(gains/ceilings/thresholds on the `2^n` grid; pure gain stages are exact `×2^n`), NOT in
the filter arithmetic — filtering is ordinary float DSP, as in every EQ. FIR/linear phase
does not change this.

---

## 2. Current status — V0.1 is FROZEN and working

`JSFX/RCBitNova V0.1` (git tag `rcbitnova-v0.1`) is the **stable working release** —
**do not modify it**. Every next iteration goes into a **new version file**
(`JSFX/RCBitNova V0.2`, `V0.3`, …): copy V0.1, work in the copy, tag when it works.

**Delivered & live-verified in V0.1:**
- Static engine: 5 filter types (Bell, Low/High Shelf, HP, LP), TPT-SVF (Simper), bit gain
  (Macro + Micro + Bit-Ratio per band), instance-local memory (fixes the old gmem
  cross-instance bug). 4 slider bands.
- Stereo **placement** per band: Both / Mid / Side / Left / Right (running-L/R engine).
- **Dynamics** per band, two modes:
  - **Mode A** = Dynamic EQ (bell-cut, phase-clean, no absolute guarantee).
  - **Mode B** = Band-split RCBit limiter (bit-exact clamp; guarantees the band's *own
    contribution* ≤ ceiling; global lookahead + PDC).
- **Soft + Hard cascade** (both A and B): independent Soft & Hard stages, two ceilings
  (Soft Ceiling + Hard Ceiling). Soft rides musically; Hard is the "last policeman".
- **Dyn Stereo Mode** for Both placement: Linked / Dual L/R / Dual M/S.
- Anti-denormal, bypass-null, PDC gated on bypass.

**Roadmap (not yet built):** shelf dynamics (dynamic de-esser); bell **character** models
(GML-8200/9500, Butterworth, house — parallelizable, good for multi-agent/Hermes); **phase
modes** (Linear-Phase FIR + Eco/HQ oversampling); **GUI** (FFT analyzer + draggable nodes
+ `@serialize`, expand to 8 bands — removes the current slider-reachability pain).

---

## 3. Canonical artifacts (read in this order)

1. **This handoff.**
2. **Design spec:** `docs/superpowers/specs/2026-06-29-rcbitnova-dynamic-eq-design.md` —
   architecture, dynamics model, placement, cascade, phase modes, quality, VST-port note.
3. **Python DSP mirror + tests (THE ORACLE):** `tools/rcbitnova_dsp.py` +
   `tests/test_rcbitnova_dsp.py` (42 tests, pure stdlib). This is the *language-neutral,
   verified reference* the JSFX mirrors. Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`.
4. **Phase plans:** `docs/superpowers/plans/2026-0*-rcbitnova-*.md` — each phase's complete
   code + TDD steps + live-verification checklist.
5. **The plugin:** `JSFX/RCBitNova V0.1` (frozen). Deployed copy runs from
   `~/Library/Application Support/REAPER/Effects/RCBitNova V0.1`.

---

## 4. The development method that works (follow it)

This recipe produced a correct plugin with almost no live debugging. Keep it.

1. **Design first.** Any new behaviour → update the spec section, get Dima's sign-off on
   the model (he thinks musically; give concrete options + a recommendation).
2. **Verify the DSP numerically in Python BEFORE writing a plan.** Prototype in a scratch
   script (steady tone / transient burst); confirm it does what's claimed and is stable.
   Only then commit code. (This caught/prevented every DSP error.)
3. **Add to the Python mirror with TDD.** New functions in `tools/rcbitnova_dsp.py`, tests
   in `tests/`. Prefer **equivalence tests**: a new cascade == the prior primitive when a
   stage is off (e.g. `modeb_cascade(soft_on=1,hard_on=0) == modeb_soft`). Powerful and cheap.
4. **Write a phase plan** (`docs/superpowers/plans/`) with the *complete* JSFX + Python
   code, no placeholders, a self-review, and — for risky DSP/integration — an **adversarial
   review** (dispatch a subagent to attack the plan for P0/P1). This found real bugs (PDC
   on bypass, MAX_LOOK too small) before they shipped.
5. **Transcribe Python → JSFX line-by-line** into the *new version file*. The math is
   already verified; the JSFX is a faithful transcription. Deploy (copy to REAPER Effects)
   and **live-verify with Dima** (he tests via TCP parameters or the FX window).
6. **Tag working versions**, push for backup.

**Testing reality:** JSFX cannot be unit-tested outside REAPER. The Python mirror is the
automated correctness guard; the live REAPER check confirms transcription + integration.

---

## 5. Architecture invariants (do NOT break)

- **Filters = TPT state-variable (Andy Simper / Cytomic).** `A = sqrt(gain_lin)`. Exact
  gain at cutoff (kills cramping). Per-sample: `v3=v0-ic2; v1=a1*ic1+a2*v3;
  v2=ic2+a2*ic1+a3*v3; ic1=2v1-ic1; ic2=2v2-ic2; out=m0*v0+m1*v1+m2*v2`. Coeffs per type
  are in `svf_make` (Python) / `svf_set` (JSFX). Bandpass detector mix `m1=k, k=1/q`
  (unity at fc); band level `= |k*v1|`.
- **Bit gain:** `gain_lin = 2^((Macro + Micro/100) * BitRatio)`. Ceilings:
  `2^(-(Macro + Micro/100))`.
- **Running signal is L/R.** Each band derives its domain by placement (Mid/Side/Left/Right
  or Both), processes, writes back to L/R. Both + Dual-MS works in M/S locally.
- **Instance-local memory only — NEVER `gmem`** (that was the original bug fixed). Current
  V0.1 memory map (offsets in `@init`): `cf=0, st=64, det=96, dst=128, cst=160, dp=192,
  dm=208, bp=216, eg=256, mb_band=1024, mb_peak, mbenv, mbmode, mbwpos, bus_dry, mbgc,
  mbeh, hc, egh`. When adding state, append past the last block.
- **Cascade model** (Soft+Hard, two ceilings), identical for A and B:
  `gSoft` (toward Soft Ceiling; Mode A: atk/rel envelope; Mode B: envelope + PurestGain
  smoothing) × `gHard` (instant attack toward Hard Ceiling, computed on `level·gSoft`).
  Mode B additionally bit-exact clamps at the Hard Ceiling. Mode A applies `gSoft·gHard`
  to a modulated bell-cut (no clamp).
- **Mode B lookahead:** one **global** lookahead L (a single plugin control), `pdc_delay=L`
  when any Mode-B band is active (and **0 when bypassed**). Detectors run on the un-delayed
  signal; corrections apply to a shared delayed L/R bus (`bus_dry`). Per-band contribution
  guarantee only (NOT the master sum — no broadband brickwall, by design).
- **Dynamics is Bell-only so far** (HP/LP never dynamic; shelf dynamics still to build).

---

## 6. EEL2 / JSFX gotchas (hard-won — will bite again)

- **No empty ternary branch.** `cond ? ( /*comment only*/ ) : (...)` → "syntax error : ) : (".
  Restructure to `cond2 ? (...)` or put a real statement inside.
- **No `1e-30` scientific literal** in this EEL2 build — it parses `1` then dangling `e-30`.
  Use `pow(2, -100)` etc.
- **Slider numbering is banked** to leave room: statics 11–48 (stride 10), dyn 51–88
  (stride 10), Hard bank 91–123 (stride 10). Read per-band sliders by index:
  `slider(base + offset)`. When adding params, use a fresh bank range.
- **Parenthesize nested-assignment clamps:** `abs(x) > c ? (x = x > 0 ? c : -c);`.
- **Ring modulo:** `(wp - i + MAX_LOOK) % MAX_LOOK` — one `+MAX_LOOK` is enough only while
  `i ≤ MAX_LOOK`. Keep `MAX_LOOK` ≥ worst-case lookahead (currently 2048 for 10 ms @ 192k).
- **State that can denormal** (SVF integrators on silent tails): the global `anti` ±tiny
  toggle on the L/R bus handles it.
- Functions are defined in `@init`; they're global thereafter.

---

## 7. How to work (commands)

```bash
cd ~/projects/reascripts/.claude/worktrees/rcbitnova        # the worktree, branch rcbitnova
python3 -m pytest tests/test_rcbitnova_dsp.py -q            # run the DSP oracle (stdlib only)
cp "JSFX/RCBitNova V0.2" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.2"   # deploy for live test
git tag -a rcbitnova-v0.2 -m "..." && git push origin rcbitnova rcbitnova-v0.2               # tag + backup
```

Python is 3.11, **stdlib only** (no numpy/scipy on this machine — magnitude via steady-state
sine or transfer-function `cmath`). Co-author trailer on commits:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` (update the model name if Fable).

---

## 8. Notes for a Fable-driven session

- Fable 5 (`claude-fable-5`) is capable; the **Python-verify-first discipline** is what keeps
  the JSFX correct regardless of model — do not skip it.
- For **bell characters** (roadmap): the models are independent — a natural fan-out
  (multiple agents, one character each, then synthesise). Each is a variation of the SVF
  bell's Q-vs-gain law / skirt shaping; verify each against a magnitude target in Python.
- For the **GUI** phase: reuse `spectrum.jsfx-inc` (LGPL, vendor it) for the analyzer;
  back every node param with a real slider (automation/preset/undo for free) + `@serialize`
  for editor-only state; expand `N_BANDS` to 8.
- Keep Dima in the loop on **musical model decisions** (he catches things like the Soft+Hard
  cascade and dual-M/S-for-toxic-side that shaped the design).
