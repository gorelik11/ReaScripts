# RCBitNova V1.1 — Eight Bands Implementation Plan

**Revision 5** — after three plan weakness reviews, plus a live API pass
(rev 1: five P0s; rev 2: two P0s; rev 3: five P0s). Dispositions are at the end of this file.
Rev 2 moved the `N_BANDS` flip to the end; rev 3 put the **source gate before it**; rev 4 makes that
gate actually run — one contract verified against an in-memory eight-band **projection**, a site
manifest derived from the spec rather than counted to 28, and a `ceil` that ceils. Rev 5 replaces
every unverified API assumption in Tasks 9 and 10 with a measurement (see the table in the
self-review) — one of which invalidated rev 4's identity design outright.

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
- **`N_BANDS` stays 4 until Task 7**, and the source gate runs before the flip. Every dynamic site is converted to `N_DYN`, and all the
  eight-band machinery is added, while the plugin is still a four-band plugin. The count flip is
  one line in its own task, after every path that could read or write past a four-band array is
  already bounded. The rejected order — flip first, bound later — produces a plugin whose
  `@slider` pass writes `det`/`dp`/`dm`/`bp` out of range on the very first load, and commits it.
- **No open-coded band-slider arithmetic outside `band_slider_base`**, except inside loops proven
  to be `N_DYN`-bounded, where the line must carry the marker comment `// N_DYN-bounded`. The gate
  in Task 6 enforces exactly this. V1.0 open-codes `10 * (b + 1)` in **eight `@gfx` sites** — hit
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
| `tools/migrate_v10_to_v11.py` | NEW. The one supported migration: copies the 95 declared parameters by index and the host tail **by position**, in place and transactionally by GUID, refusing automation, modulation and ambiguous chains. | Create (Task 9) |
| `tools/rcbitnova_gates.py` | NEW. `--source-only`: the complete 28-site table, `eval_init`, and every address computed through `lp_base`; self-tested against seeded defects. `--live`: parameter and writer manifests. Exits nonzero on failure. | Create (Task 6), extended (Task 10) |
| `tools/rcbitnova_nulltest.py` | NEW. Renders the V1.0/V1.1 null cases and compares sample for sample at zero tolerance, after asserting equal reported latency. Exits nonzero on any mismatch. | Create (Task 10) |
| `tools/rcbitnova_cpu.py` | NEW. Median peak block time and xrun count over the prescribed runs; exits nonzero on regression or any xrun. | Create (Task 10) |

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


def test_v11_shadow_layout_spaces_arrays_apart():
    """Only claims spacing. Bounds detection is GuardedMemory's job, tested below."""
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

    A SPACING MODEL, not a bounds test - it answers "how much room would this layout need with
    slack", which is useful when considering a future layout, and nothing more. Out-of-bounds
    detection is `GuardedMemory`, which is ownership-aware and runs against the production spans.
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
    ("lp_geo",     "lp_ks",     lambda nb, nd: 18),
    ("lp_off",     "lp_geo",    lambda nb, nd: 8),
    ("lp_fs",      "lp_off",    lambda nb, nd: 32),
    ("gc_trace",   "lp_fs",     lambda nb, nd: 8),
]


def audio_layout(n_bands, n_dyn):
    """Every derived base address, in words, from mb_band through gc_trace - the bridge into the
    GUI block. `n_bands` is deliberately unused by the audio chain: that is the property under
    test, growing the STATIC band count must not move a single audio address.

    Stopping this chain early was the rev-2 defect. A model that ends at lp_ks cannot say anything
    about lp_geo/lp_off/lp_fs, and `lp_base % 65536 == 0` is satisfied by a wrong address just as
    happily as by the right one.
    """
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


def test_v11_gui_block_grows_only_gc_kc_and_lp_base_is_exactly_65536():
    """`% 65536 == 0` is not a test: a wrong address can be page-aligned too. Pin the value."""
    base = lay.audio_layout(8, 4)["gc_trace"]
    four, eight = lay.gui_layout(base, 4), lay.gui_layout(base, 8)
    assert eight["gc_kc"] == four["gc_kc"]              # base unchanged
    assert eight["gc_fc"] - four["gc_fc"] == 32         # 4 more bands x 8 words
    assert eight["lp_base"] == 65536 == four["lp_base"]


def test_v11_gui_region_is_ordered_non_overlapping_and_ends_below_lp_base():
    """The GUI block is read by @gfx on another thread while lp_relayout memsets everything from
    lp_base up. Crossing that line is not a wrong number, it is a thread-safety failure."""
    base = lay.audio_layout(8, 4)["gc_trace"]
    g = lay.gui_layout(base, 8)
    order = ["gc_lin", "gc_snap", "gc_meta", "gc_kc", "gc_fc", "gc_ebuf", "gc_hits"]
    addrs = [g[n] for n in order]
    assert addrs == sorted(addrs), addrs
    assert g["clear_span"] == g["gc_hits"] + 8 - base
    assert g["gc_hits"] + 8 <= g["lp_base"], "the GUI region must end below lp_base"


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
    """Ownership-aware word memory: every access names the array it believes it is touching, and
    any offset outside that array's span raises.

    A guard-word-only design (rev 2's) catches an overrun of exactly one word and lets an access
    that jumps further land silently in the next array - which is precisely the failure mode being
    modelled, since `cf` and `st` are adjacent with zero slack. Naming the owner makes the check
    total instead of probabilistic.
    """

    def __init__(self, spans):
        self.spans = spans                       # name -> (first, last inclusive)
        self.cells = {}

    def _addr(self, name, offset, what):
        first, last = self.spans[name]
        if offset < 0 or first + offset > last:
            raise AssertionError(
                f"{what} {name}[{offset}] leaves its span {first}..{last} "
                f"(next array begins at {min((f for f, _ in self.spans.values() if f > last), default='end')})")
        return first + offset

    def write(self, name, offset, value):
        self.cells[self._addr(name, offset, "write")] = value

    def read(self, name, offset):
        return self.cells.get(self._addr(name, offset, "read"), 0.0)


def model_static_band(mem, b):
    """What setup_band plus the static sample loop touch for band b: 8 coefficient words and 4
    state words, indexed exactly as the JSFX does - cf[b*8+k], st[b*4+k]."""
    for k in range(8):
        mem.write("cf", b * 8 + k, 1.0)
    for k in range(4):
        mem.read("st", b * 4 + k)
        mem.write("st", b * 4 + k, 0.0)


```

```python
def test_v11_static_accesses_for_all_eight_bands_stay_in_bounds():
    """Run against the PRODUCTION spans, not a padded copy - ownership checking needs no slack."""
    mem = lay.GuardedMemory(lay.layout(8, 4))
    for b in range(8):
        lay.model_static_band(mem, b)               # must not raise


def test_v11_a_ninth_band_leaves_cf():
    """Proves the instrument works. Without it, the test above passes vacuously."""
    mem = lay.GuardedMemory(lay.layout(8, 4))
    try:
        lay.model_static_band(mem, 8)
    except AssertionError as e:
        assert "cf[64] leaves its span 0..63" in str(e), e
    else:
        raise AssertionError("a ninth band must leave cf")


def test_v11_an_overrun_that_jumps_clear_of_a_guard_word_is_still_caught():
    """The rev-2 design only failed on the single word after an array, so an access landing two
    or more words in - the realistic case for cf, which is indexed b*8 - went undetected."""
    mem = lay.GuardedMemory(lay.layout(8, 4))
    for bad in (64, 65, 71, 95):
        try:
            mem.write("cf", bad, 1.0)
        except AssertionError:
            continue
        raise AssertionError(f"cf[{bad}] must be rejected")


def test_v11_dynamic_access_by_a_static_band_is_caught():
    """The V1.0 static loop read dp[b*4+3] and dm[b]. If bands 5-8 ever did that, this is it."""
    mem = lay.GuardedMemory(lay.layout(8, 4))
    for name, offset in (("dm", 4), ("dp", 16), ("det", 16), ("bp", 12)):
        try:
            mem.read(name, offset)
        except AssertionError:
            continue
        raise AssertionError(f"{name}[{offset}] must be rejected with four dynamic bands")
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 235 passed (221 + 5 + 5 + 4).

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
Expected: 238 passed.

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
N_BANDS = 4;   // static EQ bands. Becomes 8 in Task 7, and NOT before: every path that could
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
gate in Task 6 compares computed word indices, and at this commit they must be identical to V1.0's.

- [ ] **Step 4: Grow the GUI coefficient scratch and add the hit-set buffer (spec §2.1)**

`gc_kc` holds 8 words per band and `gc_fc` starts immediately after it, so at eight bands
`gc_kc + b*8` for B5–B8 would overwrite the GUI's HP/LP coefficients. Size it by `N_BANDS` so it
follows the flip automatically, and add the 8-word hit set that Task 8's node cycling needs:

```eel2
gc_kc    = gc_meta + 16;              // N_BANDS * 8 words: the GUI's OWN band coefficients
gc_fc    = gc_kc + N_BANDS * 8;       // 126 words: the GUI's OWN HP/LP coefficients (2 x 63)
gc_ebuf  = gc_fc + 126;               // 24 words: numeric-entry character buffer
gc_hits  = gc_ebuf + 24;              // 8 words: nodes under the cursor this frame (Task 8)
```

and the clear span stops being a hand-typed number. Every one of those bases is already assigned
by the time the clear runs, so **derive it**:

```eel2
memset(gc_trace, 0, gc_hits + 8 - gc_trace);
```

V1.0 hard-coded 13638, and rev 1 of this plan typed 13670 — which was the spec's number and is now
wrong, because `gc_hits` did not exist when the spec was written. A derived span is correct at four
bands (13646), correct at eight (13678), and correct at whatever the flip in Task 7 makes it. Nothing
to keep in sync, and the intermediate build stays a genuine no-op.

Cross-check the two endpoints against the model:

```bash
python3 -c "from tools import rcbitnova_layout as l; print(l.gui_layout(0,4)['clear_span'], l.gui_layout(0,8)['clear_span'])"
```

Expected: `13646 13678`.

**Spec follow-up (review P1-1):** §2.1 and §6.1 pin the span to 13670 and know nothing of `gc_hits`.
Update the spec to rev 5 before Task 11 signs anything off — the plan and the spec cannot both be
the acceptance contract.

`lp_base` is computed from `gc_hits + 8`, so it recalculates itself. Task 6's gate asserts it still
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
it loads, plays, and the graph draws. The real proof is Task 10's null test; this is the smoke test.

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

Expected: no output. Task 6 runs this as a gate so it cannot rot.

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
and committed safely, and why the flip in Task 7 is one line.

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

### Task 6: The source gate — before anything flips

**Files:**
- Create: `tools/rcbitnova_gates.py`

The rejected order had this after the flip and left the flip covered by two greps alone. Those greps
check open-coded slider arithmetic and forbidden identifiers in the new loop; neither verifies one of
the 17 `@init` conversions, and neither computes an address. The failure this gate exists to catch is
**silent**: a plugin that loads, plays, and has a different memory map than the spec describes.

Everything here is source-level — no REAPER, no rendering. The live gates stay in Task 10.

**One contract, two phases (review P0-1).** Rev 3 asked this gate to run before the flip and then
excused its first assertion for failing, which makes the identical command in Task 7 prove nothing.
Instead the pre-flip run works on a **projection**: read the source, substitute `N_BANDS = 4` with
`N_BANDS = 8` in memory, and run the *full post-flip contract* against that text. Nothing is excused,
and Task 7 re-runs literally the same assertions against the real file.

```python
def check_source(path, project=False):
    text = open(path, encoding="utf-8", errors="replace").read()
    if project:
        text, n = re.subn(r"^N_BANDS\s*=\s*4;", "N_BANDS = 8;", text, count=1, flags=re.M)
        assert n == 1, f"{path}: no `N_BANDS = 4;` to project from"
    check_sites(text, path)
    check_forbidden(text, path)
    check_addresses(text, path)
```

- [ ] **Step 1: `eval_init` — evaluate the `@init` arithmetic instead of eyeballing it**

The addresses are a chain of `name = expr;` lines over integer literals, the counts, and previously
defined names — enough grammar to evaluate with `ast`.

```python
import ast, math, re

ASSIGN = re.compile(r"^\s*(\w+)\s*=\s*([^;]+);")


def eval_init(text, wanted):
    """name -> word address, evaluated from the text's own @init. Only +, -, *, /, ceil() and
    already-known names are allowed; anything else is skipped, and a `wanted` name that never
    evaluates raises rather than defaulting to something plausible."""
    env, out = {}, {}
    for line in text.splitlines():
        line = line.split("//")[0]
        m = ASSIGN.match(line)
        if not m:
            continue
        name, expr = m.group(1), re.sub(r"\bceil\(", "_ceil(", m.group(2).strip())
        try:
            value = eval(compile(ast.parse(expr, mode="eval"), "<init>", "eval"),
                         {"_ceil": math.ceil, "__builtins__": {}}, dict(env))
        except Exception:
            continue
        if isinstance(value, (int, float)):
            env[name] = value
            if name in wanted:
                out[name] = int(value)
    missing = set(wanted) - set(out)
    if missing:
        raise AssertionError(f"could not evaluate {sorted(missing)}")
    return out
```

**`math.ceil`, not a hand-rolled one (review P0-2).** Rev 3 wrote `-(-int(x) // 1)`, which truncates
to `int` *before* ceiling: `ceil(51913 / 65536)` came out 0 instead of 1, so the gate evaluated
`lp_base` as 0 and would have failed its own exact-address assertion in both phases. Tests pin the
behaviour directly:

```python
def test_v11_eval_init_ceils_at_and_around_a_page_boundary():
    for expr, want in [("ceil(1 / 65536) * 65536", 65536),
                       ("ceil(51913 / 65536) * 65536", 65536),
                       ("ceil(65536 / 65536) * 65536", 65536),
                       ("ceil(65537 / 65536) * 65536", 131072),
                       ("ceil(0 / 65536) * 65536", 0)]:
        assert gates.eval_init(f"x = {expr};", ["x"])["x"] == want, expr


def test_v11_eval_init_reproduces_the_shipped_lp_base():
    got = gates.eval_init(open("JSFX/RCBitNova V1.0").read(), ["lp_base"])
    assert got["lp_base"] == 65536
```

- [ ] **Step 2: The site manifest, derived one-to-one from spec §3.2**

Rev 3's table had 28 rows because it *added* `N_DYN`, `gc_kc` and `gc_fc` while **omitting five
authoritative runtime sites** — the `@sample` band loop, the `@sample` Mode-B pass, and all three
`@gfx` loops (coefficients 1675, hit-test 1749, node drawing 1828). Leaving the Mode-B pass on
`N_BANDS` reads and writes four-band dynamic arrays after the flip while a "28-site gate" passes.
Row count is not coverage: build the manifest from the spec's rows and assert each one by name.

```python
# spec section 3.2, one entry per authoritative site. `extra` rows are additional invariants and
# are counted separately so the total can never be mistaken for spec coverage.
SPEC_SITES = {
    "count-declaration":      (r"^N_BANDS\s*=\s*(\d+);", "8"),
    "init-memset-st":         (r"^memset\(st,\s*0,\s*(\w+) \* 4\);", "N_BANDS"),
    "init-memset-dst":        (r"^memset\(dst,\s*0,\s*(\w+) \* 4\);", "N_DYN"),
    "init-memset-cst":        (r"^memset\(cst,\s*0,\s*(\w+) \* 4\);", "N_DYN"),
    "init-eg":                (r"loop\((\w+) \* 2, eg\[i\] = 1;", "N_DYN"),
    "init-mb_peak":           (r"^mb_peak = mb_band \+ (\w+) \* 2 \* MAX_LOOK;", "N_DYN"),
    "init-mb_end":            (r"^mb_end\s+= mb_peak \+ (\w+) \* 2 \* MAX_LOOK;", "N_DYN"),
    "init-mbmode":            (r"^mbmode = mbenv \+ (\w+) \* 2;", "N_DYN"),
    "init-mbwpos":            (r"^mbwpos = mbmode \+ (\w+);", "N_DYN"),
    "init-bus_dry":           (r"^bus_dry = mbwpos \+ (\w+);", "N_DYN"),
    "init-mbenv-fill":        (r"loop\((\w+) \* 2, mbenv\[i\] = 1;", "N_DYN"),
    "init-mbwpos-clear":      (r"^memset\(mbwpos,\s*0,\s*(\w+)\);", "N_DYN"),
    "init-mbgc-fill":         (r"loop\((\w+) \* 2, mbgc\[i\] = 1;", "N_DYN"),
    "init-mbeh":              (r"^mbeh = mbgc \+ (\w+) \* 2;", "N_DYN"),
    "init-hc":                (r"^hc\s+= mbeh \+ (\w+) \* 2;", "N_DYN"),
    "init-mbeh-fill":         (r"loop\((\w+) \* 2, mbeh\[i\] = 1;", "N_DYN"),
    "init-egh":               (r"^egh = hc \+ (\w+);", "N_DYN"),
    "init-egh-fill":          (r"loop\((\w+) \* 2, egh\[i\] = 1;", "N_DYN"),
    "init-hplp_state":        (r"^hplp_state = egh \+ (\w+) \* 2;", "N_DYN"),
    "helper-gc_domain_bits":  (r"function gc_domain_bits[\s\S]*?loop\((\w+),", "N_BANDS"),
    "helper-gc_dom_used":     (r"function gc_dom_used[\s\S]*?loop\((\w+),", "N_BANDS"),
    "slider-setup-static":    (r"b = 0; loop\((\w+), setup_band\(b\); b \+= 1;\);", "N_BANDS"),
    "slider-setup-dyn":       (r"b = 0; loop\((\w+),\s+setup_band_dyn\(b\); b \+= 1;\);", "N_DYN"),
    "slider-modeb-scan":      (r"loop\((\w+),\s*\n\s*mbmode\[b\] = slider\(50 \+ 10 \* b \+ 7\);", "N_DYN"),
    "sample-band-loop":       (r"  loop\((\w+),\n    slider\(band_slider_base\(b\) \+ 1\) == 1 \? \(\s*// enable", "N_DYN"),
    "sample-static-loop":     (r"V1\.1: bands 5-8, STATIC ONLY[\s\S]*?loop\((\w+) - (\w+),", ("N_BANDS", "N_DYN")),
    "sample-modeb-pass":      (r"corrL = 0; corrR = 0;\s*\n\s*b = 0;\s*\n\s*loop\((\w+),", "N_DYN"),
    "gfx-band-setup":         (r"loop\((\w+), gc_band_setup\(gc_b\); gc_b \+= 1;\);", "N_BANDS"),
    "gfx-hit-test":           (r"gc_hit_n = 0;\s*\ngc_b = 0;\nloop\((\w+),", "N_BANDS"),
    "gfx-node-draw":          (r"loop\((\w+),\s*\n\s*gc_s = [^\n]*\n\s*gc_en = slider\(gc_s \+ 1\);", "N_BANDS"),
}

EXTRA_INVARIANTS = {
    "count-dyn-declaration":  (r"^N_DYN\s*=\s*(\d+);", "4"),
    "init-gc_fc-sizing":      (r"^gc_fc\s+= gc_kc \+ (\w+) \* 8;", "N_BANDS"),
    "init-clear-derived":     (r"^memset\(gc_trace, 0, (gc_hits \+ 8 - gc_trace)\);", "gc_hits + 8 - gc_trace"),
}
```

Every row above was **run against the shipped V1.0 and shown to match**, because this is exactly
where rev 3 went wrong twice over: its Mode-B scan row expected the `any_b` line, when that loop
opens with `mbmode[b] = slider(50 + 10 * b + 7);`, so it could never fire. Two rows drafted for this
revision failed the same test before it was written — an `any_b ?` anchor captured `BD` from an
unrelated loop, and a node-draw pattern matched nothing — and both were replaced with anchors taken
from the source. **A row that matches nothing is the defect this gate is for; write no row without
running it.**

**A row that matches nothing is a failure**, and so is a row whose capture holds the wrong token:

```python
def check_sites(text, path):
    for name, (pattern, want) in {**SPEC_SITES, **EXTRA_INVARIANTS}.items():
        m = re.search(pattern, text, re.M)
        assert m, f"{path}: site {name!r} not found - renamed, moved or deleted"
        got = m.groups() if isinstance(want, tuple) else m.group(m.lastindex or 1)
        assert got == want, f"{path}: site {name!r} carries {got!r}, expected {want!r}"
    assert len(SPEC_SITES) == 28, f"the spec has 28 sites, the manifest has {len(SPEC_SITES)}"
```

- [ ] **Step 3: The forbidden patterns**

```python
FORBIDDEN = [
    (r"10 ?\* ?\((?:b|gc_b|gc_hover|gc_drag|gc_sel) ?\+ ?1\)", "N_DYN-bounded",
     "open-coded band-slider arithmetic outside band_slider_base"),
]


def check_forbidden(text, path):
    for pattern, exempt, why in FORBIDDEN:
        for line in text.splitlines():
            if re.search(pattern, line) and exempt not in line and "function band_slider_base" not in line:
                raise AssertionError(f"{path}: {why}: {line.strip()}")
```

- [ ] **Step 4: The address gate — every base, compared to the model**

Rev 3 computed `model_gui` and then never used it, so a wrong `gc_snap`, `gc_meta`, `gc_ebuf` or
`gc_hits` could stay ordered, stay under the page boundary, and pass (review P1-1).

```python
AUDIO = ["mb_band", "mb_peak", "mb_end", "mbenv", "mbmode", "mbwpos", "bus_dry", "mbgc",
         "mbeh", "hc", "egh", "hplp_state", "hplp_cf", "lp_rt", "lp_kc", "lp_ks", "lp_geo",
         "lp_off", "lp_fs", "gc_trace"]
GUI = ["gc_lin", "gc_snap", "gc_meta", "gc_kc", "gc_fc", "gc_ebuf", "gc_hits"]


def check_addresses(text, path):
    v11 = eval_init(text, AUDIO + GUI + ["lp_base"])
    v10 = eval_init(open("JSFX/RCBitNova V1.0").read(), AUDIO + GUI[:-1] + ["lp_base"])
    model_audio = layout.audio_layout(8, 4)
    model_gui = layout.gui_layout(model_audio["gc_trace"], 8)

    for name in AUDIO:                       # exact, in both files, against the model
        assert v11[name] == v10[name] == model_audio[name], \
            f"{name}: V1.0 {v10[name]}, V1.1 {v11[name]}, model {model_audio[name]}"
    for name in GUI:                         # EVERY GUI base, not just ordering
        assert v11[name] == model_gui[name], f"{name}: {v11[name]} != model {model_gui[name]}"
    assert v11["gc_kc"] == v10["gc_kc"], "gc_kc's BASE must not move; only its size grows"
    assert v11["gc_fc"] - v10["gc_fc"] == 32
    assert v11["lp_base"] == v10["lp_base"] == 65536
    assert v11["gc_hits"] + 8 <= v11["lp_base"], "the GUI region must end below lp_base"
```

The clear span is asserted as an expression by `init-clear-derived` above — a literal number there
is itself the defect, because it cannot be right in both phases.

The rev-1 grep survives as diagnostics printed beside the numbers. It is not the gate.

- [ ] **Step 5: Self-test — seed a defect in every class and require rejection**

A gate that has never failed is a gate nobody has tested, and rev 3's negative test only edited a
copied dict and asserted Python subtracts correctly.

```python
SEEDED_DEFECTS = [
    # @init
    (lambda t: t.replace("mb_peak = mb_band + N_DYN", "mb_peak = mb_band + N_BANDS"), "mb_peak"),
    (lambda t: t.replace("memset(st, 0, N_BANDS * 4)", "memset(st, 0, N_DYN * 4)"), "init-memset-st"),
    (lambda t: t.replace("gc_fc    = gc_kc + N_BANDS * 8", "gc_fc    = gc_kc + 32"), "init-gc_fc-sizing"),
    (lambda t: t.replace("memset(gc_trace, 0, gc_hits + 8 - gc_trace)", "memset(gc_trace, 0, 13678)"),
     "init-clear-derived"),
    # runtime loops - the class rev 3's table could not see at all
    (lambda t: t.replace("  loop(N_DYN,\n    slider(band_slider_base(b) + 1) == 1 ? (",
                         "  loop(N_BANDS,\n    slider(band_slider_base(b) + 1) == 1 ? ("), "sample-band-loop"),
    (lambda t: _modeb_pass_to(t, "N_BANDS"), "sample-modeb-pass"),
    (lambda t: t.replace("loop(N_BANDS, gc_band_setup(gc_b)", "loop(N_DYN, gc_band_setup(gc_b)"), "gfx-band-setup"),
    (lambda t: _hit_test_to(t, "N_DYN"), "gfx-hit-test"),
    (lambda t: _node_draw_to(t, "N_DYN"), "gfx-node-draw"),
    (lambda t: t.replace("b = 0; loop(N_DYN,  setup_band_dyn(b)", "b = 0; loop(N_BANDS,  setup_band_dyn(b)"),
     "slider-setup-dyn"),
    # GUI addresses
    (lambda t: t.replace("gc_ebuf  = gc_fc + 126", "gc_ebuf  = gc_fc + 128"), "gc_ebuf"),
    (lambda t: t.replace("gc_hits  = gc_ebuf + 24", "gc_hits  = gc_ebuf + 32"), "gc_hits"),
    # forbidden pattern
    (lambda t: t.replace("gc_s = band_slider_base(gc_sel);", "gc_s = 10 * (gc_sel + 1);"), "band_slider_base"),
    # unevaluable chain
    (lambda t: t.replace("N_BANDS = 8;", ""), "could not evaluate"),
]


def test_v11_gate_rejects_each_seeded_defect(tmp_path):
    clean = open("JSFX/RCBitNova V1.1").read()
    for n, (mutate, expect) in enumerate(SEEDED_DEFECTS):
        src = tmp_path / f"mutant{n}"
        mutated = mutate(clean)
        assert mutated != clean, f"defect {n} ({expect}) did not change the source"
        src.write_text(mutated)
        with pytest.raises(AssertionError, match=re.escape(expect)):
            gates.check_source(str(src), project=True)
```

The `assert mutated != clean` line matters as much as the rejection: a seeding lambda whose
`replace` misses silently tests the clean file and passes.

- [ ] **Step 6: Run it against the current, still-four-band V1.1**

```bash
python3 tools/rcbitnova_gates.py --preflip   # projects N_BANDS=8 in memory, full contract
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "gate or eval_init"
```

Expected: `--preflip` passes **completely** — no excused rows. That is the whole point of the
projection: the thing Task 7 will do is verified before it is done.

- [ ] **Step 7: Commit**

```bash
git add tools/rcbitnova_gates.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.1 source gate - spec-derived sites, computed addresses, self-tested"
```

### Task 7: Flip the count

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (one line)

- [ ] **Step 1: Raise it**

```eel2
N_BANDS = 8;
```

- [ ] **Step 2: Run the same contract, now against the real file**

```bash
python3 tools/rcbitnova_gates.py --source-only && echo SOURCE_GATES_OK
```

`--source-only` is `--preflip` without the projection: identical assertions, real text. It passed on
the projection in Task 6, so anything that fails here was introduced by this one-line edit. A failure
is the map moving — which does not announce itself at load.

- [ ] **Step 3: Live check — the first genuinely eight-band load**

Enable B5 with a large boost: audible, and on the graph. Then set a B1 Mode-B ceiling low enough
that the B5 boost pushes it over — Mode B must react, proving the ordering of §3.1.

- [ ] **Step 4: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - eight static bands"
```
### Task 8: The band context menu, the selector strip, and node cycling

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
`gc_elen`) exactly as Freq/Macro/Micro/Ratio/Q do.

Commit the typed value **clamped and quantised to the declared step**:

```eel2
v = min(max(v, 0), 1);
gc_w_qchar(gc_sel, floor(v / 0.001 + 0.5) * 0.001);
```

"Full resolution" means the whole 0.001 grid instead of five coarse presets — it does not mean
off-grid values. V1.0 measured what those cost: a continuous 59.752306 Hz written to a step-1
slider left **−62 dB of null residue**. A typed 0.3335 would be reachable from the graph,
unreachable from the host, and the two would not null.

**Deviation, stated rather than hidden:** V1.0's five existing fields keep typed values exact. This
new field does not follow them. Putting those five on their declared steps is a real fix, but it
changes shipped behaviour and belongs in its own version rather than smuggled into V1.1.

The menu presets stay as the fast path. With the field present, the nine-parameter reachability
claim is honest.

- [ ] **Step 4a: Draw static-only nodes with a thinner outline (spec §5)**

§5 requires **both** signals — outline thickness and the textual tag — because thickness alone is
not accessible. V1.0 draws every node with one call at a fixed radius:

```eel2
gfx_circle(gc_nx, gc_ny, 6 * gc_sc, gc_en ? 1 : 0, 1);
```

Rev 3 added a second ring to static nodes, which gives them *more* structure than dynamic ones —
the opposite of "thinner" (review P2-1). Define **one** primitive with two styles instead: every
node is a filled body plus an outline, and the outline weight is what differs.

```eel2
// One node primitive, two styles. Dynamic bands carry a 2px outline, static-only bands 1px -
// the same stroke, thinner, which is what the spec asks for. Thickness is a redundant cue; the
// DYN/STATIC tag remains the accessible one.
gc_ow = gc_b < N_DYN ? 2 : 1;
gfx_circle(gc_nx, gc_ny, 6 * gc_sc, gc_en ? 1 : 0, 1);          // body: unchanged
gc_i = 0;
loop(gc_ow,                                                      // outline: 2 rings or 1
  gfx_circle(gc_nx, gc_ny, (6 + gc_i) * gc_sc, 0, 1);
  gc_i += 1;
);
```

At `gc_sc` = 1 the difference is one pixel of stroke, which is the smallest honest version of
"thinner"; at Retina it is two device pixels against four.

Check it at Retina scaling (`gc_sc` = 2) in all four combinations — DYN enabled, DYN disabled,
STATIC enabled, STATIC disabled — a hairline is exactly what a HiDPI backing store can swallow.

- [ ] **Step 5: Add the B1…B8 selector strip and the DYN/STATIC tag**

**Where it goes (review P1-7).** V1.0 sets `gc_fy = gc_py + gc_ph + 6 * gc_sc`, so the strip rev 3
proposed — `gc_fy - 24*gc_sc` to `gc_fy - 6*gc_sc` — sat in the **bottom 18 logical pixels of the
plot itself**. Nodes reach that edge, and node click-to-enable and drag-start run earlier in the
frame, so a click meant for B1–B8 could also enable or start dragging a node underneath. Put the
strip **below** the plot, in the readout band that already belongs to the chrome:

```eel2
gc_sy = gc_fy + 2 * gc_sc;                // strip top: BELOW the plot, not inside it
```

and make ownership explicit rather than positional. Compute the hot test **before** the node event
code and let it veto:

```eel2
// Ownership: if the pointer is over the strip, the graph does not see this click at all.
gc_strip_hot = (mouse_y >= gc_sy && mouse_y < gc_sy + 18 * gc_sc &&
                mouse_x >= gc_px && mouse_x < gc_px + N_BANDS * 34 * gc_sc);
gc_strip_hot ? ( gc_hover = -1; gc_hit_n = 0; );   // before click-to-enable and drag-start
```

Then the strip itself, drawn later in the frame:

```eel2
// A deterministic way to reach any band regardless of node overlap, plus the capability tag.
gc_b = 0;
loop(N_BANDS,
  gc_bx = gc_px + gc_b * 34 * gc_sc;
  gc_bhot = (mouse_x >= gc_bx && mouse_x < gc_bx + 30 * gc_sc &&
             mouse_y >= gc_sy && mouse_y < gc_sy + 18 * gc_sc);
  gc_sel == gc_b ? gfx_set(0.3, 0.45, 0.6, 1) : gfx_set(0.16, 0.16, 0.18, 1);
  gc_bhot ? gfx_set(0.35, 0.5, 0.66, 1);
  gfx_rect(gc_bx, gc_sy, 30 * gc_sc, 18 * gc_sc);
  gfx_set(slider(band_slider_base(gc_b) + 1) == 1 ? 0.95 : 0.45, 0.9, 0.95, 1);
  gfx_x = gc_bx + 5 * gc_sc; gfx_y = gc_sy + 4 * gc_sc;
  gfx_drawstr("B"); gfx_drawnumber(gc_b + 1, 0);
  gc_click && gc_bhot ? gc_sel = gc_b;
  gc_b += 1;
);
gfx_set(0.6, 0.6, 0.65, 1);
gfx_x = gc_px + N_BANDS * 34 * gc_sc + 10 * gc_sc; gfx_y = gc_sy + 4 * gc_sc;
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
| One node under the cursor | every click selects it (the counter advances; `% 1` keeps the selection) |
| Two coincident, both enabled | clicks alternate |
| Three coincident | clicks walk 1 → 2 → 3 → 1 |
| Three coincident, middle disabled | still reachable, and one click enables it |
| Click, wait 1 s, click again | back to the lowest band |
| Click, move away, return, click | back to the lowest band |
| Coincident nodes, then drag | the drag moves the band the last click selected |
| B5–B8 nodes at `gc_sc` = 2 | thinner outline visible, enabled and disabled alike |
| A node at the very bottom edge of the plot, strip directly below | the strip click selects the band and does **not** enable or drag the node |

- [ ] **Step 8: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - band context menu, selector strip, node cycling"
```

---


---

### Task 9: The migration script

**Files:**
- Create: `tools/migrate_v10_to_v11.py`

Before the live gates, because Task 10's null test uses it to put both instances in the same state.

**Measured facts (reapy, live V1.0, 2026-08-19):** the host reports **98** parameters — 95 declared
sliders at 0–94, then `Bypass`, `Wet`, `Delta`. V1.1 will report 134. The declared block is a
prefix; the full list is not.

**And the trap that follows from it (review P0-2): `slider1` is itself named `Bypass`.** So is host
parameter 95. Any name search finds the declared one at index 0 and silently migrates the wrong
parameter — never touching the real host bypass, and contaminating the null test that relies on this
script for equal state. **The host tail is addressed positionally, after validating its names.**

- [ ] **Step 1: Write it**

```python
"""Replace a V1.0 instance with a V1.1 instance in place, preserving its settings.

The only supported migration. V1.1 is a new file, so an existing project simply reopens V1.0 and is
unaffected - this is for moving a project forward deliberately.

Three things learned the hard way, all of them measured rather than reasoned:

1. The host list is 95 declared parameters THEN Bypass/Wet/Delta. Copying by index across the whole
   list lands the host tail in the new bands.
2. `slider1` is ALSO named "Bypass". Searching by name finds index 0, not the host parameter. The
   tail is addressed by position, after its names are validated.
3. add_fx appends. If V1.0 was not last in the chain, the FX order - and the sound - changes even
   when every value is right.

Identity is by FX GUID throughout: a track may legitimately hold more than one RCBitNova, and a
name search would delete the wrong one on the failure path.
"""

import reapy
from reapy import reascript_api as RPR

N_DECLARED_V10 = 95
N_DECLARED_V11 = 131
HOST_TAIL = ("Bypass", "Wet", "Delta")
UNSUPPORTED = ("parameter modulation", "pin mappings", "parameter aliases", "oversampling")


def _guid(track, idx):
    """The GUID as a STRING. Measured 2026-08-22: TrackFX_GetFXGUID returns a *pointer*
    ('(GUID*)0x...') that does NOT follow the FX across TrackFX_CopyToTrack - after a move the
    pointer at the destination slot is a different value entirely, so using it as identity would
    have made every post-move lookup fail. guidToString gives the real GUID, which does follow:

        before move: fx1 -> {99F84DA4-19BE-9A48-A7CF-7FCF4B302A05}
        after  move: idx0 -> {99F84DA4-19BE-9A48-A7CF-7FCF4B302A05}
    """
    return RPR.guidToString(RPR.TrackFX_GetFXGUID(track.id, idx), "")[1]


def _index_of_guid(track, guid):
    for i in range(track.n_fxs):
        if _guid(track, i) == guid:
            return i
    return None


def _cfg(track, idx, key, buf=64):
    """TrackFX_GetNamedConfigParm returns a SIX-element list - [ok, track, fx, key, value, buflen]
    - not the (ok, value) pair a two-name unpack assumes. Measured 2026-08-22; the same shape trap
    cost a live session on GetUserInputs."""
    r = RPR.TrackFX_GetNamedConfigParm(track.id, idx, key, "", buf)
    return bool(r[0]), r[4]


def _has_modulation(track, idx, n_declared):
    """Measured 2026-08-22 on this build: a clean instance answers ok=0 with an empty value, and
    after SetNamedConfigParm('param.0.mod.active', '1') it answers ok=1, '1'. So the query works
    and ok=0 genuinely means 'no modulation record', not 'unsupported'."""
    for i in range(n_declared):
        ok, value = _cfg(track, idx, f"param.{i}.mod.active", 32)
        if ok and value not in ("", "0"):
            return True
    return False


def migrate(track_index=0, dry_run=True):
    with reapy.inside_reaper():
        pr = reapy.Project()
        tr = pr.tracks[track_index]

        srcs = [fx for fx in tr.fxs if "RCBitNova V1.0" in fx.name]
        if not srcs:
            return "no V1.0 instance on this track"
        if len(srcs) > 1:
            return f"REFUSED: {len(srcs)} V1.0 instances on this track; migrate them one by one"
        src = srcs[0]
        src_idx = src.index
        src_guid = _guid(tr, src_idx)

        names = [src.params[i].name for i in range(src.n_params)]
        if len(names) != N_DECLARED_V10 + len(HOST_TAIL):
            return (f"REFUSED: V1.0 reports {len(names)} parameters, expected "
                    f"{N_DECLARED_V10 + len(HOST_TAIL)} - this REAPER build exposes a different "
                    "special-parameter set; migrate by hand")
        if tuple(names[N_DECLARED_V10:]) != HOST_TAIL:
            return f"REFUSED: unexpected host tail {names[N_DECLARED_V10:]!r}; migrate by hand"

        if any(src.params[i].envelope is not None for i in range(src.n_params)):
            return "REFUSED: this instance has automation; migrate it by hand"
        if _has_modulation(tr, src_idx, N_DECLARED_V10):
            return "REFUSED: this instance has parameter modulation; migrate it by hand"

        declared = [src.params[i].normalized for i in range(N_DECLARED_V10)]
        # POSITIONAL, not by name: parameter 0 is also called "Bypass".
        host = [src.params[N_DECLARED_V10 + k].normalized for k in range(len(HOST_TAIL))]
        enabled = RPR.TrackFX_GetEnabled(tr.id, src_idx)
        offline = RPR.TrackFX_GetOffline(tr.id, src_idx)

        if dry_run:
            return (f"would copy {len(declared)} declared + {len(host)} host parameters "
                    f"into chain position {src_idx}; unsupported state not detected "
                    f"({', '.join(UNSUPPORTED)} are NOT migrated)")

        # EVERYTHING after this line is inside try/finally, add_fx included. Rev 3 called add_fx
        # and read its GUID before the try, so the one failure the tests are meant to exercise -
        # add_fx returning None or raising - skipped the handler entirely, leaving the undo block
        # open and possibly an orphan behind.
        RPR.Undo_BeginBlock2(pr.id)
        dst_guid = None
        closed = False
        try:
            dst = tr.add_fx("JS: RCBitNova V1.1")
            if dst is None:
                raise RuntimeError("add_fx returned None: is JSFX/RCBitNova V1.1 installed?")
            dst_guid = _guid(tr, dst.index)
            dst_idx = _index_of_guid(tr, dst_guid)
            dst_names = [dst.params[i].name for i in range(dst.n_params)]
            if len(dst_names) != N_DECLARED_V11 + len(HOST_TAIL):
                raise RuntimeError(f"V1.1 reports {len(dst_names)} parameters, expected "
                                   f"{N_DECLARED_V11 + len(HOST_TAIL)}")
            if tuple(dst_names[N_DECLARED_V11:]) != HOST_TAIL:
                raise RuntimeError(f"V1.1 host tail is {dst_names[N_DECLARED_V11:]!r}")

            for i, v in enumerate(declared):
                dst.params[i].normalized = v
            for k, v in enumerate(host):
                dst.params[N_DECLARED_V11 + k].normalized = v

            # Read back BEFORE destroying the only known-good instance.
            for i, v in enumerate(declared):
                got = dst.params[i].normalized
                if got != v:
                    raise RuntimeError(f"parameter {i} ({dst_names[i]}) did not take: "
                                       f"wrote {v}, read {got}")
            for k, v in enumerate(host):
                if dst.params[N_DECLARED_V11 + k].normalized != v:
                    raise RuntimeError(f"host parameter {HOST_TAIL[k]} did not take")

            RPR.TrackFX_SetEnabled(tr.id, dst_idx, enabled)
            RPR.TrackFX_SetOffline(tr.id, dst_idx, offline)

            # Move into the source's slot, then verify the move landed before removing anything.
            RPR.TrackFX_CopyToTrack(tr.id, dst_idx, tr.id, src_idx, True)
            if _index_of_guid(tr, dst_guid) != src_idx:
                raise RuntimeError(f"move failed: V1.1 is at {_index_of_guid(tr, dst_guid)}, "
                                   f"expected {src_idx}")
            stale_idx = _index_of_guid(tr, src_guid)
            if stale_idx is None:
                raise RuntimeError("lost track of the V1.0 instance after the move")
            tr.fxs[stale_idx].delete()
        except Exception as exc:                      # noqa: BLE001 - any failure rolls back
            if dst_guid is not None:                  # BY GUID: the track may hold another V1.1
                doomed = _index_of_guid(tr, dst_guid)
                if doomed is not None:
                    tr.fxs[doomed].delete()
            RPR.Undo_EndBlock2(pr.id, "RCBitNova migration (failed)", -1)
            closed = True
            if _index_of_guid(tr, src_guid) is None:
                RPR.Undo_DoUndo2(pr.id)               # source already gone: undo for real
                return f"FAILED after the source was removed; undone: {exc}"
            return f"REFUSED, source untouched: {exc}"
        finally:
            if not closed:                            # closed exactly once, on every path
                RPR.Undo_EndBlock2(pr.id, "RCBitNova V1.0 -> V1.1", -1)
        return f"migrated {len(declared)} declared + {len(host)} host parameters"


if __name__ == "__main__":
    print(migrate(dry_run=True))
```

- [ ] **Step 1a: Verify the two detection APIs, then use them (review P1-6)**

Rev 3 called pin mappings and per-FX oversampling undetectable. They are not — but the shapes are
not what rev 4 assumed either.

**Verified live 2026-08-22 — both exist, and both return list shapes, not scalars:**

```
TrackFX_GetPinMappings(tr, fx, isout, pin, high32) -> [retval, track, fx, isout, pin, high32]
    in  pin 0 -> retval 1        # default map: pin k routes to bit k, i.e. retval == 1 << pin
    out pin 1 -> retval 2
TrackFX_GetNamedConfigParm(tr, fx, key, "", buf)   -> [ok, track, fx, key, value, buflen]
    'instance_oversample_shift' -> ok 1, value '0'      (default; detectable)
    'pdc'                       -> ok 1, value '0'
```

Both are therefore usable, and both take the five-argument form:

```python
def _nondefault_pins(track, idx, n_channels=2):
    """A default map routes pin k to bit k. Anything else is a hand-made routing this script does
    not reproduce. retval is element 0 of the returned list, and `high32` is a required argument."""
    for pin in range(n_channels):
        for is_out in (0, 1):
            if RPR.TrackFX_GetPinMappings(track.id, idx, is_out, pin, 0)[0] != (1 << pin):
                return True
    return False


def _oversampled(track, idx):
    ok, value = _cfg(track, idx, "instance_oversample_shift", 32)
    return ok and value not in ("", "0")
```

Non-default pin maps and instance oversampling join automation and modulation in the refusal list.
Only parameter aliases stay in the warning.

**Honest scope.** Automation, parameter modulation, non-default pin mappings and instance
oversampling are **detected and refused** (the last two subject to the check above). Parameter
aliases remain **undetected** — silently not migrated, and the dry run says so. An undetected item
is never described as refused.

The undo block groups the operations for the user; it does not by itself roll back an exception.
That is why every mutation is verified before the next one, why the destination is removed by GUID
on failure, and why the one path that can fail *after* the source is gone calls a real undo and
says so.

- [ ] **Step 2: Test every branch against FakeReaper BEFORE touching REAPER (review P1-5)**

Project rule, and it applies squarely here: this script's correctness is index shifts, GUID identity,
undo balance, insertion failure and not disturbing unrelated FX — exactly what a fake can assert and
a live run can only sample.

`midi-composition/tests/_reaper_fakes.py` has 62 functions and **no `TrackFX_*`**, so extend it (or
add a focused sibling) with: FX enumeration, `add_fx`, `TrackFX_CopyToTrack` with `is_move`, delete,
`TrackFX_GetFXGUID`, parameter get/set, `TrackFX_GetNamedConfigParm`, enabled/offline, and counters
for `Undo_BeginBlock2` / `Undo_EndBlock2` / `Undo_DoUndo2`.

Then assert the **whole chain and the undo balance** after each branch:

| Scenario | Chain after | Undo | Return |
|---|---|---|---|
| V1.0 at index 1 of 3, success | `[A, V1.1, B]`, values copied | 1 opened, 1 closed, 0 undos | `migrated 95 declared + 3 host` |
| `add_fx` returns `None` | unchanged | 1 opened, 1 closed | `REFUSED, source untouched` |
| `add_fx` raises | unchanged | 1 opened, 1 closed | `REFUSED, source untouched` |
| read-back mismatch | destination removed, source intact | 1 opened, 1 closed | `REFUSED, source untouched` |
| move lands at the wrong index | destination removed, source intact | 1 opened, 1 closed | `REFUSED, source untouched` |
| failure after the source was deleted | undo called once | 1 opened, 1 closed, 1 undo | `FAILED … undone` |
| an unrelated V1.1 already present | that instance survives untouched | — | — |
| two V1.0 instances | nothing created | 0 opened | `REFUSED: 2 V1.0 instances` |
| automation / modulation / pins / oversampling | nothing created | 0 opened | the matching refusal |

"One opened, one closed" on every path is the assertion rev 3 could not make, because its `add_fx`
sat outside the block that closes it.

- [ ] **Step 3: Dry-run on a project with a configured V1.0 instance, NOT last in the chain**

Run: `python3 tools/migrate_v10_to_v11.py`
Expected: `would copy 95 declared + 3 host parameters into chain position N`, with N the real slot,
followed by the unsupported-state notice.

- [ ] **Step 4: Run it for real; verify values, defaults, position, chain and the host tail**

Set the source's **host** Bypass and Wet to distinctive values first — that is the pair the rev-2
script would have silently skipped. Then confirm: all 95 values match; the 36 new parameters sit at
their declared defaults; the FX occupies the **same chain position**; host Bypass/Wet/Delta carried
over; exactly one RCBitNova remains. Undo once — V1.0 must come back in its original slot in one step.

- [ ] **Step 5: The failure paths**

| Forced failure | Expected |
|---|---|
| `RCBitNova V1.1` renamed so `add_fx` yields nothing usable | refusal, V1.0 untouched, no orphan |
| a second V1.1 already on the track | that instance survives; only the new one is removed |
| two V1.0 instances on the track | refused before anything is created |
| an automated parameter | refused before anything is created |

- [ ] **Step 6: Commit**

```bash
git add tools/migrate_v10_to_v11.py tests/
git commit -m "feat(rcbitnova): V1.1 migration - positional host tail, GUID identity, verified rollback"
```

---

### Task 10: The live gates

**Files:**
- Create: `tools/rcbitnova_nulltest.py`, `tools/rcbitnova_cpu.py`, `tests/fixtures/null_30s.wav`
- Modify: `tools/rcbitnova_gates.py` (add `--live`)

Source-level checking already happened in Task 6. What remains needs REAPER, and each of these exits
nonzero.

- [ ] **Step 1: The CPU metric — settled by measurement, not by choice (review P0-5)**

Rev 3 pinned peak block time and an xrun counter to `GetSetProjectInfo`. That key set is
render/project settings, not Performance Meter values, so the gate had no data source while reading
as though it did. **Measured on this build 2026-08-22** — every ReaScript function whose name
contains `cpu`, `perf`, `underrun`, `xrun`, `blocksize` or `audiodevice`:

```
['GetAudioDeviceInfo', 'GetUnderrunTime']
```

There is **no peak-block-time API**. So the fallback branch is not a fallback, it is the only
branch: CPU is a **documented manual Performance Meter protocol** — same runs, same statistic, a
human reading the meter into a small JSON file that `rcbitnova_cpu.py` then validates and gates on.
Downgraded from automatic to manual; never from measured to assumed.

Xruns stay automatic. `GetUnderrunTime` returns `[audio_xrun, media_xrun, curtime]` — **timestamps
in milliseconds, not counts** (measured: `[0, 0, 712432281]` on an idle system). Protocol: read
before the run, read after, treat any change in `audio_xrun` as a failure.

**The induced-xrun test is mandatory**: force one — tiny block size, everything enabled — and
confirm `audio_xrun` actually moves off 0. A gate whose failure signal has never been seen to change
is not a gate.

- [ ] **Step 2: `--live` — the parameter manifest, with real records**

Rev 3's `record()` claimed index, name, min, max, step, default and round trips, and returned
`p.formatted` — the *current value's display string*, which is neither step nor default. Two
incompatible declarations whose current values happen to format alike would compare equal.

```python
def record(fx, i, default):
    p = fx.params[i]
    lo, hi = p.range
    before = p.normalized                      # captured BEFORE any probe
    trips = []
    for probe in (0.0, 0.5, 1.0):
        p.normalized = probe
        trips.append((probe, p.normalized, p.formatted))
    p.normalized = before
    assert p.normalized == before, f"parameter {i} ({p.name}) did not restore"
    return (i, p.name, lo, hi, default, tuple(trips))
```

**Defaults come from an independently fresh instance**, read before anything is probed — a default
cannot be recovered from an instance you have already written to. Add that instance, read all 131,
delete it, and pass the values in.

The step is what the declaration says, so assert it where it is checkable: the three round trips
must land on the declared grid, and `formatted` must differ between `0.0` and `1.0` for every
parameter (a parameter that formats identically at both ends is not wired to anything).

```python
assert v11_declared[:95] == v10_declared        # full records, not just names
assert len(v11_declared) == 131
assert v11_host == v10_host == ["Bypass", "Wet", "Delta"]
```

The 95-record prefix is the compatibility contract; the host tail is checked separately **by
position**, for the reason Task 9 documents.

- [ ] **Step 3: Writer correctness is a SOURCE gate; reachability stays manual (review P1-3)**

Rev 3 said the live gate would "drive" each `gc_w_*` function and watch the manifest. It cannot:
`reapy` sets host parameters, and setting a parameter externally bypasses the very writer under
test. There is no GUI automation here, and inventing one is a bigger project than eight bands.

So split it honestly:

**Automatic, in `--source-only` (Task 6 gains this check):**

```python
WRITERS = {                       # writer -> slider offset within the band block
    "gc_w_enable": 1, "gc_w_type": 2, "gc_w_freq": 3, "gc_w_q": 4, "gc_w_macro": 5,
    "gc_w_micro": 6, "gc_w_ratio": 7, "gc_w_place": 8, "gc_w_qchar": 9,
}
BASES = [10, 20, 30, 40, 150, 160, 170, 180]


def check_writers(text, path):
    for fn, off in WRITERS.items():
        body = _function_body(text, fn)
        assert body, f"{path}: writer {fn} not found"
        want = [f"slider{b + off}" for b in BASES]
        got = re.findall(r"slider(\d+)\s*=", body)
        assert [f"slider{g}" for g in got] == want, f"{path}: {fn} writes {got}, expected {want}"
        assert re.search(r"\bslider_automate\(", body), f"{path}: {fn} never calls slider_automate"
        assert f"setup_band(b)" in body, f"{path}: {fn} does not rebuild static coefficients"
        assert re.search(r"b < N_DYN \? setup_band_dyn\(b\)", body), \
            f"{path}: {fn} calls setup_band_dyn unguarded - a drag on B5-B8 would corrupt memory"
```

This catches the whole class the review is worried about — a wrong slider number, a missing
`slider_automate`, an unguarded dynamic rebuild — statically, for all nine writers and all eight
bands, with no host involved.

**Manual, in the Task 8 reachability matrix:** that every gesture reaches the parameter it should.
That part was always a human check and is now labelled as one.

- [ ] **Step 4: `tools/rcbitnova_nulltest.py` — §6.4, bit-preserving (review P1-4)**

Every property that could quantise a real difference away is pinned, and the render state is saved
and restored:

| Question | Answer |
|---|---|
| Material | `tests/fixtures/null_30s.wav`, **committed** — 30 s, 48 kHz, 32-bit float: swept sine + noise burst + silence + a full-scale transient, generated once by `tools/make_null_fixture.py` |
| Instances | one track per version, fresh, GUI closed, 48 kHz, block 512 |
| Equal state | `migrate_v10_to_v11.py` on a **copy** of the V1.0 track, so the original survives for rendering |
| Render format | **32-bit float WAV**, dither OFF, normalization OFF, no resampling, `RENDER_SRATE` = 48000 |
| Render bounds | the fixture's exact length, entire-item bounds, **one selected track at a time** (`RENDER_SETTINGS` = stems, selected track only) |
| State handling | read every `RENDER_*` property with `GetSetProjectInfo` / `GetSetProjectInfo_String`, set, render, **restore** — asserted restored at the end |
| Completion | poll for the output file's size to stop changing, then verify the header's frame count matches the expected duration; no fixed sleep |
| Reader | a float-WAV reader in this file — Python's `wave` rejects `WAVE_FORMAT_IEEE_FLOAT` (format 3), so parse the RIFF chunks and read the data with `array('f')` |
| Latency | `TrackFX_GetNamedConfigParm(..., "pdc")` on both — verified live: returns `[ok, track, fx, key, value, buflen]`, value at index **4** — asserted **equal before** samples are compared |
| Compare | equal frame count, then sample for sample |
| Tolerance | zero |
| Report | case name, first differing frame, both values |

Cases: defaults; four bands in Mode A; four bands in Mode B; Min and Linear topologies. **Assert the
case count at the end** — a skipped case must fail, not disappear.

Equal latency is checked first because a PDC difference renders as a shifted-but-identical file,
which reads like a subtle DSP change when it is a compensation change.

**Prove the comparator can fail, below PCM resolution:** seed a difference of one float ULP into a
copy of a render and require a mismatch. If that passes, the format is quantising and the whole gate
is decorative — which is exactly what integer PCM would have done to it.

- [ ] **Step 5: `tools/rcbitnova_cpu.py` — §6.5**

| Question | Answer |
|---|---|
| Metric | peak block time, read by a human from the Performance Meter into `cpu_runs.json` — no API exists on this build (Step 1) |
| Runs | five 60-second playbacks per configuration; discard the first |
| Statistic | median of the per-run peaks |
| Blocks | 128 and 512, both reported |
| Xruns | `GetUnderrunTime` before and after each run; **any change fails** |
| Comparison A | V1.1 with B5–B8 disabled vs V1.0 — **regression, within +5 %** |
| Comparison B | V1.1 eight enabled vs V1.1 four enabled — **feature cost, informational** |

Print both; only A gates. Any xrun fails regardless of timing.

- [ ] **Step 6: Run everything and read the output**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q      # expect 238 passed
python3 tools/rcbitnova_gates.py --source-only && echo SOURCE_OK
python3 tools/rcbitnova_gates.py --live       && echo MANIFEST_OK
python3 tools/rcbitnova_nulltest.py           && echo NULL_OK
python3 tools/rcbitnova_cpu.py                && echo CPU_OK
```

A gate that was not run is a gate that failed.

- [ ] **Step 7: Commit**

```bash
git add tools/rcbitnova_nulltest.py tools/rcbitnova_cpu.py tools/make_null_fixture.py \
        tests/fixtures/null_30s.wav tools/rcbitnova_gates.py
git commit -m "test(rcbitnova): V1.1 live gates - float null render, writer source gate, proven CPU source"
```

---

### Task 11: Spec rev 5, Fable review, as-shipped, tag

- [ ] **Step 1: Bring the spec up to what was built**

Three corrections, not one:

1. **§2.1 and §6.1** still pin the clear span to 13670 and know nothing of `gc_hits`. The span is
   now *derived* (`gc_hits + 8 - gc_trace`), and the derived value is the acceptance contract.
2. **§6.7** still says V1.0's full host parameter list is a strict prefix of V1.1's. Measured, it is
   not: only the 95 declared parameters are a prefix, and the three host specials move (review
   P1-8). State it as declared-prefix-by-index plus a host tail validated by position.
3. **§5** gains the node rendering rule as built — one primitive, two outline weights.

The plan and the spec cannot both be authoritative.

- [ ] **Step 2: Fable final review**

Dispatch with `model: fable` over `JSFX/RCBitNova V1.1`, the diff against V1.0, and spec rev 5.
Ask specifically for: bit-accuracy verdict; whether any `N_DYN` site was missed; whether the
static-only loop truly touches no dynamic array; whether all nine writers are complete, correctly
numbered and guarded; whether any band-slider read still bypasses `band_slider_base`; and EEL2
function-order traps.

- [ ] **Step 3: Address every P0/P1, then re-run Tasks 6 and 10**

- [ ] **Step 4: Append "As-shipped" to the spec**

Record every live measurement, every deviation and why, every defect found live and how. Follow
V1.0 §16 as the model.

- [ ] **Step 5: Update the memory file and tag**

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
| §2 memory, zero-slack boundaries | 1 (model + ownership-aware memory), 3 (constants), 6 (computed manifest) |
| §2.1 `gc_kc` growth, clear span | 3 Step 4 (derived), 11 Step 1 (spec rev 5) |
| §3 two counts | 3, 7 |
| §3.1 signal order, structural split | 5 |
| §3.2 the 28 sites | 3 (17 dynamic), 5 (2 split + `@slider`), 6 (spec-derived manifest, self-tested) |
| §4 sliders, `band_slider_base`, named writes | 2, 3, 4, 5; writers gated in 10 Step 3 (source), manifest in 10 Step 2 |
| §5 GUI: menu, selector, DYN/STATIC, thin outline, cycling | 8 |
| §6.1–6.3 oracle, bounds, addresses | 1, 6 |
| §6.4 null test | 10 |
| §6.5 CPU | 10 |
| §6.6 migration | 9 |
| §6.7 live, reachability matrix | 8, 10 |

**Ordering property:** at the end of every task before 7, the plugin is functionally V1.0 —
`N_BANDS` is 4, the static-only loop runs zero times, the eight-way writers are never called with
`b >= 4`. Every commit is loadable, and every live check before the flip really does prove the
rewrite changed nothing. The flip is one line against code the gate has already verified.

**Dependency check:** no task uses an artifact from a later one. The source gate (6) precedes the
flip it protects (7); `rcbitnova_layout` (1) precedes the gate that imports it (6); `band_slider_base`
(2, 4) precedes the loop that calls it (5); `gc_hits` (3) precedes the cycling that indexes it (8);
migration (9) precedes the null test that uses it (10).

**Placeholder scan:** the site manifest is derived from the spec's rows and asserted name by name,
`eval_init` is implemented and pinned by tests around a page boundary, the cycling algorithm is
whole, the migration script is whole and its branches are enumerated as a FakeReaper table. The null
and CPU harnesses remain tables of pinned mechanics rather than code — every property that could
mask a difference is fixed (float format, dither off, per-track stems, restored render state, a
float-WAV reader, a seeded one-ULP failure test), but the invocation depends on this machine's
render settings and the CPU metric depends on an API that must be proven in Step 1 first.

**Live API facts (measured 2026-08-22, REAPER running).** Nothing in Tasks 9 and 10 now rests on
the review's word or mine:

| Question | Answer |
|---|---|
| `TrackFX_GetPinMappings` | exists; five args; returns a list, retval at `[0]`; default map is `1 << pin` |
| `TrackFX_GetNamedConfigParm` | exists; returns **six** elements, value at `[4]` — not an `(ok, value)` pair |
| `instance_oversample_shift` | readable, `'0'` by default → oversampling is detectable |
| `param.N.mod.active` | ok=0 when clean, ok=1/`'1'` after setting it → modulation is detectable |
| `pdc` | readable via named config |
| `GetUnderrunTime` | exists; returns `[audio_xrun, media_xrun, curtime]` — timestamps, not counts |
| peak block time | **no API exists** — only `GetAudioDeviceInfo` and `GetUnderrunTime` match; CPU is manual |
| `TrackFX_GetFXGUID` | returns a **pointer** that does NOT survive a move — identity must be `guidToString(...)` |

---

## Rev-2 Disposition (first plan weakness review, commit `e0cb25c`)

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

---

## Rev-3 Disposition (second plan weakness review, commit `ea2d5d4`)

| Finding | Disposition |
|---|---|
| **P0-1** Task 6 depends on a gate Task 9 has not created | **Accepted.** The source gate is now Task 6, before the flip (Task 7), and it self-tests against seeded defects. Verified the complaint: the fallback greps check slider arithmetic and forbidden identifiers, and touch neither the 17 `@init` conversions nor any address. |
| **P0-2** Migration copies the wrong `Bypass` | **Accepted — confirmed in the source.** `slider1:0<0,1,1{Off,On}>-Bypass` is declared parameter 0, and the host tail adds another `Bypass` at 95. `_by_name` returned 0. The tail is now addressed **positionally** after its names are validated, and the live check sets host Bypass/Wet to distinctive values precisely because that is the pair the old script skipped. |
| **P1-1** Plan and spec disagree: 13670 vs 13678 | **Accepted.** Neither number is now written in the plugin: the clear span is derived as `gc_hits + 8 - gc_trace`, which is right at four bands (13646) and eight (13678), so the intermediate build stays a real no-op. Spec goes to rev 5 in Task 11. |
| **P1-2** The address model does not run through `lp_base` | **Accepted.** The chain continues through `lp_geo`, `lp_off`, `lp_fs` to `gc_trace`; `lp_base` is asserted `== 65536` rather than merely page-aligned; the GUI interval is checked for ordering, non-overlap, derived span and `end < lp_base`. The negative test now mutates a fixture source and requires the real gate to reject it. |
| **P1-3** Task 9 specified gates rather than implementing them | **Partly accepted.** The 28-entry table is complete and `eval_init` is implemented. The null and CPU harnesses are pinned as tables of mechanics — material, instances, render command, latency source, comparison, statistic, xrun source — rather than code, because those invocations depend on this machine's render settings. That is a deliberate limit, not an oversight. |
| **P1-4** Migration not transactional for arbitrary chains | **Accepted.** Identity is by FX GUID throughout, so the failure path cannot delete a pre-existing V1.1; the move is verified before anything is deleted; multiple V1.0 instances are refused up front. The undo claim is narrowed: grouping is not rollback, every mutation is verified before the next, and the one path that can fail after the source is gone calls a real undo and reports it. Modulation is now detected and refused; pin mappings, aliases and oversampling are declared **undetected**, not "refused". |
| **P1-5** Q Character typed values unquantised | **Accepted.** Clamped and rounded to the declared 0.001 step. V1.0's five existing fields keep their typed-exact behaviour, and changing them is called out as its own version rather than folded in here. |
| **P1-6** The gate does not cover writer safety | **Accepted.** A nine-writer manifest — per-band slider IDs, `setup_band`, the `b < N_DYN` guard — checked in source and exercised for B1–B8 live, with a whole-manifest diff so "no other parameter changed" is checkable. |
| **P1-7** The thinner node outline has no implementation step | **Accepted.** Added as Task 8 Step 4a with the actual `gfx_circle` change, plus a Retina check across all four enabled/disabled × DYN/STATIC combinations. |
| **P2-1** `GuardedMemory` detects only one-word overruns | **Accepted.** Rewritten as ownership-aware `read(name, offset)` / `write(name, offset)`, rejecting every offset outside the named array's span, running against the **production** layout. A new test drives `cf[64]`, `cf[65]`, `cf[71]` and `cf[95]` — the jumps the guard-word design let through. `shadow_layout` survives with its claim narrowed to a spacing model. |

---

## Rev-4 Disposition (third plan weakness review, commit `6dda781`)

| Finding | Disposition |
|---|---|
| **P0-1** The pre-flip gate is required to fail | **Accepted.** Excusing a row made the same command in Task 7 prove nothing, and the `gc_fc` delta was phase-inconsistent too. Replaced with the review's own better option: `--preflip` builds an in-memory **projection** with `N_BANDS = 4` → `8` and runs the *full post-flip contract* against it. Nothing is excused; Task 7 re-runs identical assertions on the real text. |
| **P0-2** `eval_init` computes `ceil()` incorrectly | **Accepted — reproduced.** `-(-int(x) // 1)` truncates before ceiling: `ceil(51913/65536)` returned **0**, so the gate evaluated `lp_base` as 0 and would have failed its own assertion in both phases. Now `math.ceil`, with tests below, at and above a page boundary plus the shipped `lp_base` expression. |
| **P0-3** The "28-site table" omits the dangerous runtime sites | **Accepted — confirmed by grep.** Rev 3 reached 28 by *adding* `N_DYN`/`gc_kc`/`gc_fc` while omitting the `@sample` band loop (1290), the Mode-B pass (1489) and all three `@gfx` loops (1675, 1749, 1828). The Mode-B scan regex was also unmatchable: that loop opens with `mbmode[b] = slider(50 + 10 * b + 7);`, not the `any_b` line. Now a named manifest derived one-to-one from spec §3.2, with extra invariants counted separately, `len(SPEC_SITES) == 28` asserted, and seeded defects in **every runtime loop**. |
| **P0-4** Migration can fail before entering its rollback block | **Accepted.** `add_fx` and the GUID read moved inside `try`; `dst_guid = None` initialised; `finally` closes the undo block exactly once on every path; a `None` return is an explicit branch. The FakeReaper table asserts "one opened, one closed" per branch — the assertion rev 3's structure could not make. |
| **P0-5** The CPU gate rests on metrics that do not exist | **Accepted.** `GetSetProjectInfo` carries render/project settings, not Performance Meter values, so the gate had no data source while reading as though it did. Task 10 now **proves the API first** and branches: automated if peak block time is queryable, otherwise a documented manual Performance Meter protocol with the same runs and statistic. Xruns use `GetUnderrunTime` as **timestamps, not a counter** — read before and after, any change fails — and an induced-xrun test is mandatory, because a failure signal never seen to move is not a signal. |
| **P1-1** The address gate does not compare the complete GUI map | **Accepted.** Every GUI base is now compared exactly to `model_gui` (rev 3 computed it and never used it); the derived clear expression is asserted as an expression, so a literal there is itself the defect; `check_source`, `check_sites`, `check_forbidden`, `check_addresses` and `SEEDED_DEFECTS` are written out, with seeded defects in the GUI bases. |
| **P1-2** The parameter record omits step and default | **Accepted.** `p.formatted` was the current value's display string. Defaults now come from an independently fresh instance read before any probe; the original value is restored **and verified**; round trips must land on the declared grid and `formatted` must differ between the extremes. |
| **P1-3** The writer gate cannot invoke a GUI writer | **Accepted.** True — `reapy` sets host parameters, and doing so bypasses the writer under test. Writer correctness became a complete **source** gate (slider numbers per band, `slider_automate`, `setup_band`, the `b < N_DYN` guard, all nine writers), and the gesture-level reachability check is labelled what it always was: manual. |
| **P1-4** The null gate can quantise a residual away | **Accepted.** 32-bit float render, dither and normalization off, per-track stems, every `RENDER_*` property saved and restored (and asserted restored), completion detected by file size plus header frame count rather than a sleep, and a float-WAV reader written here because `wave` rejects format 3. The fixture is now a named committed artifact with a generator. A **one-ULP seeded difference must fail the comparator** — otherwise the format is quantising and the gate is decorative. |
| **P1-5** Destructive migration has no offline tests | **Accepted, and it is the project's standing rule.** `_reaper_fakes.py` has 62 functions and no `TrackFX_*`, so the fake gains FX enumeration, add/move/delete, GUIDs, parameters, named config, enabled/offline and undo counters. Nine branches are enumerated with the expected chain, undo balance and return value, all asserted before REAPER is touched. |
| **P1-6** Detectable host state is silently discarded | **Accepted, and now measured.** Both APIs exist. Pin mappings take five arguments and return a list (retval at `[0]`, default `1 << pin`); `TrackFX_GetNamedConfigParm` returns **six** elements with the value at `[4]`, so rev 4's `ok, value = …` unpack was itself wrong. Oversampling and modulation are both genuinely detectable — a clean instance answers ok=0, and after setting `param.0.mod.active` it answers ok=1/`'1'`. All four now refuse; only parameter aliases stay in the warning. |
| **P1-7** The selector strip shares the node click area | **Accepted — confirmed.** `gc_fy = gc_py + gc_ph + 6 * gc_sc`, so the proposed strip occupied the bottom 18 logical pixels **of the plot**, where nodes can sit, and node click/drag run earlier in the frame. Moved below the plot, with an explicit `gc_strip_hot` owner computed *before* node event handling that clears `gc_hover`/`gc_hit_n`. An edge-clamped case joins the matrix. |
| **P1-8** Spec rev 5 leaves §6.7 contradicted | **Accepted.** The rev-5 update now covers three things: the derived clear span, §6.7's prefix claim (declared-by-index plus a positional host tail), and §5's node rendering rule as built. |
| **P2-1** The static node gains an outline instead of a thinner one | **Accepted.** One primitive, two styles: body unchanged, outline drawn as 2 rings for dynamic bands and 1 for static-only. Thickness is the redundant cue; the `DYN`/`STATIC` tag remains the accessible one. |
| **P2-2** The one-node cycling expectation contradicts the algorithm | **Accepted.** The counter does advance; `% 1` keeps the selection. Matrix row restated as "selection unchanged regardless of counter value". |

---

## Rev-5 Disposition (live API pass, REAPER running, 2026-08-22)

No new review. Rev 4 left three APIs used on the reviewer's word because REAPER was down; with it
running, every one was checked, and two of the answers changed the plan.

| Assumption in rev 4 | Measured | Consequence |
|---|---|---|
| `TrackFX_GetFXGUID` is a usable identity | **False.** It returns a pointer (`(GUID*)0x…`). After `TrackFX_CopyToTrack(..., is_move=True)` the destination slot's pointer is a different value, so every post-move lookup by that pointer fails. | **The migration's whole identity design was broken.** Identity is now `guidToString(TrackFX_GetFXGUID(...), "")[1]`, the real GUID string, verified to follow the FX across a move: `{99F84DA4-…}` before, `{99F84DA4-…}` at index 0 after. |
| `TrackFX_GetNamedConfigParm` returns `(ok, value)` | **False.** Six elements: `[ok, track, fx, key, value, buflen]`. | Rev 4's `ok, value = …` unpack would have raised on first use. Added `_cfg()`; this is the same shape trap that cost a live session on `GetUserInputs`. |
| `TrackFX_GetPinMappings(track, fx, isout, pin)` | Takes **five** args (`high32`) and returns a list; retval at `[0]`; default map is `1 << pin`. | Signature and comparison corrected. |
| modulation may be undetectable | Detectable: clean → ok=0/`''`; after `SetNamedConfigParm('param.0.mod.active', '1')` → ok=1/`'1'`. | Moved from "warning" to "refused" honestly. |
| `instance_oversample_shift` | Readable, `'0'` by default. | Refused. |
| `GetUnderrunTime` is a counter | Timestamps: `[audio_xrun, media_xrun, curtime]`, e.g. `[0, 0, 712432281]`. | Before/after comparison, any change fails. |
| peak block time is queryable somewhere | **No.** The only matching functions on this build are `GetAudioDeviceInfo` and `GetUnderrunTime`. | The manual Performance Meter protocol is not a fallback — it is the only branch. Recorded as measured, not assumed. |

Probe hygiene: every instance added for these measurements was removed, and the track was verified
empty afterwards.
