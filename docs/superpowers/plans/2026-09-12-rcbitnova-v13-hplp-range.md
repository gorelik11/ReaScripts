# RCBitNova V1.3 — HP/LP Range Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Let the HP/LP corner reach 24 kHz, so the plugin's FIR Brick can band-limit at ~21.5 kHz
before a sample-rate conversion — the job the owner currently does in ReaFIR.

**Architecture:** `JSFX/RCBitNova V1.3` starts as an exact copy of V1.2 and changes two slider
declarations. The graph has FOUR frequency coordinate sites, not two, and they become one named
contract that all four read. Two numeric fields appear in the top bar. A new migrator converts the
two changed records through Hz; the null harness stops copying normalised numbers for the same
reason. **No DSP change: the null test compares V1.3 against V1.2 at zero tolerance.**

**Tech Stack:** JSFX (EEL2); Python 3.11 stdlib-only tooling (`tools/rcbitnova_*.py`); `pytest`;
`reapy` against live REAPER.

**Spec:** `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md` (**revision 3**).
Section numbers below are that document's.

## Global Constraints

- **`JSFX/RCBitNova V1.2` is read-only for the whole of this plan.** It is tagged
  `rcbitnova-v1.2` and in the owner's projects. Every plugin edit lands in `V1.3`. If a task's diff
  touches V1.2, the task is wrong.
- **No DSP change.** Same Hz on both sides, sample for sample, zero tolerance, 6 of 6.
- **`tests/fixtures/v11_declared_175.json` and `tools/migrate_v10_to_v11.py` are historical
  evidence and are never edited.**
- **REAPER orders declared parameters by SLIDER NUMBER, not by declaration order.** Measured
  2026-09-04; confirmed twice against the frozen manifest (0 mismatches by number, 68 by text). Any
  derivation of an index from the source must sort numerically.
- **Band frequency sliders keep `<20,20000,1>`.** Only records **85** (`HP Freq (Hz)`) and **89**
  (`LP Freq (Hz)`) change range.
- Read the exit code directly: `python3 -m pytest ... -q > /tmp/t.txt 2>&1; echo $?`. A pipeline's
  exit code is the last command's, and `pytest | tail && git commit` has put failing tests into
  this repository twice.
- `n_params` does not prove a build compiles. `tools/rcbitnova_compile.py` reads the FX window's
  error text; that is the check.
- EEL2: no `1e18` literal; parenthesise every assignment inside a ternary branch; no bit-shifts.

## File Structure

| File | Responsibility |
|---|---|
| `JSFX/RCBitNova V1.3` | create — the plugin. Copy of V1.2 plus this plan's changes. |
| `tests/fixtures/v12_declared_176.json` | create — V1.2's 176 declared records, frozen from the TAGGED build. The baseline V1.3 is compared against. |
| `tools/rcbitnova_gates.py` | modify — V1.3 target, the range-change table, new site rows, the two filter writers' own check, the 176-record comparison. |
| `tools/rcbitnova_curve.py` | modify — `FMAX` to 24000. |
| `tools/rcbitnova_layout.py` | modify — `GC_FMETA` grows to eight rows. |
| `tools/rcbitnova_nulltest.py` | modify — index-wise copy BY VALUE, `UNDER_TEST` to V1.3. |
| `tools/rcbitnova_compile.py` | modify — loads V1.3. |
| `tools/migrate_v12_to_v13.py` | create — the migration. Mirrors the V1.0→V1.1 script's shape, shares none of its constants. |
| `tests/_reaper_fx_fake.py` | modify — declared range/step, an actual-value accessor, a V1.3 branch. |
| `tests/test_rcbitnova_dsp.py` | modify — oracle tests near the new top, migrator tests, seeded defects. |

---

### Task 1: Freeze V1.2's 176 declared records, before V1.3 exists

The comparison baseline has to be captured from the tagged build while it is still the only one
installed. §5.1.

**Files:** create `tests/fixtures/v12_declared_176.json`; modify `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `gates.DECLARED_FIXTURE_V12`, `gates.load_declared_v12()`, and
  `gates.freeze_declared(path, n_declared, effect)` reused with V1.2's numbers.

- [ ] **Step 1: Confirm the installed V1.2 is the tagged one**

```bash
diff -q "JSFX/RCBitNova V1.2" ~/Library/Application\ Support/REAPER/Effects/"RCBitNova V1.2" \
  && git diff --stat rcbitnova-v1.2 -- "JSFX/RCBitNova V1.2" | wc -l
```
Expected: no diff output, and `0`. If either disagrees, STOP: the fixture would freeze something
other than what shipped.

- [ ] **Step 2: Add the constants and the loader**

In `tools/rcbitnova_gates.py`, beside `DECLARED_FIXTURE`:

```python
# V1.2's full declared block, frozen from the TAGGED build. Separate from v11_declared_175.json,
# which stays exactly as it is: that file is evidence of what V1.1 declared and is what proves
# V1.2's first 175 records. This one is one record longer - V1.2 added slider246, the panel-card
# state - and record 175 is frozen NOWHERE until this exists.
DECLARED_FIXTURE_V12 = os.path.join("tests", "fixtures", "v12_declared_176.json")


def load_declared_v12(path=DECLARED_FIXTURE_V12):
    with open(path) as f:
        return [tuple(r) for r in json.load(f)]
```

- [ ] **Step 3: Capture it, with REAPER open on an EMPTY project**

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from tools import rcbitnova_gates as g
g.freeze_declared(path=g.DECLARED_FIXTURE_V12, n_declared=176, effect='JS: RCBitNova V1.2')
print('frozen')"
```
Expected: `frozen`. It refuses if the track already holds an RCBitNova.

- [ ] **Step 4: Write the test that pins what was captured**

In `tests/test_rcbitnova_dsp.py`:

```python
def test_v12_manifest_is_176_records_and_ends_with_the_panel_state():
    recs = gates.load_declared_v12()
    assert len(recs) == 176
    assert recs[175][1] == "Panel: open dynamics card (0 none, 1..8 band)", recs[175]
    assert (recs[175][2], recs[175][3], recs[175][4]) == (0.0, 8.0, 1.0)
    # the first 175 must BE V1.1's, which is what made V1.2 a drop-in
    frozen11 = gates.load_declared()
    got = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in recs[:175]]
    assert got == frozen11


def test_v12_manifest_holds_the_two_records_this_feature_changes():
    recs = gates.load_declared_v12()
    assert recs[85][1] == "HP Freq (Hz)" and (recs[85][2], recs[85][3]) == (20.0, 20000.0)
    assert recs[89][1] == "LP Freq (Hz)" and (recs[89][2], recs[89][3]) == (20.0, 20000.0)
```

- [ ] **Step 5: Run**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v12_manifest > /tmp/t.txt 2>&1; echo $?
```
Expected: `0`, 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/v12_declared_176.json tools/rcbitnova_gates.py tests/test_rcbitnova_dsp.py
git commit -m "test(rcbitnova): freeze V1.2's 176 declared records before V1.3 exists"
```

---

### Task 2: V1.3 as an exact copy, and every version consumer retargeted

§6. A plan can otherwise pass every unit test against V1.2 and never compile V1.3 at all.

**Files:** create `JSFX/RCBitNova V1.3`; modify `tools/rcbitnova_gates.py`,
`tools/rcbitnova_compile.py`, `tools/rcbitnova_nulltest.py`, `tests/_reaper_fx_fake.py`,
`tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `gates.V13`; `nulltest.UNDER_TEST == "JS: RCBitNova V1.3"`, `BASE` stays V1.2.

- [ ] **Step 1: Copy, and install**

```bash
cp "JSFX/RCBitNova V1.2" "JSFX/RCBitNova V1.3"
cp "JSFX/RCBitNova V1.3" ~/Library/Application\ Support/REAPER/Effects/
```

- [ ] **Step 2: Retarget the consumers**

`tools/rcbitnova_gates.py`: add `V13 = "JSFX/RCBitNova V1.3"`, make `check_source`'s default
`path=V13`, point `_fine_ceiling_indices` at `V13`, and in `check_live` load
`"JS: RCBitNova V1.3"` with `N_DECLARED_V13 = 176`. `V12` stays, as the frozen comparison source.

`tools/rcbitnova_compile.py`: `add_fx("JS: RCBitNova V1.3")`, the delete filter, and the docstring
— it still opens "Does JSFX/RCBitNova V1.1 actually COMPILE?".

`tools/rcbitnova_nulltest.py`: `UNDER_TEST = "JS: RCBitNova V1.3"`; `BASE` stays
`"JS: RCBitNova V1.2"`. Fix the V1.0/V1.1 premise in the module docstring and in the two
diagnostics that name versions.

`tests/_reaper_fx_fake.py`: `N_DECLARED_V13 = 176`, and extend the branch:

```python
n = (N_DECLARED_V13 if "V1.3" in name else
     N_DECLARED_V12 if "V1.2" in name else
     N_DECLARED_V11 if "V1.1" in name else N_DECLARED_V10)
```

`tests/test_rcbitnova_dsp.py`: the four direct `gates.V12` opens become `gates.V13`.

- [ ] **Step 3: Prove it is a copy**

```python
def test_v13_starts_as_an_exact_copy_of_v12():
    """Until a later task changes it deliberately. The project's rule since V0.1 is that a new
    version is a new FILE, and the only safe starting point is byte equality."""
    a = open(gates.V12, encoding="utf-8", errors="replace").read()
    b = open(gates.V13, encoding="utf-8", errors="replace").read()
    assert a == b, "V1.3 must begin life identical to V1.2"
```

(This test is DELETED in Task 4, by the commit that first changes V1.3. Its job is to make the
copy explicit, not to be permanent.)

- [ ] **Step 4: Run everything**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
```
Expected: all `0`; the compile line must name **179 parameters**.

- [ ] **Step 5: Commit**

```bash
git add "JSFX/RCBitNova V1.3" tools/ tests/
git commit -m "feat(rcbitnova): V1.3 as an exact copy, every version consumer retargeted"
```

---

### Task 3: Teach the FakeReaper about ranges, before anything needs them

§4.1, review round two P0.2. `FakeParam` holds a name, an envelope and a bare `.normalized` float.
The migrator's one dangerous mechanism — converting a value through two DIFFERENT ranges — cannot
be expressed, let alone failed, against it.

**Files:** modify `tests/_reaper_fx_fake.py`, `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `FakeParam(name, value=0.0, envelope=None, lo=0.0, hi=1.0, step=0.0)` with a `.value`
  property; `FakeRPR.TrackFX_GetParam(track_id, fx, i, 0, 0) -> (value, ..., lo, hi)` matching
  reapy's tuple positions `[0]`, `[4]`, `[5]`.

- [ ] **Step 1: Write the failing test**

```python
def test_fake_param_converts_between_normalised_and_value_over_its_own_range():
    """The whole point: the same normalised number means different Hz in different ranges, and
    that is what the migration has to survive."""
    old = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=20000.0, step=1.0)
    old.value = 12000.0
    assert abs(old.normalized - (12000 - 20) / (20000 - 20)) < 1e-12

    new = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=24000.0, step=1.0)
    new.normalized = old.normalized          # the WRONG migration, expressed
    assert abs(new.value - 14398.4) < 0.1, "a raw normalised copy must land at 14398.4 Hz"

    new.value = old.value                    # the RIGHT one
    assert abs(new.value - 12000.0) < 1e-9
```

- [ ] **Step 2: Run to verify it fails**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k fake_param_converts > /tmp/t.txt 2>&1; echo $?
```
Expected: non-zero — `FakeParam() got an unexpected keyword argument 'lo'`.

- [ ] **Step 3: Implement**

```python
class FakeParam:
    """A declared parameter. `normalized` is what the host stores; `value` is what the user sees.
    Keeping BOTH, over an explicit (lo, hi), is the only way an offline test can tell a correct
    migration from a raw normalised copy - and telling those apart is this fake's new job."""

    def __init__(self, name, value=0.0, envelope=None, lo=0.0, hi=1.0, step=0.0):
        self.name = name
        self.normalized = value
        self.envelope = envelope
        self.lo, self.hi, self.step = lo, hi, step

    @property
    def value(self):
        return self.lo + self.normalized * (self.hi - self.lo)

    @value.setter
    def value(self, v):
        v = min(max(v, self.lo), self.hi)
        if self.step:
            v = round(v / self.step) * self.step
        self.normalized = 0.0 if self.hi == self.lo else (v - self.lo) / (self.hi - self.lo)
```

Add to `FakeRPR`, matching reapy's tuple positions exactly — the migrator reads `[0]`, `[4]`,
`[5]`:

```python
    def TrackFX_GetParam(self, track_id, fx_index, i, _lo, _hi):
        p = self._fx(track_id, fx_index).params[i]
        return (p.value, 0, 0, 0, p.lo, p.hi)
```

- [ ] **Step 4: Run to verify it passes**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k fake_param_converts > /tmp/t.txt 2>&1; echo $?
```
Expected: `0`.

- [ ] **Step 5: Give the V1.2/V1.3 fakes the two real ranges**

`FakeFX.__init__` currently names every declared parameter `P{i}`. Records 85 and 89 must carry
their real names and ranges, or the migrator's tests cannot address them:

```python
        self.params = [FakeParam(f"P{i}") for i in range(n_declared)]
        if n_declared >= 176:                       # V1.2 and V1.3 both declare 176
            hi = 24000.0 if "V1.3" in name else 20000.0
            self.params[85] = FakeParam("HP Freq (Hz)", lo=20.0, hi=hi, step=1.0)
            self.params[89] = FakeParam("LP Freq (Hz)", lo=20.0, hi=hi, step=1.0)
```

- [ ] **Step 6: Run the whole suite and commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
git add tests/
git commit -m "test(rcbitnova): the FakeReaper learns declared ranges, so a bad migration can fail"
```

---

### Task 4: One graph-frequency contract, all four sites, and the clamp the axis removes

§3.2 and §3.3. This is the task that can ship a smooth, believable, wrong curve.

**Files:** modify `JSFX/RCBitNova V1.3`, `tools/rcbitnova_curve.py`, `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: EEL2 `GC_FMIN`, `GC_FMAX`, `GC_FSPAN`, `GC_FLOG`; Python `curve.FMAX == 24000.0`.

- [ ] **Step 1: Write the failing gate check first**

In `tools/rcbitnova_gates.py`:

```python
GRAPH_F_SITES = ("gc_x_of_f", "gc_f_of_x", "gc_build_grid", "gc_hplp_bits")


def check_graph_frequency(text, path):
    """ONE frequency contract, read by all four sites.

    The visible axis and the realized linear-phase curve are SEPARATE coordinate systems, each
    with its own hard-coded 20000 and its own log(1000) in V1.2. Widen one and Min phase follows
    while Linear and FIR Brick read a grid built to the old top - or the reverse. Either way the
    curve is smooth, believable and wrong.

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
                f"{path}: {fn} still carries the literal {bad} - every frequency coordinate " \
                f"must come from GC_FMIN/GC_FMAX/GC_FSPAN/GC_FLOG"
        assert "GC_F" in body, f"{path}: {fn} does not read the frequency contract"
```

Call it from `check_source` after `check_addresses`.

- [ ] **Step 2: Run to verify it fails**

```bash
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
```
Expected: non-zero — `GC_FMIN is not 20` (it does not exist yet).

- [ ] **Step 3: Declare the contract in `@init`**

Immediately above `function gc_x_of_f`:

```eel2
// ---- V1.3: ONE graph-frequency contract. Four sites read it: the axis producer and reader, and
// the realized linear-phase GRID's producer and reader. V1.2 had the top and the log base written
// out four times, in two unrelated coordinate systems, and changing one pair would have left
// Linear and FIR Brick reading a grid built to a different top.
GC_FMIN = 20;
GC_FMAX = 24000;                  // requested, not effective: the engine still clamps to
                                  // srate * 0.49, so 44.1 kHz applies at most 21609 Hz
GC_FSPAN = GC_FMAX / GC_FMIN;     // 1200
GC_FLOG  = log(GC_FSPAN);
```

- [ ] **Step 4: Rewrite all four sites**

```eel2
function gc_x_of_f(f)    ( gc_px + gc_pw * (log(min(max(f,GC_FMIN),GC_FMAX) / GC_FMIN) / GC_FLOG); );
function gc_f_of_x(x)    ( GC_FMIN * pow(GC_FSPAN, min(max((x - gc_px) / gc_pw, 0), 1)); );
```

In `gc_build_grid`, the grid producer:

```eel2
    f = min(GC_FMIN * pow(GC_FSPAN, t), srate * 0.5);
```

In `gc_hplp_bits`, the grid reader:

```eel2
      t = log(min(max(f,GC_FMIN),GC_FMAX) / GC_FMIN) / GC_FLOG * (GC_LIN_N - 1);
```

The producer clamps to `srate * 0.5` and the reader does not. That is deliberate and stays: below
the clamp the producer is exactly the reader's inverse, and above it the curve flattens, which is
the truth — there is no response above Nyquist.

- [ ] **Step 5: Put the clamp the axis just removed into `gc_w_freq`**

`gc_f_of_x` could not return more than 20000, which is exactly the BAND sliders' maximum, so the
band-node drag never needed a clamp. It does now. `gc_w_freq` is the existing eight-branch BAND
writer `(b, v, qz)` — not one of the filter writers added in Task 6.

```eel2
function gc_w_freq(b, v, qz) (
  v = min(max(v, 20), 20000);                         // the BAND range, which does NOT widen:
  qz ? ( v = gc_q_step(v, 1); );                      // gc_f_of_x now reaches GC_FMAX
```

And in `check_writers`' record, or as its own site row:

```python
    "band-freq-clamp":       (r"^  v = min\(max\(v, 20\), (\d+)\);", "20000"),
```

- [ ] **Step 6: Move the Python oracle with them**

`tools/rcbitnova_curve.py`: `FMIN, FMAX = 20.0, 24000.0`.

**Audit, do not merely re-run, every existing test that relies on the default `fmax`.** A test that
passes at both bounds is not testing the bound. Find them with:

```bash
grep -n "f_to_x\|x_to_f\|realized_bits_grid\|FMAX" tests/test_rcbitnova_dsp.py
```

- [ ] **Step 7: Write the oracle tests at the new top**

```python
@pytest.mark.parametrize("f", [21500.0, 22000.0, 23500.0, 24000.0])
@pytest.mark.parametrize("kind", ["hp", "lp"])
def test_realized_grid_matches_a_direct_dtft_near_the_new_top(kind, f):
    """The reduced log grid must agree with the kernel's own transform where this feature lives.
    Below 20 kHz the two agreed in V1.2 as well; this is the region that is new."""
    sr = 96000.0
    kernel = curve.brick_kernel(kind, 21500.0, sr)
    freqs, bits = curve.realized_bits_grid(kernel, sr)
    i = min(range(len(freqs)), key=lambda k: abs(freqs[k] - f))
    direct = curve.dtft_bits(kernel, freqs[i], sr)
    assert abs(bits[i] - direct) < 0.05, \
        f"{kind} at {freqs[i]:.0f} Hz: grid {bits[i]:.3f} bits, DTFT {direct:.3f}"


def test_the_grid_top_is_the_contract_top():
    freqs, _ = curve.realized_bits_grid(curve.brick_kernel("lp", 21500.0, 96000.0), 96000.0)
    assert abs(freqs[-1] - 24000.0) < 1e-6, "the oracle's grid must end where GC_FMAX does"
```

If `curve.brick_kernel` or `curve.dtft_bits` are named differently, use the existing names —
`grep -n "^def " tools/rcbitnova_curve.py` — and keep the assertions.

- [ ] **Step 8: Seed the defects that matter**

Both halves of every pair, so changing one is never enough:

```python
    # axis widened, realized GRID left behind - the smooth believable wrong curve
    (lambda t: t.replace("    f = min(GC_FMIN * pow(GC_FSPAN, t), srate * 0.5);",
                         "    f = min(20 * pow(1000, t), srate * 0.5);"),
     "gc_build_grid still carries the literal 1000"),
    # grid producer widened, its READER left behind
    (lambda t: t.replace("      t = log(min(max(f,GC_FMIN),GC_FMAX) / GC_FMIN) / GC_FLOG * (GC_LIN_N - 1);",
                         "      t = log(min(max(f,20),20000) / 20) / log(1000) * (GC_LIN_N - 1);"),
     "gc_hplp_bits still carries the literal 20000"),
    # the band clamp the widened axis removed
    (lambda t: t.replace("  v = min(max(v, 20), 20000);                         // the BAND range",
                         "  // the BAND range"),
     "band-freq-clamp"),
```

- [ ] **Step 9: Delete Task 2's copy test, gate, compile, null**

The copy test asserted byte equality with V1.2; this task is the commit that ends that.

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
cp "JSFX/RCBitNova V1.3" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 -u tools/rcbitnova_nulltest.py defaults > /tmp/n.txt 2>&1; echo $?; tail -3 /tmp/n.txt
```
Expected: all `0`; compile names 179; `defaults identical`. The null still passes trivially here —
the declarations have not moved yet, so the same normalised numbers still mean the same Hz.

- [ ] **Step 10: Commit**

```bash
git add "JSFX/RCBitNova V1.3" tools/ tests/
git commit -m "feat(rcbitnova): one graph-frequency contract, read by all four sites"
```

---

### Task 5: The two declarations, and the fixture comparison that permits exactly two differences

§3.1 and §5.1.

**Files:** modify `JSFX/RCBitNova V1.3`, `tools/rcbitnova_gates.py`, `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `gates.RANGE_CHANGES` — `{85: ((20.0, 20000.0), (20.0, 24000.0)), 89: (...)}` — read by
  the gate here, by the migrator in Task 7 and by the null harness in Task 8.

- [ ] **Step 1: Write the range-change table and the comparison first**

```python
# The ONLY records whose declared range differs between V1.2 and V1.3. Data, not two special
# cases in code, because this is what the migrator and the null harness must both agree with.
# Indices are MEASURED: tests/fixtures/v12_declared_176.json records 85 and 89.
RANGE_CHANGES = {
    85: ((20.0, 20000.0), (20.0, 24000.0)),   # HP Freq (Hz)
    89: ((20.0, 20000.0), (20.0, 24000.0)),   # LP Freq (Hz)
}


def expected_v13_manifest():
    """DERIVED from the V1.2 fixture plus the table - never regenerated from source. --freeze
    agrees with whatever the source happens to say, which is the one thing a baseline must not do.
    """
    out = []
    for rec in load_declared_v12():
        i, name, lo, hi, step, default = rec
        if i in RANGE_CHANGES:
            (was_lo, was_hi), (now_lo, now_hi) = RANGE_CHANGES[i]
            assert (lo, hi) == (was_lo, was_hi), \
                f"record {i} ({name}) is {(lo, hi)} in the V1.2 fixture, table says {(was_lo, was_hi)}"
            lo, hi = now_lo, now_hi
        out.append((i, name, lo, hi, step, default))
    return out
```

In `check_live`, replace the frozen-prefix comparison with the full 176:

```python
    expected = expected_v13_manifest()
    got = [(r[0], r[1], r[2], r[3], r[4], r[6]) for r in dec13]
    assert len(got) == len(expected), f"V1.3 declares {len(got)}, expected {len(expected)}"
    assert got == expected, next(
        (f"record {i} differs: expected {a}, V1.3 {b}"
         for i, (a, b) in enumerate(zip(expected, got)) if a != b),
        "the derived manifest and V1.3 disagree")
```

- [ ] **Step 2: Write the offline tests for the table**

```python
def test_expected_v13_manifest_differs_from_v12_in_exactly_two_upper_bounds():
    v12 = gates.load_declared_v12()
    v13 = gates.expected_v13_manifest()
    assert len(v12) == len(v13) == 176
    diffs = [(a, b) for a, b in zip(v12, v13) if a != b]
    assert [a[0] for a, _ in diffs] == [85, 89], f"changed records: {[a[0] for a, _ in diffs]}"
    for a, b in diffs:
        assert a[3] == 20000.0 and b[3] == 24000.0, (a, b)
        assert (a[0], a[1], a[2], a[4], a[5]) == (b[0], b[1], b[2], b[4], b[5]), \
            "only the upper bound may move: not the name, the step or the default"


def test_expected_v13_manifest_refuses_a_v12_fixture_that_does_not_match_the_table():
    """The table names what it is changing FROM. If the baseline ever stops saying that, the
    derivation is built on something it was not written for and must refuse, not adapt."""
    import copy
    real = gates.load_declared_v12()
    tampered = copy.deepcopy(real)
    tampered[85] = (85, "HP Freq (Hz)", 20.0, 22000.0, 1.0, 20.0)
    with mock.patch.object(gates, "load_declared_v12", lambda *a, **k: tampered):
        with pytest.raises(AssertionError, match="table says"):
            gates.expected_v13_manifest()
```

- [ ] **Step 3: Run to verify they fail**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v13_manifest > /tmp/t.txt 2>&1; echo $?
```
Expected: non-zero — the V1.3 file still declares 20000, so `expected_v13_manifest` is fine but
`--live` would fail; the offline tests pass only once `RANGE_CHANGES` exists.

- [ ] **Step 4: Change the two declarations**

In `JSFX/RCBitNova V1.3`:

```
slider132:20<20,24000,1>-HP Freq (Hz)
slider136:20000<20,24000,1>-LP Freq (Hz)
```

**Defaults are NOT touched** — HP stays 20, LP stays 20000 — so each record differs in its upper
bound alone.

Add the site rows:

```python
    "hp-freq-range":         (r"^slider132:20<20,(\d+),1>-HP Freq", "24000"),
    "lp-freq-range":         (r"^slider136:20000<20,(\d+),1>-LP Freq", "24000"),
```

- [ ] **Step 5: Run everything, live gate included**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
cp "JSFX/RCBitNova V1.3" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 tools/rcbitnova_gates.py --live > /tmp/gl.txt 2>&1; echo $?; cat /tmp/gl.txt
```
Expected: all `0`.

**Do not run the null test yet.** It still copies raw normalised numbers, and from this commit on
that means a different LP frequency on each side. Task 8 fixes it; Task 8 is also where the null
result becomes meaningful again. This is the one window in the plan where the null is knowingly
untrustworthy, and it is stated here so nobody reads its failure as a DSP regression.

- [ ] **Step 6: Commit**

```bash
git add "JSFX/RCBitNova V1.3" tools/ tests/
git commit -m "feat(rcbitnova): HP/LP reach 24 kHz, and a range-change table two rows long"
```

---

### Task 6: Two filter writers and one ID resolver

§3.4. The resolver is the point: a commit-only branch makes typing work while the drag silently
compares against, and then writes, another band's parameter.

**Files:** modify `JSFX/RCBitNova V1.3`, `tools/rcbitnova_layout.py`, `tools/rcbitnova_gates.py`,
`tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Produces: `gc_w_hpfreq(v)`, `gc_w_lpfreq(v)`, `gc_field_row(id)`, `gc_field_band(id)`,
  `gc_field_slider(id)`; `gc_fmeta` rows 6 and 7; `layout.GC_FMETA == (304, 367)`.

- [ ] **Step 1: Grow the metadata table to eight rows**

`gc_fmeta` holds six 8-word rows at 304..351. Two more take it to 304..367, still well below
`mb_band`'s literal 1024. In `tools/rcbitnova_layout.py`:

```python
GC_FMETA = (304, 367)                     # 8 panel slots x 8 words
```

and the test that pins it:

```python
def test_panel_metadata_grew_by_two_rows_and_still_clears_mb_band():
    assert lay.GC_FMETA == (304, 367)
    assert lay.NB_LIST[1] + 1 == lay.GC_FMETA[0]
    assert lay.GC_FMETA[1] < lay.MB_BAND
    assert (lay.GC_FMETA[1] - lay.GC_FMETA[0] + 1) == 8 * 8
```

- [ ] **Step 2: Add the two rows, with a THIRD table id**

Rows 0..5 address a band table; the filter fields have no band. Table id **3** means "the offset
field IS the slider number":

```eel2
W_HPFREQ = 12; W_LPFREQ = 13;
// row 6 HP Freq  absolute slider132  20..24000  1 Hz  0 dec  12 px  W_HPFREQ
gc_fmeta[48]=3; gc_fmeta[49]=132; gc_fmeta[50]=GC_FMIN; gc_fmeta[51]=GC_FMAX; gc_fmeta[52]=1; gc_fmeta[53]=0; gc_fmeta[54]=12; gc_fmeta[55]=W_HPFREQ;
// row 7 LP Freq  absolute slider136  20..24000  1 Hz  0 dec  12 px  W_LPFREQ
gc_fmeta[56]=3; gc_fmeta[57]=136; gc_fmeta[58]=GC_FMIN; gc_fmeta[59]=GC_FMAX; gc_fmeta[60]=1; gc_fmeta[61]=0; gc_fmeta[62]=12; gc_fmeta[63]=W_LPFREQ;
```

- [ ] **Step 3: The resolver, beside `gc_slot_slider`**

```eel2
// ---- V1.3: ONE id resolver. Every part of the field controller goes through these - capture,
// metadata lookup, current-value read, drag and commit alike.
//
// Ids 200/201 are NOT 100 + band*10 + slot. Left to the panel arithmetic, id 200 resolves to band
// 10 and slot 0: the Soft-ceiling metadata row, and gc_slot_slider reading dynb[10], four words
// past an eight-entry table. A branch in the commit alone would have made typing work while the
// drag compared against, and then wrote, something else entirely.
function gc_field_row(id)   ( id >= 200 ? (6 + (id - 200)) : ((id - 100) % 10); );
function gc_field_band(id)  ( id >= 200 ? -1 : floor((id - 100) / 10); );

function gc_field_slider(id) local(r, tb) (
  r = gc_field_row(id); tb = gc_fmeta[r*8];
  tb == 3 ? ( gc_fmeta[r*8 + 1]; ) : (
    (tb == 0 ? stb[gc_field_band(id)] : tb == 1 ? dynb[gc_field_band(id)] : ceb[gc_field_band(id)])
      + gc_fmeta[r*8 + 1];
  );
);
```

- [ ] **Step 4: The two named writers**

```eel2
// V1.3: the HP/LP frequency, written in ONE place per engine. Write, automate, THEN rebuild -
// @slider is not guaranteed to run after slider_automate, established live in V1.0. No clamp of
// their own: their declared range widened with the axis, unlike the bands'.
function gc_w_hpfreq(v) (
  slider132 = floor(v + 0.5); slider_automate(slider132); gc_apply_hplp(0);
);
function gc_w_lpfreq(v) (
  slider136 = floor(v + 0.5); slider_automate(slider136); gc_apply_hplp(1);
);
```

The handle drag at the two `slider132 = ` / `slider136 = ` lines now calls them:

```eel2
    gc_fdrag == 0 ? ( gc_v != slider132 ? ( gc_w_hpfreq(gc_v); ); )
                  : ( gc_v != slider136 ? ( gc_w_lpfreq(gc_v); ); );
```

- [ ] **Step 5: Route commit and drag through the resolver**

`gc_field_commit` loses its band arithmetic and gains the two families:

```eel2
function gc_field_commit(id, v) local(b, r, w, lo, hi, st) (
  r = gc_field_row(id); b = gc_field_band(id);
  lo = gc_fmeta[r*8 + 2]; hi = gc_fmeta[r*8 + 3]; st = gc_fmeta[r*8 + 4];
  v = min(max(v, lo), hi);
  v = floor(v / st + 0.5) * st;
  w = gc_fmeta[r*8 + 7];
  w == W_SOFTCEIL  ? ( gc_w_softceil(b, v);  ) :
  w == W_HARDCEIL  ? ( gc_w_hardceil(b, v);  ) :
  w == W_ATK       ? ( gc_w_atk(b, v);       ) :
  w == W_REL       ? ( gc_w_rel(b, v);       ) :
  w == W_SOFTMICRO ? ( gc_w_softmicro(b, v); ) :
  w == W_HARDMICRO ? ( gc_w_hardmicro(b, v); ) :
  w == W_HPFREQ    ? ( gc_w_hpfreq(v);       ) :
  w == W_LPFREQ    ? ( gc_w_lpfreq(v);       );
);
```

and the drag block in `@gfx`:

```eel2
    gc_row = gc_field_row(gc_cap);
    gc_v = gc_cap_v - floor((mouse_y - gc_cap_y) / gc_sc / gc_fmeta[gc_row*8 + 6])
                      * gc_fmeta[gc_row*8 + 4];
    gc_v != slider(gc_field_slider(gc_cap)) ? ( gc_field_commit(gc_cap, gc_v); );
```

- [ ] **Step 6: Draw the two fields in the top bar**

Beside the three existing buttons, which sit at `gc_px + gc_pw - {3,2,1} * gc_bw`:

```eel2
gc_hf0 = gc_field_at(200, gc_px + gc_pw - 5 * gc_bw - 32 * gc_sc, gc_by, gc_bw,
                     "HP ", slider132, 0);
gc_hf0 ? ( gc_pfield = 200; gc_pfield_v = slider132; );
gc_hf1 = gc_field_at(201, gc_px + gc_pw - 4 * gc_bw - 24 * gc_sc, gc_by, gc_bw,
                     "LP ", slider136, 0);
gc_hf1 ? ( gc_pfield = 201; gc_pfield_v = slider136; );
```

These must be drawn BEFORE the field controller runs, exactly as the panel rows are — the
controller reads `gc_pfield`, which is reset at the top of the frame.

- [ ] **Step 7: Gate the resolver and the writers**

`check_writers` cannot cover `gc_w_hpfreq`/`gc_w_lpfreq`: it asserts eight branches and a `(b, v)`
signature. They get their own:

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
    # the controller must never take a filter id down the band path
    for fn in ("gc_field_commit",):
        body = _function_body(text, fn)
        assert "gc_slot_slider" not in body, \
            f"{path}: {fn} still calls gc_slot_slider - ids 200/201 have no band"
```

Site row for the drag:

```python
    "field-drag-resolver":   (r"gc_v != slider\((gc_field_slider)\(gc_cap\)\);?", "gc_field_slider"),
```

- [ ] **Step 8: Seed the defect this task exists to prevent**

```python
    (lambda t: t.replace("gc_v != slider(gc_field_slider(gc_cap)) ?",
                         "gc_v != slider(gc_slot_slider(floor((gc_cap - 100) / 10), gc_row)) ?"),
     "field-drag-resolver"),
```

- [ ] **Step 9: Run, compile, commit**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
cp "JSFX/RCBitNova V1.3" ~/Library/Application\ Support/REAPER/Effects/
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
git add "JSFX/RCBitNova V1.3" tools/ tests/
git commit -m "feat(rcbitnova): HP/LP numeric fields, two named writers and one id resolver"
```

---

### Task 7: `migrate_v12_to_v13.py`

§4.1. A separate tool. `migrate_v10_to_v11.py` and its thirteen tests are not touched.

**Files:** create `tools/migrate_v12_to_v13.py`; modify `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `gates.RANGE_CHANGES`, `fake.FakeParam.value`.
- Produces: `migrate_chain_v13(track, rpr, project, dry_run=True) -> str`.

- [ ] **Step 1: Write the failing test — the one that tells a good migration from a copy**

```python
def _v12_chain():
    tr, rpr = fake.chain("A", "JS: RCBitNova V1.2", "B")
    return tr, rpr, fake.FakeProject(tr)


def test_v13_migration_carries_the_two_frequencies_in_HZ_not_normalised():
    tr, rpr, pr = _v12_chain()
    src = tr.fxs[1]
    src.params[89].value = 12000.0                    # LP Freq, inside the OLD range
    out = migrate_chain_v13(tr, rpr, pr, dry_run=False)
    assert out.startswith("migrated"), out
    dst = tr.fxs[1]
    assert dst.name == "RCBitNova V1.3"
    assert abs(dst.params[89].value - 12000.0) < 0.5, \
        f"LP Freq landed at {dst.params[89].value} Hz - a raw normalised copy gives 14398.4"


def test_v13_migration_copies_every_other_record_by_normalised_number():
    tr, rpr, pr = _v12_chain()
    src = tr.fxs[1]
    for i in range(176):
        if i not in (85, 89):
            src.params[i].normalized = (i % 17) / 17.0
    migrate_chain_v13(tr, rpr, pr, dry_run=False)
    dst = tr.fxs[1]
    for i in range(176):
        if i not in (85, 89):
            assert dst.params[i].normalized == pytest.approx((i % 17) / 17.0), i


def test_v13_migration_refuses_when_a_converted_frequency_does_not_read_back():
    """A migration that cannot PROVE the frequency survived must refuse, not report success."""
    tr, rpr, pr = _v12_chain()
    tr.fxs[1].params[89].value = 12000.0
    real_add = tr.add_fx

    def sabotage(name):
        fx = real_add(name)
        fx.params[89].hi = 20000.0        # destination lies about its range
        return fx

    tr.add_fx = sabotage
    out = migrate_chain_v13(tr, rpr, pr, dry_run=False)
    assert out.startswith("REFUSED"), out
    assert "did not read back" in out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.2", "B"], "source must survive a refusal"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v13_migration > /tmp/t.txt 2>&1; echo $?
```
Expected: non-zero — `migrate_chain_v13` is not defined.

- [ ] **Step 3: Write the migrator**

Copy `tools/migrate_v10_to_v11.py` to `tools/migrate_v12_to_v13.py` and change, in this order:

1. `N_DECLARED = 176`; source `"RCBitNova V1.2"`, destination `"JS: RCBitNova V1.3"`.
2. Keep every refusal verbatim — automation, parameter modulation, non-default pin maps, instance
   oversampling, an ambiguous chain — and keep `UNDETECTED` about parameter aliases.
3. Keep the positional host tail and the GUID-STRING identity.
4. The conversion, and the read-back that makes it provable:

```python
from tools.rcbitnova_gates import RANGE_CHANGES

def _hz(rpr, track, idx, i):
    """The ACTUAL value, not the normalised one. TrackFX_GetParam returns value at [0] and the
    declared range at [4], [5]."""
    r = rpr.TrackFX_GetParam(track.id, idx, i, 0, 0)
    return r[0], r[4], r[5]

# ... after the destination exists, before the source is removed:
    for i in RANGE_CHANGES:
        hz, _, _ = source_hz[i]
        lo, hi = dst.params[i].lo, dst.params[i].hi
        rpr.TrackFX_SetParamNormalized(track.id, dst_idx, i, (hz - lo) / (hi - lo))

    for i in RANGE_CHANGES:
        hz = source_hz[i][0]
        back, _, _ = _hz(rpr, track, dst_idx, i)
        if abs(back - hz) > 0.5:                       # the declared step is 1 Hz
            return (f"REFUSED, source untouched: parameter {i} did not read back - "
                    f"wrote {hz} Hz, read {back} Hz")
```

The refusal must run **before** the V1.2 instance is deleted, and unwind inside the existing
`try/finally` so the undo block stays balanced.

- [ ] **Step 4: Run to verify they pass**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v13_migration > /tmp/t.txt 2>&1; echo $?
```
Expected: `0`.

- [ ] **Step 5: Prove the old migration is untouched**

```bash
git diff --stat tools/migrate_v10_to_v11.py | wc -l
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v11_migration > /tmp/t.txt 2>&1; echo $?
```
Expected: `0` lines of diff, and exit `0`.

- [ ] **Step 6: Commit**

```bash
git add tools/migrate_v12_to_v13.py tests/
git commit -m "feat(rcbitnova): migrate_v12_to_v13 carries the two frequencies in Hz"
```

---

### Task 8: The null harness stops copying normalised numbers

§4.2 and §4.3. Until this lands the null result means nothing.

**Files:** modify `tools/rcbitnova_nulltest.py`, `tests/test_rcbitnova_dsp.py`

**Interfaces:**
- Consumes: `gates.RANGE_CHANGES` (for the diagnostic only — the copy is by value for every
  record, so it needs no table).

- [ ] **Step 1: Replace the two write modes with one**

`render()` currently takes `values=` (a name dict, converted through the DESTINATION's live range —
the right primitive) and `norms=` (a raw normalised pass-through — the flawed path). The second
goes; the first generalises from a name dict to a full index-wise state copy:

```python
        def render(fx_name, values=None, state=None):
            """One pass: fresh item, fresh instance, set state, bake, return the file it wrote and
            the N declared ACTUAL VALUES it was holding.

            `state` is a list of actual values by INDEX, replayed through THIS instance's own
            declared range. It used to be a list of raw normalised numbers copied straight across,
            which is equality by construction only while both versions declare the same ranges -
            and the assertion below could not see the difference, because it compared normalised
            against normalised and those always agree. Two cases set LP Freq to 12000 Hz; a raw
            copy into V1.3's wider range renders them at 14398 Hz.
            """
            ...
            if state:
                for k, v in enumerate(state):
                    r = RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)
                    lo, hi = r[4], r[5]
                    RPR.TrackFX_SetParamNormalized(tr.id, i, k, (v - lo) / (hi - lo))
            got = [RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)[0] for k in range(N_DECLARED)]
```

with `N_DECLARED = 176` at module scope — **not** the historical 95. The old read-back stopped at
95, so a widened comparison is also a wider comparison.

- [ ] **Step 2: Compare values, not normalised numbers**

```python
            a, state12 = render(BASE, values=values)
            keep = a + ".base.wav"
            os.rename(a, keep)
            b, state13 = render(UNDER_TEST, state=state12)
            worst = max(range(len(state12)), key=lambda k: abs(state12[k] - state13[k]))
            assert abs(state12[worst] - state13[worst]) <= 1e-6, (
                f"{case}: the two instances do not hold the same value at declared record "
                f"{worst}: {BASE} {state12[worst]}, {UNDER_TEST} {state13[worst]}")
```

- [ ] **Step 3: Write the offline test for the conversion itself**

The harness needs REAPER, but the arithmetic does not:

```python
def test_replaying_a_value_through_a_wider_range_preserves_the_value_not_the_number():
    """The whole of the null harness's fix, in one assertion."""
    src = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=20000.0, step=1.0)
    src.value = 12000.0
    dst = fake.FakeParam("LP Freq (Hz)", lo=20.0, hi=24000.0, step=1.0)
    dst.normalized = (src.value - dst.lo) / (dst.hi - dst.lo)     # what render(state=) now does
    assert abs(dst.value - 12000.0) < 0.5
    dst.normalized = src.normalized                               # what it used to do
    assert abs(dst.value - 14398.4) < 0.1
```

- [ ] **Step 4: Run the whole null suite**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; cat /tmp/n.txt
```
Expected: both `0`. **6 of 6 identical, zero tolerance** — including `min_hplp` and
`linear_hplp`, the two that would have rendered at 14398 Hz before this task.

Needs REAPER on a project with **zero** tracks; the harness refuses otherwise.

- [ ] **Step 5: Commit**

```bash
git add tools/rcbitnova_nulltest.py tests/
git commit -m "test(rcbitnova): the null harness copies state by VALUE, and compares values"
```

---

### Task 9: Gates, seeded defects, and the live matrix

§5.2, §7.

**Files:** modify `tools/rcbitnova_gates.py`, `tests/test_rcbitnova_dsp.py`

- [ ] **Step 1: Confirm every seeded defect is rejected for ITS OWN reason**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k seeded > /tmp/t.txt 2>&1; echo $?
```
Expected: `0`. Each mutant must fail on its own message, not on a neighbour's. A mutant that
changes nothing fails the harness's own `assert mutated != clean`.

- [ ] **Step 2: Run every gate**

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?; cat /tmp/g.txt
python3 tools/rcbitnova_gates.py --live > /tmp/gl.txt 2>&1; echo $?; cat /tmp/gl.txt
python3 tools/rcbitnova_compile.py > /tmp/c.txt 2>&1; echo $?; cat /tmp/c.txt
python3 -u tools/rcbitnova_nulltest.py > /tmp/n.txt 2>&1; echo $?; tail -3 /tmp/n.txt
```
Expected: every `echo $?` prints `0`; compile names 179 parameters; null says 6 cases identical.

- [ ] **Step 3: The live acceptance test — made able to FAIL first**

In a **96 kHz** project, on material with known energy above 22 kHz:

1. `Phase: Linear`, `LP Slope: FIR Brick`, `LP res: High`, **`LP Slope: Off` first**. The analyser
   must SHOW energy above 22 kHz. **A test that cannot fail has not passed** — if the source has
   nothing up there, the rest proves nothing, and at 44.1 kHz nothing is representable above
   22.05 kHz at all.
2. Type **21500** into the new `LP` field. Read the value back from the Param list: it must be
   21500 Hz, not a normalised neighbour.
3. Measure rejection above 22 kHz against a stated threshold — write down the dBFS figure. "Nothing"
   is not a result for a finite windowed FIR.
4. Repeat with the `HP` field, and repeat both by DRAGGING rather than typing: the resolver is what
   Task 6 exists for, and a commit-only path would pass step 2 and fail this one.
5. Observe the effect immediately after each gesture, without touching anything else — that is the
   `gc_apply_hplp` rebuild, and `@slider` is not guaranteed to run after `slider_automate`.

- [ ] **Step 4: The migration, live**

On a scratch project: a V1.2 instance with `LP Freq` set to 12000 Hz, run `migrate_v12_to_v13`,
and read the V1.3 instance's `LP Freq` from the Param list. It must say **12000**, not 14398.

- [ ] **Step 5: Commit, then tag**

```bash
git add tools/ tests/
git commit -m "test(rcbitnova): V1.3 gates, seeded defects and the live matrix"
```

Tag only after the live matrix has actually been run by the owner, and record in the tag message
what was confirmed live and what was not.

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §3.1 two declarations | 5 |
| §3.2 four-site contract, oracle, DTFT tests | 4 |
| §3.3 the clamp the axis removes | 4 |
| §3.4 two writers, the fields, the ID resolver | 6 |
| §4.1 a separate migrator; FakeReaper first | 3, 7 |
| §4.2 / §4.3 the null harness by value | 8 |
| §5.1 a new 176-record fixture; V1.1's untouched | 1, 5 |
| §5.2 source gate rows and seeded defects | 4, 5, 6, 9 |
| §5.3 null 6 of 6 | 8, 9 |
| §6 version ownership | 2 |
| §7 requested vs effective; the falsifiable live test | 9 |

**Known gap, stated rather than hidden:** the plan does not add a gate row asserting that
`tests/fixtures/v11_declared_175.json` is never modified. `git diff --stat` on it is the check, and
it is listed in the Global Constraints instead. A test that reads a file to prove nobody read it
differently is circular.

**Ordering that matters:** Task 5 changes the declarations and the null test becomes untrustworthy
until Task 8. This is stated in Task 5 Step 5 so its failure is not read as a DSP regression. Tasks
3 and 4 have no dependency on each other and may be swapped.
