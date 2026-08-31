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


@dataclass
class KernelTransition:
    """Small oracle for the JSFX active/target/latest-pending state machine."""

    current: object
    length: int
    target: object | None = None
    pending: object | None = None
    position: int = 0
    fading: bool = False

    def request(self, target: object) -> None:
        if self.fading:
            if target != self.target:
                self.pending = target
            return
        if target != self.current:
            self.target = target
            self.position = 0
            self.fading = True

    def advance(self, samples: int) -> None:
        if not self.fading:
            return
        self.position += samples
        if self.position < self.length:
            return
        self.current = self.target
        self.target = None
        self.position = 0
        self.fading = False
        if self.pending is not None:
            queued = self.pending
            self.pending = None
            self.request(queued)


def amount_from_bits(bits: float) -> float:
    """Map the zero-origin bit control to a linear transfer coefficient."""

    return 2.0**bits - 1.0


def crossfade_length(sample_rate: float) -> int:
    """Return the fixed 50 ms kernel/route transition length."""

    return max(1, math.floor(sample_rate * 0.05))


def crossfade_alpha(position: int, length: int) -> float:
    """Return the clamped linear transition coefficient."""

    return min(max(position / max(length, 1), 0.0), 1.0)


def selected_listen_band(values: tuple[bool, bool, bool, bool, bool]) -> int:
    """Resolve conflicting automation deterministically to the lowest band."""

    return next((index for index, enabled in enumerate(values) if enabled), -1)


def monitor_route(*, listen_band: int, mono_check: bool) -> str:
    """Resolve Listen over Mono Check over the normal stereo route."""

    if listen_band >= 0:
        return "listen"
    if mono_check:
        return "mono"
    return "stereo"


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


def minimum_crossover_step(
    sample_rate: float, slope_db_oct: float, size: int
) -> float:
    """Require more resolvable bins as the requested crossover gets steeper."""

    transition_bins = max(2, math.ceil(slope_db_oct / 12.0) * 2)
    return max(1.0, transition_bins * sample_rate / size)


def sanitize_cuts(
    cuts: tuple[float, float, float, float],
    *,
    sample_rate: float,
    slope_db_oct: float,
    size: int,
    previous: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    """Clamp malformed/automated crossover values before kernel construction."""

    defaults = (200.0, 1500.0, 7000.0, 10000.0)
    values = [
        float(value) if math.isfinite(value) else defaults[index]
        for index, value in enumerate(cuts)
    ]
    upper = min(20000.0, sample_rate * 0.49)
    step = minimum_crossover_step(sample_rate, slope_db_oct, size)
    lower = max(20.0, step)
    if previous is not None:
        changed = [
            index for index, (value, old) in enumerate(zip(values, previous))
            if value != old
        ]
        if len(changed) == 1:
            index = changed[0]
            low = lower if index == 0 else previous[index - 1] + step
            high = upper if index == 3 else previous[index + 1] - step
            values[index] = min(max(values[index], low), max(high, low))
            return tuple(values)  # type: ignore[return-value]
    values[0] = min(max(values[0], lower), upper - 3.0 * step)
    values[1] = min(max(values[1], values[0] + step), upper - 2.0 * step)
    values[2] = min(max(values[2], values[1] + step), upper - step)
    values[3] = min(max(values[3], values[2] + step), upper)
    return tuple(values)  # type: ignore[return-value]


def kernel_rebuild_needed(
    *,
    bits: tuple[float, float, float, float, float],
    listen_band: int,
    active_injection: bool,
    active_removal: bool,
    target_injection: bool,
    target_removal: bool,
) -> bool:
    """Match the JSFX rule that suppresses zero-to-zero kernel rebuilds."""

    requested = listen_band >= 0 or any(value > 0.0 for value in bits)
    return requested or any(
        (active_injection, active_removal, target_injection, target_removal)
    )


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

    add_fft_block(design_size * 2)  # injection design spectrum
    add_fft_block(design_size * 2)  # removal design spectrum
    ptr += design_size * 2  # real kernel and Kaiser window
    banks = outputs * (2 if targets else 1)
    for _ in range(banks):
        add_fft_block(partitions * complex_partition, complex_partition)
    add_fft_block(partitions * complex_partition, complex_partition)  # shared FDL
    add_fft_block(complex_partition)  # runtime FFT input
    add_fft_block(complex_partition)  # one accumulator, reused by both outputs
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


def kaiser_i0(value: float) -> float:
    """Modified Bessel I0 matching the 40-term EEL2 implementation."""

    total = 1.0
    term = 1.0
    half = value * 0.5
    for index in range(1, 40):
        term *= (half / index) ** 2
        total += term
    return total


def kaiser_window(size: int, beta: float) -> list[float]:
    """Return the exact symmetric window used by the JSFX kernel builder."""

    normalization = 1.0 / kaiser_i0(beta)
    denominator = size - 1
    return [
        kaiser_i0(
            beta
            * math.sqrt(max(1.0 - (2.0 * index / denominator - 1.0) ** 2, 0.0))
        )
        * normalization
        for index in range(size)
    ]


def realize_spectrum(
    spectrum: list[complex], *, beta: float
) -> tuple[list[float], list[complex]]:
    """IFFT, centre, window, and re-FFT exactly as the JSFX builder does."""

    size = len(spectrum)
    impulse = ifft(spectrum)
    window = kaiser_window(size, beta)
    half = size // 2
    kernel = [
        impulse[(index + half) % size].real * window[index]
        for index in range(size)
    ]
    return kernel, fft([complex(value, 0.0) for value in kernel])


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
