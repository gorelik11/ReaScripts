# -*- coding: utf-8 -*-
"""FakeReaper tests for "RCBit Quality Toggle V1.0.py" and
"RCBit Quality Manager V1.0.py".

Pinned down before any live run:
* instances are found by fx_ident BASENAME (subfolder installs, renamed FX),
  not by display name, and older versions / other RCBit plugins are ignored;
* every chain is covered: track FX, input FX (0x1000000), master,
  monitoring FX, take FX;
* toggle rule: any Light -> all HQ; all HQ -> all Light; offline ignored;
* a stale scan never writes into a slot that now holds another plugin;
* the shared core is byte-identical in both scripts;
* the GUI frame always calls End, maps row clicks to the right instance and
  stops re-deferring when the window closes.

Run from repo root:
    python3 -m pytest tests/test_rcbit_quality.py -q
"""
from __future__ import annotations

import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOGGLE = os.path.join(REPO, "RCBit Quality Toggle V1.0.py")
MANAGER = os.path.join(REPO, "RCBit Quality Manager V1.0.py")
REC = 0x1000000


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fx(ident, val=0.0, pname="Quality", enabled=True, offline=False):
    return {"ident": ident, "pname": pname, "val": val,
            "enabled": enabled, "offline": offline}


class Owner:
    def __init__(self, name, chain=(), rec=()):
        self.name = name
        self.chain = list(chain)
        self.rec = list(rec)

    def slot(self, i):
        return self.rec[i - REC] if i >= REC else self.chain[i]


class Item:
    def __init__(self, track, pos, takes):
        self.track, self.pos, self.takes = track, pos, takes


class FakeReaper:
    def __init__(self, master, tracks, items=()):
        self.master, self.tracks, self.items = master, tracks, list(items)
        self.undo = []
        self.deferred = []
        self.shown = []
        self.scc = 0
        self.valid = set(map(id, [master] + tracks
                             + [t for it in self.items for t in it.takes]))

    def install(self, mod):
        k = self

        def get_named(owner, i, key, buf, sz):
            assert key == "fx_ident"
            return (True, owner, i, key, owner.slot(i)["ident"], sz)

        def set_param(owner, i, p, v):
            assert p == 8
            owner.slot(i)["val"] = v
            k.scc += 1

        def show(owner, i, flag):
            k.shown.append((owner.name, i, flag))

        for kind in ("Track", "Take"):
            api = {
                "FX_GetCount": lambda o: len(o.chain),
                "FX_GetNamedConfigParm": get_named,
                "FX_GetParamName": lambda o, i, p, b, s: (
                    True, o, i, p, o.slot(i)["pname"] if p == 8 else "x", s),
                "FX_GetParam": lambda o, i, p, a, b: (
                    o.slot(i)["val"], o, i, p, 0.0, 1.0),
                "FX_GetEnabled": lambda o, i: o.slot(i)["enabled"],
                "FX_GetOffline": lambda o, i: o.slot(i)["offline"],
                "FX_SetParam": set_param,
                "FX_Show": show,
            }
            for n, f in api.items():
                setattr(mod, "RPR_" + kind + n, f)
        fns = {
            "TrackFX_GetRecCount": lambda o: len(o.rec),
            "GetMasterTrack": lambda p: k.master,
            "CountTracks": lambda p: len(k.tracks),
            "GetTrack": lambda p, i: k.tracks[i],
            "GetTrackName": lambda t, b, s: (True, t, t.name, s),
            "CountMediaItems": lambda p: len(k.items),
            "GetMediaItem": lambda p, i: k.items[i],
            "GetMediaItem_Track": lambda it: it.track,
            "GetMediaItemInfo_Value": lambda it, key: it.pos,
            "CountTakes": lambda it: len(it.takes),
            "GetTake": lambda it, t: it.takes[t],
            "GetTakeName": lambda t: t.name,
            "ValidatePtr2": lambda p, o, typ: id(o) in k.valid,
            "Undo_BeginBlock2": lambda p: k.undo.append("begin"),
            "Undo_EndBlock2": lambda p, label, f: k.undo.append(label),
            "EnumProjects": lambda i, b, s: ("proj1", b, s),
            "GetProjectStateChangeCount": lambda p: k.scc,
            "time_precise": lambda: 100.0,
            "defer": lambda code: k.deferred.append(code),
        }
        for n, f in fns.items():
            setattr(mod, "RPR_" + n, f)
        return self


def make_project():
    master = Owner("MASTER", [fx("RCBitBrickwall V4.0", 1.0)],
                   rec=[fx("RCBit/RCBitLimiter V2.0", 0.0)])   # monitoring FX
    t1 = Owner("Bass", [fx("ReaEQ"), fx("RCBitLimiter V2.0", 0.0)],
               rec=[fx("RCBitBrickwall V4.0", 1.0)])           # input FX
    t2 = Owner("Drums", [
        fx("RCBitBrickwall V3.0", 0.0),                        # old version
        fx("RCBitNova V1.5", 0.0),                             # other RCBit
        fx("RCBitBrickwall V4.0", 0.0, pname="Gain"),          # not our layout
        fx("RCBitBrickwall V4.0", 0.0, offline=True),
        fx("RCBitBrickwall V4.0", 1.0, enabled=False),
    ])
    take = Owner("Vox take", [fx("RCBitLimiter V2.0", 0.0)])
    return master, [t1, t2], [Item(t1, 83.5, [take])]


@pytest.fixture(params=[TOGGLE, MANAGER], ids=["toggle", "manager"])
def mod(request):
    return load(request.param, "rcq_" + os.path.basename(request.param)[:20])


def test_shared_core_identical():
    def core(path):
        s = open(path).read()
        return s[s.index("# --- shared core"):s.index("# --- end shared core")]
    assert core(TOGGLE) == core(MANAGER)


def test_target_plugin_matches_basename_only(mod):
    assert mod.target_plugin("RCBitLimiter V2.0") == "RCBitLimiter V2.0"
    assert mod.target_plugin("sub/dir/RCBitBrickwall V4.0") == "RCBitBrickwall V4.0"
    assert mod.target_plugin("sub\\RCBitBrickwall V4.0") == "RCBitBrickwall V4.0"
    assert mod.target_plugin("RCBitBrickwall V3.0") is None
    assert mod.target_plugin("RCBitLimiter") is None
    assert mod.target_plugin("") is None


def test_scan_covers_every_chain_and_filters(mod):
    m, ts, its = make_project()
    FakeReaper(m, ts, its).install(mod)
    rows = mod.scan_project()
    got = [(r["where"], r["slot"], r["fx"], r["plugin"], r["hq"],
            r["enabled"], r["offline"]) for r in rows]
    assert got == [
        ("MASTER", "FX 1", 0, "RCBitBrickwall V4.0", True, True, False),
        ("Monitoring FX", "FX 1", REC, "RCBitLimiter V2.0", False, True, False),
        ("1: Bass", "FX 2", 1, "RCBitLimiter V2.0", False, True, False),
        ("1: Bass [input FX]", "FX 1", REC, "RCBitBrickwall V4.0", True, True, False),
        ("2: Drums", "FX 4", 3, "RCBitBrickwall V4.0", False, True, True),
        ("2: Drums", "FX 5", 4, "RCBitBrickwall V4.0", True, False, False),
        ("1: Bass | item @ 1:23.500 (Vox take)", "FX 1", 0,
         "RCBitLimiter V2.0", False, True, False),
    ]
    assert rows[-1]["kind"] == "Take"


def test_toggle_target_rule(mod):
    r = lambda hq, off=False: {"hq": hq, "offline": off}
    assert mod.toggle_target([]) is None
    assert mod.toggle_target([r(False, off=True)]) is None
    assert mod.toggle_target([r(True), r(False)]) is True       # mixed -> HQ
    assert mod.toggle_target([r(True), r(True)]) is False       # all HQ -> Light
    assert mod.toggle_target([r(True), r(False, off=True)]) is False  # offline ignored


def test_set_all_skips_offline_one_undo_point(mod):
    m, ts, its = make_project()
    fr = FakeReaper(m, ts, its).install(mod)
    rows = mod.scan_project()
    n = mod.set_all(rows, True, "lbl")
    assert n == 3                                   # the three loaded Lights
    assert fr.undo == ["begin", "lbl"]
    assert ts[1].chain[3]["val"] == 0.0             # offline untouched
    assert ts[1].chain[2]["val"] == 0.0             # non-"Quality" untouched
    assert all(r["hq"] for r in mod.scan_project() if not r["offline"])


def test_set_quality_refuses_stale_slot_and_dead_owner(mod):
    m, ts, its = make_project()
    fr = FakeReaper(m, ts, its).install(mod)
    rows = mod.scan_project()
    bass = rows[2]
    ts[0].chain[1] = fx("ReaComp", 0.0)             # slot replaced after scan
    assert mod.set_quality(bass, True) is False
    assert ts[0].chain[1]["val"] == 0.0
    fr.valid.discard(id(m))                         # owner gone
    assert mod.set_quality(rows[0], False) is False
    assert m.chain[0]["val"] == 1.0


def test_toggle_script_roundtrip():
    tog = load(TOGGLE, "rcq_tog_rt")
    m, ts, its = make_project()
    fr = FakeReaper(m, ts, its).install(tog)
    assert tog.run_toggle()["target"] == "HQ"
    assert fr.undo[-1] == "RCBit quality: all to HQ"
    assert tog.run_toggle() == {"target": "Light", "changed": 6, "total": 7}
    assert tog.main() is None                       # returns, never SystemExit


class FakeImGui:
    """Echo-style ReaImGui stand-in; `click` names the button label to press
    and `click_row` which PushID row it must be under."""

    def __init__(self, click=None, click_row=None, open_=1):
        self.click, self.click_row, self.open_ = click, click_row, open_
        self.ended = 0
        self.row = None
        self.pushed = 0
        self.texts = []

    def __getattr__(self, name):          # flags, Col_*, layout no-ops
        return lambda *a, **k: 0

    def CreateContext(self, label):
        return object()

    def Begin(self, ctx, name, p_open=None, flags=None):
        return True, self.open_

    def End(self, ctx):
        self.ended += 1

    def BeginTable(self, *a):
        return True

    def PushID(self, ctx, s):
        self.row = s

    def PopID(self, ctx):
        self.row = None

    def PushStyleColor(self, ctx, idx, col):
        self.pushed += 1

    def PopStyleColor(self, ctx, n=1):
        self.pushed -= n

    def Text(self, ctx, s):
        self.texts.append(s)

    def Button(self, ctx, label, *a):
        return label == self.click and (self.click_row is None
                                        or self.row == self.click_row)

    SmallButton = Button


def open_with(fake):
    man = load(MANAGER, "rcq_man_gui")
    m, ts, its = make_project()
    fr = FakeReaper(m, ts, its).install(man)
    g = {"imgui": fake, "ctx": object(), "rows": [], "scc": None,
         "proj": None, "t": 0.0, "scan_ms": 0.0, "msg": ""}
    man._rescan(g)
    man._QM = g
    return man, fr, (m, ts, its)


def test_frame_lists_and_redefers():
    fake = FakeImGui()
    man, fr, _ = open_with(fake)
    man._qm_frame()
    assert fake.ended == 1 and fake.pushed == 0
    assert "Light: 3    HQ: 3    Offline: 1    (scan 0 ms)" in fake.texts
    assert fr.deferred == ["_qm_frame()"]


def test_frame_row_click_flips_that_instance_only():
    fake = FakeImGui(click="Light", click_row="r2")    # row 2 = Bass FX 2
    man, fr, (m, ts, its) = open_with(fake)
    man._qm_frame()
    assert ts[0].chain[1]["val"] == 1.0
    assert its[0].takes[0].chain[0]["val"] == 0.0
    assert fr.undo == ["begin", "RCBit quality: RCBitLimiter V2.0 to HQ"]
    assert man._QM["rows"][2]["hq"] is True               # rescanned


def test_frame_toggle_all_and_show():
    fake = FakeImGui(click="Toggle all")
    man, fr, (m, ts, its) = open_with(fake)
    man._qm_frame()
    assert man.counts(man._QM["rows"]) == (0, 6, 1)
    fake.click, fake.click_row = "Show", "r6"
    man._qm_frame()
    assert fr.shown == [("Vox take", 0, 3)]


def test_frame_close_stops_loop():
    fake = FakeImGui(open_=0)
    man, fr, _ = open_with(fake)
    man._qm_frame()
    assert fake.ended == 1
    assert fr.deferred == [] and man._QM is None
