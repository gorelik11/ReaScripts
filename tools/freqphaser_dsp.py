"""Pure-Python DSP oracle for Freqphaser 1.0."""

from __future__ import annotations

from dataclasses import dataclass
import cmath
import math


ONE_BIT_DB = 6.020599913279624


@dataclass(frozen=True)
class BandSetting:
    """One band's Side-to-Mid transfer settings."""

    bits: float
    phase_deg: float
    move: bool


def amount_from_bits(bits: float) -> float:
    """Map the zero-origin bit control to a linear transfer coefficient."""

    return 2.0**bits - 1.0


def phase_factor(degrees: float) -> complex:
    """Return the unit complex factor for a phase rotation in degrees."""

    return cmath.exp(1j * math.radians(degrees))


def high_fraction(freq: float, cutoff: float, slope_db_oct: float) -> float:
    """Return a stable complementary high-side crossover fraction."""

    if freq <= 0.0:
        return 0.0
    z = slope_db_oct / ONE_BIT_DB * math.log2(freq / cutoff)
    if z >= 60.0:
        return 1.0
    if z <= -60.0:
        return 0.0
    return 1.0 / (1.0 + 2.0**-z)


def band_weights(
    freq: float,
    cuts: tuple[float, float, float, float],
    slope_db_oct: float,
) -> tuple[float, float, float, float, float]:
    """Return five non-negative masks whose sum is one."""

    c1, c2, c3, c4 = (
        high_fraction(freq, cutoff, slope_db_oct) for cutoff in cuts
    )
    return 1.0 - c1, c1 - c2, c2 - c3, c3 - c4, c4


def transfer_at(
    freq: float,
    cuts: tuple[float, float, float, float],
    slope_db_oct: float,
    settings: list[BandSetting],
) -> tuple[complex, float]:
    """Return combined Mid-injection and Side-removal responses."""

    injection = 0j
    removal = 0.0
    for weight, setting in zip(
        band_weights(freq, cuts, slope_db_oct), settings, strict=True
    ):
        amount = amount_from_bits(setting.bits)
        injection += weight * amount * phase_factor(setting.phase_deg)
        if setting.move:
            removal += weight * amount
    return injection, removal
