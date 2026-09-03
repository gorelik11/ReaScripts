# RCBitNova Dynamics Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Make the eight bands' dynamics editable from the plugin's own window instead of REAPER's
Param list, so the plugin can be used in real work.

**Architecture:** This ships as **`JSFX/RCBitNova V1.2`, an exact copy of V1.1 to begin with.
V1.1 is tagged, in use in the owner's projects, and is never edited** — the project's standing rule
since V0.1, and the reason the panel cannot be built in place. Eight collapsible rows below the
graph, one card expanded at a time. The row
carries Dyn, Mode A/B and both cascade ceilings with their own toggles; the card carries Stereo,
Attack, Release and the two Micros. Numeric fields with vertical drag, built on one generalised
field primitive and one interaction controller. **No DSP changes at all** — if a sample moves, the
work is wrong, and the null test says so.

**Tech Stack:** JSFX (EEL2); Python 3.11 stdlib-only tooling (`tools/rcbitnova_gates.py`,
`rcbitnova_nulltest.py`, `rcbitnova_compile.py`); `pytest`; `reapy` against live REAPER.

**Spec:** `docs/superpowers/specs/2026-09-02-rcbitnova-dynamics-panel-design.md` (**rev 5**).
Section numbers below are that document's.

## Global Constraints

- **`JSFX/RCBitNova V1.1` is read-only for the whole of this plan.** Every plugin edit lands in
  `JSFX/RCBitNova V1.2`. If a task's diff touches V1.1, the task is wrong.
- **No DSP change.** The null test compares **V1.2 against V1.1** — same state on both instances,
  sample for sample, zero tolerance. That is the panel's whole contract: it must not move a sample.
- **`n_params == 178` does not prove a build compiles.** A syntax error in `@gfx` leaves the slider
  count untouched. Run `python3 tools/rcbitnova_compile.py` after every step that edits the JSFX —
  it floats the FX window and reads the error text REAPER puts there.
- **EEL2 has no scientific notation.** `1e18` is a syntax error; write the digits.
- **Every assignment inside a ternary branch is parenthesised**, and **no bit-shift operators** —
  family conventions from `Fable Eq Dynamic`.
- **Functions resolve in file order.** Four V1.0 builds broke on a definition below its caller.
- **Writes go through named `sliderNN` branches only.** V1.0 established live that assigning
  through `slider(computed_index)` updates what the GUI reads back and never reaches the parameter.
- **Every geometry number, hit test and drag threshold is in logical units** (`gc_sc`, `gc_ret`).
  The plugin this copies its shape from hit-tests raw constants and is wrong on Retina.
- **`topo_pdc()` is never called from `@gfx`.** It writes variables REAPER reads.
- Run from the worktree root: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`. All 273 existing
  tests stay green at every commit.
- **Never claim a task is done without running its test and reading the output.** A pipeline like
  `pytest | tail && git commit` does not guard: the exit code is `tail`'s.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tests/fixtures/v11_declared_175.json` | V1.1's 175-record parameter map, frozen. What a future V1.1 → V1.2 migration is checked against. | Create (Task 1) |
| `JSFX/RCBitNova V1.2` | The plugin. Starts as a byte copy of V1.1 and receives every change. | Create (Task 2), modify (3–8) |
| `JSFX/RCBitNova V1.1` | **Read-only.** Tagged, shipped, in use. | never |
| `tools/rcbitnova_gates.py` | `--freeze`; a frozen side (V1.1) and a working side (V1.2); `--live` checks V1.2's prefix against the fixture; `check_writers` gains a per-writer record. | Modify (1, 2, 3, 5) |
| `tools/rcbitnova_compile.py` | Targets V1.2; expected count 178 → 179 in Task 3. | Modify (2, 3) |
| `tools/rcbitnova_nulltest.py` | Baseline moves from V1.0 to **V1.1**; the plugin under test is V1.2. | Modify (Task 2) |
| `tests/_reaper_fx_fake.py` | Gains a V1.2 shape alongside V1.1's. | Modify (Task 3) |
| `tests/test_rcbitnova_dsp.py` | Fixture test, V1.2 shape tests, writer-record tests. | Modify (1, 2, 3, 5) |
| `tools/migrate_v10_to_v11.py` | **Untouched.** It migrates V1.0 → V1.1 and that path is unchanged. | never |

Task 1 is tooling against V1.1 and changes no plugin. Task 2 creates V1.2 and proves it identical.
Task 3 is the one commit that changes V1.2's parameter map. Tasks 4–8 are the plugin, each
compile-checked and null-checked. Task 9 is the gates and the live matrix.

---

### Task 1: Freeze the 175-record parameter map

The spec calls this the strongest safeguard in the document. It must exist **before** anything
touches the plugin, because it records what the plugin looked like before.

**Files:**
- Create: `tests/fixtures/v11_declared_175.json`
- Modify: `tools/rcbitnova_gates.py`
- Test: `tests/test_rcbitnova_dsp.py` (append)

**Interfaces:**
- Produces: `gates.freeze_declared(path)` — writes the fixture from the live plugin;
  `gates.load_declared(path)` — reads it back as a list of 175 records
  `(index, name, lo, hi, step, default)`.

- [ ] **Step 1: Write the failing test**

```python
def test_v11_declared_fixture_has_the_shape_the_contract_needs():
    """The compatibility contract is 'V1.1's 175 records are a prefix'. That is only checkable
    against a record of what those 175 were BEFORE the panel existed."""
    recs = gates.load_declared(gates.DECLARED_FIXTURE)
    assert len(recs) == 175
    assert [r[0] for r in recs] == list(range(175)), "indices must be 0..174 in order"
    assert recs[0][1] == "Bypass", recs[0]
    assert recs[94][1] == "LP Resolution (Linear only)", \
        "record 94 is slider142, the last of V1.0's block - the boundary the panel must not move"
    assert recs[95][1] == "B5 Enable", \
        "record 95 is where B5 starts; a parameter inserted before it shifts eighty records"
    assert recs[174][1] == "B8 Hard Ceiling Micro (% bit)", recs[174]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k declared_fixture`
Expected: FAIL — `AttributeError: module 'tools.rcbitnova_gates' has no attribute 'load_declared'`.

- [ ] **Step 3: Implement freeze and load in `tools/rcbitnova_gates.py`**

```python
import json

DECLARED_FIXTURE = os.path.join("tests", "fixtures", "v11_declared_175.json")


def _declared_records(RPR, track, fx, n_declared):
    """(index, name, lo, hi, step, default) for the declared block, read from an UNTOUCHED
    instance - a default cannot be recovered from one that has already been written to."""
    out = []
    for i in range(n_declared):
        r = RPR.TrackFX_GetParam(track.id, fx.index, i, 0, 0)
        st = RPR.TrackFX_GetParameterStepSizes(track.id, fx.index, i, 0, 0, 0, 0)
        name = RPR.TrackFX_GetParamName(track.id, fx.index, i, "", 128)[4]
        out.append([i, name, r[4], r[5], st[4], r[0]])
    return out


def freeze_declared(path=DECLARED_FIXTURE, track_index=0, n_declared=175):
    """Write the fixture from the live plugin. Run ONCE, before the panel exists."""
    import reapy
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        tr = reapy.Project().tracks[track_index]
        assert not [f for f in tr.fxs if "RCBitNova" in f.name], \
            "use an empty scratch track"
        fx = tr.add_fx("JS: RCBitNova V1.1")
        recs = _declared_records(RPR, tr, fx, n_declared)
        fx.delete()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(recs, f, indent=1)
    return recs


def load_declared(path=DECLARED_FIXTURE):
    return [tuple(r) for r in json.load(open(path))]
```

Add `--freeze` to `main()`:

```python
    if mode == "--freeze":
        recs = freeze_declared()
        print(f"OK freeze: {len(recs)} declared records written to {DECLARED_FIXTURE}")
        return 0
```

- [ ] **Step 4: Generate the fixture against the CURRENT plugin**

REAPER must be running with an empty project on track 0.

```bash
python3 tools/rcbitnova_gates.py --freeze
```

Expected: `OK freeze: 175 declared records written to tests/fixtures/v11_declared_175.json`.

- [ ] **Step 5: Run the test**

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q`
Expected: 274 passed.

- [ ] **Step 6: Commit, on its own**

The spec asks for this in a separate commit so the diff shows exactly what was frozen and when.

```bash
git add tools/rcbitnova_gates.py tests/fixtures/v11_declared_175.json tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): freeze V1.1's 175 declared records before the panel"
```

---

### Task 2: Create V1.2 as a copy, and prove it is one

The checkpoint that matters here is negative: after this task the new file must be
indistinguishable from V1.1, so that everything which breaks later was broken by the panel and
not by the copy.

**Files:**
- Create: `JSFX/RCBitNova V1.2`
- Modify: `tools/rcbitnova_gates.py`, `tools/rcbitnova_compile.py`, `tools/rcbitnova_nulltest.py`

**Interfaces:**
- Produces: `gates.V11` (frozen, 175 declared) and `gates.V12` (working, 176 after Task 3);
  the null test's `BASE` and `UNDER_TEST` names.

- [ ] **Step 1: Copy, and change only the description**

```bash
cd /Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova
cp "JSFX/RCBitNova V1.1" "JSFX/RCBitNova V1.2"
```

In the copy, `desc:` reads `V1.2` and gains ` + dynamics panel`. Nothing else changes in this task.

- [ ] **Step 2: Give the tools two versions instead of one**

In `tools/rcbitnova_gates.py`:

```python
V10 = "JSFX/RCBitNova V1.0"
V11 = "JSFX/RCBitNova V1.1"          # FROZEN: tagged, shipped, in the owner's projects
V12 = "JSFX/RCBitNova V1.2"          # the working file - every check below targets this
N_DECLARED_V11 = 175                 # frozen forever
N_DECLARED_V12 = 175                 # becomes 176 in Task 3, when the panel slider is declared
```

Every `check_source` / `check_live` call site moves from `V11` to `V12`. `check_addresses` keeps
comparing against `V10`, which is what the memory model is anchored to.

In `tools/rcbitnova_compile.py`, the effect under test becomes `"JS: RCBitNova V1.2"` and the
expected count stays 178 until Task 3.

In `tools/rcbitnova_nulltest.py`:

```python
BASE       = "JS: RCBitNova V1.1"    # the panel must not move a sample away from this
UNDER_TEST = "JS: RCBitNova V1.2"
```

The five `CASES` and the `DIVERGENT` case stay exactly as they are — but `modeB_disabled_band` is
no longer divergent, because both sides now have the Enable gate. Move it into `CASES`:

```python
CASES = {
    ...
    # Was a deliberate divergence when the baseline was V1.0, which lacked the Enable gate on
    # Mode B. Against V1.1 it is an ordinary identical case, and a valuable one: it exercises a
    # disabled band with dynamics still configured.
    "modeB_disabled_band": {"B1 Enable": 0, "B1 Freq": 200, "B1 Dyn": 1, "B1 Dyn Mode": 1,
                            "B1 Soft Ceiling Macro (bits below 0)": 3, "B1 Soft": 1,
                            "B2 Enable": 1, "B2 Macro (bits)": 1, "B2 Freq": 1000},
}
DIVERGENT = {}
```

- [ ] **Step 3: Deploy V1.2 and check it compiles**

```bash
cp "JSFX/RCBitNova V1.2" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py
```

Expected: `OK compile: 178 parameters and no error text in the plugin window`.

- [ ] **Step 4: Prove the copy is a copy**

```bash
diff "JSFX/RCBitNova V1.1" "JSFX/RCBitNova V1.2"      # only the desc: line
python3 tools/rcbitnova_gates.py --source-only        # V1.2 passes what V1.1 passes
python3 -u tools/rcbitnova_nulltest.py                # V1.2 vs V1.1
```

Expected: one differing line; the gate green; **all six null cases identical**. Six, not five: the
former divergence is gone because both sides share the Enable gate now. If any case differs here,
the copy is not a copy and nothing else in this plan is trustworthy.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.2" tools/
git commit -m "feat(rcbitnova): V1.2 as an exact copy of V1.1, tools made version-aware"
```

---

### Task 3: Declare the panel-state slider, last

**Files:** modify `JSFX/RCBitNova V1.2`, `tools/rcbitnova_gates.py`

- [ ] **Step 1: Declare it after every existing slider**

At the very end of the slider block — after `slider245`, not after `slider142`:

```eel2
// V1.2 panel state: which dynamics card is open. 0 = none, 1..8 = that band.
// An ENUM, not a bitmask: the geometry draws one card, and a mask would accept all 256 subsets
// from Param, automation or a preset. The invalid state is unrepresentable instead of sanitised.
// DECLARED LAST, despite the number: REAPER numbers parameters in declaration order, and putting
// this beside slider142 would shift all eighty B5-B8 records and silently move every saved
// project's dynamics by one parameter.
slider143:0<0,8,1>-Panel: open dynamics card (0 none, 1..8 band)
```

- [ ] **Step 2: Add the site row that keeps it last**

In `SITES`:

```python
    "panel-state-declared-last": (
        r"^slider245:[^\n]*\n(?:[^\n]*\n)*?^slider143:0<0,8,1>-Panel:", "slider143"),
```

The row asserts that `slider143` appears **after** `slider245` in the file. Written as a presence
check because the capture is the literal itself.

- [ ] **Step 3: Verify the prefix against the fixture**

In `check_live`, after the existing comparisons:

```python
    frozen = load_declared()
    assert dec11[:175] == frozen, "V1.1's first 175 declared records must be unchanged"
    assert dec11[175][1].startswith("Panel:"), \
        f"record 175 must be the panel state, got {dec11[175][1]!r}"
    assert [r[1] for r in host11] == HOST_TAIL, "host tail must follow at 176..178"
```

- [ ] **Step 4: Move the counters — this is the task that changes them**

One new declared parameter takes V1.2 from 175/178 to 176/179. Three places hold it:

```python
# tools/rcbitnova_gates.py
N_DECLARED_V12 = 176
# tools/rcbitnova_compile.py
    if n != 179:
        problems.append(f"reports {n} parameters, expected 179")
```

and `tests/_reaper_fx_fake.py` gains the V1.2 shape beside V1.1's, so the fake can model either:

```python
N_DECLARED_V11 = 175
N_DECLARED_V12 = 176
```

`N_DECLARED_V11` and `tools/migrate_v10_to_v11.py` **do not move**: V1.1 is frozen and its
migration path is unchanged.

- [ ] **Step 5: Compile, gate, and check live**

```bash
python3 tools/rcbitnova_compile.py     # expects 179 now
python3 tools/rcbitnova_gates.py --source-only
python3 tools/rcbitnova_gates.py --live
```

Expected: all three OK. `--live` is the one that matters: it proves the eighty B5–B8 records did
not move, which is what makes a future V1.1 → V1.2 migration possible at all.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V1.2" tools/ tests/
git commit -m "feat(rcbitnova): panel-state slider in V1.2, declared last so B5-B8 do not shift"
```

---

### Task 4: `apply_band_dyn_global` and the PDC dirty flag — a refactor that changes nothing

The failure this prevents: `setup_band_dyn` writes `det`, `dp`, `dm`, `bp` and nothing else, while
`mbmode[b]`, `hc[b]` and `any_b` are rebuilt only by the `@slider` scan. A writer that calls only
the two existing rebuilds moves the field, the Param value and the menu tick while the audio stays
in the old mode. The null test cannot see it — it renders loaded state, and this only exists after
a gesture.

**Files:** modify `JSFX/RCBitNova V1.2`

- [ ] **Step 1: Extract the scan body into a function, above its first caller**

The current `@slider` scan is (quoted as it stands, including its unparenthesised
`? any_b = 1;` — the replacement below parenthesises it, per the family convention):

```eel2
any_b = 0;
b = 0;
loop(N_BANDS,
  mbmode[b] = slider(dynb[b] + 7);
  hc[b] = pow(2, -(slider(ceb[b] + 2) + slider(ceb[b] + 3) * 0.01));
  (slider(stb[b] + 1) == 1 && slider(dynb[b] + 1) == 1 && mbmode[b] == 1
   && slider(stb[b]+2) <= 2) ? any_b = 1;
  b += 1;
);
```

Define this in `@init`, after `setup_band_dyn` and before anything that calls it:

```eel2
// Rebuilds the state the per-band setup functions do NOT own: mbmode, hc, and the any_b fold.
// REBUILDS ONLY. topo_pdc() writes pdc_delay/pdc_bot_ch/pdc_top_ch/ext_tail_size - variables
// REAPER itself reads - so it is never called from here and never from @gfx. This sets a flag and
// @block, which already publishes PDC at topology commit, consumes it within one audio block.
function apply_band_dyn_global(b) local(i) (
  mbmode[b] = slider(dynb[b] + 7);
  hc[b] = pow(2, -(slider(ceb[b] + 2) + slider(ceb[b] + 3) * 0.01));
  any_b = 0;                       // a fold over ALL bands: one band changing can clear or set it
  i = 0;
  loop(N_BANDS,
    (slider(stb[i] + 1) == 1 && slider(dynb[i] + 1) == 1 && mbmode[i] == 1
     && slider(stb[i]+2) <= 2) ? ( any_b = 1; );
    i += 1;
  );
  pdc_dirty = 1;
);
```

- [ ] **Step 2: Call it from the `@slider` scan, so behaviour is unchanged**

Replace the scan body with a loop over the helper. `mbmode[i]` must be current before the fold, so
the helper's own fold re-reads it — which it does, from the slider:

```eel2
b = 0;
loop(N_BANDS, apply_band_dyn_global(b); b += 1;);
```

`topo_pdc()` at the end of `@slider` is **not** moved and not duplicated.

- [ ] **Step 3: Consume the flag at the top of `@block`**

```eel2
pdc_dirty ? ( topo_pdc(); pdc_dirty = 0; );
```

and `pdc_dirty = 0;` with the other `@init` state.

- [ ] **Step 4: Compile and prove nothing moved**

```bash
python3 tools/rcbitnova_compile.py
python3 tools/rcbitnova_gates.py --source-only
python3 -u tools/rcbitnova_nulltest.py
```

Expected: five cases identical, `modeB_disabled_band` diverging, comparator self-test true. This
refactor is the one place in the plan where the null test is checking a *rewrite of the audio
path's setup*, so run the whole suite, not one case.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.2"
git commit -m "refactor(rcbitnova): apply_band_dyn_global, and PDC published from @block"
```

---

### Task 5: Eleven writers, and a writer gate that knows they differ

88 named assignments. A wrong number edits another band's parameter and nothing crashes — the gate
is the only thing that catches it statically.

**Files:** modify `JSFX/RCBitNova V1.2`, `tools/rcbitnova_gates.py`, `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `gc_w_dyn`, `gc_w_dynmode`, `gc_w_soft`, `gc_w_hard`, `gc_w_softceil`,
  `gc_w_hardceil`, `gc_w_stereo`, `gc_w_atk`, `gc_w_rel`, `gc_w_softmicro`, `gc_w_hardmicro`,
  each `(b, v)`.

- [ ] **Step 1: Write the gate's record and its test first**

In `tools/rcbitnova_gates.py`, replace the flat `WRITERS` dict:

```python
# name -> (table, offset, step, rebuilds, publishes)
#   rebuilds  : exact call strings the body MUST contain
#   publishes : must go through apply_band_dyn_global (which sets pdc_dirty).
#               SEPARATE from rebuilds on purpose - one field doing both is how a writer that
#               rebuilds but never republishes PDC passes the gate.
WRITERS = {
    "gc_w_enable":    ("stb",  1, 1,    ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_type":      ("stb",  2, 1,    ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_freq":      ("stb",  3, 1,    ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_q":         ("stb",  4, 0.001,("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_macro":     ("stb",  5, 1,    ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_micro":     ("stb",  6, 0.1,  ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_ratio":     ("stb",  7, 0.05, ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_place":     ("stb",  8, 1,    ("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_qchar":     ("stb",  9, 0.001,("setup_band(b)", "setup_band_dyn(b)"), False),
    "gc_w_dyn":       ("dynb", 1, 1,    ("setup_band_dyn(b)", "apply_band_dyn_global(b)"), True),
    "gc_w_stereo":    ("dynb", 2, 1,    ("setup_band_dyn(b)",), False),
    "gc_w_softceil":  ("dynb", 3, 0.05, ("setup_band_dyn(b)",), False),
    "gc_w_softmicro": ("dynb", 4, 0.1,  ("setup_band_dyn(b)",), False),
    "gc_w_atk":       ("dynb", 5, 0.01, ("setup_band_dyn(b)",), False),
    "gc_w_rel":       ("dynb", 6, 1,    ("setup_band_dyn(b)",), False),
    "gc_w_dynmode":   ("dynb", 7, 1,    ("apply_band_dyn_global(b)",), True),
    "gc_w_soft":      ("dynb", 8, 1,    ("setup_band_dyn(b)",), False),
    "gc_w_hard":      ("ceb",  1, 1,    ("apply_band_dyn_global(b)",), False),
    "gc_w_hardceil":  ("ceb",  2, 0.05, ("apply_band_dyn_global(b)",), False),
    "gc_w_hardmicro": ("ceb",  3, 0.1,  ("apply_band_dyn_global(b)",), False),
}
```

Note `gc_w_hard`, `gc_w_hardceil` and `gc_w_hardmicro` rebuild through the helper because `hc[b]`
is what they change, and it is the helper that owns `hc[b]`.

```python
def check_writers(text, path):
    tables = layout.base_tables(8)
    for fn, (table, off, _step, rebuilds, publishes) in WRITERS.items():
        body = _function_body(text, fn)
        assert body, f"{path}: writer {fn} not found"
        want = [str(tables[table][b] + off) for b in range(8)]
        got = re.findall(r"slider(\d+) = v;", body)
        assert got == want, f"{path}: {fn} writes sliders {got}, expected {want}"
        assert len(re.findall(r"slider_automate\(", body)) == 8, \
            f"{path}: {fn} must call slider_automate in all eight branches"
        for call in rebuilds:
            assert call in body, f"{path}: {fn} does not call {call}"
        if publishes:
            assert "apply_band_dyn_global(b)" in body, \
                f"{path}: {fn} changes state that feeds PDC and must go through the helper"
        assert "topo_pdc(" not in body, \
            f"{path}: {fn} calls topo_pdc directly - it writes variables REAPER reads, and @block " \
            f"publishes them from pdc_dirty"
        # write, automate, THEN rebuild: the helper folds any_b by reading sliders, so rebuilding
        # first would fold the previous value and leave the state one gesture behind.
        first_write = body.index("slider_automate(")
        for call in rebuilds:
            assert body.index(call) > first_write, \
                f"{path}: {fn} calls {call} before writing the slider"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tools/rcbitnova_gates.py --source-only`
Expected: FAIL — `writer gc_w_dyn not found`.

- [ ] **Step 3: Write the eleven writers**

Each one, in full. `gc_w_dyn` shown; the other ten are identical in shape with their own table,
offset and rebuilds from the record above. Define them next to the existing nine, above `@gfx`.

```eel2
function gc_w_dyn(b, v) (
  b == 0 ? ( slider51  = v; slider_automate(slider51);  ) :
  b == 1 ? ( slider61  = v; slider_automate(slider61);  ) :
  b == 2 ? ( slider71  = v; slider_automate(slider71);  ) :
  b == 3 ? ( slider81  = v; slider_automate(slider81);  ) :
  b == 4 ? ( slider191 = v; slider_automate(slider191); ) :
  b == 5 ? ( slider201 = v; slider_automate(slider201); ) :
  b == 6 ? ( slider211 = v; slider_automate(slider211); ) :
           ( slider221 = v; slider_automate(slider221); );
  setup_band_dyn(b); apply_band_dyn_global(b);
);
```

Generate the eight numbers from the tables rather than typing them:

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from tools import rcbitnova_layout as lay
from tools.rcbitnova_gates import WRITERS
t = lay.base_tables(8)
for fn,(tab,off,_s,_r,_p) in WRITERS.items():
    print(fn, [t[tab][b]+off for b in range(8)])"
```

- [ ] **Step 4: Gate and compile**

```bash
python3 tools/rcbitnova_gates.py --source-only
python3 tools/rcbitnova_compile.py
```

Expected: both OK, 20 writers.

- [ ] **Step 5: Seed the defects that matter**

Add to `SEEDED_DEFECTS`, each required to be rejected for its own reason:

```python
    (lambda t: t.replace("b == 6 ? ( slider211 = v; slider_automate(slider211); ) :",
                         "b == 6 ? ( slider212 = v; slider_automate(slider212); ) :"),
     "gc_w_dyn writes sliders"),
    (lambda t: t.replace("function gc_w_hardceil(b, v) (\n  b == 0 ? ( slider92",
                         "function gc_w_hardceil(b, v) (\n  b == 0 ? ( slider53"),
     "gc_w_hardceil writes sliders"),          # wrong TABLE, not just a wrong digit
    (lambda t: t.replace("  setup_band_dyn(b); apply_band_dyn_global(b);\n);\n\nfunction gc_w_stereo",
                         "  setup_band_dyn(b);\n);\n\nfunction gc_w_stereo"),
     "gc_w_dyn does not call apply_band_dyn_global(b)"),
```

Run: `python3 -m pytest tests/test_rcbitnova_dsp.py -q -k seeded`
Expected: every mutant rejected for its named reason.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V1.2" tools/rcbitnova_gates.py tests/test_rcbitnova_dsp.py
git commit -m "feat(rcbitnova): eleven dynamics writers, and a per-writer gate record"
```

---

### Task 6: One field primitive and one interaction controller

Generalising the drawing does not generalise the interaction: `gc_field` only draws and hit-tests,
while every click, keystroke and commit is open-coded further down `@gfx` for exactly five fields.
Twenty numeric fields cannot be open-coded.

**Files:** modify `JSFX/RCBitNova V1.2`

**Interfaces:**
- Produces: `gc_field_at(id, bx, by, bw, label, value, dec)` returning `hot`;
  `gc_meta` table; `gc_field_commit(id, v)`.

- [ ] **Step 1: Generalise the primitive, and express the old one through it**

```eel2
// Draws a numeric field anywhere and returns whether the pointer is over it. `id` is the edit id,
// not a slot index: 0..5 are the readout fields, panel fields use 100 + band*10 + slot.
function gc_field_at(id, bx, by, bw, label, value, dec) local(hot) (
  hot = mouse_x >= bx && mouse_x < bx + bw && mouse_y >= by && mouse_y < by + gc_fh;
  gc_edit == id ? gfx_set(0.25, 0.35, 0.5, 1) :
    hot ? gfx_set(0.2, 0.2, 0.22, 1) : gfx_set(0.14, 0.14, 0.16, 1);
  gfx_rect(bx, by, bw, gc_fh);
  gfx_set(0.6, 0.6, 0.65, 1);
  gfx_x = bx + 4 * gc_sc; gfx_y = by + 4 * gc_sc;
  gfx_drawstr(label);
  gfx_set(0.9, 0.9, 0.95, 1);
  gc_edit == id ? (
    gc_ci = 0;
    loop(gc_elen, gfx_drawchar(gc_ebuf[gc_ci]); gc_ci += 1;);
    gfx_drawstr("_");
  ) : ( gfx_drawnumber(value, dec); );
  hot;
);

// The five readout fields keep their behaviour and become calls to it.
function gc_field(i, label, value, dec) (
  gc_field_at(i, gc_px + i * (gc_fw + 8 * gc_sc), gc_fy, gc_fw, label, value, dec);
);
```

- [ ] **Step 2: The metadata table**

Filled in `@init`, one row per panel parameter, indexed by slot `0..5`:

```eel2
// slot -> (table_base_id, offset, lo, hi, step, decimals, drag_units, writer_id)
// table_base_id: 0 = stb, 1 = dynb, 2 = ceb.   drag_units = logical pixels per step.
W_DYN = 1; W_DYNMODE = 2; W_SOFT = 3; W_HARD = 4; W_SOFTCEIL = 5; W_HARDCEIL = 6;
W_STEREO = 7; W_ATK = 8; W_REL = 9; W_SOFTMICRO = 10; W_HARDMICRO = 11;

gc_meta = 304;                    // 6 slots x 8 words, in the free space above nb_list
// slot 0 Soft ceiling   dynb+3   0..16    0.05  2 dec  12 px  W_SOFTCEIL
gc_meta[0]=1; gc_meta[1]=3; gc_meta[2]=0;   gc_meta[3]=16;  gc_meta[4]=0.05; gc_meta[5]=2; gc_meta[6]=12; gc_meta[7]=W_SOFTCEIL;
// slot 1 Hard ceiling   ceb+2    0..16    0.05  2 dec  12 px  W_HARDCEIL
gc_meta[8]=2; gc_meta[9]=2; gc_meta[10]=0;  gc_meta[11]=16; gc_meta[12]=0.05; gc_meta[13]=2; gc_meta[14]=12; gc_meta[15]=W_HARDCEIL;
// slot 2 Attack         dynb+5   0.05..50 0.01  2 dec  8 px   W_ATK
gc_meta[16]=1; gc_meta[17]=5; gc_meta[18]=0.05; gc_meta[19]=50; gc_meta[20]=0.01; gc_meta[21]=2; gc_meta[22]=8; gc_meta[23]=W_ATK;
// slot 3 Release        dynb+6   1..500   1     0 dec  4 px   W_REL
gc_meta[24]=1; gc_meta[25]=6; gc_meta[26]=1; gc_meta[27]=500; gc_meta[28]=1; gc_meta[29]=0; gc_meta[30]=4; gc_meta[31]=W_REL;
// slot 4 Soft Micro     dynb+4   -100..100 0.1  1 dec  6 px   W_SOFTMICRO
gc_meta[32]=1; gc_meta[33]=4; gc_meta[34]=-100; gc_meta[35]=100; gc_meta[36]=0.1; gc_meta[37]=1; gc_meta[38]=6; gc_meta[39]=W_SOFTMICRO;
// slot 5 Hard Micro     ceb+3    -100..100 0.1  1 dec  6 px   W_HARDMICRO
gc_meta[40]=2; gc_meta[41]=3; gc_meta[42]=-100; gc_meta[43]=100; gc_meta[44]=0.1; gc_meta[45]=1; gc_meta[46]=6; gc_meta[47]=W_HARDMICRO;

function gc_slot_slider(b, slot) local(t) (
  t = gc_meta[slot*8];
  (t == 0 ? stb[b] : t == 1 ? dynb[b] : ceb[b]) + gc_meta[slot*8 + 1];
);
```

`gc_meta` needs 48 words at 304..351; `nb_list` ends at 303 and `mb_band` is a literal 1024, so
there is room. Add both to `tools/rcbitnova_layout.py`'s model in Task 9's gate work.

- [ ] **Step 3: The dispatcher — metadata chooses a writer, only a named writer assigns**

EEL2 has no callable references, and a "generic" writer built from `(table, offset)` would assign
through `slider(computed_index)`, which V1.0 proved never reaches the parameter.

```eel2
function gc_field_commit(id, v) local(b, slot, w, lo, hi, st) (
  b = floor((id - 100) / 10); slot = (id - 100) % 10;
  lo = gc_meta[slot*8 + 2]; hi = gc_meta[slot*8 + 3]; st = gc_meta[slot*8 + 4];
  v = min(max(v, lo), hi);
  v = floor(v / st + 0.5) * st;             // clamp AND quantise: off-grid GUI writes cost V1.0
  w = gc_meta[slot*8 + 7];                  // -62 dB of null residue
  w == W_SOFTCEIL  ? ( gc_w_softceil(b, v);  ) :
  w == W_HARDCEIL  ? ( gc_w_hardceil(b, v);  ) :
  w == W_ATK       ? ( gc_w_atk(b, v);       ) :
  w == W_REL       ? ( gc_w_rel(b, v);       ) :
  w == W_SOFTMICRO ? ( gc_w_softmicro(b, v); ) :
                     ( gc_w_hardmicro(b, v); );
);
```

- [ ] **Step 4: The press / drag / type state machine**

State: `gc_cap` (captured field id, −1 for none), `gc_cap_v` (value at press), `gc_cap_y`,
`gc_dragging`.

```eel2
// mouse-down captures WITHOUT entering edit mode; crossing four LOGICAL pixels starts a drag and
// clears any edit focus; releasing below the threshold gives typing focus. Putting the transition
// at the press instead makes "arm a drag" and "never drag while focused" both true at once, and
// nothing can ever start dragging.
gc_click && gc_pfield >= 0 ? ( gc_cap = gc_pfield; gc_cap_v = gc_pfield_v; gc_cap_y = mouse_y;
                               gc_dragging = 0; );
gc_cap >= 0 && (mouse_cap & 1) ? (
  !gc_dragging && abs(mouse_y - gc_cap_y) / gc_sc >= 4 ? ( gc_dragging = 1; gc_edit = -1;
                                                           gc_elen = 0; );
  gc_dragging ? (
    gc_slot = (gc_cap - 100) % 10;
    gc_v = gc_cap_v - floor((mouse_y - gc_cap_y) / gc_sc / gc_meta[gc_slot*8 + 6])
                      * gc_meta[gc_slot*8 + 4];
    gc_v != slider(gc_slot_slider(floor((gc_cap - 100) / 10), gc_slot)) ?
      ( gc_field_commit(gc_cap, gc_v); );
  );
);
!(mouse_cap & 1) && gc_cap >= 0 ? (
  !gc_dragging ? ( gc_edit = gc_cap; gc_elen = 0; );   // a short press is a focus click
  gc_cap = -1; gc_dragging = 0;
);
```

- [ ] **Step 5: Route Enter through the dispatcher, and stop the readout handler clearing panel focus**

The existing keyboard block commits by `gc_edit == 0 ? gc_w_freq(...) : …`. Extend it:

```eel2
        gc_edit >= 100 ? ( gc_field_commit(gc_edit, gc_val); ) :
        gc_edit == 0 ? gc_w_freq (gc_sel, min(max(gc_val,20),20000), 0) :
```

and the readout click handler's unconditional else becomes conditional, so a panel field focused
earlier in the same frame survives:

```eel2
  gc_h4 ? ( gc_edit = 4; gc_elen = 0; ) :
  gc_h5 ? ( gc_edit = 5; gc_elen = 0; ) :
  gc_pfield < 0 ? ( gc_edit = -1; );     // only clear when nothing else claimed this click
```

- [ ] **Step 6: Compile and prove the audio is untouched**

```bash
python3 tools/rcbitnova_compile.py
python3 -u tools/rcbitnova_nulltest.py defaults
```

Expected: OK compile; `defaults identical`.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.2"
git commit -m "feat(rcbitnova): one field primitive, metadata table and field controller"
```

---

### Task 7: The eight rows

**Files:** modify `JSFX/RCBitNova V1.2`

- [ ] **Step 1: Extend the layout block, before any hit test**

Beside the existing `gc_sy`/`gc_sh`, in the block that already runs before node interaction:

```eel2
gc_rows_y = gc_sy + gc_sh + 6 * gc_sc;      // first dynamics row, clear of the B1..B8 strip
gc_rh     = 18 * gc_sc;                     // row height
gc_card_h = 90 * gc_sc;
gc_open   = slider143;                                  // 0 none, 1..8 band
gc_panel_on = !gc_small && (gfx_h - gc_py - 228 * gc_sc) >= 180 * gc_sc;
// Insufficient height is a DERIVED visibility state and never writes the parameter: dragging a
// window edge must not automate a value into the project, the undo history or automation playback.
gc_card_on = gc_panel_on && gc_open > 0 &&
             (gfx_h - gc_py - 318 * gc_sc) >= 180 * gc_sc;
gc_ph = gfx_h - gc_py - (gc_panel_on ? (gc_card_on ? 318 : 228) : 84) * gc_sc;
```

- [ ] **Step 2: Draw the rows and own their clicks**

```eel2
gc_panel_on ? (
  gc_b = 0;
  loop(N_BANDS,
    gc_ry = gc_rows_y + gc_b * gc_rh + (gc_card_on && gc_open == gc_b + 1 ? gc_card_h : 0) *
            (gc_b + 1 > gc_open ? 1 : 0);
    gc_bx = gc_px;
    // B<n>: expands this card, or collapses it when it is already open
    gc_button(gc_bx, gc_ry, 28 * gc_sc, "B", gc_open == gc_b + 1) && gc_click ?
      ( slider143 = gc_open == gc_b + 1 ? 0 : gc_b + 1; slider_automate(slider143); );
    gfx_x = gc_bx + 10 * gc_sc; gfx_y = gc_ry + 4 * gc_sc; gfx_drawnumber(gc_b + 1, 0);
    gc_bx += 32 * gc_sc;
    gc_button(gc_bx, gc_ry, 34 * gc_sc, "Dyn", slider(dynb[gc_b] + 1) == 1) && gc_click ?
      ( gc_w_dyn(gc_b, slider(dynb[gc_b] + 1) == 1 ? 0 : 1); );
    gc_bx += 38 * gc_sc;
    gc_button(gc_bx, gc_ry, 20 * gc_sc, "A", slider(dynb[gc_b] + 7) == 0) && gc_click ?
      ( gc_w_dynmode(gc_b, 0); );
    gc_button(gc_bx + 22 * gc_sc, gc_ry, 20 * gc_sc, "B", slider(dynb[gc_b] + 7) == 1) && gc_click ?
      ( gc_w_dynmode(gc_b, 1); );
    gc_bx += 48 * gc_sc;
    gc_button(gc_bx, gc_ry, 20 * gc_sc, "S", slider(dynb[gc_b] + 8) == 1) && gc_click ?
      ( gc_w_soft(gc_b, slider(dynb[gc_b] + 8) == 1 ? 0 : 1); );
    gc_field_at(100 + gc_b * 10 + 0, gc_bx + 24 * gc_sc, gc_ry, 96 * gc_sc, "Soft ",
                slider(dynb[gc_b] + 3), 2) ?
      ( gc_pfield = 100 + gc_b * 10 + 0; gc_pfield_v = slider(dynb[gc_b] + 3); );
    gc_bx += 124 * gc_sc;
    gc_button(gc_bx, gc_ry, 20 * gc_sc, "H", slider(ceb[gc_b] + 1) == 1) && gc_click ?
      ( gc_w_hard(gc_b, slider(ceb[gc_b] + 1) == 1 ? 0 : 1); );
    gc_field_at(100 + gc_b * 10 + 1, gc_bx + 24 * gc_sc, gc_ry, 96 * gc_sc, "Hard ",
                slider(ceb[gc_b] + 2), 2) ?
      ( gc_pfield = 100 + gc_b * 10 + 1; gc_pfield_v = slider(ceb[gc_b] + 2); );
    gc_b += 1;
  );
);
```

`gc_pfield` is reset to −1 at the top of each frame, before the rows are drawn. `gc_button` draws
and returns `hot`; combining it with `gc_click` is the caller's job, and here the caller is the
single owner of that click.

- [ ] **Step 3: Keep the panel from stealing node clicks**

`gc_in_plot` already gates the node hit set, and the rows are below the plot, so a row click cannot
reach a node. Extend the strip's veto to the panel so the reverse is also true:

```eel2
gc_panel_hot = gc_panel_on && mouse_y >= gc_rows_y &&
               mouse_y < gc_rows_y + 8 * gc_rh + (gc_card_on ? gc_card_h : 0);
gc_strip_hot || gc_panel_hot ? ( gc_hit_n = 0; gc_hover = -1; );
```

- [ ] **Step 4: Compile, gate, null**

```bash
python3 tools/rcbitnova_compile.py
python3 tools/rcbitnova_gates.py --source-only
python3 -u tools/rcbitnova_nulltest.py defaults
```

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.2"
git commit -m "feat(rcbitnova): eight dynamics rows, both cascade stages visible"
```

---

### Task 8: The expanded card

**Files:** modify `JSFX/RCBitNova V1.2`

- [ ] **Step 1: A segmented control, because a numeric field cannot render three labels**

`gc_field_at` draws a number and the keyboard parser accepts digits; showing `0`, `1`, `2` for
Linked / Dual L/R / Dual M/S is not the card that was agreed. Three `gc_button` calls are.

```eel2
// Returns the cell index clicked, or -1. `sel` is the current value; cells are labelled by the
// caller. Reused for Stereo (three cells) and anywhere else an enum needs picking.
function gc_seg3(bx, by, bw, sel, l0, l1, l2) local(w, r) (
  r = -1; w = bw / 3;
  gc_button(bx,         by, w - 2 * gc_sc, l0, sel == 0) && gc_click ? ( r = 0; );
  gc_button(bx + w,     by, w - 2 * gc_sc, l1, sel == 1) && gc_click ? ( r = 1; );
  gc_button(bx + 2 * w, by, w - 2 * gc_sc, l2, sel == 2) && gc_click ? ( r = 2; );
  r;
);
```

- [ ] **Step 2: Draw the card under its row**

```eel2
gc_card_on ? (
  gc_cb = gc_open - 1;
  gc_cy = gc_rows_y + gc_open * gc_rh + 4 * gc_sc;
  gfx_set(0.10, 0.11, 0.14, 1);
  gfx_rect(gc_px, gc_cy, N_BANDS * 34 * gc_sc + 240 * gc_sc, gc_card_h - 8 * gc_sc);

  gfx_set(0.6, 0.6, 0.65, 1);
  gfx_x = gc_px + 6 * gc_sc; gfx_y = gc_cy + 6 * gc_sc; gfx_drawstr("Stereo");
  gc_seg = gc_seg3(gc_px + 60 * gc_sc, gc_cy + 4 * gc_sc, 180 * gc_sc,
                   slider(dynb[gc_cb] + 2), "Linked", "Dual L/R", "Dual M/S");
  gc_seg >= 0 ? ( gc_w_stereo(gc_cb, gc_seg); );

  gc_field_at(100 + gc_cb * 10 + 2, gc_px + 250 * gc_sc, gc_cy + 4 * gc_sc, 110 * gc_sc,
              "Atk ", slider(dynb[gc_cb] + 5), 2) ?
    ( gc_pfield = 100 + gc_cb * 10 + 2; gc_pfield_v = slider(dynb[gc_cb] + 5); );
  gc_field_at(100 + gc_cb * 10 + 3, gc_px + 366 * gc_sc, gc_cy + 4 * gc_sc, 110 * gc_sc,
              "Rel ", slider(dynb[gc_cb] + 6), 0) ?
    ( gc_pfield = 100 + gc_cb * 10 + 3; gc_pfield_v = slider(dynb[gc_cb] + 6); );

  // Micro is PERCENT of a bit, step 0.1 %, which yields 0.001 bit after the division by 100.
  // The total beside it is what the stage actually does: Macro + Micro/100, in bits below 0.
  gc_field_at(100 + gc_cb * 10 + 4, gc_px + 6 * gc_sc, gc_cy + 30 * gc_sc, 130 * gc_sc,
              "Soft Micro % ", slider(dynb[gc_cb] + 4), 1) ?
    ( gc_pfield = 100 + gc_cb * 10 + 4; gc_pfield_v = slider(dynb[gc_cb] + 4); );
  gfx_set(0.55, 0.55, 0.6, 1);
  gfx_x = gc_px + 142 * gc_sc; gfx_y = gc_cy + 34 * gc_sc;
  gfx_drawstr("= "); gfx_drawnumber(slider(dynb[gc_cb] + 3) + slider(dynb[gc_cb] + 4) * 0.01, 2);
  gfx_drawstr(" bits");

  gc_field_at(100 + gc_cb * 10 + 5, gc_px + 250 * gc_sc, gc_cy + 30 * gc_sc, 130 * gc_sc,
              "Hard Micro % ", slider(ceb[gc_cb] + 3), 1) ?
    ( gc_pfield = 100 + gc_cb * 10 + 5; gc_pfield_v = slider(ceb[gc_cb] + 3); );
  gfx_set(0.55, 0.55, 0.6, 1);
  gfx_x = gc_px + 386 * gc_sc; gfx_y = gc_cy + 34 * gc_sc;
  gfx_drawstr("= "); gfx_drawnumber(slider(ceb[gc_cb] + 2) + slider(ceb[gc_cb] + 3) * 0.01, 2);
  gfx_drawstr(" bits");
);
```

- [ ] **Step 3: Sanitise the enum on read**

`slider143` is `<0,8,1>`, so REAPER already clamps it, but automation and presets can still deliver
a fractional value:

```eel2
gc_open = min(max(floor(slider143 + 0.5), 0), N_BANDS);
```

- [ ] **Step 4: Compile, gate, null**

```bash
python3 tools/rcbitnova_compile.py
python3 tools/rcbitnova_gates.py --source-only
python3 -u tools/rcbitnova_nulltest.py defaults
```

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.2"
git commit -m "feat(rcbitnova): the expanded dynamics card"
```

---

### Task 9: Gates, the null suite, and the live matrix

**Files:** modify `tools/rcbitnova_layout.py`, `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Teach the memory model about the new arrays**

`gc_meta` is 48 words at 304..351, above `nb_list` (296..303):

```python
def test_v11_panel_metadata_fits_below_mb_band():
    m = lay.low_layout(8)
    assert max(hi for _, hi in m.values()) + 1 == 272
    assert lay.TABLES_FIRST == 272 and lay.TABLES_LAST == 295
    assert lay.NB_LIST == (296, 303)
    assert lay.GC_META == (304, 351)
    assert 351 < 1024, "everything still sits below mb_band's literal"
```

Add `NB_LIST` and `GC_META` to `rcbitnova_layout.py` and include both in `check_capacity`'s
collision scan, so a future band count that reaches them is reported rather than discovered.

- [ ] **Step 2: Site rows for the panel**

```python
    "panel-rows-loop":   (r"gc_panel_on \? \(\s*\n\s*gc_b = 0;\s*\n\s*loop\((\w+),", "N_BANDS"),
    "panel-enum-clamp":  (r"gc_open = min\(max\(floor\(slider143 \+ 0\.5\), 0\), (\w+)\);",
                          "N_BANDS"),
```

- [ ] **Step 3: Run every gate**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q
python3 tools/rcbitnova_gates.py --source-only && echo SOURCE_OK
python3 tools/rcbitnova_gates.py --live       && echo LIVE_OK
python3 -u tools/rcbitnova_nulltest.py        && echo NULL_OK
```

The null run is the whole suite this time, not one case: five identical, one divergent, comparator
self-test true. **This is the check that says the panel never reached the audio.**

- [ ] **Step 4: The live matrix — reachability is not enough**

A writer passes "the value changed" while `mbmode[]`, `hc[]` or the PDC stay stale. For four of
them the check is **immediate application**: make the gesture, then observe the engine before
touching anything else.

| Parameter | How it is reached | What is observed after the gesture |
|---|---|---|
| Dyn | row toggle | the band starts or stops reducing, audibly; reported PDC changes when it is the only Mode-B band |
| Dyn Mode | row `A`/`B` | the character of the reduction changes immediately, not after the next parameter touch |
| Hard Macro | row `Hard` field, typed and dragged | the hard stage bites at the new threshold on the next transient |
| Hard Micro | card field | same, at 0.1 % resolution |
| Soft, Soft Macro/Micro | row toggle and field | the soft stage's threshold moves |
| Stereo | card segmented control | Dual L/R and Dual M/S behave differently on a wide source |
| Attack, Release | card fields | the envelope's speed changes |

Run every one of them on **B1, B4, B5 and B8** — the first two exercise the legacy slider numbers,
the last two the appended ones, and they are different named branches.

Also:

- both stages on at different thresholds, cascading audibly;
- open a card, save the project, reopen: the same card is open;
- write `slider143 = 5.5` through Param: the panel opens band 5 and does not misdraw;
- shrink the window until the card hides, then grow it back: **the same card reopens**, because the
  enum was never written;
- `gc_small`: the panel is gone and the readout still works;
- Retina: rows, fields and the 4-pixel drag threshold behave the same at `gc_sc` = 1 and 2.

- [ ] **Step 5: Commit**

```bash
git add tools/ tests/
git commit -m "test(rcbitnova): panel gates, memory model and the live matrix"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2.1 the row, both ceilings with their toggles | 7 |
| §2.2 the card, step table, segmented Stereo | 8 |
| §2.3 ceiling fields write and show Macro | 6 (metadata), 7 (row), 8 (Micro and total in the card) |
| §3 geometry, minimum height, derived visibility | 7 |
| §4.1 `apply_band_dyn_global`, PDC via `pdc_dirty`, writer order | 4, 5 |
| §4.2 the 175-record fixture and its five consumers | 1, 2, 3 |
| §4.3 field primitive, metadata, dispatcher, state machine | 6 |
| §5 gates, null, live immediate-application matrix | 9 |
| §6 knee/solo/multi-edit — deliberately absent | none, by design |

**Ordering property:** Tasks 1–2 are tooling and leave the plugin untouched; the fixture records
the plugin as it is *before* the panel, which is the only moment it can be recorded. Task 3 is the
one commit that changes the parameter map, and `--live` verifies it against the fixture immediately.
Tasks 4–8 add no parameters, so `--live` stays green throughout, and every one ends with a null run.

**Dependency check:** no task uses an artifact from a later one. The fixture (1) precedes the
consumers that read it (2, 3); the helper (4) precedes the writers that call it (5); the writers (5)
precede the controller that dispatches to them (6); the controller (6) precedes the rows and card
that draw fields (7, 8); the memory model (9) covers arrays introduced in 6.

**Placeholder scan:** every code step carries real code. Task 5 shows one writer in full and gives
the command that generates the other ten's slider numbers from the tables, rather than saying
"similar". Task 8's segmented control is written out because Stereo cannot use the field primitive.

**Type consistency:** `gc_field_at(id, bx, by, bw, label, value, dec)`, `gc_field_commit(id, v)`,
`gc_seg3(bx, by, bw, sel, l0, l1, l2)`, `apply_band_dyn_global(b)`, `gc_slot_slider(b, slot)` and
the eleven `gc_w_*(b, v)` writers are spelled identically everywhere they appear. Edit ids are
`100 + band*10 + slot` in the controller, the rows and the card alike.
