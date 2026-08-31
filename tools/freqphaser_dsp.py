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


@dataclass(frozen=True)
class EngineLayout:
    """Page-safe memory model for the shared-input convolution engine."""

    latency: int
    top: int
    fft_spans: tuple[tuple[int, int], ...]


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


def build_transfer_spectra(
    size: int,
    sample_rate: float,
    cuts: tuple[float, float, float, float],
    slope_db_oct: float,
    settings: list[BandSetting],
) -> tuple[list[complex], list[complex]]:
    """Build conjugate-symmetric injection and removal responses."""

    if size < 2 or size & (size - 1):
        raise ValueError("FFT size must be a power of two")
    injection = [0j] * size
    removal = [0j] * size
    half = size // 2
    for k in range(half + 1):
        freq = sample_rate * k / size
        inject, remove = transfer_at(freq, cuts, slope_db_oct, settings)
        if k in (0, half):
            inject = complex(inject.real, 0.0)
        injection[k] = inject
        removal[k] = complex(remove, 0.0)
        if 0 < k < half:
            injection[size - k] = inject.conjugate()
            removal[size - k] = complex(remove, 0.0)
    return injection, removal


def _align(value: int, unit: int) -> int:
    return ((value + unit - 1) // unit) * unit


def engine_layout(
    design_size: int,
    partition_size: int,
    *,
    outputs: int,
    targets: bool,
) -> EngineLayout:
    """Return the page-safe layout contract used by the JSFX engine."""

    page = 65536
    runtime_size = 2 * partition_size
    complex_partition = 2 * runtime_size
    partitions = design_size // partition_size
    ptr = 0
    spans: list[tuple[int, int]] = []

    def add_fft_block(span: int, unit: int | None = None) -> None:
        nonlocal ptr
        alignment = min(unit or span, page)
        ptr = _align(ptr, alignment)
        if unit is None:
            spans.append((ptr, span))
        else:
            for offset in range(0, span, unit):
                spans.append((ptr + offset, unit))
        ptr += span

    add_fft_block(design_size * 2)
    ptr += design_size * 2  # real kernel and Kaiser window
    banks = outputs * (2 if targets else 1)
    for _ in range(banks):
        add_fft_block(partitions * complex_partition, complex_partition)
    add_fft_block(partitions * complex_partition, complex_partition)  # shared FDL
    add_fft_block(complex_partition)  # runtime FFT input
    for _ in range(outputs):
        add_fft_block(complex_partition)  # accumulator
    add_fft_block(complex_partition)  # convolve scratch
    ptr += runtime_size
    ptr += outputs * 16384
    ptr += 2 * (32768 if design_size >= 32768 else 16384)
    return EngineLayout(
        latency=design_size // 2 + partition_size,
        top=ptr,
        fft_spans=tuple(spans),
    )


def fft(values: list[complex], *, inverse: bool = False) -> list[complex]:
    """Iterative radix-2 FFT used by the stdlib-only oracle."""

    size = len(values)
    if size < 1 or size & (size - 1):
        raise ValueError("FFT length must be a power of two")
    result = list(values)
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            result[i], result[j] = result[j], result[i]
    length = 2
    while length <= size:
        angle = (2j if inverse else -2j) * math.pi / length
        step = cmath.exp(angle)
        for base in range(0, size, length):
            weight = 1 + 0j
            half = length // 2
            for k in range(half):
                even = result[base + k]
                odd = result[base + k + half] * weight
                result[base + k] = even + odd
                result[base + k + half] = even - odd
                weight *= step
        length *= 2
    if inverse:
        result = [value / size for value in result]
    return result


def ifft(values: list[complex]) -> list[complex]:
    return fft(values, inverse=True)


def partitioned_convolve(
    signal: list[float], kernel: list[float], partition_size: int
) -> list[float]:
    """Uniform partitioned overlap-save convolution with one-hop latency."""

    runtime_size = 2 * partition_size
    partitions = len(kernel) // partition_size
    if len(kernel) % partition_size:
        raise ValueError("Kernel length must be a multiple of partition size")
    spectra = [
        fft(
            [
                complex(kernel[part * partition_size + i], 0.0)
                if i < partition_size
                else 0j
                for i in range(runtime_size)
            ]
        )
        for part in range(partitions)
    ]
    fdl = [[0j] * runtime_size for _ in range(partitions)]
    fdl_write = 0
    history = [0.0] * runtime_size
    history_pos = 0
    count = 0
    pending: list[float] = []
    output: list[float] = []
    for sample in signal:
        history[history_pos] = sample
        history_pos = (history_pos + 1) % runtime_size
        count += 1
        output.append(pending.pop(0) if pending else 0.0)
        if count == partition_size:
            count = 0
            block = [
                complex(history[(history_pos + i) % runtime_size], 0.0)
                for i in range(runtime_size)
            ]
            fdl[fdl_write] = fft(block)
            accumulation = [0j] * runtime_size
            for part in range(partitions):
                delayed = fdl[(fdl_write - part) % partitions]
                response = spectra[part]
                for i in range(runtime_size):
                    accumulation[i] += delayed[i] * response[i]
            frame = ifft(accumulation)
            pending.extend(frame[i].real for i in range(partition_size, runtime_size))
            fdl_write = (fdl_write + 1) % partitions
    return output
