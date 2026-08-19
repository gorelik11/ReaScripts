# RCBitNova V1.1 — Eight Bands Implementation Plan

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
- **Never claim a task is done without running its test and reading the output.**
- Run from the worktree root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. All 221 existing tests stay green at every commit.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/rcbitnova_layout.py` | NEW. The memory map as data: base addresses, per-band sizes, ownership (static/dynamic), and an instrumented shadow layout for bounds testing. Kept separate so the map has one machine-readable source instead of living in comments. | Create |
| `tools/rcbitnova_curve.py` | Gains `band_slider_base`. | Modify |
| `tests/test_rcbitnova_dsp.py` | V1.1 test block appended. | Modify |
| `JSFX/RCBitNova V1.1` | The plugin. | Create (copy of V1.0), then modified in Tasks 3–6 |
| `tools/migrate_v10_to_v11.py` | NEW. The one supported migration: copies 95 parameter values from a V1.0 instance to a V1.1 instance, refuses when automation is present. | Create (Task 8) |

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

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 226 passed (221 + 5).

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
Expected: 229 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_curve.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): V1.1 band_slider_base - old bands fixed, new bands above 150"
```

---

### Task 3: `JSFX/RCBitNova V1.1` — the 28 sites and the new sliders

**Files:**
- Create: `JSFX/RCBitNova V1.1` (copy of `JSFX/RCBitNova V1.0`)
- Modify: `JSFX/RCBitNova V1.1` only

- [ ] **Step 1: Create the file**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
cp "JSFX/RCBitNova V1.0" "JSFX/RCBitNova V1.1"
```

Change `desc:` to read `V1.1` and append ` + 8 bands`.

- [ ] **Step 2: Declare the two constants**

Replace `N_BANDS = 4;` with:

```eel2
N_BANDS = 8;   // static EQ bands
N_DYN   = 4;   // bands with dynamics: Mode A, Mode B, ceilings, detectors.
               // Everything sized by N_DYN keeps its V1.0 address. Raising N_BANDS past 8 is
               // NOT safe: cf ends exactly at st (64) and st exactly at det (96).
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

`memset(st, 0, N_BANDS * 4);` **keeps `N_BANDS`** — it is the static state, and it must now clear 32 words.

- [ ] **Step 3a: Grow the GUI coefficient scratch (spec §2.1)**

`gc_kc` holds 8 words per band and `gc_fc` starts immediately after it, so at eight bands
`gc_kc + b*8` for B5–B8 would overwrite the GUI's HP/LP coefficients:

```eel2
gc_kc    = gc_meta + 16;              // 64 words: the GUI's OWN band coefficients (8 x 8)
gc_fc    = gc_kc + 64;                // 126 words: the GUI's OWN HP/LP coefficients (2 x 63)
gc_ebuf  = gc_fc + 126;               // 24 words: numeric-entry character buffer
```

and the clear span grows by the same 32 words:

```eel2
memset(gc_trace, 0, 13670);
```

`lp_base` is computed from `gc_ebuf + 24`, so it recalculates itself and still lands on 65536 —
verify that in Step 4.

- [ ] **Step 4: Verify no downstream address moved**

```bash
grep -nE "^(mb_peak|mb_end|mbmode|mbwpos|bus_dry|mbeh|hc|egh|hplp_state) *=" "JSFX/RCBitNova V1.1"
grep -c "N_BANDS" "JSFX/RCBitNova V1.1"   # expect 11: the declaration + 8 static sites + 2 split sites
```

Every listed line must read `N_DYN`. This is the step where a single miss shifts the whole map by 16384 words with no error.

- [ ] **Step 5: Declare the 36 new sliders at the END of the slider block**

After `slider142`, add four blocks (shown for B5; repeat with 16x/17x/18x and B6/B7/B8, and with default frequencies 150 / 700 / 5000 / 15000):

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
declaration order (verified live), so appending is what keeps V1.0's parameter list an exact
prefix of V1.1's.

- [ ] **Step 6: Add the read helper next to `band_qeff`**

```eel2
// Band slider base. Bands 0-3 keep their V1.0 numbers; bands 4-7 live above 150.
// READS only - writes must use explicit named sliderNN branches.
function band_slider_base(b) ( b < 4 ? 10 * (b + 1) : 150 + 10 * (b - 4); );
```

Then replace the open-coded `10 * (b + 1)` in `band_qeff`, `setup_band`, `gc_band_setup`,
`gc_band_bits`, `gc_domain_bits` and `gc_dom_used` with `band_slider_base(b)`.

- [ ] **Step 7: Live check — the plugin still loads and sounds identical**

Load `RCBitNova V1.1`. Bands 5–8 are disabled, so it must behave exactly like V1.0. If REAPER
reports a memory error, a `N_DYN` site was missed in Step 3.

- [ ] **Step 8: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - N_BANDS/N_DYN split, 36 new sliders, band_slider_base"
```

---

### Task 4: Split the `@sample` band loop

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (`@sample`, the band loop at ~line 1290)

- [ ] **Step 1: Bound the existing loop to `N_DYN`**

Change `loop(N_BANDS,` at the start of the band loop to `loop(N_DYN,`. That loop keeps its
domain selection, Mode A, and every dynamic array read exactly as V1.0 has them.

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
      pl == 0 ? (
        chA = spl0; chB = spl1;
      ) : pl == 3 ? (
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
      pl == 0 ? ( spl0 = chA; spl1 = chB; ) :
      pl == 3 ? ( spl0 = chA; spl1 = chB; ) :
      pl == 4 ? ( spl0 = chB; spl1 = chA; ) :
      pl == 1 ? ( spl0 = chA + chB; spl1 = chA - chB; ) :
                ( spl0 = chB + chA; spl1 = chB - chA; );
    );
    b += 1;
  );
```

- [ ] **Step 3: Bound the Mode-B loop to `N_DYN`**

Change `loop(N_BANDS,` inside the `any_b ?` block to `loop(N_DYN,`.

- [ ] **Step 4: Audit the new loop for dynamic identifiers**

```bash
awk '/V1.1: bands 5-8, STATIC ONLY/{f=1} f && /^  \);/{exit} f' "JSFX/RCBitNova V1.1" \
  | grep -nE "\b(dp|dm|mbmode|bp|det|dst|cst|eg|egh|hc)\b"
```

Expected: no output. Any hit is a read into the four-band arrays.

- [ ] **Step 5: Live check**

Enable B5 with a large boost and confirm it is audible and appears on the graph. Then set a B1
Mode-B ceiling low enough that the B5 boost pushes it over — Mode B must react, proving the
ordering of §3.1.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - dedicated static-only loop for bands 5-8"
```

---

### Task 5: `@slider` and the GUI writers

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (`@slider` ~1096 and ~1103; the `gc_w_*` writers)

- [ ] **Step 1: Split the setup loop in `@slider`**

```eel2
b = 0; loop(N_BANDS, setup_band(b); b += 1;);
b = 0; loop(N_DYN,  setup_band_dyn(b); b += 1;);
```

`setup_band` and `band_qeff` read only sliders, so they are safe for all eight;
`setup_band_dyn` writes `det`, `dp`, `dm` and `bp`, which exist for four.

- [ ] **Step 2: Bound the Mode-B scan to `N_DYN`**

The `@slider` loop that reads `hc` and `mbmode` becomes `loop(N_DYN,`.

- [ ] **Step 3: Make every GUI writer eight-way and guard the dynamic rebuild**

For each of `gc_w_freq`, `gc_w_macro`, `gc_w_micro`, `gc_w_ratio`, `gc_w_q`, `gc_w_enable`,
replace the four-way branch with eight explicit named cases and guard the dynamic rebuild.
Shown for `gc_w_macro`; the others follow the same shape with their own offsets (Freq +3, Q +4,
Micro +6, Ratio +7, Enable +1):

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

- [ ] **Step 4: Verify no writer still falls through**

```bash
grep -A12 "^function gc_w_" "JSFX/RCBitNova V1.1" | grep -c "b == 6"
```

Expected: 6 — one per writer.

- [ ] **Step 5: Live check**

Drag each of the eight nodes and confirm in `Param` that the intended band's value changed and
no other did. Then drag B5 hard while watching CPU — memory corruption from the unguarded
`setup_band_dyn` would show as instability here.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - eight-way GUI writers, setup_band_dyn guarded by N_DYN"
```

---

### Task 6: The band context menu and the selector strip

**Files:**
- Modify: `JSFX/RCBitNova V1.1` (`@gfx`)

- [ ] **Step 1: Add a right-click menu on band nodes**

Mirroring the HP/LP menu that already exists (~line 1867):

```eel2
// Right-click a band node: the parameters gestures cannot reach. V1.0's GUI reached six of a
// band's nine, and had no way to switch a band OFF - clicking a disabled node enables it, and
// that gesture had no inverse.
gc_rclick && gc_hover >= 0 ? (
  gfx_x = mouse_x; gfx_y = mouse_y;
  gc_bm = gfx_showmenu(
    slider(band_slider_base(gc_hover) + 1) == 1 ? "Disable band||" : "Enable band||"
    "Bell|Low Shelf|High Shelf||"
    ">Placement|Both|Mid|Side|Left|Right|<|"
    ">Q Character|0.00 constant|0.25|0.50|0.75|1.00 proportional|<");
  gc_bm == 1 ? gc_w_enable(gc_hover, slider(band_slider_base(gc_hover) + 1) == 1 ? 0 : 1) :
  gc_bm >= 2 && gc_bm <= 4 ? gc_w_type(gc_hover, gc_bm - 2) :
  gc_bm >= 5 && gc_bm <= 9 ? gc_w_place(gc_hover, gc_bm - 5) :
  gc_bm >= 10 && gc_bm <= 14 ? gc_w_qchar(gc_hover, (gc_bm - 10) * 0.25);
);
```

- [ ] **Step 2: Add the three new writers**

`gc_w_type`, `gc_w_place` and `gc_w_qchar` follow exactly the shape of Step 3 in Task 5 —
eight explicit named branches, `setup_band(b)`, then `b < N_DYN ? setup_band_dyn(b);`. Their
offsets are Type +2, Placement +8, Q Character +9. For example:

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

- [ ] **Step 3: Add the B1…B8 selector strip and the DYN/STATIC tag**

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
gfx_x = gc_px + 8 * 34 * gc_sc + 10 * gc_sc; gfx_y = gc_fy - 20 * gc_sc;
gfx_drawstr(gc_sel < N_DYN ? "DYN" : "STATIC");
```

- [ ] **Step 4: Add coincident-node cycling**

```eel2
// Hit set = every node within the radius, disabled included. First click takes the lowest band;
// each further click at the same spot within 400 ms advances, wrapping. Movement or timeout
// resets. This overrides selected-node priority - otherwise the selected node traps the cursor
// and the others stay unreachable.
gc_click ? (
  (abs(mouse_x - gc_cyc_x) < gc_hit_r && abs(mouse_y - gc_cyc_y) < gc_hit_r
   && (time_precise() - gc_cyc_t) < 0.4) ? ( gc_cyc_n += 1; ) : ( gc_cyc_n = 0; );
  gc_cyc_x = mouse_x; gc_cyc_y = mouse_y; gc_cyc_t = time_precise();
);
```

`gc_hover` then selects the `gc_cyc_n`-th member of the hit set rather than the last match.

- [ ] **Step 5: Live check — the reachability matrix**

For each of B5…B8, set **all nine** parameters from the graph alone: Enable and Disable, Type
(all three), Freq, Q, Macro, Micro, Bit Ratio, Placement (all five), Q Character. Confirm each in
`Param` without opening the parameter list to change anything. Then place two nodes at the same
frequency and gain and confirm repeated clicks cycle between them.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V1.1"
git commit -m "feat(rcbitnova): V1.1 - band context menu, selector strip, node cycling"
```

---

### Task 7: The gates

**Files:** none modified unless a gate fails

- [ ] **Step 1: Oracle**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 229 passed.

- [ ] **Step 2: Address manifest — every audio base unchanged**

```bash
for f in "JSFX/RCBitNova V1.0" "JSFX/RCBitNova V1.1"; do
  echo "== $f"
  grep -nE "^(mb_band|mb_peak|mb_end|mbenv|mbmode|mbwpos|bus_dry|mbgc|mbeh|hc|egh|hplp_state|hplp_cf|lp_rt|lp_kc|lp_ks|lp_geo|lp_off|lp_fs|lp_base) *=" "$f" | sed 's/^[0-9]*://'
done
```

Every line must be textually identical between the two files except where `N_BANDS` became
`N_DYN`. `mb_end` alone proves nothing — sizing any one small array by 8 shifts everything after it.

- [ ] **Step 3: Null test (§6.4)**

48 kHz, block 512, 30 s of deterministic material, GUI closed, fresh instances, bands 5–8
disabled. Transfer state programmatically with the Task 8 script rather than by hand. Render both
versions and compare **sample for sample, zero tolerance**. Cases: defaults; four bands in Mode A;
four bands in Mode B; Min and Linear topologies.

- [ ] **Step 4: CPU (§6.5)**

Two separate comparisons — V1.1 with B5–B8 disabled against V1.0 (**regression, within +5 %**),
and V1.1 eight enabled against V1.1 four enabled (**feature cost, informational**). Blocks 128
and 512, five 60-second runs each, first discarded, compare the median peak block time.
**Zero xruns is absolute.**

- [ ] **Step 5: Parameter manifest**

```bash
python3 - <<'PY'
import reapy
with reapy.inside_reaper():
    pr = reapy.Project(); tr = pr.tracks[0]
    def manifest(name):
        fx = tr.add_fx(name)
        out = [(i, fx.params[i].name) for i in range(fx.n_params)]
        fx.delete(); return out
    a, b = manifest("JS: RCBitNova V1.0"), manifest("JS: RCBitNova V1.1")
    print("V1.0 params:", len(a), " V1.1:", len(b))
    print("prefix intact:", b[:len(a)] == a)
    print("appended:", [n for _, n in b[len(a):]][:5], "...")
PY
```

Expected: `prefix intact: True`, with 36 new names appended.

- [ ] **Step 6: Commit any fixes**

---

### Task 8: The migration script

**Files:**
- Create: `tools/migrate_v10_to_v11.py`

- [ ] **Step 1: Write it**

```python
"""Copy a V1.0 instance's settings onto a new V1.1 instance, in place.

The only supported migration. V1.1 is a new file, so an existing project simply reopens V1.0 and
is unaffected - this script is for moving a project forward deliberately.

Automation is OUT OF SCOPE: if any parameter of the source instance has an envelope, the script
reports it and leaves that instance alone rather than silently dropping the envelope.
"""

import reapy


def migrate(track_index=0, dry_run=True):
    with reapy.inside_reaper():
        pr = reapy.Project()
        tr = pr.tracks[track_index]
        src = next((fx for fx in tr.fxs if "RCBitNova V1.0" in fx.name), None)
        if src is None:
            return "no V1.0 instance on this track"
        values = [float(src.params[i]) for i in range(src.n_params)]
        if any(getattr(src.params[i], "envelope", None) for i in range(src.n_params)):
            return "REFUSED: this instance has automation; migrate it by hand"
        if dry_run:
            return f"would copy {len(values)} values"
        dst = tr.add_fx("JS: RCBitNova V1.1")
        for i, v in enumerate(values):
            if i < dst.n_params:
                dst.params[i] = v
        src.delete()
        return f"migrated {len(values)} values"


if __name__ == "__main__":
    print(migrate(dry_run=True))
```

- [ ] **Step 2: Dry-run it on a project with a configured V1.0 instance**

Run: `python3 tools/migrate_v10_to_v11.py`
Expected: `would copy 97 values` (95 sliders plus REAPER's own Bypass/Wet).

- [ ] **Step 3: Run it for real and verify with the parameter comparison from Task 7 Step 5**

Every old value must match; the 36 new ones stay at their defaults.

- [ ] **Step 4: Commit**

```bash
git add tools/migrate_v10_to_v11.py
git commit -m "feat(rcbitnova): V1.1 migration script, automation explicitly refused"
```

---

### Task 9: Fable review, as-shipped, tag

- [ ] **Step 1: Fable final review**

Dispatch with `model: fable` over `JSFX/RCBitNova V1.1`, the diff against V1.0, and spec rev 4.
Ask specifically for: bit-accuracy verdict; whether any `N_DYN` site was missed; whether the
static-only loop truly touches no dynamic array; whether the eight-way writers are complete and
the `setup_band_dyn` guard is present in all of them; and EEL2 function-order traps.

- [ ] **Step 2: Address every P0/P1, then re-run Task 7**

- [ ] **Step 3: Append "As-shipped" to the spec**

Record every live measurement, every deviation and why, every defect found live and how.
Follow V1.0 §16 as the model.

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
| §2 memory, zero-slack boundaries | 1 (model), 3 (constants), 7 (manifest) |
| §2.1 `gc_kc` growth | 3 — **see gap below** |
| §3 two counts | 3 |
| §3.1 signal order, structural split | 4 |
| §3.2 the 28 sites | 3 (17 dynamic), 4 (2 split), 5 (`@slider`) |
| §4 sliders, `band_slider_base`, named writes | 2, 3, 5 |
| §5 GUI: menu, selector, DYN/STATIC, cycling | 6 |
| §6.1–6.3 oracle, shadow layout, addresses | 1, 7 |
| §6.4 null test | 7 |
| §6.5 CPU | 7 |
| §6.6 migration | 8 |
| §6.7 live, reachability matrix | 6, 7 |

**Gap found and fixed inline:** §2.1 requires `gc_kc` to grow from 32 to 64 words, `gc_fc` and
`gc_ebuf` to shift, and the clear span to become 13670 — no task did this. Added as Task 3
Step 3a below.

**Placeholder scan:** every code step carries real code. Task 6 Step 2 shows one writer in full
and states the exact offsets for the other two rather than saying "similar".

**Type consistency:** `band_slider_base`, `N_DYN`, `gc_w_type`/`gc_w_place`/`gc_w_qchar`,
`layout`/`check_adjacency`/`shadow_layout` are spelled identically everywhere they appear.
