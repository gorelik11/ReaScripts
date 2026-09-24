"""RCBitNova's memory map as data rather than as comments.

Every address here is a literal in the JSFX @init block. Keeping a machine-readable copy is what
lets tests assert adjacency and lets the source gate compare word indices instead of eyeballing
text - three reviews of the superseded split design each found an address claim that was wrong when
checked, and one of those was in an earlier version of this very file (it omitted gc_lin, 8192
words).

Words, not bytes: EEL2 memory is word-indexed.
"""

import math

MAX_LOOK = 2048

# ---- V1.6 ----
DQ_CAP = MAX_LOOK + 1                    # 2049, see v16_new_spans
N_QUEUES = 16                            # 8 bands x 2 lanes
FFT_N = 8192
AN_PX = 2048                             # pixel-indexed arrays: the bound an_px_n clamps to
GC_N = 512
GC_LIN_N = 2048
GC_TRACE_WORDS = 2 * 5 * GC_N            # 5120

# The low map, in layout order: name -> words per band. Every one of these is sized by the band
# count; there is no second count, which is the whole point of the uniform design.
LOW = [("cf", 8), ("st", 4), ("det", 4), ("dst", 4), ("cst", 4),
       ("dp", 4), ("dm", 1), ("bp", 3), ("eg", 2)]

# V1.0's shipped bases, kept so the model can prove it describes THIS plugin.
V10_BASES = {"cf": 0, "st": 64, "det": 96, "dst": 128, "cst": 160,
             "dp": 192, "dm": 208, "bp": 216, "eg": 256}

# The three slider-base tables are FIXED here, immediately above the eight-band low map.
TABLES_FIRST, TABLES_LAST = 272, 295      # stb 272..279, dynb 280..287, ceb 288..295

# V1.1's enabled-band list and V1.2's panel field metadata sit directly above the tables. Both
# are FIXED addresses in @init, so a band count that grows the low map into them must be reported
# here rather than discovered as a band reading another band's metadata.
NB_LIST = (296, 303)                      # 8 words, one per band
GC_FMETA = (304, 367)                     # 8 slots x 8 words: 6 panel + the two HP/LP frequencies. NOT gc_meta - that name is
                                          # the curve buffers' 16 NAMED words at gc_snap + 128.
FIXED_ABOVE_TABLES = {"nb_list": NB_LIST, "gc_fmeta": GC_FMETA}

# Slider numbers bands 1-4 already own, plus the globals and the filter section. Immovable:
# REAPER stores parameters by number, so renumbering breaks every existing project.
RESERVED = (set(range(1, 5)) | set(range(11, 50)) | set(range(51, 89))
            | set(range(91, 124)) | set(range(131, 143)))
PER_BAND_BLOCKS = (9, 8, 3)               # static, dynamics, ceilings

MB_BAND = 1024                            # a literal in @init


def low_layout(n_bands):
    """name -> (first word, last word inclusive).

    An array keeps its V1.0 base wherever the previous array still fits underneath it, and is
    pushed up otherwise. At four bands that reproduces V1.0 exactly; at eight, only dm and bp move.
    """
    out, p = {}, 0
    for name, per in LOW:
        base = max(V10_BASES[name], p)
        out[name] = (base, base + n_bands * per - 1)
        p = base + n_bands * per
    return out


def max_bands_by_memory():
    """The largest band count whose low map still ends at or below mb_band's literal 1024."""
    n = 1
    while max(hi for _, hi in low_layout(n + 1).values()) + 1 <= MB_BAND:
        n += 1
    return n


def base_tables(n_bands):
    """The three slider-base tables, exactly as @init must fill them.

    Ceilings use a stride of 4 above band 4: they are only three sliders wide, and at stride 10
    band 8 would need 261, past the 256 limit.
    """
    stb = [10 * (b + 1) if b < 4 else 150 + 10 * (b - 4) for b in range(n_bands)]
    dynb = [50 + 10 * b if b < 4 else 190 + 10 * (b - 4) for b in range(n_bands)]
    ceb = [90 + 10 * b if b < 4 else 230 + 4 * (b - 4) for b in range(n_bands)]
    return {"stb": stb, "dynb": dynb, "ceb": ceb}


def _longest_run(free):
    if not free:
        return 0
    best = run = 1
    for a, b in zip(free, free[1:]):
        run = run + 1 if b == a + 1 else 1
        best = max(best, run)
    return best


def _consume_run(free, width):
    for i in range(len(free) - width + 1):
        block = free[i:i + width]
        if block[-1] - block[0] == width - 1:
            return free[:i] + free[i + width:]
    return None


def check_capacity(n_bands):
    """Empty when this band count fits. Reports every real constraint, not a remembered one.

    The superseded design said eight was the maximum because cf would overrun st. That held only
    while det was pinned at 96; here arrays float. At 34 words per band the low map holds 30, the
    fixed base tables at 272..295 stop a ninth band, and the 256-slider limit stops a tenth.
    """
    problems = []
    spans = low_layout(n_bands)
    end = max(hi for _, hi in spans.values()) + 1
    if end > MB_BAND:
        problems.append(f"low map ends at {end}, past mb_band's literal {MB_BAND}")

    # The base tables are NOT part of low_layout. At eight bands the low map ends at exactly 272;
    # a ninth pushes bp and eg straight through them.
    for name, (first, last) in spans.items():
        if last >= TABLES_FIRST and first <= TABLES_LAST:
            problems.append(f"{name} occupies {first}..{last} and collides with the base tables "
                            f"at {TABLES_FIRST}..{TABLES_LAST}")
        for other, (o_first, o_last) in FIXED_ABOVE_TABLES.items():
            if last >= o_first and first <= o_last:
                problems.append(f"{name} occupies {first}..{last} and collides with {other} "
                                f"at {o_first}..{o_last}")

    taken = set(RESERVED)
    t = base_tables(min(n_bands, 8))
    for b in range(4, min(n_bands, 8)):
        taken |= {t["stb"][b] + o for o in range(1, 10)}
        taken |= {t["dynb"][b] + o for o in range(1, 9)}
        taken |= {t["ceb"][b] + o for o in range(1, 4)}
    free = sorted(n for n in range(1, 257) if n not in taken)
    for _ in range(max(0, n_bands - 8)):
        for width in PER_BAND_BLOCKS:
            nxt = _consume_run(free, width)
            if nxt is None:
                problems.append(
                    f"slider budget: a band needs a contiguous run of {width}; the longest free "
                    f"run is {_longest_run(free)} ({len(free)} numbers left below 256)")
                return problems
            free = nxt
    return problems


# name -> (previous name, words the PREVIOUS array occupies). mb_band is a literal.
AUDIO_CHAIN = [
    ("mb_band", None, None),
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
    out = {"mb_band": MB_BAND}
    for name, prev, size in AUDIO_CHAIN[1:]:
        out[name] = out[prev] + size(n_bands)
    return out


def gui_layout(gc_trace_base, n_bands):
    """The GUI block. gc_kc is the one address that grows with the band count."""
    gc_lin = gc_trace_base + GC_TRACE_WORDS
    gc_snap = gc_lin + 2 * 2 * GC_LIN_N      # 8192 - omitting this was a real defect
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
    is the same set for every band - which is the point of the design."""
    for k in range(8):
        mem.write("cf", b * 8 + k, 1.0)
    for name, per in LOW[1:]:
        for k in range(per):
            mem.read(name, b * per + k)
            mem.write(name, b * per + k, 0.0)


# ---- V1.6: the new block, and where it pushes the engines ----
#
# ORDER IS NOT COSMETIC. an_sc is the FFT scratch, 2 * FFT_N words, and a `fft()` whose buffer
# crosses a 65536-word page corrupts SILENTLY - V0.7 established that at 32768 and it is why
# 32768 is widely believed unusable. Putting an_sc FIRST, on the page boundary the block starts
# on, makes the constraint true by construction instead of by arithmetic that has to be rechecked
# every time something above it changes size.
#
# The queues are last because they are the only entries whose size depends on a constant that a
# future version might move (MAX_LOOK); growing the tail of the block cannot disturb the FFT
# scratch's page.
V16_BLOCK = [
    ("an_sc",       lambda: 2 * FFT_N),   # FFT scratch: complex, so 2 words per bin
    ("an_w",        lambda: FFT_N),       # Hann window
    ("an_in",       lambda: FFT_N),       # ring: the tap before the plugin
    ("an_out",      lambda: FFT_N),       # ring: the tap after out_gain and the topology mute
    ("an_mi",       lambda: FFT_N // 2),  # magnitudes, IN
    ("an_mo",       lambda: FFT_N // 2),  # magnitudes, OUT
    ("an_pkI",      lambda: AN_PX),       # peak hold, IN
    ("an_pkO",      lambda: AN_PX),       # peak hold, OUT
    ("an_db",       lambda: AN_PX),       # per-column scratch
    ("an_ms_state", lambda: AN_PX),       # red-rule hysteresis, one per column
    ("an_meta",     lambda: 16),          # an_pos, an_gen, an_gen_seen, an_fill, frame_valid,
                                          # the first-load marker, and room to grow
    ("dq_v",        lambda: N_QUEUES * DQ_CAP),
    ("dq_p",        lambda: N_QUEUES * DQ_CAP),
    ("dq_meta",     lambda: N_QUEUES * 6),   # head, tail, cnt, valid, lk_pending, lastwp
]


def v16_block_base(n_bands=8):
    """Where the new block starts: the page boundary V1.5's engines used to start on."""
    return gui_layout(audio_layout(n_bands)["gc_trace"], n_bands)["lp_base"]


def v16_new_spans(n_bands=8):
    """name -> (start, end_exclusive), word indices. The source gate compares the JSFX literals
    against this, so this file stays the one place an address is decided."""
    p = v16_block_base(n_bands)
    out = {}
    for name, size in V16_BLOCK:
        w = size()
        out[name] = (p, p + w)
        p += w
    return out


def v16_lp_base(n_bands=8):
    """The engines move to the next page boundary above the new block."""
    end = max(e for _, e in v16_new_spans(n_bands).values())
    return math.ceil(end / 65536) * 65536


def v16_check(n_bands=8):
    """Every invariant the memory map has to keep, as assertions rather than as prose."""
    spans = v16_new_spans(n_bands)
    flat = sorted(spans.values())
    for (a0, a1), (b0, b1) in zip(flat, flat[1:]):
        assert a1 <= b0, f"overlapping spans: {(a0, a1)} and {(b0, b1)}"
    lo, hi = spans["an_sc"]
    assert lo // 65536 == (hi - 1) // 65536, (
        f"an_sc spans {lo}..{hi - 1} and crosses a 65536-word page - fft() would corrupt silently")
    base = v16_block_base(n_bands)
    assert flat[0][0] == base and base % 65536 == 0, "the block must start on a page boundary"
    lp = v16_lp_base(n_bands)
    assert lp % 65536 == 0 and flat[-1][1] <= lp, "the engines must start on a page above the block"
    return {"base": base, "words": flat[-1][1] - base, "lp_base": lp, "spans": spans}


if __name__ == "__main__":
    r = v16_check()
    print(f"V1.6 block: base {r['base']}, {r['words']} words, engines at {r['lp_base']}")
    for name, (a, b) in r["spans"].items():
        print(f"  {name:<12} {a:>7} .. {b:>7}   {b - a:>6} words")
