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
import math
import re
import sys

try:
    from tools import rcbitnova_layout as layout
except ImportError:                      # also runnable from inside tools/
    import rcbitnova_layout as layout

V10 = "JSFX/RCBitNova V1.0"
V11 = "JSFX/RCBitNova V1.1"

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
    "sample-band-loop":      (r"loop\((\w+),\s*\n\s*slider\(stb\[b\] \+ 1\) == 1 \? \(", "N_BANDS"),
    "sample-modeb-pass":     (r"corrL = 0; corrR = 0;\s*\n\s*b = 0;\s*\n\s*loop\((\w+),",
                              "N_BANDS"),
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


def check_source(path=V11, project=False):
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
N_DECLARED_V11 = 175
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
    text = open(V11, encoding="utf-8", errors="replace").read()
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
        n11, dec11, host11 = manifest("JS: RCBitNova V1.1", N_DECLARED_V11)

    assert n10 == N_DECLARED_V10 + 3, f"V1.0 reports {n10} parameters, expected 98"
    assert n11 == N_DECLARED_V11 + 3, f"V1.1 reports {n11} parameters, expected 178"
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
    assert len(dec11) == N_DECLARED_V11
    for rec in dec11:
        i, name, lo, hi, step, is_toggle, default, trips = rec
        assert hi > lo, f"parameter {i} ({name}) has an empty range"
        assert trips[0] != trips[2], f"parameter {i} ({name}) does not move between its extremes"
    return n10, n11, len(dec11) - len(dec10)


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--source-only"
    assert mode in ("--preflip", "--source-only", "--live"), f"unknown mode {mode}"
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
        check_source(V11, project=(mode == "--preflip"))
    except AssertionError as exc:
        print(f"FAIL {mode}: {exc}")
        return 1
    print(f"OK {mode}: {len(SITES)} sites, 24 table entries, "
          f"{len(WRITERS)} writers, {len(AUDIO) + len(GUI) + 10} addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
