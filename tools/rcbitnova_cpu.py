"""CPU cost of V1.1 against V1.0 - and a method that DID NOT WORK, kept here so it is not retried.

THERE IS NO PEAK-BLOCK-TIME API. All 957 functions exposed to ReaScript on this build, SWS
included, contain exactly one performance-related entry: GetUnderrunTime.

THE OFFLINE-THROUGHPUT IDEA BELOW IS INVALID ON THIS SETUP. Measured 2026-08-28: an apply-FX pass
over a 10 s fixture took 35.135, 35.138, 35.135, 35.139, 35.140 s across six V1.0 runs - a spread
of seven milliseconds - and V1.1 returned 35.137. REAPER's apply-FX runs the plugin at 1x realtime
here, so the stopwatch measures the clock, not the DSP: every configuration would report a ratio
of 1.000 no matter how much heavier it actually is. A baseline subtraction does not rescue it,
because the realtime lock applies to the plugin passes and not to the empty one (0.15 s).

Do NOT resurrect timed renders as a CPU gate. Two honest options remain:

  1. REAL-TIME XRUNS (automatic, implemented below): play the material and compare GetUnderrunTime
     before and after. It returns TIMESTAMPS, not counts, so any change is a failure. This catches
     "too heavy to run", which is the property that actually matters.
  2. A CAPACITY PROBE (automatic, not yet written): add instances to a track until playback starts
     producing xruns, and compare how many V1.0 and V1.1 each fit. Crude, but it measures relative
     cost objectively and needs no meter.
  3. The Performance Meter, read by a human. The schema keeps a peak_ms slot for it.

Run: python3 tools/rcbitnova_cpu.py --check
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULT = os.path.join("tests", "fixtures", "cpu_runs.json")
SCHEMA = os.path.join("tests", "fixtures", "cpu_runs.schema.json")
FIXTURE = os.path.abspath(os.path.join("tests", "fixtures", "cpu_10s.wav"))
TRACK = "RCBN CPU TEMP"
RUNS = 6                    # the first is discarded
PLAY_SECONDS = 60
GATE = 1.05

CONFIGS = {
    "baseline": None,
    "v10": ("JS: RCBitNova V1.0", 4),
    "v11_4on": ("JS: RCBitNova V1.1", 4),
    "v11_8on": ("JS: RCBitNova V1.1", 8),
}


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _band_values(fx, RPR, tr, i, n_on):
    """Enable n_on bands, each with dynamics running, so the measurement covers the whole engine
    rather than a chain of disabled branches."""
    names = [fx.params[k].name for k in range(fx.n_params)]
    for b in range(n_on):
        for pname, value in ((f"B{b+1} Enable", 1),
                             (f"B{b+1} Macro (bits)", 1),
                             (f"B{b+1} Freq", 120 * (b + 1)),
                             (f"B{b+1} Dyn", 1),
                             (f"B{b+1} Soft Ceiling Macro (bits below 0)", 2)):
            if pname not in names:
                continue
            k = names.index(pname)
            r = RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)
            lo, hi = r[4], r[5]
            RPR.TrackFX_SetParamNormalized(tr.id, i, k, (value - lo) / (hi - lo))


def measure():
    import reapy
    from tools.make_null_fixture import write_wav   # noqa: E402

    # A short fixture of its own: each timed pass writes a rendered file, and 30 s at 96 kHz in
    # 64-bit float is 80 MB a go. Ten seconds keeps the disk churn to something reasonable while
    # still exercising sweep, noise, silence and transients.

    out = {"runs": [], "play": []}
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        pr = reapy.Project()
        sr = int(RPR.GetSetProjectInfo(pr.id, "PROJECT_SRATE", 0, False))
        bsize = RPR.GetAudioDeviceInfo("BSIZE", "", 64)
        out["reaper_srate"] = sr
        out["block_size"] = bsize[2] if bsize[0] else None
        out["fixture_seconds"] = 10
        write_wav(FIXTURE, SR=sr, secs=10)

        idx = len(pr.tracks)
        RPR.InsertTrackAtIndex(idx, False)
        RPR.TrackList_AdjustWindows(False)
        tr0 = reapy.Project().tracks[idx]
        RPR.GetSetMediaTrackInfo_String(tr0.id, "P_NAME", TRACK, True)
        # no send to master: full DSP load, no sound in the room
        RPR.SetMediaTrackInfo_Value(tr0.id, "B_MAINSEND", 0)

        def track():
            return reapy.Project().tracks[idx]

        def clear():
            tr = track()
            for it in list(tr.items):
                RPR.DeleteTrackMediaItem(tr.id, it.id)
            while tr.fxs:
                tr.fxs[-1].delete()

        def load(config):
            clear()
            for t in reapy.Project().tracks:
                RPR.SetMediaTrackInfo_Value(t.id, "I_SELECTED", 1 if t.index == idx else 0)
            RPR.SetEditCurPos(0, False, False)
            RPR.InsertMedia(FIXTURE, 0)
            tr = track()
            spec = CONFIGS[config]
            if spec:
                fx = tr.add_fx(spec[0])
                _band_values(fx, RPR, tr, fx.index, spec[1])
            return track()

        def timed_render(tr):
            it = tr.items[0]
            RPR.Main_OnCommand(40289, 0)
            RPR.SetMediaItemSelected(it.id, True)
            t0 = time.perf_counter()
            RPR.Main_OnCommand(40209, 0)
            dt = time.perf_counter() - t0
            it2 = track().items[0]
            tk = RPR.GetTake(it2.id, RPR.CountTakes(it2.id) - 1)
            path = RPR.GetMediaSourceFileName(RPR.GetMediaItemTake_Source(tk), "", 1024)[1]
            # the item itself is thrown away by the next load(); only the file needs removing,
            # and no unverified action ID is involved in doing it
            os.path.exists(path) and os.unlink(path)
            return dt

        for config in CONFIGS:
            for run in range(RUNS):
                tr = load(config)
                dt = timed_render(tr)
                out["runs"].append({"config": config, "run": run, "seconds": round(dt, 4),
                                    "peak_ms": None})
                print(f"  {config:9s} run {run}: {dt:6.3f} s", flush=True)

        for config in ("v10", "v11_4on", "v11_8on"):
            tr = load(config)
            before = RPR.GetUnderrunTime(0, 0, 0)
            RPR.SetEditCurPos(0, False, True)
            RPR.CSurf_OnPlay()
            time.sleep(PLAY_SECONDS)
            RPR.CSurf_OnStop()
            after = RPR.GetUnderrunTime(0, 0, 0)
            out["play"].append({"config": config, "seconds": PLAY_SECONDS,
                                "audio_xrun_before": before[0], "audio_xrun_after": after[0],
                                "media_xrun_before": before[1], "media_xrun_after": after[1]})
            print(f"  {config:9s} played {PLAY_SECONDS}s: xrun {before[0]} -> {after[0]}",
                  flush=True)

        clear()
        RPR.DeleteTrack(track().id)

    os.makedirs(os.path.dirname(RESULT), exist_ok=True)
    with open(RESULT, "w") as f:
        json.dump(out, f, indent=2)
    return out


def check(data=None):
    data = data or json.load(open(RESULT))
    problems = []
    by = {}
    for r in data["runs"]:
        by.setdefault(r["config"], []).append(r)
    for config in CONFIGS:
        rs = by.get(config, [])
        if len(rs) != RUNS:
            problems.append(f"{config}: {len(rs)} runs, expected {RUNS}")
    for p in data["play"]:
        if p["audio_xrun_after"] != p["audio_xrun_before"]:
            problems.append(f"{p['config']}: an audio xrun occurred during playback")
    if problems:
        return problems, {}

    med = {c: median([r["seconds"] for r in by[c][1:]]) for c in CONFIGS}   # drop the first
    dsp = {c: med[c] - med["baseline"] for c in CONFIGS if c != "baseline"}
    ratio_gate = dsp["v11_4on"] / dsp["v10"]
    ratio_info = dsp["v11_8on"] / dsp["v11_4on"]
    if ratio_gate > GATE:
        problems.append(f"regression: V1.1 with four bands is {ratio_gate:.3f}x V1.0, "
                        f"limit {GATE}")
    return problems, {"median_seconds": med, "dsp_seconds": dsp,
                      "gate_ratio": ratio_gate, "eight_vs_four": ratio_info}


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    if mode == "--measure":
        raise SystemExit("--measure is disabled: apply-FX runs at 1x realtime on this setup, so "
                         "the timing it produces is the clock, not the DSP. See the module "
                         "docstring for the numbers and for what to do instead.")
    problems, summary = check()
    for k, v in summary.items():
        print(f"  {k}: {v}")
    if problems:
        for p in problems:
            print(f"FAIL cpu: {p}")
        return 1
    print(f"OK cpu: V1.1/V1.0 four bands = {summary['gate_ratio']:.3f}x (limit {GATE}); "
          f"eight vs four = {summary['eight_vs_four']:.3f}x, informational; no xruns")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
