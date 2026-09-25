"""V1.1 with bands 5-8 disabled must be sample-identical to V1.0.

WHAT THIS PROVES, exactly: equality of the RENDERED output. On this machine the render happens to
be 64-bit float at the project rate, so it is very close to internal precision - but the claim
stays "the two renders are identical", because that is what is measured.

METHOD. "Apply track FX to items as new take" (action 40209) rather than a project render: it
touches no RENDER_* setting, needs no bounds or stem configuration, and writes one file per pass.
Everything happens on a scratch track that this script creates and removes.

EQUAL STATE. Both instances get the same 95 declared normalised values, written directly. The
--live gate has already proven those 95 records identical between the versions, so writing them is
equality by construction; the migration script has its own thirteen tests and is not needed here.

Run: python3 tools/rcbitnova_nulltest.py
"""

import array
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.make_null_fixture import write_wav   # noqa: E402

FIXTURE = os.path.abspath(os.path.join("tests", "fixtures", "null_30s.wav"))
TRACK = "RCBN NULL TEMP"

# Every DECLARED record, not the historical 95. The state copy has to span every record the
# migrator also touches, slider246 included, or the two instances can differ in one the check
# never looks at.
N_DECLARED = 176

# The panel's contract is "no DSP change from V1.1", so V1.1 is the baseline. Comparing against
# V1.0 would still be true and would answer a question nobody is asking about this feature.
BASE = "RCBitNova V1.5"
UNDER_TEST = "RCBitNova V1.6"

# case -> {declared parameter name: value in ITS OWN units}
CASES = {
    "defaults": {},
    "modeA": {"B1 Enable": 1, "B1 Macro (bits)": 2, "B1 Freq": 300, "B1 Dyn": 1,
              "B1 Dyn Mode": 0, "B1 Soft Ceiling Macro (bits below 0)": 3,
              "B2 Enable": 1, "B2 Macro (bits)": -2, "B2 Freq": 3000, "B2 Dyn": 1,
              "B2 Dyn Mode": 0, "B2 Soft Ceiling Macro (bits below 0)": 2},
    "modeB": {"B1 Enable": 1, "B1 Freq": 200, "B1 Dyn": 1, "B1 Dyn Mode": 1,
              "B1 Soft Ceiling Macro (bits below 0)": 2, "B1 Hard": 1,
              "B3 Enable": 1, "B3 Freq": 5000, "B3 Dyn": 1, "B3 Dyn Mode": 1,
              "B3 Soft Ceiling Macro (bits below 0)": 1.5},
    "min_hplp": {"HP Slope (dB/oct)": 3, "HP Freq (Hz)": 80,
                 "LP Slope (dB/oct)": 2, "LP Freq (Hz)": 12000, "Phase": 0},
    "linear_hplp": {"HP Slope (dB/oct)": 3, "HP Freq (Hz)": 80,
                    "LP Slope (dB/oct)": 2, "LP Freq (Hz)": 12000, "Phase": 1,
                    "HP Resolution (Linear only)": 1, "LP Resolution (Linear only)": 1},
}

# Nothing diverges any more. This case WAS a deliberate divergence while the baseline was V1.0,
# which had no Enable gate on Mode B; against V1.1 both sides have it, so it becomes an ordinary
# identical case - and a useful one, because it exercises a disabled band that still has dynamics
# configured, which is exactly the state a panel gesture can leave behind.
CASES["modeB_disabled_band"] = {"B1 Enable": 0, "B1 Freq": 200, "B1 Dyn": 1, "B1 Dyn Mode": 1,
                                "B1 Soft Ceiling Macro (bits below 0)": 3, "B1 Soft": 1,
                                "B2 Enable": 1, "B2 Macro (bits)": 1, "B2 Freq": 1000}
DIVERGENT = {}

# ---- V1.6: transitions, the cases the steady-state set cannot reach ----
#
# The wedge's risk is not the steady state - it is every boundary: an Lk change, a lane that stops
# being written and resumes, a band switched off and on. A parameter written before the render
# never exercises any of them, so these cases drive the change DURING the render, through an FX
# parameter automation envelope: exact, repeatable, and applied by REAPER itself rather than by a
# race between this script and the audio thread.
#
# Two gotchas, both already paid for in this project:
#   - InsertEnvelopePoint takes ACTUAL slider values for an FX parameter envelope, not normalised.
#   - REAPER auto-creates a point at t=0; it must be deleted before custom points are written.
# And one that is specific to this harness: if automation turns out NOT to be applied during
# "apply track FX as new take", every case below would render identically and report a clean pass
# for a comparison that never happened. _self_test_envelope() exists to make that impossible.
#
# Shape 1 (square) everywhere: a ramp would make the two versions disagree about WHEN the value
# changed, which is a different experiment from the one being run.
MODE_B_8 = {}
for _b in range(1, 9):
    MODE_B_8.update({f"B{_b} Enable": 1, f"B{_b} Dyn": 1, f"B{_b} Dyn Mode": 1,
                     f"B{_b} Freq": 120 * _b,
                     f"B{_b} Soft Ceiling Macro (bits below 0)": 2})

TRANSITIONS = {
    # 1. the lookahead knob moved under audio, up and back down
    "lk_sweep": {"values": {**MODE_B_8, "Lookahead (ms, Mode B)": 2.0},
                 "env": {"Lookahead (ms, Mode B)": [(0.0, 2.0), (3.0, 10.0), (6.5, 2.0)]}},
    # 2. Both -> Mid -> Both: lane B stops being written while the band's cursor keeps advancing
    "both_mid_both": {"values": {**MODE_B_8, "Lookahead (ms, Mode B)": 5.0},
                      "env": {"B1 Placement": [(0.0, 0), (3.0, 1), (6.5, 0)]}},
    # 3. the same, with the Lk change landing WHILE lane B is inactive - the pending change must
    #    survive until that lane next processes, or it is marked clean without having rebuilt
    "lk_change_while_lane_inactive": {
        "values": {**MODE_B_8, "Lookahead (ms, Mode B)": 2.0},
        "env": {"B1 Placement": [(0.0, 0), (2.0, 1), (7.0, 0)],
                "Lookahead (ms, Mode B)": [(0.0, 2.0), (4.0, 9.0)]}},
    # 4. the dynamics section switched off and back on under audio
    "modeb_off_on": {"values": {**MODE_B_8, "Lookahead (ms, Mode B)": 4.0},
                     "env": {"B1 Dyn": [(0.0, 1), (3.0, 0), (6.0, 1)]}},
    # 5. a band disabled and re-enabled - V1.0 shipped with a band that was off but still audible
    "band_disable_enable": {"values": {**MODE_B_8, "Lookahead (ms, Mode B)": 4.0},
                            "env": {"B3 Enable": [(0.0, 1), (2.5, 0), (5.5, 1)]}},
}


def write_fx_envelope(RPR, track_id, fx_index, param_index, points):
    """An FX parameter envelope with square points, in the parameter's OWN units."""
    env = RPR.GetFXEnvelope(track_id, fx_index, param_index, True)
    assert env, "GetFXEnvelope returned nothing"
    RPR.DeleteEnvelopePointRange(env, -1.0, 1.0e9)      # REAPER's own point at t=0 goes first
    for t, v in points:
        RPR.InsertEnvelopePoint(env, float(t), float(v), 1, 0.0, False, True)  # shape 1 = square
    RPR.Envelope_SortPoints(env)
    return env


def read_float_wav(path):
    """Python's `wave` rejects WAVE_FORMAT_IEEE_FLOAT (3), and the renders here are float, so the
    RIFF chunks are walked directly. Returns (samples, sample_rate, channels, bits)."""
    with open(path, "rb") as f:
        data = f.read()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", f"{path}: not a RIFF/WAVE file"
    pos, fmt, payload = 12, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            payload = body
        pos += 8 + size + (size & 1)
    assert fmt is not None and payload is not None, f"{path}: missing fmt or data chunk"
    tag, ch, sr, _br, _ba, bits = fmt
    assert tag == 3, f"{path}: format tag {tag}, expected 3 (IEEE float) - an integer render " \
                     "would quantise a real difference away"
    code = "f" if bits == 32 else "d"
    samples = array.array(code)
    samples.frombytes(payload[:len(payload) - len(payload) % samples.itemsize])
    return samples, sr, ch, bits


def compare(path_a, path_b, case):
    a, sr_a, ch_a, bits_a = read_float_wav(path_a)
    b, sr_b, ch_b, bits_b = read_float_wav(path_b)
    assert (sr_a, ch_a, bits_a) == (sr_b, ch_b, bits_b), \
        f"{case}: formats differ, {(sr_a, ch_a, bits_a)} vs {(sr_b, ch_b, bits_b)}"
    assert len(a) == len(b), f"{case}: {len(a)} samples vs {len(b)} - lengths must match first"
    for i in range(len(a)):
        if a[i] != b[i]:
            raise AssertionError(f"{case}: first difference at sample {i} "
                                 f"(frame {i // ch_a}, {i / ch_a / sr_a:.6f} s): "
                                 f"V1.0 {a[i]!r} vs V1.1 {b[i]!r}")
    return len(a), sr_a, bits_a


def _self_test_comparator(path):
    """Prove the comparator can fail below PCM resolution. If a one-ULP edit passes, the format is
    quantising and the whole gate is decorative."""
    import tempfile
    with open(path, "rb") as f:
        raw = bytearray(f.read())
    samples, _sr, _ch, bits = read_float_wav(path)
    code = "f" if bits == 32 else "d"
    idx = next(i for i, v in enumerate(samples) if v != 0.0)
    one = array.array(code, [samples[idx]])
    bits_int = int.from_bytes(one.tobytes(), "little") + 1          # one ULP up
    patched = bits_int.to_bytes(one.itemsize, "little")
    off = raw.find(b"data")
    start = off + 8 + idx * one.itemsize
    raw[start:start + one.itemsize] = patched
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(bytes(raw))
    tmp.close()
    try:
        compare(path, tmp.name, "self-test")
    except AssertionError:
        return True
    finally:
        os.unlink(tmp.name)
    return False


def main():
    import reapy
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        # ---- work in the CURRENT project, and only if it is empty ----
        # An earlier revision opened a project tab of its own, to stop the owner's tab-switching
        # from changing the sample rate under the test. That killed reapy outright: its server is
        # a DEFERRED SCRIPT living in a project context, and switching the active project stops it
        # being called. The run hung with zero output and died on RELEASE with
        # ConnectionAbortedError. Refusing to run in a project that has content is the same
        # protection without fighting the architecture.
        pr = reapy.Project()
        assert len(pr.tracks) == 0, (
            f"this project has {len(pr.tracks)} tracks; open an empty project before running the "
            f"null test - it renders, and it will not do that in a session with work in it")

        sr = int(RPR.GetSetProjectInfo(pr.id, "PROJECT_SRATE", 0, False))
        if sr == 0:
            sr = 48000
            RPR.GetSetProjectInfo(pr.id, "PROJECT_SRATE", sr, True)
            RPR.GetSetProjectInfo(pr.id, "PROJECT_SRATE_USE", 1, True)
        # The fixture follows the project rather than the project being asked to follow it.
        if not os.path.exists(FIXTURE) or read_float_wav(FIXTURE)[1] != sr:
            write_wav(FIXTURE, SR=sr)

        idx = len(pr.tracks)
        RPR.InsertTrackAtIndex(idx, False)
        RPR.TrackList_AdjustWindows(False)
        RPR.GetSetMediaTrackInfo_String(reapy.Project().tracks[idx].id, "P_NAME", TRACK, True)

        def track():
            return reapy.Project().tracks[idx]

        def clear():
            tr = track()
            for it in list(tr.items):
                RPR.DeleteTrackMediaItem(tr.id, it.id)
            while tr.fxs:
                tr.fxs[-1].delete()

        def render(fx_name, values=None, state=None, env=None):
            """One pass: fresh item, fresh instance, set state, bake, return the file it wrote
            and the N_DECLARED ACTUAL VALUES it was holding.

            `state` is a list of actual values BY INDEX, replayed through THIS instance's own
            declared range. It used to be a list of raw NORMALISED numbers copied straight across,
            which is equality by construction only while both versions declare the same ranges -
            and the assertion below could not see the difference, because it compared normalised
            against normalised and those always agree. Two cases set LP Freq to 12000 Hz; copied
            as a number into a wider range that is 14398.4 Hz, and the suite would have gone half
            green, half red, with the red reading as a DSP regression.

            By INDEX, and all N_DECLARED of them - not the handful of names a CASES entry happens
            to mention. Converting only those would leave every other record on the raw normalised
            path and defeat the fix while passing its own assertion."""
            clear()
            for t in reapy.Project().tracks:
                RPR.SetMediaTrackInfo_Value(t.id, "I_SELECTED", 1 if t.index == idx else 0)
            RPR.SetEditCurPos(0, False, False)
            RPR.InsertMedia(FIXTURE, 0)
            tr = track()
            fx = tr.add_fx(fx_name)
            assert fx is not None, f"add_fx({fx_name!r}) returned None"
            # fx_ident names the FILE; fx.name is a cached display string that goes stale when a
            # desc changes. Without this the harness can render the SAME version twice and report
            # six identical cases at zero tolerance - for a comparison that never happened.
            ident = RPR.TrackFX_GetNamedConfigParm(tr.id, fx.index, "fx_ident", "", 512)[4]
            assert ident == fx_name, f"asked for the {fx_name!r} file, REAPER loaded {ident!r}"
            i = fx.index
            if values:
                names = [fx.params[k].name for k in range(fx.n_params)]
                unknown = [n for n in values if n not in names]
                assert not unknown, f"no such parameter(s): {unknown}"
                for name, value in values.items():
                    k = names.index(name)
                    r = RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)
                    lo, hi = r[4], r[5]
                    RPR.TrackFX_SetParamNormalized(tr.id, i, k, (value - lo) / (hi - lo))
            if state:
                for k, v in enumerate(state):
                    r = RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)
                    lo, hi = r[4], r[5]
                    RPR.TrackFX_SetParamNormalized(tr.id, i, k, (v - lo) / (hi - lo))
            if env:
                names = [fx.params[k].name for k in range(fx.n_params)]
                for pname, points in env.items():
                    assert pname in names, f"no such parameter: {pname}"
                    write_fx_envelope(RPR, tr.id, i, names.index(pname), points)
            got = [RPR.TrackFX_GetParam(tr.id, i, k, 0, 0)[0] for k in range(N_DECLARED)]
            it = tr.items[0]
            RPR.Main_OnCommand(40289, 0)                 # unselect all items
            RPR.SetMediaItemSelected(it.id, True)
            RPR.Main_OnCommand(40209, 0)                 # apply track FX as new take
            it2 = track().items[0]
            tk = RPR.GetTake(it2.id, RPR.CountTakes(it2.id) - 1)
            src = RPR.GetMediaItemTake_Source(tk)
            return RPR.GetMediaSourceFileName(src, "", 1024)[1], got

        outcomes = []
        only = sys.argv[1] if len(sys.argv) > 1 else None

        # MUST FAIL FIRST. If automation is not applied during "apply track FX as new take", every
        # transition case renders a constant parameter and reports a clean pass for a comparison
        # that never happened. So: the same version, with and without the envelope, must DIFFER.
        if not only or only in TRANSITIONS:
            probe = {**MODE_B_8, "Lookahead (ms, Mode B)": 2.0}
            flat, _ = render(BASE, values=probe)
            flat_keep = flat + ".flat.wav"
            os.rename(flat, flat_keep)
            moved, _ = render(BASE, values=probe,
                              env={"Lookahead (ms, Mode B)": [(0.0, 2.0), (3.0, 10.0)]})
            # compare() RAISES on a difference, it does not return one - so the expected outcome
            # here is the exception. Written the other way round the first time, which made the
            # self-test kill the run with the very evidence that it works.
            try:
                compare(flat_keep, moved, "envelope self-test")
            except AssertionError as exc:
                where = str(exc).split("first difference at ")[-1].split(":")[0]
                print(f"envelope self-test: the envelope changes the render at {where}"
                      f" - the transitions below are real", flush=True)
            else:
                raise AssertionError(
                    "an FX parameter envelope did NOT change the render: apply-FX is ignoring "
                    "automation here, so every transition case below would be vacuous")

        for case, values in {**CASES, **DIVERGENT}.items():
            if only and case != only:
                continue
            a, state_base = render(BASE, values=values)
            keep = a + ".base.wav"
            os.rename(a, keep)
            b, state_test = render(UNDER_TEST, state=state_base)
            worst = max(range(len(state_base)),
                        key=lambda k: abs(state_base[k] - state_test[k]))
            assert abs(state_base[worst] - state_test[worst]) <= 1e-6, (
                f"{case}: the two instances do not hold the same VALUE at declared record "
                f"{worst}: {BASE} {state_base[worst]}, {UNDER_TEST} {state_test[worst]}")
            if case in DIVERGENT:
                try:
                    compare(keep, b, case)
                except AssertionError as exc:
                    print(f"  {case:20s} DIVERGES as intended: {str(exc)[:66]}", flush=True)
                    outcomes.append((case, 0, 0, 0, keep, b))
                    continue
                raise AssertionError(
                    f"{case}: V1.1 matched V1.0, but this is the configuration where the Enable "
                    f"gate on Mode B is supposed to change the output. Either the gate does "
                    f"nothing, or this case does not exercise it.")
            n, rate, bits = compare(keep, b, case)
            outcomes.append((case, n, rate, bits, keep, b))
            print(f"  {case:20s} identical: {n} samples, {rate} Hz, {bits}-bit float", flush=True)

        # The transitions. The SAME envelope goes on both renders - the experiment is whether the
        # two versions agree while a parameter moves, not whether a moving parameter changes the
        # sound. State is copied from the base render exactly as above, so the two instances hold
        # identical values by construction and only the detector differs.
        for case, spec in TRANSITIONS.items():
            if only and case != only:
                continue
            a, state_base = render(BASE, values=spec["values"], env=spec["env"])
            keep = a + ".base.wav"
            os.rename(a, keep)
            b, state_test = render(UNDER_TEST, state=state_base, env=spec["env"])
            worst = max(range(len(state_base)),
                        key=lambda k: abs(state_base[k] - state_test[k]))
            assert abs(state_base[worst] - state_test[worst]) <= 1e-6, (
                f"{case}: the two instances do not hold the same VALUE at declared record "
                f"{worst}: {BASE} {state_base[worst]}, {UNDER_TEST} {state_test[worst]}")
            n, rate, bits = compare(keep, b, case)
            outcomes.append((case, n, rate, bits, keep, b))
            print(f"  {case:20s} identical: {n} samples, {rate} Hz, {bits}-bit float", flush=True)

        clear()
        RPR.DeleteTrack(track().id)                      # leave the project as it was found

    # the comparator must be able to fail below PCM resolution
    proof = _self_test_comparator(outcomes[0][4])
    print(f"  comparator rejects a one-ULP difference: {proof}", flush=True)
    assert proof, "a one-ULP edit passed - the render is quantising and this gate proves nothing"
    want = len(CASES) + len(DIVERGENT) if not only else 1
    assert len(outcomes) == want, f"{len(outcomes)} cases ran, expected {want}"
    for _case, _n, _rate, _bits, keep, b in outcomes:
        for f in (keep, b):
            os.path.exists(f) and os.unlink(f)
    print(f"OK null: {len(outcomes)} cases, zero tolerance "
          f"({len(DIVERGENT)} of them deliberately divergent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
