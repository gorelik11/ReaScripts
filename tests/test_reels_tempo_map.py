# -*- coding: utf-8 -*-
"""FakeReaper tests for reels_tempo_map.py (the RPR_* glue).

The proven midi-composition harness is MIDI-centric; the tempo-map script
touches a different slice of the API (audio takes, source filenames, project
markers, tempo/timesig markers). So this file ships a small audio-focused fake
REAPER and injects the RPR_* callables onto the loaded module's globals -- the
script calls bare RPR_* names that resolve in its own module namespace.

Run from repo root:  python3 -m pytest tests/test_reels_tempo_map.py -q
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field

import pytest

import reels_tempo_map as mod


# --- in-memory fake REAPER -------------------------------------------------


@dataclass
class FakeMarker:
    pos: float
    name: str
    is_region: bool = False
    rgnend: float = 0.0
    idx: int = 0


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
        self.items: list[FakeItem] = []
        self.selected_ids: list[int] = []
        self.markers: list[FakeMarker] = []
        self.console: list[str] = []
        self.tempo_calls: list[TempoMarkerCall] = []
        self.undo_begin = 0
        self.undo_end = 0
        self.undo_labels: list[str] = []
        self.update_timeline = 0
        self.update_arrange = 0
        self.message_boxes: list[tuple[str, str]] = []
        self.time_selection: tuple[float, float] | None = None
        self._user_input = (False, "")
        self._next_id = 1

    # builders -------------------------------------------------------------
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

    def add_marker(self, pos, name, is_region=False, rgnend=0.0):
        self.markers.append(FakeMarker(pos, name, is_region, rgnend))

    def set_user_input(self, ok, csv):
        self._user_input = (ok, csv)

    def _item_by_id(self, item_id):
        for it in self.items:
            if it.item_id == item_id:
                return it
        raise AssertionError(f"unknown item_id {item_id}")

    # RPR_* factory --------------------------------------------------------
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
            # take handle == item handle (one take per item in the fake)
            return item_id

        def RPR_GetMediaItemTake_Source(take_id):
            return take_id  # source handle == take handle

        def RPR_GetMediaSourceFileName(source, _buf, sz):
            # void-return API: tuple echoes (source, filenamebuf, sz);
            # script reads index [1] for the path.
            return (source, f._item_by_id(source).audio_path, sz)

        def RPR_GetMediaItemInfo_Value(item_id, param):
            it = f._item_by_id(item_id)
            if param == "D_POSITION":
                return it.position
            if param == "D_LENGTH":
                return it.length
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

        def RPR_EnumProjectMarkers(idx, _isrgn, _pos, _rgnend, _name, _markidx):
            # retval == next index (>0) or 0 when idx is out of range.
            if idx >= len(f.markers):
                return (0, 0, 0.0, 0.0, "", 0)
            m = f.markers[idx]
            return (idx + 1, 1 if m.is_region else 0, m.pos, m.rgnend, m.name, m.idx)

        def RPR_SetTempoTimeSigMarker(_proj, _ptidx, timepos, _measpos, _beatpos,
                                       bpm, ts_num, ts_denom, _linear):
            f.tempo_calls.append(TempoMarkerCall(timepos, bpm, ts_num, ts_denom))
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
    """Fresh fake REAPER wired onto the module's globals for each test."""
    importlib.reload(mod)  # clear any RPR_* left from a prior test
    f = TempoFakes()
    for name, fn in f.as_globals().items():
        setattr(mod, name, fn)
    return f


# --- pure-logic tests ------------------------------------------------------


@pytest.mark.parametrize("ts,expected", [
    ("4/4", (4, 4, 4)),
    ("3/4", (3, 4, 3)),
    ("7/8", (7, 8, 7)),       # additive
    ("12/8", (12, 8, 4)),     # compound
    ("6/8", (6, 8, 2)),       # compound
    ("9/8", (9, 8, 3)),       # compound
    ("5/8", (5, 8, 5)),       # additive
    ("2/2", (2, 2, 2)),
])
def test_parse_time_sig(ts, expected):
    assert mod.parse_time_sig(ts) == expected


@pytest.mark.parametrize("bad", ["", "4", "4/4/4", "x/y", "4/foo", "0/4", "4/0", "-3/4"])
def test_parse_time_sig_rejects_garbage(bad):
    # Must never raise (user types this) -- always a clean (None, None, None).
    assert mod.parse_time_sig(bad) == (None, None, None)


@pytest.mark.parametrize("num,denom,qn", [
    (4, 4, 4), (3, 4, 3), (7, 8, 3.5), (12, 8, 6.0), (2, 2, 4),
])
def test_calc_quarter_notes_per_bar(num, denom, qn):
    assert mod.calc_quarter_notes_per_bar(num, denom) == qn


# --- glue tests ------------------------------------------------------------


def test_get_selected_items(fakes):
    a = fakes.add_item(10.0, 5.0, "/a.wav", "Drums")
    b = fakes.add_item(30.0, 2.0, "/b.wav", "Bass")
    fakes.select(a)
    fakes.select(b)

    items = mod.get_selected_items()

    assert [i["audio_path"] for i in items] == ["/a.wav", "/b.wav"]
    assert items[0]["position"] == 10.0 and items[0]["length"] == 5.0
    assert items[0]["name"] == "Drums"


def test_find_first_beat_marker_within_bounds(fakes):
    fakes.add_marker(12.0, "first beat")
    assert mod.find_first_beat_marker(10.0, 20.0) == 12.0


def test_find_first_beat_marker_case_insensitive_and_trimmed(fakes):
    fakes.add_marker(12.0, "  First Beat  ")
    assert mod.find_first_beat_marker(10.0, 20.0) == 12.0


def test_find_first_beat_marker_ignores_outside_and_regions(fakes):
    fakes.add_marker(5.0, "first beat")            # before item
    fakes.add_marker(15.0, "first beat", is_region=True)  # a region, not a marker
    fakes.add_marker(99.0, "first beat")           # after item
    assert mod.find_first_beat_marker(10.0, 20.0) is None


def test_create_tempo_markers_bpm_math_4_4(fakes):
    # 120 BPM in 4/4 => one bar = 2.0s
    count = mod.create_tempo_markers([0.0, 2.0, 4.0, 6.0], offset=0.0,
                                     ts_num=4, ts_denom=4)
    assert count == 3
    assert [round(c.bpm, 3) for c in fakes.tempo_calls] == [120.0, 120.0, 120.0]
    # first marker carries the time signature, the rest pass 0/0 (keep)
    assert (fakes.tempo_calls[0].ts_num, fakes.tempo_calls[0].ts_denom) == (4, 4)
    assert (fakes.tempo_calls[1].ts_num, fakes.tempo_calls[1].ts_denom) == (0, 0)
    assert fakes.update_timeline == 1


def test_create_tempo_markers_applies_item_offset(fakes):
    mod.create_tempo_markers([0.0, 2.0], offset=100.0, ts_num=4, ts_denom=4)
    assert fakes.tempo_calls[0].timepos == 100.0


def test_create_tempo_markers_7_8_quarter_based_bpm(fakes):
    # 7/8 -> qn_per_bar = 3.5; bar = 1.0s -> bpm = 3.5*60 = 210
    mod.create_tempo_markers([0.0, 1.0, 2.0], offset=0.0, ts_num=7, ts_denom=8)
    assert round(fakes.tempo_calls[0].bpm, 3) == 210.0


def test_create_tempo_markers_anchors_to_first_beat(fakes):
    # marker nearest downbeat index 1 (t=2.0) -> markers start there
    count = mod.create_tempo_markers([0.0, 2.0, 4.0, 6.0], offset=0.0,
                                     ts_num=4, ts_denom=4,
                                     first_beat_time=2.1)
    assert fakes.tempo_calls[0].timepos == 2.0
    assert count == 2  # pairs (2,4) and (4,6)


# --- analysis window: time selection > item bounds > whole file ------------


def test_get_time_selection_none_when_empty(fakes):
    assert mod.get_time_selection() is None


def test_get_time_selection_returns_range(fakes):
    fakes.set_time_selection(3.0, 9.0)
    assert mod.get_time_selection() == (3.0, 9.0)


def test_window_no_ts_untrimmed_is_whole_item(fakes):
    # pos=10, len=8, no trim, rate 1 -> source [0,8], project start 10
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, None) == (0.0, 8.0, 10.0)


def test_window_no_ts_left_trimmed(fakes):
    # startoffs=2 -> source window starts at 2
    assert mod.compute_analysis_window(10.0, 4.0, 2.0, 1.0, None) == (2.0, 6.0, 10.0)


def test_window_no_ts_playrate_stretches_source_span(fakes):
    # rate 2 -> 4s of project covers 8s of source
    assert mod.compute_analysis_window(10.0, 4.0, 0.0, 2.0, None) == (0.0, 8.0, 10.0)


def test_window_ts_inside_item(fakes):
    # item [10,18]; TS [12,16] -> source [2,6], project start 12
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (12.0, 16.0)) == (2.0, 6.0, 12.0)


def test_window_ts_partial_overlap_clamps_to_item(fakes):
    # TS [8,14] clamped to item [10,18] -> [10,14] -> source [0,4]
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (8.0, 14.0)) == (0.0, 4.0, 10.0)


def test_window_ts_no_overlap_returns_none(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (50.0, 60.0)) is None


def test_window_ts_with_trim_and_rate(fakes):
    # pos=10,len=8,off=2,rate=2; TS [12,16] -> p0=12,p1=16
    # src_start = 2+(12-10)*2 = 6 ; src_end = 2+(16-10)*2 = 14
    assert mod.compute_analysis_window(10.0, 8.0, 2.0, 2.0, (12.0, 16.0)) == (6.0, 14.0, 12.0)


def test_create_tempo_markers_respects_playrate(fakes):
    # downbeats are window-relative; rate 2 compresses them into project time
    mod.create_tempo_markers([0.0, 4.0, 8.0], offset=10.0, ts_num=4, ts_denom=4,
                             playrate=2.0)
    assert [c.timepos for c in fakes.tempo_calls] == [10.0, 12.0]
    assert round(fakes.tempo_calls[0].bpm, 2) == 120.0  # 2s project bars


def test_main_uses_time_selection_window(fakes, monkeypatch):
    item = fakes.add_item(0.0, 8.0, "/song.wav", "Song")
    fakes.select(item)
    fakes.set_time_selection(2.0, 6.0)
    fakes.set_user_input(True, "4/4")
    calls = []

    def fake_run(audio_path, beats_per_bar, ts_num, ts_denom, src_start, src_end):
        calls.append((audio_path, src_start, src_end))
        return {"downbeats": [0.0, 2.0, 4.0]}  # window-relative

    monkeypatch.setattr(mod, "run_madmom", fake_run)
    mod.main()

    assert calls == [("/song.wav", 2.0, 6.0)]
    # window starts at project time 2.0 -> markers at 2.0 and 4.0
    assert [c.timepos for c in fakes.tempo_calls] == [2.0, 4.0]


def test_main_skips_item_outside_time_selection(fakes, monkeypatch):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_time_selection(50.0, 60.0)  # no overlap with item
    fakes.set_user_input(True, "4/4")
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: pytest.fail("run_madmom must not be called"))

    mod.main()

    assert fakes.tempo_calls == []
    # undo block still opens/closes cleanly
    assert fakes.undo_begin == 1 and fakes.undo_end == 1


def test_main_end_to_end(fakes, monkeypatch):
    item = fakes.add_item(0.0, 8.0, "/song.wav", "Song")
    fakes.select(item)
    fakes.set_user_input(True, "4/4")
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [0.0, 2.0, 4.0]})

    mod.main()

    assert len(fakes.tempo_calls) == 2
    assert fakes.undo_begin == 1 and fakes.undo_end == 1
    assert fakes.undo_labels == ["Madmom tempo map"]
    assert fakes.update_arrange == 1
    assert fakes.message_boxes == []


def test_main_no_items_shows_message(fakes):
    mod.main()
    assert fakes.message_boxes
    assert "Select" in fakes.message_boxes[0][0]


def test_main_cancel_dialog_does_nothing(fakes):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_user_input(False, "")  # user pressed Cancel

    mod.main()

    assert fakes.tempo_calls == []
    assert fakes.undo_begin == 0


def test_main_invalid_time_sig_aborts(fakes):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_user_input(True, "garbage")

    mod.main()

    assert fakes.tempo_calls == []
    assert fakes.message_boxes
    assert "Invalid" in fakes.message_boxes[0][0]
