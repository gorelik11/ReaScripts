"""Does JSFX/RCBitNova V1.1 actually COMPILE?

`n_params == 179` does not answer that. A JSFX with a syntax error in @gfx still loads and still
reports every declared slider - which is exactly how `gc_fd = 1e18` (EEL2 has no such literal)
passed a "compiles: True" check and reached the owner as a broken plugin window.

REAPER puts the compile error in the FX window as static text, so that is what gets read: add the
effect, float its window, ask the accessibility layer what the window says, close it again.
Clunky, and it is the only signal this API offers.
"""

import subprocess
import sys


def _window_text(fx_title_fragment="RCBitNova"):
    script = f'''
    tell application "System Events" to tell process "REAPER"
      set out to ""
      repeat with w in windows
        if name of w contains "{fx_title_fragment}" then
          repeat with t in (static texts of w)
            set out to out & (value of t) & linefeed
          end repeat
        end if
      end repeat
      return out
    end tell'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout


def check(track_index=0):
    import reapy
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        pr = reapy.Project()
        made_track = 0
        if len(pr.tracks) == 0:               # an empty project is the normal state for a check
            RPR.InsertTrackAtIndex(0, False)
            RPR.TrackList_AdjustWindows(False)
            made_track = 1
            pr = reapy.Project()
        tr = pr.tracks[track_index]
        before = [f.name for f in tr.fxs]
        fx = tr.add_fx("JS: RCBitNova V1.2")
        i = fx.index
        n = fx.n_params
        RPR.TrackFX_Show(tr.id, i, 3)          # float the window so its text exists to be read
    text = _window_text()
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        pr = reapy.Project()
        tr = pr.tracks[track_index]
        RPR.TrackFX_Show(tr.id, i, 2)
        [f for f in tr.fxs if "RCBitNova V1.2" in f.name][-1].delete()
        assert [f.name for f in tr.fxs] == before, "the scratch instance was not removed"
        if made_track:
            RPR.DeleteTrack(reapy.Project().tracks[0].id)

    problems = []
    if n != 179:
        problems.append(f"reports {n} parameters, expected 179")
    for line in text.splitlines():
        low = line.lower()
        if "error" in low or "syntax" in low:
            problems.append(f"window says: {line.strip()}")
    return problems, n, text


def main():
    problems, n, text = check()
    if problems:
        for p in problems:
            print(f"FAIL compile: {p}")
        return 1
    print(f"OK compile: {n} parameters and no error text in the plugin window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
