#!/usr/bin/env python3
"""Dither audio files to 16 or 24 bit with Airwindows dithers, without a DAW.

The DSP is the unmodified Airwindows source (vendor/), compiled into
build/awproc-<arch> and run through each plugin's processDoubleReplacing, as
a VST2 host does. Input is read as float64 and never passes through float32.
The plugin output must already lie on the target integer grid; it is written
as integer PCM only after that is checked, so the file holds exactly what the
plugin produced (no host dither, no rounding).

    aw_dither.py mix.wav --dither dark --bits 16
    aw_dither.py *.wav --dither ditherbox --type NJAD --bits 24 -o out/

An existing output file is never replaced unless --overwrite is given.
--verify re-runs the input through the installed plugin binary (a minimal
VST2 host, build/vst2_oracle-<arch>) and checks the file sample for sample.

Build first: ./build.sh
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile
import threading

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK_FRAMES = 65536

# Ditherbox type names, in plugin order; 16-bit types are 0..10 and the same
# names repeat for 24 bit at 11..21.
DITHERBOX_TYPES = ["Trunc", "Flat", "TPDF", "Paul", "DbPaul", "Tape", "HiGloss",
                   "Vinyl", "Spatial", "Natural", "NJAD"]

DITHERS = {
    # name: (plugin, needs x86_64)
    "dark": ("Dark", False),
    "tpdfwide": ("TPDFWide", False),
    "njad": ("NotJustAnotherDither", False),
    "spatialize": ("SpatializeDither", False),
    "vinyl": ("VinylDither", False),
    "tape": ("TapeDither", False),
    "monitoring": ("Monitoring", False),
    "studiotan": ("StudioTan", False),
    "darkstereo": ("DarkStereo", False),  # ours, derived from Dark: no installed plugin to verify against
    "ditherbox": ("Ditherbox", False),
    "ditherbox2018": ("Ditherbox2018", True),
}

VST_DIR = "/Library/Audio/Plug-Ins/VST"
INSTALLED_ELSEWHERE = {"ditherbox2018": "/Volumes/Music 5/Video/Ditherbox/Ditherbox.vst"}


def choice_value(index, count):
    """Parameter value an Airwindows popup decodes as `index`: (int)(A * (count - 0.001))."""
    return float(np.float32((index + 0.5) / count))


def plugin_params(dither, bits, dtype=None, stereo=0.55):
    """[(index, value)] that set `dither` up for `bits`-bit output."""
    if dither in ("dark", "tpdfwide", "njad", "spatialize", "vinyl", "tape"):
        return [(0, 0.0 if bits == 16 else 1.0), (1, 0.0)]  # Quant, DeRez off
    if dither == "darkstereo":
        return [(0, 0.0 if bits == 16 else 1.0), (1, 0.0), (2, stereo)]
    if dither == "monitoring":
        return [(0, choice_value(1 if bits == 16 else 0, 17))]  # Out16 / Out24
    if dither == "studiotan":
        return [(0, choice_value(3 if bits == 16 else 0, 6))]  # ST 16 / ST 24
    if dtype not in DITHERBOX_TYPES:
        raise ValueError(f"--type must be one of {', '.join(DITHERBOX_TYPES)}")
    index = DITHERBOX_TYPES.index(dtype) + (0 if bits == 16 else 11)
    return [(0, choice_value(index, 25))]


def build_exe(name, x86):
    """[argv prefix] running build/<name>-<arch>, under Rosetta when x86 on arm."""
    arch = "x86_64" if x86 else platform.machine()
    exe = os.path.join(HERE, "build", f"{name}-{arch}")
    if not os.path.exists(exe):
        raise FileNotFoundError(f"{exe} missing: run {os.path.join(HERE, 'build.sh')}")
    return (["arch", "-x86_64"] if x86 and platform.machine() != "x86_64" else []) + [exe]


def awproc_command(plugin, x86, sample_rate, params, seed, prefill):
    cmd = build_exe("awproc", x86) + [plugin, repr(float(sample_rate)), str(seed), str(prefill)]
    return cmd + [f"{i}={v!r}" for i, v in params]


def process_blocks(blocks, cmd):
    """Stream stereo float64 blocks through awproc; yields processed blocks."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    sizes = []
    error = []

    def feed():
        try:
            for block in blocks:
                block = np.ascontiguousarray(block, dtype="=f8")
                sizes.append(len(block))
                proc.stdin.write(block.tobytes())
        except Exception as exc:  # surfaced after the reader finishes
            error.append(exc)
        finally:
            proc.stdin.close()

    writer = threading.Thread(target=feed)
    writer.start()
    done = 0
    while True:
        while done >= len(sizes) and writer.is_alive():
            writer.join(0.01)
        if done >= len(sizes):
            break
        want = sizes[done] * 16
        raw = proc.stdout.read(want)
        if len(raw) != want:
            break
        yield np.frombuffer(raw, dtype="=f8").reshape(-1, 2)
        done += 1
    writer.join()
    proc.stdout.close()
    code = proc.wait()
    if error:
        raise error[0]
    if code != 0 or done != len(sizes):
        raise RuntimeError(f"awproc failed (exit {code}): {' '.join(cmd)}")


def to_integer(y, bits):
    """Plugin output -> integer samples, refusing anything off the grid."""
    scale = 2.0 ** (bits - 1)
    scaled = y * scale  # exact: power-of-two scaling
    ints = np.floor(scaled)
    if not np.array_equal(ints, scaled):
        bad = np.flatnonzero(ints != scaled)
        raise ValueError(f"plugin output is off the {bits}-bit grid at {len(bad)} samples "
                         f"(first {scaled.flat[bad[0]]!r}); is a DeRez/mode set wrong?")
    clipped = int(np.count_nonzero(ints > scale - 1) + np.count_nonzero(ints < -scale))
    return np.clip(ints, -scale, scale - 1).astype(np.int32), clipped


def pair_blocks(src, left, right):
    """Blocks of channels (left, right) of `src` as float64 stereo."""
    with sf.SoundFile(src) as fin:
        for block in fin.blocks(BLOCK_FRAMES, dtype="float64", always_2d=True):
            yield np.stack([block[:, left], block[:, right]], axis=1)


def stereo_pairs(channels):
    """Channel pairs, one plugin instance each; a lone last channel runs as both sides."""
    return [(c, min(c + 1, channels - 1)) for c in range(0, channels, 2)]


def dither_file(src, dst, dither, bits, dtype=None, seed=1, prefill=0, stereo=0.55):
    """Dither one file; returns the number of samples clipped at full scale."""
    plugin, x86 = DITHERS[dither]
    info = sf.info(src)
    cmd = awproc_command(plugin, x86, info.samplerate, plugin_params(dither, bits, dtype, stereo), seed, prefill)
    # Each stereo pair gets its own plugin instance, as a host would; all pairs
    # stream side by side.
    streams = [process_blocks(pair_blocks(src, l, r), cmd) for l, r in stereo_pairs(info.channels)]
    subtype = "PCM_16" if bits == 16 else "PCM_24"
    clipped = 0
    tmp = dst + ".part.wav"
    try:
        with sf.SoundFile(tmp, "w", info.samplerate, info.channels, subtype, format="WAV") as fout:
            for outs in zip(*streams):
                block = np.concatenate(outs, axis=1)[:, :info.channels]
                ints, n = to_integer(block, bits)
                clipped += n
                # libsndfile reads int32 as left-justified: shift 24-bit values up.
                fout.write(ints.astype(np.int16) if bits == 16 else ints << 8)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return clipped


def verify_file(src, dst, dither, bits, dtype=None, seed=1):
    """Check dst against src run through the installed plugin binary; returns its path.

    Covers the default Ditherbox noise state only: the installed plugin always
    starts from zeroed memory.
    """
    plugin, x86 = DITHERS[dither]
    bundle = INSTALLED_ELSEWHERE.get(dither, os.path.join(VST_DIR, plugin + ".vst"))
    if not os.path.exists(bundle):
        raise FileNotFoundError(f"cannot verify: {bundle} not found")
    info = sf.info(src)
    got = sf.read(dst, dtype="int32", always_2d=True)[0] >> (32 - bits)
    params = [f"{i}={v!r}" for i, v in plugin_params(dither, bits, dtype)]
    with tempfile.TemporaryDirectory() as tmp:
        fin, fout = os.path.join(tmp, "in.f64"), os.path.join(tmp, "out.f64")
        for left, right in stereo_pairs(info.channels):
            x = np.concatenate(list(pair_blocks(src, left, right)))
            np.ascontiguousarray(x, dtype="=f8").tofile(fin)
            del x
            subprocess.run(build_exe("vst2_oracle", x86) + [bundle, repr(float(info.samplerate)), str(seed),
                                                            fin, fout] + params, check=True)
            expect = to_integer(np.fromfile(fout, dtype="=f8").reshape(-1, 2), bits)[0]
            for side, ch in enumerate((left, right)):
                if len(expect) != len(got) or not np.array_equal(got[:, ch], expect[:, side]):
                    raise ValueError(f"{dst} channel {ch + 1} differs from {os.path.basename(bundle)}")
    return bundle


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="audio files (any format libsndfile reads)")
    ap.add_argument("--dither", required=True, choices=sorted(DITHERS))
    ap.add_argument("--bits", type=int, required=True, choices=[16, 24])
    ap.add_argument("--type", dest="dtype", choices=DITHERBOX_TYPES, help="Ditherbox type")
    ap.add_argument("--stereo", type=float, default=0.55,
                    help="darkstereo: L/R decorrelation, 0 = Dark exactly; nothing changes below ~0.5 (default 0.55)")
    ap.add_argument("-o", "--outdir", help="output folder (default: next to each input)")
    ap.add_argument("--overwrite", action="store_true", help="replace existing output files")
    ap.add_argument("--verify", action="store_true",
                    help="check each file sample for sample against the installed plugin binary")
    ap.add_argument("--seed", type=int, default=1, help="dither noise seed (default 1)")
    ap.add_argument("--ditherbox-noise", choices=["installed", "seeded"], default="installed",
                    help="Ditherbox never initialises its noise state: 'installed' = zero state, "
                         "as the installed plugin gets it (noise-based types then add no noise); "
                         "'seeded' = noise from --seed")
    args = ap.parse_args(argv)
    if args.dither.startswith("ditherbox") and not args.dtype:
        ap.error("--type is required for Ditherbox")
    if args.verify and args.dither == "darkstereo":
        ap.error("--verify: darkstereo has no installed plugin to compare with")
    if args.verify and args.ditherbox_noise == "seeded":
        ap.error("--verify needs --ditherbox-noise installed (the installed plugin has no seeded noise)")
    prefill = 0 if args.ditherbox_noise == "installed" else -1
    tag = args.dither + (f"-{args.dtype}" if args.dtype else "") + (f"-{args.stereo:g}" if args.dither == "darkstereo" else "")
    failed = 0
    for src in args.inputs:
        stem = os.path.splitext(os.path.basename(src))[0]
        outdir = args.outdir or os.path.dirname(os.path.abspath(src))
        os.makedirs(outdir, exist_ok=True)
        dst = os.path.join(outdir, f"{stem}_{tag}_{args.bits}bit.wav")
        if os.path.exists(dst) and not args.overwrite:
            print(f"exists, skipped: {dst}", file=sys.stderr)
            failed += 1
            continue
        clipped = dither_file(src, dst, args.dither, args.bits, args.dtype, args.seed, prefill, args.stereo)
        note = f"  ({clipped} samples clipped at full scale)" if clipped else ""
        if args.verify:
            bundle = verify_file(src, dst, args.dither, args.bits, args.dtype, args.seed)
            note += f"  [bit-identical to {bundle}]"
        print(f"{dst}{note}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
