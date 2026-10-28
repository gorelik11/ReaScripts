#!/usr/bin/env python3
"""Measure what each dither adds to one master: its side effects, not a ranking.

For every dither and bit depth the error e = output - input (float64, in LSB
of the target depth) is analysed:

  band_level     error level per 1/3 octave, dB relative to plain TPDF
  band_corr      L/R correlation of the error per band (+1 mono, 0 wide, -1 anti)
  band_width     change of the output's side/mid ratio vs the input, dB
  band_lock      coherence between signal and error per band (0 = pure noise,
                 1 = error fully determined by the music)
  modulation     spread (p95 - p5, dB) of short-time error level where music plays
  rms_dbfs       error level above 20 Hz (rms_total_dbfs includes infrasonic drift:
                 StudioTan's noise shaper wanders below 20 Hz)
  flatness       spectral flatness of the error, 0..1 (1 = white)

Writes <outdir>/bench.json, the dithered files, and "noise" files: the error
alone, raised by an exact power of two (+48.2 dB for 16 bit, +96.3 dB for
24 bit) so it can be heard.

    dither_bench.py master.wav -o "bench folder"
"""
import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy import signal

import aw_dither

DITHERS = ["dark", "njad", "tpdfwide", "studiotan", "spatialize", "vinyl", "tape"]  # darkstereo on request
REFERENCES = ["tpdf", "round"]  # plain TPDF +-1 LSB, and rounding with no dither
NOISE_GAIN = {16: 2 ** 8, 24: 2 ** 16}
NPERSEG = 16384


def third_octave_bands(lo=20.0, hi=20000.0):
    centres = 1000.0 * 2.0 ** (np.arange(-17, 14) / 3.0)
    centres = centres[(centres >= lo) & (centres <= hi)]
    return centres, centres * 2 ** (-1 / 6), centres * 2 ** (1 / 6)


def reference_output(x, bits, kind, seed=1):
    scale = 2.0 ** (bits - 1)
    if kind == "round":
        return np.floor(x * scale + 0.5) / scale
    rng = np.random.default_rng(seed)
    d = rng.random(x.shape) - rng.random(x.shape)  # TPDF, +-1 LSB
    return np.floor(x * scale + d + 0.5) / scale


def plugin_output(x, sr, dither, bits, seed=1, stereo=0.55):
    plugin, x86 = aw_dither.DITHERS[dither]
    cmd = aw_dither.awproc_command(plugin, x86, sr, aw_dither.plugin_params(dither, bits, stereo=stereo), seed, 0)
    blocks = (x[s:s + aw_dither.BLOCK_FRAMES] for s in range(0, len(x), aw_dither.BLOCK_FRAMES))
    return np.concatenate(list(aw_dither.process_blocks(blocks, cmd)))


def latency(x, y, max_lag=8):
    """Samples the dither delays its output by (StudioTan looks one sample ahead)."""
    n = min(len(x), 480000)
    errs = [np.mean((y[k:n] - x[:n - k]) ** 2) for k in range(max_lag + 1)]
    return int(np.argmin(errs))


def band_sum(f, spec, lo, hi):
    return np.array([spec[(f >= a) & (f < b)].sum() for a, b in zip(lo, hi)])


def analyse(x, y, sr, bits):
    lag = latency(x, y)
    if lag:
        x, y = x[:len(x) - lag], y[lag:]
    scale = 2.0 ** (bits - 1)
    e = (y - x) * scale  # LSB
    _, lo, hi = third_octave_bands()
    kw = dict(fs=sr, nperseg=NPERSEG)
    f, pll = signal.welch(e[:, 0], **kw)
    _, prr = signal.welch(e[:, 1], **kw)
    _, plr = signal.csd(e[:, 0], e[:, 1], **kw)
    power = band_sum(f, pll + prr, lo, hi)
    corr = band_sum(f, plr.real, lo, hi) / np.sqrt(band_sum(f, pll, lo, hi) * band_sum(f, prr, lo, hi))

    def side_mid(z):
        _, m = signal.welch((z[:, 0] + z[:, 1]) / 2, **kw)
        _, s = signal.welch((z[:, 0] - z[:, 1]) / 2, **kw)
        return band_sum(f, s, lo, hi) / band_sum(f, m, lo, hi)
    width = 10 * np.log10(side_mid(y) / side_mid(x))

    lock = []
    for ch in range(2):
        _, pxx = signal.welch(x[:, ch], **kw)
        _, pxe = signal.csd(x[:, ch], e[:, ch], **kw)
        pee = pll if ch == 0 else prr
        lock.append(band_sum(f, np.abs(pxe) ** 2, lo, hi) / (band_sum(f, pxx, lo, hi) * band_sum(f, pee, lo, hi)))
    lock = np.mean(lock, axis=0)

    eh = signal.sosfilt(signal.butter(4, 20.0, "highpass", fs=sr, output="sos"), e, axis=0)
    frame = int(0.05 * sr)
    n = len(e) // frame
    sig_db = 10 * np.log10(np.mean(x[:n * frame].reshape(n, frame, 2) ** 2, axis=(1, 2)) + 1e-30)
    err_db = 10 * np.log10(np.mean(eh[:n * frame].reshape(n, frame, 2) ** 2, axis=(1, 2)) + 1e-30)
    playing = sig_db > -60
    mod = float(np.percentile(err_db[playing], 95) - np.percentile(err_db[playing], 5))

    audible = (f >= 20) & (f <= 20000)
    p = (pll + prr)[audible]
    flat = float(np.exp(np.mean(np.log(p + 1e-300))) / np.mean(p))
    return {
        "latency_samples": lag,
        "rms_lsb": float(np.sqrt(np.mean(eh ** 2))),
        "rms_dbfs": float(20 * np.log10(np.sqrt(np.mean(eh ** 2)) / scale)),
        "rms_total_dbfs": float(20 * np.log10(np.sqrt(np.mean(e ** 2)) / scale)),
        "corr_total": float(np.corrcoef(e[:, 0], e[:, 1])[0, 1]),
        "band_power": power.tolist(),
        "band_corr": corr.tolist(),
        "band_width": width.tolist(),
        "band_lock": lock.tolist(),
        "modulation_db": mod,
        "flatness": flat,
    }, e


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--bits", type=int, nargs="+", default=[16, 24])
    ap.add_argument("--dithers", nargs="+", default=DITHERS + REFERENCES)
    ap.add_argument("--reuse", action="store_true",
                    help="re-analyse the dithered files already in outdir instead of dithering again")
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.input))[0]
    x, sr = sf.read(args.input, dtype="float64", always_2d=True)
    if x.shape[1] != 2:
        raise SystemExit("stereo input only")
    centres, _, _ = third_octave_bands()
    report = {"input": args.input, "samplerate": sr, "seconds": len(x) / sr,
              "peak_dbfs": float(20 * np.log10(np.abs(x).max())), "bands_hz": centres.tolist(), "runs": {}}
    out_json = os.path.join(args.outdir, "bench.json")
    if os.path.exists(out_json):  # add to an earlier run of the same input
        earlier = json.load(open(out_json))
        if earlier["input"] == args.input:
            report["runs"] = earlier["runs"]
    for bits in args.bits:
        for d in args.dithers:
            dith = os.path.join(args.outdir, f"{stem}_{d}_{bits}bit.wav")
            noise = os.path.join(args.outdir, f"noise_{d}_{bits}bit_+{20 * np.log10(NOISE_GAIN[bits]):.1f}dB.wav")
            if args.reuse:
                ints = sf.read(dith, dtype="int32", always_2d=True)[0] >> (32 - bits)
                y = ints / 2.0 ** (bits - 1)  # exact
                clipped = None
            else:
                for path in (dith, noise):
                    if os.path.exists(path):
                        raise SystemExit(f"exists, refusing to overwrite: {path}")
                y = reference_output(x, bits, d) if d in REFERENCES else plugin_output(x, sr, d, bits)
                ints, clipped = aw_dither.to_integer(y, bits)
            metrics, e = analyse(x, y, sr, bits)
            metrics["clipped"] = clipped
            if not args.reuse:
                sf.write(dith, ints.astype(np.int16) if bits == 16 else ints << 8, sr,
                         "PCM_16" if bits == 16 else "PCM_24")
                # e is in LSB; gain 2^k then back to full scale: exact in float64
                sf.write(noise, e * NOISE_GAIN[bits] / 2.0 ** (bits - 1), sr, "PCM_24")
            report["runs"][f"{d}_{bits}"] = metrics
            print(f"{d:10s} {bits}: rms {metrics['rms_dbfs']:7.1f} dBFS  corr {metrics['corr_total']:+.3f}  "
                  f"mod {metrics['modulation_db']:5.1f} dB  flat {metrics['flatness']:.2f}", flush=True)
            with open(out_json, "w") as fh:
                json.dump(report, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
