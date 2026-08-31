# Freqphaser 1.0 Live Acceptance Checklist

## Artifact

- Source: `JSFX/Freqphaser 1.0`
- Non-overwriting REAPER copy: `Freqphaser 1.0 Codex Test 1`
- Geometry: BD 32768, P 2048, B 4096, 16 partitions
- Reported latency: 18432 samples

## Offline contract completed

- [x] Amount endpoints: 0 bit = 0, 1 bit = 1 coefficient
- [x] Five masks are non-negative and sum to one after crossover sanitization
- [x] Conjugate-symmetric injection spectrum and real removal spectrum
- [x] IFFT, BD/2 shift, Kaiser beta 14, and realized-spectrum oracle
- [x] Full 32768/2048 impulse peak at sample 18432
- [x] All-Move unity response survives realization within 1e-8
- [x] 32768-point FFT buffers and every partition are page-safe
- [x] Lowest-numbered Listen wins conflicting automation
- [x] Listen takes priority over Mono Check
- [x] 50 ms transition endpoints at 44.1/48/88.2/96 kHz
- [x] Kernel-boundary ordering and NaN/Inf guards
- [x] Explicit named GUI slider writers and declared-step quantization

## REAPER live checks

- [ ] Close the REAPER evaluation modal and load `Freqphaser 1.0 Codex Test 1`
- [ ] Confirm no EEL2 compile error and the 900x620 GUI opens
- [ ] Confirm REAPER reports PDC 18432
- [ ] Null test all Amounts at zero against a 18432-sample delayed dry path
- [ ] Test each band at 0.00/0.50/1.00 bit in Add and Move
- [ ] Test Phase at 0, +90, -90, +180, and -180 degrees
- [ ] Sweep every crossover with 12/24/48/96 dB/oct while playing; no clicks
- [ ] Cross two host-automated crossover values; builder must retain ordered masks
- [ ] Verify exclusive Listen and Listen-over-Mono priority
- [ ] Save/reload a preset and reopen the project
- [ ] Verify 44.1/48/96/192 kHz, offline render tail, and CPU during a kernel fade
- [ ] Compare an instrumented JSFX kernel dump bin-for-bin with the Python realized oracle
- [ ] Audition the harmonica excerpt in stereo and final dual-mono output

## Current live-test blocker

REAPER v7.78 launched, but its evaluation modal blocked both the local Python bridge and atomic
REAPER commands. No claim of live compilation is made until that dialog is dismissed. The test
copy was installed without replacing any existing effect, and its SHA-256 matched the source at
installation time.
