"""RCBitNova V1.1 source gate.

Source-level only: no REAPER, no rendering. Answers one question - does `JSFX/RCBitNova V1.1`
say what the design says it says?

ONE CONTRACT, TWO PHASES. The pre-flip run works on a PROJECTION: the source text with
`N_BANDS = 4` substituted to 8 in memory, checked against the full post-flip contract. Nothing is
excused, and after the real flip the identical assertions run on the real text. An earlier draft
let the pre-flip run fail its own first assertion, which made the post-flip run prove nothing.

Run:
    python3 tools/rcbitnova_gates.py --preflip       # before the count is raised
    python3 tools/rcbitnova_gates.py --source-only   # after
"""

import ast
import json
import math
import os
import re
import sys

try:
    from tools import rcbitnova_layout as layout
except ImportError:                      # also runnable from inside tools/
    import rcbitnova_layout as layout

DECLARED_FIXTURE = os.path.join("tests", "fixtures", "v11_declared_175.json")

V10 = "JSFX/RCBitNova V1.0"
V11 = "JSFX/RCBitNova V1.1"          # FROZEN: tagged rcbitnova-v1.1, shipped, in the owner's
                                     # projects. Never edited again.
V12 = "JSFX/RCBitNova V1.2"          # the working file - every source check below targets this
N_DECLARED_V11 = 175                 # frozen forever
N_DECLARED_V12 = 176                 # 175 inherited + the panel-state slider, last

# finditer, not match: several assignments can share a line, and anchoring to the first one loses
# the rest.
ASSIGN = re.compile(r"(?:^|;)\s*(\w+)\s*=\s*([^;]+)")


def eval_init(text, wanted):
    """name -> word address, evaluated from the text's own @init.

    FIRST assignment wins. The map is set up once at the top of @init, but V1.0 reuses several of
    those names as ordinary locals further down - `st` is a loop counter inside lpk_build. Keeping
    the last value read st as 0 instead of 64 and failed check_addresses on CLEAN source.
    """
    env, out = {}, {}
    for line in text.splitlines():
        line = line.split("//")[0]
        for m in ASSIGN.finditer(line):
            name = m.group(1)
            expr = re.sub(r"\bceil\(", "_ceil(", m.group(2).strip())
            try:
                value = eval(compile(ast.parse(expr, mode="eval"), "<init>", "eval"),
                             {"_ceil": math.ceil, "__builtins__": {}}, dict(env))
            except Exception:
                continue
            if isinstance(value, (int, float)):
                env.setdefault(name, value)
                if name in wanted and name not in out:
                    out[name] = int(value)
    missing = set(wanted) - set(out)
    if missing:
        raise AssertionError(f"could not evaluate {sorted(missing)}")
    return out


# --------------------------------------------------------------------------------------------
# The site manifest. Every row was RUN against the shipped source before it was written down:
# a row that matches nothing is the defect this gate exists to catch, and three earlier drafts
# shipped rows that could never fire.
# --------------------------------------------------------------------------------------------
SITES = {
    "count-declaration":     (r"^N_BANDS = (\d+);", "8"),
    # The panel slider's NUMBER must be above every existing one. REAPER orders parameters by
    # slider number, not by declaration order (measured 2026-09-04): numbered 143 it landed at
    # record 95 and pushed the whole B5-B8 block down by one, while V1.0's 95-record prefix stayed
    # intact so every V1.0-based check still passed.
    "panel-slider-number":   (r"^slider(246):0<0,8,1>-Panel:", "246"),
    "table-decl-stb":        (r"^stb\s+= (\d+);", "272"),
    "table-decl-dynb":       (r"^dynb\s+= (\d+);", "280"),
    "table-decl-ceb":        (r"^ceb\s+= (\d+);", "288"),
    "gc_fc-sizing":          (r"^gc_fc\s+= gc_kc \+ (\w+) \* 8;", "N_BANDS"),
    "clear-derived":         (r"^memset\(gc_trace, 0, (gc_hits \+ 8 - gc_trace)\);",
                              "gc_hits + 8 - gc_trace"),
    # --- FILL BOUNDS. These write state and produce no address, so the address gate is blind to
    # them: loop(4 * 2, egh[i] = 1) leaves B5-B8's Mode-A hard envelopes at zero while every
    # modelled address stays correct. Each needs its own row.
    "fill-st":               (r"^memset\(st, 0, (\w+) \* 4\);", "N_BANDS"),
    "fill-dst":              (r"^memset\(dst, 0, (\w+) \* 4\);", "N_BANDS"),
    "fill-cst":              (r"^memset\(cst, 0, (\w+) \* 4\);", "N_BANDS"),
    "fill-mbwpos":           (r"^memset\(mbwpos, 0, (\w+)\);", "N_BANDS"),
    "fill-eg":               (r"loop\((\w+) \* 2, eg\[i\] = 1;", "N_BANDS"),
    "fill-mbenv":            (r"loop\((\w+) \* 2, mbenv\[i\] = 1;", "N_BANDS"),
    "fill-mbgc":             (r"loop\((\w+) \* 2, mbgc\[i\] = 1;", "N_BANDS"),
    "fill-mbeh":             (r"loop\((\w+) \* 2, mbeh\[i\] = 1;", "N_BANDS"),
    "fill-egh":              (r"loop\((\w+) \* 2, egh\[i\] = 1;", "N_BANDS"),
    # --- runtime loops ---
    "helper-gc_domain_bits": (r"function gc_domain_bits[\s\S]*?loop\((\w+),", "N_BANDS"),
    "helper-gc_dom_used":    (r"function gc_dom_used[\s\S]*?loop\((\w+),", "N_BANDS"),
    "slider-setup":          (r"^loop\((\w+), setup_band\(b\); setup_band_dyn\(b\); b \+= 1;\);",
                              "N_BANDS"),
    "slider-modeb-scan":     (r"loop\((\w+),\s*\n\s*mbmode\[b\] = slider\(dynb\[b\] \+ 7\);",
                              "N_BANDS"),
    # The enabled-band cache and the loop that walks it. These two rows were ONE row until the
    # cache existed, and the moment it did the old pattern started matching the BUILDER instead of
    # the audio loop - passing for the wrong reason. Anchor each to something only it contains.
    "slider-nb-list":        (r"loop\((\w+),\s*\n\s*slider\(stb\[b\] \+ 1\) == 1 \? "
                              r"\( nb_list\[nb_n\] = b;", "N_BANDS"),
    "sample-band-loop":      (r"nbi = 0;\s*\n\s*loop\((\w+),\s*\n\s*b = nb_list\[nbi\];",
                              "nb_n"),
    # Mode B walks the same enabled-band cache as the static pass. It did not in V1.0, where a
    # band switched OFF but left in Mode B still ran its split limiter on the bus.
    "sample-modeb-pass":     (r"corrL = 0; corrR = 0;\s*\n\s*nbi = 0;\s*\n\s*loop\((\w+),",
                              "nb_n"),
    "modeb-any-gate":        (r"\(slider\(stb\[b\] \+ 1\) == 1 && slider\(dynb\[b\] \+ 1\) "
                              r"== 1 && (mbmode)\[b\] == 1", "mbmode"),
    "gfx-band-setup":        (r"^loop\((\w+), gc_band_setup\(gc_b\); gc_b \+= 1;\);", "N_BANDS"),
    "gfx-hit-test":          (r"^gc_hit_n = 0;\ngc_b = 0;\nloop\((\w+),", "N_BANDS"),
    "gfx-node-draw":         (r"loop\((\w+),\s*\n\s*gc_s = stb\[gc_b\];\s*\n\s*gc_en = "
                              r"slider\(gc_s \+ 1\);", "N_BANDS"),
}

# Open-coded band-slider arithmetic. Allowed ONLY on the lines that declare and fill the tables,
# marked TABLE-DECL / TABLE-FILL. The exemption is per LINE, not per section: setup_band,
# band_qeff and every gc_* helper are declared inside @init and would otherwise be exempt too.
FORBIDDEN = [
    (r"10 ?\* ?\((?:b|gc_b|gc_hover|gc_drag|gc_sel) ?\+ ?1\)", "static-slider arithmetic"),
    (r"50 ?\+ ?10 ?\* ?b\b", "dynamics-slider arithmetic"),
    (r"90 ?\+ ?10 ?\* ?b\b", "ceiling-slider arithmetic"),
]

TABLE_ENTRY = re.compile(r"^\s*(stb|dynb|ceb)\[(\d+)\]\s*=\s*(\d+);", re.M)

WRITERS = {"gc_w_enable": 1, "gc_w_type": 2, "gc_w_freq": 3, "gc_w_q": 4, "gc_w_macro": 5,
           "gc_w_micro": 6, "gc_w_ratio": 7, "gc_w_place": 8, "gc_w_qchar": 9}

AUDIO = [n for n, _, _ in layout.AUDIO_CHAIN]
GUI = ["gc_lin", "gc_snap", "gc_meta", "gc_kc", "gc_fc", "gc_ebuf", "gc_hits"]


# --------------------------------------------------------------------------------------------
# The frozen parameter map.
#
# REAPER stores a parameter by its POSITION in declaration order. A version that inserts one in
# the middle makes every later parameter read a neighbour's value - no error, no crash, just a
# project that sounds different. This records what V1.1's 175 records were, so a later build can
# be required to keep them as an exact prefix.
# --------------------------------------------------------------------------------------------

def _declared_records(RPR, track, fx, n_declared):
    """(index, name, lo, hi, step, default) read from an UNTOUCHED instance - a default cannot be
    recovered from one that has already been written to."""
    out = []
    for i in range(n_declared):
        r = RPR.TrackFX_GetParam(track.id, fx.index, i, 0, 0)
        st = RPR.TrackFX_GetParameterStepSizes(track.id, fx.index, i, 0, 0, 0, 0)
        name = RPR.TrackFX_GetParamName(track.id, fx.index, i, "", 128)[4]
        out.append([i, name, r[4], r[5], st[4], r[0]])
    return out


def freeze_declared(path=DECLARED_FIXTURE, track_index=0, n_declared=175,
                    effect="JS: RCBitNova V1.1"):
    """Write the fixture from the live plugin. Run ONCE, from the FROZEN V1.1, before V1.2 exists."""
    import reapy
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        pr = reapy.Project()
        made_track = 0
        if len(pr.tracks) == 0:
            RPR.InsertTrackAtIndex(0, False)
            RPR.TrackList_AdjustWindows(False)
            made_track = 1
            pr = reapy.Project()
        tr = pr.tracks[track_index]
        assert not [f for f in tr.fxs if "RCBitNova" in f.name], \
            f"track {track_index} already holds an RCBitNova; use an empty scratch track"
        fx = tr.add_fx(effect)
        assert fx.n_params == n_declared + 3, \
            f"{effect} reports {fx.n_params} parameters, expected {n_declared} declared + 3 host"
        recs = _declared_records(RPR, tr, fx, n_declared)
        fx.delete()
        if made_track:
            RPR.DeleteTrack(reapy.Project().tracks[0].id)   # leave the project as it was found
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(recs, f, indent=1)
    return recs


def load_declared(path=DECLARED_FIXTURE):
    return [tuple(r) for r in json.load(open(path))]


def check_sites(text, path):
    for name, (pattern, want) in SITES.items():
        m = re.search(pattern, text, re.M)
        assert m, f"{path}: site {name!r} not found - renamed, moved or deleted"
        got = m.group(1)
        assert got == want, f"{path}: site {name!r} carries {got!r}, expected {want!r}"


def check_tables(text, path):
    want = layout.base_tables(8)
    got = {name: {} for name in want}
    for name, idx, value in TABLE_ENTRY.findall(text):
        got[name][int(idx)] = int(value)
    for name, values in want.items():
        for b, expect in enumerate(values):
            assert b in got[name], f"{path}: {name}[{b}] is never assigned"
            assert got[name][b] == expect, \
                f"{path}: {name}[{b}] = {got[name][b]}, expected {expect}"
        extra = set(got[name]) - set(range(len(values)))
        assert not extra, f"{path}: {name} has entries beyond the band count: {sorted(extra)}"


def check_forbidden(text, path):
    for pattern, why in FORBIDDEN:
        for n, line in enumerate(text.splitlines(), 1):
            if "TABLE-DECL" in line or "TABLE-FILL" in line:
                continue
            code = line.split("//")[0]
            if re.search(pattern, code):
                raise AssertionError(f"{path}:{n}: {why} outside the tables: {code.strip()}")


def _function_body(text, name):
    m = re.search(rf"^function {re.escape(name)}\(", text, re.M)
    if not m:
        return None
    depth, start = 0, None
    for i in range(m.end() - 1, len(text)):
        if text[i] == "(":
            depth += 1
            if start is None:
                start = i
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                # the parameter list closed; the body opens at the next '('
                body_open = text.find("(", i)
                depth2 = 0
                for j in range(body_open, len(text)):
                    if text[j] == "(":
                        depth2 += 1
                    elif text[j] == ")":
                        depth2 -= 1
                        if depth2 == 0:
                            return text[body_open:j + 1]
                return None
    return None


def check_writers(text, path):
    bases = layout.base_tables(8)["stb"]
    for fn, off in WRITERS.items():
        body = _function_body(text, fn)
        assert body, f"{path}: writer {fn} not found"
        want = [str(base + off) for base in bases]
        got = re.findall(r"slider(\d+) = v;", body)
        assert got == want, f"{path}: {fn} writes sliders {got}, expected {want}"
        assert len(re.findall(r"slider_automate\(", body)) == 8, \
            f"{path}: {fn} must call slider_automate in all eight branches"
        assert "setup_band(b)" in body, f"{path}: {fn} does not rebuild static coefficients"
        assert "setup_band_dyn(b)" in body, f"{path}: {fn} does not rebuild dynamics"


def check_addresses(text, path):
    low = layout.low_layout(8)
    v11 = eval_init(text, AUDIO + GUI + ["lp_base", "stb", "dynb", "ceb"] + list(low))
    v10 = eval_init(open(V10, encoding="utf-8", errors="replace").read(),
                    AUDIO + ["lp_base", "gc_kc", "gc_fc"])
    model_audio = layout.audio_layout(8)
    model_gui = layout.gui_layout(model_audio["gc_trace"], 8)

    for name, (first, _) in low.items():
        assert v11[name] == first, f"{path}: {name} = {v11[name]}, model says {first}"
    for name in AUDIO:
        assert v11[name] == model_audio[name], \
            f"{path}: {name} = {v11[name]}, model says {model_audio[name]}"
    for name in GUI:
        assert v11[name] == model_gui[name], \
            f"{path}: {name} = {v11[name]}, model says {model_gui[name]}"
    assert (v11["stb"], v11["dynb"], v11["ceb"]) == (272, 280, 288), \
        f"{path}: base tables at {(v11['stb'], v11['dynb'], v11['ceb'])}"
    # gc_kc's base DOES move here, and must: the whole chain rides on mb_peak/mb_end, which grow
    # with the band count. (The superseded split design kept the chain fixed, and an assertion
    # carried over from it - "gc_kc must not move" - failed the clean source. The model comparison
    # above is the real check.) What §2.1 is actually about is the SIZE:
    assert v11["gc_fc"] - v11["gc_kc"] == 8 * 8, \
        f"{path}: gc_kc spans {v11['gc_fc'] - v11['gc_kc']} words, expected 64 (8 bands x 8)"
    assert v10["gc_fc"] - v10["gc_kc"] == 32, "V1.0's gc_kc is 32 words - the premise of §2.1"
    assert v11["lp_base"] == 131072, \
        f"{path}: lp_base = {v11['lp_base']}, expected 131072 - one page up from V1.0"
    assert v11["gc_hits"] + 8 <= v11["lp_base"], \
        f"{path}: the GUI region must end below lp_base"


def check_source(path=V12, project=False):
    text = open(path, encoding="utf-8", errors="replace").read()
    if project:
        text, n = re.subn(r"^N_BANDS = 4;", "N_BANDS = 8;", text, count=1, flags=re.M)
        assert n == 1, f"{path}: no `N_BANDS = 4;` to project from"
    check_sites(text, path)
    check_tables(text, path)
    check_forbidden(text, path)
    check_writers(text, path)
    check_addresses(text, path)


# --------------------------------------------------------------------------------------------
# --live: the parameter manifest. Needs REAPER.
#
# Records, not names. An earlier draft returned `p.formatted` - the CURRENT value's display
# string, which is neither the step nor the default - so two incompatible declarations whose
# current values happened to format alike would have compared equal.
# --------------------------------------------------------------------------------------------

N_DECLARED_V10 = 95
HOST_TAIL = ["Bypass", "Wet", "Delta"]


def _records(RPR, track, fx_index, n_params, defaults=None):
    out = []
    for i in range(n_params):
        r = RPR.TrackFX_GetParam(track.id, fx_index, i, 0, 0)
        value, lo, hi = r[0], r[4], r[5]
        st = RPR.TrackFX_GetParameterStepSizes(track.id, fx_index, i, 0, 0, 0, 0)
        step, is_toggle = st[4], st[7]
        name = RPR.TrackFX_GetParamName(track.id, fx_index, i, "", 128)[4]
        default = value if defaults is None else defaults[i]
        trips = []
        for probe in (0.0, 0.5, 1.0):
            RPR.TrackFX_SetParamNormalized(track.id, fx_index, i, probe)
            trips.append(round(RPR.TrackFX_GetParamNormalized(track.id, fx_index, i), 9))
        RPR.TrackFX_SetParamNormalized(
            track.id, fx_index, i, (value - lo) / (hi - lo) if hi != lo else 0)
        back = RPR.TrackFX_GetParam(track.id, fx_index, i, 0, 0)[0]
        assert abs(back - value) <= 1e-6, f"parameter {i} ({name}) did not restore: {value} -> {back}"
        out.append((i, name, lo, hi, step, is_toggle, default, tuple(trips)))
    return out


def _fine_ceiling_indices():
    """Declared-parameter indices of the sixteen ceiling Macro sliders, derived from the source's
    own declaration order rather than counted by hand."""
    text = open(V12, encoding="utf-8", errors="replace").read()
    order = [int(n) for n in re.findall(r"^slider(\d+):", text, re.M)]
    t = layout.base_tables(8)
    targets = {t["dynb"][b] + 3 for b in range(8)} | {t["ceb"][b] + 2 for b in range(8)}
    out = {order.index(n) for n in targets}
    assert len(out) == 16, f"expected sixteen ceiling Macro sliders, found {len(out)}"
    return out


def check_live(track_index=0):
    """Compare V1.0's and V1.1's declared parameters as full records, and the host tail by
    POSITION - declared parameter 0 is also called "Bypass", so a name search finds the wrong one.
    """
    import reapy
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        pr = reapy.Project()
        made_track = 0
        if len(pr.tracks) == 0:
            RPR.InsertTrackAtIndex(0, False)
            RPR.TrackList_AdjustWindows(False)
            made_track = 1
            pr = reapy.Project()
        tr = pr.tracks[track_index]
        assert not [f for f in tr.fxs if "RCBitNova" in f.name], \
            f"track {track_index} already holds an RCBitNova; use an empty scratch track"

        def manifest(name, n_declared):
            fx = tr.add_fx(name)
            i = fx.index
            n = fx.n_params
            # defaults FIRST, from an untouched instance - a default cannot be recovered from one
            # that has already been written to.
            defaults = [RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)[0] for k in range(n)]
            recs = _records(RPR, tr, i, n, defaults)
            fx.delete()
            return n, recs[:n_declared], recs[n_declared:]

        n10, dec10, host10 = manifest("JS: RCBitNova V1.0", N_DECLARED_V10)
        n11, dec11, host11 = manifest("JS: RCBitNova V1.2", N_DECLARED_V12)
        if made_track:
            RPR.DeleteTrack(reapy.Project().tracks[0].id)

    assert n10 == N_DECLARED_V10 + 3, f"V1.0 reports {n10} parameters, expected 98"
    assert n11 == N_DECLARED_V12 + 3, \
        f"V1.2 reports {n11} parameters, expected {N_DECLARED_V12} declared + 3 host"
    assert [r[1] for r in host10] == HOST_TAIL, f"V1.0 host tail is {[r[1] for r in host10]}"
    assert [r[1] for r in host11] == HOST_TAIL, f"V1.1 host tail is {[r[1] for r in host11]}"
    # The ONE documented deviation from "the 95 declared records are identical": the ceiling Macro
    # sliders were re-declared with a 0.05 step so a value like 0.25 bits can be typed at all
    # (owner, 2026-08-24). Value-safe - a stored parameter is normalised over an unchanged 0..16
    # range, so existing projects reopen with the same ceilings - but it IS a record difference,
    # so the gate demands it happen on exactly these sixteen parameters and nowhere else.
    fine_ceilings = _fine_ceiling_indices()
    for a, b in zip(dec10, dec11):
        if a[0] in fine_ceilings:
            assert a[:4] == b[:4] and a[5:] == b[5:], \
                f"ceiling parameter {a[0]} differs beyond its step:\n  V1.0 {a}\n  V1.1 {b}"
            assert a[4] == 1.0 and b[4] == 0.05, \
                f"ceiling parameter {a[0]} step went {a[4]} -> {b[4]}, expected 1 -> 0.05"
        else:
            assert a == b, f"declared parameter {a[0]} differs:\n  V1.0 {a}\n  V1.1 {b}"
    assert len(dec11) == N_DECLARED_V12

    # V1.2's first 175 records must BE V1.1's, to the range, step and default. This is what makes a
    # V1.1 -> V1.2 migration possible: REAPER stores parameters by position, so a record inserted
    # anywhere but the end silently moves every later one.
    frozen = load_declared()
    # the live record is (index, name, lo, hi, step, is_toggle, default, trips); the fixture is
    # (index, name, lo, hi, step, default) - so pick fields, do not slice.
    got = [(r[0], r[1], r[2], r[3], r[4], r[6]) for r in dec11[:len(frozen)]]
    assert len(dec11) >= len(frozen), \
        f"V1.2 has {len(dec11)} declared records, fewer than the frozen {len(frozen)}"
    assert got == frozen, next(
        (f"record {i} differs: frozen {a}, V1.2 {b}"
         for i, (a, b) in enumerate(zip(frozen, got)) if a != b),
        "the frozen prefix and V1.2 disagree")
    for rec in dec11:
        i, name, lo, hi, step, is_toggle, default, trips = rec
        assert hi > lo, f"parameter {i} ({name}) has an empty range"
        assert trips[0] != trips[2], f"parameter {i} ({name}) does not move between its extremes"
    return n10, n11, len(dec11) - len(dec10)


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--source-only"
    assert mode in ("--preflip", "--source-only", "--live", "--freeze"), f"unknown mode {mode}"
    if mode == "--freeze":
        recs = freeze_declared()
        print(f"OK freeze: {len(recs)} declared records from V1.1 -> {DECLARED_FIXTURE}")
        return 0
    if mode == "--live":
        try:
            n10, n11, added = check_live()
        except AssertionError as exc:
            print(f"FAIL --live: {exc}")
            return 1
        print(f"OK --live: V1.0 {n10} params, V1.1 {n11}, {added} added; "
              f"the 95 declared records are identical and the host tail matches by position")
        return 0
    try:
        check_source(V12, project=(mode == "--preflip"))
    except AssertionError as exc:
        print(f"FAIL {mode}: {exc}")
        return 1
    print(f"OK {mode}: {len(SITES)} sites, 24 table entries, "
          f"{len(WRITERS)} writers, {len(AUDIO) + len(GUI) + 10} addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
