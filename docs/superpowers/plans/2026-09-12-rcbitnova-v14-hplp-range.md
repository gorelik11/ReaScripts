# RCBitNova V1.4 — HP/LP Range Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Revision 2, 2026-09-12.** Renumbered V1.3 -> **V1.4**: the V1.3 slot was taken by an urgent live
fix (the plugin processed nothing until a parameter was touched). Revised against **three**
weaknesses reviews — 22 findings, every one verified in source before acceptance, none rejected.
Section 10 records the dispositions.

**Goal:** Let the HP/LP corner reach 24 kHz, so the plugin's FIR Brick can band-limit at ~21.5 kHz
before a sample-rate conversion — the job the owner currently does in ReaFIR.

**Architecture:** `JSFX/RCBitNova V1.4` starts as an exact copy of **V1.3** and changes two slider
declarations. The graph has FOUR frequency coordinate sites, not two, and they become one named
contract. The grid reduction that feeds the curve is replaced, because at the new top it
misreports the brickwall by 26 dB. Two numeric fields appear in the top bar, and the top bar must
own its pointer events before node arbitration runs. A new migrator converts the two changed
records through Hz; the null harness stops copying normalised numbers for the same reason, and it
does so BEFORE the declarations move.

**Tech Stack:** JSFX (EEL2); Python 3.11 stdlib-only tooling; `pytest`; `reapy` against live REAPER.

**Spec:** `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md` (**revision 3**).
Section numbers below are that document's. The spec still says "V1.3" throughout; read it as V1.4.

## Global Constraints

- **`JSFX/RCBitNova V1.3` is read-only for the whole of this plan**, as are V1.1 and V1.2. Every
  plugin edit lands in `V1.4`. If a task's diff touches an older version, the task is wrong.
- **No DSP change.** The null test compares V1.4 against **V1.3**, same Hz on both sides, sample
  for sample, zero tolerance, 6 of 6.
- **`tests/fixtures/v11_declared_175.json` and `tools/migrate_v10_to_v11.py` are historical
  evidence and are never edited.**
- **REAPER orders declared parameters by SLIDER NUMBER, not by declaration order.** Measured
  2026-09-04; confirmed three times against the frozen manifest (0 mismatches by number, 68 by
  text). Any derivation of an index from the source must sort numerically.
- **`TrackFX_AddByName` FUZZY-MATCHES.** Measured live 2026-09-12: `add_fx("JS: RCBitNova V1.3")`
  returned a **V1.2** instance reporting 179 parameters and no error text, because REAPER had not
  scanned the new file. Every version-targeted tool now asserts the loaded `fx.name` — that guard
  is already committed. **Before any live check of V1.4, REAPER must rescan** (Preferences ->
  Plug-ins) or be restarted. A live green light on an unscanned file means nothing.
- **Band frequency sliders keep `<20,20000,1>`.** Only records **85** (`HP Freq (Hz)`) and **89**
  (`LP Freq (Hz)`) change range. Both indices are MEASURED, from the frozen manifest.
- Read the exit code directly: `python3 -m pytest ... -q > /tmp/t.txt 2>&1; echo $?`. A pipeline's
  exit code is the last command's, and `pytest | tail && git commit` has put failing tests into
  this repository twice.
- `n_params` does not prove a build compiles; `tools/rcbitnova_compile.py` reads the FX window's
  error text.
- EEL2: no `1e18` literal; parenthesise every assignment inside a ternary branch; no bit-shifts;
  **`@init` is SEQUENTIAL** — a global read above its own assignment reads zero.

## Already done, do NOT redo

These came out of the reviews and are committed:

| Fix | Commit |
|---|---|
| `_function_body` returned the `local(...)` list, not the body | `414da29` |
| `_fine_ceiling_indices` derived indices from TEXTUAL order — 7 of 16 wrong | `d7b1712` |
| `check_source`'s CLI caller and the clean-source test still named V1.2 | in `4858f4e` |
| `BASE` was `"JS: RCBitNova V1.1"`, not V1.2 | in `4858f4e` |
| compile / `--live` / null now assert the loaded effect's version | `7ebc6a6` |

## File Structure

| File | Responsibility |
|---|---|
| `JSFX/RCBitNova V1.4` | create — the plugin. Copy of V1.3 plus this plan's changes. |
| `tests/fixtures/v13_declared_176.json` | create — V1.3's 176 declared records, frozen from the installed build. The baseline V1.4 is compared against. |
| `tools/rcbitnova_gates.py` | modify — V1.4 target, the range-change table, the graph-frequency check, the filter-writer check, the two comparison owners. |
| `tools/rcbitnova_curve.py` | modify — `FMAX` to 24000, and the grid reduction that currently loses the knee. |
| `tools/rcbitnova_layout.py` | modify — `GC_FMETA` grows to eight rows. |
| `tools/rcbitnova_nulltest.py` | modify — index-wise copy BY VALUE, `BASE` V1.3 / `UNDER_TEST` V1.4. |
| `tools/rcbitnova_compile.py` | modify — loads V1.4. |
| `tools/migrate_v13_to_v14.py` | create — the migration. Mirrors the V1.0→V1.1 script's shape, shares none of its constants. |
| `tests/_reaper_fx_fake.py` | modify — declared range/step, the REAL host API shape, a V1.4 branch. |
| `tests/test_rcbitnova_dsp.py` | modify — oracle tests at the knee, migrator tests, seeded defects. |

---

### Task 1: Freeze V1.3's 176 declared records, before V1.4 exists

§5.1. The comparison baseline must be captured while V1.3 is still the only new build installed.

**Files:** create `tests/fixtures/v13_declared_176.json`; modify `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

**Interfaces:** produces `gates.DECLARED_FIXTURE_V13`, `gates.load_declared_v13()`.

- [ ] **Step 1: Confirm REAPER has actually scanned V1.3**

```bash
python3 -c "
import reapy
from reapy import reascript_api as RPR
with reapy.inside_reaper():
    pr = reapy.Project(); RPR.InsertTrackAtIndex(0, False)
    tr = reapy.Project().tracks[0]; fx = tr.add_fx('JS: RCBitNova V1.3')
    print(repr(fx.name.split(' - ')[0]), fx.n_params)
    fx.delete(); RPR.DeleteTrack(reapy.Project().tracks[0].id)"
```
Expected: `'JS: RCBitNova V1.3' 179`. **If it says V1.2, STOP** — REAPER has not scanned the file
and everything below would freeze the wrong plugin. Rescan in Preferences > Plug-ins, or restart.

- [ ] **Step 2: Add the constants and the loader**

```python
# V1.3's full declared block, frozen from the installed build. v11_declared_175.json stays exactly
# as it is - it is evidence of what V1.1 declared. This one is one record longer (slider246, the
# panel-card state) and is the baseline V1.4 is measured against.
DECLARED_FIXTURE_V13 = os.path.join("tests", "fixtures", "v13_declared_176.json")


def load_declared_v13(path=DECLARED_FIXTURE_V13):
    with open(path) as f:
        return [tuple(r) for r in json.load(f)]
```

- [ ] **Step 3: Capture it, REAPER open on a project with ZERO tracks**

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from tools import rcbitnova_gates as g
g.freeze_declared(path=g.DECLARED_FIXTURE_V13, n_declared=176, effect='JS: RCBitNova V1.3')
print('frozen')"
```

- [ ] **Step 4: Pin what was captured**

```python
def test_v13_manifest_is_176_records_and_ends_with_the_panel_state():
    recs = gates.load_declared_v13()
    assert len(recs) == 176
    assert recs[175][1] == "Panel: open dynamics card (0 none, 1..8 band)", recs[175]
    assert (recs[175][2], recs[175][3], recs[175][4]) == (0.0, 8.0, 1.0)
    frozen11 = gates.load_declared()
    assert [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in recs[:175]] == frozen11


def test_v13_manifest_holds_the_two_records_this_feature_changes():
    recs = gates.load_declared_v13()
    assert recs[85][1] == "HP Freq (Hz)" and (recs[85][2], recs[85][3]) == (20.0, 20000.0)
    assert recs[89][1] == "LP Freq (Hz)" and (recs[89][2], recs[89][3]) == (20.0, 20000.0)
```

- [ ] **Step 5: Run and commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v13_manifest > /tmp/t.txt 2>&1; echo $?
git add tests/fixtures/v13_declared_176.json tools/rcbitnova_gates.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): freeze V1.3's 176 declared records before V1.4 exists"
```

---

### Task 2: V1.4 as an exact copy, and every version consumer retargeted

§6. Otherwise a plan passes every unit test against V1.3 and never compiles V1.4 at all.

**Files:** create `JSFX/RCBitNova V1.4`; modify `tools/rcbitnova_gates.py`,
`tools/rcbitnova_compile.py`, `tools/rcbitnova_nulltest.py`, `tests/_reaper_fx_fake.py`,
`tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Copy and install**

```bash
cp "JSFX/RCBitNova V1.3" "JSFX/RCBitNova V1.4"
cp "JSFX/RCBitNova V1.4" ~/Library/Application\ Support/REAPER/Effects/
```

- [ ] **Step 2: Retarget — BOTH the defaults and the explicit callers**

`tools/rcbitnova_gates.py`: add `V14 = "JSFX/RCBitNova V1.4"`. Change **all four**:
`check_source`'s default, `_fine_ceiling_indices`'s `open(...)`, `check_live`'s
`manifest("JS: RCBitNova V1.4", ...)`, and **`main`'s explicit `check_source(V13, ...)` call** —
a default-only change leaves the CLI silently checking the old file.

`tools/rcbitnova_compile.py`: `add_fx("JS: RCBitNova V1.4")`, the delete filter, the version
assertion's message, and the docstring.

`tools/rcbitnova_nulltest.py`: `BASE = "JS: RCBitNova V1.3"`, `UNDER_TEST = "JS: RCBitNova V1.4"`.
Both are explicit assignments; neither is a default.

`tests/_reaper_fx_fake.py`: `N_DECLARED_V14 = 176` and a `"V1.4" in name` branch first.

`tests/test_rcbitnova_dsp.py`: every `gates.V13` — the file opens **and**
`gates.check_source(gates.V13, project=...)` in the clean-source test, which is a call, not an open.

- [ ] **Step 3: Prove it is a copy**

```python
def test_v14_starts_as_an_exact_copy_of_v13():
    """Deleted by Task 5, the commit that first changes V1.4. Its job is to make the starting
    point explicit, not to be permanent."""
    a = open(gates.V13, encoding="utf-8", errors="replace").read()
    b = open(gates.V14, encoding="utf-8", errors="replace").read()
    assert a == b, "V1.4 must begin life identical to V1.3"
```

- [ ] **Step 4: Prove the CLI really targets V1.4**

```python
def test_the_cli_checks_the_file_under_test_not_the_frozen_one():
    """A default-only retarget leaves `main` passing the OLD constant explicitly."""
    seen = []
    with mock.patch.object(gates, "check_source", lambda p=gates.V14, **k: seen.append(p)):
        gates.main(["gate", "--source-only"])
    assert seen == [gates.V14], f"the CLI checked {seen}"
```

- [ ] **Step 5: Run everything, then commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
git add "JSFX/RCBitNova V1.4" tools/ tests/
git commit -m "feat(rcbitnova): V1.4 as an exact copy, every version consumer retargeted"
```

The compile line must name **179 parameters** and the tool must not have refused on the version
assertion. If it refuses, REAPER has not scanned V1.4 — rescan and rerun.

---

### Task 3: Teach the FakeReaper about ranges, using the REAL host API

§4.1. `FakeParam` holds a name, an envelope and a bare `.normalized`. The migrator's one dangerous
mechanism — converting a value across two DIFFERENT ranges — cannot be expressed against it.

**The fake must expose only what real reapy exposes.** Measured: `reapy.FXParam` has `name`,
`normalized`, `range`, `envelope`, `formatted`, `format_value`, `add_envelope` — and **no `.lo`,
no `.hi`**. A fake with a friendlier API is how invalid production code passes offline and breaks
live, which is the opposite of a fake's job.

**Files:** modify `tests/_reaper_fx_fake.py`, `tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_fake_param_converts_between_normalised_and_value_over_its_own_range():
    old = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=20000.0, step=1.0)
    old.value = 12000.0
    assert abs(old.normalized - (12000 - 20) / (20000 - 20)) < 1e-12
    new = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=24000.0, step=1.0)
    new.normalized = old.normalized          # the WRONG migration, expressed
    assert abs(new.value - 14398.4) < 0.1
    new.value = old.value                    # the RIGHT one
    assert abs(new.value - 12000.0) < 1e-9


def test_fake_param_exposes_range_and_NOT_lo_hi_like_real_reapy():
    """reapy.FXParam has .range and no .lo/.hi. A fake that adds them lets production code that
    cannot work live pass offline."""
    p = fake.FakeParam("HP Freq (Hz)", lo=20.0, hi=24000.0, step=1.0)
    assert p.range == (20.0, 24000.0)
    assert not hasattr(p, "lo") and not hasattr(p, "hi")


def test_fake_rpr_get_param_returns_the_reapy_tuple_shape():
    """value at [0], lo at [4], hi at [5] - the positions migrate_v10_to_v11 already reads."""
    tr, rpr = fake.chain("A", "JS: RCBitNova V1.3", "B")
    tr.fxs[1].params[89].value = 12000.0
    r = rpr.TrackFX_GetParam(tr.id, 1, 89, 0, 0)
    assert abs(r[0] - 12000.0) < 0.5 and (r[4], r[5]) == (20.0, 20000.0)
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k "fake_param or fake_rpr" > /tmp/t.txt 2>&1; echo $?
```

- [ ] **Step 3: Implement**

```python
class FakeParam:
    """A declared parameter. `normalized` is what the host stores; `value` is what the user sees.
    Both, over an explicit (lo, hi), is the only way an offline test can tell a correct migration
    from a raw normalised copy.

    `range` and NOT `lo`/`hi`, because that is what reapy.FXParam exposes. The range is reached
    through the RPR boundary in production code, never off the param object.
    """

    __slots__ = ("name", "normalized", "envelope", "_lo", "_hi", "step")

    def __init__(self, name, value=0.0, envelope=None, lo=0.0, hi=1.0, step=0.0):
        self.name, self.normalized, self.envelope = name, value, envelope
        self._lo, self._hi, self.step = lo, hi, step

    @property
    def range(self):
        return (self._lo, self._hi)

    @property
    def value(self):
        return self._lo + self.normalized * (self._hi - self._lo)

    @value.setter
    def value(self, v):
        v = min(max(v, self._lo), self._hi)
        if self.step:
            v = round(v / self.step) * self.step
        self.normalized = 0.0 if self._hi == self._lo else (v - self._lo) / (self._hi - self._lo)
```

`__slots__` makes `hasattr(p, "lo")` false for real, not by convention.

In `FakeRPR` — note the existing `_fx` takes ONE argument, `_fx(self, idx)`:

```python
    def TrackFX_GetParam(self, track_id, fx_index, i, _lo, _hi):
        p = self._fx(fx_index).params[i]
        return (p.value, 0, 0, 0) + p.range

    def TrackFX_SetParamNormalized(self, track_id, fx_index, i, v):
        self._fx(fx_index).params[i].normalized = v
        return True
```

- [ ] **Step 4: Give the V1.3/V1.4 fakes the two real records**

`FakeFX.__init__` names every declared parameter `P{i}`:

```python
        self.params = [FakeParam(f"P{i}") for i in range(n_declared)]
        if n_declared >= 176:
            hi = 24000.0 if "V1.4" in name else 20000.0
            self.params[85] = FakeParam("HP Freq (Hz)", lo=20.0, hi=hi, step=1.0)
            self.params[89] = FakeParam("LP Freq (Hz)", lo=20.0, hi=hi, step=1.0)
            self.params[175] = FakeParam("Panel: open dynamics card (0 none, 1..8 band)",
                                         lo=0.0, hi=8.0, step=1.0)
```

- [ ] **Step 5: Run and commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
git add tests/
git commit -m "test(rcbitnova): the FakeReaper learns declared ranges, with reapy's own API shape"
```

---

### Task 4: The null harness copies state BY VALUE — before any declaration moves

§4.2, §4.3. This task is deliberately ahead of the range change. Its mechanism has no dependency on
widened declarations, and running it later would leave three commits during which the project's
headline constraint cannot be checked at all.

**Files:** modify `tools/rcbitnova_nulltest.py`, `tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Replace the two write modes with one**

`render()` takes `values=` (a name dict, converted through the destination instance's live range —
the right primitive) and `norms=` (a raw normalised pass-through — the flawed path). The second
goes; the first generalises from a name dict to a full index-wise state copy:

```python
N_DECLARED = 176            # NOT the historical 95: the copy must span every record the migrator
                            # also touches, including slider246
...
        def render(fx_name, values=None, state=None):
            """One pass: fresh item, fresh instance, set state, bake, return the file it wrote and
            the N declared ACTUAL VALUES it was holding.

            `state` is a list of actual values BY INDEX, replayed through THIS instance's own
            declared range. It used to be raw normalised numbers copied straight across, which is
            equality by construction only while both versions declare the same ranges - and the
            assertion could not see the difference, because it compared normalised against
            normalised and those always agree. Two cases set LP Freq to 12000 Hz; a raw copy into
            a wider range renders them at 14398 Hz.
            """
            ...
            if state:
                for k, v in enumerate(state):
                    r = RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)
                    lo, hi = r[4], r[5]
                    RPR.TrackFX_SetParamNormalized(tr.id, i, k, (v - lo) / (hi - lo))
            got = [RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)[0] for k in range(N_DECLARED)]
```

- [ ] **Step 2: Compare values, and identities**

```python
            a, state_base = render(BASE, values=values)
            keep = a + ".base.wav"
            os.rename(a, keep)
            b, state_test = render(UNDER_TEST, state=state_base)
            worst = max(range(len(state_base)),
                        key=lambda k: abs(state_base[k] - state_test[k]))
            assert abs(state_base[worst] - state_test[worst]) <= 1e-6, (
                f"{case}: the two instances do not hold the same value at declared record "
                f"{worst}: {BASE} {state_base[worst]}, {UNDER_TEST} {state_test[worst]}")
```

`render` already asserts the loaded `fx.name` carries the requested version — committed in
`7ebc6a6`. Both halves matter: the right effect, holding the right values.

- [ ] **Step 3: The offline test of the conversion itself**

```python
def test_replaying_a_value_through_a_wider_range_preserves_the_value_not_the_number():
    src = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=20000.0, step=1.0)
    src.value = 12000.0
    dst = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=24000.0, step=1.0)
    lo, hi = dst.range
    dst.normalized = (src.value - lo) / (hi - lo)      # what render(state=) now does
    assert abs(dst.value - 12000.0) < 0.5
    dst.normalized = src.normalized                   # what it used to do
    assert abs(dst.value - 14398.4) < 0.1
```

- [ ] **Step 4: Run the FULL null suite, on a project with ZERO tracks**

```bash
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; cat /tmp/n.txt
```
Expected: `0`, 6 of 6 identical. The ranges still match at this point, so this run proves the
**mechanism**, not the range handling — and that is exactly why it belongs here: any failure now
is the harness's, not the feature's.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_nulltest.py tests/
git commit -m "test(rcbitnova): the null harness copies state by VALUE, and compares values"
```

---

### Task 5: One graph-frequency contract, four sites, and the knee the reduction loses

§3.2, §3.3. This task can ship a smooth, believable, wrong curve. It has already been measured
doing so.

**Files:** modify `JSFX/RCBitNova V1.4`, `tools/rcbitnova_curve.py`, `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Write the failing gate check first**

```python
GRAPH_F_SITES = ("gc_x_of_f", "gc_f_of_x", "gc_build_grid", "gc_hplp_bits")


def check_graph_frequency(text, path):
    """ONE frequency contract, read by all four sites.

    The visible axis and the realized linear-phase curve are SEPARATE coordinate systems, each
    with its own hard-coded 20000 and its own log(1000). Widen one and Min phase follows while
    Linear and FIR Brick read a grid built to the old top - or the reverse.

    The check is for the ABSENCE of literals, not the presence of 24000: four copies of the right
    number pass until someone edits three of them.
    """
    for name, want in (("GC_FMIN", "20"), ("GC_FMAX", "24000")):
        m = re.search(rf"^{name} = (\d+);", text, re.M)
        assert m and m.group(1) == want, f"{path}: {name} is not {want}"
    assert re.search(r"^GC_FSPAN = GC_FMAX / GC_FMIN;", text, re.M), \
        f"{path}: GC_FSPAN must be derived, not written out"
    assert re.search(r"^GC_FLOG\s+= log\(GC_FSPAN\);", text, re.M), f"{path}: GC_FLOG missing"
    for fn in GRAPH_F_SITES:
        body = _function_body(text, fn)
        assert body, f"{path}: {fn} not found"
        for bad in ("20000", "24000", "1000"):
            assert bad not in body, \
                f"{path}: {fn} still carries the literal {bad} - every frequency coordinate must " \
                f"come from GC_FMIN/GC_FMAX/GC_FSPAN/GC_FLOG"
        assert "GC_F" in body, f"{path}: {fn} does not read the frequency contract"
    # the contract must be ASSIGNED before gc_fmeta reads it: @init is sequential
    assert text.index("GC_FMAX = ") < text.index("gc_fmeta = "), \
        f"{path}: the frequency contract is assigned AFTER gc_fmeta reads it - EEL2's @init runs " \
        f"top to bottom, so those rows would store a 0..0 range"
```

`_function_body` now skips `local(...)` clauses (`414da29`); `gc_build_grid` and `gc_hplp_bits`
both declare locals, and before that fix this check could never have passed on correct source.

- [ ] **Step 2: Run to verify it fails**

```bash
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
```
Expected: non-zero, `GC_FMIN is not 20`.

- [ ] **Step 3: Declare the contract, ABOVE `gc_fmeta`**

`gc_fmeta` is assigned around source line 315 and `gc_x_of_f` is defined around 1394. **`@init` is
sequential**, so the constants must go with `gc_fmeta`, not with the functions. Put them
immediately above `gc_fmeta = 304;`:

```eel2
// ---- V1.4: ONE graph-frequency contract. Four sites read it: the axis producer and reader, and
// the realized linear-phase GRID's producer and reader. Declared HERE, above gc_fmeta, because
// @init runs top to bottom and the panel metadata rows below read GC_FMIN/GC_FMAX - placed down
// beside the functions they would both read as ZERO and store a 0..0 range.
GC_FMIN = 20;
GC_FMAX = 24000;                  // REQUESTED, not effective: the engine still clamps to
                                  // srate * 0.49, so 44.1 kHz applies at most 21609 Hz
GC_FSPAN = GC_FMAX / GC_FMIN;     // 1200
GC_FLOG  = log(GC_FSPAN);
```

- [ ] **Step 4: Rewrite all four sites**

```eel2
function gc_x_of_f(f) ( gc_px + gc_pw * (log(min(max(f,GC_FMIN),GC_FMAX) / GC_FMIN) / GC_FLOG); );
function gc_f_of_x(x) ( GC_FMIN * pow(GC_FSPAN, min(max((x - gc_px) / gc_pw, 0), 1)); );
```

In `gc_build_grid`: `f = min(GC_FMIN * pow(GC_FSPAN, t), srate * 0.5);`

In `gc_hplp_bits`: `t = log(min(max(f,GC_FMIN),GC_FMAX) / GC_FMIN) / GC_FLOG * (GC_LIN_N - 1);`

The producer clamps to `srate * 0.5` and the reader does not. Deliberate: below the clamp the
producer is exactly the reader's inverse, and above it the curve flattens, which is the truth.

- [ ] **Step 5: Fix the reduction that loses the knee — MEASURED, not suspected**

At the new top the grid cannot represent a brickwall. Measured on the production geometry
(`dsp.fir_brick_kernel(32768, "lp", 21500, 14, 96000)`):

```
  bracketing grid points   21482.04 Hz -> 0.000000 bits
                           21556.58 Hz -> -23.253497 bits
  reader at 21500 Hz       -5.61038 bits
  direct DTFT at 21500 Hz  -1.17372 bits
  ERROR                    4.4367 bits = 26.71 dB
```

The whole transition falls between two adjacent log-grid points, and interpolating across it is
meaningless. **Point-sampling a spectrum is the bug.** Both reductions take the MINIMUM over the
bins each output point spans, falling back to the interpolated value when the span is under one
bin — the standard way an analyser draws a stopband, and it can never hide a wall.

`tools/rcbitnova_curve.py`, in `realized_bits_grid`, replacing the single interpolated sample:

```python
        # span of source bins this output point covers, from the previous output frequency
        f_prev = fmin * (fmax / fmin) ** ((i - 1) / (n_out - 1)) if i else f
        k_lo = max(0, int(min(f_prev, f) * N / sr))
        k_hi = min(half, int(max(f_prev, f) * N / sr) + 1)
        if k_hi - k_lo > 1:
            m = min(mags[k] for k in range(k_lo, k_hi))
        else:
            k0 = int(b); frac = b - k0
            m = mags[k0] * (1.0 - frac) + mags[k0 + 1] * frac
        out.append((f, mag_to_bits(m)))
```

Mirror the same rule in `gc_build_grid`. The display reduction to `GC_N` points takes the minimum
over the grid entries each display vertex spans, for the same reason.

- [ ] **Step 6: Test at the EXACT requested frequencies, not the nearest grid point**

The old test chose the grid entry nearest `f` and compared the DTFT *there*, so it never tested
interpolation and passed at 0.05 bits while the reader was 4.4 bits out.

```python
def _reader_bits(grid, f, fmin=20.0, fmax=24000.0):
    """Exactly what gc_hplp_bits does: log-interpolate between grid entries."""
    t = math.log(min(max(f, fmin), fmax) / fmin) / math.log(fmax / fmin) * (len(grid) - 1)
    i = int(t)
    if i >= len(grid) - 1:
        return grid[-1][1]
    b0, b1 = grid[i][1], grid[i + 1][1]
    return b0 + (b1 - b0) * (t - i)


@pytest.mark.parametrize("f", [21500.0, 21600.0, 22000.0, 23500.0, 24000.0])
@pytest.mark.parametrize("kind,fc", [("lp", 21500.0), ("hp", 21500.0)])
@pytest.mark.parametrize("BD", [8192, 32768])
def test_the_reader_matches_the_dtft_AT_the_requested_frequency(kind, fc, BD, f):
    """Not at the nearest stored point. The knee at fc falls BETWEEN two log-grid entries, and
    that gap is where the curve used to be 26 dB wrong."""
    sr = 96000.0
    ker = dsp.fir_brick_kernel(BD, kind, fc, 14, sr)
    grid = curve.realized_bits_grid(ker, sr, n_out=2048, fmax=24000.0)
    got, want = _reader_bits(grid, f), _dtft_bits(ker, sr, f)
    # a min-over-bins reduction may read LOW at a knee; it must never read HIGH, and never by much
    assert got <= want + 0.10, f"{kind} {BD} at {f} Hz: reader {got:.3f} > DTFT {want:.3f} bits"
    assert got >= want - 1.50, f"{kind} {BD} at {f} Hz: reader {got:.3f} << DTFT {want:.3f} bits"
```

State the tolerances' meaning in the test, as above: overstating the response is the defect that
hides a knee; understating it slightly is what a minimum reduction does by design.

- [ ] **Step 7: Put back the clamp the axis removes**

`gc_f_of_x` could not return more than 20000, which is exactly the BAND sliders' maximum, so the
band-node drag never needed a clamp. It does now. **`gc_w_freq` is the existing eight-branch BAND
writer `(b, v, qz)`** — not one of the filter writers in Task 7.

```eel2
function gc_w_freq(b, v, qz) (
  v = min(max(v, 20), 20000);                         // the BAND range, which does NOT widen:
  qz ? ( v = gc_q_step(v, 1); );                      // gc_f_of_x now reaches GC_FMAX
```

Site row: `"band-freq-clamp": (r"^  v = min\(max\(v, 20\), (\d+)\);", "20000")`.

- [ ] **Step 8: Move the oracle, and audit what depended on its default**

`tools/rcbitnova_curve.py`: `FMIN, FMAX = 20.0, 24000.0`. **Audit, do not merely re-run**, every
existing test that relies on the default `fmax` — a test that passes at both bounds is not testing
the bound:

```bash
grep -n "f_to_x\|x_to_f\|realized_bits_grid\|FMAX" tests/test_rcbitnova_dsp.py
```

- [ ] **Step 9: Seed both halves of every pair**

```python
    (lambda t: t.replace("    f = min(GC_FMIN * pow(GC_FSPAN, t), srate * 0.5);",
                         "    f = min(20 * pow(1000, t), srate * 0.5);"),
     "gc_build_grid still carries the literal 1000"),
    (lambda t: t.replace("      t = log(min(max(f,GC_FMIN),GC_FMAX) / GC_FMIN) / GC_FLOG * (GC_LIN_N - 1);",
                         "      t = log(min(max(f,20),20000) / 20) / log(1000) * (GC_LIN_N - 1);"),
     "gc_hplp_bits still carries the literal 20000"),
    (lambda t: t.replace("  v = min(max(v, 20), 20000);                         // the BAND range",
                         "  // the BAND range"),
     "band-freq-clamp"),
```

**Before adding each, confirm its target string exists in V1.4 as this task leaves it.** A seed
that changes nothing fails the harness's own `assert mutated != clean`; a seed caught by the wrong
assertion is worse than one not caught.

- [ ] **Step 10: Delete Task 2's copy test, run everything, commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
cp "JSFX/RCBitNova V1.4" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; tail -3 /tmp/n.txt
git add "JSFX/RCBitNova V1.4" tools/ tests/
git commit -m "feat(rcbitnova): one graph-frequency contract, and a reduction that keeps the knee"
```

Null is still 6 of 6 here: the declarations have not moved, and none of this touches audio.

---

### Task 6: The two declarations, the range table, and BOTH comparison owners

§3.1, §5.1.

**Files:** modify `JSFX/RCBitNova V1.4`, `tools/rcbitnova_gates.py`, `tests/test_rcbitnova_dsp.py`

**Interfaces:** produces `gates.RANGE_CHANGES` — read here, by the migrator in Task 8.

- [ ] **Step 1: The table and the derived manifest**

```python
# The ONLY records whose declared range differs between V1.3 and V1.4. Data, not two special
# cases in code, because the migrator must agree with exactly this. Indices are MEASURED:
# tests/fixtures/v13_declared_176.json records 85 and 89.
RANGE_CHANGES = {
    85: ((20.0, 20000.0), (20.0, 24000.0)),   # HP Freq (Hz)
    89: ((20.0, 20000.0), (20.0, 24000.0)),   # LP Freq (Hz)
}


def expected_v14_manifest():
    """DERIVED from the V1.3 fixture plus the table - never regenerated from source. --freeze
    agrees with whatever the source happens to say, which is the one thing a baseline must not do.
    """
    out = []
    for i, name, lo, hi, step, default in load_declared_v13():
        if i in RANGE_CHANGES:
            (was_lo, was_hi), (now_lo, now_hi) = RANGE_CHANGES[i]
            assert (lo, hi) == (was_lo, was_hi), \
                f"record {i} ({name}) is {(lo, hi)} in the V1.3 fixture, table says {(was_lo, was_hi)}"
            lo, hi = now_lo, now_hi
        out.append((i, name, lo, hi, step, default))
    return out
```

- [ ] **Step 2: Give BOTH live comparisons an owner**

`check_live` holds two independent comparisons. Task 5 of the old plan replaced only the second.

1. The **historical** loop comparing V1.0's 95 declared records against the build under test, whose
   only exemption is the sixteen ceiling-step records. Records 85 and 89 are NOT in that exemption,
   so once they widen, this loop fails on `hi` before the new assertion is ever reached.
2. The frozen-prefix comparison, which becomes the 176-record derived manifest.

The historical loop is a **V1.0 -> V1.2** contract and belongs on those versions. Either pin it to
V1.2 explicitly, or teach it `RANGE_CHANGES` as a second exemption with the same shape as the
ceiling one — permitted to differ in `hi` and in nothing else. **Pick one and say which in the
commit message**; leaving both unowned is how the gate ends up unable to pass on correct source.

```python
    expected = expected_v14_manifest()
    got = [(r[0], r[1], r[2], r[3], r[4], r[6]) for r in dec14]
    assert len(got) == len(expected), f"V1.4 declares {len(got)}, expected {len(expected)}"
    assert got == expected, next(
        (f"record {i} differs: expected {a}, V1.4 {b}"
         for i, (a, b) in enumerate(zip(expected, got)) if a != b),
        "the derived manifest and V1.4 disagree")
```

- [ ] **Step 3: Offline tests for the table**

```python
def test_expected_v14_manifest_differs_from_v13_in_exactly_two_upper_bounds():
    v13, v14 = gates.load_declared_v13(), gates.expected_v14_manifest()
    assert len(v13) == len(v14) == 176
    diffs = [(a, b) for a, b in zip(v13, v14) if a != b]
    assert [a[0] for a, _ in diffs] == [85, 89], f"changed: {[a[0] for a, _ in diffs]}"
    for a, b in diffs:
        assert a[3] == 20000.0 and b[3] == 24000.0, (a, b)
        assert (a[0], a[1], a[2], a[4], a[5]) == (b[0], b[1], b[2], b[4], b[5]), \
            "only the upper bound may move: not the name, the step or the default"


def test_expected_v14_manifest_refuses_a_baseline_that_does_not_match_the_table():
    import copy
    tampered = copy.deepcopy(gates.load_declared_v13())
    tampered[85] = (85, "HP Freq (Hz)", 20.0, 22000.0, 1.0, 20.0)
    with mock.patch.object(gates, "load_declared_v13", lambda *a, **k: tampered):
        with pytest.raises(AssertionError, match="table says"):
            gates.expected_v14_manifest()
```

- [ ] **Step 4: A RED checkpoint that is actually red**

The old plan's red step ran only offline tests that never read V1.4's declarations, so it was green
before the change. Parse the source instead:

```python
def test_the_source_declares_what_the_range_table_says():
    text = open(gates.V14, encoding="utf-8", errors="replace").read()
    for slider, idx in (("slider132", 85), ("slider136", 89)):
        m = re.search(rf"^{slider}:\d+<20,(\d+),1>", text, re.M)
        assert m, f"{slider} declaration not found"
        assert float(m.group(1)) == gates.RANGE_CHANGES[idx][1][1], \
            f"{slider} declares {m.group(1)}, the table says {gates.RANGE_CHANGES[idx][1][1]}"
```

Run it BEFORE step 5 and record the failure: `slider132 declares 20000, the table says 24000.0`.

- [ ] **Step 5: Change the two declarations**

```
slider132:20<20,24000,1>-HP Freq (Hz)
slider136:20000<20,24000,1>-LP Freq (Hz)
```

Defaults untouched. Site rows:

```python
    "hp-freq-range":         (r"^slider132:20<20,(\d+),1>-HP Freq", "24000"),
    "lp-freq-range":         (r"^slider136:20000<20,(\d+),1>-LP Freq", "24000"),
```

- [ ] **Step 6: Everything, including null and live**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
cp "JSFX/RCBitNova V1.4" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 tools/rcbitnova_gates.py --live > /tmp/gl.txt 2>&1; echo $?; cat /tmp/gl.txt
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; tail -3 /tmp/n.txt
```

All `0`, and the null is **6 of 6** — which is only meaningful because Task 4 already made the
harness copy by value. That ordering is the whole point of putting Task 4 first.

- [ ] **Step 7: Commit**

```bash
git add "JSFX/RCBitNova V1.4" tools/ tests/
git commit -m "feat(rcbitnova): HP/LP reach 24 kHz, with both live comparisons given an owner"
```

---

### Task 7: Top-bar pointer ownership, then the fields, the resolver and the writers

§3.4. Three separate defects live here, and the order matters: ownership first, or the fields
work while the band underneath them silently moves.

**Files:** modify `JSFX/RCBitNova V1.4`, `tools/rcbitnova_layout.py`, `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: The top bar must own its clicks BEFORE node arbitration**

`gc_in_plot` does not exclude the top bar. The band hit set is collected, a disabled band is
enabled, and a band drag is armed — all **before** the top-bar controls are drawn. Publishing
`gc_pfield` afterwards cannot undo a band write that already happened.

Measured at the 900x500 reference: an HP field at `x=308..418, y=14..34` overlaps the node of a
legal band at 260 Hz / Macro 4, whose widened-axis position is about `(347.5, 10)`. One click both
enables that band and arms its drag.

**This is not new to the fields** — the existing `Phase` / `HP res` / `LP res` buttons sit in the
same strip and have the same exposure. Fix it for the strip, not for the two new rectangles.

In the layout block, beside `gc_strip_hot` and `gc_panel_hot`:

```eel2
// V1.4: the top bar owns its own pointer. gc_in_plot does not exclude it, so until now a click on
// a global button could also enable and start dragging whatever band node sat under it. The two
// new frequency fields made that reachable in ordinary use; the three buttons always had it.
gc_topbar_hot = mouse_y >= gc_by && mouse_y < gc_by + gc_fh &&
                mouse_x >= gc_px + gc_pw - 5 * gc_bw - 32 * gc_sc && mouse_x < gc_px + gc_pw;
```

`gc_by`, `gc_bw` are computed further down today; move them up with the rest of the layout — they
depend only on `gc_py`, `gc_pw` and `gc_sc`.

Then extend the existing veto and gate the two band paths:

```eel2
gc_strip_hot || gc_panel_hot || gc_topbar_hot ? ( gc_hit_n = 0; gc_hover = -1; );
```

Since `gc_hover` becomes -1, both `gc_click && gc_hover >= 0 && ...` (enable) and the drag capture
fall away with no further change. Assert that in the gate rather than trusting it.

- [ ] **Step 2: Grow the metadata table, and UPDATE the existing test**

`gc_fmeta` holds six 8-word rows at 304..351; two more take it to 304..367, still far below
`mb_band`'s 1024. In `tools/rcbitnova_layout.py`: `GC_FMETA = (304, 367)`.

**Update `test_panel_metadata_sits_above_the_tables_and_below_mb_band`'s existing `(304, 351)`
assertion.** Do not add a second test asserting 367 beside it: the suite would then contain two
contradictory assertions about one mutable global, and the advertised full-suite green is false.

- [ ] **Step 3: The two rows, with a third table id**

Rows 0..5 address a band table; the filter fields have no band. Table id **3** means "the offset
field IS the slider number". A `drag_mode` replaces the raw pixel law, see Step 5:

```eel2
W_HPFREQ = 12; W_LPFREQ = 13;
// row 6 HP Freq  absolute slider132  GC_FMIN..GC_FMAX  1 Hz  0 dec  logarithmic  W_HPFREQ
gc_fmeta[48]=3; gc_fmeta[49]=132; gc_fmeta[50]=GC_FMIN; gc_fmeta[51]=GC_FMAX; gc_fmeta[52]=1; gc_fmeta[53]=0; gc_fmeta[54]=-120; gc_fmeta[55]=W_HPFREQ;
// row 7 LP Freq  absolute slider136
gc_fmeta[56]=3; gc_fmeta[57]=136; gc_fmeta[58]=GC_FMIN; gc_fmeta[59]=GC_FMAX; gc_fmeta[60]=1; gc_fmeta[61]=0; gc_fmeta[62]=-120; gc_fmeta[63]=W_LPFREQ;
```

These read `GC_FMIN`/`GC_FMAX`, which Task 5 assigned **above** this block. Prove it:

```python
def test_the_frequency_metadata_rows_hold_the_real_range_not_zero():
    """EEL2's @init is sequential. Declared below gc_fmeta, GC_FMIN/GC_FMAX read as 0 and both
    rows would store a 0..0 range - clamping every typed value to zero, silently."""
    text = open(gates.V14, encoding="utf-8", errors="replace").read()
    env = gates.eval_init(text, ["GC_FMIN", "GC_FMAX"])
    assert (env["GC_FMIN"], env["GC_FMAX"]) == (20, 24000)
    for row, slider in ((6, 132), (7, 136)):
        assert f"gc_fmeta[{row*8+1}]={slider};" in text.replace(" ", "")
        assert f"gc_fmeta[{row*8+2}]=GC_FMIN;" in text.replace(" ", "")
        assert f"gc_fmeta[{row*8+3}]=GC_FMAX;" in text.replace(" ", "")
```

- [ ] **Step 4: One id resolver, used by every part of the controller**

```eel2
// ---- V1.4: ONE id resolver. Capture, metadata lookup, current-value read, drag and commit all
// go through these. Ids 200/201 are NOT 100 + band*10 + slot: left to the panel arithmetic, id
// 200 resolves to band 10 and slot 0 - the Soft-ceiling row, and gc_slot_slider reading dynb[10],
// four words past an eight-entry table. A branch in the commit alone would have made typing work
// while the drag compared against, and then wrote, something else.
function gc_field_row(id)  ( id >= 200 ? (6 + (id - 200)) : ((id - 100) % 10); );
function gc_field_band(id) ( id >= 200 ? -1 : floor((id - 100) / 10); );

function gc_field_slider(id) local(r, tb) (
  r = gc_field_row(id); tb = gc_fmeta[r*8];
  tb == 3 ? ( gc_fmeta[r*8 + 1]; ) : (
    (tb == 0 ? stb[gc_field_band(id)] : tb == 1 ? dynb[gc_field_band(id)] : ceb[gc_field_band(id)])
      + gc_fmeta[r*8 + 1];
  );
);
```

- [ ] **Step 5: A drag law a human can use**

Rows 6 and 7 store a 1 Hz step. At the panel's 12 logical pixels per step, dragging LP from 20000
to 21500 would take **18,000 pixels** — in fields that exist precisely because dragging the axis is
too coarse.

Separate the storage step from the drag increment. A **negative** `drag_units` means logarithmic:
its magnitude is logical pixels per octave.

```eel2
  gc_du = gc_fmeta[gc_row*8 + 6];
  gc_du < 0 ? (
    // logarithmic: |gc_du| logical pixels per octave, then quantised to the declared step
    gc_v = gc_cap_v * pow(2, -(mouse_y - gc_cap_y) / gc_sc / (-gc_du));
    gc_v = min(max(gc_v, gc_fmeta[gc_row*8+2]), gc_fmeta[gc_row*8+3]);
    gc_v = floor(gc_v / gc_fmeta[gc_row*8+4] + 0.5) * gc_fmeta[gc_row*8+4];
  ) : (
    gc_v = gc_cap_v - floor((mouse_y - gc_cap_y) / gc_sc / gc_du) * gc_fmeta[gc_row*8 + 4];
  );
```

At 120 px per octave, 20000 -> 21500 is 0.104 octave ≈ **12.5 pixels**. Assert that arithmetic in a
test rather than eyeballing it.

- [ ] **Step 6: The two named writers, and commit**

```eel2
// V1.4: the HP/LP frequency, written in ONE place per engine. Write, automate, THEN rebuild -
// @slider is not guaranteed to run after slider_automate, established live in V1.0. No clamp of
// their own: their declared range widened with the axis, unlike the bands'.
function gc_w_hpfreq(v) ( slider132 = floor(v + 0.5); slider_automate(slider132); gc_apply_hplp(0); );
function gc_w_lpfreq(v) ( slider136 = floor(v + 0.5); slider_automate(slider136); gc_apply_hplp(1); );
```

The handle drag's two `slider132 = ` / `slider136 = ` branches call them. `gc_field_commit` loses
its band arithmetic, uses `gc_field_row`/`gc_field_band`, and gains `W_HPFREQ`/`W_LPFREQ` branches.

- [ ] **Step 7: Gate what can actually fail**

```python
FILTER_WRITERS = {"gc_w_hpfreq": ("slider132", "gc_apply_hplp(0)"),
                  "gc_w_lpfreq": ("slider136", "gc_apply_hplp(1)")}


def check_filter_writers(text, path):
    for fn, (sl, rebuild) in FILTER_WRITERS.items():
        body = _function_body(text, fn)
        assert body, f"{path}: {fn} not found"
        assert f"{sl} = floor(v + 0.5);" in body, f"{path}: {fn} does not write {sl} by name"
        assert f"slider_automate({sl})" in body, f"{path}: {fn} does not automate {sl}"
        assert rebuild in body, f"{path}: {fn} does not call {rebuild}"
        assert body.index(rebuild) > body.index("slider_automate("), \
            f"{path}: {fn} rebuilds before it writes"
    # the controller must resolve ids through the resolver, never through the band path
    for fn in ("gc_field_commit",):
        body = _function_body(text, fn)
        assert "gc_field_row(id)" in body, f"{path}: {fn} does not use the id resolver"
```

An earlier draft asserted `gc_slot_slider not in gc_field_commit`. **That assertion cannot fail** —
`gc_field_commit` never called it, before or after. Assert the presence of the resolver, which can.

- [ ] **Step 8: Run, compile, null, commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
cp "JSFX/RCBitNova V1.4" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; tail -3 /tmp/n.txt
git add "JSFX/RCBitNova V1.4" tools/ tests/
git commit -m "feat(rcbitnova): top-bar pointer ownership, HP/LP fields, resolver and writers"
```

---

### Task 8: `migrate_v13_to_v14.py`

§4.1. A separate tool. `migrate_v10_to_v11.py` and its thirteen tests are not touched.

**Files:** create `tools/migrate_v13_to_v14.py`; modify `tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Write the failing tests, both records, and a sabotage that is not self-consistent**

```python
def _v13_chain():
    tr, rpr = fake.chain("A", "JS: RCBitNova V1.3", "B")
    return tr, rpr, fake.FakeProject(tr)


@pytest.mark.parametrize("idx,hz", [(85, 137.0), (89, 12000.0), (85, 20.0), (89, 20000.0)])
def test_v14_migration_carries_the_frequencies_in_HZ(idx, hz):
    """Both changed records, and both bounds - a swapped index escapes a single-record test."""
    tr, rpr, pr = _v13_chain()
    tr.fxs[1].params[idx].value = hz
    out = migrate_chain_v14(tr, rpr, pr, dry_run=False)
    assert out.startswith("migrated"), out
    assert abs(tr.fxs[1].params[idx].value - hz) < 0.5, \
        f"record {idx} landed at {tr.fxs[1].params[idx].value}, not {hz}"


def test_v14_migration_copies_every_other_record_by_normalised_number():
    tr, rpr, pr = _v13_chain()
    for i in range(176):
        if i not in gates.RANGE_CHANGES:
            tr.fxs[1].params[i].normalized = (i % 17) / 17.0
    migrate_chain_v14(tr, rpr, pr, dry_run=False)
    for i in range(176):
        if i not in gates.RANGE_CHANGES:
            assert tr.fxs[1].params[i].normalized == pytest.approx((i % 17) / 17.0), i


def test_v14_migration_refuses_and_removes_the_new_instance_when_a_value_does_not_read_back():
    """The sabotage must be INDEPENDENT of the migrator's own arithmetic. Changing the
    destination's `hi` is not: the write and the read-back both use it, they agree, and the
    migration succeeds. Perturb the WRITE instead."""
    tr, rpr, pr = _v13_chain()
    tr.fxs[1].params[89].value = 12000.0
    real_set = rpr.TrackFX_SetParamNormalized

    def sabotage(track_id, fx_index, i, v):
        return real_set(track_id, fx_index, i, v * 0.5 if i == 89 else v)

    rpr.TrackFX_SetParamNormalized = sabotage
    out = migrate_chain_v14(tr, rpr, pr, dry_run=False)
    assert out.startswith("REFUSED"), out
    assert "did not read back" in out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.3", "B"], \
        "a refusal must leave NO new instance behind"
```

- [ ] **Step 2: Run to verify they fail, then write the migrator**

Copy `tools/migrate_v10_to_v11.py` to `tools/migrate_v13_to_v14.py` and change, in this order:

1. `N_DECLARED = 176`; source `"RCBitNova V1.3"`, destination `"JS: RCBitNova V1.4"`.
2. Keep every refusal verbatim, and `UNDETECTED` about parameter aliases. **Automation is refused,
   so rescaling envelopes is out of scope** — the precedent is already set.
3. Keep the positional host tail and the GUID-STRING identity.
4. The range is read **through the RPR boundary**, never off the param object — real
   `reapy.FXParam` has `.range` and no `.lo`/`.hi`, and reading attributes the fake alone provides
   is how offline-green code breaks live:

```python
def _param(rpr, track, idx, i):
    """(value, lo, hi). TrackFX_GetParam returns value at [0] and the declared range at [4], [5]."""
    r = rpr.TrackFX_GetParam(track.id, idx, i, 0, 0)
    return r[0], r[4], r[5]
```

5. The read-back **raises**, it does not return:

```python
        for i in RANGE_CHANGES:
            hz = source_hz[i]
            _, lo, hi = _param(rpr, track, dst_idx, i)
            rpr.TrackFX_SetParamNormalized(track.id, dst_idx, i, (hz - lo) / (hi - lo))
        for i in RANGE_CHANGES:
            back, _, _ = _param(rpr, track, dst_idx, i)
            if abs(back - source_hz[i]) > 0.5:          # the declared step is 1 Hz
                raise RuntimeError(f"parameter {i} did not read back: wrote {source_hz[i]} Hz, "
                                   f"read {back} Hz")
```

**`return` from inside `try` would skip the cleanup.** The inherited migrator deletes the new
instance only in its `except` branch; a bare return leaves the chain as `A, V1.3, B, V1.4` while
reporting "source untouched". Raising routes through the existing GUID-based rollback, which is
what the test above asserts.

- [ ] **Step 3: Prove the old migration is untouched, and commit**

```bash
git diff --stat tools/migrate_v10_to_v11.py | wc -l          # must be 0
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
git add tools/migrate_v13_to_v14.py tests/
git commit -m "feat(rcbitnova): migrate_v13_to_v14 carries the two frequencies in Hz"
```

---

### Task 9: Gates, seeded defects, and a live matrix that can fail

§5.2, §7.

- [ ] **Step 1: Every seeded defect rejected for ITS OWN reason**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k seeded > /tmp/t.txt 2>&1; echo $?
```

- [ ] **Step 2: Every gate**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
python3 tools/rcbitnova_gates.py --live > /tmp/gl.txt 2>&1; echo $?; cat /tmp/gl.txt
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; tail -3 /tmp/n.txt
```

Every `echo $?` prints `0`; compile names 179; null says **6 cases identical**. If any live tool
refuses on its version assertion, REAPER has not scanned V1.4 — rescan and rerun. **A live green
light on an unscanned file means nothing**: measured, `add_fx` returns the previous version and
everything passes.

- [ ] **Step 3: The live acceptance test, made able to FAIL first**

In a **96 kHz** project, on material with known energy above 22 kHz:

1. **`Phase: Linear`.** FIR Brick exists only in the linear-phase engine — under Min the slope maps
   to zero sections and no filter runs at all. The handle label says so since V1.3. And the phase
   change is **deferred until the transport stops**, so switch it stopped.
2. **`LP res: High`.** A FIR's transition band is roughly constant in Hz, so its steepness in
   octaves depends entirely on the kernel length. Measured: an HP brick at 43 Hz spans 1.65 octaves
   at BD 8192 and 0.37 at 32768. At 21.5 kHz the same widths are invisible, but say the setting
   anyway so the result is reproducible.
3. **Fail first:** with `LP Slope: Off`, the analyser must SHOW energy above 22 kHz. A test that
   cannot fail has not passed — and in a 44.1 kHz project nothing above 22.05 kHz is representable
   at all, so the whole check would be vacuous there.
4. Type **21500** into the new `LP` field. Read it back from the Param list: 21500 Hz exactly.
5. Measure rejection above 22 kHz against a **written-down dBFS figure**. "Nothing" is not a result
   for a finite windowed FIR.
6. Repeat with `HP`, and repeat both by **dragging**: the resolver and the logarithmic drag law are
   what Task 7 exists for, and a commit-only path passes step 4 and fails this one.
7. Click each field where a band node sits underneath it, with that band disabled: **no band may be
   enabled and no band value may change.** That is Task 7 Step 1.
8. Observe every effect immediately after the gesture, without touching anything else.

- [ ] **Step 4: The migration, live**

A V1.3 instance with `LP Freq` at 12000 Hz; run `migrate_v13_to_v14`; read the V1.4 instance's
`LP Freq` from the Param list. It must say **12000**, not 14398.

- [ ] **Step 5: Commit, then tag**

```bash
git add tools/ tests/
git commit -m "test(rcbitnova): V1.4 gates, seeded defects and the live matrix"
```

Tag only after the owner has actually run the live matrix, and record in the tag message what was
confirmed live and what was not.

---

## 10. Review dispositions

Twenty-two findings across three reviews. **All accepted; none rejected.**

| Review | Finding | Where it lands |
|---|---|---|
| 1 | P0.1 `@init` ordering | Task 5 Step 3, gated in Step 1 |
| 1 | P0.2 `.lo`/`.hi` do not exist on `reapy.FXParam` | Task 3, Task 8 Step 2 |
| 1 | P0.3 `return` from `try` leaves an orphan | Task 8 Step 2 |
| 1 | P1.1 `FakeRPR._fx` takes one argument; no set/get | Task 3 Step 3 |
| 1 | P1.2 self-consistent sabotage | Task 8 Step 1 |
| 1 | P1.3 oracle API and return shape | Task 5 Step 6 |
| 1 | P1.4 unusable drag law | Task 7 Step 5 |
| 1 | P1.5 null harness before the declarations | Task 4, moved ahead of Task 6 |
| 1 | P2.1 red checkpoint already green | Task 6 Step 4 |
| 2 | P0.4 `_function_body` and `local(...)` | **fixed, `414da29`** |
| 2 | P0.5 unfalsifiable `gc_slot_slider` assertion | Task 7 Step 7 |
| 2 | P1 DTFT test unrunnable against the real API | Task 5 Step 6 |
| 2 | P1 missing `gc_fmeta` row-value test | Task 7 Step 3 |
| 2 | P2 seeding order | Task 5 Step 9 |
| 3 | P0.1 the knee, 26.7 dB wrong at 21.5 kHz | Task 5 Step 5, tested in Step 6 |
| 3 | P0.2 top-bar pointer ownership | Task 7 Step 1, live in Task 9 Step 3.7 |
| 3 | P1.1 explicit `check_source` callers | **fixed**; re-asserted in Task 2 Step 4 |
| 3 | P1.2 the V1.0-prefix comparison | Task 6 Step 2 |
| 3 | P1.3 `BASE` named V1.1 | **fixed**; Task 2 Step 2 |
| 3 | P2.1 the 351 assertion left active | Task 7 Step 2 |
| — | `_fine_ceiling_indices` textual order | **fixed, `d7b1712`** |
| — | `add_fx` fuzzy-matches an unscanned version | **fixed, `7ebc6a6`**; Global Constraints |

## Self-Review

**Known gap, stated rather than hidden.** No gate asserts that `v11_declared_175.json` is never
modified; `git diff --stat` is the check, and it is in the Global Constraints. A test that reads a
file to prove nobody read it differently is circular.

**Ordering.** Task 4 before Task 6 removes the window in which the null result is meaningless.
Tasks 3 and 5 have no dependency on each other. Task 7 Step 1 must precede Step 6, or the fields
work while the band underneath them moves.

**Live prerequisite.** Tasks 1, 2, 4, 5, 6, 7, 8 and 9 all touch REAPER, and every one of them
needs REAPER to have **scanned the file under test**. Task 1 Step 1 is the check; if it names the
wrong version, nothing downstream is evidence.
