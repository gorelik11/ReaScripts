# -*- coding: utf-8 -*-
"""FakeReaper tests for reels_tempo_map_v2.py.

V2-specific: phase anchoring (re-phase + anacrusis back-fill) and multi-song-safe
narrow delete. Self-contained fake (V1 tests stay untouched).

Run from repo root:  python3 -m pytest tests/test_reels_tempo_map_v2.py -q
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest

import reels_tempo_map_v2 as mod


@dataclass
class FakeItem:
    item_id: int
    position: float
    length: float
    audio_path: str
    take_name: str
    startoffs: float = 0.0
    playrate: float = 1.0


@dataclass
class TempoMarkerCall:
    timepos: float
    bpm: float
    ts_num: int
    ts_denom: int


class TempoFakes:
    def __init__(self):
        self.items = []
        self.selected_ids = []
        self.console = []
        self.tempo_calls = []          # list[TempoMarkerCall]; index == REAPER marker idx
        self.undo_begin = 0
        self.undo_end = 0
        self.undo_labels = []
        self.update_timeline = 0
        self.update_arrange = 0
        self.message_boxes = []
        self.time_selection = None
        self._user_input = (False, "")
        self._next_id = 1

    # builders ----------------------------------------------------------
    def add_item(self, position, length, audio_path, take_name="take",
                 startoffs=0.0, playrate=1.0):
        item = FakeItem(self._next_id, position, length, audio_path, take_name,
                        startoffs, playrate)
        self._next_id += 1
        self.items.append(item)
        return item

    def set_time_selection(self, start, end):
        self.time_selection = (start, end)

    def select(self, item):
        self.selected_ids.append(item.item_id)

    def add_existing_tempo_marker(self, timepos, bpm=120.0, ts_num=0, ts_denom=0):
        self.tempo_calls.append(TempoMarkerCall(timepos, bpm, ts_num, ts_denom))

    def set_user_input(self, ok, csv):
        self._user_input = (ok, csv)

    def _item_by_id(self, item_id):
        for it in self.items:
            if it.item_id == item_id:
                return it
        raise AssertionError(f"unknown item_id {item_id}")

    # RPR_* factory -----------------------------------------------------
    def as_globals(self):
        f = self

        def RPR_ShowConsoleMsg(msg):
            f.console.append(msg)

        def RPR_ShowMessageBox(msg, title, _flags):
            f.message_boxes.append((msg, title))
            return 0

        def RPR_CountSelectedMediaItems(_proj):
            return len(f.selected_ids)

        def RPR_GetSelectedMediaItem(_proj, idx):
            return f.selected_ids[idx]

        def RPR_GetActiveTake(item_id):
            return item_id

        def RPR_GetMediaItemTake_Source(take_id):
            return take_id

        def RPR_GetMediaSourceFileName(source, _buf, sz):
            return (source, f._item_by_id(source).audio_path, sz)

        def RPR_GetMediaItemInfo_Value(item_id, param):
            it = f._item_by_id(item_id)
            if param == "D_POSITION":
                return it.position
            if param == "D_LENGTH":
                return it.length
            raise KeyError(param)

        def RPR_GetMediaItemTakeInfo_Value(take_id, param):
            it = f._item_by_id(take_id)
            if param == "D_STARTOFFS":
                return it.startoffs
            if param == "D_PLAYRATE":
                return it.playrate
            raise KeyError(param)

        def RPR_GetSet_LoopTimeRange(is_set, is_loop, start, end, allow):
            s, e = f.time_selection if f.time_selection else (0.0, 0.0)
            return (is_set, is_loop, s, e, allow)

        def RPR_GetTakeName(take_id):
            return f._item_by_id(take_id).take_name

        def RPR_SetTempoTimeSigMarker(_proj, _ptidx, timepos, _measpos, _beatpos,
                                       bpm, ts_num, ts_denom, _linear):
            f.tempo_calls.append(TempoMarkerCall(timepos, bpm, ts_num, ts_denom))
            return True

        def RPR_CountTempoTimeSigMarkers(_proj):
            return len(f.tempo_calls)

        def RPR_GetTempoTimeSigMarker(_proj, idx, _p2, _p3, _p4, _p5, _p6, _p7, _p8):
            # REAPER's Python binding REQUIRES all out-params passed positionally
            # (proj, ptidx, timepos, measurepos, beatpos, bpm, num, denom, lineartempo)
            # and wraps measurepos/num/denom in c_int -> a float there raises
            # TypeError live. Mirror both the arity and the c_int type strictness so
            # those bugs are caught offline, not in REAPER. (bool is an int subclass.)
            for nm, val in (("measurepos", _p3), ("timesig_num", _p6),
                            ("timesig_denom", _p7)):
                if not isinstance(val, int):
                    raise TypeError(
                        "RPR_GetTempoTimeSigMarker {} is c_int; got {!r}".format(nm, val))
            c = f.tempo_calls[idx]
            return (1, 0, idx, c.timepos, 0, 0.0, c.bpm, c.ts_num, c.ts_denom, 0)

        def RPR_DeleteTempoTimeSigMarker(_proj, idx):
            del f.tempo_calls[idx]
            return True

        def RPR_GetUserInputs(title, num_inputs, captions, defaults, size):
            ok, csv = f._user_input
            return (ok, title, num_inputs, captions, csv, size)

        def RPR_Undo_BeginBlock():
            f.undo_begin += 1

        def RPR_Undo_EndBlock(label, _flags):
            f.undo_end += 1
            f.undo_labels.append(label)

        def RPR_UpdateTimeline():
            f.update_timeline += 1

        def RPR_UpdateArrange():
            f.update_arrange += 1

        return {k: v for k, v in locals().items() if k.startswith("RPR_")}


@pytest.fixture
def fakes():
    importlib.reload(mod)
    f = TempoFakes()
    for name, fn in f.as_globals().items():
        setattr(mod, name, fn)
    return f


# --- pure-logic tests ------------------------------------------------------

@pytest.mark.parametrize("ts,expected", [
    ("4/4", (4, 4, 4)),
    ("7/8", (7, 8, 7)),
    ("12/8", (12, 8, 4)),
])
def test_parse_time_sig(ts, expected):
    assert mod.parse_time_sig(ts) == expected


@pytest.mark.parametrize("num,denom,qn", [(4, 4, 4), (7, 8, 3.5), (12, 8, 6.0)])
def test_calc_quarter_notes_per_bar(num, denom, qn):
    assert mod.calc_quarter_notes_per_bar(num, denom) == qn


# --- window logic ----------------------------------------------------------

def test_get_selected_items(fakes):
    a = fakes.add_item(10.0, 5.0, "/a.wav", "Drums", startoffs=2.0, playrate=1.0)
    fakes.select(a)
    items = mod.get_selected_items()
    assert items[0]["audio_path"] == "/a.wav"
    assert items[0]["startoffs"] == 2.0
    assert items[0]["name"] == "Drums"


def test_get_time_selection_none_when_empty(fakes):
    assert mod.get_time_selection() is None


def test_get_time_selection_returns_range(fakes):
    fakes.set_time_selection(3.0, 9.0)
    assert mod.get_time_selection() == (3.0, 9.0)


def test_window_ts_inside_item(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (12.0, 16.0)) == (2.0, 6.0, 12.0)


def test_window_no_ts_is_whole_item(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, None) == (0.0, 8.0, 10.0)


def test_window_ts_no_overlap_returns_none(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (50.0, 60.0)) is None


# --- phase: bar period -----------------------------------------------------

def test_compute_bar_period_constant():
    assert mod.compute_bar_period([0.0, 2.0, 4.0, 6.0]) == 2.0


def test_compute_bar_period_median_of_first_four():
    # intervals: 2.0, 2.0, 2.0, 10.0 -> median(2,2,2,10) = 2.0 (robust to outlier)
    assert mod.compute_bar_period([0.0, 2.0, 4.0, 6.0, 16.0]) == 2.0


def test_compute_bar_period_too_few_returns_none():
    assert mod.compute_bar_period([5.0]) is None


# --- phase: re-phase to anchor ---------------------------------------------

def test_rephase_shifts_nearest_line_onto_anchor():
    # downbeats start 0.2s late; anchor 0.0, period 0.9 -> shift everything -0.2
    out = mod.rephase_to_anchor([0.2, 1.1, 2.0], 0.0, 0.9)
    assert out == pytest.approx([0.0, 0.9, 1.8])


def test_rephase_picks_nearest_grid_line_when_anacrusis_skipped():
    # first downbeat ~2 bars in (1.8); anchor 0.0, period 0.9 -> stays on grid
    out = mod.rephase_to_anchor([1.8, 2.7, 3.6], 0.0, 0.9)
    assert out == pytest.approx([1.8, 2.7, 3.6])


def test_rephase_noop_without_period():
    assert mod.rephase_to_anchor([1.0, 2.0], 0.0, None) == [1.0, 2.0]


# --- phase: build_grid (anchor + back-fill) --------------------------------

def test_build_grid_no_anacrusis_starts_on_anchor():
    # first downbeat already ~on the anchor
    out = mod.build_grid([0.05, 0.95, 1.85], anchor=0.0, period=0.9)
    assert out[0] == pytest.approx(0.0)
    assert out == pytest.approx([0.0, 0.9, 1.8])


def test_build_grid_backfills_skipped_anacrusis():
    # madmom skipped ~2 opening bars (first downbeat at 1.8); back-fill to anchor
    out = mod.build_grid([1.8, 2.7, 3.6], anchor=0.0, period=0.9)
    assert out[0] == pytest.approx(0.0)        # beat 1 exactly on anchor
    assert out == pytest.approx([0.0, 0.9, 1.8, 2.7, 3.6])


def test_build_grid_anchor_offset_project_time():
    # anchor at project time 12.0 (time selection start)
    out = mod.build_grid([13.85, 14.75], anchor=12.0, period=0.95)
    assert out[0] == pytest.approx(12.0)
    assert out[1] == pytest.approx(12.95)


def test_build_grid_empty_returns_anchor_only():
    assert mod.build_grid([], anchor=5.0, period=1.0) == [5.0]


# --- phase: edge cases (round-half-up + degenerate inputs) -----------------

def test_rephase_half_bar_rounds_up_not_to_even():
    # downbeat exactly half a bar from anchor must snap FORWARD (to anchor+period),
    # not backward onto the anchor (which would collapse the grid).
    assert mod.rephase_to_anchor([1.0], 0.0, 2.0) == pytest.approx([2.0])


def test_build_grid_single_downbeat_backfills_to_anchor():
    out = mod.build_grid([5.0], anchor=0.0, period=1.0)
    assert out == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])


def test_build_grid_all_downbeats_before_anchor_returns_anchor_only():
    assert mod.build_grid([0.1, 0.2], anchor=10.0, period=1.0) == [10.0]


def test_build_grid_intervals_stay_regular_after_backfill():
    out = mod.build_grid([1.8, 2.7, 3.6], anchor=0.0, period=0.9)
    diffs = [out[i + 1] - out[i] for i in range(len(out) - 1)]
    assert diffs == pytest.approx([0.9, 0.9, 0.9, 0.9])


# --- multi-song-safe narrow delete -----------------------------------------

def test_clear_removes_only_markers_inside_window(fakes):
    fakes.add_existing_tempo_marker(5.0)    # before window -> survives (other song)
    fakes.add_existing_tempo_marker(12.0)   # inside window  -> deleted
    fakes.add_existing_tempo_marker(14.0)   # inside window  -> deleted
    fakes.add_existing_tempo_marker(40.0)   # after window   -> survives (other song)
    removed = mod.clear_tempo_markers_in_range(10.0, 18.0)
    assert removed == 2
    remaining = [c.timepos for c in fakes.tempo_calls]
    assert remaining == [5.0, 40.0]


def test_clear_nothing_in_empty_project(fakes):
    assert mod.clear_tempo_markers_in_range(0.0, 100.0) == 0


# --- marker creation -------------------------------------------------------

def test_create_markers_first_on_anchor_4_4(fakes):
    # grid built from downbeats 0.0,2.0,4.0,6.0 at anchor 0.0 -> 120 BPM 4/4
    count = mod.create_tempo_markers_v2([0.0, 2.0, 4.0], 0.0, 4, 4, 6.0, playrate=1.0)
    assert count == 3
    assert fakes.tempo_calls[0].timepos == pytest.approx(0.0)   # beat 1 on anchor
    assert [round(c.bpm, 3) for c in fakes.tempo_calls] == [120.0, 120.0, 120.0]
    # first marker carries the time signature, rest pass 0/0
    assert (fakes.tempo_calls[0].ts_num, fakes.tempo_calls[0].ts_denom) == (4, 4)
    assert (fakes.tempo_calls[1].ts_num, fakes.tempo_calls[1].ts_denom) == (0, 0)
    assert fakes.update_timeline == 1


def test_create_markers_backfilled_first_marker_is_anchor(fakes):
    # madmom skipped the opening bar: downbeats relative to window start at 2.0,4.0,6.0
    # window anchor (project) = 10.0, playrate 1 -> project downbeats 12,14,16
    # back-fill -> first marker at the anchor 10.0
    mod.create_tempo_markers_v2([2.0, 4.0, 6.0], 10.0, 4, 4, 8.0, playrate=1.0)
    assert fakes.tempo_calls[0].timepos == pytest.approx(10.0)


def test_create_markers_7_8_quarter_based_bpm(fakes):
    # 7/8 -> qn_per_bar 3.5; 1.0s bars -> bpm = 3.5*60 = 210
    mod.create_tempo_markers_v2([0.0, 1.0, 2.0], 0.0, 7, 8, 3.0, playrate=1.0)
    assert round(fakes.tempo_calls[0].bpm, 3) == 210.0


def test_create_markers_respects_playrate(fakes):
    # window-relative downbeats compressed by playrate 2 into project time;
    # window_end = anchor + (8.0 / playrate) = 10.0 + 4.0 = 14.0 (real clear bound)
    mod.create_tempo_markers_v2([0.0, 4.0, 8.0], 10.0, 4, 4, 14.0, playrate=2.0)
    assert [c.timepos for c in fakes.tempo_calls] == pytest.approx([10.0, 12.0, 14.0])
    assert round(fakes.tempo_calls[0].bpm, 2) == 120.0


def test_create_markers_single_downbeat_no_crash(fakes):
    # a 1-downbeat window: period is None -> must not raise; writes 0 markers
    count = mod.create_tempo_markers_v2([0.0], 0.0, 4, 4, 4.0, playrate=1.0)
    assert count == 0
    assert fakes.tempo_calls == []


# --- main() end-to-end -----------------------------------------------------

def test_main_anchors_first_marker_on_time_selection_start(fakes, monkeypatch):
    item = fakes.add_item(0.0, 20.0, "/song.wav", "Song")
    fakes.select(item)
    fakes.set_time_selection(5.0, 13.0)           # beat 1 = 5.0
    fakes.set_user_input(True, "4/4")
    # madmom skipped the opening: first downbeat 2.0s into the window
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [2.0, 4.0, 6.0]})
    mod.main()
    assert fakes.tempo_calls[0].timepos == pytest.approx(5.0)   # exactly on selection start


def test_main_preserves_other_song_tempo_map(fakes, monkeypatch):
    fakes.add_existing_tempo_marker(100.0, bpm=90.0, ts_num=3, ts_denom=4)  # song 2, far away
    item = fakes.add_item(0.0, 20.0, "/song1.wav", "Song1")
    fakes.select(item)
    fakes.set_time_selection(0.0, 8.0)
    fakes.set_user_input(True, "4/4")
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [0.0, 2.0, 4.0]})
    mod.main()
    survivors = [c.timepos for c in fakes.tempo_calls if c.timepos >= 50.0]
    assert survivors == [100.0]                    # song 2 untouched


def test_main_no_items_shows_message(fakes):
    mod.main()
    assert fakes.message_boxes and "Select" in fakes.message_boxes[0][0]


def test_main_cancel_does_nothing(fakes):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_user_input(False, "")
    mod.main()
    assert fakes.tempo_calls == []
    assert fakes.undo_begin == 0


def test_main_invalid_time_sig_aborts(fakes):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_user_input(True, "garbage")
    mod.main()
    assert fakes.tempo_calls == []
    assert fakes.message_boxes and "Invalid" in fakes.message_boxes[0][0]


def test_main_full_run_undo_block(fakes, monkeypatch):
    item = fakes.add_item(0.0, 8.0, "/song.wav", "Song")
    fakes.select(item)
    fakes.set_time_selection(0.0, 8.0)
    fakes.set_user_input(True, "4/4")
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [0.0, 2.0, 4.0]})
    mod.main()
    assert fakes.undo_begin == 1 and fakes.undo_end == 1
    assert fakes.undo_labels == ["Madmom tempo map V2"]
    assert fakes.update_arrange == 1


# --- source hygiene (REAPER reads the file with the ascii codec) -----------

def test_v2_source_is_pure_ascii():
    # REAPER's ReaScript host decodes the script with ascii; a stray non-ASCII byte
    # (em-dash, smart quote) crashes live with UnicodeDecodeError even though pytest
    # reads UTF-8 fine via the coding declaration. Keep the source pure ASCII.
    with open(mod.__file__, "rb") as fh:
        data = fh.read()
    offenders = [(i, hex(data[i])) for i in range(len(data)) if data[i] > 127]
    assert offenders == [], "non-ASCII bytes in reels_tempo_map_v2.py: {}".format(
        offenders[:5])
