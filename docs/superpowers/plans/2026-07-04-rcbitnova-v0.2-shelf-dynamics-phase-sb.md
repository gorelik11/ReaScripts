# RCBitNova V0.2 Phase S-B: Mode B Shelf Split Limiter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend RCBitNova Mode B (band-split bit-exact limiter, currently Bell-only) to Low Shelf and High Shelf band types — a phase-clean shelf-region brickwall / de-esser — completing V0.2's shelf dynamics.

**Architecture:** Python DSP mirror first (TDD, equivalence + behavioral tests), then a minimal JSFX edit. Mode B shelf is the existing Bell Mode B split limiter with ONE change: the extracted branch. Bell extracts the k-scaled bandpass (`dk*v1`); shelf extracts the shelf region via the same fixed-Q=0.7071 detector SVF already built in S-A — HP tap (`x - dk*v1 - v2`) for High Shelf, LP tap (`v2`) for Low Shelf. Perfect reconstruction `LP + k*BP + HP == input` makes the remainder pass untouched; the limited branch's delta is added back to the delayed dry bus, exactly as Bell. Everything else (lookahead ring, worst-peak, Soft+Hard cascade, bit-exact clamp, PDC) is reused unchanged.

**Tech Stack:** Python 3.11 stdlib (pytest), EEL2/JSFX, REAPER for live verification.

**Design proven numerically before this plan** (scratchpad `shelf_modeb_proto.py`, 2026-07-04): perfect-reconstruction identity max error **5.551e-17** (both shelf types, below the 2e-16 target); both-stages-off == pure delay **5.551e-17**; recovered clamped-branch peak lands **bit-exactly at ceiling** (HS 0.249999, LS 0.250000) from raw branch peaks 0.6417 / 0.7968; stereo `dual_lr`==independent, `dual_ms`==independent-M/S, `linked` L==R; output finite under extreme (10.0-amplitude) drive.

## Global Constraints

- Work in `~/projects/reascripts/.claude/worktrees/rcbitnova` (branch `rcbitnova`). All paths below are relative to it.
- NEVER modify `JSFX/RCBitNova V0.1` (frozen, tag `rcbitnova-v0.1`) or `JSFX/RCBitNova V0.2 SA` (frozen S-A safety fallback, tag `rcbitnova-v0.2-sa`). All JSFX edits go to `JSFX/RCBitNova V0.2`.
- Python: 3.11, **stdlib only** (no numpy/scipy). Oracle: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` — **53 tests green at plan start**; each task only adds green tests. If totals differ, verify the S-B tests below are present and passing rather than trusting arithmetic.
- **BIT-ACCURACY INVARIANT (paramount, spec section 8):** all ceilings/gains stay in the LINEAR `2^(-bits)` domain. No `log`, `log10`, dB thresholds, `pow(10, x/20)`, or `20*` gain conversion anywhere in the new code path. The clamp compares linear detector level to linear ceiling directly (`cH/ps`, `cS/worst`). The only `log10` allowed is human-readable dB in TEST measurement code, never the DSP path.
- **HONEST GUARANTEE (spec section 4):** Mode B clamps the SPLIT BRANCH's own contribution to the ceiling, NOT the summed output. On pure tones the summed output peak can even rise above the input (phase recombination of a complementary split) — this is expected and documented. Tests MUST assert the branch contribution is clamped, NOT that the summed output peak <= input.
- `JSFX/RCBitNova V0.2` must stay **pure ASCII** (non-ASCII crashed REAPER's ascii codec before). No em-dashes in JSFX.
- Instance-local memory only (never `gmem`). Phase S-B adds **NO new memory blocks**: shelf Mode B reuses `dst` (detector/extraction state), `mb_band`/`mb_peak` (lookahead ring), `mbenv`/`mbgc`/`mbeh` (cascade envelopes), exactly as Bell. Band type is mutually exclusive (Bell XOR Shelf XOR HP/LP), so slots never alias.
- EEL2 gotchas: no empty ternary branch (both sides of every `? ( ) : ( )` non-empty); no `1e-...` scientific literals in new code; nested ternary `a ? x : (b ? y : z)` is fine.
- **HARD REQUIREMENT (adversarial review, carried from S-A):** the TWO Bell-only Mode B gates must flip together **in one commit**, AND the guard test must be updated in that SAME commit:
  - `@slider` any_b/PDC gate (currently line ~221): `... && mbmode[b] == 1 && slider(10*(b+1)+2) == 0`.
  - `@sample` Mode B pass gate (currently line ~434): identical predicate.
  Both change `slider(10*(b+1)+2) == 0` (Bell only) to `slider(10*(b+1)+2) <= 2` (Bell 0, Low Shelf 1, High Shelf 2; HP=3/LP=4 stay static). Flipping only one creates PDC-without-processing or processing-without-PDC. Mode A gates are NOT touched — S-A already split Mode A into a Bell block (`mbmode==0`, Bell-only) and a separate shelf block (`ty==1||ty==2`), so Mode A shelf already works. That is why post-S-A only TWO gates carry the `mbmode==1` Bell-only string (the spec section 5 "three gate" checklist predates the S-A two-block split).
- Detector semantics: the split SVF is hard-coded to fixed Q = 0.7071 (`DET_Q`), never the band's shelf Q (spec section 4 Q-asymmetry: band Q shapes only the Mode A cut). For shelf bands `det[b*4..]` already holds the fixed-0.7071 coefficients from S-A's `setup_band_dyn`.
- Every commit ends with the CURRENT model's trailer, e.g. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` (update to whatever model runs the task).
- State transitions (spec section 5): switching band type/freq/Q live leaves stale `dst`/`mb_band`/`mbenv` state — accepted warm-up, converges in ms; NO per-sample reset.

---

### Task 1: Python Mode B shelf split — `_shelf_modeb_cascade_ch` / `shelf_modeb_cascade` / `shelf_modeb_cascade_stereo` + reconstruction & branch-clamp tests

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append after `shelf_cascade_stereo`, the last function)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: `DET_Q`, `svf_make`, `svf_process` (existing); mirrors `_modeb_cascade_ch` (existing) line-for-line except the extraction tap.
- Produces:
  - `shelf_modeb_cascade(signal, shelf_type, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms, soft_on, hard_on, gsmooth=400.0) -> list` (single channel);
  - `shelf_modeb_cascade_stereo(Lin, Rin, shelf_type, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms, soft_on, hard_on, dyn_mode, gsmooth=400.0) -> tuple[list, list]` with `dyn_mode` in `("linked","dual_lr","dual_ms")`;
  - `_shelf_modeb_cascade_ch(...)` internal.
  `q` is accepted in the public functions for API parallelism with `shelf_cascade`; Mode B split intentionally ignores the band Q (fixed `DET_Q`). Task 3 (JSFX) mirrors `_shelf_modeb_cascade_ch`'s extraction tap.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
# ---- Phase S-B: Mode B shelf split limiter ----

def _shelf_branch(x, shelf_type, fc, sr):
    """The exact split branch the plugin extracts: HP tap for high shelf, LP tap
    for low shelf, via the fixed-DET_Q detector SVF (same series as the plugin)."""
    ft = "hp" if shelf_type == "highshelf" else "lp"
    return dsp.svf_process(dsp.svf_make(ft, fc, dsp.DET_Q, 1.0, sr), x)


def test_shelf_modeb_transparent_below_ceiling_is_exact_identity():
    # Spec 6.2 perfect-reconstruction + Mode B idle: with the ceiling far above the
    # signal the limiter never engages, so the summed output == input delayed by the
    # lookahead, to machine precision (proto: max err 5.551e-17).
    sig = [0.3*math.sin(0.21*i) + 0.2*math.sin(1.7*i + 0.5) for i in range(4000)]
    L = max(1, int(2.0*0.001*SR + 0.5))
    for st in ("lowshelf", "highshelf"):
        out = dsp.shelf_modeb_cascade(sig, st, 3000.0, 0.7071, SR, 0.9, 0.95,
                                      2.0, 80.0, True, True)
        for n in range(L, len(sig)):
            assert abs(out[n] - sig[n - L]) < 2e-16


def test_shelf_modeb_both_stages_off_is_pure_delay():
    # Spec 6.4: Mode B with both stages off contributes zero correction -> output is
    # the input delayed by the lookahead (proto: 5.551e-17).
    sig = [0.5*math.sin(0.3*i) for i in range(3000)]
    L = max(1, int(2.0*0.001*SR + 0.5))
    for st in ("lowshelf", "highshelf"):
        out = dsp.shelf_modeb_cascade(sig, st, 2500.0, 0.7071, SR, 0.25, 0.5,
                                      2.0, 80.0, False, False)
        for n in range(L, len(sig)):
            assert abs(out[n] - sig[n - L]) < 1e-15


def test_shelf_modeb_highshelf_clamps_branch_at_ceiling():
    # Spec 4 honest guarantee + 6.7 (Mode B de-esser): the extracted HIGH-SHELF
    # region contribution is brick-clamped bit-exactly to the hard ceiling. Recover
    # the clamped branch from output vs delayed input plus an independent HP
    # extraction of the input (proto: recovered peak 0.249999 at ceiling 0.25, from
    # a raw branch peak of 0.6417 -> it genuinely engaged).
    w = 2*math.pi*8000.0/SR
    x = [0.8*math.sin(w*i) for i in range(1 << 15)]
    cH = 0.25
    y = dsp.shelf_modeb_cascade(x, "highshelf", 6000.0, 0.7071, SR, cH, cH,
                                2.0, 80.0, False, True)   # hard only
    L = max(1, int(2.0*0.001*SR + 0.5))
    branch = _shelf_branch(x, "highshelf", 6000.0, SR)
    clamped = [branch[n - L] + (y[n] - x[n - L]) for n in range(L, len(x))]
    assert max(abs(v) for v in clamped[-4000:]) <= cH * 1.001        # clamped to ceiling
    assert max(abs(v) for v in branch[-4000:]) > cH * 2.0            # and it engaged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "shelf_modeb"`
Expected: 3 FAIL — `AttributeError: module 'rcbitnova_dsp' has no attribute 'shelf_modeb_cascade'`.

- [ ] **Step 3: Implement** — append to `tools/rcbitnova_dsp.py`:

```python
def _shelf_modeb_cascade_ch(chA, chB, two, shelf_type, fc, sr, cS, cH, look_ms, rel_ms,
                            soft_on, hard_on, linked, gsmooth):
    """Mode-B shelf split limiter, 1 or 2 channels (mirror of _modeb_cascade_ch).
    Extracts the shelf region via a fixed-DET_Q SVF: HP tap (high shelf) or LP tap
    (low shelf), limits that branch through the same Soft+Hard lookahead cascade as
    Bell, and passes the remainder untouched (perfect reconstruction LP + k*BP + HP
    == input). Band shelf Q is intentionally unused (spec section 4 Q-asymmetry)."""
    high = shelf_type == "highshelf"
    det = svf_make("hp" if high else "lp", fc, DET_Q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    bA = [0.0]*size; pA = [0.0]*size; dA = [0.0]*size
    bB = [0.0]*size; pB = [0.0]*size; dB = [0.0]*size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envSA = gcA = envHA = 1.0
    envSB = gcB = envHB = 1.0
    outA = []
    outB = [] if two else None

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    def _stage(worst, envS, gc, envH):
        if soft_on:
            tS = cS / worst if worst > cS else 1.0
            envS = tS if tS < envS else min(1.0, tS + (envS - tS) * rel)
            gc = (gc * gsmooth + envS) * inv_g
        else:
            gc = 1.0
        if hard_on:
            ps = worst * gc
            tH = cH / ps if ps > cH else 1.0
            envH = tH if tH < envH else min(1.0, tH + (envH - tH) * rel)
        else:
            envH = 1.0
        return gc * envH, envS, gc, envH

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - iA2; v1a = a1*iA1 + a2*v3; v2 = iA2 + a2*iA1 + a3*v3
        iA1 = 2.0*v1a - iA1; iA2 = 2.0*v2 - iA2
        ba = (xa - k*v1a - v2) if high else v2
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        if two:
            v3 = xb - iB2; v1b = a1*iB1 + a2*v3; v2 = iB2 + a2*iB1 + a3*v3
            iB1 = 2.0*v1b - iB1; iB2 = 2.0*v2 - iB2
            bb = (xb - k*v1b - v2) if high else v2
            bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA)
        wb = _worst(pB) if two else 0.0
        if linked:
            w = wa if wa > wb else wb
            gA, envSA, gcA, envHA = _stage(w, envSA, gcA, envHA)
            gB = gA
        else:
            gA, envSA, gcA, envHA = _stage(wa, envSA, gcA, envHA)
            gB = 1.0
            if two:
                gB, envSB, gcB, envHB = _stage(wb, envSB, gcB, envHB)
        rpos = (wpos - L) % size
        bda = bA[rpos]; lim = bda * gA
        if hard_on and abs(lim) > cH:
            lim = cH if lim > 0 else -cH
        outA.append(dA[rpos] - bda + lim)
        if two:
            bdb = bB[rpos]; lim = bdb * gB
            if hard_on and abs(lim) > cH:
                lim = cH if lim > 0 else -cH
            outB.append(dB[rpos] - bdb + lim)
        wpos = (wpos + 1) % size
    return outA, outB


def shelf_modeb_cascade(signal, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                        look_ms, rel_ms, soft_on, hard_on, gsmooth=400.0):
    # q accepted for API parallelism with shelf_cascade; Mode B split ignores the
    # band Q (fixed DET_Q, spec section 4 Q-asymmetry).
    out, _ = _shelf_modeb_cascade_ch(signal, signal, False, shelf_type, fc, sr,
                                     ceil_soft, ceil_hard, look_ms, rel_ms,
                                     soft_on, hard_on, False, gsmooth)
    return out


def shelf_modeb_cascade_stereo(Lin, Rin, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                               look_ms, rel_ms, soft_on, hard_on, dyn_mode, gsmooth=400.0):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _shelf_modeb_cascade_ch(M, S, True, shelf_type, fc, sr, ceil_soft,
                                         ceil_hard, look_ms, rel_ms, soft_on, hard_on,
                                         False, gsmooth)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _shelf_modeb_cascade_ch(Lin, Rin, True, shelf_type, fc, sr, ceil_soft,
                                   ceil_hard, look_ms, rel_ms, soft_on, hard_on,
                                   linked, gsmooth)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 56 passed (53 + 3).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Phase S-B Python - Mode B shelf split limiter (perfect-reconstruction)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Python behavioral coverage — low-shelf mirror + stereo modes + close S-A dual-path gap

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append at end; no production code)

**Interfaces:**
- Consumes: `shelf_modeb_cascade`, `shelf_modeb_cascade_stereo`, `_shelf_branch` (Task 1); `shelf_cascade`, `shelf_cascade_stereo` (S-A); `_stereo_sigs` (existing test helper).
- Produces: nothing — characterization tests locking the low-shelf mirror, the three Mode B stereo modes, and the S-A Mode A shelf dual paths flagged as an open Minor in the S-A final review.

- [ ] **Step 1: Write the tests** — append to `tests/test_rcbitnova_dsp.py`:

```python
def test_shelf_modeb_lowshelf_clamps_branch_at_ceiling():
    # Spec 6.6 mirror symmetry (Mode B): the extracted LOW-SHELF region contribution
    # is brick-clamped bit-exactly to the ceiling (proto: recovered peak 0.250000 at
    # ceiling 0.25, from a raw branch peak of 0.7968).
    w = 2*math.pi*60.0/SR
    x = [0.8*math.sin(w*i) for i in range(1 << 16)]
    cH = 0.25
    y = dsp.shelf_modeb_cascade(x, "lowshelf", 200.0, 0.7071, SR, cH, cH,
                                2.0, 200.0, False, True)
    L = max(1, int(2.0*0.001*SR + 0.5))
    branch = _shelf_branch(x, "lowshelf", 200.0, SR)
    clamped = [branch[n - L] + (y[n] - x[n - L]) for n in range(L, len(x))]
    assert max(abs(v) for v in clamped[-4000:]) <= cH * 1.001
    assert max(abs(v) for v in branch[-4000:]) > cH * 2.0


def test_shelf_modeb_dual_lr_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.shelf_modeb_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                            0.2, 0.4, 2.0, 120.0, 1, 1, "dual_lr")
    assert Lo == dsp.shelf_modeb_cascade(L, "highshelf", 6000.0, 0.7071, SR,
                                         0.2, 0.4, 2.0, 120.0, 1, 1)
    assert Ro == dsp.shelf_modeb_cascade(R, "highshelf", 6000.0, 0.7071, SR,
                                         0.2, 0.4, 2.0, 120.0, 1, 1)


def test_shelf_modeb_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.shelf_modeb_cascade(M, "highshelf", 6000.0, 0.7071, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    So = dsp.shelf_modeb_cascade(S, "highshelf", 6000.0, 0.7071, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    Lo, Ro = dsp.shelf_modeb_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                            0.2, 0.4, 2.0, 120.0, 1, 1, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


def test_shelf_modeb_linked_identical_channels():
    w = 2 * math.pi * 8000.0 / SR
    mono = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    Lo, Ro = dsp.shelf_modeb_cascade_stereo(mono, list(mono), "highshelf", 6000.0,
                                            0.7071, SR, 0.2, 0.4, 2.0, 120.0, 1, 1, "linked")
    assert Lo == pytest.approx(Ro, abs=1e-12)


def test_shelf_modea_dual_lr_equals_independent():
    # Closes the S-A final-review open Minor: Mode A shelf dual_lr had no direct test.
    L, R = _stereo_sigs(1 << 13)
    Lo, Ro = dsp.shelf_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                      0.25, 0.5, 0.5, 60.0, True, False, "dual_lr")
    assert Lo == dsp.shelf_cascade(L, "highshelf", 6000.0, 0.7071, SR,
                                   0.25, 0.5, 0.5, 60.0, True, False)
    assert Ro == dsp.shelf_cascade(R, "highshelf", 6000.0, 0.7071, SR,
                                   0.25, 0.5, 0.5, 60.0, True, False)


def test_shelf_modea_dual_ms_equals_independent_ms():
    # Closes the S-A final-review open Minor: Mode A shelf dual_ms had no direct test.
    L, R = _stereo_sigs(1 << 13)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.shelf_cascade(M, "highshelf", 6000.0, 0.7071, SR, 0.25, 0.5, 0.5, 60.0, True, False)
    So = dsp.shelf_cascade(S, "highshelf", 6000.0, 0.7071, SR, 0.25, 0.5, 0.5, 60.0, True, False)
    Lo, Ro = dsp.shelf_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                      0.25, 0.5, 0.5, 60.0, True, False, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)
```

- [ ] **Step 2: Run the tests**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 62 passed (56 + 6). If any FAIL, it is a real bug in `_shelf_modeb_cascade_ch` or `_shelf_cascade_ch` (most likely the LP/HP tap or a stereo-mode wiring slip): STOP and debug; do not weaken assertions.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): Phase S-B - low-shelf mirror + Mode B stereo + close S-A Mode A dual gap

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: JSFX transcription into `JSFX/RCBitNova V0.2` — flip both Mode B gates + type-aware extraction tap + update guard test (one commit)

**Files:**
- Modify: `JSFX/RCBitNova V0.2` (desc line 1; header comment; `@slider` any_b gate ~line 221; `@sample` Mode B pass gate + extraction taps ~lines 434-468)
- Test: `tests/test_rcbitnova_dsp.py` (replace the S-A gate guard test in the same commit)

**Interfaces:**
- Consumes: the verified Python `_shelf_modeb_cascade_ch` (Task 1) as the transcription source; existing JSFX memory blocks `det`, `dst`, `mb_band`, `mb_peak`, `mbenv`, `mbgc`, `mbeh` — NO new blocks. Slider surface unchanged.
- Produces: `JSFX/RCBitNova V0.2` with working Mode B shelf split limiter.

CRITICAL — line numbers drift; locate every edit by its surrounding code, not the cited numbers. If an anchor does not match what this task describes, STOP and report BLOCKED.

- [ ] **Step 1: Replace the S-A gate guard test with the S-B gate-enabled test** — in `tests/test_rcbitnova_dsp.py`, find `test_jsfx_v02_modeb_gates_stay_bell_only_in_sa` and replace that whole function with:

```python
def test_jsfx_v02_modeb_gates_enable_shelf():
    # Phase S-B: BOTH Mode B gates (@slider any_b/PDC and the @sample Mode B pass)
    # must include shelf types via the `<= 2` predicate (Bell 0, Low Shelf 1, High
    # Shelf 2; HP=3/LP=4 stay static). Exactly two occurrences; if you change this
    # you are altering the Mode B gating and must update this test in the SAME commit.
    text = _jsfx_v02_text().decode("ascii")
    gate = "mbmode[b] == 1 && slider(10*(b+1)+2) <= 2"
    assert text.count(gate) == 2, (
        "Mode B shelf-enabled gate expected exactly twice (any_b + sample pass); "
        "flipping only one gate creates PDC-without-processing or the reverse")
    # the old Bell-only predicate must be fully gone (no half-flip left behind)
    assert "mbmode[b] == 1 && slider(10*(b+1)+2) == 0" not in text
```

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "gates or ascii"`
Expected: `test_jsfx_v02_modeb_gates_enable_shelf` FAILS (V0.2 still has the `== 0` gates), `test_jsfx_v02_is_pure_ascii` PASSES. This RED proves the test is coupled to the gate flip you make next.

- [ ] **Step 2: Flip the `@slider` any_b / PDC gate** — in `JSFX/RCBitNova V0.2`, find the `any_b` loop (currently ~line 221):

```
  (slider(50 + 10*b + 1) == 1 && mbmode[b] == 1 && slider(10*(b+1)+2) == 0) ? any_b = 1;
```

replace `slider(10*(b+1)+2) == 0` with `slider(10*(b+1)+2) <= 2`:

```
  (slider(50 + 10*b + 1) == 1 && mbmode[b] == 1 && slider(10*(b+1)+2) <= 2) ? any_b = 1;
```

- [ ] **Step 3: Flip the `@sample` Mode B pass gate and make the extraction tap type-aware** — find the Mode B band loop (currently ~line 434). Change the pass gate the same way:

```
      (slider(50 + 10*b + 1) == 1 && mbmode[b] == 1 && slider(10*(b+1)+2) <= 2) ? (
```

Then, immediately after the `pl = slider(10*(b+1)+8);` line inside that gate, add a band-type read (the existing `qb = bp[b*3+1];` line stays; it is unused by Mode B, harmless):

```
        ty = slider(10*(b+1)+2);
```

Then change the channel-A band extraction. Find (currently ~line 459):

```
        bA = dk * v1;
```

replace with the type-aware tap (High Shelf ty==2 -> HP; Low Shelf ty==1 -> LP; Bell ty==0 -> k*BP):

```
        bA = ty == 2 ? (xa - dk*v1 - v2) : (ty == 1 ? v2 : dk*v1);
```

Then change the channel-B extraction. Find (currently ~line 468, inside the `two ?` block):

```
          bB = dk * v1;
```

replace with:

```
          bB = ty == 2 ? (xb - dk*v1 - v2) : (ty == 1 ? v2 : dk*v1);
```

(Everything else in the Mode B block — ring write, worst-peak scan, Soft+Hard cascade, the `abs(limA) > cH` clamp, `dcA = limA - bdA`, PDC/bus write-back — is unchanged. For a shelf band `det[b*4..]` already holds the fixed-0.7071 coefficients from `setup_band_dyn`, so `dk = 1/0.7071` and `v1`/`v2` are the fixed-Q BP/LP states, exactly as the Python.)

- [ ] **Step 4: Bump the desc line and document Mode B shelf** — replace line 1:

```
desc: RCBitNova V0.2 - Bit-Accurate M/S Dynamic EQ (static + Mode A + Mode B Soft/Hard cascade + shelf dynamics A+B)
```

and add to the header comment block (after the shelf-dynamics lines from S-A, pure ASCII):

```
// Shelf Mode B (split limiter): extracts the shelf region (HP branch for High
// Shelf, LP branch for Low Shelf) via the fixed-Q 0.7071 SVF, brick-limits that
// branch to the ceiling, and passes the remainder untouched (perfect
// reconstruction). The guarantee bounds the extracted region contribution, not
// the summed output. The band Q shapes only the Mode A cut, never the Mode B split.
```

- [ ] **Step 5: Transcription self-review (line-by-line, against Task 1's Python)** — verify before committing; every item is a past live-crash class:

1. Extraction taps: `ty == 2` (High Shelf) -> `xa - dk*v1 - v2` (chA), `xb - dk*v1 - v2` (chB); `ty == 1` (Low Shelf) -> `v2`; else (Bell) -> `dk*v1`. Matches Python `ba = (xa - k*v1a - v2) if high else v2` for shelf, `k*v1a` for bell.
2. `dk` and `v1`/`v2` are the fixed-Q detector states (shelf `det[]` set to 0.7071 in `setup_band_dyn` since S-A); the split never reads a band-Q coefficient. `qb` is read but unused (leave as-is).
3. No empty ternary branches; the nested `ty == 2 ? (...) : (ty == 1 ? (...) : (...))` has statements in every arm.
4. No scientific literals (`1e-...`) in the new code.
5. State slots unchanged from Bell Mode B: `dst[b*4..]`, `mb_band`/`mb_peak` rings, `mbenv`/`mbgc`/`mbeh` — shared safely (band type exclusive).
6. Both Mode B gates now read `slider(10*(b+1)+2) <= 2`; the old `== 0` string is gone from the file (the guard test enforces both facts).
7. Mode A gates untouched: the Bell Mode A gate still says `slider(...) == 0 && mbmode[b] == 0`, the shelf Mode A gate still says `(ty == 1 || ty == 2) && mbmode[b] == 0`.
8. File byte-pure ASCII: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k ascii` passes.

- [ ] **Step 6: Run the full oracle**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 62 passed (unchanged count — Step 1 replaced one test, did not add). Confirm `test_jsfx_v02_modeb_gates_enable_shelf` and `test_jsfx_v02_is_pure_ascii` are both green.

- [ ] **Step 6b: Focused diff review before committing** — run:

```bash
git diff -- "JSFX/RCBitNova V0.2" tests/test_rcbitnova_dsp.py
```

Confirm by eye, hunk by hunk:
1. Only the two gate lines (`any_b`, Mode B pass) changed `== 0` -> `<= 2`; nothing else near them moved.
2. Only the two extraction lines (`bA`, `bB`) and the one added `ty = ...` line changed inside the Mode B block; the ring/cascade/clamp/PDC lines are untouched.
3. The Bell Mode A block and the shelf Mode A block (S-A) show ZERO changed lines.
4. Desc/header additions are ASCII-only; no slider or `@init` memory-map lines changed.
5. The test diff is only the guard-test replacement (no other test touched).

- [ ] **Step 7: Commit** (gates + taps + guard test together — the hard requirement)

```bash
git add "JSFX/RCBitNova V0.2" tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): Phase S-B JSFX - Mode B shelf split limiter (flip both gates + type-aware tap)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Deploy + live verification with Dima + push + tag V0.2

**Files:**
- Deploy copy only (no repo changes except the memory-file note in Step 5).

- [ ] **Step 1: Deploy to REAPER**

```bash
cp "JSFX/RCBitNova V0.2" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.2"
```

(The frozen `RCBitNova V0.2 SA` fallback is NOT overwritten — it stays loadable. In a sandboxed run these writes may need approval; do not bypass. After ANY JSFX hotfix during live testing, re-run `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "ascii or gates"` before redeploying.)

- [ ] **Step 2: Live checklist (Dima drives, via FX window or TCP)** — on real program material:

1. Load `RCBitNova V0.2` fresh — plugin loads with no EEL2 syntax error (the transcription gate).
2. Sanity/regression: bypass on/off = clean null; a Bell band in Mode B behaves exactly as before S-B; a shelf band in Mode A behaves exactly as after S-A.
3. **High Shelf Mode B de-esser:** B1 Type = High Shelf, ~6 kHz, Dyn on, Mode B, Hard on (ceiling ~2 bits) — sibilant peaks in the shelf region are brick-limited; body untouched.
4. **PDC activates (the review guard risk):** enabling High Shelf Mode B reports plugin latency = Lookahead; disabling it returns latency to 0. Repeat for Low Shelf. This is the explicit spec section 6 live check.
5. **Soft / cascade:** Soft on (PurestGain ride toward Soft Ceiling); then Soft+Hard cascade (two ceilings, "last policeman") on the shelf region.
6. **Low Shelf Mode B:** Type = Low Shelf, ~150-200 Hz, Hard on — low-end transient peaks tamed; top untouched.
7. **Placements:** Mid-only HS Mode B (Side untouched); Both + Dual M/S; Linked (no width pumping).
8. **Honest-guarantee sanity:** on a pure loud tone in the shelf region the summed output peak may not drop (documented, spec section 4) — judge on real material, where the region is a small part of the mix and de-essing is audible.
9. **Type switch under audio:** flip B1 Type Bell -> High Shelf -> Low Shelf -> Bell with Dyn on + Mode B playing — at most a brief warm-up, NO explosive transient / click / stuck reduction / distortion. If it distorts: reload `RCBitNova V0.2 SA` and reproduce in the Python mirror first (spec section 8).
10. **Silence tail:** after a strong burst, play silence — CPU and output settle; envelopes release to 1, no stuck gain.
11. **CPU:** no meaningful increase vs the S-A build with one dynamic shelf in Mode B.

- [ ] **Step 3: On any failure** — do NOT hunt by ear in REAPER. Reload `RCBitNova V0.2 SA`, reproduce in the Python mirror first (spec section 8), fix in Python if behavioral (then re-transcribe) or in JSFX if a pure transcription slip; re-run the full oracle; redeploy; re-check.

- [ ] **Step 4: After Dima confirms — push + tag V0.2 complete**

```bash
git push origin rcbitnova
git tag -a rcbitnova-v0.2 -m "RCBitNova V0.2 - shelf dynamics complete (S-A Mode A + S-B Mode B), live-verified"
git push origin rcbitnova-v0.2
```

(This is the point where V0.2 is fully done — S-A AND S-B both live-verified — so the `rcbitnova-v0.2` tag is now earned.)

- [ ] **Step 5: Update the auto-memory file** `~/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`: record S-B live status (verified or what failed), that V0.2 is complete and tagged `rcbitnova-v0.2`, and the next roadmap item (bell character models / phase modes / GUI).

---

## Plan self-review (done at write time)

- **Spec coverage:** section 2 detector (fixed Q for shelf) -> already in S-A `setup_band_dyn`, reused by Task 3. section 4 Mode B split -> Tasks 1 (Python) + 3 (JSFX); Q-asymmetry (band Q ignored) -> Task 1 comment + Task 3 constraint + header doc. section 5 gates/state-reuse -> Task 3 (two-gate flip + guard test; no new memory). section 6 permanent tests: item 2 split identity -> Task 1 `test_shelf_modeb_transparent_below_ceiling_is_exact_identity`; item 4 Mode B off == identity -> Task 1 `test_shelf_modeb_both_stages_off_is_pure_delay`; item 6 mirror -> Task 2 low-shelf; item 7 de-esser -> Tasks 1/2 branch-clamp. section 6 live checks incl. PDC-for-shelf -> Task 4 items 3-4. section 8 failure modes -> Global Constraints (bit-accuracy, honest guarantee, gate flip, NaN guards) + Task 4 items 9-10 + Step 3 recovery.
- **S-A open Minor closed:** Task 2 adds the Mode A shelf `dual_lr`/`dual_ms` tests the S-A final review flagged.
- **Placeholders:** none; every step has complete code or an exact command with expected output.
- **Type consistency:** `shelf_modeb_cascade` / `shelf_modeb_cascade_stereo` signatures match `shelf_cascade` conventions (`dyn_mode` strings identical); `_shelf_branch` test helper uses `svf_make("hp"/"lp", fc, DET_Q, ...)` identical to the extraction in `_shelf_modeb_cascade_ch`; the JSFX tap `ty == 2 ? (x - dk*v1 - v2) : (ty == 1 ? v2 : dk*v1)` maps term-for-term to the Python `(x - k*v1a - v2) if high else v2` (shelf) and `k*v1a` (bell).
- **Numerically pre-validated:** all test constants (5.551e-17 identity, 0.249999/0.250000 branch clamp, raw branch peaks 0.6417/0.7968, stereo equivalences) are measured from `shelf_modeb_proto.py`, not guessed.
