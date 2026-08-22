# RCBitNova V1.1 — Eight Fully Dynamic Bands: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development or
> superpowers:executing-plans to implement this task-by-task. Steps use `- [ ]` for tracking.

**Revision 1**, 2026-08-22. **Supersedes** `2026-08-19-rcbitnova-v1.1-eight-bands.md` (rev 5).
That plan built eight *static* bands with dynamics on the first four; four review rounds of its
`N_DYN` split produced three P0s that existed only because of the split. Everything it learned that
still applies — the gate design, the migration, the live API facts, the GUI work — is carried over
here.

**Goal:** eight identical bands. Static SVF, Mode A, Mode B, both ceilings, detector, placement,
proportional Q on every one.

**Spec:** `docs/superpowers/specs/2026-08-22-rcbitnova-v1.1-eight-dynamic-bands-design.md` (rev 1).

## Global Constraints

- **New file `JSFX/RCBitNova V1.1`, an exact copy of `JSFX/RCBitNova V1.0`.** V1.0 is frozen and
  tagged; `rcbitnova-v1.0` is the fallback.
- **`N_BANDS` stays 4 until Task 5.** Every preparatory change — the re-based arrays, the 80 new
  sliders, the base tables, the converted reads, the eight-way writers — is made while the plugin is
  still a four-band plugin and therefore still byte-identical in behaviour. The flip is one line
  against code the gate has already verified against an eight-band projection.
- **Bands 1–4 keep every slider number.** REAPER stores parameters by number.
- **New declarations go after every existing one** (verified live: the host numbers parameters
  densely in declaration order).
- **Reads go through the base tables `stb`/`dynb`/`ceb`; writes are explicit named `sliderNN`.**
  No `10*(b+1)`, `50+10*b` or `90+10*b` survives outside `@init`.
- **Every assignment inside a ternary branch is parenthesised. No bit-shift operators.** Family
  conventions from `Fable Eq Dynamic`; V0.8's version of the ternary defect passed the oracle and a
  full review before the CPU meter caught it.
- **EEL2 resolves functions in file order** — four V1.0 builds broke on this.
- **`lp_base` moves 65536 → 131072.** A 32768-point FFT buffer off a 65536-word page corrupts
  **silently**. The gate asserts the number; Task 9 verifies it with audio.
- **Measured, not assumed (reapy, live, 2026-08-19/22):** the host reports 98 parameters for V1.0 —
  95 declared then `Bypass`, `Wet`, `Delta`. V1.1 will report 178. Only the declared block is a
  prefix. `TrackFX_GetNamedConfigParm` returns **six** elements (value at `[4]`);
  `TrackFX_GetPinMappings` takes five arguments and returns a list (retval at `[0]`, default
  `1 << pin`); `GetUnderrunTime` returns `[audio_xrun, media_xrun, curtime]` — timestamps;
  `TrackFX_GetFXGUID` returns a **pointer that does not survive a move** — identity is
  `guidToString(...)`; there is **no peak-block-time API**.
- **Never claim a task is done without running its test and reading the output.**
- Run from the worktree root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. All 221 existing
  tests stay green at every commit.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/rcbitnova_layout.py` | NEW. The memory map as data: the low map, the base tables, the derived chain through `lp_base`, the GUI block, and `GuardedMemory`. | Create |
| `tools/rcbitnova_curve.py` | Gains the three slider-base tables. | Modify |
| `tools/rcbitnova_gates.py` | NEW. `--preflip`/`--source-only`: site manifest, forbidden reads, writer manifest, computed addresses; self-tested. `--live`: parameter manifest. | Create |
| `tools/migrate_v10_to_v11.py` | NEW. 95 declared by index, host tail by position, identity by GUID string, transactional. | Create |
| `tools/rcbitnova_nulltest.py` | NEW. Float render, equal-latency check, zero-tolerance compare. | Create |
| `tools/rcbitnova_cpu.py` | NEW. Validates a manual Performance Meter run; xruns via `GetUnderrunTime`. | Create |
| `tools/make_null_fixture.py`, `tests/fixtures/null_30s.wav` | NEW. Deterministic material. | Create |
| `tests/test_rcbitnova_dsp.py` | V1.1 block appended. | Modify |
| `JSFX/RCBitNova V1.1` | The plugin. | Create, then Tasks 3–6, 8 |

---

### Task 1: The memory map as data

**Files:** create `tools/rcbitnova_layout.py`; append to `tests/test_rcbitnova_dsp.py`

**Produces:** `LOW`, `low_layout(n)`, `base_tables(n)`, `audio_layout(n)`, `gui_layout(base, n)`,
`GuardedMemory`, `model_band_access`.

- [ ] **Step 1: Write the failing tests**

```python
from tools import rcbitnova_layout as lay   # noqa: E402


def test_v11_low_map_reproduces_the_shipped_four_band_addresses():
    """The model must produce V1.0's own numbers or it is describing another plugin."""
    m = lay.low_layout(4)
    assert m["cf"][0] == 0 and m["st"][0] == 64 and m["det"][0] == 96
    assert m["dst"][0] == 128 and m["cst"][0] == 160 and m["dp"][0] == 192
    assert m["dm"][0] == 208 and m["bp"][0] == 216 and m["eg"][0] == 256


def test_v11_eight_bands_move_only_dm_and_bp():
    """Five of seven dynamic arrays keep their base - the four-band spacing was already wide
    enough. Only dm and bp are re-based, and that is the whole low-map change."""
    m = lay.low_layout(8)
    assert m["cf"] == (0, 63) and m["st"] == (64, 95)
    assert m["det"][0] == 96 and m["dst"][0] == 128 and m["cst"][0] == 160
    assert m["dp"][0] == 192 and m["eg"][0] == 256
    assert m["dm"][0] == 224 and m["bp"][0] == 232
    assert m["eg"][1] == 271


def test_v11_low_map_leaves_room_below_mb_band():
    m = lay.low_layout(8)
    end = max(hi for _, hi in m.values()) + 1
    assert end == 272
    assert 1024 - end == 752, "mb_band is a literal 1024; this is the slack the tables live in"


def test_v11_the_real_ceiling_is_ten_bands_not_eight():
    """Both earlier versions of "eight is the maximum" were asserted, not computed, and both were
    wrong. Memory holds ~34 bands; the slider budget holds nine (scattered across the free runs);
    ten is where it actually breaks. Eight is a product decision, and this test records that
    honestly so nobody later "discovers" headroom and assumes it was overlooked."""
    assert max(hi for _, hi in lay.low_layout(9).values()) + 1 == 306, "memory is not the limit"
    assert lay.check_capacity(8) == []
    assert lay.check_capacity(9) == [], "a ninth band fits, on scattered bases"
    problems = lay.check_capacity(10)
    assert problems and any("slider" in p for p in problems), problems


def test_v11_base_tables_keep_the_old_bands_and_stay_under_256():
    t = lay.base_tables(8)
    assert t["stb"][:4] == [10, 20, 30, 40]
    assert t["dynb"][:4] == [50, 60, 70, 80]
    assert t["ceb"][:4] == [90, 100, 110, 120]
    assert t["stb"][4:] == [150, 160, 170, 180]
    assert t["dynb"][4:] == [190, 200, 210, 220]
    assert t["ceb"][4:] == [230, 234, 238, 242]      # stride 4: at 10, band 8 would hit 261
    highest = max(t["stb"][b] + 9 for b in range(8))
    highest = max(highest, max(t["dynb"][b] + 8 for b in range(8)))
    highest = max(highest, max(t["ceb"][b] + 3 for b in range(8)))
    assert highest == 245, highest


def test_v11_new_sliders_do_not_collide_with_anything_existing():
    used = set(range(1, 5)) | set(range(11, 50)) | set(range(51, 89)) \
        | set(range(91, 124)) | set(range(131, 143))
    t = lay.base_tables(8)
    new = set()
    for b in range(4, 8):
        new |= {t["stb"][b] + o for o in range(1, 10)}
        new |= {t["dynb"][b] + o for o in range(1, 9)}
        new |= {t["ceb"][b] + o for o in range(1, 4)}
    assert not (new & used), sorted(new & used)
    assert len(new) == 80


def test_v11_audio_chain_grows_exactly_as_the_spec_says():
    a, b = lay.audio_layout(4), lay.audio_layout(8)
    assert a["mb_peak"] == 17408 and b["mb_peak"] == 33792
    assert a["mb_end"] == 33792 and b["mb_end"] == 66560
    assert a["gc_trace"] == 38275, "V1.0's own comment records 38275"
    assert b["gc_trace"] == 71087


def test_v11_lp_base_moves_one_page_and_stays_aligned():
    """The single most dangerous consequence: a 32768-point FFT off a 65536-word page corrupts
    SILENTLY. Pin both values, not just the modulus."""
    four = lay.gui_layout(lay.audio_layout(4)["gc_trace"], 4)
    eight = lay.gui_layout(lay.audio_layout(8)["gc_trace"], 8)
    assert four["lp_base"] == 65536
    assert eight["lp_base"] == 131072
    assert eight["lp_base"] % 65536 == 0
    assert eight["gc_hits"] + 8 <= eight["lp_base"]


def test_v11_gui_model_reproduces_the_shipped_clear_span():
    """V1.0 clears exactly 13638 words. Derived, the span is 13646 at four bands and 13678 at
    eight - which is why the plugin must compute it rather than carry a literal."""
    base = lay.audio_layout(4)["gc_trace"]
    assert lay.gui_layout(base, 4)["clear_span"] - 8 == 13638
    assert lay.gui_layout(base, 4)["clear_span"] == 13646
    assert lay.gui_layout(lay.audio_layout(8)["gc_trace"], 8)["clear_span"] == 13678


def test_v11_all_eight_bands_access_every_array_in_bounds():
    mem = lay.GuardedMemory(lay.low_layout(8))
    for b in range(8):
        lay.model_band_access(mem, b)               # static AND dynamic: every band is equal now


def test_v11_a_ninth_band_is_rejected_by_the_instrument():
    mem = lay.GuardedMemory(lay.low_layout(8))
    try:
        lay.model_band_access(mem, 8)
    except AssertionError as e:
        assert "cf[64] leaves its span 0..63" in str(e), e
    else:
        raise AssertionError("a ninth band must be rejected")


def test_v11_an_overrun_that_clears_a_guard_word_is_still_caught():
    """Ownership checking, not sentinels: cf is indexed b*8, so a wrong band jumps well past any
    single guard word."""
    mem = lay.GuardedMemory(lay.low_layout(8))
    for name, off in (("cf", 64), ("cf", 71), ("st", 32), ("dm", 8), ("bp", 24), ("eg", 16)):
        try:
            mem.write(name, off, 1.0)
        except AssertionError:
            continue
        raise AssertionError(f"{name}[{off}] must be rejected at eight bands")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v11`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.rcbitnova_layout'`.

- [ ] **Step 3: Implement `tools/rcbitnova_layout.py`**

```python
"""RCBitNova's memory map as data rather than as comments.

Every address here is a literal in the JSFX @init block. Keeping a machine-readable copy is what
lets tests assert adjacency and lets the gate compare word indices instead of eyeballing text -
three reviews of the previous design each found an address claim that was wrong when checked, and
one of those was in an earlier version of this very file (it omitted gc_lin, 8192 words).

Words, not bytes: EEL2 memory is word-indexed.
"""

import math

MAX_LOOK = 2048
GC_N = 512
GC_LIN_N = 2048
GC_TRACE_WORDS = 2 * 5 * GC_N            # 5120

# The low map, in layout order: name -> words per band. Every one of these is sized by the band
# count now; there is no second count.
LOW = [("cf", 8), ("st", 4), ("det", 4), ("dst", 4), ("cst", 4),
       ("dp", 4), ("dm", 1), ("bp", 3), ("eg", 2)]

# V1.0's shipped bases, kept so the model can prove it describes THIS plugin.
V10_BASES = {"cf": 0, "st": 64, "det": 96, "dst": 128, "cst": 160,
             "dp": 192, "dm": 208, "bp": 216, "eg": 256}


def low_layout(n_bands):
    """name -> (first word, last word inclusive).

    Arrays keep their V1.0 base wherever the previous array still fits underneath it; otherwise
    they are pushed up. At four bands that reproduces V1.0 exactly; at eight, only dm and bp move.
    """
    out, p = {}, 0
    for name, per in LOW:
        base = max(V10_BASES[name], p)
        out[name] = (base, base + n_bands * per - 1)
        p = base + n_bands * per
    return out


# Numbers bands 1-4 already own, plus the globals and the filter section. Immovable: REAPER
# stores parameters by number.
RESERVED = (set(range(1, 5)) | set(range(11, 50)) | set(range(51, 89))
            | set(range(91, 124)) | set(range(131, 143)))
PER_BAND_BLOCKS = (9, 8, 3)          # static, dynamics, ceilings


def check_capacity(n_bands):
    """Empty when this band count fits. Reports BOTH real constraints.

    The superseded design said eight was the maximum because cf would overrun st. That was true
    only while det was pinned at 96; here arrays float, and the low map would hold ~34 bands. The
    binding constraint is the 256-slider limit against blocks that must be contiguous.
    """
    problems = []
    end = max(hi for _, hi in low_layout(n_bands).values()) + 1
    if end > 1024:
        problems.append(f"low map ends at {end}, past mb_band's literal 1024")

    taken = set(RESERVED)
    t = base_tables(min(n_bands, 8))
    for b in range(4, min(n_bands, 8)):
        taken |= {t["stb"][b] + o for o in range(1, 10)}
        taken |= {t["dynb"][b] + o for o in range(1, 9)}
        taken |= {t["ceb"][b] + o for o in range(1, 4)}
    free = sorted(n for n in range(1, 257) if n not in taken)
    for _ in range(max(0, n_bands - 8)):
        for width in PER_BAND_BLOCKS:
            run = _longest_run(free)
            if run < width:
                problems.append(
                    f"slider budget: a band needs a contiguous run of {width}; "
                    f"the longest free run is {run} ({len(free)} numbers left below 256)")
                return problems
            free = _consume_run(free, width)
    return problems


def _longest_run(free):
    best = run = 0
    for a, b in zip(free, free[1:]):
        run = run + 1 if b == a + 1 else 0
        best = max(best, run + 1)
    return best if free else 0


def _consume_run(free, width):
    for i in range(len(free) - width + 1):
        block = free[i:i + width]
        if block[-1] - block[0] == width - 1:
            return free[:i] + free[i + width:]
    return free


def base_tables(n_bands):
    """The three slider-base tables, exactly as @init must fill them.

    Ceilings use a stride of 4 above band 4: they are only three sliders wide, and at stride 10
    band 8 would need 261, past the 256 limit.
    """
    stb = [10 * (b + 1) if b < 4 else 150 + 10 * (b - 4) for b in range(n_bands)]
    dynb = [50 + 10 * b if b < 4 else 190 + 10 * (b - 4) for b in range(n_bands)]
    ceb = [90 + 10 * b if b < 4 else 230 + 4 * (b - 4) for b in range(n_bands)]
    return {"stb": stb, "dynb": dynb, "ceb": ceb}


AUDIO_CHAIN = [
    ("mb_band", None, None),                                   # literal 1024
    ("mb_peak", "mb_band", lambda n: n * 2 * MAX_LOOK),
    ("mb_end", "mb_peak", lambda n: n * 2 * MAX_LOOK),
    ("mbenv", "mb_end", lambda n: 0),
    ("mbmode", "mbenv", lambda n: n * 2),
    ("mbwpos", "mbmode", lambda n: n),
    ("bus_dry", "mbwpos", lambda n: n),
    ("mbgc", "bus_dry", lambda n: MAX_LOOK * 2),
    ("mbeh", "mbgc", lambda n: n * 2),
    ("hc", "mbeh", lambda n: n * 2),
    ("egh", "hc", lambda n: n),
    ("hplp_state", "egh", lambda n: n * 2),
    ("hplp_cf", "hplp_state", lambda n: 72),
    ("lp_rt", "hplp_cf", lambda n: 126),
    ("lp_kc", "lp_rt", lambda n: 16),
    ("lp_ks", "lp_kc", lambda n: 63),
    ("lp_geo", "lp_ks", lambda n: 18),
    ("lp_off", "lp_geo", lambda n: 8),
    ("lp_fs", "lp_off", lambda n: 32),
    ("gc_trace", "lp_fs", lambda n: 8),
]


def audio_layout(n_bands):
    """Every derived base from mb_band through gc_trace, the bridge into the GUI block.

    Stopping this chain early hides exactly the errors it exists to catch: `lp_base % 65536 == 0`
    is satisfied by a wrong address as happily as by the right one.
    """
    out = {"mb_band": 1024}
    for name, prev, size in AUDIO_CHAIN[1:]:
        out[name] = out[prev] + size(n_bands)
    return out


def gui_layout(gc_trace_base, n_bands):
    """The GUI block. gc_kc is the one address that grows with the band count."""
    gc_lin = gc_trace_base + GC_TRACE_WORDS
    gc_snap = gc_lin + 2 * 2 * GC_LIN_N          # 8192 - omitting this was a real defect
    gc_meta = gc_snap + 128
    gc_kc = gc_meta + 16
    gc_fc = gc_kc + n_bands * 8
    gc_ebuf = gc_fc + 126
    gc_hits = gc_ebuf + 24
    return {"gc_lin": gc_lin, "gc_snap": gc_snap, "gc_meta": gc_meta, "gc_kc": gc_kc,
            "gc_fc": gc_fc, "gc_ebuf": gc_ebuf, "gc_hits": gc_hits,
            "lp_base": math.ceil((gc_hits + 8) / 65536) * 65536,
            "clear_span": gc_hits + 8 - gc_trace_base}


class GuardedMemory:
    """Ownership-aware word memory: every access names the array it believes it is touching, and
    any offset outside that array's span raises.

    A guard-word design catches an overrun of exactly one word and lets a longer jump land silently
    in the next array - which is the actual failure mode here, since cf is indexed b*8 and the
    arrays are adjacent with no slack.
    """

    def __init__(self, spans):
        self.spans = spans
        self.cells = {}

    def _addr(self, name, offset, what):
        first, last = self.spans[name]
        if offset < 0 or first + offset > last:
            raise AssertionError(f"{what} {name}[{offset}] leaves its span {first}..{last}")
        return first + offset

    def write(self, name, offset, value):
        self.cells[self._addr(name, offset, "write")] = value

    def read(self, name, offset):
        return self.cells.get(self._addr(name, offset, "read"), 0.0)


def model_band_access(mem, b):
    """Everything one band touches, indexed exactly as the JSFX does. With eight uniform bands this
    is the same set for every band - which is the whole point of the design."""
    for k in range(8):
        mem.write("cf", b * 8 + k, 1.0)
    for name, per in (("st", 4), ("det", 4), ("dst", 4), ("cst", 4), ("dp", 4),
                      ("dm", 1), ("bp", 3), ("eg", 2)):
        for k in range(per):
            mem.read(name, b * per + k)
            mem.write(name, b * per + k, 0.0)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 233 passed (221 + 12).

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_layout.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.1 memory map as data - eight uniform bands, ownership-checked"
```

---

### Task 2: Slider-base tables in the curve oracle

**Files:** modify `tools/rcbitnova_curve.py`; append tests

- [ ] **Step 1: Failing tests**

```python
def test_v11_curve_uses_the_same_bases_as_the_layout_model():
    """One source of truth. Two copies of this table is how a band ends up editing another
    band's parameter."""
    assert curve.STB == lay.base_tables(8)["stb"]
    assert curve.DYNB == lay.base_tables(8)["dynb"]
    assert curve.CEB == lay.base_tables(8)["ceb"]


def test_v11_curve_reads_band_five_from_the_new_range():
    assert curve.band_slider(4, 3) == 153        # B5 Freq
    assert curve.band_slider(0, 3) == 13         # B1 Freq, unchanged
```

- [ ] **Step 2: Run, see them fail. Step 3: implement**

```python
from tools.rcbitnova_layout import base_tables

_T = base_tables(8)
STB, DYNB, CEB = _T["stb"], _T["dynb"], _T["ceb"]


def band_slider(b, offset):
    """Static-block slider number for band b. READS only - the JSFX writes through explicit named
    sliders, because V1.0 proved live that assigning through a computed index never reaches the
    parameter."""
    return STB[b] + offset
```

- [ ] **Step 4: Run.** Expected: 235 passed. **Step 5: Commit.**

---

### Task 3: `JSFX/RCBitNova V1.1` — everything except the count

**Files:** create `JSFX/RCBitNova V1.1`

**`N_BANDS` stays 4 for this whole task.** Every change below is behaviour-preserving at four
bands, which is what makes it safe to load and commit.

- [ ] **Step 1: Create the file**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
cp "JSFX/RCBitNova V1.0" "JSFX/RCBitNova V1.1"
```

Change `desc:` to `V1.1` and append ` + 8 bands`.

- [ ] **Step 2: Re-base `dm` and `bp`**

```eel2
dm  = 224;  // was 208: dp needs 32 words at eight bands
bp  = 232;  // was 216: dm needs 8
```

At four bands these simply sit higher in free space — no behaviour change. `det`, `dst`, `cst`,
`dp` and `eg` keep their V1.0 bases.

- [ ] **Step 3: The base tables**

Place them after the low-map literals, before any function that reads them:

```eel2
stb = 272; dynb = 280; ceb = 288;        // 8 words each, below mb_band's literal 1024
b = 0;
loop(N_BANDS,
  stb[b]  = b < 4 ? 10 * (b + 1) : 150 + 10 * (b - 4);
  dynb[b] = b < 4 ? 50 + 10 * b  : 190 + 10 * (b - 4);
  ceb[b]  = b < 4 ? 90 + 10 * b  : 230 + 4  * (b - 4);   // stride 4: at 10, B8 would need 261
  b += 1;
);
```

A table, not a helper: these are read in `@sample` per band per sample, and a memory read costs
less than a call plus a branch.

- [ ] **Step 4: Grow the GUI scratch, add the hit set, derive the clear span**

```eel2
gc_kc    = gc_meta + 16;              // N_BANDS * 8 words: the GUI's OWN band coefficients
gc_fc    = gc_kc + N_BANDS * 8;       // 126 words
gc_ebuf  = gc_fc + 126;               // 24 words
gc_hits  = gc_ebuf + 24;              // 8 words: nodes under the cursor this frame (Task 6)
```

```eel2
memset(gc_trace, 0, gc_hits + 8 - gc_trace);
```

Never a literal: 13646 at four bands, 13678 at eight, and a wrong constant here is silent.

- [ ] **Step 5: Declare the 80 new sliders, after every existing one**

Per band: 9 static, 8 dynamics, 3 ceilings — mirroring bands 1–4 exactly. B5 shown; repeat for
B6/B7/B8 with the bases from §4 of the spec and default frequencies 150 / 700 / 5000 / 15000:

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
slider191:0<0,1,1{Off,On}>-B5 Dyn
slider192:0<0,2,1{Linked,Dual L/R,Dual M/S}>-B5 Dyn Stereo (Both only)
slider193:1<0,16,1>-B5 Soft Ceiling Macro (bits below 0)
slider194:0<-100,100,0.1>-B5 Soft Ceiling Micro (% bit)
slider195:1<0.05,50,0.01>-B5 Attack (ms)
slider196:80<1,500,1>-B5 Release (ms)
slider197:0<0,1,1{A Dynamic EQ,B Band-Split}>-B5 Dyn Mode
slider198:1<0,1,1{Off,On}>-B5 Soft
slider231:0<0,1,1{Off,On}>-B5 Hard
slider232:0<0,16,1>-B5 Hard Ceiling Macro (bits below 0)
slider233:0<-100,100,0.1>-B5 Hard Ceiling Micro (% bit)
```

- [ ] **Step 6: Convert every open-coded read to a table read**

From `grep -nE '10 ?\* ?\(|50 \+ 10|90 \+ 10' "JSFX/RCBitNova V1.0"` — all of them, in `@init`
helpers, `@slider`, `@sample` and `@gfx`:

| Section | V1.0 form | Becomes |
|---|---|---|
| `band_qeff`, `setup_band`, `gc_band_setup`, `gc_band_bits`, `gc_domain_bits`, `gc_dom_used` | `10 * (b + 1)` | `stb[b]` |
| `setup_band_dyn` | `s = 10 * (b + 1); ds = 50 + 10 * b;` | `s = stb[b]; ds = dynb[b];` |
| `@slider` Mode-B scan | `slider(50 + 10*b + 7)`, `slider(90 + 10*b + 2)` | `slider(dynb[b] + 7)`, `slider(ceb[b] + 2)` |
| `@sample` band loop | `slider(10 * (b + 1) + …)` | `slider(stb[b] + …)` |
| `@sample` Mode-B pass | `slider(50 + 10*b + 1)`, `slider(10*(b+1)+8)` | `slider(dynb[b] + 1)`, `slider(stb[b] + 8)` |
| `@gfx` hit-test, click-to-enable, drag capture, drag read, wheel-Q, node draw, readout | `10 * (gc_b + 1)` etc. | `stb[gc_b]` etc. |

The `@gfx` group is eight sites and the one the previous design's first draft missed entirely;
unconverted, B5–B8 would read sliders 51–89 — bands 1–4's dynamics controls.

- [ ] **Step 7: Make every GUI writer eight-way**

For `gc_w_enable`, `gc_w_type`, `gc_w_freq`, `gc_w_q`, `gc_w_macro`, `gc_w_micro`, `gc_w_ratio`,
`gc_w_place`, `gc_w_qchar` — nine writers, eight explicit named branches each. No `N_DYN` guard:
every band has dynamics, so `setup_band_dyn(b)` is always correct.

```eel2
function gc_w_macro(b, v, qz) (
  qz ? ( v = gc_q_step(v, 1); );
  b == 0 ? ( slider15  = v; slider_automate(slider15);  ) :
  b == 1 ? ( slider25  = v; slider_automate(slider25);  ) :
  b == 2 ? ( slider35  = v; slider_automate(slider35);  ) :
  b == 3 ? ( slider45  = v; slider_automate(slider45);  ) :
  b == 4 ? ( slider155 = v; slider_automate(slider155); ) :
  b == 5 ? ( slider165 = v; slider_automate(slider165); ) :
  b == 6 ? ( slider175 = v; slider_automate(slider175); ) :
           ( slider185 = v; slider_automate(slider185); );
  setup_band(b);
  setup_band_dyn(b);
);
```

V1.0's writers branch B1–B3 and fall through to B4, so without this every gesture on B5–B8 would
edit B4.

- [ ] **Step 8: Live check — byte-identical behaviour**

Load it. With `N_BANDS` still 4 this is V1.0 with 80 inert parameters appended and two arrays living
8 and 16 words higher. It must load, play and draw exactly as before. The proof is Task 9's null
test; this is the smoke test.

- [ ] **Step 9: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - re-based arrays, base tables, 80 new sliders, eight-way writers"
```

---

### Task 4: The source gate — before anything flips

**Files:** create `tools/rcbitnova_gates.py`

Source-level only; the live gates are Task 9. **One contract, two phases:** the pre-flip run works
on a **projection** — the source text with `N_BANDS = 4` substituted to `8` — and runs the full
post-flip contract against it. Nothing is excused, and Task 5 re-runs identical assertions on the
real file.

```python
def check_source(path, project=False):
    text = open(path, encoding="utf-8", errors="replace").read()
    if project:
        text, n = re.subn(r"^N_BANDS\s*=\s*4;", "N_BANDS = 8;", text, count=1, flags=re.M)
        assert n == 1, f"{path}: no `N_BANDS = 4;` to project from"
    check_sites(text, path)
    check_forbidden(text, path)
    check_writers(text, path)
    check_addresses(text, path)
```

- [ ] **Step 1: `eval_init`**

```python
import ast, math, re

ASSIGN = re.compile(r"^\s*(\w+)\s*=\s*([^;]+);")


def eval_init(text, wanted):
    """name -> word address, evaluated from the text's own @init. Only +, -, *, / and ceil() over
    known names; anything else is skipped, and a `wanted` name that never evaluates raises."""
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

**`math.ceil`, never a hand-rolled one.** The previous plan wrote `-(-int(x) // 1)`, which truncates
before ceiling: `ceil(51913 / 65536)` came out 0, so the gate evaluated `lp_base` as 0 and would
have failed itself. Tests pin it below, at and above a page boundary and against the shipped
`lp_base`.

- [ ] **Step 2: The site manifest**

Far shorter than the split design's, because there is only one count. Every row was **run against
the shipped V1.0 and shown to match** — two rows drafted for the previous plan matched nothing and
shipped anyway.

```python
SITES = {
    "count-declaration":  (r"^N_BANDS\s*=\s*(\d+);", "8"),
    "low-dm":             (r"^dm\s+= (\d+);", "224"),
    "low-bp":             (r"^bp\s+= (\d+);", "232"),
    "gc_fc-sizing":       (r"^gc_fc\s+= gc_kc \+ (\w+) \* 8;", "N_BANDS"),
    "clear-derived":      (r"^memset\(gc_trace, 0, (gc_hits \+ 8 - gc_trace)\);",
                           "gc_hits + 8 - gc_trace"),
    "base-tables":        (r"stb = (\d+); dynb = (\d+); ceb = (\d+);", ("272", "280", "288")),
    "slider-setup":       (r"loop\((\w+), setup_band\(b\); setup_band_dyn\(b\); b \+= 1;\);",
                           "N_BANDS"),
    "slider-modeb-scan":  (r"loop\((\w+),\s*\n\s*mbmode\[b\] = slider\(dynb\[b\] \+ 7\);",
                           "N_BANDS"),
    "sample-band-loop":   (r"  loop\((\w+),\n    slider\(stb\[b\] \+ 1\) == 1 \? \(", "N_BANDS"),
    "sample-modeb-pass":  (r"corrL = 0; corrR = 0;\s*\n\s*b = 0;\s*\n\s*loop\((\w+),", "N_BANDS"),
    "gfx-band-setup":     (r"loop\((\w+), gc_band_setup\(gc_b\); gc_b \+= 1;\);", "N_BANDS"),
    "gfx-hit-test":       (r"gc_hit_n = 0;\s*\ngc_b = 0;\nloop\((\w+),", "N_BANDS"),
    "gfx-node-draw":      (r"loop\((\w+),\s*\n\s*gc_s = [^\n]*\n\s*gc_en = slider\(gc_s \+ 1\);",
                           "N_BANDS"),
    "helper-gc_domain_bits": (r"function gc_domain_bits[\s\S]*?loop\((\w+),", "N_BANDS"),
    "helper-gc_dom_used":    (r"function gc_dom_used[\s\S]*?loop\((\w+),", "N_BANDS"),
}
```

A row matching nothing is a **failure**, not a pass.

- [ ] **Step 3: Forbidden reads and the writer manifest**

```python
FORBIDDEN = [
    (r"10 ?\* ?\((?:b|gc_b|gc_hover|gc_drag|gc_sel) ?\+ ?1\)", "band-slider arithmetic"),
    (r"50 \+ 10 ?\* ?b", "dynamics-slider arithmetic"),
    (r"90 \+ 10 ?\* ?b", "ceiling-slider arithmetic"),
]
```

Exempt only the `@init` block that fills the tables. Everything else must read `stb`/`dynb`/`ceb`.

```python
WRITERS = {"gc_w_enable": 1, "gc_w_type": 2, "gc_w_freq": 3, "gc_w_q": 4, "gc_w_macro": 5,
           "gc_w_micro": 6, "gc_w_ratio": 7, "gc_w_place": 8, "gc_w_qchar": 9}
BASES = [10, 20, 30, 40, 150, 160, 170, 180]
```

Each writer must have eight named `sliderNN` assignments equal to `BASES[b] + offset`, call
`slider_automate`, and call `setup_band(b)` and `setup_band_dyn(b)`. A transcription slip here
writes the wrong band while every site and address assertion still passes — `reapy` cannot catch it
either, because setting a parameter externally bypasses the writer under test.

- [ ] **Step 4: The address gate**

```python
AUDIO = [n for n, _, _ in layout.AUDIO_CHAIN]
GUI = ["gc_lin", "gc_snap", "gc_meta", "gc_kc", "gc_fc", "gc_ebuf", "gc_hits"]

v11 = eval_init(text, AUDIO + GUI + ["lp_base", "stb", "dynb", "ceb"] + list(layout.V10_BASES))
model_audio = layout.audio_layout(8)
model_gui = layout.gui_layout(model_audio["gc_trace"], 8)
model_low = layout.low_layout(8)

for name in AUDIO:
    assert v11[name] == model_audio[name], (name, v11[name], model_audio[name])
for name in GUI:
    assert v11[name] == model_gui[name], (name, v11[name], model_gui[name])
for name, (first, _) in model_low.items():
    assert v11[name] == first, (name, v11[name], first)
assert (v11["stb"], v11["dynb"], v11["ceb"]) == (272, 280, 288)
assert v11["lp_base"] == 131072, "one page up from V1.0 - and it MUST stay page-aligned"
assert v11["gc_hits"] + 8 <= v11["lp_base"]
```

- [ ] **Step 5: Self-test — seed a defect in every class**

| Mutation | Rejected by |
|---|---|
| `dm` left at 208 | `low-dm` **and** the low-map comparison |
| `bp` left at 216 | `low-bp` |
| `gc_fc = gc_kc + 32` | `gc_fc-sizing` and the GUI comparison |
| a literal clear span | `clear-derived` |
| any `@sample` or `@gfx` loop bounded by 4 | its named site row |
| a `10 * (b + 1)` reintroduced in `@gfx` | `FORBIDDEN` |
| a writer's B7 branch pointing at `slider175` instead of `slider176` | `check_writers` |
| `N_BANDS = 8` deleted | `eval_init` raising |

```python
def test_v11_gate_rejects_each_seeded_defect(tmp_path):
    clean = open("JSFX/RCBitNova V1.1").read()
    for n, (mutate, expect) in enumerate(SEEDED_DEFECTS):
        mutated = mutate(clean)
        assert mutated != clean, f"defect {n} ({expect}) did not change the source"
        src = tmp_path / f"mutant{n}"
        src.write_text(mutated)
        with pytest.raises(AssertionError, match=re.escape(expect)):
            gates.check_source(str(src), project=True)
```

The `mutated != clean` line matters as much as the rejection: a seeding lambda whose `replace`
misses silently tests the clean file and passes.

- [ ] **Step 6: Run against the still-four-band V1.1**

```bash
python3 tools/rcbitnova_gates.py --preflip && echo PREFLIP_OK
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "gate or eval_init"
```

Expected: `--preflip` passes **completely**. That is the point of the projection — what Task 5 is
about to do is verified before it is done.

- [ ] **Step 7: Commit**

---

### Task 5: Flip the count

- [ ] **Step 1:** `N_BANDS = 8;`

- [ ] **Step 2: The same contract on the real file**

```bash
python3 tools/rcbitnova_gates.py --source-only && echo SOURCE_OK
```

`--source-only` is `--preflip` without the projection: identical assertions, real text. Anything
failing here was introduced by this one-line edit.

- [ ] **Step 3: Live check — the first eight-band load**

Bands 5–8 disabled by default, so it must still sound like V1.0. Then, for B5: enable it, boost it,
confirm it is audible and on the graph; turn its Dyn on and confirm Mode A pumps; switch it to
Mode B and confirm the band-split limiter engages; set its hard ceiling and confirm it bites.
**Every one of these is new in this design** — under the split, B5 could not do any of it.

- [ ] **Step 4: Commit**

---

### Task 6: GUI — menu, selector strip, cycling, Q field, GR tint

Owner's decisions, 2026-08-22. Carried over from the superseded plan except where the uniform band
count changes them.

- [ ] **Step 1: Compute `gc_rclick` once, beside `gc_click`**

V1.0 computes it at line 1868, inside the HP/LP section, because that was its only consumer. With a
second consumer it must be detected once and routed to exactly one owner:

```eel2
gc_click  = (mouse_cap & 1) && !(gc_last_cap & 1);
gc_rclick = (mouse_cap & 2) && !(gc_last_cap & 2);   // ONE detection, two consumers
```

Delete it from the HP/LP section and guard that consumer: `gc_rclick && gc_hover < 0 && gc_fnode >= 0`
— band nodes are drawn on top, so they own the event.

- [ ] **Step 2: The band context menu**

`gfx_showmenu` takes ONE string; a ternary beside string literals is not concatenation in EEL2.

```eel2
gc_rclick && gc_hover >= 0 ? (
  slider(stb[gc_hover] + 1) == 1 ? ( strcpy(#gc_menu, "Disable band||"); )
                                 : ( strcpy(#gc_menu, "Enable band||"); );
  strcat(#gc_menu, "Bell|Low Shelf|High Shelf||");
  strcat(#gc_menu, ">Placement|Both|Mid|Side|Left|Right|<|");
  strcat(#gc_menu, ">Q Character|0.00 constant|0.25|0.50|0.75|1.00 proportional|<");
  gfx_x = mouse_x; gfx_y = mouse_y;
  gc_bm = gfx_showmenu(#gc_menu);
  gc_bm == 1 ? ( gc_w_enable(gc_hover, slider(stb[gc_hover] + 1) == 1 ? 0 : 1); ) :
  gc_bm >= 2 && gc_bm <= 4 ? ( gc_w_type(gc_hover, gc_bm - 2); ) :
  gc_bm >= 5 && gc_bm <= 9 ? ( gc_w_place(gc_hover, gc_bm - 5); ) :
  gc_bm >= 10 && gc_bm <= 14 ? ( gc_w_qchar(gc_hover, (gc_bm - 10) * 0.25); );
);
```

**Load the plugin the moment this compiles** — V1.0 lost four builds to problems found only at load.

- [ ] **Step 3: Q Character numeric field**

A sixth numeric-entry field reusing `gc_edit`/`gc_ebuf`/`gc_elen`. Typed values are clamped and
**quantised to the declared step**:

```eel2
v = min(max(v, 0), 1);
gc_w_qchar(gc_sel, floor(v / 0.001 + 0.5) * 0.001);
```

Five presets cannot reproduce an existing 0.333; off-grid values cannot be reached from the host.
V1.0 measured what continuous GUI writes cost: **−62 dB of null residue**. Arthur's family rounds
typed entry the same way. V1.0's five existing fields keep their typed-exact behaviour — changing
them is its own version.

- [ ] **Step 4: The eight-button selector strip, below the plot**

V1.0 sets `gc_fy = gc_py + gc_ph + 6 * gc_sc`, so a strip drawn at `gc_fy - 24*gc_sc` sits in the
bottom 18 logical pixels **of the plot**, where nodes can be — and node click-to-enable and
drag-start run earlier in the frame. Put it below, and give it explicit ownership computed **before**
the node event code:

```eel2
gc_sy = gc_fy + 2 * gc_sc;                       // BELOW the plot
gc_strip_hot = (mouse_y >= gc_sy && mouse_y < gc_sy + 18 * gc_sc &&
                mouse_x >= gc_px && mouse_x < gc_px + N_BANDS * 34 * gc_sc);
gc_strip_hot ? ( gc_hover = -1; gc_hit_n = 0; );
```

Then the strip itself, drawn later:

```eel2
gc_b = 0;
loop(N_BANDS,
  gc_bx = gc_px + gc_b * 34 * gc_sc;
  gc_bhot = (mouse_x >= gc_bx && mouse_x < gc_bx + 30 * gc_sc &&
             mouse_y >= gc_sy && mouse_y < gc_sy + 18 * gc_sc);
  gc_sel == gc_b ? ( gfx_set(0.3, 0.45, 0.6, 1); ) : ( gfx_set(0.16, 0.16, 0.18, 1); );
  gc_bhot ? ( gfx_set(0.35, 0.5, 0.66, 1); );
  gfx_rect(gc_bx, gc_sy, 30 * gc_sc, 18 * gc_sc);
  gfx_set(slider(stb[gc_b] + 1) == 1 ? 0.95 : 0.45, 0.9, 0.95, 1);
  gfx_x = gc_bx + 5 * gc_sc; gfx_y = gc_sy + 4 * gc_sc;
  gfx_drawstr("B"); gfx_drawnumber(gc_b + 1, 0);
  gc_click && gc_bhot ? ( gc_sel = gc_b; );
  gc_b += 1;
);
```

No DYN/STATIC tag: every band is dynamic.

- [ ] **Step 5: Live gain-reduction tint on the node**

Adopted from `Fable Eq Dynamic`, where a band's card glows in proportion to current GR. Here it goes
on the node, so the graph shows which bands are working:

```eel2
// Live GR: eg[] holds the Mode-A envelope gain per band (1 = no reduction), mbgc[] the Mode-B
// gain. Tint toward orange in proportion to whichever is reducing.
gc_gr = 1 - min(eg[gc_b * 2], mbgc[gc_b * 2]);
gc_gr > 0.002 ? (
  gc_gl = min(gc_gr * 6, 1);
  gfx_set(1.0, 0.5, 0.12, 0.3 + 0.6 * gc_gl);
  gfx_circle(gc_nx, gc_ny, (8 + 2 * gc_gl) * gc_sc, 0, 1);
);
```

Read-only from `@gfx`, one word per band per frame, no writes — the same thread-safety posture V1.0
accepted for `cf`/`hplp_cf`. **Scope guard:** this is the node tint only. The V1.2 dynamics display
(per-band GR meters, history) is not pulled in.

- [ ] **Step 6: Coincident-node cycling**

`@init`, beside the other GUI state:

```eel2
gc_cyc_n = 0; gc_cyc_x = -1e9; gc_cyc_y = -1e9; gc_cyc_t = -1e9; gc_hit_n = 0;
```

In the node loop, collect the hit set instead of keeping the last match:

```eel2
gc_hit_n = 0;
gc_b = 0;
loop(N_BANDS,
  gc_nx = gc_x_of_f(slider(stb[gc_b] + 3));
  gc_ny = gc_y_of_bits(...);
  (abs(mouse_x - gc_nx) < gc_hit_r && abs(mouse_y - gc_ny) < gc_hit_r) ? (
    gc_hits[gc_hit_n] = gc_b; gc_hit_n += 1;      // disabled nodes included: that is how a
  );                                              // band gets enabled
  gc_b += 1;
);
```

Immediately after that loop — and therefore **before** click-to-enable and drag-start:

```eel2
gc_click ? (
  (abs(mouse_x - gc_cyc_x) < gc_hit_r && abs(mouse_y - gc_cyc_y) < gc_hit_r
   && (time_precise() - gc_cyc_t) < 0.4) ? ( gc_cyc_n += 1; ) : ( gc_cyc_n = 0; );
  gc_cyc_x = mouse_x; gc_cyc_y = mouse_y; gc_cyc_t = time_precise();
);
// Modulo the CURRENT count every frame: the hit set can shrink between clicks.
gc_hit_n > 0 ? ( gc_hover = gc_hits[gc_cyc_n % gc_hit_n]; ) : ( gc_hover = -1; gc_cyc_n = 0; );
```

And a reset on movement without a click, with the other end-of-frame updates:

```eel2
(abs(mouse_x - gc_cyc_x) >= gc_hit_r || abs(mouse_y - gc_cyc_y) >= gc_hit_r) ? ( gc_cyc_n = 0; );
```

- [ ] **Step 7: Live matrix**

| Case | Expected |
|---|---|
| All 20 parameters of B5…B8 from the GUI alone | each confirmed in `Param`, including a typed Q Character of 0.333 |
| One node under the cursor | selection unchanged regardless of counter value |
| Two coincident, both enabled | clicks alternate |
| Three coincident | clicks walk 1 → 2 → 3 → 1 |
| Three coincident, middle disabled | reachable, and one click enables it |
| Click, wait 1 s, click | back to the lowest band |
| Click, move away, return, click | back to the lowest band |
| Coincident nodes, then drag | the drag moves the band the last click selected |
| A node at the plot's bottom edge, strip below it | the strip click selects the band and does **not** enable or drag the node |
| B5 with Mode A pumping | the node tints orange in proportion to GR, and stops when the band is bypassed |

- [ ] **Step 8: Commit**

---

### Task 7: The migration script

**Files:** create `tools/migrate_v10_to_v11.py`

Before the live gates, because Task 9's null test uses it for equal state. Carried over from the
superseded plan with the counts updated: **95 declared → 175 declared**, host tail still three.

All of the following are measured, not assumed:

- `slider1` is itself named `Bypass`, and so is host parameter 95. **A name search finds index 0.**
  The host tail is addressed **positionally**, after validating its names.
- `TrackFX_GetFXGUID` returns a pointer that does **not** survive `TrackFX_CopyToTrack`; identity is
  `guidToString(RPR.TrackFX_GetFXGUID(tr.id, i), "")[1]`, verified to follow an FX across a move.
- `TrackFX_GetNamedConfigParm` returns **six** elements, value at `[4]`.
- `TrackFX_GetPinMappings(tr, fx, isout, pin, high32)` returns a list, retval at `[0]`, default
  `1 << pin`.
- Automation, parameter modulation, non-default pin maps and instance oversampling are all
  detectable and are **refused**. Parameter aliases are not detectable and are declared undetected.

- [ ] **Step 1: Write it** — as in the superseded plan §Task 9, with `N_DECLARED_V11 = 175`, every
  mutation inside `try/finally`, `dst_guid = None` initialised, the undo block closed exactly once
  on every path, and the destination removed by GUID on failure.

- [ ] **Step 2: FakeReaper branch tests BEFORE REAPER**

Project rule. `midi-composition/tests/_reaper_fakes.py` has 62 functions and **no `TrackFX_*`**, so
extend it: FX enumeration, `add_fx`, `TrackFX_CopyToTrack` with `is_move`, delete, GUIDs, parameter
get/set, named config, enabled/offline, and undo counters. Assert the whole chain and the undo
balance for each of: success mid-chain; `add_fx` returns `None`; `add_fx` raises; read-back
mismatch; move lands wrong; failure after the source was deleted; an unrelated V1.1 present; two
V1.0 instances; each refusal.

- [ ] **Steps 3–6:** dry run on a chain where V1.0 is **not** last; real run verifying values,
  defaults, position and the host tail (set host Bypass and Wet to distinctive values first — that
  is the pair a name search skips); the failure matrix; commit.

---

### Task 8: The live gates

**Files:** create `tools/rcbitnova_nulltest.py`, `tools/rcbitnova_cpu.py`,
`tools/make_null_fixture.py`, `tests/fixtures/null_30s.wav`; extend `rcbitnova_gates.py --live`

- [ ] **Step 1: Parameter manifest** — index, name, min, max, step, default and a three-value round
  trip for all 175 declared parameters; defaults read from an independently fresh instance before
  any probe; the original value restored **and verified**. `v11_declared[:95] == v10_declared`;
  `len(v11_declared) == 175`; the host tail checked separately by position.

- [ ] **Step 2: Null test** — `tests/fixtures/null_30s.wav`, 48 kHz, block 512, GUI closed, bands
  5–8 disabled, state transferred by the migration script. **32-bit float** render, dither and
  normalization off, per-track stems, every `RENDER_*` property saved and restored, completion by
  file size plus header frame count, a float-WAV reader written here (`wave` rejects format 3),
  equal reported `pdc` asserted **before** samples, zero tolerance. Cases: defaults; Mode A; Mode B;
  Min and Linear. Assert the case count. **Seed a one-ULP difference and require a failure** — if
  that passes, the format is quantising and the gate is decorative.

- [ ] **Step 3: `lp_base` live** — the check no gate can make. Phase=Linear, Resolution=High on both
  HP and LP, sweep a deep low-cut and a high brickwall, and confirm clean audio and the expected
  analyzer shape. A misaligned 32768-point FFT corrupts silently: it will not error, it will sound
  wrong. This is the one live test that exists specifically because `lp_base` moved to 131072.

- [ ] **Step 4: CPU** — manual Performance Meter protocol read into `cpu_runs.json`, validated by
  `rcbitnova_cpu.py`; five 60-second runs per configuration, first discarded, median of per-run
  peaks, blocks 128 and 512. Gate: **V1.1 with bands 5–8 disabled vs V1.0, within +5 %**. Report but
  do not gate: eight bands with dynamics on vs four — expect roughly double the dynamics share.
  Xruns via `GetUnderrunTime` before and after each run, **any change fails**, and the induced-xrun
  test is mandatory.

- [ ] **Step 5: Run everything, read every output. Step 6: Commit.**

---

### Task 9: Fable review, as-shipped, tag

- [ ] **Step 1:** Fable final review over `JSFX/RCBitNova V1.1`, the diff against V1.0 and the spec.
  Ask for: bit-accuracy verdict; whether any band-slider read still bypasses the tables; whether all
  nine writers are complete and correctly numbered; whether the GR tint reads any array it should
  not; EEL2 function-order traps; and unparenthesised ternary assignments.
- [ ] **Step 2:** Address every P0/P1, re-run Tasks 4 and 8.
- [ ] **Step 3:** Append "As-shipped" to the spec — every live measurement, every deviation and why,
  every defect found live and how. Follow V1.0 §16 as the model.
- [ ] **Step 4:** Update the memory file, commit, tag `rcbitnova-v1.1`, push.

---

## Self-Review

**Ordering property:** at the end of every task before 5, the plugin is functionally V1.0 —
`N_BANDS` is 4, the new sliders are inert, the re-based arrays sit in free space. Every commit is
loadable, and the flip is one line against code the gate has already verified against a projection.

**Dependency check:** the source gate (4) precedes the flip it protects (5); `rcbitnova_layout` (1)
precedes the gate that imports it (4); the base tables (2, 3) precede every read that uses them;
`gc_hits` (3) precedes the cycling that indexes it (6); migration (7) precedes the null test that
uses it (8).

**What this design removes** relative to the superseded plan: `N_DYN` and its 17 sites, the
structural `@sample` split, nine `b < N_DYN` guards, the DYN/STATIC visual language, the
marker-comment convention for `N_DYN`-bounded lines, and the three P0s those produced.

**What it adds:** 44 more sliders, 512 KB, roughly double the dynamics CPU at eight active bands,
and one genuinely dangerous consequence — `lp_base` moving to 131072, which is why Task 8 Step 3
exists.
