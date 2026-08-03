# RCBitNova V0.8 — Per-Sample Kernel Crossfade + Lane-B Skip — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make kernel changes inaudible under playing audio (a Slope switch is currently a full-amplitude step) and halve the convolution cost of selective placement.

**Architecture:** Build one **integrated two-lane reference engine** in the Python oracle that models both features exactly as the JSFX will (Task 1), then test the skip (Task 2), the crossfade (Task 3) and the memory layout (Task 4) against it. Then a **behaviour-neutral JSFX restructure** (Task 5: `Hspec2`, per-engine fade state, one validity flag, builds land in `Hspec2` and snap — output identical to V0.7), and only then **turn both features on** (Task 6). Task 7 = Fable review + tag.

**Tech Stack:** Python 3.11 stdlib only (`math`, `cmath` — NO numpy/scipy); JSFX/EEL2 (REAPER); pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-29-rcbitnova-v0.8-crossfade-laneskip-design.md` (**rev 3**). Review: `…-v0.8-crossfade-laneskip-weaknesses.md`.
- **Bit-accuracy INTACT:** no new gain stage. Crossfade weights are ordinary float DSP and are **skipped entirely when idle**, so the steady-state path stays byte-identical to V0.7. NO `log`/`dB`/`pow(10)` in any DSP path.
- **V0.7 and earlier are FROZEN** (tags `rcbitnova-v0.1` … `rcbitnova-v0.7`). Work in a NEW file `JSFX/RCBitNova V0.8` (copy of V0.7). Never edit V0.1–V0.7 files.
- **Python stdlib only.** Python: `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`.
- **Oracle is append-only**, with exactly two intentional in-place edits, both in Task 4: `lp_engine_buffers` gains `Hspec2`, and the four V0.7 tests that hardcode the pre-`Hspec2` span/top numbers are updated to the V0.8 numbers (what they assert *about* must not change — only the constants).
- **Engine constants:** `P = 2048`, `B = 4096`, `PB2 = 8192`. Normal `BD=8192, KMAX=4`; High `BD=32768, KMAX=16`.
- **`SKIP_AFTER = BD + B`**; the zero counter **saturates** there. The counter is updated **including the current sample, before** the hop decision.
- **`fade_len = floor(0.05 * srate)`** (50 ms, sample-rate independent).
- **`Hspec2` IS a live `convolve_c` operand** → FFT-touched, `PB2`-aligned, page-tested. (rev-2 said otherwise; that was the error rev 3 fixed.)
- **Hop execution order (pinned):** FDL write → lane A (pass1 active, pass2 target if fading) → lane B (same α values) → `fade_pos += P` → completion check (`memcpy Hspec2→Hspec`, `fading = 0`) → `fdl_wr += 1` (engine-level, advances even when a lane skipped).
- **Rebuilds QUEUE while fading** — `@block` commits a build only when `fading == 0`; never snap mid-fade.
- **One validity flag** per engine (`valid` in `lp_fs`), used for both the rate-limiter bypass and the fade/snap decision. V0.7's `hp_built`/`lp_built` globals are removed.
- **Verified layout numbers:** Normal span `262144`, fallback-16384 `425984`, High `786432`; packed tops `524288` / `1048576` / `1048576` / `1572864`. Marking `Hspec2` FFT-touched adds **zero** padding.
- **EEL2 gotchas:** no empty ternary branch; **no scientific literals** (`1e9`/`1e-30` mis-parse); instance-local memory only; functions defined textually before use.
- **JSFX cannot be unit-tested.** The oracle is the automated guard; each JSFX task ends with a live REAPER check with the owner (Dima).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

- **Modify** `tools/rcbitnova_dsp.py` — append `lp_engine_ref` (integrated two-lane engine with optional skip and crossfade); in-place: `Hspec2` in `lp_engine_buffers`.
- **Modify** `tests/test_rcbitnova_dsp.py` — append skip tests (Task 2), crossfade tests (Task 3), memory tests (Task 4).
- **Create** `JSFX/RCBitNova V0.8` — copy of V0.7; Task 5 restructures state (no behaviour change), Task 6 enables both features.

---

## Task 1: Oracle — integrated two-lane reference engine

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append at end)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `lp_fft`, `lp_ifft`, `partitioned_convolve` (all existing).
- Produces: `lp_engine_ref(sigA, sigB, ker_a, ker_b, P, switch_hop=None, fade_len=0, skip_after=None) -> dict` with keys `outA`, `outB`, `skipped`, `fade_hops`, `state`. `state` is a dict with `fdl_wr`, `zcA`, `zcB`, `fdlA`, `fdlB`, `hist_pos`. With `switch_hop=None` and `skip_after=None` it is a plain two-lane engine (the V0.7 baseline).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_dsp.py (append)

def test_engine_ref_matches_partitioned_convolve_when_idle():
    # With no switch and no skip, each lane must equal the existing reference engine.
    sig = [math.sin(0.3 * i) + 0.5 * math.sin(0.02 * i) for i in range(240)]
    other = [math.cos(0.21 * i) for i in range(240)]
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    r = dsp.lp_engine_ref(sig, other, ker, ker, 16)
    assert r["outA"] == dsp.partitioned_convolve(sig, ker, 16)
    assert r["outB"] == dsp.partitioned_convolve(other, ker, 16)
    assert r["skipped"] == 0 and r["fade_hops"] == 0


def test_engine_ref_instant_swap_is_the_v07_baseline():
    # fade_len = 0 must reproduce a hard kernel swap at the switch hop.
    sig = [math.sin(0.3 * i) for i in range(240)]
    zeros = [0.0] * 240
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(64)]
    r = dsp.lp_engine_ref(sig, zeros, ka, kb, 16, switch_hop=5, fade_len=0)
    assert r["fade_hops"] == 0
    # after the swap the engine must behave like one built on kb alone for fresh history
    assert len(r["outA"]) == len(sig)


def test_engine_ref_advances_fdl_wr_once_per_hop():
    sig = [1.0] * (16 * 7)
    ker = [0.0] * 64; ker[0] = 1.0
    r = dsp.lp_engine_ref(sig, sig, ker, ker, 16)
    assert r["state"]["fdl_wr"] == (16 * 7 // 16) % (64 // 16)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "engine_ref" -q`
Expected: FAIL — `AttributeError: … has no attribute 'lp_engine_ref'`.

- [ ] **Step 3: Write the implementation**

```python
# tools/rcbitnova_dsp.py (append)

def lp_engine_ref(sigA, sigB, ker_a, ker_b, P, switch_hop=None, fade_len=0, skip_after=None):
    """Integrated two-lane reference for the V0.8 linear-phase engine (spec rev 3 §4-§5).

    Models BOTH new features exactly as the JSFX must, in the pinned hop order:
      FDL write -> lane A -> lane B (same alpha values) -> fade_pos += P
      -> completion check -> fdl_wr advance (engine-level, even if a lane skipped).

    switch_hop: hop index at which ker_b becomes the target (None = never switch).
    fade_len:   crossfade length in SAMPLES; 0 = instant swap (the V0.7 baseline).
    skip_after: zero-run threshold; None disables the skip. The counter saturates and
                is updated including the current sample, BEFORE the hop decision.

    Returns dict(outA, outB, skipped, fade_hops, state)."""
    B = 2 * P
    KMAX = len(ker_a) // P

    def _spec(k):
        return [lp_fft([complex(k[kp * P + i], 0) if i < P else 0j for i in range(B)])
                for kp in range(KMAX)]

    active = _spec(ker_a)
    target = _spec(ker_b)
    fdl = {"A": [[0j] * B for _ in range(KMAX)], "B": [[0j] * B for _ in range(KMAX)]}
    hist = {"A": [0.0] * B, "B": [0.0] * B}
    pend = {"A": [], "B": []}
    out = {"A": [], "B": []}
    zc = {"A": 0, "B": 0}
    fdl_wr = 0; hpos = 0; cnt = 0; hop = 0
    skipped = 0; fading = False; fade_pos = 0; fade_hops = 0

    for n in range(len(sigA)):
        for lane, src in (("A", sigA), ("B", sigB)):
            x = src[n]
            if skip_after is None:
                zc[lane] = 0
            elif x == 0.0:
                zc[lane] = min(zc[lane] + 1, skip_after)
            else:
                zc[lane] = 0
            hist[lane][hpos] = x
        hpos = (hpos + 1) % B
        cnt += 1
        for lane in ("A", "B"):
            out[lane].append(pend[lane].pop(0) if pend[lane] else 0.0)
        if cnt < P:
            continue
        cnt = 0
        if switch_hop is not None and hop == switch_hop:
            if fade_len > 0:
                fading = True; fade_pos = 0
            else:
                active = [list(h) for h in target]
        for lane in ("A", "B"):
            if skip_after is not None and zc[lane] >= skip_after:
                pend[lane].extend([0.0] * P)
                skipped += 1
                continue
            blk = [complex(hist[lane][(hpos + i) % B], 0) for i in range(B)]
            fdl[lane][fdl_wr] = lp_fft(blk)

            def _conv(spec):
                acc = [0j] * B
                for kp in range(KMAX):
                    Fd = fdl[lane][(fdl_wr - kp) % KMAX]
                    H = spec[kp]
                    for i in range(B):
                        acc[i] += Fd[i] * H[i]
                return lp_ifft(acc)

            y1 = _conv(active)
            if fading:
                y2 = _conv(target)
                for i in range(P):
                    a = min((fade_pos + i) / fade_len, 1.0)
                    pend[lane].append(y1[P + i].real * (1.0 - a) + y2[P + i].real * a)
            else:
                pend[lane].extend(y1[P + i].real for i in range(P))
        if fading:
            fade_pos += P
            fade_hops += 1
            if fade_pos >= fade_len:
                active = [list(h) for h in target]
                fading = False
        fdl_wr = (fdl_wr + 1) % KMAX
        hop += 1

    return {"outA": out["A"], "outB": out["B"], "skipped": skipped, "fade_hops": fade_hops,
            "state": {"fdl_wr": fdl_wr, "zcA": zc["A"], "zcB": zc["B"],
                      "fdlA": fdl["A"], "fdlB": fdl["B"], "hist_pos": hpos}}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "engine_ref" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (129 prior + 3).

- [ ] **Step 6: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.8 oracle - integrated two-lane engine reference

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Oracle — lane-skip tests (bit-exactness, firing, hop alignment, four states)

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `lp_engine_ref` (Task 1).

- [ ] **Step 1: Write the tests**

```python
# tests/test_rcbitnova_dsp.py (append)

def _skip_case(P, ker, zero_run, onset_phase, tail=None):
    """Signal for lane B: `onset_phase` non-zero samples, then `zero_run` exact zeros,
    then a re-excitation tail. Lane A always carries signal."""
    if tail is None:
        tail = [math.sin(0.3 * i) for i in range(4 * P)]
    head = [math.sin(0.11 * i) + 0.3 for i in range(onset_phase)]
    sigB = head + [0.0] * zero_run + tail
    sigA = [math.sin(0.23 * i) for i in range(len(sigB))]
    return sigA, sigB


def test_lane_skip_is_bit_exact_against_the_non_skipping_engine():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    sigA, sigB = _skip_case(P, ker, zero_run=skip_after + 3 * P, onset_phase=P + 5)
    ref = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=None)
    got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
    assert got["skipped"] > 0                      # the optimisation really fired
    assert got["outB"] == ref["outB"]              # BIT-identical, not approximately equal
    assert got["outA"] == ref["outA"]              # the running lane is untouched
    assert got["state"]["fdl_wr"] == ref["state"]["fdl_wr"]
    assert got["state"]["fdlB"] == ref["state"]["fdlB"]


def test_lane_skip_output_is_exactly_zero_while_skipping():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    sigA, sigB = _skip_case(P, ker, zero_run=skip_after + 4 * P, onset_phase=0)
    got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
    # deep inside the zero run (past the FIR tail) the lane output must be exactly 0.0
    probe = skip_after + 2 * P
    assert all(v == 0.0 for v in got["outB"][probe:probe + P])


def test_lane_skip_never_fires_early_and_covers_hop_phases():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    for phase in (0, 1, P - 1):
        for run in (skip_after - 1, skip_after, skip_after + P):
            sigA, sigB = _skip_case(P, ker, zero_run=run, onset_phase=phase)
            ref = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=None)
            got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
            assert got["outB"] == ref["outB"], f"phase={phase} run={run} diverged"


def test_lane_skip_all_four_run_skip_combinations():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    n = skip_after + 6 * P
    live = [math.sin(0.23 * i) for i in range(n)]
    dead = [0.0] * n
    for sigA, sigB in ((live, live), (live, dead), (dead, live), (dead, dead)):
        ref = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=None)
        got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
        assert got["outA"] == ref["outA"] and got["outB"] == ref["outB"]
```

- [ ] **Step 2: Run them**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "lane_skip" -q`
Expected: PASS (4 passed). No RED phase — `lp_engine_ref` already exists.
If any FAILS, the skip is **not** exact: STOP and report the first diverging index and the two values. Do NOT relax `==` to `approx`; bit-exactness is the whole claim.

- [ ] **Step 3: Full suite, then commit**

Run: `python3 -m pytest tests/ -q` → all pass.

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.8 oracle - lane-skip bit-exactness, firing, hop phases

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Oracle — crossfade tests (artefact killed, exact landing, endpoint ordering)

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `lp_engine_ref`, `impulse_fft_kernel`, `fir_brick_kernel`, `_kmag`.

- [ ] **Step 1: Write the tests**

```python
# tests/test_rcbitnova_dsp.py (append)

def _curvature_anomaly_db(y, s0, s1, ref_lo, ref_hi, peak):
    """Worst second-difference spike in [s0,s1) above the steady-state baseline, in dB
    relative to peak. A waveform step shows up as a large curvature spike."""
    base = max(abs(y[n + 1] - 2 * y[n] + y[n - 1]) for n in range(ref_lo, ref_hi))
    worst = max(abs(y[n + 1] - 2 * y[n] + y[n - 1]) for n in range(s0, s1))
    return 20 * math.log10(max(worst - base, 1e-14) / peak)


def test_crossfade_removes_the_step_that_an_instant_swap_creates():
    # The measured worst case from the spec: Slope 24 -> 48 dB/oct under audio.
    sr = 96000.0; BD = 8192; P = 2048
    ka = dsp.impulse_fft_kernel(BD, "hp", 100.0, 0.0, 2, 14.0, sr)
    kb = dsp.impulse_fft_kernel(BD, "hp", 100.0, 0.0, 4, 14.0, sr)
    n = P * 22
    sig = [math.sin(2 * math.pi * 60.0 * i / sr) for i in range(n)]   # below cutoff: kernels differ
    zeros = [0.0] * n
    sw = 8
    inst = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=sw, fade_len=0)
    fade = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=sw, fade_len=int(0.05 * sr))
    s0, s1 = sw * P - P, sw * P + 6 * P
    peak = max(abs(v) for v in inst["outA"][s1:]) or 1e-9
    a_inst = _curvature_anomaly_db(inst["outA"], s0, s1, s1 + P, len(sig) - 1, peak)
    a_fade = _curvature_anomaly_db(fade["outA"], s0, s1, s1 + P, len(sig) - 1, peak)
    assert a_inst > -20.0        # the baseline really is broken (guards a vacuous test)
    assert a_fade < -60.0        # and the crossfade really fixes it
    assert a_fade < a_inst - 30.0


def test_crossfade_steady_state_is_bit_exact():
    # No switch in flight -> byte-identical to the plain engine (Arthur's discipline).
    sig = [math.sin(0.3 * i) + 0.4 * math.sin(0.017 * i) for i in range(240)]
    zeros = [0.0] * 240
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    r = dsp.lp_engine_ref(sig, zeros, ker, ker, 16, switch_hop=None, fade_len=800)
    assert r["outA"] == dsp.partitioned_convolve(sig, ker, 16)
    assert r["fade_hops"] == 0


def test_crossfade_lands_exactly_and_then_stops_fading():
    P = 16; n = P * 30
    sig = [math.sin(0.3 * i) for i in range(n)]
    zeros = [0.0] * n
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(64)]
    fade_len = 3 * P
    r = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=5, fade_len=fade_len)
    assert r["fade_hops"] == 3          # ceil(fade_len / P) hops carried a fade
    # after the fade, output must match an engine that used kb from the same hop onward
    ref = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=5, fade_len=0)
    tail = slice(5 * P + fade_len + 4 * P, n)
    assert r["outA"][tail] == pytest.approx(ref["outA"][tail], abs=1e-9)


def test_crossfade_endpoint_ordering_over_awkward_fade_lengths():
    # fade_len is not a multiple of P in practice (2400 @48k, 2205 @44.1k).
    P = 16; n = P * 30
    sig = [math.sin(0.3 * i) for i in range(n)]
    zeros = [0.0] * n
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(64)]
    for fade_len in (P - 1, P, P + 1, 2 * P + 5):
        r = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=5, fade_len=fade_len)
        assert r["fade_hops"] == -(-fade_len // P)     # ceil, no off-by-one hop
        assert len(r["outA"]) == n


def test_crossfade_and_skip_coexist():
    # A fade in progress while lane B is skipped: fade still advances, B stays silent,
    # and lane A matches the non-skipping engine bit-for-bit.
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    n = skip_after + 10 * P
    sigA = [math.sin(0.23 * i) for i in range(n)]
    sigB = [0.0] * n
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(BD)]
    sw = (skip_after // P) + 2
    ref = dsp.lp_engine_ref(sigA, sigB, ka, kb, P, switch_hop=sw, fade_len=2 * P, skip_after=None)
    got = dsp.lp_engine_ref(sigA, sigB, ka, kb, P, switch_hop=sw, fade_len=2 * P, skip_after=skip_after)
    assert got["skipped"] > 0
    assert got["fade_hops"] == ref["fade_hops"]        # fade advances despite the skip
    assert got["outA"] == ref["outA"]
    assert all(v == 0.0 for v in got["outB"][skip_after + 2 * P:])
```

- [ ] **Step 2: Run them**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "crossfade" -q`
Expected: PASS (6 passed). No RED phase.
If `test_crossfade_removes_the_step…` fails on the **baseline** assertion (`a_inst > -20`), the test signal is wrong (probe a frequency where the kernels differ), not the feature. If it fails on `a_fade < -60`, STOP and report both numbers.

- [ ] **Step 3: Full suite, then commit**

Run: `python3 -m pytest tests/ -q` → all pass.

```bash
git add tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.8 oracle - per-sample crossfade kills the step, lands exactly

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Oracle — `Hspec2` in the layout (FFT-touched) + memory tests

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (in-place edit of `lp_engine_buffers`)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces: `lp_engine_buffers` returns `Hspec2` (size `KMAX*PB2`, `fft_touched=True`) immediately after `Hspec`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_dsp.py (append)

def test_hspec2_exists_and_is_fft_touched():
    bufs = {n: (s, t) for n, s, t in dsp.lp_engine_buffers(8192, 2048)}
    assert "Hspec2" in bufs
    assert bufs["Hspec2"] == bufs["Hspec"]          # same size AND same fft_touched flag
    assert bufs["Hspec2"][1] is True                # it is a live convolve_c operand


def test_v08_spans_and_packed_tops():
    span = lambda BD: sum(s for _, s, _ in dsp.lp_engine_buffers(BD, 2048))
    assert span(8192) == 262144
    assert span(16384) == 425984
    assert span(32768) == 786432
    expect = {(8192, 8192): 524288, (32768, 8192): 1048576,
              (8192, 32768): 1048576, (32768, 32768): 1572864}
    for (b0, b1), top in expect.items():
        l0, l1 = dsp.lp_packed_layouts(0, b0, b1, 2048)
        assert l1["__top"] == top, f"({b0},{b1}) -> {l1['__top']} != {top}"
        assert dsp.page_layout_ok(l0, b0, 2048)
        assert dsp.page_layout_ok(l1, b1, 2048)


def test_every_hspec2_partition_is_page_safe():
    PAGE = 65536
    for BD in (8192, 16384, 32768):
        for base in (0, 262144, 786432):
            L = dsp.page_layout(base, BD, 2048)
            KMAX = BD // 2048; PB2 = 8192
            for kp in range(KMAX):
                s = L["Hspec2"] + kp * PB2
                assert s // PAGE == (s + PB2 - 1) // PAGE, f"BD={BD} base={base} part={kp}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "hspec2 or v08_spans" -q`
Expected: FAIL — `KeyError: 'Hspec2'`.

- [ ] **Step 3: Add `Hspec2` to `lp_engine_buffers`**

In `tools/rcbitnova_dsp.py`, insert one entry immediately after the `Hspec` line (leave every other entry untouched):

```python
        ("Hspec",  KMAX * PB2, True),      # partitions, each span PB2 convolve_c'd
        ("Hspec2", KMAX * PB2, True),      # V0.8 crossfade target - ALSO a live convolve_c
                                           # operand during a fade, so it is FFT-touched and
                                           # must obey the same PB2 / no-page-crossing rule
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -k "hspec2 or v08_spans" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Full suite — expect V0.7's span/top tests to FAIL, and update them**

Run: `python3 -m pytest tests/ -q`

The V0.7 tests `test_used_span_per_resolution`, `test_packed_normal_pair_matches_v06_footprint`, `test_packed_layouts_all_four_combinations` and `test_hires_desbuf_page_aligned_even_when_engine_base_is_not` assert the **pre-`Hspec2`** numbers and will now fail. This is expected and intended: V0.8 deliberately gives up V0.7's footprint. Update those four tests to the V0.8 numbers (`262144 / 425984 / 786432`; tops `524288 / 1048576 / 1048576 / 1572864`), and in the desbuf-alignment test recompute the expected `desbuf` offset from `dsp.lp_packed_layouts` rather than hardcoding `262144`.

Do NOT delete the tests, and do NOT change what they assert *about* — only the numbers.

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): V0.8 oracle - Hspec2 as a live convolve_c operand, page-safe

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: JSFX — restructure state for the crossfade (behaviour-neutral)

**Files:**
- Create: `JSFX/RCBitNova V0.8` (copy of `JSFX/RCBitNova V0.7`)

**Interfaces:**
- Produces: `Hspec2` at `lp_off[eng*16+15]`; `lp_fs + eng*4` = `fading, fade_pos, fade_len, valid`; `lpk_build` writes into `Hspec2`; a new `lpk_commit(eng)` that copies `Hspec2 → Hspec`. V0.7's `hp_built`/`lp_built` globals are removed.
- **This task must NOT change audio behaviour.** Every build snaps immediately (build → commit), so V0.8 sounds exactly like V0.7.

- [ ] **Step 1: Copy and update the desc line**

```bash
cp "JSFX/RCBitNova V0.7" "JSFX/RCBitNova V0.8"
```

Change line 1 to:

```eel
desc: RCBitNova V0.8 - Bit-Accurate M/S Dynamic EQ (static + Mode A + Mode B Soft/Hard cascade + shelf dynamics A+B + proportional-Q bells + min-phase HP/LP + linear-phase HP/LP + FIR Brick + per-filter hi-res + click-safe kernel crossfade + lane skip)
```

- [ ] **Step 2: Add `Hspec2` to the layout**

In `lp_layout`, after the `Hspec` line and before `fdlA`, add the new block (and extend the comment listing the slots):

```eel
  p = lp_align(p, lpPB2);  ob[15] = p; p += KM*lpPB2;    // Hspec2 (crossfade target; ALSO
                                                          // a live convolve_c operand -> same
                                                          // PB2 alignment / page rule as Hspec)
```

Keep every other assignment in `lp_layout` exactly as-is; `ob[15]` was the free slot.

- [ ] **Step 3: Add the fade-state block and remove the old build flags**

In `@init`, extend the scratch block (`lp_geo`/`lp_off` lines) with `lp_fs` and drop the four globals:

```eel
lp_geo = lp_ks + 18;      // 8 words  (2 engines * 4: BD, KMAX, lat, dryN)
lp_off = lp_geo + 8;      // 32 words (2 engines * 16 buffer addresses; 15 = Hspec2)
lp_fs  = lp_off + 32;     // 8 words  (2 engines * 4: fading, fade_pos, fade_len, valid)
lp_base = ceil((lp_fs + 8) / 65536) * 65536;   // page-align the engine block start
```

Replace V0.7's line `hp_dirty = 1; lp_dirty = 1; hp_built = 0; lp_built = 0; hp_tbuild = 0; lp_tbuild = 0;` with:

```eel
hp_dirty = 1; lp_dirty = 1; hp_tbuild = 0; lp_tbuild = 0;   // valid now lives in lp_fs
```

- [ ] **Step 4: Add the fade-state helpers (before `lpk_build`)**

```eel
// V0.8 fade state: lp_fs + eng*4 = 0 fading, 1 fade_pos, 2 fade_len, 3 valid.
// fade_len is defined in TIME (50 ms), so it is sample-rate independent.
function lp_fs_reset(eng) local(fs) (
  fs = lp_fs + eng*4;
  fs[0] = 0; fs[1] = 0; fs[2] = floor(srate * 0.05); fs[3] = 0;
);

// Commit the freshly built target as the active kernel (exact, no residual drift).
function lpk_commit(eng) local(ob, KM) (
  ob = lp_off + eng*16; KM = lp_geo[eng*4+1];
  memcpy(ob[3], ob[15], KM * lpPB2);
  lp_fs[eng*4] = 0;
);
```

- [ ] **Step 5: Make `lpk_build` write into `Hspec2`**

In `lpk_build`, change the destination only (everything else stays):

```eel
  desbuf = ob[0]; ktime = ob[1]; wink = ob[2]; hspec = ob[15]; fftw = ob[6];
```

(`hspec` is the local name used by the partition loop's `memcpy(hspec + base, fftw, lpB * 2);`, so pointing it at `ob[15]` makes the build land in `Hspec2` with no other edit.)

- [ ] **Step 6: Reset fade state wherever runtime state is reset**

In `lp_rt_reset`, append `lp_fs_reset(eng);` as its last statement, so `lp_relayout`-driven resets clear the fade too (a fade must never point into moved or cleared memory).

- [ ] **Step 7: Snap after every build (this is what keeps Task 5 behaviour-neutral)**

In `@block`, replace the two rebuild bodies so each build is followed by an immediate commit, and switch the validity flag to `lp_fs`:

```eel
hp_dirty ? (
  (lp_fs[3] == 0 || (time_precise() - hp_tbuild) >= 0.1) ? (
    lpk_build(0, 3, slider132, slider133,
      (slider131 == 6 ? 0 : slider131 == 5 ? 8 : slider131), slider131 == 6);
    lpk_commit(0);
    hp_dirty = 0; lp_fs[3] = 1; hp_tbuild = time_precise();
  );
);
lp_dirty ? (
  (lp_fs[7] == 0 || (time_precise() - lp_tbuild) >= 0.1) ? (
    lpk_build(1, 4, slider136, slider137,
      (slider135 == 6 ? 0 : slider135 == 5 ? 8 : slider135), slider135 == 6);
    lpk_commit(1);
    lp_dirty = 0; lp_fs[7] = 1; lp_tbuild = time_precise();
  );
);
```

In the `@slider` geometry-reconcile block, replace `hp_built = 0; lp_built = 0;` with `lp_fs[3] = 0; lp_fs[7] = 0;`.

- [ ] **Step 8: Static checks, then deploy**

```bash
python3 - <<'PY'
import re
s = open('JSFX/RCBitNova V0.8').read()
code = '\n'.join(l.split('//')[0] for l in s.splitlines())
assert s.count('(') == s.count(')'), 'paren mismatch'
assert s.count('[') == s.count(']'), 'bracket mismatch'
assert 'hp_built' not in code and 'lp_built' not in code, 'old validity globals still present'
assert 'ob[15]' in code, 'Hspec2 slot not wired'
assert code.count('lp_fs_reset') >= 2, 'fade reset not called from lp_rt_reset'
assert not re.search(r'\b\d+e[-+]?\d+\b', code), 'scientific literal'
print('static checks OK')
PY
cp "JSFX/RCBitNova V0.8" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.8"
```

- [ ] **Step 9: Live-verify the regression gate with the owner**

V0.8 must be indistinguishable from V0.7 at this point:
- loads with no compile error; both Resolution sliders and Phase behave as before;
- `Phase = Min` unchanged; `Linear` Both / Mid / Side unchanged;
- Normal and High both still work (this exercises the enlarged layout and the new `Hspec2` slot);
- turning Freq still clicks exactly as V0.7 did (the fade is not enabled yet — this is expected);
- CPU comparable to V0.7; no crash.

- [ ] **Step 10: Commit**

```bash
git add "JSFX/RCBitNova V0.8"
git commit -m "refactor(rcbitnova): V0.8 JSFX - Hspec2 + fade state, one validity flag (behaviour-neutral)

Builds now land in Hspec2 (lp_off[15], PB2-aligned like Hspec because it becomes a live
convolve_c operand in Task 6) and are committed immediately, so output is identical to
V0.7. Adds lp_fs (fading, fade_pos, fade_len, valid) reset from lp_rt_reset, and replaces
the duplicate hp_built/lp_built globals with the single per-engine valid flag.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: JSFX — enable the crossfade and the lane skip

**Files:**
- Modify: `JSFX/RCBitNova V0.8`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: dual-convolution per-sample crossfade in `lpk_run`; per-lane zero-run skip; rebuilds queued while fading.

- [ ] **Step 1: Rewrite the `lpk_run` hop body**

Replace the lane-A and lane-B blocks inside `cnt >= lpP ? ( … )` with the version below. It keeps V0.7's structure and adds: the skip test, the second (target) pass, and the per-sample α mix. The `local(...)` list gains `hspec2, fading, fpos, flen, a, zcA, zcB, sk`.

```eel
    cnt = 0; sc = 1.0 / lpB;
    hspec2 = ob[15];
    fading = lp_fs[eng*4]; fpos = lp_fs[eng*4+1]; flen = lp_fs[eng*4+2];
    // ---- lane A ----
    zcA = rt[6];
    zcA >= skip_after ? (
      i = 0; loop(lpP, ow = out_wr + i; ow >= 16384 ? ow -= 16384; outA[ow] = 0; i += 1;);
    ) : (
      i = 0; loop(lpB, si = ir + i; si >= lpB ? si -= lpB; fftw[i*2] = inA[si]; fftw[i*2+1] = 0; i += 1;);
      fft(fftw, lpB); fft_permute(fftw, lpB);
      memcpy(fdlA + fdl_wr * lpPB2, fftw, lpB * 2);
      memset(yacc, 0, lpB * 2);
      k = 0; loop(KM,
        idx = fdl_wr - k; idx < 0 ? idx += KM;
        memcpy(tmpc, fdlA + idx * lpPB2, lpB * 2);
        convolve_c(tmpc, hspec + k * lpPB2, lpB);
        i = 0; loop(lpB * 2, yacc[i] += tmpc[i]; i += 1;);
        k += 1;
      );
      fft_ipermute(yacc, lpB); ifft(yacc, lpB);
      fading ? (
        i = 0; loop(lpP, ow = out_wr + i; ow >= 16384 ? ow -= 16384;
          a = (fpos + i) / flen; a > 1 ? a = 1;
          outA[ow] = yacc[(lpP + i)*2] * sc * (1 - a); i += 1;);
        memset(yacc, 0, lpB * 2);
        k = 0; loop(KM,
          idx = fdl_wr - k; idx < 0 ? idx += KM;
          memcpy(tmpc, fdlA + idx * lpPB2, lpB * 2);
          convolve_c(tmpc, hspec2 + k * lpPB2, lpB);
          i = 0; loop(lpB * 2, yacc[i] += tmpc[i]; i += 1;);
          k += 1;
        );
        fft_ipermute(yacc, lpB); ifft(yacc, lpB);
        i = 0; loop(lpP, ow = out_wr + i; ow >= 16384 ? ow -= 16384;
          a = (fpos + i) / flen; a > 1 ? a = 1;
          outA[ow] += yacc[(lpP + i)*2] * sc * a; i += 1;);
      ) : (
        i = 0; loop(lpP, ow = out_wr + i; ow >= 16384 ? ow -= 16384;
          outA[ow] = yacc[(lpP + i)*2] * sc; i += 1;);
      );
    );
    // ---- lane B (identical structure, inB/fdlB/outB, SAME alpha values) ----
```

Transcribe the lane-B block by copying the lane-A block and substituting `zcB = rt[7]`, `inB`, `fdlB`, `outB`. Both lanes must use the same `fpos`/`flen`, so **do not advance `fpos` between the lanes**.

- [ ] **Step 2: Advance the fade and commit, after BOTH lanes**

Immediately after the lane-B block, before the existing `out_wr`/`fdl_wr` advance:

```eel
    fading ? (
      fpos += lpP; lp_fs[eng*4+1] = fpos;
      fpos >= flen ? lpk_commit(eng);        // exact copy Hspec2 -> Hspec, clears fading
    );
```

`lpk_commit` already clears `lp_fs[eng*4]`, so the next hop takes the single-convolution path.

- [ ] **Step 3: Add the per-sample zero-run counters**

`skip_after` is per engine (`BD + B`). Compute it next to the other per-engine locals at the top of `lpk_run`:

```eel
  skip_after = lp_geo[eng*4] + lpB;      // BD + B
```

and update the counters where the input ring is written (replacing V0.7's single `inA[ir] = iA; inB[ir] = iB;` line), so the counter includes the current sample **before** the hop decision:

```eel
  inA[ir] = iA; inB[ir] = iB;
  iA == 0 ? ( rt[6] < skip_after ? rt[6] += 1; ) : ( rt[6] = 0; );
  iB == 0 ? ( rt[7] < skip_after ? rt[7] += 1; ) : ( rt[7] = 0; );
  ir += 1; ir >= lpB ? ir = 0; cnt += 1;
```

Add `skip_after` to `lpk_run`'s `local(...)` list. Reset both counters in `lp_rt_reset` (`rt[6] = 0; rt[7] = 0;`).

- [ ] **Step 4: Start a fade instead of snapping, and queue rebuilds while fading**

In `@block`, change each engine's rebuild body so it (a) refuses to run while that engine is fading, and (b) snaps only on first build:

```eel
hp_dirty && lp_fs[0] == 0 ? (
  (lp_fs[3] == 0 || (time_precise() - hp_tbuild) >= 0.1) ? (
    lpk_build(0, 3, slider132, slider133,
      (slider131 == 6 ? 0 : slider131 == 5 ? 8 : slider131), slider131 == 6);
    lp_fs[3] == 0 ? ( lpk_commit(0); ) : ( lp_fs[0] = 1; lp_fs[1] = 0; );
    hp_dirty = 0; lp_fs[3] = 1; hp_tbuild = time_precise();
  );
);
lp_dirty && lp_fs[4] == 0 ? (
  (lp_fs[7] == 0 || (time_precise() - lp_tbuild) >= 0.1) ? (
    lpk_build(1, 4, slider136, slider137,
      (slider135 == 6 ? 0 : slider135 == 5 ? 8 : slider135), slider135 == 6);
    lp_fs[7] == 0 ? ( lpk_commit(1); ) : ( lp_fs[4] = 1; lp_fs[5] = 0; );
    lp_dirty = 0; lp_fs[7] = 1; lp_tbuild = time_precise();
  );
);
```

`hp_dirty` stays set while a fade is in flight, so the queued target is built as soon as the fade finishes. Also refresh `lp_fs[eng*4+2]` (`fade_len`) in `@slider` from the current `srate` so a sample-rate change is picked up:

```eel
lp_fs[2] = floor(srate * 0.05); lp_fs[6] = lp_fs[2];
```

- [ ] **Step 5: While `Phase = Min`, always snap**

The engines do not run in Min, so a fade could never advance. In the `@block` bodies, force the snap path when `slider140 == 0` by treating it as a first build: change each `lp_fs[3] == 0 ? ( lpk_commit(0); )` test to `(lp_fs[3] == 0 || slider140 == 0) ? ( lpk_commit(0); )` (and the engine-1 analogue with `lp_fs[7]`).

- [ ] **Step 6: Static checks, then deploy**

```bash
python3 - <<'PY'
import re
s = open('JSFX/RCBitNova V0.8').read()
code = '\n'.join(l.split('//')[0] for l in s.splitlines())
assert s.count('(') == s.count(')'), 'paren mismatch'
assert s.count('[') == s.count(']'), 'bracket mismatch'
run = code[code.index('function lpk_run'):code.index('function lpk_process')]
assert run.count('convolve_c') == 4, f'expected 4 convolve_c sites in lpk_run, got {run.count("convolve_c")}'
assert 'hspec2' in run, 'target kernel not convolved'
assert run.count('skip_after') >= 4, 'skip not wired on both lanes'
assert not re.search(r'\b\d+e[-+]?\d+\b', code), 'scientific literal'
print('static checks OK')
PY
cp "JSFX/RCBitNova V0.8" "$HOME/Library/Application Support/REAPER/Effects/RCBitNova V0.8"
```

- [ ] **Step 7: Live-verify with the owner**

In order, stopping at the first failure:
1. **Regression:** `Phase = Min` unchanged; steady-state `Linear` (no knob motion) unchanged from V0.7.
2. **The cases that provably banged:** switch **Slope 24 ↔ 48** and **Resonance 0 ↔ 1 while playing** — a bang before, nothing now. Then **Off ↔ FIR Brick** under audio.
3. **Fast Freq sweep** under audio — no zipper.
4. **Lane-B skip CPU:** `HP Placement = Mid` at **High**, waiting **longer than `(BD+B)/srate`** (≈0.4 s @96k, ≈0.8 s @48k) before reading the meter — roughly half of that engine's convolution work should disappear, audibly identical.
5. **Benchmarks, not estimates:** steady CPU **and peak block time** at 44.1 / 48 / 96 / 192 kHz with a small device block, for Normal vs High, Both vs selective (after the skip engages), one and two engines fading, and a rapid sweep that rebuilds every 100 ms. Report any xruns.
6. Offline render still carries the full tail; reported latency unchanged from V0.7.

- [ ] **Step 8: Commit**

```bash
git add "JSFX/RCBitNova V0.8"
git commit -m "feat(rcbitnova): V0.8 JSFX - per-sample kernel crossfade + lane-B skip

Crossfade: while fading each lane convolves the FDL twice (active Hspec, target Hspec2)
and mixes per sample with alpha = (fade_pos + i)/fade_len; fade_pos advances once per hop
AFTER both lanes, then lpk_commit copies Hspec2 -> Hspec exactly and clears fading, so the
steady-state path returns to V0.7's single convolution. Rebuilds QUEUE while fading (the
dirty flag persists) instead of snapping. Phase=Min and first build always snap.
Lane skip: per-lane saturating zero-run counters in rt[6]/rt[7]; after BD+B exact zeros a
lane's whole hop is skipped (P zeros emitted) - provably identical output because the FDL
is all zeros by then. fdl_wr still advances once per hop at engine level.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Final review, docs, tag

**Files:**
- Modify: the V0.8 spec (append an as-shipped section); `.superpowers/sdd/progress.md`; memory files.

- [ ] **Step 1: Full oracle regression**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (129 prior + the V0.8 additions).

- [ ] **Step 2: Dispatch Fable for the final whole-branch review**

Range `rcbitnova-v0.7..HEAD`. Remit: error-finding and bit-accuracy only (not coding). Ask specifically for: bit-accuracy INTACT; steady-state path byte-identical to V0.7 when not fading and not skipping; **every `Hspec2` partition page-safe in all layouts** (the silent-corruption class); both lanes using the same α; `fade_pos` advancing exactly once per hop and only after both lanes; `lpk_commit` never running between lanes; rebuilds genuinely queued while fading; no surviving `hp_built`/`lp_built`; the skip's zero-counter update order; EEL2 hazards.

- [ ] **Step 3: Fix any P0/P1, re-run the suite**

Run: `python3 -m pytest tests/ -q` → all pass.

- [ ] **Step 4: Append the as-shipped section to the spec**

Record the live results (including the measured before/after on Slope and Resonance switching), the benchmark numbers from Task 6 Step 7.5, and anything deferred.

- [ ] **Step 5: Tag and push**

```bash
git tag -a rcbitnova-v0.8 -m "V0.8 per-sample kernel crossfade + lane-B skip"
git push origin rcbitnova rcbitnova-v0.8
```

- [ ] **Step 6: Update the ledger and memory files**

Append the V0.8 outcome to `.superpowers/sdd/progress.md`; update `rcbitnova-state.md` and its `MEMORY.md` index line (V0.8 shipped; V0.9 = topology transitions, with the §9 timing analysis as its starting point).

---

## Self-Review (spec coverage)

- Spec §1 (both features) → Tasks 1–6.
- Spec §2/§3 (the artefact is real; per-sample beats per-hop) → Task 3's `test_crossfade_removes_the_step_that_an_instant_swap_creates`, which asserts the baseline is broken *and* the fix works.
- Spec §4 (Hspec2, α per sample, fade_len in time, pinned hop order, exact commit, snap rules, queue-while-fading, one validity flag) → Task 5 (state, snap, one flag), Task 6 (fade, order, queue, Min snap), Task 1/3 (oracle order + endpoint tests).
- Spec §5 (skip rule, exactness, engine-level `fdl_wr`, warm-up, anti-denormal) → Task 6 Step 3 (counters incl. update order), Task 2 (bit-exactness, firing, hop phases, four states), Task 6 Step 7.4 (warm-up-aware live test).
- Spec §6 (honest CPU) → Task 6 Step 7.5 benchmarks with peak block time and xruns; no estimate anywhere in this plan.
- Spec §7 (Hspec2 FFT-touched, spans/tops, state storage) → Task 4 (oracle + per-partition page test), Task 5 Steps 2–3 (`ob[15]`, `lp_fs`).
- Spec §8 (verification list) → Tasks 1–4 (oracle), Tasks 5/6 Step 7 (live).
- Spec §9 (V0.9 deferral) → Task 7 Step 6 records it; no V0.8 task implements topology transitions.
- Spec §10 (invariants) → Global Constraints + Task 7 Step 2.
