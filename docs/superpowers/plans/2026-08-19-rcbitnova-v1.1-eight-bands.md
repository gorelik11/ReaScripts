# RCBitNova V1.1 — Eight Bands Implementation Plan

**Revision 2** — after the plan weakness review
(`docs/superpowers/plans/2026-08-19-rcbitnova-v1.1-eight-bands-weaknesses.md`). Five P0s, all
accepted; disposition at the end of this file. The task order changed: `N_BANDS` is now raised to
8 **last**, not first.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the static EQ from four to eight bands, keeping dynamics (Mode A, Mode B, ceilings, detectors) on the first four only.

**Architecture:** One constant becomes two — `N_BANDS = 8` for static EQ, `N_DYN = 4` for everything dynamic — applied to 28 enumerated sites. Bands 5–8 get sliders 151–189, their own static-only loop in `@sample` placed before the Mode-B pass, and a right-click menu for the parameters gestures cannot reach. No memory address moves except the GUI coefficient scratch.

**Tech Stack:** JSFX (EEL2); Python 3.11 stdlib-only oracle (`tools/rcbitnova_dsp.py`, `tools/rcbitnova_curve.py`); `pytest`; `reapy` for parameter comparison; live REAPER.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-19-rcbitnova-v1.1-eight-bands-design.md` (**rev 4**). Section numbers below are that document's.
- **New file `JSFX/RCBitNova V1.1`, an exact copy of `JSFX/RCBitNova V1.0`.** V1.0 and earlier are frozen and tagged; `rcbitnova-v1.0` is the fallback.
- **§3.2 is the authoritative site list.** 28 places use `N_BANDS`: 17 become `N_DYN`, 8 stay, 2 split. Missing `mb_peak`/`mb_end` alone relocates the entire map by 16384 words — silently, with no error.
- **Two zero-slack boundaries:** `cf + 8*8 == st == 64` and `st + 8*4 == det == 96`. Eight bands is the maximum this layout holds. Guard words cannot be placed in the production layout — there is no spare word; bounds testing uses an instrumented shadow layout in Python (§6.2).
- **`bp`, `dp`, `dm`, `det`, `dst`, `cst`, `eg`, `egh`, `hc`, `mb_*` stay at four bands.** `bp` is written only by `setup_band_dyn`.
- **Bands 5–8 run in their own loop, before Mode B**, and that loop must not mention `dp`, `dm`, `mbmode`, `bp`, `det`, `dst`, `cst`, `eg`, `egh` or `hc`. V1.0's band loop reads `dp[b*4+3]` and `dm[b]` before filtering — a read overrun that write canaries cannot catch.
- **Reads** of band sliders go through `band_slider_base(b)`; **writes** must be explicit named `sliderNN` branches, eight-way. V1.0 proved that assigning through a computed index never reaches the parameter.
- **`setup_band_dyn(b)` is guarded by `b < N_DYN`** everywhere, including every GUI writer, which today calls it unconditionally.
- **New slider declarations go AFTER every existing one in the file.** Verified live: the host numbers parameters densely in declaration order, so this is what keeps V1.0's parameter list an exact prefix of V1.1's.
- **EEL2 resolves functions in file order** — four builds broke on this in V1.0. Check every new call site against its definition position.
- **`N_BANDS` stays 4 until Task 6.** Every dynamic site is converted to `N_DYN`, and all the
  eight-band machinery is added, while the plugin is still a four-band plugin. The count flip is
  one line in its own task, after every path that could read or write past a four-band array is
  already bounded. The rejected order — flip first, bound later — produces a plugin whose
  `@slider` pass writes `det`/`dp`/`dm`/`bp` out of range on the very first load, and commits it.
- **No open-coded band-slider arithmetic outside `band_slider_base`**, except inside loops proven
  to be `N_DYN`-bounded, where the line must carry the marker comment `// N_DYN-bounded`. The gate
  in Task 9 enforces exactly this. V1.0 open-codes `10 * (b + 1)` in **eight `@gfx` sites** — hit
  test, click-to-enable, drag capture, drag read, wheel-Q, node draw, readout, selected band —
  and all eight execute for B5–B8 once the GUI loops grow. Unconverted, they would read sliders
  51–89, which are bands 1–4's *dynamics* controls.
- **Measured, not assumed (2026-08-19, reapy on the live V1.0):** the host reports **98**
  parameters — 95 declared sliders at indices 0–94, then **three** host-owned specials,
  `Bypass`, `Wet`, `Delta`. V1.1 inserts 36 declared sliders *before* that tail, so **V1.0's full
  parameter list is NOT a prefix of V1.1's** — only the 95 declared ones are. Any index-wise copy
  or prefix comparison must stop at 94 and handle the tail by name.
- **Never claim a task is done without running its test and reading the output.**
- Run from the worktree root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. All 221 existing tests stay green at every commit.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/rcbitnova_layout.py` | NEW. The memory map as data: base addresses, per-band sizes, ownership (static/dynamic), and an instrumented shadow layout for bounds testing. Kept separate so the map has one machine-readable source instead of living in comments. | Create |
| `tools/rcbitnova_curve.py` | Gains `band_slider_base`. | Modify |
| `tests/test_rcbitnova_dsp.py` | V1.1 test block appended. | Modify |
| `JSFX/RCBitNova V1.1` | The plugin. | Create (copy of V1.0), then modified in Tasks 3–6 |
| `tools/migrate_v10_to_v11.py` | NEW. The one supported migration: copies the 95 declared parameters by index and the host tail by name, in place and transactionally, refusing when automation is present. | Create (Task 8) |
| `tools/rcbitnova_gates.py` | NEW. The release gates as executable checks: the 28-site table, the address manifest computed through `lp_base`, and the parameter manifest. Exits nonzero on failure. | Create (Task 9) |
| `tools/rcbitnova_nulltest.py` | NEW. Renders the V1.0/V1.1 null cases and compares sample for sample at zero tolerance. Exits nonzero on any mismatch. | Create (Task 9) |
| `tools/rcbitnova_cpu.py` | NEW. Median peak block time and xrun count over the prescribed runs; exits nonzero on regression or any xrun. | Create (Task 9) |

Tasks 1–2 are pure Python. Tasks 3–6 are the JSFX transcription, each live-verifiable. Tasks 7–9 are gates, migration and shipping.

---

### Task 1: The memory map as data

**Files:**
- Create: `tools/rcbitnova_layout.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces:
  - `STATIC = {"cf": (0, 8), "st": (64, 4)}` — name → (base, words per band)
  - `DYNAMIC = {"det": (96, 4), "dst": (128, 4), "cst": (160, 4), "dp": (192, 4), "dm": (208, 1), "bp": (216, 3), "eg": (256, 2)}`
  - `layout(n_bands, n_dyn) -> dict[str, tuple[int, int]]` — name → (first word, last word inclusive)
  - `check_adjacency(n_bands, n_dyn) -> list[str]` — empty when every array ends exactly where the next begins or earlier
  - `shadow_layout(n_bands, n_dyn, guard=1) -> dict` — the same map with `guard` spare words between arrays, for bounds testing only

- [ ] **Step 1: Write the failing tests**

```python
from tools import rcbitnova_layout as lay   # noqa: E402


def test_v11_four_bands_matches_the_shipped_addresses():
    """The shipped V1.0 layout must come out of the model unchanged - otherwise the model is
    describing some other plugin."""
    m = lay.layout(4, 4)
    assert m["cf"][0] == 0 and m["st"][0] == 64
    assert m["det"][0] == 96 and m["dst"][0] == 128 and m["cst"][0] == 160
    assert m["dp"][0] == 192 and m["dm"][0] == 208 and m["bp"][0] == 216 and m["eg"][0] == 256


def test_v11_eight_static_bands_fit_exactly():
    """cf ends exactly where st starts; st ends exactly where det starts. Zero slack - this is
    the whole reason eight is the maximum."""
    m = lay.layout(8, 4)
    assert m["cf"] == (0, 63), m["cf"]
    assert m["st"] == (64, 95), m["st"]
    assert m["cf"][1] + 1 == lay.STATIC["st"][0] == 64
    assert m["st"][1] + 1 == lay.DYNAMIC["det"][0] == 96
    assert lay.check_adjacency(8, 4) == []


def test_v11_nine_bands_would_overflow():
    """Guards the claim that eight is the maximum. If someone later raises N_BANDS to 9 this
    test says exactly what breaks, instead of the plugin silently corrupting itself."""
    problems = lay.check_adjacency(9, 4)
    assert problems, "nine bands must be reported as an overflow"
    assert any("cf" in p for p in problems)


def test_v11_dynamic_arrays_do_not_grow_with_band_count():
    four = lay.layout(4, 4)
    eight = lay.layout(8, 4)
    for name in lay.DYNAMIC:
        assert four[name] == eight[name], f"{name} moved when static bands grew"


def test_v11_shadow_layout_has_room_for_guards():
    """Bounds testing needs guard words, and the production layout has none - so the shadow
    layout is where overruns are detected."""
    sh = lay.shadow_layout(8, 4, guard=2)
    names = list(sh)
    for a, b in zip(names, names[1:]):
        assert sh[a][1] + 2 < sh[b][0], f"{a}/{b} have no guard gap"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v11`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.rcbitnova_layout'`.

- [ ] **Step 3: Implement `tools/rcbitnova_layout.py`**

```python
"""RCBitNova's low memory map, as data rather than as comments.

Every address here is a fixed literal in the JSFX @init block. Keeping a machine-readable copy
is what lets the tests assert adjacency instead of eyeballing arithmetic - three separate
reviews of the V1.1 spec each found an address claim that was wrong when checked.

Words, not bytes: EEL2 memory is word-indexed.
"""

# name -> (base address, words per band).  Sized by N_BANDS.
STATIC = {
    "cf": (0, 8),      # static SVF coefficients
    "st": (64, 4),     # static SVF state
}

# Sized by N_DYN. bp lives here because only setup_band_dyn writes it and only Mode A/B read it.
DYNAMIC = {
    "det": (96, 4),
    "dst": (128, 4),
    "cst": (160, 4),
    "dp": (192, 4),
    "dm": (208, 1),
    "bp": (216, 3),
    "eg": (256, 2),
}

_ORDER = ["cf", "st", "det", "dst", "cst", "dp", "dm", "bp", "eg"]


def _per_band(name):
    return STATIC[name][1] if name in STATIC else DYNAMIC[name][1]


def _base(name):
    return STATIC[name][0] if name in STATIC else DYNAMIC[name][0]


def _count(name, n_bands, n_dyn):
    return n_bands if name in STATIC else n_dyn


def layout(n_bands, n_dyn):
    """name -> (first word, last word inclusive) at the given band counts."""
    out = {}
    for name in _ORDER:
        base = _base(name)
        span = _per_band(name) * _count(name, n_bands, n_dyn)
        out[name] = (base, base + span - 1)
    return out


def check_adjacency(n_bands, n_dyn):
    """Empty list when nothing overruns its successor. Reports every collision, not just the
    first, so a bad band count shows its full blast radius."""
    m = layout(n_bands, n_dyn)
    problems = []
    for a, b in zip(_ORDER, _ORDER[1:]):
        if m[a][1] >= _base(b):
            problems.append(
                f"{a} occupies {m[a][0]}..{m[a][1]} and overruns {b} at {_base(b)}")
    return problems


def shadow_layout(n_bands, n_dyn, guard=1):
    """The same arrays re-based with `guard` spare words between them.

    The production layout has zero slack at cf/st and st/det, so a sentinel written 'just past'
    cf would land inside st and be changed by ordinary audio. Bounds testing therefore runs
    against this instrumented copy instead.
    """
    out = {}
    p = 0
    for name in _ORDER:
        span = _per_band(name) * _count(name, n_bands, n_dyn)
        out[name] = (p, p + span - 1)
        p += span + guard
    return out
```

- [ ] **Step 3a: Extend the model through `lp_base` (review P1: the address manifest was a visual grep)**

The low arrays are fixed literals, so they prove nothing about the arrays that actually move.
Everything from `mb_peak` onward is derived by multiplying by the band count, and that chain ends
at `lp_base`, which is page-aligned and therefore hides small errors until it doesn't. Model the
whole chain so the gate can assert **word indices**, not text:

```python
MAX_LOOK = 2048
GC_N = 512
GC_LIN_N = 2048
GC_TRACE_WORDS = 2 * 5 * GC_N   # 5120: [2 buffers][5 domains][GC_N]

# name -> (previous name, words), sized by N_DYN unless noted. Mirrors V1.0 @init lines 157-685.
AUDIO_CHAIN = [
    ("mb_band",    None,        None),          # literal 1024
    ("mb_peak",    "mb_band",   lambda nb, nd: nd * 2 * MAX_LOOK),
    ("mb_end",     "mb_peak",   lambda nb, nd: nd * 2 * MAX_LOOK),
    ("mbenv",      "mb_end",    lambda nb, nd: 0),
    ("mbmode",     "mbenv",     lambda nb, nd: nd * 2),
    ("mbwpos",     "mbmode",    lambda nb, nd: nd),
    ("bus_dry",    "mbwpos",    lambda nb, nd: nd),
    ("mbgc",       "bus_dry",   lambda nb, nd: MAX_LOOK * 2),
    ("mbeh",       "mbgc",      lambda nb, nd: nd * 2),
    ("hc",         "mbeh",      lambda nb, nd: nd * 2),
    ("egh",        "hc",        lambda nb, nd: nd),
    ("hplp_state", "egh",       lambda nb, nd: nd * 2),
    ("hplp_cf",    "hplp_state", lambda nb, nd: 72),
    ("lp_rt",      "hplp_cf",   lambda nb, nd: 126),
    ("lp_kc",      "lp_rt",     lambda nb, nd: 16),
    ("lp_ks",      "lp_kc",     lambda nb, nd: 63),
]


def audio_layout(n_bands, n_dyn):
    """Every derived base address, in words. `n_bands` is deliberately unused by the audio
    chain - that is the property under test: growing the STATIC band count must not move a
    single audio address."""
    out = {"mb_band": 1024}
    for name, prev, size in AUDIO_CHAIN[1:]:
        out[name] = out[prev] + size(n_bands, n_dyn)
    return out


def gui_layout(gc_trace_base, n_bands):
    """The GUI block. gc_kc is the ONE address that legitimately grows with the band count.

    gc_lin sits between gc_trace and gc_snap and is 8192 words - four times gc_trace. Leaving it
    out was the first draft's mistake and it would have put every later address 8192 words low.
    """
    gc_lin = gc_trace_base + GC_TRACE_WORDS          # 5120
    gc_snap = gc_lin + 2 * 2 * GC_LIN_N              # 8192
    gc_meta = gc_snap + 128
    gc_kc = gc_meta + 16
    gc_fc = gc_kc + n_bands * 8
    gc_ebuf = gc_fc + 126
    gc_hits = gc_ebuf + 24
    lp_base = -(-(gc_hits + 8) // 65536) * 65536
    return {"gc_lin": gc_lin, "gc_snap": gc_snap, "gc_meta": gc_meta, "gc_kc": gc_kc,
            "gc_fc": gc_fc, "gc_ebuf": gc_ebuf, "gc_hits": gc_hits, "lp_base": lp_base,
            "clear_span": gc_hits + 8 - gc_trace_base}
```

Tests:

```python
def test_v11_audio_addresses_do_not_move_when_static_bands_grow():
    """The whole point of N_DYN. If this fails, the plugin has a different memory map than the
    spec describes - silently, with no error at load."""
    assert lay.audio_layout(4, 4) == lay.audio_layout(8, 4)


def test_v11_missing_one_dynamic_site_is_caught_as_a_16384_word_shift():
    """Reproduces the exact failure the 28-site audit exists to prevent: mb_peak still sized by
    the static count. The number is the review's own 16384."""
    wrong = lay.audio_layout(4, 4).copy()
    wrong["mb_peak"] = 1024 + 8 * 2 * lay.MAX_LOOK
    assert wrong["mb_peak"] - lay.audio_layout(4, 4)["mb_peak"] == 16384


def test_v11_gui_block_grows_only_gc_kc_and_lp_base_still_lands_on_a_page():
    four = lay.gui_layout(100000, 4)
    eight = lay.gui_layout(100000, 8)
    assert eight["gc_kc"] == four["gc_kc"]              # base unchanged
    assert eight["gc_fc"] - four["gc_fc"] == 32         # 4 more bands x 8 words
    assert eight["lp_base"] % 65536 == 0


def test_v11_gui_model_reproduces_the_shipped_clear_span():
    """V1.0's @init clears exactly 13638 words. The model must produce that number at four bands
    without gc_hits, or it is describing some other plugin - the same check that caught the
    missing gc_lin."""
    assert lay.gui_layout(0, 4)["clear_span"] - 8 == 13638
    assert lay.gui_layout(0, 8)["clear_span"] == 13678
```

- [ ] **Step 3b: Make the shadow layout actually detect overruns (review P1)**

`shadow_layout` as written only spaces arrays apart; a test that guards exist is not a bounds
test. Add an instrumented memory that fails when a modeled access crosses an array's end:

```python
class GuardedMemory:
    """Word-addressed memory with a guard word after every array. Writing or reading a guard
    raises. This is where B5-B8 accesses are proven in-bounds BEFORE any JSFX is written -
    the production layout has no spare word to hold a sentinel."""

    GUARD = object()

    def __init__(self, spans):
        self.spans = spans                       # name -> (first, last)
        self.guards = {last + 1 for _, last in spans.values()}
        self.cells = {}

    def _check(self, addr, what):
        if addr in self.guards:
            owner = next(n for n, (f, l) in self.spans.items() if l + 1 == addr)
            raise AssertionError(f"{what} at {addr} hit the guard word after {owner}")

    def write(self, addr, value):
        self._check(addr, "write")
        self.cells[addr] = value

    def read(self, addr):
        self._check(addr, "read")
        return self.cells.get(addr, 0.0)


def model_static_band(mem, spans, b):
    """What setup_band + the static sample loop touch for band b: 8 coefficient words and 4
    state words. Deliberately mirrors the JSFX indexing, cf[b*8+k] and st[b*4+k]."""
    for k in range(8):
        mem.write(spans["cf"][0] + b * 8 + k, 1.0)
    for k in range(4):
        mem.read(spans["st"][0] + b * 4 + k)
        mem.write(spans["st"][0] + b * 4 + k, 0.0)
```

```python
def test_v11_static_accesses_for_all_eight_bands_stay_in_bounds():
    spans = lay.shadow_layout(8, 4, guard=1)
    mem = lay.GuardedMemory(spans)
    for b in range(8):
        lay.model_static_band(mem, spans, b)        # must not raise


def test_v11_a_ninth_band_trips_the_guard():
    """Proves the instrument works. Without this, the previous test passes vacuously."""
    spans = lay.shadow_layout(8, 4, guard=1)
    mem = lay.GuardedMemory(spans)
    try:
        lay.model_static_band(mem, spans, 8)
    except AssertionError as e:
        assert "guard word after cf" in str(e), e
    else:
        raise AssertionError("a ninth band must trip the cf guard")


def test_v11_dynamic_access_by_a_static_band_trips_the_guard():
    """The V1.0 static loop read dp[b*4+3] and dm[b]. If bands 5-8 ever did that, this is what
    it would look like."""
    spans = lay.shadow_layout(8, 4, guard=1)
    mem = lay.GuardedMemory(spans)
    try:
        mem.read(spans["dm"][0] + 4)
    except AssertionError as e:
        assert "after dm" in str(e), e
    else:
        raise AssertionError("reading dm[4] with four dynamic bands must trip the guard")
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 233 passed (221 + 5 + 4 + 3).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_layout.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.1 memory map as data, with adjacency and overflow tests"
```

---

### Task 2: `band_slider_base`

**Files:**
- Modify: `tools/rcbitnova_curve.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces: `band_slider_base(b) -> int` — 10, 20, 30, 40 for bands 0–3; 150, 160, 170, 180 for bands 4–7.

- [ ] **Step 1: Write the failing tests**

```python
def test_v11_band_slider_base_keeps_the_old_bands_where_they_were():
    """Bands 1-4 must not move: REAPER stores parameters by number and any shift would corrupt
    every existing project."""
    assert [curve.band_slider_base(b) for b in range(4)] == [10, 20, 30, 40]


def test_v11_band_slider_base_puts_new_bands_above_150():
    assert [curve.band_slider_base(b) for b in range(4, 8)] == [150, 160, 170, 180]


def test_v11_band_sliders_never_collide_with_existing_ranges():
    """51-88 is dynamics, 91-123 is ceilings, 131-142 is filters and globals. A new band's nine
    sliders must not land in any of them."""
    taken = set(range(1, 5)) | set(range(51, 89)) | set(range(91, 124)) | set(range(131, 143))
    for b in range(8):
        base = curve.band_slider_base(b)
        for off in range(1, 10):
            n = base + off
            if b < 4:
                continue                      # existing bands are 11-49 by definition
            assert n not in taken, f"band {b} slider {n} collides"
            assert 151 <= n <= 189, n
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k band_slider_base`
Expected: FAIL — `AttributeError: module 'tools.rcbitnova_curve' has no attribute 'band_slider_base'`.

- [ ] **Step 3: Append to `tools/rcbitnova_curve.py`**

```python
def band_slider_base(b):
    """Slider base for band b. Bands 0-3 keep their V1.0 numbers; bands 4-7 live above 150.

    Reads use this. WRITES MUST NOT: V1.0 established live that assigning through
    slider(computed_index) updates what the GUI reads back but never reaches the parameter, so
    every writer needs an explicit named sliderNN branch.
    """
    return 10 * (b + 1) if b < 4 else 150 + 10 * (b - 4)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 236 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_curve.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.1 band_slider_base - old bands fixed, new bands above 150"
```

---

### Task 3: `JSFX/RCBitNova V1.1` — the dynamic sites, while it is still a four-band plugin

**Files:**
- Create: `JSFX/RCBitNova V1.1` (copy of `JSFX/RCBitNova V1.0`)

**`N_BANDS` stays 4 for this entire task.** Everything here is a no-op rewrite: same counts, same
addresses, same audio. That is what makes it safe to load and commit.

- [ ] **Step 1: Create the file**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
cp "JSFX/RCBitNova V1.0" "JSFX/RCBitNova V1.1"
```

Change `desc:` to read `V1.1` and append ` + 8 bands`.

- [ ] **Step 2: Declare the two constants — both 4 for now**

```eel2
N_BANDS = 4;   // static EQ bands. Becomes 8 in Task 6, and NOT before: every path that could
               // read or write past a four-band array must be bounded first.
N_DYN   = 4;   // bands with dynamics: Mode A, Mode B, ceilings, detectors.
               // Everything sized by N_DYN keeps its V1.0 address forever. Raising N_BANDS past
               // 8 is NOT safe: cf ends exactly at st (64) and st exactly at det (96).
```

- [ ] **Step 3: Convert the 17 dynamic sites in `@init`**

Per spec §3.2, replace `N_BANDS` with `N_DYN` on these lines — everything except `memset(st, …)`:

```eel2
memset(dst, 0, N_DYN * 4);
memset(cst, 0, N_DYN * 4);
i = 0; loop(N_DYN * 2, eg[i] = 1; i += 1;);
mb_peak = mb_band + N_DYN * 2 * MAX_LOOK;
mb_end  = mb_peak + N_DYN * 2 * MAX_LOOK;
mbmode = mbenv + N_DYN * 2;
mbwpos = mbmode + N_DYN;
bus_dry = mbwpos + N_DYN;
i = 0; loop(N_DYN * 2, mbenv[i] = 1; i += 1;);
memset(mbwpos, 0, N_DYN);
i = 0; loop(N_DYN * 2, mbgc[i] = 1; i += 1;);
mbeh = mbgc + N_DYN * 2;
hc   = mbeh + N_DYN * 2;
i = 0; loop(N_DYN * 2, mbeh[i] = 1; i += 1;);
egh = hc + N_DYN;
i = 0; loop(N_DYN * 2, egh[i] = 1; i += 1;);
hplp_state = egh + N_DYN * 2;
```

`memset(st, 0, N_BANDS * 4);` **keeps `N_BANDS`** — static state, and it must clear 32 words once
the count flips.

Because both constants are still 4, this step changes no address at all. That is the point: the
gate in Task 9 compares computed word indices, and at this commit they must be identical to V1.0's.

- [ ] **Step 4: Grow the GUI coefficient scratch and add the hit-set buffer (spec §2.1)**

`gc_kc` holds 8 words per band and `gc_fc` starts immediately after it, so at eight bands
`gc_kc + b*8` for B5–B8 would overwrite the GUI's HP/LP coefficients. Size it by `N_BANDS` so it
follows the flip automatically, and add the 8-word hit set that Task 6's node cycling needs:

```eel2
gc_kc    = gc_meta + 16;              // N_BANDS * 8 words: the GUI's OWN band coefficients
gc_fc    = gc_kc + N_BANDS * 8;       // 126 words: the GUI's OWN HP/LP coefficients (2 x 63)
gc_ebuf  = gc_fc + 126;               // 24 words: numeric-entry character buffer
gc_hits  = gc_ebuf + 24;              // 8 words: nodes under the cursor this frame (Task 6)
```

and the clear span grows from V1.0's 13638 by the same 32 + 8 words:

```eel2
memset(gc_trace, 0, 13678);
```

Take the number from the model, not by hand:

```bash
python3 -c "from tools import rcbitnova_layout as l; print(l.gui_layout(0, 8)['clear_span'])"
```

`lp_base` is computed from `gc_hits + 8`, so it recalculates itself. Task 9's gate asserts it still
lands on a 65536 boundary — the hi-res FFT corrupts **silently** if it does not.

- [ ] **Step 5: Declare the 36 new sliders at the END of the slider block**

After `slider142`, add four blocks (shown for B5; repeat with 16x/17x/18x and B6/B7/B8, and with
default frequencies 150 / 700 / 5000 / 15000):

```eel2
slider151:0<0,1,1{Off,On}>-B5 Enable
slider152:0<0,2,1{Bell,Low Shelf,High Shelf}>-B5 Type
slider153:150<20,20000,1>-B5 Freq
slider154:0.707<0.1,10,0.001>-B5 Q
slider155:0<-16,16,1>-B5 Macro (bits)
slider156:0<-100,100,0.1>-B5 Micro (% bit)
slider157:1<0,3,0.05>-B5 Bit Ratio
slider158:0<0,4,1{Both,Mid,Side,Left,Right}>-B5 Placement
slider159:0<0,1,0.001>-B5 Q Character (0 Constant .. 1 Proportional)
```

They must come **after** every existing declaration: the host numbers parameters densely in
declaration order (verified live 2026-08-19), so appending is what keeps V1.0's 95 declared
parameters an exact prefix of V1.1's 131.

- [ ] **Step 6: Live check — byte-identical behaviour**

Load `RCBitNova V1.1`. With both counts at 4 it is V1.0 with 36 inert parameters appended. Confirm
it loads, plays, and the graph draws. The real proof is Task 9's null test; this is the smoke test.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - N_DYN split and 36 new sliders, still four bands"
```

---

### Task 4: Convert every band-slider read site

**Files:**
- Modify: `JSFX/RCBitNova V1.1`

Still four bands, so this is again behaviour-preserving. The review found that the first draft
converted six sites and missed eight — all in `@gfx`, all of which execute for every band once the
GUI loops grow. Unconverted, B5–B8 would read sliders 51–89: bands 1–4's dynamics controls.

- [ ] **Step 1: Add the read helper next to `band_qeff`**

```eel2
// Band slider base. Bands 0-3 keep their V1.0 numbers; bands 4-7 live above 150.
// READS only - writes must use explicit named sliderNN branches (V1.0 proved live that assigning
// through slider(computed_index) updates what the GUI reads back but never reaches the parameter).
function band_slider_base(b) ( b < 4 ? 10 * (b + 1) : 150 + 10 * (b - 4); );
```

It must be defined **above** its first caller — EEL2 resolves functions in file order, and four
builds broke on exactly this in V1.0.

- [ ] **Step 2: Convert all sixteen sites**

The complete list, from `grep -n '10 \* (\|10\*(' "JSFX/RCBitNova V1.0"`:

| Section | V1.0 line | Site | Action |
|---|---|---|---|
| `@init` | 722 | `band_qeff` | convert |
| `@init` | 740 | `setup_band` | convert |
| `@init` | 764 | `gc_band_bits` | convert |
| `@init` | 835 | `gc_band_setup` | convert |
| `@init` | 844 | `setup_band_dyn` — `s` **and** `ds = 50 + 10 * b` | leave; mark `// N_DYN-bounded` |
| `@init` | 1020 | `gc_domain_bits` | convert |
| `@init` | 1033 | `gc_dom_used` | convert |
| `@gfx` | 1750 | node x from Freq | convert |
| `@gfx` | 1751 | node y from Macro/Micro/Ratio | convert |
| `@gfx` | 1758 | click-to-enable enable test | convert |
| `@gfx` | 1765 | drag-start capture `gc_s` | convert |
| `@gfx` | 1776 | active-drag read `gc_s` | convert |
| `@gfx` | 1819 | wheel-Q `gc_s` | convert |
| `@gfx` | 1829 | node draw `gc_s` | convert |
| `@gfx` | 1951 | selected-band readout `gc_s` | convert |
| `@sample` | 1291, 1295, 1331, 1398 | the dynamic band loop | leave; mark `// N_DYN-bounded` |
| `@sample` | 1490–1492 | Mode-B pass | leave; mark `// N_DYN-bounded` |
| `@slider` | 1106 | Mode-B scan | leave; mark `// N_DYN-bounded` |

The `50 + 10 * b` form in `setup_band_dyn` and the Mode-B pass is the **dynamics** slider block,
which by design never grows past four — hence the marker rather than a helper.

- [ ] **Step 3: Verify the conversion is complete**

```bash
grep -nE '10 ?\* ?\((b|gc_b|gc_hover|gc_drag|gc_sel) ?\+ ?1\)' "JSFX/RCBitNova V1.1" \
  | grep -v 'N_DYN-bounded' | grep -v 'function band_slider_base'
```

Expected: no output. Task 9 runs this as a gate so it cannot rot.

- [ ] **Step 4: Live check**

Load it. Drag every node, use the wheel, watch the readout — with four bands the helper returns
exactly the old numbers, so anything that misbehaves is a typo in the conversion, visible now
rather than after the flip.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - all sixteen band-slider sites go through band_slider_base"
```

---

### Task 5: Bound every dynamic path, add the static-only loop, make the writers eight-way

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (`@sample` ~1290 and ~1490; `@slider` ~1096 and ~1103; `gc_w_*`)

Still four bands. `loop(N_BANDS - N_DYN, …)` runs zero iterations, and the eight-way writers are
never called with `b >= 4`. Everything below is dormant machinery — which is why it can be loaded
and committed safely, and why the flip in Task 6 is one line.

- [ ] **Step 1: Bound the `@sample` band loop to `N_DYN`**

Change `loop(N_BANDS,` at the start of the band loop (~1290) to `loop(N_DYN,`. It keeps its domain
selection, Mode A, and every dynamic array read exactly as V1.0 has them.

- [ ] **Step 2: Add the static-only loop immediately after it, before the Mode-B block**

```eel2
  // ---- V1.1: bands 5-8, STATIC ONLY ----
  // A separate loop, not a guarded branch. V1.0's band loop reads dp[b*4+3] and dm[b] to decide
  // whether Placement Both means L/R or M/S - BEFORE any filtering - so simply raising the loop
  // bound would read past the four-band arrays. That is a READ overrun: no crash, no error, and
  // invisible to write canaries.
  //
  // Nothing here may mention dp, dm, mbmode, bp, det, dst, cst, eg, egh or hc. Placement Both
  // always means L/R, because there is no dynamics mode that could make it M/S.
  //
  // Position: after the dynamic bands, before Mode B - so Mode B sees these bands, which is what
  // makes this one EQ rather than two stages with a limiter between them.
  b = N_DYN;
  loop(N_BANDS - N_DYN,
    slider(band_slider_base(b) + 1) == 1 ? (
      base = b * 8; sb = b * 4;
      a1 = cf[base]; a2 = cf[base+1]; a3 = cf[base+2];
      m0 = cf[base+4]; m1 = cf[base+5]; m2 = cf[base+6];
      pl = slider(band_slider_base(b) + 8);
      pl == 0 || pl == 3 ? (
        chA = spl0; chB = spl1;
      ) : pl == 4 ? (
        chA = spl1; chB = spl0;
      ) : (
        mid = (spl0 + spl1) * 0.5; sid = (spl0 - spl1) * 0.5;
        pl == 1 ? ( chA = mid; chB = sid; ) : ( chA = sid; chB = mid; );
      );
      // channel A always filters; channel B filters only for Both
      v3 = chA - st[sb+1];
      v1 = a1 * st[sb] + a2 * v3;
      v2 = st[sb+1] + a2 * st[sb] + a3 * v3;
      st[sb] = 2*v1 - st[sb]; st[sb+1] = 2*v2 - st[sb+1];
      chA = m0*chA + m1*v1 + m2*v2;
      pl == 0 ? (
        v3 = chB - st[sb+3];
        v1 = a1 * st[sb+2] + a2 * v3;
        v2 = st[sb+3] + a2 * st[sb+2] + a3 * v3;
        st[sb+2] = 2*v1 - st[sb+2]; st[sb+3] = 2*v2 - st[sb+3];
        chB = m0*chB + m1*v1 + m2*v2;
      );
      pl == 0 || pl == 3 ? ( spl0 = chA; spl1 = chB; ) :
      pl == 4 ? ( spl0 = chB; spl1 = chA; ) :
      pl == 1 ? ( spl0 = chA + chB; spl1 = chA - chB; ) :
                ( spl0 = chB + chA; spl1 = chB - chA; );
    );
    b += 1;
  );
```

- [ ] **Step 3: Bound the Mode-B loop and the `@slider` scan to `N_DYN`**

Change `loop(N_BANDS,` inside the `any_b ?` block (~1490) to `loop(N_DYN,`, and the `@slider` loop
that reads `hc` and `mbmode` (~1106) likewise.

- [ ] **Step 4: Split the setup loop in `@slider`**

```eel2
b = 0; loop(N_BANDS, setup_band(b); b += 1;);
b = 0; loop(N_DYN,  setup_band_dyn(b); b += 1;);
```

`setup_band` and `band_qeff` read only sliders, so they are safe for all eight; `setup_band_dyn`
writes `det`, `dp`, `dm` and `bp`, which exist for four. **This is the site the rejected task order
would have broken first** — the `@slider` pass runs before a single sample does, so a flip-first
plugin corrupts memory at load, whether or not B5–B8 are enabled.

- [ ] **Step 5: Make every GUI writer eight-way and guard the dynamic rebuild**

For each of `gc_w_freq`, `gc_w_macro`, `gc_w_micro`, `gc_w_ratio`, `gc_w_q`, `gc_w_enable`,
replace the four-way branch with eight explicit named cases and guard the dynamic rebuild.
Shown for `gc_w_macro`; the others follow the same shape with their own offsets (Enable +1,
Freq +3, Q +4, Micro +6, Ratio +7):

```eel2
function gc_w_macro(b, v, qz) (
  qz ? v = gc_q_step(v, 1);
  b == 0 ? ( slider15  = v; slider_automate(slider15);  ) :
  b == 1 ? ( slider25  = v; slider_automate(slider25);  ) :
  b == 2 ? ( slider35  = v; slider_automate(slider35);  ) :
  b == 3 ? ( slider45  = v; slider_automate(slider45);  ) :
  b == 4 ? ( slider155 = v; slider_automate(slider155); ) :
  b == 5 ? ( slider165 = v; slider_automate(slider165); ) :
  b == 6 ? ( slider175 = v; slider_automate(slider175); ) :
           ( slider185 = v; slider_automate(slider185); );
  setup_band(b);
  b < N_DYN ? setup_band_dyn(b);      // for b >= 4 this would write past det/dp/dm/bp
);
```

V1.0's writers branch B1–B3 and fall through to B4, so without this every gesture on B5–B8 would
edit B4 — and the unconditional `setup_band_dyn` would corrupt memory from an ordinary drag.

- [ ] **Step 6: Verify no writer still falls through**

```bash
grep -A14 "^function gc_w_" "JSFX/RCBitNova V1.1" | grep -c "b == 6"
```

Expected: 6 — one per writer.

- [ ] **Step 7: Audit the new loop for dynamic identifiers**

```bash
awk '/V1.1: bands 5-8, STATIC ONLY/{f=1} f && /^  \);/{exit} f' "JSFX/RCBitNova V1.1" \
  | grep -nE "\b(dp|dm|mbmode|bp|det|dst|cst|eg|egh|hc)\b"
```

Expected: no output. Any hit is a read into the four-band arrays.

- [ ] **Step 8: Live check — still identical**

The static loop runs zero times and the writers never see `b >= 4`, so this build must still sound
and behave exactly like V1.0. If anything changed, a `N_DYN` bound was applied to the wrong loop.

- [ ] **Step 9: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - dynamic paths bounded, static-only loop and eight-way writers, dormant"
```

---

### Task 6: Flip the count

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (one line)

- [ ] **Step 1: Raise it**

```eel2
N_BANDS = 8;
```

- [ ] **Step 2: Check the map before loading**

```bash
python3 tools/rcbitnova_gates.py --source-only   # written in Task 9; run its sites+address checks
grep -c "N_DYN" "JSFX/RCBitNova V1.1"
```

If Task 9 is not written yet, run the two greps from Task 4 Step 3 and Task 5 Step 7 instead, and
re-run them under the gate later.

- [ ] **Step 3: Live check — the first genuinely eight-band load**

Enable B5 with a large boost: it must be audible and appear on the graph. Then set a B1 Mode-B
ceiling low enough that the B5 boost pushes it over — Mode B must react, proving the ordering of
§3.1. Watch for a REAPER memory error at load: that means a `N_DYN` site was missed in Task 3.

- [ ] **Step 4: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - eight static bands"
```

---

### Task 7: The band context menu, the selector strip, and node cycling

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (`@gfx`)

- [ ] **Step 1: Compute `gc_rclick` once, beside `gc_click`**

V1.0 computes it at line 1868, inside the HP/LP section, because that was its only consumer. With
a second consumer the edge must be detected once, before either menu, and routed to exactly one
owner — otherwise the band menu reads the previous frame's value.

Move the line up to sit directly under `gc_click` (~1744):

```eel2
gc_click  = (mouse_cap & 1) && !(gc_last_cap & 1);
gc_rclick = (mouse_cap & 2) && !(gc_last_cap & 2);   // ONE detection, two consumers below
```

and delete it from the HP/LP section, leaving that `gc_rclick && gc_fnode >= 0 ? (…)` test intact.
Routing rule: **the band menu owns the event when `gc_hover >= 0`; the HP/LP menu owns it
otherwise.** Guard the HP/LP consumer accordingly:

```eel2
gc_rclick && gc_hover < 0 && gc_fnode >= 0 ? (   // band nodes win: they are drawn on top
```

- [ ] **Step 2: Build the menu string properly**

`gfx_showmenu` takes ONE string. A ternary followed by adjacent string literals is not
concatenation in EEL2 — it is a syntax error. Assemble into a string buffer:

```eel2
gc_rclick && gc_hover >= 0 ? (
  slider(band_slider_base(gc_hover) + 1) == 1 ? strcpy(#gc_menu, "Disable band||")
                                              : strcpy(#gc_menu, "Enable band||");
  strcat(#gc_menu, "Bell|Low Shelf|High Shelf||");
  strcat(#gc_menu, ">Placement|Both|Mid|Side|Left|Right|<|");
  strcat(#gc_menu, ">Q Character|0.00 constant|0.25|0.50|0.75|1.00 proportional|<");
  gfx_x = mouse_x; gfx_y = mouse_y;
  gc_bm = gfx_showmenu(#gc_menu);
  gc_bm == 1 ? gc_w_enable(gc_hover, slider(band_slider_base(gc_hover) + 1) == 1 ? 0 : 1) :
  gc_bm >= 2 && gc_bm <= 4 ? gc_w_type(gc_hover, gc_bm - 2) :
  gc_bm >= 5 && gc_bm <= 9 ? gc_w_place(gc_hover, gc_bm - 5) :
  gc_bm >= 10 && gc_bm <= 14 ? gc_w_qchar(gc_hover, (gc_bm - 10) * 0.25);
);
```

**Load the plugin the moment this compiles.** A menu-string mistake is a compile error, and V1.0
lost four builds to problems found only at load.

- [ ] **Step 3: Add the three new writers**

`gc_w_type`, `gc_w_place` and `gc_w_qchar` follow exactly the shape of Task 5 Step 5 — eight
explicit named branches, `setup_band(b)`, then `b < N_DYN ? setup_band_dyn(b);`. Offsets are
Type +2, Placement +8, Q Character +9. Define them **above** the `@gfx` code that calls them.

```eel2
function gc_w_type(b, v) (
  b == 0 ? ( slider12  = v; slider_automate(slider12);  ) :
  b == 1 ? ( slider22  = v; slider_automate(slider22);  ) :
  b == 2 ? ( slider32  = v; slider_automate(slider32);  ) :
  b == 3 ? ( slider42  = v; slider_automate(slider42);  ) :
  b == 4 ? ( slider152 = v; slider_automate(slider152); ) :
  b == 5 ? ( slider162 = v; slider_automate(slider162); ) :
  b == 6 ? ( slider172 = v; slider_automate(slider172); ) :
           ( slider182 = v; slider_automate(slider182); );
  setup_band(b);
  b < N_DYN ? setup_band_dyn(b);
);
```

- [ ] **Step 4: Give Q Character its full resolution**

The slider declares `0..1` in `0.001` steps; five menu presets cannot reproduce an existing 0.333,
which would make the GUI unable to represent a value the engine happily plays. Add Q Character as
a **sixth numeric-entry field**, reusing V1.0's existing entry machinery (`gc_edit`, `gc_ebuf`,
`gc_elen`) exactly as Freq/Macro/Micro/Ratio/Q do, and commit typed values unquantised.

The menu presets stay as the fast path. With the field present, the nine-parameter reachability
claim is honest.

- [ ] **Step 5: Add the B1…B8 selector strip and the DYN/STATIC tag**

```eel2
// A deterministic way to reach any band regardless of node overlap, plus the capability tag.
gc_b = 0;
loop(N_BANDS,
  gc_bx = gc_px + gc_b * 34 * gc_sc;
  gc_bhot = (mouse_x >= gc_bx && mouse_x < gc_bx + 30 * gc_sc &&
             mouse_y >= gc_fy - 24 * gc_sc && mouse_y < gc_fy - 6 * gc_sc);
  gc_sel == gc_b ? gfx_set(0.3, 0.45, 0.6, 1) : gfx_set(0.16, 0.16, 0.18, 1);
  gc_bhot ? gfx_set(0.35, 0.5, 0.66, 1);
  gfx_rect(gc_bx, gc_fy - 24 * gc_sc, 30 * gc_sc, 18 * gc_sc);
  gfx_set(slider(band_slider_base(gc_b) + 1) == 1 ? 0.95 : 0.45, 0.9, 0.95, 1);
  gfx_x = gc_bx + 5 * gc_sc; gfx_y = gc_fy - 20 * gc_sc;
  gfx_drawstr("B"); gfx_drawnumber(gc_b + 1, 0);
  gc_click && gc_bhot ? gc_sel = gc_b;
  gc_b += 1;
);
gfx_set(0.6, 0.6, 0.65, 1);
gfx_x = gc_px + N_BANDS * 34 * gc_sc + 10 * gc_sc; gfx_y = gc_fy - 20 * gc_sc;
gfx_drawstr(gc_sel < N_DYN ? "DYN" : "STATIC");
```

- [ ] **Step 6: Coincident-node cycling — the complete algorithm**

The first draft only advanced a counter and left the selection to the implementer, so the counter
could exceed the hit-set size and select nothing. All of it, in order:

**6a.** In `@init`, next to the other GUI state (~line 696):

```eel2
gc_cyc_n = 0; gc_cyc_x = -1e9; gc_cyc_y = -1e9; gc_cyc_t = -1e9; gc_hit_n = 0;
```

**6b.** In the node loop that currently sets `gc_hover` (~1747–1752), collect the hit set instead
of keeping the last match. `gc_hits` is the 8-word buffer added in Task 3 Step 4:

```eel2
gc_hit_n = 0;
gc_b = 0;
loop(N_BANDS,
  gc_nx = gc_x_of_f(slider(band_slider_base(gc_b) + 3));
  gc_ny = gc_y_of_bits(...);                       // unchanged
  (abs(mouse_x - gc_nx) < gc_hit_r && abs(mouse_y - gc_ny) < gc_hit_r) ? (
    gc_hits[gc_hit_n] = gc_b; gc_hit_n += 1;       // disabled nodes included: they must be
  );                                               // reachable, that is how a band is enabled
  gc_b += 1;
);
```

**6c.** Immediately after that loop — and therefore **before** click-to-enable (~1758) and
drag-start (~1765), both of which consume `gc_hover`:

```eel2
// Repeated clicks in the same spot walk the stack. Movement, timeout, or a click elsewhere
// resets to the lowest band. This overrides selected-node priority: otherwise the selected node
// traps the cursor and everything under it stays unreachable.
gc_click ? (
  (abs(mouse_x - gc_cyc_x) < gc_hit_r && abs(mouse_y - gc_cyc_y) < gc_hit_r
   && (time_precise() - gc_cyc_t) < 0.4) ? ( gc_cyc_n += 1; ) : ( gc_cyc_n = 0; );
  gc_cyc_x = mouse_x; gc_cyc_y = mouse_y; gc_cyc_t = time_precise();
);
// Stale counter safety: the hit set can shrink between clicks (a node moved, a band was
// disabled). Modulo the CURRENT count, every frame, so the index can never point past the set.
gc_hit_n > 0 ? ( gc_hover = gc_hits[gc_cyc_n % gc_hit_n]; ) : ( gc_hover = -1; gc_cyc_n = 0; );
```

**6d.** Reset on movement without a click, as §5 requires — put this with the other end-of-frame
state updates, after `gc_last_cap` is stored:

```eel2
(abs(mouse_x - gc_cyc_x) >= gc_hit_r || abs(mouse_y - gc_cyc_y) >= gc_hit_r) ? gc_cyc_n = 0;
```

- [ ] **Step 7: Live check — the reachability matrix**

For each of B5…B8, set **all nine** parameters from the graph alone: Enable and Disable, Type (all
three), Freq, Q, Macro, Micro, Bit Ratio, Placement (all five), Q Character (a preset **and** a
typed 0.333). Confirm each in `Param` without opening the parameter list to change anything.

Then the cycling matrix, which is where this kind of code actually fails:

| Case | Expected |
|---|---|
| One node under the cursor | every click selects it; counter stays 0 |
| Two coincident, both enabled | clicks alternate |
| Three coincident | clicks walk 1 → 2 → 3 → 1 |
| Three coincident, middle disabled | still reachable, and one click enables it |
| Click, wait 1 s, click again | back to the lowest band |
| Click, move away, return, click | back to the lowest band |
| Coincident nodes, then drag | the drag moves the band the last click selected |

- [ ] **Step 8: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - band context menu, selector strip, node cycling"
```

---

### Task 8: The migration script

**Files:**
- Create: `tools/migrate_v10_to_v11.py`

Before the gates, because Task 9's null test uses it to put both instances in the same state.

**Measured facts this task is built on (reapy, live V1.0, 2026-08-19):** the host reports **98**
parameters — 95 declared sliders at 0–94, then `Bypass`, `Wet`, `Delta`. V1.1 will report 134.
The declared block is a prefix; **the full list is not**. Copying by index across the whole list
would write V1.0's Bypass/Wet/Delta into V1.1's B5 Enable/Type/Freq.

- [ ] **Step 1: Write it**

```python
"""Replace a V1.0 instance with a V1.1 instance in place, preserving its settings.

The only supported migration. V1.1 is a new file, so an existing project simply reopens V1.0 and
is unaffected - this is for moving a project forward deliberately.

Two things the first draft got wrong, both measured rather than reasoned:

1. The host list is 95 declared parameters THEN Bypass/Wet/Delta. Copying by index across the
   whole list lands the host tail in the new bands. Declared parameters are copied by index and
   stop at 95; host parameters are matched by name.
2. add_fx appends. If V1.0 was not last in the chain, an index-preserving move is required or the
   FX order - and therefore the sound - changes even when every value is right.

Automation is out of scope: an instance with envelopes is refused, not silently flattened.
"""

import reapy
from reapy import reascript_api as RPR

N_DECLARED_V10 = 95
HOST_TAIL = ("Bypass", "Wet", "Delta")


def _params(fx):
    return [fx.params[i].name for i in range(fx.n_params)]


def _by_name(fx, name):
    for i in range(fx.n_params):
        if fx.params[i].name == name:
            return i
    return None


def migrate(track_index=0, dry_run=True):
    with reapy.inside_reaper():
        pr = reapy.Project()
        tr = pr.tracks[track_index]

        src = next((fx for fx in tr.fxs if "RCBitNova V1.0" in fx.name), None)
        if src is None:
            return "no V1.0 instance on this track"
        src_idx = src.index

        names = _params(src)
        if len(names) < N_DECLARED_V10:
            return f"REFUSED: V1.0 reports {len(names)} parameters, expected at least 95"
        if names[N_DECLARED_V10:N_DECLARED_V10 + 3] != list(HOST_TAIL):
            return (f"REFUSED: unexpected host tail {names[N_DECLARED_V10:]!r}; this REAPER build "
                    "exposes a different special-parameter set - migrate by hand")

        if any(src.params[i].envelope is not None for i in range(src.n_params)):
            return "REFUSED: this instance has automation; migrate it by hand"

        declared = [src.params[i].normalized for i in range(N_DECLARED_V10)]
        host = {n: src.params[_by_name(src, n)].normalized for n in HOST_TAIL}
        enabled = RPR.TrackFX_GetEnabled(tr.id, src_idx)
        offline = RPR.TrackFX_GetOffline(tr.id, src_idx)

        if dry_run:
            return (f"would copy {len(declared)} declared + {len(host)} host parameters "
                    f"into chain position {src_idx}")

        RPR.Undo_BeginBlock2(pr.id)
        dst = tr.add_fx("JS: RCBitNova V1.1")
        dst_idx = dst.index
        try:
            for i, v in enumerate(declared):
                dst.params[i].normalized = v
            for n, v in host.items():
                j = _by_name(dst, n)
                if j is None:
                    raise RuntimeError(f"V1.1 has no host parameter {n!r}")
                dst.params[j].normalized = v

            # Read back BEFORE destroying the only known-good instance.
            for i, v in enumerate(declared):
                if dst.params[i].normalized != v:
                    raise RuntimeError(f"parameter {i} ({dst.params[i].name}) did not take: "
                                       f"wrote {v}, read {dst.params[i].normalized}")
            for n, v in host.items():
                if dst.params[_by_name(dst, n)].normalized != v:
                    raise RuntimeError(f"host parameter {n} did not take")

            RPR.TrackFX_SetEnabled(tr.id, dst_idx, enabled)
            RPR.TrackFX_SetOffline(tr.id, dst_idx, offline)

            # Move into the source's chain position, then remove the source (whose index has
            # shifted by the insertion - find it by name rather than by the old number).
            RPR.TrackFX_CopyToTrack(tr.id, dst_idx, tr.id, src_idx, True)
            stale = next((fx for fx in tr.fxs if "RCBitNova V1.0" in fx.name), None)
            stale.delete()
        except Exception as exc:                      # noqa: BLE001 - any failure must roll back
            doomed = next((fx for fx in tr.fxs if "RCBitNova V1.1" in fx.name), None)
            if doomed is not None:
                doomed.delete()
            RPR.Undo_EndBlock2(pr.id, "RCBitNova migration (failed, rolled back)", -1)
            return f"REFUSED, source untouched: {exc}"

        RPR.Undo_EndBlock2(pr.id, "RCBitNova V1.0 -> V1.1", -1)
        return f"migrated {len(declared)} declared + {len(host)} host parameters"


if __name__ == "__main__":
    print(migrate(dry_run=True))
```

**Out of scope, stated rather than silently dropped:** parameter modulation, pin mappings,
parameter aliases, per-FX oversampling metadata. If the source has any of them, migrate by hand.
Add them to the refusal list if REAPER exposes a way to detect them.

- [ ] **Step 2: Dry-run on a project with a configured V1.0 instance, NOT last in the chain**

Run: `python3 tools/migrate_v10_to_v11.py`
Expected: `would copy 95 declared + 3 host parameters into chain position N`, with N the real slot.

- [ ] **Step 3: Run it for real; verify values, defaults, position and chain**

Confirm: every one of the 95 values matches; the 36 new parameters sit at their declared defaults;
the FX occupies the **same chain position**; Bypass/Wet/Delta carried over; exactly one RCBitNova
remains. Then undo once — REAPER must restore V1.0 in its original slot in a single step.

- [ ] **Step 4: Failure path**

Force a failure (rename `RCBitNova V1.1` temporarily so `add_fx` yields nothing usable) and confirm
the script reports a refusal, leaves the V1.0 instance untouched, and leaves no orphan V1.1.

- [ ] **Step 5: Commit**

```bash
git add tools/migrate_v10_to_v11.py
git commit -m "feat(rcbitnova): V1.1 migration - declared by index, host tail by name, transactional"
```

---

### Task 9: The gates, as executable checks

**Files:**
- Create: `tools/rcbitnova_gates.py`, `tools/rcbitnova_nulltest.py`, `tools/rcbitnova_cpu.py`

The first draft asked a human to eyeball grep output and decide two address lists were equivalent.
A typo that still looks plausible passes that. Every gate below exits nonzero on failure.

- [ ] **Step 1: `tools/rcbitnova_gates.py` — source-level gates**

Three checks, `--source-only` runs all of them without REAPER:

**(a) The 28-site table, encoded.** Not `grep -c`, which counts comment lines and collapses two
sites on one line. One assertion per site: the regex that must match, and which count it must
carry.

```python
SITES = [
    # (regex that identifies the line, required token)
    (r"^memset\(st, 0, (\w+) \* 4\);",            "N_BANDS"),
    (r"^memset\(dst, 0, (\w+) \* 4\);",           "N_DYN"),
    (r"^mb_peak = mb_band \+ (\w+) \* 2 \* MAX_LOOK;", "N_DYN"),
    (r"^mb_end  = mb_peak \+ (\w+) \* 2 \* MAX_LOOK;", "N_DYN"),
    # ... all 28, from spec section 3.2
]
```

Fail loudly when a site's line is **missing** as well as when it carries the wrong token — a
renamed or deleted line must not pass by vacuous absence.

**(b) The address manifest, computed.** Parse both files' `@init`, evaluate the arithmetic with
each file's own constants, and compare **word indices** against `rcbitnova_layout`:

```python
v10 = eval_init("JSFX/RCBitNova V1.0")
v11 = eval_init("JSFX/RCBitNova V1.1")
model = layout.audio_layout(8, 4)
for name in model:
    assert v11[name] == v10[name] == model[name], (name, v10[name], v11[name], model[name])
assert v11["lp_base"] % 65536 == 0
assert v11["gc_fc"] - v10["gc_fc"] == 32
```

The grep from the first draft stays, as diagnostic output printed alongside — not as the gate.

**(c) No open-coded band-slider arithmetic.** The Task 4 Step 3 grep, encoded, with the
`// N_DYN-bounded` markers as the only exemption.

- [ ] **Step 2: `tools/rcbitnova_nulltest.py` — §6.4, machine-checked**

Renders and compares, exits nonzero on any mismatch. Fixture: 48 kHz, block 512, 30 s of
deterministic material, GUI closed, fresh instances, bands 5–8 disabled, state transferred with
`migrate_v10_to_v11.py` rather than by hand. Cases: defaults; four bands in Mode A; four bands in
Mode B; Min and Linear topologies.

Compare **sample for sample at zero tolerance**, after asserting equal length and equal reported
latency — a PDC difference would otherwise show up as a shifted-but-identical render and could be
mistaken for a pass. Print the first differing sample index and both values on failure.

- [ ] **Step 3: `tools/rcbitnova_cpu.py` — §6.5, machine-checked**

Two comparisons, reported separately: V1.1 with B5–B8 disabled against V1.0 (**regression, must be
within +5 %**) and V1.1 eight enabled against V1.1 four enabled (**feature cost, informational**).
Blocks 128 and 512, five 60-second runs each, first discarded, median peak block time.
**Any xrun fails the gate**, regardless of timing.

- [ ] **Step 4: `--live` — the parameter manifest**

Not names only: for all 131 declared parameters record index, name, min, max, step, default, and a
set/get round trip at three representative values, then assert

```python
assert v11_declared[:95] == v10_declared          # full records, not just names
assert len(v11_declared) == 131
assert v11_host == v10_host == ["Bypass", "Wet", "Delta"]
```

The 95-record prefix is the compatibility contract; the host tail is checked separately, by name,
because it moves.

- [ ] **Step 5: Run everything**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q      # expect 236 passed
python3 tools/rcbitnova_gates.py --source-only && echo SOURCE_GATES_OK
python3 tools/rcbitnova_gates.py --live && echo PARAM_MANIFEST_OK
python3 tools/rcbitnova_nulltest.py && echo NULL_OK
python3 tools/rcbitnova_cpu.py && echo CPU_OK
```

Read the output of each. A gate that was not run is a gate that failed.

- [ ] **Step 6: Commit**

```bash
git add tools/rcbitnova_gates.py tools/rcbitnova_nulltest.py tools/rcbitnova_cpu.py
git commit -m "test(rcbitnova): V1.1 release gates as executable checks"
```

---

### Task 10: Fable review, as-shipped, tag

- [ ] **Step 1: Fable final review**

Dispatch with `model: fable` over `JSFX/RCBitNova V1.1`, the diff against V1.0, and spec rev 4.
Ask specifically for: bit-accuracy verdict; whether any `N_DYN` site was missed; whether the
static-only loop truly touches no dynamic array; whether the eight-way writers are complete and the
`setup_band_dyn` guard is present in all of them; whether any band-slider read still bypasses
`band_slider_base`; and EEL2 function-order traps.

- [ ] **Step 2: Address every P0/P1, then re-run Task 9**

- [ ] **Step 3: Append "As-shipped" to the spec**

Record every live measurement, every deviation and why, every defect found live and how. Follow
V1.0 §16 as the model.

- [ ] **Step 4: Update the memory file and tag**

```bash
git add -A
git commit -m "docs(rcbitnova): V1.1 as-shipped"
git tag rcbitnova-v1.1
git push origin rcbitnova --tags
git ls-remote --tags origin | grep rcbitnova-v1.1
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 memory, zero-slack boundaries | 1 (model + guarded memory), 3 (constants), 9 (computed manifest) |
| §2.1 `gc_kc` growth | 3 Step 4 |
| §3 two counts | 3, 6 |
| §3.1 signal order, structural split | 5 |
| §3.2 the 28 sites | 3 (17 dynamic), 5 (2 split + `@slider`), 9 (encoded as a gate) |
| §4 sliders, `band_slider_base`, named writes | 2, 3, 4, 5 |
| §5 GUI: menu, selector, DYN/STATIC, cycling | 7 |
| §6.1–6.3 oracle, bounds, addresses | 1, 9 |
| §6.4 null test | 9 |
| §6.5 CPU | 9 |
| §6.6 migration | 8 |
| §6.7 live, reachability matrix | 6, 7 |

**Ordering property:** at the end of every task before 6, the plugin is functionally V1.0 —
`N_BANDS` is 4, the static-only loop runs zero times, the eight-way writers are never called
with `b >= 4`. So every commit is loadable and every live check before the flip is a real check
that the rewrite changed nothing. The flip itself is one line against fully bounded code.

**Dependency check:** no task uses an artifact from a later one. Migration (8) precedes the gates
(9) that call it; `rcbitnova_layout` (1) precedes the gate that imports it (9); `band_slider_base`
(2, 4) precedes the static-only loop that calls it (5); `gc_hits` (3) precedes the cycling that
indexes it (7).

**Placeholder scan:** every code step carries real code. The cycling algorithm is complete —
initialization, hit set, modulo, placement relative to enable and drag, and both resets.

---

## Rev-2 Disposition (plan weakness review)

| Finding | Disposition |
|---|---|
| **P0** Task 3 creates and live-loads a knowingly invalid intermediate plugin | **Accepted, restructured.** Verified: `@slider` runs `setup_band_dyn` over `N_BANDS` before any audio, so a flip-first build corrupts `det`/`dp`/`dm`/`bp` at load, disabled bands notwithstanding. `N_BANDS` now stays 4 through Tasks 3–5 and flips in Task 6, after every dynamic path is bounded. |
| **P0** Slider-base transcription omits the interactive B5–B8 read sites | **Accepted.** Enumerated all sixteen sites by grep (eight in `@gfx`, exactly as claimed) in a Task 4 table, plus a gate that rejects open-coded forms outside `band_slider_base` except lines marked `// N_DYN-bounded`. |
| **P0** Task 7 depends on a migration script Task 8 has not created | **Accepted.** Migration is now Task 8, gates Task 9. Dependency check added to the self-review. |
| **P0** `range(src.n_params)` corrupts the new-band defaults | **Accepted, and measured.** Live reapy: V1.0 reports **98** parameters — 95 declared then `Bypass`, `Wet`, `Delta` (the plan said 97 and named two). Migration now copies 0–94 by index and the tail by name; the manifest gate compares `v11[:95] == v10` and checks the tail separately. |
| **P0** Migration changes FX-chain topology and is not transactional | **Accepted.** Records the source index, verifies every written value by read-back **before** deleting anything, carries enabled/offline, moves the destination into the source slot with `TrackFX_CopyToTrack(..., is_move=True)`, wraps it in one undo block, and on any failure deletes the destination and leaves the source untouched. Modulation, pin mappings, aliases and oversampling are declared out of scope rather than silently dropped. |
| **P1** Menu string and event-order dependencies | **Accepted.** `strcpy`/`strcat` into `#gc_menu`; `gc_rclick` computed once beside `gc_click`; band nodes own the event when `gc_hover >= 0`, HP/LP otherwise; load immediately after it compiles. |
| **P1** Coincident-node cycling is an unfinished algorithm | **Accepted.** Complete: `@init` state, hit set into `gc_hits` (disabled nodes included), `gc_cyc_n % gc_hit_n` re-evaluated every frame so a shrinking set cannot leave a stale index, placed before enable and drag, movement and timeout resets, plus a seven-case live matrix. |
| **P1** Q Character menu loses the declared resolution | **Accepted.** Sixth numeric-entry field reusing the existing entry machinery; presets remain the fast path. |
| **P1** The shadow layout never performs bounds testing | **Accepted.** `GuardedMemory` raises on any read or write of a guard word, `model_static_band` drives modeled accesses through it, and two negative tests (a ninth band, and a static band touching `dm`) prove the instrument is not vacuous. |
| **P1** `grep -c "N_BANDS"` is brittle and its expectation is wrong | **Accepted.** Replaced by the encoded 28-site table with per-site assertions, including failure on a missing line. |
| **P1** The audio-address manifest is a visual grep | **Accepted.** The model now runs through `lp_base`; the gate evaluates both files' `@init` arithmetic and compares word indices. The grep stays as diagnostics. |
| **P1** The parameter manifest tests names only | **Accepted.** Index, name, min, max, step, default and a three-value round trip for all 131 declared parameters. |
| **P1** Null and CPU gates have no executable tooling | **Accepted.** `tools/rcbitnova_nulltest.py` and `tools/rcbitnova_cpu.py`, both exiting nonzero, with the null test asserting equal length and reported latency before comparing samples. |
