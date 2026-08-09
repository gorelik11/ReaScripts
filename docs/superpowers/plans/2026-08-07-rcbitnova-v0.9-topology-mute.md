# RCBitNova V0.9 — Topology Mute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three topology switches (HP/LP Placement in `Phase=Linear`, Phase, HP/LP Resolution) mute the plugin output honestly — deferring the change until the output is at zero and holding until the new topology is provably warm — without touching the steady-state signal path.

**Architecture:** A `selected → pending → active` state machine. `@slider` only arms it; `@block` commits at exact zero, clears both linear engines and the min-phase state, publishes the new PDC, and forces snap kernel rebuilds; `@sample` runs a 5 ms fade-out / hold / 5 ms fade-in envelope at the FINAL plugin output. Because every commit clears state, one hold formula (`BD0 + BD1 + 2P`) covers every event, and the acceptance criterion is bit-equality with the same topology **running continuously** — a claim that is true exactly at that hold length and false at anything shorter.

**Tech Stack:** JSFX (EEL2) for the plugin; Python 3.11 stdlib-only DSP mirror (`tools/rcbitnova_dsp.py`) as THE ORACLE; `pytest` for the oracle tests; live REAPER for transcription verification.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-07-rcbitnova-v0.9-topology-mute-design.md` (**rev 3**). Section numbers referenced below are that document's.
- **Hold length is `BD0 + BD1 + 2P`** — the kernel's full support, NOT the reported latency `lat = BD/2 + P`. Normal+Normal 20480 samples (427 ms @48k), High+Normal 45056 (939 ms), High+High 69632 (1.45 s), `Linear→Min` 0. Measured residual against a continuously running reference: −282 dBFS at this length, −219 dBFS at `+P`, and **−43 dBFS** at rev 2's group-delay length. Anyone tempted to shorten it should read spec §4.1: at `lat` the output has appeared but still carries the filter's switch-on transient; at `BD` it is bit-identical to an engine that never stopped running.
- **New file `JSFX/RCBitNova V0.9`, created as an exact copy of `JSFX/RCBitNova V0.8`.** Never edit V0.8 or any earlier version — they are frozen and tagged. `rcbitnova-v0.8` is the fallback.
- **Bit-accuracy is non-negotiable.** No `log`, `dB`, or `pow(10)` anywhere in the DSP path. Any gain that stays in the signal is an exact power of two. The mute envelope is ordinary float and is legal ONLY because the whole block is skipped by condition when `mt_state == 0`.
- **Steady-state must be byte-identical to V0.8.** When no topology event is in flight, not one arithmetic operation may be added to `spl0`/`spl1`.
- **EEL2 gotcha, cost a full live session in V0.8:** a compound assignment (`+=`) inside a **NESTED** ternary — an inner `?` within an outer one that has an else-branch — parses, reads correctly, passes review, and silently never executes. Single-level `idx < 0 ? idx += KM;` is fine and appears throughout the V0.8 engine; that is why a grep for the form alone gives 17 false positives on working code. The mechanical gate is therefore: `diff` V0.8 against V0.9, take the ADDED lines only, and require no compound assignment among them at all — the V0.9 additions use `max()`/`min()` or put the conditional on the right-hand side (`var = cond ? 1 : var;`).
- **Geometry constants:** `P = lpP = 2048`, `B = lpB = 4096`, `BD` = 8192 (Normal) or 32768 (High), `lat_e = BD_e/2 + P` (6144 Normal, 18432 High), `KMAX = BD/P`, `PB2 = B*2`.
- **Python:** `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`. The oracle is pure stdlib — do not add dependencies.
- **Run the oracle from the worktree root:** `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. All 144 existing tests must stay green at every commit.
- **Never claim a task is done without running its test and reading the output.**

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/rcbitnova_dsp.py` | THE ORACLE. Gains `TopoMachine` (the state machine, pure logic) and a `clear_at` option on `lp_engine_ref` (to model the commit-time clear). | Modify, append-only for new functions |
| `tests/test_rcbitnova_dsp.py` | All oracle tests. Gains the V0.9 block at the end. | Modify, append |
| `JSFX/RCBitNova V0.9` | The plugin. | Create (copy of V0.8), then modify in Tasks 5–7 |
| `docs/superpowers/specs/2026-08-07-rcbitnova-v0.9-topology-mute-design.md` | The spec. §12 "As-shipped" is appended at the end. | Modify in Task 9 |

Tasks 1–4 are pure Python and fully test-driven. Tasks 5–7 are the JSFX transcription: each is verified against the oracle's pinned numbers and then live in REAPER with the owner, exactly as V0.6–V0.8 were.

---

### Task 0: Live PDC experiment — can this plugin change latency under playback at all?

**Why first:** V0.6–V0.8 never moved `pdc_delay` while the transport was running. If REAPER
re-buffers or flushes its routing when a plugin's latency changes mid-playback, the artefact
happens in the **host**, outside this instance, and no internal mute can suppress it. A bad
answer forces a different architecture (the constant-max-PDC fallback the owner rejected in
V0.6), so it must be known before any of the state machine is built. This is Fable P1-3.

**Files:**
- Create: `/private/tmp/claude-501/-Users-macbook-projects-reascripts/5fcf2fe0-bf08-4ad7-bdbe-cf2f5d585c7e/scratchpad/PDCProbe.jsfx` (scratchpad — this is a throwaway probe, not a repo artifact)

- [ ] **Step 1: Write the probe**

```eel2
desc:PDC Probe (V0.9 Task 0 - throwaway)
slider1:0<0,1,1{Off,On}>Latency

@init
buf = 0;
freembuf(65536);
wp = 0;

@slider
lat = slider1 == 1 ? 12288 : 0;
pdc_delay = lat; pdc_bot_ch = 0; pdc_top_ch = 2;

@sample
// pure delay line matching the reported latency, so the plugin itself is honest and any
// disruption heard is REAPER's, not ours
buf[wp] = spl0; buf[wp + 32768] = spl1;
rp = wp - lat; rp = rp < 0 ? rp + 32768 : rp;
spl0 = buf[rp]; spl1 = buf[rp + 32768];
wp += 1; wp >= 32768 ? wp = 0;
```

- [ ] **Step 2: Run the experiment in REAPER with the owner**

Copy the probe to `~/Library/Application Support/REAPER/Effects/`, put it on a track playing
steady material (sustained sine plus drums), add a second unprocessed track so any host-side
re-sync is audible as a relative shift, and flip `Latency` **under playback** several times.

Record: does REAPER click, drop out, re-buffer, or shift the two tracks relative to each other?
How long does it take for the shift to settle? Try both a small (256) and a large (2048) audio
device block size.

- [ ] **Step 3: Decide**

- **Clean** (only the expected latency change, no click/dropout beyond it) → proceed with Tasks
  1–9 as planned; note the observed settling time and confirm `mt_blocks = 2` is enough.
- **Not clean** → STOP and report. The architecture must change (constant max PDC, or Phase and
  Resolution behind an explicit "apply while stopped only" contract), and the spec needs a new
  revision before implementation.

- [ ] **Step 4: Record the result in the spec**

Append the finding to spec §6 as a dated note, including the block sizes tested and the observed
settling behaviour. Commit:

```bash
git add docs/superpowers/specs/2026-08-07-rcbitnova-v0.9-topology-mute-design.md
git commit -m "docs(rcbitnova): V0.9 Task 0 - live PDC-under-playback finding"
```

---

### Task 1: `TopoMachine` — states, fades, and the commit-at-zero contract

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (append after `lp_engine_ref`, at end of file)
- Test: `tests/test_rcbitnova_dsp.py` (append at end)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `class TopoMachine` with constructor `TopoMachine(srate=48000, P=2048, phase=0, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192, boot=False)` and three methods mirroring the JSFX call sites exactly:
  - `slider(phase, hp_pl, lp_pl, bd0, bd1) -> None` (mirrors `@slider`)
  - `block(play_state=1, kernels_ready=True) -> str` returning `"commit"`, `"deferred"` or `""` (mirrors `@block`)
  - `sample(bypass=False) -> float | None` returning the envelope gain, or `None` when idle (mirrors `@sample`; `None` means "no multiply happens at all")
  - Public attributes read by tests: `state` (0–3), `pend`, `ready`, `hold`, `blocks`, `act_phase`, `act_hp_pl`, `act_lp_pl`, `act_bd0`, `act_bd1`, `commit_count`, `clears` (list of `"engines"` / `"minphase"` strings recorded per commit), `g`, `boot`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rcbitnova_dsp.py`:

```python
# ===================== V0.9: topology mute state machine =====================

def _tm(**kw):
    return dsp.TopoMachine(srate=48000, P=2048, **kw)


def test_v09_idle_machine_does_not_touch_the_signal():
    m = _tm()
    for _ in range(1000):
        assert m.sample() is None          # None == the whole block is skipped
    assert m.state == 0 and m.commit_count == 0


def test_v09_slider_arms_but_does_not_apply():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    assert m.pend == 1 and m.state == 1     # fading out
    assert m.act_phase == 0                 # NOT applied yet
    assert m.commit_count == 0


def test_v09_commit_happens_exactly_when_the_envelope_reaches_zero():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    fo = int(48000 * 0.005)
    # every sample of the fade-out except the last still has g > 0, so a @block delivered
    # there must NOT commit
    for _ in range(fo - 1):
        g = m.sample()
        assert g > 0.0
        assert m.block() == "", "committed while the output was still audible"
        assert m.act_phase == 0 and m.commit_count == 0
    assert m.sample() == 0.0        # the last fade-out sample lands exactly on zero
    assert m.state == 2 and m.g == 0.0
    assert m.commit_count == 0, "commit must wait for @block, not happen in @sample"
    assert m.block() == "commit"
    assert m.act_phase == 1 and m.commit_count == 1


def test_v09_fade_out_steps_are_all_exactly_one_over_n():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    fo = int(48000 * 0.005)
    gains = [m.sample() for _ in range(fo)]
    assert gains[-1] == 0.0
    steps = [gains[i - 1] - gains[i] for i in range(1, len(gains))]
    for s in steps:
        assert abs(s - 1.0 / fo) < 1e-12          # every step 1/N, including the last
    assert abs((1.0 - gains[0]) - 1.0 / fo) < 1e-12


def test_v09_fade_in_steps_are_all_exactly_one_over_n_and_land_on_one():
    m = _tm(phase=1, bd0=8192, bd1=8192)
    m.slider(phase=0, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)   # Linear->Min: hold 0 samples
    fo = int(48000 * 0.005)
    for _ in range(fo):
        m.sample()
    m.block()                                   # commit
    m.block(); m.block()                        # burn the mt_blocks PDC gate
    while m.state == 2:
        m.sample()
    gains = []
    while m.state == 3:
        gains.append(m.sample())
    assert gains[-1] == 1.0
    steps = [gains[i] - gains[i - 1] for i in range(1, len(gains))]
    for s in steps:
        assert abs(s - 1.0 / fo) < 1e-12
    assert m.state == 0 and m.sample() is None


def test_v09_short_and_degenerate_fade_lengths_are_clamped():
    for sr in (48000, 8000, 100, 1):
        m = dsp.TopoMachine(srate=sr, P=2048, phase=0)
        m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
        n = 0
        while m.state == 1 and n < 10000:
            g = m.sample(); n += 1
            assert 0.0 <= g <= 1.0
        assert m.state == 2                     # always terminates, never divides by zero
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v09`
Expected: FAIL — `AttributeError: module 'rcbitnova_dsp' has no attribute 'TopoMachine'`.

- [ ] **Step 3: Implement `TopoMachine`**

Append to `tools/rcbitnova_dsp.py`:

```python
class TopoMachine:
    """V0.9 topology-transition state machine (spec rev 2 §4).

    Mirrors the JSFX call sites one-to-one: slider() == @slider, block() == @block,
    sample() == @sample. It is deliberately pure logic with no DSP: the audio consequences
    are proven separately by lp_engine_ref(clear_at=...) in Task 3.

    States: 0 idle, 1 fading out, 2 holding (warm-up), 3 fading in.
    sample() returns None when idle - modelling that the JSFX skips the whole block by
    condition, so the steady-state path stays byte-identical to V0.8.
    """

    def __init__(self, srate=48000, P=2048, phase=0, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192,
                 boot=False):
        self.srate = srate
        self.P = P
        self.act_phase = phase
        self.act_hp_pl = hp_pl
        self.act_lp_pl = lp_pl
        self.act_bd0 = bd0
        self.act_bd1 = bd1
        self.sel = (phase, hp_pl, lp_pl, bd0, bd1)
        self.fo = max(1, int(srate * 0.005))
        self.fi = self.fo
        self.state = 0
        self.pos = 0
        self.g = 1.0
        self.hold = 0
        self.blocks = 0
        self.pend = 0
        self.ready = 0
        self.commit_count = 0
        self.clears = []
        # boot=True models a freshly instantiated plugin whose first @slider pass must ADOPT
        # the loaded state instead of treating it as a live topology change (spec 4.3a).
        self.boot = 1 if boot else 0

    # ---- geometry ----
    @staticmethod
    def _lat(bd, P):
        """Reported latency (PDC). NOT the hold - see _hold_for_active."""
        return bd // 2 + P

    def _hold_for_active(self):
        """Spec §4.5: one formula, using the kernel's FULL SUPPORT BD, not the reported
        latency BD/2+P. At BD/2+P the output has merely appeared; only after BD samples does
        the cleared engine's zeroed past stop influencing it, which is what makes the output
        bit-identical to an engine that never stopped running. Linear -> BD0+BD1+P; Min -> 0."""
        if self.act_phase != 1:
            return 0
        return self.act_bd0 + self.act_bd1 + self.P

    # ---- @slider ----
    def slider(self, phase, hp_pl, lp_pl, bd0, bd1):
        self.sel = (phase, hp_pl, lp_pl, bd0, bd1)
        if self.boot:
            # Cold init: adopt immediately, no mute, no deferral. In the JSFX this is where
            # lp_relayout + window builds + forced snap rebuilds happen, exactly as V0.8 did.
            self.act_phase, self.act_hp_pl, self.act_lp_pl = phase, hp_pl, lp_pl
            self.act_bd0, self.act_bd1 = bd0, bd1
            self.state = 0
            self.g = 1.0
            self.pend = 0
            self.ready = 1
            self.boot = 0
            return
        changed = phase != self.act_phase
        if phase == 1 and (bd0 != self.act_bd0 or bd1 != self.act_bd1):
            changed = True
        if phase == 1 and (hp_pl != self.act_hp_pl or lp_pl != self.act_lp_pl):
            changed = True
        if changed:
            self.pend = 1
            self.ready = 0
            if self.state != 1:
                self.pos = int(round((1.0 - self.g) * self.fo))
                self.state = 1
            return
        # Reversal back to the active topology while still pending: cancel, fade back in.
        if self.pend and not changed:
            self.pend = 0
            self.state = 3
            self.pos = int(round(self.g * self.fi))

    # ---- @block ----
    def block(self, play_state=1, kernels_ready=True):
        result = ""
        if self.pend and (play_state == 0 or (self.state == 2 and self.g == 0.0)):
            self._commit()
            result = "commit"
        if self.state == 2 and not self.ready:
            self.ready = 1 if (kernels_ready and not self.pend) else 0
            if not self.ready and not self.pend:
                result = result or "deferred"
        if self.state == 2 and self.blocks > 0:
            # the commit block publishes PDC; the counted epochs are the blocks AFTER it
            if result == "commit":
                pass
            else:
                self.blocks -= 1
        return result

    def _commit(self):
        phase, hp_pl, lp_pl, bd0, bd1 = self.sel
        geometry_changed = (bd0 != self.act_bd0) or (bd1 != self.act_bd1)
        phase_edge = phase != self.act_phase
        self.clears.append("engines")
        if phase_edge:
            self.clears.append("minphase")
        self.act_phase, self.act_hp_pl, self.act_lp_pl = phase, hp_pl, lp_pl
        self.act_bd0, self.act_bd1 = bd0, bd1
        self.geometry_changed = geometry_changed
        self.hold = self._hold_for_active()
        self.blocks = 2
        self.pos = 0
        self.pend = 0
        self.ready = 0
        self.state = 2
        self.commit_count += 1

    # ---- @sample ----
    def sample(self, bypass=False):
        if self.state == 0:
            return None                       # block skipped entirely: no multiply at all
        if bypass:
            return None                       # frozen: nothing advances under bypass
        if self.state == 1:
            self.pos += 1
            self.g = (self.fo - self.pos) / self.fo
            if self.pos >= self.fo:
                self.g = 0.0
                self.state = 2
                self.pos = 0
        elif self.state == 2:
            self.g = 0.0
            if self.ready and self.blocks <= 0:
                self.pos += 1
                if self.pos >= self.hold:
                    self.state = 3
                    self.pos = 0
        else:
            self.pos += 1
            self.g = self.pos / self.fi
            if self.pos >= self.fi:
                self.g = 1.0
                self.state = 0
        return self.g
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v09`
Expected: PASS (6 tests). Then run the full suite: `python3 -m pytest tests/test_rcbitnova_dsp.py -q` — expected 150 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.9 TopoMachine - states, endpoint-inclusive fades, commit at zero"
```

---

### Task 2: Hold length, block gate, bypass freeze, and the stopped path

**Files:**
- Modify: `tools/rcbitnova_dsp.py` (only if a test exposes a gap — the class from Task 1 should already satisfy these)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: `TopoMachine` from Task 1 (all methods and attributes listed there).
- Produces: no new API — this task pins behaviour contracts that Tasks 5–7 must transcribe.

- [ ] **Step 1: Write the failing tests**

```python
def _run_to_commit(m, play_state=1):
    """Drive the machine through fade-out and commit; returns samples consumed."""
    n = 0
    while m.state == 1:
        m.sample(); n += 1
    m.block(play_state=play_state)
    return n


def test_v09_hold_matches_the_spec_table_for_every_geometry():
    cases = [
        # (bd0, bd1, expected hold in samples) - FULL KERNEL SUPPORT BD, not lat=BD/2+P
        (8192, 8192, 8192 + 8192 + 2048),      # Normal+Normal  = 18432 = 384 ms @48k
        (32768, 8192, 32768 + 8192 + 2048),    # High+Normal    = 43008 = 896 ms
        (32768, 32768, 32768 + 32768 + 2048),  # High+High      = 67584 = 1.41 s
    ]
    for bd0, bd1, want in cases:
        m = _tm(phase=0)
        m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=bd0, bd1=bd1)
        _run_to_commit(m)
        assert m.hold == want, (bd0, bd1, m.hold, want)


def test_v09_linear_to_min_holds_zero_samples():
    m = _tm(phase=1, bd0=32768, bd1=32768)
    m.slider(phase=0, hp_pl=0, lp_pl=0, bd0=32768, bd1=32768)
    _run_to_commit(m)
    assert m.hold == 0


def test_v09_placement_and_resolution_get_the_same_hold_as_phase():
    base = dict(hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    m1 = _tm(phase=1, **base); m1.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)
    m2 = _tm(phase=1, **base); m2.slider(phase=1, hp_pl=0, lp_pl=0, bd0=32768, bd1=8192)
    _run_to_commit(m1); _run_to_commit(m2)
    assert m1.hold == 18432
    assert m2.hold == 43008


def test_v09_hold_is_full_support_not_reported_latency():
    """Guard against a future 'optimization' back to lat0+lat1+P (spec §4.1, Fable P0-1)."""
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=32768, bd1=32768)
    _run_to_commit(m)
    assert m.hold == 67584
    assert m.hold != (32768 // 2 + 2048) * 2 + 2048, "hold fell back to the group-delay length"


def test_v09_fade_in_waits_for_the_block_gate_even_when_the_hold_is_zero():
    m = _tm(phase=1, bd0=8192, bd1=8192)
    m.slider(phase=0, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)   # hold == 0
    _run_to_commit(m)
    m.block()                                  # ready=1, blocks 2 -> 1
    for _ in range(5000):
        m.sample()
    assert m.state == 2, "fade-in started before the PDC block gate elapsed"
    m.block()                                  # blocks 1 -> 0
    m.sample()
    assert m.state == 3


def test_v09_hold_is_not_consumed_until_kernels_are_ready():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    _run_to_commit(m)
    for _ in range(3):
        m.block(kernels_ready=False)
    for _ in range(50000):
        m.sample()
    assert m.state == 2 and m.pos == 0, "hold consumed before kernels were valid"
    m.block(kernels_ready=True); m.block(kernels_ready=True)
    m.sample()
    assert m.pos == 1


def test_v09_bypass_freezes_the_whole_machine():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    for _ in range(200000):                    # far longer than fade+hold
        assert m.sample(bypass=True) is None
    assert m.state == 1 and m.pos == 0 and m.commit_count == 0
    # release bypass: the full sequence must still run
    _run_to_commit(m)
    assert m.commit_count == 1 and m.hold == 18432


def test_v09_stopped_transport_commits_early_but_still_holds():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    assert m.block(play_state=0) == "commit"   # early commit, no samples needed
    assert m.act_phase == 1 and m.state == 2
    m.block(); m.block()
    n = 0
    while m.state == 2 and n < 200000:
        m.sample(); n += 1
    assert n == 18432, "warm-up was skipped by the stopped path"


def test_v09_no_block_while_stopped_still_commits_on_the_first_playback_block():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    # REAPER delivered no @block at all while stopped: nothing may happen yet
    assert m.commit_count == 0 and m.act_phase == 0
    _run_to_commit(m)                          # first playback block
    assert m.commit_count == 1 and m.act_phase == 1


def test_v09_loading_a_project_with_non_default_topology_does_not_mute():
    """Fable P0-2: EEL2 defaults act_* to 0, and @init hardcodes Normal+Normal. Without the
    boot path, reopening a project saved as Linear/High/Mid would arm a mute AND play through
    the wrong topology until the hold expired - on every reload, and again on every sample-rate
    change (which re-runs @init)."""
    m = dsp.TopoMachine(srate=48000, P=2048, phase=1, hp_pl=1, lp_pl=0,
                        bd0=32768, bd1=32768, boot=True)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=32768, bd1=32768)   # the first @slider pass
    assert m.state == 0, "loading a project armed a spurious mute"
    assert m.act_phase == 1 and m.act_hp_pl == 1
    assert m.act_bd0 == 32768 and m.act_bd1 == 32768, "geometry not adopted at boot"
    assert m.sample() is None, "audio was muted on the first processed sample after load"
    assert m.boot == 0
    # and a real switch afterwards still works normally
    m.slider(phase=1, hp_pl=2, lp_pl=0, bd0=32768, bd1=32768)
    assert m.state == 1 and m.pend == 1


def test_v09_boot_adopts_whatever_the_sliders_say_even_if_it_differs_from_the_constructor():
    """The constructor models EEL2's zero-initialised globals; the sliders model the loaded
    project. Boot must follow the sliders, not the defaults."""
    m = dsp.TopoMachine(srate=48000, P=2048, phase=0, hp_pl=0, lp_pl=0,
                        bd0=8192, bd1=8192, boot=True)
    m.slider(phase=1, hp_pl=2, lp_pl=1, bd0=32768, bd1=8192)
    assert m.state == 0 and m.commit_count == 0
    assert (m.act_phase, m.act_hp_pl, m.act_lp_pl) == (1, 2, 1)
    assert (m.act_bd0, m.act_bd1) == (32768, 8192)


def test_v09_every_commit_clears_the_engines_and_phase_edges_clear_minphase():
    m = _tm(phase=1, bd0=8192, bd1=8192)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)   # placement only
    _run_to_commit(m)
    assert m.clears == ["engines"]
    m2 = _tm(phase=0)
    m2.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)  # phase edge
    _run_to_commit(m2)
    assert m2.clears == ["engines", "minphase"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v09`
Expected: at least `test_v09_hold_is_not_consumed_until_kernels_are_ready` and
`test_v09_bypass_freezes_the_whole_machine` FAIL if Task 1's implementation drifted; if all pass immediately, that is a valid outcome — Task 1 implemented the contract correctly and these tests pin it.

- [ ] **Step 3: Fix `TopoMachine` if any test fails**

Only touch `TopoMachine`. The likely gaps are: `ready` being set while `pend` is still 1, `blocks` decrementing outside state 2, or `sample(bypass=True)` mutating state. Do not add new public API.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 161 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.9 hold table, PDC block gate, bypass freeze, stopped-transport contract"
```

---

### Task 3: `clear_at` on the engine reference — the stale-tail proof

**Files:**
- Modify: `tools/rcbitnova_dsp.py:1269` (`lp_engine_ref` — add the `clear_at` keyword)
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Consumes: existing `lp_engine_ref(sigA, sigB, ker_a, ker_b, P, switch_hop=None, fade_len=0, skip_after=None)`.
- Produces: the same function with one added keyword `clear_at=None` (sample index at which the engine's FDL, input history, pending output and counters are all zeroed — modelling `lp_engine_clear` at commit). Existing calls are unaffected when it is `None`.

- [ ] **Step 1: Write the failing tests**

```python
def _noise(n, seed=1):
    """Deterministic stdlib-only pseudo-noise in [-1, 1]."""
    x = seed
    out = []
    for _ in range(n):
        x = (1103515245 * x + 12345) % 2147483648
        out.append(x / 1073741824.0 - 1.0)
    return out


def test_v09_after_a_full_support_hold_the_cleared_engine_equals_a_CONTINUOUS_one():
    """THE test the hold length must satisfy (spec §4.6, Fable P0-3).

    The reference is an engine that NEVER stopped - it processed the pre-commit history too.
    Equality can only hold once every sample the output depends on lies after the commit, i.e.
    after the kernel's full support BD. Comparing against a cleared-at-commit reference instead
    (what rev 2 specified) would be satisfied at ANY hold length, including zero, and would
    therefore test nothing."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    pre = _noise(4000, seed=7)
    post = _noise(4000, seed=99)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)["outA"]
    continuous = dsp.lp_engine_ref(sig, zeros, ker, ker, P)["outA"]           # never cleared
    hold = BD + P
    assert cleared[T + hold:] == continuous[T + hold:], \
        "after a full-support hold the cleared engine still differs from a continuous one"


def test_v09_a_group_delay_hold_would_NOT_have_been_enough():
    """The negative half of the pair: at rev 2's lat = BD/2 + P the two still differ, so this
    test fails if anyone shortens mt_hold back to the reported latency."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    pre = _noise(4000, seed=7)
    post = _noise(4000, seed=99)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)["outA"]
    continuous = dsp.lp_engine_ref(sig, zeros, ker, ker, P)["outA"]
    lat = BD // 2 + P
    window = slice(T + lat, T + lat + P)
    diff = max(abs(a - b) for a, b in zip(cleared[window], continuous[window]))
    assert diff > 1e-9, "no difference at the group-delay length - the short hold would do"


def test_v09_without_the_clear_old_domain_energy_outlives_the_group_delay():
    """The P0 finding: a linear-phase kernel has support BD, not BD/2, so a placement
    switch that keeps the state leaks old-domain output for ~BD+P samples. This test
    exists to prove the clear is NECESSARY - it must fail if someone removes it."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    pre = _noise(3000, seed=7)
    post = [0.0] * 3000                      # silence after the switch
    T = len(pre)
    zeros = [0.0] * (T + len(post))
    kept = dsp.lp_engine_ref(pre + post, zeros, ker, ker, P)                 # no clear
    lat = BD // 2 + P
    tail = kept["outA"][T + lat + P:T + BD + P]
    assert max(abs(v) for v in tail) > 1e-9, \
        "old-domain energy vanished by lat+P - the group-delay hold would have been enough"


def test_v09_serial_pair_needs_BD0_plus_BD1_plus_P():
    """Spec §4.5: the serial composition. Engine 0's output is free of pre-commit influence
    after BD0 samples; engine 1 then needs BD1 samples of that clean input, plus one hop."""
    P = 256
    BD0 = 1024
    BD1 = 512
    k0 = dsp.build_lp_kernel(BD0, "hp", 200.0, 0.0, 2, 14.0, 48000)
    k1 = dsp.build_lp_kernel(BD1, "lp", 8000.0, 0.0, 2, 14.0, 48000)
    pre = _noise(4000, seed=3)
    post = _noise(4000, seed=5)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)

    def serial(clear_at):
        a = dsp.lp_engine_ref(sig, zeros, k0, k0, P, clear_at=clear_at)["outA"]
        return dsp.lp_engine_ref(a, zeros, k1, k1, P, clear_at=clear_at)["outA"]

    cleared = serial(T)
    continuous = serial(None)
    hold = BD0 + BD1 + P
    assert cleared[T + hold:] == continuous[T + hold:], "serial pair not warm at BD0+BD1+P"


def test_v09_shipping_warmup_bounds_match_the_spec_table():
    P = 2048
    for bd0, bd1, want in ((8192, 8192, 18432), (32768, 8192, 43008), (32768, 32768, 67584)):
        assert bd0 + bd1 + P == want
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v09_after or v09_group_delay or v09_serial or v09_without"`
Expected: FAIL — `lp_engine_ref() got an unexpected keyword argument 'clear_at'`.

- [ ] **Step 3: Add `clear_at` to `lp_engine_ref`**

Change the signature at `tools/rcbitnova_dsp.py:1269`:

```python
def lp_engine_ref(sigA, sigB, ker_a, ker_b, P, switch_hop=None, fade_len=0, skip_after=None,
                  clear_at=None):
```

Extend the docstring with:

```
    clear_at:   sample index at which the engine is CLEARED exactly as V0.9's
                lp_engine_clear() does at a topology commit - FDL partitions, input history,
                pending output and all counters zeroed. The kernel and hop phase restart from
                scratch, which is what makes the post-commit output bit-equal to a fresh engine.
```

Insert at the top of the per-sample loop, before the lane loop (i.e. immediately after `for n in range(len(sigA)):`):

```python
        if clear_at is not None and n == clear_at:
            fdl = {"A": [[0j] * B for _ in range(KMAX)], "B": [[0j] * B for _ in range(KMAX)]}
            hist = {"A": [0.0] * B, "B": [0.0] * B}
            pend = {"A": [], "B": []}
            zc = {"A": 0, "B": 0}
            fdl_wr = 0
            hpos = 0
            cnt = 0
            fading = False
            fade_pos = 0
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 164 passed. If `test_v09_after_a_full_support_hold_the_cleared_engine_equals_a_CONTINUOUS_one` fails on a tail difference, the clear list is incomplete — compare against every mutable name in the function and add the missing one; do NOT relax the assertion to a tolerance.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.9 clear-at-commit proof - stale FIR tail outlives the group delay"
```

---

### Task 4: The transition-error bound (−80 dBFS) and the impulse case

**Files:**
- Test: `tests/test_rcbitnova_dsp.py` (append)
- Modify: `tools/rcbitnova_dsp.py` only if a helper is genuinely shared

**Interfaces:**
- Consumes: `TopoMachine` (Tasks 1–2), `lp_engine_ref(..., clear_at=)` (Task 3).
- Produces: nothing new — this task closes spec §8.4 and §8.11 by combining them.

- [ ] **Step 1: Write the failing tests**

```python
def _apply_machine(sig, m, events, srate=48000, block=512):
    """Run `sig` through the mute envelope, delivering @block every `block` samples and
    applying topology events at their pinned sample index. Returns the enveloped signal."""
    out = []
    for n, x in enumerate(sig):
        if n in events:
            m.slider(*events[n])
        if n % block == 0:
            m.block()
        g = m.sample()
        out.append(x if g is None else x * g)
    return out


def test_v09_no_signal_survives_the_intended_mute_above_minus_80_dbfs():
    srate = 48000
    n = srate                                     # 1 s
    sig = _noise(n, seed=11)
    m = dsp.TopoMachine(srate=srate, P=2048, phase=1, bd0=8192, bd1=8192)
    ev = {1000: (1, 1, 0, 8192, 8192)}            # placement switch at sample 1000
    out = _apply_machine(sig, m, ev, srate=srate)
    fo = max(1, int(srate * 0.005))
    start = 1000 + fo                             # fully muted from here
    end = start + 18432                           # ... until the hold expires
    peak = max(abs(v) for v in sig)
    worst = max(abs(v) for v in out[start:end])
    assert worst == 0.0, f"signal leaked through the mute: {worst} (peak {peak})"


def test_v09_fade_endpoints_never_exceed_the_minus_80_db_step_bound():
    srate = 48000
    n = 40000
    sig = [1.0] * n                               # DC: every envelope step is directly visible
    m = dsp.TopoMachine(srate=srate, P=2048, phase=1, bd0=8192, bd1=8192)
    out = _apply_machine(sig, m, {100: (1, 1, 0, 8192, 8192)}, srate=srate)
    fo = max(1, int(srate * 0.005))
    steps = [abs(out[i] - out[i - 1]) for i in range(1, len(out))]
    bound = 1.0 / fo * 1.000001
    assert max(steps) <= bound, f"largest step {max(steps)} exceeds 1/N = {1.0/fo}"


def test_v09_impulse_just_before_commit_does_not_reappear_after_the_hold():
    """Sustained audio can hide stale energy under new steady output; an impulse cannot."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    T = 2000
    sig = [0.0] * (T + 3000)
    sig[T - 1] = 1.0                              # impulse in the LAST pre-commit sample
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)
    assert all(v == 0.0 for v in cleared["outA"][T:]), \
        "the pre-commit impulse survived the clear"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "v09_no_signal or v09_fade_endpoints or v09_impulse"`
Expected: FAIL — `_apply_machine` / assertions not yet satisfied (the helper is defined in the test file by this step, so failures should be assertion failures, not import errors).

- [ ] **Step 3: Fix whatever the tests expose**

Expected fixes are in `TopoMachine` only (e.g. `sample()` returning a stale `g` during the hold, or `block()` being called before the first sample). If `test_v09_impulse_just_before_commit_does_not_reappear_after_the_hold` fails, the `clear_at` list from Task 3 is incomplete.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 167 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_dsp.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V0.9 transition-error bound and pre-commit impulse case"
```

---

### Task 5: `JSFX/RCBitNova V0.9` — new file, active topology, `lp_engine_clear`

**Files:**
- Create: `JSFX/RCBitNova V0.9` (byte copy of `JSFX/RCBitNova V0.8`)
- Modify: `JSFX/RCBitNova V0.9` only

**Interfaces:**
- Consumes: the hold formula and clear contract pinned by Tasks 1–4.
- Produces (used by Tasks 6–7): `lp_engine_clear(eng)`; instance variables `act_phase`, `act_hp_pl`, `act_lp_pl`; `@sample` reading only those.

- [ ] **Step 1: Create the new version file**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
cp "JSFX/RCBitNova V0.8" "JSFX/RCBitNova V0.9"
```

Then change the `desc:` line at the top of `JSFX/RCBitNova V0.9` to read `V0.9` instead of `V0.8`.

- [ ] **Step 2: Add `lp_engine_clear` after `lp_rt_reset`** (around line 373)

```eel2
// V0.9: clear ONE engine completely - buffers as well as counters. Resetting the indices is
// NOT enough: the FDL still holds old-domain spectra that convolve_c would fold back in, and
// a linear-phase kernel has support BD (not BD/2), so a kept-state topology switch leaks old
// output for ~BD+P samples. Clearing is what makes the V0.9 hold a cold-start warm-up
// (lat0+lat1+P) instead of a full serial FIR tail of up to 69630 samples.
function lp_engine_clear(eng) local(ob, KM, PB2K) (
  ob = lp_off + eng*16; KM = lp_geo[eng*4+1]; PB2K = KM * lpPB2;
  memset(ob[4],  0, PB2K);          // fdlA
  memset(ob[5],  0, PB2K);          // fdlB
  memset(ob[9],  0, lpB);           // inA
  memset(ob[10], 0, lpB);           // inB
  memset(ob[11], 0, 16384);         // outA
  memset(ob[12], 0, 16384);         // outB
  memset(ob[13], 0, lp_geo[eng*4+3]);   // dryA
  memset(ob[14], 0, lp_geo[eng*4+3]);   // dryB
  lp_rt_reset(eng);                 // indices + V0.8 fade state
);
```

- [ ] **Step 3: Introduce the active topology in `@init`**

Immediately after `lp_rt_reset(0);  lp_rt_reset(1);` (around line 586) add:

```eel2
// V0.9 active topology. @slider only ARMS a change; @block adopts it. Cold init is treated as
// ALREADY COMMITTED to whatever the project loaded (spec 4.3a): without this, reopening a
// project saved as Linear/High/Mid would arm a mute and play through the WRONG topology until
// the hold expired - on every load, and again on every sample-rate change, which re-runs @init.
act_phase = slider140; act_hp_pl = slider134; act_lp_pl = slider138;
mt_state = 0; mt_pos = 0; mt_g = 1; mt_pend = 0; mt_ready = 1;
mt_hold = 0; mt_blocks = 0; mt_just_committed = 0;
mt_fo = max(1, floor(srate * 0.005)); mt_fi = mt_fo;
// The geometry itself is adopted by the FIRST @slider pass rather than here, because JSFX does
// not guarantee that slider values are loaded when @init runs.
topo_boot = 1;
```

- [ ] **Step 4: Make `@sample` read the active topology**

Replace lines 752–758 (the `slider140 == 0 ? (...) : (...)` block) with:

```eel2
  act_phase == 0 ? (                                    // Min phase (V0.5 path, zero-latency)
    hp_nsec > 0 ? hplp_run(0, hp_nsec, slider134);
    lp_nsec > 0 ? hplp_run(1, lp_nsec, slider138);
  ) : (                                                 // Linear phase (convolution engines)
    lpk_process(0, act_hp_pl);                          // HP engine + ACTIVE HP placement
    lpk_process(1, act_lp_pl);                          // LP engine + ACTIVE LP placement
  );
```

Note: the min-phase branch keeps reading `slider134`/`slider138` directly — placement is not a
topology event while `Phase=Min` (spec §4.3), so V0.8 behaviour is preserved there exactly.

- [ ] **Step 5: Verify nothing else still reads `slider140` in the audio path**

Run: `grep -n "slider140" "JSFX/RCBitNova V0.9"`
Expected: hits only in the slider declaration, `@slider` (selection + rebuild logic), and `@block` (the V0.8 snap-vs-fade decision). **No hit inside `@sample`.** If `@sample` still has one, fix it before committing.

- [ ] **Step 6: Live smoke test in REAPER (with the owner)**

Load `RCBitNova V0.9` on a stereo track. With no code yet deferring anything, behaviour must be identical to V0.8: filters work in Min and Linear, Placement Mid/Side/L/R works, no crash, no silence. This is a regression gate on the `act_*` plumbing only.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V0.9"
git commit -m "feat(rcbitnova): V0.9 - new file, active topology plumbing, lp_engine_clear"
```

---

### Task 6: `@slider` arms, `@block` commits in the pinned order

**Files:**
- Modify: `JSFX/RCBitNova V0.9` (`@slider` around lines 685–715; `@block` around lines 717–743)

**Interfaces:**
- Consumes: `lp_engine_clear`, `act_*`, `mt_*` from Task 5.
- Produces (used by Task 7): `mt_state`, `mt_pend`, `mt_ready`, `mt_hold`, `mt_blocks` maintained correctly; `topo_pdc()` helper.

- [ ] **Step 1: Replace the `@slider` relayout block with arming**

Replace lines 689–696 (`sel_bd0 = ...` through the closing `);` of the relayout block) with:

```eel2
sel_bd0 = slider141 == 1 ? BD_HIGH : 8192;
sel_bd1 = slider142 == 1 ? BD_HIGH : 8192;

// V0.9 boot: the FIRST @slider pass adopts the loaded state immediately - relayout, window
// builds, resets, forced snap rebuilds - exactly as V0.8 did, with no mute and no deferral.
// This is what keeps a project reload (and a sample-rate change, which re-runs @init) from
// arming a spurious transition through the wrong topology.
topo_boot ? (
  (slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4])) ? (
    lp_relayout(sel_bd0, sel_bd1);
    lp_win_build(0); lp_win_build(1);
    lp_rt_reset(0);  lp_rt_reset(1);
  );
  act_phase = slider140; act_hp_pl = slider134; act_lp_pl = slider138;
  hp_dirty = 1; lp_dirty = 1; lp_fs[3] = 0; lp_fs[7] = 0;
  mt_state = 0; mt_g = 1; mt_pend = 0; mt_ready = 1;
  topo_boot = 0;
);

// V0.9: after boot, a topology change is ARMED here, never applied. Applying it in this pass
// is what V0.8 did, and it is why a switch under audio emitted garbage: the first affected
// sample is already in flight when @slider runs. @block adopts it once the envelope is at zero.
topo_changed = slider140 != act_phase;
(slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4])) ? topo_changed = 1;
(slider140 == 1 && (slider134 != act_hp_pl || slider138 != act_lp_pl)) ? topo_changed = 1;

topo_changed ? (
  mt_pend = 1;
  mt_ready = 0;
  mt_state != 1 ? (
    mt_pos = floor((1 - mt_g) * mt_fo + 0.5);   // restart the fade-out from where we are
    mt_state = 1;
  );
) : (
  // Reversal back to the active topology while still pending: cancel and fade back in.
  mt_pend ? (
    mt_pend = 0;
    mt_state = 3;
    mt_pos = floor(mt_g * mt_fi + 0.5);
  );
);
mt_fo = max(1, floor(srate * 0.005)); mt_fi = mt_fo;
```

- [ ] **Step 2: Make PDC a helper and compute it from the ACTIVE topology**

Replace lines 709–715 (`lin_lat = ...` through the `ext_tail_size` assignment) with:

```eel2
lp_fs[2] = floor(srate * 0.05); lp_fs[6] = lp_fs[2];   // 50 ms V0.8 kernel fade, follows srate
topo_pdc();
```

and add this function next to the other linear-engine helpers (after `lp_engine_clear`):

```eel2
// PDC policy (c) from V0.6, now derived from the ACTIVE topology and published at commit
// (or on any non-topology change such as Lk / bypass) rather than from the @slider pass that
// merely observed a switch.
function topo_pdc() (
  lin_lat = act_phase == 1 ? (lp_geo[2] + lp_geo[6]) : 0;
  pdc_delay = slider1 != 1 ? (lin_lat + (any_b ? Lk : 0)) : 0;
  pdc_bot_ch = 0; pdc_top_ch = 2;
  ext_tail_size = act_phase == 1 ? (2*lpP + lp_geo[0] + lp_geo[4] + Lk + 64) : 1024;
);
```

- [ ] **Step 3: Add `topo_commit` and put it FIRST in `@block`**

Insert at the very top of `@block` (before the two rebuild branches at line 728):

```eel2
// ---- V0.9 topology commit. Order is pinned (spec §4.4): commit -> relayout/clear -> forced
// snap builds -> mt_ready. If a build is deferred, mt_ready stays 0 and the hold does not
// start counting, so no sample is ever processed against a cleared, invalid Hspec.
mt_pend && (play_state == 0 || (mt_state == 2 && mt_g == 0)) ? (
  geo_changed = slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4]);
  phase_edge = slider140 != act_phase;
  geo_changed ? (
    lp_relayout(sel_bd0, sel_bd1);      // memsets the whole span, so it clears too
    lp_win_build(0); lp_win_build(1);
    lp_rt_reset(0);  lp_rt_reset(1);
  ) : (
    lp_engine_clear(0); lp_engine_clear(1);
  );
  phase_edge ? memset(hplp_state, 0, 72);   // do not resume a previous Min session's state
  act_phase = slider140; act_hp_pl = slider134; act_lp_pl = slider138;
  topo_pdc();
  // FULL KERNEL SUPPORT (lp_geo[0]/[4] = BD per engine), NOT the reported latency
  // lp_geo[2]/[6] = BD/2+P. See spec 4.1: at lat the output has merely appeared.
  mt_hold = act_phase == 1 ? (lp_geo[0] + lp_geo[4] + 2*lpP) : 0;
  mt_blocks = 2;
  mt_just_committed = 1;   // this pass publishes PDC; it does not count as an epoch
  mt_pos = 0;
  mt_pend = 0;
  mt_ready = 0;
  mt_state = 2;
  hp_dirty = 1; lp_dirty = 1; lp_fs[3] = 0; lp_fs[7] = 0;   // force snap rebuilds below
);
```

- [ ] **Step 4: Set `mt_ready` and tick `mt_blocks` AFTER the rebuild branches**

Append at the very end of `@block` (after the `lp_dirty` branch closes at line 743):

```eel2
// Kernels are valid once both engines have a built Hspec (or when Min is active, where no
// kernel is used). Only then may the hold be consumed.
// NOTE the shape of both assignments: NEVER `cond ? var += 1;` - that is the EEL2 form that
// silently did nothing in V0.8 (the zero-run counter). Both are written as an assignment whose
// right-hand side is the conditional, or via min/max.
mt_state == 2 && mt_pend == 0 ? (
  mt_ready = (act_phase == 0 || (lp_fs[3] && lp_fs[7])) ? 1 : mt_ready;
  // The commit block PUBLISHES the new pdc_delay; the two epochs counted are the blocks AFTER
  // it, so the commit's own pass does not decrement (spec §4.4 step 6).
  mt_just_committed ? (
    mt_just_committed = 0;
  ) : (
    mt_blocks = max(mt_blocks - 1, 0);
  );
);
```

`mt_just_committed` is set to 1 inside `topo_commit` (add it next to `mt_blocks = 2;` in Step 3)
and is the only new variable this step introduces.

- [ ] **Step 5: Check the EEL2 nested-ternary rule**

Run:
```bash
diff "JSFX/RCBitNova V0.8" "JSFX/RCBitNova V0.9" | grep '^>' | grep -nE "(\+=|-=|\*=|/=)"
```
Expected: no output (comments aside). Grepping the whole file for `? var += 1` instead gives 17
false positives on V0.8 code that demonstrably works — the defect needed the assignment to be in
a NESTED ternary, so the honest gate is "no compound assignment among the added lines at all". Then read every `?` chain added in this task and confirm each assignment is
its own statement — this is the bug class that cost a full live session in V0.8, and neither the
oracle nor a code review caught it then.

- [ ] **Step 6: Live verification in REAPER (with the owner)**

With the transport **stopped**: switch Phase, then Resolution, then Placement. Each must take
effect (audibly, on the next play) and PDC must read 0 / 12288 / 24576 / 36864 as appropriate
(REAPER: track FX window shows plugin latency). No mute is expected yet — Task 7 adds the
envelope; here the gate is that deferral does not break the plugin.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V0.9"
git commit -m "feat(rcbitnova): V0.9 - @slider arms, @block commits in pinned order with clear + snap rebuild"
```

---

### Task 7: The envelope in `@sample`

**Files:**
- Modify: `JSFX/RCBitNova V0.9` (end of `@sample`, after `spl0 *= out_gain;`)

**Interfaces:**
- Consumes: everything from Tasks 5–6.
- Produces: the shipped behaviour.

- [ ] **Step 1: Add the envelope block**

Insert immediately after `spl0 *= out_gain; spl1 *= out_gain;` and **inside** the closing paren
of the `slider1 != 1 ? (` branch (so bypass freezes the machine entirely — a counter that ran
under bypass would expire the warm-up while the engines were not being fed):

```eel2
  // ---- V0.9 topology mute, at the FINAL output. It must be here and not at the HP/LP
  // boundary: the bands, the dynamics and the Mode-B bus are stateful, so silence there is
  // not silence at the output. When mt_state == 0 the whole block is SKIPPED - not multiplied
  // by 1.0 - which is what keeps the steady-state path byte-identical to V0.8.
  mt_state ? (
    mt_state == 1 ? (
      mt_pos += 1;
      mt_g = (mt_fo - mt_pos) / mt_fo;
      mt_pos >= mt_fo ? (
        mt_g = 0; mt_state = 2; mt_pos = 0;
      );
    ) : (
      mt_state == 2 ? (
        mt_g = 0;
        (mt_ready && mt_blocks <= 0) ? (
          mt_pos += 1;
          mt_pos >= mt_hold ? (
            mt_state = 3; mt_pos = 0;
          );
        );
      ) : (
        mt_pos += 1;
        mt_g = mt_pos / mt_fi;
        mt_pos >= mt_fi ? (
          mt_g = 1; mt_state = 0;
        );
      );
    );
    spl0 *= mt_g;
    spl1 *= mt_g;
  );
```

Note the increment-before-gain order: computing the gain first and overwriting it at the end
makes the final step `2/N` instead of `1/N` (≈ −41.6 dB at 5 ms / 48 kHz) — the largest
discontinuity in a feature whose whole purpose is bounded discontinuity.

Note also the structure: `mt_state == 1 ? (...) : ( mt_state == 2 ? (...) : (...) );` — nested
parens with each assignment on its own statement, NOT a chained `a ? x : b ? y : z` with
assignments inside.

- [ ] **Step 2: Verify the steady-state skip by reading the code**

Run: `grep -n "mt_state ?" "JSFX/RCBitNova V0.9"`
Expected: exactly one hit, in `@sample`. Confirm by eye that `spl0 *= mt_g` appears **only**
inside that conditional — never at the outer level.

- [ ] **Step 3: Live verification in REAPER (with the owner) — the acceptance gate**

Run every item and record the result:

1. **Under playback**, switch Placement (Both→Mid), Phase (Min↔Linear), Resolution
   (Normal↔High). Each must give **silence** then correct audio — no burst, no click, no
   missing Side content. Expected silences: ~427 ms Normal+Normal, ~939 ms High+Normal,
   ~1.45 s High+High, ~10 ms for Linear→Min. A silence noticeably SHORTER than these means
   mt_hold was built from lp_geo[2]/[6] (latency) instead of lp_geo[0]/[4] (support).
2. **Null test (bit-accuracy gate 1):** two tracks, V0.8 and V0.9, identical settings, one
   polarity-inverted, summed → must be digital silence. Do not touch any topology slider during
   the test.
3. **Stopped-transport switch,** then play: correct audio, only a short leading silence.
4. **Switch while bypassed,** then unbypass: the full mute sequence must run on unbypass, and
   the audio after it must be correct (not cold).
5. **PDC readings:** 0 (Min), 12288 (Normal+Normal), 24576 (High+Normal), 36864 (High+High).
6. **CPU unchanged from V0.8:** Normal Both 0.90 % / Mid 0.80 %, High Both 1.6 % / Mid 1.2 %.
   A regression here means the lane-B skip broke — check `rt[6]`/`rt[7]` were not disturbed by
   `lp_engine_clear`.
7. **Fast repeated switching** under playback (five flips in two seconds): must coalesce, never
   stick muted, never click.

- [ ] **Step 4: Fix anything the live pass exposes, then re-run the failing item**

Live findings take precedence over the oracle: V0.8's one real defect was invisible to both the
oracle and a careful review, and only the live CPU meter exposed it.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V0.9"
git commit -m "feat(rcbitnova): V0.9 - topology mute envelope at the final output"
```

---

### Task 8: Bit-accuracy gates and Fable's final review

**Files:**
- Modify: none (verification only), unless a gate fails

- [ ] **Step 1: Grep gate (bit-accuracy gate 3)**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
diff <(sed 's/V0\.8/VER/' "JSFX/RCBitNova V0.8") <(sed 's/V0\.9/VER/' "JSFX/RCBitNova V0.9") \
  | grep '^>' | grep -nE "log|pow *\( *10|dB"
```

Expected: no output. Any hit is a bit-accuracy violation and must be removed, not justified.

- [ ] **Step 2: Full oracle suite (bit-accuracy gate 2)**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 167 passed, 0 failed. Read the output; do not infer it.

- [ ] **Step 3: Fable final review (bit-accuracy gate 4)**

Dispatch a review with `model: fable` covering: `JSFX/RCBitNova V0.9` in full, the spec rev 2,
and the diff against V0.8. Ask specifically for: bit-accuracy verdict; whether the steady-state
path is byte-identical to V0.8; EEL2 parsing traps (nested-ternary assignments above all);
memory-safety of `lp_engine_clear` against every geometry; and whether the `@block` order can
ever process a sample against an invalid `Hspec`.

- [ ] **Step 4: Address every P0/P1 the review raises**

Then re-run Steps 1–2 and re-verify live any item the fix touches.

- [ ] **Step 5: Commit the review**

```bash
git add docs/superpowers/specs/2026-08-07-rcbitnova-v0.9-final-review-fable.md
git commit -m "docs(rcbitnova): V0.9 final review (Fable)"
```

---

### Task 9: Ship — as-shipped spec section, memory, tag

**Files:**
- Modify: `docs/superpowers/specs/2026-08-07-rcbitnova-v0.9-topology-mute-design.md` (append §12)
- Modify: `/Users/macbook/.claude/projects/-Users-macbook-projects-reascripts/memory/rcbitnova-state.md`

- [ ] **Step 1: Append "§12 As-shipped outcome" to the spec**

Record: what shipped as specified; every live measurement (silence lengths, PDC readings, CPU
figures, null-test result); every deviation from the design and why; every defect found live and
how; and what is deferred to V1.0. Follow the shape of V0.8 §11 — it is the model.

- [ ] **Step 2: Update the memory file**

Prepend a dated V0.9 entry to `rcbitnova-state.md` in the same style as the V0.8 one: what
shipped, the tag and commit, the live-verified facts, the one lesson worth carrying forward, and
the updated deferred list. Add `rcbitnova-v0.9` to the safety-tag list.

- [ ] **Step 3: Commit and tag**

```bash
git add docs/superpowers/specs/2026-08-07-rcbitnova-v0.9-topology-mute-design.md
git commit -m "docs(rcbitnova): V0.9 as-shipped"
git tag rcbitnova-v0.9
git push origin rcbitnova --tags
```

- [ ] **Step 4: Confirm the tag exists on the remote**

Run: `git ls-remote --tags origin | grep rcbitnova-v0.9`
Expected: one line with the tag. Only after this is the version safe to build on.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §4.1 clear at commit (`lp_engine_clear`) | 3 (oracle), 5 (JSFX), proven by 3–4 |
| §4.2 state variables | 1, 5 |
| §4.3 `@slider` arms only | 1, 6 |
| §4.4 `@block` pinned order, `mt_ready`, stopped path | 2, 6 |
| §4.5 hold formula | 2, 3, 6 |
| §4.6 envelope, endpoint ramp, bypass freeze, re-trigger, "warm" | 1, 2, 4, 7 |
| §5 V0.8 crossfade interaction | 5 (`lp_engine_clear` calls `lp_rt_reset`), 8 (Fable) |
| §6 PDC block gate | 2, 6 |
| §7 four bit-accuracy gates | 7 (null test), 8 (grep, oracle, Fable) |
| §8 verification items 1–11 | 1–4 (oracle), 7 (live) |
| §9 invariants | 5 (new file), 7 (skip-by-condition), 8 |

**Placeholder scan:** no "TBD"/"handle edge cases"/"similar to Task N" — every code step carries
the actual code. Task 9 Steps 1–2 are prose deliverables by nature (a report of live results
that do not exist yet); their required contents are enumerated rather than left open.

**Type consistency:** `TopoMachine` methods (`slider`/`block`/`sample`) and attributes
(`state`, `pend`, `ready`, `hold`, `blocks`, `act_*`, `commit_count`, `clears`, `g`) are used
identically in Tasks 1, 2 and 4. `lp_engine_clear(eng)`, `topo_pdc()`, `mt_*` and `act_*` are
spelled identically in Tasks 5, 6 and 7. `clear_at` is the same keyword in Tasks 3 and 4.

**Public `g`:** `test_v09_commit_happens_exactly_when_the_envelope_reaches_zero` reads `m.g`
directly, so `TopoMachine` exposes `g` as a public attribute — it is listed in the Task 1
interface block and set in `__init__`.
