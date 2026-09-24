# RCBitNova V1.6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RCBitNova its own spectrum analyser and make the Mode-B lookahead detector cost O(1) per sample instead of O(Lk), without changing a single audio sample.

**Architecture:** Three independent changes on one new version file. A GUI-writer fix makes a Phase switch commit under playback. A monotonic queue replaces the per-sample rescan of the lookahead window, reproducing V1.5's result bug-for-bug. An `an_*` analyser section writes two rings from `@sample` and does every transform in `@gfx`, drawing IN/OUT — or Mid against Side with a red over-width warning — on the existing plot.

**Tech Stack:** JSFX/EEL2 (`JSFX/RCBitNova V1.6`), Python 3.11 oracles and gates under `tools/`, pytest under `tests/`, reapy for live gates and null runs, REAPER 7.78 at 96 kHz.

**Spec:** `docs/superpowers/specs/2026-09-24-rcbitnova-v16-analyzer-design.md` (revision 2)
**Review answered by that spec:** `docs/superpowers/specs/2026-09-24-rcbitnova-v16-analyzer-weaknesses.md`

**Worktree:** `/Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova`, branch `rcbitnova`, base tag `rcbitnova-v1.5`. Run every command from the worktree root. Never `cd` to the main checkout; never use bare `git stash` (the stack is shared).

## Global Constraints

- **REAPER identifies a JSFX by its `desc:` line, not its filename.** A new version file whose `desc` still says V1.5 is invisible: the FX browser shows nothing new and `TrackFX_AddByName` fuzzy-matches the old one and returns it, reporting the right parameter count and no error. Change `desc` in the same commit that creates the file.
- **Identify a loaded effect by `fx_ident`, never `fx.name`.** `fx.name` is REAPER's cached display string and goes stale when a `desc` changes.
- **REAPER orders parameters by slider NUMBER, not by position in the file.** The highest existing slider in V1.5 is **246**. Every new parameter is numbered **247 or above**.
- **`@slider` is NOT guaranteed to run after `slider_automate`.** Every GUI writer rebuilds its state inline.
- **State built only in `@slider` or `@block` is dead while the transport is stopped.** `@init` is the only unconditional section.
- **No assignment inside a nested ternary** (an inner `?` within an outer one that has an else-branch). Use `while(run)`, `min()`/`max()`, or plain assignments in explicit parens.
- **No FFT buffer may cross a 65536-word page.** A misaligned `fft()` corrupts silently.
- **Every address comes from `tools/rcbitnova_layout.py`.** Never port an absolute address from another plugin.
- **reapy 0.10.0 cannot WRITE `FXParam.normalized`** (`'FX' object has no attribute 'id'`, `fx_param.py:163`). Reading works. Write parameters with `rpr.TrackFX_SetParamNormalized(track.id, fx_index, i, v)`.
- **Never call `mcp__reaper__*` enumeration tools.** Read live state with a Python script inside `reapy.inside_reaper()` that prints JSON.
- **reapy returns all arguments, inputs included.** Check the actual return shape; `TrackFX_GetParam(...)` → value at `[0]`, range at `[4]`,`[5]`; `TrackFX_GetParamName(...)` → string at `[4]`.
- `FFT_N = 8192`, `MAX_LOOK = 2048`, `DQ_CAP = MAX_LOOK + 1 = 2049`, analyser sliders `247..250`, spectrum scale **−20…+2 bits**, EQ curve scale ±4 bits.

---

### Task 1: Freeze V1.5's manifest before V1.6 exists

**Files:**
- Create: `tests/fixtures/v15_declared_176.json`
- Modify: `tools/rcbitnova_gates.py` (add `DECLARED_FIXTURE_V15`, `load_declared_v15`)
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Produces: `load_declared_v15(path=DECLARED_FIXTURE_V15) -> list[tuple]`, 176 records, each `(index, name, lo, hi, step, default)` — the shape `_declared_records` writes.

This must happen **before** the V1.6 file exists. Once it exists, a mistake in it can be frozen as if it were the baseline.

- [ ] **Step 1: Read how V1.4 was frozen**

Read `tools/rcbitnova_gates.py` lines 34-56 (`DECLARED_FIXTURE_V14`, `load_declared_v14`) and `freeze_declared` at line 268. Copy that shape exactly; do not invent a second format.

- [ ] **Step 2: Freeze the live V1.5 records**

`freeze_declared` adds a FRESH instance to an EMPTY scratch track on purpose - a default cannot
be recovered from an instance that has already been written to - and it asserts the track holds no
RCBitNova. So it cannot read the owner's working instance. Insert a scratch track at the end, pass
its index, and delete it afterwards:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from tools.rcbitnova_gates import freeze_declared
print(freeze_declared(path="tests/fixtures/v15_declared_176.json",
                      track_index=SCRATCH_INDEX, n_declared=176,
                      effect="RCBitNova V1.5"))
PY
```

Expected: a JSON file with exactly 176 records.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_rcbitnova_v16_gates.py
# A record is [index, name, lo, hi, step, default] - the shape _declared_records writes.
from tools.rcbitnova_gates import load_declared_v14, load_declared_v15

def test_v15_manifest_pins_the_hp_lp_range_change():
    recs = load_declared_v15()
    assert len(recs) == 176
    assert [r[0] for r in recs] == list(range(176))
    assert recs[85][1] == "HP Freq (Hz)" and (recs[85][2], recs[85][3]) == (20.0, 24000.0)
    assert recs[89][1] == "LP Freq (Hz)" and (recs[89][2], recs[89][3]) == (20.0, 24000.0)

def test_only_the_two_range_records_changed_since_v14():
    v14, v15 = load_declared_v14(), load_declared_v15()
    differing = [i for i, (a, b) in enumerate(zip(v14, v15)) if a != b]
    assert differing == [85, 89]
```

- [ ] **Step 4: Run it**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v`
Expected: PASS. If `hi` reads 20000.0 the frozen instance was V1.4 — delete the fixture and redo Step 2 against the right instance, identified by `fx_ident`.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/v15_declared_176.json tools/rcbitnova_gates.py tests/test_rcbitnova_v16_gates.py
git commit -m "test(rcbitnova): freeze V1.5's 176 declared records before V1.6 exists"
```

---

### Task 2: V1.6 as an exact copy of V1.5, every consumer retargeted

**Files:**
- Create: `JSFX/RCBitNova V1.6`
- Modify: `tools/rcbitnova_gates.py` (add `V16`, retarget `check_source`), `tools/rcbitnova_curve.py`, `tools/rcbitnova_compile.py`, `tools/rcbitnova_nulltest.py`, `tools/rcbitnova_cpu.py`
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Produces: module constant `V16 = "JSFX/RCBitNova V1.6"` in `tools/rcbitnova_gates.py`; `check_source(path=V16, project=False)` is the default source gate from now on. `V15` becomes a FROZEN baseline constant, commented like `V14`.

- [ ] **Step 1: Copy the file and change only `desc`**

```bash
cp "JSFX/RCBitNova V1.5" "JSFX/RCBitNova V1.6"
```

Then edit line 2 of the new file so it begins `desc: RCBitNova V1.6 - ` and keeps the rest of the V1.5 description text unchanged for now.

- [ ] **Step 2: Write the failing test**

```python
def test_v16_exists_and_names_itself():
    text = open("JSFX/RCBitNova V1.6").read()
    assert text.splitlines()[1].startswith("desc: RCBitNova V1.6 - ")

def test_v16_is_byte_identical_to_v15_apart_from_desc():
    a = open("JSFX/RCBitNova V1.5").read().splitlines()
    b = open("JSFX/RCBitNova V1.6").read().splitlines()
    assert len(a) == len(b)
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    assert diff == [1], f"lines differing besides desc: {diff}"
```

- [ ] **Step 3: Run it**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v`
Expected: PASS.

- [ ] **Step 4: Retarget every consumer**

In each of `tools/rcbitnova_gates.py`, `tools/rcbitnova_curve.py`, `tools/rcbitnova_compile.py`, `tools/rcbitnova_nulltest.py`, `tools/rcbitnova_cpu.py`, find every literal `RCBitNova V1.5` that names the *working* file and change it to `V1.6`. Leave the ones that name a frozen baseline. Verify nothing was missed:

```bash
grep -rn "RCBitNova V1\.5" tools/ tests/ | grep -v "FROZEN\|baseline\|v15_declared"
grep -rn "gates\.V15" tests/
```

Expected from the first: only `tools/migrate_v14_to_v15.py` (it migrates V1.4 -> V1.5 and must
keep naming V1.5) and `nulltest.BASE` (V1.5 is now the null BASELINE). Expected from the second:
no output — `tests/test_rcbitnova_dsp.py` names the working file through `gates.V15` in nine
places and they all move to `gates.V16`.

One seeded defect moves with them: the lambda at `tests/test_rcbitnova_dsp.py:2855` replaces
`desc: RCBitNova V1.5 - ` and its expectation reads "the file is V1.5". Left alone it silently
matches nothing, and the harness's own guard ("the seeding lambda changed nothing") fires.

- [ ] **Step 5: Run the whole suite and the source gate**

Run: `python3 -m pytest tests/ -q && python3 tools/rcbitnova_gates.py --source-only`
Expected: all tests pass; the gate reports its site/table/writer/address counts against V1.6.

- [ ] **Step 6: Install for REAPER and confirm identity**

```bash
cp "JSFX/RCBitNova V1.6" ~/Library/Application\ Support/REAPER/Effects/
```

Then, with REAPER open, add it to a scratch track from a script and assert `fx_ident` is exactly `RCBitNova V1.6`. If it reports `V1.5`, the `desc` edit did not take — fix it before going on, because every later live check would silently test the old file.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.6" tools/ tests/test_rcbitnova_v16_gates.py
git commit -m "feat(rcbitnova): V1.6 as an exact copy of V1.5, every version consumer retargeted"
```

---

### Task 3: A Phase switch commits under playback

**Files:**
- Modify: `JSFX/RCBitNova V1.6` (`gc_w_topo`, around line 1079)
- Modify: `tools/rcbitnova_gates.py` (new source check)
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Produces: source gate `check_topo_writer_arms_always(text, path)`, called from `check_source`.

The defect, found live 2026-09-24: clicking `Phase` in the plugin's own window while the transport runs never commits. `gc_w_topo` gates everything on `play_state == 0`; `@block`'s commit at line 1877 waits on `mt_pend`, which only `@slider` or `gc_w_topo` set — and `@slider` need not run after `slider_automate`. FIR Brick then stays an identity until the plugin is reloaded.

- [ ] **Step 1: Write the failing source test**

```python
def _fn_body(text, name):
    i = text.index(f"function {name}(")
    depth, j, started = 0, i, False
    while True:
        if text[j] == "(":
            depth += 1; started = True
        elif text[j] == ")":
            depth -= 1
            if started and depth == 0:
                break
        j += 1
    k = text.index("(", j)
    depth = 0
    while True:
        if text[k] == "(":
            depth += 1
        elif text[k] == ")":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return text[j:k + 1]

def test_gc_w_topo_arms_regardless_of_transport():
    body = _fn_body(open("JSFX/RCBitNova V1.6").read(), "gc_w_topo")
    assert "mt_pend = 1" in body
    arm = body.index("mt_pend = 1")
    gate = body.index("play_state == 0")
    assert arm < gate, "the arm must not sit behind the play_state gate"
    assert "mt_state = 1" in body, "the fade-out must be armed too, or @block never commits"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py::test_gc_w_topo_arms_regardless_of_transport -v`
Expected: FAIL — in V1.5's body the `play_state == 0` gate precedes `mt_pend = 1`.

- [ ] **Step 3: Replace `gc_w_topo` in `JSFX/RCBitNova V1.6`**

Replace the whole function with:

```eel2
function gc_w_topo() local(changed) (
  sel_bd0 = slider141 == 1 ? BD_HIGH : 8192;
  sel_bd1 = slider142 == 1 ? BD_HIGH : 8192;
  changed = slider140 != act_phase
            || (slider140 == 1 && (sel_bd0 != lp_geo[0] || sel_bd1 != lp_geo[4]))
            || (slider140 == 1 && (slider134 != act_hp_pl || slider138 != act_lp_pl));
  // V1.6: ARM unconditionally. V1.4 gated the whole writer on a stopped transport, so a click
  // made under playback set nothing - and @block's commit is itself gated on mt_pend, which only
  // this writer and @slider set, while @slider is not guaranteed to run after slider_automate.
  // The switch then waited for a plugin reload. Found live 2026-09-24.
  changed ? (
    mt_pend = 1;
    mt_ready = 0;
    mt_state != 1 ? (
      mt_pos = floor((1 - mt_g) * mt_fo + 0.5);
      mt_state = 1;
    );
  );
  // Immediate commit ONLY when stopped: the mute ramp that would release it advances in @sample,
  // and with no audio in flight it would never advance. Under playback @block commits at the
  // bottom of the ramp, which is the V0.9 path that already exists.
  changed && play_state == 0 ? ( topo_commit_state(); );
);
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v && python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Add the check to the source gate**

In `tools/rcbitnova_gates.py`, add a `check_topo_writer_arms_always(text, path)` that performs the same three assertions as the test and raises with the offending offsets, and call it from `check_source`.

Run: `python3 tools/rcbitnova_gates.py --source-only`
Expected: passes and prints the new check.

- [ ] **Step 6: Seed a defect and prove the gate catches it**

Temporarily put `play_state == 0 &&` back in front of `changed ?` in the working file, run the gate, confirm it FAILS, then restore.

- [ ] **Step 7: Live check**

Copy the file to the Effects folder, load V1.6 on a track, start playback, set `LP Slope = FIR Brick`, `LP Freq = 18000`, then click `Phase: Min → Linear` **in the plugin window while playing**. The cut must take effect within the mute ramp (about 5 ms fade plus the hold), without a reload. Repeat with the transport stopped: it must still be immediate.

- [ ] **Step 8: Commit**

```bash
git add "JSFX/RCBitNova V1.6" tools/rcbitnova_gates.py tests/test_rcbitnova_v16_gates.py
git commit -m "fix(rcbitnova): a Phase switch made under playback now commits"
```

---

### Task 4: The queue oracle in Python, including the stale-lane case

**Files:**
- Create: `tools/rcbitnova_wedge.py`
- Test: `tests/test_rcbitnova_wedge.py`

**Interfaces:**
- Produces:
  - `brute_max(peaks, wp, Lk, max_look=2048) -> float` — V1.5's rescan, verbatim.
  - `class Wedge` with `__init__(self, cap=2049)`, `reset()`, `rebuild(peaks, wp, Lk, max_look=2048)`, `push(value, pos)`, `evict(pos)`, `top() -> float`, `count() -> int`. (No `base`: the Python oracle owns one lane's ring. The EEL2 side adds a queue index and a peak base — Task 6.)
  - `run_reference(samples, lk_at_sample, active_at_sample, max_look=2048) -> list[float]` — the V1.5 semantics including a lane that does not advance.
  - `run_wedge(...)` — same signature, the queue semantics.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_wedge.py
import random
from tools.rcbitnova_wedge import brute_max, Wedge, run_reference, run_wedge

MAX_LOOK = 2048

def test_matches_brute_force_on_random_data():
    random.seed(7)
    sig = [random.random() for _ in range(5000)]
    assert run_wedge(sig, lambda n: 192, lambda n: True) == \
           run_reference(sig, lambda n: 192, lambda n: True)

def test_matches_across_an_lk_change_midstream():
    random.seed(8)
    sig = [random.random() for _ in range(5000)]
    lk = lambda n: 192 if n < 2500 else 960
    assert run_wedge(sig, lk, lambda n: True) == run_reference(sig, lk, lambda n: True)

def test_equal_runs_do_not_diverge():
    sig = [0.5] * 3000
    assert run_wedge(sig, lambda n: 100, lambda n: True) == \
           run_reference(sig, lambda n: 100, lambda n: True)

def test_strictly_decreasing_at_max_capacity_never_overflows():
    lk = MAX_LOOK - 1
    w = Wedge(cap=lk + 2)
    for n in range(lk + 50):
        w.push(1.0 - n * 1e-6, n % MAX_LOOK)
        if n >= lk + 1:
            w.evict((n - lk - 1) % MAX_LOOK)
        assert w.count() <= w.cap

# The skipped-lane case MUST use a small ring, or it is decorative: at the production MAX_LOOK
# of 2048 a short signal never wraps, the "stale" cells are plain zeros, and a hand-written case
# passes whether the queue rebuilds or not. Verified by seeding. Minimal case, found by search:
STALE_SIG = [4.0, 9.0, 4.0, 1.0, 9.0, 4.0, 4.0, 1.0, 1.0, 4.0]
STALE_ML, STALE_LK = 8, 3
_stale_active = lambda n: n != 8                # one sample where the lane is not written

def test_skipped_lane_reproduces_the_stale_maximum():
    assert run_wedge(STALE_SIG, lambda n: STALE_LK, _stale_active, STALE_ML) == \
           run_reference(STALE_SIG, lambda n: STALE_LK, _stale_active, STALE_ML)

def test_the_stale_case_would_catch_a_queue_that_never_rebuilt():
    # a queue that pushes and evicts without ever rebuilding reports 9.0 at index 9 where the
    # rescan reports 4.0 - the exact divergence the design review predicted
    ...  # drive a bare Wedge by hand; assert (ref[9], naive[9]) == (4.0, 9.0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_wedge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.rcbitnova_wedge'`.

- [ ] **Step 3: Implement `tools/rcbitnova_wedge.py`**

```python
"""The Mode-B lookahead maximum, twice: V1.5's rescan and the monotonic queue that replaces it.

The queue must equal the rescan BUG FOR BUG. V1.5 advances a band's cursor even in placements
where lane B is never written (JSFX/RCBitNova V1.5:2230 sits outside the `two ?` block at
2175-2182), so after Both -> Mid -> Both the rescan reads stale ring values and limits on them.
A queue that quietly did the mathematically clean thing would not null against V1.5.
"""

MAX_LOOK_DEFAULT = 2048


def brute_max(peaks, wp, Lk, max_look=MAX_LOOK_DEFAULT):
    """V1.5: loop(Lk + 1, p = mb_peak[(wp - i + MAX_LOOK) % MAX_LOOK]; p > worst ? worst = p;)"""
    worst = 0.0
    for i in range(Lk + 1):
        p = peaks[(wp - i + max_look) % max_look]
        if p > worst:
            worst = p
    return worst


class Wedge:
    """Monotonic decreasing deque of (value, position); the head is the window maximum."""

    def __init__(self, cap=MAX_LOOK_DEFAULT + 1):
        self.cap = cap
        self.v = [0.0] * cap
        self.p = [0] * cap
        self.head = self.tail = self.cnt = 0

    def reset(self):
        self.head = self.tail = self.cnt = 0

    def count(self):
        return self.cnt

    def push(self, value, pos):
        run = True
        while run:
            if self.cnt > 0:
                t = self.tail - 1
                if t < 0:
                    t += self.cap
                if self.v[t] <= value:
                    self.tail = t
                    self.cnt -= 1
                else:
                    run = False
            else:
                run = False
        t = self.tail
        self.v[t] = value
        self.p[t] = pos
        t += 1
        if t >= self.cap:
            t = 0
        self.tail = t
        self.cnt += 1
        assert self.cnt <= self.cap, "queue overflow: capacity must be MAX_LOOK + 1"

    def evict(self, pos):
        if self.cnt > 1 and self.p[self.head] == pos:
            h = self.head + 1
            if h >= self.cap:
                h = 0
            self.head = h
            self.cnt -= 1

    def top(self):
        return self.v[self.head]

    def rebuild(self, peaks, wp, Lk, max_look=MAX_LOOK_DEFAULT):
        """Replay exactly the positions V1.5 would scan, oldest to newest, EXCLUDING wp."""
        self.reset()
        for r in range(Lk, 0, -1):
            pos = (wp - r + max_look) % max_look
            self.push(peaks[pos], pos)


def _drive(samples, lk_at_sample, active_at_sample, max_look, engine):
    peaks = [0.0] * max_look
    wp = 0
    out = []
    state = {"lk": None, "valid": False, "wedge": Wedge(max_look + 1)}
    for n, s in enumerate(samples):
        lk = lk_at_sample(n)
        active = active_at_sample(n)
        if active:
            peaks[wp] = abs(s)
            out.append(engine(state, peaks, wp, lk, max_look))
        else:
            out.append(None)          # the lane produced nothing this sample
        wp = (wp + 1) % max_look       # V1.5: the cursor advances either way
    return out


def _ref_engine(state, peaks, wp, lk, max_look):
    return brute_max(peaks, wp, lk, max_look)


def _wedge_engine(state, peaks, wp, lk, max_look):
    w = state["wedge"]
    expected = (wp - 1 + max_look) % max_look
    stale_cursor = state.get("last_wp") is not None and state["last_wp"] != expected
    if (not state["valid"]) or state["lk"] != lk or stale_cursor:
        w.rebuild(peaks, wp, lk, max_look)
        state["lk"] = lk
        state["valid"] = True
    w.push(peaks[wp], wp)
    w.evict((wp - lk - 1 + max_look) % max_look)
    state["last_wp"] = wp
    return w.top()


def run_reference(samples, lk_at_sample, active_at_sample, max_look=MAX_LOOK_DEFAULT):
    return _drive(samples, lk_at_sample, active_at_sample, max_look, _ref_engine)


def run_wedge(samples, lk_at_sample, active_at_sample, max_look=MAX_LOOK_DEFAULT):
    return _drive(samples, lk_at_sample, active_at_sample, max_look, _wedge_engine)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_wedge.py -v`
Expected: all PASS. If `test_skipped_lane_reproduces_the_stale_maximum` fails, the rebuild trigger is wrong — the queue must rebuild whenever the cursor advanced without it, which is what `stale_cursor` detects.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_wedge.py tests/test_rcbitnova_wedge.py
git commit -m "test(rcbitnova): the wedge oracle, including V1.5's stale skipped-lane maximum"
```

---

### Task 5: Queue memory in the layout tool

**Files:**
- Modify: `tools/rcbitnova_layout.py`
- Modify: `tools/rcbitnova_gates.py` (`check_addresses`)
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Produces: in `tools/rcbitnova_layout.py`, `DQ_CAP = 2049`, `N_QUEUES = 16`, and entries in the layout result for `dq_v` (`16 * 2049` words), `dq_p` (`16 * 2049`), `dq_meta` (`16 * 5`: head, tail, cnt, valid, lk_pending). Consumed by Task 6 and by the address gate.

- [ ] **Step 1: Write the failing test**

```python
def test_layout_declares_the_queue_block():
    from tools import rcbitnova_layout as L
    assert L.DQ_CAP == 2049 and L.N_QUEUES == 16
    spans = L.v16_new_spans()
    assert spans["dq_v"][1] - spans["dq_v"][0] == 16 * 2049
    assert spans["dq_p"][1] - spans["dq_p"][0] == 16 * 2049
    assert spans["dq_meta"][1] - spans["dq_meta"][0] == 16 * 5
    flat = sorted(spans.values())
    for (a0, a1), (b0, b1) in zip(flat, flat[1:]):
        assert a1 <= b0, f"overlap between {(a0, a1)} and {(b0, b1)}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py::test_layout_declares_the_queue_block -v`
Expected: FAIL with `AttributeError: module 'tools.rcbitnova_layout' has no attribute 'DQ_CAP'`.

- [ ] **Step 3: Add the block to the layout tool**

Add `DQ_CAP = 2049`, `N_QUEUES = 16` beside the existing `MAX_LOOK = 2048` at line 14, and a `v16_new_spans()` that lays the queue block out starting at the 131072 page boundary, returning a dict of `name -> (start, end_exclusive)`. Task 7 extends the same function with the analyser spans, so return a dict that is easy to add to.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_layout.py tests/test_rcbitnova_v16_gates.py
git commit -m "feat(rcbitnova): the wedge queue block in the layout source of truth"
```

---

### Task 6: The wedge in EEL2

**Files:**
- Modify: `JSFX/RCBitNova V1.6` (`@init` addresses; two new functions; the Mode-B block at lines 2137-2235)
- Modify: `tools/rcbitnova_gates.py`
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Consumes: the spans from Task 5, the semantics proven in Task 4.
- Produces: EEL2 functions `dq_push(q, v, p)` and `dq_evict(q, lp)` and `dq_rebuild(q, pkbase, wp, lk)`, where `q` is the queue index `band * 2 + lane`.

- [ ] **Step 1: Write the failing source test**

```python
def test_v16_has_no_bruteforce_rescan_left():
    text = open("JSFX/RCBitNova V1.6").read()
    assert "loop(Lk + 1," not in text, "the per-sample window rescan must be gone"
    assert "dq_push(" in text and "dq_evict(" in text and "dq_rebuild(" in text

def test_wedge_push_has_no_assignment_in_a_nested_ternary():
    text = open("JSFX/RCBitNova V1.6").read()
    body = _fn_body(text, "dq_push")
    assert "while(" in body, "use a while loop, not a nested ternary (V0.8's silent defect)"
    assert "+=" not in body.split("while(")[1].split(")")[0]

def test_queue_capacity_is_max_look_plus_one():
    text = open("JSFX/RCBitNova V1.6").read()
    assert "DQ_CAP = 2049" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v`
Expected: FAIL — V1.6 is still a copy of V1.5 and still contains `loop(Lk + 1,`.

- [ ] **Step 3: Add the queue functions to `@init`**

```eel2
// ---- V1.6: sliding-window maximum, 16 queues (8 bands x 2 lanes) ----
// Ported from Fable Mix Limiter 2 (Fable Eq Mix, 383-402 and 911-925). Values decrease from head
// to tail, so the head is the window maximum, and exactly one position leaves the window per
// sample. CAPACITY IS MAX_LOOK + 1: the reference pushes BEFORE evicting, so occupancy is
// transiently Lk + 2, and at the clamp Lk = 2047 that is 2049 - one past a 2048-slot buffer,
// which would overwrite its own head. The wrap below is a comparison, not a mask, so a
// non-power-of-two capacity costs nothing.
DQ_CAP = 2049;

function dq_push(q, v, p) local(base, t, run) (
  base = q * DQ_CAP;
  run = 1;
  while (run) (
    dq_cnt[q] > 0 ? (
      t = dq_tail[q] - 1; t < 0 ? t += DQ_CAP;
      dq_v[base + t] <= v ? ( dq_tail[q] = t; dq_cnt[q] = dq_cnt[q] - 1; ) : ( run = 0; );
    ) : ( run = 0; );
  );
  t = dq_tail[q];
  dq_v[base + t] = v; dq_p[base + t] = p;
  t += 1; t >= DQ_CAP ? t = 0;
  dq_tail[q] = t; dq_cnt[q] = dq_cnt[q] + 1;
);

function dq_evict(q, lp) local(h) (
  h = dq_head[q];
  (dq_cnt[q] > 1 && dq_p[q * DQ_CAP + h] == lp) ? (
    h += 1; h >= DQ_CAP ? h = 0;
    dq_head[q] = h; dq_cnt[q] = dq_cnt[q] - 1;
  );
);

// Replay exactly the positions V1.5's rescan would read, oldest to newest, EXCLUDING wp.
// Reading mb_peak at those positions - rather than recomputing anything - is what reproduces
// the stale values a skipped lane leaves in the ring.
function dq_rebuild(q, pkbase, wp, lk) local(r, pos) (
  dq_head[q] = 0; dq_tail[q] = 0; dq_cnt[q] = 0;
  r = lk;
  while (r >= 1) (
    pos = wp - r; pos < 0 ? pos += MAX_LOOK;
    dq_push(q, mb_peak[pkbase + pos], pos);
    r -= 1;
  );
);
```

- [ ] **Step 4: Replace both rescans in the Mode-B block**

For lane A, replace

```eel2
        worstA = 0; i = 0;
        loop(Lk + 1, p = mb_peak[baseA + ((wp - i + MAX_LOOK) % MAX_LOOK)]; p > worstA ? worstA = p; i += 1;);
```

with

```eel2
        qa = b * 2;
        // Rebuild when this lane is invalid, when Lk changed for it, or when the band cursor
        // advanced while this lane was not written - V1.5's own behaviour in single-lane
        // placements. Validity is PER LANE: a global flag would mark a lane clean that never
        // rebuilt. Every branch is a plain assignment in explicit parens.
        expA = wp - 1; expA < 0 ? expA += MAX_LOOK;
        (dq_valid[qa] == 0 || dq_lk[qa] != Lk || dq_lastwp[qa] != expA) ? (
          dq_rebuild(qa, baseA, wp, Lk);
          dq_valid[qa] = 1; dq_lk[qa] = Lk;
        );
        dq_push(qa, mb_peak[baseA + wp], wp);
        evA = wp - Lk - 1; evA < 0 ? evA += MAX_LOOK;
        dq_evict(qa, evA);
        dq_lastwp[qa] = wp;
        worstA = dq_v[qa * DQ_CAP + dq_head[qa]];
```

Do the same for lane B inside the `two ?` block, with `qb = b * 2 + 1` and `baseB`. Add `qa, qb, expA, expB, evA, evB` to the `@sample` local declarations if that section declares locals; otherwise they are ordinary globals like `worstA`.

- [ ] **Step 5: Run the tests and the gate**

Run: `python3 -m pytest tests/ -q && python3 tools/rcbitnova_gates.py --source-only`
Expected: all pass.

- [ ] **Step 6: Compile in REAPER**

Run: `python3 tools/rcbitnova_compile.py`
Expected: 179 parameters, no error text in the FX window. A JSFX with a syntax error still loads and still reports its sliders, so "the parameters are there" proves nothing on its own — the check must read the error line.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.6" tools/ tests/
git commit -m "perf(rcbitnova): the lookahead maximum is O(1) per sample, per lane"
```

---

### Task 7: The nulls that prove the wedge is the old detector

**Files:**
- Modify: `tools/rcbitnova_nulltest.py`
- Test: run, not asserted offline

**Interfaces:**
- Produces: `run_transition_cases()` returning `list[dict]` with keys `name`, `identical` (bool), `max_abs_diff` (float), `samples` (int).

- [ ] **Step 1: Add the six transition cases**

Extend `tools/rcbitnova_nulltest.py` with V1.6-against-V1.5 cases, comparator 64-bit float with zero tolerance, 8 bands in Mode B Split, material with content in both lanes:

1. lookahead automated mid-stream, 2 ms → 10 ms → 2 ms;
2. `Both → Mid → Both` on band 3;
3. a lookahead change while lane B is inactive, then a return to `Both`;
4. Mode B off → on; band 5 disabled → re-enabled;
5. Analyzer On with the FX window closed for the whole render;
6. `Lk = 2047` at 384 kHz with strictly decreasing data, equal runs, random data, and several ring wraps.

Automate the parameter changes with `rpr.TrackFX_SetParamNormalized(track.id, fx_index, i, v)` — never `param.normalized = v`, which reapy cannot write.

- [ ] **Step 2: Run the steady-state nulls first**

Run: `python3 tools/rcbitnova_nulltest.py`
Expected: the existing cases identical, then the six new ones identical.

- [ ] **Step 3: Seed one defect per transition and confirm each is caught**

For each case, temporarily break exactly the thing it exists to catch — for case 2, drop `dq_lastwp[qa] != expA` from the rebuild condition; for case 6, set `DQ_CAP = 2048`; for case 1, consume the `Lk` change globally instead of per lane. Each must turn its own case red and, ideally, only that one. Restore after each.

- [ ] **Step 4: Commit**

```bash
git add tools/rcbitnova_nulltest.py
git commit -m "test(rcbitnova): transition nulls - the wedge equals V1.5 at every boundary"
```

---

### Task 8: The spectrum oracle in Python

**Files:**
- Create: `tools/rcbitnova_spectrum.py`
- Test: `tests/test_rcbitnova_spectrum.py`

**Interfaces:**
- Produces:
  - `hann(n) -> list[float]`
  - `magnitudes(samples, fft_n=8192) -> list[float]` — windowed FFT magnitudes scaled by `4 / fft_n`, length `fft_n // 2`.
  - `to_columns(mags, srate, px_n, f_min, f_max, fft_n=8192) -> list[float]` — bits per column, both binning branches, Nyquist and sub-bin-1 rules.
  - `apply_tilt(cols, srate, px_n, f_min, f_max, tilt_db) -> list[float]`
  - `smooth3(cols, passes=2) -> list[float]`
  - `red_state(mid_cols, side_cols, prev_state, floor_bits=-16.0, hyst_bits=0.1) -> list[int]` — 0 normal, 1 warm, 2 bright.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcbitnova_spectrum.py
import math
from tools.rcbitnova_spectrum import (hann, magnitudes, to_columns, apply_tilt,
                                      smooth3, red_state)

SR, FFT_N, PX, FMIN, FMAX = 96000, 8192, 900, 20.0, 24000.0

def _tone(freq, n=FFT_N, amp=0.5, sr=SR):
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]

def test_a_tone_lands_on_its_own_column():
    cols = to_columns(magnitudes(_tone(1000.0)), SR, PX, FMIN, FMAX)
    peak = max(range(PX), key=lambda i: cols[i])
    x = math.log(1000.0 / FMIN) / math.log(FMAX / FMIN) * (PX - 1)
    assert abs(peak - x) <= 1.0

def test_a_tone_between_columns_still_peaks_between_them():
    f = FMIN * (FMAX / FMIN) ** ((300.5) / (PX - 1))
    cols = to_columns(magnitudes(_tone(f)), SR, PX, FMIN, FMAX)
    peak = max(range(PX), key=lambda i: cols[i])
    assert peak in (300, 301)

def test_amplitude_is_reported_in_bits():
    cols = to_columns(magnitudes(_tone(1000.0, amp=0.5)), SR, PX, FMIN, FMAX)
    assert abs(max(cols) - (-1.0)) < 0.35      # 0.5 == -1 bit

def test_halving_the_amplitude_drops_exactly_one_bit():
    a = max(to_columns(magnitudes(_tone(1000.0, amp=0.5)), SR, PX, FMIN, FMAX))
    b = max(to_columns(magnitudes(_tone(1000.0, amp=0.25)), SR, PX, FMIN, FMAX))
    assert abs((a - b) - 1.0) < 0.05

def test_columns_above_nyquist_are_floor_not_a_repeat():
    cols = to_columns(magnitudes(_tone(1000.0, sr=44100), fft_n=FFT_N),
                      44100, PX, FMIN, FMAX)
    x22k = int(math.log(22050.0 / FMIN) / math.log(FMAX / FMIN) * (PX - 1))
    assert all(c <= -20.0 for c in cols[x22k + 2:])

def test_low_columns_clamp_the_index_before_the_fraction():
    # at 192 kHz, 20 Hz is bin 0.853; a fraction computed before the clamp
    # interpolates the wrong pair and the first column jumps
    cols = to_columns(magnitudes(_tone(100.0, sr=192000)), 192000, PX, FMIN, FMAX)
    assert cols[0] <= cols[1] + 6.0

def test_tilt_is_zero_at_1k_and_one_octave_up_is_exact():
    base = [0.0] * PX
    t = apply_tilt(base, SR, PX, FMIN, FMAX, 6.020599913)
    i1k = int(math.log(1000.0 / FMIN) / math.log(FMAX / FMIN) * (PX - 1))
    i2k = int(math.log(2000.0 / FMIN) / math.log(FMAX / FMIN) * (PX - 1))
    assert abs(t[i1k]) < 0.02
    assert abs(t[i2k] - 1.0) < 0.02           # 6.0206 dB/oct == 1 bit/oct

def test_smoothing_preserves_length_and_ends():
    c = [float(i % 7) for i in range(PX)]
    s = smooth3(c, passes=2)
    assert len(s) == PX and s[0] == c[0] and s[-1] == c[-1]

def test_red_needs_the_floor_and_the_hysteresis():
    mid = [-30.0] * 4                          # both below the -16 bit floor
    side = [-25.0] * 4
    assert red_state(mid, side, [0] * 4) == [0, 0, 0, 0]
    mid2 = [-10.0, -10.0, -10.0, -10.0]
    side2 = [-10.05, -9.8, -8.5, -10.05]       # inside hysteresis, warm, bright, inside again
    st = red_state(mid2, side2, [0, 0, 0, 1])
    assert st == [0, 1, 2, 1]                  # the last stays red until it drops 0.1 bit
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_spectrum.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `tools/rcbitnova_spectrum.py`**

Use `math` and a plain iterative radix-2 FFT (no numpy — the rest of `tools/` has no numpy dependency). Rules to encode exactly:

- magnitude scale `4 / fft_n`; `mag_bits = log2(max(mag, 1e-12))`;
- per column `b0 = f_left * fft_n / srate`, `b1 = f_right * fft_n / srate`;
  **`b1 - b0 <= 1` → interpolate** between adjacent bins; **`> 1` → maximum** over them;
- clamp the bin *index* to `[1, fft_n // 2 - 2]` **before** computing the interpolation fraction;
- a column whose left edge is at or above `srate / 2` returns the floor `-20.0`, never the last bin;
- `tilt_bits = tilt_db / 6.020599913 * log2(f / 1000)`;
- `smooth3` is `prev * 0.25 + cur * 0.5 + next * 0.25` over interior columns, run `passes` times, ends untouched;
- `red_state`: eligible only when `max(mid, side) >= floor_bits`; turn on above `mid + hyst`, off below `mid - hyst`, bright above `mid + 1.0`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_spectrum.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_spectrum.py tests/test_rcbitnova_spectrum.py
git commit -m "test(rcbitnova): the spectrum oracle - binning, bits, tilt, Nyquist, the red rule"
```

---

### Task 9: Analyser memory and the `@sample` taps

**Files:**
- Modify: `tools/rcbitnova_layout.py` (analyser spans), `JSFX/RCBitNova V1.6` (`@init`, `@sample`)
- Modify: `tools/rcbitnova_gates.py` (`check_addresses`, a page-safety check)
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Consumes: `v16_new_spans()` from Task 5.
- Produces: spans `an_w` (8192), `an_in` (8192), `an_out` (8192), `an_mi` (4096), `an_mo` (4096), `an_pkI` (2048), `an_pkO` (2048), `an_db` (2048), `an_ms_state` (2048), `an_sc` (16384), `an_meta` (16); `lp_base` at 262144.

- [ ] **Step 1: Write the failing tests**

```python
def test_analyser_spans_are_declared_and_disjoint():
    from tools import rcbitnova_layout as L
    s = L.v16_new_spans()
    for name, words in [("an_w", 8192), ("an_in", 8192), ("an_out", 8192),
                        ("an_mi", 4096), ("an_mo", 4096), ("an_pkI", 2048),
                        ("an_pkO", 2048), ("an_db", 2048), ("an_ms_state", 2048),
                        ("an_sc", 16384), ("an_meta", 16)]:
        assert s[name][1] - s[name][0] == words, name
    flat = sorted(s.values())
    for (a0, a1), (b0, b1) in zip(flat, flat[1:]):
        assert a1 <= b0

def test_fft_scratch_does_not_cross_a_page():
    from tools import rcbitnova_layout as L
    lo, hi = L.v16_new_spans()["an_sc"]
    assert lo // 65536 == (hi - 1) // 65536, "an_sc crosses a 65536-word page: silent corruption"

def test_engines_start_at_the_declared_page():
    from tools import rcbitnova_layout as L
    assert L.v16_lp_base() == 262144
    assert max(e for _, e in L.v16_new_spans().values()) <= 262144
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v`
Expected: FAIL — `an_w` is not in the dict yet.

- [ ] **Step 3: Add the analyser spans and `v16_lp_base()`**

Lay the analyser block out after the queue block, page-aligning `an_sc` so its 16384 words sit inside one 65536 page, and return `262144` from `v16_lp_base()`.

- [ ] **Step 4: Write the EEL2 `@init` block and the taps**

In `@init`, set every `an_*` address from the numbers the layout tool prints (paste the literals; the gate compares them). Build the Hann window:

```eel2
i = 0; loop(FFT_N, an_w[i] = 0.5 - 0.5 * cos(2 * $pi * i / FFT_N); i += 1;);
```

At the very top of `@sample`, inside the `slider1 != 1` branch, capture the input **before anything**:

```eel2
  iL = spl0; iR = spl1;
```

At the very end of `@sample`, after `out_gain` and the topology mute:

```eel2
  // V1.6 analyser. Reads only. One cursor advances both rings, so IN and OUT can never drift
  // by a sample. an_on and the domain are read INLINE: state cached in @slider or @block is dead
  // while the transport is stopped, which is the shape of three earlier bugs in this plugin.
  slider247 >= 0.5 ? (
    an_gen != an_gen_seen ? (
      memset(an_in, 0, FFT_N); memset(an_out, 0, FFT_N);
      an_pos = 0; an_fill = 0; an_gen_seen = an_gen;
    );
    an_dom = slider248;
    an_dom == 0 ? ( an_a = (iL + iR) * 0.5;  an_b = (spl0 + spl1) * 0.5; ) :
    an_dom == 1 ? ( an_a = (iL - iR) * 0.5;  an_b = (spl0 - spl1) * 0.5; ) :
    an_dom == 2 ? ( an_a = iL;               an_b = spl0; ) :
    an_dom == 3 ? ( an_a = iR;               an_b = spl1; ) :
                  ( an_a = (spl0 + spl1) * 0.5; an_b = (spl0 - spl1) * 0.5; );
    an_in[an_pos] = an_a; an_out[an_pos] = an_b;
    an_pos += 1; an_pos >= FFT_N ? an_pos = 0;
    an_fill < FFT_N ? an_fill = an_fill + 1;
  );
```

- [ ] **Step 5: Prove the audio did not move**

Run: `python3 tools/rcbitnova_nulltest.py`
Expected: every case identical, with Analyzer both Off and On. A tap that nulls is the proof that it only reads.

- [ ] **Step 6: Run the tests and the gate, then commit**

```bash
python3 -m pytest tests/ -q && python3 tools/rcbitnova_gates.py --source-only
git add "JSFX/RCBitNova V1.6" tools/ tests/
git commit -m "feat(rcbitnova): analyser memory and the two read-only taps"
```

---

### Task 10: The analyser in `@gfx`, with the red rule

**Files:**
- Modify: `JSFX/RCBitNova V1.6` (`@gfx`)
- Test: visual, plus the oracle from Task 8

**Interfaces:**
- Consumes: the rings from Task 9 and every rule proven in Task 8.

- [ ] **Step 1: Latch the frame**

At the top of the analyser's part of `@gfx`, take `an_pos` and `an_gen_seen` **once** into frame locals and use only those for both transforms. Draw nothing unless `an_fill >= FFT_N`. If `an_gen_seen` changed by the end of the copy, discard the frame.

- [ ] **Step 2: Transform both streams**

```eel2
an_px_n = min(gc_pw, 2048);
an_st = 0;
loop(2,
  an_src = an_st == 0 ? an_in : an_out;
  an_mag = an_st == 0 ? an_mi : an_mo;
  i = 0;
  loop(FFT_N, an_sc[i*2] = an_src[(an_latch + i) % FFT_N] * an_w[i]; an_sc[i*2+1] = 0; i += 1;);
  fft(an_sc, FFT_N); fft_permute(an_sc, FFT_N);
  i = 0;
  loop(FFT_N/2,
    re = an_sc[i*2]; im = an_sc[i*2+1];
    mg = sqrt(re*re + im*im) * (4 / FFT_N);
    pv = an_mag[i] * 0.86; an_mag[i] = mg > pv ? mg : pv;
    i += 1;
  );
  an_st += 1;
);
```

- [ ] **Step 3: Bin, tilt, smooth**

Per column, with `b0`/`b1` the bin indices of the column's edges: **`b1 - b0 <= 1` interpolates** between adjacent bins, **`> 1` takes the maximum** over them. Clamp the index before the fraction. A column whose left edge is at or above `srate * 0.5` writes the floor `-20`. Convert with `log(mag)/log(2)`, add `tilt_bits = tilt_db / 6.020599913 * log(f/1000)/log(2)`, then run the 3-tap smoothing twice over the interior columns.

- [ ] **Step 4: Draw**

Spectrum first as a fill from the bottom on the **−20…+2 bit** scale, then the grid, then the EQ curve, then the band nodes. IN grey behind, OUT green in front.

- [ ] **Step 5: The red rule, in `M/S` only**

After both smoothing passes, on the drawn values:

```eel2
slider248 == 4 ? (
  gxx = 0;
  loop(an_px_n,
    md = an_cm[gxx]; sd = an_cs[gxx];
    max(md, sd) >= -16 ? (
      an_ms_state[gxx] == 0 ? (
        sd > md + 0.1 ? an_ms_state[gxx] = 1;
      ) : (
        sd < md - 0.1 ? an_ms_state[gxx] = 0;
      );
      an_ms_state[gxx] == 1 && sd > md + 1 ? an_ms_state[gxx] = 2;
      an_ms_state[gxx] == 2 && sd <= md + 1 ? an_ms_state[gxx] = 1;
    ) : ( an_ms_state[gxx] = 0; );
    gxx += 1;
  );
);
```

Colour column `gxx` warm red at state 1 and bright red at state 2.

- [ ] **Step 6: Check against the oracle**

Feed REAPER a rendered fixture of a known tone, screenshot the plot, and confirm the peak column and its bit value match `tools/rcbitnova_spectrum.py` for the same input within one column and 0.35 bits.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.6"
git commit -m "feat(rcbitnova): the analyser draws, with M/S and the red over-width rule"
```

---

### Task 11: Controls, top-bar geometry, and the manifest gate

**Files:**
- Modify: `JSFX/RCBitNova V1.6` (slider declarations, `@gfx` top bar, `gc_topbar_hot`)
- Modify: `tools/rcbitnova_gates.py` (`--live` manifest)
- Test: `tests/test_rcbitnova_v16_gates.py`

**Interfaces:**
- Produces: `expected_v16_manifest() -> list[dict]` — the 176 V1.5 records as an exact prefix, then records 176..179.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_sliders_are_numbered_above_every_existing_one():
    import re
    text = open("JSFX/RCBitNova V1.6").read()
    nums = sorted(int(m) for m in re.findall(r"^slider(\d+):", text, re.M))
    assert nums[-4:] == [247, 248, 249, 250]

def test_manifest_keeps_v15_as_an_exact_prefix():
    import json
    from tools.rcbitnova_gates import expected_v16_manifest
    v15 = json.load(open("tests/fixtures/v15_declared_176.json"))
    v16 = expected_v16_manifest()
    assert v16[:176] == v15
    assert len(v16) == 180
    assert [r["name"] for r in v16[176:]] == [
        "Analyzer", "Analyzer Domain", "Analyzer Tilt", "Analyzer Peak Hold"]
    assert v16[176]["default"] == 0.0
    assert v16[177]["labels"] == ["Mid", "Side", "Left", "Right", "M/S"]
    assert v16[179]["default"] == 0.0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_v16_gates.py -v`
Expected: FAIL — the sliders do not exist yet.

- [ ] **Step 3: Declare the four parameters**

```eel2
slider247:0<0,1,1{Off,On}>-Analyzer
slider248:0<0,4,1{Mid,Side,Left,Right,M/S}>-Analyzer Domain
slider249:2<0,2,1{0,3,4.5}>-Analyzer Tilt (dB/oct)
slider250:0<0,1,1{Off,On}>-Analyzer Peak Hold
```

- [ ] **Step 4: Draw the second top-bar row and extend pointer ownership**

Add a second row under the existing five slots, recompute `gc_panel_on` / `gc_small` from the reduced plot height, hide the row in small mode, and add the union of the four new rectangles to the early `gc_topbar_hot` calculation at the site that currently owns the top bar (V1.5 lines 2358-2373) — **before** node hit collection. A control drawn without that extension reopens the defect where a click on a label enabled and armed a band.

- [ ] **Step 5: Run the live manifest gate**

Run: `python3 tools/rcbitnova_gates.py --live`
Expected: 180 declared plus the three host parameters at 180..182, and the V1.5 prefix unchanged.

- [ ] **Step 6: Round-trip the controls**

Save the project, reload it, and confirm all four read back. Write an automation envelope on each and read it back.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.6" tools/rcbitnova_gates.py tests/test_rcbitnova_v16_gates.py
git commit -m "feat(rcbitnova): four analyser controls, a second top-bar row, ownership extended"
```

---

### Task 12: CPU acceptance and the live matrix

**Files:**
- Create: `docs/superpowers/V16-LIVE-MATRIX.md`
- Modify: `tools/rcbitnova_cpu.py`

- [ ] **Step 1: Measure under pinned conditions**

96 kHz, 512-sample block, 8 bands in Mode B Split, `Phase: Min`, Analyzer On, peak hold on, FX window **closed** for the audio-thread figure and **open** for the GUI figure, Performance Meter FX CPU column, 60 s average. Read at lookahead 0.1, 2 and 10 ms.

- [ ] **Step 2: Assert the invariant, not a number**

The three readings must agree within ±0.3 % of each other. The accepted result is **the disappearance of the linear `Lk` term**; 1.4 % was a fit intercept, and machine scheduling moves it.

- [ ] **Step 3: Write the live matrix**

`docs/superpowers/V16-LIVE-MATRIX.md`, covering: the analyser with the transport **stopped**, including a domain change there (it clears and waits — expected, not a hang); domain switching under playback with no mixed-stream smear; peak-hold reset by right-click and the reset matrix across transport start, sample-rate change and Analyzer Off→On; the lookahead knob moved under playback with no click; **anti-phase material must turn columns red and a mono source must never show red at any level**; top-bar clicks at 900×500, default and Retina sizes enabling no band; and a Phase switch under playback engaging FIR Brick without a reload.

- [ ] **Step 4: Commit, and tag only after the owner has run it**

```bash
git add docs/superpowers/V16-LIVE-MATRIX.md tools/rcbitnova_cpu.py
git commit -m "docs(rcbitnova): the V1.6 live matrix and the CPU acceptance conditions"
```

Tag `rcbitnova-v1.6` only after the owner reports the matrix, and record in the tag message what was confirmed live and what was not.

---

## Self-Review

**Spec coverage.** §1 → Tasks 4-7, 12. §2 → Tasks 6, 10 (ported forms and the two things not carried over). §3 → Tasks 9-11. §4.1 ownership/generations → Task 9 Step 4, Task 10 Step 1. §4.2 taps and five domains → Task 9 Step 4, Task 11 Step 3. §4.3 binning, `an_px_n`, Nyquist, sub-bin-1, bit conversion → Task 8, Task 10 Step 3. §4.4 drawing → Task 10 Step 4. §4.4.1 red rule → Task 8 (`red_state`), Task 10 Step 5, Task 12 Step 3. §4.5 controls, defaults, geometry, pointer ownership → Task 11. §5 memory → Tasks 5 and 9. §6 wedge, four contracts → Tasks 4, 6, 7. §7 acceptance → Tasks 7, 8, 11, 12. §8 lifecycle → Task 12 Step 3 plus the reset paths in Tasks 9-10. §9 risks → carried as comments in the code the tasks write.

**Gap found and closed:** the spec's first-load marker for peak persistence had no task; it is allocated as part of `an_meta` (16 words) in Task 9 and its reset matrix is checked in Task 12 Step 3.

**Placeholder scan:** no "TBD", no "add error handling", no "similar to Task N". Every code step carries the code.

**Type consistency:** `v16_new_spans()` and `v16_lp_base()` are named identically in Tasks 5, 9 and their tests; `dq_push(q, v, p)` / `dq_evict(q, lp)` / `dq_rebuild(q, pkbase, wp, lk)` keep the same signatures in Tasks 6 and 7; the oracle names `brute_max`, `Wedge`, `run_reference`, `run_wedge`, `red_state` match between Tasks 4, 8 and their tests.
