# aw_dither — Airwindows dithers without a DAW

Dithers audio files to 16 or 24 bit with Airwindows Dark, TPDFWide,
NotJustAnotherDither, SpatializeDither, VinylDither, TapeDither, Monitoring
(Out16/Out24) and Ditherbox (2022 build, and
the 2018 Intel build as `ditherbox2018`).

```
./build.sh
~/.venvs/madmom/bin/python aw_dither.py mix.wav --dither dark --bits 24
~/.venvs/madmom/bin/python aw_dither.py *.wav --dither ditherbox --type NJAD --bits 16 -o out/
```

`--verify` re-runs each input through the installed plugin binary and checks
the written file sample for sample. An existing output is skipped unless
`--overwrite` is given.

## Install (Finder Quick Action)

`./install.sh` builds, copies the tool to
`~/Library/Application Support/aw_dither/` and creates the Quick Action
**Airwindows Dither…** for audio files (Finder: right-click > Quick Actions).
It asks for the dither, bit depth and Ditherbox type, remembers the last
choice, writes next to each file with `--verify`, and reports in a
notification (log: `last_run.log` in the install folder). Re-run `install.sh`
after changing the tool.

The DSP is the unmodified MIT Airwindows source in `vendor/`, run through each
plugin's `processDoubleReplacing`. Input is read as float64; the output is
checked to lie on the integer grid before it is written as PCM.

## Verification

- `tests/test_aw_dither.py` compares against the installed VST2 binaries
  through `oracle/vst2_oracle.c` (a minimal VST2 host): every plugin and mode,
  44.1/48/96 kHz, bit for bit. `ditherbox2018` is compared with the 2018 binary
  under Rosetta.
- Live REAPER 7.81 A/B (2026-10-22, 20 s of real material, render dither off):
  Dark 16/24 and Ditherbox TPDF/NJAD bit-identical. TPDFWide, NJAD and
  Monitoring differ only by their noise seed, which they take from `rand()`
  when created; with REAPER's seeds recovered by brute force all three are
  bit-identical too. REAPER's own PCM16/PCM24 conversion of the plugin output
  is exact.

## Behaviour to know

- **Ditherbox (2022) adds no noise.** It never initialises its noise state, and
  the installed plugin gets zeroed memory, so Flat/TPDF/Paul/etc. run without
  noise, in REAPER as well. `--ditherbox-noise installed` (default) reproduces
  that; `seeded` gives the noise the author intended.
- Plugins seeded from `rand()` (Dark at digital silence only, TPDFWide, NJAD,
  Spatialize/Vinyl/TapeDither, Monitoring, Ditherbox2018) get `--seed`; REAPER's seed varies per instance.
- In REAPER, Airwindows state carries over between renders/playback (the first
  samples can differ from a fresh instance). Here every file starts fresh.
- BWF/bext metadata is not carried over.
