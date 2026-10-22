"""aw_dither: Airwindows dithers rebuilt from source, checked bit-for-bit
against the installed plugin binaries (the same ones REAPER loads).

Oracle tests run the shipped .vst through build/vst2_oracle-<arch> and skip
when a plugin is not installed. Run ./tools/airwindows_dither/build.sh first.
"""
import os
import platform
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools", "airwindows_dither")
sys.path.insert(0, TOOL)
import aw_dither  # noqa: E402

VST = "/Library/Audio/Plug-Ins/VST"
DITHERBOX_2018 = "/Volumes/Music 5/Video/Ditherbox/Ditherbox.vst"
NATIVE = platform.machine()

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(TOOL, "build", f"awproc-{NATIVE}")), reason="run build.sh first")


def music(sr, secs=2.0):
    """Stereo test signal: tone + decaying noise, digital silence, a near-silent stretch."""
    rng = np.random.default_rng(7)
    t = np.arange(int(sr * secs)) / sr
    x = np.stack([0.3 * np.sin(2 * np.pi * 440 * t) + 0.05 * rng.standard_normal(t.size) * np.exp(-t),
                  0.25 * np.sin(2 * np.pi * 97.3 * t + 1) + 0.0003 * np.sin(2 * np.pi * 3000 * t)], axis=1)
    x[int(sr * 0.8):int(sr * 1.0)] = 0.0
    x[int(sr * 1.0):int(sr * 1.2)] *= 1e-6
    return x


def run_awproc(plugin, sr, params, x, x86=False, seed=1, prefill=0):
    cmd = aw_dither.awproc_command(plugin, x86, sr, params, seed, prefill)
    blocks = (x[s:s + 4096] for s in range(0, len(x), 4096))
    return np.concatenate(list(aw_dither.process_blocks(blocks, cmd)))


def run_oracle(bundle, sr, params, x, tmp_path, arch=NATIVE, seed=1):
    fin, fout = tmp_path / "in.f64", tmp_path / "out.f64"
    np.ascontiguousarray(x, dtype="=f8").tofile(fin)
    cmd = [os.path.join(TOOL, "build", f"vst2_oracle-{arch}"), bundle, repr(float(sr)), str(seed),
           str(fin), str(fout)] + [f"{i}={v!r}" for i, v in params]
    if arch != NATIVE:
        cmd = ["arch", f"-{arch}"] + cmd
    subprocess.run(cmd, check=True)
    return np.fromfile(fout, dtype="=f8").reshape(-1, 2)


def bit_equal(a, b):
    return a.shape == b.shape and np.array_equal(a.view(np.uint64), b.view(np.uint64))


def installed_cases():
    cases = []
    for plugin in ["Dark", "TPDFWide", "NotJustAnotherDither"]:
        cases += [(plugin, [(0, 0.0), (1, 0.0)]), (plugin, [(0, 1.0), (1, 0.0)])]
    cases += [("Ditherbox", [(0, aw_dither.choice_value(k, 25))]) for k in range(25)]
    cases += [("Monitoring", [(0, aw_dither.choice_value(k, 17))]) for k in range(17)]
    return cases


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
@pytest.mark.parametrize("plugin,params", installed_cases())
def test_bit_identical_to_installed_plugin(plugin, params, sr, tmp_path):
    bundle = os.path.join(VST, plugin + ".vst")
    if not os.path.exists(bundle):
        pytest.skip(f"{plugin} not installed")
    x = music(sr, 1.5)
    assert bit_equal(run_awproc(plugin, sr, params, x), run_oracle(bundle, sr, params, x, tmp_path))


@pytest.mark.parametrize("plugin,params", [c for c in installed_cases() if c[0] in ("Dark", "Ditherbox")][::3])
def test_x86_64_build_matches_installed_plugin_under_rosetta(plugin, params, tmp_path):
    x = music(48000, 1.0)
    ours = run_awproc(plugin, 48000, params, x, x86=True)
    assert bit_equal(ours, run_oracle(os.path.join(VST, plugin + ".vst"), 48000, params, x, tmp_path, "x86_64"))


@pytest.mark.skipif(not os.path.exists(DITHERBOX_2018), reason="2018 Ditherbox not mounted")
@pytest.mark.parametrize("sr", [44100, 96000])
@pytest.mark.parametrize("k", range(25))
def test_ditherbox2018_bit_identical_to_2018_binary(k, sr, tmp_path):
    params = [(0, aw_dither.choice_value(k, 25))]
    x = music(sr, 1.0)
    ours = run_awproc("Ditherbox2018", sr, params, x, x86=True)
    assert bit_equal(ours, run_oracle(DITHERBOX_2018, sr, params, x, tmp_path, "x86_64"))


@pytest.mark.parametrize("dither,dtype", [("dark", None), ("tpdfwide", None), ("njad", None),
                                          ("monitoring", None), ("ditherbox", "NJAD"), ("ditherbox", "TPDF")])
@pytest.mark.parametrize("bits", [16, 24])
def test_file_holds_exactly_the_plugin_output(dither, dtype, bits, tmp_path):
    sr = 44100
    x = music(sr)
    src = tmp_path / "in.wav"
    sf.write(src, x, sr, subtype="DOUBLE")
    aw_dither.main([str(src), "--dither", dither, "--bits", str(bits), "-o", str(tmp_path)]
                   + (["--type", dtype] if dtype else []))
    tag = dither + (f"-{dtype}" if dtype else "")
    dst = tmp_path / f"in_{tag}_{bits}bit.wav"
    assert sf.info(dst).subtype == ("PCM_16" if bits == 16 else "PCM_24")
    got = sf.read(dst, dtype="int32")[0] >> (32 - bits)
    plugin = aw_dither.DITHERS[dither][0]
    expect = run_awproc(plugin, sr, aw_dither.plugin_params(dither, bits, dtype), x) * 2.0 ** (bits - 1)
    assert np.array_equal(got, expect)


def test_input_precision_below_float32_reaches_the_quantiser():
    # Just under an integer step: float64 floors to k-1, float32 would round up to k.
    k = 1000
    x = np.full((8, 2), (k - 1e-9) / 32768.0)
    assert np.float32(x[0, 0]) * 32768.0 == k
    out = run_awproc("Ditherbox", 44100, aw_dither.plugin_params("ditherbox", 16, "Trunc"), x)
    assert np.all(out * 32768.0 == k - 1)


def test_dark_is_deterministic_regardless_of_seed():
    x = music(44100, 1.0)
    params = aw_dither.plugin_params("dark", 16)
    assert bit_equal(run_awproc("Dark", 44100, params, x, seed=1), run_awproc("Dark", 44100, params, x, seed=99))


def test_seeded_ditherbox_noise_differs_from_installed_zero_state():
    x = music(44100, 0.5)
    params = aw_dither.plugin_params("ditherbox", 16, "TPDF")
    zero = run_awproc("Ditherbox", 44100, params, x, prefill=0)
    seeded = run_awproc("Ditherbox", 44100, params, x, prefill=-1)
    assert not np.array_equal(zero, seeded)


def test_off_grid_output_is_refused():
    with pytest.raises(ValueError, match="off the 16-bit grid"):
        aw_dither.to_integer(np.array([[0.5 / 32768, 0.0]]), 16)


def test_full_scale_is_clipped_and_counted():
    ints, clipped = aw_dither.to_integer(np.array([[1.0, -1.0], [0.5, -1.0 - 2 ** -15]]), 16)
    assert ints.tolist() == [[32767, -32768], [16384, -32768]]
    assert clipped == 2


def test_mono_and_three_channel_files(tmp_path):
    sr = 48000
    x = music(sr, 0.5)
    for channels in (1, 3):
        data = np.concatenate([x, x[:, :1] * 0.5], axis=1)[:, :channels]
        src = tmp_path / f"c{channels}.wav"
        sf.write(src, data, sr, subtype="DOUBLE")
        dst = tmp_path / f"c{channels}_out.wav"
        aw_dither.dither_file(str(src), str(dst), "dark", 16)
        got = sf.read(dst, dtype="int16", always_2d=True)[0]
        assert got.shape == (len(data), channels)
        # mono: the lone channel runs as both sides of one instance
        lone = data[:, -1:]
        expect = run_awproc("Dark", sr, aw_dither.plugin_params("dark", 16), np.concatenate([lone, lone], axis=1))
        assert np.array_equal(got[:, -1], expect[:, 0] * 32768.0)
