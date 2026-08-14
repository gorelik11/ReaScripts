"""Curve mathematics for the RCBitNova V1.0 GUI.

Pure functions, no drawing. Everything the @gfx graph needs, proven here before it is
transcribed to EEL2. Reads the oracle (rcbitnova_dsp); never modifies it.

Design: docs/superpowers/specs/2026-08-14-rcbitnova-v1.0-gui-curve-design.md (rev 8)

ONE CURRENCY: BITS.
Every magnitude function returns log2|H|, and composing blocks in series SUMS them. An earlier
draft mixed linear magnitudes (bands) with bit grids (realized kernels) and multiplied one by
the other - an error that produces a smooth, plausible, wrong curve. Bits everywhere makes that
class of mistake unrepresentable, and it is also the unit the Y axis is drawn in, so no
conversion happens between computing and plotting.
"""

import math

try:
    from tools import rcbitnova_dsp as dsp
except ImportError:                      # also importable directly from inside tools/
    import rcbitnova_dsp as dsp

DOMAINS = ("both", "mid", "side", "left", "right")

BRICK_SLOPE = 6                          # slider enum index for FIR Brick
# slider enum -> cascade sections. 5 = 96 dB/oct = 8 sections; 6 = Brick, which is Off in the
# min-phase path (V0.9 line 709: hp_nsec = slider131 == 6 ? 0 : ...).
_SLOPE_SECTIONS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 8, 6: 0}

MAG_FLOOR = 1e-7                         # -140 dB, far below the +-4-bit viewport
BITS_FLOOR = math.log2(MAG_FLOOR)


def mag_to_bits(m):
    """Linear magnitude -> bits, with a floor.

    FIR Brick's target contains EXACT zeros and serial cuts underflow; log2(0) would produce
    non-finite pixel coordinates and corrupt a whole line strip before any clamp.
    """
    return math.log2(max(m, MAG_FLOOR))


# --------------------------------------------------------------------------- blocks

def band_gain_bits(band):
    """Effective gain in bits, including Bit Ratio - the same expression the audio path uses."""
    return (band["macro"] + band["micro"] * 0.01) * band["ratio"]


def band_bits(band, f, sr):
    """log2|H| of one band at frequency f. A disabled band contributes exactly 0 bits."""
    if not band["enable"]:
        return 0.0
    gain_lin = dsp.bit_gain(band["macro"], band["micro"], band["ratio"])
    qe = dsp.q_eff(band["type"], band["q"], band["qchar"], band_gain_bits(band))
    c = dsp.svf_make(band["type"], dsp.fc_eff(band["freq"], sr), qe, gain_lin, sr)
    return mag_to_bits(abs(dsp.svf_response(c, f, sr)))


def hplp_bits(hp, f, sr, act_phase, realized=None):
    """log2|H| of one HP/LP block.

    Min phase: the digital cascade - and Brick is IDENTITY there, because it maps to nsec = 0,
    so the audible response really is no filter.

    Linear phase: sampled from `realized`, a dict of grids keyed by engine identity
    ({"hp": grid, "lp": grid}). HP and LP are two independently configured engines, so one
    shared sampler would force both to use the same response. There is no analytic shortcut:
    windowing changes the response, which is the whole reason Resolution exists.
    """
    nsec = _SLOPE_SECTIONS[hp["slope"]]
    is_brick = hp["slope"] == BRICK_SLOPE
    if act_phase == 0:
        if is_brick or nsec == 0:
            return 0.0
        return mag_to_bits(dsp.hplp_digital_mag(hp["ftype"], hp["freq"], hp["res"], nsec, f, sr))
    if nsec == 0 and not is_brick:
        return 0.0                       # Off is Off in Linear too
    if realized is None or hp["ftype"] not in realized:
        raise ValueError(f"Linear phase needs a realized grid for {hp['ftype']!r}")
    return sample_grid_bits(realized[hp["ftype"]], f)


def is_audible(block, act_phase):
    """Does this block actually do anything right now?

    A filter dict has no 'enable' key, so a naive .get('enable', 1) treats an Off slope as
    active - lighting up its placement domain and falsely marking the traces as a mixed
    placement family.
    """
    if "slope" in block:                                   # HP/LP
        if block["slope"] == BRICK_SLOPE:
            return act_phase == 1                          # Min + Brick is identity
        return _SLOPE_SECTIONS[block["slope"]] > 0
    return bool(block["enable"])


# --------------------------------------------------------------------------- composition

def _applies(placement, domain):
    return placement == "both" or placement == domain


def domain_bits(bands, filters, domain, f, sr, act_phase, realized=None):
    """SUM of the bit contributions of every block acting on `domain`.

    Summing within one domain is exactly correct. Summing ACROSS domains is not - a selective
    block is a stereo 2x2 matrix, not a scalar - which is why there is one trace per domain
    rather than one combined curve.
    """
    total = 0.0
    for hp in filters:
        if _applies(hp["placement"], domain) and is_audible(hp, act_phase):
            total += hplp_bits(hp, f, sr, act_phase, realized)
    for b in bands:
        if _applies(b["placement"], domain) and is_audible(b, act_phase):
            total += band_bits(b, f, sr)
    return total


def active_domains(bands, filters, act_phase):
    """Domains with at least one AUDIBLE block, so only those traces are drawn."""
    out = set()
    for blk in list(bands) + list(filters):
        if is_audible(blk, act_phase):
            out.add(blk["placement"])
    return tuple(d for d in DOMAINS if d in out)


def mixed_placement_families(bands, filters, act_phase):
    """True when M/S-placed and L/R-placed AUDIBLE blocks coexist.

    No set of per-domain scalar traces describes the true channel response then - the stages do
    not factor - so the affected traces must be drawn dashed rather than implying a measurement.
    """
    doms = active_domains(bands, filters, act_phase)
    return (any(d in doms for d in ("mid", "side"))
            and any(d in doms for d in ("left", "right")))


# --------------------------------------------------------------------------- realized kernels

def sample_grid_bits(grid, f):
    """Interpolate a (freq, bits) grid linearly in LOG frequency.

    Both halves matter: log frequency keeps a steep skirt straight on the drawn axes, and
    interpolating BITS rather than magnitudes is what the axis expects. Interpolating magnitude
    would put the midpoint of 1.0 and 0.5 at 0.75 instead of sqrt(0.5) - wrong precisely on the
    steep skirts this path exists to render honestly.
    """
    if f <= grid[0][0]:
        return grid[0][1]
    if f >= grid[-1][0]:
        return grid[-1][1]
    lo, hi = 0, len(grid) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if grid[mid][0] <= f:
            lo = mid
        else:
            hi = mid
    f0, b0 = grid[lo]
    f1, b1 = grid[hi]
    t = math.log(f / f0) / math.log(f1 / f0)
    return b0 + (b1 - b0) * t
